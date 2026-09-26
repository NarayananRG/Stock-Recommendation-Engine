"""Stage 6.2D deterministic candidate-to-event materialization acceptance tests."""
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

from stage6_candidates import CandidateStore
from stage6_connectors.live_registries import (RBI_ENTITY_ID, RBI_SOURCE_ID, SEBI_ENTITY_ID,
                                               SEBI_SOURCE_ID, build_multisource_registries)
from stage6_events import EventStore
from stage6_extraction import ExtractionStore
from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from stage6_ingestion.evidence_store import IngestionStore
from stage6_materialization import (AUTHORITY, MATERIALIZATION_SCHEMA_VERSION, MATERIALIZER_VERSION,
                                    POLICY_ID, POLICY_VERSION, MaterializationConflict,
                                    MaterializationIntegrityFailure, MaterializationStore,
                                    Stage6MaterializationError, load_policy, materialization_identity,
                                    validate_materialization, validate_policy)
from stage6_materialization.event_mapper import build_expected_event


FIXTURE_PATH = STAGE_ROOT / "fixtures" / "stage6_2d" / "materialization_cases.json"
RESULT_PATH = STAGE_ROOT / "results" / "stage6_2d_test_results.csv"
BASELINE_2C_TAG = "stage6-2c-event-candidate-classification-baseline"
BASELINE_2C_COMMIT = "5f1955aa83b02dfbd2bac28916cf64d55e3853c1"
BASELINE_2B_TAG = "stage6-2b-rss-item-extraction-baseline"
BASELINE_2A_TAG = "stage6-2a-event-intelligence-foundation-baseline"
BASELINE_1C_TAG = "stage6-1c-multisource-rss-ingestion-baseline"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
EXTRACTION_CUTOFF = "2026-09-26T08:00:01.000000Z"
MATERIALIZATION_CUTOFF = "2026-09-26T08:30:00.000000Z"
LATER_CUTOFF = "2026-09-26T09:00:00.000000Z"
CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
POLICY, POLICY_JSON, POLICY_HASH = load_policy()
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
    items = [f"<item><title>{escape(item['title'])}</title><guid>{item['case_id']}</guid></item>"
             for item in CASES if item["source_id"] == source_id]
    return ("<rss><channel><title>Synthetic Stage 6.2D cases</title>" + "".join(items) + "</channel></rss>").encode()


def capture(store: IngestionStore, registries: dict, source_id: str) -> dict:
    entity = RBI_ENTITY_ID if source_id == RBI_SOURCE_ID else SEBI_ENTITY_ID
    return store.capture_evidence(
        idempotency_key="stage6-2d-" + source_id, source_registry_snapshot_id=registries["source_v2"]["registry_snapshot_id"],
        entity_registry_snapshot_id=registries["entity_v2"]["registry_snapshot_id"], source_id=source_id,
        source_reference="fixture://stage6-2d/" + source_id, raw_payload=feed_for(source_id),
        content_type="application/rss+xml", publication_timestamp_utc="2026-09-25T00:00:00Z",
        observed_timestamp_utc="2026-09-26T08:00:00Z", retrieved_timestamp_utc="2026-09-26T08:00:01Z",
        entity_ids=[entity])["record"]


@contextmanager
def fresh_environment():
    with tempfile.TemporaryDirectory(prefix="stage6_2d_test_") as folder:
        root = Path(folder); registries = build_multisource_registries()
        ingestion = IngestionStore(root / "ingestion.sqlite3", root / "raw")
        ingestion.import_registry(registries["entity_v1"]); ingestion.import_registry(registries["source_v1"])
        ingestion.import_registry(registries["entity_v2"]); ingestion.import_registry(registries["source_v2"])
        evidence = {source: capture(ingestion, registries, source) for source in (RBI_SOURCE_ID, SEBI_SOURCE_ID)}
        extraction = ExtractionStore(root / "extraction.sqlite3", ingestion)
        extraction_batches = {source: extraction.extract(parent_evidence_id=record["evidence_id"],
                              extraction_cutoff=EXTRACTION_CUTOFF)["batch_id"] for source, record in evidence.items()}
        candidates = CandidateStore(root / "candidates.sqlite3", extraction)
        classification_batches = {source: candidates.classify_batch(extraction_batch_id=batch,
                                  classification_cutoff=EXTRACTION_CUTOFF)["classification_batch_id"]
                                  for source, batch in extraction_batches.items()}
        events = EventStore(root / "events.sqlite3", ingestion)
        materializations = MaterializationStore(root / "materializations.sqlite3", candidates, events)
        try:
            yield ingestion, extraction, candidates, events, materializations, classification_batches, evidence, root
        finally:
            for store in (materializations, events, candidates, extraction, ingestion):
                try: store.close()
                except sqlite3.Error: pass


