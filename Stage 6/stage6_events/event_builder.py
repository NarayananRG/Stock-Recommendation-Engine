"""Deterministic structured event construction; no text inference."""
from __future__ import annotations

from stage6_ingestion.canonical import canonical_hash, utc_timestamp, without

from .errors import Stage6EventError
from .event_validation import validate_event


def deterministic_event_id(event_key: str) -> str:
    if not isinstance(event_key, str) or not event_key.strip():
        raise Stage6EventError("EVENT_KEY_REQUIRED")
    return "S6EVENT_" + canonical_hash({"event_key": event_key})[:24]


def build_event(*, event_key: str, event_version: int, previous_event_version_hash: str | None,
                event_type: str, event_status: str, direction: str, severity: str,
                materiality: str, confidence: float, entities: list[str], sectors: list[str],
                geographies: list[str], commodities: list[str], currencies: list[str],
                source_evidence_ids: list[str], corroboration_status: str,
                first_known_timestamp: str, last_updated_timestamp: str,
                entity_resolution_version: str, event_horizon: str,
                transmission_channels: list[str], causality_assessment: str,
                evidence_conflicts: list[dict]) -> dict:
    event = {
        "schema_version": "STAGE6_EVENT_V1",
        "event_id": deterministic_event_id(event_key),
        "event_version": event_version,
        "previous_event_version_hash": previous_event_version_hash,
        "record_hash": "0" * 64,
        "event_type": event_type,
        "event_status": event_status,
        "direction": direction,
        "severity": severity,
        "materiality": materiality,
        "confidence": confidence,
        "entities": list(entities),
        "sectors": list(sectors),
        "geographies": list(geographies),
        "commodities": list(commodities),
        "currencies": list(currencies),
        "source_evidence_ids": list(source_evidence_ids),
        "corroboration_status": corroboration_status,
        "first_known_timestamp": utc_timestamp(first_known_timestamp, "first_known_timestamp"),
        "last_updated_timestamp": utc_timestamp(last_updated_timestamp, "last_updated_timestamp"),
        "entity_resolution_version": entity_resolution_version,
        "event_horizon": event_horizon,
        "transmission_channels": list(transmission_channels),
        "causality_assessment": causality_assessment,
        "evidence_conflicts": [dict(item) for item in evidence_conflicts],
    }
    event["record_hash"] = canonical_hash(without(event, "record_hash"))
    return validate_event(event)
