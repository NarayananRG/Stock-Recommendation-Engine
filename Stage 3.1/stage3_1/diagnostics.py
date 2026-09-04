"""Descriptive Stage 3.1 diagnostics using target-specific denominators."""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
import pandas as pd


def dataset_summary(signal_state: pd.DataFrame, opportunities: pd.DataFrame, position_day: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"Dataset": "SIGNAL_STATE", "Rows": len(signal_state), "Columns": len(signal_state.columns), "Unique Signal IDs": signal_state["Signal ID"].nunique(), "Category": ""},
        {"Dataset": "TRADE_OPPORTUNITY", "Rows": len(opportunities), "Columns": len(opportunities.columns), "Unique Signal IDs": opportunities["Signal ID"].nunique(), "Category": ""},
        {"Dataset": "D1_POSITION_DAY", "Rows": len(position_day), "Columns": len(position_day.columns), "Unique Signal IDs": position_day["Signal ID"].nunique(), "Category": ""},
    ]
    for value, count in opportunities["Dataset Cohort"].value_counts(dropna=False).items():
        rows.append({"Dataset": "TRADE_OPPORTUNITY", "Rows": int(count), "Columns": np.nan, "Unique Signal IDs": int(opportunities.loc[opportunities["Dataset Cohort"].eq(value), "Signal ID"].nunique()), "Category": f"COHORT:{value}"})
    for status, count in opportunities["ENTRY_STATUS"].value_counts(dropna=False).items():
        rows.append({"Dataset": "TRADE_OPPORTUNITY", "Rows": int(count), "Columns": np.nan, "Unique Signal IDs": int(opportunities.loc[opportunities["ENTRY_STATUS"].eq(status), "Signal ID"].nunique()), "Category": f"ENTRY_STATUS:{status}"})
    return pd.DataFrame(rows)


def _target_record(group: pd.DataFrame, keys: Mapping[str, object]) -> dict[str, object]:
    t1_app = group["T1_APPLICABLE"].fillna(False).astype(bool)
    t2_app = group["T2_APPLICABLE"].fillna(False).astype(bool)
    entry_available = ~group["ENTRY_DATA_END_CENSORED"].fillna(False).astype(bool)
    filled = group["ENTRY_FILLED"].fillna(False).astype(bool) & entry_available
    row = {
        **keys,
        "Rows": len(group),
        "Filled Opportunities": int(filled.sum()),
        "Observed Non-Fills": int((group["ENTRY_FILLED"].eq(False) & entry_available).sum()),
        "Incomplete Entry-Window Censored": int(group["ENTRY_DATA_END_CENSORED"].fillna(False).sum()),
        "Invalid-Risk Fills": int((group["ENTRY_FILLED"].eq(True) & ~group["ENTRY_RISK_VALID"].fillna(False)).sum()),
        "T1 Applicable": int(t1_app.sum()),
        "T1 Available": int(group["T1_STATUS"].eq("AVAILABLE").sum()),
        "T1 Positive": int(group["T1_BEFORE_STOP_63"].eq(True).sum()),
        "T1 Negative": int(group["T1_BEFORE_STOP_63"].eq(False).sum()),
        "T1 Data-End Censored": int(group["T1_DATA_END_CENSORED"].fillna(False).sum()),
        "T2 Applicable": int(t2_app.sum()),
        "T2 Available": int(group["T2_STATUS"].eq("AVAILABLE").sum()),
        "T2 Positive": int(group["T2_BEFORE_STOP_63"].eq(True).sum()),
        "T2 Negative": int(group["T2_BEFORE_STOP_63"].eq(False).sum()),
        "T2 Data-End Censored": int(group["T2_DATA_END_CENSORED"].fillna(False).sum()),
    }
    row["Fill Rate Among Resolved %"] = float(filled.sum() / entry_available.sum() * 100.0) if entry_available.any() else np.nan
    return row


def target_summary(frame: pd.DataFrame, group_columns: Sequence[str] = ()) -> pd.DataFrame:
    if not group_columns:
        return pd.DataFrame([_target_record(frame, {})])
    work = frame.copy()
    if "Year" in group_columns and "Year" not in work:
        work["Year"] = pd.to_datetime(work["Signal Date"]).dt.year
    rows = []
    grouping = group_columns[0] if len(group_columns) == 1 else list(group_columns)
    for key, group in work.groupby(grouping, dropna=False):
        values = (key,) if len(group_columns) == 1 else tuple(key)
        rows.append(_target_record(group, dict(zip(group_columns, values))))
    return pd.DataFrame(rows)


