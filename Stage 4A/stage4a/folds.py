"""Independent target-specific chronological fold reconstruction."""
from __future__ import annotations

from typing import Any

import pandas as pd


def target_masks(frame: pd.DataFrame, target: str, spec: dict[str, Any], year: int) -> dict[str, Any]:
    asof = pd.to_datetime(frame["Signal Date"], errors="raise").dt.normalize()
    available = pd.to_datetime(frame[spec["available_date"]], errors="coerce").dt.normalize()
    applicable = frame[spec["applicable"]].fillna(False).astype(bool)
    status = frame[spec["status"]].astype("string")
    is_available = status.isin(spec["available_statuses"])
    target_present = frame[target].notna()
    year_mask = asof.dt.year.eq(int(year))
    if not year_mask.any():
        raise ValueError(f"No evaluation rows for {year}")
    evaluation_start = asof[year_mask].min()
    training = (
        applicable & is_available & target_present & available.notna()
        & available.lt(evaluation_start) & asof.lt(evaluation_start)
    )
    evaluation_label = year_mask & applicable & is_available & target_present
    return {
        "training": training,
        "evaluation_score": year_mask,
        "evaluation_label": evaluation_label,
        "evaluation_start": evaluation_start,
        "evaluation_end": asof[year_mask].max(),
        "available": available,
        "applicable": applicable,
        "is_available": is_available,
        "target_present": target_present,
        "status": status,
    }


def reconstruct_fold_audit(
    frame: pd.DataFrame,
    frozen_manifest: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    frozen = frozen_manifest.loc[
        frozen_manifest["Dataset"].eq("trade_opportunity")
        & frozen_manifest["Target"].isin(config["targets"].keys())
        & frozen_manifest["Evaluation Year"].isin(config["evaluation_years"])
    ].copy()
    frozen_lookup = frozen.set_index(["Target", "Evaluation Year"])
    rows = []
    for target, spec in config["targets"].items():
        for year in config["evaluation_years"]:
            masks = target_masks(frame, target, spec, int(year))
            training = masks["training"]
            score = masks["evaluation_score"]
            applicable = masks["applicable"]
            available = masks["is_available"]
            target_present = masks["target_present"]
            status = masks["status"]
            data_end = status.eq("DATA_END_CENSORED").fillna(False)
            not_applicable = status.eq("NOT_APPLICABLE").fillna(False)
            violation = training & masks["available"].ge(masks["evaluation_start"])
            actual = {
                "Training Rows": int(training.sum()),
                "Training Label Available Rows": int((training & available).sum()),
                "Evaluation Candidate Rows": int((score & applicable).sum()),
                "Evaluation Label Available Rows": int((score & available & target_present).sum()),
                "Evaluation Not Applicable Rows": int((score & not_applicable).sum()),
                "Evaluation Data-End Censored Rows": int((score & data_end).sum()),
                "Training Availability Violations": int(violation.sum()),
            }
            expected_row = frozen_lookup.loc[(target, int(year))]
            differences = {
                key: int(actual[key] - int(expected_row[key])) for key in actual
                if key != "Training Availability Violations"
            }
            rows.append({
                "Target": target,
                "Evaluation Year": int(year),
                "Evaluation Start": masks["evaluation_start"],
                "Evaluation End": masks["evaluation_end"],
                **{f"Reconstructed {key}": value for key, value in actual.items()},
                **{f"Frozen {key}": int(expected_row[key]) for key in actual},
                **{f"Difference {key}": value for key, value in differences.items()},
                "Unexplained Count Differences": int(sum(abs(value) for value in differences.values())),
                "Status": "PASS" if not any(differences.values()) and actual["Training Availability Violations"] == 0 else "FAIL",
            })
    result = pd.DataFrame(rows)
    if not result["Status"].eq("PASS").all():
        raise RuntimeError("Chronological fold reconstruction differs from the frozen Stage 3.1 contract")
    return result


def modeling_masks(
    frame: pd.DataFrame,
    target: str,
    spec: dict[str, Any],
    year: int,
    sanity_tickers: list[str] | None = None,
) -> dict[str, Any]:
    masks = target_masks(frame, target, spec, year)
    if sanity_tickers:
        ticker_mask = frame["Ticker"].isin(sanity_tickers)
        masks["training"] = masks["training"] & ticker_mask
        masks["evaluation_score"] = masks["evaluation_score"] & ticker_mask
        masks["evaluation_label"] = masks["evaluation_label"] & ticker_mask
    return masks
