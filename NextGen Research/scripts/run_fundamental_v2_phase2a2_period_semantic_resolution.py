from __future__ import annotations

import json
import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))

from fundamental_research_v2_phase2a.period_semantic_resolution import resolve_documents  # noqa: E402

PILOT=ROOT/"results"/"fundamental_v2_phase2a2_pilot"
DOCS=PILOT/"documents"
OUT=PILOT/"period_semantic_resolution"
OUT.mkdir(parents=True,exist_ok=True)


def main() -> int:
    paths=sorted(DOCS.glob("*.json"))
    if not paths:
        raise RuntimeError("PHASE2A2_PILOT_DOCUMENTS_MISSING")

    documents=[json.loads(p.read_text(encoding="utf-8")) for p in paths]
    audit=resolve_documents(documents)

    (OUT/"period_semantic_resolution.json").write_text(
        json.dumps(audit,indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"freeze_candidates.json").write_text(
        json.dumps(audit["freeze_candidates"],indent=2,sort_keys=True),encoding="utf-8"
    )
    (OUT/"blocked_domain_features.json").write_text(
        json.dumps(audit["blocked_domain_features"],indent=2,sort_keys=True),encoding="utf-8"
    )

    unresolved=[]
    for doc in audit["per_document"]:
        for feature,info in doc["features"].items():
            if info["status"] in {
                "AMBIGUOUS_WITHIN_PREFERRED_CONCEPT",
                "NO_PRIORITY_CONCEPT_PRESENT",
            }:
                unresolved.append({
                    "document_key":doc["document_key"],
                    "domain":doc["domain"],
                    "feature":feature,
                    "status":info["status"],
                    "evidence":info["evidence"][:12],
                })

    summary={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A2_PERIOD_SEMANTIC_RESOLUTION_SUMMARY_V1",
        "authority":"SHADOW_ONLY",
        "document_count":audit["document_count"],
        "status_counts":audit["status_counts"],
        "freeze_candidate_count":len(audit["freeze_candidates"]),
        "freeze_candidates":audit["freeze_candidates"],
        "blocked_domain_feature_count":len(audit["blocked_domain_features"]),
        "blocked_domain_features":audit["blocked_domain_features"],
        "unresolved_example_count":len(unresolved),
        "unresolved_examples":unresolved[:30],
        "mapping_frozen":False,
        "production_model_changed":False,
        "model_training_started":False,
        "status":"PERIOD_SEMANTIC_RESOLUTION_COMPLETE_MAPPING_NOT_FROZEN",
    }
    (OUT/"summary.json").write_text(
        json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"
    )
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
