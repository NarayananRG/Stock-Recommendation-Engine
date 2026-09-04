"""Capacity-free opportunity eligibility and exact frozen entry semantics."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

import numpy as np
import pandas as pd

from hashing import deterministic_row_id


LEVEL_COLUMNS = ("Entry Low", "Entry High", "Stop Loss", "Target 1", "Target 2")


def finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def opportunity_eligibility(row: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[bool, str, str]:
    signal = str(row.get("Signal", ""))
    setup = str(row.get("Setup", ""))
    primary = set(config["baseline_primary_signals"])
    extended = set(config["research_extended_signals"])
    if signal not in primary | extended:
        return False, "NOT_ELIGIBLE", "ORIGINAL_SIGNAL_EXCLUDED"
    if setup not in set(config["valid_setups"]):
        return False, "NOT_ELIGIBLE", "INVALID_OR_NO_SETUP"
    levels = {column: finite(row.get(column)) for column in LEVEL_COLUMNS}
    if any(value is None for value in levels.values()):
        return False, "NOT_ELIGIBLE", "MISSING_TRADE_LEVEL"
    entry_low = float(levels["Entry Low"])
    entry_high = float(levels["Entry High"])
    stop = float(levels["Stop Loss"])
    t1 = float(levels["Target 1"])
    t2 = float(levels["Target 2"])
    if not (entry_low <= entry_high and stop < entry_high and t1 > entry_low and t2 > t1):
        return False, "NOT_ELIGIBLE", "INVALID_PRICE_LEVEL_ORDERING"
    cohort = "BASELINE_PRIMARY" if signal in primary else "RESEARCH_EXTENDED"
    return True, cohort, "VALID_FROZEN_TRADE_LEVELS"


def _valid_dates(frame: pd.DataFrame, signal_date: pd.Timestamp, setup: str, config: Mapping[str, Any]) -> tuple[pd.Timestamp, ...]:
    dates = tuple(pd.Timestamp(value).normalize() for value in frame.index if value > signal_date)
    count = 1 if setup == "BREAKOUT" else int(config["pullback_entry_window"])
    return dates[:count]


def simulate_entry(
    row: Mapping[str, Any],
    frame: pd.DataFrame,
    frozen_stage221: Any,
    frozen_config: Any,
    config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Use Stage 2.2.1 PendingOrder and ExecutionModel without changing thresholds."""
    signal_date = pd.Timestamp(row["Signal Date"]).normalize()
    setup = str(row["Setup"])
    valid_dates = _valid_dates(frame, signal_date, setup, config)
    base = {
        "ENTRY_FILLED": pd.NA if not valid_dates else False,
        "ENTRY_DATE": pd.NaT,
        "ENTRY_LABEL_AVAILABLE_DATE": valid_dates[-1] if valid_dates else pd.NaT,
        "ENTRY_CENSORED": not bool(valid_dates),
        "ENTRY_SESSIONS_TO_FILL": np.nan,
        "NOMINAL_ENTRY": np.nan,
        "EXECUTED_ENTRY": np.nan,
        "ENTRY_METHOD": "",
        "ENTRY_INTRADAY_LIMIT": False,
        "ENTRY_DAY_SEQUENCE_AMBIGUOUS": False,
        "ENTRY_RISK_VALID": False,
        "INITIAL_RISK_PER_SHARE": np.nan,
        "ENTRY_STATUS": "NO_FUTURE_SESSION" if not valid_dates else "EXPIRED",
    }
    if not valid_dates:
        return base
    order = frozen_stage221.PendingOrder(
        order_id=0,
        variant="STAGE3_CAPACITY_FREE",
        ticker=str(row["Ticker"]),
        signal_date=signal_date,
        signal=str(row["Signal"]),
        setup=setup,
        created_date=signal_date,
        expiry_date=valid_dates[-1],
        valid_dates=valid_dates,
        entry_low=float(row["Entry Low"]),
        entry_high=float(row["Entry High"]),
        stop=float(row["Stop Loss"]),
        target1=float(row["Target 1"]),
        target2=float(row["Target 2"]),
        actionability=float(row["Actionability Score"]),
        technical_score=float(row["Technical Score"]),
        rr_t1=float(row["R:R T1"]),
        rs60=float(row["RS 60D"]),
        market_regime=str(row.get("Market Regime", "")),
    )
    execution = frozen_stage221.ExecutionModel(frozen_config)
    fill = None
    for date in valid_dates:
        if date in frame.index:
            fill = execution.assess_fill(order, frame.loc[date], date)
            if fill is not None:
                break
    if fill is None:
        return base
    executed = execution.executed_entry(
        fill.nominal_entry,
        fill.entry_method,
        order.entry_high if setup == "PULLBACK" else None,
    )
    risk = executed - order.stop
    base.update(
        {
            "ENTRY_FILLED": True,
            "ENTRY_DATE": fill.fill_date,
            "ENTRY_LABEL_AVAILABLE_DATE": fill.fill_date,
            "ENTRY_CENSORED": False,
            "ENTRY_SESSIONS_TO_FILL": valid_dates.index(fill.fill_date) + 1,
            "NOMINAL_ENTRY": float(fill.nominal_entry),
            "EXECUTED_ENTRY": float(executed),
            "ENTRY_METHOD": str(fill.entry_method),
            "ENTRY_INTRADAY_LIMIT": bool(fill.intraday_limit),
            "ENTRY_DAY_SEQUENCE_AMBIGUOUS": bool(fill.intraday_limit),
            "ENTRY_RISK_VALID": bool(risk > 0 and order.target1 > executed),
            "INITIAL_RISK_PER_SHARE": float(risk),
            "ENTRY_STATUS": "FILLED" if risk > 0 and order.target1 > executed else "INVALID_RISK",
        }
    )
    return base


def build_opportunities(
    signal_state: pd.DataFrame,
    features: Mapping[str, pd.DataFrame],
    frozen_stage221: Any,
    frozen_config: Any,
    config: Mapping[str, Any],
) -> pd.DataFrame:
    records = []
    for row in signal_state.to_dict("records"):
        eligible, cohort, reason = opportunity_eligibility(row, config)
        if not eligible:
            continue
        item = dict(row)
        item["Opportunity Eligible"] = True
        item["Dataset Cohort"] = cohort
        item["Opportunity Eligibility Reason"] = reason
        item["STAGE3_ROW_ID"] = deterministic_row_id(
            config["dataset_schema_versions"]["trade_opportunity"], item["Signal ID"]
        )
        item.update(simulate_entry(item, features[str(item["Ticker"])], frozen_stage221, frozen_config, config))
        records.append(item)
    result = pd.DataFrame(records)
    if not result.empty:
        result["ENTRY_DATE"] = pd.to_datetime(result["ENTRY_DATE"], errors="coerce").dt.normalize()
    return result
