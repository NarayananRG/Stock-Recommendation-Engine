"""Pure deterministic candidate-to-event and audit-record mapping."""
from __future__ import annotations

from stage6_events import build_event
from stage6_ingestion.canonical import canonical_hash, without

from .policy import MATERIALIZER_VERSION


MATERIALIZATION_SCHEMA_VERSION = "STAGE6_EVENT_MATERIALIZATION_V1"


def materialization_identity(candidate: dict, policy_hash: str) -> str:
    return "S6MAT_" + canonical_hash({
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate["record_hash"],
        "materialization_policy_hash": policy_hash,
        "materializer_version": MATERIALIZER_VERSION,
    })[:24]


def materialization_batch_identity(*, classification_batch_id: str,
                                   classification_batch_identity_hash: str,
                                   policy_id: str, policy_hash: str,
                                   materialization_cutoff: str) -> tuple[str, str]:
    identity = canonical_hash({
        "classification_batch_id": classification_batch_id,
        "classification_batch_identity_hash": classification_batch_identity_hash,
        "policy_id": policy_id,
        "policy_hash": policy_hash,
        "materializer_version": MATERIALIZER_VERSION,
        "materialization_cutoff": materialization_cutoff,
    })
    return "S6MATBATCH_" + identity[:24], identity


def decision_status(candidate: dict) -> str:
    return {"MATCHED": "MATERIALIZED", "NO_MATCH": "SKIPPED_NO_MATCH",
            "AMBIGUOUS": "SKIPPED_AMBIGUOUS"}[candidate["classification_status"]]


def build_expected_event(candidate: dict, evidence: dict, materialization_cutoff: str,
                         policy: dict) -> dict:
    defaults = policy["event_defaults"]
    return build_event(
        event_key="stage6_2d_candidate:" + candidate["candidate_id"], event_version=1,
        previous_event_version_hash=None, event_type=candidate["candidate_event_type"],
        source_evidence_ids=[evidence["evidence_id"]],
        first_known_timestamp=evidence["retrieved_timestamp_utc"],
        last_updated_timestamp=materialization_cutoff,
        entity_resolution_version=evidence["entity_registry_snapshot_id"], **defaults)


def build_materialization_record(*, candidate: dict, classification_batch: dict,
                                 policy: dict, policy_hash: str,
                                 materialization_cutoff: str,
                                 event: dict | None) -> dict:
    status = decision_status(candidate)
    record = {
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "materialization_id": materialization_identity(candidate, policy_hash),
        "record_hash": "0" * 64,
        "candidate_id": candidate["candidate_id"],
        "candidate_hash": candidate["record_hash"],
        "candidate_record_type": "EVENT_CANDIDATE",
        "classification_batch_id": classification_batch["classification_batch_id"],
        "classification_batch_identity_hash": classification_batch["batch_identity_hash"],
        "materialization_policy_id": policy["policy_id"],
        "materialization_policy_hash": policy_hash,
        "materializer_version": policy["materializer_version"],
        "decision_status": status,
        "event_id": event["event_id"] if event else None,
        "event_version": event["event_version"] if event else None,
        "event_record_hash": event["record_hash"] if event else None,
        "upstream_evidence_id": candidate["upstream_parent_evidence_id"],
        "upstream_evidence_hash": candidate["upstream_parent_evidence_hash"],
        "classification_cutoff": classification_batch["classification_cutoff"],
        "materialization_cutoff": materialization_cutoff,
    }
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
