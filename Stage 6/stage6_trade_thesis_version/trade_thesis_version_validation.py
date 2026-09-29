import re
from copy import deepcopy
from datetime import date

from stage6_ingestion.canonical import canonical_hash, parse_utc, without
from stage6_trade_thesis.trade_thesis_validation import (
    BINDING_FIELDS,
    CHANGE_FIELDS,
    FILL_FIELDS,
    THESIS_FIELDS,
    validate_trade_thesis,
)
from stage6_thesis_review_assessment.review_assessment_validation import validate_assessment
from stage6_thesis_review_input.review_input_validation import validate_review_snapshot
from .errors import TradeThesisVersionIntegrityFailure
from .policy import *
from .trade_thesis_version_builder import SAFETY, build_version_record, direct_inputs

HASH = re.compile(r"[a-f0-9]{64}")
WRAPPER_FIELDS = {
    "schema_version", "version_record_id", "thesis_id", "thesis_version",
    "trade_thesis", "previous_thesis_binding", "review_snapshot_binding",
    "assessment_binding", "code_commit", "processor_version", "policy_id",
    "policy_hash", "materialization_contract_version",
    "materialization_contract_hash", "trade_thesis_schema_blob", "authority",
    *SAFETY.keys(), "record_hash",
}


def fail(code):
    raise TradeThesisVersionIntegrityFailure(code)


def binding(value):
    return (
        isinstance(value, dict)
        and set(value) == BINDING_FIELDS
        and all(isinstance(value.get(key), str) and value[key] for key in BINDING_FIELDS)
        and HASH.fullmatch(value["record_hash"])
    )


def positive(value):
    return type(value) in (int, float) and not isinstance(value, bool) and value > 0


def price(value):
    return value is None or (
        isinstance(value, dict)
        and set(value) == {"value", "currency"}
        and positive(value["value"])
        and value["currency"] == "INR"
    )


def eligibility(assessment):
    ready = (
        assessment.get("review_outcome") == "DETERMINATE"
        and assessment.get("next_thesis_version_status") == "READY_FOR_MATERIALIZATION"
        and assessment.get("target_thesis_status") in ELIGIBLE_STATUSES
        and assessment.get("proposed_transition_metadata") is not None
    )
    return "READY_FOR_MATERIALIZATION" if ready else "WITHHELD_INDETERMINATE"


def validate_chain(previous, snapshot, assessment):
    validate_trade_thesis(previous)
    validate_review_snapshot(snapshot)
    validate_assessment(assessment, previous, snapshot)
    expected = (
        previous["thesis_id"], previous["record_hash"],
        snapshot["review_snapshot_id"], snapshot["record_hash"],
        previous["thesis_id"], previous["record_hash"],
        previous["thesis_id"], previous["recommendation_id"], previous["ticker"],
        previous["version"], previous["decision_cutoff"], snapshot["review_cutoff"],
    )
    actual = (
        assessment["previous_thesis_binding"]["record_id"],
        assessment["previous_thesis_binding"]["record_hash"],
        assessment["review_snapshot_binding"]["record_id"],
        assessment["review_snapshot_binding"]["record_hash"],
        snapshot["previous_thesis_binding"]["record_id"],
        snapshot["previous_thesis_binding"]["record_hash"],
        assessment["thesis_id"], assessment["recommendation_id"], assessment["ticker"],
        assessment["previous_thesis_version"], assessment["prior_decision_cutoff"],
        assessment["review_cutoff"],
    )
    if actual != expected or assessment["review_cutoff"] != snapshot["review_cutoff"]:
        fail("TRADE_THESIS_VERSION_CHAIN_MISMATCH")
    if previous["version"] != 1 or parse_utc(assessment["review_cutoff"], "review") <= parse_utc(previous["decision_cutoff"], "previous"):
        fail("TRADE_THESIS_VERSION_CHRONOLOGY_INVALID")
    transition = assessment.get("proposed_transition_metadata")
    if eligibility(assessment) == "READY_FOR_MATERIALIZATION":
        if (
            transition.get("previous_version") != 1
            or transition.get("proposed_next_version") != 2
            or transition.get("previous_version_hash") != previous["record_hash"]
            or transition.get("target_thesis_status") != assessment["target_thesis_status"]
            or transition.get("review_cutoff") != assessment["review_cutoff"]
            or transition.get("last_review_date") != assessment["review_cutoff"][:10]
            or transition.get("change_type") != CHANGE_TYPES[assessment["target_thesis_status"]]
            or transition.get("change_reason_code") != assessment["transition_reason_code"]
            or transition.get("review_evidence_ids") != assessment["review_evidence_ids"]
            or transition.get("next_version_direct_input_policy") != [PREVIOUS_SCHEMA, SNAPSHOT_SCHEMA, ASSESSMENT_SCHEMA]
        ):
            fail("TRADE_THESIS_VERSION_TRANSITION_INVALID")
    return True


