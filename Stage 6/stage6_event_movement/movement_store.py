import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json,parse_utc
from stage6_dimension_matching import DimensionMatchingStore
from stage6_dimension_matching.policy import EXPECTED_POLICY_HASH_V1 as MATCH_POLICY_HASH
from .errors import EventMovementConflict,EventMovementIntegrityFailure,Stage6EventMovementError
from .movement_builder import SCHEMA_VERSION,build_event_movement,eligible_subjects
from .movement_validation import validate_event_movement
from .policy import AUTHORITY,EXPECTED_POLICY_HASH_V1,POLICY_ID,PROCESSOR_VERSION,load_policy
STORE_SCHEMA_VERSION="STAGE6_3G_EVENT_MOVEMENT_STORE_V1";BASELINE_COMMIT="b1c755e03666be30f623acd6ff3e77184a58ea41"
class EventMovementStore:
 def __init__(self,database:Path,matching_store:DimensionMatchingStore):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.matching_store=matching_store;self.policy,self.policy_json,self.policy_hash=load_policy()
  if self.policy_hash!=EXPECTED_POLICY_HASH_V1:raise EventMovementIntegrityFailure("MOVEMENT_EXPECTED_POLICY_HASH_MISMATCH")
  new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._meta();self._policy()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE event_movement_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT,movement_schema_version TEXT,baseline_commit TEXT,processor_version TEXT,authority TEXT);CREATE TABLE event_movement_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE event_movement_records(movement_record_id TEXT PRIMARY KEY,match_id TEXT UNIQUE,match_hash TEXT,event_id TEXT,event_version INTEGER,event_hash TEXT,event_entity_registry_snapshot_id TEXT,event_entity_registry_version INTEGER,event_entity_registry_hash TEXT,movement_cutoff_timestamp TEXT,record_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE event_movement_items(movement_record_id TEXT,movement_item_id TEXT,source_event_qualifier_id TEXT,reference_event_qualifier_id TEXT,movement_metric TEXT,movement_direction TEXT,movement_rule_id TEXT,movement_rule_hash TEXT,source_dimension_entity_id TEXT,reference_dimension_entity_id TEXT,canonical_json TEXT,PRIMARY KEY(movement_record_id,movement_item_id),FOREIGN KEY(movement_record_id) REFERENCES event_movement_records);CREATE TABLE event_movement_evidence(movement_record_id TEXT,movement_item_id TEXT,evidence_id TEXT,evidence_hash TEXT,PRIMARY KEY(movement_record_id,movement_item_id,evidence_id),FOREIGN KEY(movement_record_id,movement_item_id) REFERENCES event_movement_items);CREATE TABLE event_movement_dependencies(movement_record_id TEXT,record_type TEXT,record_id TEXT,record_hash TEXT,PRIMARY KEY(movement_record_id,record_type,record_id),FOREIGN KEY(movement_record_id) REFERENCES event_movement_records);""")
  self.connection.execute("INSERT INTO event_movement_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY));self.connection.execute("INSERT INTO event_movement_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json))
  for table in ("event_movement_store_meta","event_movement_policies","event_movement_records","event_movement_items","event_movement_evidence","event_movement_dependencies"):self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _meta(self):
  rows=self.connection.execute("SELECT * FROM event_movement_store_meta").fetchall()
  if len(rows)!=1 or tuple(rows[0])!=(1,STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY):raise EventMovementIntegrityFailure("MOVEMENT_METADATA_MISMATCH")
 def _policy(self):
  rows=self.connection.execute("SELECT * FROM event_movement_policies").fetchall()
  if len(rows)!=1 or tuple(rows[0])!=(POLICY_ID,EXPECTED_POLICY_HASH_V1,self.policy_json):raise EventMovementIntegrityFailure("MOVEMENT_POLICY_SNAPSHOT_MISMATCH")
 def _upstream(self):
  if self.matching_store.integrity_check().get("result")!="PASS":raise EventMovementIntegrityFailure("MATCHING_STORE_INTEGRITY_FAILED")
 def _chain(self,match_id):
  row=self.matching_store.connection.execute("SELECT * FROM dimension_match_records WHERE match_id=?",(match_id,)).fetchone()
  if row is None:raise Stage6EventMovementError("DIMENSION_MATCH_NOT_FOUND")
  match=json.loads(row["canonical_json"])
  if match.get("schema_version")!="STAGE6_EVENT_EXPOSURE_DIMENSION_MATCH_V1" or (match.get("policy_id"),match.get("policy_hash"))!=("S6DIMMATCHPOL_STAGE6_3E_V1",MATCH_POLICY_HASH) or (row["match_id"],row["record_hash"])!=(match["match_id"],match["record_hash"]):raise EventMovementIntegrityFailure("MOVEMENT_MATCH_IDENTITY_INVALID")
  q,t,b,event,registry,ingestion=self.matching_store._chain(match["qualification_id"])
  if (match["event_hash"],match["event_entity_registry_snapshot_id"],match["event_entity_registry_version"],match["event_entity_registry_hash"])!=(event["record_hash"],registry["registry_snapshot_id"],registry["registry_version"],registry["registry_hash"]):raise EventMovementIntegrityFailure("MOVEMENT_EVENT_OR_REGISTRY_IDENTITY_INVALID")
  if parse_utc(registry["as_of_timestamp"],"registry_asof")>parse_utc(match["match_cutoff_timestamp"],"movement_cutoff"):raise Stage6EventMovementError("MOVEMENT_REGISTRY_FROM_FUTURE")
  return match,event,registry,ingestion
 def _authority(self,ingestion,evidence):
  registry=ingestion._verify_persisted_registry_chain("SOURCE",evidence["source_registry_snapshot_id"]);matches=[x for x in registry["sources"] if x["source_id"]==evidence["source_id"]]
  if len(matches)!=1 or matches[0]["authority_level"] not in {"PRIMARY_OFFICIAL","AUTHORITATIVE_INDEPENDENT"}:raise Stage6EventMovementError("MOVEMENT_EVIDENCE_AUTHORITY_INVALID")
 def _resolve(self,match,event,ingestion,inputs):
  if not isinstance(inputs,list):raise Stage6EventMovementError("MOVEMENT_INPUTS_INVALID")
  rules={x["event_type"]:x for x in self.policy["rules"]};rule=rules.get(event["event_type"]);eligible=set(eligible_subjects(match,event["event_type"],rules));qualifiers={x["event_qualifier_id"]:x for x in match["event_qualifiers"]}
  if not eligible and inputs:raise Stage6EventMovementError("NO_ELIGIBLE_MOVEMENT_TARGETS")
  seen=set();items=[];all_evidence={};event_store=self.matching_store.qualification_store.transmission_store.binding_store.event_store
  for raw in inputs:
   if not isinstance(raw,dict) or set(raw)!={"source_event_qualifier_id","reference_event_qualifier_id","movement_metric","movement_direction","evidence_ids"}:raise Stage6EventMovementError("MOVEMENT_INPUT_FIELDS_INVALID")
   source=qualifiers.get(raw["source_event_qualifier_id"])
   if source is None:raise Stage6EventMovementError("MOVEMENT_SOURCE_QUALIFIER_NOT_FOUND")
   if source["event_qualifier_id"] not in eligible:raise Stage6EventMovementError("MOVEMENT_SUBJECT_NOT_EXACT_MATCHED")
   if rule is None or source["dimension_type"]!=rule["dimension_type"] or source["event_field"]!=rule["event_field"]:raise Stage6EventMovementError("MOVEMENT_SOURCE_POLICY_MISMATCH")
   if raw["movement_metric"]!=rule["movement_metric"]:raise Stage6EventMovementError("MOVEMENT_METRIC_INVALID")
   if raw["movement_direction"] not in rule["allowed_movements"]:raise Stage6EventMovementError("MOVEMENT_DIRECTION_INVALID")
   reference=None
   if rule["reference_requirement"]=="REQUIRED":
    if raw["reference_event_qualifier_id"] is None:raise Stage6EventMovementError("CURRENCY_REFERENCE_REQUIRED")
    reference=qualifiers.get(raw["reference_event_qualifier_id"])
    if reference is None:raise Stage6EventMovementError("MOVEMENT_REFERENCE_QUALIFIER_NOT_FOUND")
    if reference["dimension_type"]!="CURRENCY" or reference["event_field"]!="currencies":raise Stage6EventMovementError("CURRENCY_REFERENCE_TYPE_INVALID")
    if source["event_qualifier_id"]==reference["event_qualifier_id"] or source["dimension_entity_id"]==reference["dimension_entity_id"]:raise Stage6EventMovementError("CURRENCY_SUBJECT_REFERENCE_MUST_DIFFER")
    key=(source["event_qualifier_id"],reference["event_qualifier_id"])
   else:
    if raw["reference_event_qualifier_id"] is not None:raise Stage6EventMovementError("COMMODITY_REFERENCE_PROHIBITED")
    key=(source["event_qualifier_id"],)
   if key in seen:raise Stage6EventMovementError("DUPLICATE_MOVEMENT_TARGET")
   seen.add(key);ids=raw["evidence_ids"]
   if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):raise Stage6EventMovementError("MOVEMENT_EVIDENCE_IDS_INVALID")
   ids=sorted(ids)
   if not set(ids)<=set(event["source_evidence_ids"]):raise Stage6EventMovementError("MOVEMENT_EVIDENCE_NOT_EVENT_SUBSET")
   evidence=event_store._load_evidence(ids)
   for record in evidence:
    self._authority(ingestion,record)
    if parse_utc(record["retrieved_timestamp_utc"],"retrieved")>parse_utc(event["last_updated_timestamp"],"event_updated") or parse_utc(event["last_updated_timestamp"],"event_updated")>parse_utc(match["match_cutoff_timestamp"],"movement_cutoff"):raise Stage6EventMovementError("MOVEMENT_EVIDENCE_PIT_INVALID")
    entities=set(record["entity_ids"])
    if source["dimension_entity_id"] not in entities:raise Stage6EventMovementError("MOVEMENT_EVIDENCE_SUBJECT_SUPPORT_MISSING")
    if reference and reference["dimension_entity_id"] not in entities:raise Stage6EventMovementError("MOVEMENT_EVIDENCE_REFERENCE_SUPPORT_MISSING")
    all_evidence[record["evidence_id"]]=record
   refs=sorted(({"evidence_id":x["evidence_id"],"evidence_hash":x["record_hash"]} for x in evidence),key=lambda x:x["evidence_id"])
   items.append({"movement_rule_id":rule["rule_id"],"movement_rule_hash":canonical_hash(rule),"event_type":event["event_type"],"movement_kind":rule["movement_kind"],"source_event_qualifier_id":source["event_qualifier_id"],"source_event_field":source["event_field"],"source_event_dimension_value":source["event_dimension_value"],"source_dimension_type":source["dimension_type"],"source_dimension_entity_id":source["dimension_entity_id"],"reference_event_qualifier_id":reference["event_qualifier_id"] if reference else None,"reference_event_dimension_value":reference["event_dimension_value"] if reference else None,"reference_dimension_entity_id":reference["dimension_entity_id"] if reference else None,"movement_metric":raw["movement_metric"],"movement_direction":raw["movement_direction"],"movement_basis":"EXPLICIT_EVIDENCE_BACKED_DECLARATION","evidence_refs":refs})
  return sorted(items,key=lambda x:(x["source_event_qualifier_id"],x["reference_event_qualifier_id"] or "",x["movement_metric"],x["movement_direction"])),[all_evidence[x] for x in sorted(all_evidence)]
 def _deps(self,match,event,registry,evidence):return [("STAGE6_3E_DIMENSION_MATCH",match["match_id"],match["record_hash"]),("STAGE6_EVENT",f'{event["event_id"]}:v{event["event_version"]}',event["record_hash"]),("EVENT_ENTITY_REGISTRY_SNAPSHOT",registry["registry_snapshot_id"],registry["registry_hash"]),("EVENT_MOVEMENT_POLICY",POLICY_ID,self.policy_hash),*[("EVIDENCE",x["evidence_id"],x["record_hash"]) for x in evidence]]
 def qualify_event_movement(self,*,match_id,movement_inputs):
  self._meta();self._policy();self._upstream();match,event,registry,ingestion=self._chain(match_id);items,evidence=self._resolve(match,event,ingestion,movement_inputs);record=build_event_movement(match=match,event=event,event_registry=registry,movement_items=items,policy=self.policy,policy_hash=self.policy_hash);validate_event_movement(record,match,event,registry,self.policy,self.policy_hash)
  old=self.connection.execute("SELECT canonical_json FROM event_movement_records WHERE match_id=?",(match_id,)).fetchone()
  if old:
   if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","movement":record}
   raise EventMovementConflict("MATCH_ALREADY_HAS_DISTINCT_EVENT_MOVEMENT_RECORD")
  deps=self._deps(match,event,registry,evidence)
  with self.connection:
   self.connection.execute("INSERT INTO event_movement_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(record["movement_record_id"],match["match_id"],match["record_hash"],event["event_id"],event["event_version"],event["record_hash"],registry["registry_snapshot_id"],registry["registry_version"],registry["registry_hash"],record["movement_cutoff_timestamp"],record["record_hash"],canonical_json(record)))
   self.connection.executemany("INSERT INTO event_movement_items VALUES(?,?,?,?,?,?,?,?,?,?,?)",[(record["movement_record_id"],x["movement_item_id"],x["source_event_qualifier_id"],x["reference_event_qualifier_id"],x["movement_metric"],x["movement_direction"],x["movement_rule_id"],x["movement_rule_hash"],x["source_dimension_entity_id"],x["reference_dimension_entity_id"],canonical_json(x)) for x in record["movement_items"]])
   self.connection.executemany("INSERT INTO event_movement_evidence VALUES(?,?,?,?)",[(record["movement_record_id"],x["movement_item_id"],r["evidence_id"],r["evidence_hash"]) for x in record["movement_items"] for r in x["evidence_refs"]])
   self.connection.executemany("INSERT INTO event_movement_dependencies VALUES(?,?,?,?)",[(record["movement_record_id"],*x) for x in deps])
  return {"status":"CREATED","movement":record}
 def integrity_check(self):
  self._meta();self._policy();self._upstream()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise EventMovementIntegrityFailure("MOVEMENT_SQLITE_INTEGRITY_FAILED")
  tables=("event_movement_store_meta","event_movement_policies","event_movement_records","event_movement_items","event_movement_evidence","event_movement_dependencies")
  for table in tables:
   names={x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
   if names!={f"protect_{table}_update",f"protect_{table}_delete"}:raise EventMovementIntegrityFailure("MOVEMENT_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM event_movement_records"):
   count+=1;stored=json.loads(row["canonical_json"]);match,event,registry,ingestion=self._chain(stored["match_id"]);inputs=[{"source_event_qualifier_id":x["source_event_qualifier_id"],"reference_event_qualifier_id":x["reference_event_qualifier_id"],"movement_metric":x["movement_metric"],"movement_direction":x["movement_direction"],"evidence_ids":[r["evidence_id"] for r in x["evidence_refs"]]} for x in stored["movement_items"]];items,evidence=self._resolve(match,event,ingestion,inputs);replay=build_event_movement(match=match,event=event,event_registry=registry,movement_items=items,policy=self.policy,policy_hash=self.policy_hash)
   if stored!=replay or row["canonical_json"]!=canonical_json(stored):raise EventMovementIntegrityFailure("MOVEMENT_REPLAY_MISMATCH")
   typed=(row["movement_record_id"],row["match_id"],row["match_hash"],row["event_id"],row["event_version"],row["event_hash"],row["event_entity_registry_snapshot_id"],row["event_entity_registry_version"],row["event_entity_registry_hash"],row["movement_cutoff_timestamp"],row["record_hash"]);wanted=(stored["movement_record_id"],stored["match_id"],stored["match_hash"],stored["event_id"],stored["event_version"],stored["event_hash"],stored["event_entity_registry_snapshot_id"],stored["event_entity_registry_version"],stored["event_entity_registry_hash"],stored["movement_cutoff_timestamp"],stored["record_hash"])
   if typed!=wanted:raise EventMovementIntegrityFailure("MOVEMENT_TYPED_RECORD_MISMATCH")
   irows=self.connection.execute("SELECT * FROM event_movement_items WHERE movement_record_id=? ORDER BY source_event_qualifier_id,COALESCE(reference_event_qualifier_id,''),movement_metric,movement_direction",(stored["movement_record_id"],)).fetchall();child=[json.loads(x["canonical_json"]) for x in irows]
   if child!=stored["movement_items"] or any((r["movement_item_id"],r["source_event_qualifier_id"],r["reference_event_qualifier_id"],r["movement_metric"],r["movement_direction"],r["movement_rule_id"],r["movement_rule_hash"],r["source_dimension_entity_id"],r["reference_dimension_entity_id"],r["canonical_json"])!=(x["movement_item_id"],x["source_event_qualifier_id"],x["reference_event_qualifier_id"],x["movement_metric"],x["movement_direction"],x["movement_rule_id"],x["movement_rule_hash"],x["source_dimension_entity_id"],x["reference_dimension_entity_id"],canonical_json(x)) for r,x in zip(irows,child)):raise EventMovementIntegrityFailure("MOVEMENT_ITEM_COVERAGE_MISMATCH")
   refs={(x["movement_item_id"],x["evidence_id"],x["evidence_hash"]) for x in self.connection.execute("SELECT * FROM event_movement_evidence WHERE movement_record_id=?",(stored["movement_record_id"],))};wanted_refs={(x["movement_item_id"],r["evidence_id"],r["evidence_hash"]) for x in stored["movement_items"] for r in x["evidence_refs"]}
   if refs!=wanted_refs:raise EventMovementIntegrityFailure("MOVEMENT_EVIDENCE_COVERAGE_MISMATCH")
   actual={(x["record_type"],x["record_id"]):x["record_hash"] for x in self.connection.execute("SELECT * FROM event_movement_dependencies WHERE movement_record_id=?",(stored["movement_record_id"],))};expected={(a,b):c for a,b,c in self._deps(match,event,registry,evidence)}
   if actual!=expected:raise EventMovementIntegrityFailure("MOVEMENT_DEPENDENCY_MISMATCH")
  return {"result":"PASS","movements":count,"authority":AUTHORITY,"policy_hash":self.policy_hash}
