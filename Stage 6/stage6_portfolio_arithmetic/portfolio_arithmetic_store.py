from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_json
from .errors import PortfolioArithmeticConflict, PortfolioArithmeticIntegrityFailure, Stage6PortfolioArithmeticError
from .policy import *
from .portfolio_arithmetic_builder import build_portfolio_arithmetic
from .portfolio_arithmetic_validation import validate_portfolio_arithmetic

TABLES = (
    "portfolio_arithmetic_store_meta", "portfolio_arithmetic_policies",
    "portfolio_arithmetic_contracts", "portfolio_arithmetic_records",
    "portfolio_arithmetic_positions", "portfolio_arithmetic_exposures",
    "portfolio_arithmetic_pending_commitments", "portfolio_arithmetic_dependencies",
)


class PortfolioArithmeticStore:
    def __init__(self, database: Path, source_store):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.source_store = source_store
        self.policy, self.policy_json, self.policy_hash = load_policy()
        self.contract, self.contract_json, self.contract_hash = load_arithmetic_contract()
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
CREATE TABLE portfolio_arithmetic_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,payload_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL,portfolio_context_blob TEXT NOT NULL);
CREATE TABLE portfolio_arithmetic_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_arithmetic_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_arithmetic_records(arithmetic_record_id TEXT PRIMARY KEY,source_snapshot_id TEXT UNIQUE NOT NULL,source_snapshot_hash TEXT NOT NULL,currency TEXT NOT NULL,invested_capital_json TEXT NOT NULL,committed_capital_json TEXT NOT NULL,available_capital_json TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_arithmetic_positions(arithmetic_record_id TEXT NOT NULL,ordinal INTEGER NOT NULL,logical_key TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(arithmetic_record_id,ordinal),UNIQUE(arithmetic_record_id,logical_key),FOREIGN KEY(arithmetic_record_id) REFERENCES portfolio_arithmetic_records);
CREATE TABLE portfolio_arithmetic_exposures(arithmetic_record_id TEXT NOT NULL,exposure_type TEXT NOT NULL,ordinal INTEGER NOT NULL,identity_key TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(arithmetic_record_id,exposure_type,ordinal),UNIQUE(arithmetic_record_id,exposure_type,identity_key),FOREIGN KEY(arithmetic_record_id) REFERENCES portfolio_arithmetic_records);
CREATE TABLE portfolio_arithmetic_pending_commitments(arithmetic_record_id TEXT NOT NULL,aggregation_type TEXT NOT NULL,ordinal INTEGER NOT NULL,identity_key TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(arithmetic_record_id,aggregation_type,ordinal),UNIQUE(arithmetic_record_id,aggregation_type,identity_key),FOREIGN KEY(arithmetic_record_id) REFERENCES portfolio_arithmetic_records);
CREATE TABLE portfolio_arithmetic_dependencies(arithmetic_record_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(arithmetic_record_id,record_type,record_id),FOREIGN KEY(arithmetic_record_id) REFERENCES portfolio_arithmetic_records);
""")
        self.connection.execute("INSERT INTO portfolio_arithmetic_store_meta VALUES(1,?,?,?,?,?,?)", (
            STORE_SCHEMA_VERSION, SCHEMA_VERSION, BASELINE_COMMIT, PROCESSOR_VERSION, AUTHORITY,
            PORTFOLIO_CONTEXT_BLOB))
        self.connection.execute("INSERT INTO portfolio_arithmetic_policies VALUES(?,?,?)", (
            POLICY_ID, self.policy_hash, self.policy_json))
        self.connection.execute("INSERT INTO portfolio_arithmetic_contracts VALUES(?,?,?)", (
            ARITHMETIC_CONTRACT_VERSION, self.contract_hash, self.contract_json))
        for table in TABLES:
            self.connection.executescript(
                f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;"
                f"CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
        self.connection.commit()

    def _verify_singletons(self):
        meta = self.connection.execute("SELECT * FROM portfolio_arithmetic_store_meta").fetchall()
        expected = (1, STORE_SCHEMA_VERSION, SCHEMA_VERSION, BASELINE_COMMIT, PROCESSOR_VERSION,
                    AUTHORITY, PORTFOLIO_CONTEXT_BLOB)
        if len(meta) != 1 or tuple(meta[0]) != expected:
            raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_METADATA_MISMATCH")
        policies = self.connection.execute("SELECT * FROM portfolio_arithmetic_policies").fetchall()
        if len(policies) != 1 or tuple(policies[0]) != (POLICY_ID, self.policy_hash, self.policy_json):
            raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_POLICY_MISMATCH")
        contracts = self.connection.execute("SELECT * FROM portfolio_arithmetic_contracts").fetchall()
        if len(contracts) != 1 or tuple(contracts[0]) != (
                ARITHMETIC_CONTRACT_VERSION, self.contract_hash, self.contract_json):
            raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_CONTRACT_MISMATCH")

    def _source(self, source_snapshot_id: str) -> dict:
        try:
            result = self.source_store.integrity_check()
        except Exception as exc:
            raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_SOURCE_INTEGRITY_REQUIRED") from exc
        if result.get("result") != "PASS":
            raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_SOURCE_INTEGRITY_REQUIRED")
        row = self.source_store.connection.execute(
            "SELECT canonical_json FROM portfolio_source_snapshots WHERE source_snapshot_id=?",
            (source_snapshot_id,)).fetchone()
        if row is None:
            raise Stage6PortfolioArithmeticError("PORTFOLIO_ARITHMETIC_SOURCE_NOT_FOUND")
        return json.loads(row[0])

    @staticmethod
    def _position_key(item: dict) -> str:
        return "|".join((item["company_entity_id"], item["ticker"], item["recommendation_id"]))

    def _dependencies(self, record: dict) -> list[tuple[str, str, str]]:
        return [
            ("STAGE6_5A_PORTFOLIO_SOURCE", record["source_snapshot_id"], record["source_snapshot_hash"]),
            ("STAGE6_5B_POLICY", POLICY_ID, self.policy_hash),
            ("STAGE6_5B_ARITHMETIC_CONTRACT", ARITHMETIC_CONTRACT_VERSION, self.contract_hash),
        ]

    def aggregate(self, *, source_snapshot_id: str) -> dict:
        self._verify_singletons()
        source = self._source(source_snapshot_id)
        record = build_portfolio_arithmetic(
            source_snapshot=source, policy_hash=self.policy_hash,
            arithmetic_contract_hash=self.contract_hash)
        validate_portfolio_arithmetic(record)
        text = canonical_json(record)
        old = self.connection.execute(
            "SELECT canonical_json FROM portfolio_arithmetic_records WHERE source_snapshot_id=?",
            (source_snapshot_id,)).fetchone()
        if old:
            if old[0] == text:
                return {"status": "IDEMPOTENT_SUCCESS", "portfolio_arithmetic": record}
            raise PortfolioArithmeticConflict("PORTFOLIO_ARITHMETIC_CONFLICT")
        with self.connection:
            self.connection.execute("INSERT INTO portfolio_arithmetic_records VALUES(?,?,?,?,?,?,?,?,?)", (
                record["arithmetic_record_id"], source_snapshot_id, record["source_snapshot_hash"],
                record["currency"], canonical_json(record["invested_capital"]),
                canonical_json(record["committed_capital"]), canonical_json(record["available_capital"]),
                record["record_hash"], text))
            for ordinal, item in enumerate(record["derived_open_positions"], 1):
                self.connection.execute("INSERT INTO portfolio_arithmetic_positions VALUES(?,?,?,?)", (
                    record["arithmetic_record_id"], ordinal, self._position_key(item), canonical_json(item)))
            for exposure_type, field, identity_field in (
                ("COMPANY", "held_company_concentration", "company_entity_id"),
                ("SECTOR", "held_sector_exposure", "sector_entity_id"),
                ("SUBSECTOR", "held_subsector_exposure", "subsector_entity_id")):
                for ordinal, item in enumerate(record[field], 1):
                    self.connection.execute("INSERT INTO portfolio_arithmetic_exposures VALUES(?,?,?,?,?)", (
                        record["arithmetic_record_id"], exposure_type, ordinal, item[identity_field],
                        canonical_json(item)))
            for aggregation_type, field, identity_field in (
                ("COMPANY", "pending_commitment_by_company", "company_entity_id"),
                ("SECTOR", "pending_commitment_by_sector", "sector_entity_id"),
                ("SUBSECTOR", "pending_commitment_by_subsector", "subsector_entity_id")):
                for ordinal, item in enumerate(record[field], 1):
                    self.connection.execute("INSERT INTO portfolio_arithmetic_pending_commitments VALUES(?,?,?,?,?)", (
                        record["arithmetic_record_id"], aggregation_type, ordinal, item[identity_field],
                        canonical_json(item)))
            self.connection.executemany("INSERT INTO portfolio_arithmetic_dependencies VALUES(?,?,?,?)", [
                (record["arithmetic_record_id"], *dependency) for dependency in self._dependencies(record)])
        return {"status": "CREATED", "portfolio_arithmetic": record}

    def integrity_check(self) -> dict:
        self._verify_singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_SQLITE_INTEGRITY_FAILED")
        if self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_FOREIGN_KEY_FAILED")
        for table in TABLES:
            actual = {row[0] for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
            if actual != {f"protect_{table}_update", f"protect_{table}_delete"}:
                raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_TRIGGER_MISSING")
        count = 0
        for row in self.connection.execute("SELECT * FROM portfolio_arithmetic_records"):
            count += 1
            stored = json.loads(row["canonical_json"])
            validate_portfolio_arithmetic(stored)
            source = self._source(stored["source_snapshot_id"])
            replay = build_portfolio_arithmetic(
                source_snapshot=source, policy_hash=self.policy_hash,
                arithmetic_contract_hash=self.contract_hash)
            if replay != stored or row["canonical_json"] != canonical_json(stored):
                raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_REPLAY_MISMATCH")
            typed = tuple(row[key] for key in (
                "arithmetic_record_id", "source_snapshot_id", "source_snapshot_hash", "currency",
                "invested_capital_json", "committed_capital_json", "available_capital_json", "record_hash"))
            wanted = (stored["arithmetic_record_id"], stored["source_snapshot_id"],
                      stored["source_snapshot_hash"], stored["currency"],
                      canonical_json(stored["invested_capital"]), canonical_json(stored["committed_capital"]),
                      canonical_json(stored["available_capital"]), stored["record_hash"])
            if typed != wanted:
                raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_TYPED_COLUMN_MISMATCH")
            positions = self.connection.execute(
                "SELECT * FROM portfolio_arithmetic_positions WHERE arithmetic_record_id=? ORDER BY ordinal",
                (stored["arithmetic_record_id"],)).fetchall()
            if [json.loads(x["canonical_json"]) for x in positions] != stored["derived_open_positions"]:
                raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_POSITION_COVERAGE_MISMATCH")
            if [x["logical_key"] for x in positions] != [self._position_key(x) for x in stored["derived_open_positions"]]:
                raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_POSITION_KEY_MISMATCH")
            exposure_rows = self.connection.execute(
                "SELECT * FROM portfolio_arithmetic_exposures WHERE arithmetic_record_id=? ORDER BY exposure_type,ordinal",
                (stored["arithmetic_record_id"],)).fetchall()
            wanted_exposures = []
            for exposure_type, field, identity_field in (
                ("COMPANY", "held_company_concentration", "company_entity_id"),
                ("SECTOR", "held_sector_exposure", "sector_entity_id"),
                ("SUBSECTOR", "held_subsector_exposure", "subsector_entity_id")):
                wanted_exposures.extend((exposure_type, i, x[identity_field], canonical_json(x))
                                        for i, x in enumerate(stored[field], 1))
            actual_exposures = [(x["exposure_type"], x["ordinal"], x["identity_key"], x["canonical_json"])
                                for x in exposure_rows]
            if actual_exposures != sorted(wanted_exposures):
                raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_EXPOSURE_COVERAGE_MISMATCH")
            pending_rows = self.connection.execute(
                "SELECT * FROM portfolio_arithmetic_pending_commitments WHERE arithmetic_record_id=? ORDER BY aggregation_type,ordinal",
                (stored["arithmetic_record_id"],)).fetchall()
            wanted_pending = []
            for aggregation_type, field, identity_field in (
                ("COMPANY", "pending_commitment_by_company", "company_entity_id"),
                ("SECTOR", "pending_commitment_by_sector", "sector_entity_id"),
                ("SUBSECTOR", "pending_commitment_by_subsector", "subsector_entity_id")):
                wanted_pending.extend((aggregation_type, i, x[identity_field], canonical_json(x))
                                      for i, x in enumerate(stored[field], 1))
            actual_pending = [(x["aggregation_type"], x["ordinal"], x["identity_key"], x["canonical_json"])
                              for x in pending_rows]
            if actual_pending != sorted(wanted_pending):
                raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_PENDING_COVERAGE_MISMATCH")
            actual_dependencies = [(x["record_type"], x["record_id"], x["record_hash"])
                                   for x in self.connection.execute(
                                       "SELECT * FROM portfolio_arithmetic_dependencies WHERE arithmetic_record_id=? ORDER BY record_type,record_id",
                                       (stored["arithmetic_record_id"],))]
            if actual_dependencies != sorted(self._dependencies(stored)):
                raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_DEPENDENCY_MISMATCH")
        return {"result": "PASS", "portfolio_arithmetic_records": count}
