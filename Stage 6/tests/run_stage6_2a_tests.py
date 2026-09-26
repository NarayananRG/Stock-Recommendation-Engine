"""Stage 6.2A immutable event-foundation acceptance and adversarial tests."""
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

from stage6_events import (AUTHORITY, EventIntegrityFailure, EventStore,
                           EventVersionConflict, Stage6EventError, build_event,
                           deterministic_event_id, validate_event)
from stage6_events.event_store import BASELINE_COMMIT, BASELINE_TAG
from stage6_ingestion.canonical import canonical_hash, canonical_json, parse_utc, without
from stage6_ingestion.evidence_store import IngestionStore
from stage6_ingestion.fixtures import build_fixture_registries
from stage6_ingestion.registry import build_source_registry


RESULT_PATH = STAGE_ROOT / "results" / "stage6_2a_test_results.csv"
FIXTURE_ROOT = STAGE_ROOT / "fixtures" / "stage6_2a"
ENTITY = "S6FIX_COMPANY_001"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
CHECKS: list[tuple[str, str, object]] = []


def check(category: str, name: str):
    def register(function):
        CHECKS.append((category, name, function))
        return function
    return register


def require(value: object, message: str = "assertion failed") -> None:
    if not value:
        raise AssertionError(message)


def expect(error: type[BaseException], function, contains: str | None = None) -> BaseException:
    try:
        function()
    except error as exc:
        if contains:
            require(contains in str(exc), f"expected {contains!r} in {exc!r}")
        return exc
    raise AssertionError(f"expected {error.__name__}")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def source_fixture() -> dict:
    records = json.loads((FIXTURE_ROOT / "source_records.json").read_text(encoding="utf-8"))
    return build_source_registry(records, "2026-01-02T00:00:00Z")


@contextmanager
def fresh_environment():
    with tempfile.TemporaryDirectory(prefix="stage6_2a_test_") as folder:
        root = Path(folder)
        registries = build_fixture_registries()
        ingestion = IngestionStore(root / "ingestion.sqlite3", root / "raw")
        ingestion.import_registry(registries["entity_v1"])
        ingestion.import_registry(registries["entity_v2"])
        sources = source_fixture()
        ingestion.import_registry(sources)
        evidence: dict[str, dict] = {}
        names = [
            ("official1", "S6FIX_2A_OFFICIAL_001", "09:02:00"),
            ("official2", "S6FIX_2A_OFFICIAL_002", "09:03:00"),
            ("independent1", "S6FIX_2A_INDEPENDENT_001", "09:04:00"),
            ("independent2", "S6FIX_2A_INDEPENDENT_002", "09:05:00"),
            ("discovery", "S6FIX_2A_DISCOVERY_001", "09:06:00"),
            ("unverified", "S6FIX_2A_UNVERIFIED_001", "09:07:00"),
            ("official1b", "S6FIX_2A_OFFICIAL_001", "09:08:00"),
        ]
        for name, source_id, retrieved_time in names:
            result = ingestion.capture_evidence(
                idempotency_key=f"stage6-2a-{name}",
                source_registry_snapshot_id=sources["registry_snapshot_id"],
                entity_registry_snapshot_id=registries["entity_v1"]["registry_snapshot_id"],
                source_id=source_id, source_reference=f"fixture://stage6-2a/{name}",
                raw_payload=f"synthetic event evidence {name}".encode(), content_type="text/plain",
                publication_timestamp_utc="2026-05-01T09:00:00Z",
                observed_timestamp_utc="2026-05-01T09:01:00Z",
                retrieved_timestamp_utc=f"2026-05-01T{retrieved_time}Z", entity_ids=[ENTITY])
            evidence[name] = result["record"]
        evidence["quarantined"] = ingestion.capture_evidence(
            idempotency_key="stage6-2a-quarantined", source_registry_snapshot_id=sources["registry_snapshot_id"],
            entity_registry_snapshot_id=registries["entity_v1"]["registry_snapshot_id"],
            source_id="S6FIX_2A_OFFICIAL_001", source_reference="fixture://stage6-2a/quarantined",
            raw_payload=b"synthetic quarantined", content_type="text/plain",
            publication_timestamp_utc="2026-05-01T09:00:00Z", observed_timestamp_utc="2026-05-01T09:01:00Z",
            retrieved_timestamp_utc="2026-05-01T09:09:00Z", entity_ids=[ENTITY],
            retrieval_status="QUARANTINED")["record"]
        evidence["attempt"] = ingestion.capture_acquisition_failure(
            idempotency_key="stage6-2a-attempt", source_registry_snapshot_id=sources["registry_snapshot_id"],
            entity_registry_snapshot_id=registries["entity_v1"]["registry_snapshot_id"],
            source_id="S6FIX_2A_OFFICIAL_001", source_reference="fixture://stage6-2a/attempt",
            retrieval_status="FAILED", failure_reason="synthetic", failure_stage="FIXTURE",
            attempted_at_utc="2026-05-01T09:10:00Z", entity_ids=[ENTITY])["record"]
        event_store = EventStore(root / "events.sqlite3", ingestion)
        try:
            yield ingestion, event_store, evidence, registries, root
        finally:
            event_store.close()
            ingestion.close()


