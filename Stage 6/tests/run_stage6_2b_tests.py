"""Stage 6.2B immutable RSS/Atom extraction acceptance tests."""
from __future__ import annotations

import ast
import csv
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock


STAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE_ROOT.parent
sys.path.insert(0, str(STAGE_ROOT))

from stage6_connectors.live_registries import (RBI_ENTITY_ID, RBI_SOURCE_ID, SEBI_ENTITY_ID,
                                               SEBI_SOURCE_ID, build_multisource_registries)
from stage6_events import EventStore
from stage6_extraction import (AUTHORITY, EXTRACTION_SCHEMA_VERSION, PARSER_VERSION,
                               SUPPORTED_SOURCES, ExtractionConflict,
                               ExtractionIntegrityFailure, ExtractionStore,
                               Stage6ExtractionError, batch_identity,
                               extraction_identity, parse_feed_items)
from stage6_extraction.rss_item_parser import (MAX_FEED_ITEMS, MAX_TEXT_FIELD_CHARS,
                                               MAX_TOTAL_EXTRACTED_CHARS)
from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from stage6_ingestion.evidence_store import IngestionStore
from stage6_ingestion.registry import build_source_registry


FIXTURES = STAGE_ROOT / "fixtures" / "stage6_2b"
RESULT_PATH = STAGE_ROOT / "results" / "stage6_2b_test_results.csv"
BASELINE_2A_TAG = "stage6-2a-event-intelligence-foundation-baseline"
BASELINE_2A_COMMIT = "850809db87b2d63380c532404ca8922bc8807a7b"
BASELINE_1C_TAG = "stage6-1c-multisource-rss-ingestion-baseline"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
CUTOFF = "2026-09-26T08:00:01.000000Z"
OBSERVED = "2026-09-26T08:00:00Z"
RETRIEVED = "2026-09-26T08:00:01Z"
RSS = (FIXTURES / "rss_multiple.xml").read_bytes()
ATOM = (FIXTURES / "atom_multiple.xml").read_bytes()
CHECKS: list[tuple[str, str, object]] = []


def check(category: str, name: str):
    def register(function):
        CHECKS.append((category, name, function)); return function
    return register


def require(value: object, message: str = "assertion failed") -> None:
    if not value: raise AssertionError(message)


def expect(error: type[BaseException], function, contains: str | None = None) -> BaseException:
    try: function()
    except error as exc:
        if contains: require(contains in str(exc), f"expected {contains!r} in {exc!r}")
        return exc
    raise AssertionError(f"expected {error.__name__}")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def capture(store: IngestionStore, registries: dict, *, key: str, source_id: str, payload: bytes,
            status: str = "RETRIEVED", retrieved: str = RETRIEVED, source_registry: dict | None = None) -> dict:
    entity = SEBI_ENTITY_ID if source_id == SEBI_SOURCE_ID else RBI_ENTITY_ID
    return store.capture_evidence(
        idempotency_key=key,
        source_registry_snapshot_id=(source_registry or registries["source_v2"])["registry_snapshot_id"],
        entity_registry_snapshot_id=registries["entity_v2"]["registry_snapshot_id"],
        source_id=source_id, source_reference=f"fixture://stage6-2b/{key}", raw_payload=payload,
        content_type="application/rss+xml", publication_timestamp_utc="2026-09-25T04:30:00Z",
        observed_timestamp_utc=OBSERVED, retrieved_timestamp_utc=retrieved,
        entity_ids=[entity], retrieval_status=status)["record"]