def ambiguity_summary(opportunities: pd.DataFrame, position_day: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Dataset": "TRADE_OPPORTUNITY",
            "Rows": len(opportunities),
            "Entry-Day Ambiguous": int(opportunities["ENTRY_DAY_SEQUENCE_AMBIGUOUS"].fillna(False).sum()),
            "Same-Bar Outcome Ambiguous": int(opportunities["OUTCOME_SEQUENCE_AMBIGUOUS"].fillna(False).sum()),
        },
        {
            "Dataset": "D1_POSITION_DAY",
            "Rows": len(position_day),
            "Entry-Day Ambiguous": int(position_day["ENTRY_DAY_SEQUENCE_AMBIGUOUS"].fillna(False).sum()),
            "Same-Bar Outcome Ambiguous": int(position_day["EXIT_DAY_SEQUENCE_AMBIGUOUS"].fillna(False).sum()),
        },
    ])


def censoring_summary(
    datasets: Mapping[str, pd.DataFrame],
    label_registry: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    seen: set[tuple[str, str]] = set()
    for _, spec in label_registry.iterrows():
        key = (str(spec["Dataset"]), str(spec["Label Name"]))
        if key in seen:
            continue
        seen.add(key)
        dataset, target = key
        frame = datasets[dataset]
        status_column = str(spec["Status Column"])
        if target not in frame.columns or status_column not in frame.columns:
            continue
        status = frame[status_column].astype("string")
        if status_column == "ENTRY_STATUS":
            available = status.isin(["FILLED", "FILLED_INVALID_RISK", "NOT_FILLED"])
            not_applicable = pd.Series(False, index=frame.index)
        else:
            available = status.eq("AVAILABLE").fillna(False)
            not_applicable = status.eq("NOT_APPLICABLE").fillna(False)
        data_end = status.eq("DATA_END_CENSORED").fillna(False)
        applicable = ~not_applicable
        applicable_count = int(applicable.sum())
        rows.append({
            "Dataset": dataset,
            "Target": target,
            "Total Rows": len(frame),
            "Applicable Rows": applicable_count,
            "Available Rows": int(available.sum()),
            "Not Applicable Rows": int(not_applicable.sum()),
            "Data-End Censored Rows": int(data_end.sum()),
            "Censoring Rate Among Applicable %": float(data_end.sum() / applicable_count * 100.0) if applicable_count else np.nan,
            "Availability Rate Among Applicable %": float(available.sum() / applicable_count * 100.0) if applicable_count else np.nan,
        })
    return pd.DataFrame(rows).sort_values(["Dataset", "Target"]).reset_index(drop=True)


def feature_missingness(datasets: Mapping[str, pd.DataFrame], registry: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, item in registry.iterrows():
        dataset, name = str(item["Dataset"]), str(item["Feature Name"])
        frame = datasets[dataset]
        if name not in frame:
            continue
        missing = int(frame[name].isna().sum())
        rows.append({
            "Dataset": dataset,
            "Feature": name,
            "Rows": len(frame),
            "Missing Rows": missing,
            "Missing %": float(missing / len(frame) * 100.0) if len(frame) else np.nan,
            "ML Allowed": bool(item["ML Allowed"]),
        })
    return pd.DataFrame(rows).sort_values(["Dataset", "Missing %", "Feature"], ascending=[True, False, True]).reset_index(drop=True)


def feature_distribution_by_era(signal_state: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    allowed = registry[(registry["Dataset"] == "signal_state") & registry["ML Allowed"].fillna(False).astype(bool)]
    numeric = [name for name in allowed["Feature Name"] if name in signal_state and pd.api.types.is_numeric_dtype(signal_state[name])]
    work = signal_state.copy()
    years = pd.to_datetime(work["Signal Date"]).dt.year
    work["Era"] = pd.cut(years, bins=[2010, 2015, 2020, 2023, 2026], labels=["2011-2015", "2016-2020", "2021-2023", "2024-2026"])
    rows = []
    for era, group in work.groupby("Era", observed=True):
        for feature in numeric:
            values = pd.to_numeric(group[feature], errors="coerce")
            rows.append({
                "Dataset": "signal_state", "Era": str(era), "Feature": feature,
                "Rows": len(group), "Available Rows": int(values.notna().sum()),
                "Mean": float(values.mean()) if values.notna().any() else np.nan,
                "Std": float(values.std()) if values.notna().sum() > 1 else np.nan,
                "Min": float(values.min()) if values.notna().any() else np.nan,
                "Median": float(values.median()) if values.notna().any() else np.nan,
                "Max": float(values.max()) if values.notna().any() else np.nan,
            })
    return pd.DataFrame(rows)


def d1_position_day_summary(position_day: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "Dataset Label": "INDEPENDENT D1 SHADOW MANAGEMENT DATASET",
        "Rows": len(position_day),
        "Unique Signals": position_day["Signal ID"].nunique(),
        "First Management Date": pd.to_datetime(position_day["Management Date"]).min(),
        "Last Management Date": pd.to_datetime(position_day["Management Date"]).max(),
        "Average Days Held State": float(pd.to_numeric(position_day["Days Held"]).mean()),
        "Rows With Stop Revision": int((pd.to_numeric(position_day["Stop Revision Count"]) > 0).sum()),
        "Final Label Data-End Censored Rows": int(position_day["D1_FINAL_DATA_END_CENSORED"].fillna(False).sum()),
    }])
