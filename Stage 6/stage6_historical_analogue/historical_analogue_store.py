import json,sqlite3
from pathlib import Path
from stage6_analogue_features.feature_validation import validate_feature_snapshot
from stage6_analogue_outcomes.outcome_validation import validate_outcome_record
from stage6_analogue_selection.selection_validation import validate_selection_record
from stage6_ingestion.canonical import canonical_json
from .errors import HistoricalAnalogueConflict,HistoricalAnalogueIntegrityFailure,Stage6HistoricalAnalogueError
from .historical_analogue_builder import build_historical_analogue
from .historical_analogue_validation import validate_wrapper
from .policy import *
TABLES=("historical_analogue_store_meta","historical_analogue_policies","analogue_aggregation_contracts","historical_analogue_records","historical_analogue_coverage","historical_analogue_dependencies")
class HistoricalAnalogueStore:
 def __init__(self,database:Path,selection_store,outcome_store,feature_store):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.selection_store=selection_store;self.outcome_store=outcome_store;self.feature_store=feature_store;self.policy,self.policy_json,self.policy_hash=load_policy();self.aggregation_contract,self.aggregation_contract_json,self.aggregation_contract_hash=load_aggregation_contract();new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._singletons()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE historical_analogue_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,payload_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,selection_engine_commit TEXT NOT NULL,outcome_attachment_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL,historical_contract_blob TEXT NOT NULL);CREATE TABLE historical_analogue_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE analogue_aggregation_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE historical_analogue_records(wrapper_id TEXT PRIMARY KEY,logical_key TEXT UNIQUE NOT NULL,selection_record_id TEXT NOT NULL,outcome_attachment_set_id TEXT NOT NULL,target_feature_snapshot_id TEXT NOT NULL,historical_analogue_id TEXT NOT NULL UNIQUE,historical_analogue_record_hash TEXT NOT NULL UNIQUE,wrapper_hash TEXT NOT NULL UNIQUE,record_hash TEXT NOT NULL UNIQUE,canonical_json TEXT NOT NULL);CREATE TABLE historical_analogue_coverage(wrapper_id TEXT PRIMARY KEY,canonical_json TEXT NOT NULL,FOREIGN KEY(wrapper_id) REFERENCES historical_analogue_records);CREATE TABLE historical_analogue_dependencies(wrapper_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(wrapper_id,record_type,record_id),FOREIGN KEY(wrapper_id) REFERENCES historical_analogue_records);""")
  self.connection.execute("INSERT INTO historical_analogue_store_meta VALUES(1,?,?,?,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,SELECTION_ENGINE_COMMIT,OUTCOME_ATTACHMENT_COMMIT,PROCESSOR_VERSION,AUTHORITY,HISTORICAL_BLOB));self.connection.execute("INSERT INTO historical_analogue_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json));self.connection.execute("INSERT INTO analogue_aggregation_contracts VALUES(?,?,?)",(AGGREGATION_CONTRACT_VERSION,self.aggregation_contract_hash,self.aggregation_contract_json))
  for table in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
  self.connection.commit()
 def _singletons(self):
  meta=self.connection.execute("SELECT * FROM historical_analogue_store_meta").fetchall();expected=(1,STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,SELECTION_ENGINE_COMMIT,OUTCOME_ATTACHMENT_COMMIT,PROCESSOR_VERSION,AUTHORITY,HISTORICAL_BLOB)
  if len(meta)!=1 or tuple(meta[0])!=expected:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_METADATA_MISMATCH")
  p=self.connection.execute("SELECT * FROM historical_analogue_policies").fetchall();a=self.connection.execute("SELECT * FROM analogue_aggregation_contracts").fetchall()
  if len(p)!=1 or tuple(p[0])!=(POLICY_ID,EXPECTED_POLICY_HASH_V1,self.policy_json):raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_POLICY_MISMATCH")
  if len(a)!=1 or tuple(a[0])!=(AGGREGATION_CONTRACT_VERSION,EXPECTED_AGGREGATION_CONTRACT_HASH_V1,self.aggregation_contract_json):raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_AGGREGATION_CONTRACT_MISMATCH")
 def _selection(self,identity):
  if self.selection_store.integrity_check()["result"]!="PASS":raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_SELECTION_INTEGRITY_REQUIRED")
  row=self.selection_store.connection.execute("SELECT canonical_json FROM analogue_selection_records WHERE selection_record_id=?",(identity,)).fetchone()
  if row is None:raise Stage6HistoricalAnalogueError("HISTORICAL_ANALOGUE_SELECTION_NOT_FOUND")
  value=json.loads(row[0]);validate_selection_record(value)
  expected=("STAGE6_ANALOGUE_SELECTION_V1","STAGE6_4C_ANALOGUE_SELECTOR_V1","S6ANSELPOL_STAGE6_4C_V1","36dfffc457342314e0907e31bebb7e54bd21747134dbaded7d34b822e6bcc9b2","STAGE6_ANALOGUE_COMPARISON_CONTRACT_V1","115ae49b1ac8cc005ca1bdb876576600603d593ec2e1ed09c2fee4c6d79b1401","STAGE6_MIXED_DISTANCE_V1",AUTHORITY)
  if tuple(value.get(k) for k in ("schema_version","processor_version","policy_id","policy_hash","comparison_contract_version","comparison_contract_hash","similarity_metric","authority"))!=expected:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_SELECTION_IDENTITY_INVALID")
  return value
 def _outcome(self,identity):
  if self.outcome_store.integrity_check()["result"]!="PASS":raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_OUTCOME_INTEGRITY_REQUIRED")
  row=self.outcome_store.connection.execute("SELECT canonical_json FROM analogue_outcome_attachment_sets WHERE attachment_set_id=?",(identity,)).fetchone()
  if row is None:raise Stage6HistoricalAnalogueError("HISTORICAL_ANALOGUE_OUTCOME_NOT_FOUND")
  value=json.loads(row[0]);validate_outcome_record(value);expected=("STAGE6_ANALOGUE_OUTCOME_ATTACHMENT_V1","STAGE6_4D_ANALOGUE_OUTCOME_ATTACHER_V1","S6ANOUTPOL_STAGE6_4D_V1","3aa6bc70bfd1a8b29287cd609282d6a5d00c9839aeebaaa09d5761b8ce1d0a24","STAGE6_ANALOGUE_OUTCOME_DEFINITION_V1","2535f09dacd8d67215121d4a60a925885ab53ba8e771e8df355c4c14b12ea85a",SELECTION_ENGINE_COMMIT,AUTHORITY)
  if tuple(value.get(k) for k in ("schema_version","processor_version","policy_id","policy_hash","outcome_definition_version","outcome_definition_hash","selection_engine_commit","authority"))!=expected:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_OUTCOME_IDENTITY_INVALID")
  return value
 def _target(self,identity):
  if self.feature_store.integrity_check()["result"]!="PASS":raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_FEATURE_INTEGRITY_REQUIRED")
  row=self.feature_store.connection.execute("SELECT canonical_json FROM analogue_feature_snapshots WHERE feature_snapshot_id=?",(identity,)).fetchone()
  if row is None:raise Stage6HistoricalAnalogueError("HISTORICAL_ANALOGUE_TARGET_NOT_FOUND")
  value=json.loads(row[0]);validate_feature_snapshot(value);expected=("STAGE6_ANALOGUE_FEATURE_SNAPSHOT_V1","STAGE6_4B_ANALOGUE_FEATURE_FREEZER_V1","S6ANFEATPOL_STAGE6_4B_V1","ee9b8a5cfb5500d88e9002ffd984d8e37cc690496201fe7913e164f188281f16","STAGE6_ANALOGUE_FEATURE_CONTRACT_V1","4a263fb50e4db4eb44e2e474087cd0cd1e08a68b02298d019ad9d02e8f45484f",AUTHORITY)
  if tuple(value.get(k) for k in ("schema_version","processor_version","policy_id","policy_hash","feature_contract_version","feature_contract_hash","authority"))!=expected:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_TARGET_IDENTITY_INVALID")
  return value
 def _deps(self,r):return [("STAGE6_4C_ANALOGUE_SELECTION",r["selection_record_id"],r["selection_record_hash"]),("STAGE6_4D_OUTCOME_ATTACHMENT",r["outcome_attachment_set_id"],r["outcome_attachment_set_hash"]),("STAGE6_4B_TARGET_ANALOGUE_FEATURE",r["target_feature_snapshot_id"],r["target_feature_snapshot_hash"]),("STAGE6_4E_POLICY",POLICY_ID,self.policy_hash),("STAGE6_4E_AGGREGATION_CONTRACT",AGGREGATION_CONTRACT_VERSION,self.aggregation_contract_hash)]
 def materialize(self,*,selection_record_id,outcome_attachment_set_id):
  self._singletons();selection=self._selection(selection_record_id);outcome=self._outcome(outcome_attachment_set_id);target=self._target(selection["target_feature_snapshot_id"]);record=build_historical_analogue(selection=selection,outcome=outcome,target=target,policy=self.policy,policy_hash=self.policy_hash,aggregation_contract_hash=self.aggregation_contract_hash);validate_wrapper(record);logical="S6HANLOG_"+canonical_json({"selection":selection_record_id,"outcome":outcome_attachment_set_id,"target":target["feature_snapshot_id"]})
  old=self.connection.execute("SELECT canonical_json FROM historical_analogue_records WHERE logical_key=?",(logical,)).fetchone()
  if old:
   if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","historical_analogue":record}
   raise HistoricalAnalogueConflict("HISTORICAL_ANALOGUE_CONFLICT")
  p=record["historical_analogue_payload"]
  with self.connection:
   self.connection.execute("INSERT INTO historical_analogue_records VALUES(?,?,?,?,?,?,?,?,?,?)",(record["wrapper_id"],logical,record["selection_record_id"],record["outcome_attachment_set_id"],record["target_feature_snapshot_id"],p["historical_analogue_id"],p["record_hash"],record["wrapper_hash"],record["record_hash"],canonical_json(record)));self.connection.execute("INSERT INTO historical_analogue_coverage VALUES(?,?)",(record["wrapper_id"],canonical_json(record["coverage_audit"])));self.connection.executemany("INSERT INTO historical_analogue_dependencies VALUES(?,?,?,?)",[(record["wrapper_id"],*d) for d in self._deps(record)])
  return {"status":"CREATED","historical_analogue":record}
 def integrity_check(self):
  self._singletons()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_SQLITE_INTEGRITY_FAILED")
  for table in TABLES:
   if {x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}!={f"protect_{table}_update",f"protect_{table}_delete"}:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM historical_analogue_records"):
   count+=1;stored=json.loads(row["canonical_json"]);validate_wrapper(stored);selection=self._selection(stored["selection_record_id"]);outcome=self._outcome(stored["outcome_attachment_set_id"]);target=self._target(stored["target_feature_snapshot_id"]);replay=build_historical_analogue(selection=selection,outcome=outcome,target=target,policy=self.policy,policy_hash=self.policy_hash,aggregation_contract_hash=self.aggregation_contract_hash)
   if replay!=stored or row["canonical_json"]!=canonical_json(stored):raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_REPLAY_MISMATCH")
   p=stored["historical_analogue_payload"];typed=tuple(row[k] for k in ("wrapper_id","selection_record_id","outcome_attachment_set_id","target_feature_snapshot_id","historical_analogue_id","historical_analogue_record_hash","wrapper_hash","record_hash"));wanted=(stored["wrapper_id"],stored["selection_record_id"],stored["outcome_attachment_set_id"],stored["target_feature_snapshot_id"],p["historical_analogue_id"],p["record_hash"],stored["wrapper_hash"],stored["record_hash"])
   if typed!=wanted:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_TYPED_MISMATCH")
   coverage=self.connection.execute("SELECT canonical_json FROM historical_analogue_coverage WHERE wrapper_id=?",(stored["wrapper_id"],)).fetchone()
   if coverage is None or json.loads(coverage[0])!=stored["coverage_audit"]:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_COVERAGE_MISMATCH")
   deps={(x["record_type"],x["record_id"]):x["record_hash"] for x in self.connection.execute("SELECT * FROM historical_analogue_dependencies WHERE wrapper_id=?",(stored["wrapper_id"],))};expected={(a,b):c for a,b,c in self._deps(stored)}
   if deps!=expected:raise HistoricalAnalogueIntegrityFailure("HISTORICAL_ANALOGUE_DEPENDENCY_MISMATCH")
  return {"result":"PASS","historical_analogue_records":count,"authority":AUTHORITY,"policy_hash":self.policy_hash,"aggregation_contract_hash":self.aggregation_contract_hash}