def materialize_all(store: MaterializationStore, batches: dict[str, str], cutoff: str = MATERIALIZATION_CUTOFF) -> dict[str, dict]:
    output = {}
    for source, batch_id in batches.items():
        for record in store.materialize_batch(classification_batch_id=batch_id, materialization_cutoff=cutoff)["records"]:
            candidate_json = store.candidate_store.connection.execute(
                "SELECT canonical_json FROM candidate_records WHERE candidate_id=?", (record["candidate_id"],)).fetchone()[0]
            candidate = json.loads(candidate_json)
            extraction_json = store.candidate_store.extraction_store.connection.execute(
                "SELECT canonical_json FROM extracted_items WHERE extraction_id=?", (candidate["input_extraction_id"],)).fetchone()[0]
            output[json.loads(extraction_json)["guid_or_atom_id"]] = record
    return output


def restore_trigger(store: MaterializationStore, table: str, operation: str) -> None:
    store.connection.executescript(f"""
    CREATE TRIGGER protect_{table}_{operation.lower()} BEFORE {operation} ON {table}
    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_{operation}'); END;
    """)


def mutate_record(store: MaterializationStore, mutator, expected: str, sync_typed: bool = False) -> None:
    row = store.connection.execute("SELECT * FROM materialization_records ORDER BY materialization_id LIMIT 1").fetchone()
    record = json.loads(row["canonical_json"]); mutator(record)
    store.connection.execute("DROP TRIGGER protect_materialization_records_update")
    if sync_typed:
        store.connection.execute("UPDATE materialization_records SET canonical_json=?,decision_status=?,event_record_hash=?,record_hash=? WHERE materialization_id=?",
            (canonical_json(record), record["decision_status"], record["event_record_hash"], record["record_hash"], row["materialization_id"]))
    else:
        store.connection.execute("UPDATE materialization_records SET canonical_json=? WHERE materialization_id=?",
                                 (canonical_json(record), row["materialization_id"]))
    restore_trigger(store, "materialization_records", "UPDATE"); store.connection.commit()
    expect(MaterializationIntegrityFailure, store.integrity_check, expected)


# Baseline and input.
@check("BASELINE", "Stage 6.2C tag exact ancestor")
def _():
    require(git("rev-parse", f"{BASELINE_2C_TAG}^{{}}") == BASELINE_2C_COMMIT)
    subprocess.check_call(["git", "merge-base", "--is-ancestor", BASELINE_2C_COMMIT, "HEAD"], cwd=REPO_ROOT)

@check("BASELINE", "authority is SHADOW_ONLY")
def _(): require(AUTHORITY == "SHADOW_ONLY")

@check("INPUT", "valid complete classification batch accepted")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        require(store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=MATERIALIZATION_CUTOFF)["status"] == "CREATED")

@check("INPUT", "missing classification batch rejected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        expect(Stage6MaterializationError, lambda: store.materialize_batch(classification_batch_id="MISSING", materialization_cutoff=MATERIALIZATION_CUTOFF), "NOT_FOUND")

@check("INPUT", "tampered candidate store rejected transitively")
def _():
    with fresh_environment() as (_, _, candidates, _, store, batches, _, _):
        candidates.connection.execute("DROP TRIGGER protect_candidate_records_update")
        candidates.connection.execute("UPDATE candidate_records SET record_hash=? WHERE candidate_id=(SELECT candidate_id FROM candidate_records LIMIT 1)", ("f"*64,)); candidates.connection.commit()
        expect(MaterializationIntegrityFailure, lambda: store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=MATERIALIZATION_CUTOFF), "UPSTREAM_CANDIDATE")

@check("INPUT", "invalid candidate status rejected transitively")
def _():
    with fresh_environment() as (_, _, candidates, _, store, batches, _, _):
        candidates.connection.execute("DROP TRIGGER protect_candidate_records_update")
        candidates.connection.execute("UPDATE candidate_records SET classification_status='INVALID'"); candidates.connection.commit()
        expect(MaterializationIntegrityFailure, lambda: store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=MATERIALIZATION_CUTOFF), "UPSTREAM_CANDIDATE")


