"""Identity-sample parity, including exact shared loss and ranking paths."""
import numpy as np
import pandas as pd
from .bootstrap import vector_metrics
from .metrics import classification_metrics
from .ranking import bucket_metrics


def consistency_audits(frame):
    rows, ranking_rows = [], []
    valid = frame.loc[frame["Actual Label"].notna()]
    for (mode, target, model), group in valid.groupby(["Mode", "Target", "Model Variant"], sort=True):
        group = group.sort_values("Signal ID", kind="mergesort")
        dates = pd.Index(sorted(pd.to_datetime(group["Signal Date"]).unique()))
        actual = vector_metrics(group, np.ones((1, len(dates)), dtype=int), dates).iloc[0].to_dict()
        actual["Overall Success Rate"] = actual["Prevalence"]
        point = classification_metrics(group["Actual Label"], group["Predicted Probability"], group["Training Prior"])
        point.update(bucket_metrics(group).iloc[0].to_dict())
        for metric, value in point.items():
            observed = actual[metric]
            tolerance = 0.0 if metric == "Log Loss" or metric in bucket_metrics(group).columns else 1e-14
            passed = bool(np.isclose(value, observed, rtol=0, atol=tolerance, equal_nan=True))
            rows.append({"Mode": mode, "Target": target, "Model Variant": model, "Metric": metric,
                         "Point Value": value, "Identity Bootstrap Value": observed,
                         "Absolute Difference": abs(value - observed), "Absolute Tolerance": tolerance,
                         "Status": "PASS" if passed else "FAIL"})
        for bucket in ["Top 10%", "Top 20%", "Bottom 20%"]:
            ranking_rows.append({"Mode": mode, "Target": target, "Model Variant": model,
                "Context": "Point and identity bootstrap", "Bucket": bucket,
                "Ranking Rule": "Probability DESC; Signal ID ASC; bottom takes canonical tail",
                "Tie Rule": "Signal ID ASC in canonical order", "Bucket Size": point[bucket + " Rows"],
                "Shared Helper": "stage4a1.ranking.bucket_metrics / bucket_membership",
                "Status": "PASS" if all(r["Status"] == "PASS" for r in rows if r["Mode"] == mode and r["Target"] == target and r["Model Variant"] == model and r["Metric"].startswith(bucket)) else "FAIL"})
    return pd.DataFrame(rows), pd.DataFrame(ranking_rows)
