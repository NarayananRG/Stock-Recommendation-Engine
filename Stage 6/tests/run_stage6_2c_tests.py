"""Stage 6.2C deterministic candidate classification acceptance tests."""
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
from xml.sax.saxutils import escape


STAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE_ROOT.parent
sys.path.insert(0, str(STAGE_ROOT))

from stage6_candidates import (AUTHORITY, CANDIDATE_SCHEMA_VERSION, CLASSIFICATION_METHOD,
                               CLASSIFIER_VERSION, RULESET_ID, RULESET_VERSION,
                               CandidateConflict, CandidateIntegrityFailure, CandidateStore,
                               Stage6CandidateError, candidate_identity, classify_extraction,
                               load_ruleset, normalize_text, validate_ruleset)
from stage6_candidates.candidate_validation import validate_candidate
from stage6_connectors.live_registries import (RBI_ENTITY_ID, RBI_SOURCE_ID, SEBI_ENTITY_ID,
                                               SEBI_SOURCE_ID, build_multisource_registries)
from stage6_events import EventStore
from stage6_extraction import ExtractionStore
from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from stage6_ingestion.evidence_store import IngestionStore


FIXTURE_PATH = STAGE_ROOT / "fixtures" / "stage6_2c" / "classification_cases.json"
RESULT_PATH = STAGE_ROOT / "results" / "stage6_2c_test_results.csv"
BASELINE_2B_TAG = "stage6-2b-rss-item-extraction-baseline"
BASELINE_2B_COMMIT = "48a1f4f95e3a582abdf0c8d50bb1ead50474e2d4"
BASELINE_2A_TAG = "stage6-2a-event-intelligence-foundation-baseline"
BASELINE_1C_TAG = "stage6-1c-multisource-rss-ingestion-baseline"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
EXTRACTION_CUTOFF = "2026-09-26T08:00:01.000000Z"
LATER_CUTOFF = "2026-09-26T09:00:00.000000Z"
CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
RULESET, RULESET_JSON, RULESET_HASH = load_ruleset()
CHECKS: list[tuple[str, str, object]] = []


def check(category: str, name: str):
    def register(function): CHECKS.append((category, name, function)); return function
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


def feed_for(source_id: str) -> bytes:
    selected = [item for item in CASES if item["source_id"] == source_id]
    items = []
    for item in selected:
        description = "" if item["description"] is None else f"<description>{escape(item['description'])}</description>"
        items.append(f"<item><title>{escape(item['title'])}</title>{description}<guid>{item['case_id']}</guid></item>")
    return ("<rss><channel><title>Synthetic Stage 6.2C cases</title>" + "".join(items) + "</channel></rss>").encode()


def capture(store: IngestionStore, registries: dict, source_id: str, key: str, payload: bytes) -> dict:
    entity = RBI_ENTITY_ID if source_id == RBI_SOURCE_ID else SEBI_ENTITY_ID
    return store.capture_evidence(
        idempotency_key=key, source_registry_snapshot_id=registries["source_v2"]["registry_snapshot_id"],
        entity_registry_snapshot_id=registries["entity_v2"]["registry_snapshot_id"], source_id=source_id,
        source_reference=f"fixture://stage6-2c/{key}", raw_payload=payload, content_type="application/rss+xml",
        publication_timestamp_utc=None, observed_timestamp_utc="2026-09-26T08:00:00Z",
        retrieved_timestamp_utc="2026-09-26T08:00:01Z", entity_ids=[entity])["record"]