# Policy closure.
@check("POLICY", "valid policy accepted")
def _(): require(validate_policy(deepcopy(POLICY)) == POLICY)

@check("POLICY", "policy canonical hash deterministic")
def _(): require(load_policy()[2] == POLICY_HASH == canonical_hash(POLICY))

def invalid_policy(field: str, value: object) -> None:
    policy = deepcopy(POLICY); policy[field] = value
    expect(Stage6MaterializationError, lambda: validate_policy(policy), "POLICY")

@check("POLICY", "wrong policy identity fields rejected")
def _():
    invalid_policy("schema_version", "WRONG"); invalid_policy("policy_id", "WRONG")
    invalid_policy("policy_version", 2); invalid_policy("materializer_version", "WRONG")

@check("POLICY", "unknown eligible status rejected")
def _(): invalid_policy("eligible_candidate_status", "AMBIGUOUS")

@check("POLICY", "wrong conservative defaults rejected")
def _():
    for field, value in (("event_status", "ACTIVE"), ("direction", "POSITIVE"), ("severity", "HIGH"),
                         ("materiality", "MATERIAL"), ("event_horizon", "DAYS"),
                         ("causality_assessment", "PLAUSIBLE_CONTRIBUTOR")):
        policy = deepcopy(POLICY); policy["event_defaults"][field] = value
        expect(Stage6MaterializationError, lambda p=policy: validate_policy(p), "DEFAULTS")

@check("POLICY", "wrong confidence rejected")
def _():
    policy = deepcopy(POLICY); policy["event_defaults"]["confidence"] = 0.5
    expect(Stage6MaterializationError, lambda: validate_policy(policy), "DEFAULTS")
    policy = deepcopy(POLICY); policy["event_defaults"]["confidence"] = 0
    expect(Stage6MaterializationError, lambda: validate_policy(policy), "CONFIDENCE_TYPE")

@check("POLICY", "wrong corroboration rejected")
def _():
    policy = deepcopy(POLICY); policy["event_defaults"]["corroboration_status"] = "CONFIRMED"
    expect(Stage6MaterializationError, lambda: validate_policy(policy), "DEFAULTS")

@check("POLICY", "non-empty inference defaults rejected")
def _():
    for field in ("entities", "sectors", "geographies", "commodities", "currencies", "transmission_channels", "evidence_conflicts"):
        policy = deepcopy(POLICY); policy["event_defaults"][field] = ["X"]
        expect(Stage6MaterializationError, lambda p=policy: validate_policy(p), "DEFAULTS")


# Eligibility and mapping.
@check("ELIGIBILITY", "MATCHED NO_MATCH AMBIGUOUS decisions are exact")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        records = materialize_all(store, batches)
        require(records["matched_rate_hike"]["decision_status"] == "MATERIALIZED")
        require(records["no_match"]["decision_status"] == "SKIPPED_NO_MATCH")
        require(records["ambiguous"]["decision_status"] == "SKIPPED_AMBIGUOUS")

@check("ELIGIBILITY", "only matched candidates produce events")
def _():
    with fresh_environment() as (_, _, _, events, store, batches, _, _):
        records = materialize_all(store, batches)
        require(events.connection.execute("SELECT COUNT(*) FROM event_records").fetchone()[0] == 3)
        require(records["no_match"]["event_id"] is None and records["ambiguous"]["event_id"] is None)

@check("EVENT_MAPPING", "rate hike rate cut and regulatory action map exactly")
def _():
    with fresh_environment() as (_, _, _, events, store, batches, _, _):
        records = materialize_all(store, batches)
        for case_id, event_type in (("matched_rate_hike", "RATE_HIKE"), ("matched_rate_cut", "RATE_CUT"),
                                    ("matched_regulatory_action", "REGULATORY_ACTION")):
            require(events.get_event(records[case_id]["event_id"], 1)["event_type"] == event_type)

@check("EVENT_MAPPING", "all conservative event defaults exact")
def _():
    with fresh_environment() as (_, _, _, events, store, batches, _, _):
        record = materialize_all(store, batches)["matched_rate_hike"]; event = events.get_event(record["event_id"], 1)
        for field, value in POLICY["event_defaults"].items(): require(event[field] == value, field)

@check("EVENT_MAPPING", "confidence zero is placeholder and no entities inferred")
def _():
    with fresh_environment() as (_, _, _, events, store, batches, _, _):
        records = materialize_all(store, batches)
        for record in records.values():
            if record["event_id"]:
                event = events.get_event(record["event_id"], 1); require(event["confidence"] == 0.0 and event["entities"] == [])

