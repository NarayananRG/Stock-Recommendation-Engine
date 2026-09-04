"""Leakage-safe target, forward-path, and ambiguity labels for Stage 3."""
from __future__ import annotations

from typing import Any, Dict, Mapping

import numpy as np
import pandas as pd


def _empty_target(prefix: str) -> Dict[str, Any]:
    return {
        f"{prefix}_BEFORE_STOP_63": pd.NA,
        f"STOP_BEFORE_{prefix}_63": pd.NA,
        f"{prefix}_SESSIONS": np.nan,
        f"{prefix}_RESOLUTION_DATE": pd.NaT,
        f"{prefix}_LABEL_AVAILABLE_DATE": pd.NaT,
        f"{prefix}_CENSORED": True,
        f"{prefix}_LABEL_OUTCOME": "UNAVAILABLE",
    }


def _target_path(
    frame: pd.DataFrame,
    entry_date: pd.Timestamp,
    stop: float,
    target: float,
    intraday_limit: bool,
    max_sessions: int,
) -> Dict[str, Any]:
    bars = frame.loc[frame.index >= entry_date].iloc[:max_sessions]
    if bars.empty or pd.Timestamp(bars.index[0]).normalize() != entry_date:
        return {"outcome": "CENSORED", "event_date": pd.NaT, "sessions": np.nan, "available": pd.NaT, "censored": True, "ambiguous": False}
    ambiguous = False
    for number, (date_value, bar) in enumerate(bars.iterrows(), start=1):
        date = pd.Timestamp(date_value).normalize()
        open_price, low, high = float(bar["Open"]), float(bar["Low"]), float(bar["High"])
        if number == 1 and intraday_limit:
            stop_hit = low <= stop
            target_hit = high >= target
            ambiguous = ambiguous or (stop_hit and target_hit)
            if stop_hit:
                return {"outcome": "STOP", "event_date": date, "sessions": number, "available": date, "censored": False, "ambiguous": ambiguous}
            continue
        if number > 1:
            if open_price <= stop:
                return {"outcome": "STOP", "event_date": date, "sessions": number, "available": date, "censored": False, "ambiguous": ambiguous}
            if open_price >= target:
                return {"outcome": "TARGET", "event_date": date, "sessions": number, "available": date, "censored": False, "ambiguous": ambiguous}
        stop_hit, target_hit = low <= stop, high >= target
        if stop_hit and target_hit:
            ambiguous = True
            return {"outcome": "STOP", "event_date": date, "sessions": number, "available": date, "censored": False, "ambiguous": True}
        if stop_hit:
            return {"outcome": "STOP", "event_date": date, "sessions": number, "available": date, "censored": False, "ambiguous": ambiguous}
        if target_hit:
            return {"outcome": "TARGET", "event_date": date, "sessions": number, "available": date, "censored": False, "ambiguous": ambiguous}
    if len(bars) < max_sessions:
        return {"outcome": "CENSORED", "event_date": pd.NaT, "sessions": np.nan, "available": pd.NaT, "censored": True, "ambiguous": ambiguous}
    horizon_date = pd.Timestamp(bars.index[-1]).normalize()
    return {"outcome": "HORIZON_NO_HIT", "event_date": horizon_date, "sessions": np.nan, "available": horizon_date, "censored": False, "ambiguous": ambiguous}


