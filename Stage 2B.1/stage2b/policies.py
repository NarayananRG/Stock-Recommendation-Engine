"""Deterministic post-entry policies for Stage 2B. No entry logic lives here."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional
import math


POLICIES = (
    "D1_TRAIL_ONLY", "D2_BREAK_EVEN_TRAIL", "D3_PARTIAL_T1_TRAIL",
    "D4_TREND_PROTECT", "D5_RESISTANCE_TIGHTEN", "D6_HYBRID_DYNAMIC",
)


@dataclass(frozen=True)
class PolicyConfig:
    """Authoritative behavioral constants for the accepted Stage 2B policies."""

    partial_fraction: float
    break_even_trigger_r: float
    max_hold_sessions: int
    swing_low_sessions: int

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "PolicyConfig":
        config = cls(
            partial_fraction=float(values["partial_fraction"]),
            break_even_trigger_r=float(values["break_even_trigger_r"]),
            max_hold_sessions=int(values["max_hold_sessions"]),
            swing_low_sessions=int(values["swing_low_sessions"]),
        )
        if config.swing_low_sessions != 10:
            raise ValueError("Accepted Stage 2B requires swing_low_sessions == 10")
        if not 0 < config.partial_fraction <= 1:
            raise ValueError("partial_fraction must be in (0, 1]")
        if config.max_hold_sessions <= 0 or config.break_even_trigger_r < 0:
            raise ValueError("Invalid management policy configuration")
        return config


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


def decide_after_close(
    policy: str,
    state: Dict[str, Any],
    row: Any,
    resistance: Optional[float],
    config: Optional[PolicyConfig] = None,
) -> ManagementDecision:
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
        trigger_r = 1.0 if config is None else config.break_even_trigger_r
        if state["current_r"] >= trigger_r and state["executed_entry"] > proposed_stop:
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