@contextmanager
def fresh_environment():
    with tempfile.TemporaryDirectory(prefix="stage6_2c_test_") as folder:
        root = Path(folder); registries = build_multisource_registries()
        ingestion = IngestionStore(root / "ingestion.sqlite3", root / "raw")
        ingestion.import_registry(registries["entity_v1"]); ingestion.import_registry(registries["source_v1"])
        ingestion.import_registry(registries["entity_v2"]); ingestion.import_registry(registries["source_v2"])
        rbi = capture(ingestion, registries, RBI_SOURCE_ID, "rbi-cases", feed_for(RBI_SOURCE_ID))
        sebi = capture(ingestion, registries, SEBI_SOURCE_ID, "sebi-cases", feed_for(SEBI_SOURCE_ID))
        extraction = ExtractionStore(root / "extraction.sqlite3", ingestion)
        rbi_batch = extraction.extract(parent_evidence_id=rbi["evidence_id"], extraction_cutoff=EXTRACTION_CUTOFF)["batch_id"]
        sebi_batch = extraction.extract(parent_evidence_id=sebi["evidence_id"], extraction_cutoff=EXTRACTION_CUTOFF)["batch_id"]
        candidates = CandidateStore(root / "candidates.sqlite3", extraction)
        try: yield ingestion, extraction, candidates, {RBI_SOURCE_ID: rbi_batch, SEBI_SOURCE_ID: sebi_batch}, root
        finally:
            try: candidates.close()
            except sqlite3.Error: pass
            try: extraction.close()
            except sqlite3.Error: pass
            ingestion.close()


def classify_all(store: CandidateStore, batches: dict[str, str], cutoff: str = EXTRACTION_CUTOFF) -> dict[str, dict]:
    output = {}
    for source, batch in batches.items():
        result = store.classify_batch(extraction_batch_id=batch, classification_cutoff=cutoff)
        for record in result["records"]:
            extraction = store.extraction_store.connection.execute(
                "SELECT canonical_json FROM extracted_items WHERE extraction_id=?", (record["input_extraction_id"],)).fetchone()
            item = json.loads(extraction[0]); output[item["guid_or_atom_id"]] = record
    return output


def fake_extraction(title: str | None, description: str | None, source: str = RBI_SOURCE_ID,
                    identity: str = "X") -> dict:
    return {"extraction_id": f"S6XITEM_{identity}", "record_hash": canonical_hash({"identity": identity}),
            "source_id": source, "title_text": title, "description_text": description,
            "extracted_at_cutoff": EXTRACTION_CUTOFF, "parent_evidence_id": "S6EV_PARENT",
            "parent_evidence_hash": "a" * 64}


def restore_trigger(store: CandidateStore, table: str, operation: str) -> None:
    store.connection.executescript(f"""
    CREATE TRIGGER protect_{table}_{operation.lower()} BEFORE {operation} ON {table}
    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_{operation}'); END;
    """)


# Baseline and input.
@check("BASELINE", "Stage 6.2B tag exact ancestor")
def _():
    require(git("rev-parse", f"{BASELINE_2B_TAG}^{{}}") == BASELINE_2B_COMMIT)
    subprocess.check_call(["git", "merge-base", "--is-ancestor", BASELINE_2B_COMMIT, "HEAD"], cwd=REPO_ROOT)

@check("BASELINE", "authority remains SHADOW_ONLY")
def _(): require(AUTHORITY == "SHADOW_ONLY")

@check("INPUT", "valid complete extraction batch accepted")
def _():
    with fresh_environment() as (_, _, store, batches, _): require(store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF)["status"] == "CREATED")

@check("INPUT", "missing extraction batch rejected")
def _():
    with fresh_environment() as (_, _, store, _, _): expect(Stage6CandidateError, lambda: store.classify_batch(extraction_batch_id="S6XBATCH_MISSING", classification_cutoff=EXTRACTION_CUTOFF), "NOT_FOUND")

@check("INPUT", "tampered extraction store rejected")
def _():
    with fresh_environment() as (_, extraction, store, batches, _):
        extraction.connection.execute("DROP TRIGGER protect_extracted_items_update")
        target = extraction.connection.execute("SELECT extraction_id FROM extracted_items LIMIT 1").fetchone()[0]
        extraction.connection.execute("UPDATE extracted_items SET record_hash=? WHERE extraction_id=?", ("b" * 64, target)); extraction.connection.commit()
        expect(CandidateIntegrityFailure, lambda: store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF), "UPSTREAM_EXTRACTION")

@check("INPUT", "wrong extraction schema rejected transitively")
def _():
    with fresh_environment() as (_, extraction, store, batches, _):
        row = extraction.connection.execute("SELECT * FROM extracted_items LIMIT 1").fetchone(); record = json.loads(row["canonical_json"]); record["schema_version"] = "WRONG"
        extraction.connection.execute("DROP TRIGGER protect_extracted_items_update")
        extraction.connection.execute("UPDATE extracted_items SET canonical_json=? WHERE extraction_id=?", (canonical_json(record), row["extraction_id"])); extraction.connection.commit()
        expect(CandidateIntegrityFailure, lambda: store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF), "UPSTREAM_EXTRACTION")