def request(evidence: dict[str, dict], names: list[str], *, event_key: str = "fixture-event-001",
            event_version: int = 1, previous: str | None = None, status: str = "ACTIVE",
            corroboration: str = "SINGLE_SOURCE_OFFICIAL", materiality: str = "NON_MATERIAL",
            first: str | None = None, updated: str = "2026-05-01T10:00:00.000000Z",
            entities: list[str] | None = None, conflicts: list[dict] | None = None,
            causality: str = "NO_SUPPORTED_CAUSE_FOUND", channels: list[str] | None = None,
            entity_registry: str | None = None, **changes: object) -> dict:
    selected = [evidence[name] for name in names]
    available = [item["retrieved_timestamp_utc"] for item in selected if item["retrieved_timestamp_utc"]]
    earliest = min(available) if available else "2026-05-01T09:10:00.000000Z"
    values = {
        "event_key": event_key, "event_version": event_version,
        "previous_event_version_hash": previous,
        "source_evidence_ids": [item["evidence_id"] for item in selected],
        "entity_resolution_version": entity_registry,
        "event_type": "RATE_HIKE", "event_status": status, "direction": "UNKNOWN",
        "severity": "UNKNOWN", "materiality": materiality, "confidence": 0.5,
        "entities": [ENTITY] if entities is None else entities, "sectors": [], "geographies": ["IN"],
        "commodities": [], "currencies": [], "corroboration_status": corroboration,
        "first_known_timestamp": first or earliest, "last_updated_timestamp": updated,
        "event_horizon": "UNKNOWN", "transmission_channels": channels or [],
        "causality_assessment": causality, "evidence_conflicts": conflicts or [],
    }
    values.update(changes)
    return values


def append(store: EventStore, evidence: dict[str, dict], names: list[str], **kwargs: object) -> dict:
    values = request(evidence, names, **kwargs)
    if values["entity_resolution_version"] is None:
        row = store.ingestion_store.connection.execute(
            "SELECT snapshot_id FROM registry_snapshots WHERE registry_kind='ENTITY' ORDER BY registry_version LIMIT 1").fetchone()
        values["entity_resolution_version"] = row[0]
    return store.append_event(**values)


def restore_trigger(store: EventStore, table: str, operation: str) -> None:
    name = f"protect_{table}_{operation.lower()}"
    store.connection.executescript(f"""
    CREATE TRIGGER {name} BEFORE {operation} ON {table}
    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_{operation}'); END;
    """)


def standalone_event(**changes: object) -> dict:
    values = {
        "event_key": "standalone", "event_version": 1, "previous_event_version_hash": None,
        "event_type": "OTHER", "event_status": "ACTIVE", "direction": "UNKNOWN",
        "severity": "UNKNOWN", "materiality": "NON_MATERIAL", "confidence": 0.5,
        "entities": [], "sectors": [], "geographies": [], "commodities": [], "currencies": [],
        "source_evidence_ids": ["S6EV_FIXTURE"], "corroboration_status": "UNVERIFIED",
        "first_known_timestamp": "2026-05-01T09:02:00Z", "last_updated_timestamp": "2026-05-01T09:03:00Z",
        "entity_resolution_version": "S6ENTREG_FIXTURE", "event_horizon": "UNKNOWN",
        "transmission_channels": [], "causality_assessment": "NO_SUPPORTED_CAUSE_FOUND",
        "evidence_conflicts": [],
    }
    values.update(changes)
    return build_event(**values)


