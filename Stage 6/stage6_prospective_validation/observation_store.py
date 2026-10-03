"""Isolated append-only persistence for Stage 6.8C observations."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .checkpoint_builder import validate_checkpoint
from .errors import ProspectiveConflict, ProspectiveIntegrityFailure, Stage6ProspectiveError
from .observation_config import (
    AUTHORITY, OBSERVATION_CONTRACT, OBSERVATION_POLICY, OBSERVATION_STORE_SCHEMA,
    load_observation_contract, load_observation_policy,
)
from .recommendation_envelope import validate_envelope

TABLES = ("observation_store_meta", "cohort_fingerprints", "recommendation_audit_envelopes", "benchmark_checkpoints")


def validate_observation_store_path(database, repo_root, *, allow_test_runtime=False):
    database = Path(database).resolve(); repo = Path(repo_root).resolve()
    if allow_test_runtime:
        return database
    approved = (repo / "Stage 6/runtime/prospective_validation").resolve()
    try:
        database.relative_to(approved)
    except ValueError as exc:
        raise Stage6ProspectiveError("PROSPECTIVE_OBSERVATION_RUNTIME_BOUNDARY_VIOLATION") from exc
    lowered = {part.lower() for part in database.parts}
    if lowered & {"results", "fixtures", "fixture", "tests", "test"}:
        raise Stage6ProspectiveError("PROSPECTIVE_OBSERVATION_RUNTIME_BOUNDARY_VIOLATION")
    return database


class ProspectiveObservationStore:
    def __init__(self, database, repo_root, cohort_fingerprint, *, allow_test_runtime=False):
        self.database = validate_observation_store_path(database, repo_root, allow_test_runtime=allow_test_runtime)
        self.cohort = cohort_fingerprint
        if (self.cohort.get("cohort_fingerprint_id") is None
                or self.cohort.get("record_hash") != canonical_hash({k: v for k, v in self.cohort.items() if k != "record_hash"})):
            raise ProspectiveIntegrityFailure("COHORT_FINGERPRINT_INVALID")
        self.policy, self.policy_json, self.policy_hash = load_observation_policy()
        self.contract, self.contract_json, self.contract_hash = load_observation_contract()
        new = not self.database.exists()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        if new:
            self._initialize()
        try:
            self.integrity_check()
        except Exception:
            self.connection.close()
            raise

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self): self.connection.close()

    def _initialize(self):
        self.connection.executescript("""