@check("INPUT", "orphan extraction rejected transitively")
def _():
    with fresh_environment() as (_, extraction, store, batches, _):
        extraction.connection.execute("INSERT INTO extracted_items VALUES(?,?,?,?,?,?,?)", ("S6XITEM_ORPHAN", "P", 999, "/x", "c"*64, "d"*64, "{}")); extraction.connection.commit()
        expect(CandidateIntegrityFailure, lambda: store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF), "UPSTREAM_EXTRACTION")


# Ruleset and normalization.
@check("RULESET", "valid V1 ruleset and deterministic hash")
def _(): require(validate_ruleset(deepcopy(RULESET)) == RULESET and canonical_hash(RULESET) == RULESET_HASH)

def invalid_ruleset(mutator, contains: str) -> None:
    ruleset = deepcopy(RULESET); mutator(ruleset); expect(Stage6CandidateError, lambda: validate_ruleset(ruleset), contains)

@check("RULESET", "duplicate rule ID rejected")
def _(): invalid_ruleset(lambda r: r["rules"].append(deepcopy(r["rules"][0])), "DUPLICATE_OR_INVALID_RULE_ID")

@check("RULESET", "unknown source rejected")
def _(): invalid_ruleset(lambda r: r["rules"][0].update(source_id="UNKNOWN"), "SOURCE_UNSUPPORTED")

@check("RULESET", "unknown event type rejected")
def _(): invalid_ruleset(lambda r: r["rules"][0].update(candidate_event_type="NOT_AN_EVENT"), "EVENT_TYPE_UNSUPPORTED")

@check("RULESET", "empty positive rule rejected")
def _(): invalid_ruleset(lambda r: (r["rules"][0].update(required_all_phrases=[]), r["rules"][0].update(required_any_phrases=[])), "POSITIVE_PHRASE_REQUIRED")

@check("RULESET", "duplicate phrase rejected")
def _(): invalid_ruleset(lambda r: r["rules"][0].update(required_any_phrases=["cut", "cut"]), "LIST_INVALID")

@check("RULESET", "unknown field and invalid identity rejected")
def _():
    invalid_ruleset(lambda r: r["rules"][0].update(fields=["link_value"]), "SEARCH_FIELD_UNSUPPORTED")
    invalid_ruleset(lambda r: r.update(schema_version="WRONG"), "IDENTITY_INVALID")

@check("NORMALIZATION", "case NFKC punctuation and whitespace deterministic")
def _():
    require(normalize_text("  ＲＥＰＯ—Rate\tINCREASED! ") == "repo rate increased")
    require(normalize_text("Repo...Rate") == "repo rate")

@check("NORMALIZATION", "normalized hashes deterministic")
def _():
    one = classify_extraction(fake_extraction("Repo Rate", "Raised"), RULESET)
    two = classify_extraction(fake_extraction("ＲＥＰＯ Rate", "RAISED"), RULESET)
    require(one["normalized_title_hash"] == two["normalized_title_hash"] and one["normalized_description_hash"] == two["normalized_description_hash"])


# Token matching and classifications.
@check("TOKEN_MATCHING", "cut token matches but shortcut does not")
def _():
    require(classify_extraction(fake_extraction("Repo rate cut", None), RULESET)["candidate_event_type"] == "RATE_CUT")
    require(classify_extraction(fake_extraction("Repo rate shortcut", None), RULESET)["classification_status"] == "NO_MATCH")

@check("TOKEN_MATCHING", "repo rate matches normalized whitespace")
def _(): require(classify_extraction(fake_extraction("Repo---rate", "was raised"), RULESET)["candidate_event_type"] == "RATE_HIKE")

@check("TOKEN_MATCHING", "generic rate increase and generic order do not match")
def _():
    require(classify_extraction(fake_extraction("Rate of growth increased", None), RULESET)["classification_status"] == "NO_MATCH")
    require(classify_extraction(fake_extraction("General order", None, SEBI_SOURCE_ID), RULESET)["classification_status"] == "NO_MATCH")
    require(classify_extraction(fake_extraction("Orderly market", None, SEBI_SOURCE_ID), RULESET)["classification_status"] == "NO_MATCH")

