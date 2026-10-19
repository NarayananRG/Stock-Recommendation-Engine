"""Prefer the latest completed official daily run over an older restored UI selection.

Preserve explicit selections made in the current process. Never create a run,
change live BUY policy, manipulate paper ledgers, or promote stale data.
"""
from pathlib import Path
import os, ast

api=Path(os.environ["SRE_ENGINE_ROOT"])/"modern_ui"/"api.py"
src=api.read_text(encoding="utf-8")
begin=src.find("    def active_prediction_run(self)")
if begin<0: raise RuntimeError("GATE_A_ACTIVE_RUN_METHOD_MISSING")
end=src.find("\n    def ",begin+8)
if end<0: raise RuntimeError("GATE_A_ACTIVE_RUN_END_MISSING")
original=src[begin:end]
if "GATE_A_OFFICIAL_RUN_RECOVERY" in original: raise RuntimeError("GATE_A_RUN_RECOVERY_ALREADY_PRESENT")
if "self._saved_active_run_id()" not in original or "self._prediction_run_by_id(" not in original:
    raise RuntimeError("GATE_A_UNEXPECTED_ACTIVE_RUN_CONTRACT")
replacement='''    def active_prediction_run(self) -> dict[str, Any] | None:
        saved = self._prediction_run_by_id(self._saved_active_run_id())
        # GATE_A_OFFICIAL_RUN_RECOVERY: a restored selection must not silently
        # supersede a newer verified daily decision. Never override an explicit
        # selection made in this application session.
        if not getattr(self, "_phase6_run_selected_in_session", False):
            try:
                state = self._read_daily_state() or {}
                latest = state.get("last_successful_run") or {}
                last_id = str(latest.get("run_id") or "")
                last_session = str(latest.get("market_session") or latest.get("analysis_session") or "")
                old_session = str(((saved or {}).get("run") or {}).get("market_session") or "")
                compatible = latest.get("model_version") == APP_VERSION
                if (last_id and compatible and last_session and
                    (saved is None or (old_session and last_session > old_session))):
                    candidate = self._prediction_run_by_id(last_id)
                    if candidate and str((candidate.get("run") or {}).get("run_id") or "") == last_id:
                        if str((candidate.get("run") or {}).get("market_session") or "") == last_session:
                            selected = self._set_active_run(last_id, target_explicit=False,
                                                            target_origin="NONE")
                            if selected:
                                return selected
            except (OSError, ValueError, TypeError, AttributeError, KeyError):
                pass  # Retain the saved run; never manufacture a replacement.
        return saved
'''
out=src[:begin]+replacement+src[end:]
ast.parse(out)
api.write_text(out,encoding="utf-8")
assert "GATE_A_OFFICIAL_RUN_RECOVERY" in api.read_text(encoding="utf-8")
print("GATE_A_OFFICIAL_RUN_RECOVERY_PATCH_PASS")
