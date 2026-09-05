"""Fixed Stage 4A.1 classification, ranking, calibration, and rank-agreement metrics."""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd
from .ranking import bucket_metrics, bucket_membership
from scipy.stats import pearsonr, spearmanr
from sklearn.metrics import accuracy_score, average_precision_score, brier_score_loss, confusion_matrix, f1_score, log_loss, precision_score, recall_score, roc_auc_score


METRIC_COLUMNS = ["Rows", "Positive Count", "Prevalence", "ROC AUC", "Average Precision", "Brier Score", "Brier Benchmark Score", "Brier Skill Score vs Training Prior", "Log Loss", "Accuracy at 0.50", "Precision at 0.50", "Recall at 0.50", "Specificity at 0.50", "F1 at 0.50"]


def fixed_log_loss(actual: Iterable[float], probability: Iterable[float]) -> float:
    """Frozen Stage 4A contract; clipping never mutates saved probabilities."""
    y = np.asarray(list(actual), dtype=float)
    p = np.asarray(list(probability), dtype=float)
    if y.ndim != 1 or p.shape != y.shape or not len(y):
        raise ValueError("Log Loss requires nonempty matching one-dimensional inputs")
    if not np.isin(y, [0, 1]).all():
        raise ValueError("Log Loss labels must be binary")
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("Log Loss probabilities must be finite and in [0,1]")
    clipped = np.clip(p, 1e-15, 1.0 - 1e-15)
    return float(log_loss(y, clipped, labels=[0, 1]))


def classification_metrics(actual: Iterable[float], probability: Iterable[float], prior_values: Iterable[float] | float) -> dict[str, Any]:
    y = np.asarray(list(actual), dtype=int)
    p = np.asarray(list(probability), dtype=float)
    prior = np.full(len(y), float(prior_values)) if np.isscalar(prior_values) else np.asarray(list(prior_values), dtype=float)
    if not len(y):
        return {column: np.nan for column in METRIC_COLUMNS} | {"Rows": 0, "Positive Count": 0}
    auc = float(roc_auc_score(y, p)) if np.unique(y).size == 2 else np.nan
    ap = float(average_precision_score(y, p)) if y.sum() else np.nan
    brier = float(brier_score_loss(y, p))
    benchmark = float(np.mean((y - prior) ** 2))
    predicted = (p >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, predicted, labels=[0, 1]).ravel()
    return {
        "Rows": len(y), "Positive Count": int(y.sum()), "Prevalence": float(y.mean()), "ROC AUC": auc,
        "Average Precision": ap, "Brier Score": brier, "Brier Benchmark Score": benchmark,
        "Brier Skill Score vs Training Prior": float(1 - brier / benchmark) if benchmark > 0 else np.nan,
        "Log Loss": fixed_log_loss(y, p),
        "Accuracy at 0.50": float(accuracy_score(y, predicted)),
        "Precision at 0.50": float(precision_score(y, predicted, zero_division=0)),
        "Recall at 0.50": float(recall_score(y, predicted, zero_division=0)),
        "Specificity at 0.50": float(tn / (tn + fp)) if tn + fp else np.nan,
        "F1 at 0.50": float(f1_score(y, predicted, zero_division=0)),
    }


def grouped_metrics(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    rows = []
    valid = frame.loc[frame["Actual Label"].notna()].copy()
    for keys, group in valid.groupby(groups, dropna=False, sort=True):
        values = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(groups, values, strict=True))
        row.update(classification_metrics(group["Actual Label"], group["Predicted Probability"], group["Training Prior"]))
        rows.append(row)
    return pd.DataFrame(rows, columns=groups + METRIC_COLUMNS)


