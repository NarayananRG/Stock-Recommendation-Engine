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


def _run(cmd: list[str], env: dict[str, str]) -> None:
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def _write_seed_engine(root: Path) -> None:
    (root / "modern_ui/frontend").mkdir(parents=True)
    api = root / "modern_ui/api.py"
    api.write_text(
        r'''from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any

APP_VERSION = "0.12.1-phase6-target-hotfix"

def _finite(value):
    return None if value in (None, "") else float(value)

class Config:
    def __init__(self, app_data_dir: Path):
        self.app_data_dir = app_data_dir

class AppContext:
    def __init__(self, app_data_dir: Path, runs: dict[str, dict[str, Any]]):
        self.config = Config(app_data_dir)
        self.runs = runs
        self.active_analysis_file = self.config.app_data_dir / "active_analysis_run.json"
        self._phase6_run_selected_in_session = False

    def _saved_active_run_id(self) -> str | None:
        return self._active_run_metadata().get("run_id")

    def _prediction_run_by_id(self, run_id: str | None) -> dict[str, Any] | None:
        return self.runs.get(str(run_id or ""))

    def _active_run_metadata(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.active_analysis_file.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _set_active_run(
        self,
        run_id: str,
        *,
        target_explicit: bool | None = None,
        target_origin: str | None = None,
        selected_in_session: bool = False,
    ) -> dict[str, Any] | None:
        data = self._prediction_run_by_id(run_id)
        if not data:
            return None
        previous = self._active_run_metadata()
        payload = {"run_id": run_id, "updated_at": datetime.now().isoformat(timespec="seconds")}
        if previous.get("run_id") == run_id:
            for key in ("target_explicit", "target_origin"):
                if key in previous:
                    payload[key] = previous[key]
        if target_explicit is not None:
            payload["target_explicit"] = bool(target_explicit)
        if target_origin is not None:
            payload["target_origin"] = str(target_origin)
        self.active_analysis_file.parent.mkdir(parents=True, exist_ok=True)
        self.active_analysis_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if selected_in_session:
            self._phase6_run_selected_in_session = True
        return data

    def active_prediction_run(self) -> dict[str, Any] | None:
        return self._prediction_run_by_id(self._saved_active_run_id())

    def active_target_state(self) -> dict[str, Any]:
        active = self.active_prediction_run()
        run = {} if not active else dict(active.get("run") or {})
        raw_target = _finite(run.get("target_return"))
        meta = self._active_run_metadata()
        same_run = bool(run.get("run_id")) and str(meta.get("run_id") or "") == str(run.get("run_id") or "")
        explicit = bool(same_run and meta.get("target_explicit") is True and raw_target is not None)
        legacy_unconfirmed = bool(raw_target is not None and not explicit)
        restored = bool(explicit and not self._phase6_run_selected_in_session)
        if explicit:
            origin = "RESTORED_EXPLICIT_USER_TARGET" if restored else str(meta.get("target_origin") or "USER_SUPPLIED")
        elif legacy_unconfirmed:
            origin = "LEGACY_RESTORED_UNCONFIRMED"
        else:
            origin = "NONE"
        return {
            "explicit": explicit,
            "value": raw_target if explicit else None,
            "raw_persisted_value": raw_target,
            "origin": origin,
            "restored": restored,
            "legacy_unconfirmed": legacy_unconfirmed,
            "display_status": "EXPLICIT_TARGET" if explicit else "NO_TARGET",
        }

    def ui_run_input(self) -> dict[str, Any] | None:
        active = self.active_prediction_run()
        if not active:
            return None
        run = dict(active.get("run") or {})
        state = self.active_target_state()
        if not state["explicit"]:
            run["target_return"] = None
        run["target_explicit"] = state["explicit"]
        run["target_origin"] = state["origin"]
        run["target_restored"] = state["restored"]
        return run
''',
        encoding="utf-8",
    )
    (root / "modern_ui/frontend/app.js").write_text(
        "function decisionDisplayTitle(x){return x;}\n$('#heroSub').textContent=decisionDisplayTitle(hero.opportunity_status||'Ranked evidence')+' · '+(targetState.explicit?(hero.target_status||'NO TARGET'):'target not set');\n",
        encoding="utf-8",
    )


def _load_api(engine: Path):
    spec = importlib.util.spec_from_file_location("api", engine / "modern_ui/api.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def main() -> int:
    scratch = ROOT / "work"
    scratch.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="sre_phase7_state_", dir=scratch))
    try:
        engine = temp / "engine"
        _write_seed_engine(engine)
        env = os.environ.copy()
        env["SRE_ENGINE_ROOT"] = str(engine)
        _run([sys.executable, str(ROOT / ".ci/native109/patch109_first_launch_state.py")], env)

        api = _load_api(engine)
        app_data = temp / "appdata"
        app_data.mkdir()
        stale_run = "20261012T092526Z-2"
        runs = {stale_run: {"run": {"run_id": stale_run, "target_return": 0.05}}}
        (app_data / "active_analysis_run.json").write_text(
            json.dumps(
                {
                    "run_id": stale_run,
                    "target_explicit": True,
                    "target_origin": "USER_SUPPLIED",
                    "target_return": 0.05,
                    "app_version": "0.12.1-phase6-target-hotfix",
                }
            ),
            encoding="utf-8",
        )

        ctx = api.AppContext(app_data, runs)
        cases = [
            ("version", api.APP_VERSION == "0.12.2-phase7-first-launch-state-hotfix"),
            ("first launch active run reset", ctx.ui_run_input() is None),
            ("first launch target reset", ctx.active_target_state()["explicit"] is False and ctx.active_target_state()["value"] is None),
            ("marker written", json.loads((app_data / "current_ui_state_version.json").read_text(encoding="utf-8"))["app_version"] == api.APP_VERSION),
            ("hero target suffix suppressed", "target not set" not in (engine / "modern_ui/frontend/app.js").read_text(encoding="utf-8")),
        ]

        new_run = "20261012T120000Z-1"
        ctx.runs[new_run] = {"run": {"run_id": new_run, "target_return": 0.05}}
        ctx._set_active_run(new_run, target_explicit=True, target_origin="USER_SUPPLIED", selected_in_session=True)
        same_version = api.AppContext(app_data, ctx.runs)
        restored = same_version.active_target_state()
        cases.extend(
            [
                ("same-version run restored", same_version.ui_run_input()["run_id"] == new_run),
                ("same-version target restored", restored["explicit"] is True and abs(restored["value"] - 0.05) < 0.000001),
                ("same-version restored label", restored["restored"] is True),
            ]
        )

        for name, ok in cases:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        return 0 if all(ok for _, ok in cases) else 1
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
