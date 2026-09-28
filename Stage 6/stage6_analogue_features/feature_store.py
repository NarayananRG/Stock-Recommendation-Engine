import json,sqlite3
from pathlib import Path
from stage6_company_effect import CompanyEffectStore
from stage6_events import EventStore
from stage6_ingestion.canonical import canonical_json
from stage6_market_context import MarketContextStore
from .errors import AnalogueFeatureConflict,AnalogueFeatureIntegrityFailure,Stage6AnalogueFeatureError
from .feature_builder import SCHEMA_VERSION,build_feature_snapshot
from .feature_validation import validate_feature_snapshot
from .policy import AUTHORITY,BASELINE_COMMIT,EXPECTED_FEATURE_CONTRACT_HASH_V1,EXPECTED_POLICY_HASH_V1,FEATURE_CONTRACT_VERSION,POLICY_ID,PROCESSOR_VERSION,load_feature_contract,load_policy
STORE_SCHEMA_VERSION="STAGE6_4B_ANALOGUE_FEATURE_STORE_V1";TABLES=("analogue_feature_store_meta","analogue_feature_policies","analogue_feature_contracts","analogue_feature_snapshots","analogue_feature_dependencies")
class AnalogueFeatureStore:
 def __init__(self,database:Path,company_effect_store:CompanyEffectStore,market_context_store:MarketContextStore,event_store:EventStore):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.company_effect_store=company_effect_store;self.market_context_store=market_context_store;self.event_store=event_store;self.policy,self.policy_json,self.policy_hash=load_policy();self.feature_contract,self.feature_contract_json,self.feature_contract_hash=load_feature_contract();new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._meta();self._policy();self._contract()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE analogue_feature_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,snapshot_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL);CREATE TABLE analogue_feature_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE analogue_feature_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE analogue_feature_snapshots(feature_snapshot_id TEXT PRIMARY KEY,logical_feature_key TEXT UNIQUE NOT NULL,company_entity_id TEXT NOT NULL,company_effect_record_id TEXT NOT NULL,company_effect_record_hash TEXT NOT NULL,event_id TEXT NOT NULL,event_version INTEGER NOT NULL,event_hash TEXT NOT NULL,market_context_record_id TEXT NOT NULL,market_context_record_hash TEXT NOT NULL,selection_cutoff TEXT NOT NULL,selection_input_hash TEXT NOT NULL,feature_snapshot_hash TEXT UNIQUE NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE analogue_feature_dependencies(feature_snapshot_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(feature_snapshot_id,record_type,record_id),FOREIGN KEY(feature_snapshot_id) REFERENCES analogue_feature_snapshots);""")
  self.connection.execute("INSERT INTO analogue_feature_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY));self.connection.execute("INSERT INTO analogue_feature_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json));self.connection.execute("INSERT INTO analogue_feature_contracts VALUES(?,?,?)",(FEATURE_CONTRACT_VERSION,self.feature_contract_hash,self.feature_contract_json))
  for t in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{t}_update BEFORE UPDATE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{t}_delete BEFORE DELETE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _meta(self):
  r=self.connection.execute("SELECT * FROM analogue_feature_store_meta").fetchall()
  if len(r)!=1 or tuple(r[0])!=(1,STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY):raise AnalogueFeatureIntegrityFailure("ANALOGUE_FEATURE_METADATA_MISMATCH")
 def _policy(self):
  r=self.connection.execute("SELECT * FROM analogue_feature_policies").fetchall()
  if len(r)!=1 or tuple(r[0])!=(POLICY_ID,EXPECTED_POLICY_HASH_V1,self.policy_json):raise AnalogueFeatureIntegrityFailure("ANALOGUE_FEATURE_POLICY_MISMATCH")
 def _contract(self):
  r=self.connection.execute("SELECT * FROM analogue_feature_contracts").fetchall()
  if len(r)!=1 or tuple(r[0])!=(FEATURE_CONTRACT_VERSION,EXPECTED_FEATURE_CONTRACT_HASH_V1,self.feature_contract_json):raise AnalogueFeatureIntegrityFailure("ANALOGUE_FEATURE_CONTRACT_MISMATCH")
 def _load(self,effect_id,market_id):
  if self.company_effect_store.integrity_check()["result"]!="PASS":raise AnalogueFeatureIntegrityFailure("COMPANY_EFFECT_STORE_INTEGRITY_REQUIRED")
  erow=self.company_effect_store.connection.execute("SELECT canonical_json FROM company_effect_records WHERE company_effect_record_id=?",(effect_id,)).fetchone()
  if erow is None:raise Stage6AnalogueFeatureError("COMPANY_EFFECT_NOT_FOUND")
  effect=json.loads(erow[0]);expected=("STAGE6_EVENT_COMPANY_EFFECT_V1","S6COMEFFPOL_STAGE6_3I_V1","3a92f28b24d46a8b7f6ed1ac9a77562355ae751dfce23e23ed4a9ba4dfc21786","STAGE6_3I_COMPANY_EFFECT_SYNTHESIZER_V1","SHADOW_ONLY")
  if (effect.get("schema_version"),effect.get("policy_id"),effect.get("policy_hash"),effect.get("processor_version"),effect.get("authority"))!=expected:raise AnalogueFeatureIntegrityFailure("COMPANY_EFFECT_IDENTITY_INVALID")
  source,_=self.company_effect_store._load(effect["source_family"],effect["source_record_id"]);source_cutoff=source["direction_cutoff_timestamp"] if effect["source_family"]=="STAGE6_3F_DIRECTION" else source["path_effect_cutoff_timestamp"]
  if self.market_context_store.integrity_check()["result"]!="PASS":raise AnalogueFeatureIntegrityFailure("MARKET_CONTEXT_STORE_INTEGRITY_REQUIRED")
  mrow=self.market_context_store.connection.execute("SELECT canonical_json FROM market_context_records WHERE market_context_record_id=?",(market_id,)).fetchone()
  if mrow is None:raise Stage6AnalogueFeatureError("MARKET_CONTEXT_NOT_FOUND")
  market=json.loads(mrow[0]);mexpected=("STAGE6_MARKET_CONTEXT_V2","S6MCTXPOL_STAGE6_4A_V1","422fa524a21a09a29ca0caa94a382ea056fba958d7c1a0a05c465740cb791d94","STAGE6_4A_MARKET_CONTEXT_MATERIALIZER_V1","SHADOW_ONLY")
  if (market["contract_payload"].get("schema_version"),market.get("policy_id"),market.get("policy_hash"),market.get("processor_version"),market.get("authority"))!=mexpected:raise AnalogueFeatureIntegrityFailure("MARKET_CONTEXT_IDENTITY_INVALID")
  if effect["company_entity_id"]!=market["company_entity_id"]:raise Stage6AnalogueFeatureError("ANALOGUE_COMPANY_IDENTITY_MISMATCH")
  if self.event_store.integrity_check()["result"]!="PASS":raise AnalogueFeatureIntegrityFailure("EVENT_STORE_INTEGRITY_REQUIRED")
  event=self.event_store.get_event(effect["event_id"],effect["event_version"])
  if event.get("schema_version")!="STAGE6_EVENT_V1" or (event["event_id"],event["event_version"],event["record_hash"],event["event_type"])!=(effect["event_id"],effect["event_version"],effect["event_hash"],effect["event_type"]):raise AnalogueFeatureIntegrityFailure("ANALOGUE_EVENT_IDENTITY_INVALID")
  return effect,market,event,source_cutoff
 def _deps(self,r):return [("STAGE6_3I_COMPANY_EFFECT",r["company_effect_record_id"],r["company_effect_record_hash"]),("STAGE6_4A_MARKET_CONTEXT",r["market_context_record_id"],r["market_context_record_hash"]),("STAGE6_EVENT",f'{r["event_id"]}:v{r["event_version"]}',r["event_hash"]),("STAGE6_4B_POLICY",POLICY_ID,self.policy_hash),("STAGE6_4B_FEATURE_CONTRACT",FEATURE_CONTRACT_VERSION,self.feature_contract_hash)]
 def freeze(self,*,company_effect_record_id,market_context_record_id):
  self._meta();self._policy();self._contract();effect,market,event,cutoff=self._load(company_effect_record_id,market_context_record_id);record=build_feature_snapshot(effect=effect,market=market,event=event,source_cutoff=cutoff,policy=self.policy,policy_hash=self.policy_hash,feature_contract_hash=self.feature_contract_hash);validate_feature_snapshot(record);old=self.connection.execute("SELECT canonical_json FROM analogue_feature_snapshots WHERE logical_feature_key=?",(record["logical_feature_key"],)).fetchone()
  if old:
   if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","feature_snapshot":record}
   raise AnalogueFeatureConflict("ANALOGUE_FEATURE_LOGICAL_IDENTITY_CONFLICT")
  with self.connection:
   self.connection.execute("INSERT INTO analogue_feature_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(record["feature_snapshot_id"],record["logical_feature_key"],record["company_entity_id"],record["company_effect_record_id"],record["company_effect_record_hash"],record["event_id"],record["event_version"],record["event_hash"],record["market_context_record_id"],record["market_context_record_hash"],record["selection_cutoff"],record["selection_input_hash"],record["feature_snapshot_hash"],record["record_hash"],canonical_json(record)));self.connection.executemany("INSERT INTO analogue_feature_dependencies VALUES(?,?,?,?)",[(record["feature_snapshot_id"],*x) for x in self._deps(record)])
  return {"status":"CREATED","feature_snapshot":record}
 def integrity_check(self):
  self._meta();self._policy();self._contract()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise AnalogueFeatureIntegrityFailure("ANALOGUE_FEATURE_SQLITE_INTEGRITY_FAILED")
  for t in TABLES:
   if {x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,))}!={f"protect_{t}_update",f"protect_{t}_delete"}:raise AnalogueFeatureIntegrityFailure("ANALOGUE_FEATURE_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM analogue_feature_snapshots"):
   count+=1;stored=json.loads(row["canonical_json"]);validate_feature_snapshot(stored);effect,market,event,cutoff=self._load(stored["company_effect_record_id"],stored["market_context_record_id"]);replay=build_feature_snapshot(effect=effect,market=market,event=event,source_cutoff=cutoff,policy=self.policy,policy_hash=self.policy_hash,feature_contract_hash=self.feature_contract_hash)
   if stored!=replay or row["canonical_json"]!=canonical_json(stored):raise AnalogueFeatureIntegrityFailure("ANALOGUE_FEATURE_REPLAY_MISMATCH")
   typed=(row["feature_snapshot_id"],row["logical_feature_key"],row["company_entity_id"],row["company_effect_record_id"],row["company_effect_record_hash"],row["event_id"],row["event_version"],row["event_hash"],row["market_context_record_id"],row["market_context_record_hash"],row["selection_cutoff"],row["selection_input_hash"],row["feature_snapshot_hash"],row["record_hash"]);wanted=tuple(stored[x] for x in ("feature_snapshot_id","logical_feature_key","company_entity_id","company_effect_record_id","company_effect_record_hash","event_id","event_version","event_hash","market_context_record_id","market_context_record_hash","selection_cutoff","selection_input_hash","feature_snapshot_hash","record_hash"))
   if typed!=wanted:raise AnalogueFeatureIntegrityFailure("ANALOGUE_FEATURE_TYPED_RECORD_MISMATCH")
   actual={(x["record_type"],x["record_id"]):x["record_hash"] for x in self.connection.execute("SELECT * FROM analogue_feature_dependencies WHERE feature_snapshot_id=?",(stored["feature_snapshot_id"],))};expected={(a,b):c for a,b,c in self._deps(stored)}
   if actual!=expected:raise AnalogueFeatureIntegrityFailure("ANALOGUE_FEATURE_DEPENDENCY_MISMATCH")
  return {"result":"PASS","feature_snapshots":count,"authority":AUTHORITY,"policy_hash":self.policy_hash,"feature_contract_hash":self.feature_contract_hash}
