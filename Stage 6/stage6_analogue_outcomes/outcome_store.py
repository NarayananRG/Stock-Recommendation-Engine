import json
import sqlite3
from pathlib import Path

from stage6_analogue_selection.selection_validation import validate_selection_record
from stage6_ingestion.canonical import canonical_json

from .errors import AnalogueOutcomeConflict, AnalogueOutcomeIntegrityFailure, Stage6AnalogueOutcomeError
from .outcome_builder import HORIZONS, RETURN_NAMES, build_outcome_attachment
from .outcome_validation import validate_outcome_record
from .policy import (
    AUTHORITY, BASELINE_COMMIT, COMPARISON_CONTRACT_HASH, COMPARISON_CONTRACT_VERSION,
    EXPECTED_OUTCOME_DEFINITION_HASH_V1, EXPECTED_POLICY_HASH_V1, METRIC,
    OUTCOME_DEFINITION_VERSION, POLICY_ID, PROCESSOR_VERSION, SCHEMA_VERSION,
    SELECTION_ENGINE_COMMIT, SELECTION_POLICY_HASH, SELECTION_POLICY_ID,
    SELECTION_PROCESSOR, SELECTION_SCHEMA, STORE_SCHEMA_VERSION,
    load_outcome_definition, load_policy,
)

TABLES = (
    "analogue_outcome_store_meta", "analogue_outcome_policies", "analogue_outcome_definitions",
    "analogue_outcome_attachment_sets", "analogue_outcome_attachments", "analogue_outcome_measurements",
    "analogue_outcome_evidence_bindings", "analogue_outcome_dependencies",
)


