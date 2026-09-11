from __future__ import annotations

import pandas as pd

from .hashing import canonical_json_hash


FORBIDDEN_FEATURE_NAMES={"Signal ID","Ticker","Signal Date","ENTRY_FILLED","T1_BEFORE_STOP_63","T2_BEFORE_STOP_63"}
FORBIDDEN_FEATURE_TOKENS=("AVAILABLE_DATE","RESOLUTION_DATE","SOURCE_DATE","FWD_","FUTURE_MFE","FUTURE_MAE","CENSORED","EXIT","LABEL_AVAILABLE")


def validate_feature_contract(feature_sets: dict[str,list[str]]) -> None:
    if len(feature_sets["FS2_RAW_SIGNAL_STATE"])!=92 or len(feature_sets["FS3_FULL_SIGNAL_STATE"])!=97:
        raise ValueError("Frozen FS2/FS3 feature counts changed")
    leaks=[]
    for name in feature_sets["FS3_FULL_SIGNAL_STATE"]:
        upper=name.upper().replace(" ","_").replace("-","_")
        if name in FORBIDDEN_FEATURE_NAMES or "DATE" in upper or any(token in upper for token in FORBIDDEN_FEATURE_TOKENS):
            leaks.append(name)
    if leaks:
        raise ValueError(f"Prohibited prospective features: {leaks}")


def feature_row_hash(row: pd.Series, feature_names: list[str]) -> str:
    return canonical_json_hash({name:row[name] for name in feature_names})


def add_feature_hashes(frame: pd.DataFrame, feature_names: list[str]) -> pd.DataFrame:
    output=frame.copy();output["Feature Row Hash"]=[feature_row_hash(row,feature_names) for _,row in output.iterrows()];return output
