"""Stage 6.1A deterministic, fixture-only acceptance and adversarial tests."""
from __future__ import annotations

import ast
import csv
import json
import math
import shutil
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

from stage6_ingestion.canonical import canonical_hash, canonical_json, sha256_bytes, utc_timestamp, without
from stage6_ingestion.errors import IdempotencyConflict, IntegrityFailure, ResolutionError, Stage6IngestionError
from stage6_ingestion.evidence_store import (
    ARCHITECTURE_COMMIT, ARCHITECTURE_TAG, AUTHORITY, IngestionStore,
)
from stage6_ingestion.fixtures import build_fixture_registries
from stage6_ingestion.raw_store import RawPayloadStore
from stage6_ingestion.registry import (
    build_entity_registry, build_source_registry, resolve_alias, resolve_entity,
    resolve_source_record, resolve_ticker, verify_entity_registry, verify_source_registry,
)


BASELINE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
BASELINE_COMMIT = "d5bc19c7c2341f56bcaa8c890e0d95979dca878b"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
PRODUCTION_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"
RESULT_PATH = STAGE_ROOT / "results" / "stage6_1a_test_results.csv"
FIXTURE_SOURCE = "S6FIX_SOURCE_OFFICIAL_001"
FIXTURE_ENTITY = "S6FIX_COMPANY_001"
REGISTRIES = build_fixture_registries()
CHECKS: list[tuple[str, str, object]] = []


def check(category: str, name: str):
    def register(function):
        CHECKS.append((category, name, function))
        return function
    return register


def require(condition: object, message: str = "assertion failed") -> None:
    if not condition:
        raise AssertionError(message)


def expect(error: type[BaseException], function, contains: str | None = None) -> BaseException:
    try:
        function()
    except error as exc:
        if contains is not None:
            require(contains in str(exc), f"expected {contains!r} in {exc!r}")
        return exc
    raise AssertionError(f"expected {error.__name__}")


@contextmanager
def fresh_store(import_v2: bool = False):
    with tempfile.TemporaryDirectory(prefix="stage6_1a_test_") as folder:
        root = Path(folder)
        store = IngestionStore(root / "store.sqlite3", root / "raw")
        store.import_registry(REGISTRIES["entity_v1"])
        store.import_registry(REGISTRIES["source_v1"])
        if import_v2:
            store.import_registry(REGISTRIES["entity_v2"])
            store.import_registry(REGISTRIES["source_v2"])
        try:
            yield store, root
        finally:
            store.close()


def capture(store: IngestionStore, key: str = "evidence-1", payload: bytes = b"fixture payload",
            source_registry: str = "source_v1", entity_registry: str = "entity_v1",
            publication: str | None = "2026-05-01T09:00:00Z",
            observed: str = "2026-05-01T09:01:00Z", retrieved: str = "2026-05-01T09:02:00Z",
            **links) -> dict:
    return store.capture_evidence(
        idempotency_key=key,
        source_registry_snapshot_id=REGISTRIES[source_registry]["registry_snapshot_id"],
        entity_registry_snapshot_id=REGISTRIES[entity_registry]["registry_snapshot_id"],
        source_id=FIXTURE_SOURCE,
        source_reference=f"fixture://{key}", raw_payload=payload, content_type="text/plain",
        publication_timestamp_utc=publication, observed_timestamp_utc=observed,
        retrieved_timestamp_utc=retrieved, entity_ids=[FIXTURE_ENTITY], **links,
    )


def failure(store: IngestionStore, key: str = "failure-1", status: str = "FAILED",
            attempted: str = "2026-05-01T09:00:00Z", source_registry: str = "source_v1") -> dict:
    return store.capture_acquisition_failure(
        idempotency_key=key,
        source_registry_snapshot_id=REGISTRIES[source_registry]["registry_snapshot_id"],
        entity_registry_snapshot_id=REGISTRIES["entity_v1"]["registry_snapshot_id"],
        source_id=FIXTURE_SOURCE, source_reference=f"fixture://{key}", retrieval_status=status,
        failure_reason="Synthetic acquisition failed", failure_stage="FIXTURE_READ",
        attempted_at_utc=attempted, entity_ids=[FIXTURE_ENTITY],
    )


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=REPO_ROOT, text=True).strip()


@check("ARCHITECTURE_IDENTITY", "corrected frozen architecture tag pinned")
def _(): require(ARCHITECTURE_TAG == BASELINE_TAG)

@check("ARCHITECTURE_IDENTITY", "corrected frozen architecture commit pinned")
def _(): require(ARCHITECTURE_COMMIT == BASELINE_COMMIT)

