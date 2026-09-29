from stage6_ingestion.canonical import canonical_hash, parse_utc, without
from stage6_thesis_review_assessment.review_assessment_builder import canonical_support, decide
from .errors import RecursiveThesisIntegrityFailure
from .policy import *
from .recursive_review_builder import ASSESSMENT_SAFETY, REVIEW_SAFETY, build_assessment, build_review_snapshot, current_binding

BINDING_FIELDS = {"record_type", "record_id", "record_hash"}
REVIEW_FIELDS = {
    "schema_version", "review_snapshot_id", "current_thesis_source", "current_version_record_id",
    "current_thesis_binding", "thesis_id", "current_version", "recommendation_id", "ticker",
    "previous_decision_cutoff", "review_cutoff", "availability", "evidence_bindings",
    "company_effect_bindings", "company_effect_summaries", "market_binding", "analogue_binding",
    "portfolio_binding", "portfolio_ticker_presence", "direct_input_bindings", "factual_delta_metadata",
    "processor_version", "policy_id", "policy_hash", "contract_version", "contract_hash",
    "decision_semantics", "semantic_code_commit", "authority", *REVIEW_SAFETY.keys(), "record_hash",
}
ASSESSMENT_FIELDS = {
    "schema_version", "assessment_id", "current_thesis_binding", "review_snapshot_binding",
    "thesis_id", "current_version", "next_proposed_version", "recommendation_id", "ticker",
    "prior_decision_cutoff", "review_cutoff", "invalidation_assessments", "change_assertions",
    "material_change_status", "review_outcome", "target_thesis_status", "transition_reason_code",
    "review_evidence_ids", "decision_semantics", "processor_version", "policy_id", "policy_hash",
    "contract_version", "contract_hash", "semantic_code_commit", "authority", *ASSESSMENT_SAFETY.keys(),
    "next_thesis_version_status", "record_hash",
}


def fail(code):
    raise RecursiveThesisIntegrityFailure(code)


def binding(value):
    return isinstance(value, dict) and set(value) == BINDING_FIELDS and all(isinstance(value.get(key), str) and value[key] for key in BINDING_FIELDS)


def validate_review_snapshot(record, current):
    if not isinstance(record, dict) or set(record) != REVIEW_FIELDS:
        fail("RECURSIVE_REVIEW_FIELDS_INVALID")
    identity = tuple(record.get(key) for key in ("schema_version", "processor_version", "policy_id", "policy_hash", "contract_version", "contract_hash", "decision_semantics", "semantic_code_commit", "authority"))
    expected = (REVIEW_SCHEMA, PROCESSOR, POLICY_ID, EXPECTED_POLICY_HASH, CONTRACT_VERSION, EXPECTED_CONTRACT_HASH, SEMANTICS, SEMANTIC_COMMIT, AUTHORITY)
    if identity != expected or record["current_thesis_source"] not in SOURCE_TYPES:
        fail("RECURSIVE_REVIEW_IDENTITY_INVALID")
    if type(record["current_version"]) is not int or record["current_version"] < 2 or record["current_version"] != current["version"]:
        fail("RECURSIVE_REVIEW_VERSION_INVALID")
    if record["current_thesis_binding"] != current_binding(current):
        fail("RECURSIVE_REVIEW_CURRENT_BINDING_INVALID")
    if (record["thesis_id"], record["recommendation_id"], record["ticker"], record["previous_decision_cutoff"]) != (current["thesis_id"], current["recommendation_id"], current["ticker"], current["decision_cutoff"]):
        fail("RECURSIVE_REVIEW_CURRENT_FIELDS_INVALID")
    if parse_utc(record["review_cutoff"], "review") <= parse_utc(current["decision_cutoff"], "current"):
        fail("RECURSIVE_REVIEW_CUTOFF_INVALID")
    if not isinstance(record["availability"], dict) or set(record["availability"]) != {"evidence", "company_effects", "market_context", "historical_analogue", "portfolio_context"} or any(value not in AVAILABLE for value in record["availability"].values()):
        fail("RECURSIVE_REVIEW_AVAILABILITY_INVALID")
    groups = [record["evidence_bindings"], record["company_effect_bindings"]]
    if any(not isinstance(group, list) or any(not binding(item) for item in group) for group in groups):
        fail("RECURSIVE_REVIEW_BINDING_ARRAY_INVALID")
    optional = [item for item in (record["market_binding"], record["analogue_binding"], record["portfolio_binding"]) if item is not None]
    if any(not binding(item) for item in optional):
        fail("RECURSIVE_REVIEW_OPTIONAL_BINDING_INVALID")
    expected_inputs = [record["current_thesis_binding"], *record["evidence_bindings"], *record["company_effect_bindings"], *optional]
    if record["direct_input_bindings"] != expected_inputs or len({(item["record_type"], item["record_id"], item["record_hash"]) for item in expected_inputs}) != len(expected_inputs):
        fail("RECURSIVE_REVIEW_DIRECT_INPUT_INVALID")
    for key, value in REVIEW_SAFETY.items():
        if record.get(key) != value:
            fail("RECURSIVE_REVIEW_SAFETY_INVALID")
    if record["review_snapshot_id"] != "S6THRECURIN_" + canonical_hash(without(record, "review_snapshot_id", "record_hash"))[:24] or record["record_hash"] != canonical_hash(without(record, "record_hash")):
        fail("RECURSIVE_REVIEW_HASH_INVALID")
    return record