CREATE TABLE observation_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema TEXT NOT NULL,policy_id TEXT NOT NULL,policy_hash TEXT NOT NULL,contract_id TEXT NOT NULL,contract_hash TEXT NOT NULL,authority TEXT NOT NULL,trading_authority INTEGER NOT NULL CHECK(trading_authority=0));
CREATE TABLE cohort_fingerprints(cohort_fingerprint_id TEXT PRIMARY KEY,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE recommendation_audit_envelopes(envelope_id TEXT PRIMARY KEY,recommendation_id TEXT UNIQUE NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE benchmark_checkpoints(checkpoint_id TEXT PRIMARY KEY,envelope_id TEXT NOT NULL,recommendation_id TEXT NOT NULL,checkpoint_type TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL,UNIQUE(recommendation_id,checkpoint_type),FOREIGN KEY(envelope_id) REFERENCES recommendation_audit_envelopes(envelope_id));
""")
        self.connection.execute("INSERT INTO observation_store_meta VALUES(1,?,?,?,?,?,?,0)", (OBSERVATION_STORE_SCHEMA, OBSERVATION_POLICY, self.policy_hash, OBSERVATION_CONTRACT, self.contract_hash, AUTHORITY))
        self.connection.execute("INSERT INTO cohort_fingerprints VALUES(?,?,?)", (self.cohort["cohort_fingerprint_id"], self.cohort["record_hash"], canonical_json(self.cohort)))
        for table in TABLES:
            self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END; CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
        self.connection.commit()

    def persist_envelope(self, envelope):
        validate_envelope(envelope)
        if envelope["cohort_fingerprint_binding"] != {"record_type": self.cohort["schema_version"], "record_id": self.cohort["cohort_fingerprint_id"], "record_hash": self.cohort["record_hash"]}:
            raise ProspectiveIntegrityFailure("ENVELOPE_COHORT_BINDING_INVALID")
        text = canonical_json(envelope)
        old = self.connection.execute("SELECT canonical_json FROM recommendation_audit_envelopes WHERE recommendation_id=? OR envelope_id=?", (envelope["recommendation_id"], envelope["envelope_id"])).fetchone()
        if old:
            if old[0] == text: return {"status": "IDEMPOTENT_SUCCESS", "envelope": envelope}
            raise ProspectiveConflict("RECOMMENDATION_ENVELOPE_CONFLICT")
        with self.connection:
            self.connection.execute("INSERT INTO recommendation_audit_envelopes VALUES(?,?,?,?)", (envelope["envelope_id"], envelope["recommendation_id"], envelope["record_hash"], text))
        return {"status": "CREATED", "envelope": envelope}

    def persist_checkpoint(self, checkpoint):
        validate_checkpoint(checkpoint)
        binding = checkpoint["recommendation_audit_envelope_binding"]
        row = self.connection.execute("SELECT recommendation_id,record_hash FROM recommendation_audit_envelopes WHERE envelope_id=?", (binding["record_id"],)).fetchone()
        if row is None or (row["recommendation_id"], row["record_hash"]) != (checkpoint["recommendation_id"], binding["record_hash"]):
            raise ProspectiveIntegrityFailure("CHECKPOINT_ENVELOPE_BINDING_INVALID")
        text = canonical_json(checkpoint)
        old = self.connection.execute("SELECT canonical_json FROM benchmark_checkpoints WHERE checkpoint_id=? OR (recommendation_id=? AND checkpoint_type=?)", (checkpoint["checkpoint_id"], checkpoint["recommendation_id"], checkpoint["checkpoint_type"])).fetchone()
        if old:
            if old[0] == text: return {"status": "IDEMPOTENT_SUCCESS", "checkpoint": checkpoint}
            raise ProspectiveConflict("BENCHMARK_CHECKPOINT_CONFLICT")
        with self.connection:
            self.connection.execute("INSERT INTO benchmark_checkpoints VALUES(?,?,?,?,?,?)", (checkpoint["checkpoint_id"], binding["record_id"], checkpoint["recommendation_id"], checkpoint["checkpoint_type"], checkpoint["record_hash"], text))
        return {"status": "CREATED", "checkpoint": checkpoint}

    def integrity_check(self):
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ProspectiveIntegrityFailure("OBSERVATION_SQLITE_INVALID")
        meta = self.connection.execute("SELECT * FROM observation_store_meta").fetchall()
        expected = (1, OBSERVATION_STORE_SCHEMA, OBSERVATION_POLICY, self.policy_hash, OBSERVATION_CONTRACT, self.contract_hash, AUTHORITY, 0)
        if len(meta) != 1 or tuple(meta[0]) != expected:
            raise ProspectiveIntegrityFailure("OBSERVATION_METADATA_INVALID")
        cohort = self.connection.execute("SELECT * FROM cohort_fingerprints").fetchall()
        if len(cohort) != 1 or (cohort[0]["cohort_fingerprint_id"], cohort[0]["record_hash"], cohort[0]["canonical_json"]) != (self.cohort["cohort_fingerprint_id"], self.cohort["record_hash"], canonical_json(self.cohort)):
            raise ProspectiveIntegrityFailure("OBSERVATION_COHORT_INVALID")
        for table in TABLES:
            triggers = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
            if triggers != {f"protect_{table}_update", f"protect_{table}_delete"}:
                raise ProspectiveIntegrityFailure("OBSERVATION_TRIGGER_MISSING")
        for row in self.connection.execute("SELECT * FROM recommendation_audit_envelopes"):
            value = json.loads(row["canonical_json"]); validate_envelope(value)
            if canonical_json(value) != row["canonical_json"] or (value["envelope_id"], value["recommendation_id"], value["record_hash"]) != (row["envelope_id"], row["recommendation_id"], row["record_hash"]):
                raise ProspectiveIntegrityFailure("STORED_ENVELOPE_INVALID")
            expected_cohort = {"record_type": self.cohort["schema_version"], "record_id": self.cohort["cohort_fingerprint_id"], "record_hash": self.cohort["record_hash"]}
            if value.get("cohort_fingerprint_binding") != expected_cohort:
                raise ProspectiveIntegrityFailure("STORED_ENVELOPE_COHORT_BINDING_INVALID")
        for row in self.connection.execute("SELECT * FROM benchmark_checkpoints"):
            value = json.loads(row["canonical_json"]); validate_checkpoint(value)
            if canonical_json(value) != row["canonical_json"] or (value["checkpoint_id"], value["recommendation_id"], value["checkpoint_type"], value["record_hash"]) != (row["checkpoint_id"], row["recommendation_id"], row["checkpoint_type"], row["record_hash"]):
                raise ProspectiveIntegrityFailure("STORED_CHECKPOINT_INVALID")
            envelope = self.connection.execute("SELECT recommendation_id,record_hash,canonical_json FROM recommendation_audit_envelopes WHERE envelope_id=?", (row["envelope_id"],)).fetchone()
            binding = value.get("recommendation_audit_envelope_binding", {})
            if (envelope is None or binding.get("record_id") != row["envelope_id"]
                    or binding.get("record_hash") != envelope["record_hash"]
                    or value.get("recommendation_id") != envelope["recommendation_id"]
                    or row["recommendation_id"] != envelope["recommendation_id"]):
                raise ProspectiveIntegrityFailure("STORED_CHECKPOINT_ENVELOPE_RELATIONSHIP_INVALID")
        return {"result": "PASS", "envelopes": self.connection.execute("SELECT count(*) FROM recommendation_audit_envelopes").fetchone()[0], "checkpoints": self.connection.execute("SELECT count(*) FROM benchmark_checkpoints").fetchone()[0], "authority": AUTHORITY, "trading_authority": False}
