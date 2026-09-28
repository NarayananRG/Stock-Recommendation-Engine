from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, localcontext

from .errors import Stage6PortfolioArithmeticError

ZERO = Decimal("0")
ONE = Decimal("1")
TOLERANCE = Decimal("1E-12")


def decimal_value(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise Stage6PortfolioArithmeticError(f"PORTFOLIO_ARITHMETIC_NUMBER_INVALID:{field}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Stage6PortfolioArithmeticError(f"PORTFOLIO_ARITHMETIC_NUMBER_INVALID:{field}") from exc
    if not result.is_finite():
        raise Stage6PortfolioArithmeticError(f"PORTFOLIO_ARITHMETIC_NONFINITE:{field}")
    return result


def add(values) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return sum(values, ZERO)


def multiply(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return left * right


def divide(left: Decimal, right: Decimal) -> Decimal:
    if right == ZERO:
        raise Stage6PortfolioArithmeticError("PORTFOLIO_ARITHMETIC_DIVISION_BY_ZERO")
    with localcontext() as context:
        context.prec = 50
        return left / right


def emit(value: Decimal) -> int | float:
    if not value.is_finite():
        raise Stage6PortfolioArithmeticError("PORTFOLIO_ARITHMETIC_NONFINITE_RESULT")
    if value == value.to_integral_value():
        return int(value)
    result = float(format(value.normalize(), "f"))
    if not math.isfinite(result):
        raise Stage6PortfolioArithmeticError("PORTFOLIO_ARITHMETIC_NONFINITE_RESULT")
    return result


def money(value: Decimal, currency: str) -> dict:
    return {"value": emit(value), "unit": currency}


def fraction(value: Decimal) -> dict:
    return {"value": emit(value), "unit": "FRACTION_OF_INVESTED_CAPITAL",
            "denominator_definition": "INVESTED_CAPITAL"}
