from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd
from .hashing import sha256_file

FILES=[
"prospective_universe.csv","results/stage4a3_frozen_universe.csv","results/stage4a3_frozen_universe_hash.json",
"results/stage4a3_model_bundle_manifest.json","results/stage4a3_model_reconstruction_audit.csv","results/stage4a3_2026_prediction_parity.csv",
"results/stage4a3_snapshot_schema.json","results/stage4a3_outcome_schema.json","results/stage4a3_hash_chain_spec.json",
"results/stage4a3_final_analysis_gate_spec.json","results/stage4a3_primary_hypothesis.json","results/stage4a3_protocol_identity.json",
"results/stage4a3_source_manifest.json","dry_run/snapshots/2025/2025-12-10/snapshot_metadata.json",
"dry_run/snapshots/2025/2025-12-10/candidate_predictions.csv.gz","dry_run/snapshots/2025/2025-12-10/feature_snapshot.csv.gz",
"dry_run/snapshots/2025/2025-12-10/snapshot_manifest.json","dry_run/snapshots/2025/2025-12-10/hash_chain.json",
"dry_run/audit/prospective_snapshot_index.csv",
]

def compare(a:Path,b:Path)->pd.DataFrame:
    rows=[]
    for relative in FILES:
        left=a/relative;right=b/relative;same=left.exists() and right.exists() and sha256_file(left)==sha256_file(right)
        rows.append({"Artifact":relative,"Build 1 SHA256":sha256_file(left) if left.exists() else "MISSING","Build 2 SHA256":sha256_file(right) if right.exists() else "MISSING","Behaviorally Meaningful Differences":0 if same else 1,"Status":"PASS" if same else "FAIL"})
    return pd.DataFrame(rows)

def main()->None:
    p=argparse.ArgumentParser();p.add_argument("--build-1",type=Path,required=True);p.add_argument("--build-2",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args();frame=compare(a.build_1,a.build_2);a.output.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(a.output,index=False,lineterminator="\n");print(frame["Status"].value_counts().to_dict());raise SystemExit(0 if frame["Status"].eq("PASS").all() else 1)
if __name__=="__main__":main()