def validate_trade_thesis_v2(record, previous, snapshot, assessment):
    validate_chain(previous, snapshot, assessment)
    if eligibility(assessment) != "READY_FOR_MATERIALIZATION":
        fail("TRADE_THESIS_VERSION_NOT_ELIGIBLE")
    if not isinstance(record, dict) or set(record) != THESIS_FIELDS:
        fail("TRADE_THESIS_V2_FIELDS_INVALID")
    identity = tuple(record.get(key) for key in ("schema_version", "version", "thesis_engine_version", "code_commit", "authority_mode"))
    if identity != (SCHEMA_VERSION, 2, THESIS_ENGINE_VERSION, RUNTIME_SEMANTIC_COMMIT, AUTHORITY):
        fail("TRADE_THESIS_V2_IDENTITY_INVALID")
    try:
        parse_utc(record["decision_cutoff"], "decision_cutoff")
        date.fromisoformat(record["last_review_date"])
        if record["entry_date"] is not None:
            date.fromisoformat(record["entry_date"])
    except Exception as exc:
        raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_V2_TIME_INVALID") from exc
    inputs = direct_inputs(previous, snapshot, assessment)
    if record["input_records"] != inputs or any(not binding(value) for value in record["input_records"]):
        fail("TRADE_THESIS_V2_INPUTS_INVALID")
    preserved = (
        "thesis_id", "recommendation_id", "ticker", "entry_date", "holding_horizon",
        "entry_rationale", "supporting_evidence", "known_risks", "initial_entry_range",
        "fill_references", "aggregate_fill", "initial_stop", "current_stop",
        "initial_target", "current_target", "invalidation_conditions",
    )
    if any(record[key] != previous[key] for key in preserved):
        fail("TRADE_THESIS_V2_PRESERVED_FIELD_MISMATCH")
    if not isinstance(record["entry_rationale"], list) or not record["entry_rationale"] or not all(isinstance(x, str) for x in record["entry_rationale"]):
        fail("TRADE_THESIS_V2_RATIONALE_INVALID")
    for key in ("supporting_evidence", "known_risks", "invalidation_conditions"):
        if not isinstance(record[key], list) or (key == "invalidation_conditions" and not record[key]):
            fail("TRADE_THESIS_V2_LIST_INVALID")
    if len(record["supporting_evidence"]) != len(set(record["supporting_evidence"])):
        fail("TRADE_THESIS_V2_EVIDENCE_DUPLICATE")
    entry_range = record["initial_entry_range"]
    if not isinstance(entry_range, dict) or set(entry_range) != {"low", "high", "currency"} or not positive(entry_range["low"]) or not positive(entry_range["high"]) or entry_range["low"] > entry_range["high"] or entry_range["currency"] != "INR":
        fail("TRADE_THESIS_V2_RANGE_INVALID")
    if not isinstance(record["fill_references"], list):
        fail("TRADE_THESIS_V2_FILLS_INVALID")
    for fill in record["fill_references"]:
        if not isinstance(fill, dict) or set(fill) != FILL_FIELDS or type(fill["quantity"]) is not int or fill["quantity"] <= 0 or not positive(fill["price"]) or fill["currency"] != "INR" or fill["source_system"] != "STAGE5D5_FROZEN_PRODUCTION_CONTROL":
            fail("TRADE_THESIS_V2_FILL_INVALID")
    aggregate = record["aggregate_fill"]
    if aggregate is not None and (not isinstance(aggregate, dict) or set(aggregate) != {"total_quantity", "volume_weighted_average_price", "currency"} or type(aggregate["total_quantity"]) is not int or aggregate["total_quantity"] <= 0 or not positive(aggregate["volume_weighted_average_price"]) or aggregate["currency"] != "INR"):
        fail("TRADE_THESIS_V2_AGGREGATE_INVALID")
    if not all(price(record[key]) for key in ("initial_stop", "current_stop", "initial_target", "current_target")):
        fail("TRADE_THESIS_V2_PRICE_INVALID")
    if record["thesis_status"] != assessment["target_thesis_status"] or record["thesis_status"] == "CLOSED":
        fail("TRADE_THESIS_V2_STATUS_INVALID")
    if record["decision_cutoff"] != assessment["review_cutoff"] or record["last_review_date"] != assessment["proposed_transition_metadata"]["last_review_date"]:
        fail("TRADE_THESIS_V2_REVIEW_TIME_INVALID")
    if record["previous_version_hash"] != previous["record_hash"] or record["previous_version_hash"] != assessment["proposed_transition_metadata"]["previous_version_hash"]:
        fail("TRADE_THESIS_V2_PREVIOUS_HASH_INVALID")
    if not isinstance(previous["change_history"], list) or [item["version"] for item in previous["change_history"]] != [1]:
        fail("TRADE_THESIS_V2_PREVIOUS_HISTORY_INVALID")
    if record["change_history"][:-1] != previous["change_history"] or [item["version"] for item in record["change_history"]] != [1, 2]:
        fail("TRADE_THESIS_V2_HISTORY_CONTINUITY_INVALID")
    change = record["change_history"][-1]
    wanted_change = {
        "version": 2,
        "changed_at_utc": assessment["review_cutoff"],
        "decision_cutoff": assessment["review_cutoff"],
        "change_type": assessment["proposed_transition_metadata"]["change_type"],
        "reason": assessment["transition_reason_code"],
        "evidence_ids": assessment["review_evidence_ids"],
        "input_records": inputs,
    }
    if not isinstance(change, dict) or set(change) != CHANGE_FIELDS or change != wanted_change:
        fail("TRADE_THESIS_V2_HISTORY_ENTRY_INVALID")
    if record["record_hash"] != canonical_hash(without(record, "record_hash")):
        fail("TRADE_THESIS_V2_HASH_INVALID")
    return record


