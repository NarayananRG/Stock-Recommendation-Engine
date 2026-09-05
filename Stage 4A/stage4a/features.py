"""Registry-derived, pre-registered Stage 4A feature sets."""
from __future__ import annotations

from typing import Any

import pandas as pd

from hashing import canonical_json_hash


RULE_GROUP = "RULE_ENGINE_DERIVED_FEATURES"
FEATURE_SET_ORDER = ["FS1_RULE_SUMMARY", "FS2_RAW_SIGNAL_STATE", "FS3_FULL_SIGNAL_STATE"]


def _truthy(series: pd.Series) -> pd.Series:
    return series.astype("string").str.upper().isin(["TRUE", "1", "YES"])


def leakage_feature_names(features: list[str]) -> list[str]:
    explicit = {
        "Signal ID", "STAGE3_ROW_ID", "STAGE3_1_ROW_ID", "Ticker", "Signal Date",
        "Feature As-Of Date", "Entry Date", "ENTRY_FILLED", "ENTRY_DATE",
        "ENTRY_SESSIONS_TO_FILL", "ENTRY_STATUS", "T1_BEFORE_STOP_63",
        "T2_BEFORE_STOP_63", "STOP_BEFORE_T1_63", "STOP_BEFORE_T2_63",
        "TIME_TO_T1", "TIME_TO_T2", "D1_SHADOW", "D1_FINAL", "D1_REMAINING",
    }
    forbidden_tokens = (
        "AVAILABLE_DATE", "RESOLUTION_DATE", "SOURCE_DATE", "FWD_", "FUTURE_MFE",
        "FUTURE_MAE", "CENSORED", "STATUS", "EXIT", "LABEL_AVAILABLE",
    )
    leaks = []
    for name in features:
        upper = name.upper().replace(" ", "_").replace("-", "_")
        if name in explicit or "DATE" in upper or any(token in upper for token in forbidden_tokens):
            leaks.append(name)
    return sorted(set(leaks))


def build_feature_contract(
    feature_registry: pd.DataFrame,
    ml_registry: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[dict[str, list[str]], pd.DataFrame, dict[str, str], dict[str, dict[str, list[str]]]]:
    ml_allowed = ml_registry.loc[
        ml_registry["Dataset"].eq("trade_opportunity") & ml_registry["Role"].eq("FEATURE_ALLOWED"),
        "Column",
    ].astype(str).tolist()
    registry_allowed_frame = feature_registry.loc[
        feature_registry["Dataset"].eq("trade_opportunity") & _truthy(feature_registry["ML Allowed"])
    ].copy()
    registry_allowed = registry_allowed_frame["Feature Name"].astype(str).tolist()
    if len(ml_allowed) != len(set(ml_allowed)) or len(registry_allowed) != len(set(registry_allowed)):
        raise ValueError("Duplicate FEATURE_ALLOWED entries are prohibited")
    if set(ml_allowed) != set(registry_allowed):
        missing_ml = sorted(set(registry_allowed) - set(ml_allowed))
        missing_feature = sorted(set(ml_allowed) - set(registry_allowed))
        raise ValueError(f"Feature registry mismatch; missing_ml={missing_ml}, missing_feature={missing_feature}")
    all_features = sorted(ml_allowed)
    leaks = leakage_feature_names(all_features)
    if leaks:
        raise ValueError(f"Leakage fields in model features: {leaks}")

    registry_allowed_frame = registry_allowed_frame.set_index("Feature Name", drop=False)
    rule_features = sorted(
        name for name in all_features
        if registry_allowed_frame.loc[name, "Feature Group"] == RULE_GROUP
    )
    raw_features = sorted(name for name in all_features if name not in rule_features)
    feature_sets = {
        "FS1_RULE_SUMMARY": rule_features,
        "FS2_RAW_SIGNAL_STATE": raw_features,
        "FS3_FULL_SIGNAL_STATE": all_features,
    }
    if not rule_features or set(rule_features) & set(raw_features) or set(rule_features) | set(raw_features) != set(all_features):
        raise ValueError("Pre-registered feature set partition is invalid")

    rows: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    type_map: dict[str, dict[str, list[str]]] = {}
    for feature_set in FEATURE_SET_ORDER:
        names = feature_sets[feature_set]
        hash_rows = []
        numeric, categorical = [], []
        for name in names:
            source_row = registry_allowed_frame.loc[name]
            row_payload = {column: source_row[column] for column in feature_registry.columns}
            registry_row_hash = canonical_json_hash(row_payload)
            hash_rows.append(row_payload)
            data_type = str(source_row["Data Type"])
            if data_type.lower().startswith(("int", "float")):
                numeric.append(name)
            else:
                categorical.append(name)
            rows.append({
                "Feature Set": feature_set,
                "Feature Name": name,
                "Feature Group": source_row["Feature Group"],
                "Data Type": data_type,
                "Source": source_row["Source"],
                "As-Of Semantics": source_row["As-Of Semantics"],
                "Feature Registry Hash": registry_row_hash,
            })
        payload = {
            "dataset": "trade_opportunity",
            "feature_set": feature_set,
            "definition": config["feature_sets"][feature_set]["definition"],
            "dataset_qualified_features": [f"trade_opportunity::{name}" for name in sorted(names)],
            "feature_registry_rows": sorted(hash_rows, key=lambda value: value["Feature Name"]),
        }
        hashes[feature_set] = canonical_json_hash(payload)
        type_map[feature_set] = {"numeric": numeric, "categorical": categorical}
    return feature_sets, pd.DataFrame(rows), hashes, type_map