@check("EVIDENCE", "event binds exact parent evidence and registry snapshot")
def _():
    with fresh_environment() as (_, _, _, events, store, batches, evidence, _):
        records = materialize_all(store, batches)
        event = events.get_event(records["matched_rate_hike"]["event_id"], 1); source = evidence[RBI_SOURCE_ID]
        require(event["source_evidence_ids"] == [source["evidence_id"]])
        require(event["entity_resolution_version"] == source["entity_registry_snapshot_id"])

@check("EVIDENCE", "wrong evidence hash rejected transitively")
def _():
    with fresh_environment() as (ingestion, _, _, _, store, batches, _, _):
        ingestion.connection.execute("DROP TRIGGER protect_ingestion_records_update")
        target = ingestion.connection.execute("SELECT record_id FROM ingestion_records WHERE record_kind='EVIDENCE' ORDER BY record_id LIMIT 1").fetchone()[0]
        ingestion.connection.execute("UPDATE ingestion_records SET record_hash=? WHERE record_id=?", ("a"*64,target)); ingestion.connection.commit()
        expect(MaterializationIntegrityFailure, lambda: store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=MATERIALIZATION_CUTOFF), "UPSTREAM_CANDIDATE")

@check("EVIDENCE", "non-primary official evidence rejected")
def _():
    with fresh_environment() as (ingestion, _, _, events, store, batches, evidence, _):
        original = store.candidate_store.integrity_check; event_original = events.integrity_check
        store.candidate_store.integrity_check = lambda: {"result":"PASS"}; events.integrity_check = lambda: {"result":"PASS"}
        row = ingestion.connection.execute("SELECT canonical_json FROM ingestion_records WHERE record_id=?", (evidence[RBI_SOURCE_ID]["evidence_id"],)).fetchone()
        record = json.loads(row[0]); record["authority_level"] = "SECONDARY_INDEPENDENT"
        ingestion.connection.execute("DROP TRIGGER protect_ingestion_records_update")
        ingestion.connection.execute("UPDATE ingestion_records SET canonical_json=? WHERE record_id=?", (canonical_json(record), record["evidence_id"])); ingestion.connection.commit()
        try: expect(Stage6MaterializationError, lambda: store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=MATERIALIZATION_CUTOFF), "PRIMARY_OFFICIAL")
        finally: store.candidate_store.integrity_check = original; events.integrity_check = event_original


# PIT, identity, versioning and counts.
@check("PIT", "classification cutoff equal materialization cutoff accepted")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        require(store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=EXTRACTION_CUTOFF)["status"] == "CREATED")

@check("PIT", "later materialization cutoff accepted")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        require(store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=LATER_CUTOFF)["status"] == "CREATED")

@check("PIT", "earlier materialization cutoff rejected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        expect(Stage6MaterializationError, lambda: store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff="2026-09-26T08:00:00Z"), "BEFORE_CLASSIFICATION")

@check("TIMESTAMP", "first-known retrieval and last-updated materialization cutoff exact")
def _():
    with fresh_environment() as (_, _, _, events, store, batches, evidence, _):
        record = materialize_all(store, batches)["matched_rate_hike"]; event = events.get_event(record["event_id"], 1)
        require(event["first_known_timestamp"] == evidence[RBI_SOURCE_ID]["retrieved_timestamp_utc"])
        require(event["last_updated_timestamp"] == MATERIALIZATION_CUTOFF)
        require(event["first_known_timestamp"] != evidence[RBI_SOURCE_ID]["publication_timestamp_utc"])

@check("IDENTITY", "event key and event ID deterministic per candidate")
def _():
    with fresh_environment() as (_, _, _, events, store, batches, _, _):
        record = materialize_all(store, batches)["matched_rate_hike"]
        key = json.loads(events.connection.execute("SELECT event_key_json FROM event_series WHERE event_id=?", (record["event_id"],)).fetchone()[0])["event_key"]
        require(key == "stage6_2d_candidate:" + record["candidate_id"])

@check("IDENTITY", "different candidates produce separate event series")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        records = materialize_all(store, batches)
        event_ids = {record["event_id"] for record in records.values() if record["event_id"]}
        require(len(event_ids) == 3)

@check("IDENTITY", "materialization identity deterministic and cutoff independent")
def _():
    with fresh_environment() as (_, _, candidates, _, store, batches, _, _):
        candidate = json.loads(candidates.connection.execute("SELECT canonical_json FROM candidate_records LIMIT 1").fetchone()[0])
        require(materialization_identity(candidate, POLICY_HASH) == materialization_identity(candidate, POLICY_HASH))

@check("IDENTITY", "event ID is independent of materialization cutoff")
def _():
    event_ids=[]
    for cutoff in (MATERIALIZATION_CUTOFF,LATER_CUTOFF):
        with fresh_environment() as (_, _, _, events, store, batches, _, _):
            records=materialize_all(store,batches,cutoff); event_ids.append(records["matched_rate_hike"]["event_id"])
    require(event_ids[0]==event_ids[1])

@check("VERSIONING", "only event V1 with null predecessor")
def _():
    with fresh_environment() as (_, _, _, events, store, batches, _, _):
        materialize_all(store, batches)
        for row in events.connection.execute("SELECT canonical_json FROM event_records"):
            event = json.loads(row[0]); require(event["event_version"] == 1 and event["previous_event_version_hash"] is None)

@check("VERSIONING", "materialization API exposes no V2 parameter")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        expect(TypeError, lambda: store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=MATERIALIZATION_CUTOFF, event_version=2))

