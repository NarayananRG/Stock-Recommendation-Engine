"""Runtime validation for STAGE6_RSS_ITEM_V1."""
from __future__ import annotations

import re

from stage6_ingestion.canonical import canonical_hash, parse_utc, utc_timestamp, without

from .errors import ExtractionIntegrityFailure, Stage6ExtractionError
from .extraction_builder import EXTRACTION_SCHEMA_VERSION, extraction_identity
from .rss_item_parser import PARSER_VERSION


HASH = re.compile(r"^[a-f0-9]{64}$")
FIELDS = {
    "schema_version", "parser_version", "extraction_id", "record_hash", "parent_evidence_id",
    "parent_evidence_hash", "parent_record_type", "source_id", "item_ordinal",
    "structural_locator", "item_identifier_type", "item_identifier_value", "title_text",
    "description_text", "link_value", "guid_or_atom_id", "publication_timestamp_utc",
    "timestamp_status", "field_hashes", "item_fingerprint", "parent_retrieved_timestamp_utc",
    "extracted_at_cutoff",
}
NULLABLE_TEXT = ("title_text", "description_text", "link_value", "guid_or_atom_id")


def validate_extraction_record(record: dict, *, verify_hash: bool = True) -> dict:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise Stage6ExtractionError("EXTRACTION_FIELDS_MISMATCH")
    if record["schema_version"] != EXTRACTION_SCHEMA_VERSION or record["parser_version"] != PARSER_VERSION:
        raise Stage6ExtractionError("EXTRACTION_SCHEMA_OR_PARSER_INVALID")
    for field in ("extraction_id", "parent_evidence_id", "source_id", "structural_locator",
                  "item_identifier_value"):
        if not isinstance(record[field], str) or not record[field]:
            raise Stage6ExtractionError(f"EXTRACTION_STRING_INVALID:{field}")
    if record["parent_record_type"] != "EVIDENCE":
        raise Stage6ExtractionError("EXTRACTION_PARENT_TYPE_INVALID")
    for field in ("record_hash", "parent_evidence_hash", "item_fingerprint"):
        if not isinstance(record[field], str) or not HASH.fullmatch(record[field]):
            raise Stage6ExtractionError(f"EXTRACTION_HASH_INVALID:{field}")
    if type(record["item_ordinal"]) is not int or record["item_ordinal"] < 0:
        raise Stage6ExtractionError("EXTRACTION_ORDINAL_INVALID")
    if record["item_identifier_type"] not in {"GUID", "ATOM_ID", "LINK", "STRUCTURAL_LOCATOR"}:
        raise Stage6ExtractionError("EXTRACTION_IDENTIFIER_TYPE_INVALID")
    for field in NULLABLE_TEXT:
        if record[field] is not None and not isinstance(record[field], str):
            raise Stage6ExtractionError(f"EXTRACTION_TEXT_INVALID:{field}")
    if record["timestamp_status"] not in {"VALID", "MISSING", "INVALID_OR_AMBIGUOUS"}:
        raise Stage6ExtractionError("EXTRACTION_TIMESTAMP_STATUS_INVALID")
    publication = record["publication_timestamp_utc"]
    if publication is not None:
        if utc_timestamp(publication, "publication_timestamp_utc") != publication or record["timestamp_status"] != "VALID":
            raise Stage6ExtractionError("EXTRACTION_PUBLICATION_TIMESTAMP_INVALID")
    elif record["timestamp_status"] == "VALID":
        raise Stage6ExtractionError("EXTRACTION_TIMESTAMP_STATUS_INVALID")
    for field in ("parent_retrieved_timestamp_utc", "extracted_at_cutoff"):
        if utc_timestamp(record[field], field) != record[field]:
            raise Stage6ExtractionError(f"EXTRACTION_TIMESTAMP_INVALID:{field}")
    if parse_utc(record["parent_retrieved_timestamp_utc"], "parent_retrieved") > parse_utc(record["extracted_at_cutoff"], "cutoff"):
        raise Stage6ExtractionError("EXTRACTION_PIT_CUTOFF_FAILED")
    if not isinstance(record["field_hashes"], dict) or set(record["field_hashes"]) != set(NULLABLE_TEXT):
        raise Stage6ExtractionError("EXTRACTION_FIELD_HASHES_INVALID")
    for field in NULLABLE_TEXT:
        if record["field_hashes"].get(field) != canonical_hash(record[field]):
            raise ExtractionIntegrityFailure("EXTRACTION_FIELD_HASH_MISMATCH")
    fingerprint = canonical_hash({name: record[name] for name in (
        "structural_locator", "item_identifier_type", "item_identifier_value", "title_text",
        "description_text", "link_value", "guid_or_atom_id", "publication_timestamp_utc", "timestamp_status")})
    if record["item_fingerprint"] != fingerprint:
        raise ExtractionIntegrityFailure("ITEM_FINGERPRINT_MISMATCH")
    expected_id = extraction_identity(record["parent_evidence_id"], record["parent_evidence_hash"],
                                      record["structural_locator"], record["parser_version"])
    if record["extraction_id"] != expected_id:
        raise ExtractionIntegrityFailure("EXTRACTION_IDENTITY_MISMATCH")
    if verify_hash and record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise ExtractionIntegrityFailure("EXTRACTION_RECORD_HASH_MISMATCH")
    return record
