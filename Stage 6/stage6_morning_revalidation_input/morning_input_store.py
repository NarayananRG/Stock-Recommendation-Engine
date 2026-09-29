import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json,parse_utc,without
from stage6_portfolio_context.portfolio_context_validation import validate_portfolio_context_wrapper
from stage6_market_context.market_context_validation import validate_record as validate_market
from stage6_historical_analogue.historical_analogue_validation import validate_wrapper as validate_analogue
from .errors import Stage6MorningInputError,MorningInputConflict,MorningInputIntegrityFailure
from .policy import *
from .thesis_resolver import resolve_thesis,_integrity
from .morning_input_builder import build_snapshot
from .morning_input_validation import validate_request,validate_snapshot

TABLES=("morning_revalidation_input_store_meta","morning_revalidation_input_policies","morning_revalidation_input_contracts","morning_revalidation_input_records","morning_revalidation_input_bindings","morning_revalidation_input_dependencies","morning_revalidation_input_audits")
class MorningInputStore:
 def __init__(self,database:Path,portfolio_store,thesis_store,stage6e_store,recursive_store,*,evidence_store=None,company_effect_store=None,market_context_store=None,historical_analogue_store=None):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.portfolio_store=portfolio_store;self.thesis_store=thesis_store;self.stage6e_store=stage6e_store;self.recursive_store=recursive_store;self.evidence_store=evidence_store;self.company_effect_store=company_effect_store;self.market_context_store=market_context_store;self.historical_analogue_store=historical_analogue_store
  self.policy,self.policy_json,self.policy_hash=load_policy();self.contract,self.contract_json,self.contract_hash=load_contract();new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._initialize()
  self._singletons()
 def close(self):self.connection.close()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def _initialize(self):
  self.connection.executescript("""
CREATE TABLE morning_revalidation_input_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema TEXT NOT NULL,baseline TEXT NOT NULL,processor TEXT NOT NULL,authority TEXT NOT NULL,portfolio_blob TEXT NOT NULL,thesis_blob TEXT NOT NULL,market_blob TEXT NOT NULL,analogue_blob TEXT NOT NULL);
CREATE TABLE morning_revalidation_input_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE morning_revalidation_input_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE morning_revalidation_input_records(morning_snapshot_id TEXT PRIMARY KEY,logical_key TEXT UNIQUE NOT NULL,portfolio_context_id TEXT NOT NULL,recommendation_id TEXT NOT NULL,ticker TEXT NOT NULL,thesis_id TEXT NOT NULL,thesis_version INTEGER NOT NULL,target_session_date TEXT NOT NULL,revalidation_cutoff TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TABLE morning_revalidation_input_bindings(morning_snapshot_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(morning_snapshot_id,record_type,record_id),FOREIGN KEY(morning_snapshot_id) REFERENCES morning_revalidation_input_records);
CREATE TABLE morning_revalidation_input_dependencies(morning_snapshot_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(morning_snapshot_id,record_type,record_id),FOREIGN KEY(morning_snapshot_id) REFERENCES morning_revalidation_input_records);
CREATE TABLE morning_revalidation_input_audits(morning_snapshot_id TEXT PRIMARY KEY,canonical_json TEXT NOT NULL,FOREIGN KEY(morning_snapshot_id) REFERENCES morning_revalidation_input_records);
""")
  self.connection.execute("INSERT INTO morning_revalidation_input_store_meta VALUES(1,?,?,?,?,?,?,?,?)",(STORE_SCHEMA,BASELINE,PROCESSOR,AUTHORITY,PORTFOLIO_BLOB,THESIS_BLOB,MARKET_BLOB,ANALOGUE_BLOB));self.connection.execute("INSERT INTO morning_revalidation_input_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json));self.connection.execute("INSERT INTO morning_revalidation_input_contracts VALUES(?,?,?)",(CONTRACT_VERSION,self.contract_hash,self.contract_json))
  for table in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _singletons(self):
  meta=self.connection.execute("SELECT * FROM morning_revalidation_input_store_meta").fetchall();expected=(1,STORE_SCHEMA,BASELINE,PROCESSOR,AUTHORITY,PORTFOLIO_BLOB,THESIS_BLOB,MARKET_BLOB,ANALOGUE_BLOB)
  if len(meta)!=1 or tuple(meta[0])!=expected:raise MorningInputIntegrityFailure("MORNING_INPUT_METADATA_MISMATCH")
  p=self.connection.execute("SELECT * FROM morning_revalidation_input_policies").fetchall();c=self.connection.execute("SELECT * FROM morning_revalidation_input_contracts").fetchall()
  if len(p)!=1 or tuple(p[0])!=(POLICY_ID,self.policy_hash,self.policy_json):raise MorningInputIntegrityFailure("MORNING_INPUT_POLICY_MISMATCH")
  if len(c)!=1 or tuple(c[0])!=(CONTRACT_VERSION,self.contract_hash,self.contract_json):raise MorningInputIntegrityFailure("MORNING_INPUT_CONTRACT_MISMATCH")
 def _record(self,store,table,column,identity,code):
  _integrity(store,code+"_INTEGRITY_REQUIRED");row=store.connection.execute(f"SELECT canonical_json FROM {table} WHERE {column}=?",(identity,)).fetchone()
  if row is None:raise Stage6MorningInputError(code+"_NOT_FOUND")
  return json.loads(row[0])
 def _portfolio(self,identity):
  wrapper=self._record(self.portfolio_store,"portfolio_context_records","portfolio_context_id",identity,"PORTFOLIO_CONTEXT");validate_portfolio_context_wrapper(wrapper)
  if tuple(wrapper.get(k) for k in ("processor_version","policy_id","policy_hash","assembly_contract_version","assembly_contract_hash","authority"))!=("STAGE6_5D_PORTFOLIO_CONTEXT_ASSEMBLER_V1","S6PORTCTXPOL_STAGE6_5D_V1","fa76c6f99b6bb7122c59864d725272992a90e0d5c09f4c7b806f42dfea6191c8","STAGE6_PORTFOLIO_CONTEXT_ASSEMBLY_CONTRACT_V1","e980580a573dea1bedd78108e6ac9aaf2d08277728d5c0ef9e12af6db5f3bc8b",AUTHORITY):raise MorningInputIntegrityFailure("PORTFOLIO_CONTEXT_IDENTITY_INVALID")
  return wrapper["portfolio_context"]
 def _selected(self,portfolio,recommendation,ticker):
  matches=[x for x in portfolio["pending_entries"] if x.get("recommendation_id")==recommendation and x.get("ticker")==ticker]
  if len(matches)!=1:raise Stage6MorningInputError("PENDING_ENTRY_MATCH_COUNT_INVALID")
  return matches[0]
 def _evidence(self,ids,thesis,cutoff):
  if not isinstance(ids,list) or len(ids)!=len(set(ids)):raise Stage6MorningInputError("EVIDENCE_SELECTION_INVALID")
  if not ids:return []
  _integrity(self.evidence_store,"EVIDENCE_INTEGRITY_REQUIRED");out=[]
  for identity in ids:
   row=self.evidence_store.connection.execute("SELECT canonical_json FROM ingestion_records WHERE record_id=?",(identity,)).fetchone()
   if row is None:raise Stage6MorningInputError("EVIDENCE_NOT_FOUND")
   item=json.loads(row[0]);retrieved=parse_utc(item.get("retrieved_timestamp_utc"),"retrieved")
   if item.get("schema_version")!="STAGE6_EVIDENCE_V2" or item.get("record_kind")!="EVIDENCE" or item.get("evidence_id")!=identity or item.get("record_hash")!=canonical_hash(without(item,"record_hash")) or not(parse_utc(thesis["decision_cutoff"],"thesis")<retrieved<=parse_utc(cutoff,"revalidation")):raise MorningInputIntegrityFailure("EVIDENCE_INVALID")
   out.append(item)
  return out
 def _effects(self,ids):
  if not isinstance(ids,list) or len(ids)!=len(set(ids)):raise Stage6MorningInputError("COMPANY_EFFECT_SELECTION_INVALID")
  out=[]
  for identity in ids:
   item=self._record(self.company_effect_store,"company_effect_records","company_effect_record_id",identity,"COMPANY_EFFECT")
   if item.get("schema_version")!="STAGE6_EVENT_COMPANY_EFFECT_V1" or item.get("company_event_effect") not in {"FAVORABLE","ADVERSE","MIXED","INDETERMINATE","NOT_EVALUATED"} or item.get("record_hash")!=canonical_hash(without(item,"record_hash")):raise MorningInputIntegrityFailure("COMPANY_EFFECT_INVALID")
   out.append(item)
  return out
 def _market(self,identity,ticker,cutoff):
  if identity is None:return None
  item=self._record(self.market_context_store,"market_context_records","market_context_record_id",identity,"MARKET_CONTEXT");validate_market(item);p=item["contract_payload"]
  if p["ticker"]!=ticker or p["pit_verified"] is not True or not(parse_utc(p["data_cutoff_timestamp"],"data")<=parse_utc(p["as_of_timestamp"],"asof")<=parse_utc(cutoff,"cutoff")):raise MorningInputIntegrityFailure("MARKET_CONTEXT_INVALID")
  return item
 def _analogue(self,identity,cutoff):
  if identity is None:return None
  item=self._record(self.historical_analogue_store,"historical_analogue_records","historical_analogue_id",identity,"HISTORICAL_ANALOGUE");validate_analogue(item);p=item["historical_analogue_payload"]
  if p["pit_verified"] is not True or p["analogue_count"]!=len(p["selected_analogues"]) or not(parse_utc(p["selection_cutoff"],"selection")<=parse_utc(p["as_of_timestamp"],"asof")<=parse_utc(cutoff,"cutoff")):raise MorningInputIntegrityFailure("HISTORICAL_ANALOGUE_INVALID")
  return item
 def freeze(self,*,portfolio_context_id,recommendation_id,ticker,current_thesis_source,current_version_record_id,target_session_date,revalidation_cutoff,evidence_ids,company_effect_ids,market_context_id=None,historical_analogue_id=None):
  self._singletons();portfolio=self._portfolio(portfolio_context_id);pending=self._selected(portfolio,recommendation_id,ticker);_,thesis=resolve_thesis(current_thesis_source,current_version_record_id,self.thesis_store,self.stage6e_store,self.recursive_store);validate_request(portfolio,pending,thesis,target_session_date,revalidation_cutoff)
  evidence=self._evidence(evidence_ids,thesis,revalidation_cutoff);effects=self._effects(company_effect_ids);market=self._market(market_context_id,ticker,revalidation_cutoff);analogue=self._analogue(historical_analogue_id,revalidation_cutoff)
  record=build_snapshot(portfolio=portfolio,pending=pending,source=current_thesis_source,source_record_id=current_version_record_id,thesis=thesis,target_session_date=target_session_date,revalidation_cutoff=revalidation_cutoff,evidence=evidence,effects=effects,market=market,analogue=analogue,policy_hash=self.policy_hash,contract_hash=self.contract_hash);validate_snapshot(record,portfolio,pending,current_thesis_source,current_version_record_id,thesis,evidence,effects,market,analogue,self.policy_hash,self.contract_hash)
  logical=canonical_json({"portfolio_hash":portfolio["record_hash"],"recommendation_id":recommendation_id,"thesis_hash":thesis["record_hash"],"target_session_date":target_session_date,"revalidation_cutoff":revalidation_cutoff});old=self.connection.execute("SELECT canonical_json FROM morning_revalidation_input_records WHERE logical_key=?",(logical,)).fetchone()
  if old:
   if old[0]==canonical_json(record):return {"status":"IDEMPOTENT_SUCCESS","morning_input_snapshot":record}
   raise MorningInputConflict("MORNING_INPUT_LOGICAL_CONFLICT")
  deps=[*(tuple(x[k] for k in ("record_type","record_id","record_hash")) for x in record["direct_input_bindings"]),("STAGE6_7A_POLICY",POLICY_ID,self.policy_hash),("STAGE6_7A_INPUT_CONTRACT",CONTRACT_VERSION,self.contract_hash)];audit={"morning_snapshot_id":record["morning_snapshot_id"],"target_session_date":target_session_date,"revalidation_cutoff":revalidation_cutoff,"entry_revalidation_status":"NOT_EVALUATED","entry_proposal_status":"NOT_MATERIALIZED"}
  with self.connection:
   self.connection.execute("INSERT INTO morning_revalidation_input_records VALUES(?,?,?,?,?,?,?,?,?,?,?)",(record["morning_snapshot_id"],logical,portfolio_context_id,recommendation_id,ticker,thesis["thesis_id"],thesis["version"],target_session_date,revalidation_cutoff,record["record_hash"],canonical_json(record)));self.connection.executemany("INSERT INTO morning_revalidation_input_bindings VALUES(?,?,?,?)",[(record["morning_snapshot_id"],x["record_type"],x["record_id"],x["record_hash"]) for x in record["direct_input_bindings"]]);self.connection.executemany("INSERT INTO morning_revalidation_input_dependencies VALUES(?,?,?,?)",[(record["morning_snapshot_id"],*x) for x in deps]);self.connection.execute("INSERT INTO morning_revalidation_input_audits VALUES(?,?)",(record["morning_snapshot_id"],canonical_json(audit)))
  return {"status":"CREATED","morning_input_snapshot":record}
 def integrity_check(self):
  self._singletons()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise MorningInputIntegrityFailure("MORNING_INPUT_SQLITE_INVALID")
  for table in TABLES:
   if {x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,))}!={f"protect_{table}_update",f"protect_{table}_delete"}:raise MorningInputIntegrityFailure("MORNING_INPUT_TRIGGER_MISSING")
  for row in self.connection.execute("SELECT * FROM morning_revalidation_input_records"):
   stored=json.loads(row["canonical_json"]);portfolio=self._portfolio(row["portfolio_context_id"]);pending=self._selected(portfolio,row["recommendation_id"],row["ticker"]);_,thesis=resolve_thesis(stored["current_thesis_source"],stored["current_version_record_id"],self.thesis_store,self.stage6e_store,self.recursive_store);evidence=self._evidence([x["record_id"] for x in stored["evidence_bindings"]],thesis,stored["revalidation_cutoff"]);effects=self._effects([x["record_id"] for x in stored["company_effect_bindings"]]);market=self._market(None if stored["market_context_binding"] is None else stored["market_context_binding"]["record_id"],stored["ticker"],stored["revalidation_cutoff"]);analogue=self._analogue(None if stored["historical_analogue_binding"] is None else stored["historical_analogue_binding"]["record_id"],stored["revalidation_cutoff"]);validate_snapshot(stored,portfolio,pending,stored["current_thesis_source"],stored["current_version_record_id"],thesis,evidence,effects,market,analogue,self.policy_hash,self.contract_hash)
   bindings=sorted(tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM morning_revalidation_input_bindings WHERE morning_snapshot_id=?",(stored["morning_snapshot_id"],)));expected=sorted(tuple(x[k] for k in ("record_type","record_id","record_hash")) for x in stored["direct_input_bindings"]);deps=sorted(tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM morning_revalidation_input_dependencies WHERE morning_snapshot_id=?",(stored["morning_snapshot_id"],)));wanted=sorted([*expected,("STAGE6_7A_POLICY",POLICY_ID,self.policy_hash),("STAGE6_7A_INPUT_CONTRACT",CONTRACT_VERSION,self.contract_hash)])
   audit={"morning_snapshot_id":stored["morning_snapshot_id"],"target_session_date":stored["target_session_date"],"revalidation_cutoff":stored["revalidation_cutoff"],"entry_revalidation_status":"NOT_EVALUATED","entry_proposal_status":"NOT_MATERIALIZED"};ar=self.connection.execute("SELECT canonical_json FROM morning_revalidation_input_audits WHERE morning_snapshot_id=?",(stored["morning_snapshot_id"],)).fetchone()
   if bindings!=expected or deps!=wanted or ar is None or ar[0]!=canonical_json(audit):raise MorningInputIntegrityFailure("MORNING_INPUT_CHILD_MISMATCH")
  return {"result":"PASS","snapshots":self.connection.execute("SELECT count(*) FROM morning_revalidation_input_records").fetchone()[0],"authority":AUTHORITY}
