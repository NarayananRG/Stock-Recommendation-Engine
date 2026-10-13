from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    scratch = ROOT / "work"
    scratch.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="sre_phase81_paperdup_", dir=scratch))
    try:
        engine = temp / "engine"
        (engine / "modern_ui").mkdir(parents=True)
        api = engine / "modern_ui/api.py"
        api.write_text(
            '''from pathlib import Path
APP_VERSION = "0.13.4-phase8-formatter-hotfix"

class Ctx:
    def __init__(self, active=True, fail=False):
        self.active = active
        self.fail = fail
        self.record_calls = 0
    def _daily_data_gate(self):
        return {"ready": True, "target_session": "2026-10-13", "blocked_reason": None}
    def _read_daily_state(self):
        return {"last_successful_run": {"market_session": "2026-10-13", "run_id": "RUN13"}}
    def post_close_daily_status(self):
        return {"run_status": "READY"}
    def phase81_paper_status(self):
        return {"active": self.active}
    def phase81_record_today(self):
        self.record_calls += 1
        if self.fail:
            raise RuntimeError("paper write failed")
        return {"event_id": "E1", "duplicate": self.record_calls > 1}
    def active_target_state(self):
        return {"explicit": False}
    def ensure_analysis_run(self, *args):
        raise AssertionError("duplicate path must not rerun analysis")
    def run_post_close_daily_flow(self, *, force: bool = False):
        gate = self._daily_data_gate()
        previous = self._read_daily_state()
        prior_success = previous.get("last_successful_run") or {}
        if not gate["ready"]:
            return {"ok": False}
        if prior_success.get("market_session") == gate["target_session"] and not force:
            return {**self.post_close_daily_status(), "ok": True, "run_status": "DUPLICATE_PROTECTED", "duplicate": True}
        raise AssertionError("unexpected path")
''',
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["SRE_ENGINE_ROOT"] = str(engine)
        subprocess.run(
            [sys.executable, str(ROOT / ".ci/native119/patch119_phase81_paper_journal_duplicate.py")],
            cwd=ROOT,
            env=env,
            check=True,
        )

        spec = importlib.util.spec_from_file_location("paperdup_api", api)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        active = mod.Ctx(active=True)
        r1 = active.run_post_close_daily_flow()
        r2 = active.run_post_close_daily_flow()

        inactive = mod.Ctx(active=False)
        r3 = inactive.run_post_close_daily_flow()

        failing = mod.Ctx(active=True, fail=True)
        r4 = failing.run_post_close_daily_flow()

        source = api.read_text(encoding="utf-8")
        cases = [
            ("version bumped", '0.13.5-phase8-paper-journal-hotfix' in source),
            ("duplicate path remains protected", r1["run_status"] == "DUPLICATE_PROTECTED" and r1["duplicate"] is True),
            ("active portfolio records observation", r1.get("paper_portfolio_observation", {}).get("event_id") == "E1"),
            ("repeat stays idempotent-capable", r2.get("paper_portfolio_observation", {}).get("duplicate") is True and active.record_calls == 2),
            ("inactive portfolio untouched", "paper_portfolio_observation" not in r3 and inactive.record_calls == 0),
            ("paper write failure visible but nonfatal", r4.get("paper_portfolio_observation", {}).get("status") == "ERROR"),
        ]
        for name, ok in cases:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        return 0 if all(ok for _, ok in cases) else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
