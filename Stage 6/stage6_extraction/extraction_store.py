"""Append-only Stage 6.2B extraction store with deterministic parser replay."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json, parse_utc, sha256_bytes
from stage6_ingestion.evidence_store import IngestionStore

from .errors import ExtractionConflict, ExtractionIntegrityFailure, Stage6ExtractionError
from .extraction_builder import (EXTRACTION_SCHEMA_VERSION, batch_identity,
                                 build_extraction_record)
from .extraction_validation import validate_extraction_record
from .rss_item_parser import PARSER_VERSION, parse_feed_items


STORE_SCHEMA_VERSION = "STAGE6_2B_EXTRACTION_STORE_V1"
AUTHORITY = "SHADOW_ONLY"
SUPPORTED_SOURCES = {"SEBI_OFFICIAL_RSS", "RBI_OFFICIAL_PRESS_RELEASES_RSS"}
BASELINE_2A_TAG = "stage6-2a-event-intelligence-foundation-baseline"
BASELINE_2A_COMMIT = "850809db87b2d63380c532404ca8922bc8807a7b"
BASELINE_1C_TAG = "stage6-1c-multisource-rss-ingestion-baseline"
BASELINE_1C_COMMIT = "6046ea1bfcc13130581170c0d1a2ec50a1a2b2c5"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
ARCHITECTURE_COMMIT = "d5bc19c7c2341f56bcaa8c890e0d95979dca878b"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
PRODUCTION_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"


class ExtractionStore:
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

    def __enter__(self) -> "ExtractionStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript("""
        CREATE TABLE extraction_store_meta(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), store_schema_version TEXT NOT NULL,
          extraction_schema_version TEXT NOT NULL, parser_version TEXT NOT NULL,
          baseline_2a_tag TEXT NOT NULL, baseline_2a_commit TEXT NOT NULL,
          baseline_1c_tag TEXT NOT NULL, baseline_1c_commit TEXT NOT NULL,
          architecture_tag TEXT NOT NULL, architecture_commit TEXT NOT NULL,
          production_tag TEXT NOT NULL, production_commit TEXT NOT NULL, authority TEXT NOT NULL);
        CREATE TABLE extraction_batches(
          batch_id TEXT PRIMARY KEY, batch_identity_hash TEXT NOT NULL UNIQUE,
          parent_evidence_id TEXT NOT NULL, parent_evidence_hash TEXT NOT NULL,
          source_id TEXT NOT NULL, extraction_cutoff TEXT NOT NULL,
          parser_version TEXT NOT NULL, item_count INTEGER NOT NULL CHECK(item_count>=0));
        CREATE TABLE extracted_items(
          extraction_id TEXT PRIMARY KEY, parent_evidence_id TEXT NOT NULL,
          item_ordinal INTEGER NOT NULL CHECK(item_ordinal>=0), structural_locator TEXT NOT NULL,
          item_fingerprint TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL,
          UNIQUE(parent_evidence_id,item_ordinal), UNIQUE(parent_evidence_id,structural_locator));
        CREATE TABLE batch_items(
          batch_id TEXT NOT NULL, extraction_id TEXT NOT NULL, item_ordinal INTEGER NOT NULL,
          PRIMARY KEY(batch_id,extraction_id), UNIQUE(batch_id,item_ordinal),
          FOREIGN KEY(batch_id) REFERENCES extraction_batches(batch_id),
          FOREIGN KEY(extraction_id) REFERENCES extracted_items(extraction_id));
        CREATE TABLE extraction_dependencies(
          extraction_id TEXT PRIMARY KEY, dependency_record_id TEXT NOT NULL,
          dependency_record_hash TEXT NOT NULL, dependency_record_type TEXT NOT NULL CHECK(dependency_record_type='EVIDENCE'),
          FOREIGN KEY(extraction_id) REFERENCES extracted_items(extraction_id));
        """)
        self.connection.execute("INSERT INTO extraction_store_meta VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?)", (
            STORE_SCHEMA_VERSION, EXTRACTION_SCHEMA_VERSION, PARSER_VERSION,
            BASELINE_2A_TAG, BASELINE_2A_COMMIT, BASELINE_1C_TAG, BASELINE_1C_COMMIT,
            ARCHITECTURE_TAG, ARCHITECTURE_COMMIT, PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY))
        for table in ("extraction_store_meta", "extraction_batches", "extracted_items",
                      "batch_items", "extraction_dependencies"):
            self.connection.executescript(f"""
            CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_UPDATE'); END;
            CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_DELETE'); END;
            """)
        self.connection.commit()

    def _verify_metadata(self) -> None:
        fields = ("store_schema_version", "extraction_schema_version", "parser_version",
                  "baseline_2a_tag", "baseline_2a_commit", "baseline_1c_tag", "baseline_1c_commit",
                  "architecture_tag", "architecture_commit", "production_tag", "production_commit", "authority")
        expected = (STORE_SCHEMA_VERSION, EXTRACTION_SCHEMA_VERSION, PARSER_VERSION,
                    BASELINE_2A_TAG, BASELINE_2A_COMMIT, BASELINE_1C_TAG, BASELINE_1C_COMMIT,
                    ARCHITECTURE_TAG, ARCHITECTURE_COMMIT, PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY)
        try:
            row = self.connection.execute("SELECT * FROM extraction_store_meta WHERE singleton=1").fetchone()
            if row is None or tuple(row[field] for field in fields) != expected:
                raise ExtractionIntegrityFailure("EXTRACTION_STORE_METADATA_MISMATCH")
        except sqlite3.Error as exc:
            raise ExtractionIntegrityFailure("EXTRACTION_STORE_METADATA_INVALID") from exc

    def _verify_ingestion(self) -> None:
        try:
            if self.ingestion_store.integrity_check().get("result") != "PASS":
                raise ExtractionIntegrityFailure("UPSTREAM_INGESTION_INTEGRITY_FAILED")
        except Exception as exc:
            if isinstance(exc, ExtractionIntegrityFailure):
                raise
            raise ExtractionIntegrityFailure("UPSTREAM_INGESTION_INTEGRITY_FAILED") from exc

    def _load_parent(self, evidence_id: str, *, verify_store: bool = True) -> tuple[dict, bytes]:
        if verify_store:
            self._verify_ingestion()
        row = self.ingestion_store.connection.execute(
            "SELECT * FROM ingestion_records WHERE record_id=?", (evidence_id,)).fetchone()
        if row is None:
            raise ExtractionIntegrityFailure("PARENT_EVIDENCE_MISSING")
        try:
            parent = json.loads(row["canonical_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ExtractionIntegrityFailure("PARENT_EVIDENCE_JSON_INVALID") from exc
        if row["canonical_json"] != canonical_json(parent):
            raise ExtractionIntegrityFailure("PARENT_EVIDENCE_CANONICAL_MISMATCH")
        if parent.get("record_kind") != "EVIDENCE" or row["record_kind"] != "EVIDENCE":
            raise Stage6ExtractionError("PARENT_MUST_BE_EVIDENCE")
        if parent.get("retrieval_status") != "RETRIEVED" or row["retrieval_status"] != "RETRIEVED":
            raise Stage6ExtractionError("PARENT_MUST_BE_RETRIEVED")
        if parent.get("source_id") not in SUPPORTED_SOURCES:
            raise Stage6ExtractionError("UNSUPPORTED_EXTRACTION_SOURCE")
        if parent.get("record_hash") != canonical_hash({k: v for k, v in parent.items() if k != "record_hash"}) or row["record_hash"] != parent["record_hash"]:
            raise ExtractionIntegrityFailure("PARENT_EVIDENCE_HASH_MISMATCH")
        raw_hash, raw_reference = parent.get("raw_payload_hash"), parent.get("raw_payload_reference")
        if not raw_hash or not raw_reference:
            raise ExtractionIntegrityFailure("PARENT_RAW_PAYLOAD_BINDING_MISSING")
        try:
            path = self.ingestion_store.raw_store.verify(raw_hash)
            payload = path.read_bytes()
        except Exception as exc:
            raise ExtractionIntegrityFailure("PARENT_RAW_PAYLOAD_INVALID") from exc
        if sha256_bytes(payload) != raw_hash:
            raise ExtractionIntegrityFailure("PARENT_RAW_PAYLOAD_HASH_MISMATCH")
        if raw_reference != self.ingestion_store.raw_store.relative_reference(raw_hash):
            raise ExtractionIntegrityFailure("PARENT_RAW_REFERENCE_MISMATCH")
        return parent, payload

    @staticmethod
    def _pit(parent: dict, cutoff: str) -> None:
        if parse_utc(parent["retrieved_timestamp_utc"], "parent.retrieved") > parse_utc(cutoff, "extraction_cutoff"):
            raise Stage6ExtractionError("EXTRACTION_FUTURE_EVIDENCE_PROHIBITED")

    def extract(self, *, parent_evidence_id: str, extraction_cutoff: str) -> dict:
        from stage6_ingestion.canonical import utc_timestamp
        cutoff = utc_timestamp(extraction_cutoff, "extraction_cutoff")
        parent, payload = self._load_parent(parent_evidence_id)
        self._pit(parent, cutoff)
        parsed = parse_feed_items(payload)
        records = [build_extraction_record(parsed_item=item, parent=parent, cutoff=cutoff) for item in parsed]
        for record in records:
            validate_extraction_record(record)
        batch_id, identity_hash = batch_identity(parent["evidence_id"], parent["record_hash"], cutoff)
        existing = self.connection.execute("SELECT * FROM extraction_batches WHERE batch_id=?", (batch_id,)).fetchone()
        if existing is not None:
            stored = [json.loads(row[0]) for row in self.connection.execute(
                "SELECT i.canonical_json FROM batch_items b JOIN extracted_items i ON i.extraction_id=b.extraction_id "
                "WHERE b.batch_id=? ORDER BY b.item_ordinal", (batch_id,))]
            expected_batch = (identity_hash, parent["evidence_id"], parent["record_hash"], parent["source_id"], cutoff, PARSER_VERSION, len(records))
            actual_batch = tuple(existing[field] for field in ("batch_identity_hash", "parent_evidence_id", "parent_evidence_hash",
                                                                "source_id", "extraction_cutoff", "parser_version", "item_count"))
            if actual_batch == expected_batch and stored == records:
                return {"status": "IDEMPOTENT_SUCCESS", "batch_id": batch_id, "records": records}
            raise ExtractionConflict("INCOMPATIBLE_EXTRACTION_BATCH")
        prior = self.connection.execute("SELECT extraction_cutoff FROM extraction_batches WHERE parent_evidence_id=?", (parent_evidence_id,)).fetchone()
        if prior is not None:
            raise ExtractionConflict("PARENT_ALREADY_EXTRACTED_AT_DIFFERENT_CUTOFF")
        try:
            with self.connection:
                self.connection.execute("INSERT INTO extraction_batches VALUES(?,?,?,?,?,?,?,?)", (
                    batch_id, identity_hash, parent["evidence_id"], parent["record_hash"],
                    parent["source_id"], cutoff, PARSER_VERSION, len(records)))
                for record in records:
                    self.connection.execute("INSERT INTO extracted_items VALUES(?,?,?,?,?,?,?)", (
                        record["extraction_id"], parent["evidence_id"], record["item_ordinal"],
                        record["structural_locator"], record["item_fingerprint"], record["record_hash"], canonical_json(record)))
                    self.connection.execute("INSERT INTO batch_items VALUES(?,?,?)", (
                        batch_id, record["extraction_id"], record["item_ordinal"]))
                    self.connection.execute("INSERT INTO extraction_dependencies VALUES(?,?,?,?)", (
                        record["extraction_id"], parent["evidence_id"], parent["record_hash"], "EVIDENCE"))
        except sqlite3.IntegrityError as exc:
            raise ExtractionConflict("EXTRACTION_STORE_INSERT_CONFLICT") from exc
        return {"status": "CREATED", "batch_id": batch_id, "records": records}

    def integrity_check(self) -> dict:
        try:
            self._verify_metadata()
            if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ExtractionIntegrityFailure("EXTRACTION_SQLITE_INTEGRITY_FAILURE")
            if self.connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ExtractionIntegrityFailure("EXTRACTION_FOREIGN_KEY_FAILURE")
            self._verify_ingestion()
            tables = ("extraction_store_meta", "extraction_batches", "extracted_items", "batch_items", "extraction_dependencies")
            for table in tables:
                names = {row[0] for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
                if names != {f"protect_{table}_update", f"protect_{table}_delete"}:
                    raise ExtractionIntegrityFailure("EXTRACTION_APPEND_ONLY_TRIGGER_MISSING")
            expected_item_ids: set[str] = set()
            batch_count = 0
            for batch in self.connection.execute("SELECT * FROM extraction_batches ORDER BY batch_id"):
                batch_count += 1
                parent, payload = self._load_parent(batch["parent_evidence_id"], verify_store=False)
                self._pit(parent, batch["extraction_cutoff"])
                expected_id, expected_identity = batch_identity(parent["evidence_id"], parent["record_hash"],
                                                                 batch["extraction_cutoff"], batch["parser_version"])
                if (batch["batch_id"] != expected_id or batch["batch_identity_hash"] != expected_identity
                        or batch["parent_evidence_hash"] != parent["record_hash"]
                        or batch["source_id"] != parent["source_id"] or batch["parser_version"] != PARSER_VERSION):
                    raise ExtractionIntegrityFailure("EXTRACTION_BATCH_IDENTITY_MISMATCH")
                parsed = parse_feed_items(payload)
                expected = [build_extraction_record(parsed_item=item, parent=parent,
                                                     cutoff=batch["extraction_cutoff"], parser_version=batch["parser_version"])
                            for item in parsed]
                rows = self.connection.execute(
                    "SELECT i.*,b.item_ordinal AS batch_ordinal FROM batch_items b JOIN extracted_items i "
                    "ON i.extraction_id=b.extraction_id WHERE b.batch_id=? ORDER BY b.item_ordinal", (batch["batch_id"],)).fetchall()
                if batch["item_count"] != len(expected) or len(rows) != len(expected):
                    raise ExtractionIntegrityFailure("EXTRACTION_BATCH_ITEM_COUNT_MISMATCH")
                if [row["batch_ordinal"] for row in rows] != list(range(len(rows))):
                    raise ExtractionIntegrityFailure("EXTRACTION_ITEM_ORDINAL_GAP")
                for row, replay in zip(rows, expected):
                    record = json.loads(row["canonical_json"])
                    if row["canonical_json"] != canonical_json(record):
                        raise ExtractionIntegrityFailure("EXTRACTION_CANONICAL_JSON_MISMATCH")
                    validate_extraction_record(record)
                    typed = (record["extraction_id"], record["parent_evidence_id"], record["item_ordinal"],
                             record["structural_locator"], record["item_fingerprint"], record["record_hash"])
                    stored = tuple(row[field] for field in ("extraction_id", "parent_evidence_id", "item_ordinal",
                                                             "structural_locator", "item_fingerprint", "record_hash"))
                    if typed != stored:
                        raise ExtractionIntegrityFailure("EXTRACTION_TYPED_COLUMN_MISMATCH")
                    if record != replay:
                        raise ExtractionIntegrityFailure("EXTRACTION_PARSER_REPLAY_MISMATCH")
                    dep = self.connection.execute("SELECT * FROM extraction_dependencies WHERE extraction_id=?", (record["extraction_id"],)).fetchone()
                    if dep is None or (dep["dependency_record_id"], dep["dependency_record_hash"], dep["dependency_record_type"]) != (
                            parent["evidence_id"], parent["record_hash"], "EVIDENCE"):
                        raise ExtractionIntegrityFailure("EXTRACTION_DEPENDENCY_BINDING_MISMATCH")
                    expected_item_ids.add(record["extraction_id"])
            all_items = {row[0] for row in self.connection.execute("SELECT extraction_id FROM extracted_items")}
            all_dependencies = {row[0] for row in self.connection.execute("SELECT extraction_id FROM extraction_dependencies")}
            all_memberships = {row[0] for row in self.connection.execute("SELECT extraction_id FROM batch_items")}
            if all_items != expected_item_ids or all_dependencies != all_items or all_memberships != all_items:
                raise ExtractionIntegrityFailure("EXTRACTION_ORPHAN_OR_COVERAGE_MISMATCH")
            return {"result": "PASS", "batches": batch_count, "items": len(all_items),
                    "parser_version": PARSER_VERSION, "authority": AUTHORITY}
        except ExtractionIntegrityFailure:
            raise
        except Stage6ExtractionError as exc:
            raise ExtractionIntegrityFailure("EXTRACTION_SEMANTIC_INTEGRITY_FAILURE") from exc
        except Exception as exc:
            raise ExtractionIntegrityFailure("FULL_EXTRACTION_INTEGRITY_FAILURE") from exc