@check("ARCHITECTURE_IDENTITY", "baseline tag resolves to pinned commit")
def _(): require(git("rev-parse", f"{BASELINE_TAG}^{{}}") == BASELINE_COMMIT)

@check("ARCHITECTURE_IDENTITY", "HEAD ancestry includes corrected baseline")
def _(): subprocess.check_call(["git", "merge-base", "--is-ancestor", BASELINE_COMMIT, "HEAD"], cwd=REPO_ROOT)

@check("ARCHITECTURE_IDENTITY", "authority is shadow only")
def _(): require(AUTHORITY == "SHADOW_ONLY")

@check("CANONICAL_HASHING", "key order independent canonical hash")
def _(): require(canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2}))

@check("CANONICAL_HASHING", "UTF-8 canonical encoding stable")
def _(): require(canonical_json({"name": "தமிழ்"}).encode("utf-8").decode("utf-8") == '{"name":"தமிழ்"}')

@check("CANONICAL_HASHING", "NaN rejected")
def _(): expect(Stage6IngestionError, lambda: canonical_json({"x": math.nan}), "NON_CANONICAL_VALUE")

@check("CANONICAL_HASHING", "unsupported value rejected")
def _(): expect(Stage6IngestionError, lambda: canonical_json({1, 2}), "NON_CANONICAL_VALUE")

@check("REGISTRY_BUILDING", "valid entity registry V1")
def _(): require(verify_entity_registry(REGISTRIES["entity_v1"])["registry_version"] == 1)

@check("REGISTRY_BUILDING", "valid source registry V1")
def _(): require(verify_source_registry(REGISTRIES["source_v1"])["registry_version"] == 1)

@check("REGISTRY_BUILDING", "entity snapshot identity deterministic")
def _(): require(build_fixture_registries()["entity_v1"]["registry_snapshot_id"] == REGISTRIES["entity_v1"]["registry_snapshot_id"])

@check("REGISTRY_BUILDING", "source registry hash deterministic")
def _(): require(build_fixture_registries()["source_v1"]["registry_hash"] == REGISTRIES["source_v1"]["registry_hash"])

@check("REGISTRY_BUILDING", "entity per-record hashes exact")
def _():
    for row in REGISTRIES["entity_v1"]["entities"]: require(row["record_hash"] == canonical_hash(without(row, "record_hash")))

@check("REGISTRY_BUILDING", "source per-record hashes exact")
def _():
    for row in REGISTRIES["source_v1"]["sources"]: require(row["record_hash"] == canonical_hash(without(row, "record_hash")))

@check("REGISTRY_BUILDING", "entity V2 chain exact")
def _(): require(verify_entity_registry(REGISTRIES["entity_v2"], REGISTRIES["entity_v1"])["previous_registry_hash"] == REGISTRIES["entity_v1"]["registry_hash"])

@check("REGISTRY_BUILDING", "source V2 chain exact")
def _(): require(verify_source_registry(REGISTRIES["source_v2"], REGISTRIES["source_v1"])["previous_registry_hash"] == REGISTRIES["source_v1"]["registry_hash"])

@check("REGISTRY_BUILDING", "version gap rejected")
def _():
    bad = deepcopy(REGISTRIES["source_v2"]); bad["registry_version"] = 3
    expect(IntegrityFailure, lambda: verify_source_registry(bad, REGISTRIES["source_v1"]), "REGISTRY_VERSION_GAP")

@check("REGISTRY_BUILDING", "incorrect previous registry hash rejected")
def _():
    bad = deepcopy(REGISTRIES["entity_v2"]); bad["previous_registry_hash"] = "0" * 64
    expect(IntegrityFailure, lambda: verify_entity_registry(bad, REGISTRIES["entity_v1"]), "REGISTRY_PREVIOUS_HASH_MISMATCH")

@check("REGISTRY_BUILDING", "record lineage mismatch rejected")
def _():
    bad = deepcopy(REGISTRIES["source_v2"]); bad["sources"][0]["previous_version_hash"] = "0" * 64
    bad["sources"][0]["record_hash"] = canonical_hash(without(bad["sources"][0], "record_hash"))
    identity = without(bad, "registry_snapshot_id", "registry_hash")
    bad["registry_snapshot_id"] = "S6SRCREG_" + canonical_hash(identity)[:24]
    bad["registry_hash"] = canonical_hash(without(bad, "registry_hash"))
    expect(IntegrityFailure, lambda: verify_source_registry(bad, REGISTRIES["source_v1"]), "RECORD_LINEAGE_INVALID")

