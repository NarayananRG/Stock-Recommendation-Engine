"""Independent D1 shadow trajectories and completed-session position-day rows."""
from __future__ import annotations

from typing import Any, Dict, Mapping

import numpy as np
import pandas as pd

from hashing import deterministic_row_id


POSITION_STOCK_FEATURES = {
    "Close": "Current Close",
    "SMA20": "SMA20",
    "SMA50": "SMA50",
    "SMA200": "SMA200",
    "ST": "Daily ST",
    "STTrend": "Daily ST Direction",
    "WeeklyST": "Weekly ST",
    "WeeklySTTrend": "Weekly ST Direction",
    "RSI": "RSI",
    "WeeklyRSI": "Weekly RSI",
    "ADX": "ADX",
    "ATR": "ATR",
    "RS20": "RS20",
    "RS60": "RS60",
    "RS120": "RS120",
    "Return5Pct": "Current Stock Return 5D %",
    "Return20Pct": "Current Stock Return 20D %",
    "RealizedVol20Pct": "Current Stock Realized Volatility 20D %",
    "RelativeVolume20": "Current Volume Ratio",
}

POSITION_MARKET_FEATURES = {
    "MarketRegime": "Current Market Regime",
    "Price": "Current NIFTY Close",
    "DailyRSI": "Current NIFTY Daily RSI",
    "WeeklyRSI": "Current NIFTY Weekly RSI",
    "ADX": "Current NIFTY ADX",
    "ATRPct": "Current NIFTY ATR %",
    "DailyST": "Current NIFTY Daily ST Direction",
    "WeeklyST": "Current NIFTY Weekly ST Direction",
    "Return5Pct": "Current NIFTY Return 5D %",
    "Return20Pct": "Current NIFTY Return 20D %",
    "RealizedVol20Pct": "Current NIFTY Volatility 20D %",
    "Drawdown252Pct": "Current NIFTY Drawdown 252D %",
}


def _net_outcome(nominal_entry: float, executed_entry: float, nominal_exit: float, config: Mapping[str, Any]) -> tuple[float, float]:
    slip = float(config["slippage_bps"]) / 10000.0
    cost = float(config["transaction_cost_bps"]) / 10000.0
    executed_exit = nominal_exit * (1.0 - slip)
    entry_cost = executed_entry * cost
    exit_cost = executed_exit * cost
    gross = nominal_exit - nominal_entry
    net = gross - (executed_entry - nominal_entry) - (nominal_exit - executed_exit) - entry_cost - exit_cost
    return executed_exit, net


