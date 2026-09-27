import json,sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash,canonical_json,parse_utc
from stage6_exposure_binding.binding_builder import assertion_hash
from stage6_dimension_matching import DimensionMatchingStore
from stage6_dimension_matching.policy import EXPECTED_POLICY_HASH_V1 as MATCH_POLICY_HASH
from .direction_builder import DIRECTIONS,SCHEMA_VERSION,build_direction_record,eligibility
from .direction_validation import validate_direction_record
from .errors import DirectionConflict,DirectionIntegrityFailure,Stage6DirectionError
from .policy import AUTHORITY,EXPECTED_POLICY_HASH_V1,POLICY_ID,PROCESSOR_VERSION,load_policy

STORE_SCHEMA_VERSION="STAGE6_3F_DIRECTION_STORE_V1"
BASELINE_COMMIT="884b35bf86f12b3835c56855fdec2cd61df688ad"

class DirectionStore:
 def __init__(self,database:Path,matching_store:DimensionMatchingStore):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.matching_store=matching_store
  self.policy,self.policy_json,self.policy_hash=load_policy()
  if self.policy_hash!=EXPECTED_POLICY_HASH_V1:raise DirectionIntegrityFailure("DIRECTION_EXPECTED_POLICY_HASH_MISMATCH")
  new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._meta();self._policy()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE direction_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT,direction_schema_version TEXT,baseline_commit TEXT,processor_version TEXT,authority TEXT);CREATE TABLE direction_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE direction_records(direction_record_id TEXT PRIMARY KEY,match_id TEXT UNIQUE,match_hash TEXT,qualification_id TEXT,qualification_hash TEXT,transmission_id TEXT,transmission_hash TEXT,binding_id TEXT,binding_hash TEXT,event_id TEXT,event_version INTEGER,event_hash TEXT,exposure_id TEXT,exposure_version INTEGER,exposure_hash TEXT,direction_cutoff_timestamp TEXT,record_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE direction_qualifiers(direction_record_id TEXT,direction_qualifier_id TEXT,source_path_id TEXT,effect_direction TEXT,direction_rule_id TEXT,direction_rule_hash TEXT,assertion_hash TEXT,canonical_json TEXT,PRIMARY KEY(direction_record_id,direction_qualifier_id),FOREIGN KEY(direction_record_id) REFERENCES direction_records);CREATE TABLE direction_qualifier_evidence(direction_record_id TEXT,direction_qualifier_id TEXT,evidence_id TEXT,evidence_hash TEXT,PRIMARY KEY(direction_record_id,direction_qualifier_id,evidence_id),FOREIGN KEY(direction_record_id,direction_qualifier_id) REFERENCES direction_qualifiers);CREATE TABLE direction_path_results(direction_record_id TEXT,source_path_id TEXT,eligibility_status TEXT,effect_direction TEXT,canonical_json TEXT,PRIMARY KEY(direction_record_id,source_path_id),FOREIGN KEY(direction_record_id) REFERENCES direction_records);CREATE TABLE direction_dependencies(direction_record_id TEXT,record_type TEXT,record_id TEXT,record_hash TEXT,PRIMARY KEY(direction_record_id,record_type,record_id),FOREIGN KEY(direction_record_id) REFERENCES direction_records);""")
  self.connection.execute("INSERT INTO direction_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY));self.connection.execute("INSERT INTO direction_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json))
  for table in ("direction_store_meta","direction_policies","direction_records","direction_qualifiers","direction_qualifier_evidence","direction_path_results","direction_dependencies"):self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _meta(self):
  rows=self.connection.execute("SELECT * FROM direction_store_meta").fetchall()
  if len(rows)!=1 or tuple(rows[0])!=(1,STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY):raise DirectionIntegrityFailure("DIRECTION_METADATA_MISMATCH")
 def _policy(self):
  rows=self.connection.execute("SELECT * FROM direction_policies").fetchall()
  if len(rows)!=1 or tuple(rows[0])!=(POLICY_ID,EXPECTED_POLICY_HASH_V1,self.policy_json):raise DirectionIntegrityFailure("DIRECTION_POLICY_SNAPSHOT_MISMATCH")
 def _upstream(self):
  if self.matching_store.integrity_check().get("result")!="PASS":raise DirectionIntegrityFailure("MATCHING_STORE_INTEGRITY_FAILED")
 def _chain(self,match_id):
  row=self.matching_store.connection.execute("SELECT * FROM dimension_match_records WHERE match_id=?",(match_id,)).fetchone()
  if row is None:raise Stage6DirectionError("DIMENSION_MATCH_NOT_FOUND")
  match=json.loads(row["canonical_json"])
  if match.get("schema_version")!="STAGE6_EVENT_EXPOSURE_DIMENSION_MATCH_V1" or (match.get("policy_id"),match.get("policy_hash"))!=("S6DIMMATCHPOL_STAGE6_3E_V1",MATCH_POLICY_HASH) or (row["match_id"],row["record_hash"])!=(match["match_id"],match["record_hash"]):raise DirectionIntegrityFailure("DIMENSION_MATCH_IDENTITY_INVALID")
  q,t,b,event,_,ingestion=self.matching_store._chain(match["qualification_id"]);binding_store=self.matching_store.qualification_store.transmission_store.binding_store;exposure=binding_store._exposure(match["exposure_id"],match["exposure_version"])
  expected=(q["record_hash"],t["record_hash"],b["record_hash"],event["record_hash"],exposure["record_hash"]);actual=(match["qualification_hash"],match["transmission_hash"],match["binding_hash"],match["event_hash"],match["exposure_hash"])
  if actual!=expected:raise DirectionIntegrityFailure("DIRECTION_UPSTREAM_HASH_INVALID")
  return match,q,t,b,event,exposure,ingestion
 def _resolve(self,match,event,exposure,inputs):
  if not isinstance(inputs,list):raise Stage6DirectionError("DIRECTIONAL_INPUTS_INVALID")
  paths={x["source_path_id"]:x for x in match["path_matches"]};rules={x["event_type"]:x for x in self.policy["rules"]};rule=rules.get(event["event_type"]);eligible={pid:p for pid,p in paths.items() if eligibility(p,event["event_type"],rules)}
  if not eligible and inputs:raise Stage6DirectionError("NO_ELIGIBLE_DIRECTION_PATHS")
  assertions={assertion_hash(x):x for x in exposure["assertions"]};seen=set();items=[];all_evidence={};exposure_store=self.matching_store.qualification_store.transmission_store.binding_store.exposure_store
  for raw in inputs:
   if not isinstance(raw,dict) or set(raw)!={"source_path_id","effect_direction","evidence_ids"}:raise Stage6DirectionError("DIRECTIONAL_INPUT_FIELDS_INVALID")
   pid=raw["source_path_id"]
   if pid in seen:raise Stage6DirectionError("DUPLICATE_DIRECTION_PATH")
   seen.add(pid);path=eligible.get(pid)
   if path is None:raise Stage6DirectionError("DIRECTION_PATH_NOT_ELIGIBLE")
   if raw["effect_direction"] not in DIRECTIONS:raise Stage6DirectionError("EFFECT_DIRECTION_INVALID")
   ids=raw["evidence_ids"]
   if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):raise Stage6DirectionError("DIRECTION_EVIDENCE_IDS_INVALID")
   ids=sorted(ids);assertion=assertions.get(path["assertion_hash"])
   if assertion is None:raise DirectionIntegrityFailure("DIRECTION_ASSERTION_MISSING")
   if not set(ids)<=set(assertion["evidence_ids"]):raise Stage6DirectionError("DIRECTION_EVIDENCE_NOT_ASSERTION_SUBSET")
   evidence=exposure_store._evidence(ids,exposure["data_cutoff_timestamp"])
   if parse_utc(exposure["data_cutoff_timestamp"],"exposure_cutoff")>parse_utc(match["match_cutoff_timestamp"],"direction_cutoff"):raise Stage6DirectionError("DIRECTION_EXPOSURE_FROM_FUTURE")
   dims=set(path["matched_dimension_entity_ids"])
   for record in evidence:
    entities=set(record["entity_ids"])
    if match["company_entity_id"] not in entities:raise Stage6DirectionError("DIRECTION_EVIDENCE_COMPANY_SUPPORT_MISSING")
    if rule["dimension_requirement"]=="EXACT_ENTITY_MATCH_REQUIRED" and not entities&dims:raise Stage6DirectionError("DIRECTION_EVIDENCE_DIMENSION_SUPPORT_MISSING")
    all_evidence[record["evidence_id"]]=record
   refs=sorted(({"evidence_id":x["evidence_id"],"evidence_hash":x["record_hash"]} for x in evidence),key=lambda x:x["evidence_id"])
   items.append({"source_path_id":pid,"direction_rule_id":rule["rule_id"],"direction_rule_hash":canonical_hash(rule),"event_type":event["event_type"],"event_driver_change":rule["event_driver_change"],"source_rule_id":path["source_rule_id"],"source_rule_hash":path["source_rule_hash"],"assertion_hash":path["assertion_hash"],"exposure_type":path["exposure_type"],"dimension_match_status":path["dimension_match_status"],"matched_dimension_entity_ids":path["matched_dimension_entity_ids"],"effect_direction":raw["effect_direction"],"direction_basis":"EXPLICIT_EVIDENCE_BACKED_DECLARATION","evidence_refs":refs})
  return sorted(items,key=lambda x:x["source_path_id"]),[all_evidence[x] for x in sorted(all_evidence)]
 def _deps(self,match,q,t,b,event,exposure,evidence):
  return [("STAGE6_3E_DIMENSION_MATCH",match["match_id"],match["record_hash"]),("STAGE6_3D_DIMENSION_QUALIFICATION",q["qualification_id"],q["record_hash"]),("STAGE6_3C_TRANSMISSION",t["transmission_id"],t["record_hash"]),("STAGE6_3B_EVENT_EXPOSURE_BINDING",b["binding_id"],b["record_hash"]),("STAGE6_EVENT",f'{event["event_id"]}:v{event["event_version"]}',event["record_hash"]),("STAGE6_EXPOSURE",f'{exposure["exposure_id"]}:v{exposure["exposure_version"]}',exposure["record_hash"]),("DIRECTION_POLICY",POLICY_ID,self.policy_hash),*[("EVIDENCE",x["evidence_id"],x["record_hash"]) for x in evidence]]
 def evaluate_direction(self,*,match_id,directional_inputs):
  self._meta();self._policy();self._upstream();match,q,t,b,event,exposure,_=self._chain(match_id);items,evidence=self._resolve(match,event,exposure,directional_inputs);record=build_direction_record(match=match,qualification=q,transmission=t,binding=b,event=event,exposure=exposure,qualifier_items=items,policy=self.policy,policy_hash=self.policy_hash);validate_direction_record(record,match,q,t,b,event,exposure,self.policy,self.policy_hash)
  old=self.connection.execute("SELECT canonical_json FROM direction_records WHERE match_id=?",(match_id,)).fetchone()
  if old:
   if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","direction":record}
   raise DirectionConflict("MATCH_ALREADY_HAS_DISTINCT_DIRECTION_RECORD")
  deps=self._deps(match,q,t,b,event,exposure,evidence)
  with self.connection:
   self.connection.execute("INSERT INTO direction_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(record["direction_record_id"],match["match_id"],match["record_hash"],q["qualification_id"],q["record_hash"],t["transmission_id"],t["record_hash"],b["binding_id"],b["record_hash"],event["event_id"],event["event_version"],event["record_hash"],exposure["exposure_id"],exposure["exposure_version"],exposure["record_hash"],record["direction_cutoff_timestamp"],record["record_hash"],canonical_json(record)))
   self.connection.executemany("INSERT INTO direction_qualifiers VALUES(?,?,?,?,?,?,?,?)",[(record["direction_record_id"],x["direction_qualifier_id"],x["source_path_id"],x["effect_direction"],x["direction_rule_id"],x["direction_rule_hash"],x["assertion_hash"],canonical_json(x)) for x in record["direction_qualifiers"]])
   self.connection.executemany("INSERT INTO direction_qualifier_evidence VALUES(?,?,?,?)",[(record["direction_record_id"],x["direction_qualifier_id"],r["evidence_id"],r["evidence_hash"]) for x in record["direction_qualifiers"] for r in x["evidence_refs"]])
   self.connection.executemany("INSERT INTO direction_path_results VALUES(?,?,?,?,?)",[(record["direction_record_id"],x["source_path_id"],x["eligibility_status"],x["effect_direction"],canonical_json(x)) for x in record["path_direction_results"]])
   self.connection.executemany("INSERT INTO direction_dependencies VALUES(?,?,?,?)",[(record["direction_record_id"],*x) for x in deps])
  return {"status":"CREATED","direction":record}
 def integrity_check(self):
  self._meta();self._policy();self._upstream()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise DirectionIntegrityFailure("DIRECTION_SQLITE_INTEGRITY_FAILED")
  tables=("direction_store_meta","direction_policies","direction_records","direction_qualifiers","direction_qualifier_evidence","direction_path_results","direction_dependencies")
  for table in tables:
   names={x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
   if names!={f"protect_{table}_update",f"protect_{table}_delete"}:raise DirectionIntegrityFailure("DIRECTION_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM direction_records"):
   count+=1;stored=json.loads(row["canonical_json"]);match,q,t,b,event,exposure,_=self._chain(stored["match_id"]);inputs=[{"source_path_id":x["source_path_id"],"effect_direction":x["effect_direction"],"evidence_ids":[r["evidence_id"] for r in x["evidence_refs"]]} for x in stored["direction_qualifiers"]];items,evidence=self._resolve(match,event,exposure,inputs);replay=build_direction_record(match=match,qualification=q,transmission=t,binding=b,event=event,exposure=exposure,qualifier_items=items,policy=self.policy,policy_hash=self.policy_hash)
   if stored!=replay or row["canonical_json"]!=canonical_json(stored):raise DirectionIntegrityFailure("DIRECTION_REPLAY_MISMATCH")
   typed=(row["direction_record_id"],row["match_id"],row["match_hash"],row["qualification_id"],row["qualification_hash"],row["transmission_id"],row["transmission_hash"],row["binding_id"],row["binding_hash"],row["event_id"],row["event_version"],row["event_hash"],row["exposure_id"],row["exposure_version"],row["exposure_hash"],row["direction_cutoff_timestamp"],row["record_hash"]);wanted=(stored["direction_record_id"],stored["match_id"],stored["match_hash"],stored["qualification_id"],stored["qualification_hash"],stored["transmission_id"],stored["transmission_hash"],stored["binding_id"],stored["binding_hash"],stored["event_id"],stored["event_version"],stored["event_hash"],stored["exposure_id"],stored["exposure_version"],stored["exposure_hash"],stored["direction_cutoff_timestamp"],stored["record_hash"])
   if typed!=wanted:raise DirectionIntegrityFailure("DIRECTION_TYPED_RECORD_MISMATCH")
   qrows=self.connection.execute("SELECT * FROM direction_qualifiers WHERE direction_record_id=? ORDER BY source_path_id",(stored["direction_record_id"],)).fetchall();qualifiers=[json.loads(x["canonical_json"]) for x in qrows]
   if qualifiers!=stored["direction_qualifiers"] or any((r["direction_qualifier_id"],r["source_path_id"],r["effect_direction"],r["direction_rule_id"],r["direction_rule_hash"],r["assertion_hash"],r["canonical_json"])!=(x["direction_qualifier_id"],x["source_path_id"],x["effect_direction"],x["direction_rule_id"],x["direction_rule_hash"],x["assertion_hash"],canonical_json(x)) for r,x in zip(qrows,qualifiers)):raise DirectionIntegrityFailure("DIRECTION_QUALIFIER_COVERAGE_MISMATCH")
   refs={(x["direction_qualifier_id"],x["evidence_id"],x["evidence_hash"]) for x in self.connection.execute("SELECT * FROM direction_qualifier_evidence WHERE direction_record_id=?",(stored["direction_record_id"],))};wanted_refs={(x["direction_qualifier_id"],r["evidence_id"],r["evidence_hash"]) for x in stored["direction_qualifiers"] for r in x["evidence_refs"]}
   if refs!=wanted_refs:raise DirectionIntegrityFailure("DIRECTION_EVIDENCE_COVERAGE_MISMATCH")
   prows=self.connection.execute("SELECT * FROM direction_path_results WHERE direction_record_id=? ORDER BY source_path_id",(stored["direction_record_id"],)).fetchall();results=[json.loads(x["canonical_json"]) for x in prows]
   if results!=stored["path_direction_results"] or any((r["source_path_id"],r["eligibility_status"],r["effect_direction"],r["canonical_json"])!=(x["source_path_id"],x["eligibility_status"],x["effect_direction"],canonical_json(x)) for r,x in zip(prows,results)):raise DirectionIntegrityFailure("DIRECTION_PATH_COVERAGE_MISMATCH")
   actual={(x["record_type"],x["record_id"]):x["record_hash"] for x in self.connection.execute("SELECT * FROM direction_dependencies WHERE direction_record_id=?",(stored["direction_record_id"],))};expected={(a,b):c for a,b,c in self._deps(match,q,t,b,event,exposure,evidence)}
   if actual!=expected:raise DirectionIntegrityFailure("DIRECTION_DEPENDENCY_MISMATCH")
  return {"result":"PASS","directions":count,"authority":AUTHORITY,"policy_hash":self.policy_hash}
