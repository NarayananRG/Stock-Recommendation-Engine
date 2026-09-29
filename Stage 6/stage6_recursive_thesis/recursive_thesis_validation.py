from datetime import date

from stage6_ingestion.canonical import canonical_hash, parse_utc, without
from stage6_trade_thesis.trade_thesis_validation import BINDING_FIELDS, CHANGE_FIELDS, THESIS_FIELDS
from .errors import RecursiveThesisIntegrityFailure
from .policy import *
from .recursive_review_validation import validate_assessment
from .recursive_thesis_builder import VERSION_SAFETY, build_version_wrapper, version_inputs

WRAPPER_FIELDS = {
    "schema_version", "version_record_id", "thesis_id", "thesis_version", "trade_thesis",
    "current_thesis_source", "current_version_record_id", "current_thesis_binding",
    "review_snapshot_binding", "assessment_binding", "thesis_engine_version", "semantic_code_commit",
    "processor_version", "policy_id", "policy_hash", "contract_version", "contract_hash",
    "trade_thesis_schema_blob", "authority", "material_change_status", *VERSION_SAFETY.keys(), "record_hash",
}
PRESERVED = ("thesis_id", "recommendation_id", "ticker", "entry_date", "holding_horizon", "entry_rationale", "supporting_evidence", "known_risks", "initial_entry_range", "fill_references", "aggregate_fill", "initial_stop", "current_stop", "initial_target", "current_target", "invalidation_conditions")


def fail(code):
    raise RecursiveThesisIntegrityFailure(code)


def validate_recursive_thesis(record, current, snapshot, assessment):
    validate_assessment(assessment, current, snapshot)
    if assessment["review_outcome"] != "DETERMINATE" or assessment["next_thesis_version_status"] != "READY_FOR_MATERIALIZATION":
        fail("RECURSIVE_THESIS_NOT_ELIGIBLE")
    if not isinstance(record, dict) or set(record) != THESIS_FIELDS:
        fail("RECURSIVE_THESIS_FIELDS_INVALID")
    next_version = current["version"] + 1
    if type(current["version"]) is not int or current["version"] < 2 or type(record["version"]) is not int or record["version"] != next_version:
        fail("RECURSIVE_THESIS_VERSION_INVALID")
    if tuple(record.get(key) for key in ("schema_version", "thesis_engine_version", "code_commit", "authority_mode")) != (THESIS_SCHEMA, SEMANTICS, SEMANTIC_COMMIT, AUTHORITY):
        fail("RECURSIVE_THESIS_IDENTITY_INVALID")
    if any(record[key] != current[key] for key in PRESERVED):
        fail("RECURSIVE_THESIS_PRESERVED_FIELD_INVALID")
    if record["decision_cutoff"] != snapshot["review_cutoff"] or parse_utc(record["decision_cutoff"], "new") <= parse_utc(current["decision_cutoff"], "current") or record["last_review_date"] != snapshot["review_cutoff"][:10]:
        fail("RECURSIVE_THESIS_TIME_INVALID")
    date.fromisoformat(record["last_review_date"])
    inputs = version_inputs(current, snapshot, assessment)
    if record["input_records"] != inputs or any(not isinstance(item, dict) or set(item) != BINDING_FIELDS for item in inputs):
        fail("RECURSIVE_THESIS_INPUT_INVALID")
    if record["thesis_status"] != assessment["target_thesis_status"] or record["thesis_status"] == "CLOSED":
        fail("RECURSIVE_THESIS_STATUS_INVALID")
    if record["previous_version_hash"] != current["record_hash"]:
        fail("RECURSIVE_THESIS_PREVIOUS_HASH_INVALID")
    expected_prior = list(range(1, current["version"] + 1))
    if [item.get("version") for item in current["change_history"]] != expected_prior:
        fail("RECURSIVE_CURRENT_HISTORY_INVALID")
    if record["change_history"][:-1] != current["change_history"] or [item.get("version") for item in record["change_history"]] != [*expected_prior, next_version]:
        fail("RECURSIVE_THESIS_HISTORY_INVALID")
    change = record["change_history"][-1]
    wanted_change = {"version": next_version, "changed_at_utc": snapshot["review_cutoff"], "decision_cutoff": snapshot["review_cutoff"], "change_type": CHANGE_TYPES[assessment["target_thesis_status"]], "reason": assessment["transition_reason_code"], "evidence_ids": assessment["review_evidence_ids"], "input_records": inputs}
    if not isinstance(change, dict) or set(change) != CHANGE_FIELDS or change != wanted_change:
        fail("RECURSIVE_THESIS_HISTORY_ENTRY_INVALID")
    if record["record_hash"] != canonical_hash(without(record, "record_hash")):
        fail("RECURSIVE_THESIS_HASH_INVALID")
    return record


def validate_version_wrapper(record, source, source_record_id, current, snapshot, assessment, policy_hash=None, contract_hash=None):
    if not isinstance(record, dict) or set(record) != WRAPPER_FIELDS:
        fail("RECURSIVE_WRAPPER_FIELDS_INVALID")
    validate_recursive_thesis(record["trade_thesis"], current, snapshot, assessment)
    expected = (WRAPPER_SCHEMA, record["trade_thesis"]["version"], source, source_record_id, SEMANTICS, SEMANTIC_COMMIT, PROCESSOR, POLICY_ID, CONTRACT_VERSION, THESIS_BLOB, AUTHORITY, assessment["material_change_status"])
    actual = tuple(record.get(key) for key in ("schema_version", "thesis_version", "current_thesis_source", "current_version_record_id", "thesis_engine_version", "semantic_code_commit", "processor_version", "policy_id", "contract_version", "trade_thesis_schema_blob", "authority", "material_change_status"))
    if actual != expected or record["thesis_id"] != current["thesis_id"]:
        fail("RECURSIVE_WRAPPER_IDENTITY_INVALID")
    if policy_hash is not None and record["policy_hash"] != policy_hash:
        fail("RECURSIVE_WRAPPER_POLICY_HASH_INVALID")
    if contract_hash is not None and record["contract_hash"] != contract_hash:
        fail("RECURSIVE_WRAPPER_CONTRACT_HASH_INVALID")
    if [record["current_thesis_binding"], record["review_snapshot_binding"], record["assessment_binding"]] != version_inputs(current, snapshot, assessment):
        fail("RECURSIVE_WRAPPER_BINDING_INVALID")
    for key, value in VERSION_SAFETY.items():
        if record.get(key) != value:
            fail("RECURSIVE_WRAPPER_SAFETY_INVALID")
    if record["version_record_id"] != "S6THRECURVER_" + canonical_hash(without(record, "version_record_id", "record_hash"))[:24] or record["record_hash"] != canonical_hash(without(record, "record_hash")):
        fail("RECURSIVE_WRAPPER_HASH_INVALID")
    return record
