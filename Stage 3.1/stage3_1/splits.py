"""Target-specific historical walk-forward / pseudo-OOS manifests."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


def target_specifications(config: Mapping[str, Any]) -> list[dict[str, str]]:
    specs = [
        {"target": "ENTRY_FILLED", "dataset": "trade_opportunity", "task": "BINARY_CLASSIFICATION",
         "asof": "Signal Date", "available": "ENTRY_LABEL_AVAILABLE_DATE", "applicable": "ENTRY_APPLICABLE",
         "status": "ENTRY_STATUS", "available_status": "FILLED|FILLED_INVALID_RISK|NOT_FILLED"},
        {"target": "T1_BEFORE_STOP_63", "dataset": "trade_opportunity", "task": "BINARY_CLASSIFICATION",
         "asof": "Signal Date", "available": "T1_LABEL_AVAILABLE_DATE", "applicable": "T1_APPLICABLE",
         "status": "T1_STATUS", "available_status": "AVAILABLE"},
        {"target": "T2_BEFORE_STOP_63", "dataset": "trade_opportunity", "task": "BINARY_CLASSIFICATION",
         "asof": "Signal Date", "available": "T2_LABEL_AVAILABLE_DATE", "applicable": "T2_APPLICABLE",
         "status": "T2_STATUS", "available_status": "AVAILABLE"},
        {"target": "TIME_TO_T1_SESSIONS", "dataset": "trade_opportunity", "task": "CONDITIONAL_REGRESSION",
         "asof": "Signal Date", "available": "TIME_TO_T1_AVAILABLE_DATE", "applicable": "TIME_TO_T1_APPLICABLE",
         "status": "TIME_TO_T1_STATUS", "available_status": "AVAILABLE"},
        {"target": "TIME_TO_T2_SESSIONS", "dataset": "trade_opportunity", "task": "CONDITIONAL_REGRESSION",
         "asof": "Signal Date", "available": "TIME_TO_T2_AVAILABLE_DATE", "applicable": "TIME_TO_T2_APPLICABLE",
         "status": "TIME_TO_T2_STATUS", "available_status": "AVAILABLE"},
        {"target": "D1_SHADOW_NET_R", "dataset": "trade_opportunity", "task": "REGRESSION",
         "asof": "Signal Date", "available": "D1_SHADOW_LABEL_AVAILABLE_DATE", "applicable": "D1_SHADOW_APPLICABLE",
         "status": "D1_SHADOW_STATUS", "available_status": "AVAILABLE"},
        {"target": "D1_EXIT_NEXT_SESSION", "dataset": "d1_position_day", "task": "BINARY_CLASSIFICATION",
         "asof": "Management Date", "available": "D1_LABEL_AVAILABLE_DATE", "applicable": "D1_FINAL_APPLICABLE",
         "status": "D1_FINAL_STATUS", "available_status": "AVAILABLE"},
        {"target": "D1_REMAINING_NET_R", "dataset": "d1_position_day", "task": "REGRESSION",
         "asof": "Management Date", "available": "D1_LABEL_AVAILABLE_DATE", "applicable": "D1_FINAL_APPLICABLE",
         "status": "D1_FINAL_STATUS", "available_status": "AVAILABLE"},
    ]
    for horizon in config["forward_horizons"]:
        specs.append({
            "target": f"FWD_CLOSE_RETURN_{horizon}_ENTRY_INCLUSIVE_PCT",
            "dataset": "trade_opportunity", "task": "REGRESSION", "asof": "Signal Date",
            "available": f"FWD_{horizon}_AVAILABLE_DATE", "applicable": f"FWD_{horizon}_APPLICABLE",
            "status": f"FWD_{horizon}_STATUS", "available_status": "AVAILABLE",
        })
    for horizon in config["position_day_horizons"]:
        for suffix in ("RETURN", "MFE", "MAE"):
            specs.append({
                "target": f"NEXT_{horizon}_SESSION_{suffix}",
                "dataset": "d1_position_day", "task": "REGRESSION", "asof": "Management Date",
                "available": f"NEXT_{horizon}_SESSION_LABEL_AVAILABLE_DATE",
                "applicable": f"NEXT_{horizon}_SESSION_APPLICABLE",
                "status": f"NEXT_{horizon}_SESSION_STATUS", "available_status": "AVAILABLE",
            })
    return specs


def build_walk_forward_manifest(
    opportunities: pd.DataFrame,
    position_day: pd.DataFrame,
    config: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    datasets = {"trade_opportunity": opportunities, "d1_position_day": position_day}
    manifest_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for spec in target_specifications(config):
        frame = datasets[spec["dataset"]]
        asof = pd.to_datetime(frame[spec["asof"]], errors="coerce").dt.normalize()
        available = pd.to_datetime(frame[spec["available"]], errors="coerce").dt.normalize()
        applicable = frame[spec["applicable"]].fillna(False).astype(bool)
        status = frame[spec["status"]].astype("string")
        allowed_status = set(spec["available_status"].split("|"))
        is_available = status.isin(allowed_status)
        data_end = status.eq("DATA_END_CENSORED").fillna(False)
        not_applicable = status.eq("NOT_APPLICABLE").fillna(False)
        target_present = frame[spec["target"]].notna()

        before_asof = available.notna() & (available < asof)
        unavailable_with_value = ~is_available & target_present
        not_applicable_with_value = not_applicable & target_present
        censored_with_value = data_end & target_present
        audit_rows.append({
            "Dataset": spec["dataset"],
            "Target": spec["target"],
            "Total Rows": len(frame),
            "Applicable Rows": int(applicable.sum()),
            "Available Rows": int(is_available.sum()),
            "Not Applicable Rows": int(not_applicable.sum()),
            "Data-End Censored Rows": int(data_end.sum()),
            "Availability Before As-Of Violations": int(before_asof.sum()),
            "Unavailable Label With Value Violations": int(unavailable_with_value.sum()),
            "Not Applicable Label With Value Violations": int(not_applicable_with_value.sum()),
            "Data-End Censored Label With Manufactured Value Violations": int(censored_with_value.sum()),
            "Training Availability Violations": 0,
            "Status": "PASS" if not any([
                before_asof.any(), unavailable_with_value.any(),
                not_applicable_with_value.any(), censored_with_value.any(),
            ]) else "FAIL",
        })

        for year in config["evaluation_years"]:
            year_mask = asof.dt.year.eq(int(year))
            if not year_mask.any():
                continue
            evaluation_start = asof[year_mask].min()
            evaluation_end = asof[year_mask].max()
            training = (
                applicable & is_available & target_present & available.notna()
                & (available < evaluation_start) & (asof < evaluation_start)
            )
            violation = training & (available >= evaluation_start)
            ambiguous_column = "OUTCOME_SEQUENCE_AMBIGUOUS" if spec["dataset"] == "trade_opportunity" else "ENTRY_DAY_SEQUENCE_AMBIGUOUS"
            ambiguous = frame[ambiguous_column].fillna(False).astype(bool) if ambiguous_column in frame else pd.Series(False, index=frame.index)
            manifest_rows.append({
                "Method": "HISTORICAL WALK-FORWARD / PSEUDO-OOS",
                "Dataset": spec["dataset"],
                "Target": spec["target"],
                "Model Task Type": spec["task"],
                "Evaluation Year": int(year),
                "Evaluation Start": evaluation_start,
                "Evaluation End": evaluation_end,
                "Training Rows": int(training.sum()),
                "Training Label Available Rows": int((training & is_available).sum()),
                "Evaluation Candidate Rows": int((year_mask & applicable).sum()),
                "Evaluation Label Available Rows": int((year_mask & is_available & target_present).sum()),
                "Evaluation Not Applicable Rows": int((year_mask & not_applicable).sum()),
                "Evaluation Data-End Censored Rows": int((year_mask & data_end).sum()),
                "Training As-Of Date Min": asof[training].min() if training.any() else pd.NaT,
                "Training As-Of Date Max": asof[training].max() if training.any() else pd.NaT,
                "Training Label Availability Max": available[training].max() if training.any() else pd.NaT,
                "Training Availability Violations": int(violation.sum()),
                "Ambiguous Rows Count": int((year_mask & ambiguous).sum()),
            })
    return pd.DataFrame(manifest_rows), pd.DataFrame(audit_rows)
