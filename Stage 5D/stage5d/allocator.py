from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Iterable

from .horizon import HorizonPreference, HorizonStatus, assess_horizon
from .portfolio_state import OpenPosition, PortfolioSnapshot, decimal_value
from .user_profile import InvestmentProfile

RISK_FRACTION = Decimal("0.0075")
POSITION_CAP_FRACTION = Decimal("0.25")
MAX_OPEN_POSITIONS = 5


def _whole_shares(amount: Decimal, price_or_risk: Decimal) -> int:
    if amount <= 0 or price_or_risk <= 0:
        return 0
    return int((amount / price_or_risk).to_integral_value(rounding=ROUND_FLOOR))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _candidate_value(candidate: dict[str, object], name: str, fallback: str | None = None) -> Decimal:
    value = candidate.get(name, candidate.get(fallback) if fallback else None)
    if value is None:
        raise ValueError(f"candidate is missing {name}")
    return decimal_value(value)


def _stable_order(candidate: dict[str, object]) -> tuple[object, ...]:
    rank = candidate.get("deterministic_rank")
    normalized_rank = int(rank) if rank is not None else 2_147_483_647
    return normalized_rank, str(candidate.get("signal_date", "")), str(candidate.get("ticker", "")), str(candidate.get("signal_id", ""))


def _recommendation_id(candidate: dict[str, object], profile_version: int) -> str:
    allowed = {key: candidate.get(key) for key in ("signal_id", "ticker", "signal_date", "deterministic_signal", "entry_low", "entry_high", "sizing_entry_price", "stop", "target_1", "target_2", "deterministic_rank", "validated_holding_sessions", "holding_evidence_source")}
    payload = json.dumps({"profile_version": profile_version, "candidate": allowed}, sort_keys=True, separators=(",", ":"), default=str)
    return "S5D1_REC_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class AllocationResult:
    recommendations: tuple[dict[str, object], ...]
    portfolio_summary: dict[str, object]
    portfolio_snapshot: PortfolioSnapshot


