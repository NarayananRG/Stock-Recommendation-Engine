from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


def decimal_value(value: object) -> Decimal:
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("portfolio values must be finite")
    return amount


@dataclass(frozen=True)
class OpenPosition:
    ticker: str
    quantity: int
    current_price_inr: Decimal
    cost_basis_per_share_inr: Decimal

    @classmethod
    def create(cls, ticker: str, quantity: int, current_price_inr: object, cost_basis_per_share_inr: object) -> "OpenPosition":
        if not ticker or int(quantity) <= 0:
            raise ValueError("open positions require a ticker and positive whole-share quantity")
        current = decimal_value(current_price_inr)
        basis = decimal_value(cost_basis_per_share_inr)
        if current < 0 or basis < 0:
            raise ValueError("prices cannot be negative")
        return cls(str(ticker), int(quantity), current, basis)

    @property
    def market_value_inr(self) -> Decimal:
        return self.current_price_inr * self.quantity

    @property
    def cost_basis_inr(self) -> Decimal:
        return self.cost_basis_per_share_inr * self.quantity


@dataclass(frozen=True)
class PortfolioSnapshot:
    capital_ceiling_inr: Decimal
    current_market_value_of_open_positions_inr: Decimal
    cost_basis_of_open_positions_inr: Decimal
    reserved_capital_for_pending_entries_inr: Decimal
    available_capital_for_new_positions_inr: Decimal
    number_of_open_positions: int
    portfolio_status: str
    new_buys_allowed: bool
    capital_overage_inr: Decimal
    positions: tuple[OpenPosition, ...]

    @classmethod
    def create(cls, capital_ceiling_inr: object, positions: Iterable[OpenPosition] = (), reserved_capital_for_pending_entries_inr: object = 0) -> "PortfolioSnapshot":
        ceiling = decimal_value(capital_ceiling_inr)
        reserved = decimal_value(reserved_capital_for_pending_entries_inr)
        if ceiling <= 0 or reserved < 0:
            raise ValueError("capital ceiling must be positive and reserved capital cannot be negative")
        items = tuple(positions)
        market_value = sum((item.market_value_inr for item in items), Decimal("0"))
        cost_basis = sum((item.cost_basis_inr for item in items), Decimal("0"))
        overage = max(Decimal("0"), market_value - ceiling)
        status = "OVER_NEW_CAP" if overage > 0 else "WITHIN_CAP"
        available = max(Decimal("0"), ceiling - market_value - reserved)
        return cls(ceiling, market_value, cost_basis, reserved, available, len(items), status, overage == 0, overage, items)