# Baseline and schema.
@check("BASELINE", "Stage 6.1C baseline is exact ancestor")
def _():
    require(git("rev-parse", f"{BASELINE_TAG}^{{}}") == BASELINE_COMMIT)
    subprocess.check_call(["git", "merge-base", "--is-ancestor", BASELINE_COMMIT, "HEAD"], cwd=REPO_ROOT)

@check("BASELINE", "authority is SHADOW_ONLY")
def _(): require(AUTHORITY == "SHADOW_ONLY")

@check("SCHEMA", "valid event accepted")
def _(): require(validate_event(standalone_event())["schema_version"] == "STAGE6_EVENT_V1")

for category_name, mutation, error_text in [
    ("wrong schema rejected", lambda e: e.update(schema_version="WRONG"), "EVENT_SCHEMA_VERSION_INVALID"),
    ("missing field rejected", lambda e: e.pop("direction"), "EVENT_FIELDS_MISMATCH"),
    ("extra field rejected", lambda e: e.update(extra=True), "EVENT_FIELDS_MISMATCH"),
    ("invalid enum rejected", lambda e: e.update(direction="UP"), "EVENT_ENUM_INVALID"),
    ("confidence below zero rejected", lambda e: e.update(confidence=-0.1), "EVENT_CONFIDENCE_INVALID"),
    ("confidence above one rejected", lambda e: e.update(confidence=1.1), "EVENT_CONFIDENCE_INVALID"),
    ("duplicate array rejected", lambda e: e.update(entities=["X", "X"]), "EVENT_ARRAY_INVALID"),
    ("invalid hash rejected", lambda e: e.update(record_hash="bad"), "EVENT_RECORD_HASH_INVALID"),
]:
    def make_schema_test(name=category_name, mutate=mutation, contains=error_text):
        @check("SCHEMA", name)
        def _test():
            event = standalone_event(); mutate(event)
            expect(Stage6EventError, lambda: validate_event(event, verify_hash=False), contains)
        return _test
    make_schema_test()


# Dependencies, point-in-time, and entities.
@check("DEPENDENCY", "valid evidence ID hash and type binding")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        created = append(store, evidence, ["official1"])
        row = store.connection.execute("SELECT * FROM event_dependencies").fetchone()
        require((row["dependency_record_id"], row["dependency_record_hash"], row["dependency_record_type"]) ==
                (evidence["official1"]["evidence_id"], evidence["official1"]["record_hash"], "EVIDENCE"))
        require(created["status"] == "CREATED")

@check("DEPENDENCY", "acquisition attempt rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        expect(Stage6EventError, lambda: append(store, evidence, ["attempt"]), "ACQUISITION_ATTEMPT")

@check("DEPENDENCY", "quarantined evidence rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        expect(Stage6EventError, lambda: append(store, evidence, ["quarantined"]), "NOT_RETRIEVED")

@check("DEPENDENCY", "missing evidence rejected")
def _():
    with fresh_environment() as (_, store, evidence, registries, _):
        bad = request(evidence, ["official1"], entity_registry=registries["entity_v1"]["registry_snapshot_id"])
        bad["source_evidence_ids"] = ["S6EV_MISSING"]
        expect(EventIntegrityFailure, lambda: store.append_event(**bad), "DEPENDENCY_MISSING")

@check("DEPENDENCY", "tampered evidence rejected")
def _():
    with fresh_environment() as (ingestion, store, evidence, _, _):
        ingestion.connection.execute("DROP TRIGGER protect_ingestion_records_update")
        ingestion.connection.execute("UPDATE ingestion_records SET canonical_json='{}' WHERE record_id=?", (evidence["official1"]["evidence_id"],)); ingestion.connection.commit()
        expect(EventIntegrityFailure, lambda: append(store, evidence, ["official1"]), "UPSTREAM_INGESTION")

@check("PIT", "future evidence rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        expect(Stage6EventError, lambda: append(store, evidence, ["official1"],
            first="2026-05-01T09:01:00Z", updated="2026-05-01T09:01:30Z"), "FUTURE_EVIDENCE")

@check("PIT", "V1 first known equals earliest retrieval")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        expect(Stage6EventError, lambda: append(store, evidence, ["official1"], first="2026-05-01T09:00:00Z"), "FIRST_KNOWN")

@check("PIT", "first known not after last updated")
def _(): expect(Stage6EventError, lambda: standalone_event(first_known_timestamp="2026-05-02T00:00:00Z"), "EVENT_CHRONOLOGY")

@check("PIT", "later version cannot backdate last updated")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        v1 = append(store, evidence, ["official1"])["event"]
        expect(Stage6EventError, lambda: append(store, evidence, ["official1"], event_version=2,
            previous=v1["record_hash"], first=v1["first_known_timestamp"], updated="2026-05-01T09:59:00Z"), "BACKDATING")

@check("ENTITY", "valid immutable entity snapshot accepted")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["official1"])["status"] == "CREATED")

