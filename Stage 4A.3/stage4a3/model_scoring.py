from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd

from .hashing import canonical_json_hash, sha256_file


def verify_bundle(model_dir: Path) -> dict:
    manifest=json.loads((model_dir/"model_bundle_manifest.json").read_text(encoding="utf-8"))
    payload={key:value for key,value in manifest.items() if key!="FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"}
    if canonical_json_hash(payload)!=manifest["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]:
        raise RuntimeError("MODEL_BUNDLE_DRIFT")
    expected={item["model_name"]:item for item in manifest["models"]}
    if len(expected)!=7:
        raise RuntimeError("MODEL_BUNDLE_COMPONENT_COUNT_MISMATCH")
    for name,item in expected.items():
        if sha256_file(model_dir/f"{name}.joblib")!=item["serialized_model_sha256"]:
            raise RuntimeError(f"MODEL_BUNDLE_DRIFT: {name}")
    return manifest


def score_candidates(features: pd.DataFrame, model_dir: Path) -> tuple[pd.DataFrame,str]:
    manifest=verify_bundle(model_dir);scores={}
    for item in manifest["models"]:
        bundle=joblib.load(model_dir/f"{item['model_name']}.joblib")
        names=bundle["feature_names"]
        if any(name not in features for name in names):
            raise ValueError(f"Missing frozen features for {item['model_name']}")
        transformed=bundle["preprocessor"].transform(features[names])
        scores[item["model_name"]]=bundle["estimator"].predict_proba(transformed)[:,1]
    output=pd.DataFrame(index=features.index)
    output["R1 Score"]=scores["PRIMARY_ONLY_T1_LOGIT_FULL"]
    output["R2 Score"]=scores["PRIMARY_ONLY_T1_LOGIT_RAW"]
    output["R3 Score"]=scores["TRANSFER_ENTRY_LOGIT_FULL"]*scores["TRANSFER_T1_LOGIT_FULL"]
    output["R4 Score"]=scores["TRANSFER_ENTRY_LOGIT_RAW"]*scores["TRANSFER_T1_LOGIT_RAW"]
    output["R5 Score"]=scores["TRANSFER_ENTRY_RF_FULL"]
    return output,manifest["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]