@contextmanager
def fresh_environment():
    with tempfile.TemporaryDirectory(prefix="stage6_2b_test_") as folder:
        root = Path(folder); registries = build_multisource_registries()
        ingestion = IngestionStore(root / "ingestion.sqlite3", root / "raw")
        ingestion.import_registry(registries["entity_v1"]); ingestion.import_registry(registries["source_v1"])
        ingestion.import_registry(registries["entity_v2"]); ingestion.import_registry(registries["source_v2"])
        evidence = {
            "sebi": capture(ingestion, registries, key="sebi", source_id=SEBI_SOURCE_ID, payload=RSS),
            "rbi": capture(ingestion, registries, key="rbi", source_id=RBI_SOURCE_ID, payload=ATOM),
            "quarantined": capture(ingestion, registries, key="quarantined", source_id=SEBI_SOURCE_ID, payload=RSS, status="QUARANTINED"),
            "partial": capture(ingestion, registries, key="partial", source_id=RBI_SOURCE_ID, payload=ATOM, status="PARTIAL"),
        }
        evidence["attempt"] = ingestion.capture_acquisition_failure(
            idempotency_key="stage6-2b-attempt", source_registry_snapshot_id=registries["source_v2"]["registry_snapshot_id"],
            entity_registry_snapshot_id=registries["entity_v2"]["registry_snapshot_id"], source_id=RBI_SOURCE_ID,
            source_reference="fixture://stage6-2b/attempt", retrieval_status="FAILED", failure_reason="synthetic",
            failure_stage="FIXTURE", attempted_at_utc=RETRIEVED, entity_ids=[RBI_ENTITY_ID])["record"]
        sources = deepcopy(registries["source_v2"]["sources"])
        unknown = deepcopy(next(item for item in sources if item["source_id"] == RBI_SOURCE_ID))
        unknown.update(source_id="S6FIX_UNKNOWN_RSS", source_name="Synthetic Unknown RSS", source_record_version=1,
                       previous_version_hash=None, effective_from="2026-09-26T06:50:00Z", reviewed_at_utc="2026-09-26T06:50:00Z")
        unknown.pop("record_hash", None); sources.append(unknown)
        source_v3 = build_source_registry(sources, "2026-09-26T07:00:00Z", registries["source_v2"])
        ingestion.import_registry(source_v3)
        evidence["unknown"] = capture(ingestion, registries, key="unknown", source_id="S6FIX_UNKNOWN_RSS",
                                              payload=RSS, source_registry=source_v3)
        extraction = ExtractionStore(root / "extraction.sqlite3", ingestion)
        try: yield ingestion, extraction, evidence, registries, root
        finally:
            try: extraction.close()
            except sqlite3.Error: pass
            ingestion.close()


def extract(store: ExtractionStore, record: dict, cutoff: str = CUTOFF) -> dict:
    return store.extract(parent_evidence_id=record["evidence_id"], extraction_cutoff=cutoff)


def restore_trigger(store: ExtractionStore, table: str, operation: str) -> None:
    name = f"protect_{table}_{operation.lower()}"
    store.connection.executescript(f"""
    CREATE TRIGGER {name} BEFORE {operation} ON {table}
    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_{operation}'); END;
    """)


# Baselines.
@check("BASELINE", "Stage 6.2A tag exact ancestor")
def _():
    require(git("rev-parse", f"{BASELINE_2A_TAG}^{{}}") == BASELINE_2A_COMMIT)
    subprocess.check_call(["git", "merge-base", "--is-ancestor", BASELINE_2A_COMMIT, "HEAD"], cwd=REPO_ROOT)

@check("BASELINE", "authority remains SHADOW_ONLY")
def _(): require(AUTHORITY == "SHADOW_ONLY")


# Input acceptance and rejection.
@check("INPUT", "valid retrieved SEBI evidence accepted")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(len(extract(store, evidence["sebi"])["records"]) == 4)

@check("INPUT", "valid retrieved RBI evidence accepted")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(len(extract(store, evidence["rbi"])["records"]) == 3)

@check("INPUT", "missing evidence rejected")
def _():
    with fresh_environment() as (_, store, _, _, _): expect(ExtractionIntegrityFailure, lambda: store.extract(parent_evidence_id="S6EV_MISSING", extraction_cutoff=CUTOFF), "PARENT_EVIDENCE_MISSING")

for name, message in [("attempt", "PARENT_MUST_BE_EVIDENCE"), ("quarantined", "PARENT_MUST_BE_RETRIEVED"),
                      ("partial", "PARENT_MUST_BE_RETRIEVED"), ("unknown", "UNSUPPORTED_EXTRACTION_SOURCE")]:
    def make_input_test(item=name, contains=message):
        @check("INPUT", f"{item} parent rejected")
        def _test():
            with fresh_environment() as (_, store, evidence, _, _):
                expect(Stage6ExtractionError, lambda: extract(store, evidence[item]), contains)
        return _test
    make_input_test()