for case_id, expected_type in [("rbi_hike_increased", "RATE_HIKE"), ("rbi_hike_raise", "RATE_HIKE"),
                               ("rbi_hike_hike", "RATE_HIKE"), ("rbi_cut_reduced", "RATE_CUT"),
                               ("rbi_cut_cut", "RATE_CUT"), ("rbi_cut_lowered", "RATE_CUT"),
                               ("sebi_interim", "REGULATORY_ACTION"), ("sebi_final", "REGULATORY_ACTION"),
                               ("sebi_adjudication", "REGULATORY_ACTION"), ("sebi_settlement", "REGULATORY_ACTION")]:
    def make_match_test(item=case_id, event_type=expected_type):
        @check("LITERAL_CLASSIFICATION", f"{item} matched")
        def _test():
            with fresh_environment() as (_, _, store, batches, _):
                record = classify_all(store, batches)[item]
                require(record["classification_status"] == "MATCHED" and record["candidate_event_type"] == event_type)
        return _test
    make_match_test()

@check("SOURCE_ISOLATION", "RBI and SEBI rules cannot cross-fire")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        records = classify_all(store, batches)
        require(records["sebi_source_isolation"]["classification_status"] == "NO_MATCH")
        require(records["rbi_source_isolation"]["classification_status"] == "NO_MATCH")

@check("NO_MATCH", "explicit NO_MATCH is retained and never OTHER")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        record = classify_all(store, batches)["rbi_no_match_report"]
        require(record["classification_status"] == "NO_MATCH" and record["candidate_event_type"] is None)
        require(record["matched_rule_ids"] == [] and record["match_traces"] == [] and "OTHER" not in canonical_json(record))

@check("AMBIGUOUS", "rate hike and cut remain sorted ambiguous without priority")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        record = classify_all(store, batches)["rbi_ambiguous"]
        require(record["classification_status"] == "AMBIGUOUS" and record["candidate_event_type"] is None)
        require(record["ambiguous_event_types"] == ["RATE_CUT", "RATE_HIKE"] and len(record["matched_rule_ids"]) == 2)

@check("SAME_TYPE", "multiple same-type rules remain MATCHED")
def _():
    ruleset = deepcopy(RULESET); second = deepcopy(next(r for r in ruleset["rules"] if r["rule_id"] == "RBI_RATE_HIKE_EXPLICIT_V1"))
    second["rule_id"] = "RBI_RATE_HIKE_SECOND_V1"; ruleset["rules"].append(second); ruleset["rules"].sort(key=lambda r: r["rule_id"])
    result = classify_extraction(fake_extraction("Repo rate raised", None), ruleset)
    require(result["classification_status"] == "MATCHED" and result["candidate_event_type"] == "RATE_HIKE" and len(result["matched_rule_ids"]) == 2)

@check("MATCH_TRACE", "trace names exact rule phrase and field deterministically")
def _():
    extraction = fake_extraction("Repo rate", "Raised")
    first = classify_extraction(extraction, RULESET); second = classify_extraction(extraction, RULESET)
    require(first == second)
    trace = first["match_traces"][0]
    require(trace["rule_id"] == "RBI_RATE_HIKE_EXPLICIT_V1")
    require({item["phrase"]: item["fields"] for item in trace["phrase_matches"]} == {"raised": ["description_text"], "repo rate": ["title_text"]})


# Identity, PIT, batch, dependencies.
@check("IDENTITY", "candidate identity stable and cutoff-independent")
def _():
    extraction = fake_extraction("Repo rate raised", None)
    require(candidate_identity(extraction, RULESET_HASH) == candidate_identity(extraction, RULESET_HASH))
    require(candidate_identity(extraction, RULESET_HASH) != candidate_identity(fake_extraction("Repo rate raised", None, identity="Y"), RULESET_HASH))
    require(candidate_identity(extraction, RULESET_HASH) != candidate_identity(extraction, "f" * 64))

