"""Append-only candidate store with extraction and classifier replay."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_extraction import ExtractionStore
from stage6_ingestion.canonical import canonical_json, parse_utc, utc_timestamp

from .candidate_builder import (CANDIDATE_SCHEMA_VERSION, build_candidate,
                                classification_batch_identity)
from .candidate_validation import validate_candidate
from .errors import CandidateConflict, CandidateIntegrityFailure, Stage6CandidateError
from .ruleset import (CLASSIFICATION_METHOD, CLASSIFIER_VERSION, RULESET_ID,
                      RULESET_VERSION, load_ruleset, validate_ruleset)


STORE_SCHEMA_VERSION = "STAGE6_2C_CANDIDATE_STORE_V1"
AUTHORITY = "SHADOW_ONLY"
BASELINE_2B_TAG = "stage6-2b-rss-item-extraction-baseline"
BASELINE_2B_COMMIT = "48a1f4f95e3a582abdf0c8d50bb1ead50474e2d4"
BASELINE_2A_TAG = "stage6-2a-event-intelligence-foundation-baseline"
BASELINE_2A_COMMIT = "850809db87b2d63380c532404ca8922bc8807a7b"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
ARCHITECTURE_COMMIT = "d5bc19c7c2341f56bcaa8c890e0d95979dca878b"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
PRODUCTION_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"


class CandidateStore:
    def __init__(self, database: Path, extraction_store: ExtractionStore):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.extraction_store = extraction_store
        self.ruleset, self.ruleset_json, self.ruleset_hash = load_ruleset()
        new = not self.database.exists()
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            if new:
                self._initialize()
            self._verify_metadata()
            self._verify_ruleset_snapshot()
        except Exception:
            self.connection.close()
            raise

    def __enter__(self) -> "CandidateStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript("""
        CREATE TABLE candidate_store_meta(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), store_schema_version TEXT NOT NULL,
          candidate_schema_version TEXT NOT NULL, classifier_version TEXT NOT NULL,
          classification_method TEXT NOT NULL, baseline_2b_tag TEXT NOT NULL, baseline_2b_commit TEXT NOT NULL,
          baseline_2a_tag TEXT NOT NULL, baseline_2a_commit TEXT NOT NULL,
          architecture_tag TEXT NOT NULL, architecture_commit TEXT NOT NULL,
          production_tag TEXT NOT NULL, production_commit TEXT NOT NULL, authority TEXT NOT NULL);
        CREATE TABLE candidate_rulesets(
          ruleset_id TEXT PRIMARY KEY, ruleset_version INTEGER NOT NULL UNIQUE,
          ruleset_hash TEXT NOT NULL UNIQUE, classifier_version TEXT NOT NULL, canonical_json TEXT NOT NULL);
        CREATE TABLE classification_batches(
          classification_batch_id TEXT PRIMARY KEY, batch_identity_hash TEXT NOT NULL UNIQUE,
          extraction_batch_id TEXT NOT NULL, extraction_batch_identity_hash TEXT NOT NULL,
          ruleset_id TEXT NOT NULL, ruleset_hash TEXT NOT NULL, classifier_version TEXT NOT NULL,
          classification_cutoff TEXT NOT NULL, candidate_count INTEGER NOT NULL CHECK(candidate_count>=0),
          FOREIGN KEY(ruleset_id) REFERENCES candidate_rulesets(ruleset_id));
        CREATE TABLE candidate_records(
          candidate_id TEXT PRIMARY KEY, input_extraction_id TEXT NOT NULL,
          input_extraction_hash TEXT NOT NULL, ruleset_hash TEXT NOT NULL, source_id TEXT NOT NULL,
          classification_status TEXT NOT NULL, candidate_event_type TEXT,
          record_hash TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL,
          UNIQUE(input_extraction_id,input_extraction_hash,ruleset_hash));
        CREATE TABLE batch_candidates(
          classification_batch_id TEXT NOT NULL, candidate_id TEXT NOT NULL, item_ordinal INTEGER NOT NULL,
          PRIMARY KEY(classification_batch_id,candidate_id), UNIQUE(classification_batch_id,item_ordinal),
          FOREIGN KEY(classification_batch_id) REFERENCES classification_batches(classification_batch_id),
          FOREIGN KEY(candidate_id) REFERENCES candidate_records(candidate_id));
        CREATE TABLE candidate_dependencies(
          candidate_id TEXT NOT NULL, dependency_record_id TEXT NOT NULL,
          dependency_record_hash TEXT NOT NULL, dependency_record_type TEXT NOT NULL
            CHECK(dependency_record_type IN ('RSS_ITEM_EXTRACTION','CLASSIFICATION_RULESET')),
          PRIMARY KEY(candidate_id,dependency_record_type),
          FOREIGN KEY(candidate_id) REFERENCES candidate_records(candidate_id));
        """)
        self.connection.execute("INSERT INTO candidate_store_meta VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            STORE_SCHEMA_VERSION, CANDIDATE_SCHEMA_VERSION, CLASSIFIER_VERSION, CLASSIFICATION_METHOD,
            BASELINE_2B_TAG, BASELINE_2B_COMMIT, BASELINE_2A_TAG, BASELINE_2A_COMMIT,
            ARCHITECTURE_TAG, ARCHITECTURE_COMMIT, PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY))
        self.connection.execute("INSERT INTO candidate_rulesets VALUES(?,?,?,?,?)", (
            RULESET_ID, RULESET_VERSION, self.ruleset_hash, CLASSIFIER_VERSION, self.ruleset_json))
        for table in ("candidate_store_meta", "candidate_rulesets", "classification_batches",
                      "candidate_records", "batch_candidates", "candidate_dependencies"):
            self.connection.executescript(f"""
            CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_UPDATE'); END;
            CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_DELETE'); END;
            """)
        self.connection.commit()

    def _verify_metadata(self) -> None:
        fields = ("store_schema_version", "candidate_schema_version", "classifier_version", "classification_method",
                  "baseline_2b_tag", "baseline_2b_commit", "baseline_2a_tag", "baseline_2a_commit",
                  "architecture_tag", "architecture_commit", "production_tag", "production_commit", "authority")
        expected = (STORE_SCHEMA_VERSION, CANDIDATE_SCHEMA_VERSION, CLASSIFIER_VERSION, CLASSIFICATION_METHOD,
                    BASELINE_2B_TAG, BASELINE_2B_COMMIT, BASELINE_2A_TAG, BASELINE_2A_COMMIT,
                    ARCHITECTURE_TAG, ARCHITECTURE_COMMIT, PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY)
        try:
            row = self.connection.execute("SELECT * FROM candidate_store_meta WHERE singleton=1").fetchone()
            if row is None or tuple(row[field] for field in fields) != expected:
                raise CandidateIntegrityFailure("CANDIDATE_STORE_METADATA_MISMATCH")
        except sqlite3.Error as exc:
            raise CandidateIntegrityFailure("CANDIDATE_STORE_METADATA_INVALID") from exc

    def _verify_ruleset_snapshot(self) -> dict:
        row = self.connection.execute("SELECT * FROM candidate_rulesets WHERE ruleset_id=?", (RULESET_ID,)).fetchone()
        if row is None:
            raise CandidateIntegrityFailure("CANDIDATE_RULESET_MISSING")
        try:
            stored = json.loads(row["canonical_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise CandidateIntegrityFailure("CANDIDATE_RULESET_JSON_INVALID") from exc
        validate_ruleset(stored)
        if (row["canonical_json"] != canonical_json(stored) or row["ruleset_version"] != stored["ruleset_version"]
                or row["classifier_version"] != stored["classifier_version"]
                or row["ruleset_hash"] != self.ruleset_hash or stored != self.ruleset):
            raise CandidateIntegrityFailure("CANDIDATE_RULESET_SNAPSHOT_MISMATCH")
        return stored

    def _verify_extraction(self) -> None:
        try:
            if self.extraction_store.integrity_check().get("result") != "PASS":
                raise CandidateIntegrityFailure("UPSTREAM_EXTRACTION_INTEGRITY_FAILED")
        except Exception as exc:
            if isinstance(exc, CandidateIntegrityFailure):
                raise
            raise CandidateIntegrityFailure("UPSTREAM_EXTRACTION_INTEGRITY_FAILED") from exc

    def _extraction_batch(self, batch_id: str) -> tuple[sqlite3.Row, list[dict]]:
        batch = self.extraction_store.connection.execute(
            "SELECT * FROM extraction_batches WHERE batch_id=?", (batch_id,)).fetchone()
        if batch is None:
            raise Stage6CandidateError("EXTRACTION_BATCH_NOT_FOUND")
        rows = self.extraction_store.connection.execute(
            "SELECT i.canonical_json FROM batch_items b JOIN extracted_items i ON i.extraction_id=b.extraction_id "
            "WHERE b.batch_id=? ORDER BY b.item_ordinal", (batch_id,)).fetchall()
        records = [json.loads(row[0]) for row in rows]
        if len(records) != batch["item_count"]:
            raise CandidateIntegrityFailure("EXTRACTION_BATCH_COVERAGE_MISMATCH")
        return batch, records

    def classify_batch(self, *, extraction_batch_id: str, classification_cutoff: str) -> dict:
        self._verify_metadata(); self._verify_ruleset_snapshot(); self._verify_extraction()
        cutoff = utc_timestamp(classification_cutoff, "classification_cutoff")
        extraction_batch, extractions = self._extraction_batch(extraction_batch_id)
        if parse_utc(extraction_batch["extraction_cutoff"], "extraction_cutoff") > parse_utc(cutoff, "classification_cutoff"):
            raise Stage6CandidateError("CLASSIFICATION_CUTOFF_BEFORE_EXTRACTION")
        candidates = [build_candidate(record, self.ruleset, self.ruleset_hash) for record in extractions]
        for candidate in candidates:
            validate_candidate(candidate, self.ruleset)
        batch_id, identity_hash = classification_batch_identity(
            extraction_batch_id=extraction_batch_id,
            extraction_batch_identity_hash=extraction_batch["batch_identity_hash"],
            ruleset_id=RULESET_ID, ruleset_hash=self.ruleset_hash, classification_cutoff=cutoff)
        existing_batch = self.connection.execute(
            "SELECT * FROM classification_batches WHERE classification_batch_id=?", (batch_id,)).fetchone()
        if existing_batch is not None:
            stored = [json.loads(row[0]) for row in self.connection.execute(
                "SELECT c.canonical_json FROM batch_candidates b JOIN candidate_records c ON c.candidate_id=b.candidate_id "
                "WHERE b.classification_batch_id=? ORDER BY b.item_ordinal", (batch_id,))]
            expected_batch = (identity_hash, extraction_batch_id, extraction_batch["batch_identity_hash"],
                              RULESET_ID, self.ruleset_hash, CLASSIFIER_VERSION, cutoff, len(candidates))
            actual_batch = tuple(existing_batch[field] for field in (
                "batch_identity_hash", "extraction_batch_id", "extraction_batch_identity_hash",
                "ruleset_id", "ruleset_hash", "classifier_version", "classification_cutoff", "candidate_count"))
            if actual_batch == expected_batch and stored == candidates:
                return {"status": "IDEMPOTENT_SUCCESS", "classification_batch_id": batch_id, "records": candidates}
            raise CandidateConflict("INCOMPATIBLE_CLASSIFICATION_BATCH")
        try:
            with self.connection:
                self.connection.execute("INSERT INTO classification_batches VALUES(?,?,?,?,?,?,?,?,?)", (
                    batch_id, identity_hash, extraction_batch_id, extraction_batch["batch_identity_hash"],
                    RULESET_ID, self.ruleset_hash, CLASSIFIER_VERSION, cutoff, len(candidates)))
                for extraction, candidate in zip(extractions, candidates):
                    existing = self.connection.execute(
                        "SELECT canonical_json FROM candidate_records WHERE candidate_id=?", (candidate["candidate_id"],)).fetchone()
                    if existing is None:
                        self.connection.execute("INSERT INTO candidate_records VALUES(?,?,?,?,?,?,?,?,?)", (
                            candidate["candidate_id"], candidate["input_extraction_id"], candidate["input_extraction_hash"],
                            candidate["ruleset_hash"], candidate["source_id"], candidate["classification_status"], candidate["candidate_event_type"],
                            candidate["record_hash"], canonical_json(candidate)))
                        self.connection.executemany("INSERT INTO candidate_dependencies VALUES(?,?,?,?)", [
                            (candidate["candidate_id"], extraction["extraction_id"], extraction["record_hash"], "RSS_ITEM_EXTRACTION"),
                            (candidate["candidate_id"], RULESET_ID, self.ruleset_hash, "CLASSIFICATION_RULESET"),
                        ])
                    elif existing[0] != canonical_json(candidate):
                        raise CandidateConflict("INCOMPATIBLE_CANDIDATE_IDENTITY")
                    self.connection.execute("INSERT INTO batch_candidates VALUES(?,?,?)", (
                        batch_id, candidate["candidate_id"], extraction["item_ordinal"]))
        except sqlite3.IntegrityError as exc:
            raise CandidateConflict("CANDIDATE_STORE_INSERT_CONFLICT") from exc
        return {"status": "CREATED", "classification_batch_id": batch_id, "records": candidates}

    def integrity_check(self) -> dict:
        try:
            self._verify_metadata()
            if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CandidateIntegrityFailure("CANDIDATE_SQLITE_INTEGRITY_FAILURE")
            if self.connection.execute("PRAGMA foreign_key_check").fetchall():
                raise CandidateIntegrityFailure("CANDIDATE_FOREIGN_KEY_FAILURE")
            ruleset = self._verify_ruleset_snapshot(); self._verify_extraction()
            tables = ("candidate_store_meta", "candidate_rulesets", "classification_batches",
                      "candidate_records", "batch_candidates", "candidate_dependencies")
            for table in tables:
                triggers = {row[0] for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
                if triggers != {f"protect_{table}_update", f"protect_{table}_delete"}:
                    raise CandidateIntegrityFailure("CANDIDATE_APPEND_ONLY_TRIGGER_MISSING")
            expected_candidate_ids: set[str] = set()
            batches = 0
            for batch in self.connection.execute("SELECT * FROM classification_batches ORDER BY classification_batch_id"):
                batches += 1
                extraction_batch, extractions = self._extraction_batch(batch["extraction_batch_id"])
                if parse_utc(extraction_batch["extraction_cutoff"], "extraction_cutoff") > parse_utc(batch["classification_cutoff"], "classification_cutoff"):
                    raise CandidateIntegrityFailure("CANDIDATE_BATCH_PIT_FAILURE")
                expected_id, expected_hash = classification_batch_identity(
                    extraction_batch_id=batch["extraction_batch_id"],
                    extraction_batch_identity_hash=extraction_batch["batch_identity_hash"],
                    ruleset_id=RULESET_ID, ruleset_hash=self.ruleset_hash,
                    classification_cutoff=batch["classification_cutoff"])
                if (batch["classification_batch_id"], batch["batch_identity_hash"], batch["extraction_batch_identity_hash"],
                        batch["ruleset_id"], batch["ruleset_hash"], batch["classifier_version"]) != (
                        expected_id, expected_hash, extraction_batch["batch_identity_hash"], RULESET_ID,
                        self.ruleset_hash, CLASSIFIER_VERSION):
                    raise CandidateIntegrityFailure("CANDIDATE_BATCH_IDENTITY_MISMATCH")
                expected = [build_candidate(record, ruleset, self.ruleset_hash) for record in extractions]
                rows = self.connection.execute(
                    "SELECT c.*,b.item_ordinal AS batch_ordinal FROM batch_candidates b JOIN candidate_records c "
                    "ON c.candidate_id=b.candidate_id WHERE b.classification_batch_id=? ORDER BY b.item_ordinal",
                    (batch["classification_batch_id"],)).fetchall()
                if batch["candidate_count"] != len(expected) or len(rows) != len(expected):
                    raise CandidateIntegrityFailure("CANDIDATE_BATCH_COUNT_MISMATCH")
                if [row["batch_ordinal"] for row in rows] != list(range(len(rows))):
                    raise CandidateIntegrityFailure("CANDIDATE_BATCH_ORDINAL_GAP")
                for extraction, replay, row in zip(extractions, expected, rows):
                    candidate = json.loads(row["canonical_json"])
                    if row["canonical_json"] != canonical_json(candidate):
                        raise CandidateIntegrityFailure("CANDIDATE_CANONICAL_JSON_MISMATCH")
                    validate_candidate(candidate, ruleset)
                    typed = (candidate["candidate_id"], candidate["input_extraction_id"], candidate["input_extraction_hash"], candidate["ruleset_hash"],
                             candidate["source_id"], candidate["classification_status"], candidate["candidate_event_type"],
                             candidate["record_hash"])
                    stored = tuple(row[field] for field in ("candidate_id", "input_extraction_id", "input_extraction_hash", "ruleset_hash",
                                                             "source_id", "classification_status", "candidate_event_type", "record_hash"))
                    if typed != stored:
                        raise CandidateIntegrityFailure("CANDIDATE_TYPED_COLUMN_MISMATCH")
                    if candidate != replay:
                        raise CandidateIntegrityFailure("CANDIDATE_CLASSIFIER_REPLAY_MISMATCH")
                    if (candidate["upstream_parent_evidence_id"], candidate["upstream_parent_evidence_hash"]) != (
                            extraction["parent_evidence_id"], extraction["parent_evidence_hash"]):
                        raise CandidateIntegrityFailure("CANDIDATE_UPSTREAM_LINEAGE_MISMATCH")
                    deps = {dep["dependency_record_type"]: dep for dep in self.connection.execute(
                        "SELECT * FROM candidate_dependencies WHERE candidate_id=?", (candidate["candidate_id"],))}
                    if set(deps) != {"RSS_ITEM_EXTRACTION", "CLASSIFICATION_RULESET"}:
                        raise CandidateIntegrityFailure("CANDIDATE_DEPENDENCY_COVERAGE_MISMATCH")
                    if (deps["RSS_ITEM_EXTRACTION"]["dependency_record_id"], deps["RSS_ITEM_EXTRACTION"]["dependency_record_hash"]) != (
                            extraction["extraction_id"], extraction["record_hash"]):
                        raise CandidateIntegrityFailure("CANDIDATE_EXTRACTION_DEPENDENCY_MISMATCH")
                    if (deps["CLASSIFICATION_RULESET"]["dependency_record_id"], deps["CLASSIFICATION_RULESET"]["dependency_record_hash"]) != (
                            RULESET_ID, self.ruleset_hash):
                        raise CandidateIntegrityFailure("CANDIDATE_RULESET_DEPENDENCY_MISMATCH")
                    expected_candidate_ids.add(candidate["candidate_id"])
            all_candidates = {row[0] for row in self.connection.execute("SELECT candidate_id FROM candidate_records")}
            dependency_candidates = {row[0] for row in self.connection.execute("SELECT DISTINCT candidate_id FROM candidate_dependencies")}
            mapped_candidates = {row[0] for row in self.connection.execute("SELECT DISTINCT candidate_id FROM batch_candidates")}
            if all_candidates != expected_candidate_ids or dependency_candidates != all_candidates or mapped_candidates != all_candidates:
                raise CandidateIntegrityFailure("CANDIDATE_ORPHAN_OR_COVERAGE_MISMATCH")
            return {"result": "PASS", "classification_batches": batches, "candidates": len(all_candidates),
                    "ruleset_hash": self.ruleset_hash, "authority": AUTHORITY}
        except CandidateIntegrityFailure:
            raise
        except Stage6CandidateError as exc:
            raise CandidateIntegrityFailure(f"CANDIDATE_SEMANTIC_INTEGRITY_FAILURE:{exc}") from exc
        except Exception as exc:
            raise CandidateIntegrityFailure("FULL_CANDIDATE_INTEGRITY_FAILURE") from exc
