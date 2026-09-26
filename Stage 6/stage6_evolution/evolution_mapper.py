"""Deterministic directive-to-Event-V2 mapping."""
from __future__ import annotations

from stage6_events import build_event
from stage6_ingestion.canonical import canonical_hash, without

from .policy import EVOLVER_VERSION


EVOLUTION_SCHEMA_VERSION = "STAGE6_EVENT_EVOLUTION_V1"
PRESERVED_FIELDS = ("event_type", "direction", "severity", "materiality", "confidence", "entities",
                    "sectors", "geographies", "commodities", "currencies", "first_known_timestamp",
                    "entity_resolution_version", "event_horizon", "transmission_channels", "causality_assessment")


def corroboration_status(evidence: list[dict]) -> str:
    trustworthy = {item["source_id"] for item in evidence
                   if item["authority_level"] in {"PRIMARY_OFFICIAL", "AUTHORITATIVE_INDEPENDENT"}}
    authorities = {item["authority_level"] for item in evidence}
    if len(trustworthy) >= 2:
        return "CORROBORATED"
    if len(trustworthy) == 1 and authorities == {"PRIMARY_OFFICIAL"}:
        return "SINGLE_SOURCE_OFFICIAL"
    if len(trustworthy) == 1 and authorities == {"AUTHORITATIVE_INDEPENDENT"}:
        return "SINGLE_SOURCE_INDEPENDENT"
    raise ValueError("UNSUPPORTED_EVOLUTION_EVIDENCE_AUTHORITY")


def build_event_v2(*, event_key: str, base_event: dict, directive: dict, evidence: list[dict]) -> dict:
    evidence_ids = sorted({*base_event["source_evidence_ids"], *directive["additional_evidence_ids"]})
    if directive["directive_type"] == "OPEN_CONFLICT":
        status, corroboration = "CONFLICTED", "CONFLICTING_EVIDENCE"
        conflicts = [{"evidence_ids": directive["conflict_evidence_ids"],
                      "description": directive["conflict_description"], "status": "OPEN"}]
    else:
        status, corroboration, conflicts = "CANDIDATE", corroboration_status(evidence), []
    preserved = {field: base_event[field] for field in PRESERVED_FIELDS}
    return build_event(
        event_key=event_key, event_version=2, previous_event_version_hash=base_event["record_hash"],
        event_status=status, source_evidence_ids=evidence_ids, corroboration_status=corroboration,
        last_updated_timestamp=directive["evolution_cutoff"], evidence_conflicts=conflicts, **preserved)


def evolution_identity(directive: dict, base_event: dict, policy_hash: str) -> str:
    return "S6EVO_" + canonical_hash({"directive_id": directive["directive_id"],
        "directive_hash": directive["record_hash"], "base_event_id": base_event["event_id"],
        "base_event_hash": base_event["record_hash"], "policy_hash": policy_hash,
        "evolver_version": EVOLVER_VERSION})[:24]


def build_evolution_record(*, directive: dict, base_event: dict, result_event: dict,
                           materialization: dict, policy_hash: str) -> dict:
    record = {
        "schema_version": EVOLUTION_SCHEMA_VERSION,
        "evolution_id": evolution_identity(directive, base_event, policy_hash),
        "record_hash": "0" * 64,
        "directive_id": directive["directive_id"], "directive_hash": directive["record_hash"],
        "directive_type": directive["directive_type"], "target_event_id": base_event["event_id"],
        "base_event_version": 1, "base_event_hash": base_event["record_hash"],
        "result_event_version": 2, "result_event_hash": result_event["record_hash"],
        "target_materialization_id": materialization["materialization_id"],
        "target_materialization_hash": materialization["record_hash"],
        "policy_id": directive["policy_id"], "policy_hash": policy_hash,
        "evolver_version": directive["evolver_version"], "evolution_cutoff": directive["evolution_cutoff"],
        "result_event_status": result_event["event_status"],
        "result_corroboration_status": result_event["corroboration_status"],
        "added_evidence_ids": directive["additional_evidence_ids"],
    }
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
