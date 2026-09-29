import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json, parse_utc, without
from stage6_market_context.market_context_validation import validate_record as validate_market
from stage6_historical_analogue.historical_analogue_validation import validate_wrapper as validate_analogue
from stage6_portfolio_context.portfolio_context_validation import validate_portfolio_context_wrapper
from .current_thesis_resolver import resolve_current, resolve_stage6e, validate_source_request
from .errors import Stage6RecursiveThesisError, RecursiveThesisConflict, RecursiveThesisIntegrityFailure
from .policy import *
from .recursive_review_builder import build_assessment, build_review_snapshot
from .recursive_review_validation import validate_assessment, validate_review_snapshot, validate_structured
from .recursive_thesis_builder import build_version_wrapper
from .recursive_thesis_validation import validate_version_wrapper

TABLES = (
    "recursive_thesis_store_meta", "recursive_thesis_policies", "recursive_thesis_contracts",
    "recursive_review_snapshots", "recursive_review_snapshot_bindings", "recursive_review_snapshot_dependencies",
    "recursive_review_assessments", "recursive_review_assertions", "recursive_invalidation_assessments",
    "recursive_assessment_dependencies", "recursive_thesis_versions", "recursive_version_dependencies",
    "recursive_version_audits",
)


class RecursiveThesisStore:
    def __init__(self, database: Path, stage6e_store, *, evidence_store=None, company_effect_store=None, market_context_store=None, historical_analogue_store=None, portfolio_context_store=None):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.stage6e_store = stage6e_store
        self.evidence_store = evidence_store
        self.company_effect_store = company_effect_store
        self.market_context_store = market_context_store
        self.historical_analogue_store = historical_analogue_store
        self.portfolio_context_store = portfolio_context_store
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
CREATE TABLE recursive_thesis_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema TEXT NOT NULL,development_baseline TEXT NOT NULL,semantic_commit TEXT NOT NULL,processor TEXT NOT NULL,authority TEXT NOT NULL,thesis_blob TEXT NOT NULL);
CREATE TABLE recursive_thesis_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE recursive_thesis_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE recursive_review_snapshots(review_snapshot_id TEXT PRIMARY KEY,logical_review_key TEXT UNIQUE NOT NULL,current_source TEXT NOT NULL,current_version_record_id TEXT NOT NULL,current_thesis_hash TEXT NOT NULL,review_cutoff TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE recursive_review_snapshot_bindings(review_snapshot_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(review_snapshot_id,record_type,record_id),FOREIGN KEY(review_snapshot_id) REFERENCES recursive_review_snapshots);
CREATE TABLE recursive_review_snapshot_dependencies(review_snapshot_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(review_snapshot_id,record_type,record_id),FOREIGN KEY(review_snapshot_id) REFERENCES recursive_review_snapshots);
CREATE TABLE recursive_review_assessments(assessment_id TEXT PRIMARY KEY,review_snapshot_id TEXT UNIQUE NOT NULL,current_thesis_hash TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL,FOREIGN KEY(review_snapshot_id) REFERENCES recursive_review_snapshots);
CREATE TABLE recursive_review_assertions(assessment_id TEXT NOT NULL,assertion_id TEXT NOT NULL,ordinal INTEGER NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(assessment_id,assertion_id),UNIQUE(assessment_id,ordinal),FOREIGN KEY(assessment_id) REFERENCES recursive_review_assessments);
CREATE TABLE recursive_invalidation_assessments(assessment_id TEXT NOT NULL,condition_index INTEGER NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(assessment_id,condition_index),FOREIGN KEY(assessment_id) REFERENCES recursive_review_assessments);
CREATE TABLE recursive_assessment_dependencies(assessment_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(assessment_id,record_type,record_id),FOREIGN KEY(assessment_id) REFERENCES recursive_review_assessments);
CREATE TABLE recursive_thesis_versions(version_record_id TEXT PRIMARY KEY,thesis_id TEXT NOT NULL,version INTEGER NOT NULL,current_thesis_hash TEXT UNIQUE NOT NULL,review_snapshot_id TEXT UNIQUE NOT NULL,assessment_id TEXT UNIQUE NOT NULL,thesis_hash TEXT UNIQUE NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL,UNIQUE(thesis_id,version),FOREIGN KEY(review_snapshot_id) REFERENCES recursive_review_snapshots,FOREIGN KEY(assessment_id) REFERENCES recursive_review_assessments);
CREATE TABLE recursive_version_dependencies(version_record_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(version_record_id,record_type,record_id),FOREIGN KEY(version_record_id) REFERENCES recursive_thesis_versions);
CREATE TABLE recursive_version_audits(version_record_id TEXT PRIMARY KEY,version INTEGER NOT NULL,change_type TEXT NOT NULL,decision_cutoff TEXT NOT NULL,canonical_json TEXT NOT NULL,FOREIGN KEY(version_record_id) REFERENCES recursive_thesis_versions);
""")
        self.connection.execute("INSERT INTO recursive_thesis_store_meta VALUES(1,?,?,?,?,?,?)", (STORE_SCHEMA, BASELINE, SEMANTIC_COMMIT, PROCESSOR, AUTHORITY, THESIS_BLOB))
        self.connection.execute("INSERT INTO recursive_thesis_policies VALUES(?,?,?)", (POLICY_ID, self.policy_hash, self.policy_json))
        self.connection.execute("INSERT INTO recursive_thesis_contracts VALUES(?,?,?)", (CONTRACT_VERSION, self.contract_hash, self.contract_json))
        for table in TABLES:
            self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
        self.connection.commit()

    def _singletons(self):
        meta = self.connection.execute("SELECT * FROM recursive_thesis_store_meta").fetchall()
        if len(meta) != 1 or tuple(meta[0]) != (1, STORE_SCHEMA, BASELINE, SEMANTIC_COMMIT, PROCESSOR, AUTHORITY, THESIS_BLOB):
            raise RecursiveThesisIntegrityFailure("RECURSIVE_METADATA_MISMATCH")
        policy = self.connection.execute("SELECT * FROM recursive_thesis_policies").fetchall()
        if len(policy) != 1 or tuple(policy[0]) != (POLICY_ID, self.policy_hash, self.policy_json):
            raise RecursiveThesisIntegrityFailure("RECURSIVE_POLICY_MISMATCH")
        contract = self.connection.execute("SELECT * FROM recursive_thesis_contracts").fetchall()
        if len(contract) != 1 or tuple(contract[0]) != (CONTRACT_VERSION, self.contract_hash, self.contract_json):
            raise RecursiveThesisIntegrityFailure("RECURSIVE_CONTRACT_MISMATCH")

    def _integrity(self, store, code):
        if store is None:
            raise RecursiveThesisIntegrityFailure(code)
        try:
            result = store.integrity_check()
        except Exception as exc:
            raise RecursiveThesisIntegrityFailure(code) from exc
        if result.get("result") != "PASS":
            raise RecursiveThesisIntegrityFailure(code)

    def _json(self, store, table, column, identity, code):
        self._integrity(store, code + "_INTEGRITY_REQUIRED")
        row = store.connection.execute(f"SELECT canonical_json FROM {table} WHERE {column}=?", (identity,)).fetchone()
        if row is None:
            raise Stage6RecursiveThesisError(code + "_NOT_FOUND")
        return json.loads(row[0])

    def _evidence(self, ids, prior, cutoff):
        if not ids:
            return []
        self._integrity(self.evidence_store, "EVIDENCE_STORE_INTEGRITY_REQUIRED")
        result = []
        for identity in ids:
            row = self.evidence_store.connection.execute("SELECT canonical_json FROM ingestion_records WHERE record_id=?", (identity,)).fetchone()
            if row is None:
                raise Stage6RecursiveThesisError("EVIDENCE_NOT_FOUND")
            item = json.loads(row[0])
            if item.get("schema_version") != "STAGE6_EVIDENCE_V2" or item.get("record_kind") != "EVIDENCE" or item.get("evidence_id") != identity or item.get("record_hash") != canonical_hash(without(item, "record_hash")):
                raise RecursiveThesisIntegrityFailure("EVIDENCE_IDENTITY_INVALID")
            retrieved = parse_utc(item.get("retrieved_timestamp_utc"), "retrieved")
            if not (parse_utc(prior, "prior") < retrieved <= parse_utc(cutoff, "review")):
                raise RecursiveThesisIntegrityFailure("NEW_EVIDENCE_CHRONOLOGY_INVALID")
            result.append(item)
        return result

    def _effects(self, ids):
        if not ids:
            return []
        result = []
        for identity in ids:
            item = self._json(self.company_effect_store, "company_effect_records", "company_effect_record_id", identity, "COMPANY_EFFECT")
            if item.get("schema_version") != "STAGE6_EVENT_COMPANY_EFFECT_V1" or item.get("company_effect_record_id") != identity or item.get("company_event_effect") not in {"FAVORABLE", "ADVERSE", "MIXED", "INDETERMINATE", "NOT_EVALUATED"} or item.get("record_hash") != canonical_hash(without(item, "record_hash")):
                raise RecursiveThesisIntegrityFailure("COMPANY_EFFECT_IDENTITY_INVALID")
            result.append(item)
        return result

    def _market(self, identity, ticker, cutoff):
        if identity is None:
            return None
        item = self._json(self.market_context_store, "market_context_records", "market_context_record_id", identity, "MARKET_CONTEXT")
        validate_market(item)
        payload = item["contract_payload"]
        if payload["schema_version"] != "STAGE6_MARKET_CONTEXT_V2" or payload["ticker"] != ticker or payload["pit_verified"] is not True or not (parse_utc(payload["data_cutoff_timestamp"], "data") <= parse_utc(payload["as_of_timestamp"], "asof") <= parse_utc(cutoff, "review")):
            raise RecursiveThesisIntegrityFailure("MARKET_CONTEXT_REVIEW_INVALID")
        return item

    def _analogue(self, identity, cutoff):
        if identity is None:
            return None
        item = self._json(self.historical_analogue_store, "historical_analogue_records", "historical_analogue_id", identity, "HISTORICAL_ANALOGUE")
        validate_analogue(item)
        payload = item["historical_analogue_payload"]
        if payload["schema_version"] != "STAGE6_HISTORICAL_ANALOGUE_V2" or payload["pit_verified"] is not True or payload["analogue_count"] != len(payload["selected_analogues"]) or not (parse_utc(payload["selection_cutoff"], "selection") <= parse_utc(payload["as_of_timestamp"], "asof") <= parse_utc(cutoff, "review")):
            raise RecursiveThesisIntegrityFailure("HISTORICAL_ANALOGUE_REVIEW_INVALID")
        return item

    def _portfolio(self, identity, cutoff):
        if identity is None:
            return None
        item = self._json(self.portfolio_context_store, "portfolio_context_records", "portfolio_context_id", identity, "PORTFOLIO_CONTEXT")
        validate_portfolio_context_wrapper(item)
        payload = item["portfolio_context"]
        if payload["schema_version"] != "STAGE6_PORTFOLIO_CONTEXT_V2" or not (parse_utc(payload["data_cutoff_timestamp"], "data") <= parse_utc(payload["as_of_timestamp"], "asof") <= parse_utc(cutoff, "review")):
            raise RecursiveThesisIntegrityFailure("PORTFOLIO_CONTEXT_REVIEW_INVALID")
        return item

    def _selected(self, current, review_cutoff, evidence_ids, company_effect_ids, market_context_id, historical_analogue_id, portfolio_context_id):
        if not isinstance(evidence_ids, list) or not isinstance(company_effect_ids, list) or len(evidence_ids) != len(set(evidence_ids)) or len(company_effect_ids) != len(set(company_effect_ids)):
            raise Stage6RecursiveThesisError("RECURSIVE_INPUT_SELECTION_INVALID")
        return {
            "evidence": self._evidence(evidence_ids, current["decision_cutoff"], review_cutoff),
            "effects": self._effects(company_effect_ids),
            "market": self._market(market_context_id, current["ticker"], review_cutoff),
            "analogue": self._analogue(historical_analogue_id, review_cutoff),
            "portfolio": self._portfolio(portfolio_context_id, review_cutoff),
        }

    def review(self, *, current_thesis_source, current_version_record_id, review_cutoff, evidence_ids, company_effect_ids, invalidation_assessments, change_assertions, market_context_id=None, historical_analogue_id=None, portfolio_context_id=None):
        self._singletons()
        validate_source_request(current_thesis_source, current_version_record_id)
        source_wrapper, current = resolve_current(current_thesis_source, current_version_record_id, self.stage6e_store, self)
        if type(current.get("version")) is not int or current["version"] < 2:
            raise RecursiveThesisIntegrityFailure("CURRENT_THESIS_VERSION_INVALID")
        if parse_utc(review_cutoff, "review") <= parse_utc(current["decision_cutoff"], "current"):
            raise RecursiveThesisIntegrityFailure("RECURSIVE_REVIEW_CUTOFF_INVALID")
        selected = self._selected(current, review_cutoff, evidence_ids, company_effect_ids, market_context_id, historical_analogue_id, portfolio_context_id)
        snapshot = build_review_snapshot(current=current, source=current_thesis_source, source_record_id=current_version_record_id, review_cutoff=review_cutoff, policy_hash=self.policy_hash, contract_hash=self.contract_hash, **selected)
        validate_review_snapshot(snapshot, current)
        validate_structured(current, snapshot, invalidation_assessments, change_assertions)
        assessment = build_assessment(current=current, snapshot=snapshot, invalidation_assessments=invalidation_assessments, change_assertions=change_assertions, policy_hash=self.policy_hash, contract_hash=self.contract_hash)
        validate_assessment(assessment, current, snapshot)
        logical = canonical_json({"current_thesis_hash": current["record_hash"], "review_cutoff": review_cutoff})
        old_snapshot = self.connection.execute("SELECT canonical_json FROM recursive_review_snapshots WHERE logical_review_key=?", (logical,)).fetchone()
        if old_snapshot and old_snapshot[0] != canonical_json(snapshot):
            raise RecursiveThesisConflict("RECURSIVE_REVIEW_LOGICAL_CONFLICT")
        old_assessment = self.connection.execute("SELECT canonical_json FROM recursive_review_assessments WHERE review_snapshot_id=?", (snapshot["review_snapshot_id"],)).fetchone()
        if old_assessment and old_assessment[0] != canonical_json(assessment):
            raise RecursiveThesisConflict("RECURSIVE_ASSESSMENT_CONFLICT")
        wrapper = None
        if assessment["review_outcome"] == "DETERMINATE":
            wrapper = build_version_wrapper(current_thesis_source, current_version_record_id, current, snapshot, assessment, self.policy_hash, self.contract_hash)
            validate_version_wrapper(wrapper, current_thesis_source, current_version_record_id, current, snapshot, assessment, self.policy_hash, self.contract_hash)
            old_version = self.connection.execute("SELECT canonical_json FROM recursive_thesis_versions WHERE thesis_id=? AND version=?", (current["thesis_id"], current["version"] + 1)).fetchone()
            if old_version:
                if old_version[0] == canonical_json(wrapper):
                    return {"status": "IDEMPOTENT_SUCCESS", "review_snapshot": snapshot, "assessment": assessment, "version_record": wrapper, "trade_thesis": wrapper["trade_thesis"]}
                raise RecursiveThesisConflict("RECURSIVE_THESIS_FORK_PROHIBITED")
        snapshot_new = old_snapshot is None
        assessment_new = old_assessment is None
        with self.connection:
            if snapshot_new:
                self._insert_snapshot(snapshot, logical)
            if assessment_new:
                self._insert_assessment(assessment)
            if wrapper is not None:
                self._insert_version(wrapper)
        if wrapper is None:
            return {"status": "WITHHELD_INDETERMINATE", "review_snapshot": snapshot, "assessment": assessment, "version_record": None, "trade_thesis": None}
        return {"status": "CREATED", "review_snapshot": snapshot, "assessment": assessment, "version_record": wrapper, "trade_thesis": wrapper["trade_thesis"]}

    def _policy_dependencies(self):
        return [("STAGE6_6F_POLICY", POLICY_ID, self.policy_hash), ("STAGE6_6F_CONTRACT", CONTRACT_VERSION, self.contract_hash)]

    def _insert_snapshot(self, snapshot, logical):
        self.connection.execute("INSERT INTO recursive_review_snapshots VALUES(?,?,?,?,?,?,?,?)", (snapshot["review_snapshot_id"], logical, snapshot["current_thesis_source"], snapshot["current_version_record_id"], snapshot["current_thesis_binding"]["record_hash"], snapshot["review_cutoff"], snapshot["record_hash"], canonical_json(snapshot)))
        bindings = [(item["record_type"], item["record_id"], item["record_hash"]) for item in snapshot["direct_input_bindings"]]
        self.connection.executemany("INSERT INTO recursive_review_snapshot_bindings VALUES(?,?,?,?)", [(snapshot["review_snapshot_id"], *item) for item in bindings])
        self.connection.executemany("INSERT INTO recursive_review_snapshot_dependencies VALUES(?,?,?,?)", [(snapshot["review_snapshot_id"], *item) for item in [*bindings, *self._policy_dependencies()]])

    def _insert_assessment(self, assessment):
        self.connection.execute("INSERT INTO recursive_review_assessments VALUES(?,?,?,?,?)", (assessment["assessment_id"], assessment["review_snapshot_binding"]["record_id"], assessment["current_thesis_binding"]["record_hash"], assessment["record_hash"], canonical_json(assessment)))
        self.connection.executemany("INSERT INTO recursive_review_assertions VALUES(?,?,?,?)", [(assessment["assessment_id"], item["assertion_id"], index, canonical_json(item)) for index, item in enumerate(assessment["change_assertions"])])
        self.connection.executemany("INSERT INTO recursive_invalidation_assessments VALUES(?,?,?)", [(assessment["assessment_id"], item["condition_index"], canonical_json(item)) for item in assessment["invalidation_assessments"]])
        direct = [tuple(assessment["current_thesis_binding"][key] for key in ("record_type", "record_id", "record_hash")), tuple(assessment["review_snapshot_binding"][key] for key in ("record_type", "record_id", "record_hash")), *self._policy_dependencies()]
        self.connection.executemany("INSERT INTO recursive_assessment_dependencies VALUES(?,?,?,?)", [(assessment["assessment_id"], *item) for item in direct])

    def _insert_version(self, wrapper):
        thesis = wrapper["trade_thesis"]
        self.connection.execute("INSERT INTO recursive_thesis_versions VALUES(?,?,?,?,?,?,?,?,?)", (wrapper["version_record_id"], wrapper["thesis_id"], wrapper["thesis_version"], wrapper["current_thesis_binding"]["record_hash"], wrapper["review_snapshot_binding"]["record_id"], wrapper["assessment_binding"]["record_id"], thesis["record_hash"], wrapper["record_hash"], canonical_json(wrapper)))
        inputs = [wrapper["current_thesis_binding"], wrapper["review_snapshot_binding"], wrapper["assessment_binding"]]
        deps = [*(tuple(item[key] for key in ("record_type", "record_id", "record_hash")) for item in inputs), *self._policy_dependencies()]
        self.connection.executemany("INSERT INTO recursive_version_dependencies VALUES(?,?,?,?)", [(wrapper["version_record_id"], *item) for item in deps])
        audit = thesis["change_history"][-1]
        self.connection.execute("INSERT INTO recursive_version_audits VALUES(?,?,?,?,?)", (wrapper["version_record_id"], thesis["version"], audit["change_type"], audit["decision_cutoff"], canonical_json(audit)))

    def _current_for_snapshot(self, snapshot, wrappers):
        if snapshot["current_thesis_source"] == "STAGE6_6E":
            return resolve_stage6e(self.stage6e_store, snapshot["current_version_record_id"])[1]
        wrapper = wrappers.get(snapshot["current_version_record_id"])
        if wrapper is None:
            raise RecursiveThesisIntegrityFailure("RECURSIVE_CURRENT_SOURCE_MISSING")
        return wrapper["trade_thesis"]

    def integrity_check(self):
        self._singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RecursiveThesisIntegrityFailure("RECURSIVE_SQLITE_INTEGRITY_FAILED")
        for table in TABLES:
            triggers = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,))}
            if triggers != {f"protect_{table}_update", f"protect_{table}_delete"}:
                raise RecursiveThesisIntegrityFailure("RECURSIVE_TRIGGER_MISSING")
        self._integrity(self.stage6e_store, "STAGE6_6E_SOURCE_INTEGRITY_REQUIRED")
        wrappers = {}
        rows = self.connection.execute("SELECT * FROM recursive_thesis_versions ORDER BY version,version_record_id").fetchall()
        for row in rows:
            wrapper = json.loads(row["canonical_json"])
            source = wrapper["current_thesis_source"]
            if source == "STAGE6_6E":
                current = resolve_stage6e(self.stage6e_store, wrapper["current_version_record_id"])[1]
            else:
                prior = wrappers.get(wrapper["current_version_record_id"])
                if prior is None:
                    raise RecursiveThesisIntegrityFailure("RECURSIVE_VERSION_CHAIN_SOURCE_MISSING")
                current = prior["trade_thesis"]
            snapshot_row = self.connection.execute("SELECT canonical_json FROM recursive_review_snapshots WHERE review_snapshot_id=?", (wrapper["review_snapshot_binding"]["record_id"],)).fetchone()
            assessment_row = self.connection.execute("SELECT canonical_json FROM recursive_review_assessments WHERE assessment_id=?", (wrapper["assessment_binding"]["record_id"],)).fetchone()
            if snapshot_row is None or assessment_row is None:
                raise RecursiveThesisIntegrityFailure("RECURSIVE_VERSION_CHILD_MISSING")
            snapshot = json.loads(snapshot_row[0]); assessment = json.loads(assessment_row[0])
            validate_version_wrapper(wrapper, source, wrapper["current_version_record_id"], current, snapshot, assessment, self.policy_hash, self.contract_hash)
            if build_version_wrapper(source, wrapper["current_version_record_id"], current, snapshot, assessment, self.policy_hash, self.contract_hash) != wrapper or row["canonical_json"] != canonical_json(wrapper):
                raise RecursiveThesisIntegrityFailure("RECURSIVE_VERSION_REPLAY_MISMATCH")
            typed = (row["version_record_id"], row["thesis_id"], row["version"], row["current_thesis_hash"], row["review_snapshot_id"], row["assessment_id"], row["thesis_hash"], row["record_hash"])
            expected = (wrapper["version_record_id"], wrapper["thesis_id"], wrapper["thesis_version"], wrapper["current_thesis_binding"]["record_hash"], wrapper["review_snapshot_binding"]["record_id"], wrapper["assessment_binding"]["record_id"], wrapper["trade_thesis"]["record_hash"], wrapper["record_hash"])
            if typed != expected:
                raise RecursiveThesisIntegrityFailure("RECURSIVE_VERSION_TYPED_MISMATCH")
            self._verify_version_children(wrapper)
            wrappers[wrapper["version_record_id"]] = wrapper
        snapshots = {}
        for row in self.connection.execute("SELECT * FROM recursive_review_snapshots"):
            snapshot = json.loads(row["canonical_json"]); current = self._current_for_snapshot(snapshot, wrappers)
            validate_review_snapshot(snapshot, current)
            if row["canonical_json"] != canonical_json(snapshot) or row["record_hash"] != snapshot["record_hash"]:
                raise RecursiveThesisIntegrityFailure("RECURSIVE_SNAPSHOT_REPLAY_MISMATCH")
            self._verify_snapshot_children(snapshot)
            snapshots[snapshot["review_snapshot_id"]] = (snapshot, current)
        for row in self.connection.execute("SELECT * FROM recursive_review_assessments"):
            assessment = json.loads(row["canonical_json"]); pair = snapshots.get(assessment["review_snapshot_binding"]["record_id"])
            if pair is None:
                raise RecursiveThesisIntegrityFailure("RECURSIVE_ASSESSMENT_SNAPSHOT_MISSING")
            snapshot, current = pair; validate_assessment(assessment, current, snapshot)
            if build_assessment(current=current, snapshot=snapshot, invalidation_assessments=assessment["invalidation_assessments"], change_assertions=assessment["change_assertions"], policy_hash=self.policy_hash, contract_hash=self.contract_hash) != assessment or row["canonical_json"] != canonical_json(assessment):
                raise RecursiveThesisIntegrityFailure("RECURSIVE_ASSESSMENT_REPLAY_MISMATCH")
            self._verify_assessment_children(assessment)
        return {"result": "PASS", "review_snapshots": len(snapshots), "assessments": self.connection.execute("SELECT count(*) FROM recursive_review_assessments").fetchone()[0], "trade_thesis_versions": len(wrappers), "authority": AUTHORITY}

    def _verify_snapshot_children(self, snapshot):
        identity = snapshot["review_snapshot_id"]
        bindings = sorted(tuple(row) for row in self.connection.execute("SELECT record_type,record_id,record_hash FROM recursive_review_snapshot_bindings WHERE review_snapshot_id=?", (identity,)))
        expected_bindings = sorted(tuple(item[key] for key in ("record_type", "record_id", "record_hash")) for item in snapshot["direct_input_bindings"])
        dependencies = sorted(tuple(row) for row in self.connection.execute("SELECT record_type,record_id,record_hash FROM recursive_review_snapshot_dependencies WHERE review_snapshot_id=?", (identity,)))
        if bindings != expected_bindings or dependencies != sorted([*expected_bindings, *self._policy_dependencies()]):
            raise RecursiveThesisIntegrityFailure("RECURSIVE_SNAPSHOT_DEPENDENCY_MISMATCH")

    def _verify_assessment_children(self, assessment):
        identity = assessment["assessment_id"]
        assertions = [json.loads(row[0]) for row in self.connection.execute("SELECT canonical_json FROM recursive_review_assertions WHERE assessment_id=? ORDER BY ordinal", (identity,))]
        invalidations = [json.loads(row[0]) for row in self.connection.execute("SELECT canonical_json FROM recursive_invalidation_assessments WHERE assessment_id=? ORDER BY condition_index", (identity,))]
        expected_deps = [tuple(assessment[key][part] for part in ("record_type", "record_id", "record_hash")) for key in ("current_thesis_binding", "review_snapshot_binding")]
        deps = sorted(tuple(row) for row in self.connection.execute("SELECT record_type,record_id,record_hash FROM recursive_assessment_dependencies WHERE assessment_id=?", (identity,)))
        if assertions != assessment["change_assertions"] or invalidations != assessment["invalidation_assessments"] or deps != sorted([*expected_deps, *self._policy_dependencies()]):
            raise RecursiveThesisIntegrityFailure("RECURSIVE_ASSESSMENT_CHILD_MISMATCH")

    def _verify_version_children(self, wrapper):
        identity = wrapper["version_record_id"]
        inputs = [wrapper["current_thesis_binding"], wrapper["review_snapshot_binding"], wrapper["assessment_binding"]]
        expected = [tuple(item[key] for key in ("record_type", "record_id", "record_hash")) for item in inputs]
        deps = sorted(tuple(row) for row in self.connection.execute("SELECT record_type,record_id,record_hash FROM recursive_version_dependencies WHERE version_record_id=?", (identity,)))
        audit = self.connection.execute("SELECT canonical_json FROM recursive_version_audits WHERE version_record_id=?", (identity,)).fetchone()
        if deps != sorted([*expected, *self._policy_dependencies()]) or audit is None or json.loads(audit[0]) != wrapper["trade_thesis"]["change_history"][-1]:
            raise RecursiveThesisIntegrityFailure("RECURSIVE_VERSION_CHILD_MISMATCH")

    def update_record(self, *_, **__):
        raise Stage6RecursiveThesisError("IMMUTABLE_RECORD_UPDATE_PROHIBITED")
