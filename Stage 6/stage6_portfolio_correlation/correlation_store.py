from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .correlation_builder import build_portfolio_correlation
from .correlation_validation import validate_portfolio_correlation
from .errors import PortfolioCorrelationConflict, PortfolioCorrelationIntegrityFailure, Stage6PortfolioCorrelationError
from .policy import *

TABLES = (
    "portfolio_correlation_store_meta", "portfolio_correlation_policies",
    "portfolio_correlation_contracts", "portfolio_correlation_records",
    "portfolio_correlation_series", "portfolio_correlation_observations",
    "portfolio_correlation_pairs", "portfolio_correlation_source_bindings",
    "portfolio_correlation_dependencies",
)


class PortfolioCorrelationStore:
    def __init__(self, database: Path, arithmetic_store):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.arithmetic_store = arithmetic_store
        self.policy, self.policy_json, self.policy_hash = load_policy()
        self.contract, self.contract_json, self.contract_hash = load_correlation_contract()
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
CREATE TABLE portfolio_correlation_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,payload_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL,portfolio_context_blob TEXT NOT NULL);
CREATE TABLE portfolio_correlation_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_correlation_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_correlation_records(correlation_context_id TEXT PRIMARY KEY,arithmetic_record_id TEXT NOT NULL,arithmetic_record_hash TEXT NOT NULL,source_export_id TEXT UNIQUE NOT NULL,source_export_hash TEXT NOT NULL,manifest_hash TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_correlation_series(correlation_context_id TEXT NOT NULL,ordinal INTEGER NOT NULL,company_entity_id TEXT NOT NULL,status TEXT NOT NULL,series_hash TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(correlation_context_id,ordinal),UNIQUE(correlation_context_id,company_entity_id),FOREIGN KEY(correlation_context_id) REFERENCES portfolio_correlation_records);
CREATE TABLE portfolio_correlation_observations(correlation_context_id TEXT NOT NULL,company_entity_id TEXT NOT NULL,ordinal INTEGER NOT NULL,period_end_utc TEXT NOT NULL,source_record_id TEXT NOT NULL,source_record_hash TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(correlation_context_id,company_entity_id,ordinal),UNIQUE(correlation_context_id,company_entity_id,period_end_utc),FOREIGN KEY(correlation_context_id) REFERENCES portfolio_correlation_records);
CREATE TABLE portfolio_correlation_pairs(correlation_context_id TEXT NOT NULL,ordinal INTEGER NOT NULL,left_member TEXT NOT NULL,right_member TEXT NOT NULL,status TEXT NOT NULL,value_json TEXT NOT NULL,pair_hash TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(correlation_context_id,ordinal),UNIQUE(correlation_context_id,left_member,right_member),FOREIGN KEY(correlation_context_id) REFERENCES portfolio_correlation_records);
CREATE TABLE portfolio_correlation_source_bindings(correlation_context_id TEXT PRIMARY KEY,source_system TEXT NOT NULL,source_export_id TEXT NOT NULL,source_export_hash TEXT NOT NULL,source_dataset_id TEXT NOT NULL,source_schema_version TEXT NOT NULL,manifest_hash TEXT NOT NULL,canonical_json TEXT NOT NULL,FOREIGN KEY(correlation_context_id) REFERENCES portfolio_correlation_records);
CREATE TABLE portfolio_correlation_dependencies(correlation_context_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(correlation_context_id,record_type,record_id),FOREIGN KEY(correlation_context_id) REFERENCES portfolio_correlation_records);
""")
        self.connection.execute("INSERT INTO portfolio_correlation_store_meta VALUES(1,?,?,?,?,?,?)", (
            STORE_SCHEMA_VERSION, SCHEMA_VERSION, BASELINE_COMMIT, PROCESSOR_VERSION, AUTHORITY,
            PORTFOLIO_CONTEXT_BLOB))
        self.connection.execute("INSERT INTO portfolio_correlation_policies VALUES(?,?,?)", (
            POLICY_ID, self.policy_hash, self.policy_json))
        self.connection.execute("INSERT INTO portfolio_correlation_contracts VALUES(?,?,?)", (
            CORRELATION_CONTRACT_VERSION, self.contract_hash, self.contract_json))
        for table in TABLES:
            self.connection.executescript(
                f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;"
                f"CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
        self.connection.commit()

    def _verify_singletons(self):
        meta = self.connection.execute("SELECT * FROM portfolio_correlation_store_meta").fetchall()
        expected = (1, STORE_SCHEMA_VERSION, SCHEMA_VERSION, BASELINE_COMMIT, PROCESSOR_VERSION,
                    AUTHORITY, PORTFOLIO_CONTEXT_BLOB)
        if len(meta) != 1 or tuple(meta[0]) != expected:
            raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_METADATA_MISMATCH")
        policy = self.connection.execute("SELECT * FROM portfolio_correlation_policies").fetchall()
        if len(policy) != 1 or tuple(policy[0]) != (POLICY_ID, self.policy_hash, self.policy_json):
            raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_POLICY_MISMATCH")
        contract = self.connection.execute("SELECT * FROM portfolio_correlation_contracts").fetchall()
        if len(contract) != 1 or tuple(contract[0]) != (CORRELATION_CONTRACT_VERSION, self.contract_hash, self.contract_json):
            raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_CONTRACT_MISMATCH")

    def _arithmetic(self, arithmetic_record_id):
        try:
            result = self.arithmetic_store.integrity_check()
        except Exception as exc:
            raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_ARITHMETIC_INTEGRITY_REQUIRED") from exc
        if result.get("result") != "PASS":
            raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_ARITHMETIC_INTEGRITY_REQUIRED")
        row = self.arithmetic_store.connection.execute(
            "SELECT canonical_json FROM portfolio_arithmetic_records WHERE arithmetic_record_id=?",
            (arithmetic_record_id,)).fetchone()
        if row is None:
            raise Stage6PortfolioCorrelationError("PORTFOLIO_ARITHMETIC_RECORD_NOT_FOUND")
        return json.loads(row[0])

    def _dependencies(self, record):
        return [
            ("STAGE6_5B_PORTFOLIO_ARITHMETIC", record["arithmetic_record_id"], record["arithmetic_record_hash"]),
            ("STAGE6_5C_POLICY", POLICY_ID, self.policy_hash),
            ("STAGE6_5C_CORRELATION_CONTRACT", CORRELATION_CONTRACT_VERSION, self.contract_hash),
        ]

    def calculate(self, *, arithmetic_record_id, return_history_manifest):
        self._verify_singletons()
        arithmetic = self._arithmetic(arithmetic_record_id)
        record = build_portfolio_correlation(
            arithmetic_record=arithmetic, return_history_manifest=return_history_manifest,
            policy_hash=self.policy_hash, correlation_contract_hash=self.contract_hash)
        validate_portfolio_correlation(record)
        text = canonical_json(record)
        export_id = record["return_history_manifest"]["source_export_id"]
        existing = self.connection.execute(
            "SELECT canonical_json FROM portfolio_correlation_records WHERE source_export_id=?",
            (export_id,)).fetchone()
        if existing:
            if existing[0] == text:
                return {"status": "IDEMPOTENT_SUCCESS", "portfolio_correlation": record}
            raise PortfolioCorrelationConflict("PORTFOLIO_CORRELATION_EXPORT_CONFLICT")
        manifest = record["return_history_manifest"]
        with self.connection:
            self.connection.execute("INSERT INTO portfolio_correlation_records VALUES(?,?,?,?,?,?,?,?)", (
                record["correlation_context_id"], arithmetic_record_id, record["arithmetic_record_hash"],
                export_id, manifest["source_export_hash"], record["return_history_manifest_hash"],
                record["record_hash"], text))
            for ordinal, series in enumerate(manifest["series"], 1):
                self.connection.execute("INSERT INTO portfolio_correlation_series VALUES(?,?,?,?,?,?)", (
                    record["correlation_context_id"], ordinal, series["company_entity_id"], series["status"],
                    canonical_hash(series),
                    canonical_json(series)))
                for obs_ordinal, observation in enumerate(series["observations"], 1):
                    self.connection.execute("INSERT INTO portfolio_correlation_observations VALUES(?,?,?,?,?,?,?)", (
                        record["correlation_context_id"], series["company_entity_id"], obs_ordinal,
                        observation["period_end_utc"], observation["source_record_id"],
                        observation["source_record_hash"], canonical_json(observation)))
            for ordinal, pair in enumerate(record["pairwise_correlations"], 1):
                members = pair["correlation"]["members"]
                self.connection.execute("INSERT INTO portfolio_correlation_pairs VALUES(?,?,?,?,?,?,?,?)", (
                    record["correlation_context_id"], ordinal, members[0], members[1],
                    pair["calculation_status"], canonical_json(pair["correlation"]["value"]),
                    canonical_hash(pair),
                    canonical_json(pair)))
            binding = {k: manifest[k] for k in ("source_system", "source_export_id", "source_export_hash",
                                                  "source_dataset_id", "source_schema_version")}
            binding["return_history_manifest_hash"] = record["return_history_manifest_hash"]
            self.connection.execute("INSERT INTO portfolio_correlation_source_bindings VALUES(?,?,?,?,?,?,?,?)", (
                record["correlation_context_id"], manifest["source_system"], export_id,
                manifest["source_export_hash"], manifest["source_dataset_id"], manifest["source_schema_version"],
                record["return_history_manifest_hash"], canonical_json(binding)))
            self.connection.executemany("INSERT INTO portfolio_correlation_dependencies VALUES(?,?,?,?)", [
                (record["correlation_context_id"], *d) for d in self._dependencies(record)])
        return {"status": "CREATED", "portfolio_correlation": record}

    def integrity_check(self):
        self._verify_singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_SQLITE_INTEGRITY_FAILED")
        if self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_FOREIGN_KEY_FAILED")
        for table in TABLES:
            triggers = {r[0] for r in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
            if triggers != {f"protect_{table}_update", f"protect_{table}_delete"}:
                raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_TRIGGER_MISSING")
        count = 0
        for row in self.connection.execute("SELECT * FROM portfolio_correlation_records"):
            count += 1
            stored = json.loads(row["canonical_json"])
            validate_portfolio_correlation(stored)
            arithmetic = self._arithmetic(stored["arithmetic_record_id"])
            replay = build_portfolio_correlation(
                arithmetic_record=arithmetic, return_history_manifest=stored["return_history_manifest"],
                policy_hash=self.policy_hash, correlation_contract_hash=self.contract_hash)
            if replay != stored or row["canonical_json"] != canonical_json(stored):
                raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_REPLAY_MISMATCH")
            typed = tuple(row[k] for k in ("correlation_context_id", "arithmetic_record_id",
                                            "arithmetic_record_hash", "source_export_id", "source_export_hash",
                                            "manifest_hash", "record_hash"))
            manifest = stored["return_history_manifest"]
            wanted = (stored["correlation_context_id"], stored["arithmetic_record_id"],
                      stored["arithmetic_record_hash"], manifest["source_export_id"], manifest["source_export_hash"],
                      stored["return_history_manifest_hash"], stored["record_hash"])
            if typed != wanted:
                raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_TYPED_COLUMN_MISMATCH")
            series = self.connection.execute(
                "SELECT * FROM portfolio_correlation_series WHERE correlation_context_id=? ORDER BY ordinal",
                (stored["correlation_context_id"],)).fetchall()
            if [json.loads(r["canonical_json"]) for r in series] != manifest["series"]:
                raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_SERIES_MISMATCH")
            for row_series, expected_series in zip(series, manifest["series"]):
                if (row_series["company_entity_id"], row_series["status"], row_series["series_hash"]) != (
                        expected_series["company_entity_id"], expected_series["status"], canonical_hash(expected_series)):
                    raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_SERIES_TYPED_MISMATCH")
            expected_observations = [(s["company_entity_id"], i, canonical_json(o))
                                     for s in manifest["series"] for i, o in enumerate(s["observations"], 1)]
            observations = self.connection.execute(
                "SELECT * FROM portfolio_correlation_observations WHERE correlation_context_id=? ORDER BY company_entity_id,ordinal",
                (stored["correlation_context_id"],)).fetchall()
            if [(r["company_entity_id"], r["ordinal"], r["canonical_json"]) for r in observations] != expected_observations:
                raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_OBSERVATION_MISMATCH")
            for observation in observations:
                value = json.loads(observation["canonical_json"])
                if (observation["period_end_utc"], observation["source_record_id"], observation["source_record_hash"]) != (
                        value["period_end_utc"], value["source_record_id"], value["source_record_hash"]):
                    raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_OBSERVATION_TYPED_MISMATCH")
            pairs = self.connection.execute(
                "SELECT * FROM portfolio_correlation_pairs WHERE correlation_context_id=? ORDER BY ordinal",
                (stored["correlation_context_id"],)).fetchall()
            if [json.loads(r["canonical_json"]) for r in pairs] != stored["pairwise_correlations"]:
                raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_PAIR_MISMATCH")
            for row_pair, expected_pair in zip(pairs, stored["pairwise_correlations"]):
                members = expected_pair["correlation"]["members"]
                if (row_pair["left_member"], row_pair["right_member"], row_pair["status"],
                    row_pair["value_json"], row_pair["pair_hash"]) != (
                        members[0], members[1], expected_pair["calculation_status"],
                        canonical_json(expected_pair["correlation"]["value"]), canonical_hash(expected_pair)):
                    raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_PAIR_TYPED_MISMATCH")
            binding = self.connection.execute(
                "SELECT * FROM portfolio_correlation_source_bindings WHERE correlation_context_id=?",
                (stored["correlation_context_id"],)).fetchone()
            expected_binding = {k: manifest[k] for k in ("source_system", "source_export_id", "source_export_hash",
                                                           "source_dataset_id", "source_schema_version")}
            expected_binding["return_history_manifest_hash"] = stored["return_history_manifest_hash"]
            if binding is None or binding["canonical_json"] != canonical_json(expected_binding):
                raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_SOURCE_BINDING_MISMATCH")
            if tuple(binding[k] for k in ("source_system", "source_export_id", "source_export_hash",
                                          "source_dataset_id", "source_schema_version", "manifest_hash")) != (
                    manifest["source_system"], manifest["source_export_id"], manifest["source_export_hash"],
                    manifest["source_dataset_id"], manifest["source_schema_version"],
                    stored["return_history_manifest_hash"]):
                raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_SOURCE_BINDING_TYPED_MISMATCH")
            dependencies = [(r["record_type"], r["record_id"], r["record_hash"]) for r in self.connection.execute(
                "SELECT * FROM portfolio_correlation_dependencies WHERE correlation_context_id=? ORDER BY record_type,record_id",
                (stored["correlation_context_id"],))]
            if dependencies != sorted(self._dependencies(stored)):
                raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_DEPENDENCY_MISMATCH")
        return {"result": "PASS", "portfolio_correlation_records": count}
