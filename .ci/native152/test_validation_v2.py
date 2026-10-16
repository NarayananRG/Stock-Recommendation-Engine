from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from validation_v2 import (  # noqa: E402
    ExecutionAssumptions,
    create_portfolio,
    legacy_portfolios,
    load_portfolio,
    freeze_point_in_time_snapshot,
    pit_filings,
    pit_price_bars,
    pit_valuation_observations,
    process_paper_session,
    run_replay,
)


def candidate(symbol: str, session: str, action: str = "RECOVERY BUY") -> dict:
    return {
        "symbol": symbol,
        "market_session": session,
        "live_decision": {
            "final_action": action,
            "executable": action.endswith("BUY"),
            "strategy_style": "RECOVERY",
            "confidence": "HIGH",
            "recovery_thesis": f"{symbol} recovery thesis",
            "invalidation": "Thesis breaks",
            "evidence": {"session": session, "symbol": symbol},
        },
    }


class PaperPortfolioV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.db = Path(self.tmp.name) / "phase81_validation.sqlite3"
        self.p = create_portfolio(
            self.db,
            starting_session="2026-10-15",
            starting_run_id="RUN-D0",
            starting_capital=100000,
            app_version="0.14.12-validation-v2",
            production_model_version="LIVE_DECISION_V1",
            evidence_pipeline_version="evidence-v2",
            router_sha256="abc",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, session, run, *, candidates=None, plan=None, opens=None, closes=None, monitoring=None, crash=None):
        return process_paper_session(
            self.db,
            portfolio_id=self.p["portfolio_id"],
            expected_session=session,
            latest_official_session=session,
            official_freshness="PASS",
            production_session=session,
            production_run_id=run,
            app_version="0.14.12-validation-v2",
            production_model_version="LIVE_DECISION_V1",
            evidence_pipeline_version="evidence-v2",
            candidates=candidates or [],
            allocation_plan=plan or {"new_buys": []},
            official_opens=opens or {},
            official_closes=closes or {},
            monitoring=monitoring or {},
            assumptions=ExecutionAssumptions(),
            crash_hook=crash,
        )

    def test_d0_to_d4_forward_only_accounting(self):
        d0 = self.call(
            "2026-10-15", "RUN-D0",
            candidates=[candidate("HINDZINC", "2026-10-15"), candidate("GODREJCP", "2026-10-15")],
            plan={"new_buys": [{"symbol": "HINDZINC", "estimated_cost": 40000}, {"symbol": "GODREJCP", "estimated_cost": 30000}]},
        )
        self.assertEqual(2, len(d0["new_orders"]))
        self.assertEqual(100000, load_portfolio(self.db)["cash"])
        self.assertEqual(70000, load_portfolio(self.db)["pending_capital"])

        d1 = self.call(
            "2026-10-16", "RUN-D1", opens={"HINDZINC": 500, "GODREJCP": 1000},
            closes={"HINDZINC": 510, "GODREJCP": 990},
        )
        state = load_portfolio(self.db)
        self.assertEqual(2, len(d1["fills"]))
        self.assertEqual(79, next(p for p in state["positions"] if p["symbol"] == "HINDZINC")["qty"])
        self.assertEqual(29, next(p for p in state["positions"] if p["symbol"] == "GODREJCP")["qty"])
        self.assertAlmostEqual(31397.25, state["cash"], places=2)
        self.assertAlmostEqual(100397.25, state["nav"], places=2)

        self.call("2026-10-17", "RUN-D2", closes={"HINDZINC": 550, "GODREJCP": 1050})
        state = load_portfolio(self.db)
        self.assertAlmostEqual(105297.25, state["nav"], places=2)
        self.assertAlmostEqual(5297.25, state["unrealized_pnl"], places=2)

        d3 = self.call(
            "2026-10-20", "RUN-D3", closes={"HINDZINC": 540, "GODREJCP": 1040},
            monitoring={"HINDZINC": {"state": "EXIT SIGNAL", "reason": "Thesis invalidated"}},
        )
        self.assertEqual("EXIT SIGNAL", next(x for x in d3["monitoring_events"] if x["symbol"] == "HINDZINC")["event_type"])
        self.assertNotEqual("CLOSED", next(p for p in load_portfolio(self.db)["positions"] if p["symbol"] == "HINDZINC")["state"])

        self.call("2026-10-21", "RUN-D4", opens={"HINDZINC": 530}, closes={"GODREJCP": 1045})
        state = load_portfolio(self.db)
        closed = next(p for p in state["positions"] if p["symbol"] == "HINDZINC")
        self.assertEqual("CLOSED", closed["state"])
        self.assertAlmostEqual(2247.94, closed["realized_pnl"], places=2)
        self.assertAlmostEqual(2247.94, state["realized_pnl"], places=2)

    def test_duplicate_and_restart_safety(self):
        args = dict(
            candidates=[candidate("HINDZINC", "2026-10-15")],
            plan={"new_buys": [{"symbol": "HINDZINC", "estimated_cost": 40000}]},
        )
        first = self.call("2026-10-15", "RUN-D0", **args)
        second = self.call("2026-10-15", "RUN-D0", **args)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(1, len(load_portfolio(self.db)["pending_orders"]))
        changed_run = self.call("2026-10-15", "RUN-REPAIRED-LATER", candidates=[candidate("GODREJCP", "2026-10-15")], plan={"new_buys": [{"symbol": "GODREJCP", "estimated_cost": 30000}]})
        self.assertTrue(changed_run["duplicate"])
        self.assertEqual("RUN-D0", changed_run["production_run_id"])
        self.assertEqual(1, len(load_portfolio(self.db)["pending_orders"]))
        # A new connection is used for every call, exercising restart restoration.
        self.call("2026-10-16", "RUN-D1", opens={"HINDZINC": 500}, closes={"HINDZINC": 510})
        duplicate_fill = self.call("2026-10-16", "RUN-D1", opens={"HINDZINC": 500}, closes={"HINDZINC": 510})
        self.assertTrue(duplicate_fill["duplicate"])
        self.assertEqual(1, len([x for x in load_portfolio(self.db)["journal"] if x["event_type"] == "BUY FILLED"]))

    def test_crash_after_fill_journal_rolls_back_atomically(self):
        self.call(
            "2026-10-15", "RUN-D0",
            candidates=[candidate("HINDZINC", "2026-10-15")],
            plan={"new_buys": [{"symbol": "HINDZINC", "estimated_cost": 40000}]},
        )
        with self.assertRaisesRegex(RuntimeError, "SIMULATED_CRASH"):
            self.call("2026-10-16", "RUN-D1", opens={"HINDZINC": 500}, crash="AFTER_FILL_JOURNAL")
        state = load_portfolio(self.db)
        self.assertEqual(100000, state["cash"])
        self.assertEqual(0, len(state["positions"]))
        self.assertEqual(0, len([x for x in state["journal"] if x["event_type"] == "BUY FILLED"]))
        self.call("2026-10-16", "RUN-D1", opens={"HINDZINC": 500}, closes={"HINDZINC": 510})
        self.assertEqual(1, len([x for x in load_portfolio(self.db)["journal"] if x["event_type"] == "BUY FILLED"]))

    def test_legacy_is_read_only_and_never_promoted(self):
        con = sqlite3.connect(self.db)
        try:
            con.execute("create table if not exists paper_portfolios (portfolio_id text primary key, created_at text, starting_session text, starting_capital real, state_json text)")
            con.execute("insert into paper_portfolios values('OLD','2026-10-01','2026-10-01',100000,'{}')")
            con.commit()
        finally:
            con.close()
        old = legacy_portfolios(self.db)
        self.assertEqual("LEGACY_VALIDATION_V1", old[0]["classification"])
        self.assertTrue(old[0]["read_only"])
        self.assertNotEqual("OLD", load_portfolio(self.db)["portfolio_id"])

    def test_official_gate_blocks_all_mutation(self):
        before = load_portfolio(self.db)
        result = process_paper_session(
            self.db, portfolio_id=self.p["portfolio_id"], expected_session="2026-10-16",
            latest_official_session="2026-10-15", official_freshness="FAIL",
            production_session="2026-10-16", production_run_id="RUN", app_version="v",
            production_model_version="m", evidence_pipeline_version="e", candidates=[],
            allocation_plan={}, official_opens={}, official_closes={},
        )
        self.assertIn("OFFICIAL DATA NOT READY", result["status"])
        self.assertEqual(before["journal"], load_portfolio(self.db)["journal"])


