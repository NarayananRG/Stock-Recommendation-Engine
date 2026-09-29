import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_json,parse_utc
from .errors import Stage6ThesisSeedError,ThesisSeedConflict,ThesisSeedIntegrityFailure
from .policy import *
from .thesis_seed_builder import build_seed
from .thesis_seed_validation import validate_seed,validate_source

TABLES=("thesis_seed_store_meta","thesis_seed_policies","thesis_seed_contracts","thesis_seed_records","thesis_seed_fills","thesis_seed_source_bindings","thesis_seed_evidence_bindings","thesis_seed_dependencies")

class ThesisSeedStore:
    def __init__(self,database:Path,evidence_store=None):
        self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.evidence_store=evidence_store
        self.policy,self.policy_json,self.policy_hash=load_policy();self.contract,self.contract_json,self.contract_hash=load_seed_contract()
        new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
        if new:self._initialize()
        self._verify_singletons()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def close(self):self.connection.close()
    def _initialize(self):
        self.connection.executescript("""
CREATE TABLE thesis_seed_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL,trade_thesis_blob TEXT NOT NULL);
CREATE TABLE thesis_seed_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE thesis_seed_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE thesis_seed_records(seed_record_id TEXT PRIMARY KEY,source_export_id TEXT UNIQUE NOT NULL,source_export_hash TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE thesis_seed_fills(seed_record_id TEXT NOT NULL,ordinal INTEGER NOT NULL,transaction_id TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(seed_record_id,ordinal),UNIQUE(seed_record_id,transaction_id),FOREIGN KEY(seed_record_id) REFERENCES thesis_seed_records);
CREATE TABLE thesis_seed_source_bindings(seed_record_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,recorded_at_utc TEXT NOT NULL,PRIMARY KEY(seed_record_id,record_type,record_id),FOREIGN KEY(seed_record_id) REFERENCES thesis_seed_records);
CREATE TABLE thesis_seed_evidence_bindings(seed_record_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(seed_record_id,record_id),FOREIGN KEY(seed_record_id) REFERENCES thesis_seed_records);
CREATE TABLE thesis_seed_dependencies(seed_record_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(seed_record_id,record_type,record_id),FOREIGN KEY(seed_record_id) REFERENCES thesis_seed_records);
""")
        self.connection.execute("INSERT INTO thesis_seed_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY,TRADE_THESIS_BLOB))
        self.connection.execute("INSERT INTO thesis_seed_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json));self.connection.execute("INSERT INTO thesis_seed_contracts VALUES(?,?,?)",(SEED_CONTRACT_VERSION,self.contract_hash,self.contract_json))
        for table in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
        self.connection.commit()
    def _verify_singletons(self):
        rows=self.connection.execute("SELECT * FROM thesis_seed_store_meta").fetchall()
        if len(rows)!=1 or tuple(rows[0])!=(1,STORE_SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY,TRADE_THESIS_BLOB):raise ThesisSeedIntegrityFailure("THESIS_SEED_METADATA_MISMATCH")
        rows=self.connection.execute("SELECT * FROM thesis_seed_policies").fetchall()
        if len(rows)!=1 or tuple(rows[0])!=(POLICY_ID,self.policy_hash,self.policy_json):raise ThesisSeedIntegrityFailure("THESIS_SEED_POLICY_MISMATCH")
        rows=self.connection.execute("SELECT * FROM thesis_seed_contracts").fetchall()
        if len(rows)!=1 or tuple(rows[0])!=(SEED_CONTRACT_VERSION,self.contract_hash,self.contract_json):raise ThesisSeedIntegrityFailure("THESIS_SEED_CONTRACT_MISMATCH")
    def _evidence_bindings(self,ids,cutoff):
        if not ids:return []
        if self.evidence_store is None:raise ThesisSeedIntegrityFailure("EVIDENCE_STORE_REQUIRED")
        try:result=self.evidence_store.integrity_check()
        except Exception as exc:raise ThesisSeedIntegrityFailure("EVIDENCE_STORE_INTEGRITY_REQUIRED") from exc
        if result.get("result")!="PASS":raise ThesisSeedIntegrityFailure("EVIDENCE_STORE_INTEGRITY_REQUIRED")
        output=[]
        for identity in ids:
            row=self.evidence_store.connection.execute("SELECT canonical_json FROM ingestion_records WHERE record_id=?",(identity,)).fetchone()
            if row is None:raise Stage6ThesisSeedError("SUPPORTING_EVIDENCE_NOT_FOUND")
            record=json.loads(row[0])
            if record.get("schema_version")!="STAGE6_EVIDENCE_V2" or record.get("record_kind")!="EVIDENCE" or record.get("evidence_id")!=identity:raise ThesisSeedIntegrityFailure("SUPPORTING_EVIDENCE_KIND_INVALID")
            if parse_utc(record["retrieved_timestamp_utc"],"retrieved")>parse_utc(cutoff,"cutoff"):raise ThesisSeedIntegrityFailure("SUPPORTING_EVIDENCE_AFTER_CUTOFF")
            output.append({"record_type":"STAGE6_EVIDENCE_V2","record_id":identity,"record_hash":record["record_hash"]})
        return output
    def freeze(self,source):
        self._verify_singletons();validate_source(source)
        bindings=self._evidence_bindings(source["supporting_evidence_ids"],source["decision_cutoff"])
        record=build_seed(source,bindings,self.policy_hash,self.contract_hash);validate_seed(record);text=canonical_json(record)
        old=self.connection.execute("SELECT canonical_json FROM thesis_seed_records WHERE source_export_id=?",(source["source_export_id"],)).fetchone()
        if old:
            if old[0]==text:return {"status":"IDEMPOTENT_SUCCESS","initial_thesis_seed":record}
            raise ThesisSeedConflict("THESIS_SEED_EXPORT_CONFLICT")
        source_binding=source["recommendation_binding"]
        dependencies=[*( (x["record_type"],x["record_id"],x["record_hash"]) for x in bindings),("STAGE6_6A_POLICY",POLICY_ID,self.policy_hash),("STAGE6_6A_SEED_CONTRACT",SEED_CONTRACT_VERSION,self.contract_hash)]
        with self.connection:
            self.connection.execute("INSERT INTO thesis_seed_records VALUES(?,?,?,?,?)",(record["seed_record_id"],record["source_export_id"],record["source_export_hash"],record["record_hash"],text))
            self.connection.executemany("INSERT INTO thesis_seed_fills VALUES(?,?,?,?)",[(record["seed_record_id"],i,x["transaction_id"],canonical_json(x)) for i,x in enumerate(record["original_fill_audit_records"])])
            self.connection.execute("INSERT INTO thesis_seed_source_bindings VALUES(?,?,?,?,?)",(record["seed_record_id"],source_binding["record_type"],source_binding["record_id"],source_binding["record_hash"],source_binding["recorded_at_utc"]))
            self.connection.executemany("INSERT INTO thesis_seed_evidence_bindings VALUES(?,?,?,?)",[(record["seed_record_id"],x["record_type"],x["record_id"],x["record_hash"]) for x in bindings])
            self.connection.executemany("INSERT INTO thesis_seed_dependencies VALUES(?,?,?,?)",[(record["seed_record_id"],*x) for x in dependencies])
        return {"status":"CREATED","initial_thesis_seed":record}
    def integrity_check(self):
        self._verify_singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise ThesisSeedIntegrityFailure("THESIS_SEED_SQLITE_INTEGRITY_FAILED")
        if self.connection.execute("PRAGMA foreign_key_check").fetchall():raise ThesisSeedIntegrityFailure("THESIS_SEED_FOREIGN_KEY_FAILED")
        for table in TABLES:
            triggers={x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
            if triggers!={f"protect_{table}_update",f"protect_{table}_delete"}:raise ThesisSeedIntegrityFailure("THESIS_SEED_TRIGGER_MISSING")
        count=0
        for row in self.connection.execute("SELECT * FROM thesis_seed_records"):
            count+=1;record=json.loads(row["canonical_json"]);validate_seed(record)
            if row["canonical_json"]!=canonical_json(record) or tuple(row[k] for k in ("seed_record_id","source_export_id","source_export_hash","record_hash"))!=tuple(record[k] for k in ("seed_record_id","source_export_id","source_export_hash","record_hash")):raise ThesisSeedIntegrityFailure("THESIS_SEED_TYPED_MISMATCH")
            fills=[json.loads(x[0]) for x in self.connection.execute("SELECT canonical_json FROM thesis_seed_fills WHERE seed_record_id=? ORDER BY ordinal",(record["seed_record_id"],))]
            if fills!=record["original_fill_audit_records"]:raise ThesisSeedIntegrityFailure("THESIS_SEED_FILL_REPLAY_MISMATCH")
            source_rows=[tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash,recorded_at_utc FROM thesis_seed_source_bindings WHERE seed_record_id=?",(record["seed_record_id"],))]
            b=record["recommendation_binding"]
            if source_rows!=[(b["record_type"],b["record_id"],b["record_hash"],b["recorded_at_utc"])]:raise ThesisSeedIntegrityFailure("THESIS_SEED_SOURCE_BINDING_MISMATCH")
            evidence=[tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM thesis_seed_evidence_bindings WHERE seed_record_id=? ORDER BY record_id",(record["seed_record_id"],))]
            if evidence!=sorted((x["record_type"],x["record_id"],x["record_hash"]) for x in record["evidence_bindings"]):raise ThesisSeedIntegrityFailure("THESIS_SEED_EVIDENCE_BINDING_MISMATCH")
            verified_evidence=self._evidence_bindings(record["supporting_evidence_ids"],record["decision_cutoff"])
            if verified_evidence!=record["evidence_bindings"]:raise ThesisSeedIntegrityFailure("THESIS_SEED_EVIDENCE_REPLAY_MISMATCH")
            expected=[*( (x["record_type"],x["record_id"],x["record_hash"]) for x in record["evidence_bindings"]),("STAGE6_6A_POLICY",POLICY_ID,self.policy_hash),("STAGE6_6A_SEED_CONTRACT",SEED_CONTRACT_VERSION,self.contract_hash)]
            actual=[tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM thesis_seed_dependencies WHERE seed_record_id=? ORDER BY record_type,record_id",(record["seed_record_id"],))]
            if actual!=sorted(expected):raise ThesisSeedIntegrityFailure("THESIS_SEED_DEPENDENCY_MISMATCH")
            source={k:record[k] for k in ("source_system","source_stage5d5_commit","source_export_id","source_export_hash","source_database_id","source_schema_version","decision_cutoff","recommendation_binding","recommendation_id","ticker","holding_horizon","entry_rationale","known_risks","initial_entry_range","initial_stop","initial_target","invalidation_conditions","supporting_evidence_ids")}|{"fills":record["original_fill_audit_records"]}
            validate_source(source)
            rebuilt=build_seed(source,record["evidence_bindings"],self.policy_hash,self.contract_hash)
            if rebuilt!=record:raise ThesisSeedIntegrityFailure("THESIS_SEED_REPLAY_MISMATCH")
        return {"result":"PASS","seed_records":count,"authority":AUTHORITY}
    def update_record(self,*_,**__):raise Stage6ThesisSeedError("IMMUTABLE_RECORD_UPDATE_PROHIBITED")