@check("ENTITY", "missing entity rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        expect(EventIntegrityFailure, lambda: append(store, evidence, ["official1"], entities=["S6FIX_MISSING"]), "ENTITY_BINDING")

@check("ENTITY", "future entity registry rejected")
def _():
    with fresh_environment() as (_, store, evidence, registries, _):
        expect(EventIntegrityFailure, lambda: append(store, evidence, ["official1"],
            entity_registry=registries["entity_v2"]["registry_snapshot_id"], updated="2026-05-01T10:00:00Z"), "FROM_FUTURE")


# Versioning and idempotency.
@check("EVENT_VERSIONING", "V1 has null predecessor")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["official1"])["event"]["previous_event_version_hash"] is None)

@check("EVENT_VERSIONING", "V2 exact predecessor and V3 chain")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        v1 = append(store, evidence, ["official1"])["event"]
        v2 = append(store, evidence, ["official1"], event_version=2, previous=v1["record_hash"], first=v1["first_known_timestamp"], updated="2026-05-01T11:00:00Z", confidence=0.6)["event"]
        v3 = append(store, evidence, ["official1"], event_version=3, previous=v2["record_hash"], first=v1["first_known_timestamp"], updated="2026-05-01T12:00:00Z", confidence=0.7)["event"]
        require(v2["previous_event_version_hash"] == v1["record_hash"] and v3["previous_event_version_hash"] == v2["record_hash"])

@check("EVENT_VERSIONING", "skipped version rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        v1 = append(store, evidence, ["official1"])["event"]
        expect(EventVersionConflict, lambda: append(store, evidence, ["official1"], event_version=3,
            previous=v1["record_hash"], first=v1["first_known_timestamp"]), "NOT_CONTIGUOUS")

@check("EVENT_VERSIONING", "wrong predecessor rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        v1 = append(store, evidence, ["official1"])["event"]
        expect(EventVersionConflict, lambda: append(store, evidence, ["official1"], event_version=2,
            previous="f" * 64, first=v1["first_known_timestamp"]), "PREDECESSOR_MISMATCH")

@check("EVENT_VERSIONING", "database update and delete prohibited")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        event = append(store, evidence, ["official1"])["event"]
        expect(sqlite3.DatabaseError, lambda: store.connection.execute("UPDATE event_records SET event_version=2"), "IMMUTABLE_TABLE_UPDATE")
        expect(sqlite3.DatabaseError, lambda: store.connection.execute("DELETE FROM event_records WHERE event_id=?", (event["event_id"],)), "IMMUTABLE_TABLE_DELETE")

@check("IDEMPOTENCY", "exact retry succeeds idempotently")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        append(store, evidence, ["official1"]); require(append(store, evidence, ["official1"])["status"] == "IDEMPOTENT_SUCCESS")

@check("IDEMPOTENCY", "incompatible duplicate fails")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        append(store, evidence, ["official1"])
        expect(EventVersionConflict, lambda: append(store, evidence, ["official1"], confidence=0.9), "INCOMPATIBLE_DUPLICATE")

@check("IDEMPOTENCY", "different event key creates distinct event id")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        one = append(store, evidence, ["official1"], event_key="one")["event"]
        two = append(store, evidence, ["official1"], event_key="two")["event"]
        require(one["event_id"] != two["event_id"])

@check("IDEMPOTENCY", "same event key retains stable event id across versions")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        v1 = append(store, evidence, ["official1"])["event"]
        v2 = append(store, evidence, ["official1"], event_version=2, previous=v1["record_hash"],
            first=v1["first_known_timestamp"], updated="2026-05-01T11:00:00Z", confidence=0.6)["event"]
        require(v1["event_id"] == v2["event_id"] == deterministic_event_id("fixture-event-001"))

@check("IDEMPOTENCY", "same version with different evidence fails")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        append(store, evidence, ["official1"])
        expect(EventVersionConflict, lambda: append(store, evidence, ["official2"]), "INCOMPATIBLE_DUPLICATE")


# Corroboration, materiality, conflicts, and explicit boundaries.
@check("CORROBORATION", "one official supports SINGLE_SOURCE_OFFICIAL")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["official1"])["status"] == "CREATED")