def allocate_candidates(
    profile: InvestmentProfile,
    open_positions: Iterable[OpenPosition],
    candidates: Iterable[dict[str, object]],
    *,
    reserved_capital_for_pending_entries_inr: object = 0,
) -> AllocationResult:
    portfolio = PortfolioSnapshot.create(profile.capital_ceiling_inr, open_positions, reserved_capital_for_pending_entries_inr)
    available = portfolio.available_capital_for_new_positions_inr
    proposed_positions = 0
    recommendations: list[dict[str, object]] = []
    risk_budget = profile.capital_ceiling_inr * RISK_FRACTION
    position_cap = profile.capital_ceiling_inr * POSITION_CAP_FRACTION

    for candidate in sorted((dict(item) for item in candidates), key=_stable_order):
        available_before = available
        horizon = assess_horizon(candidate, profile.preferred_horizon)
        entry_low = _candidate_value(candidate, "entry_low")
        entry_high = _candidate_value(candidate, "entry_high")
        entry = _candidate_value(candidate, "sizing_entry_price", "entry_high")
        stop = _candidate_value(candidate, "stop")
        target_1 = _candidate_value(candidate, "target_1")
        target_2 = _candidate_value(candidate, "target_2")
        risk_per_share = entry - stop
        max_cash = _whole_shares(available, entry)
        max_risk = _whole_shares(risk_budget, risk_per_share)
        max_position = _whole_shares(position_cap, entry)
        quantity = 0

        signal = str(candidate.get("deterministic_signal", ""))
        if not portfolio.new_buys_allowed:
            status, reason = "BLOCKED_PORTFOLIO_OVER_CAP", f"Current market exposure exceeds the new capital ceiling by INR {_money(portfolio.capital_overage_inr):.2f}; existing positions continue under deterministic exits."
        elif signal != "BUY":
            status, reason = "WAIT_NO_QUALIFYING_SETUP", "The deterministic strategy did not produce an eligible BUY setup."
        elif horizon.horizon_status is not HorizonStatus.ELIGIBLE:
            status, reason = "WATCH_HORIZON_MISMATCH", horizon.estimated_or_rule_based_holding_compatibility
        elif entry <= 0 or entry_low <= 0 or entry_high <= 0 or risk_per_share <= 0:
            status, reason = "WATCH_INVALID_RISK", "Entry and stop do not define positive per-share risk."
        elif max_cash < 1:
            status, reason = "WATCH_INSUFFICIENT_CAPITAL", "Available cash cannot purchase one whole share at the sizing entry price."
        elif max_risk < 1:
            status, reason = "WATCH_RISK_BUDGET_TOO_SMALL", "One-share risk exceeds the fixed 0.75% risk budget; the rule is not overridden."
        elif max_position < 1:
            status, reason = "WATCH_POSITION_CAP_TOO_SMALL", "One share would exceed the fixed 25% position cap."
        elif portfolio.number_of_open_positions + proposed_positions >= MAX_OPEN_POSITIONS:
            status, reason = "BLOCKED_MAX_POSITIONS", "The five-position portfolio limit is already reached."
        else:
            quantity = min(max_cash, max_risk, max_position)
            status, reason = "ACTIONABLE_BUY", f"Proposed {quantity} whole shares within cash, 0.75% risk, 25% position, and five-position limits."

        purchase = entry * quantity
        available_after = available - purchase
        if quantity:
            available = available_after
            proposed_positions += 1
        row = {
            "recommendation_id": _recommendation_id(candidate, profile.profile_version),
            "profile_version": profile.profile_version,
            "ticker": str(candidate.get("ticker", "")),
            "signal_date": str(candidate.get("signal_date", "")),
            "deterministic_signal": signal,
            "entry_low": _money(entry_low), "entry_high": _money(entry_high), "sizing_entry_price": _money(entry),
            "stop": _money(stop), "target_1": _money(target_1), "target_2": _money(target_2),
            "capital_ceiling_inr": _money(profile.capital_ceiling_inr),
            "deployed_before_inr": _money(portfolio.current_market_value_of_open_positions_inr),
            "available_before_inr": _money(available_before),
            "risk_budget_inr": _money(risk_budget), "risk_per_share_inr": _money(risk_per_share),
            "max_qty_by_cash": max_cash, "max_qty_by_risk": max_risk, "max_qty_by_position_cap": max_position,
            "recommended_quantity": int(quantity), "estimated_purchase_value_inr": _money(purchase),
            "available_after_inr": _money(available_after if quantity else available),
            "selected_horizon": profile.preferred_horizon.value, "horizon_session_limit": horizon.horizon_session_limit,
            "estimated_or_rule_based_holding_compatibility": horizon.estimated_or_rule_based_holding_compatibility,
            "horizon_status": horizon.horizon_status.value, "portfolio_action_status": status, "plain_language_reason": reason,
        }
        recommendations.append(row)

    recommended_deployment = sum((Decimal(str(row["estimated_purchase_value_inr"])) for row in recommendations), Decimal("0"))
    actionable = sum(row["portfolio_action_status"] == "ACTIONABLE_BUY" for row in recommendations)
    summary_status = portfolio.portfolio_status if portfolio.portfolio_status == "OVER_NEW_CAP" else ("ALLOCATIONS_PROPOSED" if actionable else "NO_ACTIONABLE_BUY")
    summary = {
        "profile_version": profile.profile_version,
        "capital_ceiling_inr": _money(profile.capital_ceiling_inr),
        "current_market_value_of_open_positions_inr": _money(portfolio.current_market_value_of_open_positions_inr),
        "cost_basis_of_open_positions_inr": _money(portfolio.cost_basis_of_open_positions_inr),
        "reserved_capital_for_pending_entries_inr": _money(portfolio.reserved_capital_for_pending_entries_inr),
        "available_capital_before_inr": _money(portfolio.available_capital_for_new_positions_inr),
        "selected_horizon": profile.preferred_horizon.value,
        "open_positions": portfolio.number_of_open_positions,
        "maximum_open_positions": MAX_OPEN_POSITIONS,
        "portfolio_status": portfolio.portfolio_status,
        "new_buys_allowed": portfolio.new_buys_allowed,
        "capital_overage_inr": _money(portfolio.capital_overage_inr),
        "recommended_new_deployment_inr": _money(recommended_deployment),
        "cash_after_proposed_orders_inr": _money(available),
        "actionable_recommendations": actionable,
        "allocation_status": summary_status,
        "cash_retention_is_valid": True,
    }
    return AllocationResult(tuple(recommendations), summary, portfolio)
