from __future__ import annotations

import importlib.util
import json
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
    temp = Path(tempfile.mkdtemp(prefix="sre_phase7_refresh_contract_", dir=scratch))
    try:
        engine = temp / "engine"
        (engine / "stock_app").mkdir(parents=True)
        (engine / "modern_ui/frontend").mkdir(parents=True)
        (engine / "phase7").mkdir(parents=True)
        (engine / "stock_app/__init__.py").write_text("", encoding="utf-8")
        (engine / "stock_app/official_daily_refresh.py").write_text("# replaced by native114\n", encoding="utf-8")
        (engine / "modern_ui/api.py").write_text(
            '''from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
APP_VERSION = "0.12.7-phase7-official-source-diagnostics-hotfix"
class Ctx:
    def __init__(self, latest="2026-10-09", refresh=None):
        self.latest = latest
        self.refresh = refresh
        self.prices = type("P", (), {"cache": {}})()
    @classmethod
    def expected_market_session(cls, now=None):
        return {"current_calendar_date": "2026-10-12", "expected_market_session": "2026-10-12"}
    def data_source_status(self):
        return {"mode": "REAL_OFFICIAL_DATA", "active": {"latest_session": self.latest, "cache_roots": [], "history_coverage": 1.0, "identity_coverage": 1.0}}
    def _refresh_official_first_market_data(self) -> dict[str, Any]:
        return {"status": "ERROR", "error": "old", "source": self.data_source_status(), "automatic_yfinance_fallback": False}

    def _daily_data_gate(self) -> dict[str, Any]:
        return {}

    def post_close_daily_status(self) -> dict[str, Any]:
        return {}

    def run_post_close_daily_flow(self, *, force: bool = False) -> dict[str, Any]:
        return {}
    def _read_daily_state(self): return {}
    def ui_run_input(self): return None
    def latest_prediction_rows(self, limit=100): return []
''',
            encoding="utf-8",
        )
        (engine / "modern_ui/frontend/app.js").write_text(
            "function renderPostCloseDaily(x){return x}\nfunction renderToday(d){return d}\n",
            encoding="utf-8",
        )
        (engine / "modern_ui/frontend/styles.css").write_text("", encoding="utf-8")
        env = os.environ.copy()
        env["SRE_ENGINE_ROOT"] = str(engine)
        subprocess.run([sys.executable, str(ROOT / ".ci/native114/patch114_refresh_contract.py")], cwd=ROOT, env=env, check=True)

        sys.path.insert(0, str(engine))
        spec = importlib.util.spec_from_file_location("api_refresh_contract", engine / "modern_ui/api.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        official = (engine / "stock_app/official_daily_refresh.py").read_text(encoding="utf-8")
        js = (engine / "modern_ui/frontend/app.js").read_text(encoding="utf-8")
        policy = json.loads((engine / "phase7/refresh_contract_0127.json").read_text(encoding="utf-8"))

        api_text = (engine / "modern_ui/api.py").read_text(encoding="utf-8")
        cases: list[tuple[str, bool]] = [
            ("contract status names", all(x in (official + api_text) for x in policy["statuses"])),
            ("no legacy refreshed status", '"REFRESHED"' not in official and "status == \"REFRESHED \"" not in official),
            ("verified status present", "REFRESHED_AND_VERIFIED" in official),
            ("no automatic yfinance import", "import yfinance" not in official.lower()),
            ("frontend source detail", "Source detail" in js and "refresh_label" in js),
            ("blocked icon non-green", "action-ring.blocked" in (engine / "modern_ui/frontend/styles.css").read_text(encoding="utf-8")),
        ]

        stale = mod.Ctx(latest="2026-10-09").post_close_daily_status()
        cases.extend([
            ("stale blocked", stale["run_status"] == "BLOCKED - OFFICIAL SOURCE ERROR"),
            ("stale not refreshed", stale["refresh_label"] == "FAILED"),
            ("stale detail preserved", stale["source_detail"] != "UNKNOWN_OFFICIAL_SOURCE_ERROR"),
            ("latest preserved", stale["latest_available_official_session"] == "2026-10-09"),
        ])
        for name, ok in cases:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        return 0 if all(ok for _, ok in cases) else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
