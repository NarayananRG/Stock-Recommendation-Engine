import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json,parse_utc
from stage6_exposure_binding.binding_builder import assertion_hash
from stage6_event_movement import EventMovementStore
from stage6_event_movement.policy import EXPECTED_POLICY_HASH_V1 as MOVEMENT_POLICY_HASH
from .errors import MovementPathEffectConflict,MovementPathEffectIntegrityFailure,Stage6MovementPathEffectError
from .path_effect_builder import SCHEMA_VERSION,build_path_effect,eligible_pairs
from .path_effect_validation import validate_path_effect
from .policy import AUTHORITY,EXPECTED_POLICY_HASH_V1,POLICY_ID,PROCESSOR_VERSION,load_policy
STORE_SCHEMA_VERSION="STAGE6_3H_MOVEMENT_PATH_EFFECT_STORE_V1";BASELINE_COMMIT="8dc5150020c8a5b2f93e7ca42a8fd25478539417"
class MovementPathEffectStore:
 def __init__(self,database:Path,movement_store:EventMovementStore):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.movement_store=movement_store;self.policy,self.policy_json,self.policy_hash=load_policy()
  if self.policy_hash!=EXPECTED_POLICY_HASH_V1:raise MovementPathEffectIntegrityFailure("PATH_EFFECT_EXPECTED_POLICY_HASH_MISMATCH")
  new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._meta();self._policy()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE movement_path_effect_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT,path_effect_schema_version TEXT,baseline_commit TEXT,processor_version TEXT,authority TEXT);CREATE TABLE movement_path_effect_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE movement_path_effect_records(path_effect_record_id TEXT PRIMARY KEY,movement_record_id TEXT UNIQUE,movement_record_hash TEXT,match_id TEXT,match_hash TEXT,exposure_id TEXT,exposure_version INTEGER,exposure_hash TEXT,path_effect_cutoff_timestamp TEXT,record_hash TEXT UNIQUE,canonical_json TEXT);CREATE TABLE movement_path_effect_items(path_effect_record_id TEXT,path_effect_item_id TEXT,path_effect_pair_id TEXT,source_path_id TEXT,movement_item_id TEXT,effect_direction TEXT,effect_rule_id TEXT,effect_rule_hash TEXT,assertion_hash TEXT,canonical_json TEXT,PRIMARY KEY(path_effect_record_id,path_effect_item_id),FOREIGN KEY(path_effect_record_id) REFERENCES movement_path_effect_records);CREATE TABLE movement_path_effect_evidence(path_effect_record_id TEXT,path_effect_item_id TEXT,evidence_id TEXT,evidence_hash TEXT,PRIMARY KEY(path_effect_record_id,path_effect_item_id,evidence_id),FOREIGN KEY(path_effect_record_id,path_effect_item_id) REFERENCES movement_path_effect_items);CREATE TABLE movement_path_effect_results(path_effect_record_id TEXT,path_effect_pair_id TEXT,source_path_id TEXT,movement_item_id TEXT,eligibility_status TEXT,effect_direction TEXT,canonical_json TEXT,PRIMARY KEY(path_effect_record_id,path_effect_pair_id),FOREIGN KEY(path_effect_record_id) REFERENCES movement_path_effect_records);CREATE TABLE movement_path_effect_dependencies(path_effect_record_id TEXT,record_type TEXT,record_id TEXT,record_hash TEXT,PRIMARY KEY(path_effect_record_id,record_type,record_id),FOREIGN KEY(path_effect_record_id) REFERENCES movement_path_effect_records);""")
  self.connection.execute("INSERT INTO movement_path_effect_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY));self.connection.execute("INSERT INTO movement_path_effect_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json))
  for table in ("movement_path_effect_store_meta","movement_path_effect_policies","movement_path_effect_records","movement_path_effect_items","movement_path_effect_evidence","movement_path_effect_results","movement_path_effect_dependencies"):self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _meta(self):
  rows=self.connection.execute("SELECT * FROM movement_path_effect_store_meta").fetchall()
  if len(rows)!=1 or tuple(rows[0])!=(1,STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY):raise MovementPathEffectIntegrityFailure("PATH_EFFECT_METADATA_MISMATCH")
 def _policy(self):
  rows=self.connection.execute("SELECT * FROM movement_path_effect_policies").fetchall()
  if len(rows)!=1 or tuple(rows[0])!=(POLICY_ID,EXPECTED_POLICY_HASH_V1,self.policy_json):raise MovementPathEffectIntegrityFailure("PATH_EFFECT_POLICY_SNAPSHOT_MISMATCH")
 def _upstream(self):
  if self.movement_store.integrity_check().get("result")!="PASS":raise MovementPathEffectIntegrityFailure("EVENT_MOVEMENT_STORE_INTEGRITY_FAILED")
 def _chain(self,movement_record_id):
  row=self.movement_store.connection.execute("SELECT * FROM event_movement_records WHERE movement_record_id=?",(movement_record_id,)).fetchone()
  if row is None:raise Stage6MovementPathEffectError("EVENT_MOVEMENT_RECORD_NOT_FOUND")
  movement=json.loads(row["canonical_json"])
  if movement.get("schema_version")!="STAGE6_EVENT_DIMENSION_MOVEMENT_V1" or movement.get("processor_version")!="STAGE6_3G_EVENT_MOVEMENT_QUALIFIER_V1" or (movement.get("policy_id"),movement.get("policy_hash"),movement.get("authority"))!=("S6MOVPOL_STAGE6_3G_V1",MOVEMENT_POLICY_HASH,"SHADOW_ONLY") or (row["movement_record_id"],row["record_hash"])!=(movement["movement_record_id"],movement["record_hash"]):raise MovementPathEffectIntegrityFailure("EVENT_MOVEMENT_IDENTITY_INVALID")
  match,event,registry,ingestion=self.movement_store._chain(movement["match_id"])
  if (movement["match_hash"],movement["event_id"],movement["event_version"],movement["event_hash"])!=(match["record_hash"],event["event_id"],event["event_version"],event["record_hash"]):raise MovementPathEffectIntegrityFailure("PATH_EFFECT_MOVEMENT_CHAIN_INVALID")
  binding_store=self.movement_store.matching_store.qualification_store.transmission_store.binding_store;exposure=binding_store._exposure(match["exposure_id"],match["exposure_version"])
  if exposure["record_hash"]!=match["exposure_hash"] or exposure["company_entity_id"]!=match["company_entity_id"]:raise MovementPathEffectIntegrityFailure("PATH_EFFECT_EXPOSURE_IDENTITY_INVALID")
  return movement,match,exposure
 def _resolve(self,movement,match,exposure,inputs):
  if not isinstance(inputs,list):raise Stage6MovementPathEffectError("PATH_EFFECT_INPUTS_INVALID")
  pairs={x["path_effect_pair_id"]:x for x in eligible_pairs(match,movement,self.policy)};paths={x["source_path_id"]:x for x in match["path_matches"]};movements={x["movement_item_id"]:x for x in movement["movement_items"]};rules={x["event_type"]:x for x in self.policy["rules"]};rule=rules.get(movement["event_type"])
  if not pairs and inputs:raise Stage6MovementPathEffectError("NO_ELIGIBLE_PATH_EFFECTS")
  assertions={assertion_hash(x):x for x in exposure["assertions"]};seen=set();items=[];all_evidence={};exposure_store=self.movement_store.matching_store.qualification_store.transmission_store.binding_store.exposure_store
  for raw in inputs:
   if not isinstance(raw,dict) or set(raw)!={"source_path_id","movement_item_id","effect_direction","evidence_ids"}:raise Stage6MovementPathEffectError("PATH_EFFECT_INPUT_FIELDS_INVALID")
   pair=next((x for x in pairs.values() if x["source_path_id"]==raw["source_path_id"] and x["movement_item_id"]==raw["movement_item_id"]),None)
   if pair is None:raise Stage6MovementPathEffectError("PATH_MOVEMENT_PAIR_NOT_ELIGIBLE")
   if pair["path_effect_pair_id"] in seen:raise Stage6MovementPathEffectError("DUPLICATE_PATH_MOVEMENT_EFFECT")
   seen.add(pair["path_effect_pair_id"]);path=paths[raw["source_path_id"]];movement_item=movements[raw["movement_item_id"]]
   if raw["effect_direction"] not in rule["allowed_effect_directions"]:raise Stage6MovementPathEffectError("EFFECT_DIRECTION_INVALID")
   if movement_item["movement_direction"]=="UNKNOWN" and raw["effect_direction"]!="UNKNOWN":raise Stage6MovementPathEffectError("UNKNOWN_MOVEMENT_REQUIRES_UNKNOWN_EFFECT")
   ids=raw["evidence_ids"]
   if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):raise Stage6MovementPathEffectError("PATH_EFFECT_EVIDENCE_IDS_INVALID")
   ids=sorted(ids);assertion=assertions.get(path["assertion_hash"])
   if assertion is None:raise MovementPathEffectIntegrityFailure("PATH_EFFECT_ASSERTION_MISSING")
   if not set(ids)<=set(assertion["evidence_ids"]):raise Stage6MovementPathEffectError("PATH_EFFECT_EVIDENCE_NOT_ASSERTION_SUBSET")
   evidence=exposure_store._evidence(ids,exposure["data_cutoff_timestamp"])
   if parse_utc(exposure["data_cutoff_timestamp"],"exposure_cutoff")>parse_utc(movement["movement_cutoff_timestamp"],"path_effect_cutoff"):raise Stage6MovementPathEffectError("PATH_EFFECT_EXPOSURE_FROM_FUTURE")
   for record in evidence:
    entities=set(record["entity_ids"])
    if match["company_entity_id"] not in entities:raise Stage6MovementPathEffectError("PATH_EFFECT_EVIDENCE_COMPANY_SUPPORT_MISSING")
    if movement_item["source_dimension_entity_id"] not in entities:raise Stage6MovementPathEffectError("PATH_EFFECT_EVIDENCE_DIMENSION_SUPPORT_MISSING")
    all_evidence[record["evidence_id"]]=record
   refs=sorted(({"evidence_id":x["evidence_id"],"evidence_hash":x["record_hash"]} for x in evidence),key=lambda x:x["evidence_id"])
   items.append({**pair,"source_rule_id":path["source_rule_id"],"source_rule_hash":path["source_rule_hash"],"assertion_hash":path["assertion_hash"],"exposure_type":path["exposure_type"],"dimension_match_status":path["dimension_match_status"],"matched_dimension_entity_ids":path["matched_dimension_entity_ids"],"effect_direction":raw["effect_direction"],"effect_basis":"EXPLICIT_EVIDENCE_BACKED_DECLARATION","evidence_refs":refs})
  return sorted(items,key=lambda x:(x["source_path_id"],x["movement_item_id"])),[all_evidence[x] for x in sorted(all_evidence)]
 def _deps(self,movement,match,exposure,evidence):return [("STAGE6_3G_EVENT_MOVEMENT",movement["movement_record_id"],movement["record_hash"]),("STAGE6_3E_DIMENSION_MATCH",match["match_id"],match["record_hash"]),("STAGE6_EXPOSURE",f'{exposure["exposure_id"]}:v{exposure["exposure_version"]}',exposure["record_hash"]),("MOVEMENT_PATH_EFFECT_POLICY",POLICY_ID,self.policy_hash),*[("EVIDENCE",x["evidence_id"],x["record_hash"]) for x in evidence]]
 def evaluate_path_effect(self,*,movement_record_id,effect_inputs):
  self._meta();self._policy();self._upstream();movement,match,exposure=self._chain(movement_record_id);items,evidence=self._resolve(movement,match,exposure,effect_inputs);record=build_path_effect(movement=movement,match=match,exposure=exposure,effect_items=items,policy=self.policy,policy_hash=self.policy_hash);validate_path_effect(record,movement,match,exposure,self.policy,self.policy_hash);old=self.connection.execute("SELECT canonical_json FROM movement_path_effect_records WHERE movement_record_id=?",(movement_record_id,)).fetchone()
  if old:
   if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","path_effect":record}
   raise MovementPathEffectConflict("MOVEMENT_RECORD_ALREADY_HAS_DISTINCT_PATH_EFFECT_RECORD")
  deps=self._deps(movement,match,exposure,evidence)
  with self.connection:
   self.connection.execute("INSERT INTO movement_path_effect_records VALUES(?,?,?,?,?,?,?,?,?,?,?)",(record["path_effect_record_id"],movement["movement_record_id"],movement["record_hash"],match["match_id"],match["record_hash"],exposure["exposure_id"],exposure["exposure_version"],exposure["record_hash"],record["path_effect_cutoff_timestamp"],record["record_hash"],canonical_json(record)))
   self.connection.executemany("INSERT INTO movement_path_effect_items VALUES(?,?,?,?,?,?,?,?,?,?)",[(record["path_effect_record_id"],x["path_effect_item_id"],x["path_effect_pair_id"],x["source_path_id"],x["movement_item_id"],x["effect_direction"],x["effect_rule_id"],x["effect_rule_hash"],x["assertion_hash"],canonical_json(x)) for x in record["effect_items"]])
   self.connection.executemany("INSERT INTO movement_path_effect_evidence VALUES(?,?,?,?)",[(record["path_effect_record_id"],x["path_effect_item_id"],r["evidence_id"],r["evidence_hash"]) for x in record["effect_items"] for r in x["evidence_refs"]])
   self.connection.executemany("INSERT INTO movement_path_effect_results VALUES(?,?,?,?,?,?,?)",[(record["path_effect_record_id"],x["path_effect_pair_id"],x["source_path_id"],x["movement_item_id"],x["eligibility_status"],x["effect_direction"],canonical_json(x)) for x in record["path_effect_results"]])
   self.connection.executemany("INSERT INTO movement_path_effect_dependencies VALUES(?,?,?,?)",[(record["path_effect_record_id"],*x) for x in deps])
  return {"status":"CREATED","path_effect":record}
 def integrity_check(self):
  self._meta();self._policy();self._upstream()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise MovementPathEffectIntegrityFailure("PATH_EFFECT_SQLITE_INTEGRITY_FAILED")
  tables=("movement_path_effect_store_meta","movement_path_effect_policies","movement_path_effect_records","movement_path_effect_items","movement_path_effect_evidence","movement_path_effect_results","movement_path_effect_dependencies")
  for table in tables:
   names={x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}
   if names!={f"protect_{table}_update",f"protect_{table}_delete"}:raise MovementPathEffectIntegrityFailure("PATH_EFFECT_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM movement_path_effect_records"):
   count+=1;stored=json.loads(row["canonical_json"]);movement,match,exposure=self._chain(stored["movement_record_id"]);inputs=[{"source_path_id":x["source_path_id"],"movement_item_id":x["movement_item_id"],"effect_direction":x["effect_direction"],"evidence_ids":[r["evidence_id"] for r in x["evidence_refs"]]} for x in stored["effect_items"]];items,evidence=self._resolve(movement,match,exposure,inputs);replay=build_path_effect(movement=movement,match=match,exposure=exposure,effect_items=items,policy=self.policy,policy_hash=self.policy_hash)
   if stored!=replay or row["canonical_json"]!=canonical_json(stored):raise MovementPathEffectIntegrityFailure("PATH_EFFECT_REPLAY_MISMATCH")
   typed=(row["path_effect_record_id"],row["movement_record_id"],row["movement_record_hash"],row["match_id"],row["match_hash"],row["exposure_id"],row["exposure_version"],row["exposure_hash"],row["path_effect_cutoff_timestamp"],row["record_hash"]);wanted=(stored["path_effect_record_id"],stored["movement_record_id"],stored["movement_record_hash"],stored["match_id"],stored["match_hash"],stored["exposure_id"],stored["exposure_version"],stored["exposure_hash"],stored["path_effect_cutoff_timestamp"],stored["record_hash"])
   if typed!=wanted:raise MovementPathEffectIntegrityFailure("PATH_EFFECT_TYPED_RECORD_MISMATCH")
   irows=self.connection.execute("SELECT * FROM movement_path_effect_items WHERE path_effect_record_id=? ORDER BY source_path_id,movement_item_id",(stored["path_effect_record_id"],)).fetchall();child=[json.loads(x["canonical_json"]) for x in irows]
   if child!=stored["effect_items"]:raise MovementPathEffectIntegrityFailure("PATH_EFFECT_ITEM_COVERAGE_MISMATCH")
   refs={(x["path_effect_item_id"],x["evidence_id"],x["evidence_hash"]) for x in self.connection.execute("SELECT * FROM movement_path_effect_evidence WHERE path_effect_record_id=?",(stored["path_effect_record_id"],))};wanted_refs={(x["path_effect_item_id"],r["evidence_id"],r["evidence_hash"]) for x in stored["effect_items"] for r in x["evidence_refs"]}
   if refs!=wanted_refs:raise MovementPathEffectIntegrityFailure("PATH_EFFECT_EVIDENCE_COVERAGE_MISMATCH")
   results=[json.loads(x["canonical_json"]) for x in self.connection.execute("SELECT * FROM movement_path_effect_results WHERE path_effect_record_id=? ORDER BY source_path_id,movement_item_id",(stored["path_effect_record_id"],))]
   if results!=stored["path_effect_results"]:raise MovementPathEffectIntegrityFailure("PATH_EFFECT_RESULT_COVERAGE_MISMATCH")
   actual={(x["record_type"],x["record_id"]):x["record_hash"] for x in self.connection.execute("SELECT * FROM movement_path_effect_dependencies WHERE path_effect_record_id=?",(stored["path_effect_record_id"],))};expected={(a,b):c for a,b,c in self._deps(movement,match,exposure,evidence)}
   if actual!=expected:raise MovementPathEffectIntegrityFailure("PATH_EFFECT_DEPENDENCY_MISMATCH")
  return {"result":"PASS","path_effects":count,"authority":AUTHORITY,"policy_hash":self.policy_hash}