@check("REGISTRY_TAMPERING", "source record tamper rejected")
def _():
    bad = deepcopy(REGISTRIES["source_v1"]); bad["sources"][0]["source_name"] = "tampered"
    expect(IntegrityFailure, lambda: verify_source_registry(bad), "REGISTRY_RECORD_HASH_MISMATCH")

@check("REGISTRY_TAMPERING", "entity record tamper rejected")
def _():
    bad = deepcopy(REGISTRIES["entity_v1"]); bad["entities"][0]["canonical_name"] = "tampered"
    expect(IntegrityFailure, lambda: verify_entity_registry(bad), "REGISTRY_RECORD_HASH_MISMATCH")

@check("REGISTRY_TAMPERING", "entity root registry tamper rejected")
def _():
    bad = deepcopy(REGISTRIES["entity_v1"]); bad["as_of_timestamp"] = "2026-01-03T00:00:00.000000Z"
    expect(IntegrityFailure, lambda: verify_entity_registry(bad), "REGISTRY_SNAPSHOT_ID_MISMATCH")

@check("REGISTRY_TAMPERING", "unexpected registry record field rejected")
def _():
    bad = deepcopy(REGISTRIES["source_v1"]); bad["sources"][0]["unexpected"] = True
    bad["sources"][0]["record_hash"] = canonical_hash(without(bad["sources"][0], "record_hash"))
    expect(IntegrityFailure, lambda: verify_source_registry(bad), "REGISTRY_RECORD_FIELDS_MISMATCH")

@check("PIT_ENTITY_RESOLUTION", "historical old ticker resolves")
def _(): require(resolve_ticker(REGISTRIES["entity_v1"], "FIXTURE_EXCHANGE", "FIXOLD", "2026-05-01T00:00:00Z")["entity_id"] == FIXTURE_ENTITY)

@check("PIT_ENTITY_RESOLUTION", "future ticker invisible historically")
def _(): expect(ResolutionError, lambda: resolve_ticker(REGISTRIES["entity_v1"], "FIXTURE_EXCHANGE", "FIXNEW", "2026-05-01T00:00:00Z"))

@check("PIT_ENTITY_RESOLUTION", "later ticker resolves")
def _(): require(resolve_ticker(REGISTRIES["entity_v1"], "FIXTURE_EXCHANGE", "FIXNEW", "2026-08-01T00:00:00Z")["entity_id"] == FIXTURE_ENTITY)

@check("PIT_ENTITY_RESOLUTION", "historical alias resolves")
def _(): require(resolve_alias(REGISTRIES["entity_v1"], "Fixture Legacy Tech", "2026-05-01T00:00:00Z")["entity_id"] == FIXTURE_ENTITY)

@check("PIT_ENTITY_RESOLUTION", "future alias invisible historically")
def _(): expect(ResolutionError, lambda: resolve_alias(REGISTRIES["entity_v1"], "Fixture Technologies", "2026-05-01T00:00:00Z"))

@check("PIT_ENTITY_RESOLUTION", "unknown entity rejected")
def _(): expect(ResolutionError, lambda: resolve_entity(REGISTRIES["entity_v1"], "UNKNOWN", "2026-05-01T00:00:00Z"))

@check("PIT_ENTITY_RESOLUTION", "ambiguous ticker mapping rejected")
def _():
    records = json.loads((STAGE_ROOT / "fixtures/stage6_1a/entity_records_v1.json").read_text(encoding="utf-8"))
    duplicate = deepcopy(records[0]); duplicate["entity_id"] = "S6FIX_COMPANY_002"; duplicate["canonical_name"] = "Fixture Duplicate"; duplicate["legal_name"] = "Fixture Duplicate Limited"
    expect(IntegrityFailure, lambda: build_entity_registry(records + [duplicate], "2026-01-02T00:00:00Z"), "AMBIGUOUS_TICKER_MAPPING")

@check("SOURCE_RESOLUTION", "source exists at valid cutoff")
def _(): require(resolve_source_record(REGISTRIES["source_v1"], FIXTURE_SOURCE, "2026-05-01T00:00:00Z")["source_id"] == FIXTURE_SOURCE)

@check("SOURCE_RESOLUTION", "source outside effective interval rejected")
def _(): expect(ResolutionError, lambda: resolve_source_record(REGISTRIES["source_v1"], FIXTURE_SOURCE, "2025-01-01T00:00:00Z"), "SOURCE_OUTSIDE_EFFECTIVE_INTERVAL")

