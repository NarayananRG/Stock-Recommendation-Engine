"""Deterministic overlap-aware date-block bootstrap with paired samples."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from .ranking import bucket_metrics
from . import metrics as shared_metrics


SCOPES = {
    "POOLED_2016_2026": (2016, 2026),
    "ERA_2016_2020": (2016, 2020),
    "ERA_2021_2023": (2021, 2023),
    "RECENT_2024_2026": (2024, 2026),
}


def sample_date_counts(n_dates: int, block_length: int, replicates: int, rng: np.random.Generator) -> np.ndarray:
    if n_dates <= 0:
        raise ValueError("Bootstrap scope has no dates")
    effective = min(block_length, n_dates)
    blocks = math.ceil(n_dates / effective)
    result = np.zeros((replicates, n_dates), dtype=np.int16)
    offsets = np.arange(effective)
    for replicate in range(replicates):
        starts = rng.integers(0, n_dates - effective + 1, size=blocks)
        positions = (starts[:, None] + offsets).reshape(-1)[:n_dates]
        result[replicate] = np.bincount(positions, minlength=n_dates)
    return result


def _auc_ap(weights: np.ndarray, y: np.ndarray, probability: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(probability, kind="mergesort")
    p = probability[order]; labels = y[order]; w = weights[:, order]
    pos = w * labels; neg = w * (1 - labels)
    positives = pos.sum(axis=1); negatives = neg.sum(axis=1)
    numerator = np.zeros(len(w), dtype=float)
    start = 0
    neg_before = np.zeros(len(w), dtype=float)
    while start < len(p):
        end = start + 1
        while end < len(p) and p[end] == p[start]:
            end += 1
        tie_pos = pos[:, start:end].sum(axis=1); tie_neg = neg[:, start:end].sum(axis=1)
        numerator += tie_pos * (neg_before + 0.5 * tie_neg)
        neg_before += tie_neg
        start = end
    auc = np.divide(numerator, positives * negatives, out=np.full(len(w), np.nan), where=(positives > 0) & (negatives > 0))

    order = np.argsort(-probability, kind="mergesort")
    p = probability[order]; labels = y[order]; w = weights[:, order]
    pos = w * labels; total = w
    cumulative_pos = np.zeros(len(w)); cumulative_total = np.zeros(len(w)); ap_num = np.zeros(len(w))
    start = 0
    while start < len(p):
        end = start + 1
        while end < len(p) and p[end] == p[start]:
            end += 1
        group_pos = pos[:, start:end].sum(axis=1); group_total = total[:, start:end].sum(axis=1)
        cumulative_pos += group_pos; cumulative_total += group_total
        precision = np.divide(cumulative_pos, cumulative_total, out=np.zeros(len(w)), where=cumulative_total > 0)
        ap_num += group_pos * precision
        start = end
    ap = np.divide(ap_num, positives, out=np.full(len(w), np.nan), where=positives > 0)
    return auc, ap


def vector_metrics(group: pd.DataFrame, date_counts: np.ndarray, dates: pd.Index) -> pd.DataFrame:
    lookup = {pd.Timestamp(date): i for i, date in enumerate(dates)}
    date_index = np.array([lookup[pd.Timestamp(date)] for date in pd.to_datetime(group["Signal Date"])], dtype=int)
    weights = date_counts[:, date_index].astype(float)
    y = group["Actual Label"].astype(int).to_numpy(); p = group["Predicted Probability"].astype(float).to_numpy(); prior = group["Training Prior"].astype(float).to_numpy()
    totals = weights.sum(axis=1); positives = weights @ y; prevalence = np.divide(positives, totals, out=np.full(len(totals), np.nan), where=totals > 0)
    auc, ap = _auc_ap(weights, y, p)
    brier = np.divide(weights @ ((y - p) ** 2), totals, out=np.full(len(totals), np.nan), where=totals > 0)
    benchmark = np.divide(weights @ ((y - prior) ** 2), totals, out=np.full(len(totals), np.nan), where=totals > 0)
    bss = np.divide(brier, benchmark, out=np.full(len(totals), np.nan), where=benchmark > 0); bss = 1 - bss
    # Explicit repeated observations preserve the point-metric computation path.
    loss = np.array([
        shared_metrics.fixed_log_loss(np.repeat(y, count.astype(int)), np.repeat(p, count.astype(int)))
        if count.sum() else np.nan for count in weights
    ])
    pred = (p >= .5).astype(int); tp = weights @ ((pred == 1) & (y == 1)); tn = weights @ ((pred == 0) & (y == 0)); fp = weights @ ((pred == 1) & (y == 0)); fn = weights @ ((pred == 0) & (y == 1))
    accuracy = np.divide(tp + tn, totals, out=np.full(len(totals), np.nan), where=totals > 0)
    precision = np.divide(tp, tp + fp, out=np.zeros(len(totals)), where=(tp + fp) > 0)
    recall = np.divide(tp, tp + fn, out=np.zeros(len(totals)), where=(tp + fn) > 0)
    specificity = np.divide(tn, tn + fp, out=np.full(len(totals), np.nan), where=(tn + fp) > 0)
    f1 = np.divide(2 * precision * recall, precision + recall, out=np.zeros(len(totals)), where=(precision + recall) > 0)
    ranking = bucket_metrics(group, weights)
    result = pd.DataFrame({
        "Rows": totals.astype(int), "Positive Count": positives.astype(int), "Prevalence": prevalence,
        "ROC AUC": auc, "Average Precision": ap, "Brier Score": brier, "Brier Benchmark Score": benchmark,
        "Brier Skill Score vs Training Prior": bss, "Log Loss": loss, "Accuracy at 0.50": accuracy,
        "Precision at 0.50": precision, "Recall at 0.50": recall, "Specificity at 0.50": specificity, "F1 at 0.50": f1,
    })
    for column in ranking:
        if column not in {"Rows", "Overall Success Rate"}:
            result[column] = ranking[column]
    return result


def run_bootstrap(frame: pd.DataFrame, block_length: int, replicates: int, seed: int) -> pd.DataFrame:
    valid = frame.loc[frame["Actual Label"].notna()].copy()
    valid["Signal Date"] = pd.to_datetime(valid["Signal Date"]).dt.normalize()
    rows = []
    rng = np.random.default_rng(seed)
    for target in sorted(valid["Target"].unique()):
        target_frame = valid.loc[valid["Target"].eq(target)]
        for scope, (start, end) in SCOPES.items():
            scoped = target_frame.loc[target_frame["Evaluation Year"].between(start, end)]
            dates = pd.Index(sorted(scoped["Signal Date"].unique()))
            if len(dates) == 0:
                continue
            counts = sample_date_counts(len(dates), block_length, replicates, rng)
            for (mode, model, feature_set), group in scoped.groupby(["Mode", "Model Variant", "Feature Set"], sort=True):
                metrics = vector_metrics(group.sort_values("Signal ID", kind="mergesort"), counts, dates)
                metrics.insert(0, "Replicate", np.arange(replicates, dtype=int)); metrics.insert(0, "Scope", scope)
                metrics.insert(0, "Feature Set", feature_set); metrics.insert(0, "Model Variant", model); metrics.insert(0, "Target", target); metrics.insert(0, "Mode", mode)
                metrics.insert(0, "Block Length", block_length)
                rows.append(metrics)
    result = pd.concat(rows, ignore_index=True)
    return result.sort_values(["Scope", "Target", "Model Variant", "Mode", "Replicate"], kind="mergesort").reset_index(drop=True)


def summarize_bootstrap(raw: pd.DataFrame) -> pd.DataFrame:
    id_columns = ["Block Length", "Mode", "Target", "Model Variant", "Feature Set", "Scope"]
    metric_columns = [column for column in raw.columns if column not in id_columns + ["Replicate"]]
    rows = []
    for keys, group in raw.groupby(id_columns, sort=True):
        for metric in metric_columns:
            values = group[metric].dropna()
            rows.append(dict(zip(id_columns, keys, strict=True)) | {"Metric": metric, "Valid Replicates": len(values), "2.5%": values.quantile(.025), "Median": values.quantile(.5), "97.5%": values.quantile(.975)})
    return pd.DataFrame(rows)


def paired_comparison(raw: pd.DataFrame, point_metrics: pd.DataFrame, point_ranking: pd.DataFrame) -> pd.DataFrame:
    keys = ["Target", "Model Variant", "Scope"]
    metrics = [("ROC AUC", False), ("Brier Score", False), ("Brier Skill Score vs Training Prior", False), ("Top 20% Lift", True)]
    rows = []
    for values, group in raw.groupby(keys, sort=True):
        base = {"Target": values[0], "Model Variant": values[1], "Scope": values[2]}
        feature_set = group["Feature Set"].iloc[0]
        row = base | {"Feature Set": feature_set, "Block Length": int(group["Block Length"].iloc[0])}
        for metric, ranking in metrics:
            pivot = group.pivot(index="Replicate", columns="Mode", values=metric)
            delta = pivot["PRIMARY_ONLY"] - pivot["TRANSFER"]
            source = point_ranking if ranking else point_metrics
            selected = source.loc[source["Target"].eq(values[0]) & source["Model Variant"].eq(values[1]) & source["Scope"].eq(values[2])]
            transfer = float(selected.loc[selected["Mode"].eq("TRANSFER"), metric].iloc[0])
            primary = float(selected.loc[selected["Mode"].eq("PRIMARY_ONLY"), metric].iloc[0])
            row[f"TRANSFER {metric}"] = transfer; row[f"PRIMARY_ONLY {metric}"] = primary; row[f"Delta {metric}"] = primary - transfer
            row[f"Delta {metric} 2.5%"] = delta.quantile(.025); row[f"Delta {metric} Median"] = delta.quantile(.5); row[f"Delta {metric} 97.5%"] = delta.quantile(.975); row[f"Delta {metric} Valid Replicates"] = delta.notna().sum()
        rows.append(row)
    return pd.DataFrame(rows)
