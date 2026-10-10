from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.canonical_mapping_audit import audit_documents  # noqa: E402

PILOT=ROOT/"results"/"fundamental_v2_phase2a2_pilot"
DOCS=PILOT/"documents"
OUT=PILOT/"canonical_mapping_audit"
OUT.mkdir(parents=True,exist_ok=True)


def main() -> int:
    paths=sorted(DOCS.glob("*.json"))
    if not paths:
        raise RuntimeError("PHASE2A2_PILOT_DOCUMENTS_MISSING")

    documents=[json.loads(p.read_text(encoding="utf-8")) for p in paths]
    audit=audit_documents(documents)

    (OUT/"canonical_mapping_audit.json").write_text(
        json.dumps(audit,indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"context_profile.json").write_text(
        json.dumps(audit["context_profile"],indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"feature_domain_coverage.json").write_text(
        json.dumps(audit["feature_domain_coverage"],indent=2,sort_keys=True),encoding="utf-8"
    )

    feature_summary={}
    for feature in sorted(next(iter(audit["per_document"]))["features"]):
        statuses=Counter(
            d["features"][feature]["status"] for d in audit["per_document"]
        )
        feature_summary[feature]=dict(statuses)

    ambiguous_examples=[]
    for doc in audit["per_document"]:
        for feature,info in doc["features"].items():
            if info["status"]=="AMBIGUOUS_MULTIPLE_CANDIDATES":
                ambiguous_examples.append({
                    "document_key":doc["document_key"],
                    "domain":doc["domain"],
                    "feature":feature,
                    "eligible_count":info["eligible_count"],
                    "eligible":[{
                        "concept_local_name":x["concept_local_name"],
                        "context_ref":x["context_ref"],
                        "period_kind":x["period_kind"],
                        "duration_bucket":x["duration_bucket"],
                        "raw_value":x["raw_value"],
                        "unit_measures":x["unit_measures"],
                    } for x in info["eligible"][:12]],
                })

    summary={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A2_CANONICAL_MAPPING_AUDIT_SUMMARY_V1",
        "authority":"SHADOW_ONLY",
        "document_count":audit["document_count"],
        "candidate_fact_count":audit["candidate_fact_count"],
        "status_counts":audit["status_counts"],
        "feature_status_summary":feature_summary,
        "feature_domain_coverage":audit["feature_domain_coverage"],
        "ambiguous_example_count":len(ambiguous_examples),
        "ambiguous_examples":ambiguous_examples[:30],
        "status":"CANONICAL_MAPPING_AUDIT_COMPLETE_NOT_YET_FROZEN",
        "production_model_changed":False,
        "model_training_started":False,
    }
    (OUT/"summary.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
