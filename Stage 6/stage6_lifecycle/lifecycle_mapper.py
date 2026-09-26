"""Deterministic evidence-transition and Event V3 mapping."""
from __future__ import annotations

from stage6_events import build_event
from stage6_ingestion.canonical import canonical_hash, without

from .policy import PROCESSOR_VERSION


LIFECYCLE_SCHEMA_VERSION = "STAGE6_EVENT_LIFECYCLE_V1"
PRESERVED_FIELDS = ("event_type", "direction", "severity", "materiality", "confidence", "entities",
                    "sectors", "geographies", "commodities", "currencies", "first_known_timestamp",
                    "entity_resolution_version", "event_horizon", "transmission_channels", "causality_assessment")


def corroboration_status(evidence: list[dict]) -> str:
    sources = {item["source_id"] for item in evidence}
    authorities = {item["authority_level"] for item in evidence}
    if len(sources) >= 2:
        return "CORROBORATED"
    if len(sources) == 1 and authorities == {"PRIMARY_OFFICIAL"}:
        return "SINGLE_SOURCE_OFFICIAL"
    if len(sources) == 1 and authorities == {"AUTHORITATIVE_INDEPENDENT"}:
        return "SINGLE_SOURCE_INDEPENDENT"
    raise ValueError("UNSUPPORTED_LIFECYCLE_EVIDENCE_AUTHORITY")


def active_evidence_ids(base_event: dict, directive_type: str, transitions: list[dict]) -> list[str]:
    active = set(base_event["source_evidence_ids"])
    if directive_type == "RETRACT_EVENT":
        return sorted(item["lifecycle_evidence_id"] for item in transitions)
    for item in transitions:
        active.remove(item["affected_evidence_id"])
        if item["relation"] == "CORRECTION":
            active.add(item["lifecycle_evidence_id"])
    if not active:
        raise ValueError("LIFECYCLE_ACTIVE_EVIDENCE_EMPTY")
    return sorted(active)


def build_event_v3(*, event_key: str, base_event: dict, directive: dict,
                   transitions: list[dict], active_evidence: list[dict]) -> dict:
    active_ids = active_evidence_ids(base_event, directive["directive_type"], transitions)
    if sorted(item["evidence_id"] for item in active_evidence) != active_ids:
        raise ValueError("LIFECYCLE_ACTIVE_EVIDENCE_RECORDS_MISMATCH")
    status = "RETRACTED" if directive["directive_type"] == "RETRACT_EVENT" else "CANDIDATE"
    preserved = {field: base_event[field] for field in PRESERVED_FIELDS}
    return build_event(event_key=event_key, event_version=3,
        previous_event_version_hash=base_event["record_hash"], event_status=status,
        source_evidence_ids=active_ids, corroboration_status=corroboration_status(active_evidence),
        last_updated_timestamp=directive["lifecycle_cutoff"], evidence_conflicts=[], **preserved)


def lifecycle_identity(directive: dict, base_event: dict, evolution: dict, policy_hash: str) -> str:
    return "S6LIFE_" + canonical_hash({"directive_id": directive["directive_id"],
        "directive_hash": directive["record_hash"], "base_event_id": base_event["event_id"],
        "base_event_hash": base_event["record_hash"], "target_evolution_id": evolution["evolution_id"],
        "target_evolution_hash": evolution["record_hash"], "policy_hash": policy_hash,
        "processor_version": PROCESSOR_VERSION})[:24]


def build_lifecycle_record(*, directive: dict, base_event: dict, result_event: dict,
                           evolution: dict, materialization: dict, transitions: list[dict],
                           resolved_conflict: dict | None, policy_hash: str) -> dict:
    record = {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
        "lifecycle_id": lifecycle_identity(directive, base_event, evolution, policy_hash),
        "record_hash": "0" * 64, "directive_id": directive["directive_id"],
        "directive_hash": directive["record_hash"], "directive_type": directive["directive_type"],
        "target_event_id": base_event["event_id"], "base_event_version": 2,
        "base_event_hash": base_event["record_hash"], "result_event_version": 3,
        "result_event_hash": result_event["record_hash"], "target_evolution_id": evolution["evolution_id"],
        "target_evolution_hash": evolution["record_hash"],
        "target_materialization_id": materialization["materialization_id"],
        "target_materialization_hash": materialization["record_hash"],
        "policy_id": directive["policy_id"], "policy_hash": policy_hash,
        "processor_version": directive["processor_version"], "lifecycle_cutoff": directive["lifecycle_cutoff"],
        "result_event_status": result_event["event_status"],
        "result_corroboration_status": result_event["corroboration_status"],
        "evidence_transitions": [dict(item) for item in transitions],
        "resolved_conflict": dict(resolved_conflict) if resolved_conflict is not None else None,
    }
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
