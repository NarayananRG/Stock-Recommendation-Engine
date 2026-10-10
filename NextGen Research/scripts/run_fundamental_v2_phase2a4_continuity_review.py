from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.continuity_findings_review import review_continuity  # noqa: E402

PANEL=ROOT/"results"/"fundamental_v2_phase2a4_feature_panel"/"canonical_feature_panel.csv"
SUMMARY=ROOT/"results"/"fundamental_v2_phase2a4_feature_panel"/"summary.json"
OUT=ROOT/"results"/"fundamental_v2_phase2a4_continuity_review"
OUT.mkdir(parents=True,exist_ok=True)


def main() -> int:
    if not PANEL.exists():
        raise RuntimeError("PHASE2A4_PANEL_MISSING")
    if not SUMMARY.exists():
        raise RuntimeError("PHASE2A4_SUMMARY_MISSING")

    base=json.loads(SUMMARY.read_text(encoding="utf-8"))
    if base.get("status")!="CANONICAL_FEATURE_PANEL_BUILT_CONTINUITY_AUDIT_COMPLETE":
        raise RuntimeError("PHASE2A4_PANEL_NOT_COMPLETE")

    with PANEL.open("r",encoding="utf-8",newline="") as handle:
        rows=list(csv.DictReader(handle))
    for row in rows:
        row["archive_gap"]=str(row.get("archive_gap") or "").lower() in {"true","1","yes"}

    review=review_continuity(rows)
    if review["panel_row_count"]!=2181:
        raise RuntimeError(f"PHASE2A4_REVIEW_ROW_COUNT_MISMATCH:{review['panel_row_count']}")

    (OUT/"continuity_findings_review.json").write_text(
        json.dumps(review,indent=2,sort_keys=True),encoding="utf-8"
    )

    compact={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A4_CONTINUITY_FINDINGS_SUMMARY_V1",
        "authority":"SHADOW_ONLY",
        "status":"CONTINUITY_FINDINGS_READY_FOR_EVENT_FEATURE_DESIGN_REVIEW",
        "panel_row_count":review["panel_row_count"],
        "history_count":review["history_count"],
        "overall_feature_continuity":review["overall_feature_continuity"],
        "basis_feature_continuity":review["basis_feature_continuity"],
        "quarter_feature_continuity":review["quarter_feature_continuity"],
        "derived_growth_features_created":False,
        "production_model_changed":False,
        "model_training_started":False,
        "next_gate":"PHASE2A5_EVENT_FEATURE_DESIGN_CONTRACT",
    }
    (OUT/"summary.json").write_text(
        json.dumps(compact,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps(compact,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
