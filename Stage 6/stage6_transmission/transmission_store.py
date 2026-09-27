import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_json
from stage6_exposure_binding import BindingStore
from .errors import *
from .policy import AUTHORITY,EXPECTED_POLICY_HASH_V1,POLICY_ID,PROCESSOR_VERSION,load_policy
from .transmission_builder import SCHEMA_VERSION,build_transmission
from .transmission_validation import validate_transmission
STORE_SCHEMA_VERSION="STAGE6_3C_TRANSMISSION_STORE_V1"
class TransmissionStore:
 def __init__(self,database:Path,binding_store:BindingStore):
  self.database=Path(database);self.binding_store=binding_store;self.policy,self.policy_json,self.policy_hash=load_policy()
  if self.policy_hash!=EXPECTED_POLICY_HASH_V1:raise TransmissionIntegrityFailure("TRANSMISSION_EXPECTED_V1_POLICY_HASH_MISMATCH")
  new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._meta();self._policy()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE transmission_store_meta(singleton INTEGER PRIMARY KEY,store_schema_version TEXT,binding_baseline_commit TEXT,transmission_schema_version TEXT,processor_version TEXT,authority TEXT);CREATE TABLE transmission_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT,canonical_json TEXT);CREATE TABLE transmission_records(transmission_id TEXT PRIMARY KEY,binding_id TEXT,binding_hash TEXT,evaluation_cutoff_timestamp TEXT,record_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE transmission_assertion_evaluations(transmission_id TEXT,assertion_hash TEXT,exposure_type TEXT,type_match_status TEXT,canonical_json TEXT,PRIMARY KEY(transmission_id,assertion_hash),FOREIGN KEY(transmission_id) REFERENCES transmission_records);CREATE TABLE transmission_paths(transmission_id TEXT,path_id TEXT,canonical_json TEXT,PRIMARY KEY(transmission_id,path_id),FOREIGN KEY(transmission_id) REFERENCES transmission_records);CREATE TABLE transmission_dependencies(transmission_id TEXT,record_type TEXT,record_id TEXT,record_hash TEXT,PRIMARY KEY(transmission_id,record_type,record_id),FOREIGN KEY(transmission_id) REFERENCES transmission_records);""")
  self.connection.execute("INSERT INTO transmission_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,"d05495b250ff9abefd912b763780ec5f4f6003cb",SCHEMA_VERSION,PROCESSOR_VERSION,AUTHORITY));self.connection.execute("INSERT INTO transmission_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json))
  for t in ("transmission_store_meta","transmission_policies","transmission_records","transmission_assertion_evaluations","transmission_paths","transmission_dependencies"):self.connection.executescript(f"CREATE TRIGGER protect_{t}_update BEFORE UPDATE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{t}_delete BEFORE DELETE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _meta(self):
  r=self.connection.execute("SELECT * FROM transmission_store_meta").fetchone()
  if r is None or tuple(r)!=(1,STORE_SCHEMA_VERSION,"d05495b250ff9abefd912b763780ec5f4f6003cb",SCHEMA_VERSION,PROCESSOR_VERSION,AUTHORITY):raise TransmissionIntegrityFailure("TRANSMISSION_METADATA_MISMATCH")
 def _policy(self):
  r=self.connection.execute("SELECT * FROM transmission_policies WHERE policy_id=?",(POLICY_ID,)).fetchone()
  if self.policy_hash!=EXPECTED_POLICY_HASH_V1 or r is None or (r["policy_hash"],r["canonical_json"])!=(EXPECTED_POLICY_HASH_V1,self.policy_json):raise TransmissionIntegrityFailure("TRANSMISSION_POLICY_SNAPSHOT_MISMATCH")
 def _binding(self,identity):
  r=self.binding_store.connection.execute("SELECT canonical_json FROM binding_records WHERE binding_id=?",(identity,)).fetchone()
  if r is None:raise Stage6TransmissionError("BINDING_NOT_FOUND")
  b=json.loads(r[0]);
  if b["binding_basis"]!="EXPLICIT_ASSERTION_SELECTION" or b["authority"]!="SHADOW_ONLY" or any(b[k]!="NOT_EVALUATED" for k in ("semantic_compatibility_status","directional_effect_status","causal_effect_status")):raise Stage6TransmissionError("BINDING_SAFETY_PRECONDITION_FAILED")
  return b
 def evaluate_binding(self,*,binding_id):
  self._meta();self._policy()
  if self.binding_store.integrity_check()["result"]!="PASS":raise TransmissionIntegrityFailure("BINDING_STORE_FAILED")
  b=self._binding(binding_id);x=build_transmission(b,self.policy,self.policy_hash);validate_transmission(x,b,self.policy,self.policy_hash);old=self.connection.execute("SELECT canonical_json FROM transmission_records WHERE transmission_id=?",(x["transmission_id"],)).fetchone()
  if old:
   if old[0]==canonical_json(x):return {"status":"IDEMPOTENT_SUCCESS","transmission":x}
   raise TransmissionConflict("TRANSMISSION_ID_COLLISION")
  deps=[("EVENT_EXPOSURE_BINDING",b["binding_id"],b["record_hash"]),("TRANSMISSION_POLICY",POLICY_ID,self.policy_hash)]
  with self.connection:
   self.connection.execute("INSERT INTO transmission_records VALUES(?,?,?,?,?,?)",(x["transmission_id"],b["binding_id"],b["record_hash"],x["evaluation_cutoff_timestamp"],x["record_hash"],canonical_json(x)))
   self.connection.executemany("INSERT INTO transmission_assertion_evaluations VALUES(?,?,?,?,?)",[(x["transmission_id"],a["assertion_hash"],a["exposure_type"],a["type_match_status"],canonical_json(a)) for a in x["assertion_evaluations"]]);self.connection.executemany("INSERT INTO transmission_paths VALUES(?,?,?)",[(x["transmission_id"],p["path_id"],canonical_json(p)) for p in x["transmission_paths"]]);self.connection.executemany("INSERT INTO transmission_dependencies VALUES(?,?,?,?)",[(x["transmission_id"],*d) for d in deps])
  return {"status":"CREATED","transmission":x}
 def integrity_check(self):
  self._meta();self._policy()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise TransmissionIntegrityFailure("SQLITE_FAILED")
  if self.binding_store.integrity_check()["result"]!="PASS":raise TransmissionIntegrityFailure("BINDING_STORE_FAILED")
  for t in ("transmission_store_meta","transmission_policies","transmission_records","transmission_assertion_evaluations","transmission_paths","transmission_dependencies"):
   names={r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,))}
   if names!={f"protect_{t}_update",f"protect_{t}_delete"}:raise TransmissionIntegrityFailure("TRIGGER_MISSING")
  count=0
  for r in self.connection.execute("SELECT * FROM transmission_records"):
   count+=1;x=json.loads(r["canonical_json"]);b=self._binding(x["binding_id"]);validate_transmission(x,b,self.policy,self.policy_hash)
   if (r["transmission_id"],r["binding_id"],r["binding_hash"],r["evaluation_cutoff_timestamp"],r["record_hash"])!=(x["transmission_id"],x["binding_id"],x["binding_hash"],x["evaluation_cutoff_timestamp"],x["record_hash"]):raise TransmissionIntegrityFailure("TYPED_MISMATCH")
   a=[json.loads(z[0]) for z in self.connection.execute("SELECT canonical_json FROM transmission_assertion_evaluations WHERE transmission_id=? ORDER BY assertion_hash",(x["transmission_id"],))];p=[json.loads(z[0]) for z in self.connection.execute("SELECT canonical_json FROM transmission_paths WHERE transmission_id=? ORDER BY path_id",(x["transmission_id"],))]
   if a!=x["assertion_evaluations"] or p!=x["transmission_paths"]:raise TransmissionIntegrityFailure("CHILD_COVERAGE_MISMATCH")
   deps={(z["record_type"],z["record_id"]):z["record_hash"] for z in self.connection.execute("SELECT * FROM transmission_dependencies WHERE transmission_id=?",(x["transmission_id"],))};wanted={("EVENT_EXPOSURE_BINDING",b["binding_id"]):b["record_hash"],("TRANSMISSION_POLICY",POLICY_ID):self.policy_hash}
   if deps!=wanted:raise TransmissionIntegrityFailure("DEPENDENCY_MISMATCH")
  return {"result":"PASS","transmissions":count,"authority":AUTHORITY,"policy_hash":self.policy_hash}
