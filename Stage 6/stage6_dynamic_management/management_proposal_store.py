import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_json
from .current_thesis_resolver import resolve_current, validate_source_request
from .errors import Stage6DynamicManagementError, DynamicManagementConflict, DynamicManagementIntegrityFailure
from .management_proposal_builder import build_proposal, logical_key
from .management_proposal_validation import validate_proposal, validate_request
from .policy import *

TABLES = (
    "dynamic_management_store_meta", "dynamic_management_policies", "dynamic_management_contracts",
    "dynamic_management_proposals", "dynamic_management_support_bindings",
    "dynamic_management_dependencies", "dynamic_management_audits",
)


class DynamicManagementStore:
    def __init__(self, database: Path, stage6e_store, recursive_store):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.stage6e_store = stage6e_store
        self.recursive_store = recursive_store
        self.policy, self.policy_json, self.policy_hash = load_policy()
        self.contract, self.contract_json, self.contract_hash = load_contract()
        new = not self.database.exists()
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        if new:
            self._initialize()
        self._singletons()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.connection.close()

    def _initialize(self):
        self.connection.executescript("""
CREATE TABLE dynamic_management_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema TEXT NOT NULL,development_baseline TEXT NOT NULL,processor TEXT NOT NULL,authority TEXT NOT NULL,thesis_blob TEXT NOT NULL);
CREATE TABLE dynamic_management_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE dynamic_management_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE dynamic_management_proposals(proposal_id TEXT PRIMARY KEY,logical_key TEXT UNIQUE NOT NULL,thesis_id TEXT NOT NULL,thesis_version INTEGER NOT NULL,current_source TEXT NOT NULL,current_version_record_id TEXT NOT NULL,current_thesis_hash TEXT NOT NULL,proposal_cutoff TEXT NOT NULL,proposal_mode TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE dynamic_management_support_bindings(proposal_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(proposal_id,record_type,record_id),FOREIGN KEY(proposal_id) REFERENCES dynamic_management_proposals);
CREATE TABLE dynamic_management_dependencies(proposal_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(proposal_id,record_type,record_id),FOREIGN KEY(proposal_id) REFERENCES dynamic_management_proposals);
CREATE TABLE dynamic_management_audits(proposal_id TEXT PRIMARY KEY,proposal_cutoff TEXT NOT NULL,proposal_mode TEXT NOT NULL,canonical_json TEXT NOT NULL,FOREIGN KEY(proposal_id) REFERENCES dynamic_management_proposals);
""")
        self.connection.execute("INSERT INTO dynamic_management_store_meta VALUES(1,?,?,?,?,?)", (STORE_SCHEMA, BASELINE, PROCESSOR, AUTHORITY, THESIS_BLOB))
        self.connection.execute("INSERT INTO dynamic_management_policies VALUES(?,?,?)", (POLICY_ID, self.policy_hash, self.policy_json))
        self.connection.execute("INSERT INTO dynamic_management_contracts VALUES(?,?,?)", (CONTRACT_VERSION, self.contract_hash, self.contract_json))
        for table in TABLES:
            self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
        self.connection.commit()

    def _singletons(self):
        meta = self.connection.execute("SELECT * FROM dynamic_management_store_meta").fetchall()
        if len(meta) != 1 or tuple(meta[0]) != (1, STORE_SCHEMA, BASELINE, PROCESSOR, AUTHORITY, THESIS_BLOB):
            raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_METADATA_MISMATCH")
        policies = self.connection.execute("SELECT * FROM dynamic_management_policies").fetchall()
        if len(policies) != 1 or tuple(policies[0]) != (POLICY_ID, self.policy_hash, self.policy_json):
            raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_POLICY_MISMATCH")
        contracts = self.connection.execute("SELECT * FROM dynamic_management_contracts").fetchall()
        if len(contracts) != 1 or tuple(contracts[0]) != (CONTRACT_VERSION, self.contract_hash, self.contract_json):
            raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_CONTRACT_MISMATCH")

    def _policy_dependencies(self):
        return [("STAGE6_6G_POLICY", POLICY_ID, self.policy_hash), ("STAGE6_6G_PROPOSAL_CONTRACT", CONTRACT_VERSION, self.contract_hash)]

    def _dependencies(self, record):
        values = [record["current_thesis_binding"], record["bound_review_snapshot_binding"], record["bound_review_assessment_binding"]]
        return [*(tuple(item[key] for key in ("record_type", "record_id", "record_hash")) for item in values), *self._policy_dependencies()]

    def propose(self, *, current_thesis_source, current_version_record_id, proposal_cutoff, proposal_mode, proposed_stop, proposed_target, reason_code, supporting_bindings):
        self._singletons()
        validate_source_request(current_thesis_source, current_version_record_id)
        _, thesis, snapshot, assessment = resolve_current(current_thesis_source, current_version_record_id, self.stage6e_store, self.recursive_store)
        validate_request(thesis=thesis, snapshot=snapshot, assessment=assessment, proposal_cutoff=proposal_cutoff, proposal_mode=proposal_mode, proposed_stop=proposed_stop, proposed_target=proposed_target, reason_code=reason_code, supporting_bindings=supporting_bindings)
        record = build_proposal(source=current_thesis_source, source_record_id=current_version_record_id, thesis=thesis, snapshot=snapshot, assessment=assessment, proposal_cutoff=proposal_cutoff, proposal_mode=proposal_mode, proposed_stop=proposed_stop, proposed_target=proposed_target, reason_code=reason_code, supporting_bindings=supporting_bindings, policy_hash=self.policy_hash, contract_hash=self.contract_hash)
        validate_proposal(record, current_thesis_source, current_version_record_id, thesis, snapshot, assessment, self.policy_hash, self.contract_hash)
        logical = logical_key(thesis, proposal_mode, proposed_stop, proposed_target, reason_code)
        existing = self.connection.execute("SELECT canonical_json FROM dynamic_management_proposals WHERE logical_key=?", (logical,)).fetchone()
        if existing:
            if existing[0] == canonical_json(record):
                return {"status": "IDEMPOTENT_SUCCESS", "proposal": record}
            raise DynamicManagementConflict("DYNAMIC_MANAGEMENT_LOGICAL_CONFLICT")
        audit = {"proposal_id": record["proposal_id"], "proposal_cutoff": proposal_cutoff, "proposal_mode": proposal_mode, "factual_change_metadata": record["factual_change_metadata"], "execution_status": "NOT_AUTHORIZED"}
        with self.connection:
            self.connection.execute("INSERT INTO dynamic_management_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?)", (record["proposal_id"], logical, record["thesis_id"], record["thesis_version"], current_thesis_source, current_version_record_id, record["current_thesis_binding"]["record_hash"], proposal_cutoff, proposal_mode, record["record_hash"], canonical_json(record)))
            self.connection.executemany("INSERT INTO dynamic_management_support_bindings VALUES(?,?,?,?)", [(record["proposal_id"], item["record_type"], item["record_id"], item["record_hash"]) for item in record["supporting_bindings"]])
            self.connection.executemany("INSERT INTO dynamic_management_dependencies VALUES(?,?,?,?)", [(record["proposal_id"], *item) for item in self._dependencies(record)])
            self.connection.execute("INSERT INTO dynamic_management_audits VALUES(?,?,?,?)", (record["proposal_id"], proposal_cutoff, proposal_mode, canonical_json(audit)))
        return {"status": "CREATED", "proposal": record}

    def _children(self, record):
        identity = record["proposal_id"]
        support = sorted(tuple(row) for row in self.connection.execute("SELECT record_type,record_id,record_hash FROM dynamic_management_support_bindings WHERE proposal_id=?", (identity,)))
        expected_support = sorted(tuple(item[key] for key in ("record_type", "record_id", "record_hash")) for item in record["supporting_bindings"])
        dependencies = sorted(tuple(row) for row in self.connection.execute("SELECT record_type,record_id,record_hash FROM dynamic_management_dependencies WHERE proposal_id=?", (identity,)))
        audit_row = self.connection.execute("SELECT canonical_json FROM dynamic_management_audits WHERE proposal_id=?", (identity,)).fetchone()
        audit = {"proposal_id": identity, "proposal_cutoff": record["proposal_cutoff"], "proposal_mode": record["proposal_mode"], "factual_change_metadata": record["factual_change_metadata"], "execution_status": "NOT_AUTHORIZED"}
        if support != expected_support or dependencies != sorted(self._dependencies(record)) or audit_row is None or audit_row[0] != canonical_json(audit):
            raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_CHILD_MISMATCH")

    def integrity_check(self):
        self._singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_SQLITE_INTEGRITY_FAILED")
        for table in TABLES:
            triggers = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
            if triggers != {f"protect_{table}_update", f"protect_{table}_delete"}:
                raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_TRIGGER_MISSING")
        count = 0
        for row in self.connection.execute("SELECT * FROM dynamic_management_proposals"):
            count += 1; record = json.loads(row["canonical_json"])
            _, thesis, snapshot, assessment = resolve_current(row["current_source"], row["current_version_record_id"], self.stage6e_store, self.recursive_store)
            validate_proposal(record, row["current_source"], row["current_version_record_id"], thesis, snapshot, assessment, self.policy_hash, self.contract_hash)
            expected_typed = (record["proposal_id"], logical_key(thesis, record["proposal_mode"], record["proposed_stop"], record["proposed_target"], record["reason_code"]), record["thesis_id"], record["thesis_version"], record["current_thesis_source"], record["current_version_record_id"], record["current_thesis_binding"]["record_hash"], record["proposal_cutoff"], record["proposal_mode"], record["record_hash"])
            actual_typed = tuple(row[key] for key in ("proposal_id", "logical_key", "thesis_id", "thesis_version", "current_source", "current_version_record_id", "current_thesis_hash", "proposal_cutoff", "proposal_mode", "record_hash"))
            if actual_typed != expected_typed or row["canonical_json"] != canonical_json(record):
                raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_TYPED_MISMATCH")
            self._children(record)
        return {"result": "PASS", "proposals": count, "authority": AUTHORITY, "trading_authority": False}

    def update_record(self, *_, **__):
        raise Stage6DynamicManagementError("IMMUTABLE_RECORD_UPDATE_PROHIBITED")