def add_scope(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["Scope"] = "POOLED_2016_2026"
    result.loc[result["Evaluation Year"].between(2016, 2020), "Era"] = "ERA_2016_2020"
    result.loc[result["Evaluation Year"].between(2021, 2023), "Era"] = "ERA_2021_2023"
    result.loc[result["Evaluation Year"].between(2024, 2026), "Era"] = "RECENT_2024_2026"
    return result


def metric_tables(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    keys = ["Mode", "Target", "Model Variant", "Feature Set"]
    pooled = grouped_metrics(frame, keys); pooled.insert(0, "Scope", "POOLED_2016_2026")
    yearly = grouped_metrics(frame, keys + ["Evaluation Year"])
    work = add_scope(frame)
    era = grouped_metrics(work, keys + ["Era"]).rename(columns={"Era": "Scope"})
    recent = era.loc[era["Scope"].eq("RECENT_2024_2026")].reset_index(drop=True)
    return pooled, yearly, era, recent


def ranking_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    valid = add_scope(frame.loc[frame["Actual Label"].notna()].copy())
    scopes = [("POOLED_2016_2026", valid)] + [(scope, valid.loc[valid["Era"].eq(scope)]) for scope in ["ERA_2016_2020", "ERA_2021_2023", "RECENT_2024_2026"]]
    rows = []
    keys = ["Mode", "Target", "Model Variant", "Feature Set"]
    for scope, scoped in scopes:
        for values, group in scoped.groupby(keys, sort=True):
            row = dict(zip(keys, values, strict=True)) | {"Scope": scope} | bucket_metrics(group).iloc[0].to_dict()
            rows.append(row)
    return pd.DataFrame(rows)


def calibration(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid = frame.loc[frame["Actual Label"].notna()].copy()
    rows, summaries = [], []
    keys = ["Mode", "Target", "Model Variant", "Feature Set"]
    for values, group in valid.groupby(keys, sort=True):
        buckets = np.minimum(np.floor(group["Predicted Probability"].astype(float) * 10).astype(int), 9)
        ece = 0.0
        for bucket in range(10):
            subset = group.loc[buckets.eq(bucket)]
            mean_p = float(subset["Predicted Probability"].mean()) if len(subset) else np.nan
            observed = float(subset["Actual Label"].mean()) if len(subset) else np.nan
            error = abs(mean_p - observed) if len(subset) else np.nan
            if len(subset): ece += len(subset) / len(group) * error
            rows.append(dict(zip(keys, values, strict=True)) | {"Bucket": f"{bucket/10:.1f}-{(bucket+1)/10:.1f}", "Rows": len(subset), "Mean Predicted Probability": mean_p, "Observed Success Rate": observed, "Calibration Error": error})
        summaries.append(dict(zip(keys, values, strict=True)) | {"Rows": len(group), "Expected Calibration Error": ece})
    return pd.DataFrame(rows), pd.DataFrame(summaries)


def yearly_stability(yearly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    keys = ["Mode", "Target", "Model Variant", "Feature Set"]
    for values, group in yearly.groupby(keys, sort=True):
        auc = group["ROC AUC"].dropna(); bss = group["Brier Skill Score vs Training Prior"].dropna()
        rows.append(dict(zip(keys, values, strict=True)) | {
            "Valid Evaluation Years": len(auc), "Years ROC AUC > 0.50": int(auc.gt(.5).sum()), "Years ROC AUC > 0.55": int(auc.gt(.55).sum()),
            "Years Positive Brier Skill": int(bss.gt(0).sum()), "Median Yearly ROC AUC": auc.median(), "Mean Yearly ROC AUC": auc.mean(),
            "Worst Yearly ROC AUC": auc.min(), "Best Yearly ROC AUC": auc.max(), "Std Yearly ROC AUC": auc.std(ddof=0),
        })
    return pd.DataFrame(rows)


def rank_agreement(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    valid = frame.loc[frame["Actual Label"].notna()].copy()
    for (target, model), group in valid.groupby(["Target", "Model Variant"], sort=True):
        left = group.loc[group["Mode"].eq("TRANSFER"), ["Signal ID", "Predicted Probability"]].rename(columns={"Predicted Probability": "Transfer"})
        right = group.loc[group["Mode"].eq("PRIMARY_ONLY"), ["Signal ID", "Predicted Probability"]].rename(columns={"Predicted Probability": "Primary"})
        pair = left.merge(right, on="Signal ID", validate="one_to_one")
        def top_ids(column: str, fraction: float) -> set[str]:
            selected = bucket_membership(pair[column], pair["Signal ID"], np.ones(len(pair), dtype=int), fraction)[0]
            return set(pair.loc[selected > 0, "Signal ID"])
        t10, p10 = top_ids("Transfer", .1), top_ids("Primary", .1); t20, p20 = top_ids("Transfer", .2), top_ids("Primary", .2)
        rows.append({"Target": target, "Model Variant": model, "Rows": len(pair),
            "Pearson Probability Correlation": pearsonr(pair["Transfer"], pair["Primary"]).statistic if pair["Transfer"].nunique() > 1 and pair["Primary"].nunique() > 1 else np.nan,
            "Spearman Rank Correlation": spearmanr(pair["Transfer"], pair["Primary"]).statistic if pair["Transfer"].nunique() > 1 and pair["Primary"].nunique() > 1 else np.nan,
            "Top 10% Overlap Count": len(t10 & p10), "Top 10% Jaccard": len(t10 & p10) / len(t10 | p10),
            "Top 20% Overlap Count": len(t20 & p20), "Top 20% Jaccard": len(t20 & p20) / len(t20 | p20)})
    return pd.DataFrame(rows)