@check("SOURCE_RESOLUTION", "disabled source handled safely")
def _():
    records = json.loads((STAGE_ROOT / "fixtures/stage6_1a/source_records_v1.json").read_text(encoding="utf-8")); records[0]["enabled"] = False
    snapshot = build_source_registry(records, "2026-01-02T00:00:00Z")
    expect(ResolutionError, lambda: resolve_source_record(snapshot, FIXTURE_SOURCE, "2026-05-01T00:00:00Z"), "SOURCE_DISABLED_OR_UNVERIFIED")

@check("SOURCE_RESOLUTION", "unverified source handled safely")
def _():
    records = json.loads((STAGE_ROOT / "fixtures/stage6_1a/source_records_v1.json").read_text(encoding="utf-8")); records[0]["verification_status"] = "PENDING_REVIEW"
    snapshot = build_source_registry(records, "2026-01-02T00:00:00Z")
    expect(ResolutionError, lambda: resolve_source_record(snapshot, FIXTURE_SOURCE, "2026-05-01T00:00:00Z"), "SOURCE_DISABLED_OR_UNVERIFIED")

@check("SUCCESSFUL_EVIDENCE", "raw bytes stored content addressably")
def _():
    with fresh_store() as (store, _):
        record = capture(store)["record"]; require(store.raw_store.path_for(record["raw_payload_hash"]).read_bytes() == b"fixture payload")

@check("SUCCESSFUL_EVIDENCE", "payload hash exact")
def _():
    with fresh_store() as (store, _): require(capture(store)["record"]["raw_payload_hash"] == sha256_bytes(b"fixture payload"))

@check("SUCCESSFUL_EVIDENCE", "record hash exact")
def _():
    with fresh_store() as (store, _):
        record = capture(store)["record"]; require(record["record_hash"] == canonical_hash(without(record, "record_hash")))

@check("SUCCESSFUL_EVIDENCE", "source registry binding exact")
def _():
    with fresh_store() as (store, _):
        record = capture(store)["record"]; require(record["source_registry_hash"] == REGISTRIES["source_v1"]["registry_hash"])

@check("SUCCESSFUL_EVIDENCE", "entity registry binding exact")
def _():
    with fresh_store() as (store, _):
        record = capture(store)["record"]; require(record["entity_registry_hash"] == REGISTRIES["entity_v1"]["registry_hash"])

@check("SUCCESSFUL_EVIDENCE", "source record version and hash derived internally")
def _():
    with fresh_store() as (store, _):
        record = capture(store)["record"]; source = REGISTRIES["source_v1"]["sources"][0]
        require((record["source_record_version"], record["source_record_hash"]) == (source["source_record_version"], source["record_hash"]))

@check("SUCCESSFUL_EVIDENCE", "authority derived internally")
def _():
    with fresh_store() as (store, _): require(capture(store)["record"]["authority_level"] == "PRIMARY_OFFICIAL")

@check("SUCCESSFUL_EVIDENCE", "unknown attached entity rejected")
def _():
    with fresh_store() as (store, _):
        expect(ResolutionError, lambda: store.capture_evidence(idempotency_key="bad-entity", source_registry_snapshot_id=REGISTRIES["source_v1"]["registry_snapshot_id"], entity_registry_snapshot_id=REGISTRIES["entity_v1"]["registry_snapshot_id"], source_id=FIXTURE_SOURCE, source_reference="fixture://bad", raw_payload=b"x", content_type="text/plain", publication_timestamp_utc=None, observed_timestamp_utc="2026-05-01T00:00:00Z", retrieved_timestamp_utc="2026-05-01T00:00:01Z", entity_ids=["UNKNOWN"]))

@check("SUCCESSFUL_EVIDENCE", "content hash is exact raw bytes hash")
def _():
    with fresh_store() as (store, _):
        record = capture(store)["record"]; require(record["content_hash"] == record["raw_payload_hash"])

@check("SUCCESSFUL_EVIDENCE", "evidence envelope field set matches frozen contract")
def _():
    required = set(json.loads((STAGE_ROOT / "contracts/evidence.schema.json").read_text(encoding="utf-8"))["required"])
    with fresh_store() as (store, _): require(set(capture(store)["record"]) == required)

@check("TIMESTAMPS", "known publication chronology accepted")
def _():
    with fresh_store() as (store, _): require(capture(store)["status"] == "CREATED")

@check("TIMESTAMPS", "publication after observation rejected")
def _():
    with fresh_store() as (store, _): expect(Stage6IngestionError, lambda: capture(store, publication="2026-05-01T09:02:00Z"), "EVIDENCE_TIMESTAMP_CHRONOLOGY_INVALID")

