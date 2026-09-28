import math

from .errors import Stage6AnalogueSelectionError

HORIZONS = ("1D", "3D", "5D", "20D")


def _mean(values):
    return sum(values) / len(values)


def categorical_distance(a, b):
    if a is None or b is None:
        return 1.0, ["MISSING_VALUE_PENALTY"]
    return (0.0, []) if a == b else (1.0, ["CATEGORICAL_MISMATCH"])


def numeric_distance(a, b, unit_a, unit_b):
    if a is None or b is None:
        return 1.0, ["MISSING_VALUE_PENALTY"]
    if unit_a != unit_b:
        return 1.0, ["INCOMPATIBLE_UNIT"]
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise Stage6AnalogueSelectionError("ANALOGUE_NUMERIC_VALUE_INVALID")
    if not math.isfinite(a) or not math.isfinite(b):
        raise Stage6AnalogueSelectionError("ANALOGUE_NUMERIC_VALUE_NONFINITE")
    denominator = abs(a) + abs(b)
    return (0.0 if denominator == 0 else abs(a - b) / denominator), []


def measure_distance(a, b):
    return numeric_distance(a.get("value"), b.get("value"), a.get("unit"), b.get("unit"))


def return_distance(a, b):
    distances, reasons = [], []
    for horizon in HORIZONS:
        distance, atomic = numeric_distance(a.get(horizon), b.get(horizon), a.get("unit"), b.get("unit"))
        distances.append(distance)
        reasons.extend(f"{horizon}:{reason}" for reason in atomic)
    return _mean(distances), reasons


def named_array_distance(a, b):
    left = {item["name"].casefold(): item for item in a}
    right = {item["name"].casefold(): item for item in b}
    names = sorted(set(left) | set(right))
    if not names:
        return 1.0, ["EMPTY_CONTEXT_PENALTY"]
    distances, reasons = [], []
    for name in names:
        if name not in left or name not in right:
            distances.append(1.0)
            reasons.append(f"{name}:MISSING_NAME_PENALTY")
        else:
            distance, atomic = measure_distance(left[name], right[name])
            distances.append(distance)
            reasons.extend(f"{name}:{reason}" for reason in atomic)
    return _mean(distances), reasons


def compare_snapshots(target, candidate, weights):
    distances, reasons = {}, {}
    for name in ("event_type", "severity", "materiality"):
        distances[name], reasons[name] = categorical_distance(target.get(name), candidate.get(name))
    stock_returns, stock_reasons = return_distance(target["stock_return_state"]["returns"], candidate["stock_return_state"]["returns"])
    gap, gap_reasons = measure_distance(target["stock_return_state"]["gap"], candidate["stock_return_state"]["gap"])
    distances["stock_return_state"] = _mean([stock_returns, gap])
    reasons["stock_return_state"] = stock_reasons + gap_reasons
    for name in ("volume", "volatility"):
        distances[name], reasons[name] = measure_distance(target[name], candidate[name])
    distances["technical_structure"], reasons["technical_structure"] = categorical_distance(target["technical_structure"].get("value"), candidate["technical_structure"].get("value"))
    sector, sector_reasons = return_distance(target["sector_behaviour"]["sector_returns"], candidate["sector_behaviour"]["sector_returns"])
    nifty, nifty_reasons = return_distance(target["sector_behaviour"]["nifty_returns"], candidate["sector_behaviour"]["nifty_returns"])
    relative, relative_reasons = measure_distance(target["sector_behaviour"]["relative_strength"], candidate["sector_behaviour"]["relative_strength"])
    distances["sector_behaviour"] = _mean([sector, nifty, relative])
    reasons["sector_behaviour"] = sector_reasons + nifty_reasons + relative_reasons
    distances["market_regime"], reasons["market_regime"] = categorical_distance(target["market_regime"].get("value"), candidate["market_regime"].get("value"))
    for name in ("commodity_context", "currency_context", "rate_context"):
        distances[name], reasons[name] = named_array_distance(target[name], candidate[name])
    if set(distances) != set(weights):
        raise Stage6AnalogueSelectionError("ANALOGUE_DISTANCE_FIELDS_INVALID")
    total = sum(weights[name] * distances[name] for name in weights) / sum(weights.values())
    if not 0.0 <= total <= 1.0:
        raise Stage6AnalogueSelectionError("ANALOGUE_DISTANCE_OUT_OF_RANGE")
    return distances, reasons, total, 1.0 - total