def _baseline_compatible_t1(
    row: Mapping[str, Any], frame: pd.DataFrame, config: Mapping[str, Any]
) -> Dict[str, Any]:
    """Exact CandidateOutcomeEngine-compatible one-share T1 diagnostic."""
    entry_date = pd.Timestamp(row["ENTRY_DATE"]).normalize()
    bars = frame.loc[frame.index >= entry_date]
    stop, target = float(row["Stop Loss"]), float(row["Target 1"])
    executed_entry, nominal_entry = float(row["EXECUTED_ENTRY"]), float(row["NOMINAL_ENTRY"])
    risk = executed_entry - stop
    nominal_exit = float(bars["Close"].iloc[-1])
    exit_date = pd.Timestamp(bars.index[-1]).normalize()
    reason, count, ambiguity = "DATA_END", 0, False
    for date_value, bar in bars.iterrows():
        date = pd.Timestamp(date_value).normalize(); count += 1
        low, high, open_price = float(bar["Low"]), float(bar["High"]), float(bar["Open"])
        if count == 1 and bool(row["ENTRY_INTRADAY_LIMIT"]):
            stop_hit, theoretical = low <= stop, high >= target
            ambiguity = ambiguity or theoretical
            if stop_hit:
                nominal_exit, exit_date = stop, date
                reason = "STOP_COLLISION_ENTRY_BAR" if theoretical else "STOP_ENTRY_BAR"
                break
        else:
            if count > 1 and open_price <= stop:
                nominal_exit, exit_date, reason = open_price, date, "STOP_GAP"
                break
            if count > 1 and open_price >= target:
                nominal_exit, exit_date, reason = open_price, date, "TARGET_GAP"
                break
            stop_hit, target_hit = low <= stop, high >= target
            if stop_hit:
                nominal_exit, exit_date = stop, date
                reason = "STOP_COLLISION" if target_hit else "STOP"
                break
            if target_hit:
                nominal_exit, exit_date, reason = target, date, "TARGET"
                break
        if count >= int(config["max_hold_sessions"]):
            nominal_exit, exit_date, reason = float(bar["Close"]), date, f"TIME_{int(config['max_hold_sessions'])}D"
            break
    slip = float(config["slippage_bps"]) / 10000.0
    cost = float(config["transaction_cost_bps"]) / 10000.0
    executed_exit = nominal_exit * (1.0 - slip)
    net = (nominal_exit - nominal_entry) - (executed_entry - nominal_entry) - (nominal_exit - executed_exit) - executed_entry * cost - executed_exit * cost
    return {
        "BASELINE_COMPAT_T1_EXIT_DATE": exit_date,
        "BASELINE_COMPAT_T1_EXIT_REASON": reason,
        "BASELINE_COMPAT_T1_BARS_HELD": count,
        "BASELINE_COMPAT_T1_NOMINAL_EXIT": nominal_exit,
        "BASELINE_COMPAT_T1_EXECUTED_EXIT": executed_exit,
        "BASELINE_COMPAT_T1_NET_R": net / risk,
        "BASELINE_COMPAT_ENTRY_BAR_AMBIGUITY": ambiguity,
    }


