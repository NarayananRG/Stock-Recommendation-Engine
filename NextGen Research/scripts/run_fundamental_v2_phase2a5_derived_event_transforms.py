from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.derived_event_transforms import transform_all  # noqa: E402

PANEL=ROOT/"results"/"fundamental_v2_phase2a4_feature_panel"/"canonical_feature_panel.csv"
ELIG=ROOT/"results"/"fundamental_v2_phase2a5_event_feature_eligibility"/"eligibility_audit.json"
CONTRACT=ROOT/"fundamental_research_v2_phase2a"/"phase2a5_derived_event_feature_transform_contract_v1.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a5_derived_event_transforms"
OUT.mkdir(parents=True,exist_ok=True)


def main() -> int:
    for path,code in [
        (PANEL,"PHASE2A4_PANEL_MISSING"),
        (ELIG,"PHASE2A5_ELIGIBILITY_AUDIT_MISSING"),
        (CONTRACT,"PHASE2A5_TRANSFORM_CONTRACT_MISSING"),
    ]:
        if not path.exists():
            raise RuntimeError(code)

    with PANEL.open("r",encoding="utf-8",newline="") as handle:
        rows=list(csv.DictReader(handle))
    for row in rows:
        row["archive_gap"]=str(row.get("archive_gap") or "").lower() in {"true","1","yes"}

    elig=json.loads(ELIG.read_text(encoding="utf-8"))
    eligible_events=elig.get("eligible_events") or []
    if len(eligible_events)!=17402:
        raise RuntimeError(f"PHASE2A5_ELIGIBLE_EVENT_COUNT_MISMATCH:{len(eligible_events)}")

    events=transform_all(eligible_events,rows)
    if len(events)!=17402:
        raise RuntimeError(f"PHASE2A5_TRANSFORM_EVENT_COUNT_MISMATCH:{len(events)}")

    with (OUT/"derived_events.jsonl").open("w",encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event,sort_keys=True)+"\n")

    by_feature=Counter(x["feature"] for x in events)
    by_comparison=Counter(x["comparison"] for x in events)
    sign_transitions=Counter(x["sign_transition"] for x in events)
    directions=Counter(x["direction"] for x in events)

    summary={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A5_DERIVED_EVENT_TRANSFORM_SUMMARY_V1",
        "authority":"SHADOW_ONLY",
        "status":"DERIVED_EVENT_TRANSFORM_AUDIT_PASS",
        "derived_event_count":len(events),
        "feature_counts":dict(sorted(by_feature.items())),
        "comparison_counts":dict(sorted(by_comparison.items())),
        "direction_counts":dict(sorted(directions.items())),
        "sign_transition_counts":dict(sorted(sign_transitions.items())),
        "symmetric_change_formula_version":"SYMMETRIC_CHANGE_V1",
        "traditional_percent_change_created":False,
        "semantic_good_bad_label_created":False,
        "market_labels_created":False,
        "production_model_changed":False,
        "model_training_started":False,
        "next_gate":"PHASE2A5_DERIVED_EVENT_DISTRIBUTION_AND_SIGN_TRANSITION_REVIEW",
    }
    (OUT/"summary.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