def simulate_d1_shadow(
    opportunity: Mapping[str, Any],
    frame: pd.DataFrame,
    market: pd.DataFrame,
    policies: Any,
    policy_config: Any,
    config: Mapping[str, Any],
    experiment_id: str,
) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
    entry_date = pd.Timestamp(opportunity["ENTRY_DATE"]).normalize()
    bars = frame.loc[frame.index >= entry_date].iloc[: int(config["max_hold_sessions"])]
    if bars.empty or pd.Timestamp(bars.index[0]).normalize() != entry_date:
        raise RuntimeError(f"Missing D1 entry bar: {opportunity['Ticker']} {entry_date.date()}")
    nominal_entry = float(opportunity["NOMINAL_ENTRY"])
    executed_entry = float(opportunity["EXECUTED_ENTRY"])
    initial_stop = float(opportunity["Stop Loss"])
    original_t1 = float(opportunity["Target 1"])
    original_t2 = float(opportunity["Target 2"])
    risk = float(opportunity["INITIAL_RISK_PER_SHARE"])
    intraday_limit = bool(opportunity["ENTRY_INTRADAY_LIMIT"])
    current_stop = initial_stop
    stop_revisions = 0
    highest_full = executed_entry
    lowest_full = executed_entry
    highest_conservative = executed_entry
    lowest_conservative = executed_entry
    exit_date = pd.NaT
    exit_reason = ""
    nominal_exit = np.nan
    exit_bar_number = np.nan
    outcome_ambiguous = False
    censored = False
    rows: list[Dict[str, Any]] = []

    for bar_number, (date_value, bar) in enumerate(bars.iterrows(), start=1):
        date = pd.Timestamp(date_value).normalize()
        open_price, high, low, close = map(float, (bar["Open"], bar["High"], bar["Low"], bar["Close"]))
        if bar_number > 1:
            if open_price <= current_stop:
                exit_date, exit_reason, nominal_exit, exit_bar_number = date, "GAP_STOP", open_price, bar_number
            elif open_price >= original_t2:
                exit_date, exit_reason, nominal_exit, exit_bar_number = date, "EXIT_T2", open_price, bar_number
        if not exit_reason:
            highest_full = max(highest_full, high)
            lowest_full = min(lowest_full, low)
            if not (bar_number == 1 and intraday_limit):
                highest_conservative = max(highest_conservative, high)
                lowest_conservative = min(lowest_conservative, low)
            stop_hit = low <= current_stop
            t1_hit = high >= original_t1
            target_hit = high >= original_t2
            if bar_number == 1 and intraday_limit:
                if stop_hit:
                    # Preserve the accepted Stage 2B.1 shadow diagnostic:
                    # touching either T1 or the active T2 on the same daily
                    # bar as the stop is an unresolved OHLC sequence.
                    outcome_ambiguous = bool(t1_hit or target_hit)
                    exit_date = date
                    exit_reason = "STOP_COLLISION_ENTRY_BAR" if (t1_hit or target_hit) else "STOP_ENTRY_BAR"
                    nominal_exit, exit_bar_number = current_stop, bar_number
            elif stop_hit:
                outcome_ambiguous = bool(t1_hit or target_hit)
                exit_date = date
                exit_reason = "EXIT_STOP_COLLISION" if (t1_hit or target_hit) else "EXIT_STOP"
                nominal_exit, exit_bar_number = current_stop, bar_number
            elif target_hit:
                exit_date, exit_reason, nominal_exit, exit_bar_number = date, "EXIT_T2", original_t2, bar_number
        if not exit_reason and bar_number >= int(config["max_hold_sessions"]):
            exit_date, exit_reason, nominal_exit, exit_bar_number = date, "EXIT_MAX_63D", close, bar_number
        if not exit_reason and date == pd.Timestamp(frame.index[-1]).normalize():
            exit_date, exit_reason, nominal_exit, exit_bar_number = date, "END_OF_DATA", close, bar_number
            censored = bar_number < int(config["max_hold_sessions"])
        if exit_reason:
            break

        state = {
            "current_stop": current_stop,
            "active_target": original_t2,
            "original_t2": original_t2,
            "executed_entry": executed_entry,
            "current_r": (close - executed_entry) / risk,
            "partial_taken": False,
            "t1_reached": high >= original_t1,
            "days_held": bar_number,
            "t1_q75": None,
        }
        decision = policies.decide_after_close("D1_TRAIL_ONLY", state, bar, None, policy_config)
        previous_stop = current_stop
        current_stop = max(current_stop, float(decision.proposed_stop))
        if current_stop > previous_stop + 1e-12:
            stop_revisions += 1
        market_slice = market.loc[:date]
        if market_slice.empty:
            raise RuntimeError(f"No past NIFTY state for management date {date}")
        market_row = market_slice.iloc[-1]
        current_r = (close - executed_entry) / risk
        daily = {
            "Signal ID": opportunity["Signal ID"],
            "Ticker": opportunity["Ticker"],
            "Signal Date": opportunity["Signal Date"],
            "Setup": opportunity["Setup"],
            "Original Signal": opportunity["Original Signal"],
            "Dataset Cohort": "INDEPENDENT_D1_SHADOW_POSITION_DAY",
            "Source Experiment ID": config["source_experiment_id"],
            "Stage 3 Experiment ID": experiment_id,
            "Entry Date": entry_date,
            "Management Date": date,
            "Feature As-Of Date": date,
            "Days Held": bar_number,
            "Executed Entry": executed_entry,
            "Initial Stop": initial_stop,
            "Previous Session Stop": previous_stop,
            "Current Stop": current_stop,
            "Stop Effective Semantics": "AFTER_CLOSE_EFFECTIVE_NEXT_AVAILABLE_SESSION",
            "Original T1": original_t1,
            "Original T2": original_t2,
            "Current R": current_r,
            "Current MFE Conservative To Date": (highest_conservative - executed_entry) / risk,
            "Current MAE Conservative To Date": (lowest_conservative - executed_entry) / risk,
            "Current MFE Full Bar Diagnostic To Date": (highest_full - executed_entry) / risk,
            "Current MAE Full Bar Diagnostic To Date": (lowest_full - executed_entry) / risk,
            "Stop Distance R": (close - current_stop) / risk,
            "T1 Distance R": (original_t1 - close) / risk,
            "T2 Distance R": (original_t2 - close) / risk,
            "Stop Revision Count": stop_revisions,
            "Entry Market Regime": opportunity["Market Regime"],
            "Entry Technical Score": opportunity["Technical Score"],
            "Entry Actionability Score": opportunity["Actionability Score"],
            "ENTRY_DAY_SEQUENCE_AMBIGUOUS": intraday_limit,
            "EXIT_DAY_SEQUENCE_AMBIGUOUS": False,
            "LABEL_SEMANTICS": "CONSERVATIVE_STOP_FIRST",
        }
        for source, target in POSITION_STOCK_FEATURES.items():
            daily[target] = bar[source]
        for source, target in POSITION_MARKET_FEATURES.items():
            daily[target] = market_row[source]
        daily["Current Market Feature Source Date"] = pd.Timestamp(market_slice.index[-1]).normalize()
        daily["STAGE3_ROW_ID"] = deterministic_row_id(config["dataset_schema_versions"]["d1_position_day"], opportunity["Signal ID"], date.strftime("%Y-%m-%d"))
        rows.append(daily)

    if not exit_reason:
        raise RuntimeError(f"D1 shadow did not resolve: {opportunity['Ticker']} {entry_date.date()}")
    executed_exit, net = _net_outcome(nominal_entry, executed_entry, float(nominal_exit), config)
    net_r = net / risk
    shadow = {
        "D1_SHADOW_EXIT_DATE": exit_date,
        "D1_SHADOW_EXIT_REASON": exit_reason,
        "D1_SHADOW_BARS_HELD": int(exit_bar_number),
        "D1_SHADOW_NOMINAL_EXIT": float(nominal_exit),
        "D1_SHADOW_EXECUTED_EXIT": float(executed_exit),
        "D1_SHADOW_STOP_REVISION_COUNT": stop_revisions,
        "D1_SHADOW_NET_R": net_r,
        "D1_SHADOW_NET_RETURN_PCT": net / executed_entry * 100.0,
        "D1_SHADOW_LABEL_AVAILABLE_DATE": pd.NaT if censored else exit_date,
        "D1_SHADOW_CENSORED": censored,
        "D1_SHADOW_LABEL_TYPE": "INDEPENDENT_POLICY_OUTCOME_LABEL",
        "D1_SHADOW_OUTCOME_SEQUENCE_AMBIGUOUS": outcome_ambiguous,
    }
    for daily in rows:
        date = pd.Timestamp(daily["Management Date"]).normalize()
        future_dates = frame.index[frame.index > date]
        daily["D1_EXIT_NEXT_SESSION"] = bool(len(future_dates) and pd.Timestamp(future_dates[0]).normalize() == exit_date)
        current_number = int(daily["Days Held"])
        daily["D1_REMAINING_SESSIONS"] = int(exit_bar_number) - current_number
        # Remaining net R is the incremental value of continuing from this
        # completed close to the final D1 exit, relative to closing now under
        # the same frozen friction model.  Entry costs are sunk and cancel.
        _, current_mark_net = _net_outcome(nominal_entry, executed_entry, float(daily["Current Close"]), config)
        daily["D1_REMAINING_NET_R"] = net_r - current_mark_net / risk
        daily["D1_FINAL_EXIT_REASON"] = exit_reason
        daily["ORIGINAL_T2_REACHED_BEFORE_D1_EXIT"] = exit_reason == "EXIT_T2"
        daily["EXIT_DAY_SEQUENCE_AMBIGUOUS"] = outcome_ambiguous
        daily["D1_LABEL_AVAILABLE_DATE"] = pd.NaT if censored else exit_date
        daily["D1_LABEL_CENSORED"] = censored
        current_close = float(daily["Current Close"])
        future = frame.loc[frame.index > date]
        for horizon in config["position_day_horizons"]:
            window = future.iloc[: int(horizon)]
            available = len(window) == int(horizon)
            daily[f"NEXT_{horizon}_SESSION_CENSORED"] = not available
            daily[f"NEXT_{horizon}_SESSION_LABEL_AVAILABLE_DATE"] = pd.Timestamp(window.index[-1]).normalize() if available else pd.NaT
            if available:
                daily[f"NEXT_{horizon}_SESSION_RETURN"] = (float(window["Close"].iloc[-1]) / current_close - 1.0) * 100.0
                daily[f"NEXT_{horizon}_SESSION_MFE"] = (float(window["High"].max()) / current_close - 1.0) * 100.0
                daily[f"NEXT_{horizon}_SESSION_MAE"] = (float(window["Low"].min()) / current_close - 1.0) * 100.0
            else:
                daily[f"NEXT_{horizon}_SESSION_RETURN"] = np.nan
                daily[f"NEXT_{horizon}_SESSION_MFE"] = np.nan
                daily[f"NEXT_{horizon}_SESSION_MAE"] = np.nan
    return shadow, rows


