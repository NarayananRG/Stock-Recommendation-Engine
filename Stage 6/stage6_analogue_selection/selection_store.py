import json
import sqlite3
from pathlib import Path

from stage6_analogue_features.feature_validation import validate_feature_snapshot
from stage6_ingestion.canonical import canonical_json

from .errors import AnalogueSelectionConflict, AnalogueSelectionIntegrityFailure, Stage6AnalogueSelectionError
from .policy import (
    AUTHORITY,
    BASELINE_COMMIT,
    COMPARISON_CONTRACT_VERSION,
    EXPECTED_COMPARISON_CONTRACT_HASH_V1,
    EXPECTED_POLICY_HASH_V1,
    FEATURE_CONTRACT_HASH,
    FEATURE_CONTRACT_VERSION,
    FEATURE_POLICY_HASH,
    FEATURE_POLICY_ID,
    FEATURE_PROCESSOR,
    FEATURE_SCHEMA,
    POLICY_ID,
    PROCESSOR_VERSION,
    SCHEMA_VERSION,
    STORE_SCHEMA_VERSION,
    load_comparison_contract,
    load_policy,
)
from .selection_builder import build_selection
from .selection_validation import validate_selection_record

TABLES = (
    "analogue_selection_store_meta",
    "analogue_selection_policies",
    "analogue_comparison_contracts",
    "analogue_selection_records",
    "analogue_selection_universe",
    "analogue_candidate_evaluations",
    "analogue_selected_records",
    "analogue_selection_dependencies",
)


