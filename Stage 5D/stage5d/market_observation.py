from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .ledger import canonical_json, payload_sha256
from .source_contract import canonical_date


def finite_decimal(value: Any, name: str, *, optional: bool = False) -> Decimal | None:
    if value is None and optional:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be a finite decimal")
    return result


@dataclass(frozen=True)
class MarketObservation:
    ticker: str
    session_date: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    daily_supertrend: Decimal | None = None
    swing_low_10: Decimal | None = None
    source_data_hash: str | None = None
    source_name: str | None = None

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "MarketObservation":
        ticker = str(values.get("ticker", "")).strip().upper()
        if not ticker:
            raise ValueError("ticker is required")
        result = cls(
            ticker=ticker,
            session_date=canonical_date(values.get("session_date"), "session_date"),
            open=finite_decimal(values.get("open"), "open"),
            high=finite_decimal(values.get("high"), "high"),
            low=finite_decimal(values.get("low"), "low"),
            close=finite_decimal(values.get("close"), "close"),
            daily_supertrend=finite_decimal(values.get("daily_supertrend"), "daily_supertrend", optional=True),
            swing_low_10=finite_decimal(values.get("swing_low_10"), "swing_low_10", optional=True),
            source_data_hash=None if values.get("source_data_hash") is None else str(values["source_data_hash"]),
            source_name=None if values.get("source_name") is None else str(values["source_name"]),
        )
        if min(result.open, result.high, result.low, result.close) <= 0:
            raise ValueError("OHLC values must be positive")
        if result.high < max(result.open, result.close, result.low) or result.low > min(result.open, result.close):
            raise ValueError("inconsistent OHLC bar")
        return result

    @property
    def observation_id(self) -> str:
        return f"OBS_{payload_sha256(self.ticker + '|' + self.session_date)[:24]}"

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_payload(self) -> str:
        return canonical_json(self.payload())
