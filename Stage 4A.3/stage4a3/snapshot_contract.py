from __future__ import annotations

from typing import Any

import pandas as pd

from .hashing import canonical_json_hash, dataframe_content_hash


PREDICTION_COLUMNS = [
    "Protocol Version","Protocol Commit","Protocol Tag","Snapshot ID","Signal Date","Snapshot Created UTC","Snapshot Created Asia/Kolkata",
    "Signal ID","Ticker","Original Signal","Signal","Setup","Market Regime","Trade Quality","Actionability Score","Technical Score",
    "Planned Entry","Initial Stop","Original T1","Original T2","Dataset Cohort",
    *[item for code in range(6) for item in (f"R{code} Score",f"R{code} Same-Date Rank",f"R{code}_K1 Selected",f"R{code}_K2 Selected")],
    "Feature Row Hash","Model Bundle Hash","Prediction Semantics",
]

FORBIDDEN_OUTCOME_TOKENS = ("ENTRY_FILLED","T1_BEFORE","T2_BEFORE","NET R","NET PNL","EXIT PRICE","FUTURE","MFE","MAE","D1 OUTCOME")

SNAPSHOT_SCHEMA: dict[str, Any] = {
    "schema_version":"STAGE4A3_SNAPSHOT_V1",
    "required_files":["snapshot_metadata.json","candidate_predictions.csv.gz","feature_snapshot.csv.gz","market_data_manifest.json","snapshot_manifest.json","hash_chain.json"],
    "candidate_prediction_columns":PREDICTION_COLUMNS,
    "prediction_semantics":"SHADOW_ONLY_NO_TRADING_EFFECT",
    "forbidden_outcome_tokens":list(FORBIDDEN_OUTCOME_TOKENS),
    "immutability":"CREATE_ONCE_NO_OVERWRITE_NO_APPEND_NO_RESCORE",
}


def validate_candidate_predictions(frame: pd.DataFrame) -> None:
    missing=[column for column in PREDICTION_COLUMNS if column not in frame]
    extras=[column for column in frame if any(token in column.upper() for token in FORBIDDEN_OUTCOME_TOKENS)]
    if missing:
        raise ValueError(f"Missing prediction columns: {missing}")
    if extras:
        raise ValueError(f"Future/outcome columns prohibited: {extras}")
    if not frame["Prediction Semantics"].eq("SHADOW_ONLY_NO_TRADING_EFFECT").all():
        raise ValueError("Prediction semantics mismatch")
    score_columns=[f"R{code} Score" for code in range(6)]
    if frame[score_columns].isna().any().any():
        raise ValueError("Missing scores may not be imputed")


def snapshot_content_hash(metadata: dict[str, Any], predictions: pd.DataFrame, features: pd.DataFrame, market_manifest: dict[str, Any]) -> str:
    return canonical_json_hash({"metadata":metadata,"prediction_hash":dataframe_content_hash(predictions),"feature_hash":dataframe_content_hash(features),"market_manifest":market_manifest})