@check("DECISIONS", "one decision per candidate and counts reconcile")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        result = store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=MATERIALIZATION_CUTOFF)
        batch = store.connection.execute("SELECT * FROM materialization_batches WHERE materialization_batch_id=?", (result["materialization_batch_id"],)).fetchone()
        require((batch["candidate_count"], batch["materialized_count"], batch["skipped_no_match_count"], batch["skipped_ambiguous_count"]) == (4,2,1,1))


# Dependencies, immutability, idempotency and recovery.
@check("DEPENDENCY", "materialized decision has all exact dependencies")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        record = materialize_all(store, batches)["matched_rate_hike"]
        deps = {row["dependency_record_type"]: row for row in store.connection.execute("SELECT * FROM materialization_dependencies WHERE materialization_id=?", (record["materialization_id"],))}
        require(set(deps) == {"EVENT_CANDIDATE","CLASSIFICATION_BATCH","MATERIALIZATION_POLICY","STAGE6_EVENT","EVIDENCE"})
        require((deps["EVENT_CANDIDATE"]["dependency_record_id"], deps["EVENT_CANDIDATE"]["dependency_record_hash"]) == (record["candidate_id"],record["candidate_hash"]))
        require((deps["STAGE6_EVENT"]["dependency_record_id"], deps["STAGE6_EVENT"]["dependency_record_hash"]) == (record["event_id"]+":v1",record["event_record_hash"]))
        require((deps["MATERIALIZATION_POLICY"]["dependency_record_id"],deps["MATERIALIZATION_POLICY"]["dependency_record_hash"])==(POLICY_ID,POLICY_HASH))
        require((deps["EVIDENCE"]["dependency_record_id"],deps["EVIDENCE"]["dependency_record_hash"])==(record["upstream_evidence_id"],record["upstream_evidence_hash"]))
        require(deps["CLASSIFICATION_BATCH"]["dependency_record_id"]==record["classification_batch_id"])

@check("DEPENDENCY", "skipped decision has no event or evidence dependency")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        record = materialize_all(store, batches)["no_match"]
        types = {row[0] for row in store.connection.execute("SELECT dependency_record_type FROM materialization_dependencies WHERE materialization_id=?", (record["materialization_id"],))}
        require(types == {"EVENT_CANDIDATE","CLASSIFICATION_BATCH","MATERIALIZATION_POLICY"})

@check("IMMUTABILITY", "all materialization tables block update and delete")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        materialize_all(store, batches)
        for table in ("materialization_store_meta","materialization_policies","materialization_batches","materialization_records","batch_materializations","materialization_dependencies"):
            expect(sqlite3.DatabaseError, lambda t=table: store.connection.execute(f"UPDATE {t} SET rowid=rowid"), "IMMUTABLE_TABLE_UPDATE")
            expect(sqlite3.DatabaseError, lambda t=table: store.connection.execute(f"DELETE FROM {t}"), "IMMUTABLE_TABLE_DELETE")