@check("TIMESTAMPS", "observation after retrieval rejected")
def _():
    with fresh_store() as (store, _): expect(Stage6IngestionError, lambda: capture(store, observed="2026-05-01T09:03:00Z"), "EVIDENCE_TIMESTAMP_CHRONOLOGY_INVALID")

@check("TIMESTAMPS", "naive timestamp rejected")
def _(): expect(Stage6IngestionError, lambda: utc_timestamp("2026-05-01T09:00:00", "test"), "NAIVE_TIMESTAMP")

@check("TIMESTAMPS", "publication null accepted")
def _():
    with fresh_store() as (store, _): require(capture(store, publication=None)["record"]["publication_timestamp_utc"] is None)

@check("TIMESTAMPS", "publication null does not inherit observation")
def _():
    with fresh_store() as (store, _):
        record = capture(store, publication=None)["record"]; require(record["publication_timestamp_utc"] is None and record["observed_timestamp_utc"] is not None)

@check("FAILED_ACQUISITION", "FAILED no-payload record valid")
def _():
    with fresh_store() as (store, _): require(failure(store)["record"]["raw_payload_hash"] is None)

@check("FAILED_ACQUISITION", "NOT_FOUND no-payload record valid")
def _():
    with fresh_store() as (store, _): require(failure(store, status="NOT_FOUND")["record"]["retrieval_status"] == "NOT_FOUND")

@check("FAILED_ACQUISITION", "ACCESS_DENIED no-payload record valid")
def _():
    with fresh_store() as (store, _): require(failure(store, status="ACCESS_DENIED")["record"]["retrieval_status"] == "ACCESS_DENIED")

@check("FAILED_ACQUISITION", "failure reason required")
def _():
    with fresh_store() as (store, _):
        expect(Stage6IngestionError, lambda: store.capture_acquisition_failure(idempotency_key="bad", source_registry_snapshot_id=REGISTRIES["source_v1"]["registry_snapshot_id"], entity_registry_snapshot_id=REGISTRIES["entity_v1"]["registry_snapshot_id"], source_id=FIXTURE_SOURCE, source_reference="fixture://bad", retrieval_status="FAILED", failure_reason="", failure_stage="READ", attempted_at_utc="2026-05-01T00:00:00Z"), "FAILURE_REASON_AND_STAGE_REQUIRED")

@check("FAILED_ACQUISITION", "failure attempted time required and aware")
def _():
    with fresh_store() as (store, _): expect(Stage6IngestionError, lambda: failure(store, attempted="2026-05-01T00:00:00"), "NAIVE_TIMESTAMP")

@check("FAILED_ACQUISITION", "failure is acquisition attempt")
def _():
    with fresh_store() as (store, _): require(failure(store)["record"]["record_kind"] == "ACQUISITION_ATTEMPT")

@check("FAILED_ACQUISITION", "failure never fabricates no-news semantics")
def _():
    with fresh_store() as (store, _):
        text = canonical_json(failure(store)["record"]).upper(); require("NO_NEWS" not in text and "NO_EVENT" not in text and '"SAFE"' not in text and '"NEUTRAL"' not in text)

@check("IDEMPOTENCY", "identical retry returns idempotent success")
def _():
    with fresh_store() as (store, _): capture(store); require(capture(store)["status"] == "IDEMPOTENT_SUCCESS")

@check("IDEMPOTENCY", "changed payload same key conflicts")
def _():
    with fresh_store() as (store, _): capture(store); expect(IdempotencyConflict, lambda: capture(store, payload=b"changed"), "IDEMPOTENCY_CONFLICT")

@check("IDEMPOTENCY", "changed registry same key conflicts")
def _():
    with fresh_store(import_v2=True) as (store, _): capture(store); expect(IdempotencyConflict, lambda: capture(store, source_registry="source_v2", entity_registry="entity_v2", observed="2026-08-03T09:01:00Z", retrieved="2026-08-03T09:02:00Z", publication="2026-08-03T09:00:00Z"), "IDEMPOTENCY_CONFLICT")

@check("IDEMPOTENCY", "changed timestamp same key conflicts")
def _():
    with fresh_store() as (store, _): capture(store); expect(IdempotencyConflict, lambda: capture(store, retrieved="2026-05-01T09:03:00Z"), "IDEMPOTENCY_CONFLICT")

@check("IDEMPOTENCY", "changed failure status same key conflicts")
def _():
    with fresh_store() as (store, _): failure(store); expect(IdempotencyConflict, lambda: failure(store, status="NOT_FOUND"), "IDEMPOTENCY_CONFLICT")

