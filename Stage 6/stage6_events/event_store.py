"""Append-only Stage 6.2A event store with verified Stage 6.1 dependencies."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json, parse_utc, without
from stage6_ingestion.evidence_store import IngestionStore
from stage6_ingestion.registry import resolve_entity

from .corroboration import enforce_evidence_policy
from .errors import EventIntegrityFailure, EventVersionConflict, Stage6EventError
from .event_builder import build_event, deterministic_event_id
from .event_validation import validate_event


STORE_SCHEMA_VERSION = "STAGE6_2A_EVENT_STORE_V1"
EVENT_SCHEMA_VERSION = "STAGE6_EVENT_V1"
AUTHORITY = "SHADOW_ONLY"
BASELINE_TAG = "stage6-1c-multisource-rss-ingestion-baseline"
BASELINE_COMMIT = "6046ea1bfcc13130581170c0d1a2ec50a1a2b2c5"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
ARCHITECTURE_COMMIT = "d5bc19c7c2341f56bcaa8c890e0d95979dca878b"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
PRODUCTION_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"


class EventStore:
    """Owns immutable events while treating the ingestion store as read-only."""

    def __init__(self, database: Path, ingestion_store: IngestionStore):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.ingestion_store = ingestion_store
        new = not self.database.exists()
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            if new:
                self._initialize()
            self._verify_metadata()
        except Exception:
            self.connection.close()
            raise

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript("""
        CREATE TABLE event_store_meta(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), store_schema_version TEXT NOT NULL,
          event_schema_version TEXT NOT NULL, baseline_tag TEXT NOT NULL, baseline_commit TEXT NOT NULL,
          architecture_tag TEXT NOT NULL, architecture_commit TEXT NOT NULL,
          production_tag TEXT NOT NULL, production_commit TEXT NOT NULL, authority TEXT NOT NULL);
        CREATE TABLE event_series(
          event_id TEXT PRIMARY KEY, event_key_json TEXT NOT NULL UNIQUE, event_key_hash TEXT NOT NULL UNIQUE);
        CREATE TABLE event_records(
          event_id TEXT NOT NULL, event_version INTEGER NOT NULL CHECK(event_version>=1),
          previous_event_version_hash TEXT, record_hash TEXT NOT NULL UNIQUE,
          last_updated_timestamp TEXT NOT NULL, canonical_json TEXT NOT NULL,
          PRIMARY KEY(event_id,event_version), FOREIGN KEY(event_id) REFERENCES event_series(event_id));
        CREATE TABLE event_dependencies(
          event_id TEXT NOT NULL, event_version INTEGER NOT NULL, dependency_record_id TEXT NOT NULL,
          dependency_record_hash TEXT NOT NULL, dependency_record_type TEXT NOT NULL CHECK(dependency_record_type='EVIDENCE'),
          PRIMARY KEY(event_id,event_version,dependency_record_id),
          FOREIGN KEY(event_id,event_version) REFERENCES event_records(event_id,event_version));
        """)
        self.connection.execute("INSERT INTO event_store_meta VALUES(1,?,?,?,?,?,?,?,?,?)", (
            STORE_SCHEMA_VERSION, EVENT_SCHEMA_VERSION, BASELINE_TAG, BASELINE_COMMIT,
            ARCHITECTURE_TAG, ARCHITECTURE_COMMIT, PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY))
        for table in ("event_store_meta", "event_series", "event_records", "event_dependencies"):
            self.connection.executescript(f"""
            CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_UPDATE'); END;
            CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_DELETE'); END;
            """)
        self.connection.commit()

    def _verify_metadata(self) -> None:
        try:
            row = self.connection.execute("SELECT * FROM event_store_meta WHERE singleton=1").fetchone()
            fields = ("store_schema_version", "event_schema_version", "baseline_tag", "baseline_commit",
                      "architecture_tag", "architecture_commit", "production_tag", "production_commit", "authority")
            expected = (STORE_SCHEMA_VERSION, EVENT_SCHEMA_VERSION, BASELINE_TAG, BASELINE_COMMIT,
                        ARCHITECTURE_TAG, ARCHITECTURE_COMMIT, PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY)
            if row is None or tuple(row[field] for field in fields) != expected:
                raise EventIntegrityFailure("EVENT_STORE_METADATA_MISMATCH")
        except sqlite3.Error as exc:
            raise EventIntegrityFailure("EVENT_STORE_METADATA_INVALID") from exc

    def _verify_ingestion(self) -> None:
        try:
            if self.ingestion_store.integrity_check().get("result") != "PASS":
                raise EventIntegrityFailure("UPSTREAM_INGESTION_INTEGRITY_FAILED")
        except Exception as exc:
            if isinstance(exc, EventIntegrityFailure):
                raise
            raise EventIntegrityFailure("UPSTREAM_INGESTION_INTEGRITY_FAILED") from exc

    def _load_evidence(self, evidence_ids: list[str], *, verify_store: bool = True) -> list[dict]:
        if (not isinstance(evidence_ids, list) or not evidence_ids
                or any(not isinstance(item, str) or not item for item in evidence_ids)
                or len(evidence_ids) != len(set(evidence_ids))):
            raise Stage6EventError("SOURCE_EVIDENCE_IDS_INVALID")
        if verify_store:
            self._verify_ingestion()
        records = []
        for evidence_id in evidence_ids:
            row = self.ingestion_store.connection.execute(
                "SELECT * FROM ingestion_records WHERE record_id=?", (evidence_id,)).fetchone()
            if row is None:
                raise EventIntegrityFailure("EVIDENCE_DEPENDENCY_MISSING")
            try:
                record = json.loads(row["canonical_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise EventIntegrityFailure("EVIDENCE_CANONICAL_JSON_INVALID") from exc
            if row["canonical_json"] != canonical_json(record):
                raise EventIntegrityFailure("EVIDENCE_CANONICAL_JSON_MISMATCH")
            if (record.get("record_kind") != "EVIDENCE" or row["record_kind"] != "EVIDENCE"):
                raise Stage6EventError("ACQUISITION_ATTEMPT_NOT_EVENT_EVIDENCE")
            if record.get("retrieval_status") != "RETRIEVED" or row["retrieval_status"] != "RETRIEVED":
                raise Stage6EventError("EVENT_EVIDENCE_NOT_RETRIEVED")
            expected_hash = canonical_hash(without(record, "record_hash"))
            if record.get("record_hash") != expected_hash or row["record_hash"] != expected_hash:
                raise EventIntegrityFailure("EVIDENCE_RECORD_HASH_MISMATCH")
            if record.get("retrieved_timestamp_utc") is None:
                raise Stage6EventError("EVIDENCE_RETRIEVED_TIMESTAMP_REQUIRED")
            records.append(record)
        return records

    def _verify_entity_binding(self, snapshot_id: str, entities: list[str], cutoff: str) -> None:
        try:
            snapshot = self.ingestion_store._verify_persisted_registry_chain("ENTITY", snapshot_id)
            if parse_utc(snapshot["as_of_timestamp"], "entity_registry.as_of_timestamp") > parse_utc(cutoff, "last_updated_timestamp"):
                raise EventIntegrityFailure("EVENT_ENTITY_REGISTRY_FROM_FUTURE")
            for entity_id in entities:
                resolve_entity(snapshot, entity_id, cutoff)
        except EventIntegrityFailure:
            raise
        except Exception as exc:
            raise EventIntegrityFailure("EVENT_ENTITY_BINDING_INVALID") from exc

    @staticmethod
    def _validate_pit(event: dict, evidence: list[dict], prior: dict | None) -> None:
        retrieved = [parse_utc(item["retrieved_timestamp_utc"], "retrieved_timestamp_utc") for item in evidence]
        cutoff = parse_utc(event["last_updated_timestamp"], "last_updated_timestamp")
        if any(value > cutoff for value in retrieved):
            raise Stage6EventError("FUTURE_EVIDENCE_PROHIBITED")
        earliest = min(retrieved)
        first = parse_utc(event["first_known_timestamp"], "first_known_timestamp")
        if prior is None:
            if first != earliest:
                raise Stage6EventError("FIRST_KNOWN_MUST_EQUAL_EARLIEST_RETRIEVAL")
        else:
            if event["first_known_timestamp"] != prior["first_known_timestamp"]:
                raise Stage6EventError("FIRST_KNOWN_IMMUTABLE")
            if cutoff < parse_utc(prior["last_updated_timestamp"], "prior.last_updated_timestamp"):
                raise Stage6EventError("EVENT_UPDATE_BACKDATING_PROHIBITED")

    def append_event(self, *, event_key: str, event_version: int,
                     previous_event_version_hash: str | None, source_evidence_ids: list[str],
                     entity_resolution_version: str, **classification: object) -> dict:
        self._verify_metadata()
        evidence = self._load_evidence(source_evidence_ids)
        event = build_event(
            event_key=event_key, event_version=event_version,
            previous_event_version_hash=previous_event_version_hash,
            source_evidence_ids=source_evidence_ids,
            entity_resolution_version=entity_resolution_version,
            **classification,
        )
        event_id = event["event_id"]
        key_json = canonical_json({"event_key": event_key})
        key_hash = canonical_hash({"event_key": event_key})
        series = self.connection.execute("SELECT * FROM event_series WHERE event_id=?", (event_id,)).fetchone()
        if series is not None and (series["event_key_json"] != key_json or series["event_key_hash"] != key_hash):
            raise EventVersionConflict("EVENT_IDENTITY_COLLISION")
        prior_row = self.connection.execute(
            "SELECT canonical_json FROM event_records WHERE event_id=? ORDER BY event_version DESC LIMIT 1", (event_id,)).fetchone()
        prior = json.loads(prior_row[0]) if prior_row else None
        existing = self.connection.execute(
            "SELECT canonical_json FROM event_records WHERE event_id=? AND event_version=?", (event_id, event_version)).fetchone()
        dependencies = [(item["evidence_id"], item["record_hash"], "EVIDENCE") for item in evidence]
        if existing is not None:
            stored_dependencies = [tuple(row) for row in self.connection.execute(
                "SELECT dependency_record_id,dependency_record_hash,dependency_record_type FROM event_dependencies "
                "WHERE event_id=? AND event_version=? ORDER BY dependency_record_id", (event_id, event_version))]
            if existing[0] == canonical_json(event) and sorted(dependencies) == stored_dependencies:
                return {"status": "IDEMPOTENT_SUCCESS", "event": event}
            raise EventVersionConflict("INCOMPATIBLE_DUPLICATE_EVENT_VERSION")
        expected_version = 1 if prior is None else prior["event_version"] + 1
        if event_version != expected_version:
            raise EventVersionConflict("EVENT_VERSION_NOT_CONTIGUOUS")
        expected_previous = None if prior is None else prior["record_hash"]
        if previous_event_version_hash != expected_previous:
            raise EventVersionConflict("EVENT_PREDECESSOR_MISMATCH")
        self._validate_pit(event, evidence, prior)
        self._verify_entity_binding(entity_resolution_version, event["entities"], event["last_updated_timestamp"])
        enforce_evidence_policy(event, evidence)
        serialized = canonical_json(event)
        try:
            with self.connection:
                if series is None:
                    self.connection.execute("INSERT INTO event_series VALUES(?,?,?)", (event_id, key_json, key_hash))
                self.connection.execute("INSERT INTO event_records VALUES(?,?,?,?,?,?)", (
                    event_id, event_version, previous_event_version_hash, event["record_hash"],
                    event["last_updated_timestamp"], serialized))
                self.connection.executemany("INSERT INTO event_dependencies VALUES(?,?,?,?,?)", [
                    (event_id, event_version, record_id, record_hash, record_type)
                    for record_id, record_hash, record_type in dependencies])
        except sqlite3.IntegrityError as exc:
            raise EventVersionConflict("EVENT_STORE_INSERT_CONFLICT") from exc
        return {"status": "CREATED", "event": event}

    def get_event(self, event_id: str, event_version: int | None = None) -> dict:
        if event_version is None:
            row = self.connection.execute(
                "SELECT canonical_json FROM event_records WHERE event_id=? ORDER BY event_version DESC LIMIT 1", (event_id,)).fetchone()
        else:
            row = self.connection.execute(
                "SELECT canonical_json FROM event_records WHERE event_id=? AND event_version=?", (event_id, event_version)).fetchone()
        if row is None:
            raise Stage6EventError("EVENT_NOT_FOUND")
        return json.loads(row[0])

    def integrity_check(self) -> dict:
        try:
            self._verify_metadata()
            if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise EventIntegrityFailure("EVENT_SQLITE_INTEGRITY_FAILURE")
            if self.connection.execute("PRAGMA foreign_key_check").fetchall():
                raise EventIntegrityFailure("EVENT_FOREIGN_KEY_FAILURE")
            self._verify_ingestion()
            for table in ("event_store_meta", "event_series", "event_records", "event_dependencies"):
                triggers = self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchall()
                if {row[0] for row in triggers} != {f"protect_{table}_update", f"protect_{table}_delete"}:
                    raise EventIntegrityFailure("APPEND_ONLY_TRIGGER_MISSING")
            series_rows = {row["event_id"]: row for row in self.connection.execute("SELECT * FROM event_series")}
            seen_series: set[str] = set()
            event_count = 0
            for event_id, series in series_rows.items():
                key = json.loads(series["event_key_json"])
                if (series["event_key_json"] != canonical_json(key)
                        or series["event_key_hash"] != canonical_hash(key)
                        or event_id != deterministic_event_id(key.get("event_key"))):
                    raise EventIntegrityFailure("EVENT_IDENTITY_MISMATCH")
                rows = self.connection.execute(
                    "SELECT * FROM event_records WHERE event_id=? ORDER BY event_version", (event_id,)).fetchall()
                if not rows or [row["event_version"] for row in rows] != list(range(1, len(rows) + 1)):
                    raise EventIntegrityFailure("EVENT_VERSION_CHAIN_GAP")
                prior = None
                for row in rows:
                    event_count += 1
                    event = json.loads(row["canonical_json"])
                    if row["canonical_json"] != canonical_json(event):
                        raise EventIntegrityFailure("EVENT_CANONICAL_JSON_MISMATCH")
                    validate_event(event)
                    expected_previous = None if prior is None else prior["record_hash"]
                    if (event["event_id"], event["event_version"], event["previous_event_version_hash"],
                            event["record_hash"], event["last_updated_timestamp"]) != (
                            row["event_id"], row["event_version"], row["previous_event_version_hash"],
                            row["record_hash"], row["last_updated_timestamp"]):
                        raise EventIntegrityFailure("EVENT_TYPED_COLUMN_MISMATCH")
                    if event["previous_event_version_hash"] != expected_previous:
                        raise EventIntegrityFailure("EVENT_PREDECESSOR_MISMATCH")
                    dep_rows = self.connection.execute(
                        "SELECT * FROM event_dependencies WHERE event_id=? AND event_version=? ORDER BY dependency_record_id",
                        (event_id, event["event_version"])).fetchall()
                    dep_ids = [row["dependency_record_id"] for row in dep_rows]
                    if set(dep_ids) != set(event["source_evidence_ids"]) or len(dep_ids) != len(event["source_evidence_ids"]):
                        raise EventIntegrityFailure("EVENT_DEPENDENCY_COVERAGE_MISMATCH")
                    evidence = self._load_evidence(event["source_evidence_ids"], verify_store=False)
                    evidence_by_id = {item["evidence_id"]: item for item in evidence}
                    for dep in dep_rows:
                        source = evidence_by_id.get(dep["dependency_record_id"])
                        if dep["dependency_record_type"] != "EVIDENCE":
                            raise EventIntegrityFailure("EVENT_DEPENDENCY_TYPE_INVALID")
                        if source is None or dep["dependency_record_hash"] != source["record_hash"]:
                            raise EventIntegrityFailure("EVENT_DEPENDENCY_HASH_MISMATCH")
                    self._validate_pit(event, evidence, prior)
                    self._verify_entity_binding(event["entity_resolution_version"], event["entities"], event["last_updated_timestamp"])
                    enforce_evidence_policy(event, evidence)
                    prior = event
                seen_series.add(event_id)
            orphans = self.connection.execute(
                "SELECT COUNT(*) FROM event_dependencies d LEFT JOIN event_records r "
                "ON r.event_id=d.event_id AND r.event_version=d.event_version WHERE r.event_id IS NULL").fetchone()[0]
            if orphans:
                raise EventIntegrityFailure("ORPHAN_EVENT_DEPENDENCY")
            record_series = {row[0] for row in self.connection.execute("SELECT DISTINCT event_id FROM event_records")}
            if record_series != seen_series:
                raise EventIntegrityFailure("EVENT_SERIES_COVERAGE_MISMATCH")
            return {"result": "PASS", "event_series": len(series_rows), "event_versions": event_count,
                    "authority": AUTHORITY}
        except EventIntegrityFailure:
            raise
        except Stage6EventError as exc:
            raise EventIntegrityFailure("EVENT_SEMANTIC_INTEGRITY_FAILURE") from exc
        except Exception as exc:
            raise EventIntegrityFailure("FULL_EVENT_STORE_INTEGRITY_FAILURE") from exc

    def update_event(self, *_args: object, **_kwargs: object) -> None:
        raise Stage6EventError("IMMUTABLE_EVENT_UPDATE_PROHIBITED")
