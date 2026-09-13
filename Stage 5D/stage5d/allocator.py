from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Iterable

from .horizon import HorizonAssessment, HorizonPreference, HorizonStatus, assess_horizon
from .portfolio_state import OpenPosition, PortfolioSnapshot, decimal_value
from .user_profile import InvestmentProfile

RISK_FRACTION = Decimal("0.0075")
POSITION_CAP_FRACTION = Decimal("0.25")
MAX_OPEN_POSITIONS = 5
ACTIONABLE_DETERMINISTIC_SIGNALS = frozenset({"STRONG BUY", "BUY"})

SOURCE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "signal_id": ("signal_id", "Signal ID"),
    "ticker": ("ticker", "Ticker", "Symbol"),
    "signal_date": ("signal_date", "Signal Date", "Date"),
    "decision_date": ("decision_date", "Decision Date"),
    "deterministic_signal": ("deterministic_signal", "Signal"),
    "entry_low": ("entry_low", "Entry Low"),
    "entry_high": ("entry_high", "Entry High"),
    "sizing_entry_price": ("sizing_entry_price", "Sizing Entry Price"),
    "stop": ("stop", "Stop", "Stop Loss"),
    "target_1": ("target_1", "Target 1"),
    "target_2": ("target_2", "Target 2"),
    "deterministic_rank": ("deterministic_rank", "Deterministic Rank", "Rank"),
}


def _source_value(candidate: dict[str, object], field: str) -> object | None:
    for alias in SOURCE_FIELD_ALIASES[field]:
        if alias in candidate:
            return candidate[alias]
    return None


def normalize_source_candidate(candidate: dict[str, object]) -> dict[str, object]:
    """Explicitly adapt frozen Stage 1.2.3-style fields to Stage 5D names."""
    normalized = {field: _source_value(candidate, field) for field in SOURCE_FIELD_ALIASES}
    normalized["ticker"] = str(normalized["ticker"] or "").strip()
    normalized["signal_id"] = str(normalized["signal_id"] or "").strip()
    normalized["signal_date"] = str(normalized["signal_date"] or "").strip()
    normalized["decision_date"] = str(normalized["decision_date"] or normalized["signal_date"]).strip()
    normalized["deterministic_signal"] = " ".join(str(normalized["deterministic_signal"] or "").strip().upper().split())
    if normalized["sizing_entry_price"] is None:
        normalized["sizing_entry_price"] = normalized["entry_high"]
    return normalized


def _whole_shares(amount: Decimal, price_or_risk: Decimal) -> int:
    if amount <= 0 or price_or_risk <= 0:
        return 0
    return int((amount / price_or_risk).to_integral_value(rounding=ROUND_FLOOR))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _nullable_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return decimal_value(value)
    except (ValueError, TypeError, ArithmeticError):
        return None


def _nullable_money(value: Decimal | None) -> float | None:
    return None if value is None else _money(value)


def _rank_key(value: object | None) -> tuple[int, str]:
    if value is None:
        return 2_147_483_647, ""
    try:
        return int(value), ""
    except (ValueError, TypeError):
        return 2_147_483_647, str(value)


def _stable_order(candidate: dict[str, object]) -> tuple[object, ...]:
    rank, invalid_rank = _rank_key(candidate.get("deterministic_rank"))
    return (
        rank, invalid_rank, str(candidate.get("signal_date", "")),
        str(candidate.get("ticker", "")), str(candidate.get("signal_id", "")),
    )


def _canonical_value(value: object | None) -> object:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    if not number.is_finite():
        return None
    return format(number.normalize(), "f")


def _candidate_identity(candidate: dict[str, object]) -> dict[str, object]:
    return {
        key: (_canonical_value(value) if key in {
            "entry_low", "entry_high", "sizing_entry_price", "stop", "target_1", "target_2", "deterministic_rank"
        } else value)
        for key, value in candidate.items()
    }


