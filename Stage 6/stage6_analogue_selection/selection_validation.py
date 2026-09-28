from stage6_ingestion.canonical import canonical_hash, without

from .errors import AnalogueSelectionIntegrityFailure
from .policy import AUTHORITY, COMPARISON_CONTRACT_VERSION, METRIC, POLICY_ID, PROCESSOR_VERSION, SCHEMA_VERSION
from .selection_builder import EXCLUSION_RULES, SAFETY, UNIVERSE_VERSION


def validate_selection_record(record):
    if record.get("schema_version") != SCHEMA_VERSION or record.get("authority") != AUTHORITY:
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_SCHEMA_INVALID")
    if (record.get("policy_id"), record.get("processor_version"), record.get("comparison_contract_version"), record.get("similarity_metric")) != (POLICY_ID, PROCESSOR_VERSION, COMPARISON_CONTRACT_VERSION, METRIC):
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_IDENTITY_INVALID")
    if record.get("candidate_universe_version") != UNIVERSE_VERSION or record.get("exclusion_rules") != list(EXCLUSION_RULES):
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_RULES_INVALID")
    bindings = record.get("candidate_bindings", [])
    if not bindings or bindings != sorted(bindings, key=lambda x: x["feature_snapshot_id"]):
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_UNIVERSE_INVALID")
    if record.get("candidate_universe_hash") != canonical_hash({"universe_version": UNIVERSE_VERSION, "bindings": bindings}):
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_UNIVERSE_HASH_INVALID")
    evaluations = record.get("candidate_evaluations", [])
    if [x["candidate_feature_snapshot_id"] for x in evaluations] != [x["feature_snapshot_id"] for x in bindings]:
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_EVALUATION_COVERAGE_INVALID")
    selected = record.get("selected_analogues", [])
    if record.get("analogue_count") != len(selected) or len(selected) > record.get("top_k", -1):
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_COUNT_INVALID")
    selected_ids = [x["analogue_id"] for x in selected]
    evaluation_selected = [x["candidate_feature_snapshot_id"] for x in evaluations if x["selected"]]
    if set(selected_ids) != set(evaluation_selected) or record["target_feature_snapshot_id"] in selected_ids:
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_SELECTED_SUBSET_INVALID")
    ranked = sorted((x for x in evaluations if x["selected"]), key=lambda x: (x["distance"], x["candidate_feature_snapshot_id"]))
    if selected_ids != [x["candidate_feature_snapshot_id"] for x in ranked]:
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_ORDER_INVALID")
    if any(record.get(key) != value for key, value in SAFETY.items()) or record.get("pit_verified") is not True:
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_SAFETY_INVALID")
    result_hash = canonical_hash(without(record, "selection_record_id", "record_hash"))
    if record.get("selection_record_id") != "S6ANSEL_" + result_hash[:24]:
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_ID_INVALID")
    if record.get("record_hash") != canonical_hash(without(record, "record_hash")):
        raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_RECORD_HASH_INVALID")
    return record
