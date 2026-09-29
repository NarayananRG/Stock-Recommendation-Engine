import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_json
from .errors import Stage6TradeThesisVersionError, TradeThesisVersionConflict, TradeThesisVersionIntegrityFailure
from .policy import *
from .trade_thesis_version_builder import build_version_record, direct_inputs
from .trade_thesis_version_validation import eligibility, validate_chain, validate_version_record

TABLES = (
    "trade_thesis_version_store_meta",
    "trade_thesis_version_policies",
    "trade_thesis_version_contracts",
    "trade_thesis_version_records",
    "trade_thesis_version_dependencies",
    "trade_thesis_version_audits",
)


class TradeThesisVersionStore:
    def __init__(self, database: Path, assessment_store, review_store, thesis_store):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.assessment_store = assessment_store
        self.review_store = review_store
        self.thesis_store = thesis_store
        self.policy, self.policy_json, self.policy_hash = load_policy()
        self.contract, self.contract_json, self.contract_hash = load_contract()
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
CREATE TABLE trade_thesis_version_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,development_baseline TEXT NOT NULL,runtime_semantic_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL,trade_thesis_blob TEXT NOT NULL);
CREATE TABLE trade_thesis_version_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE trade_thesis_version_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE trade_thesis_version_records(version_record_id TEXT PRIMARY KEY,thesis_id TEXT NOT NULL,version INTEGER NOT NULL,assessment_id TEXT UNIQUE NOT NULL,thesis_hash TEXT UNIQUE NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL,UNIQUE(thesis_id,version));
CREATE TABLE trade_thesis_version_dependencies(version_record_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(version_record_id,record_type,record_id),FOREIGN KEY(version_record_id) REFERENCES trade_thesis_version_records);
CREATE TABLE trade_thesis_version_audits(version_record_id TEXT PRIMARY KEY,version INTEGER NOT NULL,change_type TEXT NOT NULL,decision_cutoff TEXT NOT NULL,canonical_json TEXT NOT NULL,FOREIGN KEY(version_record_id) REFERENCES trade_thesis_version_records);
""")
        self.connection.execute(
            "INSERT INTO trade_thesis_version_store_meta VALUES(1,?,?,?,?,?,?)",
            (STORE_SCHEMA_VERSION, DEVELOPMENT_BASELINE, RUNTIME_SEMANTIC_COMMIT, PROCESSOR_VERSION, AUTHORITY, TRADE_THESIS_BLOB),
        )
        self.connection.execute("INSERT INTO trade_thesis_version_policies VALUES(?,?,?)", (POLICY_ID, self.policy_hash, self.policy_json))
        self.connection.execute("INSERT INTO trade_thesis_version_contracts VALUES(?,?,?)", (CONTRACT_VERSION, self.contract_hash, self.contract_json))
        for table in TABLES:
            self.connection.executescript(
                f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;"
                f"CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;"
            )
        self.connection.commit()

    def _verify_singletons(self):
        meta = self.connection.execute("SELECT * FROM trade_thesis_version_store_meta").fetchall()
        expected = (1, STORE_SCHEMA_VERSION, DEVELOPMENT_BASELINE, RUNTIME_SEMANTIC_COMMIT, PROCESSOR_VERSION, AUTHORITY, TRADE_THESIS_BLOB)
        if len(meta) != 1 or tuple(meta[0]) != expected:
            raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_METADATA_MISMATCH")
        policies = self.connection.execute("SELECT * FROM trade_thesis_version_policies").fetchall()
        if len(policies) != 1 or tuple(policies[0]) != (POLICY_ID, self.policy_hash, self.policy_json):
            raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_POLICY_MISMATCH")
        contracts = self.connection.execute("SELECT * FROM trade_thesis_version_contracts").fetchall()
        if len(contracts) != 1 or tuple(contracts[0]) != (CONTRACT_VERSION, self.contract_hash, self.contract_json):
            raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_CONTRACT_MISMATCH")

    def _integrity(self, store, code):
        if store is None:
            raise TradeThesisVersionIntegrityFailure(code)
        try:
            result = store.integrity_check()
        except Exception as exc:
            raise TradeThesisVersionIntegrityFailure(code) from exc
        if result.get("result") != "PASS":
            raise TradeThesisVersionIntegrityFailure(code)

    def _load_json(self, store, table, column, identity, code):
        self._integrity(store, code + "_INTEGRITY_REQUIRED")
        row = store.connection.execute(f"SELECT canonical_json FROM {table} WHERE {column}=?", (identity,)).fetchone()
        if row is None:
            raise Stage6TradeThesisVersionError(code + "_NOT_FOUND")
        return json.loads(row[0])

    def _chain(self, assessment_id):
        assessment = self._load_json(
            self.assessment_store, "thesis_review_assessment_records", "assessment_id", assessment_id, "REVIEW_ASSESSMENT"
        )
        snapshot_id = assessment["review_snapshot_binding"]["record_id"]
        snapshot = self._load_json(
            self.review_store, "thesis_review_input_records", "review_snapshot_id", snapshot_id, "REVIEW_SNAPSHOT"
        )
        thesis_id = assessment["previous_thesis_binding"]["record_id"]
        wrapper = self._load_json(self.thesis_store, "trade_thesis_records", "thesis_id", thesis_id, "PREVIOUS_THESIS")
        previous = wrapper["trade_thesis"]
        validate_chain(previous, snapshot, assessment)
        return previous, snapshot, assessment

    def materialize(self, assessment_id):
        self._verify_singletons()
        previous, snapshot, assessment = self._chain(assessment_id)
        if eligibility(assessment) != "READY_FOR_MATERIALIZATION":
            return {"status": "WITHHELD_INDETERMINATE", "version_record": None, "trade_thesis": None}
        record = build_version_record(previous, snapshot, assessment, self.policy_hash, self.contract_hash)
        validate_version_record(record, previous, snapshot, assessment, self.policy_hash, self.contract_hash)
        text = canonical_json(record)
        old_assessment = self.connection.execute(
            "SELECT canonical_json FROM trade_thesis_version_records WHERE assessment_id=?", (assessment_id,)
        ).fetchone()
        if old_assessment:
            if old_assessment[0] == text:
                return {"status": "IDEMPOTENT_SUCCESS", "version_record": record, "trade_thesis": record["trade_thesis"]}
            raise TradeThesisVersionConflict("TRADE_THESIS_VERSION_ASSESSMENT_CONFLICT")
        old_version = self.connection.execute(
            "SELECT canonical_json FROM trade_thesis_version_records WHERE thesis_id=? AND version=2", (previous["thesis_id"],)
        ).fetchone()
        if old_version:
            raise TradeThesisVersionConflict("TRADE_THESIS_VERSION_CONFLICT")
        inputs = direct_inputs(previous, snapshot, assessment)
        dependencies = [
            *(tuple(item[key] for key in ("record_type", "record_id", "record_hash")) for item in inputs),
            ("STAGE6_6E_POLICY", POLICY_ID, self.policy_hash),
            ("STAGE6_6E_MATERIALIZATION_CONTRACT", CONTRACT_VERSION, self.contract_hash),
        ]
        audit = record["trade_thesis"]["change_history"][-1]
        with self.connection:
            self.connection.execute(
                "INSERT INTO trade_thesis_version_records VALUES(?,?,?,?,?,?,?)",
                (
                    record["version_record_id"], record["thesis_id"], 2, assessment_id,
                    record["trade_thesis"]["record_hash"], record["record_hash"], text,
                ),
            )
            self.connection.executemany(
                "INSERT INTO trade_thesis_version_dependencies VALUES(?,?,?,?)",
                [(record["version_record_id"], *item) for item in dependencies],
            )
            self.connection.execute(
                "INSERT INTO trade_thesis_version_audits VALUES(?,?,?,?,?)",
                (record["version_record_id"], 2, audit["change_type"], audit["decision_cutoff"], canonical_json(audit)),
            )
        return {"status": "CREATED", "version_record": record, "trade_thesis": record["trade_thesis"]}

    def integrity_check(self):
        self._verify_singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_SQLITE_INTEGRITY_FAILED")
        if self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_FOREIGN_KEY_FAILED")
        for table in TABLES:
            triggers = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
            if triggers != {f"protect_{table}_update", f"protect_{table}_delete"}:
                raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_TRIGGER_MISSING")
        count = 0
        for row in self.connection.execute("SELECT * FROM trade_thesis_version_records"):
            count += 1
            record = json.loads(row["canonical_json"])
            previous, snapshot, assessment = self._chain(row["assessment_id"])
            validate_version_record(record, previous, snapshot, assessment, self.policy_hash, self.contract_hash)
            rebuilt = build_version_record(previous, snapshot, assessment, self.policy_hash, self.contract_hash)
            if rebuilt != record or row["canonical_json"] != canonical_json(record):
                raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_REPLAY_MISMATCH")
            typed = (row["version_record_id"], row["thesis_id"], row["version"], row["assessment_id"], row["thesis_hash"], row["record_hash"])
            expected_typed = (
                record["version_record_id"], record["thesis_id"], 2, assessment["assessment_id"],
                record["trade_thesis"]["record_hash"], record["record_hash"],
            )
            if typed != expected_typed:
                raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_TYPED_MISMATCH")
            inputs = direct_inputs(previous, snapshot, assessment)
            expected_dependencies = sorted([
                *(tuple(item[key] for key in ("record_type", "record_id", "record_hash")) for item in inputs),
                ("STAGE6_6E_POLICY", POLICY_ID, self.policy_hash),
                ("STAGE6_6E_MATERIALIZATION_CONTRACT", CONTRACT_VERSION, self.contract_hash),
            ])
            actual_dependencies = sorted(tuple(item) for item in self.connection.execute(
                "SELECT record_type,record_id,record_hash FROM trade_thesis_version_dependencies WHERE version_record_id=?",
                (record["version_record_id"],),
            ))
            if actual_dependencies != expected_dependencies:
                raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_DEPENDENCY_MISMATCH")
            audit = self.connection.execute(
                "SELECT canonical_json FROM trade_thesis_version_audits WHERE version_record_id=?", (record["version_record_id"],)
            ).fetchone()
            if audit is None or json.loads(audit[0]) != record["trade_thesis"]["change_history"][-1]:
                raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_AUDIT_MISMATCH")
        return {"result": "PASS", "trade_thesis_versions": count, "authority": AUTHORITY}

    def update_record(self, *_, **__):
        raise Stage6TradeThesisVersionError("IMMUTABLE_RECORD_UPDATE_PROHIBITED")