@check("PIT", "equal and later cutoff accepted; earlier rejected")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF)
        store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=LATER_CUTOFF)
    with fresh_environment() as (_, _, store, batches, _):
        expect(Stage6CandidateError, lambda: store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff="2026-09-26T08:00:00Z"), "BEFORE_EXTRACTION")

@check("BATCH", "one candidate per item including no-match and ambiguous")
def _():
    with fresh_environment() as (_, extraction, store, batches, _):
        result = store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF)
        count = extraction.connection.execute("SELECT item_count FROM extraction_batches WHERE batch_id=?", (batches[RBI_SOURCE_ID],)).fetchone()[0]
        require(len(result["records"]) == count and {r["classification_status"] for r in result["records"]} >= {"MATCHED", "NO_MATCH", "AMBIGUOUS"})

@check("BATCH", "later cutoff reuses same candidate records")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        one = store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF)
        two = store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=LATER_CUTOFF)
        require([r["candidate_id"] for r in one["records"]] == [r["candidate_id"] for r in two["records"]])

@check("IDEMPOTENCY", "exact classification batch rerun is idempotent")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF)
        require(store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF)["status"] == "IDEMPOTENT_SUCCESS")

@check("DEPENDENCY", "exact extraction and ruleset ID hash type bindings")
def _():
    with fresh_environment() as (_, extraction, store, batches, _):
        record = store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF)["records"][0]
        source = json.loads(extraction.connection.execute("SELECT canonical_json FROM extracted_items WHERE extraction_id=?", (record["input_extraction_id"],)).fetchone()[0])
        deps = {row["dependency_record_type"]: row for row in store.connection.execute("SELECT * FROM candidate_dependencies WHERE candidate_id=?", (record["candidate_id"],))}
        require((deps["RSS_ITEM_EXTRACTION"]["dependency_record_id"], deps["RSS_ITEM_EXTRACTION"]["dependency_record_hash"]) == (source["extraction_id"], source["record_hash"]))
        require((deps["CLASSIFICATION_RULESET"]["dependency_record_id"], deps["CLASSIFICATION_RULESET"]["dependency_record_hash"]) == (RULESET_ID, RULESET_HASH))

@check("DEPENDENCY", "classification leaves source extraction text unchanged")
def _():
    with fresh_environment() as (_, extraction, store, batches, _):
        before = [row[0] for row in extraction.connection.execute(
            "SELECT canonical_json FROM extracted_items ORDER BY extraction_id")]
        store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF)
        after = [row[0] for row in extraction.connection.execute(
            "SELECT canonical_json FROM extracted_items ORDER BY extraction_id")]
        require(before == after)


# Immutability and integrity adversaries.
@check("IMMUTABILITY", "candidate ruleset and batch update delete blocked")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF)
        expect(sqlite3.DatabaseError, lambda: store.connection.execute("UPDATE candidate_records SET source_id='X'"), "IMMUTABLE_TABLE_UPDATE")
        expect(sqlite3.DatabaseError, lambda: store.connection.execute("DELETE FROM candidate_records"), "IMMUTABLE_TABLE_DELETE")
        expect(sqlite3.DatabaseError, lambda: store.connection.execute("UPDATE candidate_rulesets SET ruleset_version=2"), "IMMUTABLE_TABLE_UPDATE")
        expect(sqlite3.DatabaseError, lambda: store.connection.execute("DELETE FROM candidate_rulesets"), "IMMUTABLE_TABLE_DELETE")
        expect(sqlite3.DatabaseError, lambda: store.connection.execute("UPDATE classification_batches SET candidate_count=0"), "IMMUTABLE_TABLE_UPDATE")

@check("IMMUTABILITY", "trigger removal detected")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        store.classify_batch(extraction_batch_id=batches[RBI_SOURCE_ID], classification_cutoff=EXTRACTION_CUTOFF)
        store.connection.execute("DROP TRIGGER protect_candidate_records_delete"); store.connection.commit()
        expect(CandidateIntegrityFailure, store.integrity_check, "TRIGGER_MISSING")