def validate_structured(current, snapshot, invalidations, assertions):
    if not isinstance(invalidations, list) or len(invalidations) != len(current["invalidation_conditions"]) or not isinstance(assertions, list):
        fail("RECURSIVE_INVALIDATION_COVERAGE_INVALID")
    available = {(item["record_type"], item["record_id"], item["record_hash"]) for item in snapshot["direct_input_bindings"] if item["record_type"] in SUPPORT_TYPES}
    indices = []
    for item in invalidations:
        if not isinstance(item, dict) or set(item) != {"condition_index", "condition_text", "evaluation_status", "supporting_bindings"} or type(item["condition_index"]) is not int:
            fail("RECURSIVE_INVALIDATION_FIELDS_INVALID")
        index = item["condition_index"]
        indices.append(index)
        if index < 0 or index >= len(current["invalidation_conditions"]) or item["condition_text"] != current["invalidation_conditions"][index] or item["evaluation_status"] not in INVALIDATION_STATES:
            fail("RECURSIVE_INVALIDATION_INVALID")
        supports = item["supporting_bindings"]
        if not isinstance(supports, list) or any(not binding(value) or tuple(value[key] for key in ("record_type", "record_id", "record_hash")) not in available for value in supports):
            fail("RECURSIVE_INVALIDATION_SUPPORT_INVALID")
        if item["evaluation_status"] == "TRIGGERED" and not supports:
            fail("RECURSIVE_TRIGGER_SUPPORT_REQUIRED")
        if item["evaluation_status"] == "NOT_EVALUATED" and supports:
            fail("RECURSIVE_UNEVALUATED_SUPPORT_PROHIBITED")
    if sorted(indices) != list(range(len(current["invalidation_conditions"]))):
        fail("RECURSIVE_INVALIDATION_INDEX_INVALID")
    for item in assertions:
        if not isinstance(item, dict) or set(item) != {"assertion_id", "assessment", "reason_code", "supporting_bindings"} or item["assessment"] not in ASSERTION_STATES or item["reason_code"] not in REASON_CODES:
            fail("RECURSIVE_ASSERTION_INVALID")
        supports = item["supporting_bindings"]
        if not isinstance(supports, list) or not supports or any(not binding(value) or tuple(value[key] for key in ("record_type", "record_id", "record_hash")) not in available for value in supports):
            fail("RECURSIVE_ASSERTION_SUPPORT_INVALID")
        core = {"assessment": item["assessment"], "reason_code": item["reason_code"], "supporting_bindings": canonical_support(supports)}
        if item["assertion_id"] != "S6THRECURASSERT_" + canonical_hash(core)[:24]:
            fail("RECURSIVE_ASSERTION_ID_INVALID")
    return True


def validate_assessment(record, current, snapshot):
    if not isinstance(record, dict) or set(record) != ASSESSMENT_FIELDS:
        fail("RECURSIVE_ASSESSMENT_FIELDS_INVALID")
    identity = tuple(record.get(key) for key in ("schema_version", "decision_semantics", "processor_version", "policy_id", "policy_hash", "contract_version", "contract_hash", "semantic_code_commit", "authority"))
    expected = (ASSESSMENT_SCHEMA, SEMANTICS, PROCESSOR, POLICY_ID, EXPECTED_POLICY_HASH, CONTRACT_VERSION, EXPECTED_CONTRACT_HASH, SEMANTIC_COMMIT, AUTHORITY)
    if identity != expected:
        fail("RECURSIVE_ASSESSMENT_IDENTITY_INVALID")
    validate_review_snapshot(snapshot, current)
    validate_structured(current, snapshot, record["invalidation_assessments"], record["change_assertions"])
    expected_chain = (current_binding(current), {"record_type": REVIEW_SCHEMA, "record_id": snapshot["review_snapshot_id"], "record_hash": snapshot["record_hash"]}, current["thesis_id"], current["version"], current["version"] + 1, current["recommendation_id"], current["ticker"], current["decision_cutoff"], snapshot["review_cutoff"])
    actual_chain = tuple(record[key] for key in ("current_thesis_binding", "review_snapshot_binding", "thesis_id", "current_version", "next_proposed_version", "recommendation_id", "ticker", "prior_decision_cutoff", "review_cutoff"))
    if actual_chain != expected_chain:
        fail("RECURSIVE_ASSESSMENT_CHAIN_INVALID")
    wanted = decide(record["invalidation_assessments"], record["change_assertions"])
    if tuple(record[key] for key in ("material_change_status", "review_outcome", "target_thesis_status", "transition_reason_code")) != wanted:
        fail("RECURSIVE_ASSESSMENT_DECISION_INVALID")
    expected_status = "READY_FOR_MATERIALIZATION" if record["review_outcome"] == "DETERMINATE" else "WITHHELD_INDETERMINATE"
    if record["next_thesis_version_status"] != expected_status:
        fail("RECURSIVE_ASSESSMENT_READINESS_INVALID")
    supports = [value for item in [*record["invalidation_assessments"], *record["change_assertions"]] for value in item["supporting_bindings"]]
    if record["review_evidence_ids"] != sorted({item["record_id"] for item in supports if item["record_type"] == "STAGE6_EVIDENCE_V2"}):
        fail("RECURSIVE_ASSESSMENT_EVIDENCE_INVALID")
    for key, value in ASSESSMENT_SAFETY.items():
        if record.get(key) != value:
            fail("RECURSIVE_ASSESSMENT_SAFETY_INVALID")
    if record["assessment_id"] != "S6THRECURASS_" + canonical_hash(without(record, "assessment_id", "record_hash"))[:24] or record["record_hash"] != canonical_hash(without(record, "record_hash")):
        fail("RECURSIVE_ASSESSMENT_HASH_INVALID")
    return record