@check("CORROBORATION", "one independent supports SINGLE_SOURCE_INDEPENDENT")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["independent1"], corroboration="SINGLE_SOURCE_INDEPENDENT")["status"] == "CREATED")

@check("CORROBORATION", "two records from same source are not corroboration")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        expect(Stage6EventError, lambda: append(store, evidence, ["official1", "official1b"], corroboration="CORROBORATED"), "INDEPENDENCE")

@check("CORROBORATION", "two independent trustworthy sources corroborate")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["independent1", "independent2"], corroboration="CORROBORATED")["status"] == "CREATED")

@check("CORROBORATION", "primary direct evidence supports confirmed")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["official1"], corroboration="CONFIRMED")["status"] == "CREATED")

@check("CORROBORATION", "discovery cannot masquerade as corroborated")
def _():
    with fresh_environment() as (_, store, evidence, _, _): expect(Stage6EventError, lambda: append(store, evidence, ["discovery"], corroboration="CORROBORATED"), "INDEPENDENCE")

@check("CORROBORATION", "unverified cannot masquerade as confirmed")
def _():
    with fresh_environment() as (_, store, evidence, _, _): expect(Stage6EventError, lambda: append(store, evidence, ["unverified"], corroboration="CONFIRMED"), "PRIMARY")

@check("MATERIALITY", "discovery may be non material")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["discovery"], corroboration="DISCOVERY_ONLY")["status"] == "CREATED")

@check("MATERIALITY", "discovery cannot independently be material")
def _():
    with fresh_environment() as (_, store, evidence, _, _): expect(Stage6EventError, lambda: append(store, evidence, ["discovery"], corroboration="DISCOVERY_ONLY", materiality="MATERIAL"), "MATERIALITY")

@check("MATERIALITY", "primary official supports material")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["official1"], materiality="MATERIAL")["status"] == "CREATED")

@check("MATERIALITY", "corroborated trustworthy supports high")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["independent1", "independent2"], corroboration="CORROBORATED", materiality="HIGH")["status"] == "CREATED")

@check("MATERIALITY", "unsupported high rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _): expect(Stage6EventError, lambda: append(store, evidence, ["discovery"], corroboration="DISCOVERY_ONLY", materiality="HIGH"), "HIGH_MATERIALITY")

@check("MATERIALITY", "unsupported critical rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _): expect(Stage6EventError, lambda: append(store, evidence, ["official1"], materiality="CRITICAL"), "CRITICAL_MATERIALITY")

@check("MATERIALITY", "critical conservative support accepted")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["official1", "independent1"], corroboration="CORROBORATED", materiality="CRITICAL")["status"] == "CREATED")

@check("CONFLICT", "conflicting evidence is explicit and preserved")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        ids = [evidence["official1"]["evidence_id"], evidence["independent1"]["evidence_id"]]
        event = append(store, evidence, ["official1", "independent1"], status="CONFLICTED",
            corroboration="CONFLICTING_EVIDENCE", conflicts=[{"evidence_ids": ids, "description": "Synthetic material disagreement", "status": "OPEN"}])["event"]
        require(event["evidence_conflicts"][0]["status"] == "OPEN")

