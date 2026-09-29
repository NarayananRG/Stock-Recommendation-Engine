import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_json
from .errors import PortfolioContextConflict, PortfolioContextIntegrityFailure, Stage6PortfolioContextError
from .policy import *
from .portfolio_context_builder import assemble_portfolio_context
from .portfolio_context_validation import validate_portfolio_context_wrapper

TABLES=("portfolio_context_store_meta","portfolio_context_policies","portfolio_context_assembly_contracts","portfolio_context_records","portfolio_context_dependencies","portfolio_context_audits")


class PortfolioContextStore:
    def __init__(self,database:Path,arithmetic_store,correlation_store):
        self.database=Path(database); self.database.parent.mkdir(parents=True,exist_ok=True)
        self.arithmetic_store=arithmetic_store; self.correlation_store=correlation_store
        self.policy,self.policy_json,self.policy_hash=load_policy()
        self.contract,self.contract_json,self.contract_hash=load_assembly_contract()
        new=not self.database.exists(); self.connection=sqlite3.connect(self.database); self.connection.row_factory=sqlite3.Row; self.connection.execute("PRAGMA foreign_keys=ON")
        if new:self._initialize()
        self._verify_singletons()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def close(self):self.connection.close()

    def _initialize(self):
        self.connection.executescript("""
CREATE TABLE portfolio_context_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,payload_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL,portfolio_context_blob TEXT NOT NULL);
CREATE TABLE portfolio_context_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_context_assembly_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_context_records(assembly_record_id TEXT PRIMARY KEY,portfolio_context_id TEXT UNIQUE NOT NULL,arithmetic_record_id TEXT NOT NULL,correlation_context_id TEXT UNIQUE NOT NULL,portfolio_record_hash TEXT UNIQUE NOT NULL,wrapper_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE portfolio_context_dependencies(assembly_record_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(assembly_record_id,record_type,record_id),FOREIGN KEY(assembly_record_id) REFERENCES portfolio_context_records);
CREATE TABLE portfolio_context_audits(assembly_record_id TEXT PRIMARY KEY,canonical_json TEXT NOT NULL,FOREIGN KEY(assembly_record_id) REFERENCES portfolio_context_records);
""")
        self.connection.execute("INSERT INTO portfolio_context_store_meta VALUES(1,?,?,?,?,?,?)",(STORE_SCHEMA_VERSION,PAYLOAD_SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY,PORTFOLIO_CONTEXT_BLOB))
        self.connection.execute("INSERT INTO portfolio_context_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json))
        self.connection.execute("INSERT INTO portfolio_context_assembly_contracts VALUES(?,?,?)",(ASSEMBLY_CONTRACT_VERSION,self.contract_hash,self.contract_json))
        for table in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
        self.connection.commit()

    def _verify_singletons(self):
        meta=self.connection.execute("SELECT * FROM portfolio_context_store_meta").fetchall()
        if len(meta)!=1 or tuple(meta[0])!=(1,STORE_SCHEMA_VERSION,PAYLOAD_SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY,PORTFOLIO_CONTEXT_BLOB):raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_METADATA_MISMATCH")
        policy=self.connection.execute("SELECT * FROM portfolio_context_policies").fetchall()
        if len(policy)!=1 or tuple(policy[0])!=(POLICY_ID,self.policy_hash,self.policy_json):raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_POLICY_MISMATCH")
        contract=self.connection.execute("SELECT * FROM portfolio_context_assembly_contracts").fetchall()
        if len(contract)!=1 or tuple(contract[0])!=(ASSEMBLY_CONTRACT_VERSION,self.contract_hash,self.contract_json):raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CONTRACT_MISMATCH")

    def _record(self,store,table,id_field,identity,error):
        try:result=store.integrity_check()
        except Exception as exc:raise PortfolioContextIntegrityFailure(error) from exc
        if result.get("result")!="PASS":raise PortfolioContextIntegrityFailure(error)
        row=store.connection.execute(f"SELECT canonical_json FROM {table} WHERE {id_field}=?",(identity,)).fetchone()
        if row is None:raise Stage6PortfolioContextError(error.replace("INTEGRITY_REQUIRED","NOT_FOUND"))
        return json.loads(row[0])

    def _dependencies(self,w):
        return [("STAGE6_5B_PORTFOLIO_ARITHMETIC",w["arithmetic_record_id"],w["arithmetic_record_hash"]),("STAGE6_5C_PORTFOLIO_CORRELATION",w["correlation_context_id"],w["correlation_record_hash"]),("STAGE6_5D_POLICY",POLICY_ID,self.policy_hash),("STAGE6_5D_ASSEMBLY_CONTRACT",ASSEMBLY_CONTRACT_VERSION,self.contract_hash)]

    def assemble(self,*,arithmetic_record_id,correlation_context_id):
        self._verify_singletons()
        arithmetic=self._record(self.arithmetic_store,"portfolio_arithmetic_records","arithmetic_record_id",arithmetic_record_id,"PORTFOLIO_CONTEXT_ARITHMETIC_INTEGRITY_REQUIRED")
        correlation=self._record(self.correlation_store,"portfolio_correlation_records","correlation_context_id",correlation_context_id,"PORTFOLIO_CONTEXT_CORRELATION_INTEGRITY_REQUIRED")
        wrapper=assemble_portfolio_context(arithmetic_record=arithmetic,correlation_record=correlation,policy_hash=self.policy_hash,assembly_contract_hash=self.contract_hash); validate_portfolio_context_wrapper(wrapper)
        text=canonical_json(wrapper); old=self.connection.execute("SELECT canonical_json FROM portfolio_context_records WHERE correlation_context_id=?",(correlation_context_id,)).fetchone()
        if old:
            if old[0]==text:return {"status":"IDEMPOTENT_SUCCESS","portfolio_context_assembly":wrapper}
            raise PortfolioContextConflict("PORTFOLIO_CONTEXT_CONFLICT")
        payload=wrapper["portfolio_context"]
        audit={"source_snapshot_id":wrapper["source_snapshot_id"],"source_snapshot_hash":wrapper["source_snapshot_hash"],"subsector_coverage_audit":wrapper["subsector_coverage_audit"],"pending_commitment_audit":wrapper["pending_commitment_audit"]}
        with self.connection:
            self.connection.execute("INSERT INTO portfolio_context_records VALUES(?,?,?,?,?,?,?)",(wrapper["assembly_record_id"],payload["portfolio_context_id"],arithmetic_record_id,correlation_context_id,payload["record_hash"],wrapper["wrapper_hash"],text))
            self.connection.executemany("INSERT INTO portfolio_context_dependencies VALUES(?,?,?,?)",[(wrapper["assembly_record_id"],*d) for d in self._dependencies(wrapper)])
            self.connection.execute("INSERT INTO portfolio_context_audits VALUES(?,?)",(wrapper["assembly_record_id"],canonical_json(audit)))
        return {"status":"CREATED","portfolio_context_assembly":wrapper}

    def integrity_check(self):
        self._verify_singletons()
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_SQLITE_INTEGRITY_FAILED")
        if self.connection.execute("PRAGMA foreign_key_check").fetchall():raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_FOREIGN_KEY_FAILED")
        for table in TABLES:
            triggers={r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
            if triggers!={f"protect_{table}_update",f"protect_{table}_delete"}:raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_TRIGGER_MISSING")
        count=0
        for row in self.connection.execute("SELECT * FROM portfolio_context_records"):
            count+=1; stored=json.loads(row["canonical_json"]); validate_portfolio_context_wrapper(stored)
            arithmetic=self._record(self.arithmetic_store,"portfolio_arithmetic_records","arithmetic_record_id",stored["arithmetic_record_id"],"PORTFOLIO_CONTEXT_ARITHMETIC_INTEGRITY_REQUIRED")
            correlation=self._record(self.correlation_store,"portfolio_correlation_records","correlation_context_id",stored["correlation_context_id"],"PORTFOLIO_CONTEXT_CORRELATION_INTEGRITY_REQUIRED")
            replay=assemble_portfolio_context(arithmetic_record=arithmetic,correlation_record=correlation,policy_hash=self.policy_hash,assembly_contract_hash=self.contract_hash)
            if replay!=stored or row["canonical_json"]!=canonical_json(stored):raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_REPLAY_MISMATCH")
            payload=stored["portfolio_context"]
            if tuple(row[k] for k in ("assembly_record_id","portfolio_context_id","arithmetic_record_id","correlation_context_id","portfolio_record_hash","wrapper_hash"))!=(stored["assembly_record_id"],payload["portfolio_context_id"],stored["arithmetic_record_id"],stored["correlation_context_id"],payload["record_hash"],stored["wrapper_hash"]):raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_TYPED_MISMATCH")
            deps=[(r["record_type"],r["record_id"],r["record_hash"]) for r in self.connection.execute("SELECT * FROM portfolio_context_dependencies WHERE assembly_record_id=? ORDER BY record_type,record_id",(stored["assembly_record_id"],))]
            if deps!=sorted(self._dependencies(stored)):raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_DEPENDENCY_MISMATCH")
            audit={"source_snapshot_id":stored["source_snapshot_id"],"source_snapshot_hash":stored["source_snapshot_hash"],"subsector_coverage_audit":stored["subsector_coverage_audit"],"pending_commitment_audit":stored["pending_commitment_audit"]}
            audit_row=self.connection.execute("SELECT canonical_json FROM portfolio_context_audits WHERE assembly_record_id=?",(stored["assembly_record_id"],)).fetchone()
            if audit_row is None or audit_row[0]!=canonical_json(audit):raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_AUDIT_MISMATCH")
        return {"result":"PASS","portfolio_context_records":count}
