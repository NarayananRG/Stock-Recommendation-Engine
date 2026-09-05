"""Independent chronological fold construction for transfer and primary-only modes."""
from __future__ import annotations

from typing import Any

import pandas as pd


def masks(frame: pd.DataFrame, target: str, spec: dict[str, Any], year: int, cohort: str | None) -> dict[str, Any]:
    signal_date = pd.to_datetime(frame["Signal Date"]).dt.normalize()
    available_date = pd.to_datetime(frame[spec["available_date"]], errors="coerce").dt.normalize()
    applicable = frame[spec["applicable"]].fillna(False).astype(bool)
    status = frame[spec["status"]].astype("string")
    resolved = status.isin(spec["available_statuses"]) & frame[target].notna() & available_date.notna()
    year_mask = signal_date.dt.year.eq(int(year))
    if not year_mask.any():
        raise ValueError(f"No evaluation rows for {year}")
    evaluation_start = signal_date.loc[year_mask].min()
    cohort_mask = pd.Series(True, index=frame.index) if cohort is None else frame["Dataset Cohort"].eq(cohort)
    training = applicable & resolved & signal_date.lt(evaluation_start) & available_date.lt(evaluation_start) & cohort_mask
    score = year_mask & cohort_mask
    label = score & applicable & resolved
    return {"training": training, "evaluation_score": score, "evaluation_label": label, "evaluation_start": evaluation_start, "available_date": available_date, "signal_date": signal_date, "applicable": applicable, "status": status}


def fold_audit(frame: pd.DataFrame, config: dict[str, Any], years: list[int]) -> pd.DataFrame:
    rows = []
    for mode, cohort in [("TRANSFER", None), ("PRIMARY_ONLY", config["primary_cohort"])]:
        for target, spec in config["targets"].items():
            for year in years:
                item = masks(frame, target, spec, year, cohort)
                train = frame.loc[item["training"]]
                evaluation = item["evaluation_score"]
                labeled = item["evaluation_label"]
                data_end = item["status"].eq("DATA_END_CENSORED").fillna(False)
                not_applicable = item["status"].eq("NOT_APPLICABLE").fillna(False)
                max_available = item["available_date"].loc[item["training"]].max()
                max_signal = item["signal_date"].loc[item["training"]].max()
                rows.append({
                    "Training Mode": mode, "Target": target, "Evaluation Year": year,
                    "Evaluation Start": item["evaluation_start"],
                    "Training Rows": len(train), "Training Positive Rows": int(train[target].astype(int).sum()),
                    "Training Negative Rows": int(len(train) - train[target].astype(int).sum()),
                    "Training Prevalence": float(train[target].astype(int).mean()),
                    "Evaluation Candidate Rows": int(evaluation.sum()), "Evaluation Label-Available Rows": int(labeled.sum()),
                    "Evaluation Data-End Censored Rows": int((evaluation & data_end).sum()),
                    "Evaluation Not-Applicable Rows": int((evaluation & not_applicable).sum()),
                    "Minimum Training Signal Date": item["signal_date"].loc[item["training"]].min(),
                    "Maximum Training Signal Date": max_signal, "Maximum Training Label-Available Date": max_available,
                    "Chronology Violations": int(pd.notna(max_available) and max_available >= item["evaluation_start"]),
                    "Both Classes": int(train[target].nunique(dropna=True)) == 2,
                    "Status": "PASS" if pd.notna(max_available) and max_available < item["evaluation_start"] and train[target].nunique(dropna=True) == 2 else "FAIL",
                })
    result = pd.DataFrame(rows)
    if not result["Status"].eq("PASS").all():
        raise RuntimeError("Stage 4A.1 fold audit failed")
    return result
