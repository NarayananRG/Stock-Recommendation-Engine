from copy import deepcopy

from stage6_ingestion.canonical import canonical_hash, without
from stage6_thesis_review_assessment.review_assessment_builder import canonical_support, decide
from .policy import *

REVIEW_SAFETY = {
    "current_thesis_status": "FROZEN",
    "review_inputs_status": "CALLER_SELECTED_UNINTERPRETED",
    "absence_semantics": "NOT_REASSURING",
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

ASSESSMENT_SAFETY = {
    "current_thesis_status": "FROZEN",
    "review_snapshot_status": "FROZEN",
    "stop_change_status": "NOT_EVALUATED",
    "target_change_status": "NOT_EVALUATED",
    "portfolio_action_status": "NOT_EVALUATED",
    "replacement_status": "NOT_EVALUATED",
    "buy_sell_hold_status": "NOT_EVALUATED",
    "trading_authority": False,
}


def binding(record_type, record_id, record_hash):
    return {"record_type": record_type, "record_id": record_id, "record_hash": record_hash}


def current_binding(thesis):
    return binding(THESIS_SCHEMA, thesis["thesis_id"], thesis["record_hash"])


def _portfolio_presence(portfolio, ticker):
    if portfolio is None:
        return "NOT_PROVIDED"
    payload = portfolio["portfolio_context"]
    opened = any(item.get("ticker") == ticker for item in payload.get("open_positions", []))
    pending = any(item.get("ticker") == ticker for item in payload.get("pending_entries", []))
    if opened and pending:
        return "OPEN_AND_PENDING"
    if opened:
        return "OPEN_POSITION"
    if pending:
        return "PENDING_ENTRY"
    return "NOT_PRESENT"


def build_review_snapshot(*, current, source, source_record_id, review_cutoff, evidence, effects, market, analogue, portfolio, policy_hash, contract_hash):
    current_input = current_binding(current)
    evidence_bindings = sorted(
        [binding("STAGE6_EVIDENCE_V2", item["evidence_id"], item["record_hash"]) for item in evidence],
        key=lambda item: item["record_id"],
    )
    effect_bindings = sorted(
        [binding("STAGE6_EVENT_COMPANY_EFFECT_V1", item["company_effect_record_id"], item["record_hash"]) for item in effects],
        key=lambda item: item["record_id"],
    )
    market_binding = None if market is None else binding("STAGE6_MARKET_CONTEXT_V2", market["contract_payload"]["market_context_id"], market["record_hash"])
    analogue_binding = None if analogue is None else binding("STAGE6_HISTORICAL_ANALOGUE_V2", analogue["historical_analogue_payload"]["historical_analogue_id"], analogue["record_hash"])
    portfolio_binding = None if portfolio is None else binding("STAGE6_PORTFOLIO_CONTEXT_V2", portfolio["portfolio_context"]["portfolio_context_id"], portfolio["record_hash"])
    optional = [item for item in (market_binding, analogue_binding, portfolio_binding) if item is not None]
    inputs = [current_input, *evidence_bindings, *effect_bindings, *optional]
    availability = {
        "evidence": "AVAILABLE" if evidence else "NOT_PROVIDED",
        "company_effects": "AVAILABLE" if effects else "NOT_PROVIDED",
        "market_context": "AVAILABLE" if market else "NOT_PROVIDED",
        "historical_analogue": "AVAILABLE" if analogue else "NOT_PROVIDED",
        "portfolio_context": "AVAILABLE" if portfolio else "NOT_PROVIDED",
    }
    record = {
        "schema_version": REVIEW_SCHEMA,
        "review_snapshot_id": "",
        "current_thesis_source": source,
        "current_version_record_id": source_record_id,
        "current_thesis_binding": current_input,
        "thesis_id": current["thesis_id"],
        "current_version": current["version"],
        "recommendation_id": current["recommendation_id"],
        "ticker": current["ticker"],
        "previous_decision_cutoff": current["decision_cutoff"],
        "review_cutoff": review_cutoff,
        "availability": availability,
        "evidence_bindings": evidence_bindings,
        "company_effect_bindings": effect_bindings,
        "company_effect_summaries": [
            {"company_effect_record_id": item["company_effect_record_id"], "company_event_effect": item["company_event_effect"], "relevance": "CALLER_SELECTED_UNINTERPRETED"}
            for item in sorted(effects, key=lambda item: item["company_effect_record_id"])
        ],
        "market_binding": market_binding,
        "analogue_binding": analogue_binding,
        "portfolio_binding": portfolio_binding,
        "portfolio_ticker_presence": _portfolio_presence(portfolio, current["ticker"]),
        "direct_input_bindings": inputs,
        "factual_delta_metadata": {
            "new_evidence_count": len(evidence),
            "company_effect_count": len(effects),
            "optional_context_count": len(optional),
            "window_start_exclusive": current["decision_cutoff"],
            "window_end_inclusive": review_cutoff,
        },
        "processor_version": PROCESSOR,
        "policy_id": POLICY_ID,
        "policy_hash": policy_hash,
        "contract_version": CONTRACT_VERSION,
        "contract_hash": contract_hash,
        "decision_semantics": SEMANTICS,
        "semantic_code_commit": SEMANTIC_COMMIT,
        "authority": AUTHORITY,
        **REVIEW_SAFETY,
        "record_hash": "",
    }
    record["review_snapshot_id"] = "S6THRECURIN_" + canonical_hash(without(record, "review_snapshot_id", "record_hash"))[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record


def _normalize_invalidations(current, values):
    result = [
        {
            "condition_index": item["condition_index"],
            "condition_text": item["condition_text"],
            "evaluation_status": item["evaluation_status"],
            "supporting_bindings": canonical_support(item["supporting_bindings"]),
        }
        for item in values
    ]
    return sorted(result, key=lambda item: item["condition_index"])


def _normalize_assertions(values):
    result = []
    for item in values:
        core = {"assessment": item["assessment"], "reason_code": item["reason_code"], "supporting_bindings": canonical_support(item["supporting_bindings"])}
        result.append({"assertion_id": "S6THRECURASSERT_" + canonical_hash(core)[:24], **core})
    return sorted(result, key=lambda item: (item["assessment"], item["reason_code"], canonical_hash(item["supporting_bindings"])))


def build_assessment(*, current, snapshot, invalidation_assessments, change_assertions, policy_hash, contract_hash):
    invalidations = _normalize_invalidations(current, invalidation_assessments)
    assertions = _normalize_assertions(change_assertions)
    material, outcome, target, reason = decide(invalidations, assertions)
    supports = [binding for item in [*invalidations, *assertions] for binding in item["supporting_bindings"]]
    evidence_ids = sorted({item["record_id"] for item in supports if item["record_type"] == "STAGE6_EVIDENCE_V2"})
    record = {
        "schema_version": ASSESSMENT_SCHEMA,
        "assessment_id": "",
        "current_thesis_binding": current_binding(current),
        "review_snapshot_binding": binding(REVIEW_SCHEMA, snapshot["review_snapshot_id"], snapshot["record_hash"]),
        "thesis_id": current["thesis_id"],
        "current_version": current["version"],
        "next_proposed_version": current["version"] + 1,
        "recommendation_id": current["recommendation_id"],
        "ticker": current["ticker"],
        "prior_decision_cutoff": current["decision_cutoff"],
        "review_cutoff": snapshot["review_cutoff"],
        "invalidation_assessments": invalidations,
        "change_assertions": assertions,
        "material_change_status": material,
        "review_outcome": outcome,
        "target_thesis_status": target,
        "transition_reason_code": reason,
        "review_evidence_ids": evidence_ids,
        "decision_semantics": SEMANTICS,
        "processor_version": PROCESSOR,
        "policy_id": POLICY_ID,
        "policy_hash": policy_hash,
        "contract_version": CONTRACT_VERSION,
        "contract_hash": contract_hash,
        "semantic_code_commit": SEMANTIC_COMMIT,
        "authority": AUTHORITY,
        **ASSESSMENT_SAFETY,
        "next_thesis_version_status": "READY_FOR_MATERIALIZATION" if outcome == "DETERMINATE" else "WITHHELD_INDETERMINATE",
        "record_hash": "",
    }
    record["assessment_id"] = "S6THRECURASS_" + canonical_hash(without(record, "assessment_id", "record_hash"))[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
