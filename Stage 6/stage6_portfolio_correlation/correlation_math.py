from decimal import Decimal, InvalidOperation, localcontext

from .errors import Stage6PortfolioCorrelationError

PRECISION = 50
BOUNDARY_TOLERANCE = Decimal("1E-24")
ZERO = Decimal("0")
ONE = Decimal("1")


def decimal_value(value, field="return_value") -> Decimal:
    if isinstance(value, bool):
        raise Stage6PortfolioCorrelationError(f"{field}: NUMERIC_REQUIRED")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise Stage6PortfolioCorrelationError(f"{field}: NUMERIC_REQUIRED") from exc
    if not result.is_finite():
        raise Stage6PortfolioCorrelationError(f"{field}: NONFINITE")
    return result


def emit(value: Decimal):
    if not value.is_finite():
        raise Stage6PortfolioCorrelationError("CORRELATION_NONFINITE")
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def pearson(xs, ys):
    if len(xs) != len(ys) or not xs:
        raise Stage6PortfolioCorrelationError("CORRELATION_ALIGNED_VALUES_INVALID")
    with localcontext() as context:
        context.prec = PRECISION
        x = [decimal_value(v) for v in xs]
        y = [decimal_value(v) for v in ys]
        n = Decimal(len(x))
        mean_x = sum(x, ZERO) / n
        mean_y = sum(y, ZERO) / n
        dx = [v - mean_x for v in x]
        dy = [v - mean_y for v in y]
        numerator = sum((a * b for a, b in zip(dx, dy)), ZERO)
        sx = sum((a * a for a in dx), ZERO)
        sy = sum((b * b for b in dy), ZERO)
        denominator = (sx * sy).sqrt()
        if denominator == ZERO:
            return None
        result = numerator / denominator
        if result > ONE:
            if result - ONE <= BOUNDARY_TOLERANCE:
                return ONE
            raise Stage6PortfolioCorrelationError("CORRELATION_ABOVE_BOUND")
        if result < -ONE:
            if -ONE - result <= BOUNDARY_TOLERANCE:
                return -ONE
            raise Stage6PortfolioCorrelationError("CORRELATION_BELOW_BOUND")
        return result
