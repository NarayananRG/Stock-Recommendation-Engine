"""Label-specific historical walk-forward / pseudo-OOS split manifests."""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


def target_specifications(config: Mapping[str, Any]) -> list[dict[str, str]]:
    specs = [
        {"target": "ENTRY_FILLED", "dataset": "trade_opportunity", "asof": "Signal Date", "available": "ENTRY_LABEL_AVAILABLE_DATE", "censored": "ENTRY_CENSORED"},
        {"target": "T1_BEFORE_STOP_63", "dataset": "trade_opportunity", "asof": "Signal Date", "available": "T1_LABEL_AVAILABLE_DATE", "censored": "T1_CENSORED"},
        {"target": "T2_BEFORE_STOP_63", "dataset": "trade_opportunity", "asof": "Signal Date", "available": "T2_LABEL_AVAILABLE_DATE", "censored": "T2_CENSORED"},
        {"target": "TIME_TO_T1_SESSIONS", "dataset": "trade_opportunity", "asof": "Signal Date", "available": "T1_LABEL_AVAILABLE_DATE", "censored": "T1_CENSORED"},
        {"target": "TIME_TO_T2_SESSIONS", "dataset": "trade_opportunity", "asof": "Signal Date", "available": "T2_LABEL_AVAILABLE_DATE", "censored": "T2_CENSORED"},
        {"target": "D1_SHADOW_NET_R", "dataset": "trade_opportunity", "asof": "Signal Date", "available": "D1_SHADOW_LABEL_AVAILABLE_DATE", "censored": "D1_SHADOW_CENSORED"},
        {"target": "D1_EXIT_NEXT_SESSION", "dataset": "d1_position_day", "asof": "Management Date", "available": "D1_LABEL_AVAILABLE_DATE", "censored": "D1_LABEL_CENSORED"},
        {"target": "D1_REMAINING_NET_R", "dataset": "d1_position_day", "asof": "Management Date", "available": "D1_LABEL_AVAILABLE_DATE", "censored": "D1_LABEL_CENSORED"},
    ]
    for horizon in config["forward_horizons"]:
        specs.append({"target": f"FWD_CLOSE_RETURN_{horizon}_PCT", "dataset": "trade_opportunity", "asof": "Signal Date", "available": f"FWD_{horizon}_AVAILABLE_DATE", "censored": f"FWD_{horizon}_CENSORED"})
    for horizon in config["position_day_horizons"]:
        for suffix in ("RETURN", "MFE", "MAE"):
            specs.append({"target": f"NEXT_{horizon}_SESSION_{suffix}", "dataset": "d1_position_day", "asof": "Management Date", "available": f"NEXT_{horizon}_SESSION_LABEL_AVAILABLE_DATE", "censored": f"NEXT_{horizon}_SESSION_CENSORED"})
    return specs


def build_walk_forward_manifest(
    opportunities: pd.DataFrame,
    position_day: pd.DataFrame,
    config: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    datasets = {"trade_opportunity": opportunities, "d1_position_day": position_day}
    rows, audits = [], []
    for spec in target_specifications(config):
        frame = datasets[spec["dataset"]].copy()
        if spec["target"] not in frame or spec["available"] not in frame or spec["censored"] not in frame:
            continue
        asof = pd.to_datetime(frame[spec["asof"]], errors="coerce").dt.normalize()
        available = pd.to_datetime(frame[spec["available"]], errors="coerce").dt.normalize()
        censored = frame[spec["censored"]].fillna(True).astype(bool)
        target_present = frame[spec["target"]].notna()
        bad_before_asof = available.notna() & (available < asof)
        bad_censored_label = censored & target_present
        audits.append({
            "Target": spec["target"], "Dataset": spec["dataset"], "Rows": len(frame),
            "Available Labels": int(available.notna().sum()), "Censored Rows": int(censored.sum()),
            "Availability Before As-Of Violations": int(bad_before_asof.sum()),
            "Censored Rows With Manufactured Label": int(bad_censored_label.sum()),
            "Status": "PASS" if not bad_before_asof.any() and not bad_censored_label.any() else "FAIL",
        })
        for year in config["evaluation_years"]:
            year_mask = asof.dt.year == int(year)
            if not year_mask.any():
                continue
            evaluation_start = asof[year_mask].min()
            evaluation_end = asof[year_mask].max()
            training = available.notna() & (available < evaluation_start) & (~censored) & target_present & (asof < evaluation_start)
            evaluation = year_mask & (~censored) & target_present
            ambiguous_column = "OUTCOME_SEQUENCE_AMBIGUOUS" if spec["dataset"] == "trade_opportunity" else "ENTRY_DAY_SEQUENCE_AMBIGUOUS"
            ambiguous = frame[ambiguous_column].fillna(False).astype(bool) if ambiguous_column in frame else pd.Series(False, index=frame.index)
            rows.append({
                "Method": "HISTORICAL WALK-FORWARD / PSEUDO-OOS",
                "Dataset": spec["dataset"],
                "Target": spec["target"],
                "Evaluation Year": int(year),
                "Evaluation Start": evaluation_start,
                "Evaluation End": evaluation_end,
                "Training Signal Date Min": asof[training].min() if training.any() else pd.NaT,
                "Training Signal Date Max": asof[training].max() if training.any() else pd.NaT,
                "Training Label Availability Cutoff": evaluation_start,
                "Training Rows": int(training.sum()),
                "Evaluation Rows": int(evaluation.sum()),
                "Censored Rows Excluded": int((year_mask & censored).sum()),
                "Ambiguous Rows Count": int((year_mask & ambiguous).sum()),
                "Training Availability Violations": int((training & (available >= evaluation_start)).sum()),
            })
    manifest = pd.DataFrame(rows)
    audit = pd.DataFrame(audits)
    return manifest, audit
