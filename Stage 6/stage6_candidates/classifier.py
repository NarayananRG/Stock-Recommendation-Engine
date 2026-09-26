"""Pure deterministic literal token-sequence candidate classifier."""
from __future__ import annotations

from stage6_ingestion.canonical import canonical_hash

from .ruleset import normalize_text, validate_ruleset


def _contains_phrase(text: str, phrase: str) -> bool:
    haystack, needle = text.split(), phrase.split()
    if not needle or len(needle) > len(haystack):
        return False
    return any(haystack[index:index + len(needle)] == needle
               for index in range(len(haystack) - len(needle) + 1))


def classify_extraction(extraction: dict, ruleset: dict) -> dict:
    validate_ruleset(ruleset)
    normalized = {
        "title_text": normalize_text(extraction.get("title_text")),
        "description_text": normalize_text(extraction.get("description_text")),
    }
    traces = []
    for rule in ruleset["rules"]:
        if rule["source_id"] != extraction["source_id"]:
            continue
        phrase_fields: dict[str, list[str]] = {}
        for phrase in (rule["required_all_phrases"] + rule["required_any_phrases"] + rule["excluded_phrases"]):
            phrase_fields[phrase] = sorted(field for field in rule["fields"]
                                                   if _contains_phrase(normalized[field], phrase))
        if any(not phrase_fields[phrase] for phrase in rule["required_all_phrases"]):
            continue
        if rule["required_any_phrases"] and not any(phrase_fields[p] for p in rule["required_any_phrases"]):
            continue
        if any(phrase_fields[phrase] for phrase in rule["excluded_phrases"]):
            continue
        positive = sorted(set(rule["required_all_phrases"] + rule["required_any_phrases"]))
        matches = [{"phrase": phrase, "fields": phrase_fields[phrase]}
                   for phrase in positive if phrase_fields[phrase]]
        traces.append({"rule_id": rule["rule_id"], "candidate_event_type": rule["candidate_event_type"],
                       "phrase_matches": matches})
    traces.sort(key=lambda item: item["rule_id"])
    types = sorted({trace["candidate_event_type"] for trace in traces})
    if not traces:
        status, candidate_type, ambiguous = "NO_MATCH", None, []
    elif len(types) == 1:
        status, candidate_type, ambiguous = "MATCHED", types[0], []
    else:
        status, candidate_type, ambiguous = "AMBIGUOUS", None, types
    return {
        "classification_status": status,
        "candidate_event_type": candidate_type,
        "ambiguous_event_types": ambiguous,
        "matched_rule_ids": [trace["rule_id"] for trace in traces],
        "match_traces": traces,
        "normalized_title_hash": canonical_hash(normalized["title_text"]),
        "normalized_description_hash": canonical_hash(normalized["description_text"]),
    }
