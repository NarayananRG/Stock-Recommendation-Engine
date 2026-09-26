"""Runtime validation for immutable lifecycle result records."""
from __future__ import annotations

import re

from stage6_ingestion.canonical import canonical_hash, without

from .errors import LifecycleIntegrityFailure, Stage6LifecycleError
from .lifecycle_mapper import LIFECYCLE_SCHEMA_VERSION, lifecycle_identity
from .policy import POLICY_ID, PROCESSOR_VERSION, SUPPORTED_DIRECTIVES


HASH = re.compile(r"^[a-f0-9]{64}$")
FIELDS = {"schema_version", "lifecycle_id", "record_hash", "directive_id", "directive_hash",
          "directive_type", "target_event_id", "base_event_version", "base_event_hash",
          "result_event_version", "result_event_hash", "target_evolution_id", "target_evolution_hash",
          "target_materialization_id", "target_materialization_hash", "policy_id", "policy_hash",
          "processor_version", "lifecycle_cutoff", "result_event_status",
          "result_corroboration_status", "evidence_transitions", "resolved_conflict"}
TRANSITION_FIELDS = {"relation", "affected_evidence_id", "affected_evidence_hash",
                     "lifecycle_evidence_id", "lifecycle_evidence_hash"}


def validate_lifecycle(record: dict, directive: dict, base_event: dict, evolution: dict,
                       materialization: dict, *, expected_policy_hash: str,
                       verify_hash: bool = True) -> dict:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise Stage6LifecycleError("LIFECYCLE_FIELDS_MISMATCH")
    if (record["schema_version"] != LIFECYCLE_SCHEMA_VERSION or record["policy_id"] != POLICY_ID
            or record["processor_version"] != PROCESSOR_VERSION
            or record["directive_type"] not in SUPPORTED_DIRECTIVES):
        raise Stage6LifecycleError("LIFECYCLE_IDENTITY_FIELDS_INVALID")
    if (record["directive_id"], record["directive_hash"], record["target_event_id"],
            record["base_event_version"], record["base_event_hash"], record["result_event_version"],
            record["target_evolution_id"], record["target_evolution_hash"],
            record["target_materialization_id"], record["target_materialization_hash"],
            record["lifecycle_cutoff"]) != (
            directive["directive_id"], directive["record_hash"], base_event["event_id"], 2,
            base_event["record_hash"], 3, evolution["evolution_id"], evolution["record_hash"],
            materialization["materialization_id"], materialization["record_hash"],
            directive["lifecycle_cutoff"]):
        raise Stage6LifecycleError("LIFECYCLE_BINDING_MISMATCH")
    for field in ("record_hash", "directive_hash", "base_event_hash", "result_event_hash",
                  "target_evolution_hash", "target_materialization_hash", "policy_hash"):
        if not isinstance(record[field], str) or not HASH.fullmatch(record[field]):
            raise Stage6LifecycleError(f"LIFECYCLE_HASH_INVALID:{field}")
    if (not isinstance(expected_policy_hash, str) or not HASH.fullmatch(expected_policy_hash)
            or record["policy_hash"] != expected_policy_hash
            or directive["policy_hash"] != expected_policy_hash
            or record["policy_hash"] != directive["policy_hash"]):
        raise Stage6LifecycleError("LIFECYCLE_POLICY_HASH_MISMATCH")
    transitions = record["evidence_transitions"]
    if (not isinstance(transitions, list) or not transitions
            or any(not isinstance(item, dict) or set(item) != TRANSITION_FIELDS for item in transitions)
            or transitions != sorted(transitions, key=lambda item: (item["affected_evidence_id"], item["lifecycle_evidence_id"]))
            or len({(item["affected_evidence_id"], item["lifecycle_evidence_id"]) for item in transitions}) != len(transitions)):
        raise Stage6LifecycleError("LIFECYCLE_TRANSITIONS_INVALID")
    for item in transitions:
        if item["relation"] not in {"CORRECTION", "RETRACTION"}:
            raise Stage6LifecycleError("LIFECYCLE_TRANSITION_RELATION_INVALID")
        for field in ("affected_evidence_hash", "lifecycle_evidence_hash"):
            if not isinstance(item[field], str) or not HASH.fullmatch(item[field]):
                raise Stage6LifecycleError("LIFECYCLE_TRANSITION_HASH_INVALID")
    conflict = record["resolved_conflict"]
    if directive["directive_type"] == "RESOLVE_CONFLICT":
        if (not isinstance(conflict, dict) or set(conflict) != {"evidence_ids", "description", "status"}
                or conflict["status"] != "RESOLVED" or not isinstance(conflict["description"], str)
                or not conflict["description"] or not isinstance(conflict["evidence_ids"], list)
                or len(conflict["evidence_ids"]) < 2 or len(conflict["evidence_ids"]) != len(set(conflict["evidence_ids"]))):
            raise Stage6LifecycleError("RESOLVED_CONFLICT_SNAPSHOT_INVALID")
    elif conflict is not None:
        raise Stage6LifecycleError("RESOLVED_CONFLICT_SNAPSHOT_PROHIBITED")
    if record["lifecycle_id"] != lifecycle_identity(directive, base_event, evolution, record["policy_hash"]):
        raise LifecycleIntegrityFailure("LIFECYCLE_ID_MISMATCH")
    if verify_hash and record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise LifecycleIntegrityFailure("LIFECYCLE_RECORD_HASH_MISMATCH")
    return record
