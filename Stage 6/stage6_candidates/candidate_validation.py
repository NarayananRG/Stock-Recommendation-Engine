"""Runtime invariants for STAGE6_EVENT_CANDIDATE_V1."""
from __future__ import annotations

import re

from stage6_events.event_validation import EVENT_TYPES
from stage6_ingestion.canonical import canonical_hash, utc_timestamp, without

from .candidate_builder import CANDIDATE_SCHEMA_VERSION, candidate_identity
from .errors import CandidateIntegrityFailure, Stage6CandidateError
from .ruleset import CLASSIFICATION_METHOD, CLASSIFIER_VERSION


HASH = re.compile(r"^[a-f0-9]{64}$")
FIELDS = {
    "schema_version", "candidate_id", "record_hash", "input_extraction_id",
    "input_extraction_hash", "input_record_type", "source_id", "classifier_version",
    "ruleset_id", "ruleset_version", "ruleset_hash", "classification_method",
    "classification_status", "candidate_event_type", "ambiguous_event_types",
    "matched_rule_ids", "match_traces", "normalized_title_hash",
    "normalized_description_hash", "input_available_at_utc",
    "upstream_parent_evidence_id", "upstream_parent_evidence_hash",
}


def _sorted_unique_strings(value: object, field: str) -> list[str]:
    if (not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value)) or value != sorted(value)):
        raise Stage6CandidateError(f"CANDIDATE_LIST_INVALID:{field}")
    return value


def validate_candidate(record: dict, ruleset: dict, *, verify_hash: bool = True) -> dict:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise Stage6CandidateError("CANDIDATE_FIELDS_MISMATCH")
    if (record["schema_version"] != CANDIDATE_SCHEMA_VERSION
            or record["classifier_version"] != CLASSIFIER_VERSION
            or record["classification_method"] != CLASSIFICATION_METHOD):
        raise Stage6CandidateError("CANDIDATE_IDENTITY_FIELDS_INVALID")
    for field in ("candidate_id", "input_extraction_id", "source_id", "ruleset_id",
                  "upstream_parent_evidence_id"):
        if not isinstance(record[field], str) or not record[field]:
            raise Stage6CandidateError(f"CANDIDATE_STRING_INVALID:{field}")
    if record["input_record_type"] != "RSS_ITEM_EXTRACTION":
        raise Stage6CandidateError("CANDIDATE_INPUT_TYPE_INVALID")
    if type(record["ruleset_version"]) is not int or record["ruleset_version"] < 1:
        raise Stage6CandidateError("CANDIDATE_RULESET_VERSION_INVALID")
    for field in ("record_hash", "input_extraction_hash", "ruleset_hash", "normalized_title_hash",
                  "normalized_description_hash", "upstream_parent_evidence_hash"):
        if not isinstance(record[field], str) or not HASH.fullmatch(record[field]):
            raise Stage6CandidateError(f"CANDIDATE_HASH_INVALID:{field}")
    if utc_timestamp(record["input_available_at_utc"], "input_available_at_utc") != record["input_available_at_utc"]:
        raise Stage6CandidateError("CANDIDATE_AVAILABILITY_TIMESTAMP_INVALID")
    matched = _sorted_unique_strings(record["matched_rule_ids"], "matched_rule_ids")
    ambiguous = _sorted_unique_strings(record["ambiguous_event_types"], "ambiguous_event_types")
    if any(value not in EVENT_TYPES for value in ambiguous):
        raise Stage6CandidateError("CANDIDATE_AMBIGUOUS_TYPE_INVALID")
    traces = record["match_traces"]
    if not isinstance(traces, list) or [item.get("rule_id") for item in traces] != matched:
        raise Stage6CandidateError("CANDIDATE_TRACE_ORDER_OR_COVERAGE_INVALID")
    rules = {rule["rule_id"]: rule for rule in ruleset["rules"]}
    matched_types = []
    for trace in traces:
        if not isinstance(trace, dict) or set(trace) != {"rule_id", "candidate_event_type", "phrase_matches"}:
            raise Stage6CandidateError("CANDIDATE_TRACE_FIELDS_INVALID")
        rule = rules.get(trace["rule_id"])
        if rule is None or trace["candidate_event_type"] != rule["candidate_event_type"] or record["source_id"] != rule["source_id"]:
            raise Stage6CandidateError("CANDIDATE_TRACE_RULE_MISMATCH")
        phrases = trace["phrase_matches"]
        if not isinstance(phrases, list) or [item.get("phrase") for item in phrases] != sorted(item.get("phrase", "") for item in phrases):
            raise Stage6CandidateError("CANDIDATE_PHRASE_TRACE_ORDER_INVALID")
        for item in phrases:
            if not isinstance(item, dict) or set(item) != {"phrase", "fields"}:
                raise Stage6CandidateError("CANDIDATE_PHRASE_TRACE_INVALID")
            _sorted_unique_strings(item["fields"], "trace.fields")
            if item["phrase"] not in rule["required_all_phrases"] + rule["required_any_phrases"]:
                raise Stage6CandidateError("CANDIDATE_TRACE_PHRASE_UNKNOWN")
        matched_types.append(rule["candidate_event_type"])
    status, event_type = record["classification_status"], record["candidate_event_type"]
    distinct_types = sorted(set(matched_types))
    if status == "MATCHED":
        if not matched or len(distinct_types) != 1 or event_type != distinct_types[0] or ambiguous:
            raise Stage6CandidateError("CANDIDATE_MATCHED_INVARIANT_FAILED")
    elif status == "NO_MATCH":
        if event_type is not None or ambiguous or matched or traces:
            raise Stage6CandidateError("CANDIDATE_NO_MATCH_INVARIANT_FAILED")
    elif status == "AMBIGUOUS":
        if event_type is not None or len(distinct_types) < 2 or ambiguous != distinct_types or not matched:
            raise Stage6CandidateError("CANDIDATE_AMBIGUOUS_INVARIANT_FAILED")
    else:
        raise Stage6CandidateError("CANDIDATE_STATUS_INVALID")
    pseudo_extraction = {"extraction_id": record["input_extraction_id"], "record_hash": record["input_extraction_hash"]}
    if record["candidate_id"] != candidate_identity(pseudo_extraction, record["ruleset_hash"]):
        raise CandidateIntegrityFailure("CANDIDATE_IDENTITY_MISMATCH")
    if verify_hash and record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise CandidateIntegrityFailure("CANDIDATE_RECORD_HASH_MISMATCH")
    return record
