"""Runtime invariants for STAGE6_EVENT_MATERIALIZATION_V1."""
from __future__ import annotations

import re

from stage6_ingestion.canonical import canonical_hash, parse_utc, utc_timestamp, without

from .errors import MaterializationIntegrityFailure, Stage6MaterializationError
from .event_mapper import MATERIALIZATION_SCHEMA_VERSION, materialization_identity
from .policy import MATERIALIZER_VERSION, POLICY_ID


HASH = re.compile(r"^[a-f0-9]{64}$")
FIELDS = {"schema_version", "materialization_id", "record_hash", "candidate_id", "candidate_hash",
          "candidate_record_type", "classification_batch_id", "classification_batch_identity_hash",
          "materialization_policy_id", "materialization_policy_hash", "materializer_version",
          "decision_status", "event_id", "event_version", "event_record_hash",
          "upstream_evidence_id", "upstream_evidence_hash", "classification_cutoff",
          "materialization_cutoff"}


def validate_materialization(record: dict, candidate: dict, *, verify_hash: bool = True) -> dict:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise Stage6MaterializationError("MATERIALIZATION_FIELDS_MISMATCH")
    if (record["schema_version"] != MATERIALIZATION_SCHEMA_VERSION
            or record["materializer_version"] != MATERIALIZER_VERSION
            or record["materialization_policy_id"] != POLICY_ID
            or record["candidate_record_type"] != "EVENT_CANDIDATE"):
        raise Stage6MaterializationError("MATERIALIZATION_IDENTITY_FIELDS_INVALID")
    for field in ("materialization_id", "candidate_id", "classification_batch_id", "upstream_evidence_id"):
        if not isinstance(record[field], str) or not record[field]:
            raise Stage6MaterializationError(f"MATERIALIZATION_STRING_INVALID:{field}")
    for field in ("record_hash", "candidate_hash", "classification_batch_identity_hash",
                  "materialization_policy_hash", "upstream_evidence_hash"):
        if not isinstance(record[field], str) or not HASH.fullmatch(record[field]):
            raise Stage6MaterializationError(f"MATERIALIZATION_HASH_INVALID:{field}")
    for field in ("classification_cutoff", "materialization_cutoff"):
        if utc_timestamp(record[field], field) != record[field]:
            raise Stage6MaterializationError(f"MATERIALIZATION_TIMESTAMP_INVALID:{field}")
    if parse_utc(record["classification_cutoff"], "classification_cutoff") > parse_utc(record["materialization_cutoff"], "materialization_cutoff"):
        raise Stage6MaterializationError("MATERIALIZATION_PIT_FAILURE")
    if (record["candidate_id"], record["candidate_hash"], record["upstream_evidence_id"],
            record["upstream_evidence_hash"]) != (candidate["candidate_id"], candidate["record_hash"],
            candidate["upstream_parent_evidence_id"], candidate["upstream_parent_evidence_hash"]):
        raise Stage6MaterializationError("MATERIALIZATION_CANDIDATE_BINDING_MISMATCH")
    status = record["decision_status"]
    event_values = (record["event_id"], record["event_version"], record["event_record_hash"])
    if status == "MATERIALIZED":
        if (candidate["classification_status"] != "MATCHED" or candidate["candidate_event_type"] is None
                or candidate["ambiguous_event_types"] or not isinstance(event_values[0], str)
                or type(event_values[1]) is not int or event_values[1] != 1 or not isinstance(event_values[2], str)
                or not HASH.fullmatch(event_values[2])):
            raise Stage6MaterializationError("MATERIALIZED_INVARIANT_FAILED")
    elif status == "SKIPPED_NO_MATCH":
        if candidate["classification_status"] != "NO_MATCH" or event_values != (None, None, None):
            raise Stage6MaterializationError("SKIPPED_NO_MATCH_INVARIANT_FAILED")
    elif status == "SKIPPED_AMBIGUOUS":
        if candidate["classification_status"] != "AMBIGUOUS" or event_values != (None, None, None):
            raise Stage6MaterializationError("SKIPPED_AMBIGUOUS_INVARIANT_FAILED")
    else:
        raise Stage6MaterializationError("MATERIALIZATION_DECISION_STATUS_INVALID")
    if record["materialization_id"] != materialization_identity(candidate, record["materialization_policy_hash"]):
        raise MaterializationIntegrityFailure("MATERIALIZATION_ID_MISMATCH")
    if verify_hash and record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise MaterializationIntegrityFailure("MATERIALIZATION_RECORD_HASH_MISMATCH")
    return record