def _allocation_run_id(
    profile: InvestmentProfile,
    portfolio: PortfolioSnapshot,
    candidates: list[dict[str, object]],
    horizon: HorizonAssessment,
    decision_date: str | None,
) -> str:
    positions = [
        {
            "ticker": position.ticker.strip().upper(),
            "quantity": position.quantity,
            "current_market_price_inr": _canonical_value(position.current_price_inr),
            "cost_basis_per_share_inr": _canonical_value(position.cost_basis_per_share_inr),
        }
        for position in sorted(portfolio.positions, key=lambda item: (item.ticker.strip().upper(), item.quantity, item.current_price_inr, item.cost_basis_per_share_inr))
    ]
    payload = {
        "profile_version": profile.profile_version,
        "capital_ceiling_inr": _canonical_value(profile.capital_ceiling_inr),
        "selected_horizon": profile.preferred_horizon.value,
        "management_policy": {
            "id": horizon.management_policy_id,
            "source": horizon.management_policy_source,
            "max_sessions": horizon.management_policy_max_sessions,
            "validation_semantics": horizon.management_policy_validation_semantics,
        },
        "open_positions": positions,
        "reserved_capital_for_pending_entries_inr": _canonical_value(portfolio.reserved_capital_for_pending_entries_inr),
        "candidate_decision_inputs": [_candidate_identity(item) for item in candidates],
        "decision_date": decision_date,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "S5D1_RUN_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _recommendation_id(allocation_run_id: str, candidate: dict[str, object], ordinal: int) -> str:
    identity = {
        "allocation_run_id": allocation_run_id,
        "candidate_identity": _candidate_identity(candidate),
        "candidate_ordinal": ordinal,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "S5D1_REC_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _source_status(signal: str) -> str:
    if signal.startswith("WATCH"):
        return "WATCH_SOURCE_SIGNAL"
    if signal == "AVOID":
        return "AVOID_SOURCE_SIGNAL"
    return "WAIT_SOURCE_SIGNAL"


@dataclass(frozen=True)
class AllocationResult:
    allocation_run_id: str
    recommendations: tuple[dict[str, object], ...]
    portfolio_summary: dict[str, object]
    portfolio_snapshot: PortfolioSnapshot


def allocate_candidates(
    profile: InvestmentProfile,
    open_positions: Iterable[OpenPosition],
    candidates: Iterable[dict[str, object]],
    *,
    reserved_capital_for_pending_entries_inr: object = 0,
    decision_date: str | None = None,
) -> AllocationResult:
    portfolio = PortfolioSnapshot.create(profile.capital_ceiling_inr, open_positions, reserved_capital_for_pending_entries_inr)
    normalized_candidates = sorted((normalize_source_candidate(dict(item)) for item in candidates), key=_stable_order)
    horizon = assess_horizon({}, profile.preferred_horizon)
    effective_decision_date = decision_date
    if effective_decision_date is None:
        dates = [str(item["decision_date"]) for item in normalized_candidates if item.get("decision_date")]
        effective_decision_date = max(dates) if dates else None
    allocation_run_id = _allocation_run_id(profile, portfolio, normalized_candidates, horizon, effective_decision_date)

    available = portfolio.available_capital_for_new_positions_inr
    proposed_positions = 0
    recommendations: list[dict[str, object]] = []
    risk_budget = profile.capital_ceiling_inr * RISK_FRACTION
    position_cap = profile.capital_ceiling_inr * POSITION_CAP_FRACTION
    existing_tickers = {position.ticker.strip().upper() for position in portfolio.positions}
    seen_actionable_tickers: set[str] = set()

    for ordinal, candidate in enumerate(normalized_candidates, start=1):
        available_before = available
        signal = str(candidate["deterministic_signal"])
        ticker = str(candidate["ticker"])
        ticker_key = ticker.upper()
        actionable_signal = signal in ACTIONABLE_DETERMINISTIC_SIGNALS

        entry_low = _nullable_decimal(candidate.get("entry_low"))
        entry_high = _nullable_decimal(candidate.get("entry_high"))
        entry = _nullable_decimal(candidate.get("sizing_entry_price"))
        stop = _nullable_decimal(candidate.get("stop"))
        target_1 = _nullable_decimal(candidate.get("target_1"))
        target_2 = _nullable_decimal(candidate.get("target_2"))
        risk_per_share = entry - stop if entry is not None and stop is not None else None
        max_cash = max_risk = max_position = 0
        quantity = 0

        if not actionable_signal:
            status = _source_status(signal)
            reason = f"Deterministic source signal {signal or 'UNSPECIFIED'} is not actionable; no capital is proposed."
        else:
            duplicate_ticker = ticker_key in seen_actionable_tickers
            seen_actionable_tickers.add(ticker_key)
            levels_valid = (
                bool(ticker_key) and entry_low is not None and entry_high is not None and entry is not None
                and stop is not None and target_1 is not None and target_2 is not None
                and entry_low > 0 and entry_high > 0 and entry > 0 and stop >= 0
                and target_1 > 0 and target_2 > 0 and risk_per_share is not None and risk_per_share > 0
            )
            if duplicate_ticker:
                status, reason = "BLOCKED_DUPLICATE_TICKER", "A prior actionable candidate for this ticker already exists in this allocation run."
            elif ticker_key in existing_tickers:
                status, reason = "BLOCKED_EXISTING_POSITION", "Existing position already open; Stage 5D does not pyramid or average into an existing holding."
            elif portfolio.portfolio_status == "OVER_NEW_CAP":
                status, reason = "BLOCKED_PORTFOLIO_OVER_CAP", f"Current market exposure exceeds the capital ceiling by INR {_money(portfolio.capital_overage_inr):.2f}; existing positions are not force-sold."
            elif portfolio.portfolio_status == "OVER_COMMITTED_CAP":
                status, reason = "BLOCKED_COMMITTED_CAPITAL_OVERAGE", f"Open-position market value plus reserved pending capital exceeds the ceiling by INR {_money(portfolio.committed_capital_overage_inr):.2f}; no pending order is cancelled automatically."
            elif horizon.horizon_status is not HorizonStatus.ELIGIBLE:
                status, reason = "WATCH_HORIZON_MISMATCH", horizon.estimated_or_rule_based_holding_compatibility
            elif not levels_valid:
                status, reason = "WATCH_INVALID_RISK", "Actionable BUY signals require finite positive entry, target, and risk-defining stop levels."
            else:
                assert entry is not None and risk_per_share is not None
                max_cash = _whole_shares(available, entry)
                max_risk = _whole_shares(risk_budget, risk_per_share)
                max_position = _whole_shares(position_cap, entry)
                if max_cash < 1:
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

        purchase = (entry or Decimal("0")) * quantity
        if quantity:
            available -= purchase
            proposed_positions += 1
        row = {
            "allocation_run_id": allocation_run_id,
            "recommendation_id": _recommendation_id(allocation_run_id, candidate, ordinal),
            "profile_version": profile.profile_version,
            "ticker": ticker,
            "signal_date": str(candidate["signal_date"]),
            "decision_date": str(candidate["decision_date"]),
            "deterministic_signal": signal,
            "entry_low": _nullable_money(entry_low),
            "entry_high": _nullable_money(entry_high),
            "sizing_entry_price": _nullable_money(entry),
            "stop": _nullable_money(stop),
            "target_1": _nullable_money(target_1),
            "target_2": _nullable_money(target_2),
            "capital_ceiling_inr": _money(profile.capital_ceiling_inr),
            "deployed_before_inr": _money(portfolio.current_market_value_of_open_positions_inr),
            "available_before_inr": _money(available_before),
            "risk_budget_inr": _money(risk_budget),
            "risk_per_share_inr": _nullable_money(risk_per_share),
            "max_qty_by_cash": max_cash,
            "max_qty_by_risk": max_risk,
            "max_qty_by_position_cap": max_position,
            "recommended_quantity": int(quantity),
            "estimated_purchase_value_inr": _money(purchase),
            "available_after_inr": _money(available),
            "selected_horizon": profile.preferred_horizon.value,
            "horizon_session_limit": horizon.horizon_session_limit,
            "management_policy_id": horizon.management_policy_id,
            "management_policy_source": horizon.management_policy_source,
            "management_policy_max_sessions": horizon.management_policy_max_sessions,
            "management_policy_validation_semantics": horizon.management_policy_validation_semantics,
            "estimated_or_rule_based_holding_compatibility": horizon.estimated_or_rule_based_holding_compatibility,
            "horizon_status": horizon.horizon_status.value,
            "portfolio_action_status": status,
            "plain_language_reason": reason,
        }
        recommendations.append(row)

    recommended_deployment = sum((Decimal(str(row["estimated_purchase_value_inr"])) for row in recommendations), Decimal("0"))
    actionable = sum(row["portfolio_action_status"] == "ACTIONABLE_BUY" for row in recommendations)
    summary_status = portfolio.portfolio_status if portfolio.portfolio_status != "WITHIN_CAP" else ("ALLOCATIONS_PROPOSED" if actionable else "NO_ACTIONABLE_BUY")
    summary = {
        "allocation_run_id": allocation_run_id,
        "profile_version": profile.profile_version,
        "capital_ceiling_inr": _money(profile.capital_ceiling_inr),
        "current_market_value_of_open_positions_inr": _money(portfolio.current_market_value_of_open_positions_inr),
        "cost_basis_of_open_positions_inr": _money(portfolio.cost_basis_of_open_positions_inr),
        "reserved_capital_for_pending_entries_inr": _money(portfolio.reserved_capital_for_pending_entries_inr),
        "committed_capital_inr": _money(portfolio.committed_capital_inr),
        "committed_capital_overage_inr": _money(portfolio.committed_capital_overage_inr),
        "available_capital_before_inr": _money(portfolio.available_capital_for_new_positions_inr),
        "selected_horizon": profile.preferred_horizon.value,
        "horizon_session_limit": horizon.horizon_session_limit,
        "horizon_status": horizon.horizon_status.value,
        "management_policy_id": horizon.management_policy_id,
        "management_policy_source": horizon.management_policy_source,
        "management_policy_max_sessions": horizon.management_policy_max_sessions,
        "management_policy_validation_semantics": horizon.management_policy_validation_semantics,
        "decision_date": effective_decision_date,
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
    return AllocationResult(allocation_run_id, tuple(recommendations), summary, portfolio)
