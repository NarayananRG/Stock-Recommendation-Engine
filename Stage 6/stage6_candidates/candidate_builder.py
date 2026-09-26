"""Build immutable candidate records from extraction plus ruleset."""
from __future__ import annotations

from stage6_ingestion.canonical import canonical_hash, without

from .classifier import classify_extraction
from .ruleset import CLASSIFICATION_METHOD, CLASSIFIER_VERSION


CANDIDATE_SCHEMA_VERSION = "STAGE6_EVENT_CANDIDATE_V1"


def candidate_identity(extraction: dict, ruleset_hash: str) -> str:
    return "S6CAND_" + canonical_hash({
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "input_extraction_id": extraction["extraction_id"],
        "input_extraction_hash": extraction["record_hash"],
        "classifier_version": CLASSIFIER_VERSION,
        "ruleset_hash": ruleset_hash,
    })[:24]


def build_candidate(extraction: dict, ruleset: dict, ruleset_hash: str) -> dict:
    result = classify_extraction(extraction, ruleset)
    record = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "candidate_id": candidate_identity(extraction, ruleset_hash),
        "record_hash": "0" * 64,
        "input_extraction_id": extraction["extraction_id"],
        "input_extraction_hash": extraction["record_hash"],
        "input_record_type": "RSS_ITEM_EXTRACTION",
        "source_id": extraction["source_id"],
        "classifier_version": CLASSIFIER_VERSION,
        "ruleset_id": ruleset["ruleset_id"],
        "ruleset_version": ruleset["ruleset_version"],
        "ruleset_hash": ruleset_hash,
        "classification_method": CLASSIFICATION_METHOD,
        **result,
        "input_available_at_utc": extraction["extracted_at_cutoff"],
        "upstream_parent_evidence_id": extraction["parent_evidence_id"],
        "upstream_parent_evidence_hash": extraction["parent_evidence_hash"],
    }
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record


def classification_batch_identity(*, extraction_batch_id: str, extraction_batch_identity_hash: str,
                                  ruleset_id: str, ruleset_hash: str,
                                  classification_cutoff: str) -> tuple[str, str]:
    identity = canonical_hash({
        "extraction_batch_id": extraction_batch_id,
        "extraction_batch_identity_hash": extraction_batch_identity_hash,
        "ruleset_id": ruleset_id,
        "ruleset_hash": ruleset_hash,
        "classifier_version": CLASSIFIER_VERSION,
        "classification_cutoff": classification_cutoff,
    })
    return "S6CBATCH_" + identity[:24], identity
