"""Fail-closed Stage 6.2F directive validation."""
from __future__ import annotations

import re

from stage6_ingestion.canonical import canonical_hash, parse_utc, utc_timestamp, without

from .directive_builder import DIRECTIVE_SCHEMA_VERSION, directive_identity
from .errors import LifecycleIntegrityFailure, Stage6LifecycleError
from .policy import POLICY_ID, PROCESSOR_VERSION, SUPPORTED_DIRECTIVES


HASH = re.compile(r"^[a-f0-9]{64}$")
FIELDS = {"schema_version", "directive_id", "record_hash", "directive_type", "target_event_id",
          "base_event_version", "base_event_hash", "target_evolution_id", "target_evolution_hash",
          "target_materialization_id", "target_materialization_hash", "lifecycle_evidence_ids",
          "affected_evidence_ids", "lifecycle_cutoff", "policy_id", "policy_hash", "processor_version"}


def _ids(value: object, field: str) -> list[str]:
    if (not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value)) or value != sorted(value)):
        raise Stage6LifecycleError(f"LIFECYCLE_DIRECTIVE_IDS_INVALID:{field}")
    return value


def validate_directive(record: dict, base_event: dict, evolution: dict, materialization: dict, *,
                       expected_policy_hash: str, verify_hash: bool = True) -> dict:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise Stage6LifecycleError("LIFECYCLE_DIRECTIVE_FIELDS_MISMATCH")
    if (record["schema_version"] != DIRECTIVE_SCHEMA_VERSION or record["policy_id"] != POLICY_ID
            or record["processor_version"] != PROCESSOR_VERSION
            or record["directive_type"] not in SUPPORTED_DIRECTIVES):
        raise Stage6LifecycleError("LIFECYCLE_DIRECTIVE_IDENTITY_INVALID")
    if (record["target_event_id"], record["base_event_version"], record["base_event_hash"],
            record["target_evolution_id"], record["target_evolution_hash"],
            record["target_materialization_id"], record["target_materialization_hash"]) != (
            base_event["event_id"], 2, base_event["record_hash"], evolution["evolution_id"],
            evolution["record_hash"], materialization["materialization_id"], materialization["record_hash"]):
        raise Stage6LifecycleError("LIFECYCLE_DIRECTIVE_ANCHOR_MISMATCH")
    for field in ("record_hash", "base_event_hash", "target_evolution_hash", "target_materialization_hash", "policy_hash"):
        if not isinstance(record[field], str) or not HASH.fullmatch(record[field]):
            raise Stage6LifecycleError(f"LIFECYCLE_DIRECTIVE_HASH_INVALID:{field}")
    if not isinstance(expected_policy_hash, str) or not HASH.fullmatch(expected_policy_hash):
        raise Stage6LifecycleError("EXPECTED_LIFECYCLE_POLICY_HASH_INVALID")
    if record["policy_hash"] != expected_policy_hash:
        raise Stage6LifecycleError("LIFECYCLE_DIRECTIVE_POLICY_HASH_MISMATCH")
    lifecycle, affected = _ids(record["lifecycle_evidence_ids"], "lifecycle"), _ids(record["affected_evidence_ids"], "affected")
    if len(lifecycle) != len(affected):
        raise Stage6LifecycleError("LIFECYCLE_DIRECTIVE_ONE_TO_ONE_REQUIRED")
    cutoff = utc_timestamp(record["lifecycle_cutoff"], "lifecycle_cutoff")
    if cutoff != record["lifecycle_cutoff"] or parse_utc(cutoff, "lifecycle_cutoff") < parse_utc(base_event["last_updated_timestamp"], "base.last_updated"):
        raise Stage6LifecycleError("LIFECYCLE_CUTOFF_INVALID")
    if record["directive_id"] != directive_identity(record):
        raise LifecycleIntegrityFailure("LIFECYCLE_DIRECTIVE_ID_MISMATCH")
    if verify_hash and record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise LifecycleIntegrityFailure("LIFECYCLE_DIRECTIVE_RECORD_HASH_MISMATCH")
    return record
