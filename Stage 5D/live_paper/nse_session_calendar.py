"""Pinned, network-free NSE Capital Market ordinary-session calendar."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path


DEFAULT_CALENDAR_PATH = Path(__file__).resolve().parent / "data/nse_equity_calendar_2026.json"
# This code-pinned value prevents an altered artifact from being accepted merely
# by recomputing the hash stored inside that same artifact.
EXPECTED_2026_CALENDAR_PAYLOAD_HASH = "c93f0340ca55ace9650b4c68e85836d01303f35f8abd7dc22cad5ef34800a656"


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_verified_calendar(calendar_path: Path = DEFAULT_CALENDAR_PATH) -> dict:
    """Load the checked-in calendar and verify schema, source identity and hash."""
    try:
        document = json.loads(Path(calendar_path).read_text(encoding="utf-8"))
        stored_hash = document["calendar_payload_hash"]
        payload = {key: value for key, value in document.items() if key != "calendar_payload_hash"}
        source = payload["source"]
        if payload["schema_version"] != "NSE_EQUITY_CALENDAR_V1":
            raise ValueError("schema")
        if (payload["exchange"] != "NSE" or payload["segment"] != "CAPITAL MARKET SEGMENT"
                or payload["calendar_year"] != 2026 or payload["timezone"] != "Asia/Kolkata"):
            raise ValueError("identity")
        if (source["authority"] != "National Stock Exchange of India Limited"
                or source["department"] != "CAPITAL MARKET SEGMENT"
                or source["download_ref"] != "NSE/CMTR/71775"
                or source["circular_ref"] != "172/2025"
                or source["circular_date"] != "2025-12-12"):
            raise ValueError("source")
        if source["source_payload_hash"] != _canonical_hash({
                key: value for key, value in source.items() if key != "source_payload_hash"}):
            raise ValueError("source hash")
        computed_hash = _canonical_hash(payload)
        if stored_hash != computed_hash or computed_hash != EXPECTED_2026_CALENDAR_PAYLOAD_HASH:
            raise ValueError("calendar hash")
        if payload["regular_weekend_days"] != ["SATURDAY", "SUNDAY"]:
            raise ValueError("weekends")
        closed = payload["closed_dates"]
        weekend = payload["weekend_holiday_dates"]
        special = payload["special_sessions"]
        if len(closed) != len(set(closed)) or len(weekend) != len(set(weekend)):
            raise ValueError("duplicate dates")
        for value in [*closed, *weekend, *special.keys()]:
            parsed = date.fromisoformat(value)
            if parsed.year != payload["calendar_year"]:
                raise ValueError("date outside calendar year")
        return document
    except Exception as exc:
        raise RuntimeError("PAPER_ACTION_MARKET_CALENDAR_INTEGRITY_FAILURE") from exc


def verify_scheduled_session(session_date: str, calendar_path: Path = DEFAULT_CALENDAR_PATH) -> dict:
    """Return auditable scheduled-session evidence or fail closed."""
    try:
        parsed = date.fromisoformat(session_date)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION") from exc
    if parsed.isoformat() != session_date:
        raise RuntimeError("PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION")
    if parsed.year != 2026:
        raise RuntimeError("PAPER_ACTION_MARKET_CALENDAR_UNAVAILABLE")
    calendar = load_verified_calendar(calendar_path)
    if session_date in calendar["special_sessions"]:
        raise RuntimeError("PAPER_ACTION_SPECIAL_SESSION_UNSUPPORTED")
    if parsed.weekday() >= 5 or session_date in calendar["closed_dates"]:
        raise RuntimeError("PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION")
    return {
        "session_date": session_date,
        "evidence_type": "NSE_OFFICIAL_SCHEDULED_SESSION",
        "calendar_year": calendar["calendar_year"],
        "exchange": calendar["exchange"],
        "segment": calendar["segment"],
        "source_download_ref": calendar["source"]["download_ref"],
        "source_circular_ref": calendar["source"]["circular_ref"],
        "calendar_payload_hash": calendar["calendar_payload_hash"],
    }
