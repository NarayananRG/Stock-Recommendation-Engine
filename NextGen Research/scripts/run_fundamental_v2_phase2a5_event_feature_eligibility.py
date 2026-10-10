from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.event_feature_eligibility import eligibility_audit  # noqa: E402

PANEL=ROOT/"results"/"fundamental_v2_phase2a4_feature_panel"/"canonical_feature_panel.csv"
CONT=ROOT/"results"/"fundamental_v2_phase2a4_continuity_review"/"summary.json"
CONTRACT=ROOT/"fundamental_research_v2_phase2a"/"phase2a5_event_feature_design_contract_v1.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a5_event_feature_eligibility"
OUT.mkdir(parents=True,exist_ok=True)


def main() -> int:
    for path,code in [
        (PANEL,"PHASE2A4_PANEL_MISSING"),
        (CONT,"PHASE2A4_CONTINUITY_REVIEW_MISSING"),
        (CONTRACT,"PHASE2A5_CONTRACT_MISSING"),
    ]:
        if not path.exists():
            raise RuntimeError(code)

    continuity=json.loads(CONT.read_text(encoding="utf-8"))
    if continuity.get("status")!="CONTINUITY_FINDINGS_READY_FOR_EVENT_FEATURE_DESIGN_REVIEW":
        raise RuntimeError("PHASE2A4_CONTINUITY_NOT_READY")

    with PANEL.open("r",encoding="utf-8",newline="") as handle:
        rows=list(csv.DictReader(handle))
    for row in rows:
        row["archive_gap"]=str(row.get("archive_gap") or "").lower() in {"true","1","yes"}

    audit=eligibility_audit(rows)
    if audit["panel_row_count"]!=2181:
        raise RuntimeError(f"PHASE2A5_PANEL_ROW_COUNT_MISMATCH:{audit['panel_row_count']}")

    (OUT/"eligibility_audit.json").write_text(
        json.dumps(audit,indent=2,sort_keys=True),encoding="utf-8"
    )
    summary={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A5_EVENT_FEATURE_ELIGIBILITY_SUMMARY_V1",
        "authority":"SHADOW_ONLY",
        "status":"EVENT_FEATURE_ELIGIBILITY_AUDIT_PASS",
        "panel_row_count":audit["panel_row_count"],
        "history_count":audit["history_count"],
        "feature_policy_count":audit["feature_policy_count"],
        "pre_pit_candidate_count":audit["pre_pit_candidate_count"],
        "pit_order_rejection_count":audit["pit_order_rejection_count"],
        "eligible_event_count":audit["eligible_event_count"],
        "feature_eligibility":audit["feature_eligibility"],
        "derived_feature_values_created":False,
        "production_model_changed":False,
        "model_training_started":False,
        "next_gate":"PHASE2A5_DERIVED_EVENT_FEATURE_TRANSFORM_CONTRACT",
    }
    (OUT/"summary.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
