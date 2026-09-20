from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .market_observation import MarketObservation


SUPPORTED_POLICIES = {"STATIC_T2_20D": 20, "D1_TRAIL_ONLY_63D": 63}


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    reason: str
    exit_reason: str | None = None
    reference_trigger_price: Decimal | None = None
    proposed_stop_after_close: Decimal | None = None
    next_session_stop: Decimal | None = None


def d1_after_close(old_stop: Decimal, close: Decimal, st: Decimal | None, swing: Decimal | None) -> tuple[Decimal, str]:
    candidates: list[tuple[Decimal, str]] = []
    if st is not None and old_stop < st < close:
        candidates.append((st, "TRAIL_SUPERTREND"))
    if swing is not None and old_stop < swing < close:
        candidates.append((swing, "TRAIL_SWING_LOW"))
    if not candidates:
        return old_stop, "HOLD_NO_CHANGE"
    return max(candidates, key=lambda item: item[0])


def evaluate_completed_session(
    policy_id: str,
    bars_held: int,
    effective_stop: Decimal,
    active_target: Decimal,
    observation: MarketObservation,
    *,
    is_entry_day: bool = False,
    entry_execution_context: str = "REAL_USER_FILL_ORDER_UNKNOWN",
) -> PolicyDecision:
    if policy_id not in SUPPORTED_POLICIES:
        return PolicyDecision("UNSUPPORTED_POLICY", "UNSUPPORTED_POLICY")

    # A real fill timestamp/order is not in Stage 5D.2. Full-day extremes cannot
    # safely be attributed to the post-fill portion of the entry session.
    if is_entry_day and entry_execution_context == "REAL_USER_FILL_ORDER_UNKNOWN":
        decision = PolicyDecision("ENTRY_BAR_EXECUTION_ORDER_UNRESOLVED", "ENTRY_BAR_EXECUTION_ORDER_UNRESOLVED")
    else:
        if is_entry_day and entry_execution_context == "SYNTHETIC_INTRADAY_LIMIT":
            stop_hit = observation.low <= effective_stop
            target_hit = observation.high >= active_target
            if stop_hit:
                reason = "STOP_COLLISION_ENTRY_BAR" if target_hit else "STOP_ENTRY_BAR"
                return PolicyDecision("EXIT_TRIGGERED_STOP_COLLISION" if target_hit else "EXIT_TRIGGERED_STOP", reason, reason, effective_stop)
            # Target-only ordering relative to a limit fill is unknowable.
            decision = PolicyDecision("ENTRY_BAR_EXECUTION_ORDER_UNRESOLVED", "ENTRY_BAR_TARGET_ONLY_UNRESOLVED")
        else:
            # Known-open entry deliberately skips gap logic on that entry bar;
            # otherwise gap adjudication precedes ordinary range adjudication.
            if not (is_entry_day and entry_execution_context == "SYNTHETIC_KNOWN_OPEN"):
                if observation.open <= effective_stop:
                    return PolicyDecision("EXIT_TRIGGERED_STOP_GAP", "STOP_GAP", "STOP_GAP", observation.open)
                if observation.open >= active_target:
                    return PolicyDecision("EXIT_TRIGGERED_TARGET_GAP", "TARGET_GAP", "TARGET_GAP", observation.open)
            stop_hit = observation.low <= effective_stop
            target_hit = observation.high >= active_target
            if stop_hit and target_hit:
                return PolicyDecision("EXIT_TRIGGERED_STOP_COLLISION", "STOP_COLLISION", "STOP_COLLISION", effective_stop)
            if stop_hit:
                return PolicyDecision("EXIT_TRIGGERED_STOP", "STOP", "STOP", effective_stop)
            if target_hit:
                return PolicyDecision("EXIT_TRIGGERED_TARGET", "TARGET", "TARGET", active_target)
            decision = PolicyDecision("HOLD", "HOLD_NO_CHANGE")

    if bars_held >= SUPPORTED_POLICIES[policy_id]:
        reason = "TIME_20D" if policy_id == "STATIC_T2_20D" else "MAX_63D"
        label = "EXIT_DUE_TIME_20D" if policy_id == "STATIC_T2_20D" else "EXIT_DUE_MAX_63D"
        return PolicyDecision(label, reason, reason, observation.close)

    if policy_id == "D1_TRAIL_ONLY_63D":
        proposed, reason = d1_after_close(effective_stop, observation.close, observation.daily_supertrend, observation.swing_low_10)
        if proposed > effective_stop:
            return PolicyDecision(
                "RAISE_STOP_NEXT_SESSION" if decision.decision == "HOLD" else decision.decision,
                reason,
                proposed_stop_after_close=proposed,
                next_session_stop=proposed,
            )
    return decision