@check("IMMUTABILITY", "application update rejected")
def _():
    with fresh_store() as (store, _): expect(Stage6IngestionError, lambda: store.update_record("anything"), "IMMUTABLE_RECORD_UPDATE_PROHIBITED")

@check("IMMUTABILITY", "database record UPDATE rejected")
def _():
    with fresh_store() as (store, _):
        capture(store); expect(sqlite3.DatabaseError, lambda: store.connection.execute("UPDATE ingestion_records SET source_id='x'"), "IMMUTABLE_TABLE_UPDATE")

@check("IMMUTABILITY", "database record DELETE rejected")
def _():
    with fresh_store() as (store, _):
        capture(store); expect(sqlite3.DatabaseError, lambda: store.connection.execute("DELETE FROM ingestion_records"), "IMMUTABLE_TABLE_DELETE")

@check("IMMUTABILITY", "imported V1 remains unchanged after V2")
def _():
    with fresh_store(import_v2=True) as (store, _):
        rows = store.connection.execute("SELECT canonical_json FROM registry_snapshots WHERE registry_kind='SOURCE' ORDER BY registry_version").fetchall()
        require(json.loads(rows[0][0]) == REGISTRIES["source_v1"] and json.loads(rows[1][0]) == REGISTRIES["source_v2"])

@check("IMMUTABILITY", "evidence bound to V1 remains bound after V2 import")
def _():
    with fresh_store(import_v2=True) as (store, _):
        record = capture(store)["record"]
        require(record["source_registry_snapshot_id"] == REGISTRIES["source_v1"]["registry_snapshot_id"])
        require(record["entity_registry_snapshot_id"] == REGISTRIES["entity_v1"]["registry_snapshot_id"])

@check("RAW_STORE", "identical bytes deduplicate safely")
def _():
    with tempfile.TemporaryDirectory() as folder:
        raw = RawPayloadStore(Path(folder)); require(raw.put(b"same") == raw.put(b"same"))

@check("RAW_STORE", "different bytes produce different objects")
def _():
    with tempfile.TemporaryDirectory() as folder:
        raw = RawPayloadStore(Path(folder)); require(raw.put(b"one")[0] != raw.put(b"two")[0])

@check("RAW_STORE", "modified raw bytes detected")
def _():
    with fresh_store() as (store, _):
        record = capture(store)["record"]; store.raw_store.path_for(record["raw_payload_hash"]).write_bytes(b"tampered")
        expect(IntegrityFailure, store.integrity_check, "RAW_PAYLOAD_HASH_MISMATCH")

@check("RAW_STORE", "missing raw file detected")
def _():
    with fresh_store() as (store, _):
        record = capture(store)["record"]; store.raw_store.path_for(record["raw_payload_hash"]).unlink()
        expect(IntegrityFailure, store.integrity_check, "RAW_PAYLOAD_MISSING")

@check("RAW_STORE", "wrong raw metadata reference detected")
def _():
    with fresh_store() as (store, _):
        capture(store); store.connection.execute("DROP TRIGGER protect_raw_payloads_update"); store.connection.execute("UPDATE raw_payloads SET relative_reference='raw/wrong'"); store.connection.commit()
        expect(IntegrityFailure, store.integrity_check, "RAW_PAYLOAD_REFERENCE_MISMATCH")

@check("LINKED_EVIDENCE", "valid correction link accepted")
def _():
    with fresh_store() as (store, _):
        original = capture(store)["record"]; result = capture(store, key="correction", payload=b"corrected", correction_of_evidence_id=original["evidence_id"])
        require(result["record"]["correction_of_evidence_id"] == original["evidence_id"])

@check("LINKED_EVIDENCE", "valid retraction link accepted")
def _():
    with fresh_store() as (store, _):
        original = capture(store)["record"]; result = capture(store, key="retraction", payload=b"retraction", retraction_of_evidence_id=original["evidence_id"])
        require(result["record"]["retraction_of_evidence_id"] == original["evidence_id"])

@check("LINKED_EVIDENCE", "missing linked evidence rejected")
def _():
    with fresh_store() as (store, _): expect(Stage6IngestionError, lambda: capture(store, correction_of_evidence_id="S6EV_MISSING"), "LINKED_EVIDENCE_NOT_FOUND")

@check("LINKED_EVIDENCE", "self reference rejected")
def _():
    with fresh_store() as (store, _): expect(Stage6IngestionError, lambda: store._link_check("S6EV_SELF", {"parent": "S6EV_SELF"}), "EVIDENCE_SELF_REFERENCE")