def add_opportunity_labels(row: Mapping[str, Any], frame: pd.DataFrame, config: Mapping[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "LABEL_SEMANTICS": "CONSERVATIVE_STOP_FIRST",
        "OUTCOME_SEQUENCE_AMBIGUOUS": False,
        "CENSORED": True,
        "STOP_SESSIONS": np.nan,
        "TARGET_TIME_LABEL_AVAILABLE_DATE": pd.NaT,
    }
    for target_name in ("T1", "T2"):
        result.update(_empty_target(target_name))
    for horizon in config["forward_horizons"]:
        result.update({
            f"FWD_CLOSE_RETURN_{horizon}_PCT": np.nan,
            f"FWD_CLOSE_RETURN_{horizon}_R": np.nan,
            f"FWD_{horizon}_AVAILABLE_DATE": pd.NaT,
            f"FWD_{horizon}_CENSORED": True,
            f"MFE_R_{horizon}_FULL_BAR_DIAGNOSTIC": np.nan,
            f"MAE_R_{horizon}_FULL_BAR_DIAGNOSTIC": np.nan,
            f"MFE_R_{horizon}_CONSERVATIVE": np.nan,
            f"MAE_R_{horizon}_CONSERVATIVE": np.nan,
            f"MFE_PCT_{horizon}_CONSERVATIVE": np.nan,
            f"MAE_PCT_{horizon}_CONSERVATIVE": np.nan,
        })
    entry_filled = row.get("ENTRY_FILLED")
    if pd.isna(entry_filled) or not bool(entry_filled) or not bool(row.get("ENTRY_RISK_VALID")):
        return result
    entry_date = pd.Timestamp(row["ENTRY_DATE"]).normalize()
    executed = float(row["EXECUTED_ENTRY"]); stop = float(row["Stop Loss"]); risk = executed - stop
    intraday = bool(row["ENTRY_INTRADAY_LIMIT"])
    target_paths = {}
    for name, column in (("T1", "Target 1"), ("T2", "Target 2")):
        path = _target_path(frame, entry_date, stop, float(row[column]), intraday, int(config["max_hold_sessions"]))
        target_paths[name] = path
        outcome = path["outcome"]
        result[f"{name}_BEFORE_STOP_63"] = pd.NA if path["censored"] else outcome == "TARGET"
        result[f"STOP_BEFORE_{name}_63"] = pd.NA if path["censored"] else outcome == "STOP"
        result[f"{name}_SESSIONS"] = path["sessions"] if outcome == "TARGET" else np.nan
        result[f"{name}_RESOLUTION_DATE"] = path["event_date"]
        result[f"{name}_LABEL_AVAILABLE_DATE"] = path["available"]
        result[f"{name}_CENSORED"] = bool(path["censored"])
        result[f"{name}_LABEL_OUTCOME"] = outcome
        result["OUTCOME_SEQUENCE_AMBIGUOUS"] = bool(result["OUTCOME_SEQUENCE_AMBIGUOUS"] or path["ambiguous"])
    stop_sessions = [p["sessions"] for p in target_paths.values() if p["outcome"] == "STOP"]
    result["STOP_SESSIONS"] = min(stop_sessions) if stop_sessions else np.nan
    available_dates = [p["available"] for p in target_paths.values() if pd.notna(p["available"])]
    result["TARGET_TIME_LABEL_AVAILABLE_DATE"] = max(available_dates) if available_dates else pd.NaT
    result["CENSORED"] = bool(target_paths["T1"]["censored"] or target_paths["T2"]["censored"])
    result["TIME_TO_T1_SESSIONS"] = result["T1_SESSIONS"]
    result["TIME_TO_T2_SESSIONS"] = result["T2_SESSIONS"]
    bars = frame.loc[frame.index >= entry_date]
    for horizon in config["forward_horizons"]:
        window = bars.iloc[: int(horizon)]
        if len(window) < int(horizon):
            continue
        available = pd.Timestamp(window.index[-1]).normalize()
        close = float(window["Close"].iloc[-1])
        result[f"FWD_CLOSE_RETURN_{horizon}_PCT"] = (close / executed - 1.0) * 100.0
        result[f"FWD_CLOSE_RETURN_{horizon}_R"] = (close - executed) / risk
        result[f"FWD_{horizon}_AVAILABLE_DATE"] = available
        result[f"FWD_{horizon}_CENSORED"] = False
        high_full, low_full = float(window["High"].max()), float(window["Low"].min())
        result[f"MFE_R_{horizon}_FULL_BAR_DIAGNOSTIC"] = (high_full - executed) / risk
        result[f"MAE_R_{horizon}_FULL_BAR_DIAGNOSTIC"] = (low_full - executed) / risk
        conservative = window.iloc[1:] if intraday else window
        high_cons = max(executed, float(conservative["High"].max())) if not conservative.empty else executed
        low_cons = min(executed, float(conservative["Low"].min())) if not conservative.empty else executed
        result[f"MFE_R_{horizon}_CONSERVATIVE"] = (high_cons - executed) / risk
        result[f"MAE_R_{horizon}_CONSERVATIVE"] = (low_cons - executed) / risk
        result[f"MFE_PCT_{horizon}_CONSERVATIVE"] = (high_cons / executed - 1.0) * 100.0
        result[f"MAE_PCT_{horizon}_CONSERVATIVE"] = (low_cons / executed - 1.0) * 100.0
    result.update(_baseline_compatible_t1(row, frame, config))
    return result


def label_registry(config: Mapping[str, Any]) -> pd.DataFrame:
    rows = []
    def add(name: str, family: str, availability: str, censoring: str, description: str, ambiguity: str = "") -> None:
        rows.append({"Label Name": name, "Label Family": family, "Description": description, "Availability Date Column": availability, "Censoring Column": censoring, "Ambiguity Semantics": ambiguity, "ML Input Allowed": False})
    add("ENTRY_FILLED", "ENTRY_FILL_CLASSIFICATION", "ENTRY_LABEL_AVAILABLE_DATE", "ENTRY_CENSORED", "Whether the frozen independent entry order filled")
    add("ENTRY_SESSIONS_TO_FILL", "ENTRY_FILL_TIME", "ENTRY_LABEL_AVAILABLE_DATE", "ENTRY_CENSORED", "Sessions from signal to fill; NaN for non-fills")
    for target in ("T1", "T2"):
        available, censored = f"{target}_LABEL_AVAILABLE_DATE", f"{target}_CENSORED"
        add(f"{target}_BEFORE_STOP_63", "TARGET_CLASSIFICATION", available, censored, f"Whether {target} resolved before stop within 63 sessions", "CONSERVATIVE_STOP_FIRST")
        add(f"STOP_BEFORE_{target}_63", "STOP_CLASSIFICATION", available, censored, f"Whether stop resolved before {target} within 63 sessions", "CONSERVATIVE_STOP_FIRST")
        add(f"TIME_TO_{target}_SESSIONS", "TARGET_TIME", available, censored, f"Sessions to {target}; NaN for non-hits", "CONSERVATIVE_STOP_FIRST")
        add(f"{target}_SESSIONS", "TARGET_TIME", available, censored, f"Sessions to {target}; compatibility field", "CONSERVATIVE_STOP_FIRST")
    for horizon in config["forward_horizons"]:
        available, censored = f"FWD_{horizon}_AVAILABLE_DATE", f"FWD_{horizon}_CENSORED"
        add(f"FWD_CLOSE_RETURN_{horizon}_PCT", "FORWARD_RETURN", available, censored, f"Raw close return over {horizon} entry-inclusive sessions")
        add(f"FWD_CLOSE_RETURN_{horizon}_R", "FORWARD_RETURN_R", available, censored, f"Risk-normalized close return over {horizon} entry-inclusive sessions")
        for prefix in ("MFE_R", "MAE_R"):
            add(f"{prefix}_{horizon}_FULL_BAR_DIAGNOSTIC", "PATH_DIAGNOSTIC", available, censored, f"{prefix} including the full entry bar", "ENTRY BAR MAY BE AMBIGUOUS")
            add(f"{prefix}_{horizon}_CONSERVATIVE", "PATH_CONSERVATIVE", available, censored, f"{prefix} excluding an ambiguous intraday-limit entry bar", "CONSERVATIVE_POST_ENTRY")
        for prefix in ("MFE_PCT", "MAE_PCT"):
            add(f"{prefix}_{horizon}_CONSERVATIVE", "PATH_CONSERVATIVE", available, censored, f"Percentage {prefix} excluding an ambiguous intraday-limit entry bar", "CONSERVATIVE_POST_ENTRY")
    for name in ("D1_SHADOW_NET_R", "D1_SHADOW_NET_RETURN_PCT", "D1_SHADOW_BARS_HELD", "D1_SHADOW_EXIT_REASON"):
        add(name, "INDEPENDENT_D1_SHADOW_OUTCOME", "D1_SHADOW_LABEL_AVAILABLE_DATE", "D1_SHADOW_CENSORED", "Independent capacity-free D1 final outcome", "CONSERVATIVE_STOP_FIRST")
    for name in ("D1_EXIT_NEXT_SESSION", "D1_REMAINING_SESSIONS", "D1_REMAINING_NET_R", "D1_FINAL_EXIT_REASON", "ORIGINAL_T2_REACHED_BEFORE_D1_EXIT"):
        add(name, "POSITION_DAY_FUTURE_OUTCOME", "D1_LABEL_AVAILABLE_DATE", "D1_LABEL_CENSORED", "Future D1 outcome strictly after the management-session close", "CONSERVATIVE_STOP_FIRST")
    for horizon in config["position_day_horizons"]:
        available, censored = f"NEXT_{horizon}_SESSION_LABEL_AVAILABLE_DATE", f"NEXT_{horizon}_SESSION_CENSORED"
        for suffix in ("RETURN", "MFE", "MAE"):
            add(f"NEXT_{horizon}_SESSION_{suffix}", "POSITION_DAY_FORWARD_PATH", available, censored, f"Next-{horizon}-session {suffix} from the completed management close")
    return pd.DataFrame(rows)
