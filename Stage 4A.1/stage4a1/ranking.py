"""One canonical bucket-selection implementation for points and bootstrap samples.

Integer row multiplicities represent repeated observations, never deduplication.
Buckets use the frozen Stage 4A max(1, ceil(n * fraction)) convention.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def canonical_order(probabilities, signal_ids) -> np.ndarray:
    return np.lexsort((np.asarray(signal_ids, dtype=str), -np.asarray(probabilities, dtype=float)))


def bucket_size(total, fraction: float) -> np.ndarray:
    return np.maximum(1, np.ceil(np.asarray(total) * fraction).astype(np.int64))


def bucket_membership(probabilities, signal_ids, multiplicities, fraction: float, bottom: bool = False) -> np.ndarray:
    """Return selected occurrence counts in the ORIGINAL row order.

    Taking the tail of the canonical order requires reversing that order for
    accumulation; it does not involve another sort. A boundary can select only
    some occurrences of a repeatedly sampled row.
    """
    weights = np.asarray(multiplicities)
    if weights.ndim == 1:
        weights = weights[None, :]
    if weights.ndim != 2 or weights.shape[1] != len(probabilities):
        raise ValueError("Row multiplicity shape differs from probabilities")
    if not np.isfinite(weights).all() or (weights < 0).any() or (weights != np.floor(weights)).any():
        raise ValueError("Observation multiplicities must be nonnegative integers")
    if (weights.sum(axis=1) == 0).any():
        raise ValueError("Cannot rank an empty sample")
    order = canonical_order(probabilities, signal_ids)
    if bottom:
        order = order[::-1]
    ranked = weights[:, order]
    before = np.cumsum(ranked, axis=1) - ranked
    selected = np.minimum(ranked, np.maximum(0, bucket_size(weights.sum(axis=1), fraction)[:, None] - before))
    result = np.empty_like(selected)
    result[:, order] = selected
    return result


def bucket_metrics(group: pd.DataFrame, multiplicities=None) -> pd.DataFrame:
    """Shared rates and lifts; points use one occurrence per input row."""
    weights = np.ones((1, len(group)), dtype=np.int64) if multiplicities is None else np.asarray(multiplicities)
    if weights.ndim == 1:
        weights = weights[None, :]
    y = group["Actual Label"].to_numpy(dtype=int)
    p = group["Predicted Probability"].to_numpy(dtype=float)
    ids = group["Signal ID"].to_numpy(dtype=str)
    totals = weights.sum(axis=1)
    base = (weights * y[None, :]).sum(axis=1) / totals
    result = {"Rows": totals.astype(int), "Overall Success Rate": base}
    for label, fraction, bottom in [("Top 10%", .1, False), ("Top 20%", .2, False), ("Bottom 20%", .2, True)]:
        selected = bucket_membership(p, ids, weights, fraction, bottom)
        counts = selected.sum(axis=1)
        rate = (selected * y[None, :]).sum(axis=1) / counts
        result[label + " Rows"] = counts.astype(int)
        result[label + " Success Rate"] = rate
        result[label + " Lift"] = np.divide(rate, base, out=np.full(len(base), np.nan), where=base > 0)
    return pd.DataFrame(result)