@check("INPUT", "tampered evidence rejected")
def _():
    with fresh_environment() as (ingestion, store, evidence, _, _):
        ingestion.connection.execute("DROP TRIGGER protect_ingestion_records_update")
        ingestion.connection.execute("UPDATE ingestion_records SET record_hash=? WHERE record_id=?", ("a" * 64, evidence["sebi"]["evidence_id"])); ingestion.connection.commit()
        expect(ExtractionIntegrityFailure, lambda: extract(store, evidence["sebi"]), "UPSTREAM_INGESTION")

@check("INPUT", "missing raw object rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        store.ingestion_store.raw_store.path_for(evidence["sebi"]["raw_payload_hash"]).unlink()
        expect(ExtractionIntegrityFailure, lambda: extract(store, evidence["sebi"]), "UPSTREAM_INGESTION")

@check("INPUT", "raw hash mismatch rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        store.ingestion_store.raw_store.path_for(evidence["sebi"]["raw_payload_hash"]).write_bytes(b"tampered")
        expect(ExtractionIntegrityFailure, lambda: extract(store, evidence["sebi"]), "UPSTREAM_INGESTION")


# XML, RSS, Atom, timestamps.
for fixture, message in [("dtd_entity.xml", "UNSAFE_XML"), ("malformed.xml", "MALFORMED_XML"),
                         ("unsupported_root.xml", "UNSUPPORTED_FEED_ROOT")]:
    def make_xml_test(file=fixture, contains=message):
        @check("XML_SECURITY", f"{file} rejected")
        def _test(): expect(Stage6ExtractionError, lambda: parse_feed_items((FIXTURES / file).read_bytes()), contains)
        return _test
    make_xml_test()

@check("XML_SECURITY", "external entity resolver is unavailable and never called")
def _():
    with mock.patch.object(socket, "socket", side_effect=AssertionError("NETWORK_USED")):
        expect(Stage6ExtractionError, lambda: parse_feed_items((FIXTURES / "dtd_entity.xml").read_bytes()), "UNSAFE_XML")

@check("RSS", "RSS fields and zero-based locators deterministic")
def _():
    items = parse_feed_items(RSS); first = items[0]
    require(first["structural_locator"] == "/rss/channel/item[0]")
    require(first["title_text"] == "Repeated synthetic title" and first["description_text"] == "<p>Escaped HTML remains inert.</p>")
    require(first["link_value"] == "https://invalid.example/item-one" and first["guid_or_atom_id"] == "duplicate-guid")

@check("RSS", "RSS timestamp canonicalized")
def _(): require(parse_feed_items(RSS)[0]["publication_timestamp_utc"] == "2026-09-25T04:31:00.000000Z")

@check("RSS", "RSS missing optional fields preserved as null")
def _():
    item = parse_feed_items(RSS)[3]
    require(item["title_text"] is None and item["link_value"] is None and item["guid_or_atom_id"] is None and item["publication_timestamp_utc"] is None)

@check("ATOM", "Atom namespace fields and alternate link deterministic")
def _():
    first = parse_feed_items(ATOM)[0]
    require(first["structural_locator"] == "/feed/entry[0]" and first["title_text"] == "Atom nested title")
    require(first["description_text"] == "Publisher summary text." and first["link_value"] == "https://invalid.example/atom-one")
    require(first["guid_or_atom_id"] == "atom-id-one")

@check("ATOM", "Atom content and updated fallbacks")
def _():
    second = parse_feed_items(ATOM)[1]
    require(second["description_text"] == "<strong>Escaped atom content stays inert.</strong>")
    require(second["publication_timestamp_utc"] == "2026-09-25T05:02:00.000000Z")

@check("TIMESTAMPS", "timezone-less timestamp is not invented")
def _():
    rss, atom = parse_feed_items(RSS)[2], parse_feed_items(ATOM)[2]
    require(rss["publication_timestamp_utc"] is None and rss["timestamp_status"] == "INVALID_OR_AMBIGUOUS")
    require(atom["publication_timestamp_utc"] is None and atom["timestamp_status"] == "INVALID_OR_AMBIGUOUS")

@check("TIMESTAMPS", "feed-level timestamp never copied to item")
def _(): require(parse_feed_items(RSS)[3]["publication_timestamp_utc"] is None)


# Identity, provenance, PIT, text and links.
@check("IDENTITY", "extraction ID deterministic for same parent and locator")
def _(): require(extraction_identity("P", "a" * 64, "/rss/channel/item[0]") == extraction_identity("P", "a" * 64, "/rss/channel/item[0]"))

@check("IDENTITY", "different locator creates different ID")
def _(): require(extraction_identity("P", "a" * 64, "/rss/channel/item[0]") != extraction_identity("P", "a" * 64, "/rss/channel/item[1]"))

@check("IDENTITY", "different parent creates different ID")
def _(): require(extraction_identity("P1", "a" * 64, "/rss/channel/item[0]") != extraction_identity("P2", "b" * 64, "/rss/channel/item[0]"))

@check("IDENTITY", "duplicate titles remain distinct by locator")
def _():
    items = parse_feed_items(RSS); require(items[0]["title_text"] == items[1]["title_text"] and items[0]["structural_locator"] != items[1]["structural_locator"])

@check("IDENTITY", "duplicate GUIDs remain distinct by locator")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        records = extract(store, evidence["sebi"])["records"]
        require(records[0]["guid_or_atom_id"] == records[1]["guid_or_atom_id"] and records[0]["extraction_id"] != records[1]["extraction_id"])

@check("PROVENANCE", "exact parent ID hash and type dependency")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        record = extract(store, evidence["sebi"])["records"][0]
        dep = store.connection.execute("SELECT * FROM extraction_dependencies WHERE extraction_id=?", (record["extraction_id"],)).fetchone()
        require((dep["dependency_record_id"], dep["dependency_record_hash"], dep["dependency_record_type"]) ==
                (evidence["sebi"]["evidence_id"], evidence["sebi"]["record_hash"], "EVIDENCE"))

@check("PROVENANCE", "parent availability timestamp preserved")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(extract(store, evidence["sebi"])["records"][0]["parent_retrieved_timestamp_utc"] == evidence["sebi"]["retrieved_timestamp_utc"])

@check("PIT", "parent retrieved equal cutoff accepted")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(extract(store, evidence["sebi"])["status"] == "CREATED")

@check("PIT", "future parent evidence rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _): expect(Stage6ExtractionError, lambda: extract(store, evidence["sebi"], "2026-09-26T08:00:00Z"), "FUTURE_EVIDENCE")

@check("PIT", "publisher timestamp does not replace availability")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        record = extract(store, evidence["sebi"])["records"][0]
        require(record["publication_timestamp_utc"] != record["parent_retrieved_timestamp_utc"])

@check("TEXT", "nested and escaped text remains deterministic and inert")
def _():
    one = parse_feed_items(RSS)[0]; two = parse_feed_items(RSS)[0]
    require(one == two and one["title_text"] == "Repeated synthetic title" and "<p>" in one["description_text"])

@check("TEXT", "no NLP normalization translation or summarization")
def _():
    text = parse_feed_items(ATOM)[1]["description_text"]
    require(text == "<strong>Escaped atom content stays inert.</strong>")

@check("TEXT", "field hashes deterministic")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        record = extract(store, evidence["sebi"])["records"][0]
        require(record["field_hashes"]["title_text"] == canonical_hash(record["title_text"]))

@check("LINKS", "links and invalid-looking URLs persist without fetch")
def _():
    rss = parse_feed_items(RSS); atom = parse_feed_items(ATOM)
    require(rss[1]["link_value"] == "not-a-fetchable-url" and atom[2]["link_value"] == "not-a-network-request")

@check("LINKS", "enclosures ignored and never fetched")
def _(): require("never-fetch" not in canonical_json(parse_feed_items(RSS)) and "never-fetch" not in canonical_json(parse_feed_items(ATOM)))


# Limits and idempotency.
def rss_items(count: int, title_size: int = 1, description_size: int = 0) -> bytes:
    item = f"<item><title>{'T' * title_size}</title><description>{'D' * description_size}</description></item>"
    return f"<rss><channel>{item * count}</channel></rss>".encode()

@check("LIMITS", "item count boundary accepted")
def _(): require(len(parse_feed_items(rss_items(MAX_FEED_ITEMS))) == MAX_FEED_ITEMS)

@check("LIMITS", "too many items rejected")
def _(): expect(Stage6ExtractionError, lambda: parse_feed_items(rss_items(MAX_FEED_ITEMS + 1)), "ITEM_LIMIT")

@check("LIMITS", "oversized text rejected without truncation")
def _(): expect(Stage6ExtractionError, lambda: parse_feed_items(rss_items(1, MAX_TEXT_FIELD_CHARS + 1)), "FIELD_LIMIT")

@check("LIMITS", "total extracted size boundary enforced")
def _():
    count = (MAX_TOTAL_EXTRACTED_CHARS // (MAX_TEXT_FIELD_CHARS * 2)) + 1
    expect(Stage6ExtractionError, lambda: parse_feed_items(rss_items(count, MAX_TEXT_FIELD_CHARS, MAX_TEXT_FIELD_CHARS)), "TOTAL_EXTRACTED")

@check("IDEMPOTENCY", "exact rerun idempotent")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        extract(store, evidence["sebi"]); require(extract(store, evidence["sebi"])["status"] == "IDEMPOTENT_SUCCESS")

@check("IDEMPOTENCY", "incompatible stored batch rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        result = extract(store, evidence["sebi"]); store.connection.execute("DROP TRIGGER protect_extracted_items_update")
        store.connection.execute("UPDATE extracted_items SET canonical_json='{}' WHERE extraction_id=?", (result["records"][0]["extraction_id"],))
        restore_trigger(store, "extracted_items", "UPDATE"); store.connection.commit()
        expect(ExtractionConflict, lambda: extract(store, evidence["sebi"]), "INCOMPATIBLE")

@check("IDEMPOTENCY", "different parent creates new batch")
def _():
    with fresh_environment() as (ingestion, store, evidence, registries, _):
        other = capture(ingestion, registries, key="sebi-other", source_id=SEBI_SOURCE_ID, payload=RSS)
        one = extract(store, evidence["sebi"]); two = extract(store, other)
        require(one["batch_id"] != two["batch_id"])

@check("IDEMPOTENCY", "parser version participates in batch identity")
def _(): require(batch_identity("P", "a" * 64, CUTOFF, "V1")[0] != batch_identity("P", "a" * 64, CUTOFF, "V2")[0])


# Immutability and restart integrity.
@check("IMMUTABILITY", "UPDATE and DELETE blocked")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        extract(store, evidence["sebi"])
        expect(sqlite3.DatabaseError, lambda: store.connection.execute("UPDATE extracted_items SET item_ordinal=9"), "IMMUTABLE_TABLE_UPDATE")
        expect(sqlite3.DatabaseError, lambda: store.connection.execute("DELETE FROM extraction_batches"), "IMMUTABLE_TABLE_DELETE")

@check("IMMUTABILITY", "trigger removal detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        extract(store, evidence["sebi"]); store.connection.execute("DROP TRIGGER protect_extracted_items_delete"); store.connection.commit()
        expect(ExtractionIntegrityFailure, store.integrity_check, "TRIGGER_MISSING")

@check("RESTART_INTEGRITY", "clean restart passes with parser replay")
def _():
    with fresh_environment() as (ingestion, store, evidence, _, root):
        extract(store, evidence["sebi"]); store.close(); reopened = ExtractionStore(root / "extraction.sqlite3", ingestion)
        try: require(reopened.integrity_check()["result"] == "PASS")
        finally: reopened.close()
        store.connection = sqlite3.connect(":memory:")

@check("RESTART_INTEGRITY", "parent evidence tamper detected")
def _():
    with fresh_environment() as (ingestion, store, evidence, _, _):
        extract(store, evidence["sebi"]); ingestion.connection.execute("DROP TRIGGER protect_ingestion_records_update")
        ingestion.connection.execute("UPDATE ingestion_records SET record_hash=? WHERE record_id=?", ("b" * 64, evidence["sebi"]["evidence_id"])); ingestion.connection.commit()
        expect(ExtractionIntegrityFailure, store.integrity_check, "UPSTREAM_INGESTION")

@check("RESTART_INTEGRITY", "raw payload tamper detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        extract(store, evidence["sebi"]); store.ingestion_store.raw_store.path_for(evidence["sebi"]["raw_payload_hash"]).write_bytes(b"changed")
        expect(ExtractionIntegrityFailure, store.integrity_check, "UPSTREAM_INGESTION")

@check("RESTART_INTEGRITY", "dependency tamper detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        extract(store, evidence["sebi"]); store.connection.execute("DROP TRIGGER protect_extraction_dependencies_update")
        store.connection.execute("UPDATE extraction_dependencies SET dependency_record_hash=?", ("c" * 64,))
        restore_trigger(store, "extraction_dependencies", "UPDATE"); store.connection.commit()
        expect(ExtractionIntegrityFailure, store.integrity_check, "DEPENDENCY_BINDING")

def mutate_item(store: ExtractionStore, mutate, expected: str) -> None:
    row = store.connection.execute("SELECT * FROM extracted_items ORDER BY item_ordinal LIMIT 1").fetchone()
    record = json.loads(row["canonical_json"]); mutate(record)
    store.connection.execute("DROP TRIGGER protect_extracted_items_update")
    store.connection.execute("UPDATE extracted_items SET canonical_json=? WHERE extraction_id=?", (canonical_json(record), row["extraction_id"]))
    restore_trigger(store, "extracted_items", "UPDATE"); store.connection.commit()
    expect(ExtractionIntegrityFailure, store.integrity_check, expected)

@check("RESTART_INTEGRITY", "canonical item tamper detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _): extract(store, evidence["sebi"]); mutate_item(store, lambda r: r.update(title_text="changed"), "FIELD_HASH")

@check("RESTART_INTEGRITY", "item fingerprint tamper detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _): extract(store, evidence["sebi"]); mutate_item(store, lambda r: r.update(item_fingerprint="d" * 64), "ITEM_FINGERPRINT")

@check("RESTART_INTEGRITY", "field hash tamper detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _): extract(store, evidence["sebi"]); mutate_item(store, lambda r: r["field_hashes"].update(title_text="e" * 64), "FIELD_HASH")

@check("RESTART_INTEGRITY", "batch item count tamper detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        extract(store, evidence["sebi"]); store.connection.execute("DROP TRIGGER protect_extraction_batches_update")
        store.connection.execute("UPDATE extraction_batches SET item_count=99"); restore_trigger(store, "extraction_batches", "UPDATE"); store.connection.commit()
        expect(ExtractionIntegrityFailure, store.integrity_check, "ITEM_COUNT")

@check("RESTART_INTEGRITY", "locator tamper detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        extract(store, evidence["sebi"]); store.connection.execute("DROP TRIGGER protect_extracted_items_update")
        store.connection.execute("UPDATE extracted_items SET structural_locator='/wrong' WHERE item_ordinal=0")
        restore_trigger(store, "extracted_items", "UPDATE"); store.connection.commit()
        expect(ExtractionIntegrityFailure, store.integrity_check, "TYPED_COLUMN")

@check("RESTART_INTEGRITY", "parser replay mismatch detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        extract(store, evidence["sebi"]); row = store.connection.execute("SELECT * FROM extracted_items WHERE item_ordinal=0").fetchone()
        record = json.loads(row["canonical_json"]); record["title_text"] = "Valid but non-replayed title"
        record["field_hashes"]["title_text"] = canonical_hash(record["title_text"])
        record["item_fingerprint"] = canonical_hash({name: record[name] for name in ("structural_locator", "item_identifier_type", "item_identifier_value", "title_text", "description_text", "link_value", "guid_or_atom_id", "publication_timestamp_utc", "timestamp_status")})
        record["record_hash"] = canonical_hash(without(record, "record_hash"))
        store.connection.execute("DROP TRIGGER protect_extracted_items_update")
        store.connection.execute("UPDATE extracted_items SET canonical_json=?,item_fingerprint=?,record_hash=? WHERE extraction_id=?",
            (canonical_json(record), record["item_fingerprint"], record["record_hash"], record["extraction_id"]))
        restore_trigger(store, "extracted_items", "UPDATE"); store.connection.commit()
        expect(ExtractionIntegrityFailure, store.integrity_check, "PARSER_REPLAY")

@check("RESTART_INTEGRITY", "orphan item detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        extract(store, evidence["sebi"])
        store.connection.execute("INSERT INTO extracted_items VALUES(?,?,?,?,?,?,?)", ("S6XITEM_ORPHAN", "P", 999, "/orphan", "f" * 64, "e" * 64, "{}")); store.connection.commit()
        expect(ExtractionIntegrityFailure, store.integrity_check, "ORPHAN_OR_COVERAGE")


# Event, network, trading and frozen boundaries.
@check("EVENT_BOUNDARY", "zero EventStore writes")
def _():
    with fresh_environment() as (ingestion, store, evidence, _, root):
        event_store = EventStore(root / "events.sqlite3", ingestion)
        try:
            before = event_store.connection.execute("SELECT COUNT(*) FROM event_records").fetchone()[0]
            extract(store, evidence["sebi"])
            after = event_store.connection.execute("SELECT COUNT(*) FROM event_records").fetchone()[0]
            require(before == after == 0)
        finally: event_store.close()

@check("EVENT_BOUNDARY", "extraction contract contains no event classification fields")
def _():
    prohibited = {"event_type", "direction", "severity", "materiality", "confidence", "entities", "sentiment"}
    with fresh_environment() as (_, store, evidence, _, _): require(not prohibited.intersection(extract(store, evidence["sebi"])["records"][0]))

@check("NETWORK", "socket sentinel proves zero network calls")
def _():
    with mock.patch.object(socket, "socket", side_effect=AssertionError("NETWORK_USED")): require(len(parse_feed_items(RSS)) == 4)

@check("NETWORK", "no network connector or event imports in extraction module")
def _():
    prohibited = {"socket", "requests", "urllib", "http", "aiohttp", "stage6_connectors", "stage6_events"}
    for path in (STAGE_ROOT / "stage6_extraction").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8")); imports = set()
        imports |= {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
        imports |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        require(not imports.intersection(prohibited))

@check("TRADING", "no trading ML LLM ranking or broker implementation")
def _():
    text = "\n".join(path.read_text(encoding="utf-8").casefold() for path in (STAGE_ROOT / "stage6_extraction").glob("*.py"))
    for token in ("buy_signal", "sell_signal", "hold_recommendation", "broker_order", "target_price",
                  "stop_loss", "import sklearn", "import openai", "append_event("):
        require(token not in text)

@check("BASELINE", "frozen architecture unchanged")
def _():
    paths = ["Stage 6/Stage6_Master_Architecture.md", "Stage 6/contracts", "Stage 6/policy",
             "Stage 6/scripts/validate_stage6_0.py", "Stage 6/results/stage6_0_architecture_contract.json"]
    require(git("diff", "--name-only", ARCHITECTURE_TAG, "--", *paths) == "")

@check("BASELINE", "Stage 6.1 unchanged")
def _(): require(git("diff", "--name-only", BASELINE_1C_TAG, "--", "Stage 6/stage6_ingestion", "Stage 6/stage6_connectors") == "")

@check("BASELINE", "frozen Stage 6.2A unchanged")
def _():
    paths = ["Stage 6/stage6_events", "Stage 6/Stage6_2A_Delivery_Report.md", "Stage 6/results/stage6_2a_contract.json",
             "Stage 6/results/stage6_2a_test_results.csv", "Stage 6/fixtures/stage6_2a"]
    require(git("diff", "--name-only", BASELINE_2A_TAG, "--", *paths) == "")

@check("BASELINE", "Stage 5D unchanged")
def _(): require(git("diff", "--name-only", PRODUCTION_TAG, "--", "Stage 5D") == "")


def main() -> int:
    rows: list[dict[str, str]] = []
    for number, (category, name, function) in enumerate(CHECKS, 1):
        try:
            with mock.patch.object(socket, "socket", side_effect=AssertionError("STAGE6_2B_NETWORK_USED")): function()
            rows.append({"test_id": f"S6_2B_{number:03d}", "category": category, "test_name": name, "result": "PASS", "detail": ""})
        except Exception as exc:
            rows.append({"test_id": f"S6_2B_{number:03d}", "category": category, "test_name": name, "result": "FAIL", "detail": f"{type(exc).__name__}:{exc}"})
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["test_id", "category", "test_name", "result", "detail"], lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    failed = [row for row in rows if row["result"] != "PASS"]
    print(json.dumps({"stage": "6.2B", "tests": len(rows), "passed": len(rows) - len(failed),
                      "failed": len(failed), "result": "PASS" if not failed else "FAIL",
                      "authority": AUTHORITY, "network_calls": 0, "creates_events": False,
                      "creates_evidence": False}, sort_keys=True, separators=(",", ":")))
    for row in failed: print(f"FAIL {row['test_id']} {row['test_name']}: {row['detail']}")
    return 1 if failed else 0


if __name__ == "__main__": raise SystemExit(main())
