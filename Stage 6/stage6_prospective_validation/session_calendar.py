"""Pinned, network-free NSE ordinary-session verification for Stage 6.8 V1."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .errors import Stage6ProspectiveError


CALENDAR_SCHEMA = "NSE_EQUITY_CALENDAR_V1"
CALENDAR_TIMEZONE = "Asia/Kolkata"
IST = timezone(timedelta(hours=5, minutes=30), CALENDAR_TIMEZONE)
EXPECTED_CALENDAR_PAYLOAD_HASH = "c93f0340ca55ace9650b4c68e85836d01303f35f8abd7dc22cad5ef34800a656"
SUBMISSION_DEADLINE = "BEFORE_09_15_IST_ON_TARGET_SESSION"
DEFAULT_CALENDAR_PATH = (
    Path(__file__).resolve().parents[2]
    / "Stage 5D"
    / "live_paper"
    / "data"
    / "nse_equity_calendar_2026.json"
)


def _canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_verified_calendar(calendar_path=DEFAULT_CALENDAR_PATH):
    try:
        document = json.loads(Path(calendar_path).read_text(encoding="utf-8"))
        stored_hash = document["calendar_payload_hash"]
        payload = {key: value for key, value in document.items() if key != "calendar_payload_hash"}
        source = payload["source"]
        if payload["schema_version"] != CALENDAR_SCHEMA:
            raise ValueError("schema")
        if (
            payload["exchange"] != "NSE"
            or payload["segment"] != "CAPITAL MARKET SEGMENT"
            or payload["calendar_year"] != 2026
            or payload["timezone"] != CALENDAR_TIMEZONE
        ):
            raise ValueError("identity")
        if (
            source["authority"] != "National Stock Exchange of India Limited"
            or source["department"] != "CAPITAL MARKET SEGMENT"
            or source["download_ref"] != "NSE/CMTR/71775"
            or source["circular_ref"] != "172/2025"
            or source["circular_date"] != "2025-12-12"
        ):
            raise ValueError("source")
        if source["source_payload_hash"] != _canonical_hash(
            {key: value for key, value in source.items() if key != "source_payload_hash"}
        ):
            raise ValueError("source hash")
        computed_hash = _canonical_hash(payload)
        if stored_hash != computed_hash or computed_hash != EXPECTED_CALENDAR_PAYLOAD_HASH:
            raise ValueError("calendar hash")
        if payload["regular_weekend_days"] != ["SATURDAY", "SUNDAY"]:
            raise ValueError("weekends")
        if len(payload["closed_dates"]) != len(set(payload["closed_dates"])):
            raise ValueError("duplicate closed dates")
        if len(payload["weekend_holiday_dates"]) != len(set(payload["weekend_holiday_dates"])):
            raise ValueError("duplicate weekend dates")
        for value in [
            *payload["closed_dates"],
            *payload["weekend_holiday_dates"],
            *payload["special_sessions"].keys(),
        ]:
            parsed = date.fromisoformat(value)
            if parsed.year != payload["calendar_year"]:
                raise ValueError("date outside calendar year")
        return document
    except Exception as exc:
        raise Stage6ProspectiveError("NSE_CALENDAR_INTEGRITY_FAILURE") from exc


def verify_ordinary_session(session_date, calendar_path=DEFAULT_CALENDAR_PATH):
    try:
        parsed = date.fromisoformat(session_date)
    except (TypeError, ValueError) as exc:
        raise Stage6ProspectiveError("TARGET_SESSION_DATE_INVALID") from exc
    if parsed.isoformat() != session_date:
        raise Stage6ProspectiveError("TARGET_SESSION_DATE_INVALID")
    if parsed.year != 2026:
        raise Stage6ProspectiveError("NSE_CALENDAR_YEAR_UNSUPPORTED")
    calendar = load_verified_calendar(calendar_path)
    if session_date in calendar["special_sessions"]:
        raise Stage6ProspectiveError("UNSUPPORTED_FOR_STAGE6_8_V1")
    if parsed.weekday() >= 5:
        raise Stage6ProspectiveError("TARGET_SESSION_WEEKEND")
    if session_date in calendar["closed_dates"]:
        raise Stage6ProspectiveError("TARGET_SESSION_OFFICIAL_CLOSED_DATE")
    return {
        "session_date": session_date,
        "evidence_type": "NSE_OFFICIAL_SCHEDULED_SESSION",
        "calendar_schema": CALENDAR_SCHEMA,
        "calendar_year": calendar["calendar_year"],
        "exchange": calendar["exchange"],
        "segment": calendar["segment"],
        "timezone": CALENDAR_TIMEZONE,
        "source_download_ref": calendar["source"]["download_ref"],
        "source_circular_ref": calendar["source"]["circular_ref"],
        "calendar_payload_hash": calendar["calendar_payload_hash"],
        "special_session_status": "ORDINARY_SESSION_CONFIRMED",
    }


def pre_session_deadline_utc(session_date, calendar_path=DEFAULT_CALENDAR_PATH):
    proof = verify_ordinary_session(session_date, calendar_path)
    local = datetime.combine(date.fromisoformat(session_date), time(9, 15), IST)
    return local.astimezone(timezone.utc), proof
