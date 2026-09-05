"""Descriptive cohort, comparison, and fixed evidence diagnostics."""
from __future__ import annotations

import numpy as np
import pandas as pd

from metrics import classification_metrics


def cohort_metrics(predictions: pd.DataFrame, column: str) -> pd.DataFrame:
    valid = predictions.loc[predictions["Actual Label"].notna()].copy()
    rows = []
    for keys, group in valid.groupby(["Target", "Model Variant", "Feature Set", column], dropna=False, sort=True):
        row = {
            "Target": keys[0], "Model Variant": keys[1], "Feature Set": keys[2],
            "Cohort": keys[3], "Cohort Field": column, "Models Refit for Cohort": False,
        }
        row.update(classification_metrics(group["Actual Label"], group["Predicted Probability"], group["Training Prior"]))
        rows.append(row)
    return pd.DataFrame(rows)


def dataset_cohort_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    all_rows = predictions.copy()
    all_rows["Dataset Cohort"] = "ALL"
    return pd.concat([
        cohort_metrics(all_rows, "Dataset Cohort"),
        cohort_metrics(predictions, "Dataset Cohort"),
    ], ignore_index=True)


def research_evidence_classification(
    pooled: pd.DataFrame, recent: pd.DataFrame, stability: pd.DataFrame
) -> pd.DataFrame:
    merged = pooled.merge(
        recent[["Target", "Model Variant", "Feature Set", "ROC AUC", "Brier Skill Score vs Training Prior"]],
        on=["Target", "Model Variant", "Feature Set"], suffixes=(" Pooled", " Recent"), validate="one_to_one",
    ).merge(stability, on=["Target", "Model Variant", "Feature Set"], validate="one_to_one")
    rows = []
    for record in merged.to_dict("records"):
        pooled_auc = record["ROC AUC Pooled"]
        pooled_bss = record["Brier Skill Score vs Training Prior Pooled"]
        recent_auc = record["ROC AUC Recent"]
        recent_bss = record["Brier Skill Score vs Training Prior Recent"]
        years_positive = record["Years ROC AUC > 0.50"]
        promising = (
            pooled_auc >= 0.55 and pooled_bss >= 0.02 and years_positive >= 7
            and recent_auc >= 0.52 and recent_bss >= 0.0
        )
        if promising:
            category = "PROMISING HISTORICAL SIGNAL"
        elif pooled_auc > 0.50 and pooled_bss > 0.0:
            category = "WEAK POSITIVE HISTORICAL SIGNAL"
        elif ((pooled_auc > 0.50) != (pooled_bss > 0.0)) or (pooled_auc >= 0.55 and recent_auc < 0.52) or (years_positive >= 6 and recent_auc < 0.50):
            category = "MIXED"
        else:
            category = "NO USEFUL HISTORICAL SIGNAL"
        rows.append({
            "Target": record["Target"], "Model Variant": record["Model Variant"],
            "Feature Set": record["Feature Set"], "Research Evidence Classification": category,
            "Pooled ROC AUC": pooled_auc, "Pooled Brier Skill Score": pooled_bss,
            "Years ROC AUC > 0.50": years_positive, "Recent 2024-2026 ROC AUC": recent_auc,
            "Recent 2024-2026 Brier Skill Score": recent_bss,
            "Production Model Selected": False, "Validated for Live Trading": False,
        })
    return pd.DataFrame(rows)


def model_comparison(
    pooled: pd.DataFrame,
    recent: pd.DataFrame,
    stability: pd.DataFrame,
    lift: pd.DataFrame,
) -> pd.DataFrame:
    top10 = lift.loc[(lift["Scope"].eq("POOLED_OOS")) & lift["Bucket"].eq("TOP_10_PERCENT"),
                     ["Target", "Model Variant", "Feature Set", "Lift"]].rename(
                         columns={"Lift": "Pooled Top-Decile Lift"}
                     )
    result = pooled.merge(
        recent[["Target", "Model Variant", "Feature Set", "ROC AUC", "Brier Skill Score vs Training Prior"]],
        on=["Target", "Model Variant", "Feature Set"], suffixes=(" Pooled", " Recent"), validate="one_to_one",
    ).merge(
        stability[["Target", "Model Variant", "Feature Set", "Median Yearly ROC AUC", "Total Yearly Positive Count"]],
        on=["Target", "Model Variant", "Feature Set"], validate="one_to_one",
    ).merge(top10, on=["Target", "Model Variant", "Feature Set"], how="left", validate="one_to_one")
    result = result.rename(columns={"Lift": "Pooled Top-Decile Lift"})
    notes = {
        "LOGIT_RAW": "Raw point-in-time state without rule summaries",
        "LOGIT_FULL": "Descriptive comparison to LOGIT_RAW and LOGIT_RULE",
        "LOGIT_RULE": "Rule summaries without richer raw state",
        "RF_FULL": "Fixed nonlinear comparison to LOGIT_FULL",
        "DUMMY_PRIOR": "Training-fold prevalence benchmark",
    }
    result["Comparison Purpose"] = result["Model Variant"].map(notes)
    result["Model Selected"] = False
    return result
