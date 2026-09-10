from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _metrics(returns: np.ndarray) -> dict[str, float]:
    wealth = np.cumprod(1.0 + returns)
    total = float(wealth[-1] - 1.0)
    years = len(returns) / 252.0
    dd = wealth / np.maximum.accumulate(wealth) - 1.0
    return {"Terminal Return %": total * 100, "CAGR %": ((1 + total) ** (1 / years) - 1) * 100,
            "Mean Daily Return %": float(np.mean(returns) * 100), "Annualized Volatility %": float(np.std(returns, ddof=1) * math.sqrt(252) * 100),
            "Maximum Drawdown %": float(np.min(dd) * 100)}


def paired_block_bootstrap(policy: str, policy_returns: np.ndarray, rule_returns: np.ndarray, block_length: int, replicates: int = 2000, seed: int = 42,
                           policy_exposure: np.ndarray | None = None, rule_exposure: np.ndarray | None = None) -> pd.DataFrame:
    if len(policy_returns) != len(rule_returns):
        raise ValueError("Paired return arrays differ in length")
    n = len(policy_returns)
    policy_exposure = np.zeros(n) if policy_exposure is None else policy_exposure
    rule_exposure = np.zeros(n) if rule_exposure is None else rule_exposure
    rng = np.random.default_rng(seed)
    max_start = n - block_length
    rows = []
    for replicate in range(replicates):
        starts = rng.integers(0, max_start + 1, size=math.ceil(n / block_length))
        indices = np.concatenate([np.arange(start, start + block_length) for start in starts])[:n]
        pm = _metrics(policy_returns[indices]); rm = _metrics(rule_returns[indices])
        pm["Average Exposure %"] = float(np.mean(policy_exposure[indices]) * 100)
        rm["Average Exposure %"] = float(np.mean(rule_exposure[indices]) * 100)
        row = {"Policy": policy, "Comparator": f"R0_K{policy[-1]}", "Block Length": block_length, "Replicate": replicate, "Sample Length": n}
        for key in pm:
            row[f"Policy {key}"] = pm[key]; row[f"Rule {key}"] = rm[key]; row[f"Delta {key}"] = pm[key] - rm[key]
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_bootstrap(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    delta_columns = [c for c in frame.columns if c.startswith("Delta ")]
    for (policy, block), group in frame.groupby(["Policy", "Block Length"]):
        for column in delta_columns:
            values = group[column]
            rows.append({"Policy": policy, "Comparator": f"R0_K{policy[-1]}", "Block Length": block, "Metric": column.removeprefix("Delta "),
                         "Delta 2.5%": values.quantile(.025), "Delta Median": values.median(), "Delta 97.5%": values.quantile(.975), "P(Delta>0) %": (values > 0).mean() * 100})
    return pd.DataFrame(rows)