class AnalogueOutcomeStore:
    def __init__(self, database: Path, selection_store, evidence_store):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.selection_store = selection_store
        self.evidence_store = evidence_store
        self.policy, self.policy_json, self.policy_hash = load_policy()
        self.outcome_definition, self.outcome_definition_json, self.outcome_definition_hash = load_outcome_definition()
        new = not self.database.exists()
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        if new:
            self._initialize()
        self._singletons()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self): self.connection.close()

    def _initialize(self):
        self.connection.executescript("""
        CREATE TABLE analogue_outcome_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,attachment_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,selection_engine_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL);
        CREATE TABLE analogue_outcome_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
        CREATE TABLE analogue_outcome_definitions(definition_version TEXT PRIMARY KEY,definition_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
        CREATE TABLE analogue_outcome_attachment_sets(attachment_set_id TEXT PRIMARY KEY,logical_attachment_key TEXT UNIQUE NOT NULL,selection_record_id TEXT NOT NULL,selection_record_hash TEXT NOT NULL,outcome_unit TEXT NOT NULL,selected_analogue_count INTEGER NOT NULL,attachment_set_hash TEXT UNIQUE NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
        CREATE TABLE analogue_outcome_attachments(attachment_set_id TEXT NOT NULL,analogue_id TEXT NOT NULL,selection_rank INTEGER NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(attachment_set_id,analogue_id),FOREIGN KEY(attachment_set_id) REFERENCES analogue_outcome_attachment_sets);
        CREATE TABLE analogue_outcome_measurements(attachment_set_id TEXT NOT NULL,analogue_id TEXT NOT NULL,measurement_key TEXT NOT NULL,status TEXT NOT NULL,value REAL,unit TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(attachment_set_id,analogue_id,measurement_key),FOREIGN KEY(attachment_set_id,analogue_id) REFERENCES analogue_outcome_attachments);
        CREATE TABLE analogue_outcome_evidence_bindings(attachment_set_id TEXT NOT NULL,analogue_id TEXT NOT NULL,measurement_key TEXT NOT NULL,evidence_id TEXT NOT NULL,evidence_hash TEXT NOT NULL,PRIMARY KEY(attachment_set_id,analogue_id,measurement_key,evidence_id),FOREIGN KEY(attachment_set_id,analogue_id,measurement_key) REFERENCES analogue_outcome_measurements);
        CREATE TABLE analogue_outcome_dependencies(attachment_set_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(attachment_set_id,record_type,record_id),FOREIGN KEY(attachment_set_id) REFERENCES analogue_outcome_attachment_sets);
        """)
        self.connection.execute("INSERT INTO analogue_outcome_store_meta VALUES(1,?,?,?,?,?,?)", (STORE_SCHEMA_VERSION, SCHEMA_VERSION, BASELINE_COMMIT, SELECTION_ENGINE_COMMIT, PROCESSOR_VERSION, AUTHORITY))
        self.connection.execute("INSERT INTO analogue_outcome_policies VALUES(?,?,?)", (POLICY_ID, self.policy_hash, self.policy_json))
        self.connection.execute("INSERT INTO analogue_outcome_definitions VALUES(?,?,?)", (OUTCOME_DEFINITION_VERSION, self.outcome_definition_hash, self.outcome_definition_json))
        for table in TABLES:
            self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
        self.connection.commit()

    def _singletons(self):
        meta = self.connection.execute("SELECT * FROM analogue_outcome_store_meta").fetchall()
        if len(meta) != 1 or tuple(meta[0]) != (1, STORE_SCHEMA_VERSION, SCHEMA_VERSION, BASELINE_COMMIT, SELECTION_ENGINE_COMMIT, PROCESSOR_VERSION, AUTHORITY):
            raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_METADATA_MISMATCH")
        policies = self.connection.execute("SELECT * FROM analogue_outcome_policies").fetchall()
        if len(policies) != 1 or tuple(policies[0]) != (POLICY_ID, EXPECTED_POLICY_HASH_V1, self.policy_json):
            raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_POLICY_MISMATCH")
        definitions = self.connection.execute("SELECT * FROM analogue_outcome_definitions").fetchall()
        if len(definitions) != 1 or tuple(definitions[0]) != (OUTCOME_DEFINITION_VERSION, EXPECTED_OUTCOME_DEFINITION_HASH_V1, self.outcome_definition_json):
            raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_DEFINITION_MISMATCH")

    def _selection(self, selection_record_id):
        if self.selection_store.integrity_check()["result"] != "PASS":
            raise AnalogueOutcomeIntegrityFailure("ANALOGUE_SELECTION_STORE_INTEGRITY_REQUIRED")
        row = self.selection_store.connection.execute("SELECT canonical_json FROM analogue_selection_records WHERE selection_record_id=?", (selection_record_id,)).fetchone()
        if row is None: raise Stage6AnalogueOutcomeError("ANALOGUE_SELECTION_NOT_FOUND")
        record = json.loads(row[0]); validate_selection_record(record)
        expected = (SELECTION_SCHEMA, SELECTION_PROCESSOR, SELECTION_POLICY_ID, SELECTION_POLICY_HASH, COMPARISON_CONTRACT_VERSION, COMPARISON_CONTRACT_HASH, METRIC, AUTHORITY, True)
        actual = tuple(record.get(key) for key in ("schema_version", "processor_version", "policy_id", "policy_hash", "comparison_contract_version", "comparison_contract_hash", "similarity_metric", "authority", "pit_verified"))
        if actual != expected: raise AnalogueOutcomeIntegrityFailure("ANALOGUE_SELECTION_IDENTITY_INVALID")
        return record

    def _evidence_records(self, payloads):
        if self.evidence_store.integrity_check()["result"] != "PASS":
            raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_EVIDENCE_STORE_INTEGRITY_REQUIRED")
        ids = set()
        for payload in payloads:
            measurements = [value for horizon in payload.get("horizons", {}).values() for value in horizon.values()]
            measurements += [payload.get("maximum_adverse_excursion", {}), payload.get("maximum_favourable_excursion", {}), payload.get("recovery_time", {})]
            for measurement in measurements:
                ids.update(binding.get("evidence_id") for binding in measurement.get("evidence_bindings", []) if isinstance(binding, dict))
        return {identity: self.evidence_store.get_record(identity) for identity in sorted(ids)}

    def _measurements(self, attachment):
        for horizon in HORIZONS:
            for name in RETURN_NAMES: yield f"{horizon}.{name}", attachment["horizons"][horizon][name]
        yield "maximum_adverse_excursion", attachment["maximum_adverse_excursion"]
        yield "maximum_favourable_excursion", attachment["maximum_favourable_excursion"]
        yield "recovery_time", attachment["recovery_time"]

    def _dependencies(self, record):
        values = [("STAGE6_4C_ANALOGUE_SELECTION", record["selection_record_id"], record["selection_record_hash"]), ("STAGE6_4D_POLICY", POLICY_ID, self.policy_hash), ("STAGE6_4D_OUTCOME_DEFINITION", OUTCOME_DEFINITION_VERSION, self.outcome_definition_hash)]
        values += [("STAGE6_EVIDENCE", item["evidence_id"], item["evidence_hash"]) for item in record["evidence_bindings"]]
        return values

    def attach(self, *, selection_record_id, outcome_unit, analogue_payloads):
        self._singletons(); selection = self._selection(selection_record_id); evidence = self._evidence_records(analogue_payloads)
        record = build_outcome_attachment(selection=selection, payloads=analogue_payloads, outcome_unit=outcome_unit, evidence_records=evidence, policy=self.policy, policy_hash=self.policy_hash, outcome_definition_hash=self.outcome_definition_hash)
        validate_outcome_record(record)
        old = self.connection.execute("SELECT canonical_json FROM analogue_outcome_attachment_sets WHERE logical_attachment_key=?", (record["logical_attachment_key"],)).fetchone()
        if old:
            if old[0] == canonical_json(record): return {"status":"IDEMPOTENT_SUCCESS","outcome_attachment":record}
            raise AnalogueOutcomeConflict("ANALOGUE_OUTCOME_ATTACHMENT_CONFLICT")
        with self.connection:
            self.connection.execute("INSERT INTO analogue_outcome_attachment_sets VALUES(?,?,?,?,?,?,?,?,?)", (record["attachment_set_id"], record["logical_attachment_key"], record["selection_record_id"], record["selection_record_hash"], record["outcome_unit"], record["selected_analogue_count"], record["attachment_set_hash"], record["record_hash"], canonical_json(record)))
            for attachment in record["analogue_attachments"]:
                self.connection.execute("INSERT INTO analogue_outcome_attachments VALUES(?,?,?,?)", (record["attachment_set_id"], attachment["analogue_id"], attachment["selection_rank"], canonical_json(attachment)))
                for key, measurement in self._measurements(attachment):
                    self.connection.execute("INSERT INTO analogue_outcome_measurements VALUES(?,?,?,?,?,?,?)", (record["attachment_set_id"], attachment["analogue_id"], key, measurement["status"], measurement["value"], measurement["unit"], canonical_json(measurement)))
                    self.connection.executemany("INSERT INTO analogue_outcome_evidence_bindings VALUES(?,?,?,?,?)", [(record["attachment_set_id"], attachment["analogue_id"], key, item["evidence_id"], item["evidence_hash"]) for item in measurement["evidence_bindings"]])
            self.connection.executemany("INSERT INTO analogue_outcome_dependencies VALUES(?,?,?,?)", [(record["attachment_set_id"], *item) for item in self._dependencies(record)])
        return {"status":"CREATED","outcome_attachment":record}

    def integrity_check(self):
        self._singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall(): raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_SQLITE_INTEGRITY_FAILED")
        for table in TABLES:
            triggers={row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
            if triggers!={f"protect_{table}_update",f"protect_{table}_delete"}: raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_TRIGGER_MISSING")
        count=0
        for row in self.connection.execute("SELECT * FROM analogue_outcome_attachment_sets"):
            count+=1; stored=json.loads(row["canonical_json"]); validate_outcome_record(stored); selection=self._selection(stored["selection_record_id"])
            payloads=[{"analogue_id":item["analogue_id"],"horizons":item["horizons"],"maximum_adverse_excursion":item["maximum_adverse_excursion"],"maximum_favourable_excursion":item["maximum_favourable_excursion"],"recovery_time":item["recovery_time"]} for item in stored["analogue_attachments"]]
            evidence=self._evidence_records(payloads); replay=build_outcome_attachment(selection=selection,payloads=payloads,outcome_unit=stored["outcome_unit"],evidence_records=evidence,policy=self.policy,policy_hash=self.policy_hash,outcome_definition_hash=self.outcome_definition_hash)
            if replay!=stored or row["canonical_json"]!=canonical_json(stored): raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_REPLAY_MISMATCH")
            typed=tuple(row[key] for key in ("attachment_set_id","logical_attachment_key","selection_record_id","selection_record_hash","outcome_unit","selected_analogue_count","attachment_set_hash","record_hash")); wanted=tuple(stored[key] for key in ("attachment_set_id","logical_attachment_key","selection_record_id","selection_record_hash","outcome_unit","selected_analogue_count","attachment_set_hash","record_hash"))
            if typed!=wanted: raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_TYPED_RECORD_MISMATCH")
            attachment_rows=self.connection.execute("SELECT * FROM analogue_outcome_attachments WHERE attachment_set_id=? ORDER BY selection_rank",(stored["attachment_set_id"],)).fetchall(); attachments=[json.loads(item["canonical_json"]) for item in attachment_rows]
            if attachments!=stored["analogue_attachments"] or any((item["analogue_id"],item["selection_rank"])!=(attachment["analogue_id"],attachment["selection_rank"]) for item,attachment in zip(attachment_rows,attachments)): raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_ATTACHMENT_ROWS_MISMATCH")
            for attachment in attachments:
                rows=self.connection.execute("SELECT * FROM analogue_outcome_measurements WHERE attachment_set_id=? AND analogue_id=? ORDER BY measurement_key",(stored["attachment_set_id"],attachment["analogue_id"])).fetchall(); actual={item["measurement_key"]:json.loads(item["canonical_json"]) for item in rows}; expected=dict(self._measurements(attachment))
                if actual!=expected or any((item["status"],item["value"],item["unit"])!=(actual[item["measurement_key"]]["status"],actual[item["measurement_key"]]["value"],actual[item["measurement_key"]]["unit"]) for item in rows): raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_MEASUREMENTS_MISMATCH")
                for key,measurement in expected.items():
                    bindings=[{"evidence_id":item["evidence_id"],"evidence_hash":item["evidence_hash"]} for item in self.connection.execute("SELECT * FROM analogue_outcome_evidence_bindings WHERE attachment_set_id=? AND analogue_id=? AND measurement_key=? ORDER BY evidence_id",(stored["attachment_set_id"],attachment["analogue_id"],key))]
                    if bindings!=measurement["evidence_bindings"]: raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_EVIDENCE_ROWS_MISMATCH")
            actual_deps={(item["record_type"],item["record_id"]):item["record_hash"] for item in self.connection.execute("SELECT * FROM analogue_outcome_dependencies WHERE attachment_set_id=?",(stored["attachment_set_id"],))}; expected_deps={(kind,identity):digest for kind,identity,digest in self._dependencies(stored)}
            if actual_deps!=expected_deps: raise AnalogueOutcomeIntegrityFailure("ANALOGUE_OUTCOME_DEPENDENCY_MISMATCH")
        return {"result":"PASS","attachment_sets":count,"authority":AUTHORITY,"policy_hash":self.policy_hash,"outcome_definition_hash":self.outcome_definition_hash}