class ReplayV2Tests(unittest.TestCase):
    def test_anti_lookahead_filters(self):
        self.assertEqual(["2026-10-15"], [x["date"] for x in pit_price_bars([{"date": "2026-10-15"}, {"date": "2026-10-16"}], "2026-10-15")])
        self.assertEqual(["OLD"], [x["id"] for x in pit_filings([{"id": "OLD", "effective_availability_ts": "2026-10-15T15:00:00"}, {"id": "FUTURE", "effective_availability_ts": "2026-10-20T09:00:00"}], "2026-10-15T23:59:59")])
        self.assertEqual([10], [x["pe"] for x in pit_valuation_observations([{"session": "2026-10-14", "pe": 10}, {"session": "2026-10-15", "pe": 99}], "2026-10-15")])
        current = {"session": "2026-10-15", "fundamental": {"eps": 10}}
        frozen = freeze_point_in_time_snapshot(current)
        current["fundamental"]["eps"] = 999
        self.assertEqual(10, frozen["fundamental"]["eps"])

    def test_continuous_replay_next_open_and_actual_benchmark(self):
        packages = {
            "2026-10-15": dict(rows=[candidate("AAA", "2026-10-15")], opens={"AAA": 90}, closes={"AAA": 100}, benchmark_close=100, allocation_plan={"new_buys": [{"symbol": "AAA", "estimated_cost": 50000}]}),
            "2026-10-16": dict(rows=[], opens={"AAA": 100}, closes={"AAA": 110}, benchmark_close=105, allocation_plan={"new_buys": []}),
            "2026-10-17": dict(rows=[], opens={}, closes={"AAA": 120}, benchmark_close=110, allocation_plan={"new_buys": []}),
        }
        def provider(session, state):
            return {"replayability": "FULL_PIT_VALID", "market_data_status": "PASS", "fundamental_pit_status": "PASS", "valuation_pit_status": "PASS", "universe_status": "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS", "live_decision_v1_run_status": "PASS", **packages[session]}
        result = run_replay(requested_period="CUSTOM", sessions=list(packages), starting_capital=100000, assumptions=ExecutionAssumptions(), session_provider=provider)
        self.assertEqual(1, result["metrics"]["filled_entries"])
        self.assertEqual(100000, result["series"][0]["portfolio_nav"])
        self.assertAlmostEqual(109905.15, result["series"][-1]["portfolio_nav"], places=2)
        self.assertEqual(110000, result["series"][-1]["benchmark_nav"])
        self.assertEqual(0.10, result["metrics"]["benchmark_return"])

    def test_incomplete_sessions_excluded_and_metrics_not_faked(self):
        def provider(session, state):
            return {"replayability": "NOT_REPLAYABLE", "market_data_status": "MISSING", "fundamental_pit_status": "MISSING", "valuation_pit_status": "MISSING"}
        result = run_replay(requested_period="1M", sessions=["2026-10-15"], starting_capital=100000, assumptions=ExecutionAssumptions(), session_provider=provider)
        self.assertEqual(0, result["sessions_replayed"])
        self.assertIsNone(result["metrics"]["portfolio_return"])
        self.assertIsNone(result["metrics"]["max_drawdown"])
        self.assertEqual("NOT REPLAYABLE", result["pit_completeness"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
