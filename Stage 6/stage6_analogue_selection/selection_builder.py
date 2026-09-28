from copy import deepcopy
from datetime import date

from stage6_ingestion.canonical import canonical_hash, parse_utc, without

from .comparator import compare_snapshots
from .errors import Stage6AnalogueSelectionError
from .policy import COMPARISON_CONTRACT_VERSION, METRIC, SCHEMA_VERSION

UNIVERSE_VERSION = "EXPLICIT_STAGE6_4B_FEATURE_SNAPSHOT_SET_V1"
EXCLUSION_RULES = (
    "EXCLUDE_TARGET_SNAPSHOT_ID",
    "EXCLUDE_NON_HISTORICAL_CUTOFF",
    "EXCLUDE_OUTSIDE_ELIGIBLE_DATE_RANGE",
    "EXCLUDE_TARGET_EVENT_ID",
    "EXACT_EVENT_TYPE_REQUIRED",
)
SAFETY = {
    "future_outcomes_status": "NOT_ATTACHED",
    "outcome_distributions_status": "NOT_EVALUATED",
    "expected_return_status": "NOT_EVALUATED",
    "target_price_status": "NOT_EVALUATED",
    "security_ranking_status": "NOT_EVALUATED",
    "portfolio_influence_status": "NOT_EVALUATED",
    "buy_sell_hold_status": "NOT_EVALUATED",
    "similarity_metric_status": "EVALUATED",
    "analogue_selection_status": "EVALUATED",
    "trading_authority": False,
}


def _date(value, name):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise Stage6AnalogueSelectionError(f"ANALOGUE_ELIGIBLE_DATE_INVALID:{name}") from exc


def candidate_binding(record):
    return {
        "feature_snapshot_id": record["feature_snapshot_id"],
        "feature_snapshot_hash": record["feature_snapshot_hash"],
        "record_hash": record["record_hash"],
    }


def candidate_universe(records):
    bindings = sorted((candidate_binding(record) for record in records), key=lambda x: x["feature_snapshot_id"])
    return bindings, canonical_hash({"universe_version": UNIVERSE_VERSION, "bindings": bindings})


