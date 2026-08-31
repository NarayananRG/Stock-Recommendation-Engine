"""Deterministic post-entry policies for Stage 2B. No entry logic lives here."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import math


POLICIES = (
    "D1_TRAIL_ONLY", "D2_BREAK_EVEN_TRAIL", "D3_PARTIAL_T1_TRAIL",
    "D4_TREND_PROTECT", "D5_RESISTANCE_TIGHTEN", "D6_HYBRID_DYNAMIC",
)


@dataclass
class ManagementDecision:
    proposed_stop: float
    proposed_target: float
    decision: str = "HOLD"
    reason: str = "HOLD_NO_CHANGE"
    scheduled_exit: Optional[str] = None


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def trend_reason(row: Any) -> Optional[str]:
    close = _finite(row.get("Close")); sma20 = _finite(row.get("SMA20")); sma50 = _finite(row.get("SMA50"))
    daily = _finite(row.get("STTrend")); weekly = _finite(row.get("WeeklySTTrend"))
    if close is not None and sma20 is not None and daily is not None and daily < 0 and close < sma20:
        return "EXIT_DAILY_TREND_DETERIORATION"
    if close is not None and sma50 is not None and weekly is not None and weekly < 0 and close < sma50:
        return "EXIT_WEEKLY_TREND_DETERIORATION"
    return None


def decide_after_close(policy: str, state: Dict[str, Any], row: Any, resistance: Optional[float]) -> ManagementDecision:
    """Return a D+1 decision from a completed D bar; never executes it."""
    old_stop = float(state["current_stop"]); old_target = float(state["active_target"])
    close = float(row["Close"]); proposed_stop = old_stop; stop_reason = ""
    if policy in POLICIES:
        st = _finite(row.get("ST")); swing = _finite(row.get("SwingLow10"))
        if st is not None and old_stop < st < close and st > proposed_stop:
            proposed_stop, stop_reason = st, "TRAIL_SUPERTREND"
        if swing is not None and old_stop < swing < close and swing > proposed_stop:
            proposed_stop, stop_reason = swing, "TRAIL_SWING_LOW"
    if policy in {"D2_BREAK_EVEN_TRAIL", "D3_PARTIAL_T1_TRAIL", "D4_TREND_PROTECT", "D5_RESISTANCE_TIGHTEN", "D6_HYBRID_DYNAMIC"}:
        if state["current_r"] >= 1.0 and state["executed_entry"] > proposed_stop:
            proposed_stop, stop_reason = float(state["executed_entry"]), "BREAK_EVEN_TRIGGERED"

    proposed_target = old_target; target_reason = ""
    if policy in {"D5_RESISTANCE_TIGHTEN", "D6_HYBRID_DYNAMIC"} and state["partial_taken"] and resistance is not None:
        if close < resistance < old_target:
            proposed_target, target_reason = float(resistance), "TARGET_TIGHTEN_RESISTANCE"

    tr = trend_reason(row) if policy in {"D4_TREND_PROTECT", "D6_HYBRID_DYNAMIC"} else None
    scheduled = tr
    if policy == "D6_HYBRID_DYNAMIC" and tr and state.get("t1_q75") is not None:
        if state["days_held"] > state["t1_q75"] and not state["partial_taken"] and state["current_r"] <= 0:
            scheduled = "EXIT_STALE_TRADE"

    if scheduled:
        return ManagementDecision(proposed_stop, proposed_target, "SCHEDULE_EXIT", scheduled, scheduled)
    if target_reason:
        return ManagementDecision(proposed_stop, proposed_target, "TIGHTEN_TARGET", target_reason)
    if proposed_stop > old_stop:
        return ManagementDecision(proposed_stop, proposed_target, "RAISE_STOP", stop_reason)
    return ManagementDecision(old_stop, old_target)
