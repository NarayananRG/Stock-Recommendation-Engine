import json,sqlite3
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json,parse_utc,without
from stage6_trade_thesis.trade_thesis_validation import validate_trade_thesis
from stage6_market_context.market_context_validation import validate_record as validate_market
from stage6_historical_analogue.historical_analogue_validation import validate_wrapper as validate_analogue
from stage6_portfolio_context.portfolio_context_validation import validate_portfolio_context_wrapper
from .errors import Stage6ThesisReviewInputError,ThesisReviewInputConflict,ThesisReviewInputIntegrityFailure
from .policy import *
from .review_input_builder import build_review_snapshot
from .review_input_validation import validate_review_request,validate_review_snapshot

TABLES=("thesis_review_input_store_meta","thesis_review_input_policies","thesis_review_input_contracts","thesis_review_input_records","thesis_review_input_bindings","thesis_review_input_dependencies")
class ThesisReviewInputStore:
 def __init__(self,database:Path,thesis_store,*,evidence_store=None,company_effect_store=None,market_context_store=None,historical_analogue_store=None,portfolio_context_store=None):
  self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True);self.thesis_store=thesis_store;self.evidence_store=evidence_store;self.company_effect_store=company_effect_store;self.market_context_store=market_context_store;self.historical_analogue_store=historical_analogue_store;self.portfolio_context_store=portfolio_context_store;self.policy,self.policy_json,self.policy_hash=load_policy();self.contract,self.contract_json,self.contract_hash=load_contract();new=not self.database.exists();self.connection=sqlite3.connect(self.database);self.connection.row_factory=sqlite3.Row;self.connection.execute("PRAGMA foreign_keys=ON")
  if new:self._init()
  self._singletons()
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def close(self):self.connection.close()
 def _init(self):
  self.connection.executescript("""CREATE TABLE thesis_review_input_store_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),store_schema_version TEXT NOT NULL,baseline_commit TEXT NOT NULL,processor_version TEXT NOT NULL,authority TEXT NOT NULL);CREATE TABLE thesis_review_input_policies(policy_id TEXT PRIMARY KEY,policy_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE thesis_review_input_contracts(contract_version TEXT PRIMARY KEY,contract_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE thesis_review_input_records(review_snapshot_id TEXT PRIMARY KEY,logical_review_key TEXT UNIQUE NOT NULL,thesis_id TEXT NOT NULL,review_cutoff TEXT NOT NULL,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);CREATE TABLE thesis_review_input_bindings(review_snapshot_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(review_snapshot_id,record_type,record_id),FOREIGN KEY(review_snapshot_id) REFERENCES thesis_review_input_records);CREATE TABLE thesis_review_input_dependencies(review_snapshot_id TEXT NOT NULL,record_type TEXT NOT NULL,record_id TEXT NOT NULL,record_hash TEXT NOT NULL,PRIMARY KEY(review_snapshot_id,record_type,record_id),FOREIGN KEY(review_snapshot_id) REFERENCES thesis_review_input_records);""")
  self.connection.execute("INSERT INTO thesis_review_input_store_meta VALUES(1,?,?,?,?)",(STORE_SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY));self.connection.execute("INSERT INTO thesis_review_input_policies VALUES(?,?,?)",(POLICY_ID,self.policy_hash,self.policy_json));self.connection.execute("INSERT INTO thesis_review_input_contracts VALUES(?,?,?)",(CONTRACT_VERSION,self.contract_hash,self.contract_json))
  for t in TABLES:self.connection.executescript(f"CREATE TRIGGER protect_{t}_update BEFORE UPDATE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;CREATE TRIGGER protect_{t}_delete BEFORE DELETE ON {t} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;")
  self.connection.commit()
 def _singletons(self):
  m=self.connection.execute("SELECT * FROM thesis_review_input_store_meta").fetchall();p=self.connection.execute("SELECT * FROM thesis_review_input_policies").fetchall();c=self.connection.execute("SELECT * FROM thesis_review_input_contracts").fetchall()
  if len(m)!=1 or tuple(m[0])!=(1,STORE_SCHEMA_VERSION,BASELINE_COMMIT,PROCESSOR_VERSION,AUTHORITY):raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_METADATA_MISMATCH")
  if len(p)!=1 or tuple(p[0])!=(POLICY_ID,self.policy_hash,self.policy_json):raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_POLICY_MISMATCH")
  if len(c)!=1 or tuple(c[0])!=(CONTRACT_VERSION,self.contract_hash,self.contract_json):raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_CONTRACT_MISMATCH")
 def _integrity(self,store,code):
  if store is None:raise ThesisReviewInputIntegrityFailure(code)
  try:r=store.integrity_check()
  except Exception as exc:raise ThesisReviewInputIntegrityFailure(code) from exc
  if r.get("result")!="PASS":raise ThesisReviewInputIntegrityFailure(code)
 def _json(self,store,table,column,identity,code):
  self._integrity(store,code+"_INTEGRITY_REQUIRED");row=store.connection.execute(f"SELECT canonical_json FROM {table} WHERE {column}=?",(identity,)).fetchone()
  if row is None:raise Stage6ThesisReviewInputError(code+"_NOT_FOUND")
  return json.loads(row[0])
 def _thesis(self,identity):
  wrapper=self._json(self.thesis_store,"trade_thesis_records","thesis_id",identity,"PREVIOUS_THESIS");thesis=wrapper["trade_thesis"];validate_trade_thesis(thesis)
  if thesis["thesis_id"]!=identity or thesis["version"]!=1 or thesis["thesis_engine_version"]!="STAGE6_INITIAL_THESIS_SEMANTICS_V1" or thesis["code_commit"]!="1672ab7ed7322b8dc4406ab5ea556325977bc8cd" or thesis["authority_mode"]!=AUTHORITY:raise ThesisReviewInputIntegrityFailure("PREVIOUS_THESIS_IDENTITY_INVALID")
  return thesis
 def _evidence(self,ids,prior,cutoff):
  if not ids:return []
  self._integrity(self.evidence_store,"EVIDENCE_STORE_INTEGRITY_REQUIRED");out=[]
  for identity in ids:
   row=self.evidence_store.connection.execute("SELECT canonical_json FROM ingestion_records WHERE record_id=?",(identity,)).fetchone()
   if row is None:raise Stage6ThesisReviewInputError("EVIDENCE_NOT_FOUND")
   x=json.loads(row[0]);retrieved=parse_utc(x.get("retrieved_timestamp_utc"),"retrieved")
   if x.get("schema_version")!=EVIDENCE_SCHEMA or x.get("record_kind")!="EVIDENCE" or x.get("evidence_id")!=identity or x.get("record_hash")!=canonical_hash(without(x,"record_hash")):raise ThesisReviewInputIntegrityFailure("EVIDENCE_IDENTITY_INVALID")
   if not (parse_utc(prior,"prior")<retrieved<=parse_utc(cutoff,"review")):raise ThesisReviewInputIntegrityFailure("NEW_EVIDENCE_CHRONOLOGY_INVALID")
   out.append(x)
  return out
 def _effects(self,ids):
  if not ids:return []
  out=[]
  for identity in ids:
   x=self._json(self.company_effect_store,"company_effect_records","company_effect_record_id",identity,"COMPANY_EFFECT")
   expected=(COMPANY_EFFECT_SCHEMA,identity,"STAGE6_3I_COMPANY_EFFECT_SYNTHESIZER_V1","S6COMEFFPOL_STAGE6_3I_V1","3a92f28b24d46a8b7f6ed1ac9a77562355ae751dfce23e23ed4a9ba4dfc21786",AUTHORITY)
   if tuple(x.get(k) for k in ("schema_version","company_effect_record_id","processor_version","policy_id","policy_hash","authority"))!=expected or x.get("record_hash")!=canonical_hash(without(x,"record_hash")):raise ThesisReviewInputIntegrityFailure("COMPANY_EFFECT_IDENTITY_INVALID")
   out.append(x)
  return out
 def _market(self,identity,ticker,cutoff):
  if identity is None:return None
  x=self._json(self.market_context_store,"market_context_records","market_context_record_id",identity,"MARKET_CONTEXT");validate_market(x);p=x["contract_payload"]
  if tuple(x.get(k) for k in ("processor_version","policy_id","policy_hash","authority"))!=("STAGE6_4A_MARKET_CONTEXT_MATERIALIZER_V1","S6MCTXPOL_STAGE6_4A_V1","422fa524a21a09a29ca0caa94a382ea056fba958d7c1a0a05c465740cb791d94",AUTHORITY) or p["schema_version"]!=MARKET_SCHEMA or p["ticker"]!=ticker or p["pit_verified"] is not True or not(parse_utc(p["data_cutoff_timestamp"],"data")<=parse_utc(p["as_of_timestamp"],"asof")<=parse_utc(cutoff,"review")):raise ThesisReviewInputIntegrityFailure("MARKET_CONTEXT_REVIEW_INVALID")
  return x
 def _analogue(self,identity,cutoff):
  if identity is None:return None
  x=self._json(self.historical_analogue_store,"historical_analogue_records","historical_analogue_id",identity,"HISTORICAL_ANALOGUE");validate_analogue(x);p=x["historical_analogue_payload"]
  if tuple(x.get(k) for k in ("processor_version","policy_id","policy_hash","aggregation_contract_version","aggregation_contract_hash","authority"))!=("STAGE6_4E_HISTORICAL_ANALOGUE_AGGREGATOR_V1","S6ANAGGPOL_STAGE6_4E_V1","41dacb0dfa0dcf09d5311b78573a50865372ada0bbf917d9c95e03edc4c0173f","STAGE6_ANALOGUE_AGGREGATION_CONTRACT_V1","028f3829634793af67c33f7ab041ae8c8732e9d8ea3502c058a478ea9316b981",AUTHORITY) or p["schema_version"]!=ANALOGUE_SCHEMA or p["pit_verified"] is not True or p["analogue_count"]!=len(p["selected_analogues"]) or not(parse_utc(p["selection_cutoff"],"selection")<=parse_utc(p["as_of_timestamp"],"asof")<=parse_utc(cutoff,"review")):raise ThesisReviewInputIntegrityFailure("HISTORICAL_ANALOGUE_REVIEW_INVALID")
  return x
 def _portfolio(self,identity,cutoff):
  if identity is None:return None
  x=self._json(self.portfolio_context_store,"portfolio_context_records","portfolio_context_id",identity,"PORTFOLIO_CONTEXT");validate_portfolio_context_wrapper(x);p=x["portfolio_context"]
  if tuple(x.get(k) for k in ("processor_version","policy_id","policy_hash","assembly_contract_version","assembly_contract_hash","authority"))!=("STAGE6_5D_PORTFOLIO_CONTEXT_ASSEMBLER_V1","S6PORTCTXPOL_STAGE6_5D_V1","fa76c6f99b6bb7122c59864d725272992a90e0d5c09f4c7b806f42dfea6191c8","STAGE6_PORTFOLIO_CONTEXT_ASSEMBLY_CONTRACT_V1","e980580a573dea1bedd78108e6ac9aaf2d08277728d5c0ef9e12af6db5f3bc8b",AUTHORITY) or p["schema_version"]!=PORTFOLIO_SCHEMA or not(parse_utc(p["data_cutoff_timestamp"],"data")<=parse_utc(p["as_of_timestamp"],"asof")<=parse_utc(cutoff,"review")):raise ThesisReviewInputIntegrityFailure("PORTFOLIO_CONTEXT_REVIEW_INVALID")
  return x
 def _build(self,thesis_id,review_cutoff,evidence_ids,company_effect_ids,market_context_id,historical_analogue_id,portfolio_context_id):
  validate_review_request(thesis_id=thesis_id,review_cutoff=review_cutoff,evidence_ids=evidence_ids,company_effect_ids=company_effect_ids,market_context_id=market_context_id,historical_analogue_id=historical_analogue_id,portfolio_context_id=portfolio_context_id);thesis=self._thesis(thesis_id)
  if parse_utc(review_cutoff,"review")<=parse_utc(thesis["decision_cutoff"],"prior"):raise ThesisReviewInputIntegrityFailure("REVIEW_CUTOFF_NOT_AFTER_PREVIOUS")
  kwargs={"thesis":thesis,"review_cutoff":review_cutoff,"evidence":self._evidence(evidence_ids,thesis["decision_cutoff"],review_cutoff),"company_effects":self._effects(company_effect_ids),"market_context":self._market(market_context_id,thesis["ticker"],review_cutoff),"historical_analogue":self._analogue(historical_analogue_id,review_cutoff),"portfolio_context":self._portfolio(portfolio_context_id,review_cutoff),"policy_hash":self.policy_hash,"contract_hash":self.contract_hash};record=build_review_snapshot(**kwargs);validate_review_snapshot(record);return record
 def freeze(self,*,thesis_id,review_cutoff,evidence_ids,company_effect_ids,market_context_id=None,historical_analogue_id=None,portfolio_context_id=None):
  self._singletons();record=self._build(thesis_id,review_cutoff,evidence_ids,company_effect_ids,market_context_id,historical_analogue_id,portfolio_context_id);text=canonical_json(record);logical=canonical_json({"thesis_id":thesis_id,"review_cutoff":record["review_cutoff"]});old=self.connection.execute("SELECT canonical_json FROM thesis_review_input_records WHERE logical_review_key=?",(logical,)).fetchone()
  if old:
   if old[0]==text:return {"status":"IDEMPOTENT_SUCCESS","review_input_snapshot":record}
   raise ThesisReviewInputConflict("THESIS_REVIEW_LOGICAL_CONFLICT")
  deps=[*( (x["record_type"],x["record_id"],x["record_hash"]) for x in record["direct_input_bindings"]),("STAGE6_6C_POLICY",POLICY_ID,self.policy_hash),("STAGE6_6C_REVIEW_INPUT_CONTRACT",CONTRACT_VERSION,self.contract_hash)]
  with self.connection:
   self.connection.execute("INSERT INTO thesis_review_input_records VALUES(?,?,?,?,?,?)",(record["review_snapshot_id"],logical,record["thesis_id"],record["review_cutoff"],record["record_hash"],text));self.connection.executemany("INSERT INTO thesis_review_input_bindings VALUES(?,?,?,?)",[(record["review_snapshot_id"],x["record_type"],x["record_id"],x["record_hash"]) for x in record["direct_input_bindings"]]);self.connection.executemany("INSERT INTO thesis_review_input_dependencies VALUES(?,?,?,?)",[(record["review_snapshot_id"],*x) for x in deps])
  return {"status":"CREATED","review_input_snapshot":record}
 def integrity_check(self):
  self._singletons()
  if self.connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok" or self.connection.execute("PRAGMA foreign_key_check").fetchall():raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_SQLITE_INTEGRITY_FAILED")
  for t in TABLES:
   if {x[0] for x in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,))}!={f"protect_{t}_update",f"protect_{t}_delete"}:raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_TRIGGER_MISSING")
  count=0
  for row in self.connection.execute("SELECT * FROM thesis_review_input_records"):
   count+=1;r=json.loads(row["canonical_json"]);validate_review_snapshot(r);ids=lambda kind:[x["record_id"] for x in r["direct_input_bindings"] if x["record_type"]==kind];rebuilt=self._build(r["thesis_id"],r["review_cutoff"],ids(EVIDENCE_SCHEMA),ids(COMPANY_EFFECT_SCHEMA),ids(MARKET_SCHEMA)[0] if ids(MARKET_SCHEMA) else None,ids(ANALOGUE_SCHEMA)[0] if ids(ANALOGUE_SCHEMA) else None,ids(PORTFOLIO_SCHEMA)[0] if ids(PORTFOLIO_SCHEMA) else None)
   if rebuilt!=r or row["canonical_json"]!=canonical_json(r) or tuple(row[k] for k in ("review_snapshot_id","thesis_id","review_cutoff","record_hash"))!=(r["review_snapshot_id"],r["thesis_id"],r["review_cutoff"],r["record_hash"]):raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_REPLAY_MISMATCH")
   b=[tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM thesis_review_input_bindings WHERE review_snapshot_id=? ORDER BY record_type,record_id",(r["review_snapshot_id"],))]
   if b!=[(x["record_type"],x["record_id"],x["record_hash"]) for x in r["direct_input_bindings"]]:raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_BINDING_MISMATCH")
   expected=sorted([*b,("STAGE6_6C_POLICY",POLICY_ID,self.policy_hash),("STAGE6_6C_REVIEW_INPUT_CONTRACT",CONTRACT_VERSION,self.contract_hash)]);actual=sorted(tuple(x) for x in self.connection.execute("SELECT record_type,record_id,record_hash FROM thesis_review_input_dependencies WHERE review_snapshot_id=?",(r["review_snapshot_id"],)))
   if actual!=expected:raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_DEPENDENCY_MISMATCH")
  return {"result":"PASS","review_snapshots":count,"authority":AUTHORITY}
 def update_record(self,*_,**__):raise Stage6ThesisReviewInputError("IMMUTABLE_RECORD_UPDATE_PROHIBITED")
