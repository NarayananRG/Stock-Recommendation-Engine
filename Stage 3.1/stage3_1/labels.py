"""Target-specific applicability, availability, and censoring semantics."""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


def _valid_entry_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["ENTRY_FILLED"].fillna(False).astype(bool)
        & frame["ENTRY_RISK_VALID"].fillna(False).astype(bool)
    )


def _reason_for_invalid_entry(frame: pd.DataFrame) -> pd.Series:
    filled = frame["ENTRY_FILLED"].fillna(False).astype(bool)
    return pd.Series(np.where(filled, "INVALID_ENTRY_RISK", "NO_ENTRY"), index=frame.index, dtype="string")


def harden_opportunity_labels(frame: pd.DataFrame, config: Mapping[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    valid_entry = _valid_entry_mask(result)
    invalid_reason = _reason_for_invalid_entry(result)

    for target in ("T1", "T2"):
        legacy_censored = result[f"{target}_CENSORED"].fillna(True).astype(bool)
        applicable = valid_entry
        data_end = applicable & legacy_censored
        status = pd.Series("NOT_APPLICABLE", index=result.index, dtype="string")
        status.loc[applicable & ~data_end] = "AVAILABLE"
        status.loc[data_end] = "DATA_END_CENSORED"
        reason = invalid_reason.copy()
        reason.loc[applicable & ~data_end] = "NONE"
        reason.loc[data_end] = "HISTORY_ENDED_BEFORE_TARGET_OR_HORIZON_RESOLUTION"

        result[f"{target}_APPLICABLE"] = applicable.astype("boolean")
        result[f"{target}_STATUS"] = status
        result[f"{target}_DATA_END_CENSORED"] = data_end.astype("boolean")
        result[f"{target}_UNAVAILABLE_REASON"] = reason
        result[f"{target}_CENSORED"] = result[f"{target}_DATA_END_CENSORED"]
        result.loc[~applicable, [
            f"{target}_BEFORE_STOP_63",
            f"STOP_BEFORE_{target}_63",
            f"{target}_SESSIONS",
            f"{target}_RESOLUTION_DATE",
            f"{target}_LABEL_AVAILABLE_DATE",
        ]] = pd.NA
        result.loc[~applicable, f"{target}_LABEL_OUTCOME"] = "NOT_APPLICABLE"
        result.loc[data_end, f"{target}_LABEL_OUTCOME"] = "DATA_END_CENSORED"

        success = result[f"{target}_BEFORE_STOP_63"].eq(True).fillna(False)
        time_applicable = applicable
        time_data_end = data_end
        time_status = pd.Series("NOT_APPLICABLE", index=result.index, dtype="string")
        time_status.loc[success] = "AVAILABLE"
        time_status.loc[time_data_end] = "DATA_END_CENSORED"
        time_reason = pd.Series("TARGET_NOT_REACHED", index=result.index, dtype="string")
        time_reason.loc[~applicable] = invalid_reason.loc[~applicable]
        time_reason.loc[success] = "NONE"
        time_reason.loc[time_data_end] = "UNDERLYING_TARGET_UNRESOLVED_AT_DATA_END"
        result[f"TIME_TO_{target}_APPLICABLE"] = time_applicable.astype("boolean")
        result[f"TIME_TO_{target}_STATUS"] = time_status
        result[f"TIME_TO_{target}_DATA_END_CENSORED"] = time_data_end.astype("boolean")
        result[f"TIME_TO_{target}_UNAVAILABLE_REASON"] = time_reason
        result[f"TIME_TO_{target}_AVAILABLE_DATE"] = result[f"{target}_LABEL_AVAILABLE_DATE"].where(success)
        result.loc[~success, f"TIME_TO_{target}_SESSIONS"] = np.nan

    for horizon in config["forward_horizons"]:
        legacy_censored = result[f"FWD_{horizon}_CENSORED"].fillna(True).astype(bool)
        applicable = valid_entry
        data_end = applicable & legacy_censored
        status = pd.Series("NOT_APPLICABLE", index=result.index, dtype="string")
        status.loc[applicable & ~data_end] = "AVAILABLE"
        status.loc[data_end] = "DATA_END_CENSORED"
        reason = invalid_reason.copy()
        reason.loc[applicable & ~data_end] = "NONE"
        reason.loc[data_end] = f"INSUFFICIENT_HISTORY_FOR_{horizon}_ENTRY_INCLUSIVE_SESSIONS"

        result[f"FWD_{horizon}_APPLICABLE"] = applicable.astype("boolean")
        result[f"FWD_{horizon}_STATUS"] = status
        result[f"FWD_{horizon}_DATA_END_CENSORED"] = data_end.astype("boolean")
        result[f"FWD_{horizon}_UNAVAILABLE_REASON"] = reason
        result[f"FWD_{horizon}_CENSORED"] = result[f"FWD_{horizon}_DATA_END_CENSORED"]

        legacy_pct = f"FWD_CLOSE_RETURN_{horizon}_PCT"
        legacy_r = f"FWD_CLOSE_RETURN_{horizon}_R"
        canonical_pct = f"FWD_CLOSE_RETURN_{horizon}_ENTRY_INCLUSIVE_PCT"
        canonical_r = f"FWD_CLOSE_RETURN_{horizon}_ENTRY_INCLUSIVE_R"
        result[canonical_pct] = result[legacy_pct]
        result[canonical_r] = result[legacy_r]
        value_columns = [
            legacy_pct, legacy_r, canonical_pct, canonical_r,
            f"MFE_R_{horizon}_FULL_BAR_DIAGNOSTIC",
            f"MAE_R_{horizon}_FULL_BAR_DIAGNOSTIC",
            f"MFE_R_{horizon}_CONSERVATIVE",
            f"MAE_R_{horizon}_CONSERVATIVE",
            f"MFE_PCT_{horizon}_CONSERVATIVE",
            f"MAE_PCT_{horizon}_CONSERVATIVE",
            f"FWD_{horizon}_AVAILABLE_DATE",
        ]
        result.loc[~applicable, value_columns] = pd.NA

    d1_applicable = (
        result["Dataset Cohort"].astype(str).eq("BASELINE_PRIMARY")
        & valid_entry
    )
    legacy_d1_censored = result["D1_SHADOW_CENSORED"].fillna(False).astype(bool)
    d1_data_end = d1_applicable & legacy_d1_censored
    d1_status = pd.Series("NOT_APPLICABLE", index=result.index, dtype="string")
    d1_status.loc[d1_applicable & ~d1_data_end] = "AVAILABLE"
    d1_status.loc[d1_data_end] = "DATA_END_CENSORED"
    d1_reason = pd.Series("NON_PRIMARY_COHORT", index=result.index, dtype="string")
    d1_reason.loc[result["Dataset Cohort"].astype(str).eq("BASELINE_PRIMARY") & ~valid_entry] = invalid_reason
    d1_reason.loc[d1_applicable & ~d1_data_end] = "NONE"
    d1_reason.loc[d1_data_end] = "D1_TRAJECTORY_UNRESOLVED_AT_DATA_END"
    result["D1_SHADOW_APPLICABLE"] = d1_applicable.astype("boolean")
    result["D1_SHADOW_STATUS"] = d1_status
    result["D1_SHADOW_DATA_END_CENSORED"] = d1_data_end.astype("boolean")
    result["D1_SHADOW_UNAVAILABLE_REASON"] = d1_reason
    result["D1_SHADOW_CENSORED"] = result["D1_SHADOW_DATA_END_CENSORED"]
    d1_values = [
        "D1_SHADOW_EXIT_DATE", "D1_SHADOW_EXIT_REASON", "D1_SHADOW_BARS_HELD",
        "D1_SHADOW_NOMINAL_EXIT", "D1_SHADOW_EXECUTED_EXIT",
        "D1_SHADOW_STOP_REVISION_COUNT", "D1_SHADOW_NET_R",
        "D1_SHADOW_NET_RETURN_PCT", "D1_SHADOW_LABEL_AVAILABLE_DATE",
    ]
    result.loc[~d1_applicable, [column for column in d1_values if column in result]] = pd.NA

    result["CENSORED"] = (
        result["T1_DATA_END_CENSORED"].fillna(False)
        | result["T2_DATA_END_CENSORED"].fillna(False)
    ).astype("boolean")
    return result


def label_registry(config: Mapping[str, Any]) -> pd.DataFrame:
    columns = [
        "Dataset", "Label Name", "Label Family", "Description", "Model Task Type",
        "Target Condition", "Applicability Rule", "Availability Date Column",
        "Status Column", "Data-End Censoring Column", "Unavailable Reason Column",
        "Ambiguity Semantics", "Horizon Count Semantics", "ML Input Allowed",
        "Legacy Alias Of",
    ]
    rows: list[dict[str, Any]] = []

    def add(dataset: str, name: str, family: str, description: str, task: str,
            condition: str, rule: str, available: str, status: str, censor: str,
            reason: str, ambiguity: str = "", horizon: str = "", alias: str = "") -> None:
        rows.append(dict(zip(columns, [
            dataset, name, family, description, task, condition, rule, available,
            status, censor, reason, ambiguity, horizon, False, alias,
        ])))

    add("trade_opportunity", "ENTRY_FILLED", "ENTRY_FILL_CLASSIFICATION",
        "Whether the frozen order filled within its required setup-specific entry window",
        "BINARY_CLASSIFICATION", "", "Opportunity Eligible == TRUE",
        "ENTRY_LABEL_AVAILABLE_DATE", "ENTRY_STATUS", "ENTRY_DATA_END_CENSORED",
        "ENTRY_UNAVAILABLE_REASON", "", "SETUP_SPECIFIC_FUTURE_SESSION_WINDOW")

    for target in ("T1", "T2"):
        add("trade_opportunity", f"{target}_BEFORE_STOP_63", "TARGET_CLASSIFICATION",
            f"Whether {target} resolved before stop within 63 entry-inclusive sessions",
            "BINARY_CLASSIFICATION", "", "ENTRY_FILLED == TRUE AND ENTRY_RISK_VALID == TRUE",
            f"{target}_LABEL_AVAILABLE_DATE", f"{target}_STATUS", f"{target}_DATA_END_CENSORED",
            f"{target}_UNAVAILABLE_REASON", "CONSERVATIVE_STOP_FIRST", "ENTRY_INCLUSIVE_SESSION_COUNT")
        add("trade_opportunity", f"STOP_BEFORE_{target}_63", "STOP_CLASSIFICATION",
            f"Whether stop resolved before {target} within 63 entry-inclusive sessions",
            "BINARY_CLASSIFICATION", "", "ENTRY_FILLED == TRUE AND ENTRY_RISK_VALID == TRUE",
            f"{target}_LABEL_AVAILABLE_DATE", f"{target}_STATUS", f"{target}_DATA_END_CENSORED",
            f"{target}_UNAVAILABLE_REASON", "CONSERVATIVE_STOP_FIRST", "ENTRY_INCLUSIVE_SESSION_COUNT")
        add("trade_opportunity", f"TIME_TO_{target}_SESSIONS", "TARGET_TIME",
            f"Sessions to {target}; defined only when {target} succeeds",
            "CONDITIONAL_REGRESSION", f"{target}_BEFORE_STOP_63 == TRUE",
            "ENTRY_FILLED == TRUE AND ENTRY_RISK_VALID == TRUE",
            f"TIME_TO_{target}_AVAILABLE_DATE", f"TIME_TO_{target}_STATUS",
            f"TIME_TO_{target}_DATA_END_CENSORED", f"TIME_TO_{target}_UNAVAILABLE_REASON",
            "CONSERVATIVE_STOP_FIRST", "ENTRY_INCLUSIVE_SESSION_COUNT")

    for horizon in config["forward_horizons"]:
        canonical_pct = f"FWD_CLOSE_RETURN_{horizon}_ENTRY_INCLUSIVE_PCT"
        canonical_r = f"FWD_CLOSE_RETURN_{horizon}_ENTRY_INCLUSIVE_R"
        for name, family, description in (
            (canonical_pct, "FORWARD_RETURN", f"Close return to the {horizon}th entry-inclusive session"),
            (canonical_r, "FORWARD_RETURN_R", f"Risk-normalized close return to the {horizon}th entry-inclusive session"),
        ):
            add("trade_opportunity", name, family, description, "REGRESSION", "",
                "ENTRY_FILLED == TRUE AND ENTRY_RISK_VALID == TRUE",
                f"FWD_{horizon}_AVAILABLE_DATE", f"FWD_{horizon}_STATUS",
                f"FWD_{horizon}_DATA_END_CENSORED", f"FWD_{horizon}_UNAVAILABLE_REASON",
                "", "ENTRY_INCLUSIVE_N_SESSIONS")
        for legacy, canonical in (
            (f"FWD_CLOSE_RETURN_{horizon}_PCT", canonical_pct),
            (f"FWD_CLOSE_RETURN_{horizon}_R", canonical_r),
        ):
            add("trade_opportunity", legacy, "LEGACY_ALIAS", f"Exact alias of {canonical}",
                "REGRESSION", "", "ENTRY_FILLED == TRUE AND ENTRY_RISK_VALID == TRUE",
                f"FWD_{horizon}_AVAILABLE_DATE", f"FWD_{horizon}_STATUS",
                f"FWD_{horizon}_DATA_END_CENSORED", f"FWD_{horizon}_UNAVAILABLE_REASON",
                "", "ENTRY_INCLUSIVE_N_SESSIONS", canonical)
        for prefix in ("MFE_R", "MAE_R", "MFE_PCT", "MAE_PCT"):
            for suffix in (["FULL_BAR_DIAGNOSTIC", "CONSERVATIVE"] if prefix in {"MFE_R", "MAE_R"} else ["CONSERVATIVE"]):
                name = f"{prefix}_{horizon}_{suffix}"
                add("trade_opportunity", name, "FORWARD_PATH", f"{prefix} over {horizon} entry-inclusive sessions",
                    "REGRESSION", "", "ENTRY_FILLED == TRUE AND ENTRY_RISK_VALID == TRUE",
                    f"FWD_{horizon}_AVAILABLE_DATE", f"FWD_{horizon}_STATUS",
                    f"FWD_{horizon}_DATA_END_CENSORED", f"FWD_{horizon}_UNAVAILABLE_REASON",
                    "ENTRY_BAR_MAY_BE_AMBIGUOUS" if suffix == "FULL_BAR_DIAGNOSTIC" else "CONSERVATIVE_POST_ENTRY",
                    "ENTRY_INCLUSIVE_N_SESSIONS")

    for name in ("D1_SHADOW_NET_R", "D1_SHADOW_NET_RETURN_PCT", "D1_SHADOW_BARS_HELD", "D1_SHADOW_EXIT_REASON"):
        add("trade_opportunity", name, "INDEPENDENT_D1_SHADOW_OUTCOME",
            "Independent capacity-free frozen D1 final outcome", "REGRESSION_OR_CLASSIFICATION", "",
            "Dataset Cohort == BASELINE_PRIMARY AND ENTRY_FILLED == TRUE AND ENTRY_RISK_VALID == TRUE",
            "D1_SHADOW_LABEL_AVAILABLE_DATE", "D1_SHADOW_STATUS",
            "D1_SHADOW_DATA_END_CENSORED", "D1_SHADOW_UNAVAILABLE_REASON",
            "CONSERVATIVE_STOP_FIRST", "ENTRY_INCLUSIVE_SESSION_COUNT")

    for name in ("D1_EXIT_NEXT_SESSION", "D1_REMAINING_NET_R"):
        add("d1_position_day", name, "D1_FINAL_OUTCOME", "Final frozen D1 outcome from current completed session",
            "CLASSIFICATION" if name == "D1_EXIT_NEXT_SESSION" else "REGRESSION", "",
            "Position-day row exists", "D1_LABEL_AVAILABLE_DATE", "D1_FINAL_STATUS",
            "D1_FINAL_DATA_END_CENSORED", "D1_FINAL_UNAVAILABLE_REASON",
            "CONSERVATIVE_STOP_FIRST", "COMPLETED_MANAGEMENT_SESSION")
    for horizon in config["position_day_horizons"]:
        for suffix in ("RETURN", "MFE", "MAE"):
            name = f"NEXT_{horizon}_SESSION_{suffix}"
            add("d1_position_day", name, "POSITION_DAY_FORWARD_PATH",
                f"Next-{horizon}-session {suffix} from completed management close", "REGRESSION", "",
                "Position-day row exists", f"NEXT_{horizon}_SESSION_LABEL_AVAILABLE_DATE",
                f"NEXT_{horizon}_SESSION_STATUS", f"NEXT_{horizon}_SESSION_DATA_END_CENSORED",
                f"NEXT_{horizon}_SESSION_UNAVAILABLE_REASON", "", "AFTER_MANAGEMENT_N_SESSIONS")
    return pd.DataFrame(rows, columns=columns).sort_values(["Dataset", "Label Name"]).reset_index(drop=True)