class AnalogueSelectionStore:
    def __init__(self, database: Path, feature_store):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.feature_store = feature_store
        self.policy, self.policy_json, self.policy_hash = load_policy()
        self.comparison_contract, self.comparison_contract_json, self.comparison_contract_hash = load_comparison_contract()
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
        self.connection.executescript(
            """
            CREATE TABLE analogue_selection_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,selection_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL);
            CREATE TABLE analogue_selection_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
            CREATE TABLE analogue_comparison_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
            CREATE TABLE analogue_selection_records(selection_record_id TEXT PRIMARY KEY,selection_spec_hash TEXT UNIQUE NOT NULL,target_feature_snapshot_id TEXT NOT NULL,target_feature_snapshot_hash TEXT NOT NULL,candidate_universe_hash TEXT NOT NULL,analogue_count INTEGER NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
            CREATE TABLE analogue_selection_universe(selection_record_id TEXT NOT NULL,candidate_feature_snapshot_id TEXT NOT NULL,candidate_feature_snapshot_hash TEXT NOT NULL,candidate_record_hash TEXT NOT NULL,ordinal INTEGER NOT NULL,PRIMARY KEY(selection_record_id,candidate_feature_snapshot_id),FOREIGN KEY(selection_record_id) REFERENCES analogue_selection_records(selection_record_id));
            CREATE TABLE analogue_candidate_evaluations(selection_record_id TEXT NOT NULL,candidate_feature_snapshot_id TEXT NOT NULL,selected INTEGER NOT NULL,distance REAL,canonical_json TEXT NOT NULL,PRIMARY KEY(selection_record_id,candidate_feature_snapshot_id),FOREIGN KEY(selection_record_id) REFERENCES analogue_selection_records(selection_record_id));
            CREATE TABLE analogue_selected_records(selection_record_id TEXT NOT NULL,analogue_id TEXT NOT NULL,rank_ordinal INTEGER NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(selection_record_id,analogue_id),FOREIGN KEY(selection_record_id) REFERENCES analogue_selection_records(selection_record_id));
            CREATE TABLE analogue_selection_dependencies(selection_record_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(selection_record_id,record_type,record_id),FOREIGN KEY(selection_record_id) REFERENCES analogue_selection_records(selection_record_id));
            """
        )
        self.connection.execute("INSERT INTO analogue_selection_store_meta VALUES(1,?,?,?,?,?)", (STORE_SCHEMA_VERSION, SCHEMA_VERSION, BASELINE_COMMIT, PROCESSOR_VERSION, AUTHORITY))
        self.connection.execute("INSERT INTO analogue_selection_policies VALUES(?,?,?)", (POLICY_ID, self.policy_hash, self.policy_json))
        self.connection.execute("INSERT INTO analogue_comparison_contracts VALUES(?,?,?)", (COMPARISON_CONTRACT_VERSION, self.comparison_contract_hash, self.comparison_contract_json))
        for table in TABLES:
            self.connection.executescript(
                f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;"
                f"CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;"
            )
        self.connection.commit()

    def _verify_singletons(self):
        meta = self.connection.execute("SELECT * FROM analogue_selection_store_meta").fetchall()
        expected_meta = (1, STORE_SCHEMA_VERSION, SCHEMA_VERSION, BASELINE_COMMIT, PROCESSOR_VERSION, AUTHORITY)
        if len(meta) != 1 or tuple(meta[0]) != expected_meta:
            raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_METADATA_MISMATCH")
        policies = self.connection.execute("SELECT * FROM analogue_selection_policies").fetchall()
        if len(policies) != 1 or tuple(policies[0]) != (POLICY_ID, EXPECTED_POLICY_HASH_V1, self.policy_json):
            raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_POLICY_MISMATCH")
        contracts = self.connection.execute("SELECT * FROM analogue_comparison_contracts").fetchall()
        expected_contract = (COMPARISON_CONTRACT_VERSION, EXPECTED_COMPARISON_CONTRACT_HASH_V1, self.comparison_contract_json)
        if len(contracts) != 1 or tuple(contracts[0]) != expected_contract:
            raise AnalogueSelectionIntegrityFailure("ANALOGUE_COMPARISON_CONTRACT_MISMATCH")

    def _feature(self, feature_snapshot_id):
        if self.feature_store.integrity_check()["result"] != "PASS":
            raise AnalogueSelectionIntegrityFailure("ANALOGUE_FEATURE_STORE_INTEGRITY_REQUIRED")
        row = self.feature_store.connection.execute(
            "SELECT canonical_json FROM analogue_feature_snapshots WHERE feature_snapshot_id=?", (feature_snapshot_id,)
        ).fetchone()
        if row is None:
            raise Stage6AnalogueSelectionError("ANALOGUE_FEATURE_SNAPSHOT_NOT_FOUND")
        record = json.loads(row[0])
        validate_feature_snapshot(record)
        expected = (FEATURE_SCHEMA, FEATURE_PROCESSOR, FEATURE_POLICY_ID, FEATURE_POLICY_HASH, FEATURE_CONTRACT_VERSION, FEATURE_CONTRACT_HASH, AUTHORITY, True, "PASS")
        actual = tuple(record.get(key) for key in ("schema_version", "processor_version", "policy_id", "policy_hash", "feature_contract_version", "feature_contract_hash", "authority", "pit_verified", "leakage_status"))
        if actual != expected:
            raise AnalogueSelectionIntegrityFailure("ANALOGUE_FEATURE_IDENTITY_INVALID")
        return record

    def _dependencies(self, record):
        dependencies = [("STAGE6_4B_ANALOGUE_FEATURE_TARGET", record["target_feature_snapshot_id"], record["target_record_hash"])]
        dependencies.extend(("STAGE6_4B_ANALOGUE_FEATURE_CANDIDATE", item["feature_snapshot_id"], item["record_hash"]) for item in record["candidate_bindings"])
        dependencies.extend((
            ("STAGE6_4C_POLICY", POLICY_ID, self.policy_hash),
            ("STAGE6_4C_COMPARISON_CONTRACT", COMPARISON_CONTRACT_VERSION, self.comparison_contract_hash),
        ))
        return dependencies

    def select(self, *, target_feature_snapshot_id, candidate_feature_snapshot_ids, eligible_start_date, eligible_end_date):
        self._verify_singletons()
        if not isinstance(candidate_feature_snapshot_ids, list) or not candidate_feature_snapshot_ids:
            raise Stage6AnalogueSelectionError("ANALOGUE_CANDIDATE_SET_REQUIRED")
        if len(candidate_feature_snapshot_ids) != len(set(candidate_feature_snapshot_ids)):
            raise Stage6AnalogueSelectionError("ANALOGUE_DUPLICATE_CANDIDATE_ID")
        target = self._feature(target_feature_snapshot_id)
        candidates = [self._feature(candidate_id) for candidate_id in candidate_feature_snapshot_ids]
        record = build_selection(target=target, candidates=candidates, eligible_start_date=eligible_start_date, eligible_end_date=eligible_end_date, policy=self.policy, policy_hash=self.policy_hash, comparison_contract=self.comparison_contract, comparison_contract_hash=self.comparison_contract_hash)
        validate_selection_record(record)
        old = self.connection.execute("SELECT canonical_json FROM analogue_selection_records WHERE selection_spec_hash=?", (record["selection_spec_hash"],)).fetchone()
        if old:
            if old[0] == canonical_json(record):
                return {"status": "IDEMPOTENT_SUCCESS", "selection_record": record}
            raise AnalogueSelectionConflict("ANALOGUE_SELECTION_SPECIFICATION_CONFLICT")
        with self.connection:
            self.connection.execute("INSERT INTO analogue_selection_records VALUES(?,?,?,?,?,?,?,?)", (record["selection_record_id"], record["selection_spec_hash"], record["target_feature_snapshot_id"], record["target_feature_snapshot_hash"], record["candidate_universe_hash"], record["analogue_count"], record["record_hash"], canonical_json(record)))
            self.connection.executemany("INSERT INTO analogue_selection_universe VALUES(?,?,?,?,?)", [(record["selection_record_id"], item["feature_snapshot_id"], item["feature_snapshot_hash"], item["record_hash"], ordinal) for ordinal, item in enumerate(record["candidate_bindings"], 1)])
            self.connection.executemany("INSERT INTO analogue_candidate_evaluations VALUES(?,?,?,?,?)", [(record["selection_record_id"], item["candidate_feature_snapshot_id"], int(item["selected"]), item["distance"], canonical_json(item)) for item in record["candidate_evaluations"]])
            self.connection.executemany("INSERT INTO analogue_selected_records VALUES(?,?,?,?)", [(record["selection_record_id"], item["analogue_id"], rank, canonical_json(item)) for rank, item in enumerate(record["selected_analogues"], 1)])
            self.connection.executemany("INSERT INTO analogue_selection_dependencies VALUES(?,?,?,?)", [(record["selection_record_id"], *item) for item in self._dependencies(record)])
        return {"status": "CREATED", "selection_record": record}

    def integrity_check(self):
        self._verify_singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_SQLITE_INTEGRITY_FAILED")
        for table in TABLES:
            triggers = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
            if triggers != {f"protect_{table}_update", f"protect_{table}_delete"}:
                raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_TRIGGER_MISSING")
        count = 0
        for row in self.connection.execute("SELECT * FROM analogue_selection_records"):
            count += 1
            stored = json.loads(row["canonical_json"])
            validate_selection_record(stored)
            target = self._feature(stored["target_feature_snapshot_id"])
            candidates = [self._feature(item["feature_snapshot_id"]) for item in stored["candidate_bindings"]]
            replay = build_selection(target=target, candidates=candidates, eligible_start_date=stored["eligible_date_range"]["start_date"], eligible_end_date=stored["eligible_date_range"]["end_date"], policy=self.policy, policy_hash=self.policy_hash, comparison_contract=self.comparison_contract, comparison_contract_hash=self.comparison_contract_hash)
            if replay != stored or row["canonical_json"] != canonical_json(stored):
                raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_REPLAY_MISMATCH")
            typed = (row["selection_record_id"], row["selection_spec_hash"], row["target_feature_snapshot_id"], row["target_feature_snapshot_hash"], row["candidate_universe_hash"], row["analogue_count"], row["record_hash"])
            expected_typed = tuple(stored[key] for key in ("selection_record_id", "selection_spec_hash", "target_feature_snapshot_id", "target_feature_snapshot_hash", "candidate_universe_hash", "analogue_count", "record_hash"))
            if typed != expected_typed:
                raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_TYPED_RECORD_MISMATCH")
            universe = [dict(row) for row in self.connection.execute("SELECT candidate_feature_snapshot_id,candidate_feature_snapshot_hash,candidate_record_hash,ordinal FROM analogue_selection_universe WHERE selection_record_id=? ORDER BY ordinal", (stored["selection_record_id"],))]
            expected_universe = [{"candidate_feature_snapshot_id": item["feature_snapshot_id"], "candidate_feature_snapshot_hash": item["feature_snapshot_hash"], "candidate_record_hash": item["record_hash"], "ordinal": ordinal} for ordinal, item in enumerate(stored["candidate_bindings"], 1)]
            if universe != expected_universe:
                raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_UNIVERSE_MISMATCH")
            evaluation_rows = self.connection.execute("SELECT * FROM analogue_candidate_evaluations WHERE selection_record_id=? ORDER BY candidate_feature_snapshot_id", (stored["selection_record_id"],)).fetchall()
            evaluations = [json.loads(item["canonical_json"]) for item in evaluation_rows]
            if evaluations != stored["candidate_evaluations"]:
                raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_EVALUATIONS_MISMATCH")
            for typed_row, evaluation in zip(evaluation_rows, evaluations):
                if (typed_row["candidate_feature_snapshot_id"], typed_row["selected"], typed_row["distance"]) != (evaluation["candidate_feature_snapshot_id"], int(evaluation["selected"]), evaluation["distance"]):
                    raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_EVALUATION_TYPED_MISMATCH")
            selected_rows = self.connection.execute("SELECT * FROM analogue_selected_records WHERE selection_record_id=? ORDER BY rank_ordinal", (stored["selection_record_id"],)).fetchall()
            selected = [json.loads(item["canonical_json"]) for item in selected_rows]
            if selected != stored["selected_analogues"]:
                raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_SELECTED_ROWS_MISMATCH")
            for rank, (typed_row, selected_item) in enumerate(zip(selected_rows, selected), 1):
                if (typed_row["analogue_id"], typed_row["rank_ordinal"]) != (selected_item["analogue_id"], rank):
                    raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_SELECTED_TYPED_MISMATCH")
            actual_dependencies = {(item["record_type"], item["record_id"]): item["record_hash"] for item in self.connection.execute("SELECT * FROM analogue_selection_dependencies WHERE selection_record_id=?", (stored["selection_record_id"],))}
            expected_dependencies = {(kind, identity): digest for kind, identity, digest in self._dependencies(stored)}
            if actual_dependencies != expected_dependencies:
                raise AnalogueSelectionIntegrityFailure("ANALOGUE_SELECTION_DEPENDENCY_MISMATCH")
        return {"result": "PASS", "selection_records": count, "authority": AUTHORITY, "policy_hash": self.policy_hash, "comparison_contract_hash": self.comparison_contract_hash}
