from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


def decimal_value(value: object) -> Decimal:
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("portfolio values must be finite")
    return amount


def whole_share_quantity(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("quantity must be a positive whole-share number")
    try:
        quantity = Decimal(str(value))
    except Exception as exc:
        raise ValueError("quantity must be a positive whole-share number") from exc
    if not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value():
        raise ValueError("quantity must be a positive whole-share number")
    return int(quantity)


@dataclass(frozen=True)
class OpenPosition:
    ticker: str
    quantity: int
    current_price_inr: Decimal
    cost_basis_per_share_inr: Decimal

    @classmethod
    def create(cls, ticker: str, quantity: object, current_price_inr: object, cost_basis_per_share_inr: object) -> "OpenPosition":
        if not str(ticker).strip():
            raise ValueError("open positions require a ticker")
        checked_quantity = whole_share_quantity(quantity)
        current = decimal_value(current_price_inr)
        basis = decimal_value(cost_basis_per_share_inr)
        if current < 0 or basis < 0:
            raise ValueError("prices cannot be negative")
        return cls(str(ticker).strip(), checked_quantity, current, basis)

    @property
    def market_value_inr(self) -> Decimal:
        return self.current_price_inr * self.quantity

    @property
    def cost_basis_inr(self) -> Decimal:
        return self.cost_basis_per_share_inr * self.quantity


@dataclass(frozen=True)
class PendingEntryReservation:
    ticker: str
    reserved_capital_inr: Decimal
    source_recommendation_id: str | None = None
    source_signal_id: str | None = None

    @classmethod
    def create(
        cls,
        ticker: str,
        reserved_capital_inr: object,
        source_recommendation_id: str | None = None,
        source_signal_id: str | None = None,
    ) -> "PendingEntryReservation":
        normalized_ticker = str(ticker).strip()
        reserved = decimal_value(reserved_capital_inr)
        if not normalized_ticker or reserved <= 0:
            raise ValueError("pending reservations require a ticker and positive reserved capital")
        return cls(
            normalized_ticker,
            reserved,
            None if source_recommendation_id is None else str(source_recommendation_id),
            None if source_signal_id is None else str(source_signal_id),
        )


@dataclass(frozen=True)
class PortfolioSnapshot:
    capital_ceiling_inr: Decimal
    current_market_value_of_open_positions_inr: Decimal
    cost_basis_of_open_positions_inr: Decimal
    reserved_capital_for_pending_entries_inr: Decimal
    committed_capital_inr: Decimal
    available_capital_for_new_positions_inr: Decimal
    number_of_open_positions: int
    portfolio_status: str
    new_buys_allowed: bool
    capital_overage_inr: Decimal
    committed_capital_overage_inr: Decimal
    positions: tuple[OpenPosition, ...]
    pending_entry_reservations: tuple[PendingEntryReservation, ...]

    @classmethod
    def create(
        cls,
        capital_ceiling_inr: object,
        positions: Iterable[OpenPosition] = (),
        reserved_capital_for_pending_entries_inr: object = 0,
        pending_entry_reservations: Iterable[PendingEntryReservation] = (),
    ) -> "PortfolioSnapshot":
        ceiling = decimal_value(capital_ceiling_inr)
        aggregate_reserved = decimal_value(reserved_capital_for_pending_entries_inr)
        reservations = tuple(pending_entry_reservations)
        if ceiling <= 0 or aggregate_reserved < 0:
            raise ValueError("capital ceiling must be positive and reserved capital cannot be negative")
        if reservations and aggregate_reserved != 0:
            raise ValueError("use structured pending reservations or aggregate reserved capital, not both")
        reserved = sum((item.reserved_capital_inr for item in reservations), Decimal("0")) if reservations else aggregate_reserved
        items = tuple(positions)
        market_value = sum((item.market_value_inr for item in items), Decimal("0"))
        cost_basis = sum((item.cost_basis_inr for item in items), Decimal("0"))
        committed = market_value + reserved
        market_overage = max(Decimal("0"), market_value - ceiling)
        committed_overage = max(Decimal("0"), committed - ceiling)
        if market_overage > 0:
            status = "OVER_NEW_CAP"
        elif committed_overage > 0:
            status = "OVER_COMMITTED_CAP"
        else:
            status = "WITHIN_CAP"
        available = max(Decimal("0"), ceiling - committed)
        return cls(
            ceiling, market_value, cost_basis, reserved, committed, available,
            len(items), status, committed_overage == 0, market_overage,
            committed_overage, items, reservations,
        )
