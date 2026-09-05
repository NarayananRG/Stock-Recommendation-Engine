"""Stage 4A.1 cohort, signal, and evidence diagnostics."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .metrics import classification_metrics
from .ranking import bucket_metrics


def top20_lift(group: pd.DataFrame) -> float:
    return float(bucket_metrics(group).iloc[0]["Top 20% Lift"])


def dataset_cohort_comparison(frozen: pd.DataFrame) -> pd.DataFrame:
    rows = []
    valid = frozen.loc[frozen["Actual Label"].notna()].copy()
    for (cohort, target, model, feature_set), group in valid.groupby(["Dataset Cohort", "Target", "Model Variant", "Feature Set"], sort=True):
        metrics = classification_metrics(group["Actual Label"], group["Predicted Probability"], group["Training Prior"])
        rows.append({"Dataset Cohort": cohort, "Target": target, "Model Variant": model, "Feature Set": feature_set,
            "Rows": metrics["Rows"], "Positive Count": metrics["Positive Count"], "Prevalence": metrics["Prevalence"],
            "ROC AUC": metrics["ROC AUC"], "Average Precision": metrics["Average Precision"],
            "Brier Skill Score vs Training Prior": metrics["Brier Skill Score vs Training Prior"], "Top 20% Lift": top20_lift(group)})
    return pd.DataFrame(rows)


def original_signal_diagnostics(transfer_primary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    valid = transfer_primary.loc[transfer_primary["Actual Label"].notna()].copy()
    for (signal, target, model), group in valid.groupby(["Original Signal", "Target", "Model Variant"], sort=True):
        metrics = classification_metrics(group["Actual Label"], group["Predicted Probability"], group["Training Prior"])
        rows.append({"Original Signal": signal, "Target": target, "Model Variant": model, "Rows": len(group),
            "Positive Count": int(group["Actual Label"].sum()), "Prevalence": group["Actual Label"].mean(), "ROC AUC": metrics["ROC AUC"],
            "Average Precision": metrics["Average Precision"], "Brier Skill Score vs Training Prior": metrics["Brier Skill Score vs Training Prior"],
            "Small Sample Warning": len(group) < 100})
    return pd.DataFrame(rows)


def evidence_classification(point_metrics: pd.DataFrame, yearly: pd.DataFrame, bootstrap_summary: pd.DataFrame, minimum_valid: int) -> pd.DataFrame:
    pooled = point_metrics.loc[point_metrics["Scope"].eq("POOLED_2016_2026")]
    recent = point_metrics.loc[point_metrics["Scope"].eq("RECENT_2024_2026")]
    lower = bootstrap_summary.loc[(bootstrap_summary["Block Length"].eq(63)) & bootstrap_summary["Scope"].eq("POOLED_2016_2026") & bootstrap_summary["Metric"].eq("ROC AUC")]
    rows = []
    for _, item in pooled.iterrows():
        mask = recent["Mode"].eq(item["Mode"]) & recent["Target"].eq(item["Target"]) & recent["Model Variant"].eq(item["Model Variant"])
        recent_auc = float(recent.loc[mask, "ROC AUC"].iloc[0]) if mask.any() else np.nan
        annual = yearly.loc[yearly["Mode"].eq(item["Mode"]) & yearly["Target"].eq(item["Target"]) & yearly["Model Variant"].eq(item["Model Variant"])]
        ci = lower.loc[lower["Mode"].eq(item["Mode"]) & lower["Target"].eq(item["Target"]) & lower["Model Variant"].eq(item["Model Variant"])]
        ci_lower = float(ci["2.5%"].iloc[0]); valid_boot = int(ci["Valid Replicates"].iloc[0])
        years_positive = int(annual["ROC AUC"].gt(.5).sum()); valid_years = int(annual["ROC AUC"].notna().sum())
        robust = item["ROC AUC"] > .55 and ci_lower > .5 and item["Brier Skill Score vs Training Prior"] > 0 and recent_auc > .52 and years_positive >= 7
        if valid_boot < minimum_valid or valid_years < 3:
            classification = "INSUFFICIENT SAMPLE"
        elif robust:
            classification = "ROBUST POSITIVE HISTORICAL SIGNAL"
        elif item["ROC AUC"] > .5 and (item["Brier Skill Score vs Training Prior"] > 0 or (pd.notna(recent_auc) and recent_auc > .5)):
            classification = "WEAK POSITIVE HISTORICAL SIGNAL"
        elif item["ROC AUC"] <= .5 and item["Brier Skill Score vs Training Prior"] <= 0 and (pd.isna(recent_auc) or recent_auc <= .5):
            classification = "NO USEFUL HISTORICAL SIGNAL"
        else:
            classification = "MIXED / INCONCLUSIVE"
        rows.append({"Mode": item["Mode"], "Target": item["Target"], "Model Variant": item["Model Variant"], "Feature Set": item["Feature Set"],
            "Pooled ROC AUC": item["ROC AUC"], "Pooled AUC 63-Date Lower 95%": ci_lower, "Pooled Brier Skill": item["Brier Skill Score vs Training Prior"],
            "Recent 2024-2026 ROC AUC": recent_auc, "Valid Annual AUCs": valid_years, "Years AUC > 0.50": years_positive,
            "Valid Pooled 63-Date AUC Replicates": valid_boot, "Research Evidence Classification": classification})
    return pd.DataFrame(rows)
