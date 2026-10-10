"""Sign-safe derived fundamental event transforms for Phase 2A.5."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable


def as_decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"INVALID_DECIMAL_VALUE:{value}") from exc


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def sign_name(value: Decimal) -> str:
    if value > 0:
        return "POSITIVE"
    if value < 0:
        return "NEGATIVE"
    return "ZERO"


def direction_name(delta: Decimal) -> str:
    if delta > 0:
        return "INCREASE"
    if delta < 0:
        return "DECREASE"
    return "UNCHANGED"


def symmetric_change(previous: Decimal, current: Decimal) -> Decimal:
    denominator=abs(previous)+abs(current)
    if denominator==0:
        return Decimal(0)
    return Decimal(2)*(current-previous)/denominator


def _parse_ts(value: str) -> datetime:
    text=str(value or "").strip()
    if not text:
        raise ValueError("AVAILABILITY_TIMESTAMP_REQUIRED")
    return datetime.fromisoformat(text)


def transform_event(eligible: dict, previous_row: dict, current_row: dict) -> dict:
    feature=eligible.get("feature")
    if previous_row.get("symbol")!=current_row.get("symbol"):
        raise ValueError("CROSS_SYMBOL_COMPARISON_FORBIDDEN")
    if previous_row.get("reporting_basis")!=current_row.get("reporting_basis"):
        raise ValueError("CROSS_BASIS_COMPARISON_FORBIDDEN")
    if previous_row.get("event_id")!=eligible.get("previous_event_id"):
        raise ValueError("PREVIOUS_EVENT_ID_MISMATCH")
    if current_row.get("event_id")!=eligible.get("current_event_id"):
        raise ValueError("CURRENT_EVENT_ID_MISMATCH")

    previous_value=as_decimal(previous_row.get(f"{feature}__value"))
    current_value=as_decimal(current_row.get(f"{feature}__value"))
    previous_ts=previous_row.get("availability_ts")
    current_ts=current_row.get("availability_ts")
    if _parse_ts(current_ts) < _parse_ts(previous_ts):
        raise ValueError("PIT_TIMESTAMP_ORDER_VIOLATION")
    if current_ts!=eligible.get("effective_availability_ts"):
        raise ValueError("EFFECTIVE_AVAILABILITY_MISMATCH")

    delta=current_value-previous_value
    schange=symmetric_change(previous_value,current_value)
    previous_sign=sign_name(previous_value)
    current_sign=sign_name(current_value)

    return {
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A5_DERIVED_EVENT_V1",
        "authority":"SHADOW_ONLY",
        "symbol":current_row.get("symbol"),
        "reporting_basis":current_row.get("reporting_basis"),
        "feature":feature,
        "comparison":eligible.get("comparison"),
        "previous_quarter_end":eligible.get("previous_quarter_end"),
        "current_quarter_end":eligible.get("current_quarter_end"),
        "previous_event_id":eligible.get("previous_event_id"),
        "current_event_id":eligible.get("current_event_id"),
        "previous_availability_ts":previous_ts,
        "effective_availability_ts":current_ts,
        "previous_value":decimal_text(previous_value),
        "current_value":decimal_text(current_value),
        "absolute_delta":decimal_text(delta),
        "symmetric_change":decimal_text(schange),
        "direction":direction_name(delta),
        "previous_sign":previous_sign,
        "current_sign":current_sign,
        "sign_transition":f"{previous_sign}_TO_{current_sign}",
        "traditional_percent_change_created":False,
        "semantic_good_bad_label_created":False,
        "production_model_changed":False,
        "model_training_started":False,
    }


def transform_all(eligible_events: Iterable[dict], panel_rows: Iterable[dict]) -> list[dict]:
    by_event={}
    for row in panel_rows:
        event_id=row.get("event_id")
        if not event_id:
            raise ValueError("PANEL_EVENT_ID_MISSING")
        if event_id in by_event:
            raise ValueError(f"DUPLICATE_PANEL_EVENT_ID:{event_id}")
        by_event[event_id]=row

    output=[]
    for eligible in eligible_events:
        previous=by_event.get(eligible.get("previous_event_id"))
        current=by_event.get(eligible.get("current_event_id"))
        if previous is None or current is None:
            raise ValueError("ELIGIBLE_EVENT_PANEL_ROW_MISSING")
        output.append(transform_event(eligible,previous,current))

    output.sort(key=lambda x:(
        x["feature"],x["comparison"],x["symbol"],x["reporting_basis"],x["current_quarter_end"]
    ))
    return output