def build_d1_datasets(
    opportunities: pd.DataFrame,
    features: Mapping[str, pd.DataFrame],
    market: pd.DataFrame,
    policies: Any,
    policy_config: Any,
    config: Mapping[str, Any],
    experiment_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    updated = opportunities.copy()
    shadow_columns: Dict[int, Dict[str, Any]] = {}
    daily_rows: list[Dict[str, Any]] = []
    mask = (updated["Dataset Cohort"] == "BASELINE_PRIMARY") & updated["ENTRY_FILLED"].fillna(False).astype(bool) & updated["ENTRY_RISK_VALID"].fillna(False).astype(bool)
    for index, opportunity in updated.loc[mask].iterrows():
        shadow, rows = simulate_d1_shadow(opportunity, features[str(opportunity["Ticker"])], market, policies, policy_config, config, experiment_id)
        shadow_columns[int(index)] = shadow
        daily_rows.extend(rows)
    for index, values in shadow_columns.items():
        for column, value in values.items():
            updated.at[index, column] = value
    position_day = pd.DataFrame(daily_rows)
    if not position_day.empty:
        date_columns = [
            column for column in position_day.columns
            if (column.endswith(" Date") and not column.endswith(" To Date")) or column.endswith("_DATE")
        ]
        for column in date_columns:
            position_day[column] = pd.to_datetime(position_day[column], errors="coerce").dt.normalize()
    return updated, position_day
