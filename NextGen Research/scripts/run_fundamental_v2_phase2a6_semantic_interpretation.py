from __future__ import annotations

import json
import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.semantic_interpretation import semantic_audit  # noqa: E402

EVENTS=ROOT/"results"/"fundamental_v2_phase2a5_derived_event_transforms"/"derived_events.jsonl"
DIST=ROOT/"results"/"fundamental_v2_phase2a5_derived_event_distribution_review"/"summary.json"
CONTRACT=ROOT/"fundamental_research_v2_phase2a"/"phase2a6_semantic_interpretation_contract_v1.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a6_semantic_interpretation"
OUT.mkdir(parents=True,exist_ok=True)


def main() -> int:
    for path,code in [
        (EVENTS,"PHASE2A5_DERIVED_EVENTS_MISSING"),
        (DIST,"PHASE2A5_DISTRIBUTION_REVIEW_MISSING"),
        (CONTRACT,"PHASE2A6_SEMANTIC_CONTRACT_MISSING"),
    ]:
        if not path.exists():
            raise RuntimeError(code)

    distribution=json.loads(DIST.read_text(encoding="utf-8"))
    if distribution.get("status")!="DERIVED_EVENT_DISTRIBUTION_REVIEW_COMPLETE":
        raise RuntimeError("PHASE2A5_DISTRIBUTION_REVIEW_NOT_COMPLETE")
    if int(distribution.get("derived_event_count") or 0)!=17253:
        raise RuntimeError("PHASE2A5_DERIVED_EVENT_COUNT_UNEXPECTED")

    with EVENTS.open("r",encoding="utf-8") as handle:
        events=[json.loads(line) for line in handle if line.strip()]
    if len(events)!=17253:
        raise RuntimeError(f"PHASE2A6_INPUT_EVENT_COUNT_MISMATCH:{len(events)}")

    audit=semantic_audit(events)
    if sum(audit["semantic_class_counts"].values())!=17253:
        raise RuntimeError("PHASE2A6_SEMANTIC_COUNT_MISMATCH")

    (OUT/"semantic_coverage_audit.json").write_text(
        json.dumps(audit,indent=2,sort_keys=True),encoding="utf-8"
    )

    summary={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A6_SEMANTIC_INTERPRETATION_SUMMARY_V1",
        "authority":"SHADOW_ONLY",
        "status":"PHASE2A6_SEMANTIC_COVERAGE_AUDIT_PASS",
        "derived_event_count":audit["derived_event_count"],
        "semantic_class_counts":audit["semantic_class_counts"],
        "feature_semantic_counts":audit["feature_semantic_counts"],
        "strong_sign_transition_counts":audit["strong_sign_transition_counts"],
        "trading_signal_created":False,
        "composite_score_created":False,
        "market_labels_created":False,
        "production_model_changed":False,
        "model_training_started":False,
        "next_gate":"PHASE2A7_DETERIORATION_RISK_EVENT_BUILDER",
    }
    (OUT/"summary.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