def build_selection(*, target, candidates, eligible_start_date, eligible_end_date, policy, policy_hash, comparison_contract, comparison_contract_hash):
    start, end = _date(eligible_start_date, "start"), _date(eligible_end_date, "end")
    if start > end:
        raise Stage6AnalogueSelectionError("ANALOGUE_ELIGIBLE_DATE_RANGE_REVERSED")
    if end >= parse_utc(target["selection_cutoff"], "target_cutoff").date():
        raise Stage6AnalogueSelectionError("ANALOGUE_ELIGIBLE_END_NOT_HISTORICAL")
    if not candidates:
        raise Stage6AnalogueSelectionError("ANALOGUE_CANDIDATE_SET_REQUIRED")
    ids = [record["feature_snapshot_id"] for record in candidates]
    if len(ids) != len(set(ids)):
        raise Stage6AnalogueSelectionError("ANALOGUE_DUPLICATE_CANDIDATE_ID")
    ordered = sorted(candidates, key=lambda x: x["feature_snapshot_id"])
    bindings, universe_hash = candidate_universe(ordered)
    weights = deepcopy(comparison_contract["feature_weights"])
    specification = {
        "target_feature_snapshot_id": target["feature_snapshot_id"],
        "target_feature_snapshot_hash": target["feature_snapshot_hash"],
        "candidate_universe_hash": universe_hash,
        "eligible_date_range": {"start_date": eligible_start_date, "end_date": eligible_end_date},
        "exclusion_rules": list(EXCLUSION_RULES),
        "feature_contract_version": target["feature_contract_version"],
        "feature_contract_hash": target["feature_contract_hash"],
        "comparison_contract_version": COMPARISON_CONTRACT_VERSION,
        "comparison_contract_hash": comparison_contract_hash,
        "policy_id": policy["policy_id"],
        "policy_hash": policy_hash,
        "metric": METRIC,
        "feature_weights": weights,
        "max_distance": deepcopy(policy["max_distance"]),
        "top_k": policy["top_k"],
        "minimum_required_analogue_count": policy["minimum_required_analogue_count"],
    }
    spec_hash = canonical_hash(specification)
    evaluations = []
    for candidate in ordered:
        reasons = []
        candidate_date = parse_utc(candidate["as_of_timestamp"], "candidate_as_of").date()
        if candidate["feature_snapshot_id"] == target["feature_snapshot_id"]:
            reasons.append("TARGET_SELF_EXCLUDED")
        if parse_utc(candidate["selection_cutoff"], "candidate_cutoff") >= parse_utc(target["selection_cutoff"], "target_cutoff"):
            reasons.append("NON_HISTORICAL_CUTOFF")
        if not start <= candidate_date <= end:
            reasons.append("OUTSIDE_ELIGIBLE_DATE_RANGE")
        if candidate["event_id"] == target["event_id"]:
            reasons.append("TARGET_EVENT_ID_EXCLUDED")
        if candidate["selection_input_snapshot"]["event_type"] != target["selection_input_snapshot"]["event_type"]:
            reasons.append("EVENT_TYPE_MISMATCH")
        evaluation = {
            "candidate_feature_snapshot_id": candidate["feature_snapshot_id"],
            "candidate_feature_snapshot_hash": candidate["feature_snapshot_hash"],
            "candidate_record_hash": candidate["record_hash"],
            "candidate_company_entity_id": candidate["company_entity_id"],
            "candidate_event_id": candidate["event_id"],
            "candidate_event_version": candidate["event_version"],
            "historical_as_of_timestamp": candidate["as_of_timestamp"],
            "candidate_selection_cutoff": candidate["selection_cutoff"],
            "selection_input_hash": candidate["selection_input_hash"],
            "eligibility_status": "EXCLUDED" if reasons else "ELIGIBLE",
            "exclusion_reason_codes": reasons,
            "top_level_feature_distances": None,
            "comparison_reason_codes": None,
            "distance": None,
            "similarity_score": None,
            "duplicate_event_disposition": "NOT_APPLICABLE",
            "duplicate_input_disposition": "NOT_APPLICABLE",
            "selected": False,
        }
        if not reasons:
            distances, comparison_reasons, distance, similarity = compare_snapshots(target["selection_input_snapshot"], candidate["selection_input_snapshot"], weights)
            evaluation.update(top_level_feature_distances=distances, comparison_reason_codes=comparison_reasons, distance=distance, similarity_score=similarity)
        evaluations.append(evaluation)
    eligible = [item for item in evaluations if item["eligibility_status"] == "ELIGIBLE" and item["distance"] <= policy["max_distance"]["value"]]
    by_event = {}
    for item in sorted(eligible, key=lambda x: (x["distance"], x["candidate_feature_snapshot_id"])):
        if item["candidate_event_id"] in by_event:
            item["duplicate_event_disposition"] = "EXCLUDED_DUPLICATE_EVENT"
            item["exclusion_reason_codes"].append("DUPLICATE_EVENT_EXCLUDED")
        else:
            by_event[item["candidate_event_id"]] = item
            item["duplicate_event_disposition"] = "RETAINED_EVENT_REPRESENTATIVE"
    by_input = {}
    event_winners = list(by_event.values())
    for item in sorted(event_winners, key=lambda x: (x["distance"], x["candidate_feature_snapshot_id"])):
        if item["selection_input_hash"] in by_input:
            item["duplicate_input_disposition"] = "EXCLUDED_DUPLICATE_INPUT"
            item["exclusion_reason_codes"].append("DUPLICATE_INPUT_EXCLUDED")
        else:
            by_input[item["selection_input_hash"]] = item
            item["duplicate_input_disposition"] = "RETAINED_INPUT_REPRESENTATIVE"
    ranked = sorted(by_input.values(), key=lambda x: (x["distance"], x["candidate_feature_snapshot_id"]))[: policy["top_k"]]
    selected_ids = {item["candidate_feature_snapshot_id"] for item in ranked}
    candidate_map = {record["feature_snapshot_id"]: record for record in ordered}
    selected = []
    for item in ranked:
        item["selected"] = True
        candidate = candidate_map[item["candidate_feature_snapshot_id"]]
        selected.append({
            "analogue_id": candidate["feature_snapshot_id"],
            "historical_as_of_timestamp": candidate["as_of_timestamp"],
            "entity_id": candidate["company_entity_id"],
            "event_id": candidate["event_id"],
            "similarity_score": {"value": item["similarity_score"], "unit": "UNITLESS_SCORE"},
            "distance": {"value": item["distance"], "unit": "UNITLESS_DISTANCE"},
            "input_snapshot_hash": candidate["selection_input_hash"],
        })
    for item in evaluations:
        if item["candidate_feature_snapshot_id"] not in selected_ids and item["eligibility_status"] == "ELIGIBLE" and not item["exclusion_reason_codes"]:
            item["exclusion_reason_codes"].append("TOP_K_NOT_SELECTED")
    core = {
        "schema_version": SCHEMA_VERSION,
        "target_feature_snapshot_id": target["feature_snapshot_id"],
        "target_feature_snapshot_hash": target["feature_snapshot_hash"],
        "target_record_hash": target["record_hash"],
        "target_selection_input_hash": target["selection_input_hash"],
        "target_company_entity_id": target["company_entity_id"],
        "target_event_id": target["event_id"],
        "target_event_version": target["event_version"],
        "target_event_hash": target["event_hash"],
        "target_as_of_timestamp": target["as_of_timestamp"],
        "target_selection_cutoff": target["selection_cutoff"],
        "feature_contract_version": target["feature_contract_version"],
        "feature_contract_hash": target["feature_contract_hash"],
        "comparison_contract_version": COMPARISON_CONTRACT_VERSION,
        "comparison_contract_hash": comparison_contract_hash,
        "policy_id": policy["policy_id"],
        "policy_hash": policy_hash,
        "processor_version": policy["processor_version"],
        "authority": policy["authority"],
        "candidate_universe_version": UNIVERSE_VERSION,
        "candidate_universe_hash": universe_hash,
        "candidate_bindings": bindings,
        "eligible_date_range": specification["eligible_date_range"],
        "exclusion_rules": list(EXCLUSION_RULES),
        "similarity_metric": METRIC,
        "feature_weights": weights,
        "max_distance": deepcopy(policy["max_distance"]),
        "top_k": policy["top_k"],
        "minimum_required_analogue_count": policy["minimum_required_analogue_count"],
        "selection_spec_hash": spec_hash,
        "candidate_evaluations": evaluations,
        "selected_analogues": selected,
        "analogue_count": len(selected),
        "interpretation_readiness": "READY_FOR_OUTCOME_ATTACHMENT" if len(selected) >= policy["minimum_required_analogue_count"] else "INSUFFICIENT_ANALOGUES",
        "pit_verified": True,
        **SAFETY,
    }
    result_hash = canonical_hash(core)
    record = {**core, "selection_record_id": "S6ANSEL_" + result_hash[:24], "record_hash": "0" * 64}
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
