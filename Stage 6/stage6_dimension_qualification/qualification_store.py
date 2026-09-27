import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json,parse_utc
from stage6_ingestion.registry import resolve_entity
from stage6_transmission import TransmissionStore
from .errors import *
from .policy import AUTHORITY,EXPECTED_POLICY_HASH_V1,POLICY_ID,PROCESSOR_VERSION,load_policy
from .qualification_builder import SCHEMA_VERSION,build_qualification
from .qualification_validation import validate_qualification
STORE_SCHEMA_VERSION="STAGE6_3D_DIMENSION_QUALIFICATION_STORE_V1";BASELINE="1f98a158d3d47f14d0ec50e298d8e5fcc6314ab7";TRANSMISSION_DEPENDENCY_TYPE="STAGE6_3C_TRANSMISSION";BINDING_DEPENDENCY_TYPE="STAGE6_3B_EVENT_EXPOSURE_BINDING"
class DimensionQualificationStore:
 def __init__(self,database:Path,transmission_store:TransmissionStore):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.transmission_store=transmission_store;self.policy,self.policy_json,self.policy_hash=load_policy()
  if self.policy_hash!=EXPECTED_POLICY_HASH_V1:raise DimensionIntegrityFailure("DIMENSION_EXPECTED_POLICY_HASH_MISMATCH")
  new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._meta();self._policy()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE dimension_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT,baseline_commit TEXT,qualification_schema_version TEXT,processor_version TEXT,authority TEXT);CREATE TABLE dimension_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT,canonical_json TEXT);CREATE TABLE dimension_records(qualification_id TEXT PRIMARY KEY,transmission_id TEXT UNIQUE,transmission_hash TEXT,binding_id TEXT,binding_hash TEXT,exposure_id TEXT,exposure_hash TEXT,record_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE dimension_qualifiers(qualification_id TEXT,qualifier_id TEXT,assertion_hash TEXT,source_path_id TEXT,source_rule_id TEXT,source_rule_hash TEXT,exposure_type TEXT,dimension_type TEXT,dimension_entity_id TEXT,dimension_entity_type TEXT,canonical_json TEXT,PRIMARY KEY(qualification_id,qualifier_id),FOREIGN KEY(qualification_id) REFERENCES dimension_records);CREATE TABLE dimension_qualifier_evidence(qualification_id TEXT,qualifier_id TEXT,evidence_id TEXT,evidence_hash TEXT,PRIMARY KEY(qualification_id,qualifier_id,evidence_id),FOREIGN KEY(qualification_id,qualifier_id) REFERENCES dimension_qualifiers);CREATE TABLE dimension_dependencies(qualification_id TEXT,record_type TEXT,record_id TEXT,record_hash TEXT,PRIMARY KEY(qualification_id,record_type,record_id),FOREIGN KEY(qualification_id) REFERENCES dimension_records);""")
  self.connection.execute("INSERT INTO dimension_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,BASELINE,SCHEMA_VERSION,PROCESSOR_VERSION,AUTHORITY));self.connection.execute("INSERT INTO dimension_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json))
  for t in ("dimension_store_meta","dimension_policies","dimension_records","dimension_qualifiers","dimension_qualifier_evidence","dimension_dependencies"):self.connection.executescript(f"CREATE TRIGGER protect_{t}_update BEFORE UPDATE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{t}_delete BEFORE DELETE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _meta(self):
  rows=self.connection.execute("SELECT * FROM dimension_store_meta").fetchall()
  if len(rows)!=1 or tuple(rows[0])!=(1,STORE_SCHEMA_VERSION,BASELINE,SCHEMA_VERSION,PROCESSOR_VERSION,AUTHORITY):raise DimensionIntegrityFailure("DIMENSION_METADATA_MISMATCH")
 def _policy(self):
  rows=self.connection.execute("SELECT * FROM dimension_policies").fetchall()
  if self.policy_hash!=EXPECTED_POLICY_HASH_V1 or len(rows)!=1 or tuple(rows[0])!=(POLICY_ID,EXPECTED_POLICY_HASH_V1,self.policy_json):raise DimensionIntegrityFailure("DIMENSION_POLICY_SNAPSHOT_MISMATCH")
 def _upstream(self):
  if self.transmission_store.integrity_check()["result"]!="PASS":raise DimensionIntegrityFailure("TRANSMISSION_STORE_INTEGRITY_FAILED")
 def _load(self,identity):
  row=self.transmission_store.connection.execute("SELECT * FROM transmission_records WHERE transmission_id=?",(identity,)).fetchone()
  if row is None:raise Stage6DimensionError("TRANSMISSION_NOT_FOUND")
  transmission=json.loads(row["canonical_json"])
  if transmission.get("schema_version")!="STAGE6_TRANSMISSION_PATH_EVALUATION_V1":raise DimensionIntegrityFailure("TRANSMISSION_SCHEMA_INVALID")
  if (row["transmission_id"],row["record_hash"])!=(transmission["transmission_id"],transmission["record_hash"]):raise DimensionIntegrityFailure("TRANSMISSION_TYPED_BINDING_INVALID")
  bs=self.transmission_store.binding_store;br=bs.connection.execute("SELECT canonical_json FROM binding_records WHERE binding_id=?",(transmission["binding_id"],)).fetchone()
  if br is None:raise DimensionIntegrityFailure("BINDING_MISSING")
  binding=json.loads(br[0]);exposure=bs._exposure(binding["exposure_id"],binding["exposure_version"])
  if (transmission["binding_hash"],binding["exposure_hash"])!=(binding["record_hash"],exposure["record_hash"]):raise DimensionIntegrityFailure("DIMENSION_UPSTREAM_HASH_MISMATCH")
  return transmission,binding,exposure
 def _resolve(self,transmission,binding,exposure,inputs):
  if not isinstance(inputs,list):raise Stage6DimensionError("QUALIFIER_INPUTS_INVALID")
  paths={p["assertion_hash"]:p for p in transmission["transmission_paths"]};rules={r["source_rule_id"]:r for r in self.policy["rules"]};assertions={}
  for a in exposure["assertions"]:assertions.setdefault(canonical_hash(a),[]).append(a)
  if not paths and inputs:raise Stage6DimensionError("NO_COMPATIBLE_PATH_QUALIFIER_PROHIBITED")
  registry=self.transmission_store.binding_store.exposure_store.ingestion_store._verify_persisted_registry_chain("ENTITY",exposure["entity_registry_snapshot_id"]);items=[];all_evidence={};seen=set()
  for raw in inputs:
   if not isinstance(raw,dict) or set(raw)!={"assertion_hash","dimension_type","dimension_entity_id","evidence_ids"}:raise Stage6DimensionError("QUALIFIER_INPUT_FIELDS_INVALID")
   path=paths.get(raw["assertion_hash"])
   if path is None:raise Stage6DimensionError("QUALIFIER_ASSERTION_NOT_COMPATIBLE")
   rule=rules[path["rule_id"]]
   if rule["dimension_mode"]!="EXPLICIT_REQUIRED":raise Stage6DimensionError("DIMENSION_QUALIFIER_NOT_ALLOWED")
   if raw["dimension_type"]!=rule["dimension_type"]:raise Stage6DimensionError("DIMENSION_TYPE_POLICY_MISMATCH")
   key=(raw["assertion_hash"],raw["dimension_type"],raw["dimension_entity_id"])
   if key in seen:raise Stage6DimensionError("DUPLICATE_DIMENSION_QUALIFIER")
   seen.add(key);matches=assertions.get(raw["assertion_hash"],[])
   if len(matches)!=1:raise Stage6DimensionError("QUALIFIER_ASSERTION_RESOLUTION_INVALID")
   assertion=matches[0]
   if assertion["exposure_type"]!=path["exposure_type"]:raise DimensionIntegrityFailure("QUALIFIER_EXPOSURE_TYPE_MISMATCH")
   ids=raw["evidence_ids"]
   if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):raise Stage6DimensionError("QUALIFIER_EVIDENCE_IDS_INVALID")
   ids=sorted(ids)
   if not set(ids)<=set(assertion["evidence_ids"]):raise Stage6DimensionError("QUALIFIER_EVIDENCE_NOT_ASSERTION_SUBSET")
   try:entity=resolve_entity(registry,raw["dimension_entity_id"],transmission["evaluation_cutoff_timestamp"])
   except Exception as exc:raise Stage6DimensionError("DIMENSION_ENTITY_RESOLUTION_FAILED") from exc
   if entity["entity_type"]!=raw["dimension_type"]:raise Stage6DimensionError("DIMENSION_ENTITY_TYPE_MISMATCH")
   evidence=self.transmission_store.binding_store.exposure_store._evidence(ids,exposure["data_cutoff_timestamp"])
   if parse_utc(exposure["data_cutoff_timestamp"],"cutoff")>parse_utc(transmission["evaluation_cutoff_timestamp"],"qualification"):raise Stage6DimensionError("DIMENSION_QUALIFICATION_PIT_INVALID")
   if any(raw["dimension_entity_id"] not in e["entity_ids"] for e in evidence):raise Stage6DimensionError("QUALIFIER_EVIDENCE_ENTITY_SUPPORT_MISSING")
   refs=sorted([{"evidence_id":e["evidence_id"],"evidence_hash":e["record_hash"]} for e in evidence],key=lambda x:x["evidence_id"]);all_evidence.update({e["evidence_id"]:e for e in evidence})
   items.append({"assertion_hash":raw["assertion_hash"],"source_path_id":path["path_id"],"source_rule_id":path["rule_id"],"source_rule_hash":path["rule_hash"],"exposure_type":path["exposure_type"],"dimension_type":raw["dimension_type"],"dimension_entity_id":raw["dimension_entity_id"],"dimension_entity_type":entity["entity_type"],"evidence_refs":refs})
  return items,[all_evidence[k] for k in sorted(all_evidence)]
 def _deps(self,x,transmission,binding,exposure,evidence):return [(TRANSMISSION_DEPENDENCY_TYPE,transmission["transmission_id"],transmission["record_hash"]),(BINDING_DEPENDENCY_TYPE,binding["binding_id"],binding["record_hash"]),("STAGE6_EXPOSURE",f'{exposure["exposure_id"]}:v{exposure["exposure_version"]}',exposure["record_hash"]),("ENTITY_REGISTRY_SNAPSHOT",exposure["entity_registry_snapshot_id"],exposure["entity_registry_hash"]),("DIMENSION_QUALIFICATION_POLICY",POLICY_ID,self.policy_hash),*[("EVIDENCE",e["evidence_id"],e["record_hash"]) for e in evidence]]
 def qualify_transmission(self,*,transmission_id,qualifier_inputs):
  self._meta();self._policy();self._upstream();t,b,e=self._load(transmission_id);items,evidence=self._resolve(t,b,e,qualifier_inputs);x=build_qualification(transmission=t,binding=b,exposure=e,qualifier_items=items,policy=self.policy,policy_hash=self.policy_hash);validate_qualification(x,t,b,e,self.policy,self.policy_hash);old=self.connection.execute("SELECT canonical_json FROM dimension_records WHERE transmission_id=?",(transmission_id,)).fetchone()
  if old:
   if old[0]==canonical_json(x):return {"status":"IDEMPOTENT_SUCCESS","qualification":x}
   raise DimensionConflict("TRANSMISSION_ALREADY_HAS_DISTINCT_DIMENSION_QUALIFICATION")
  deps=self._deps(x,t,b,e,evidence)
  with self.connection:
   self.connection.execute("INSERT INTO dimension_records VALUES(?,?,?,?,?,?,?,?,?)",(x["qualification_id"],transmission_id,t["record_hash"],b["binding_id"],b["record_hash"],e["exposure_id"],e["record_hash"],x["record_hash"],canonical_json(x)))
   self.connection.executemany("INSERT INTO dimension_qualifiers VALUES(?,?,?,?,?,?,?,?,?,?,?)",[(x["qualification_id"],q["qualifier_id"],q["assertion_hash"],q["source_path_id"],q["source_rule_id"],q["source_rule_hash"],q["exposure_type"],q["dimension_type"],q["dimension_entity_id"],q["dimension_entity_type"],canonical_json(q)) for q in x["qualifiers"]])
   self.connection.executemany("INSERT INTO dimension_qualifier_evidence VALUES(?,?,?,?)",[(x["qualification_id"],q["qualifier_id"],r["evidence_id"],r["evidence_hash"]) for q in x["qualifiers"] for r in q["evidence_refs"]]);self.connection.executemany("INSERT INTO dimension_dependencies VALUES(?,?,?,?)",[(x["qualification_id"],*d) for d in deps])
  return {"status":"CREATED","qualification":x}
 def integrity_check(self):
  self._meta();self._policy();self._upstream()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise DimensionIntegrityFailure("DIMENSION_SQLITE_INTEGRITY_FAILED")
  for t in ("dimension_store_meta","dimension_policies","dimension_records","dimension_qualifiers","dimension_qualifier_evidence","dimension_dependencies"):
   names={r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,))}
   if names!={f"protect_{t}_update",f"protect_{t}_delete"}:raise DimensionIntegrityFailure("DIMENSION_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM dimension_records"):
   count+=1;x=json.loads(row["canonical_json"]);t,b,e=self._load(x["transmission_id"]);inputs=[{"assertion_hash":q["assertion_hash"],"dimension_type":q["dimension_type"],"dimension_entity_id":q["dimension_entity_id"],"evidence_ids":[r["evidence_id"] for r in q["evidence_refs"]]} for q in x["qualifiers"]];items,evidence=self._resolve(t,b,e,inputs);replay=build_qualification(transmission=t,binding=b,exposure=e,qualifier_items=items,policy=self.policy,policy_hash=self.policy_hash)
   if x!=replay or row["canonical_json"]!=canonical_json(x):raise DimensionIntegrityFailure("DIMENSION_REPLAY_MISMATCH")
   if tuple(row)!=(x["qualification_id"],x["transmission_id"],x["transmission_hash"],x["binding_id"],x["binding_hash"],x["exposure_id"],x["exposure_hash"],x["record_hash"],canonical_json(x)):raise DimensionIntegrityFailure("DIMENSION_TYPED_RECORD_MISMATCH")
   qrows=self.connection.execute("SELECT * FROM dimension_qualifiers WHERE qualification_id=? ORDER BY assertion_hash,dimension_type,dimension_entity_id",(x["qualification_id"],)).fetchall();qs=[json.loads(r["canonical_json"]) for r in qrows]
   if qs!=x["qualifiers"]:raise DimensionIntegrityFailure("DIMENSION_QUALIFIER_COVERAGE_MISMATCH")
   for r,q in zip(qrows,qs):
    if tuple(r)!=(x["qualification_id"],q["qualifier_id"],q["assertion_hash"],q["source_path_id"],q["source_rule_id"],q["source_rule_hash"],q["exposure_type"],q["dimension_type"],q["dimension_entity_id"],q["dimension_entity_type"],canonical_json(q)):raise DimensionIntegrityFailure("DIMENSION_QUALIFIER_TYPED_MISMATCH")
   actual_refs={(r["qualifier_id"],r["evidence_id"],r["evidence_hash"]) for r in self.connection.execute("SELECT * FROM dimension_qualifier_evidence WHERE qualification_id=?",(x["qualification_id"],))};wanted_refs={(q["qualifier_id"],r["evidence_id"],r["evidence_hash"]) for q in x["qualifiers"] for r in q["evidence_refs"]}
   if actual_refs!=wanted_refs:raise DimensionIntegrityFailure("DIMENSION_QUALIFIER_EVIDENCE_COVERAGE_MISMATCH")
   actual={(r["record_type"],r["record_id"]):r["record_hash"] for r in self.connection.execute("SELECT * FROM dimension_dependencies WHERE qualification_id=?",(x["qualification_id"],))};wanted={(a,b):c for a,b,c in self._deps(x,t,b,e,evidence)}
   if actual!=wanted:raise DimensionIntegrityFailure("DIMENSION_DEPENDENCY_MISMATCH")
  return {"result":"PASS","qualifications":count,"authority":AUTHORITY,"policy_hash":self.policy_hash}
