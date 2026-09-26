"""Immutable deterministic literal-ruleset loading and validation."""
from __future__ import annotations

import json
from pathlib import Path

from stage6_events.event_validation import EVENT_TYPES
from stage6_ingestion.canonical import canonical_hash, canonical_json

from .errors import Stage6CandidateError


RULESET_SCHEMA_VERSION = "STAGE6_2C_RULESET_V1"
RULESET_VERSION = 1
RULESET_ID = "S6RULESET_STAGE6_2C_V1"
CLASSIFIER_VERSION = "STAGE6_2C_LITERAL_CLASSIFIER_V1"
CLASSIFICATION_METHOD = "DETERMINISTIC_LITERAL_RULES"
SUPPORTED_SOURCES = {"SEBI_OFFICIAL_RSS", "RBI_OFFICIAL_PRESS_RELEASES_RSS"}
RULESET_FIELDS = {"schema_version", "ruleset_id", "ruleset_version", "classifier_version",
                  "classification_method", "supported_sources", "rules"}
RULE_FIELDS = {"rule_id", "source_id", "candidate_event_type", "fields",
               "required_all_phrases", "required_any_phrases", "excluded_phrases"}
SEARCH_FIELDS = {"title_text", "description_text"}
DEFAULT_RULESET_PATH = Path(__file__).with_name("ruleset_v1.json")


def _unique_sorted_strings(value: object, field: str, *, allow_empty: bool = True) -> list[str]:
    if (not isinstance(value, list) or (not allow_empty and not value)
            or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value)) or value != sorted(value)):
        raise Stage6CandidateError(f"RULESET_LIST_INVALID:{field}")
    return value


def validate_ruleset(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict) or set(snapshot) != RULESET_FIELDS:
        raise Stage6CandidateError("RULESET_FIELDS_MISMATCH")
    if (snapshot["schema_version"] != RULESET_SCHEMA_VERSION or snapshot["ruleset_id"] != RULESET_ID
            or snapshot["ruleset_version"] != RULESET_VERSION
            or snapshot["classifier_version"] != CLASSIFIER_VERSION
            or snapshot["classification_method"] != CLASSIFICATION_METHOD):
        raise Stage6CandidateError("RULESET_IDENTITY_INVALID")
    sources = _unique_sorted_strings(snapshot["supported_sources"], "supported_sources", allow_empty=False)
    if set(sources) != SUPPORTED_SOURCES:
        raise Stage6CandidateError("RULESET_SUPPORTED_SOURCES_INVALID")
    rules = snapshot["rules"]
    if not isinstance(rules, list) or not rules:
        raise Stage6CandidateError("RULESET_RULES_REQUIRED")
    rule_ids = [rule.get("rule_id") if isinstance(rule, dict) else None for rule in rules]
    if (any(not isinstance(rule_id, str) or not rule_id for rule_id in rule_ids)
            or len(rule_ids) != len(set(rule_ids))):
        raise Stage6CandidateError("DUPLICATE_OR_INVALID_RULE_ID")
    if rule_ids != sorted(rule_ids):
        raise Stage6CandidateError("RULESET_ORDER_NONCANONICAL")
    seen: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != RULE_FIELDS:
            raise Stage6CandidateError("RULE_FIELDS_MISMATCH")
        rule_id = rule["rule_id"]
        if not isinstance(rule_id, str) or not rule_id or rule_id in seen:
            raise Stage6CandidateError("DUPLICATE_OR_INVALID_RULE_ID")
        seen.add(rule_id)
        if rule["source_id"] not in SUPPORTED_SOURCES:
            raise Stage6CandidateError("RULE_SOURCE_UNSUPPORTED")
        if rule["candidate_event_type"] not in EVENT_TYPES:
            raise Stage6CandidateError("RULE_EVENT_TYPE_UNSUPPORTED")
        fields = _unique_sorted_strings(rule["fields"], f"{rule_id}.fields", allow_empty=False)
        if not set(fields).issubset(SEARCH_FIELDS):
            raise Stage6CandidateError("RULE_SEARCH_FIELD_UNSUPPORTED")
        lists = []
        for name in ("required_all_phrases", "required_any_phrases", "excluded_phrases"):
            phrases = _unique_sorted_strings(rule[name], f"{rule_id}.{name}")
            if any(normalize_text(phrase) != phrase for phrase in phrases):
                raise Stage6CandidateError("RULE_PHRASE_NOT_CANONICAL")
            lists.extend(phrases)
        if len(lists) != len(set(lists)):
            raise Stage6CandidateError("RULE_PHRASE_DUPLICATED_ACROSS_LISTS")
        if not rule["required_all_phrases"] and not rule["required_any_phrases"]:
            raise Stage6CandidateError("RULE_POSITIVE_PHRASE_REQUIRED")
    return snapshot


def normalize_text(value: str | None) -> str:
    import unicodedata
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    separated = "".join(character if character.isalnum() else " " for character in normalized)
    return " ".join(separated.split())


def load_ruleset(path: Path = DEFAULT_RULESET_PATH) -> tuple[dict, str, str]:
    try:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage6CandidateError("RULESET_LOAD_FAILED") from exc
    validate_ruleset(snapshot)
    serialized = canonical_json(snapshot)
    return snapshot, serialized, canonical_hash(snapshot)