@check("LINKED_EVIDENCE", "original record remains immutable")
def _():
    with fresh_store() as (store, _):
        original = capture(store)["record"]; capture(store, key="correction", payload=b"corrected", correction_of_evidence_id=original["evidence_id"])
        require(store.get_record(original["evidence_id"]) == original)

@check("RESTART", "close and reopen retains identities")
def _():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); store = IngestionStore(root / "store.sqlite3", root / "raw"); store.import_registry(REGISTRIES["entity_v1"]); store.import_registry(REGISTRIES["source_v1"]); record = capture(store)["record"]; store.close()
        reopened = IngestionStore(root / "store.sqlite3", root / "raw"); require(reopened.get_record(record["evidence_id"]) == record); reopened.close()

@check("RESTART", "integrity passes after restart")
def _():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); store = IngestionStore(root / "store.sqlite3", root / "raw"); store.import_registry(REGISTRIES["entity_v1"]); store.import_registry(REGISTRIES["source_v1"]); capture(store); failure(store); store.close()
        reopened = IngestionStore(root / "store.sqlite3", root / "raw"); require(reopened.integrity_check()["result"] == "PASS"); reopened.close()

@check("INTEGRITY_TAMPER", "canonical evidence JSON tamper detected")
def _():
    with fresh_store() as (store, _):
        record = capture(store)["record"]; bad = deepcopy(record); bad["source_reference"] = "tampered"
        store.connection.execute("DROP TRIGGER protect_ingestion_records_update"); store.connection.execute("UPDATE ingestion_records SET canonical_json=?", (canonical_json(bad),)); store.connection.commit()
        expect(IntegrityFailure, store.integrity_check, "EVIDENCE_RECORD_HASH_MISMATCH")

@check("INTEGRITY_TAMPER", "typed evidence column tamper detected")
def _():
    with fresh_store() as (store, _):
        capture(store); store.connection.execute("DROP TRIGGER protect_ingestion_records_update"); store.connection.execute("UPDATE ingestion_records SET source_id='tampered'"); store.connection.commit()
        expect(IntegrityFailure, store.integrity_check, "EVIDENCE_TYPED_COLUMN_MISMATCH")

@check("INTEGRITY_TAMPER", "registry canonical payload tamper detected")
def _():
    with fresh_store() as (store, _):
        bad = deepcopy(REGISTRIES["source_v1"]); bad["sources"][0]["source_name"] = "tampered"
        store.connection.execute("DROP TRIGGER protect_registry_snapshots_update"); store.connection.execute("UPDATE registry_snapshots SET canonical_json=? WHERE registry_kind='SOURCE'", (canonical_json(bad),)); store.connection.commit()
        expect(IntegrityFailure, store.integrity_check, "REGISTRY_RECORD_HASH_MISMATCH")

@check("INTEGRITY_TAMPER", "idempotency binding tamper detected")
def _():
    with fresh_store() as (store, _):
        capture(store); store.connection.execute("DROP TRIGGER protect_idempotency_bindings_update"); store.connection.execute("UPDATE idempotency_bindings SET record_hash=?", ("0" * 64,)); store.connection.commit()
        expect(IntegrityFailure, store.integrity_check, "IDEMPOTENCY_BINDING_MISMATCH")

@check("INTEGRITY_TAMPER", "missing idempotency binding detected")
def _():
    with fresh_store() as (store, _):
        capture(store); store.connection.execute("DROP TRIGGER protect_idempotency_bindings_delete"); store.connection.execute("DELETE FROM idempotency_bindings"); store.connection.commit()
        expect(IntegrityFailure, store.integrity_check, "IDEMPOTENCY_BINDING_COVERAGE_MISMATCH")

@check("INTEGRITY_TAMPER", "store metadata mismatch fails closed")
def _():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); store = IngestionStore(root / "store.sqlite3", root / "raw"); store.connection.execute("DROP TRIGGER protect_store_meta_update"); store.connection.execute("UPDATE store_meta SET authority='TRADING'"); store.connection.commit(); store.close()
        expect(IntegrityFailure, lambda: IngestionStore(root / "store.sqlite3", root / "raw"), "STORE_METADATA_IDENTITY_MISMATCH")

@check("FULL_STORE_INTEGRITY", "complete fixture store verifies")
def _():
    with fresh_store(import_v2=True) as (store, _): capture(store); failure(store, key="failure-2"); require(store.integrity_check()["result"] == "PASS")

