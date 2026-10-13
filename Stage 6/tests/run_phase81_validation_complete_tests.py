from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_minimal_engine(engine: Path) -> None:
    (engine / "stock_app").mkdir(parents=True)
    (engine / "modern_ui/frontend").mkdir(parents=True)
    (engine / "phase8").mkdir(parents=True)
    (engine / "stock_app/__init__.py").write_text("", encoding="utf-8")
    (engine / "modern_ui/api.py").write_text(
        '''from __future__ import annotations
import json, re
from datetime import datetime
from pathlib import Path
from typing import Any
APP_VERSION = "0.12.7-phase7-official-source-diagnostics-hotfix"
class Config:
    app_data_dir = Path(".")
    official_cache_dir = Path("official_cache")
class Ctx:
    def __init__(self):
        self.config = Config()
    def _daily_data_gate(self):
        return {"ready": True, "target_session": "2026-10-12", "latest_official_session": "2026-10-12", "source": {"mode": "REAL_OFFICIAL_DATA"}}
    def ui_run_input(self):
        return {"run_id": "RUN1", "market_session": "2026-10-12"}
    def latest_prediction_rows(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {"symbol": "AAA", "opportunity_status": "WATCH - TECHNICAL ONLY", "executable": False, "execution_reason": "WATCH_NON_EXECUTABLE"},
            {"symbol": "BBB", "opportunity_status": "BUY", "executable": True},
        ]
    def post_close_daily_status(self) -> dict[str, Any]:
        return {"run_status": "READY"}
    def run_post_close_daily_flow(self, *, force: bool = False) -> dict[str, Any]:
        success = {"run_id": "RUN1", "market_session": "2026-10-12"}
        result = {**self.post_close_daily_status(), "ok": True, "run_status": "SUCCESS", "duplicate": False, "last_successful_daily_run": success}
        return result
def build_app():
    ctx=Ctx()
    class App:
        def get(self, path):
            def deco(fn): return fn
            return deco
        def post(self, path):
            def deco(fn): return fn
            return deco
    app=App()
    @app.get("/api/today")
    def today() -> dict[str, Any]:
        return {}
''',
        encoding="utf-8",
    )
    (engine / "modern_ui/frontend/app.js").write_text(
        "const $=(s)=>document.querySelector(s);\nfunction api(){}\nfunction busy(){}\nfunction toast(){}\nfunction escapeHtml(x){return String(x)}\nfunction fmtINR(x){return String(x)}\nfunction fmtPctFraction(x){return String(x)}\nfunction switchPage(page){if(page==='today')loadToday();}\nfunction loadToday(){}\n",
        encoding="utf-8",
    )
    (engine / "modern_ui/frontend/index.html").write_text(
        '<nav><button type="button" class="nav-item" data-page="today">Today</button><button type="button" class="nav-item" data-page="history">History</button><button type="button" class="nav-item" data-page="system">System</button></nav><main><section id="todayPage" class="page-section">Today</section><section id="historyPage" class="page-section hidden">History</section><section id="systemPage" class="page-section hidden">System</section></main>',
        encoding="utf-8",
    )
    (engine / "modern_ui/frontend/styles.css").write_text("", encoding="utf-8")


