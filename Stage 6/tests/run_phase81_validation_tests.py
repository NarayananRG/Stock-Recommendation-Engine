from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    scratch = ROOT / "work"
    scratch.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="sre_phase81_", dir=scratch))
    try:
        engine = temp / "engine"
        (engine / "stock_app").mkdir(parents=True)
        (engine / "modern_ui/frontend").mkdir(parents=True)
        (engine / "phase8").mkdir(parents=True)
        (engine / "stock_app/__init__.py").write_text("", encoding="utf-8")
        (engine / "modern_ui/api.py").write_text(
            '''from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any
APP_VERSION = "0.12.7-phase7-official-source-diagnostics-hotfix"
class Config:
    app_data_dir = Path(".")
class Ctx:
    def __init__(self):
        self.config = Config()
    def _daily_data_gate(self):
        return {"ready": True, "target_session": "2026-10-12", "latest_official_session": "2026-10-12", "source": {"mode": "REAL_OFFICIAL_DATA"}}
    def latest_prediction_rows(self, limit=20):
        return [{"symbol": "AAA", "opportunity_status": "WATCH - TECHNICAL ONLY", "executable": False, "execution_reason": "WATCH_NON_EXECUTABLE"}]
    def ui_run_input(self):
        return {"run_id": "RUN1", "market_session": "2026-10-12"}
    def _read_daily_state(self): return {}
    def run_post_close_daily_flow(self, *, force: bool = False) -> dict[str, Any]: return {}
    def latest_prediction_rows_anchor(self): return None
    def latest_prediction_rows(self, limit: int = 20) -> list[dict[str, Any]]:
        return [{"symbol": "AAA", "opportunity_status": "WATCH - TECHNICAL ONLY", "executable": False, "execution_reason": "WATCH_NON_EXECUTABLE"}]
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
        (engine / "modern_ui/frontend/app.js").write_text("function switchPage(page){if(page==='today')loadToday();}\nfunction loadToday(){}\n", encoding="utf-8")
        (engine / "modern_ui/frontend/index.html").write_text('<nav><button type="button" class="nav-item" data-page="today">Today</button><button type="button" class="nav-item" data-page="system">System</button></nav><main></main>', encoding="utf-8")
        (engine / "modern_ui/frontend/styles.css").write_text("", encoding="utf-8")
        env = os.environ.copy()
        env["SRE_ENGINE_ROOT"] = str(engine)
        subprocess.run([sys.executable, str(ROOT / ".ci/native115/patch115_phase81_validation.py")], cwd=ROOT, env=env, check=True)
        subprocess.run([sys.executable, str(ROOT / ".ci/native116/patch116_phase81_complete.py")], cwd=ROOT, env=env, check=True)
        sys.path.insert(0, str(engine))
        from stock_app import phase81_validation as v

        rows = [
            {"symbol": "AAA", "opportunity_status": "STRONG BUY CANDIDATE", "executable": True},
            {"symbol": "BBB", "opportunity_status": "WATCH - TECHNICAL ONLY", "executable": False, "execution_reason": "WATCH_NON_EXECUTABLE"},
        ]
        zero = [{"symbol": "CCC", "opportunity_status": "WATCH - TECHNICAL ONLY", "executable": False, "execution_reason": "WATCH_NON_EXECUTABLE"}]
        assumptions = v.ExecutionAssumptions()
        s1 = v.session_summary("2026-10-12", zero, capital_plan={"new_buys": [], "excluded": []}, assumptions=assumptions, pit_status="FULL_PIT_VALID", model_identity="test")
        s2 = v.session_summary("2026-10-13", rows, capital_plan={"new_buys": [{"capital": 50000}], "excluded": []}, assumptions=assumptions, pit_status="FULL_PIT_VALID", model_identity="test")
        fill = v.next_open_fill("2026-10-12", "2026-10-13", 100.0, "BUY", v.ExecutionAssumptions(slippage_bps=10, transaction_cost_bps=5))
        db = temp / "paper.sqlite3"
        p = v.create_portfolio(db, starting_session="2026-10-12")
        e1 = v.record_daily_observation(db, portfolio_id=p["portfolio_id"], market_session="2026-10-12", production_run_id="RUN1", recommendations=zero)
        e2 = v.record_daily_observation(db, portfolio_id=p["portfolio_id"], market_session="2026-10-12", production_run_id="RUN1", recommendations=zero)
        metrics = v.replay_metrics([s1, s2], nav=[100000, 100000, 102000], benchmark_nav=[100000, 101000, 103000])
        cases = [
            ("authority frozen", v.AUTHORITY["combined_v2_authority"] == "SHADOW_ONLY" and v.AUTHORITY["combined_v2_target_used_in_score"] is False),
            ("watch non executable", v.is_executable(zero[0]) is False),
            ("zero buy cash retained", s1["executable_buy_count"] == 0 and s1["cash_retained"] == 100000.0 and s1["capital_deployed"] == 0.0),
            ("buy session counted", s2["executable_buy_count"] == 1 and s2["capital_deployed"] == 50000.0),
            ("next open timing", fill["fill_session"] == "2026-10-13" and fill["fill_price"] == 100.1 and fill["net_price"] == 100.15),
            ("same day fill rejected", _raises(lambda: v.next_open_fill("2026-10-12", "2026-10-12", 100, "BUY"))),
            ("whole shares", v.whole_share_quantity(100000, 100.0, v.ExecutionAssumptions(slippage_bps=10, transaction_cost_bps=5)) == 998),
            ("duplicate idempotent", e1["event_id"] == e2["event_id"] and e2["duplicate"] is True),
            ("metrics buy frequency", metrics["total_replayable_sessions"] == 2 and metrics["sessions_with_executable_buy"] == 1 and metrics["buy_frequency"] == 0.5),
            ("cash periods counted", metrics["average_cash_pct"] > 0),
            ("drawdown computed", v.max_drawdown([100, 120, 90]) == -0.25),
            ("no yfinance import", "import yfinance" not in (engine / "stock_app/phase81_validation.py").read_text(encoding="utf-8").lower()),
            ("static validation nav", 'data-page="validation"' in (engine / "modern_ui/frontend/index.html").read_text(encoding="utf-8")),
        ]
        for name, ok in cases:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        return 0 if all(ok for _, ok in cases) else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def _raises(fn) -> bool:
    try:
        fn()
        return False
    except Exception:
        return True


if __name__ == "__main__":
    raise SystemExit(main())
