import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_json
from stage6_direction_semantics import DirectionStore
from stage6_movement_path_effect import MovementPathEffectStore
from .company_effect_builder import SCHEMA_VERSION,build_company_effect
from .company_effect_validation import validate_company_effect
from .errors import CompanyEffectConflict,CompanyEffectIntegrityFailure,Stage6CompanyEffectError
from .policy import AUTHORITY,EXPECTED_POLICY_HASH_V1,POLICY_ID,PROCESSOR_VERSION,SOURCE_3F_HASH,SOURCE_3H_HASH,load_policy
STORE_SCHEMA_VERSION="STAGE6_3I_COMPANY_EFFECT_STORE_V1";BASELINE_COMMIT="af059d6acd8af023056b28f2cad6ba58a7bce6da"
class CompanyEffectStore:
 def __init__(self,database:Path,direction_store:DirectionStore|None=None,path_effect_store:MovementPathEffectStore|None=None):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.direction_store=direction_store;self.path_effect_store=path_effect_store;self.policy,self.policy_json,self.policy_hash=load_policy()
  if self.policy_hash!=EXPECTED_POLICY_HASH_V1:raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_EXPECTED_POLICY_HASH_MISMATCH")
  new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._meta();self._policy()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE company_effect_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT,effect_schema_version TEXT,baseline_commit TEXT,processor_version TEXT,authority TEXT);CREATE TABLE company_effect_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE company_effect_records(company_effect_record_id TEXT PRIMARY KEY,source_family TEXT,source_record_id TEXT UNIQUE,source_record_hash TEXT,match_id TEXT,match_hash TEXT,event_id TEXT,event_version INTEGER,event_hash TEXT,exposure_id TEXT,exposure_version INTEGER,exposure_hash TEXT,company_entity_id TEXT,company_event_effect TEXT,record_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE company_effect_units(company_effect_record_id TEXT,normalized_unit_id TEXT,source_path_id TEXT,movement_item_id TEXT,effect_direction TEXT,qualification_state TEXT,canonical_json TEXT,PRIMARY KEY(company_effect_record_id,normalized_unit_id),FOREIGN KEY(company_effect_record_id) REFERENCES company_effect_records);CREATE TABLE company_effect_dependencies(company_effect_record_id TEXT,record_type TEXT,record_id TEXT,record_hash TEXT,PRIMARY KEY(company_effect_record_id,record_type,record_id),FOREIGN KEY(company_effect_record_id) REFERENCES company_effect_records);""")
  self.connection.execute("INSERT INTO company_effect_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY));self.connection.execute("INSERT INTO company_effect_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json))
  for t in ("company_effect_store_meta","company_effect_policies","company_effect_records","company_effect_units","company_effect_dependencies"):self.connection.executescript(f"CREATE TRIGGER protect_{t}_update BEFORE UPDATE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{t}_delete BEFORE DELETE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _meta(self):
  r=self.connection.execute("SELECT * FROM company_effect_store_meta").fetchall()
  if len(r)!=1 or tuple(r[0])!=(1,STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY):raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_METADATA_MISMATCH")
 def _policy(self):
  r=self.connection.execute("SELECT * FROM company_effect_policies").fetchall()
  if len(r)!=1 or tuple(r[0])!=(POLICY_ID,EXPECTED_POLICY_HASH_V1,self.policy_json):raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_POLICY_SNAPSHOT_MISMATCH")
 def _load(self,family,source_id):
  routes={x["event_type"]:x["source_family"] for x in self.policy["routes"]}
  if family=="STAGE6_3F_DIRECTION":
   if self.direction_store is None or self.direction_store.integrity_check()["result"]!="PASS":raise CompanyEffectIntegrityFailure("DIRECTION_STORE_INTEGRITY_REQUIRED")
   row=self.direction_store.connection.execute("SELECT canonical_json FROM direction_records WHERE direction_record_id=?",(source_id,)).fetchone()
   if row is None:raise Stage6CompanyEffectError("DIRECTION_SOURCE_NOT_FOUND")
   source=json.loads(row[0]);match,*_=self.direction_store._chain(source["match_id"])
   if (source.get("schema_version"),source.get("processor_version"),source.get("policy_id"),source.get("policy_hash"),source.get("authority"))!=("STAGE6_ECONOMIC_PATH_DIRECTION_V1","STAGE6_3F_DIRECTION_EVALUATOR_V1","S6DIRPOL_STAGE6_3F_V1",SOURCE_3F_HASH,"SHADOW_ONLY"):raise CompanyEffectIntegrityFailure("DIRECTION_SOURCE_IDENTITY_INVALID")
  elif family=="STAGE6_3H_MOVEMENT_PATH_EFFECT":
   if self.path_effect_store is None or self.path_effect_store.integrity_check()["result"]!="PASS":raise CompanyEffectIntegrityFailure("PATH_EFFECT_STORE_INTEGRITY_REQUIRED")
   row=self.path_effect_store.connection.execute("SELECT canonical_json FROM movement_path_effect_records WHERE path_effect_record_id=?",(source_id,)).fetchone()
   if row is None:raise Stage6CompanyEffectError("PATH_EFFECT_SOURCE_NOT_FOUND")
   source=json.loads(row[0]);movement,match,exposure=self.path_effect_store._chain(source["movement_record_id"])
   if (source.get("schema_version"),source.get("processor_version"),source.get("policy_id"),source.get("policy_hash"),source.get("authority"))!=("STAGE6_MOVEMENT_AWARE_PATH_EFFECT_V1","STAGE6_3H_MOVEMENT_PATH_EFFECT_EVALUATOR_V1","S6PATHEFFPOL_STAGE6_3H_V1",SOURCE_3H_HASH,"SHADOW_ONLY"):raise CompanyEffectIntegrityFailure("PATH_EFFECT_SOURCE_IDENTITY_INVALID")
  else:raise Stage6CompanyEffectError("SOURCE_FAMILY_UNSUPPORTED")
  if routes.get(source["event_type"])!=family:raise Stage6CompanyEffectError("EVENT_SOURCE_FAMILY_MISMATCH")
  if (source["match_id"],source["match_hash"],source["event_id"],source["event_version"],source["event_hash"],source["exposure_id"],source["exposure_version"],source["exposure_hash"],source["company_entity_id"])!=(match["match_id"],match["record_hash"],match["event_id"],match["event_version"],match["event_hash"],match["exposure_id"],match["exposure_version"],match["exposure_hash"],match["company_entity_id"]):raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_UPSTREAM_IDENTITY_INVALID")
  return source,match
 def _deps(self,family,source,match):return [(family,source["direction_record_id"] if family=="STAGE6_3F_DIRECTION" else source["path_effect_record_id"],source["record_hash"]),("STAGE6_3E_DIMENSION_MATCH",match["match_id"],match["record_hash"]),("COMPANY_EFFECT_POLICY",POLICY_ID,self.policy_hash)]
 def synthesize_company_effect(self,*,source_family,source_record_id):
  self._meta();self._policy();source,match=self._load(source_family,source_record_id)
  try:record=build_company_effect(source_family=source_family,source=source,match=match,policy=self.policy,policy_hash=self.policy_hash)
  except ValueError as exc:raise CompanyEffectIntegrityFailure(str(exc)) from exc
  validate_company_effect(record,source_family,source,match,self.policy,self.policy_hash);old=self.connection.execute("SELECT canonical_json FROM company_effect_records WHERE source_record_id=?",(source_record_id,)).fetchone()
  if old:
   if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","company_effect":record}
   raise CompanyEffectConflict("SOURCE_ALREADY_HAS_DISTINCT_COMPANY_EFFECT_RECORD")
  deps=self._deps(source_family,source,match)
  with self.connection:
   self.connection.execute("INSERT INTO company_effect_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(record["company_effect_record_id"],source_family,source_record_id,source["record_hash"],match["match_id"],match["record_hash"],match["event_id"],match["event_version"],match["event_hash"],match["exposure_id"],match["exposure_version"],match["exposure_hash"],match["company_entity_id"],record["company_event_effect"],record["record_hash"],canonical_json(record)))
   self.connection.executemany("INSERT INTO company_effect_units VALUES(?,?,?,?,?,?,?)",[(record["company_effect_record_id"],x["normalized_unit_id"],x["source_path_id"],x["movement_item_id"],x["effect_direction"],x["qualification_state"],canonical_json(x)) for x in record["normalized_effect_units"]]);self.connection.executemany("INSERT INTO company_effect_dependencies VALUES(?,?,?,?)",[(record["company_effect_record_id"],*x) for x in deps])
  return {"status":"CREATED","company_effect":record}
 def integrity_check(self):
  self._meta();self._policy()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_SQLITE_INTEGRITY_FAILED")
  for t in ("company_effect_store_meta","company_effect_policies","company_effect_records","company_effect_units","company_effect_dependencies"):
   if {x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,))}!={f"protect_{t}_update",f"protect_{t}_delete"}:raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM company_effect_records"):
   count+=1;stored=json.loads(row["canonical_json"]);source,match=self._load(stored["source_family"],stored["source_record_id"])
   try:replay=build_company_effect(source_family=stored["source_family"],source=source,match=match,policy=self.policy,policy_hash=self.policy_hash)
   except ValueError as exc:raise CompanyEffectIntegrityFailure(str(exc)) from exc
   if stored!=replay or row["canonical_json"]!=canonical_json(stored):raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_REPLAY_MISMATCH")
   typed=(row["company_effect_record_id"],row["source_family"],row["source_record_id"],row["source_record_hash"],row["match_id"],row["match_hash"],row["event_id"],row["event_version"],row["event_hash"],row["exposure_id"],row["exposure_version"],row["exposure_hash"],row["company_entity_id"],row["company_event_effect"],row["record_hash"]);wanted=(stored["company_effect_record_id"],stored["source_family"],stored["source_record_id"],stored["source_record_hash"],stored["match_id"],stored["match_hash"],stored["event_id"],stored["event_version"],stored["event_hash"],stored["exposure_id"],stored["exposure_version"],stored["exposure_hash"],stored["company_entity_id"],stored["company_event_effect"],stored["record_hash"])
   if typed!=wanted:raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_TYPED_RECORD_MISMATCH")
   urows=self.connection.execute("SELECT * FROM company_effect_units WHERE company_effect_record_id=? ORDER BY source_path_id,COALESCE(movement_item_id,'')",(stored["company_effect_record_id"],)).fetchall();units=[json.loads(x["canonical_json"]) for x in urows]
   if units!=stored["normalized_effect_units"] or any((r["normalized_unit_id"],r["source_path_id"],r["movement_item_id"],r["effect_direction"],r["qualification_state"],r["canonical_json"])!=(x["normalized_unit_id"],x["source_path_id"],x["movement_item_id"],x["effect_direction"],x["qualification_state"],canonical_json(x)) for r,x in zip(urows,units)):raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_UNIT_COVERAGE_MISMATCH")
   actual={(x["record_type"],x["record_id"]):x["record_hash"] for x in self.connection.execute("SELECT * FROM company_effect_dependencies WHERE company_effect_record_id=?",(stored["company_effect_record_id"],))};expected={(a,b):c for a,b,c in self._deps(stored["source_family"],source,match)}
   if actual!=expected:raise CompanyEffectIntegrityFailure("COMPANY_EFFECT_DEPENDENCY_MISMATCH")
  return {"result":"PASS","company_effects":count,"authority":AUTHORITY,"policy_hash":self.policy_hash}
