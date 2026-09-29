import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_json
from stage6_thesis_seed.thesis_seed_validation import validate_seed
from .errors import Stage6TradeThesisError,TradeThesisConflict,TradeThesisIntegrityFailure
from .policy import *
from .trade_thesis_builder import build_materialization_record
from .trade_thesis_validation import validate_materialization_record

TABLES=("trade_thesis_store_meta","trade_thesis_policies","trade_thesis_contracts","trade_thesis_records","trade_thesis_dependencies","trade_thesis_audits")

class TradeThesisStore:
    def __init__(self,database:Path,seed_store):
        self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.seed_store=seed_store
        self.policy,self.policy_json,self.policy_hash=load_policy();self.contract,self.contract_json,self.contract_hash=load_materialization_contract()
        new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
        if new:self._initialize()
        self._verify_singletons()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def close(self):self.connection.close()
    def _initialize(self):
        self.connection.executescript("""
CREATE TABLE trade_thesis_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL,trade_thesis_blob TEXT NOT NULL);
CREATE TABLE trade_thesis_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE trade_thesis_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE trade_thesis_records(materialization_record_id TEXT PRIMARY KEY,thesis_id TEXT UNIQUE NOT NULL,seed_record_id TEXT UNIQUE NOT NULL,thesis_hash TEXT UNIQUE NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE trade_thesis_dependencies(materialization_record_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(materialization_record_id,record_type,record_id),FOREIGN KEY(materialization_record_id) REFERENCES trade_thesis_records);
CREATE TABLE trade_thesis_audits(materialization_record_id TEXT PRIMARY KEY,version INTEGER NOT NULL,change_type TEXT NOT NULL,decision_cutoff TEXT NOT NULL,canonical_json TEXT NOT NULL,FOREIGN KEY(materialization_record_id) REFERENCES trade_thesis_records);
""")
        self.connection.execute("INSERT INTO trade_thesis_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY,TRADE_THESIS_BLOB))
        self.connection.execute("INSERT INTO trade_thesis_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json));self.connection.execute("INSERT INTO trade_thesis_contracts VALUES(?,?,?)",(MATERIALIZATION_CONTRACT_VERSION,self.contract_hash,self.contract_json))
        for table in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
        self.connection.commit()
    def _verify_singletons(self):
        rows=self.connection.execute("SELECT * FROM trade_thesis_store_meta").fetchall()
        if len(rows)!=1 or tuple(rows[0])!=(1,STORE_SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY,TRADE_THESIS_BLOB):raise TradeThesisIntegrityFailure("TRADE_THESIS_METADATA_MISMATCH")
        rows=self.connection.execute("SELECT * FROM trade_thesis_policies").fetchall()
        if len(rows)!=1 or tuple(rows[0])!=(POLICY_ID,self.policy_hash,self.policy_json):raise TradeThesisIntegrityFailure("TRADE_THESIS_POLICY_MISMATCH")
        rows=self.connection.execute("SELECT * FROM trade_thesis_contracts").fetchall()
        if len(rows)!=1 or tuple(rows[0])!=(MATERIALIZATION_CONTRACT_VERSION,self.contract_hash,self.contract_json):raise TradeThesisIntegrityFailure("TRADE_THESIS_CONTRACT_MISMATCH")
    def _seed(self,identity):
        try:result=self.seed_store.integrity_check()
        except Exception as exc:raise TradeThesisIntegrityFailure("THESIS_SEED_STORE_INTEGRITY_REQUIRED") from exc
        if result.get("result")!="PASS":raise TradeThesisIntegrityFailure("THESIS_SEED_STORE_INTEGRITY_REQUIRED")
        row=self.seed_store.connection.execute("SELECT canonical_json FROM thesis_seed_records WHERE seed_record_id=?",(identity,)).fetchone()
        if row is None:raise Stage6TradeThesisError("THESIS_SEED_NOT_FOUND")
        seed=json.loads(row[0]);validate_seed(seed);return seed
    def materialize(self,seed_record_id):
        self._verify_singletons();seed=self._seed(seed_record_id);record=build_materialization_record(seed,self.policy_hash,self.contract_hash);validate_materialization_record(record,seed);text=canonical_json(record)
        old=self.connection.execute("SELECT canonical_json FROM trade_thesis_records WHERE seed_record_id=?",(seed_record_id,)).fetchone()
        if old:
            if old[0]==text:return {"status":"IDEMPOTENT_SUCCESS","materialization_record":record,"trade_thesis":record["trade_thesis"]}
            raise TradeThesisConflict("TRADE_THESIS_SEED_CONFLICT")
        deps=[(SEED_SCHEMA_VERSION,seed["seed_record_id"],seed["record_hash"]),("STAGE6_6B_POLICY",POLICY_ID,self.policy_hash),("STAGE6_6B_MATERIALIZATION_CONTRACT",MATERIALIZATION_CONTRACT_VERSION,self.contract_hash)]
        audit=record["trade_thesis"]["change_history"][0]
        with self.connection:
            self.connection.execute("INSERT INTO trade_thesis_records VALUES(?,?,?,?,?,?)",(record["materialization_record_id"],record["trade_thesis"]["thesis_id"],seed_record_id,record["trade_thesis"]["record_hash"],record["record_hash"],text))
            self.connection.executemany("INSERT INTO trade_thesis_dependencies VALUES(?,?,?,?)",[(record["materialization_record_id"],*x) for x in deps])
            self.connection.execute("INSERT INTO trade_thesis_audits VALUES(?,?,?,?,?)",(record["materialization_record_id"],1,audit["change_type"],audit["decision_cutoff"],canonical_json(audit)))
        return {"status":"CREATED","materialization_record":record,"trade_thesis":record["trade_thesis"]}
    def integrity_check(self):
        self._verify_singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise TradeThesisIntegrityFailure("TRADE_THESIS_SQLITE_INTEGRITY_FAILED")
        if self.connection.execute("PRAGMA foreign_key_check").fetchall():raise TradeThesisIntegrityFailure("TRADE_THESIS_FOREIGN_KEY_FAILED")
        for table in TABLES:
            if {x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}!={f"protect_{table}_update",f"protect_{table}_delete"}:raise TradeThesisIntegrityFailure("TRADE_THESIS_TRIGGER_MISSING")
        count=0
        for row in self.connection.execute("SELECT * FROM trade_thesis_records"):
            count+=1;record=json.loads(row["canonical_json"]);seed=self._seed(row["seed_record_id"]);validate_materialization_record(record,seed)
            if row["canonical_json"]!=canonical_json(record) or (row["materialization_record_id"],row["thesis_id"],row["thesis_hash"],row["record_hash"])!=(record["materialization_record_id"],record["trade_thesis"]["thesis_id"],record["trade_thesis"]["record_hash"],record["record_hash"]):raise TradeThesisIntegrityFailure("TRADE_THESIS_TYPED_MISMATCH")
            expected=sorted([(SEED_SCHEMA_VERSION,seed["seed_record_id"],seed["record_hash"]),("STAGE6_6B_POLICY",POLICY_ID,self.policy_hash),("STAGE6_6B_MATERIALIZATION_CONTRACT",MATERIALIZATION_CONTRACT_VERSION,self.contract_hash)])
            actual=sorted(tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM trade_thesis_dependencies WHERE materialization_record_id=?",(record["materialization_record_id"],)))
            if actual!=expected:raise TradeThesisIntegrityFailure("TRADE_THESIS_DEPENDENCY_MISMATCH")
            audit=self.connection.execute("SELECT canonical_json FROM trade_thesis_audits WHERE materialization_record_id=?",(record["materialization_record_id"],)).fetchone()
            if audit is None or json.loads(audit[0])!=record["trade_thesis"]["change_history"][0]:raise TradeThesisIntegrityFailure("TRADE_THESIS_AUDIT_MISMATCH")
            if build_materialization_record(seed,self.policy_hash,self.contract_hash)!=record:raise TradeThesisIntegrityFailure("TRADE_THESIS_REPLAY_MISMATCH")
        return {"result":"PASS","trade_theses":count,"authority":AUTHORITY}
    def update_record(self,*_,**__):raise Stage6TradeThesisError("IMMUTABLE_RECORD_UPDATE_PROHIBITED")
