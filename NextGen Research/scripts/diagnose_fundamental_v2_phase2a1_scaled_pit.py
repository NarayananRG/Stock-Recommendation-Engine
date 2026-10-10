from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

OUT = ROOT / "results" / "fundamental_v2_phase2a1_scaled"
VALIDATION = OUT / "scaled_pit_validation.json"
EVENTS = OUT / "all_target_events.json"
REPORT = OUT / "scaled_pit_failure_diagnostic.json"


def main() -> int:
    if not VALIDATION.exists() or not EVENTS.exists():
        print(json.dumps({
            "status":"FAIL",
            "reason":"SCALED_RESULTS_MISSING",
            "validation_path":str(VALIDATION),
            "events_path":str(EVENTS),
        }, indent=2))
        return 2

    validation=json.loads(VALIDATION.read_text(encoding="utf-8"))
    events=json.loads(EVENTS.read_text(encoding="utf-8"))
    failures=validation.get("failures") or []

    by_id={e.get("event_id"):e for e in events if e.get("event_id")}
    implicated=[]

    for failure in failures:
        row=dict(failure)
        eid=row.get("event_id")
        if eid and eid in by_id:
            row["event"]=by_id[eid]
        else:
            symbol=row.get("symbol")
            quarter=row.get("quarter_end") or row.get("current_quarter") or row.get("prior_quarter")
            basis=row.get("basis")
            related=[
                e for e in events
                if (not symbol or e.get("symbol")==symbol)
                and (not quarter or e.get("quarter_end")==quarter)
                and (not basis or e.get("reporting_basis")==basis)
            ]
            row["related_events"]=related
        implicated.append(row)

    summary={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A1_SCALED_PIT_FAILURE_DIAGNOSTIC_V1",
        "validation_status":validation.get("status"),
        "failure_count":len(failures),
        "failure_codes":dict(Counter(x.get("code","UNKNOWN") for x in failures)),
        "implicated":implicated,
        "authority":"SHADOW_ONLY",
        "production_model_changed":False,
        "model_training_started":False,
    }

    REPORT.write_text(json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
