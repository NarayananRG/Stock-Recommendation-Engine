from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.canonical_feature_panel import (  # noqa: E402
    FEATURES,
    build_panel_rows,
    continuity_audit,
)

EVENTS=ROOT/"results"/"fundamental_v2_phase2a1_scaled"/"all_target_events.json"
PHASE3=ROOT/"results"/"fundamental_v2_phase2a3_scaled_mapping_validation"
CLOSURE=PHASE3/"phase2a3_closure_v1.json"
BY_DOC=PHASE3/"by_document"
OUT=ROOT/"results"/"fundamental_v2_phase2a4_feature_panel"
OUT.mkdir(parents=True,exist_ok=True)


def load_documents():
    docs=[]
    for path in sorted(BY_DOC.glob("*.json")):
        docs.append(json.loads(path.read_text(encoding="utf-8")))
    return docs


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        raise RuntimeError("PHASE2A4_PANEL_EMPTY")
    fields=[
        "symbol","quarter_end","reporting_basis","submission_type","event_id",
        "availability_ts","provider_seq_id","archive_gap","domain",
        "source_document_kind","retrieval_representation","source_content_sha256",
    ]
    for feature in FEATURES:
        fields.extend([
            f"{feature}__status",
            f"{feature}__concept",
            f"{feature}__value",
        ])
    with path.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if not EVENTS.exists():
        raise RuntimeError("PHASE2A1_EVENTS_MISSING")
    if not CLOSURE.exists():
        raise RuntimeError("PHASE2A3_CLOSURE_MISSING")

    closure=json.loads(CLOSURE.read_text(encoding="utf-8"))
    if not closure.get("phase2a3_closed"):
        raise RuntimeError("PHASE2A3_NOT_CLOSED")
    if closure.get("status")!="PASS_WITH_QUANTIFIED_OFFICIAL_ARCHIVE_GAPS":
        raise RuntimeError("PHASE2A3_CLOSURE_STATUS_NOT_ACCEPTED")
    if int(closure.get("semantic_hard_failure_count") or 0)!=0:
        raise RuntimeError("PHASE2A3_SEMANTIC_FAILURE_PRESENT")

    terminal={
        x.get("event_id") for x in closure.get("terminal_gaps",[])
        if x.get("event_id")
    }
    events=json.loads(EVENTS.read_text(encoding="utf-8"))
    docs=load_documents()
    rows=build_panel_rows(events,docs,terminal)

    if len(rows)!=2181:
        raise RuntimeError(f"PHASE2A4_ROW_COUNT_MISMATCH:{len(rows)}")
    archive_rows=sum(1 for x in rows if x.get("archive_gap"))
    if archive_rows!=10:
        raise RuntimeError(f"PHASE2A4_ARCHIVE_GAP_COUNT_MISMATCH:{archive_rows}")

    audit=continuity_audit(rows)
    write_csv(OUT/"canonical_feature_panel.csv",rows)
    with (OUT/"canonical_feature_panel.jsonl").open("w",encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row,sort_keys=True)+"\n")
    (OUT/"feature_continuity_audit.json").write_text(
        json.dumps(audit,indent=2,sort_keys=True),encoding="utf-8"
    )

    parsed_rows=len(rows)-archive_rows
    status={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A4_SUMMARY_V1",
        "authority":"SHADOW_ONLY",
        "status":"CANONICAL_FEATURE_PANEL_BUILT_CONTINUITY_AUDIT_COMPLETE",
        "panel_row_count":len(rows),
        "parsed_source_row_count":parsed_rows,
        "archive_gap_row_count":archive_rows,
        "history_count":audit["history_count"],
        "target_quarter_count":6,
        "reporting_bases":sorted({x["reporting_basis"] for x in rows}),
        "feature_count":len(FEATURES),
        "derived_growth_features_created":False,
        "production_model_changed":False,
        "model_training_started":False,
        "next_gate":"PHASE2A4_CONTINUITY_FINDINGS_REVIEW_THEN_EVENT_FEATURE_DESIGN",
    }
    (OUT/"summary.json").write_text(
        json.dumps(status,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps(status,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
