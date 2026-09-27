import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_json,parse_utc
from stage6_ingestion.registry import resolve_entity
from stage6_dimension_qualification import DimensionQualificationStore
from stage6_dimension_qualification.policy import EXPECTED_POLICY_HASH_V1 as QUALIFICATION_POLICY_HASH
from .errors import *
from .matching_builder import SCHEMA_VERSION,build_dimension_match
from .matching_validation import validate_dimension_match
from .policy import AUTHORITY,EXPECTED_POLICY_HASH_V1,POLICY_ID,PROCESSOR_VERSION,load_policy
STORE_SCHEMA_VERSION="STAGE6_3E_DIMENSION_MATCH_STORE_V1";BASELINE="dd897395ed7bffdfdb2a03fee5fa00343d88d488"
class DimensionMatchingStore:
 def __init__(self,database:Path,qualification_store:DimensionQualificationStore):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.qualification_store=qualification_store;self.policy,self.policy_json,self.policy_hash=load_policy()
  if self.policy_hash!=EXPECTED_POLICY_HASH_V1:raise DimensionMatchingIntegrityFailure("MATCH_EXPECTED_POLICY_HASH_MISMATCH")
  new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._meta();self._policy()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE dimension_match_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT,baseline_commit TEXT,match_schema_version TEXT,processor_version TEXT,authority TEXT);CREATE TABLE dimension_match_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT,canonical_json TEXT);CREATE TABLE dimension_match_records(match_id TEXT PRIMARY KEY,qualification_id TEXT UNIQUE,qualification_hash TEXT,transmission_id TEXT,transmission_hash TEXT,binding_id TEXT,binding_hash TEXT,event_id TEXT,event_version INTEGER,event_hash TEXT,record_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE event_dimension_qualifiers(match_id TEXT,event_qualifier_id TEXT,event_field TEXT,event_dimension_value TEXT,dimension_type TEXT,dimension_entity_id TEXT,dimension_entity_type TEXT,canonical_json TEXT,PRIMARY KEY(match_id,event_qualifier_id),FOREIGN KEY(match_id) REFERENCES dimension_match_records);CREATE TABLE event_dimension_qualifier_evidence(match_id TEXT,event_qualifier_id TEXT,evidence_id TEXT,evidence_hash TEXT,PRIMARY KEY(match_id,event_qualifier_id,evidence_id),FOREIGN KEY(match_id,event_qualifier_id) REFERENCES event_dimension_qualifiers);CREATE TABLE dimension_path_matches(match_id TEXT,source_path_id TEXT,dimension_match_status TEXT,canonical_json TEXT,PRIMARY KEY(match_id,source_path_id),FOREIGN KEY(match_id) REFERENCES dimension_match_records);CREATE TABLE dimension_match_dependencies(match_id TEXT,record_type TEXT,record_id TEXT,record_hash TEXT,PRIMARY KEY(match_id,record_type,record_id),FOREIGN KEY(match_id) REFERENCES dimension_match_records);""")
  self.connection.execute("INSERT INTO dimension_match_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,BASELINE,SCHEMA_VERSION,PROCESSOR_VERSION,AUTHORITY));self.connection.execute("INSERT INTO dimension_match_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json))
  for table in ("dimension_match_store_meta","dimension_match_policies","dimension_match_records","event_dimension_qualifiers","event_dimension_qualifier_evidence","dimension_path_matches","dimension_match_dependencies"):self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _meta(self):
  rows=self.connection.execute("SELECT * FROM dimension_match_store_meta").fetchall()
  if len(rows)!=1 or tuple(rows[0])!=(1,STORE_SCHEMA_VERSION,BASELINE,SCHEMA_VERSION,PROCESSOR_VERSION,AUTHORITY):raise DimensionMatchingIntegrityFailure("MATCH_METADATA_MISMATCH")
 def _policy(self):
  rows=self.connection.execute("SELECT * FROM dimension_match_policies").fetchall()
  if self.policy_hash!=EXPECTED_POLICY_HASH_V1 or len(rows)!=1 or tuple(rows[0])!=(POLICY_ID,EXPECTED_POLICY_HASH_V1,self.policy_json):raise DimensionMatchingIntegrityFailure("MATCH_POLICY_SNAPSHOT_MISMATCH")
 def _upstream(self):
  if self.qualification_store.integrity_check()["result"]!="PASS":raise DimensionMatchingIntegrityFailure("QUALIFICATION_STORE_INTEGRITY_FAILED")
 def _chain(self,qualification_id):
  qrow=self.qualification_store.connection.execute("SELECT * FROM dimension_records WHERE qualification_id=?",(qualification_id,)).fetchone()
  if qrow is None:raise Stage6DimensionMatchingError("QUALIFICATION_NOT_FOUND")
  q=json.loads(qrow["canonical_json"])
  if q.get("schema_version")!="STAGE6_EXPOSURE_DIMENSION_QUALIFICATION_V1" or (q.get("policy_id"),q.get("policy_hash"))!=("S6DIMPOL_STAGE6_3D_V1",QUALIFICATION_POLICY_HASH) or (qrow["qualification_id"],qrow["record_hash"])!=(q["qualification_id"],q["record_hash"]):raise DimensionMatchingIntegrityFailure("QUALIFICATION_IDENTITY_INVALID")
  ts=self.qualification_store.transmission_store;trow=ts.connection.execute("SELECT * FROM transmission_records WHERE transmission_id=?",(q["transmission_id"],)).fetchone()
  if trow is None:raise DimensionMatchingIntegrityFailure("MATCH_TRANSMISSION_MISSING")
  t=json.loads(trow["canonical_json"]);bs=ts.binding_store;brow=bs.connection.execute("SELECT * FROM binding_records WHERE binding_id=?",(q["binding_id"],)).fetchone()
  if brow is None:raise DimensionMatchingIntegrityFailure("MATCH_BINDING_MISSING")
  b=json.loads(brow["canonical_json"]);event=bs._event(b["event_id"],b["event_version"])
  if (q["transmission_hash"],q["binding_hash"],q["event_id"],q["event_version"],q["event_hash"])!=(t["record_hash"],b["record_hash"],event["event_id"],event["event_version"],event["record_hash"]):raise DimensionMatchingIntegrityFailure("MATCH_UPSTREAM_HASH_INVALID")
  ingestion=bs.event_store.ingestion_store;registry=ingestion._verify_persisted_registry_chain("ENTITY",event["entity_resolution_version"])
  if parse_utc(registry["as_of_timestamp"],"event_registry")>parse_utc(q["qualification_cutoff_timestamp"],"match_cutoff"):raise Stage6DimensionMatchingError("EVENT_REGISTRY_FROM_FUTURE")
  return q,t,b,event,registry,ingestion
 def _authority(self,ingestion,evidence):
  registry=ingestion._verify_persisted_registry_chain("SOURCE",evidence["source_registry_snapshot_id"]);matches=[x for x in registry["sources"] if x["source_id"]==evidence["source_id"]]
  if len(matches)!=1 or matches[0]["authority_level"] not in {"PRIMARY_OFFICIAL","AUTHORITATIVE_INDEPENDENT"}:raise Stage6DimensionMatchingError("EVENT_QUALIFIER_EVIDENCE_AUTHORITY_INVALID")
 def _resolve(self,q,t,b,event,registry,ingestion,inputs):
  if not isinstance(inputs,list):raise Stage6DimensionMatchingError("EVENT_QUALIFIER_INPUTS_INVALID")
  paths=t["transmission_paths"];rules={r["source_rule_id"]:r for r in self.policy["rules"]};rule=rules.get(t.get("rule_id"))
  if not paths and inputs:raise Stage6DimensionMatchingError("NO_COMPATIBLE_PATH_EVENT_QUALIFIER_PROHIBITED")
  if paths and rule["dimension_mode"]=="NOT_REQUIRED" and inputs:raise Stage6DimensionMatchingError("EVENT_DIMENSION_QUALIFIER_NOT_ALLOWED")
  seen_values=set();seen_entities=set();items=[];all_evidence={};cutoff=q["qualification_cutoff_timestamp"]
  for raw in inputs:
   if not isinstance(raw,dict) or set(raw)!={"dimension_type","event_dimension_value","dimension_entity_id","evidence_ids"}:raise Stage6DimensionMatchingError("EVENT_QUALIFIER_INPUT_FIELDS_INVALID")
   if rule is None or rule["dimension_mode"]!="EXPLICIT_REQUIRED":raise Stage6DimensionMatchingError("EVENT_DIMENSION_QUALIFIER_NOT_ALLOWED")
   if raw["dimension_type"]!=rule["dimension_type"]:raise Stage6DimensionMatchingError("EVENT_DIMENSION_TYPE_POLICY_MISMATCH")
   if raw["event_dimension_value"] not in event[rule["event_field"]]:raise Stage6DimensionMatchingError("EVENT_DIMENSION_VALUE_NOT_PRESENT")
   if raw["event_dimension_value"] in seen_values:raise Stage6DimensionMatchingError("DUPLICATE_EVENT_DIMENSION_VALUE")
   entity_key=(raw["dimension_type"],raw["dimension_entity_id"])
   if entity_key in seen_entities:raise Stage6DimensionMatchingError("DUPLICATE_EVENT_DIMENSION_ENTITY")
   seen_values.add(raw["event_dimension_value"]);seen_entities.add(entity_key)
   ids=raw["evidence_ids"]
   if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):raise Stage6DimensionMatchingError("EVENT_QUALIFIER_EVIDENCE_IDS_INVALID")
   ids=sorted(ids)
   if not set(ids)<=set(event["source_evidence_ids"]):raise Stage6DimensionMatchingError("EVENT_QUALIFIER_EVIDENCE_NOT_EVENT_SUBSET")
   try:entity=resolve_entity(registry,raw["dimension_entity_id"],cutoff)
   except Exception as exc:raise Stage6DimensionMatchingError("EVENT_DIMENSION_ENTITY_RESOLUTION_FAILED") from exc
   if entity["entity_type"]!=raw["dimension_type"]:raise Stage6DimensionMatchingError("EVENT_DIMENSION_ENTITY_TYPE_MISMATCH")
   evidence=self.qualification_store.transmission_store.binding_store.event_store._load_evidence(ids)
   for record in evidence:
    self._authority(ingestion,record)
    if parse_utc(record["retrieved_timestamp_utc"],"retrieved")>parse_utc(event["last_updated_timestamp"],"event_updated") or parse_utc(event["last_updated_timestamp"],"event_updated")>parse_utc(cutoff,"cutoff"):raise Stage6DimensionMatchingError("EVENT_QUALIFIER_EVIDENCE_PIT_INVALID")
    if raw["dimension_entity_id"] not in record["entity_ids"]:raise Stage6DimensionMatchingError("EVENT_QUALIFIER_EVIDENCE_ENTITY_SUPPORT_MISSING")
    all_evidence[record["evidence_id"]]=record
   refs=sorted([{"evidence_id":x["evidence_id"],"evidence_hash":x["record_hash"]} for x in evidence],key=lambda x:x["evidence_id"]);items.append({"event_field":rule["event_field"],"event_dimension_value":raw["event_dimension_value"],"dimension_type":raw["dimension_type"],"dimension_entity_id":raw["dimension_entity_id"],"dimension_entity_type":entity["entity_type"],"evidence_refs":refs})
  return items,[all_evidence[k] for k in sorted(all_evidence)]
 def _deps(self,q,t,b,event,registry,evidence):return [("STAGE6_3D_DIMENSION_QUALIFICATION",q["qualification_id"],q["record_hash"]),("STAGE6_3C_TRANSMISSION",t["transmission_id"],t["record_hash"]),("STAGE6_3B_EVENT_EXPOSURE_BINDING",b["binding_id"],b["record_hash"]),("STAGE6_EVENT",f'{event["event_id"]}:v{event["event_version"]}',event["record_hash"]),("EVENT_ENTITY_REGISTRY_SNAPSHOT",registry["registry_snapshot_id"],registry["registry_hash"]),("DIMENSION_MATCHING_POLICY",POLICY_ID,self.policy_hash),*[("EVIDENCE",x["evidence_id"],x["record_hash"]) for x in evidence]]
 def match_qualification(self,*,qualification_id,event_qualifier_inputs):
  self._meta();self._policy();self._upstream();q,t,b,event,registry,ingestion=self._chain(qualification_id);items,evidence=self._resolve(q,t,b,event,registry,ingestion,event_qualifier_inputs);record=build_dimension_match(qualification=q,transmission=t,binding=b,event=event,event_registry=registry,event_qualifiers=items,policy=self.policy,policy_hash=self.policy_hash);validate_dimension_match(record,q,t,b,event,registry,self.policy,self.policy_hash);old=self.connection.execute("SELECT canonical_json FROM dimension_match_records WHERE qualification_id=?",(qualification_id,)).fetchone()
  if old:
   if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","match":record}
   raise DimensionMatchingConflict("QUALIFICATION_ALREADY_HAS_DISTINCT_DIMENSION_MATCH")
  deps=self._deps(q,t,b,event,registry,evidence)
  with self.connection:
   self.connection.execute("INSERT INTO dimension_match_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(record["match_id"],q["qualification_id"],q["record_hash"],t["transmission_id"],t["record_hash"],b["binding_id"],b["record_hash"],event["event_id"],event["event_version"],event["record_hash"],record["record_hash"],canonical_json(record)))
   self.connection.executemany("INSERT INTO event_dimension_qualifiers VALUES(?,?,?,?,?,?,?,?)",[(record["match_id"],x["event_qualifier_id"],x["event_field"],x["event_dimension_value"],x["dimension_type"],x["dimension_entity_id"],x["dimension_entity_type"],canonical_json(x)) for x in record["event_qualifiers"]]);self.connection.executemany("INSERT INTO event_dimension_qualifier_evidence VALUES(?,?,?,?)",[(record["match_id"],x["event_qualifier_id"],r["evidence_id"],r["evidence_hash"]) for x in record["event_qualifiers"] for r in x["evidence_refs"]]);self.connection.executemany("INSERT INTO dimension_path_matches VALUES(?,?,?,?)",[(record["match_id"],x["source_path_id"],x["dimension_match_status"],canonical_json(x)) for x in record["path_matches"]]);self.connection.executemany("INSERT INTO dimension_match_dependencies VALUES(?,?,?,?)",[(record["match_id"],*x) for x in deps])
  return {"status":"CREATED","match":record}
 def integrity_check(self):
  self._meta();self._policy();self._upstream()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise DimensionMatchingIntegrityFailure("MATCH_SQLITE_INTEGRITY_FAILED")
  for table in ("dimension_match_store_meta","dimension_match_policies","dimension_match_records","event_dimension_qualifiers","event_dimension_qualifier_evidence","dimension_path_matches","dimension_match_dependencies"):
   names={x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
   if names!={f"protect_{table}_update",f"protect_{table}_delete"}:raise DimensionMatchingIntegrityFailure("MATCH_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM dimension_match_records"):
   count+=1;stored=json.loads(row["canonical_json"]);q,t,b,event,registry,ingestion=self._chain(stored["qualification_id"]);inputs=[{"dimension_type":x["dimension_type"],"event_dimension_value":x["event_dimension_value"],"dimension_entity_id":x["dimension_entity_id"],"evidence_ids":[r["evidence_id"] for r in x["evidence_refs"]]} for x in stored["event_qualifiers"]];items,evidence=self._resolve(q,t,b,event,registry,ingestion,inputs);replay=build_dimension_match(qualification=q,transmission=t,binding=b,event=event,event_registry=registry,event_qualifiers=items,policy=self.policy,policy_hash=self.policy_hash)
   if stored!=replay or row["canonical_json"]!=canonical_json(stored):raise DimensionMatchingIntegrityFailure("MATCH_REPLAY_MISMATCH")
   typed=(row["match_id"],row["qualification_id"],row["qualification_hash"],row["transmission_id"],row["transmission_hash"],row["binding_id"],row["binding_hash"],row["event_id"],row["event_version"],row["event_hash"],row["record_hash"]);expected=(stored["match_id"],stored["qualification_id"],stored["qualification_hash"],stored["transmission_id"],stored["transmission_hash"],stored["binding_id"],stored["binding_hash"],stored["event_id"],stored["event_version"],stored["event_hash"],stored["record_hash"])
   if typed!=expected:raise DimensionMatchingIntegrityFailure("MATCH_TYPED_RECORD_MISMATCH")
   qrows=self.connection.execute("SELECT * FROM event_dimension_qualifiers WHERE match_id=? ORDER BY event_field,event_dimension_value,dimension_type,dimension_entity_id",(stored["match_id"],)).fetchall();qualifiers=[json.loads(x["canonical_json"]) for x in qrows]
   if qualifiers!=stored["event_qualifiers"]:raise DimensionMatchingIntegrityFailure("MATCH_EVENT_QUALIFIER_COVERAGE_MISMATCH")
   for r,x in zip(qrows,qualifiers):
    if (r["event_qualifier_id"],r["event_field"],r["event_dimension_value"],r["dimension_type"],r["dimension_entity_id"],r["dimension_entity_type"],r["canonical_json"])!=(x["event_qualifier_id"],x["event_field"],x["event_dimension_value"],x["dimension_type"],x["dimension_entity_id"],x["dimension_entity_type"],canonical_json(x)):raise DimensionMatchingIntegrityFailure("MATCH_EVENT_QUALIFIER_TYPED_MISMATCH")
   refs={(r["event_qualifier_id"],r["evidence_id"],r["evidence_hash"]) for r in self.connection.execute("SELECT * FROM event_dimension_qualifier_evidence WHERE match_id=?",(stored["match_id"],))};wanted_refs={(x["event_qualifier_id"],r["evidence_id"],r["evidence_hash"]) for x in stored["event_qualifiers"] for r in x["evidence_refs"]}
   if refs!=wanted_refs:raise DimensionMatchingIntegrityFailure("MATCH_EVENT_EVIDENCE_COVERAGE_MISMATCH")
   pathrows=self.connection.execute("SELECT * FROM dimension_path_matches WHERE match_id=? ORDER BY source_path_id",(stored["match_id"],)).fetchall();path_matches=[json.loads(x["canonical_json"]) for x in pathrows]
   if path_matches!=stored["path_matches"] or any((r["source_path_id"],r["dimension_match_status"],r["canonical_json"])!=(x["source_path_id"],x["dimension_match_status"],canonical_json(x)) for r,x in zip(pathrows,path_matches)):raise DimensionMatchingIntegrityFailure("MATCH_PATH_COVERAGE_MISMATCH")
   actual={(x["record_type"],x["record_id"]):x["record_hash"] for x in self.connection.execute("SELECT * FROM dimension_match_dependencies WHERE match_id=?",(stored["match_id"],))};wanted={(a,b):c for a,b,c in self._deps(q,t,b,event,registry,evidence)}
   if actual!=wanted:raise DimensionMatchingIntegrityFailure("MATCH_DEPENDENCY_MISMATCH")
  return {"result":"PASS","matches":count,"authority":AUTHORITY,"policy_hash":self.policy_hash}
