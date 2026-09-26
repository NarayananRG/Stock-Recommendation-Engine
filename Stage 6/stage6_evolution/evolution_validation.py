"""Runtime validation for STAGE6_EVENT_EVOLUTION_V1."""
from __future__ import annotations

import re

from stage6_ingestion.canonical import canonical_hash, utc_timestamp, without

from .errors import EvolutionIntegrityFailure, Stage6EvolutionError
from .evolution_mapper import EVOLUTION_SCHEMA_VERSION, evolution_identity
from .policy import EVOLVER_VERSION, POLICY_ID


HASH = re.compile(r"^[a-f0-9]{64}$")
FIELDS = {"schema_version", "evolution_id", "record_hash", "directive_id", "directive_hash",
          "directive_type", "target_event_id", "base_event_version", "base_event_hash",
          "result_event_version", "result_event_hash", "target_materialization_id",
          "target_materialization_hash", "policy_id", "policy_hash", "evolver_version",
          "evolution_cutoff", "result_event_status", "result_corroboration_status",
          "added_evidence_ids"}


def validate_evolution(record: dict, directive: dict, base_event: dict,
                       materialization: dict, *, verify_hash: bool = True) -> dict:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise Stage6EvolutionError("EVOLUTION_FIELDS_MISMATCH")
    if (record["schema_version"] != EVOLUTION_SCHEMA_VERSION or record["policy_id"] != POLICY_ID
            or record["evolver_version"] != EVOLVER_VERSION
            or record["directive_type"] not in {"ADD_SUPPORT", "OPEN_CONFLICT"}):
        raise Stage6EvolutionError("EVOLUTION_IDENTITY_FIELDS_INVALID")
    if (record["directive_id"], record["directive_hash"], record["target_event_id"],
            record["base_event_version"], record["base_event_hash"],
            record["target_materialization_id"], record["target_materialization_hash"],
            record["evolution_cutoff"], record["added_evidence_ids"]) != (
            directive["directive_id"], directive["record_hash"], base_event["event_id"], 1,
            base_event["record_hash"], materialization["materialization_id"],
            materialization["record_hash"], directive["evolution_cutoff"],
            directive["additional_evidence_ids"]):
        raise Stage6EvolutionError("EVOLUTION_BINDING_MISMATCH")
    if type(record["result_event_version"]) is not int or record["result_event_version"] != 2:
        raise Stage6EvolutionError("EVOLUTION_RESULT_VERSION_INVALID")
    for field in ("record_hash", "directive_hash", "base_event_hash", "result_event_hash",
                  "target_materialization_hash", "policy_hash"):
        if not isinstance(record[field], str) or not HASH.fullmatch(record[field]):
            raise Stage6EvolutionError(f"EVOLUTION_HASH_INVALID:{field}")
    if utc_timestamp(record["evolution_cutoff"], "evolution_cutoff") != record["evolution_cutoff"]:
        raise Stage6EvolutionError("EVOLUTION_CUTOFF_INVALID")
    expected = ("CANDIDATE", "CORROBORATED", "SINGLE_SOURCE_OFFICIAL", "SINGLE_SOURCE_INDEPENDENT")
    if record["directive_type"] == "ADD_SUPPORT":
        if record["result_event_status"] != expected[0] or record["result_corroboration_status"] not in expected[1:]:
            raise Stage6EvolutionError("ADD_SUPPORT_RESULT_INVALID")
    elif (record["result_event_status"], record["result_corroboration_status"]) != ("CONFLICTED", "CONFLICTING_EVIDENCE"):
        raise Stage6EvolutionError("OPEN_CONFLICT_RESULT_INVALID")
    if record["evolution_id"] != evolution_identity(directive, base_event, record["policy_hash"]):
        raise EvolutionIntegrityFailure("EVOLUTION_ID_MISMATCH")
    if verify_hash and record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise EvolutionIntegrityFailure("EVOLUTION_RECORD_HASH_MISMATCH")
    return record
