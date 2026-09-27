import json,sqlite3
from datetime import date
from pathlib import Path
from stage6_ingestion import IngestionStore,resolve_entity,resolve_ticker
from stage6_ingestion.canonical import canonical_json,parse_utc
from stage6_ingestion.errors import ResolutionError
from .errors import MarketContextConflict,MarketContextIntegrityFailure,Stage6MarketContextError
from .market_context_builder import SCHEMA_VERSION,build_record,normalize_payload
from .market_context_validation import validate_record
from .policy import AUTHORITY,BASELINE_COMMIT,EXPECTED_POLICY_HASH_V1,POLICY_ID,PROCESSOR_VERSION,load_policy
STORE_SCHEMA_VERSION="STAGE6_4A_MARKET_CONTEXT_STORE_V1"
TABLES=("market_context_store_meta","market_context_policies","market_context_records","market_context_evidence","market_context_dependencies")
def _active(mapping,cutoff):
 d=cutoff.date();start=date.fromisoformat(mapping["effective_from"]);end=date.fromisoformat(mapping["effective_to"]) if mapping.get("effective_to") else None
 return start<=d and (end is None or d<=end)
class MarketContextStore:
 def __init__(self,database:Path,ingestion_store:IngestionStore):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.ingestion_store=ingestion_store;self.policy,self.policy_json,self.policy_hash=load_policy();new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._meta();self._policy()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE market_context_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,contract_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL);CREATE TABLE market_context_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE market_context_records(market_context_record_id TEXT PRIMARY KEY,logical_context_key TEXT UNIQUE NOT NULL,company_entity_id TEXT NOT NULL,company_entity_record_hash TEXT NOT NULL,entity_registry_snapshot_id TEXT NOT NULL,entity_registry_hash TEXT NOT NULL,exchange TEXT NOT NULL,ticker TEXT NOT NULL,as_of_timestamp TEXT NOT NULL,data_cutoff_timestamp TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE market_context_evidence(market_context_record_id TEXT NOT NULL,evidence_id TEXT NOT NULL,evidence_hash TEXT NOT NULL,canonical_json TEXT NOT NULL,PRIMARY KEY(market_context_record_id,evidence_id),FOREIGN KEY(market_context_record_id) REFERENCES market_context_records);CREATE TABLE market_context_dependencies(market_context_record_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(market_context_record_id,record_type,record_id),FOREIGN KEY(market_context_record_id) REFERENCES market_context_records);""")
  self.connection.execute("INSERT INTO market_context_store_meta VALUES(1,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY));self.connection.execute("INSERT INTO market_context_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json))
  for t in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{t}_update BEFORE UPDATE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{t}_delete BEFORE DELETE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _meta(self):
  rows=self.connection.execute("SELECT * FROM market_context_store_meta").fetchall()
  if len(rows)!=1 or tuple(rows[0])!=(1,STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY):raise MarketContextIntegrityFailure("MARKET_CONTEXT_METADATA_MISMATCH")
 def _policy(self):
  rows=self.connection.execute("SELECT * FROM market_context_policies").fetchall()
  if len(rows)!=1 or tuple(rows[0])!=(POLICY_ID,EXPECTED_POLICY_HASH_V1,self.policy_json):raise MarketContextIntegrityFailure("MARKET_CONTEXT_POLICY_SNAPSHOT_MISMATCH")
 def _resolve(self,payload,company_entity_id,entity_registry_snapshot_id,exchange):
  if self.ingestion_store.integrity_check()["result"]!="PASS":raise MarketContextIntegrityFailure("INGESTION_STORE_INTEGRITY_REQUIRED")
  cutoff=parse_utc(payload["data_cutoff_timestamp"],"data_cutoff_timestamp");registry=self.ingestion_store._verify_persisted_registry_chain("ENTITY",entity_registry_snapshot_id)
  if parse_utc(registry["as_of_timestamp"],"registry.as_of")>cutoff:raise MarketContextIntegrityFailure("ENTITY_REGISTRY_FROM_FUTURE")
  try:company=resolve_entity(registry,company_entity_id,payload["data_cutoff_timestamp"])
  except ResolutionError as exc:raise Stage6MarketContextError("MARKET_CONTEXT_COMPANY_RESOLUTION_FAILED") from exc
  if company["entity_type"]!="COMPANY":raise Stage6MarketContextError("MARKET_CONTEXT_COMPANY_REQUIRED")
  try:resolved=resolve_ticker(registry,exchange,payload["ticker"],payload["data_cutoff_timestamp"])
  except ResolutionError as exc:raise Stage6MarketContextError("MARKET_CONTEXT_TICKER_RESOLUTION_FAILED") from exc
  if resolved["entity_id"]!=company_entity_id:raise Stage6MarketContextError("MARKET_CONTEXT_TICKER_ENTITY_MISMATCH")
  mappings=[m for m in company["ticker_mappings"] if m["exchange"]==exchange and m["ticker"]==payload["ticker"] and _active(m,cutoff)]
  if len(mappings)!=1:raise Stage6MarketContextError("MARKET_CONTEXT_TICKER_MAPPING_NOT_EXACT")
  bindings=[]
  for evidence_id in payload["source_evidence_ids"]:
   record=self.ingestion_store.get_record(evidence_id)
   if record["record_kind"]!="EVIDENCE":raise Stage6MarketContextError("MARKET_CONTEXT_ACQUISITION_ATTEMPT_REJECTED")
   if parse_utc(record["retrieved_timestamp_utc"],"retrieved")>cutoff:raise Stage6MarketContextError("MARKET_CONTEXT_EVIDENCE_AFTER_CUTOFF")
   bindings.append({"evidence_id":record["evidence_id"],"evidence_hash":record["record_hash"],"source_registry_snapshot_id":record["source_registry_snapshot_id"],"source_registry_hash":record["source_registry_hash"],"entity_registry_snapshot_id":record["entity_registry_snapshot_id"],"entity_registry_hash":record["entity_registry_hash"],"retrieved_timestamp_utc":record["retrieved_timestamp_utc"]})
  return company,registry,mappings[0],sorted(bindings,key=lambda x:x["evidence_id"])
 def _deps(self,record):
  deps=[("ENTITY_REGISTRY",record["entity_registry_snapshot_id"],record["entity_registry_hash"]),("ENTITY_RECORD",record["company_entity_id"],record["company_entity_record_hash"]),("MARKET_CONTEXT_POLICY",POLICY_ID,self.policy_hash)]
  deps.extend(("EVIDENCE",x["evidence_id"],x["evidence_hash"]) for x in record["evidence_bindings"]);return deps
 def materialize(self,*,market_context,company_entity_id,entity_registry_snapshot_id,exchange):
  self._meta();self._policy();payload=normalize_payload(market_context,self.policy);company,registry,mapping,evidence=self._resolve(payload,company_entity_id,entity_registry_snapshot_id,exchange);record=build_record(payload=payload,company_entity=company,registry=registry,mapping=mapping,evidence_bindings=evidence,policy=self.policy,policy_hash=self.policy_hash);validate_record(record)
  old=self.connection.execute("SELECT canonical_json FROM market_context_records WHERE logical_context_key=?",(record["logical_context_key"],)).fetchone()
  if old:
   if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","market_context":record}
   raise MarketContextConflict("MARKET_CONTEXT_LOGICAL_IDENTITY_CONFLICT")
  with self.connection:
   p=record["contract_payload"];self.connection.execute("INSERT INTO market_context_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(record["market_context_record_id"],record["logical_context_key"],record["company_entity_id"],record["company_entity_record_hash"],record["entity_registry_snapshot_id"],record["entity_registry_hash"],record["exchange"],p["ticker"],p["as_of_timestamp"],p["data_cutoff_timestamp"],record["record_hash"],canonical_json(record)))
   self.connection.executemany("INSERT INTO market_context_evidence VALUES(?,?,?,?)",[(record["market_context_record_id"],x["evidence_id"],x["evidence_hash"],canonical_json(x)) for x in evidence]);self.connection.executemany("INSERT INTO market_context_dependencies VALUES(?,?,?,?)",[(record["market_context_record_id"],*x) for x in self._deps(record)])
  return {"status":"CREATED","market_context":record}
 def integrity_check(self):
  self._meta();self._policy()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise MarketContextIntegrityFailure("MARKET_CONTEXT_SQLITE_INTEGRITY_FAILED")
  for t in TABLES:
   if {x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,))}!={f"protect_{t}_update",f"protect_{t}_delete"}:raise MarketContextIntegrityFailure("MARKET_CONTEXT_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM market_context_records"):
   count+=1;stored=json.loads(row["canonical_json"]);validate_record(stored);raw=dict(stored["contract_payload"]);raw.pop("market_context_id");payload=normalize_payload(raw,self.policy);company,registry,mapping,evidence=self._resolve(payload,stored["company_entity_id"],stored["entity_registry_snapshot_id"],stored["exchange"]);replay=build_record(payload=payload,company_entity=company,registry=registry,mapping=mapping,evidence_bindings=evidence,policy=self.policy,policy_hash=self.policy_hash)
   if replay!=stored or row["canonical_json"]!=canonical_json(stored):raise MarketContextIntegrityFailure("MARKET_CONTEXT_REPLAY_MISMATCH")
   p=stored["contract_payload"];typed=(row["market_context_record_id"],row["logical_context_key"],row["company_entity_id"],row["company_entity_record_hash"],row["entity_registry_snapshot_id"],row["entity_registry_hash"],row["exchange"],row["ticker"],row["as_of_timestamp"],row["data_cutoff_timestamp"],row["record_hash"]);wanted=(stored["market_context_record_id"],stored["logical_context_key"],stored["company_entity_id"],stored["company_entity_record_hash"],stored["entity_registry_snapshot_id"],stored["entity_registry_hash"],stored["exchange"],p["ticker"],p["as_of_timestamp"],p["data_cutoff_timestamp"],stored["record_hash"])
   if typed!=wanted:raise MarketContextIntegrityFailure("MARKET_CONTEXT_TYPED_RECORD_MISMATCH")
   erows=self.connection.execute("SELECT * FROM market_context_evidence WHERE market_context_record_id=? ORDER BY evidence_id",(stored["market_context_record_id"],)).fetchall();actual=[json.loads(x["canonical_json"]) for x in erows]
   if actual!=evidence or any((r["evidence_id"],r["evidence_hash"],r["canonical_json"])!=(x["evidence_id"],x["evidence_hash"],canonical_json(x)) for r,x in zip(erows,actual)):raise MarketContextIntegrityFailure("MARKET_CONTEXT_EVIDENCE_COVERAGE_MISMATCH")
   deps={(x["record_type"],x["record_id"]):x["record_hash"] for x in self.connection.execute("SELECT * FROM market_context_dependencies WHERE market_context_record_id=?",(stored["market_context_record_id"],))};expected={(a,b):c for a,b,c in self._deps(stored)}
   if deps!=expected:raise MarketContextIntegrityFailure("MARKET_CONTEXT_DEPENDENCY_MISMATCH")
  return {"result":"PASS","market_contexts":count,"authority":AUTHORITY,"policy_hash":self.policy_hash}
