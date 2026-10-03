"""Shared deterministic primitives for the isolated next-generation research lane."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

AUTHORITY = {
    "authority": "RESEARCH_ONLY",
    "active_prospective_authority": "NONE",
    "trading_authority": False,
    "model_promotion_authority": "NONE",
    "active_source_registry_authority": "NONE",
    "active_recommendation_influence": "NONE",
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(kind: str, payload: dict) -> dict:
    body = {"schema": kind, **AUTHORITY, **payload}
    digest = sha256(body)
    return {**body, "record_id": f"{kind}_{digest[:24]}", "record_hash": digest}


def parse_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    return value if isinstance(value, date) else date.fromisoformat(value)


def parse_time(value: str | datetime) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt.astimezone(timezone.utc)


def money(value: Decimal | str | int | float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))