@check("CONFLICT", "conflicting status requires conflicted event status")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        ids = [evidence["official1"]["evidence_id"], evidence["independent1"]["evidence_id"]]
        expect(Stage6EventError, lambda: append(store, evidence, ["official1", "independent1"], corroboration="CONFLICTING_EVIDENCE",
            conflicts=[{"evidence_ids": ids, "description": "x", "status": "OPEN"}]), "MUST_BE_EXPLICIT")

@check("CONFLICT", "conflict needs two dependency evidence IDs")
def _(): expect(Stage6EventError, lambda: standalone_event(
    evidence_conflicts=[{"evidence_ids": ["S6EV_FIXTURE"], "description": "x", "status": "OPEN"}]), "CONFLICT_INVALID")

@check("CONFLICT", "conflict resolution requires new version")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        ids = [evidence["official1"]["evidence_id"], evidence["independent1"]["evidence_id"]]
        conflict = [{"evidence_ids": ids, "description": "Synthetic disagreement", "status": "OPEN"}]
        v1 = append(store, evidence, ["official1", "independent1"], status="CONFLICTED", corroboration="CONFLICTING_EVIDENCE", conflicts=conflict)["event"]
        resolved = [{"evidence_ids": ids, "description": "Synthetic disagreement resolved", "status": "RESOLVED"}]
        v2 = append(store, evidence, ["official1", "independent1"], event_version=2, previous=v1["record_hash"],
            first=v1["first_known_timestamp"], updated="2026-05-01T11:00:00Z", status="ACTIVE",
            corroboration="CORROBORATED", conflicts=resolved)["event"]
        require(store.get_event(v1["event_id"], 1)["event_status"] == "CONFLICTED" and v2["event_status"] == "ACTIVE")

for name, causality in [("confirmed cause rejected", "CONFIRMED_CAUSE"),
                        ("plausible contributor rejected", "PLAUSIBLE_CONTRIBUTOR"),
                        ("correlated move rejected", "CORRELATED_MARKET_MOVE")]:
    def make_causality_test(test_name=name, value=causality):
        @check("CAUSALITY", test_name)
        def _test():
            with fresh_environment() as (_, store, evidence, _, _):
                expect(Stage6EventError, lambda: append(store, evidence, ["official1"], causality=value), "CAUSALITY_PROHIBITED")
        return _test
    make_causality_test()

@check("CAUSALITY", "no supported cause accepted")
def _():
    with fresh_environment() as (_, store, evidence, _, _): require(append(store, evidence, ["official1"])["status"] == "CREATED")

