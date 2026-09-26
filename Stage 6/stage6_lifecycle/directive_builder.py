"""Deterministic explicit lifecycle directive construction."""
from __future__ import annotations

from stage6_ingestion.canonical import canonical_hash, utc_timestamp, without


DIRECTIVE_SCHEMA_VERSION = "STAGE6_EVENT_LIFECYCLE_DIRECTIVE_V1"


def directive_identity(record: dict) -> str:
    return "S6LIFEDIR_" + canonical_hash({
        "schema_version": DIRECTIVE_SCHEMA_VERSION,
        "directive_type": record["directive_type"],
        "target_event_id": record["target_event_id"],
        "base_event_hash": record["base_event_hash"],
        "target_evolution_id": record["target_evolution_id"],
        "target_evolution_hash": record["target_evolution_hash"],
        "target_materialization_id": record["target_materialization_id"],
        "target_materialization_hash": record["target_materialization_hash"],
        "lifecycle_evidence_ids": sorted(record["lifecycle_evidence_ids"]),
        "affected_evidence_ids": sorted(record["affected_evidence_ids"]),
        "lifecycle_cutoff": record["lifecycle_cutoff"],
        "policy_hash": record["policy_hash"],
        "processor_version": record["processor_version"],
    })[:24]


def build_directive(*, directive_type: str, base_event: dict, evolution: dict,
                    materialization: dict, lifecycle_evidence_ids: list[str],
                    affected_evidence_ids: list[str], lifecycle_cutoff: str,
                    policy: dict, policy_hash: str) -> dict:
    record = {
        "schema_version": DIRECTIVE_SCHEMA_VERSION, "directive_id": "", "record_hash": "0" * 64,
        "directive_type": directive_type, "target_event_id": base_event["event_id"],
        "base_event_version": base_event["event_version"], "base_event_hash": base_event["record_hash"],
        "target_evolution_id": evolution["evolution_id"], "target_evolution_hash": evolution["record_hash"],
        "target_materialization_id": materialization["materialization_id"],
        "target_materialization_hash": materialization["record_hash"],
        "lifecycle_evidence_ids": sorted(lifecycle_evidence_ids),
        "affected_evidence_ids": sorted(affected_evidence_ids),
        "lifecycle_cutoff": utc_timestamp(lifecycle_cutoff, "lifecycle_cutoff"),
        "policy_id": policy["policy_id"], "policy_hash": policy_hash,
        "processor_version": policy["processor_version"],
    }
    record["directive_id"] = directive_identity(record)
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
