"""Append-only SQLite registry/evidence store; fixture-only and network-free."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .canonical import canonical_hash, canonical_json, parse_utc, sha256_bytes, utc_timestamp, without
from .errors import IdempotencyConflict, IntegrityFailure, Stage6IngestionError
from .raw_store import RawPayloadStore
from .registry import (
    AUTHORITY_LEVELS, SHA256_PATTERN, assert_source_approved_for_automated_ingestion,
    resolve_entity, resolve_source_record, verify_entity_registry, verify_source_registry,
)


STORE_SCHEMA_VERSION = "STAGE6_1A_STORE_V1"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
ARCHITECTURE_COMMIT = "d5bc19c7c2341f56bcaa8c890e0d95979dca878b"
AUTHORITY = "SHADOW_ONLY"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
PRODUCTION_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"
PAYLOAD_STATUSES = {"RETRIEVED", "PARTIAL", "QUARANTINED"}
FAILURE_STATUSES = {"NOT_FOUND", "ACCESS_DENIED", "FAILED"}
EVIDENCE_FIELDS = {
    "schema_version", "record_kind", "evidence_id", "source_id", "source_record_version",
    "source_record_hash", "authority_level", "source_reference", "source_registry_snapshot_id",
    "source_registry_version", "source_registry_hash", "entity_registry_snapshot_id",
    "entity_registry_version", "entity_registry_hash", "publication_timestamp_utc",
    "observed_timestamp_utc", "retrieved_timestamp_utc", "timestamp_order_verified",
    "content_hash", "raw_title", "raw_document_reference", "content_type", "language",
    "document_version", "raw_payload_reference", "raw_payload_hash", "entity_ids",
    "event_candidate_ids", "retrieval_status", "failure_reason", "failure_stage",
    "attempted_at_utc", "parent_evidence_id", "correction_of_evidence_id",
    "retraction_of_evidence_id", "record_hash",
}


class IngestionStore:
    def __init__(self, database: Path, raw_root: Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.raw_store = RawPayloadStore(raw_root)
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

    def __enter__(self) -> "IngestionStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript("""
        CREATE TABLE store_meta(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), store_schema_version TEXT NOT NULL,
          architecture_baseline_tag TEXT NOT NULL, architecture_baseline_commit TEXT NOT NULL,
          production_control_tag TEXT NOT NULL, production_control_commit TEXT NOT NULL,
          authority TEXT NOT NULL);
        CREATE TABLE registry_snapshots(
          snapshot_id TEXT PRIMARY KEY, registry_kind TEXT NOT NULL CHECK(registry_kind IN ('ENTITY','SOURCE')),
          registry_version INTEGER NOT NULL, registry_hash TEXT NOT NULL UNIQUE,
          previous_registry_hash TEXT, canonical_json TEXT NOT NULL,
          UNIQUE(registry_kind, registry_version));
        CREATE TABLE raw_payloads(
          raw_payload_hash TEXT PRIMARY KEY, relative_reference TEXT NOT NULL UNIQUE,
          byte_length INTEGER NOT NULL CHECK(byte_length>=0));
        CREATE TABLE ingestion_records(
          record_id TEXT PRIMARY KEY, record_kind TEXT NOT NULL,
          retrieval_status TEXT NOT NULL, source_registry_snapshot_id TEXT NOT NULL,
          entity_registry_snapshot_id TEXT NOT NULL, source_id TEXT NOT NULL,
          source_record_version INTEGER NOT NULL, source_record_hash TEXT NOT NULL,
          authority_level TEXT NOT NULL, raw_payload_reference TEXT, raw_payload_hash TEXT,
          canonical_json TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE,
          FOREIGN KEY(raw_payload_hash) REFERENCES raw_payloads(raw_payload_hash));
        CREATE TABLE idempotency_bindings(
          idempotency_key TEXT PRIMARY KEY, logical_input_json TEXT NOT NULL,
          logical_input_hash TEXT NOT NULL, record_id TEXT NOT NULL, record_hash TEXT NOT NULL,
          FOREIGN KEY(record_id) REFERENCES ingestion_records(record_id));
        """)
        self.connection.execute("INSERT INTO store_meta VALUES(1,?,?,?,?,?,?)", (
            STORE_SCHEMA_VERSION, ARCHITECTURE_TAG, ARCHITECTURE_COMMIT,
            PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY))
        for table in ("registry_snapshots", "raw_payloads", "ingestion_records", "idempotency_bindings", "store_meta"):
            self.connection.executescript(f"""
            CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_UPDATE'); END;
            CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_DELETE'); END;
            """)
        self.connection.commit()

    def _verify_metadata(self) -> None:
        try:
            row = self.connection.execute("SELECT * FROM store_meta WHERE singleton=1").fetchone()
            expected = (STORE_SCHEMA_VERSION, ARCHITECTURE_TAG, ARCHITECTURE_COMMIT,
                        PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY)
            actual = tuple(row[key] for key in ("store_schema_version", "architecture_baseline_tag",
                           "architecture_baseline_commit", "production_control_tag",
                           "production_control_commit", "authority"))
            if actual != expected:
                raise IntegrityFailure("STORE_METADATA_IDENTITY_MISMATCH")
        except (sqlite3.Error, TypeError) as exc:
            raise IntegrityFailure("STORE_METADATA_INVALID") from exc

    def _registry(self, snapshot_id: str, expected_kind: str) -> dict:
        row = self.connection.execute("SELECT * FROM registry_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None or row["registry_kind"] != expected_kind:
            raise IntegrityFailure("REFERENCED_REGISTRY_SNAPSHOT_MISSING")
        snapshot = json.loads(row["canonical_json"])
        if row["canonical_json"] != canonical_json(snapshot):
            raise IntegrityFailure("REGISTRY_CANONICAL_JSON_MISMATCH")
        verifier = verify_entity_registry if expected_kind == "ENTITY" else verify_source_registry
        verifier(snapshot)
        if row["registry_hash"] != snapshot["registry_hash"]:
            raise IntegrityFailure("REGISTRY_TYPED_COLUMN_MISMATCH")
        return snapshot

    def _verify_persisted_registry_chain(self, kind: str, target_snapshot_id: str) -> dict:
        target = self.connection.execute(
            "SELECT registry_version FROM registry_snapshots WHERE snapshot_id=? AND registry_kind=?",
            (target_snapshot_id, kind),
        ).fetchone()
        if target is None:
            raise IntegrityFailure("REFERENCED_REGISTRY_SNAPSHOT_MISSING")
        rows = self.connection.execute(
            "SELECT * FROM registry_snapshots WHERE registry_kind=? AND registry_version<=? ORDER BY registry_version",
            (kind, target["registry_version"]),
        ).fetchall()
        if not rows or rows[0]["registry_version"] != 1 or len(rows) != target["registry_version"]:
            raise IntegrityFailure("REGISTRY_CHAIN_PREDECESSOR_MISSING")
        prior = None
        exact = None
        verifier = verify_entity_registry if kind == "ENTITY" else verify_source_registry
        for row in rows:
            snapshot = json.loads(row["canonical_json"])
            if row["canonical_json"] != canonical_json(snapshot):
                raise IntegrityFailure("REGISTRY_CANONICAL_JSON_MISMATCH")
            verifier(snapshot, prior)
            if (row["snapshot_id"], row["registry_version"], row["registry_hash"], row["previous_registry_hash"]) != (
                    snapshot["registry_snapshot_id"], snapshot["registry_version"], snapshot["registry_hash"],
                    snapshot["previous_registry_hash"]):
                raise IntegrityFailure("REGISTRY_TYPED_COLUMN_MISMATCH")
            if row["snapshot_id"] == target_snapshot_id:
                exact = snapshot
            prior = snapshot
        if exact is None:
            raise IntegrityFailure("REFERENCED_REGISTRY_SNAPSHOT_MISSING")
        return exact

    @staticmethod
    def _verify_record_semantics(record: dict) -> None:
        if (not isinstance(record, dict) or set(record) != EVIDENCE_FIELDS
                or record.get("schema_version") != "STAGE6_EVIDENCE_V2"):
            raise IntegrityFailure("EVIDENCE_ENVELOPE_FIELDS_MISMATCH")
        for field in ("evidence_id", "source_id", "source_reference", "source_registry_snapshot_id",
                      "entity_registry_snapshot_id"):
            if not isinstance(record[field], str) or not record[field]:
                raise IntegrityFailure(f"EVIDENCE_STRING_FIELD_INVALID:{field}")
        for field in ("source_record_version", "source_registry_version", "entity_registry_version"):
            if type(record[field]) is not int or record[field] < 1:
                raise IntegrityFailure(f"EVIDENCE_VERSION_FIELD_INVALID:{field}")
        for field in ("source_record_hash", "source_registry_hash", "entity_registry_hash", "record_hash"):
            if not isinstance(record[field], str) or not SHA256_PATTERN.fullmatch(record[field]):
                raise IntegrityFailure(f"EVIDENCE_HASH_FIELD_INVALID:{field}")
        if record["authority_level"] not in AUTHORITY_LEVELS:
            raise IntegrityFailure("EVIDENCE_AUTHORITY_INVALID")
        for field in ("raw_title", "raw_document_reference", "content_type", "language", "document_version",
                      "raw_payload_reference", "failure_reason", "failure_stage"):
            if record[field] is not None and not isinstance(record[field], str):
                raise IntegrityFailure(f"EVIDENCE_NULLABLE_STRING_INVALID:{field}")
        for field in ("content_hash", "raw_payload_hash"):
            if record[field] is not None and (not isinstance(record[field], str)
                                              or not SHA256_PATTERN.fullmatch(record[field])):
                raise IntegrityFailure(f"EVIDENCE_HASH_FIELD_INVALID:{field}")
        for field in ("entity_ids", "event_candidate_ids"):
            values = record[field]
            if (not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values)
                    or len(values) != len(set(values))):
                raise IntegrityFailure(f"EVIDENCE_ID_ARRAY_INVALID:{field}")
        for field in ("parent_evidence_id", "correction_of_evidence_id", "retraction_of_evidence_id"):
            if record[field] is not None and (not isinstance(record[field], str) or not record[field]):
                raise IntegrityFailure(f"EVIDENCE_LINK_INVALID:{field}")
        status = record["retrieval_status"]
        if status in PAYLOAD_STATUSES:
            if record["record_kind"] != "EVIDENCE" or not str(record["evidence_id"]).startswith("S6EV_"):
                raise IntegrityFailure("EVIDENCE_KIND_OR_ID_INVALID")
            observed = utc_timestamp(record["observed_timestamp_utc"], "observed_timestamp_utc")
            retrieved = utc_timestamp(record["retrieved_timestamp_utc"], "retrieved_timestamp_utc")
            published = (utc_timestamp(record["publication_timestamp_utc"], "publication_timestamp_utc")
                         if record["publication_timestamp_utc"] is not None else None)
            if observed != record["observed_timestamp_utc"] or retrieved != record["retrieved_timestamp_utc"]:
                raise IntegrityFailure("EVIDENCE_TIMESTAMP_NOT_CANONICAL")
            if parse_utc(observed, "observed") > parse_utc(retrieved, "retrieved"):
                raise IntegrityFailure("EVIDENCE_TIMESTAMP_CHRONOLOGY_INVALID")
            if published is not None:
                if published != record["publication_timestamp_utc"] or parse_utc(published, "published") > parse_utc(observed, "observed"):
                    raise IntegrityFailure("EVIDENCE_TIMESTAMP_CHRONOLOGY_INVALID")
            if record["timestamp_order_verified"] is not (published is not None):
                if not (published is None and record["timestamp_order_verified"] is None):
                    raise IntegrityFailure("TIMESTAMP_ORDER_FLAG_INVALID")
            if any(record[key] is not None for key in ("failure_reason", "failure_stage", "attempted_at_utc")):
                raise IntegrityFailure("EVIDENCE_FAILURE_FIELDS_INVALID")
            for field in ("content_hash", "raw_payload_reference", "raw_payload_hash", "content_type",
                          "raw_document_reference"):
                if not isinstance(record[field], str) or not record[field]:
                    raise IntegrityFailure(f"EVIDENCE_PAYLOAD_FIELD_INVALID:{field}")
        elif status in FAILURE_STATUSES:
            if record["record_kind"] != "ACQUISITION_ATTEMPT" or not str(record["evidence_id"]).startswith("S6ACQ_"):
                raise IntegrityFailure("ACQUISITION_KIND_OR_ID_INVALID")
            attempted = utc_timestamp(record["attempted_at_utc"], "attempted_at_utc")
            if attempted != record["attempted_at_utc"] or not record["failure_reason"] or not record["failure_stage"]:
                raise IntegrityFailure("ACQUISITION_FAILURE_FIELDS_INVALID")
            if any(record[key] is not None for key in ("publication_timestamp_utc", "observed_timestamp_utc",
                                                       "retrieved_timestamp_utc", "timestamp_order_verified")):
                raise IntegrityFailure("ACQUISITION_TIMESTAMP_FIELDS_INVALID")
            if any(record[key] is not None for key in ("content_hash", "raw_payload_reference", "raw_payload_hash",
                                                       "raw_document_reference", "content_type")):
                raise IntegrityFailure("FAILURE_RECORD_FABRICATED_PAYLOAD")
        else:
            raise IntegrityFailure("RETRIEVAL_STATUS_INVALID")

    def import_registry(self, snapshot: dict) -> dict:
        schema = snapshot.get("schema_version")
        if schema == "STAGE6_ENTITY_REGISTRY_V1":
            kind, verifier = "ENTITY", verify_entity_registry
        elif schema == "STAGE6_SOURCE_REGISTRY_V1":
            kind, verifier = "SOURCE", verify_source_registry
        else:
            raise Stage6IngestionError("UNSUPPORTED_REGISTRY_SCHEMA")
        existing = self.connection.execute("SELECT * FROM registry_snapshots WHERE snapshot_id=?", (snapshot.get("registry_snapshot_id"),)).fetchone()
        serialized = canonical_json(snapshot)
        if existing:
            if existing["canonical_json"] != serialized:
                raise IntegrityFailure("REGISTRY_SNAPSHOT_ID_COLLISION")
            return {"status": "IDEMPOTENT_SUCCESS", "snapshot_id": existing["snapshot_id"]}
        prior_row = self.connection.execute(
            "SELECT canonical_json FROM registry_snapshots WHERE registry_kind=? ORDER BY registry_version DESC LIMIT 1", (kind,)).fetchone()
        prior = json.loads(prior_row[0]) if prior_row else None
        verifier(snapshot, prior)
        try:
            with self.connection:
                self.connection.execute("INSERT INTO registry_snapshots VALUES(?,?,?,?,?,?)", (
                    snapshot["registry_snapshot_id"], kind, snapshot["registry_version"],
                    snapshot["registry_hash"], snapshot["previous_registry_hash"], serialized))
        except sqlite3.IntegrityError as exc:
            raise IntegrityFailure("REGISTRY_VERSION_OR_HASH_CONFLICT") from exc
        return {"status": "CREATED", "snapshot_id": snapshot["registry_snapshot_id"]}

    def get_record(self, record_id: str) -> dict:
        row = self.connection.execute("SELECT canonical_json FROM ingestion_records WHERE record_id=?", (record_id,)).fetchone()
        if row is None:
            raise Stage6IngestionError("RECORD_NOT_FOUND")
        return json.loads(row[0])

    def _link_check(self, record_id: str, links: dict[str, str | None]) -> None:
        for link in links.values():
            if link is None:
                continue
            if link == record_id:
                raise Stage6IngestionError("EVIDENCE_SELF_REFERENCE")
            row = self.connection.execute("SELECT record_kind FROM ingestion_records WHERE record_id=?", (link,)).fetchone()
            if row is None or row[0] != "EVIDENCE":
                raise Stage6IngestionError("LINKED_EVIDENCE_NOT_FOUND")

    def _bindings(self, source_snapshot_id: str, entity_snapshot_id: str, source_id: str,
                  entity_ids: list[str], cutoff: str) -> tuple[dict, dict, dict]:
        source_registry = self._verify_persisted_registry_chain("SOURCE", source_snapshot_id)
        entity_registry = self._verify_persisted_registry_chain("ENTITY", entity_snapshot_id)
        cutoff_value = parse_utc(cutoff, "acquisition_cutoff")
        if (parse_utc(source_registry["as_of_timestamp"], "source_registry.as_of_timestamp") > cutoff_value
                or parse_utc(entity_registry["as_of_timestamp"], "entity_registry.as_of_timestamp") > cutoff_value):
            raise IntegrityFailure("REGISTRY_SNAPSHOT_FROM_FUTURE")
        source = resolve_source_record(source_registry, source_id, cutoff, require_usable=False)
        assert_source_approved_for_automated_ingestion(source)
        for entity_id in entity_ids:
            resolve_entity(entity_registry, entity_id, cutoff)
        return source_registry, entity_registry, source

    def _idempotent_existing(self, key: str, logical_json: str, logical_hash: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM idempotency_bindings WHERE idempotency_key=?", (key,)).fetchone()
        if row is None:
            return None
        if row["logical_input_json"] != logical_json or row["logical_input_hash"] != logical_hash:
            raise IdempotencyConflict("IDEMPOTENCY_CONFLICT")
        return {"status": "IDEMPOTENT_SUCCESS", "record": self.get_record(row["record_id"])}

    def _persist(self, key: str, logical: dict, envelope: dict, raw: tuple[str, str, int] | None) -> dict:
        logical_json = canonical_json(logical)
        logical_hash = canonical_hash(logical)
        existing = self._idempotent_existing(key, logical_json, logical_hash)
        if existing:
            return existing
        record_hash = canonical_hash(without(envelope, "record_hash"))
        envelope["record_hash"] = record_hash
        self._verify_record_semantics(envelope)
        serialized = canonical_json(envelope)
        with self.connection:
            if raw:
                self.connection.execute("INSERT OR IGNORE INTO raw_payloads VALUES(?,?,?)", raw)
            self.connection.execute("INSERT INTO ingestion_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                envelope["evidence_id"], envelope["record_kind"], envelope["retrieval_status"],
                envelope["source_registry_snapshot_id"], envelope["entity_registry_snapshot_id"],
                envelope["source_id"], envelope["source_record_version"], envelope["source_record_hash"],
                envelope["authority_level"], envelope["raw_payload_reference"], envelope["raw_payload_hash"],
                serialized, record_hash))
            self.connection.execute("INSERT INTO idempotency_bindings VALUES(?,?,?,?,?)", (
                key, logical_json, logical_hash, envelope["evidence_id"], record_hash))
        return {"status": "CREATED", "record": envelope}

    def capture_evidence(self, *, idempotency_key: str, source_registry_snapshot_id: str,
                         entity_registry_snapshot_id: str, source_id: str, source_reference: str,
                         raw_payload: bytes, content_type: str, publication_timestamp_utc: str | None,
                         observed_timestamp_utc: str, retrieved_timestamp_utc: str,
                         entity_ids: list[str], retrieval_status: str = "RETRIEVED",
                         raw_title: str | None = None, language: str | None = None,
                         document_version: str | None = None, event_candidate_ids: list[str] | None = None,
                         parent_evidence_id: str | None = None, correction_of_evidence_id: str | None = None,
                         retraction_of_evidence_id: str | None = None) -> dict:
        if retrieval_status not in PAYLOAD_STATUSES:
            raise Stage6IngestionError("INVALID_PAYLOAD_RETRIEVAL_STATUS")
        if not isinstance(source_reference, str) or not source_reference:
            raise Stage6IngestionError("SOURCE_REFERENCE_REQUIRED")
        if not isinstance(content_type, str) or not content_type:
            raise Stage6IngestionError("CONTENT_TYPE_REQUIRED")
        if not isinstance(raw_payload, bytes):
            raise Stage6IngestionError("RAW_PAYLOAD_MUST_BE_BYTES")
        events = event_candidate_ids or []
        if (not isinstance(entity_ids, list) or any(not isinstance(value, str) or not value for value in entity_ids)
                or len(entity_ids) != len(set(entity_ids))):
            raise Stage6IngestionError("ENTITY_IDS_INVALID")
        if (not isinstance(events, list) or any(not isinstance(value, str) or not value for value in events)
                or len(events) != len(set(events))):
            raise Stage6IngestionError("EVENT_CANDIDATE_IDS_INVALID")
        for link in (parent_evidence_id, correction_of_evidence_id, retraction_of_evidence_id):
            if link is not None and (not isinstance(link, str) or not link):
                raise Stage6IngestionError("EVIDENCE_LINK_INVALID")
        observed = utc_timestamp(observed_timestamp_utc, "observed_timestamp_utc")
        retrieved = utc_timestamp(retrieved_timestamp_utc, "retrieved_timestamp_utc")
        published = (utc_timestamp(publication_timestamp_utc, "publication_timestamp_utc")
                     if publication_timestamp_utc is not None else None)
        if parse_utc(observed, "observed") > parse_utc(retrieved, "retrieved") or (published and parse_utc(published, "published") > parse_utc(observed, "observed")):
            raise Stage6IngestionError("EVIDENCE_TIMESTAMP_CHRONOLOGY_INVALID")
        source_registry, entity_registry, source = self._bindings(
            source_registry_snapshot_id, entity_registry_snapshot_id, source_id, entity_ids, observed)
        payload_hash = sha256_bytes(raw_payload)
        logical = {"operation": "EVIDENCE", "key": idempotency_key, "source_registry_snapshot_id": source_registry_snapshot_id,
                   "entity_registry_snapshot_id": entity_registry_snapshot_id, "source_id": source_id,
                   "source_reference": source_reference, "raw_payload_hash": payload_hash, "content_type": content_type,
                   "publication": published, "observed": observed, "retrieved": retrieved, "entity_ids": entity_ids,
                   "retrieval_status": retrieval_status, "raw_title": raw_title, "language": language,
                   "document_version": document_version, "event_candidate_ids": events,
                   "parent": parent_evidence_id, "correction": correction_of_evidence_id, "retraction": retraction_of_evidence_id}
        logical_json, logical_hash = canonical_json(logical), canonical_hash(logical)
        existing = self._idempotent_existing(idempotency_key, logical_json, logical_hash)
        if existing:
            return existing
        record_id = "S6EV_" + canonical_hash({"idempotency_key": idempotency_key, "logical_hash": logical_hash})[:24]
        links = {"parent_evidence_id": parent_evidence_id, "correction_of_evidence_id": correction_of_evidence_id,
                 "retraction_of_evidence_id": retraction_of_evidence_id}
        self._link_check(record_id, links)
        raw_hash, raw_reference, size = self.raw_store.put(raw_payload)
        envelope = {
            "schema_version": "STAGE6_EVIDENCE_V2", "record_kind": "EVIDENCE", "evidence_id": record_id,
            "source_id": source_id, "source_record_version": source["source_record_version"],
            "source_record_hash": source["record_hash"], "authority_level": source["authority_level"],
            "source_reference": source_reference, "source_registry_snapshot_id": source_registry_snapshot_id,
            "source_registry_version": source_registry["registry_version"], "source_registry_hash": source_registry["registry_hash"],
            "entity_registry_snapshot_id": entity_registry_snapshot_id, "entity_registry_version": entity_registry["registry_version"],
            "entity_registry_hash": entity_registry["registry_hash"], "publication_timestamp_utc": published,
            "observed_timestamp_utc": observed, "retrieved_timestamp_utc": retrieved,
            "timestamp_order_verified": True if published else None, "content_hash": raw_hash,
            "raw_title": raw_title, "raw_document_reference": source_reference, "content_type": content_type,
            "language": language, "document_version": document_version, "raw_payload_reference": raw_reference,
            "raw_payload_hash": raw_hash, "entity_ids": list(entity_ids), "event_candidate_ids": events,
            "retrieval_status": retrieval_status, "failure_reason": None, "failure_stage": None, "attempted_at_utc": None,
            **links, "record_hash": ""
        }
        return self._persist(idempotency_key, logical, envelope, (raw_hash, raw_reference, size))

    def capture_acquisition_failure(self, *, idempotency_key: str, source_registry_snapshot_id: str,
                                    entity_registry_snapshot_id: str, source_id: str, source_reference: str,
                                    retrieval_status: str, failure_reason: str, failure_stage: str,
                                    attempted_at_utc: str, entity_ids: list[str] | None = None) -> dict:
        if retrieval_status not in FAILURE_STATUSES:
            raise Stage6IngestionError("INVALID_FAILURE_STATUS")
        if not failure_reason or not failure_stage:
            raise Stage6IngestionError("FAILURE_REASON_AND_STAGE_REQUIRED")
        if not isinstance(source_reference, str) or not source_reference:
            raise Stage6IngestionError("SOURCE_REFERENCE_REQUIRED")
        attempted = utc_timestamp(attempted_at_utc, "attempted_at_utc")
        entities = entity_ids or []
        if (not isinstance(entities, list) or any(not isinstance(value, str) or not value for value in entities)
                or len(entities) != len(set(entities))):
            raise Stage6IngestionError("ENTITY_IDS_INVALID")
        source_registry, entity_registry, source = self._bindings(
            source_registry_snapshot_id, entity_registry_snapshot_id, source_id, entities, attempted)
        logical = {"operation": "ACQUISITION_ATTEMPT", "key": idempotency_key,
                   "source_registry_snapshot_id": source_registry_snapshot_id,
                   "entity_registry_snapshot_id": entity_registry_snapshot_id, "source_id": source_id,
                   "source_reference": source_reference, "retrieval_status": retrieval_status,
                   "failure_reason": failure_reason, "failure_stage": failure_stage,
                   "attempted_at_utc": attempted, "entity_ids": entities}
        logical_hash = canonical_hash(logical)
        record_id = "S6ACQ_" + canonical_hash({"idempotency_key": idempotency_key, "logical_hash": logical_hash})[:24]
        envelope = {
            "schema_version": "STAGE6_EVIDENCE_V2", "record_kind": "ACQUISITION_ATTEMPT", "evidence_id": record_id,
            "source_id": source_id, "source_record_version": source["source_record_version"],
            "source_record_hash": source["record_hash"], "authority_level": source["authority_level"],
            "source_reference": source_reference, "source_registry_snapshot_id": source_registry_snapshot_id,
            "source_registry_version": source_registry["registry_version"], "source_registry_hash": source_registry["registry_hash"],
            "entity_registry_snapshot_id": entity_registry_snapshot_id, "entity_registry_version": entity_registry["registry_version"],
            "entity_registry_hash": entity_registry["registry_hash"], "publication_timestamp_utc": None,
            "observed_timestamp_utc": None, "retrieved_timestamp_utc": None, "timestamp_order_verified": None,
            "content_hash": None, "raw_title": None, "raw_document_reference": None, "content_type": None,
            "language": None, "document_version": None, "raw_payload_reference": None, "raw_payload_hash": None,
            "entity_ids": entities, "event_candidate_ids": [], "retrieval_status": retrieval_status,
            "failure_reason": failure_reason, "failure_stage": failure_stage, "attempted_at_utc": attempted,
            "parent_evidence_id": None, "correction_of_evidence_id": None, "retraction_of_evidence_id": None,
            "record_hash": ""
        }
        return self._persist(idempotency_key, logical, envelope, None)

    def integrity_check(self) -> dict:
        try:
            self._verify_metadata()
            if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise IntegrityFailure("SQLITE_INTEGRITY_FAILURE")
            if self.connection.execute("PRAGMA foreign_key_check").fetchall():
                raise IntegrityFailure("SQLITE_FOREIGN_KEY_FAILURE")
            registries: dict[str, dict] = {}
            for kind in ("ENTITY", "SOURCE"):
                prior = None
                rows = self.connection.execute("SELECT * FROM registry_snapshots WHERE registry_kind=? ORDER BY registry_version", (kind,)).fetchall()
                for row in rows:
                    snapshot = json.loads(row["canonical_json"])
                    if row["canonical_json"] != canonical_json(snapshot):
                        raise IntegrityFailure("REGISTRY_CANONICAL_JSON_MISMATCH")
                    verifier = verify_entity_registry if kind == "ENTITY" else verify_source_registry
                    verifier(snapshot, prior)
                    if (row["snapshot_id"], row["registry_version"], row["registry_hash"], row["previous_registry_hash"]) != (
                            snapshot["registry_snapshot_id"], snapshot["registry_version"], snapshot["registry_hash"], snapshot["previous_registry_hash"]):
                        raise IntegrityFailure("REGISTRY_TYPED_COLUMN_MISMATCH")
                    registries[row["snapshot_id"]] = snapshot
                    prior = snapshot
            raw_rows = {row["raw_payload_hash"]: row for row in self.connection.execute("SELECT * FROM raw_payloads")}
            for digest, row in raw_rows.items():
                path = self.raw_store.verify(digest, row["byte_length"])
                if row["relative_reference"] != self.raw_store.relative_reference(digest) or path != self.raw_store.path_for(digest):
                    raise IntegrityFailure("RAW_PAYLOAD_REFERENCE_MISMATCH")
            records: dict[str, dict] = {}
            for row in self.connection.execute("SELECT * FROM ingestion_records ORDER BY record_id"):
                record = json.loads(row["canonical_json"])
                if row["canonical_json"] != canonical_json(record):
                    raise IntegrityFailure("EVIDENCE_CANONICAL_JSON_MISMATCH")
                self._verify_record_semantics(record)
                if record["record_hash"] != canonical_hash(without(record, "record_hash")) or row["record_hash"] != record["record_hash"]:
                    raise IntegrityFailure("EVIDENCE_RECORD_HASH_MISMATCH")
                typed = (record["evidence_id"], record["record_kind"], record["retrieval_status"],
                         record["source_registry_snapshot_id"], record["entity_registry_snapshot_id"], record["source_id"],
                         record["source_record_version"], record["source_record_hash"], record["authority_level"],
                         record["raw_payload_reference"], record["raw_payload_hash"])
                stored = tuple(row[key] for key in ("record_id", "record_kind", "retrieval_status", "source_registry_snapshot_id",
                               "entity_registry_snapshot_id", "source_id", "source_record_version", "source_record_hash",
                               "authority_level", "raw_payload_reference", "raw_payload_hash"))
                if typed != stored:
                    raise IntegrityFailure("EVIDENCE_TYPED_COLUMN_MISMATCH")
                source_registry = registries.get(record["source_registry_snapshot_id"])
                entity_registry = registries.get(record["entity_registry_snapshot_id"])
                if not source_registry or not entity_registry:
                    raise IntegrityFailure("REFERENCED_REGISTRY_SNAPSHOT_MISSING")
                cutoff = record["observed_timestamp_utc"] or record["attempted_at_utc"]
                cutoff_value = parse_utc(cutoff, "acquisition_cutoff")
                if (parse_utc(source_registry["as_of_timestamp"], "source_registry.as_of_timestamp") > cutoff_value
                        or parse_utc(entity_registry["as_of_timestamp"], "entity_registry.as_of_timestamp") > cutoff_value):
                    raise IntegrityFailure("REGISTRY_SNAPSHOT_FROM_FUTURE")
                source = resolve_source_record(source_registry, record["source_id"], cutoff, require_usable=False)
                assert_source_approved_for_automated_ingestion(source)
                if (source["source_record_version"], source["record_hash"], source["authority_level"]) != (
                        record["source_record_version"], record["source_record_hash"], record["authority_level"]):
                    raise IntegrityFailure("SOURCE_RECORD_BINDING_MISMATCH")
                if (source_registry["registry_version"], source_registry["registry_hash"]) != (record["source_registry_version"], record["source_registry_hash"]):
                    raise IntegrityFailure("SOURCE_REGISTRY_BINDING_MISMATCH")
                if (entity_registry["registry_version"], entity_registry["registry_hash"]) != (record["entity_registry_version"], record["entity_registry_hash"]):
                    raise IntegrityFailure("ENTITY_REGISTRY_BINDING_MISMATCH")
                for entity_id in record["entity_ids"]:
                    resolve_entity(entity_registry, entity_id, cutoff)
                if record["record_kind"] == "EVIDENCE":
                    if not record["raw_payload_hash"] or record["raw_payload_hash"] not in raw_rows:
                        raise IntegrityFailure("PAYLOAD_REQUIRED_RECORD_MISSING_RAW")
                    self.raw_store.verify(record["raw_payload_hash"])
                    if record["content_hash"] != record["raw_payload_hash"]:
                        raise IntegrityFailure("CONTENT_HASH_CONTRACT_MISMATCH")
                elif any(record[key] is not None for key in ("raw_payload_reference", "raw_payload_hash", "content_hash")):
                    raise IntegrityFailure("FAILURE_RECORD_FABRICATED_PAYLOAD")
                records[record["evidence_id"]] = record
            for record in records.values():
                for key in ("parent_evidence_id", "correction_of_evidence_id", "retraction_of_evidence_id"):
                    link = record[key]
                    if link is not None and (link == record["evidence_id"] or link not in records or records[link]["record_kind"] != "EVIDENCE"):
                        raise IntegrityFailure("EVIDENCE_LINK_INVALID")
            bound_record_ids: set[str] = set()
            for row in self.connection.execute("SELECT * FROM idempotency_bindings"):
                logical = json.loads(row["logical_input_json"])
                if (row["logical_input_json"] != canonical_json(logical)
                        or canonical_hash(logical) != row["logical_input_hash"]):
                    raise IntegrityFailure("IDEMPOTENCY_LOGICAL_HASH_MISMATCH")
                record = records.get(row["record_id"])
                if not record or record["record_hash"] != row["record_hash"]:
                    raise IntegrityFailure("IDEMPOTENCY_BINDING_MISMATCH")
                bound_record_ids.add(row["record_id"])
            if bound_record_ids != set(records):
                raise IntegrityFailure("IDEMPOTENCY_BINDING_COVERAGE_MISMATCH")
            return {"result": "PASS", "registries": len(registries), "records": len(records),
                    "raw_payloads": len(raw_rows), "authority": AUTHORITY}
        except (IntegrityFailure, Stage6IngestionError, sqlite3.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, IntegrityFailure):
                raise
            raise IntegrityFailure("FULL_STORE_INTEGRITY_FAILURE") from exc

    def update_record(self, *_args: object, **_kwargs: object) -> None:
        raise Stage6IngestionError("IMMUTABLE_RECORD_UPDATE_PROHIBITED")