@check("RESTART_INTEGRITY", "clean restart passes classifier replay")
def _():
    with fresh_environment() as (_, extraction, store, batches, root):
        classify_all(store, batches); store.close(); reopened = CandidateStore(root / "candidates.sqlite3", extraction)
        try: require(reopened.integrity_check()["result"] == "PASS")
        finally: reopened.close()
        store.connection = sqlite3.connect(":memory:")

def mutate_candidate(store: CandidateStore, mutator, expected: str, sync_typed: bool = False) -> None:
    row = store.connection.execute("SELECT * FROM candidate_records WHERE classification_status='MATCHED' ORDER BY candidate_id LIMIT 1").fetchone()
    record = json.loads(row["canonical_json"]); mutator(record)
    store.connection.execute("DROP TRIGGER protect_candidate_records_update")
    if sync_typed:
        store.connection.execute("UPDATE candidate_records SET canonical_json=?,classification_status=?,candidate_event_type=?,record_hash=? WHERE candidate_id=?",
            (canonical_json(record), record["classification_status"], record["candidate_event_type"], record["record_hash"], row["candidate_id"]))
    else:
        store.connection.execute("UPDATE candidate_records SET canonical_json=? WHERE candidate_id=?", (canonical_json(record), row["candidate_id"]))
    restore_trigger(store, "candidate_records", "UPDATE"); store.connection.commit()
    expect(CandidateIntegrityFailure, store.integrity_check, expected)

@check("RESTART_INTEGRITY", "candidate canonical JSON and record hash tamper detected")
def _():
    with fresh_environment() as (_, _, store, batches, _): classify_all(store, batches); mutate_candidate(store, lambda r: r.update(record_hash="e"*64), "RECORD_HASH")

@check("RESTART_INTEGRITY", "candidate status tamper detected")
def _():
    with fresh_environment() as (_, _, store, batches, _): classify_all(store, batches); mutate_candidate(store, lambda r: r.update(classification_status="INVALID"), "STATUS_INVALID")

@check("RESTART_INTEGRITY", "candidate event type tamper detected")
def _():
    with fresh_environment() as (_, _, store, batches, _): classify_all(store, batches); mutate_candidate(store, lambda r: r.update(candidate_event_type="OTHER"), "INVARIANT_FAILED")

@check("RESTART_INTEGRITY", "matched rule and match trace tamper detected")
def _():
    with fresh_environment() as (_, _, store, batches, _): classify_all(store, batches); mutate_candidate(store, lambda r: r.update(matched_rule_ids=["UNKNOWN"]), "TRACE_ORDER_OR_COVERAGE")
    with fresh_environment() as (_, _, store, batches, _): classify_all(store, batches); mutate_candidate(store, lambda r: r.update(match_traces=[]), "TRACE_ORDER_OR_COVERAGE")

@check("RESTART_INTEGRITY", "ruleset tamper detected")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        classify_all(store, batches); store.connection.execute("DROP TRIGGER protect_candidate_rulesets_update")
        store.connection.execute("UPDATE candidate_rulesets SET ruleset_hash=?", ("f"*64,)); restore_trigger(store, "candidate_rulesets", "UPDATE"); store.connection.commit()
        expect(CandidateIntegrityFailure, store.integrity_check, "RULESET_SNAPSHOT")

@check("RESTART_INTEGRITY", "dependency missing wrong hash type and extra detected")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        classify_all(store, batches); store.connection.execute("DROP TRIGGER protect_candidate_dependencies_update")
        store.connection.execute("UPDATE candidate_dependencies SET dependency_record_hash=? WHERE dependency_record_type='RSS_ITEM_EXTRACTION'", ("1"*64,))
        restore_trigger(store, "candidate_dependencies", "UPDATE"); store.connection.commit()
        expect(CandidateIntegrityFailure, store.integrity_check, "EXTRACTION_DEPENDENCY")
    with fresh_environment() as (_, _, store, batches, _):
        classify_all(store, batches); store.connection.execute("DROP TRIGGER protect_candidate_dependencies_delete")
        store.connection.execute("DELETE FROM candidate_dependencies WHERE dependency_record_type='CLASSIFICATION_RULESET'")
        restore_trigger(store, "candidate_dependencies", "DELETE"); store.connection.commit()
        expect(CandidateIntegrityFailure, store.integrity_check, "DEPENDENCY_COVERAGE")

