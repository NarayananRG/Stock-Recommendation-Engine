import json, sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_json
from stage6_morning_revalidation_input.policy import PROCESSOR as INPUT_PROCESSOR, POLICY_ID as INPUT_POLICY_ID, EXPECTED_POLICY_HASH as INPUT_POLICY_HASH, CONTRACT_VERSION as INPUT_CONTRACT, EXPECTED_CONTRACT_HASH as INPUT_CONTRACT_HASH
from stage6_morning_revalidation_input.thesis_resolver import resolve_thesis
from .errors import Stage6MorningProposalError, MorningProposalConflict, MorningProposalIntegrityFailure
from .policy import *
from .code_manifest import build_code_manifest, verify_code_manifest
from .morning_revalidation_proposal_builder import build_proposal, support_key
from .morning_revalidation_proposal_validation import validate_inputs, validate_proposal

TABLES=("morning_revalidation_proposal_store_meta","morning_revalidation_proposal_policies","morning_revalidation_proposal_contracts","morning_revalidation_code_manifests","morning_revalidation_proposals","morning_revalidation_invalidation_assessments","morning_revalidation_change_assertions","morning_revalidation_support_bindings","morning_revalidation_dependencies","morning_revalidation_audits")
class MorningRevalidationProposalStore:
 def __init__(self,database:Path,morning_input_store):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.morning_input_store=morning_input_store
  self.policy,self.policy_json,self.policy_hash=load_policy();self.contract,self.contract_json,self.contract_hash=load_contract();self.manifest=build_code_manifest();self.manifest_json=canonical_json(self.manifest);self.code_hash=self.manifest["decision_code_hash"]
  new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._initialize()
  self._singletons()
 def close(self):self.connection.close()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def _initialize(self):
  self.connection.executescript("""
CREATE TABLE morning_revalidation_proposal_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema TEXT NOT NULL,baseline TEXT NOT NULL,processor TEXT NOT NULL,authority TEXT NOT NULL,input_schema TEXT NOT NULL,input_processor TEXT NOT NULL,input_policy TEXT NOT NULL,input_policy_hash TEXT NOT NULL,input_contract TEXT NOT NULL,input_contract_hash TEXT NOT NULL);
CREATE TABLE morning_revalidation_proposal_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE morning_revalidation_proposal_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE morning_revalidation_code_manifests(manifest_version TEXT PRIMARY KEY,decision_code_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE morning_revalidation_proposals(proposal_id TEXT PRIMARY KEY,morning_snapshot_id TEXT UNIQUE NOT NULL,decision TEXT NOT NULL,reason_code TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE morning_revalidation_invalidation_assessments(proposal_id TEXT NOT NULL,condition_index INTEGER NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(proposal_id,condition_index),FOREIGN KEY(proposal_id) REFERENCES morning_revalidation_proposals);
CREATE TABLE morning_revalidation_change_assertions(proposal_id TEXT NOT NULL,assertion_ordinal INTEGER NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(proposal_id,assertion_ordinal),FOREIGN KEY(proposal_id) REFERENCES morning_revalidation_proposals);
CREATE TABLE morning_revalidation_support_bindings(proposal_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(proposal_id,record_type,record_id,record_hash),FOREIGN KEY(proposal_id) REFERENCES morning_revalidation_proposals);
CREATE TABLE morning_revalidation_dependencies(proposal_id TEXT NOT NULL,dependency_ordinal INTEGER NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(proposal_id,dependency_ordinal),FOREIGN KEY(proposal_id) REFERENCES morning_revalidation_proposals);
CREATE TABLE morning_revalidation_audits(proposal_id TEXT PRIMARY KEY,canonical_json TEXT NOT NULL,FOREIGN KEY(proposal_id) REFERENCES morning_revalidation_proposals);
""")
  meta=(1,STORE_SCHEMA,BASELINE,PROCESSOR,AUTHORITY,INPUT_SCHEMA,INPUT_PROCESSOR,INPUT_POLICY_ID,INPUT_POLICY_HASH,INPUT_CONTRACT,INPUT_CONTRACT_HASH)
  self.connection.execute("INSERT INTO morning_revalidation_proposal_store_meta VALUES(?,?,?,?,?,?,?,?,?,?,?)",meta);self.connection.execute("INSERT INTO morning_revalidation_proposal_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json));self.connection.execute("INSERT INTO morning_revalidation_proposal_contracts VALUES(?,?,?)",(CONTRACT_VERSION,self.contract_hash,self.contract_json));self.connection.execute("INSERT INTO morning_revalidation_code_manifests VALUES(?,?,?)",(MANIFEST_VERSION,self.code_hash,self.manifest_json))
  for table in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _singletons(self):
  meta=self.connection.execute("SELECT * FROM morning_revalidation_proposal_store_meta").fetchall();expected=(1,STORE_SCHEMA,BASELINE,PROCESSOR,AUTHORITY,INPUT_SCHEMA,INPUT_PROCESSOR,INPUT_POLICY_ID,INPUT_POLICY_HASH,INPUT_CONTRACT,INPUT_CONTRACT_HASH)
  if len(meta)!=1 or tuple(meta[0])!=expected:raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_METADATA_MISMATCH")
  p=self.connection.execute("SELECT * FROM morning_revalidation_proposal_policies").fetchall();c=self.connection.execute("SELECT * FROM morning_revalidation_proposal_contracts").fetchall();m=self.connection.execute("SELECT * FROM morning_revalidation_code_manifests").fetchall()
  if len(p)!=1 or tuple(p[0])!=(POLICY_ID,self.policy_hash,self.policy_json):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_POLICY_MISMATCH")
  if len(c)!=1 or tuple(c[0])!=(CONTRACT_VERSION,self.contract_hash,self.contract_json):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_CONTRACT_MISMATCH")
  if len(m)!=1 or tuple(m[0])!=(MANIFEST_VERSION,self.code_hash,self.manifest_json):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_MANIFEST_MISMATCH")
  verify_code_manifest(json.loads(m[0][2]))
 def _load(self,morning_snapshot_id):
  try:up=self.morning_input_store.integrity_check()
  except Exception as exc:raise MorningProposalIntegrityFailure("STAGE6_7A_INTEGRITY_REQUIRED") from exc
  if up.get("result")!="PASS":raise MorningProposalIntegrityFailure("STAGE6_7A_INTEGRITY_REQUIRED")
  row=self.morning_input_store.connection.execute("SELECT canonical_json FROM morning_revalidation_input_records WHERE morning_snapshot_id=?",(morning_snapshot_id,)).fetchone()
  if row is None:raise Stage6MorningProposalError("MORNING_SNAPSHOT_NOT_FOUND")
  snapshot=json.loads(row[0])
  if snapshot.get("schema_version")!=INPUT_SCHEMA or snapshot.get("processor_version")!=INPUT_PROCESSOR or snapshot.get("policy_id")!=INPUT_POLICY_ID or snapshot.get("policy_hash")!=INPUT_POLICY_HASH or snapshot.get("contract_version")!=INPUT_CONTRACT or snapshot.get("contract_hash")!=INPUT_CONTRACT_HASH or snapshot.get("authority")!=AUTHORITY:raise MorningProposalIntegrityFailure("MORNING_SNAPSHOT_IDENTITY_INVALID")
  required={"pit_validation_status":"PASS","pending_entry_status":"FROZEN","current_thesis_status":"FROZEN","stage5d_mutation_status":"PROHIBITED","entry_revalidation_status":"NOT_EVALUATED","entry_proposal_status":"NOT_MATERIALIZED"}
  if any(snapshot.get(k)!=v for k,v in required.items()):raise MorningProposalIntegrityFailure("MORNING_SNAPSHOT_STATE_INVALID")
  source=snapshot["current_thesis_source"];source_id=snapshot["current_version_record_id"]
  _,thesis=resolve_thesis(source,source_id,self.morning_input_store.thesis_store,self.morning_input_store.stage6e_store,self.morning_input_store.recursive_store)
  portfolio=self.morning_input_store._portfolio(snapshot["portfolio_context_binding"]["record_id"]);pending=self.morning_input_store._selected(portfolio,snapshot["recommendation_id"],snapshot["ticker"])
  if (pending.get("thesis_id"),thesis.get("thesis_id"),thesis.get("recommendation_id"),thesis.get("ticker"))!=(snapshot["thesis_id"],snapshot["thesis_id"],snapshot["recommendation_id"],snapshot["ticker"]):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_CROSS_BINDING_INVALID")
  universe={(INPUT_SCHEMA,snapshot["morning_snapshot_id"],snapshot["record_hash"]),*(support_key(x) for x in snapshot["direct_input_bindings"])}
  return snapshot,thesis,portfolio,universe
 def propose(self,*,morning_snapshot_id,invalidation_assessments,morning_change_assertions):
  self._singletons();snapshot,thesis,portfolio,universe=self._load(morning_snapshot_id);ia,ca=validate_inputs(thesis,invalidation_assessments,morning_change_assertions,universe)
  record=build_proposal(snapshot=snapshot,thesis=thesis,portfolio=portfolio,invalidation_assessments=ia,change_assertions=ca,policy_hash=self.policy_hash,contract_hash=self.contract_hash,manifest=self.manifest);validate_proposal(record,snapshot,thesis,portfolio,ia,ca,self.policy_hash,self.contract_hash,self.manifest)
  old=self.connection.execute("SELECT canonical_json FROM morning_revalidation_proposals WHERE morning_snapshot_id=?",(morning_snapshot_id,)).fetchone()
  if old:
   if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","proposal":record}
   raise MorningProposalConflict("MORNING_REVALIDATION_PROPOSAL_CONFLICT")
  pid=record["proposal_id"];audit={"proposal_id":pid,"morning_snapshot_id":morning_snapshot_id,"entry_revalidation_status":"EVALUATED","proposal_status":"SHADOW_PROPOSAL_ONLY","execution_status":"NOT_AUTHORIZED","stage5d_mutation_status":"PROHIBITED"}
  with self.connection:
   self.connection.execute("INSERT INTO morning_revalidation_proposals VALUES(?,?,?,?,?,?)",(pid,morning_snapshot_id,record["proposal_decision"],record["proposal_reason_code"],record["record_hash"],canonical_json(record)))
   self.connection.executemany("INSERT INTO morning_revalidation_invalidation_assessments VALUES(?,?,?)",[(pid,x["condition_index"],canonical_json(x)) for x in ia]);self.connection.executemany("INSERT INTO morning_revalidation_change_assertions VALUES(?,?,?)",[(pid,i,canonical_json(x)) for i,x in enumerate(ca)]);self.connection.executemany("INSERT INTO morning_revalidation_support_bindings VALUES(?,?,?,?)",[(pid,*support_key(x)) for x in record["support_bindings"]]);self.connection.executemany("INSERT INTO morning_revalidation_dependencies VALUES(?,?,?,?,?)",[(pid,i,x["record_type"],x["record_id"],x["record_hash"]) for i,x in enumerate(record["direct_dependencies"])]);self.connection.execute("INSERT INTO morning_revalidation_audits VALUES(?,?)",(pid,canonical_json(audit)))
  return {"status":"CREATED","proposal":record}
 def integrity_check(self):
  self._singletons()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_SQLITE_INVALID")
  for table in TABLES:
   names={x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
   if names!={f"protect_{table}_update",f"protect_{table}_delete"}:raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_TRIGGER_MISSING")
  for row in self.connection.execute("SELECT * FROM morning_revalidation_proposals"):
   record=json.loads(row["canonical_json"]);snapshot,thesis,portfolio,universe=self._load(record["morning_snapshot_binding"]["record_id"]);ia=[json.loads(x[0]) for x in self.connection.execute("SELECT canonical_json FROM morning_revalidation_invalidation_assessments WHERE proposal_id=? ORDER BY condition_index",(record["proposal_id"],))];ca=[json.loads(x[0]) for x in self.connection.execute("SELECT canonical_json FROM morning_revalidation_change_assertions WHERE proposal_id=? ORDER BY assertion_ordinal",(record["proposal_id"],))];validate_inputs(thesis,ia,ca,universe);validate_proposal(record,snapshot,thesis,portfolio,ia,ca,self.policy_hash,self.contract_hash,self.manifest)
   if (row["proposal_id"],row["morning_snapshot_id"],row["decision"],row["reason_code"],row["record_hash"])!=(record["proposal_id"],record["morning_snapshot_binding"]["record_id"],record["proposal_decision"],record["proposal_reason_code"],record["record_hash"]):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_ROW_MISMATCH")
   supports=sorted(tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM morning_revalidation_support_bindings WHERE proposal_id=?",(record["proposal_id"],)));expected=sorted(support_key(x) for x in record["support_bindings"]);deps=[tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM morning_revalidation_dependencies WHERE proposal_id=? ORDER BY dependency_ordinal",(record["proposal_id"],))];wanted=[support_key(x) for x in record["direct_dependencies"]];audit={"proposal_id":record["proposal_id"],"morning_snapshot_id":snapshot["morning_snapshot_id"],"entry_revalidation_status":"EVALUATED","proposal_status":"SHADOW_PROPOSAL_ONLY","execution_status":"NOT_AUTHORIZED","stage5d_mutation_status":"PROHIBITED"};ar=self.connection.execute("SELECT canonical_json FROM morning_revalidation_audits WHERE proposal_id=?",(record["proposal_id"],)).fetchone()
   if supports!=expected or deps!=wanted or len(deps)!=6 or ar is None or ar[0]!=canonical_json(audit):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_CHILD_MISMATCH")
  return {"result":"PASS","proposals":self.connection.execute("SELECT count(*) FROM morning_revalidation_proposals").fetchone()[0],"authority":AUTHORITY}
