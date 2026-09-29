from copy import deepcopy
from decimal import Decimal

from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from .errors import Stage6DynamicManagementError
from .policy import *

SAFETY = {
    "proposal_status": "SHADOW_PROPOSAL_ONLY",
    "thesis_mutation_status": "NOT_APPLIED",
    "stage5d_mutation_status": "PROHIBITED",
    "execution_status": "NOT_AUTHORIZED",
    "stop_application_status": "NOT_APPLIED",
    "target_application_status": "NOT_APPLIED",
    "quantity_change_status": "NOT_EVALUATED",
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


def thesis_binding(thesis):
    return binding(THESIS_SCHEMA, thesis["thesis_id"], thesis["record_hash"])


def canonical_support(values):
    if not isinstance(values, list):
        raise Stage6DynamicManagementError("SUPPORT_BINDINGS_INVALID")
    keys = []
    for item in values:
        if not isinstance(item, dict) or set(item) != {"record_type", "record_id", "record_hash"} or not all(isinstance(item[key], str) and item[key] for key in item):
            raise Stage6DynamicManagementError("SUPPORT_BINDING_INVALID")
        keys.append((item["record_type"], item["record_id"], item["record_hash"]))
    if len(keys) != len(set(keys)):
        raise Stage6DynamicManagementError("DUPLICATE_SUPPORT_BINDING")
    return [binding(*parts) for parts in sorted(keys)]


def _difference(old, proposed):
    if old is None or proposed is None:
        return None
    return format(abs(Decimal(str(proposed["value"])) - Decimal(str(old["value"]))), "f")


def factual_changes(current_stop, proposed_stop, current_target, proposed_target):
    return {
        "stop_changed": canonical_json(current_stop) != canonical_json(proposed_stop),
        "old_stop": deepcopy(current_stop),
        "proposed_stop": deepcopy(proposed_stop),
        "stop_absolute_difference_inr": _difference(current_stop, proposed_stop),
        "target_changed": canonical_json(current_target) != canonical_json(proposed_target),
        "old_target": deepcopy(current_target),
        "proposed_target": deepcopy(proposed_target),
        "target_absolute_difference_inr": _difference(current_target, proposed_target),
    }


def build_proposal(*, source, source_record_id, thesis, snapshot, assessment, proposal_cutoff, proposal_mode, proposed_stop, proposed_target, reason_code, supporting_bindings, policy_hash, contract_hash):
    supports = canonical_support(supporting_bindings)
    review_type = snapshot["schema_version"]; assessment_type = assessment["schema_version"]
    record = {
        "schema_version": PROPOSAL_SCHEMA,
        "proposal_id": "",
        "thesis_id": thesis["thesis_id"],
        "thesis_version": thesis["version"],
        "current_thesis_source": source,
        "current_version_record_id": source_record_id,
        "current_thesis_binding": thesis_binding(thesis),
        "bound_review_snapshot_binding": binding(review_type, snapshot["review_snapshot_id"], snapshot["record_hash"]),
        "bound_review_assessment_binding": binding(assessment_type, assessment["assessment_id"], assessment["record_hash"]),
        "proposal_cutoff": proposal_cutoff,
        "thesis_status": thesis["thesis_status"],
        "proposal_mode": proposal_mode,
        "current_stop": deepcopy(thesis["current_stop"]),
        "proposed_stop": deepcopy(proposed_stop),
        "current_target": deepcopy(thesis["current_target"]),
        "proposed_target": deepcopy(proposed_target),
        "reason_code": reason_code,
        "supporting_bindings": supports,
        "factual_change_metadata": factual_changes(thesis["current_stop"], proposed_stop, thesis["current_target"], proposed_target),
        "processor_version": PROCESSOR,
        "policy_id": POLICY_ID,
        "policy_hash": policy_hash,
        "contract_version": CONTRACT_VERSION,
        "contract_hash": contract_hash,
        "authority": AUTHORITY,
        **SAFETY,
        "record_hash": "",
    }
    record["proposal_id"] = "S6MGMT_" + canonical_hash(without(record, "proposal_id", "record_hash"))[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record


def logical_key(thesis, proposal_mode, proposed_stop, proposed_target, reason_code):
    return canonical_json({"current_thesis_hash": thesis["record_hash"], "proposal_mode": proposal_mode, "proposed_stop": proposed_stop, "proposed_target": proposed_target, "reason_code": reason_code})