@check("IMMUTABILITY", "trigger removal detected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        materialize_all(store, batches); store.connection.execute("DROP TRIGGER protect_materialization_records_delete"); store.connection.commit()
        expect(MaterializationIntegrityFailure, store.integrity_check, "TRIGGER_MISSING")

@check("IDEMPOTENCY", "exact batch rerun idempotent with no duplicates")
def _():
    with fresh_environment() as (_, _, _, events, store, batches, _, _):
        first = store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=MATERIALIZATION_CUTOFF)
        second = store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=MATERIALIZATION_CUTOFF)
        require(second["status"] == "IDEMPOTENT_SUCCESS")
        require(events.connection.execute("SELECT COUNT(*) FROM event_records").fetchone()[0] == 2)
        require(store.connection.execute("SELECT COUNT(*) FROM materialization_records").fetchone()[0] == 4)

@check("IDEMPOTENCY", "later conflicting cutoff for same V1 candidate rejected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID],materialization_cutoff=MATERIALIZATION_CUTOFF)
        expect(Exception,lambda:store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID],materialization_cutoff=LATER_CUTOFF),"INCOMPATIBLE")

@check("IDEMPOTENCY", "incompatible duplicate materialization content rejected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        result=store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID],materialization_cutoff=MATERIALIZATION_CUTOFF)
        store.connection.execute("DROP TRIGGER protect_materialization_records_update")
        store.connection.execute("UPDATE materialization_records SET canonical_json='{}' WHERE materialization_id=(SELECT materialization_id FROM materialization_records LIMIT 1)"); store.connection.commit()
        expect(MaterializationConflict,lambda:store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID],materialization_cutoff=MATERIALIZATION_CUTOFF),"INCOMPATIBLE")

@check("RECOVERY", "orphan event detected and same-batch retry recovers")
def _():
    with fresh_environment() as (_, _, candidates, events, store, batches, _, _):
        batch, candidate_rows = store._classification_batch(batches[RBI_SOURCE_ID]); candidate = next(c for c in candidate_rows if c["classification_status"] == "MATCHED")
        extraction, evidence = store._lineage(candidate); event = build_expected_event(candidate, evidence, MATERIALIZATION_CUTOFF, POLICY)
        events.append_event(event_key="stage6_2d_candidate:"+candidate["candidate_id"], event_version=1,
            previous_event_version_hash=None, source_evidence_ids=[evidence["evidence_id"]], entity_resolution_version=evidence["entity_registry_snapshot_id"],
            event_type=candidate["candidate_event_type"], **POLICY["event_defaults"], first_known_timestamp=evidence["retrieved_timestamp_utc"], last_updated_timestamp=MATERIALIZATION_CUTOFF)
        expect(MaterializationIntegrityFailure, store.integrity_check, "ORPHAN_STAGE6_2D_EVENT")
        require(store.materialize_batch(classification_batch_id=batches[RBI_SOURCE_ID], materialization_cutoff=MATERIALIZATION_CUTOFF)["status"] == "CREATED")
        require(store.integrity_check()["result"] == "PASS")

@check("ORPHAN", "unrelated EventStore event is outside ownership boundary")
def _():
    with fresh_environment() as (_, _, _, events, store, batches, evidence, _):
        source=evidence[RBI_SOURCE_ID]
        events.append_event(event_key="unrelated:event", event_version=1, previous_event_version_hash=None,
            source_evidence_ids=[source["evidence_id"]], entity_resolution_version=source["entity_registry_snapshot_id"],
            event_type="RATE_HIKE", **POLICY["event_defaults"], first_known_timestamp=source["retrieved_timestamp_utc"], last_updated_timestamp=MATERIALIZATION_CUTOFF)
        require(store.integrity_check()["result"] == "PASS")


# Restart adversaries and boundaries.
@check("RESTART_INTEGRITY", "clean full restart integrity passes")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        materialize_all(store, batches); require(store.integrity_check()["result"] == "PASS")

