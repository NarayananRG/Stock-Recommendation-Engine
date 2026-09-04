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

ENTRY_FROZEN_POSITION_FEATURES = {
    "Entry Market Regime", "Entry Technical Score", "Entry Actionability Score",
    "Executed Entry", "Initial Stop", "Original T1", "Original T2",
    "Original Signal", "Setup", "Stop Distance R", "T1 Distance R",
    "T2 Distance R",
}

ENTRY_FROZEN_AS_OF = (
    "KNOWN SINCE ENTRY; RETAINED AS FROZEN ENTRY STATE THROUGH MANAGEMENT DATE"
)
MANAGEMENT_CLOSE_AS_OF = "COMPLETED MANAGEMENT SESSION CLOSE"
SIGNAL_CLOSE_AS_OF = "SIGNAL SESSION CLOSE"


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
    source_rows: dict[str, list[dict[str, Any]]] = {}
    for record in stage3_registry.to_dict("records"):
        source_rows.setdefault(str(record["Feature Name"]), []).append(record)
    rows: list[dict[str, Any]] = []
    for dataset, frame in datasets.items():
        for feature_name in sorted(set(frame.columns).intersection(source_rows)):
            candidates = source_rows[feature_name]
            preferred_as_of = MANAGEMENT_CLOSE_AS_OF if dataset == "d1_position_day" else SIGNAL_CLOSE_AS_OF
            preferred = [row for row in candidates if str(row.get("As-Of Semantics", "")) == preferred_as_of]
            source = dict((preferred or candidates)[0])
            date_like = is_date_like(feature_name, frame[feature_name])
            allowed = bool(source.get("ML Allowed", False)) and not date_like
            classification = ""
            if dataset == "d1_position_day":
                if feature_name in ENTRY_FROZEN_POSITION_FEATURES:
                    classification = "ENTRY_FROZEN_STATE"
                    source["Source"] = "Stage 3 position-day dataset: frozen entry-time state"
                    source["Formula / Description"] = (
                        f"{feature_name} is an entry-time frozen value retained unchanged through each management date."
                    )
                    source["As-Of Semantics"] = ENTRY_FROZEN_AS_OF
                    source["Missing Value Meaning"] = (
                        "The source entry-time value was unavailable when the position was opened."
                    )
                    source["Known Ambiguity"] = ""
                    source["Stage Source"] = (
                        "Stage 2B.1 D1_TRAIL_ONLY entry snapshot / Stage 3 position-day dataset"
                    )
                else:
                    classification = "CURRENT_MANAGEMENT_STATE"
                    source["Source"] = "Stage 3 position-day dataset: current D1 management state"
                    source["Formula / Description"] = (
                        f"{feature_name} is the current D1 management-state value known at the completed management-session close."
                    )
                    source["As-Of Semantics"] = MANAGEMENT_CLOSE_AS_OF
                    source["Missing Value Meaning"] = (
                        "Required frozen point-in-time inputs or lookback history were unavailable for the completed management session."
                    )
                    source["Known Ambiguity"] = ""
                    source["Stage Source"] = (
                        "Stage 2B.1 D1_TRAIL_ONLY / frozen point-in-time inputs / Stage 3 position-day state"
                    )
            else:
                source["As-Of Semantics"] = SIGNAL_CLOSE_AS_OF
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
                    "As-Of Semantics": source.get("As-Of Semantics", ""),
                    "Point-In-Time Safe": bool(source.get("Point-In-Time Safe", False)),
                    "ML Allowed": allowed,
                    "Reason if ML Disallowed": reason,
                    "Missing Value Meaning": source.get("Missing Value Meaning", ""),
                    "Known Ambiguity": source.get("Known Ambiguity", ""),
                    "Stage Source": source.get("Stage Source", ""),
                    "Metadata Classification": classification,
                }
            )
    result = pd.DataFrame(rows)
    if result.duplicated(["Dataset", "Feature Name"]).any():
        raise RuntimeError("Feature registry composite key is not unique")
    return result.sort_values(["Dataset", "Feature Name"]).reset_index(drop=True)


def feature_metadata_semantic_audit(
    registry: pd.DataFrame,
    ml_registry: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def value(dataset: str, feature: str, column: str) -> str:
        match = registry[
            registry["Dataset"].eq(dataset)
            & registry["Feature Name"].eq(feature)
        ]
        if len(match) != 1:
            return "MISSING_OR_DUPLICATED"
        return str(match.iloc[0][column])

    def add(check: str, passed: bool, expected: str, actual: Any) -> None:
        rows.append({
            "Check": check,
            "Status": "PASS" if bool(passed) else "FAIL",
            "Expected": expected,
            "Actual": actual,
        })

    d1_adx_asof = value("d1_position_day", "ADX", "As-Of Semantics")
    add("D1 ADX management-close as-of", d1_adx_asof == MANAGEMENT_CLOSE_AS_OF, MANAGEMENT_CLOSE_AS_OF, d1_adx_asof)
    d1_daily_source = " | ".join([
        value("d1_position_day", "Daily ST", "Source"),
        value("d1_position_day", "Daily ST", "Formula / Description"),
    ])
    add("D1 Daily ST current-management description", "current d1 management" in d1_daily_source.lower(), "CURRENT D1 MANAGEMENT STATE", d1_daily_source)
    d1_regime_class = value("d1_position_day", "Current Market Regime", "Metadata Classification")
    add("D1 Current Market Regime classification", d1_regime_class == "CURRENT_MANAGEMENT_STATE", "CURRENT_MANAGEMENT_STATE", d1_regime_class)
    entry_score_asof = value("d1_position_day", "Entry Technical Score", "As-Of Semantics")
    add("D1 Entry Technical Score entry-frozen as-of", entry_score_asof == ENTRY_FROZEN_AS_OF, ENTRY_FROZEN_AS_OF, entry_score_asof)
    original_t1_class = value("d1_position_day", "Original T1", "Metadata Classification")
    add("D1 Original T1 classification", original_t1_class == "ENTRY_FROZEN_STATE", "ENTRY_FROZEN_STATE", original_t1_class)
    signal_adx_asof = value("signal_state", "ADX", "As-Of Semantics")
    add("Signal-state ADX signal-close as-of", signal_adx_asof == SIGNAL_CLOSE_AS_OF, SIGNAL_CLOSE_AS_OF, signal_adx_asof)
    signal_adx_description = value("signal_state", "ADX", "Formula / Description")
    d1_adx_description = value("d1_position_day", "ADX", "Formula / Description")
    add("Same feature may have dataset-specific descriptions", signal_adx_description != d1_adx_description, "DIFFERENT", "DIFFERENT" if signal_adx_description != d1_adx_description else "SAME")
    duplicate_count = int(registry.duplicated(["Dataset", "Feature Name"]).sum())
    add("Feature registry Dataset + Feature Name unique", duplicate_count == 0, "0", duplicate_count)
    allowed_features = set(map(tuple, registry.loc[registry["ML Allowed"].fillna(False).astype(bool), ["Dataset", "Feature Name"]].to_numpy()))
    allowed_ml = set(map(tuple, ml_registry.loc[ml_registry["Role"].eq("FEATURE_ALLOWED"), ["Dataset", "Column"]].to_numpy()))
    difference_count = len(allowed_features.symmetric_difference(allowed_ml))
    add("Feature registry equals ML registry per dataset", difference_count == 0, "0 symmetric differences", difference_count)
    return pd.DataFrame(rows)


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
