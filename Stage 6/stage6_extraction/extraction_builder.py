"""Build deterministic immutable derived-item records."""
from __future__ import annotations

from stage6_ingestion.canonical import canonical_hash, utc_timestamp, without

from .rss_item_parser import PARSER_VERSION


EXTRACTION_SCHEMA_VERSION = "STAGE6_RSS_ITEM_V1"


def batch_identity(parent_evidence_id: str, parent_evidence_hash: str, cutoff: str,
                   parser_version: str = PARSER_VERSION) -> tuple[str, str]:
    identity = canonical_hash({
        "parent_evidence_id": parent_evidence_id, "parent_evidence_hash": parent_evidence_hash,
        "extraction_cutoff": utc_timestamp(cutoff, "extraction_cutoff"), "parser_version": parser_version,
    })
    return "S6XBATCH_" + identity[:24], identity


def extraction_identity(parent_evidence_id: str, parent_evidence_hash: str,
                        locator: str, parser_version: str = PARSER_VERSION) -> str:
    return "S6XITEM_" + canonical_hash({
        "schema_version": EXTRACTION_SCHEMA_VERSION, "parser_version": parser_version,
        "parent_evidence_id": parent_evidence_id, "parent_evidence_hash": parent_evidence_hash,
        "structural_locator": locator,
    })[:24]


def build_extraction_record(*, parsed_item: dict, parent: dict, cutoff: str,
                            parser_version: str = PARSER_VERSION) -> dict:
    fields = {name: canonical_hash(parsed_item[name]) for name in
              ("title_text", "description_text", "link_value", "guid_or_atom_id")}
    fingerprint_fields = {name: parsed_item[name] for name in (
        "structural_locator", "item_identifier_type", "item_identifier_value", "title_text",
        "description_text", "link_value", "guid_or_atom_id", "publication_timestamp_utc",
        "timestamp_status")}
    record = {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "parser_version": parser_version,
        "extraction_id": extraction_identity(parent["evidence_id"], parent["record_hash"],
                                             parsed_item["structural_locator"], parser_version),
        "record_hash": "0" * 64,
        "parent_evidence_id": parent["evidence_id"],
        "parent_evidence_hash": parent["record_hash"],
        "parent_record_type": "EVIDENCE",
        "source_id": parent["source_id"],
        **parsed_item,
        "field_hashes": fields,
        "item_fingerprint": canonical_hash(fingerprint_fields),
        "parent_retrieved_timestamp_utc": parent["retrieved_timestamp_utc"],
        "extracted_at_cutoff": utc_timestamp(cutoff, "extraction_cutoff"),
    }
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
