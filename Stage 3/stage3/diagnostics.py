"""Descriptive dataset diagnostics only. No feature selection or model training."""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


ERAS = (("2011-2015", 2011, 2015), ("2016-2020", 2016, 2020), ("2021-2023", 2021, 2023), ("2024-2026", 2024, 2026))


def feature_missingness(datasets: Mapping[str, pd.DataFrame], feature_names: Iterable[str]) -> pd.DataFrame:
    wanted = set(feature_names)
    rows = []
    for dataset, frame in datasets.items():
        date_column = "Management Date" if "Management Date" in frame else "Signal Date"
        dates = pd.to_datetime(frame[date_column], errors="coerce")
        tickers = frame.get("Ticker", pd.Series("", index=frame.index)).astype(str)
        for feature in sorted(wanted & set(frame.columns)):
            missing = frame[feature].isna()
            present_dates = dates[~missing]
            rows.append({
                "Dataset": dataset, "Feature": feature, "Missing Count": int(missing.sum()),
                "Missing %": float(missing.mean() * 100.0),
                "First Available Date": present_dates.min() if not present_dates.empty else pd.NaT,
                "Last Available Date": present_dates.max() if not present_dates.empty else pd.NaT,
                "Affected Tickers": "|".join(sorted(tickers[missing].unique())),
                "Affected Years": "|".join(map(str, sorted(dates[missing].dropna().dt.year.unique()))),
                "HIGH_MISSINGNESS": bool(missing.mean() >= 0.50),
            })
    return pd.DataFrame(rows)


def feature_distribution_by_era(frame: pd.DataFrame, feature_names: Iterable[str], date_column: str = "Signal Date") -> pd.DataFrame:
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    rows = []
    for feature in sorted(set(feature_names) & set(frame.columns)):
        # Boolean features are numeric diagnostics too, but pandas/numpy do
        # not define interpolated quantiles directly on bool arrays.
        values = pd.to_numeric(frame[feature], errors="coerce").astype(float)
        if values.notna().sum() == 0:
            continue
        for era, start, end in ERAS:
            sample = values[(dates.dt.year >= start) & (dates.dt.year <= end)].dropna()
            rows.append({
                "Diagnostic": "DESCRIPTIVE DRIFT DIAGNOSTIC", "Feature": feature, "Era": era,
                "Rows": len(sample), "Median": sample.median(), "Q25": sample.quantile(0.25),
                "Q75": sample.quantile(0.75), "Mean": sample.mean(), "Std": sample.std(),
            })
    return pd.DataFrame(rows)


def _target_record(group: pd.DataFrame, keys: Mapping[str, object]) -> dict[str, object]:
    t1_available = ~group["T1_CENSORED"].fillna(True).astype(bool)
    t2_available = ~group["T2_CENSORED"].fillna(True).astype(bool)
    entry_available = ~group["ENTRY_CENSORED"].fillna(True).astype(bool)
    filled = group["ENTRY_FILLED"].fillna(False).astype(bool) & entry_available
    record = dict(keys)
    record.update({
        "Rows": len(group), "Filled Opportunities": int(filled.sum()), "Non-Filled Opportunities": int((entry_available & ~filled).sum()),
        "Entry Censored": int((~entry_available).sum()),
        "Fill Rate %": float(filled.sum() / entry_available.sum() * 100.0) if entry_available.any() else np.nan,
        "T1 Positive": int((group["T1_BEFORE_STOP_63"] == True).sum()),
        "T1 Negative": int((t1_available & (group["T1_BEFORE_STOP_63"] == False)).sum()),
        "T1 Censored": int((~t1_available).sum()),
        "T1 Hit Rate %": float((group.loc[t1_available, "T1_BEFORE_STOP_63"] == True).mean() * 100.0) if t1_available.any() else np.nan,
        "T2 Positive": int((group["T2_BEFORE_STOP_63"] == True).sum()),
        "T2 Negative": int((t2_available & (group["T2_BEFORE_STOP_63"] == False)).sum()),
        "T2 Censored": int((~t2_available).sum()),
        "T2 Hit Rate %": float((group.loc[t2_available, "T2_BEFORE_STOP_63"] == True).mean() * 100.0) if t2_available.any() else np.nan,
        "Entry-Day Ambiguity Rate %": float(group["ENTRY_DAY_SEQUENCE_AMBIGUOUS"].fillna(False).astype(bool).mean() * 100.0),
        "Same-Bar Ambiguity Rate %": float(group["OUTCOME_SEQUENCE_AMBIGUOUS"].fillna(False).astype(bool).mean() * 100.0),
    })
    return record


