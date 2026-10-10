from __future__ import annotations

import json
import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.derived_event_distribution_review import review_distributions  # noqa: E402

EVENTS=ROOT/"results"/"fundamental_v2_phase2a5_derived_event_transforms"/"derived_events.jsonl"
ELIG=ROOT/"results"/"fundamental_v2_phase2a5_event_feature_eligibility"/"eligibility_audit.json"
TRANSFORM_SUMMARY=ROOT/"results"/"fundamental_v2_phase2a5_derived_event_transforms"/"summary.json"
CONTRACT=ROOT/"fundamental_research_v2_phase2a"/"phase2a5_derived_event_distribution_review_contract_v1.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a5_derived_event_distribution_review"
OUT.mkdir(parents=True,exist_ok=True)


def main() -> int:
    for path,code in [
        (EVENTS,"PHASE2A5_DERIVED_EVENTS_MISSING"),
        (ELIG,"PHASE2A5_ELIGIBILITY_AUDIT_MISSING"),
        (TRANSFORM_SUMMARY,"PHASE2A5_TRANSFORM_SUMMARY_MISSING"),
        (CONTRACT,"PHASE2A5_DISTRIBUTION_REVIEW_CONTRACT_MISSING"),
    ]:
        if not path.exists():
            raise RuntimeError(code)

    transform_summary=json.loads(TRANSFORM_SUMMARY.read_text(encoding="utf-8"))
    if transform_summary.get("status")!="DERIVED_EVENT_TRANSFORM_AUDIT_PASS":
        raise RuntimeError("PHASE2A5_TRANSFORM_NOT_CLOSED")

    eligibility=json.loads(ELIG.read_text(encoding="utf-8"))
    with EVENTS.open("r",encoding="utf-8") as handle:
        events=[json.loads(line) for line in handle if line.strip()]

    review=review_distributions(events,eligibility)
    if review["pre_pit_candidate_count"]!=17402:
        raise RuntimeError("PHASE2A5_REVIEW_PRE_PIT_COUNT_MISMATCH")
    if review["pit_order_rejection_count"]!=149:
        raise RuntimeError(
            f"PHASE2A5_REVIEW_PIT_REJECTION_COUNT_MISMATCH:{review['pit_order_rejection_count']}"
        )
    if review["derived_event_count"]!=17253:
        raise RuntimeError(
            f"PHASE2A5_REVIEW_DERIVED_COUNT_MISMATCH:{review['derived_event_count']}"
        )

    (OUT/"distribution_review.json").write_text(
        json.dumps(review,indent=2,sort_keys=True),encoding="utf-8"
    )

    summary={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A5_DERIVED_EVENT_DISTRIBUTION_REVIEW_SUMMARY_V1",
        "authority":"SHADOW_ONLY",
        "status":"DERIVED_EVENT_DISTRIBUTION_REVIEW_COMPLETE",
        "derived_event_count":review["derived_event_count"],
        "pre_pit_candidate_count":review["pre_pit_candidate_count"],
        "pit_order_rejection_count":review["pit_order_rejection_count"],
        "feature_summary":review["feature_summary"],
        "pit_order_rejection_summary":review["pit_order_rejection_summary"],
        "absolute_delta_cross_company_distribution_created":False,
        "semantic_good_bad_label_created":False,
        "market_labels_created":False,
        "production_model_changed":False,
        "model_training_started":False,
        "next_gate":"PHASE2A5_EVENT_SEMANTIC_INTERPRETATION_CONTRACT",
    }
    (OUT/"summary.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
