"""Append-only Stage 6.2D decision store with cross-store deterministic replay."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_candidates import CandidateStore
from stage6_events import EventStore
from stage6_ingestion.canonical import canonical_json, parse_utc, utc_timestamp

from .errors import MaterializationConflict, MaterializationIntegrityFailure, Stage6MaterializationError
from .event_mapper import (MATERIALIZATION_SCHEMA_VERSION, build_expected_event,
                           build_materialization_record, materialization_batch_identity)
from .materialization_validation import validate_materialization
from .policy import (MATERIALIZER_VERSION, POLICY_ID, POLICY_VERSION, load_policy,
                     validate_policy)


STORE_SCHEMA_VERSION = "STAGE6_2D_MATERIALIZATION_STORE_V1"
AUTHORITY = "SHADOW_ONLY"
BASELINE_2C_TAG = "stage6-2c-event-candidate-classification-baseline"
BASELINE_2C_COMMIT = "5f1955aa83b02dfbd2bac28916cf64d55e3853c1"
BASELINE_2B_TAG = "stage6-2b-rss-item-extraction-baseline"
BASELINE_2B_COMMIT = "48a1f4f95e3a582abdf0c8d50bb1ead50474e2d4"
BASELINE_2A_TAG = "stage6-2a-event-intelligence-foundation-baseline"
BASELINE_2A_COMMIT = "850809db87b2d63380c532404ca8922bc8807a7b"
ARCHITECTURE_TAG = "stage6-decision-intelligence-architecture-baseline-v2"
ARCHITECTURE_COMMIT = "d5bc19c7c2341f56bcaa8c890e0d95979dca878b"
PRODUCTION_TAG = "stage5d5-live-paper-runner-baseline"
PRODUCTION_COMMIT = "74b2710f0e19bd403978da81e87f25a3059ace06"
EVENT_PREFIX = "stage6_2d_candidate:"


class MaterializationStore:
    def __init__(self, database: Path, candidate_store: CandidateStore, event_store: EventStore):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.candidate_store = candidate_store
        self.event_store = event_store
        self.policy, self.policy_json, self.policy_hash = load_policy()
        new = not self.database.exists()
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            if new:
                self._initialize()
            self._verify_metadata()
            self._verify_policy_snapshot()
        except Exception:
            self.connection.close()
            raise

    def __enter__(self) -> "MaterializationStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript("""
        CREATE TABLE materialization_store_meta(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), store_schema_version TEXT NOT NULL,
          materialization_schema_version TEXT NOT NULL, materializer_version TEXT NOT NULL,
          baseline_2c_tag TEXT NOT NULL, baseline_2c_commit TEXT NOT NULL,
          baseline_2b_tag TEXT NOT NULL, baseline_2b_commit TEXT NOT NULL,
          baseline_2a_tag TEXT NOT NULL, baseline_2a_commit TEXT NOT NULL,
          architecture_tag TEXT NOT NULL, architecture_commit TEXT NOT NULL,
          production_tag TEXT NOT NULL, production_commit TEXT NOT NULL, authority TEXT NOT NULL);
        CREATE TABLE materialization_policies(
          policy_id TEXT PRIMARY KEY, policy_version INTEGER NOT NULL UNIQUE,
          policy_hash TEXT NOT NULL UNIQUE, materializer_version TEXT NOT NULL,
          canonical_json TEXT NOT NULL);
        CREATE TABLE materialization_batches(
          materialization_batch_id TEXT PRIMARY KEY, batch_identity_hash TEXT NOT NULL UNIQUE,
          classification_batch_id TEXT NOT NULL, classification_batch_identity_hash TEXT NOT NULL,
          policy_id TEXT NOT NULL, policy_hash TEXT NOT NULL, materializer_version TEXT NOT NULL,
          classification_cutoff TEXT NOT NULL, materialization_cutoff TEXT NOT NULL,
          candidate_count INTEGER NOT NULL CHECK(candidate_count>=0),
          materialized_count INTEGER NOT NULL CHECK(materialized_count>=0),
          skipped_no_match_count INTEGER NOT NULL CHECK(skipped_no_match_count>=0),
          skipped_ambiguous_count INTEGER NOT NULL CHECK(skipped_ambiguous_count>=0),
          FOREIGN KEY(policy_id) REFERENCES materialization_policies(policy_id));
        CREATE TABLE materialization_records(
          materialization_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
          candidate_hash TEXT NOT NULL, decision_status TEXT NOT NULL,
          event_id TEXT, event_version INTEGER, event_record_hash TEXT,
          record_hash TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL,
          UNIQUE(candidate_id,candidate_hash,record_hash));
        CREATE TABLE batch_materializations(
          materialization_batch_id TEXT NOT NULL, materialization_id TEXT NOT NULL,
          candidate_ordinal INTEGER NOT NULL,
          PRIMARY KEY(materialization_batch_id,materialization_id),
          UNIQUE(materialization_batch_id,candidate_ordinal),
          FOREIGN KEY(materialization_batch_id) REFERENCES materialization_batches(materialization_batch_id),
          FOREIGN KEY(materialization_id) REFERENCES materialization_records(materialization_id));
        CREATE TABLE materialization_dependencies(
          materialization_id TEXT NOT NULL, dependency_record_id TEXT NOT NULL,
          dependency_record_hash TEXT NOT NULL, dependency_record_type TEXT NOT NULL
            CHECK(dependency_record_type IN ('EVENT_CANDIDATE','CLASSIFICATION_BATCH',
                  'MATERIALIZATION_POLICY','STAGE6_EVENT','EVIDENCE')),
          PRIMARY KEY(materialization_id,dependency_record_type),
          FOREIGN KEY(materialization_id) REFERENCES materialization_records(materialization_id));
        """)
        self.connection.execute("INSERT INTO materialization_store_meta VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            STORE_SCHEMA_VERSION, MATERIALIZATION_SCHEMA_VERSION, MATERIALIZER_VERSION,
            BASELINE_2C_TAG, BASELINE_2C_COMMIT, BASELINE_2B_TAG, BASELINE_2B_COMMIT,
            BASELINE_2A_TAG, BASELINE_2A_COMMIT, ARCHITECTURE_TAG, ARCHITECTURE_COMMIT,
            PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY))
        self.connection.execute("INSERT INTO materialization_policies VALUES(?,?,?,?,?)", (
            POLICY_ID, POLICY_VERSION, self.policy_hash, MATERIALIZER_VERSION, self.policy_json))
        for table in ("materialization_store_meta", "materialization_policies", "materialization_batches",
                      "materialization_records", "batch_materializations", "materialization_dependencies"):
            self.connection.executescript(f"""
            CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_UPDATE'); END;
            CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TABLE_DELETE'); END;
            """)
        self.connection.commit()

    def _verify_metadata(self) -> None:
        fields = ("store_schema_version", "materialization_schema_version", "materializer_version",
                  "baseline_2c_tag", "baseline_2c_commit", "baseline_2b_tag", "baseline_2b_commit",
                  "baseline_2a_tag", "baseline_2a_commit", "architecture_tag", "architecture_commit",
                  "production_tag", "production_commit", "authority")
        expected = (STORE_SCHEMA_VERSION, MATERIALIZATION_SCHEMA_VERSION, MATERIALIZER_VERSION,
                    BASELINE_2C_TAG, BASELINE_2C_COMMIT, BASELINE_2B_TAG, BASELINE_2B_COMMIT,
                    BASELINE_2A_TAG, BASELINE_2A_COMMIT, ARCHITECTURE_TAG, ARCHITECTURE_COMMIT,
                    PRODUCTION_TAG, PRODUCTION_COMMIT, AUTHORITY)
        try:
            row = self.connection.execute("SELECT * FROM materialization_store_meta WHERE singleton=1").fetchone()
            if row is None or tuple(row[field] for field in fields) != expected:
                raise MaterializationIntegrityFailure("MATERIALIZATION_STORE_METADATA_MISMATCH")
        except sqlite3.Error as exc:
            raise MaterializationIntegrityFailure("MATERIALIZATION_STORE_METADATA_INVALID") from exc

    def _verify_policy_snapshot(self) -> dict:
        row = self.connection.execute("SELECT * FROM materialization_policies WHERE policy_id=?", (POLICY_ID,)).fetchone()
        if row is None:
            raise MaterializationIntegrityFailure("MATERIALIZATION_POLICY_MISSING")
        try:
            stored = json.loads(row["canonical_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise MaterializationIntegrityFailure("MATERIALIZATION_POLICY_JSON_INVALID") from exc
        validate_policy(stored)
        if (row["canonical_json"] != canonical_json(stored) or row["policy_version"] != POLICY_VERSION
                or row["materializer_version"] != MATERIALIZER_VERSION
                or row["policy_hash"] != self.policy_hash or stored != self.policy):
            raise MaterializationIntegrityFailure("MATERIALIZATION_POLICY_SNAPSHOT_MISMATCH")
        return stored

    def _verify_upstream(self) -> None:
        try:
            if self.candidate_store.integrity_check().get("result") != "PASS":
                raise MaterializationIntegrityFailure("UPSTREAM_CANDIDATE_INTEGRITY_FAILED")
        except Exception as exc:
            if isinstance(exc, MaterializationIntegrityFailure):
                raise
            raise MaterializationIntegrityFailure("UPSTREAM_CANDIDATE_INTEGRITY_FAILED") from exc
        try:
            if self.event_store.integrity_check().get("result") != "PASS":
                raise MaterializationIntegrityFailure("UPSTREAM_EVENT_INTEGRITY_FAILED")
        except Exception as exc:
            if isinstance(exc, MaterializationIntegrityFailure):
                raise
            raise MaterializationIntegrityFailure("UPSTREAM_EVENT_INTEGRITY_FAILED") from exc

    def _classification_batch(self, batch_id: str) -> tuple[dict, list[dict]]:
        row = self.candidate_store.connection.execute(
            "SELECT * FROM classification_batches WHERE classification_batch_id=?", (batch_id,)).fetchone()
        if row is None:
            raise Stage6MaterializationError("CLASSIFICATION_BATCH_NOT_FOUND")
        batch = dict(row)
        candidates = [json.loads(item[0]) for item in self.candidate_store.connection.execute(
            "SELECT c.canonical_json FROM batch_candidates b JOIN candidate_records c "
            "ON c.candidate_id=b.candidate_id WHERE b.classification_batch_id=? ORDER BY b.item_ordinal", (batch_id,))]
        if len(candidates) != batch["candidate_count"]:
            raise MaterializationIntegrityFailure("CLASSIFICATION_BATCH_COVERAGE_MISMATCH")
        return batch, candidates

    def _lineage(self, candidate: dict) -> tuple[dict, dict]:
        extraction_row = self.candidate_store.extraction_store.connection.execute(
            "SELECT canonical_json FROM extracted_items WHERE extraction_id=?", (candidate["input_extraction_id"],)).fetchone()
        if extraction_row is None:
            raise MaterializationIntegrityFailure("MATERIALIZATION_EXTRACTION_MISSING")
        extraction = json.loads(extraction_row[0])
        if (candidate["input_extraction_hash"], candidate["upstream_parent_evidence_id"],
                candidate["upstream_parent_evidence_hash"]) != (extraction["record_hash"],
                extraction["parent_evidence_id"], extraction["parent_evidence_hash"]):
            raise MaterializationIntegrityFailure("MATERIALIZATION_CANDIDATE_EXTRACTION_LINEAGE_MISMATCH")
        ingestion = self.event_store.ingestion_store
        evidence_row = ingestion.connection.execute(
            "SELECT canonical_json FROM ingestion_records WHERE record_id=?", (extraction["parent_evidence_id"],)).fetchone()
        if evidence_row is None:
            raise MaterializationIntegrityFailure("MATERIALIZATION_EVIDENCE_MISSING")
        evidence = json.loads(evidence_row[0])
        if (evidence["record_hash"] != extraction["parent_evidence_hash"]
                or evidence["evidence_id"] != candidate["upstream_parent_evidence_id"]
                or evidence["record_hash"] != candidate["upstream_parent_evidence_hash"]):
            raise MaterializationIntegrityFailure("MATERIALIZATION_EVIDENCE_LINEAGE_MISMATCH")
        if evidence["authority_level"] != "PRIMARY_OFFICIAL":
            raise Stage6MaterializationError("PRIMARY_OFFICIAL_EVIDENCE_REQUIRED")
        return extraction, evidence

    @staticmethod
    def _verify_chronology(evidence: dict, extraction: dict, classification_batch: dict, cutoff: str) -> None:
        values = [parse_utc(evidence["retrieved_timestamp_utc"], "retrieved_timestamp_utc"),
                  parse_utc(extraction["extracted_at_cutoff"], "extracted_at_cutoff"),
                  parse_utc(classification_batch["classification_cutoff"], "classification_cutoff"),
                  parse_utc(cutoff, "materialization_cutoff")]
        if values != sorted(values):
            raise Stage6MaterializationError("MATERIALIZATION_CHRONOLOGY_INVALID")

    def _event_v1_only(self, event_id: str) -> None:
        versions = [row[0] for row in self.event_store.connection.execute(
            "SELECT event_version FROM event_records WHERE event_id=? ORDER BY event_version", (event_id,))]
        if versions != [1]:
            raise MaterializationIntegrityFailure("STAGE6_2D_EVENT_V1_ONLY_VIOLATION")

    def _expected_dependencies(self, record: dict) -> list[tuple[str, str, str]]:
        dependencies = [
            (record["candidate_id"], record["candidate_hash"], "EVENT_CANDIDATE"),
            (record["classification_batch_id"], record["classification_batch_identity_hash"], "CLASSIFICATION_BATCH"),
            (POLICY_ID, self.policy_hash, "MATERIALIZATION_POLICY"),
        ]
        if record["decision_status"] == "MATERIALIZED":
            dependencies.extend([
                (f'{record["event_id"]}:v1', record["event_record_hash"], "STAGE6_EVENT"),
                (record["upstream_evidence_id"], record["upstream_evidence_hash"], "EVIDENCE"),
            ])
        return dependencies

    def materialize_batch(self, *, classification_batch_id: str, materialization_cutoff: str) -> dict:
        self._verify_metadata(); self._verify_policy_snapshot(); self._verify_upstream()
        cutoff = utc_timestamp(materialization_cutoff, "materialization_cutoff")
        batch, candidates = self._classification_batch(classification_batch_id)
        if parse_utc(batch["classification_cutoff"], "classification_cutoff") > parse_utc(cutoff, "materialization_cutoff"):
            raise Stage6MaterializationError("MATERIALIZATION_CUTOFF_BEFORE_CLASSIFICATION")
        records = []
        for candidate in candidates:
            extraction, evidence = self._lineage(candidate)
            self._verify_chronology(evidence, extraction, batch, cutoff)
            event = None
            if candidate["classification_status"] == "MATCHED":
                if candidate["candidate_event_type"] is None or candidate["ambiguous_event_types"]:
                    raise Stage6MaterializationError("MATCHED_CANDIDATE_INVARIANT_FAILED")
                expected_event = build_expected_event(candidate, evidence, cutoff, self.policy)
                response = self.event_store.append_event(
                    event_key=EVENT_PREFIX + candidate["candidate_id"], event_version=1,
                    previous_event_version_hash=None,
                    source_evidence_ids=[evidence["evidence_id"]],
                    entity_resolution_version=evidence["entity_registry_snapshot_id"],
                    event_type=candidate["candidate_event_type"], **self.policy["event_defaults"],
                    first_known_timestamp=evidence["retrieved_timestamp_utc"], last_updated_timestamp=cutoff)
                if response["status"] not in {"CREATED", "IDEMPOTENT_SUCCESS"} or response["event"] != expected_event:
                    raise MaterializationIntegrityFailure("EVENTSTORE_RESULT_MISMATCH")
                event = response["event"]
                self._event_v1_only(event["event_id"])
            record = build_materialization_record(
                candidate=candidate, classification_batch=batch, policy=self.policy,
                policy_hash=self.policy_hash, materialization_cutoff=cutoff, event=event)
            validate_materialization(record, candidate)
            records.append(record)
        counts = {status: sum(record["decision_status"] == status for record in records)
                  for status in ("MATERIALIZED", "SKIPPED_NO_MATCH", "SKIPPED_AMBIGUOUS")}
        batch_id, identity_hash = materialization_batch_identity(
            classification_batch_id=classification_batch_id,
            classification_batch_identity_hash=batch["batch_identity_hash"], policy_id=POLICY_ID,
            policy_hash=self.policy_hash, materialization_cutoff=cutoff)
        existing_batch = self.connection.execute(
            "SELECT * FROM materialization_batches WHERE materialization_batch_id=?", (batch_id,)).fetchone()
        if existing_batch is not None:
            stored = [json.loads(row[0]) for row in self.connection.execute(
                "SELECT r.canonical_json FROM batch_materializations b JOIN materialization_records r "
                "ON r.materialization_id=b.materialization_id WHERE b.materialization_batch_id=? "
                "ORDER BY b.candidate_ordinal", (batch_id,))]
            if stored == records:
                return {"status": "IDEMPOTENT_SUCCESS", "materialization_batch_id": batch_id, "records": records}
            raise MaterializationConflict("INCOMPATIBLE_MATERIALIZATION_BATCH")
        try:
            with self.connection:
                self.connection.execute("INSERT INTO materialization_batches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    batch_id, identity_hash, classification_batch_id, batch["batch_identity_hash"],
                    POLICY_ID, self.policy_hash, MATERIALIZER_VERSION, batch["classification_cutoff"], cutoff,
                    len(records), counts["MATERIALIZED"], counts["SKIPPED_NO_MATCH"], counts["SKIPPED_AMBIGUOUS"]))
                for ordinal, record in enumerate(records):
                    existing = self.connection.execute(
                        "SELECT canonical_json FROM materialization_records WHERE materialization_id=?",
                        (record["materialization_id"],)).fetchone()
                    if existing is None:
                        self.connection.execute("INSERT INTO materialization_records VALUES(?,?,?,?,?,?,?,?,?)", (
                            record["materialization_id"], record["candidate_id"], record["candidate_hash"],
                            record["decision_status"], record["event_id"], record["event_version"],
                            record["event_record_hash"], record["record_hash"], canonical_json(record)))
                        self.connection.executemany("INSERT INTO materialization_dependencies VALUES(?,?,?,?)", [
                            (record["materialization_id"], dep_id, dep_hash, dep_type)
                            for dep_id, dep_hash, dep_type in self._expected_dependencies(record)])
                    elif existing[0] != canonical_json(record):
                        raise MaterializationConflict("INCOMPATIBLE_MATERIALIZATION_IDENTITY")
                    self.connection.execute("INSERT INTO batch_materializations VALUES(?,?,?)", (
                        batch_id, record["materialization_id"], ordinal))
        except sqlite3.IntegrityError as exc:
            raise MaterializationConflict("MATERIALIZATION_STORE_INSERT_CONFLICT") from exc
        return {"status": "CREATED", "materialization_batch_id": batch_id, "records": records}

    def integrity_check(self) -> dict:
        try:
            self._verify_metadata()
            if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise MaterializationIntegrityFailure("MATERIALIZATION_SQLITE_INTEGRITY_FAILURE")
            if self.connection.execute("PRAGMA foreign_key_check").fetchall():
                raise MaterializationIntegrityFailure("MATERIALIZATION_FOREIGN_KEY_FAILURE")
            policy = self._verify_policy_snapshot(); self._verify_upstream()
            tables = ("materialization_store_meta", "materialization_policies", "materialization_batches",
                      "materialization_records", "batch_materializations", "materialization_dependencies")
            for table in tables:
                triggers = {row[0] for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
                if triggers != {f"protect_{table}_update", f"protect_{table}_delete"}:
                    raise MaterializationIntegrityFailure("MATERIALIZATION_APPEND_ONLY_TRIGGER_MISSING")
            expected_ids: set[str] = set()
            batches = 0
            for stored_batch in self.connection.execute("SELECT * FROM materialization_batches ORDER BY materialization_batch_id"):
                batches += 1
                source_batch, candidates = self._classification_batch(stored_batch["classification_batch_id"])
                expected_batch_id, expected_batch_hash = materialization_batch_identity(
                    classification_batch_id=source_batch["classification_batch_id"],
                    classification_batch_identity_hash=source_batch["batch_identity_hash"], policy_id=POLICY_ID,
                    policy_hash=self.policy_hash, materialization_cutoff=stored_batch["materialization_cutoff"])
                batch_fields = (stored_batch["materialization_batch_id"], stored_batch["batch_identity_hash"],
                                stored_batch["classification_batch_identity_hash"], stored_batch["policy_id"],
                                stored_batch["policy_hash"], stored_batch["materializer_version"],
                                stored_batch["classification_cutoff"])
                expected_fields = (expected_batch_id, expected_batch_hash, source_batch["batch_identity_hash"],
                                   POLICY_ID, self.policy_hash, MATERIALIZER_VERSION, source_batch["classification_cutoff"])
                if batch_fields != expected_fields:
                    raise MaterializationIntegrityFailure("MATERIALIZATION_BATCH_IDENTITY_MISMATCH")
                rows = self.connection.execute(
                    "SELECT r.*,b.candidate_ordinal FROM batch_materializations b JOIN materialization_records r "
                    "ON r.materialization_id=b.materialization_id WHERE b.materialization_batch_id=? "
                    "ORDER BY b.candidate_ordinal", (stored_batch["materialization_batch_id"],)).fetchall()
                if len(rows) != len(candidates) or [row["candidate_ordinal"] for row in rows] != list(range(len(rows))):
                    raise MaterializationIntegrityFailure("MATERIALIZATION_BATCH_COVERAGE_MISMATCH")
                replay_records = []
                for candidate, row in zip(candidates, rows):
                    extraction, evidence = self._lineage(candidate)
                    self._verify_chronology(evidence, extraction, source_batch, stored_batch["materialization_cutoff"])
                    event = None
                    if candidate["classification_status"] == "MATCHED":
                        expected_event = build_expected_event(candidate, evidence, stored_batch["materialization_cutoff"], policy)
                        event = self.event_store.get_event(expected_event["event_id"], 1)
                        self._event_v1_only(event["event_id"])
                        if event != expected_event:
                            raise MaterializationIntegrityFailure("MATERIALIZED_EVENT_REPLAY_MISMATCH")
                    record = json.loads(row["canonical_json"])
                    if row["canonical_json"] != canonical_json(record):
                        raise MaterializationIntegrityFailure("MATERIALIZATION_CANONICAL_JSON_MISMATCH")
                    validate_materialization(record, candidate)
                    replay = build_materialization_record(
                        candidate=candidate, classification_batch=source_batch, policy=policy,
                        policy_hash=self.policy_hash, materialization_cutoff=stored_batch["materialization_cutoff"], event=event)
                    if record != replay:
                        raise MaterializationIntegrityFailure("MATERIALIZATION_REPLAY_MISMATCH")
                    typed = (record["materialization_id"], record["candidate_id"], record["candidate_hash"],
                             record["decision_status"], record["event_id"], record["event_version"],
                             record["event_record_hash"], record["record_hash"])
                    stored = tuple(row[field] for field in ("materialization_id", "candidate_id", "candidate_hash",
                                                            "decision_status", "event_id", "event_version",
                                                            "event_record_hash", "record_hash"))
                    if typed != stored:
                        raise MaterializationIntegrityFailure("MATERIALIZATION_TYPED_COLUMN_MISMATCH")
                    deps = {dep["dependency_record_type"]: dep for dep in self.connection.execute(
                        "SELECT * FROM materialization_dependencies WHERE materialization_id=?", (record["materialization_id"],))}
                    expected_deps = {dep_type: (dep_id, dep_hash) for dep_id, dep_hash, dep_type in self._expected_dependencies(record)}
                    if set(deps) != set(expected_deps):
                        raise MaterializationIntegrityFailure("MATERIALIZATION_DEPENDENCY_COVERAGE_MISMATCH")
                    for dep_type, expected in expected_deps.items():
                        if (deps[dep_type]["dependency_record_id"], deps[dep_type]["dependency_record_hash"]) != expected:
                            raise MaterializationIntegrityFailure("MATERIALIZATION_DEPENDENCY_MISMATCH")
                    replay_records.append(record); expected_ids.add(record["materialization_id"])
                counts = {status: sum(record["decision_status"] == status for record in replay_records)
                          for status in ("MATERIALIZED", "SKIPPED_NO_MATCH", "SKIPPED_AMBIGUOUS")}
                if (stored_batch["candidate_count"], stored_batch["materialized_count"],
                        stored_batch["skipped_no_match_count"], stored_batch["skipped_ambiguous_count"]) != (
                        len(replay_records), counts["MATERIALIZED"], counts["SKIPPED_NO_MATCH"],
                        counts["SKIPPED_AMBIGUOUS"]):
                    raise MaterializationIntegrityFailure("MATERIALIZATION_BATCH_COUNT_MISMATCH")
            all_records = {row[0] for row in self.connection.execute("SELECT materialization_id FROM materialization_records")}
            mapped = {row[0] for row in self.connection.execute("SELECT DISTINCT materialization_id FROM batch_materializations")}
            dependency_records = {row[0] for row in self.connection.execute("SELECT DISTINCT materialization_id FROM materialization_dependencies")}
            if all_records != expected_ids or mapped != all_records or dependency_records != all_records:
                raise MaterializationIntegrityFailure("MATERIALIZATION_ORPHAN_OR_COVERAGE_MISMATCH")
            materialized_events = {row[0] for row in self.connection.execute(
                "SELECT event_id FROM materialization_records WHERE decision_status='MATERIALIZED'")}
            owned_events = set()
            for series in self.event_store.connection.execute("SELECT event_id,event_key_json FROM event_series"):
                event_key = json.loads(series["event_key_json"]).get("event_key")
                if isinstance(event_key, str) and event_key.startswith(EVENT_PREFIX):
                    owned_events.add(series["event_id"])
            if owned_events != materialized_events:
                raise MaterializationIntegrityFailure("ORPHAN_STAGE6_2D_EVENT")
            return {"result": "PASS", "materialization_batches": batches,
                    "materialization_records": len(all_records), "materialized_events": len(materialized_events),
                    "policy_hash": self.policy_hash, "authority": AUTHORITY}
        except MaterializationIntegrityFailure:
            raise
        except Stage6MaterializationError as exc:
            raise MaterializationIntegrityFailure(f"MATERIALIZATION_SEMANTIC_INTEGRITY_FAILURE:{exc}") from exc
        except Exception as exc:
            raise MaterializationIntegrityFailure("FULL_MATERIALIZATION_INTEGRITY_FAILURE") from exc