@check("RESTART_INTEGRITY", "wrong ruleset dependency hash detected")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        classify_all(store, batches); store.connection.execute("DROP TRIGGER protect_candidate_dependencies_update")
        store.connection.execute("UPDATE candidate_dependencies SET dependency_record_hash=? WHERE dependency_record_type='CLASSIFICATION_RULESET'", ("2"*64,))
        restore_trigger(store, "candidate_dependencies", "UPDATE"); store.connection.commit()
        expect(CandidateIntegrityFailure, store.integrity_check, "RULESET_DEPENDENCY")

@check("RESTART_INTEGRITY", "invalid dependency type detected")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        classify_all(store, batches); store.connection.execute("PRAGMA ignore_check_constraints=ON")
        store.connection.execute("DROP TRIGGER protect_candidate_dependencies_update")
        store.connection.execute("UPDATE candidate_dependencies SET dependency_record_type='INVALID' WHERE dependency_record_type='RSS_ITEM_EXTRACTION'")
        restore_trigger(store, "candidate_dependencies", "UPDATE"); store.connection.commit()
        expect(CandidateIntegrityFailure, store.integrity_check, "DEPENDENCY_COVERAGE")

@check("RESTART_INTEGRITY", "extra dependency detected")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        classify_all(store, batches); store.connection.execute("PRAGMA ignore_check_constraints=ON")
        row = store.connection.execute("SELECT candidate_id FROM candidate_records ORDER BY candidate_id LIMIT 1").fetchone()
        store.connection.execute("INSERT INTO candidate_dependencies VALUES(?,?,?,?)",
            (row[0], "EXTRA", "S6EXTRA", "3"*64)); store.connection.commit()
        expect(CandidateIntegrityFailure, store.integrity_check, "DEPENDENCY_COVERAGE")

@check("RESTART_INTEGRITY", "batch count tamper detected")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        classify_all(store, batches); store.connection.execute("DROP TRIGGER protect_classification_batches_update")
        store.connection.execute("UPDATE classification_batches SET candidate_count=999"); restore_trigger(store, "classification_batches", "UPDATE"); store.connection.commit()
        expect(CandidateIntegrityFailure, store.integrity_check, "BATCH_COUNT")

@check("RESTART_INTEGRITY", "orphan candidate detected")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        classify_all(store, batches)
        store.connection.execute("INSERT INTO candidate_records VALUES(?,?,?,?,?,?,?,?,?)", ("S6CAND_ORPHAN", "X", "a"*64, RULESET_HASH, RBI_SOURCE_ID, "NO_MATCH", None, "b"*64, "{}")); store.connection.commit()
        expect(CandidateIntegrityFailure, store.integrity_check, "ORPHAN_OR_COVERAGE")

@check("RESTART_INTEGRITY", "classifier replay mismatch detected")
def _():
    with fresh_environment() as (_, _, store, batches, _):
        classify_all(store, batches)
        def valid_but_wrong(record):
            record.update(classification_status="NO_MATCH", candidate_event_type=None,
                          ambiguous_event_types=[], matched_rule_ids=[], match_traces=[])
            record["record_hash"] = canonical_hash(without(record, "record_hash"))
        mutate_candidate(store, valid_but_wrong, "CLASSIFIER_REPLAY", sync_typed=True)


# Read-only and authority boundaries.
@check("BOUNDARY", "zero EventStore evidence and extraction writes")
def _():
    with fresh_environment() as (ingestion, extraction, store, batches, root):
        event_store = EventStore(root / "events.sqlite3", ingestion)
        try:
            before = (ingestion.connection.execute("SELECT COUNT(*) FROM ingestion_records").fetchone()[0],
                      extraction.connection.execute("SELECT COUNT(*) FROM extracted_items").fetchone()[0],
                      event_store.connection.execute("SELECT COUNT(*) FROM event_records").fetchone()[0])
            classify_all(store, batches)
            after = (ingestion.connection.execute("SELECT COUNT(*) FROM ingestion_records").fetchone()[0],
                     extraction.connection.execute("SELECT COUNT(*) FROM extracted_items").fetchone()[0],
                     event_store.connection.execute("SELECT COUNT(*) FROM event_records").fetchone()[0])
            require(before == after and after[2] == 0)
        finally: event_store.close()

