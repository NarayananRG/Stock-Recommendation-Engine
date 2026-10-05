"""Configurable India execution research model; ships without statutory schedules."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from common import money, parse_date, record, sha256


@dataclass(frozen=True)
class CostScheduleBook:
    schedules: tuple[dict, ...]

    @classmethod
    def build(cls, schedules: list[dict]) -> "CostScheduleBook":
        checked = sorted((dict(s) for s in schedules), key=lambda x: x["effective_from"])
        for i, s in enumerate(checked):
            if not s.get("schedule_id") or not s.get("provenance") or s.get("verification_status") not in {"VERIFIED", "TEST_FIXTURE_ONLY"}:
                raise ValueError("schedule identity, provenance, and verification required")
            if i and parse_date(s["effective_from"]) <= parse_date(checked[i - 1].get("effective_to") or "9999-12-31"):
                raise ValueError("overlapping cost schedules")
        return cls(tuple(checked))

    def select(self, session_date: str, production: bool = False) -> dict:
        day = parse_date(session_date)
        matches = [s for s in self.schedules if parse_date(s["effective_from"]) <= day <= parse_date(s.get("effective_to") or "9999-12-31")]
        if len(matches) != 1:
            raise ValueError("COST_SCHEDULE_NOT_CONFIGURED")
        if production and matches[0]["verification_status"] != "VERIFIED":
            raise ValueError("NOT_CONFIGURED_FOR_PRODUCTION_RESEARCH")
        return matches[0]


def _fees(gross: Decimal, side: str, schedule: dict) -> dict[str, Decimal]:
    items: dict[str, Decimal] = {}
    gst_base = Decimal("0")
    for component in schedule.get("components", []):
        if side not in component["sides"]:
            continue
        amount = gross * Decimal(str(component.get("rate_bps", 0))) / Decimal("10000")
        amount = max(amount, Decimal(str(component.get("minimum", 0))))
        if component.get("maximum") is not None:
            amount = min(amount, Decimal(str(component["maximum"])))
        items[component["name"]] = money(amount)
        if component.get("gst_applicable"):
            gst_base += items[component["name"]]
    gst_rate = Decimal(str(schedule.get("gst_rate_percent", 0)))
    if gst_rate:
        items["GST"] = money(gst_base * gst_rate / Decimal("100"))
    return items


def simulate_execution(*, security_id: str, session_date: str, side: str, requested_quantity: int,
                       market_reference_price: str | float, volume: int | None, adv: int | None,
                       tradeable_status: str, schedule_book: CostScheduleBook, slippage_policy: dict,
                       liquidity_policy: dict, stress: bool = False) -> dict:
    if side not in {"BUY", "SELL"} or requested_quantity <= 0:
        raise ValueError("invalid order")
    schedule = schedule_book.select(session_date)
    fill, reason = requested_quantity, "ELIGIBLE"
    if tradeable_status == "UNTRADEABLE":
        fill, reason = 0, "UNTRADEABLE"
    elif tradeable_status != "TRADEABLE":
        fill, reason = 0, "SUSPENDED_OR_UNKNOWN"
    elif not volume or volume <= 0:
        fill, reason = 0, "REJECTED_LIQUIDITY"
    else:
        max_fill = int(Decimal(volume) * Decimal(str(liquidity_policy["max_participation_rate"])))
        if adv is not None and adv < int(liquidity_policy.get("minimum_adv", 0)):
            max_fill = 0
        if requested_quantity > max_fill:
            if liquidity_policy.get("insufficient_volume_action") == "PARTIAL" and max_fill > 0:
                fill, reason = max_fill, "PARTIAL"
            else:
                fill, reason = 0, "REJECTED_LIQUIDITY"
    status = reason if reason in {"PARTIAL", "UNTRADEABLE", "SUSPENDED_OR_UNKNOWN", "REJECTED_LIQUIDITY"} else "FILLED"
    bps = Decimal(str(slippage_policy["fixed_bps"]))
    if stress:
        bps *= Decimal(str(slippage_policy.get("stress_multiplier", 1)))
    direction = Decimal("1") if side == "BUY" else Decimal("-1")
    reference = Decimal(str(market_reference_price))
    price = money(reference * (Decimal("1") + direction * bps / Decimal("10000")))
    gross = money(price * fill)
    fees = _fees(gross, side, schedule) if fill else {}
    total = money(sum(fees.values(), Decimal("0")))
    net = money(-(gross + total) if side == "BUY" else gross - total)
    participation = None if not volume else str((Decimal(fill) / Decimal(volume)).quantize(Decimal("0.000001")))
    payload = {
        "security_id": security_id, "market_session": session_date, "side": side,
        "requested_quantity": requested_quantity, "filled_quantity": fill,
        "market_reference_price": str(money(reference)), "assumed_execution_price": str(price),
        "gross_value": str(gross), "cost_components": {k: str(v) for k, v in sorted(fees.items())},
        "total_transaction_cost": str(total), "net_cash_impact": str(net),
        "fill_status": status, "participation_rate": participation, "reason": reason,
        "cost_schedule_id": schedule["schedule_id"], "cost_schedule_hash": sha256(schedule),
        "slippage_policy_id": slippage_policy["policy_id"], "slippage_policy_hash": sha256(slippage_policy),
        "liquidity_policy_id": liquidity_policy["policy_id"], "liquidity_policy_hash": sha256(liquidity_policy),
    }
    return record("EXECUTION_RESULT_V1", payload)


def resolve_stop_target(open_price: float, stop: float, target: float, day_low: float, day_high: float, policy: str = "STOP_FIRST") -> str:
    if open_price <= stop:
        return "GAP_STOP_AT_OPEN"
    if open_price >= target:
        return "GAP_TARGET_AT_OPEN"
    stop_hit, target_hit = day_low <= stop, day_high >= target
    if stop_hit and target_hit:
        return "STOP_HIT" if policy == "STOP_FIRST" else "TARGET_HIT"
    return "STOP_HIT" if stop_hit else "TARGET_HIT" if target_hit else "NO_EXIT"

