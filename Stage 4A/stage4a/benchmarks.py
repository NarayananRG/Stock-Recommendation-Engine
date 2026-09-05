"""Frozen Stage 1 score-ranking benchmarks."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


def rule_score_benchmarks(predictions: pd.DataFrame, joint_predictions: pd.DataFrame) -> pd.DataFrame:
    direct = predictions.loc[predictions["Model Variant"].eq("DUMMY_PRIOR")].copy()
    joint = joint_predictions.loc[joint_predictions["Model Variant"].eq("DUMMY_PRIOR")].copy()
    work = pd.concat([direct, joint], ignore_index=True, sort=False)
    work = work.loc[work["Actual Label"].notna()]
    rows = []
    scopes = [("POOLED_OOS", work)] + [
        (label, work.loc[work["Evaluation Year"].between(start, end)])
        for start, end, label in [(2016, 2020, "2016-2020"), (2021, 2023, "2021-2023"), (2024, 2026, "2024-2026")]
    ]
    for scope, scoped in scopes:
        for target, group in scoped.groupby("Target", sort=True):
            y = group["Actual Label"].astype(int)
            for score_name in ["Actionability Score", "Technical Score"]:
                score = pd.to_numeric(group[score_name], errors="coerce")
                valid = score.notna()
                yy, ss = y.loc[valid], score.loc[valid]
                rows.append({
                    "Target": target, "Scope": scope, "Rule Score": score_name,
                    "Rows": int(len(yy)), "Positive Count": int(yy.sum()),
                    "ROC AUC": float(roc_auc_score(yy, ss)) if yy.nunique() == 2 else np.nan,
                    "Average Precision": float(average_precision_score(yy, ss)) if int(yy.sum()) else np.nan,
                    "Score Modified": False,
                })
    return pd.DataFrame(rows)