def main() -> int:
    scratch = ROOT / "work"
    scratch.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="sre_phase81_complete_", dir=scratch))
    try:
        engine = temp / "engine"
        write_minimal_engine(engine)
        (engine / "official_cache").mkdir()
        for session in ("2026-10-08", "2026-10-09", "2026-10-12"):
            (engine / "official_cache" / f"bhavcopy_{session}.json").write_text("{}", encoding="utf-8")
        env = os.environ.copy()
        env["SRE_ENGINE_ROOT"] = str(engine)
        subprocess.run([sys.executable, str(ROOT / ".ci/native115/patch115_phase81_validation.py")], cwd=ROOT, env=env, check=True)
        subprocess.run([sys.executable, str(ROOT / ".ci/native116/patch116_phase81_complete.py")], cwd=ROOT, env=env, check=True)
        sys.path.insert(0, str(engine))
        from stock_app import phase81_validation as v

        db = temp / "paper.sqlite3"
        p = v.create_portfolio(db, starting_session="2026-10-12", starting_capital=100000)
        watch = [{"symbol": "AAA", "opportunity_status": "WATCH - TECHNICAL ONLY", "executable": False}]
        buy = [{"symbol": "BBB", "opportunity_status": "BUY", "executable": True}]
        e1 = v.record_daily_observation(db, portfolio_id=p["portfolio_id"], market_session="2026-10-12", production_run_id="RUN1", recommendations=watch)
        e2 = v.record_daily_observation(db, portfolio_id=p["portfolio_id"], market_session="2026-10-12", production_run_id="RUN1", recommendations=watch)
        e3 = v.record_daily_observation(db, portfolio_id=p["portfolio_id"], market_session="2026-10-13", production_run_id="RUN2", recommendations=buy, capital_plan={"new_buys": [{"symbol": "BBB", "capital": 50000}]})
        fills = v.apply_open_fills(db, portfolio_id=p["portfolio_id"], fill_session="2026-10-14", open_prices={"BBB": 100.0}, assumptions=v.ExecutionAssumptions(slippage_bps=10, transaction_cost_bps=5))
        holds = v.mark_daily_hold_exit(db, portfolio_id=p["portfolio_id"], market_session="2026-10-14", production_run_id="RUN3", recommendations=[{"symbol": "BBB", "opportunity_status": "HOLD", "executable": False}])
        weakening = v.mark_daily_hold_exit(db, portfolio_id=p["portfolio_id"], market_session="2026-10-15", production_run_id="RUN4", recommendations=[{"symbol": "BBB", "opportunity_status": "WEAKENING", "executable": False}])
        exits = v.mark_daily_hold_exit(db, portfolio_id=p["portfolio_id"], market_session="2026-10-16", production_run_id="RUN5", recommendations=[{"symbol": "BBB", "opportunity_status": "EXIT", "executable": False}])
        close = v.apply_open_fills(db, portfolio_id=p["portfolio_id"], fill_session="2026-10-19", open_prices={"BBB": 110.0}, assumptions=v.ExecutionAssumptions(slippage_bps=10, transaction_cost_bps=5))
        state = v.load_portfolio(db, p["portfolio_id"])
        s0 = v.session_summary("2026-10-08", [], capital_plan={"new_buys": []}, assumptions=v.ExecutionAssumptions(), pit_status="PIT_DATA_INCOMPLETE", model_identity="test")
        s1 = v.session_summary("2026-10-12", buy, capital_plan={"new_buys": [{"symbol": "BBB", "capital": 50000}]}, assumptions=v.ExecutionAssumptions(), pit_status="FULL_PIT_VALID", model_identity="test")
        metrics = v.replay_metrics([s0, s1], nav=[100000, 102000], benchmark_nav=[100000, 101000], trades=[{"state": "CLOSED", "realized_pnl": 1000, "holding_sessions": 3}])
        html = (engine / "modern_ui/frontend/index.html").read_text(encoding="utf-8")
        js = (engine / "modern_ui/frontend/app.js").read_text(encoding="utf-8")
        module_text = (engine / "stock_app/phase81_validation.py").read_text(encoding="utf-8").lower()
        con = sqlite3.connect(db)
        journal_count = con.execute("select count(*) from paper_journal").fetchone()[0]
        cases = [
            ("version identity", "0.13.2-phase8-validation-complete" in (engine / "modern_ui/api.py").read_text(encoding="utf-8")),
            ("single static validation nav", html.count('data-page="validation"') == 1),
            ("validation page hidden", 'id="validationPage" class="page-section hidden"' in html),
            ("tabs implemented", "function setValidationTab(tab)" in js and "validationPaperPanel" in js),
            ("default replay tab visible", "setValidationTab('replay')" in js),
            ("paper tab hidden initially", 'id="validationPaperPanel" class="panel-card hidden"' in html),
            ("error visible", "validationError('Historical replay failed'" in js and "validationError('Paper portfolio failed'" in js),
            ("run replay button", "RUN HISTORICAL REPLAY" in js),
            ("start paper button", "START PROSPECTIVE TRACKING" in js),
            ("no silent catches", "catch{}" not in js),
            ("no dynamic nav injection", "ensureValidationNav" not in js),
            ("multi-session loop helpers", v.trading_sessions_for_range(["2026-10-08", "2026-10-09", "2026-10-12"], "2026-10-01", "2026-10-12") == ["2026-10-08", "2026-10-09", "2026-10-12"]),
            ("range 1M", v.period_start("2026-10-12", "1M") == "2026-09-11"),
            ("range 3M", v.period_start("2026-10-12", "3M") == "2026-07-11"),
            ("range 6M", v.period_start("2026-10-12", "6M") == "2026-04-09"),
            ("custom range", v.period_start("2026-10-12", "Custom", "2026-10-01") == "2026-10-01"),
            ("PIT future price rejection", raises(lambda: v.reject_future_price("2026-10-12", "2026-10-13"))),
            ("PIT future fundamental rejection", raises(lambda: v.reject_future_fundamental("2026-10-12", "2026-10-13"))),
            ("incomplete classification", s0["pit_status"] == "PIT_DATA_INCOMPLETE"),
            ("same-day fill rejected", raises(lambda: v.next_open_fill("2026-10-12", "2026-10-12", 100, "BUY"))),
            ("whole share sizing", v.whole_share_quantity(100000, 100, v.ExecutionAssumptions(slippage_bps=10, transaction_cost_bps=5)) == 998),
            ("slippage and costs deterministic", v.next_open_fill("2026-10-12", "2026-10-13", 100, "BUY", v.ExecutionAssumptions(slippage_bps=10, transaction_cost_bps=5))["net_price"] == 100.15),
            ("zero buy cash", e1["decision"] == "CASH / NO EXECUTABLE BUY"),
            ("watch cannot position", v.is_executable(watch[0]) is False),
            ("buy pending order", e3["event_type"] == "SIGNAL_GENERATED" and e3["orders"][0]["state"] == "PENDING_NEXT_OPEN"),
            ("next session fills", len(fills) == 1 and fills[0]["event_type"] == "FILLED"),
            ("hold keeps position", len(holds) == 1 and holds[0]["event_type"] == "HELD"),
            ("weakening no exit", len(weakening) == 1 and weakening[0]["event_type"] == "WEAKENING"),
            ("exit pending and fill", len(exits) == 1 and exits[0]["event_type"] == "EXIT_SIGNAL_GENERATED" and len(close) == 1 and close[0]["event_type"] == "CLOSED"),
            ("realized pnl", close[0]["realized_pnl"] > 0),
            ("nav persisted", state["nav"] > 100000),
            ("duplicate idempotent", e2["duplicate"] is True and e1["event_id"] == e2["event_id"]),
            ("append-only journal", journal_count >= 7),
            ("benchmark alignment", metrics["benchmark_return"] == 0.01),
            ("zero buy streak", metrics["longest_no_buy_streak"] == 0),
            ("buy frequency", metrics["buy_frequency"] == 1.0),
            ("max drawdown", v.max_drawdown([100, 120, 90]) == -0.25),
            ("activity classification", metrics["activity_classification"] == "NORMAL_ACTIVITY"),
            ("no yfinance", "import yfinance" not in module_text),
            ("production authority unchanged", v.AUTHORITY["production_rank_authority_changed"] is False),
            ("shadow authority unchanged", v.AUTHORITY["technical_v2_authority"] == "SHADOW_ONLY" and v.AUTHORITY["fundamental_v3_authority"] == "SHADOW_ONLY" and v.AUTHORITY["combined_v2_authority"] == "SHADOW_ONLY"),
        ]
        for name, ok in cases:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        return 0 if all(ok for _, ok in cases) else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def raises(fn) -> bool:
    try:
        fn()
        return False
    except Exception:
        return True


if __name__ == "__main__":
    raise SystemExit(main())
