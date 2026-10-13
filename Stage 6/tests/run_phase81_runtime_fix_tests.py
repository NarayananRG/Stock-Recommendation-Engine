from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)


def main() -> int:
    scratch = ROOT / "work"
    scratch.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="sre_phase81_runtime_", dir=scratch))
    try:
        engine = temp / "engine"
        (engine / "modern_ui/frontend").mkdir(parents=True)
        (engine / "modern_ui/__init__.py").write_text("", encoding="utf-8")
        api = engine / "modern_ui/api.py"
        api.write_text('''from typing import Any
APP_VERSION = "0.13.2-phase8-validation-complete"

class Prices:
    def __init__(self):
        self._cache = {"x": 1}

class Ctx:
    def __init__(self):
        self.prices = Prices()
        self.calls = 0
    def expected_market_session(self):
        return {"expected_market_session": "2026-10-13"}
    def data_source_status(self):
        self.calls += 1
        return {"mode": "REAL_OFFICIAL_DATA", "active": {"latest_session": "2026-10-12", "cache_roots": ["mock"], "history_coverage": 1.0}}
    def _refresh_official_first_market_data(self) -> dict[str, Any]:
        expected = self.expected_market_session()["expected_market_session"]
        try:
            before = self.data_source_status()
            active_before = dict(before.get("active") or {})
            if before.get("mode") == "REAL_OFFICIAL_DATA" and active_before.get("latest_session") == expected:
                return {"status": "PASS", "refresh_result": {"status": "ALREADY_CURRENT", "verified_latest_session": expected}, "source": before}
            from stock_app.official_daily_refresh import refresh_official_session
            refresh = refresh_official_session(list(active_before.get("cache_roots") or []), expected)
            if refresh.get("status") == "REFRESHED_AND_VERIFIED":
                for attr in ("_cache", "cache", "_history_cache", "_data_cache"):
                    value = getattr(self.prices, attr, None)
                    if isinstance(value, dict):
                        value.clear()
            source = self.data_source_status()
            latest = (source.get("active") or {}).get("latest_session")
            if source.get("mode") == "REAL_OFFICIAL_DATA" and latest == expected:
                status = "PASS"
            elif refresh.get("status") == "OFFICIAL_NOT_READY":
                status = "NOT_READY"
            else:
                status = "ERROR"
            return {"status": status, "refresh_result": refresh, "source": source, "automatic_yfinance_fallback": False}
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc), "source": self.data_source_status()}

    def phase81_paper_status(self):
        return {"active": False}
    def phase81_start_paper(self, starting_capital=100000.0):
        raise AssertionError("inactive paper must not auto-start")
    def _daily_data_gate(self):
        return {}
    def ui_run_input(self):
        return {}
    def latest_prediction_rows(self, limit=200):
        return []
    def _phase81_db_path(self):
        return Path("x")
    def phase81_record_today(self) -> dict[str, Any]:
        from stock_app.phase81_validation import record_daily_observation
        status = self.phase81_paper_status()
        if not status.get("active"):
            status = self.phase81_start_paper(100000.0)
        gate = self._daily_data_gate()
        run = self.ui_run_input() or {}
        return record_daily_observation(self._phase81_db_path(), portfolio_id=status["portfolio_id"], market_session=str(gate.get("target_session") or gate.get("latest_official_session")), production_run_id=run.get("run_id"), recommendations=self.latest_prediction_rows(limit=200), capital_plan={"new_buys": [], "excluded": []})
''', encoding="utf-8")
        (engine / "modern_ui/frontend/app.js").write_text("function loadValidation(){}\n", encoding="utf-8")
        (engine / "modern_ui/frontend/styles.css").write_text("", encoding="utf-8")

        env = os.environ.copy()
        env["SRE_ENGINE_ROOT"] = str(engine)
        subprocess.run([sys.executable, str(ROOT / ".ci/native117/patch117_phase81_runtime_fix.py")], cwd=ROOT, env=env, check=True)

        stock_app = types.ModuleType("stock_app")
        refresh_mod = types.ModuleType("stock_app.official_daily_refresh")
        refresh_mod.refresh_official_session = lambda roots, expected: {
            "status": "REFRESHED_AND_VERIFIED",
            "verified_latest_session": expected,
            "persisted": True,
        }
        phase_mod = types.ModuleType("stock_app.phase81_validation")
        phase_mod.record_daily_observation = lambda *a, **k: {"unexpected": True}
        sys.modules["stock_app"] = stock_app
        sys.modules["stock_app.official_daily_refresh"] = refresh_mod
        sys.modules["stock_app.phase81_validation"] = phase_mod

        spec = importlib.util.spec_from_file_location("runtime_api", api)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        ctx = mod.Ctx()
        result = ctx._refresh_official_first_market_data()
        inactive = ctx.phase81_record_today()
        js = (engine / "modern_ui/frontend/app.js").read_text(encoding="utf-8")
        css = (engine / "modern_ui/frontend/styles.css").read_text(encoding="utf-8")
        source = api.read_text(encoding="utf-8")

        cases = [
            ("version bumped", '0.13.3-phase8-runtime-fix' in source),
            ("verified refresh becomes pass", result.get("status") == "PASS"),
            ("verified latest normalized", (result.get("source") or {}).get("active", {}).get("latest_session") == "2026-10-13"),
            ("price cache cleared", ctx.prices._cache == {}),
            ("inactive paper does not auto-start", inactive.get("status") == "PAPER_PORTFOLIO_INACTIVE" and inactive.get("recorded") is False),
            ("validation route isolation hook", "phase81SetValidationRoute" in js and "stopImmediatePropagation" in js),
            ("validation default hidden css", "#validationPage{display:none!important}" in css),
            ("validation active css", "#validationPage.phase81-route-active{display:block!important}" in css),
        ]
        for name, ok in cases:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        return 0 if all(ok for _, ok in cases) else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
