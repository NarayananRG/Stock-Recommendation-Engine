"""Fixed classification, calibration, stability, and ranking diagnostics."""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


METRIC_COLUMNS = [
    "Rows", "Positive Count", "Prevalence", "ROC AUC", "Average Precision",
    "Brier Score", "Brier Benchmark Score", "Brier Skill Score vs Training Prior",
    "Log Loss", "Accuracy at 0.50", "Precision at 0.50", "Recall at 0.50",
    "Specificity at 0.50", "F1 at 0.50",
]


def classification_metrics(
    actual: Iterable[float],
    probability: Iterable[float],
    training_prior: Iterable[float] | float,
) -> dict[str, Any]:
    y = np.asarray(list(actual), dtype=int)
    p = np.asarray(list(probability), dtype=float)
    if np.isscalar(training_prior):
        prior = np.full(len(y), float(training_prior), dtype=float)
    else:
        prior = np.asarray(list(training_prior), dtype=float)
    if len(y) != len(p) or len(y) != len(prior):
        raise ValueError("Metric input lengths differ")
    if len(y) == 0:
        return {column: np.nan for column in METRIC_COLUMNS} | {"Rows": 0, "Positive Count": 0}
    if np.any((p < 0.0) | (p > 1.0)) or np.any((prior < 0.0) | (prior > 1.0)):
        raise ValueError("Classification probabilities must lie in [0, 1]")
    two_classes = len(np.unique(y)) == 2
    auc = float(roc_auc_score(y, p)) if two_classes else np.nan
    ap = float(average_precision_score(y, p)) if int(y.sum()) else np.nan
    brier = float(brier_score_loss(y, p))
    benchmark_brier = float(np.mean(np.square(y - prior)))
    brier_skill = float(1.0 - brier / benchmark_brier) if benchmark_brier > 0 else np.nan
    clipped = np.clip(p, 1e-15, 1.0 - 1e-15)
    loss = float(log_loss(y, clipped, labels=[0, 1]))
    predicted = (p >= 0.5).astype(int)
    matrix = confusion_matrix(y, predicted, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()
    specificity = float(tn / (tn + fp)) if tn + fp else np.nan
    return {
        "Rows": int(len(y)),
        "Positive Count": int(y.sum()),
        "Prevalence": float(y.mean()),
        "ROC AUC": auc,
        "Average Precision": ap,
        "Brier Score": brier,
        "Brier Benchmark Score": benchmark_brier,
        "Brier Skill Score vs Training Prior": brier_skill,
        "Log Loss": loss,
        "Accuracy at 0.50": float(accuracy_score(y, predicted)),
        "Precision at 0.50": float(precision_score(y, predicted, zero_division=0)),
        "Recall at 0.50": float(recall_score(y, predicted, zero_division=0)),
        "Specificity at 0.50": specificity,
        "F1 at 0.50": float(f1_score(y, predicted, zero_division=0)),
    }


def _metric_groups(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    rows = []
    valid = frame.loc[frame["Actual Label"].notna()].copy()
    for keys, group in valid.groupby(group_columns, dropna=False, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(group_columns, keys, strict=True))
        row.update(classification_metrics(
            group["Actual Label"], group["Predicted Probability"], group["Training Prior"]
        ))
        rows.append(row)
    return pd.DataFrame(rows, columns=group_columns + METRIC_COLUMNS)


def metrics_by_year(predictions: pd.DataFrame) -> pd.DataFrame:
    return _metric_groups(predictions, ["Target", "Model Variant", "Feature Set", "Evaluation Year"])


def pooled_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    result = _metric_groups(predictions, ["Target", "Model Variant", "Feature Set"])
    result.insert(3, "Scope", "POOLED_OOS")
    return result


def metrics_by_era(predictions: pd.DataFrame) -> pd.DataFrame:
    work = predictions.copy()
    work["Era"] = pd.cut(
        work["Evaluation Year"], bins=[2015, 2020, 2023, 2026],
        labels=["2016-2020", "2021-2023", "2024-2026"], include_lowest=True,
    ).astype("string")
    return _metric_groups(work, ["Target", "Model Variant", "Feature Set", "Era"])


def recent_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    recent = predictions.loc[predictions["Evaluation Year"].between(2024, 2026)]
    result = _metric_groups(recent, ["Target", "Model Variant", "Feature Set"])
    result.insert(3, "Period", "2024-2026")
    return result


def yearly_stability(yearly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in yearly.groupby(["Target", "Model Variant", "Feature Set"], sort=True):
        auc = group["ROC AUC"].dropna()
        bss = group["Brier Skill Score vs Training Prior"].dropna()
        rows.append({
            "Target": keys[0], "Model Variant": keys[1], "Feature Set": keys[2],
            "Valid Evaluation Years": int(len(auc)),
            "Years ROC AUC > 0.50": int(auc.gt(0.50).sum()),
            "Years ROC AUC > 0.55": int(auc.gt(0.55).sum()),
            "Years Positive Brier Skill": int(bss.gt(0.0).sum()),
            "Median Yearly ROC AUC": float(auc.median()) if len(auc) else np.nan,
            "Mean Yearly ROC AUC": float(auc.mean()) if len(auc) else np.nan,
            "Worst Yearly ROC AUC": float(auc.min()) if len(auc) else np.nan,
            "Best Yearly ROC AUC": float(auc.max()) if len(auc) else np.nan,
            "Std Yearly ROC AUC": float(auc.std(ddof=0)) if len(auc) else np.nan,
            "Total Yearly Positive Count": int(group["Positive Count"].sum()),
        })
    return pd.DataFrame(rows)


def calibration_diagnostics(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, summary = [], []
    valid = predictions.loc[predictions["Actual Label"].notna()].copy()
    group_columns = ["Target", "Model Variant", "Feature Set"]
    for keys, group in valid.groupby(group_columns, sort=True):
        probability = group["Predicted Probability"].astype(float)
        bucket_id = np.minimum(np.floor(probability * 10.0).astype(int), 9)
        total = len(group)
        weighted_error = 0.0
        for bucket in range(10):
            subset = group.loc[bucket_id.eq(bucket)]
            mean_probability = float(subset["Predicted Probability"].mean()) if len(subset) else np.nan
            observed = float(subset["Actual Label"].mean()) if len(subset) else np.nan
            error = abs(mean_probability - observed) if len(subset) else np.nan
            if len(subset):
                weighted_error += len(subset) / total * error
            rows.append({
                "Target": keys[0], "Model Variant": keys[1], "Feature Set": keys[2],
                "Bucket": f"{bucket / 10:.1f}-{(bucket + 1) / 10:.1f}",
                "Rows": len(subset), "Mean Predicted Probability": mean_probability,
                "Observed Success Rate": observed, "Calibration Error": error,
            })
        summary.append({
            "Target": keys[0], "Model Variant": keys[1], "Feature Set": keys[2],
            "Rows": total, "Expected Calibration Error": float(weighted_error),
        })
    return pd.DataFrame(rows), pd.DataFrame(summary)


def top_bucket_lift(predictions: pd.DataFrame) -> pd.DataFrame:
    work = predictions.loc[predictions["Actual Label"].notna()].copy()
    scopes = [("POOLED_OOS", work)]
    for start, end, label in [(2016, 2020, "2016-2020"), (2021, 2023, "2021-2023"), (2024, 2026, "2024-2026")]:
        scopes.append((label, work.loc[work["Evaluation Year"].between(start, end)]))
    rows = []
    for scope, scoped in scopes:
        for keys, group in scoped.groupby(["Target", "Model Variant", "Feature Set"], sort=True):
            ordered = group.sort_values(["Predicted Probability", "Signal ID"], ascending=[False, True], kind="mergesort")
            n = len(ordered)
            if not n:
                continue
            base_rate = float(ordered["Actual Label"].mean())
            for fraction, bucket_name in [(0.10, "TOP_10_PERCENT"), (0.20, "TOP_20_PERCENT")]:
                count = max(1, int(math.ceil(n * fraction)))
                subset = ordered.iloc[:count]
                rate = float(subset["Actual Label"].mean())
                rows.append({
                    "Target": keys[0], "Model Variant": keys[1], "Feature Set": keys[2],
                    "Scope": scope, "Bucket": bucket_name, "Rows": count,
                    "Success Rate": rate, "Overall Base Rate": base_rate,
                    "Lift": float(rate / base_rate) if base_rate > 0 else np.nan,
                })
            count = max(1, int(math.ceil(n * 0.20)))
            subset = ordered.iloc[-count:]
            rate = float(subset["Actual Label"].mean())
            rows.append({
                "Target": keys[0], "Model Variant": keys[1], "Feature Set": keys[2],
                "Scope": scope, "Bucket": "BOTTOM_20_PERCENT", "Rows": count,
                "Success Rate": rate, "Overall Base Rate": base_rate,
                "Lift": float(rate / base_rate) if base_rate > 0 else np.nan,
            })
    return pd.DataFrame(rows)
