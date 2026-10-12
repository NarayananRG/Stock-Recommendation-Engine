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
    temp = Path(tempfile.mkdtemp(prefix="sre_phase7_0124_", dir=scratch))
    try:
        engine = temp / "engine"
        (engine / "modern_ui/frontend").mkdir(parents=True)
        (engine / "phase7").mkdir(parents=True)
        (engine / "modern_ui/api.py").write_text(
            '''from __future__ import annotations
import json, os
from datetime import datetime, timedelta
from pathlib import Path
APP_VERSION = "0.12.3-phase7-daily-flow-ui-hotfix"
class Ctx:
    def __init__(self, latest="2026-10-09", mode="REAL_OFFICIAL_DATA"):
        self.latest = latest; self.mode = mode; self.config = type("C", (), {"app_data_dir": Path(".")})()
    def data_source_status(self):
        return {"mode": self.mode, "active": {"latest_session": self.latest, "history_coverage": 1.0, "identity_coverage": 1.0}}
    def ui_run_input(self): return None
    def latest_prediction_rows(self, limit=100): return []
    def active_target_state(self): return {"explicit": False}
    def _read_daily_state(self): return {}
    def _write_daily_state(self, payload): self.written = payload
    def _daily_data_gate(self) -> dict:
        return {"target_session": self.latest, "latest_official_session": self.latest, "ready": True, "blocked_reason": None}
    def post_close_daily_status(self) -> dict:
        return {}
    def ensure_analysis_run(self, *a): self.created = True; return {"run": {"run_id": "R1"}}, False
    def monitoring(self): return None
''',
            encoding="utf-8",
        )
        (engine / "modern_ui/frontend/app.js").write_text(
            "function renderPostCloseDaily(x){const a=[['Target session',x.target_session],['Latest official session',x.latest_available_official_session],['Recommendations',String(x.recommendation_count??0)]]}\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["SRE_ENGINE_ROOT"] = str(engine)
        subprocess.run([sys.executable, str(ROOT / ".ci/native111/patch111_session_freshness_windows.py")], cwd=ROOT, env=env, check=True)
        spec = importlib.util.spec_from_file_location("api0124", engine / "modern_ui/api.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        cases: list[tuple[str, bool]] = []
        samples = [
            ("monday after close", "2026-10-12T16:10:00+05:30", "2026-10-12"),
            ("monday before close", "2026-10-12T14:30:00+05:30", "2026-10-09"),
            ("saturday", "2026-10-10T18:00:00+05:30", "2026-10-09"),
            ("sunday", "2026-10-11T18:00:00+05:30", "2026-10-09"),
            ("holiday monday", "2026-01-26T18:00:00+05:30", "2026-01-23"),
        ]
        for name, now, expected in samples:
            os.environ["SRE_EXPECTED_SESSION_NOW"] = now
            cases.append((name, mod.Ctx.expected_market_session()["expected_market_session"] == expected))

        os.environ["SRE_EXPECTED_SESSION_NOW"] = "2026-10-12T16:10:00+05:30"
        stale = mod.Ctx(latest="2026-10-09")._daily_data_gate()
        current = mod.Ctx(latest="2026-10-12")._daily_data_gate()
        cases.extend(
            [
                ("stale official blocked", stale["ready"] is False and stale["blocked_reason"] == "OFFICIAL_DATA_NOT_READY"),
                ("current official pass", current["ready"] is True and current["freshness_gate"] == "PASS"),
                ("separate concepts", stale["current_calendar_date"] == "2026-10-12" and stale["expected_market_session"] == "2026-10-12" and stale["latest_official_session"] == "2026-10-09"),
                ("no yfinance invocation", "import yfinance" not in (engine / "modern_ui/api.py").read_text(encoding="utf-8").lower()),
                ("windows docs", (engine / "WINDOWS_TRUST_STATUS.md").exists() and (engine / "phase7/windows_packaging_comparison_0124.md").exists()),
            ]
        )
        for name, ok in cases:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        return 0 if all(ok for _, ok in cases) else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
