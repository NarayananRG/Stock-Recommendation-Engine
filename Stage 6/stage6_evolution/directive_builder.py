"""Build explicit immutable Stage 6.2E evolution directives."""
from __future__ import annotations

from stage6_ingestion.canonical import canonical_hash, utc_timestamp, without

from .policy import EVOLVER_VERSION


DIRECTIVE_SCHEMA_VERSION = "STAGE6_EVENT_EVOLUTION_DIRECTIVE_V1"


def directive_identity(payload: dict) -> str:
    return "S6EVODIR_" + canonical_hash({
        "schema_version": DIRECTIVE_SCHEMA_VERSION,
        "directive_type": payload["directive_type"],
        "target_event_id": payload["target_event_id"],
        "base_event_hash": payload["base_event_hash"],
        "additional_evidence_ids": sorted(payload["additional_evidence_ids"]),
        "conflict_evidence_ids": sorted(payload["conflict_evidence_ids"]),
        "conflict_description": payload["conflict_description"],
        "evolution_cutoff": payload["evolution_cutoff"],
        "policy_hash": payload["policy_hash"],
        "evolver_version": EVOLVER_VERSION,
    })[:24]


def build_directive(*, directive_type: str, target_event_id: str, base_event: dict,
                    materialization: dict, additional_evidence_ids: list[str],
                    conflict_evidence_ids: list[str], conflict_description: str | None,
                    evolution_cutoff: str, policy: dict, policy_hash: str) -> dict:
    record = {
        "schema_version": DIRECTIVE_SCHEMA_VERSION,
        "directive_id": "",
        "record_hash": "0" * 64,
        "directive_type": directive_type,
        "target_event_id": target_event_id,
        "base_event_version": base_event["event_version"],
        "base_event_hash": base_event["record_hash"],
        "target_materialization_id": materialization["materialization_id"],
        "target_materialization_hash": materialization["record_hash"],
        "additional_evidence_ids": sorted(additional_evidence_ids),
        "conflict_evidence_ids": sorted(conflict_evidence_ids),
        "conflict_description": conflict_description,
        "evolution_cutoff": utc_timestamp(evolution_cutoff, "evolution_cutoff"),
        "policy_id": policy["policy_id"],
        "policy_hash": policy_hash,
        "evolver_version": policy["evolver_version"],
    }
    record["directive_id"] = directive_identity(record)
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