def target_summary(frame: pd.DataFrame, group_columns: Sequence[str] = ()) -> pd.DataFrame:
    if not group_columns:
        return pd.DataFrame([_target_record(frame, {})])
    rows = []
    for keys, group in frame.groupby(list(group_columns), dropna=False, observed=True):
        key_values = keys if isinstance(keys, tuple) else (keys,)
        rows.append(_target_record(group, dict(zip(group_columns, key_values))))
    return pd.DataFrame(rows)


def dataset_summary(signal_state: pd.DataFrame, opportunities: pd.DataFrame, position_day: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"Dataset": "SIGNAL_STATE", "Rows": len(signal_state), "Columns": signal_state.shape[1], "Unique Signal IDs": signal_state["Signal ID"].nunique()},
        {"Dataset": "TRADE_OPPORTUNITY", "Rows": len(opportunities), "Columns": opportunities.shape[1], "Unique Signal IDs": opportunities["Signal ID"].nunique()},
        {"Dataset": "D1_POSITION_DAY", "Rows": len(position_day), "Columns": position_day.shape[1], "Unique Signal IDs": position_day["Signal ID"].nunique()},
    ]
    for signal, count in signal_state["Signal"].value_counts(dropna=False).items():
        rows.append({"Dataset": "SIGNAL_STATE_BY_SIGNAL", "Category": signal, "Rows": int(count), "Columns": np.nan, "Unique Signal IDs": int(count)})
    return pd.DataFrame(rows)


def ambiguity_summary(opportunities: pd.DataFrame, position_day: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([
        {"Dataset": "TRADE_OPPORTUNITY", "Rows": len(opportunities), "Entry-Day Ambiguous": int(opportunities["ENTRY_DAY_SEQUENCE_AMBIGUOUS"].fillna(False).sum()), "Same-Bar Outcome Ambiguous": int(opportunities["OUTCOME_SEQUENCE_AMBIGUOUS"].fillna(False).sum())},
        {"Dataset": "D1_POSITION_DAY", "Rows": len(position_day), "Entry-Day Ambiguous": int(position_day["ENTRY_DAY_SEQUENCE_AMBIGUOUS"].fillna(False).sum()), "Same-Bar Outcome Ambiguous": int(position_day["EXIT_DAY_SEQUENCE_AMBIGUOUS"].fillna(False).sum())},
    ])


def censoring_summary(opportunities: pd.DataFrame, position_day: pd.DataFrame, config: Mapping[str, object]) -> pd.DataFrame:
    rows = [
        {"Dataset": "TRADE_OPPORTUNITY", "Target": "T1_BEFORE_STOP_63", "Rows": len(opportunities), "Censored Rows": int(opportunities["T1_CENSORED"].fillna(True).sum())},
        {"Dataset": "TRADE_OPPORTUNITY", "Target": "T2_BEFORE_STOP_63", "Rows": len(opportunities), "Censored Rows": int(opportunities["T2_CENSORED"].fillna(True).sum())},
        {"Dataset": "TRADE_OPPORTUNITY", "Target": "D1_SHADOW_NET_R", "Rows": len(opportunities), "Censored Rows": int(opportunities.get("D1_SHADOW_CENSORED", pd.Series(True, index=opportunities.index)).fillna(True).sum())},
    ]
    for horizon in config["forward_horizons"]:
        rows.append({"Dataset": "TRADE_OPPORTUNITY", "Target": f"FWD_CLOSE_RETURN_{horizon}_PCT", "Rows": len(opportunities), "Censored Rows": int(opportunities[f"FWD_{horizon}_CENSORED"].fillna(True).sum())})
    for row in rows:
        row["Censoring Rate %"] = row["Censored Rows"] / max(row["Rows"], 1) * 100.0
    return pd.DataFrame(rows)


def d1_position_day_summary(position_day: pd.DataFrame) -> pd.DataFrame:
    if position_day.empty:
        return pd.DataFrame([{"Rows": 0, "Unique Signals": 0}])
    return pd.DataFrame([{
        "Dataset Label": "INDEPENDENT D1 SHADOW MANAGEMENT DATASET", "Rows": len(position_day),
        "Unique Signals": position_day["Signal ID"].nunique(), "First Management Date": position_day["Management Date"].min(),
        "Last Management Date": position_day["Management Date"].max(), "Average Days Held State": position_day["Days Held"].mean(),
        "Rows With Stop Revision": int((position_day["Stop Revision Count"] > 0).sum()),
        "Final Label Censored Rows": int(position_day["D1_LABEL_CENSORED"].fillna(True).sum()),
    }])
