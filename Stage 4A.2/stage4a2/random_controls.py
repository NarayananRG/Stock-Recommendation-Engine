from __future__ import annotations

import numpy as np
import pandas as pd


METRICS = ["Total Return %", "CAGR %", "Maximum Drawdown %", "Expectancy R", "Profit Factor", "Win Rate %", "Trade Count", "Average Exposure %", "Days Fully Cash", "Fill Rate %"]


def distribution_summary(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for k, group in raw.groupby("Daily K"):
        for metric in METRICS:
            values = pd.to_numeric(group[metric], errors="coerce").dropna()
            rows.append({"Daily K": k, "Metric": metric, "Random 2.5%": values.quantile(.025), "Random Median": values.median(), "Random 97.5%": values.quantile(.975)})
    return pd.DataFrame(rows)


def named_percentiles(named: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in named[named["Policy"].str.contains("_K", regex=False)].iterrows():
        k = int(str(row["Policy"])[-1])
        controls = raw[raw["Daily K"] == k]
        for metric in METRICS:
            values = pd.to_numeric(controls[metric], errors="coerce").dropna().to_numpy()
            value = float(row[metric])
            percentile = float((np.sum(values < value) + .5 * np.sum(values == value)) / len(values) * 100) if len(values) else np.nan
            rows.append({"Policy": row["Policy"], "Daily K": k, "Metric": metric, "Named Value": value, "Random Percentile %": percentile})
    return pd.DataFrame(rows)
