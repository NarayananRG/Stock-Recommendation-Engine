"""Validation for explicit immutable evolution directives."""
from __future__ import annotations

import re

from stage6_ingestion.canonical import canonical_hash, parse_utc, utc_timestamp, without

from .directive_builder import DIRECTIVE_SCHEMA_VERSION, directive_identity
from .errors import EvolutionIntegrityFailure, Stage6EvolutionError
from .policy import EVOLVER_VERSION, MAX_CONFLICT_DESCRIPTION, POLICY_ID, SUPPORTED_DIRECTIVES


HASH = re.compile(r"^[a-f0-9]{64}$")
FIELDS = {"schema_version", "directive_id", "record_hash", "directive_type", "target_event_id",
          "base_event_version", "base_event_hash", "target_materialization_id",
          "target_materialization_hash", "additional_evidence_ids", "conflict_evidence_ids",
          "conflict_description", "evolution_cutoff", "policy_id", "policy_hash", "evolver_version"}


def _ids(value: object, field: str, *, minimum: int = 0) -> list[str]:
    if (not isinstance(value, list) or len(value) < minimum
            or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value)) or value != sorted(value)):
        raise Stage6EvolutionError(f"DIRECTIVE_EVIDENCE_IDS_INVALID:{field}")
    return value


def validate_directive(record: dict, base_event: dict, materialization: dict, *, verify_hash: bool = True) -> dict:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise Stage6EvolutionError("DIRECTIVE_FIELDS_MISMATCH")
    if (record["schema_version"] != DIRECTIVE_SCHEMA_VERSION or record["policy_id"] != POLICY_ID
            or record["evolver_version"] != EVOLVER_VERSION or record["directive_type"] not in SUPPORTED_DIRECTIVES):
        raise Stage6EvolutionError("DIRECTIVE_IDENTITY_FIELDS_INVALID")
    if (record["target_event_id"], record["base_event_version"], record["base_event_hash"],
            record["target_materialization_id"], record["target_materialization_hash"]) != (
            base_event["event_id"], 1, base_event["record_hash"], materialization["materialization_id"],
            materialization["record_hash"]):
        raise Stage6EvolutionError("DIRECTIVE_ANCHOR_BINDING_MISMATCH")
    for field in ("record_hash", "base_event_hash", "target_materialization_hash", "policy_hash"):
        if not isinstance(record[field], str) or not HASH.fullmatch(record[field]):
            raise Stage6EvolutionError(f"DIRECTIVE_HASH_INVALID:{field}")
    additional = _ids(record["additional_evidence_ids"], "additional", minimum=1)
    conflicts = _ids(record["conflict_evidence_ids"], "conflict")
    existing = set(base_event["source_evidence_ids"])
    if not set(additional) - existing:
        raise Stage6EvolutionError("DIRECTIVE_NEW_EVIDENCE_REQUIRED")
    if record["directive_type"] == "ADD_SUPPORT":
        if conflicts or record["conflict_description"] is not None:
            raise Stage6EvolutionError("ADD_SUPPORT_CONFLICT_FIELDS_PROHIBITED")
    else:
        description = record["conflict_description"]
        union = existing | set(additional)
        if len(conflicts) < 2 or not set(conflicts).issubset(union) or not set(conflicts) - existing:
            raise Stage6EvolutionError("OPEN_CONFLICT_EVIDENCE_INVALID")
        if not isinstance(description, str) or not description.strip() or len(description) > MAX_CONFLICT_DESCRIPTION:
            raise Stage6EvolutionError("OPEN_CONFLICT_DESCRIPTION_INVALID")
    cutoff = utc_timestamp(record["evolution_cutoff"], "evolution_cutoff")
    if cutoff != record["evolution_cutoff"] or parse_utc(cutoff, "evolution_cutoff") < parse_utc(base_event["last_updated_timestamp"], "last_updated_timestamp"):
        raise Stage6EvolutionError("DIRECTIVE_EVOLUTION_CUTOFF_INVALID")
    if record["directive_id"] != directive_identity(record):
        raise EvolutionIntegrityFailure("DIRECTIVE_ID_MISMATCH")
    if verify_hash and record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise EvolutionIntegrityFailure("DIRECTIVE_RECORD_HASH_MISMATCH")
    return record
