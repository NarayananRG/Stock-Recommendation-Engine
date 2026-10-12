from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])


def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(label + " contract missing")
    return text.replace(old, new, 1)


api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")

old_version = 'APP_VERSION = "0.12.1-phase6-target-hotfix"'
new_version = 'APP_VERSION = "0.12.2-phase7-first-launch-state-hotfix"'
s = repl(s, old_version, new_version, "backend version")

anchor = '''        self.active_analysis_file = self.config.app_data_dir / "active_analysis_run.json"
        self._phase6_run_selected_in_session = False
'''
replacement = '''        self.active_analysis_file = self.config.app_data_dir / "active_analysis_run.json"
        self.ui_state_version_file = self.config.app_data_dir / "current_ui_state_version.json"
        self._phase6_run_selected_in_session = False
        self._ensure_current_ui_state_version()
'''
s = repl(s, anchor, replacement, "ui state marker init")

active_meta = '''    def _active_run_metadata(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.active_analysis_file.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

'''
version_helpers = '''    def _ui_state_version_payload(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.ui_state_version_file.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _ensure_current_ui_state_version(self) -> None:
        payload = self._ui_state_version_payload()
        if payload.get("app_version") == APP_VERSION:
            return
        previous = payload.get("app_version")
        self.config.app_data_dir.mkdir(parents=True, exist_ok=True)
        for path in (
            self.active_analysis_file,
            self.config.app_data_dir / "active_target_state.json",
            self.config.app_data_dir / "active_opportunity_run.json",
            self.config.app_data_dir / "transient_ui_run_state.json",
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        self.ui_state_version_file.write_text(
            json.dumps(
                {
                    "schema": "SRE_CURRENT_UI_STATE_VERSION_V1",
                    "app_version": APP_VERSION,
                    "previous_app_version": previous,
                    "active_selection_reset": True,
                    "historical_runs_preserved": True,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _active_run_metadata(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.active_analysis_file.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

'''
s = repl(s, active_meta, version_helpers, "ui state version helpers")

s = repl(
    s,
    '        payload = {"run_id": run_id, "updated_at": datetime.now().isoformat(timespec="seconds")}\n',
    '        payload = {"run_id": run_id, "app_version": APP_VERSION, "updated_at": datetime.now().isoformat(timespec="seconds")}\n',
    "active run version stamp",
)

s = repl(
    s,
    '''    def active_prediction_run(self) -> dict[str, Any] | None:
        return self._prediction_run_by_id(self._saved_active_run_id())

''',
    '''    def active_prediction_run(self) -> dict[str, Any] | None:
        meta = self._active_run_metadata()
        if meta.get("app_version") != APP_VERSION:
            return None
        return self._prediction_run_by_id(self._saved_active_run_id())

''',
    "active run version guard",
)

s = repl(
    s,
    '        explicit = bool(same_run and meta.get("target_explicit") is True and raw_target is not None)\n',
    '        explicit = bool(same_run and meta.get("app_version") == APP_VERSION and meta.get("target_explicit") is True and raw_target is not None)\n',
    "target version guard",
)

api.write_text(s, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
t = repl(
    t,
    "$('#heroSub').textContent=decisionDisplayTitle(hero.opportunity_status||'Ranked evidence')+' · '+(targetState.explicit?(hero.target_status||'NO TARGET'):'target not set');",
    "$('#heroSub').textContent=decisionDisplayTitle(hero.opportunity_status||'Ranked evidence')+(targetState.explicit?(' · '+(hero.target_status||'NO TARGET')):'');",
    "overview hero target suffix",
)
js.write_text(t, encoding="utf-8")

phase = root / "phase7"
phase.mkdir(parents=True, exist_ok=True)
(phase / "first_launch_state_hotfix_0122.json").write_text(
    """{
  "schema": "SRE_PHASE7_FIRST_LAUNCH_STATE_HOTFIX_0122",
  "release": "0.12.2-phase7-first-launch-state-hotfix",
  "versioned_ui_state_marker": "current_ui_state_version.json",
  "new_version_first_launch_active_run": null,
  "new_version_first_launch_target_explicit": false,
  "historical_runs_preserved": true,
  "production_recommendation_authority_changed": false,
  "production_rank_authority_changed": false,
  "technical_v2_authority_changed": false,
  "fundamental_v3_authority_changed": false,
  "combined_v2_authority_changed": false,
  "automatic_yfinance_fallback": false
}
""",
    encoding="utf-8",
)

check = api.read_text(encoding="utf-8")
assert 'APP_VERSION = "0.12.2-phase7-first-launch-state-hotfix"' in check
assert "current_ui_state_version.json" in check
assert 'meta.get("app_version") != APP_VERSION' in check
assert 'meta.get("app_version") == APP_VERSION' in check
assert "target not set" not in js.read_text(encoding="utf-8")
print("0.12.2 first-launch state hotfix applied")
