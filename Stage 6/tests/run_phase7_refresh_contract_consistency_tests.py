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