@check("NETWORK_PROHIBITION", "no prohibited network imports")
def _():
    prohibited = {"requests", "urllib", "httpx", "aiohttp", "yfinance", "selenium", "playwright", "socket", "websocket"}
    prohibited_calls = {"urlopen", "create_connection", "getaddrinfo", "connect"}
    for path in (STAGE_ROOT / "stage6_ingestion").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): require(not ({name.name.split('.')[0] for name in node.names} & prohibited), f"network import in {path.name}")
            if isinstance(node, ast.ImportFrom): require((node.module or "").split('.')[0] not in prohibited, f"network import in {path.name}")
            if isinstance(node, ast.Call):
                called = node.func.attr if isinstance(node.func, ast.Attribute) else (node.func.id if isinstance(node.func, ast.Name) else "")
                sqlite_connect = (called == "connect" and isinstance(node.func, ast.Attribute)
                                  and isinstance(node.func.value, ast.Name) and node.func.value.id == "sqlite3")
                require(called not in prohibited_calls or sqlite_connect, f"network-like call {called} in {path.name}")

@check("NETWORK_PROHIBITION", "socket sentinel remains unused")
def _():
    with mock.patch.object(socket, "socket", side_effect=AssertionError("NETWORK_SENTINEL_USED")):
        with fresh_store() as (store, _): capture(store); require(store.integrity_check()["result"] == "PASS")

@check("NETWORK_PROHIBITION", "fixture demo declares zero network calls")
def _():
    from stage6_ingestion.run_fixture_demo import run_demo
    with mock.patch.object(socket, "socket", side_effect=AssertionError("NETWORK_SENTINEL_USED")):
        result = run_demo(); require(result["network_calls"] is False and result["fixture_only"] is True)

@check("BOUNDARY", "frozen Stage 6 architecture files unchanged")
def _():
    paths = ["Stage 6/contracts", "Stage 6/policy", "Stage 6/Stage6_Master_Architecture.md", "Stage 6/results/stage6_0_architecture_contract.json", "Stage 6/scripts/validate_stage6_0.py"]
    require(git("diff", "--name-only", BASELINE_TAG, "--", *paths) == "")

@check("BOUNDARY", "Stage 5D files unchanged")
def _(): require(git("diff", "--name-only", PRODUCTION_TAG, "--", "Stage 5D") == "")

@check("BOUNDARY", "production control tag unchanged")
def _(): require(git("rev-parse", f"{PRODUCTION_TAG}^{{}}") == PRODUCTION_COMMIT)

@check("BOUNDARY", "no broker or order execution implementation")
def _():
    source = "\n".join(path.read_text(encoding="utf-8").casefold() for path in (STAGE_ROOT / "stage6_ingestion").glob("*.py"))
    require("broker" not in source and "place_order" not in source and "execute_trade" not in source)

@check("BOUNDARY", "no ML decision authority implementation")
def _():
    source = "\n".join(path.read_text(encoding="utf-8").casefold() for path in (STAGE_ROOT / "stage6_ingestion").glob("*.py"))
    require("ml_production" not in source and "model.predict" not in source)

@check("BOUNDARY", "no runtime artifacts tracked")
def _(): require(git("ls-files", "Stage 6/runtime") == "")

@check("BOUNDARY", "no pycache or pyc tracked in Stage 6.1A")
def _():
    tracked = git("ls-files", "Stage 6/stage6_ingestion", "Stage 6/tests", "Stage 6/fixtures")
    require("__pycache__" not in tracked and ".pyc" not in tracked)


def main() -> int:
    rows: list[dict[str, str]] = []
    for number, (category, name, function) in enumerate(CHECKS, 1):
        try:
            function()
            rows.append({"test_id": f"S6_1A_{number:03d}", "category": category, "test_name": name, "result": "PASS", "detail": ""})
        except Exception as exc:  # Test evidence must retain every failure deterministically.
            rows.append({"test_id": f"S6_1A_{number:03d}", "category": category, "test_name": name, "result": "FAIL", "detail": f"{type(exc).__name__}:{exc}"})
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["test_id", "category", "test_name", "result", "detail"], lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    failed = [row for row in rows if row["result"] != "PASS"]
    print(json.dumps({"stage": "6.1A", "tests": len(rows), "passed": len(rows) - len(failed), "failed": len(failed), "result": "PASS" if not failed else "FAIL", "authority": AUTHORITY, "fixture_only": True, "network_calls": False}, sort_keys=True, separators=(",", ":")))
    for row in failed: print(f"FAIL {row['test_id']} {row['test_name']}: {row['detail']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
