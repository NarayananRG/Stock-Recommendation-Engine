from __future__ import annotations

import json
import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.ambiguity_resolution import audit_ambiguities  # noqa: E402

PILOT=ROOT/"results"/"fundamental_v2_phase2a2_pilot"
DOCS=PILOT/"documents"
OUT=PILOT/"ambiguity_resolution"
OUT.mkdir(parents=True,exist_ok=True)


def main() -> int:
    paths=sorted(DOCS.glob("*.json"))
    if not paths:
        raise RuntimeError("PHASE2A2_PILOT_DOCUMENTS_MISSING")

    documents=[json.loads(p.read_text(encoding="utf-8")) for p in paths]
    audit=audit_ambiguities(documents)

    (OUT/"ambiguity_resolution_audit.json").write_text(
        json.dumps(audit,indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"domain_feature_summary.json").write_text(
        json.dumps(audit["domain_feature_summary"],indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"freeze_candidates.json").write_text(
        json.dumps(audit["freeze_candidates"],indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"blocked_domain_features.json").write_text(
        json.dumps(audit["blocked_domain_features"],indent=2,sort_keys=True),encoding="utf-8"
    )

    genuine_examples=[]
    for doc in audit["per_document"]:
        for feature,info in doc["features"].items():
            if info["status"]=="GENUINE_AMBIGUITY":
                genuine_examples.append({
                    "document_key":doc["document_key"],
                    "feature":feature,
                    "reason_codes":info["reason_codes"],
                    "eligible":info["eligible"][:20],
                })

    summary={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A2_AMBIGUITY_RESOLUTION_SUMMARY_V1",
        "authority":"SHADOW_ONLY",
        "document_count":audit["document_count"],
        "status_counts":audit["status_counts"],
        "reason_counts":audit["reason_counts"],
        "freeze_candidate_count":len(audit["freeze_candidates"]),
        "freeze_candidates":audit["freeze_candidates"],
        "blocked_domain_feature_count":len(audit["blocked_domain_features"]),
        "blocked_domain_features":audit["blocked_domain_features"],
        "genuine_ambiguity_example_count":len(genuine_examples),
        "genuine_ambiguity_examples":genuine_examples[:30],
        "mapping_frozen":False,
        "production_model_changed":False,
        "model_training_started":False,
        "status":"AMBIGUITY_AUDIT_COMPLETE_MAPPING_NOT_FROZEN",
    }
    (OUT/"summary.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
