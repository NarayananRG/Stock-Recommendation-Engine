from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

from .portfolio_state import decimal_value

STRATEGY_VERSION = "STAGE_2_1_FROZEN"
ACTIONABLE_DETERMINISTIC_SIGNALS = frozenset({"STRONG BUY", "BUY"})
FROZEN_RANKING_CONTRACT = (
    "SIGNAL",
    "ACTIONABILITY_DESC",
    "TECHNICAL_DESC",
    "RR_T1_DESC",
    "RS60_DESC",
    "TICKER_ASC",
)

SOURCE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "signal_id": ("signal_id", "Signal ID"),
    "ticker": ("ticker", "Ticker", "Symbol"),
    "signal_date": ("signal_date", "Signal Date", "Date"),
    "decision_date": ("decision_date", "Decision Date"),
    "deterministic_signal": ("deterministic_signal", "Signal"),
    "setup": ("setup", "Setup"),
    "trade_quality": ("trade_quality", "Trade Quality"),
    "technical_score": ("technical_score", "Technical Score"),
    "actionability_score": ("actionability_score", "Actionability Score"),
    "market_regime": ("market_regime", "Market Regime"),
    "market_score": ("market_score", "Market Score"),
    "entry_low": ("entry_low", "Entry Low"),
    "entry_high": ("entry_high", "Entry High"),
    "sizing_entry_price": ("sizing_entry_price", "Sizing Entry Price"),
    "stop": ("stop", "Stop", "Stop Loss"),
    "target_1": ("target_1", "Target 1"),
    "target_2": ("target_2", "Target 2"),
    "planned_rr_t1": ("planned_rr_t1", "Planned R:R T1", "R:R T1"),
    "planned_rr_t2": ("planned_rr_t2", "Planned R:R T2", "R:R T2"),
    "rs60": ("rs60", "RS 60D"),
}

NUMERIC_FIELDS = frozenset({
    "technical_score", "actionability_score", "market_score", "entry_low",
    "entry_high", "sizing_entry_price", "stop", "target_1", "target_2",
    "planned_rr_t1", "planned_rr_t2", "rs60",
})
REQUIRED_ACTIONABLE_RANKING_FIELDS = {
    "actionability_score": "Actionability Score",
    "technical_score": "Technical Score",
    "planned_rr_t1": "R:R T1",
    "rs60": "RS 60D",
}
REQUIRED_ACTIONABLE_LEVEL_FIELDS = {
    "entry_low": "Entry Low",
    "entry_high": "Entry High",
    "sizing_entry_price": "Sizing Entry Price",
    "stop": "Stop Loss",
    "target_1": "Target 1",
    "target_2": "Target 2",
}


def canonical_date(value: object, field_name: str = "date") -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")
    try:
        if value != value:
            raise ValueError(f"{field_name} is invalid")
    except TypeError:
        pass
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        parsed = value.replace(tzinfo=None).date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{field_name} is required")
        try:
            if len(text) == 10:
                parsed = date.fromisoformat(text)
            else:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None).date()
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a valid date") from exc
    return parsed.isoformat()


def derive_signal_id(*, ticker: str, signal_date: str, signal: str, setup: str) -> str:
    payload = {
        "strategy_version": STRATEGY_VERSION,
        "ticker": ticker,
        "signal_date": canonical_date(signal_date, "signal_date").replace("-", ""),
        "signal": signal,
        "setup": setup,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "SIG_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _source_value(candidate: dict[str, object], field: str) -> object | None:
    for alias in SOURCE_FIELD_ALIASES[field]:
        if alias in candidate:
            return candidate[alias]
    return None


def _nullable_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return decimal_value(value)
    except (ValueError, TypeError, ArithmeticError):
        return None


def normalize_source_candidate(candidate: dict[str, object]) -> dict[str, object]:
    """Adapt and validate one frozen scanner row without consulting ML metadata."""
    normalized = {field: _source_value(candidate, field) for field in SOURCE_FIELD_ALIASES}
    ticker = str(normalized["ticker"] or "").strip()
    signal = " ".join(str(normalized["deterministic_signal"] or "").strip().upper().split())
    if not ticker:
        raise ValueError("Deterministic input contract failure: Ticker is required")
    if not signal:
        raise ValueError(f"Deterministic input contract failure for {ticker}: Signal is required")
    signal_date = canonical_date(normalized["signal_date"], "signal_date")
    candidate_decision_date = normalized["decision_date"]
    setup = str(normalized["setup"] or "")
    normalized.update({
        "ticker": ticker,
        "signal_date": signal_date,
        "decision_date": canonical_date(candidate_decision_date, "decision_date") if candidate_decision_date is not None else None,
        "deterministic_signal": signal,
        "setup": setup,
        "trade_quality": None if normalized["trade_quality"] is None else str(normalized["trade_quality"]),
        "market_regime": None if normalized["market_regime"] is None else str(normalized["market_regime"]),
    })
    if normalized["sizing_entry_price"] is None:
        normalized["sizing_entry_price"] = normalized["entry_high"]
    for field in NUMERIC_FIELDS:
        normalized[field] = _nullable_decimal(normalized[field])

    expected_signal_id = derive_signal_id(ticker=ticker, signal_date=signal_date, signal=signal, setup=setup)
    supplied_signal_id = normalized["signal_id"]
    if supplied_signal_id is not None and str(supplied_signal_id).strip() != expected_signal_id:
        raise ValueError(f"Signal ID mismatch for {ticker}: expected {expected_signal_id}, received {supplied_signal_id}")
    normalized["signal_id"] = expected_signal_id

    if signal in ACTIONABLE_DETERMINISTIC_SIGNALS:
        for field, source_name in REQUIRED_ACTIONABLE_RANKING_FIELDS.items():
            if normalized[field] is None:
                raise ValueError(f"Deterministic input contract failure for {ticker}: actionable row requires finite {source_name}")
        for field, source_name in REQUIRED_ACTIONABLE_LEVEL_FIELDS.items():
            if normalized[field] is None:
                raise ValueError(f"Deterministic input contract failure for {ticker}: actionable row requires finite {source_name}")
    return normalized


def frozen_priority_key(candidate: dict[str, object]) -> tuple[object, ...]:
    signal = str(candidate["deterministic_signal"])
    if signal not in ACTIONABLE_DETERMINISTIC_SIGNALS:
        return (2, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), str(candidate["ticker"]))
    return (
        0 if signal == "STRONG BUY" else 1,
        -Decimal(candidate["actionability_score"]),
        -Decimal(candidate["technical_score"]),
        -Decimal(candidate["planned_rr_t1"]),
        -Decimal(candidate["rs60"]),
        str(candidate["ticker"]),
    )