def validate_version_record(record, previous, snapshot, assessment, policy_hash=None, contract_hash=None):
    if not isinstance(record, dict) or set(record) != WRAPPER_FIELDS:
        fail("TRADE_THESIS_VERSION_WRAPPER_FIELDS_INVALID")
    expected = (
        WRAPPER_SCHEMA_VERSION, 2, RUNTIME_SEMANTIC_COMMIT, PROCESSOR_VERSION,
        POLICY_ID, CONTRACT_VERSION, TRADE_THESIS_BLOB, AUTHORITY,
    )
    actual = tuple(record.get(key) for key in (
        "schema_version", "thesis_version", "code_commit", "processor_version",
        "policy_id", "materialization_contract_version", "trade_thesis_schema_blob", "authority",
    ))
    if actual != expected:
        fail("TRADE_THESIS_VERSION_WRAPPER_IDENTITY_INVALID")
    if policy_hash is not None and record["policy_hash"] != policy_hash:
        fail("TRADE_THESIS_VERSION_POLICY_HASH_INVALID")
    if contract_hash is not None and record["materialization_contract_hash"] != contract_hash:
        fail("TRADE_THESIS_VERSION_CONTRACT_HASH_INVALID")
    if not HASH.fullmatch(str(record.get("policy_hash", ""))) or not HASH.fullmatch(str(record.get("materialization_contract_hash", ""))):
        fail("TRADE_THESIS_VERSION_DEPENDENCY_HASH_INVALID")
    validate_trade_thesis_v2(record["trade_thesis"], previous, snapshot, assessment)
    inputs = direct_inputs(previous, snapshot, assessment)
    if record["thesis_id"] != previous["thesis_id"] or [record["previous_thesis_binding"], record["review_snapshot_binding"], record["assessment_binding"]] != inputs:
        fail("TRADE_THESIS_VERSION_WRAPPER_BINDING_INVALID")
    for key, value in SAFETY.items():
        if record.get(key) != value:
            fail("TRADE_THESIS_VERSION_SAFETY_INVALID")
    if record["version_record_id"] != "S6THVER_" + canonical_hash(without(record, "version_record_id", "record_hash"))[:24]:
        fail("TRADE_THESIS_VERSION_WRAPPER_ID_INVALID")
    if record["record_hash"] != canonical_hash(without(record, "record_hash")):
        fail("TRADE_THESIS_VERSION_WRAPPER_HASH_INVALID")
    return record
