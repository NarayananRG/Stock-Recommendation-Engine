"""Dataset-specific feature registry and hard date-leakage controls."""
from __future__ import annotations

import re
from typing import Any, Mapping

import pandas as pd


IDENTIFIER_COLUMNS = {
    "Signal ID", "Ticker", "Signal Date", "Entry Date", "Management Date",
    "Feature As-Of Date", "Source Experiment ID", "Stage 3 Experiment ID",
    "Stage 3.1 Experiment ID", "STAGE3_ROW_ID", "STAGE3_1_ROW_ID",
    "Dataset Cohort", "Experiment ID",
}

TARGET_PREFIXES = (
    "FWD_", "FWD_CLOSE_RETURN_", "MFE_R_", "MAE_R_", "MFE_PCT_", "MAE_PCT_",
    "TIME_TO_", "D1_REMAINING_", "NEXT_", "T1_", "T2_", "STOP_",
)

TARGET_EXACT = {
    "ENTRY_FILLED", "ENTRY_SESSIONS_TO_FILL", "D1_EXIT_NEXT_SESSION",
    "D1_FINAL_EXIT_REASON", "ORIGINAL_T2_REACHED_BEFORE_D1_EXIT",
}


def is_date_like(column: str, series: pd.Series) -> bool:
    name = str(column)
    lowered = name.lower()
    numeric_to_date_metric = lowered.endswith(" to date") and pd.api.types.is_numeric_dtype(series.dtype)
    named_date = not numeric_to_date_metric and (
        lowered.endswith(" date")
        or lowered.endswith("_date")
        or "source date" in lowered
        or "available date" in lowered
        or "availability date" in lowered
        or "resolution date" in lowered
    )
    dtype_date = pd.api.types.is_datetime64_any_dtype(series.dtype)
    return bool(named_date or dtype_date)


def normalize_date_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        lowered = str(column).lower()
        numeric_to_date_metric = lowered.endswith(" to date") and pd.api.types.is_numeric_dtype(result[column].dtype)
        named_date = not numeric_to_date_metric and (
            lowered.endswith(" date")
            or lowered.endswith("_date")
            or "source date" in lowered
            or "available date" in lowered
            or "availability date" in lowered
            or "resolution date" in lowered
        )
        if named_date:
            result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    return result


def feature_registry(
    datasets: Mapping[str, pd.DataFrame],
    stage3_registry: pd.DataFrame,
) -> pd.DataFrame:
    base = stage3_registry.drop_duplicates("Feature Name").set_index("Feature Name", drop=False)
    rows: list[dict[str, Any]] = []
    for dataset, frame in datasets.items():
        for feature_name, source_row in base.iterrows():
            if feature_name not in frame.columns:
                continue
            source = source_row.to_dict()
            date_like = is_date_like(feature_name, frame[feature_name])
            allowed = bool(source.get("ML Allowed", False)) and not date_like
            semantics = (
                "COMPLETED MANAGEMENT SESSION CLOSE"
                if dataset == "d1_position_day"
                else "SIGNAL SESSION CLOSE"
            )
            if date_like:
                reason = "RAW CALENDAR OR SOURCE-LINEAGE DATE; AUDIT METADATA ONLY"
            else:
                reason = "" if allowed else str(source.get("Reason if ML Disallowed", "") or "NOT PRE-REGISTERED AS ML INPUT")
            rows.append(
                {
                    "Dataset": dataset,
                    "Feature Name": feature_name,
                    "Feature Group": source.get("Feature Group", "UNCLASSIFIED"),
                    "Data Type": str(frame[feature_name].dtype),
                    "Source": source.get("Source", ""),
                    "Formula / Description": source.get("Formula / Description", ""),
                    "As-Of Semantics": semantics,
                    "Point-In-Time Safe": bool(source.get("Point-In-Time Safe", False)),
                    "ML Allowed": allowed,
                    "Reason if ML Disallowed": reason,
                    "Missing Value Meaning": source.get("Missing Value Meaning", ""),
                    "Known Ambiguity": source.get("Known Ambiguity", ""),
                    "Stage Source": source.get("Stage Source", ""),
                }
            )
    result = pd.DataFrame(rows)
    if result.duplicated(["Dataset", "Feature Name"]).any():
        raise RuntimeError("Feature registry composite key is not unique")
    return result.sort_values(["Dataset", "Feature Name"]).reset_index(drop=True)


def _is_label_metadata(column: str) -> bool:
    upper = column.upper()
    return any(
        marker in upper
        for marker in (
            "AVAILABLE_DATE", "APPLICABLE", "STATUS", "CENSORED",
            "UNAVAILABLE_REASON", "SEMANTICS", "AMBIGUOUS", "RESOLUTION_DATE",
        )
    )


def _is_target(column: str, label_names: set[tuple[str, str]], dataset: str) -> bool:
    return (
        (dataset, column) in label_names
        or column.startswith(TARGET_PREFIXES)
        or column in TARGET_EXACT
    )


def ml_column_registry(
    datasets: Mapping[str, pd.DataFrame],
    registry: pd.DataFrame,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    allowed = {
        (str(row["Dataset"]), str(row["Feature Name"]))
        for _, row in registry.loc[registry["ML Allowed"].fillna(False).astype(bool)].iterrows()
    }
    label_names = {(str(row["Dataset"]), str(row["Label Name"])) for _, row in labels.iterrows()}
    rows: list[dict[str, str]] = []
    for dataset, frame in datasets.items():
        for column in frame.columns:
            if column in IDENTIFIER_COLUMNS or column.endswith("ROW_ID"):
                role = "IDENTIFIER"
            elif is_date_like(column, frame[column]):
                role = "LABEL_METADATA" if _is_label_metadata(column) else "LEAKAGE_EXCLUDE"
            elif _is_label_metadata(column):
                role = "LABEL_METADATA"
            elif _is_target(column, label_names, dataset):
                role = "TARGET"
            elif column.startswith(("Candidate ", "BASELINE_COMPAT_", "D1_SHADOW_")):
                role = "LEAKAGE_EXCLUDE"
            elif (dataset, column) in allowed:
                role = "FEATURE_ALLOWED"
            elif "FULL_BAR_DIAGNOSTIC" in column or "Full Bar Diagnostic" in column:
                role = "FEATURE_DIAGNOSTIC_ONLY"
            else:
                role = "LEAKAGE_EXCLUDE"
            rows.append({"Dataset": dataset, "Column": column, "Role": role})
    return pd.DataFrame(rows).drop_duplicates(["Dataset", "Column"]).sort_values(["Dataset", "Column"]).reset_index(drop=True)


def date_feature_audit(datasets: Mapping[str, pd.DataFrame], ml_registry: pd.DataFrame) -> pd.DataFrame:
    role_lookup = ml_registry.set_index(["Dataset", "Column"])["Role"].to_dict()
    rows = []
    for dataset, frame in datasets.items():
        for column in frame.columns:
            if not is_date_like(column, frame[column]):
                continue
            role = role_lookup[(dataset, column)]
            rows.append(
                {
                    "Dataset": dataset,
                    "Column": column,
                    "Data Type": str(frame[column].dtype),
                    "Role": role,
                    "Date-Like": True,
                    "FEATURE_ALLOWED Violation": role == "FEATURE_ALLOWED",
                }
            )
    return pd.DataFrame(rows).sort_values(["Dataset", "Column"]).reset_index(drop=True)