@check("BOUNDARY", "candidate contract excludes event interpretation fields")
def _():
    prohibited = {"event_status", "confidence", "direction", "severity", "materiality", "entities",
                  "causality_assessment", "transmission_channels", "sentiment", "score", "probability"}
    with fresh_environment() as (_, _, store, batches, _): require(not prohibited.intersection(classify_all(store, batches).popitem()[1]))

@check("NETWORK_AI_TRADING", "no network connector LLM ML sentiment or trading implementation")
def _():
    prohibited_imports = {"socket", "requests", "urllib", "http", "aiohttp", "stage6_connectors"}
    text = ""
    for path in (STAGE_ROOT / "stage6_candidates").glob("*.py"):
        source = path.read_text(encoding="utf-8"); text += source.casefold(); tree = ast.parse(source)
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
        imports |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        require(not imports.intersection(prohibited_imports))
    for token in ("append_event(", "capture_evidence(", "requests.get", "openai", "transformers", "embedding",
                  "sentiment model", "buy_signal", "sell_signal", "broker_order", "position_size"):
        require(token not in text)

@check("NETWORK_AI_TRADING", "socket sentinel and zero link fetches")
def _():
    with mock.patch.object(socket, "socket", side_effect=AssertionError("NETWORK_USED")):
        require(classify_extraction(fake_extraction("Repo rate raised", "https://invalid.example"), RULESET)["classification_status"] == "MATCHED")

@check("BASELINE", "all frozen paths unchanged")
def _():
    architecture = ["Stage 6/Stage6_Master_Architecture.md", "Stage 6/contracts", "Stage 6/policy", "Stage 6/scripts/validate_stage6_0.py", "Stage 6/results/stage6_0_architecture_contract.json"]
    require(git("diff", "--name-only", ARCHITECTURE_TAG, "--", *architecture) == "")
    require(git("diff", "--name-only", BASELINE_1C_TAG, "--", "Stage 6/stage6_ingestion", "Stage 6/stage6_connectors") == "")
    stage2a = ["Stage 6/stage6_events", "Stage 6/Stage6_2A_Delivery_Report.md", "Stage 6/results/stage6_2a_contract.json", "Stage 6/results/stage6_2a_test_results.csv", "Stage 6/fixtures/stage6_2a"]
    require(git("diff", "--name-only", BASELINE_2A_TAG, "--", *stage2a) == "")
    stage2b = ["Stage 6/stage6_extraction", "Stage 6/Stage6_2B_Delivery_Report.md", "Stage 6/results/stage6_2b_contract.json", "Stage 6/results/stage6_2b_test_results.csv", "Stage 6/fixtures/stage6_2b"]
    require(git("diff", "--name-only", BASELINE_2B_TAG, "--", *stage2b) == "")
    require(git("diff", "--name-only", PRODUCTION_TAG, "--", "Stage 5D") == "")


def main() -> int:
    rows = []
    for number, (category, name, function) in enumerate(CHECKS, 1):
        try:
            with mock.patch.object(socket, "socket", side_effect=AssertionError("STAGE6_2C_NETWORK_USED")): function()
            rows.append({"test_id": f"S6_2C_{number:03d}", "category": category, "test_name": name, "result": "PASS", "detail": ""})
        except Exception as exc:
            rows.append({"test_id": f"S6_2C_{number:03d}", "category": category, "test_name": name, "result": "FAIL", "detail": f"{type(exc).__name__}:{exc}"})
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["test_id", "category", "test_name", "result", "detail"], lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    failed = [row for row in rows if row["result"] != "PASS"]
    print(json.dumps({"stage":"6.2C", "tests":len(rows), "passed":len(rows)-len(failed), "failed":len(failed),
                      "result":"PASS" if not failed else "FAIL", "authority":AUTHORITY, "network_calls":0,
                      "evidence_writes":0, "extraction_writes":0, "event_writes":0}, sort_keys=True, separators=(",", ":")))
    for row in failed: print(f"FAIL {row['test_id']} {row['test_name']}: {row['detail']}")
    return 1 if failed else 0


if __name__ == "__main__": raise SystemExit(main())
