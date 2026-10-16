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
    ensure_legacy_continuity,
    legacy_portfolios,
    load_portfolio,
    migrate,
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
            app_version="0.14.13-paper-trading-repair",
            production_model_version="LIVE_DECISION_V1",
            evidence_pipeline_version="evidence-v2",
            router_sha256="abc",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, session, run, *, candidates=None, plan=None, opens=None, closes=None, sessions=None, opens_by_session=None, monitoring=None, crash=None):
        return process_paper_session(
            self.db,
            portfolio_id=self.p["portfolio_id"],
            expected_session=session,
            latest_official_session=session,
            official_freshness="PASS",
            production_session=session,
            production_run_id=run,
            app_version="0.14.13-paper-trading-repair",
            production_model_version="LIVE_DECISION_V1",
            evidence_pipeline_version="evidence-v2",
            candidates=candidates or [],
            allocation_plan=plan or {"new_buys": []},
            official_opens=opens or {},
            official_closes=closes or {},
            available_sessions=sessions,
            official_opens_by_session=opens_by_session,
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

    def test_fresh_start_reuses_the_single_active_portfolio(self):
        again = create_portfolio(
            self.db, starting_session="2026-10-16", starting_run_id="RUN-IGNORED",
            starting_capital=250000, app_version="0.14.13-paper-trading-repair",
            production_model_version="LIVE_DECISION_V1", evidence_pipeline_version="evidence-v2",
            router_sha256="different",
        )
        self.assertEqual(self.p["portfolio_id"], again["portfolio_id"])
        self.assertEqual(100000, again["starting_capital"])
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(1, con.execute("select count(*) from paper_v2_portfolios where status='ACTIVE'").fetchone()[0])
        finally:
            con.close()

    def test_missed_next_session_uses_frozen_first_eligible_open(self):
        self.call(
            "2026-10-15", "RUN-D0",
            candidates=[candidate("HINDZINC", "2026-10-15")],
            plan={"new_buys": [{"symbol": "HINDZINC", "estimated_cost": 40000}]},
        )
        result = self.call(
            "2026-10-20", "RUN-D2", sessions=["2026-10-15", "2026-10-16", "2026-10-20"],
            opens_by_session={"2026-10-16": {"HINDZINC": 500}, "2026-10-20": {"HINDZINC": 900}},
            closes={"HINDZINC": 510},
        )
        self.assertEqual("2026-10-16", result["fills"][0]["fill_session"])
        self.assertEqual(500, result["fills"][0]["official_open"])
        position = load_portfolio(self.db)["positions"][0]
        self.assertEqual("2026-10-16", position["entry_fill_session"])

    def test_missing_eligible_open_stays_pending_and_records_blocked_evidence(self):
        self.call(
            "2026-10-15", "RUN-D0", candidates=[candidate("HINDZINC", "2026-10-15")],
            plan={"new_buys": [{"symbol": "HINDZINC", "estimated_cost": 40000}]},
        )
        blocked = self.call(
            "2026-10-20", "RUN-D2", sessions=["2026-10-15", "2026-10-16", "2026-10-20"],
            opens_by_session={"2026-10-20": {"HINDZINC": 900}},
        )
        state = load_portfolio(self.db)
        self.assertEqual([], blocked["fills"])
        self.assertEqual("2026-10-16", state["pending_orders"][0]["eligible_session"])
        blocked_events = [x for x in state["journal"] if x["event_type"] == "EXECUTION BLOCKED"]
        self.assertEqual(1, len(blocked_events))
        self.assertEqual("MISSING_OFFICIAL_OPEN", blocked_events[0]["reason"])

    def test_weekend_is_not_treated_as_an_execution_session(self):
        self.call(
            "2026-10-16", "RUN-FRI", candidates=[candidate("HINDZINC", "2026-10-16")],
            plan={"new_buys": [{"symbol": "HINDZINC", "estimated_cost": 40000}]},
        )
        monday = self.call(
            "2026-10-19", "RUN-MON", sessions=["2026-10-16", "2026-10-19"],
            opens_by_session={"2026-10-19": {"HINDZINC": 500}}, closes={"HINDZINC": 505},
        )
        self.assertEqual("2026-10-19", monday["fills"][0]["fill_session"])
        self.assertEqual("2026-10-19", load_portfolio(self.db)["positions"][0]["entry_fill_session"])

    def test_duplicate_decision_still_progresses_older_pending_lifecycle(self):
        self.call("2026-10-15", "RUN-D0")
        con = sqlite3.connect(self.db)
        try:
            order = {
                "order_id": "OLDER", "portfolio_id": self.p["portfolio_id"], "symbol": "HINDZINC",
                "side": "BUY", "state": "PENDING_NEXT_OPEN", "signal_session": "2026-10-14",
                "production_run_id": "OLDER-RUN", "reserved_capital": 40000, "eligible_session": None,
            }
            con.execute(
                "insert into paper_v2_orders(order_id,portfolio_id,symbol,side,state,signal_session,fill_session,reserved_capital,eligible_session,order_json) values(?,?,?,?,?,?,?,?,?,?)",
                ("OLDER", self.p["portfolio_id"], "HINDZINC", "BUY", "PENDING_NEXT_OPEN", "2026-10-14", None, 40000, None, json.dumps(order)),
            )
            con.commit()
        finally:
            con.close()
        duplicate = self.call(
            "2026-10-15", "RUN-RETRY", sessions=["2026-10-14", "2026-10-15"],
            opens_by_session={"2026-10-15": {"HINDZINC": 500}}, closes={"HINDZINC": 510},
        )
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(1, len(duplicate["fills"]))
        self.assertEqual(1, len(load_portfolio(self.db)["positions"]))

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

    def test_legacy_listing_does_not_override_existing_native_v2(self):
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


class LegacyContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.db = Path(self.tmp.name) / "phase81_validation.sqlite3"
        con = sqlite3.connect(self.db)
        try:
            con.executescript(
                """
                create table paper_portfolios (portfolio_id text primary key, created_at text not null, starting_session text not null, starting_capital real not null, state_json text not null);
                create table paper_positions (position_id text primary key, portfolio_id text not null, symbol text not null, state text not null, qty integer not null, entry_price real, state_json text not null);
                create table paper_orders (order_id text primary key, portfolio_id text not null, symbol text not null, side text not null, state text not null, signal_session text not null, fill_session text, order_json text not null);
                create table paper_journal (event_id text primary key, portfolio_id text not null, market_session text not null, production_run_id text, event_type text not null, created_at text not null, idempotency_key text not null unique, event_json text not null);
                create table paper_nav (portfolio_id text not null, market_session text not null, nav real not null, benchmark_value real, nav_json text not null, primary key(portfolio_id,market_session));
                """
            )
            state = {"portfolio_id": "LEGACY", "status": "ACTIVE", "starting_capital": 100000, "cash": 100000, "nav": 100000, "realized_pnl": 0, "unrealized_pnl": 0}
            con.execute("insert into paper_portfolios values(?,?,?,?,?)", ("LEGACY", "2026-10-13T12:00:00", "2026-10-13", 100000, json.dumps(state)))
            for n, session in enumerate(("2026-10-13", "2026-10-14", "2026-10-14", "2026-10-15"), 1):
                event = {"event_id": f"E{n}", "portfolio_id": "LEGACY", "market_session": session, "production_run_id": f"R{n}", "event_type": "DAILY_DECISION", "created_at": f"2026-10-{12+n:02d}T12:00:00", "decision": "CASH / NO EXECUTABLE BUY"}
                con.execute("insert into paper_journal values(?,?,?,?,?,?,?,?)", (f"E{n}", "LEGACY", session, f"R{n}", "DAILY_DECISION", event["created_at"], f"K{n}", json.dumps(event)))
            for session in ("2026-10-13", "2026-10-14", "2026-10-15"):
                con.execute("insert into paper_nav values(?,?,?,?,?)", ("LEGACY", session, 100000, None, json.dumps({"market_session": session, "nav": 100000, "cash": 100000})))
            con.commit()
        finally:
            con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def migrate(self):
        return ensure_legacy_continuity(
            self.db, app_version="0.14.13-paper-trading-repair",
            production_model_version="LIVE_DECISION_V1",
            evidence_pipeline_version="0.14.11-missing-evidence-coverage-repair",
            router_sha256="router",
        )

    def test_legacy_cash_portfolio_migrates_once_without_reset(self):
        first = self.migrate()
        before_repeat = load_portfolio(self.db)
        second = self.migrate()
        after_repeat = load_portfolio(self.db)
        self.assertTrue(first["migrated"])
        self.assertEqual("V2_ALREADY_ACTIVE", second["status"])
        self.assertEqual("LEGACY", after_repeat["portfolio_id"])
        self.assertEqual(100000, after_repeat["starting_capital"])
        self.assertEqual(100000, after_repeat["cash"])
        self.assertEqual(3, len(after_repeat["nav_history"]))
        self.assertEqual(4, len([x for x in after_repeat["journal"] if x["event_type"] == "LEGACY DAILY_DECISION"]))
        self.assertEqual(before_repeat["journal"], after_repeat["journal"])
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual("4", con.execute("select value from validation_schema_meta_v2 where key='schema_version'").fetchone()[0])
            self.assertEqual("ok", con.execute("pragma integrity_check").fetchone()[0])
            self.assertEqual(1, con.execute("select count(*) from paper_v2_migrations").fetchone()[0])
        finally:
            con.close()

    def test_legacy_positions_and_pending_orders_preserve_economic_state(self):
        con = sqlite3.connect(self.db)
        try:
            state = json.loads(con.execute("select state_json from paper_portfolios where portfolio_id='LEGACY'").fetchone()[0])
            state.update(cash=60000, nav=99500, invested_value=39500)
            con.execute("update paper_portfolios set state_json=? where portfolio_id='LEGACY'", (json.dumps(state),))
            position = {
                "position_id": "POS1", "portfolio_id": "LEGACY", "symbol": "HINDZINC",
                "state": "HELD", "qty": 79, "entry_price": 490, "last_price": 500,
                "entry_signal_date": "2026-10-13", "entry_fill_date": "2026-10-14",
                "last_valuation_session": "2026-10-15",
            }
            con.execute(
                "insert into paper_positions values(?,?,?,?,?,?,?)",
                ("POS1", "LEGACY", "HINDZINC", "HELD", 79, 490, json.dumps(position)),
            )
            order = {
                "order_id": "ORD1", "portfolio_id": "LEGACY", "symbol": "GODREJCP",
                "side": "BUY", "state": "PENDING_NEXT_OPEN", "signal_session": "2026-10-15",
                "expected_execution_session": "2026-10-16", "allocation": {"estimated_cost": 10000},
            }
            con.execute(
                "insert into paper_orders values(?,?,?,?,?,?,?,?)",
                ("ORD1", "LEGACY", "GODREJCP", "BUY", "PENDING_NEXT_OPEN", "2026-10-15", None, json.dumps(order)),
            )
            con.commit()
        finally:
            con.close()
        migrated = self.migrate()
        state = load_portfolio(self.db)
        self.assertEqual(1, migrated["positions"])
        self.assertEqual(1, migrated["pending_orders"])
        self.assertEqual(60000, state["cash"])
        self.assertEqual(99500, state["nav"])
        self.assertEqual("HOLD", state["positions"][0]["state"])
        self.assertEqual("2026-10-14", state["positions"][0]["entry_fill_session"])
        self.assertEqual(10000, state["pending_capital"])
        self.assertEqual("2026-10-16", state["pending_orders"][0]["eligible_session"])

    def test_migrated_session_commit_prevents_historical_trade_injection(self):
        self.migrate()
        state = load_portfolio(self.db)
        result = process_paper_session(
            self.db, portfolio_id=state["portfolio_id"], expected_session="2026-10-15",
            latest_official_session="2026-10-15", official_freshness="PASS",
            production_session="2026-10-15", production_run_id="NEW-RUN",
            app_version="0.14.13-paper-trading-repair", production_model_version="LIVE_DECISION_V1",
            evidence_pipeline_version="evidence", candidates=[candidate("HINDZINC", "2026-10-15")],
            allocation_plan={"new_buys": [{"symbol": "HINDZINC", "estimated_cost": 40000}]},
            official_opens={}, official_closes={}, available_sessions=["2026-10-15"], official_opens_by_session={},
        )
        self.assertTrue(result["duplicate"])
        self.assertEqual([], result["new_orders"])
        self.assertEqual([], load_portfolio(self.db)["pending_orders"])


class SchemaMigrationTests(unittest.TestCase):
    def test_ambiguous_preexisting_order_duplicates_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            db = Path(directory) / "ambiguous.sqlite3"
            con = sqlite3.connect(db, isolation_level=None)
            try:
                con.executescript(
                    """
                    create table paper_v2_portfolios (
                      portfolio_id text primary key, created_at text not null, status text not null,
                      starting_capital real not null, starting_session text not null,
                      starting_run_id text not null, app_version text not null,
                      production_model_version text not null, evidence_pipeline_version text not null,
                      router_sha256 text not null, state_json text not null
                    );
                    create table paper_v2_orders (
                      order_id text primary key, portfolio_id text not null, symbol text not null,
                      side text not null, state text not null, signal_session text not null,
                      fill_session text, reserved_capital real not null default 0, order_json text not null
                    );
                    """
                )
                state = json.dumps({"portfolio_id": "P", "cash": 100000, "status": "ACTIVE"})
                con.execute("insert into paper_v2_portfolios values(?,?,?,?,?,?,?,?,?,?,?)", ("P", "2026-10-15T00:00:00", "ACTIVE", 100000, "2026-10-15", "R", "v3", "m", "e", "sha", state))
                for order_id in ("A", "B"):
                    order = json.dumps({"order_id": order_id, "portfolio_id": "P", "symbol": "AAA", "side": "BUY", "state": "PENDING_NEXT_OPEN", "signal_session": "2026-10-15"})
                    con.execute("insert into paper_v2_orders values(?,?,?,?,?,?,?,?,?)", (order_id, "P", "AAA", "BUY", "PENDING_NEXT_OPEN", "2026-10-15", None, 10000, order))
                with self.assertRaisesRegex(RuntimeError, "AMBIGUOUS_ORDER_DUPLICATES"):
                    migrate(con)
                self.assertEqual(2, con.execute("select count(*) from paper_v2_orders").fetchone()[0])
                self.assertEqual("ok", con.execute("pragma integrity_check").fetchone()[0])
            finally:
                con.close()


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
