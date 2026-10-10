from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.validation import validate_pit_events  # noqa: E402

PILOT = ("M&M", "IRCTC", "NESTLEIND", "PATANJALI")
OUT = ROOT / "results" / "fundamental_v2_phase2a1_pilot"
EVENTS = OUT / "pilot_events.json"
REPORT = OUT / "pilot_pit_validation.json"


def main() -> int:
    if not EVENTS.exists():
        print(json.dumps({
            "status": "FAIL",
            "reason": "PILOT_EVENTS_NOT_FOUND",
            "path": str(EVENTS),
        }, indent=2))
        return 2

    events = json.loads(EVENTS.read_text(encoding="utf-8"))
    if not isinstance(events, list):
        print(json.dumps({"status": "FAIL", "reason": "PILOT_EVENTS_NOT_LIST"}, indent=2))
        return 3

    report = validate_pit_events(
        events,
        required_symbols=PILOT,
        require_all_target_quarters=True,
    )
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
