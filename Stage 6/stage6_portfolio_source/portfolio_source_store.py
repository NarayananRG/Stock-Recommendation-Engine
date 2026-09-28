from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_json
from stage6_ingestion.registry import verify_entity_registry
from .errors import PortfolioSourceConflict, PortfolioSourceIntegrityFailure
from .policy import *
from .portfolio_source_builder import build_portfolio_source_snapshot
from .portfolio_source_validation import validate_portfolio_source_snapshot

TABLES = (
    "portfolio_source_store_meta", "portfolio_source_policies", "portfolio_constituent_contracts",
    "portfolio_source_snapshots", "portfolio_source_positions", "portfolio_source_pending_entries",
    "portfolio_source_bindings", "portfolio_source_dependencies",
)


class PortfolioSourceStore:
    def __init__(self, database: Path, entity_registry: dict):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.entity_registry = json.loads(canonical_json(verify_entity_registry(entity_registry)))
        self.policy, self.policy_json, self.policy_hash = load_policy()
        self.contract, self.contract_json, self.contract_hash = load_constituent_contract()
        new = not self.database.exists()
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        if new:
            self._initialize()
        self._verify_singletons()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.connection.close()

    def _initialize(self):
        self.connection.executescript("""
CREATE TABLE portfolio_source_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,payload_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,stage5d5_reference_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL,portfolio_context_blob TEXT NOT NULL);
CREATE TABLE portfolio_source_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_constituent_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_source_snapshots(source_snapshot_id TEXT PRIMARY KEY,source_export_id TEXT UNIQUE NOT NULL,source_export_hash TEXT NOT NULL,source_system TEXT NOT NULL,data_cutoff_timestamp TEXT NOT NULL,entity_registry_snapshot_id TEXT NOT NULL,entity_registry_hash TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,source_export_json TEXT NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_source_positions(source_snapshot_id TEXT NOT NULL,ordinal INTEGER NOT NULL,logical_key TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(source_snapshot_id,ordinal),UNIQUE(source_snapshot_id,logical_key),FOREIGN KEY(source_snapshot_id) REFERENCES portfolio_source_snapshots);
CREATE TABLE portfolio_source_pending_entries(source_snapshot_id TEXT NOT NULL,ordinal INTEGER NOT NULL,logical_key TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(source_snapshot_id,ordinal),UNIQUE(source_snapshot_id,logical_key),FOREIGN KEY(source_snapshot_id) REFERENCES portfolio_source_snapshots);
CREATE TABLE portfolio_source_bindings(source_snapshot_id TEXT NOT NULL,constituent_kind TEXT NOT NULL,constituent_key TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,recorded_at_utc TEXT NOT NULL,PRIMARY KEY(source_snapshot_id,constituent_kind,constituent_key,record_type,record_id),FOREIGN KEY(source_snapshot_id) REFERENCES portfolio_source_snapshots);
CREATE TABLE portfolio_source_dependencies(source_snapshot_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(source_snapshot_id,record_type,record_id),FOREIGN KEY(source_snapshot_id) REFERENCES portfolio_source_snapshots);
""")
        self.connection.execute("INSERT INTO portfolio_source_store_meta VALUES(1,?,?,?,?,?,?,?)", (
            STORE_SCHEMA_VERSION, SCHEMA_VERSION, BASELINE_COMMIT, STAGE5D5_REFERENCE_COMMIT,
            PROCESSOR_VERSION, AUTHORITY, PORTFOLIO_CONTEXT_BLOB))
        self.connection.execute("INSERT INTO portfolio_source_policies VALUES(?,?,?)", (
            POLICY_ID, self.policy_hash, self.policy_json))
        self.connection.execute("INSERT INTO portfolio_constituent_contracts VALUES(?,?,?)", (
            CONSTITUENT_CONTRACT_VERSION, self.contract_hash, self.contract_json))
        for table in TABLES:
            self.connection.executescript(
                f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;"
                f"CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
        self.connection.commit()

    def _verify_singletons(self):
        expected = (1, STORE_SCHEMA_VERSION, SCHEMA_VERSION, BASELINE_COMMIT,
                    STAGE5D5_REFERENCE_COMMIT, PROCESSOR_VERSION, AUTHORITY, PORTFOLIO_CONTEXT_BLOB)
        rows = self.connection.execute("SELECT * FROM portfolio_source_store_meta").fetchall()
        if len(rows) != 1 or tuple(rows[0]) != expected:
            raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_METADATA_MISMATCH")
        rows = self.connection.execute("SELECT * FROM portfolio_source_policies").fetchall()
        if len(rows) != 1 or tuple(rows[0]) != (POLICY_ID, self.policy_hash, self.policy_json):
            raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_POLICY_MISMATCH")
        rows = self.connection.execute("SELECT * FROM portfolio_constituent_contracts").fetchall()
        if len(rows) != 1 or tuple(rows[0]) != (CONSTITUENT_CONTRACT_VERSION, self.contract_hash, self.contract_json):
            raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_CONTRACT_MISMATCH")

    @staticmethod
    def _key(item: dict) -> str:
        return "|".join((item["company_entity_id"], item["ticker"], item["recommendation_id"]))

    def _dependencies(self, record: dict) -> list[tuple[str, str, str]]:
        values = {
            ("ENTITY_REGISTRY", record["entity_registry_snapshot_id"], record["entity_registry_hash"]),
            ("STAGE6_5A_POLICY", POLICY_ID, self.policy_hash),
            ("STAGE6_5A_CONSTITUENT_CONTRACT", CONSTITUENT_CONTRACT_VERSION, self.contract_hash),
        }
        for item in record["open_positions"] + record["pending_entries"]:
            values.update(("ENTITY_RECORD", x["entity_id"], x["record_hash"])
                          for x in item["entity_record_bindings"])
        return sorted(values)

    def freeze(self, source_export: dict) -> dict:
        self._verify_singletons()
        record = build_portfolio_source_snapshot(
            source_export=source_export, entity_registry=self.entity_registry,
            policy_hash=self.policy_hash, constituent_contract_hash=self.contract_hash)
        validate_portfolio_source_snapshot(record)
        text = canonical_json(record)
        source_text = canonical_json(source_export)
        old = self.connection.execute(
            "SELECT canonical_json FROM portfolio_source_snapshots WHERE source_export_id=?",
            (record["source_export_id"],)).fetchone()
        if old:
            if old[0] == text:
                return {"status": "IDEMPOTENT_SUCCESS", "portfolio_source_snapshot": record}
            raise PortfolioSourceConflict("PORTFOLIO_SOURCE_EXPORT_CONFLICT")
        with self.connection:
            self.connection.execute("INSERT INTO portfolio_source_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)", (
                record["source_snapshot_id"], record["source_export_id"], record["source_export_hash"],
                record["source_system"], record["data_cutoff_timestamp"],
                record["entity_registry_snapshot_id"], record["entity_registry_hash"], record["record_hash"],
                source_text, text))
            for kind, values, table in (
                ("POSITION", record["open_positions"], "portfolio_source_positions"),
                ("PENDING", record["pending_entries"], "portfolio_source_pending_entries")):
                for ordinal, item in enumerate(values, 1):
                    key = self._key(item)
                    self.connection.execute(f"INSERT INTO {table} VALUES(?,?,?,?)", (
                        record["source_snapshot_id"], ordinal, key, canonical_json(item)))
                    self.connection.executemany("INSERT INTO portfolio_source_bindings VALUES(?,?,?,?,?,?,?)", [
                        (record["source_snapshot_id"], kind, key, binding["record_type"], binding["record_id"],
                         binding["record_hash"], binding["recorded_or_persisted_at_utc"])
                        for binding in item["source_record_bindings"]])
            self.connection.executemany("INSERT INTO portfolio_source_dependencies VALUES(?,?,?,?)", [
                (record["source_snapshot_id"], *dependency) for dependency in self._dependencies(record)])
        return {"status": "CREATED", "portfolio_source_snapshot": record}

    def integrity_check(self) -> dict:
        self._verify_singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_SQLITE_INTEGRITY_FAILED")
        if self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_FOREIGN_KEY_FAILED")
        for table in TABLES:
            actual = {row[0] for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
            if actual != {f"protect_{table}_update", f"protect_{table}_delete"}:
                raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_TRIGGER_MISSING")
        count = 0
        for row in self.connection.execute("SELECT * FROM portfolio_source_snapshots"):
            count += 1
            stored = json.loads(row["canonical_json"])
            source_export = json.loads(row["source_export_json"])
            if canonical_json(source_export) != row["source_export_json"]:
                raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_EXPORT_CANONICAL_JSON_MISMATCH")
            validate_portfolio_source_snapshot(stored)
            replay = build_portfolio_source_snapshot(
                source_export=source_export, entity_registry=self.entity_registry,
                policy_hash=self.policy_hash, constituent_contract_hash=self.contract_hash)
            if replay != stored or canonical_json(stored) != row["canonical_json"]:
                raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_REPLAY_MISMATCH")
            typed = tuple(row[key] for key in (
                "source_snapshot_id", "source_export_id", "source_export_hash", "source_system",
                "data_cutoff_timestamp", "entity_registry_snapshot_id", "entity_registry_hash", "record_hash"))
            wanted = tuple(stored[key] for key in (
                "source_snapshot_id", "source_export_id", "source_export_hash", "source_system",
                "data_cutoff_timestamp", "entity_registry_snapshot_id", "entity_registry_hash", "record_hash"))
            if typed != wanted:
                raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_TYPED_COLUMN_MISMATCH")
            for table, field in (("portfolio_source_positions", "open_positions"),
                                 ("portfolio_source_pending_entries", "pending_entries")):
                rows = self.connection.execute(
                    f"SELECT * FROM {table} WHERE source_snapshot_id=? ORDER BY ordinal",
                    (stored["source_snapshot_id"],)).fetchall()
                if [json.loads(x["canonical_json"]) for x in rows] != stored[field]:
                    raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_CONSTITUENT_COVERAGE_MISMATCH")
                if [x["ordinal"] for x in rows] != list(range(1, len(rows) + 1)):
                    raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_CONSTITUENT_ORDINAL_MISMATCH")
                if [x["logical_key"] for x in rows] != [self._key(x) for x in stored[field]]:
                    raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_CONSTITUENT_KEY_MISMATCH")
            expected_bindings = set()
            for kind, values in (("POSITION", stored["open_positions"]), ("PENDING", stored["pending_entries"])):
                for item in values:
                    key = self._key(item)
                    expected_bindings.update((kind, key, x["record_type"], x["record_id"], x["record_hash"],
                                              x["recorded_or_persisted_at_utc"])
                                             for x in item["source_record_bindings"])
            actual_bindings = {tuple(x[k] for k in (
                "constituent_kind", "constituent_key", "record_type", "record_id", "record_hash", "recorded_at_utc"))
                for x in self.connection.execute("SELECT * FROM portfolio_source_bindings WHERE source_snapshot_id=?",
                                                 (stored["source_snapshot_id"],))}
            if actual_bindings != expected_bindings:
                raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_BINDING_COVERAGE_MISMATCH")
            actual_dependencies = {(x["record_type"], x["record_id"], x["record_hash"])
                                   for x in self.connection.execute(
                                       "SELECT * FROM portfolio_source_dependencies WHERE source_snapshot_id=?",
                                       (stored["source_snapshot_id"],))}
            if actual_dependencies != set(self._dependencies(stored)):
                raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_DEPENDENCY_MISMATCH")
        return {"result": "PASS", "portfolio_source_snapshots": count}
