"""The single canonical JSON, hash, and UTC timestamp implementation."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .errors import Stage6IngestionError


def canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise Stage6IngestionError("NON_CANONICAL_VALUE") from exc


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: object) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def without(value: dict, *keys: str) -> dict:
    return {key: item for key, item in value.items() if key not in keys}


def utc_timestamp(value: str | datetime, field: str) -> str:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise Stage6IngestionError(f"INVALID_TIMESTAMP:{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Stage6IngestionError(f"NAIVE_TIMESTAMP:{field}")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_utc(value: str, field: str) -> datetime:
    normalized = utc_timestamp(value, field)
    return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
