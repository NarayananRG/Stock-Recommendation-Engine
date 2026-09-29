from copy import deepcopy

from stage6_ingestion.canonical import canonical_hash, without
from .policy import *
from .recursive_review_builder import binding, current_binding

VERSION_SAFETY = {
    "current_thesis_status": "FROZEN",
    "review_snapshot_status": "FROZEN",
    "review_assessment_status": "FROZEN",
    "next_thesis_version_status": "MATERIALIZED",
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


def version_inputs(current, snapshot, assessment):
    return [
        current_binding(current),
        binding(REVIEW_SCHEMA, snapshot["review_snapshot_id"], snapshot["record_hash"]),
        binding(ASSESSMENT_SCHEMA, assessment["assessment_id"], assessment["record_hash"]),
    ]


def build_thesis(current, snapshot, assessment):
    next_version = current["version"] + 1
    inputs = version_inputs(current, snapshot, assessment)
    change = {
        "version": next_version,
        "changed_at_utc": snapshot["review_cutoff"],
        "decision_cutoff": snapshot["review_cutoff"],
        "change_type": CHANGE_TYPES[assessment["target_thesis_status"]],
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
    thesis = {key: deepcopy(current[key]) for key in preserved}
    thesis.update({
        "schema_version": THESIS_SCHEMA,
        "version": next_version,
        "thesis_engine_version": SEMANTICS,
        "code_commit": SEMANTIC_COMMIT,
        "decision_cutoff": snapshot["review_cutoff"],
        "input_records": inputs,
        "thesis_status": assessment["target_thesis_status"],
        "last_review_date": snapshot["review_cutoff"][:10],
        "change_history": deepcopy(current["change_history"]) + [change],
        "previous_version_hash": current["record_hash"],
        "record_hash": "",
        "authority_mode": AUTHORITY,
    })
    thesis["record_hash"] = canonical_hash(without(thesis, "record_hash"))
    return thesis


def build_version_wrapper(source, source_record_id, current, snapshot, assessment, policy_hash, contract_hash):
    thesis = build_thesis(current, snapshot, assessment)
    inputs = version_inputs(current, snapshot, assessment)
    record = {
        "schema_version": WRAPPER_SCHEMA,
        "version_record_id": "",
        "thesis_id": thesis["thesis_id"],
        "thesis_version": thesis["version"],
        "trade_thesis": thesis,
        "current_thesis_source": source,
        "current_version_record_id": source_record_id,
        "current_thesis_binding": inputs[0],
        "review_snapshot_binding": inputs[1],
        "assessment_binding": inputs[2],
        "thesis_engine_version": SEMANTICS,
        "semantic_code_commit": SEMANTIC_COMMIT,
        "processor_version": PROCESSOR,
        "policy_id": POLICY_ID,
        "policy_hash": policy_hash,
        "contract_version": CONTRACT_VERSION,
        "contract_hash": contract_hash,
        "trade_thesis_schema_blob": THESIS_BLOB,
        "authority": AUTHORITY,
        "material_change_status": assessment["material_change_status"],
        **VERSION_SAFETY,
        "record_hash": "",
    }
    record["version_record_id"] = "S6THRECURVER_" + canonical_hash(without(record, "version_record_id", "record_hash"))[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
