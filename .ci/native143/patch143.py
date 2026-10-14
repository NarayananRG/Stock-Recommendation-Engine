from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

def edit(relative: str, old: str, new: str, label: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8-sig")
    if old not in text:
        raise RuntimeError(f"{label}: missing patch point {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Release identity only. Qualification, ranking, thresholds and provider routing are unchanged.
edit(
    "modern_ui/api.py",
    'APP_VERSION = "0.14.2-session-truth-ux-repair"',
    'APP_VERSION = "0.14.3-decision-clarity-ux"',
    "backend version",
)
edit(
    "stock_app/live_decision_v1.py",
    'MODEL = "0.14.2-session-truth-ux-repair"',
    'MODEL = "0.14.3-decision-clarity-ux"',
    "live decision release identity",
)
print("0.14.3 release identity applied")
