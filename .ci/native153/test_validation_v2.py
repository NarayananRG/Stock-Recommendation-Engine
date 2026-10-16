from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
engine = Path(os.environ["SRE_ENGINE_ROOT"]) if os.environ.get("SRE_ENGINE_ROOT") else None
module_path = engine / "stock_app" / "validation_v2.py" if engine and (engine / "stock_app" / "validation_v2.py").exists() else repo / ".ci" / "native153" / "validation_v2.py"
spec = importlib.util.spec_from_file_location("sre_validation_v2", module_path)
v2 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(v2)


def rec(symbol: str, action: str = "RECOVERY BUY", executable: bool = True) -> dict:
    return {
        "symbol": symbol,
        "executable": executable,
        "live_decision": {
            "final_action": action,
            "executable": executable,
            "strategy_style": "RECOVERY",
            "confidence": "MEDIUM",
            "thesis": f"{symbol} deterministic fixture",
        },
    }


def run() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "validation_v2.sqlite3"
        p = v2.create_portfolio(
            db,
            start_session="2026-10-15",
            starting_capital=100000,
            start_production_run_id="RUN-D0",
            app_version="0.14.12-validation-v2",
            model_version="LIVE_DECISION_V1",
            evidence_version="0.14.11",
        )
        pid = p["portfolio_id"]
        assert p["cash"] == 100000
        assert p["active"] is True
        assert p["legacy_v1_excluded"] is True

        plan = {
            "new_buys": [
                {"symbol": "HINDZINC", "estimated_cost": 30000},
                {"symbol": "GODREJCP", "estimated_cost": 30000},
            ]
        }
        signal = v2.record_signal_session(
            db,
            portfolio_id=pid,
            market_session="2026-10-15",
            production_run_id="RUN-D0",
            app_version="0.14.12-validation-v2",
            model_version="LIVE_DECISION_V1",
            evidence_version="0.14.11",
            recommendations=[rec("HINDZINC"), rec("GODREJCP"), rec("INFY", "WATCH - RECOVERY", False)],
            capital_plan=plan,
            official_data_ready=True,
            analysis_session_current=True,
        )
        assert signal["event_type"] == "BUY_SIGNAL"
        assert signal["allocated_buy_count"] == 2
        status = v2.load_portfolio(db, pid)
        assert len(status["pending_orders"]) == 2
        assert status["cash"] == 100000, "Signal generation must not spend cash"

        duplicate = v2.record_signal_session(
            db,
            portfolio_id=pid,
            market_session="2026-10-15",
            production_run_id="RUN-D0",
            app_version="0.14.12-validation-v2",
            model_version="LIVE_DECISION_V1",
            evidence_version="0.14.11",
            recommendations=[rec("HINDZINC"), rec("GODREJCP")],
            capital_plan=plan,
            official_data_ready=True,
            analysis_session_current=True,
        )
        assert duplicate["duplicate"] is True
        assert len(v2.load_portfolio(db, pid)["pending_orders"]) == 2

        fills = v2.apply_next_open_fills(
            db,
            portfolio_id=pid,
            fill_session="2026-10-16",
            official_open_prices={"HINDZINC": 500.0, "GODREJCP": 1200.0},
            assumptions=v2.ExecutionAssumptions(slippage_bps=10, transaction_cost_bps=5),
        )
        assert len(fills) == 2
        status = v2.load_portfolio(db, pid)
        assert len(status["positions"]) == 2
        assert len(status["pending_orders"]) == 0
        assert status["cash"] < 100000
        cash_after_fill = status["cash"]

        no_double_fill = v2.apply_next_open_fills(
            db,
            portfolio_id=pid,
            fill_session="2026-10-16",
            official_open_prices={"HINDZINC": 500.0, "GODREJCP": 1200.0},
        )
        assert no_double_fill == []
        assert v2.load_portfolio(db, pid)["cash"] == cash_after_fill

        mark = v2.mark_to_market(
            db,
            portfolio_id=pid,
            market_session="2026-10-16",
            official_close_prices={"HINDZINC": 520.0, "GODREJCP": 1210.0},
            benchmark_value=101000.0,
        )
        assert mark["valuation_quality"] == "CURRENT_OFFICIAL_MARKS"
        assert mark["nav"] > 0
        assert mark["unrealized_pnl"] != 0

        stale_mark = v2.mark_to_market(
            db,
            portfolio_id=pid,
            market_session="2026-10-17",
            official_close_prices={"HINDZINC": 525.0},
            benchmark_value=100500.0,
        )
        assert stale_mark["valuation_quality"] == "STALE_MARK"
        assert "GODREJCP" in stale_mark["stale_symbols"]

        exit_order = v2.queue_exit(
            db,
            portfolio_id=pid,
            symbol="HINDZINC",
            market_session="2026-10-17",
            production_run_id="RUN-D2",
            reason="THESIS_BROKEN",
        )
        assert exit_order["state"] == "PENDING_EXIT_NEXT_OPEN"
        status = v2.load_portfolio(db, pid)
        assert any(o["side"] == "SELL" for o in status["pending_orders"])

        exit_fills = v2.apply_next_open_fills(
            db,
            portfolio_id=pid,
            fill_session="2026-10-20",
            official_open_prices={"HINDZINC": 530.0},
        )
        assert len(exit_fills) == 1
        assert exit_fills[0]["event_type"] == "EXIT_FILLED"
        status = v2.load_portfolio(db, pid)
        assert all(x["symbol"] != "HINDZINC" for x in status["positions"])
        assert status["realized_pnl"] != 0

        blocked_db = v2.record_signal_session(
            db,
            portfolio_id=pid,
            market_session="2026-10-20",
            production_run_id="RUN-D3",
            app_version="0.14.12-validation-v2",
            model_version="LIVE_DECISION_V1",
            evidence_version="0.14.11",
            recommendations=[rec("INFY")],
            capital_plan={"new_buys": [{"symbol": "INFY", "estimated_cost": 10000}]},
            official_data_ready=False,
            analysis_session_current=False,
        )
        assert blocked_db["event_type"] == "NO_ACTION_OFFICIAL_DATA_NOT_READY"

        bench = v2.benchmark_nav_series(100000, [("D0", 100), ("D1", 105), ("D2", 110)])
        assert bench[0]["benchmark_nav"] == 100000
        assert bench[-1]["benchmark_nav"] == 110000

        metrics = v2.replay_metrics(
            starting_capital=100000,
            nav_series=[{"session": "D0", "nav": 100000}, {"session": "D1", "nav": 102000}, {"session": "D2", "nav": 108000}],
            benchmark_series=bench,
            filled_entries=2,
            filled_exits=1,
            closed_trade_pnls=[500.0, -100.0],
        )
        assert metrics["portfolio_return"] == 0.08
        assert metrics["benchmark_return"] == 0.10
        assert metrics["excess_return"] == -0.02
        assert metrics["win_rate"] == 0.5

        assert v2.classify_replay_session(
            market_data_ready=True,
            fundamental_pit_ready=True,
            valuation_pit_ready=True,
            production_reconstruction_ready=True,
        ) == "FULL_PIT_VALID"
        assert v2.classify_replay_session(
            market_data_ready=True,
            fundamental_pit_ready=False,
            valuation_pit_ready=True,
            production_reconstruction_ready=True,
        ) == "NOT_REPLAYABLE"

        all_portfolios = v2.list_portfolios(db)
        assert len(all_portfolios) == 1
        assert all_portfolios[0]["portfolio_id"] == pid

    print("VALIDATION V2 CORE TESTS PASS")


if __name__ == "__main__":
    run()