@check("RESTART_INTEGRITY", "policy snapshot tamper detected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        materialize_all(store, batches); store.connection.execute("DROP TRIGGER protect_materialization_policies_update")
        store.connection.execute("UPDATE materialization_policies SET policy_hash=?", ("f"*64,)); restore_trigger(store,"materialization_policies","UPDATE"); store.connection.commit()
        expect(MaterializationIntegrityFailure, store.integrity_check, "POLICY_SNAPSHOT")

@check("RESTART_INTEGRITY", "materialization canonical and hash tamper detected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root): materialize_all(store,batches); mutate_record(store,lambda r:r.update(record_hash="f"*64),"RECORD_HASH")

@check("RESTART_INTEGRITY", "decision status tamper detected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root): materialize_all(store,batches); mutate_record(store,lambda r:r.update(decision_status="INVALID"),"DECISION_STATUS")

@check("RESTART_INTEGRITY", "dependency missing wrong hash type and extra detected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        materialize_all(store,batches); store.connection.execute("DROP TRIGGER protect_materialization_dependencies_update")
        store.connection.execute("UPDATE materialization_dependencies SET dependency_record_hash=? WHERE dependency_record_type='EVENT_CANDIDATE'",("1"*64,)); restore_trigger(store,"materialization_dependencies","UPDATE"); store.connection.commit()
        expect(MaterializationIntegrityFailure,store.integrity_check,"DEPENDENCY_MISMATCH")
    with fresh_environment() as (*_, store, batches, evidence, root):
        materialize_all(store,batches); store.connection.execute("DROP TRIGGER protect_materialization_dependencies_delete")
        store.connection.execute("DELETE FROM materialization_dependencies WHERE dependency_record_type='MATERIALIZATION_POLICY'"); restore_trigger(store,"materialization_dependencies","DELETE"); store.connection.commit()
        expect(MaterializationIntegrityFailure,store.integrity_check,"DEPENDENCY_COVERAGE")

@check("RESTART_INTEGRITY", "wrong dependency type detected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        materialize_all(store,batches); store.connection.execute("PRAGMA ignore_check_constraints=ON")
        store.connection.execute("DROP TRIGGER protect_materialization_dependencies_update")
        store.connection.execute("UPDATE materialization_dependencies SET dependency_record_type='INVALID' WHERE dependency_record_type='EVENT_CANDIDATE'"); restore_trigger(store,"materialization_dependencies","UPDATE"); store.connection.commit()
        expect(MaterializationIntegrityFailure,store.integrity_check,"DEPENDENCY_COVERAGE")

@check("RESTART_INTEGRITY", "extra dependency detected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        materialize_all(store,batches); store.connection.execute("PRAGMA ignore_check_constraints=ON")
        materialization_id=store.connection.execute("SELECT materialization_id FROM materialization_records LIMIT 1").fetchone()[0]
        store.connection.execute("INSERT INTO materialization_dependencies VALUES(?,?,?,?)",(materialization_id,"EXTRA","2"*64,"EXTRA")); store.connection.commit()
        expect(MaterializationIntegrityFailure,store.integrity_check,"DEPENDENCY_COVERAGE")

@check("RESTART_INTEGRITY", "batch count tamper detected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        materialize_all(store,batches); store.connection.execute("DROP TRIGGER protect_materialization_batches_update")
        store.connection.execute("UPDATE materialization_batches SET candidate_count=999"); restore_trigger(store,"materialization_batches","UPDATE"); store.connection.commit()
        expect(MaterializationIntegrityFailure,store.integrity_check,"BATCH_COUNT")

@check("RESTART_INTEGRITY", "orphan decision detected")
def _():
    with fresh_environment() as (*_, store, batches, evidence, root):
        materialize_all(store,batches); store.connection.execute("INSERT INTO materialization_records VALUES(?,?,?,?,?,?,?,?,?)",("S6MAT_ORPHAN","C","a"*64,"SKIPPED_NO_MATCH",None,None,None,"b"*64,"{}")); store.connection.commit()
        expect(MaterializationIntegrityFailure,store.integrity_check,"ORPHAN_OR_COVERAGE")

@check("RESTART_INTEGRITY", "EventStore event hash tamper detected transitively")
def _():
    with fresh_environment() as (_,_,_,events,store,batches,_,_):
        materialize_all(store,batches); events.connection.execute("DROP TRIGGER protect_event_records_update")
        events.connection.execute("UPDATE event_records SET record_hash=? WHERE event_id=(SELECT event_id FROM event_records LIMIT 1)",("3"*64,)); events.connection.commit()
        expect(MaterializationIntegrityFailure,store.integrity_check,"UPSTREAM_EVENT")

@check("RESTART_INTEGRITY", "materialization replay mismatch detected")
def _():
    with fresh_environment() as (*_,store,batches,evidence,root):
        materialize_all(store,batches)
        def wrong(record):
            record["materialization_cutoff"]=LATER_CUTOFF
            record["record_hash"]=canonical_hash(without(record,"record_hash"))
        mutate_record(store,wrong,"REPLAY",sync_typed=True)

@check("BOUNDARY", "zero evidence extraction and candidate writes")
def _():
    with fresh_environment() as (ingestion, extraction, candidates, events, store, batches, _, _):
        before=(ingestion.connection.execute("SELECT COUNT(*) FROM ingestion_records").fetchone()[0],extraction.connection.execute("SELECT COUNT(*) FROM extracted_items").fetchone()[0],candidates.connection.execute("SELECT COUNT(*) FROM candidate_records").fetchone()[0])
        materialize_all(store,batches)
        after=(ingestion.connection.execute("SELECT COUNT(*) FROM ingestion_records").fetchone()[0],extraction.connection.execute("SELECT COUNT(*) FROM extracted_items").fetchone()[0],candidates.connection.execute("SELECT COUNT(*) FROM candidate_records").fetchone()[0])
        require(before==after)

@check("NETWORK_AI_TRADING", "no network AI ML sentiment or trading implementation")
def _():
    prohibited_imports={"socket","requests","urllib","http","aiohttp","openai","transformers"}; text=""
    for path in (STAGE_ROOT/"stage6_materialization").glob("*.py"):
        source=path.read_text(encoding="utf-8"); text+=source.casefold(); tree=ast.parse(source)
        imports={node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node,ast.Import)}
        imports|={str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)}
        require(not imports.intersection(prohibited_imports))
    for token in ("requests.get","openai","transformers","embedding","sentiment model","buy_signal","sell_signal","broker_order","position_size"):
        require(token not in text)

@check("NETWORK_AI_TRADING", "socket sentinel proves zero network")
def _():
    with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK_USED")):
        with fresh_environment() as (*_, store, batches, evidence, root): materialize_all(store,batches)

@check("BASELINE", "all frozen paths unchanged")
def _():
    architecture=["Stage 6/Stage6_Master_Architecture.md","Stage 6/contracts","Stage 6/policy","Stage 6/scripts/validate_stage6_0.py","Stage 6/results/stage6_0_architecture_contract.json"]
    require(git("diff","--name-only",ARCHITECTURE_TAG,"--",*architecture)=="")
    require(git("diff","--name-only",BASELINE_1C_TAG,"--","Stage 6/stage6_ingestion","Stage 6/stage6_connectors")=="")
    for ref,paths in ((BASELINE_2A_TAG,["Stage 6/stage6_events","Stage 6/fixtures/stage6_2a","Stage 6/results/stage6_2a_contract.json","Stage 6/results/stage6_2a_test_results.csv","Stage 6/Stage6_2A_Delivery_Report.md"]),(BASELINE_2B_TAG,["Stage 6/stage6_extraction","Stage 6/fixtures/stage6_2b","Stage 6/results/stage6_2b_contract.json","Stage 6/results/stage6_2b_test_results.csv","Stage 6/Stage6_2B_Delivery_Report.md"]),(BASELINE_2C_TAG,["Stage 6/stage6_candidates","Stage 6/fixtures/stage6_2c","Stage 6/results/stage6_2c_contract.json","Stage 6/results/stage6_2c_test_results.csv","Stage 6/Stage6_2C_Delivery_Report.md"])):
        require(git("diff","--name-only",ref,"--",*paths)=="")
    require(git("diff","--name-only",PRODUCTION_TAG,"--","Stage 5D")=="")


def main() -> int:
    rows=[]
    for number,(category,name,function) in enumerate(CHECKS,1):
        try:
            with mock.patch.object(socket,"socket",side_effect=AssertionError("STAGE6_2D_NETWORK_USED")): function()
            rows.append({"test_id":f"S6_2D_{number:03d}","category":category,"test_name":name,"result":"PASS","detail":""})
        except Exception as exc:
            rows.append({"test_id":f"S6_2D_{number:03d}","category":category,"test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}:{exc}"})
    RESULT_PATH.parent.mkdir(parents=True,exist_ok=True)
    with RESULT_PATH.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=["test_id","category","test_name","result","detail"],lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    failed=[row for row in rows if row["result"]!="PASS"]
    print(json.dumps({"stage":"6.2D","tests":len(rows),"passed":len(rows)-len(failed),"failed":len(failed),"result":"PASS" if not failed else "FAIL","authority":AUTHORITY,"network_calls":0,"evidence_writes":0,"extraction_writes":0,"candidate_writes":0},sort_keys=True,separators=(",",":")))
    for row in failed: print("FAIL",row["test_id"],row["test_name"]+":",row["detail"])
    return 1 if failed else 0


if __name__=="__main__": raise SystemExit(main())
