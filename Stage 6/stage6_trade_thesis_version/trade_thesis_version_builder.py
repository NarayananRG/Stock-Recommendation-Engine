from copy import deepcopy

from stage6_ingestion.canonical import canonical_hash, without
from .policy import *

SAFETY = {
    "previous_thesis_status": "FROZEN",
    "review_snapshot_status": "FROZEN",
    "review_assessment_status": "FROZEN",
    "assessment_outcome": "DETERMINATE",
    "trade_thesis_version_2_status": "MATERIALIZED",
    "schema_validation_status": "PASS",
    "stop_change_status": "NOT_EVALUATED",
    "target_change_status": "NOT_EVALUATED",
    "portfolio_action_status": "NOT_EVALUATED",
    "replacement_status": "NOT_EVALUATED",
    "buy_sell_hold_status": "NOT_EVALUATED",
    "network_calls": 0,
    "external_api_calls": 0,
    "market_data_downloads": 0,
    "stage5d_live_database_calls": 0,
    "broker_calls": 0,
    "llm": False,
    "nlp": False,
    "ml": False,
    "ocr": False,
    "embeddings": False,
    "semantic_similarity": False,
    "trading_authority": False,
}


def binding(record_type, record_id, record_hash):
    return {"record_type": record_type, "record_id": record_id, "record_hash": record_hash}


def direct_inputs(previous, snapshot, assessment):
    return [
        binding(PREVIOUS_SCHEMA, previous["thesis_id"], previous["record_hash"]),
        binding(SNAPSHOT_SCHEMA, snapshot["review_snapshot_id"], snapshot["record_hash"]),
        binding(ASSESSMENT_SCHEMA, assessment["assessment_id"], assessment["record_hash"]),
    ]


def build_trade_thesis_v2(previous, snapshot, assessment):
    inputs = direct_inputs(previous, snapshot, assessment)
    transition = assessment["proposed_transition_metadata"]
    change = {
        "version": 2,
        "changed_at_utc": assessment["review_cutoff"],
        "decision_cutoff": assessment["review_cutoff"],
        "change_type": transition["change_type"],
        "reason": assessment["transition_reason_code"],
        "evidence_ids": deepcopy(assessment["review_evidence_ids"]),
        "input_records": deepcopy(inputs),
    }
    preserved = (
        "thesis_id", "recommendation_id", "ticker", "entry_date", "holding_horizon",
        "entry_rationale", "supporting_evidence", "known_risks", "initial_entry_range",
        "fill_references", "aggregate_fill", "initial_stop", "current_stop",
        "initial_target", "current_target", "invalidation_conditions",
    )
    thesis = {key: deepcopy(previous[key]) for key in preserved}
    thesis.update({
        "schema_version": SCHEMA_VERSION,
        "version": 2,
        "thesis_engine_version": THESIS_ENGINE_VERSION,
        "code_commit": RUNTIME_SEMANTIC_COMMIT,
        "decision_cutoff": assessment["review_cutoff"],
        "input_records": inputs,
        "thesis_status": assessment["target_thesis_status"],
        "last_review_date": transition["last_review_date"],
        "change_history": deepcopy(previous["change_history"]) + [change],
        "previous_version_hash": previous["record_hash"],
        "record_hash": "",
        "authority_mode": AUTHORITY,
    })
    thesis["record_hash"] = canonical_hash(without(thesis, "record_hash"))
    return thesis


def build_version_record(previous, snapshot, assessment, policy_hash, contract_hash):
    thesis = build_trade_thesis_v2(previous, snapshot, assessment)
    inputs = direct_inputs(previous, snapshot, assessment)
    record = {
        "schema_version": WRAPPER_SCHEMA_VERSION,
        "version_record_id": "",
        "thesis_id": thesis["thesis_id"],
        "thesis_version": 2,
        "trade_thesis": thesis,
        "previous_thesis_binding": inputs[0],
        "review_snapshot_binding": inputs[1],
        "assessment_binding": inputs[2],
        "code_commit": RUNTIME_SEMANTIC_COMMIT,
        "processor_version": PROCESSOR_VERSION,
        "policy_id": POLICY_ID,
        "policy_hash": policy_hash,
        "materialization_contract_version": CONTRACT_VERSION,
        "materialization_contract_hash": contract_hash,
        "trade_thesis_schema_blob": TRADE_THESIS_BLOB,
        "authority": AUTHORITY,
        **SAFETY,
        "record_hash": "",
    }
    record["version_record_id"] = "S6THVER_" + canonical_hash(without(record, "version_record_id", "record_hash"))[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