@check("TRANSMISSION", "empty channels accepted and claim rejected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        require(append(store, evidence, ["official1"])["event"]["transmission_channels"] == [])
    with fresh_environment() as (_, store, evidence, _, _):
        expect(Stage6EventError, lambda: append(store, evidence, ["official1"], channels=["RATE"]), "TRANSMISSION_PROHIBITED")


# Restart and adversarial integrity.
@check("INTEGRITY", "restart integrity passes")
def _():
    with fresh_environment() as (ingestion, store, evidence, _, root):
        append(store, evidence, ["official1"]); store.close()
        reopened = EventStore(root / "events.sqlite3", ingestion)
        try: require(reopened.integrity_check()["result"] == "PASS")
        finally: reopened.close()
        store.connection = sqlite3.connect(":memory:")

def tamper_event(column: str, value: str, expected: str) -> None:
    with fresh_environment() as (_, store, evidence, _, _):
        append(store, evidence, ["official1"])
        store.connection.execute("DROP TRIGGER protect_event_records_update")
        store.connection.execute(f"UPDATE event_records SET {column}=?", (value,)); restore_trigger(store, "event_records", "UPDATE"); store.connection.commit()
        expect(EventIntegrityFailure, store.integrity_check, expected)

@check("INTEGRITY", "event JSON tamper detected")
def _(): tamper_event("canonical_json", "{}", "EVENT_SEMANTIC_INTEGRITY_FAILURE")

@check("INTEGRITY", "event typed hash tamper detected")
def _(): tamper_event("record_hash", "a" * 64, "EVENT_TYPED_COLUMN_MISMATCH")

@check("INTEGRITY", "dependency hash tamper detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        append(store, evidence, ["official1"]); store.connection.execute("DROP TRIGGER protect_event_dependencies_update")
        store.connection.execute("UPDATE event_dependencies SET dependency_record_hash=?", ("b" * 64,)); restore_trigger(store, "event_dependencies", "UPDATE"); store.connection.commit()
        expect(EventIntegrityFailure, store.integrity_check, "DEPENDENCY_HASH_MISMATCH")

@check("INTEGRITY", "missing dependency sidecar detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        append(store, evidence, ["official1"]); store.connection.execute("DROP TRIGGER protect_event_dependencies_delete")
        store.connection.execute("DELETE FROM event_dependencies"); restore_trigger(store, "event_dependencies", "DELETE"); store.connection.commit()
        expect(EventIntegrityFailure, store.integrity_check, "DEPENDENCY_COVERAGE")

@check("INTEGRITY", "extra dependency sidecar detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        event = append(store, evidence, ["official1"])["event"]
        extra = evidence["independent1"]
        store.connection.execute("INSERT INTO event_dependencies VALUES(?,?,?,?,?)", (event["event_id"], 1, extra["evidence_id"], extra["record_hash"], "EVIDENCE")); store.connection.commit()
        expect(EventIntegrityFailure, store.integrity_check, "DEPENDENCY_COVERAGE")

@check("INTEGRITY", "wrong dependency record type detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        append(store, evidence, ["official1"]); store.connection.execute("DROP TRIGGER protect_event_dependencies_update")
        store.connection.execute("PRAGMA ignore_check_constraints=ON")
        store.connection.execute("UPDATE event_dependencies SET dependency_record_type='ACQUISITION_ATTEMPT'")
        restore_trigger(store, "event_dependencies", "UPDATE"); store.connection.commit()
        expect(EventIntegrityFailure, store.integrity_check, "DEPENDENCY_TYPE_INVALID")

@check("INTEGRITY", "orphan dependency detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        append(store, evidence, ["official1"])
        store.connection.execute("PRAGMA foreign_keys=OFF")
        store.connection.execute("INSERT INTO event_dependencies VALUES(?,?,?,?,?)",
            ("S6EVENT_ORPHAN", 1, evidence["independent1"]["evidence_id"], evidence["independent1"]["record_hash"], "EVIDENCE"))
        store.connection.commit()
        expect(EventIntegrityFailure, store.integrity_check, "FOREIGN_KEY_FAILURE")

@check("INTEGRITY", "chain tamper detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        v1 = append(store, evidence, ["official1"])["event"]
        append(store, evidence, ["official1"], event_version=2, previous=v1["record_hash"], first=v1["first_known_timestamp"], updated="2026-05-01T11:00:00Z", confidence=0.6)
        store.connection.execute("DROP TRIGGER protect_event_records_update")
        store.connection.execute("UPDATE event_records SET previous_event_version_hash=? WHERE event_version=2", ("c" * 64,)); restore_trigger(store, "event_records", "UPDATE"); store.connection.commit()
        expect(EventIntegrityFailure, store.integrity_check, "TYPED_COLUMN")

@check("INTEGRITY", "upstream evidence tamper after event creation detected")
def _():
    with fresh_environment() as (ingestion, store, evidence, _, _):
        append(store, evidence, ["official1"])
        ingestion.connection.execute("DROP TRIGGER protect_ingestion_records_update")
        ingestion.connection.execute("UPDATE ingestion_records SET record_hash=? WHERE record_id=?", ("d" * 64, evidence["official1"]["evidence_id"])); ingestion.connection.commit()
        expect(EventIntegrityFailure, store.integrity_check, "UPSTREAM_INGESTION")

@check("INTEGRITY", "append-only trigger removal detected")
def _():
    with fresh_environment() as (_, store, evidence, _, _):
        append(store, evidence, ["official1"]); store.connection.execute("DROP TRIGGER protect_event_series_delete"); store.connection.commit()
        expect(EventIntegrityFailure, store.integrity_check, "APPEND_ONLY_TRIGGER_MISSING")


# Network, non-inference, trading, and frozen boundaries.
@check("NETWORK_BOUNDARY", "socket sentinel and zero network implementation")
def _():
    sources = "\n".join(path.read_text(encoding="utf-8") for path in (STAGE_ROOT / "stage6_events").glob("*.py"))
    require(all(token not in sources for token in ("requests", "urllib", "http.client", "aiohttp", "socket.")))

@check("NETWORK_BOUNDARY", "no network or connector imports")
def _():
    prohibited = {"requests", "urllib", "http", "aiohttp", "socket", "stage6_connectors"}
    for path in (STAGE_ROOT / "stage6_events").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
        imports |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        require(not imports.intersection(prohibited))

@check("TRADING_BOUNDARY", "no trading ML LLM or broker authority")
def _():
    sources = "\n".join(path.read_text(encoding="utf-8").lower() for path in (STAGE_ROOT / "stage6_events").glob("*.py"))
    for token in ("buy_signal", "sell_signal", "broker_order", "target_price", "stop_loss", "import sklearn", "import openai", "import llm"):
        require(token not in sources)

@check("FIXTURE", "event fixture examples cover frozen types")
def _():
    cases = json.loads((FIXTURE_ROOT / "event_cases.json").read_text(encoding="utf-8"))
    require({item["event_type"] for item in cases} == {"RATE_HIKE", "REGULATORY_ACTION", "GOVERNMENT_POLICY", "MERGER", "CREDIT_DOWNGRADE", "OTHER"})

@check("BASELINE", "frozen Stage 6 architecture unchanged")
def _():
    paths = ["Stage 6/Stage6_Master_Architecture.md", "Stage 6/contracts", "Stage 6/policy",
             "Stage 6/scripts/validate_stage6_0.py", "Stage 6/results/stage6_0_architecture_contract.json"]
    require(git("diff", "--name-only", ARCHITECTURE_TAG, "--", *paths) == "")

@check("BASELINE", "Stage 6.1 ingestion and connectors unchanged")
def _(): require(git("diff", "--name-only", BASELINE_TAG, "--", "Stage 6/stage6_ingestion", "Stage 6/stage6_connectors") == "")

@check("BASELINE", "historical Stage 6.1 evidence unchanged")
def _():
    paths = ["Stage 6/Stage6_1A_Delivery_Report.md", "Stage 6/Stage6_1B_Delivery_Report.md", "Stage 6/Stage6_1C_Delivery_Report.md",
             "Stage 6/results/stage6_1a_test_results.csv", "Stage 6/results/stage6_1b_test_results.csv", "Stage 6/results/stage6_1c_test_results.csv"]
    require(git("diff", "--name-only", BASELINE_TAG, "--", *paths) == "")

@check("BASELINE", "Stage 5D unchanged")
def _(): require(git("diff", "--name-only", PRODUCTION_TAG, "--", "Stage 5D") == "")


def main() -> int:
    rows: list[dict[str, str]] = []
    for number, (category, name, function) in enumerate(CHECKS, 1):
        try:
            with mock.patch.object(socket, "socket", side_effect=AssertionError("STAGE6_2A_NETWORK_USED")):
                function()
            rows.append({"test_id": f"S6_2A_{number:03d}", "category": category, "test_name": name, "result": "PASS", "detail": ""})
        except Exception as exc:
            rows.append({"test_id": f"S6_2A_{number:03d}", "category": category, "test_name": name, "result": "FAIL", "detail": f"{type(exc).__name__}:{exc}"})
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["test_id", "category", "test_name", "result", "detail"], lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    failed = [row for row in rows if row["result"] != "PASS"]
    summary = {"stage": "6.2A", "tests": len(rows), "passed": len(rows) - len(failed), "failed": len(failed),
               "result": "PASS" if not failed else "FAIL", "authority": AUTHORITY,
               "fixture_only": True, "network_calls": 0}
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    for row in failed:
        print(f"FAIL {row['test_id']} {row['test_name']}: {row['detail']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
