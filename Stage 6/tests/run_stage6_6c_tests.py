import ast,csv,json,sqlite3,subprocess,sys,tempfile
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_thesis_seed.thesis_seed_store import ThesisSeedStore
from stage6_trade_thesis.trade_thesis_store import TradeThesisStore
import stage6_thesis_review_input.review_input_store as store_module
from stage6_thesis_review_input.errors import *
from stage6_thesis_review_input.policy import *
from stage6_thesis_review_input.review_input_builder import SAFETY,build_review_snapshot,portfolio_presence
from stage6_thesis_review_input.review_input_store import TABLES,ThesisReviewInputStore
from stage6_thesis_review_input.review_input_validation import FIELDS,validate_review_request,validate_review_snapshot

OUT=ROOT/"results"/"stage6_6c_test_results.csv";CASES=[];CTX={}
def case(group,name,fn):CASES.append((group,name,fn))
def require(x,msg="assertion failed"):
 if not x:raise AssertionError(msg)
def expect(exc,fn,contains=None):
 try:fn()
 except exc as e:
  if contains:require(contains in str(e))
  return
 raise AssertionError(f"expected {exc}")
def changed(value,path,replacement):
 out=deepcopy(value);cur=out
 for key in path[:-1]:cur=cur[key]
 cur[path[-1]]=replacement;return out
def git(*args):return subprocess.check_output(["git",*args],cwd=REPO,text=True).strip()
def source():return json.loads((ROOT/"fixtures/stage6_6a/initial_thesis_seed_examples.json").read_text())["examples"][0]
def fixture():return json.loads((ROOT/"fixtures/stage6_6c/thesis_review_input_examples.json").read_text())
class FakeStore:
 def __init__(self,table,key,records):
  self.connection=sqlite3.connect(":memory:");self.connection.row_factory=sqlite3.Row;self.connection.execute(f"CREATE TABLE {table}({key} TEXT PRIMARY KEY,canonical_json TEXT)");self.table=table;self.key=key;self.passes=True
  for identity,record in records:self.connection.execute(f"INSERT INTO {table} VALUES(?,?)",(identity,canonical_json(record)))
  self.connection.commit()
 def integrity_check(self):return {"result":"PASS" if self.passes else "FAIL"}
 def close(self):self.connection.close()
def evidence(identity="S6EV_REVIEW_001",retrieved="2026-09-28T18:00:00.000000Z",kind="EVIDENCE"):
 x={"schema_version":"STAGE6_EVIDENCE_V2","record_kind":kind,"evidence_id":identity,"retrieved_timestamp_utc":retrieved,"payload":"UNINTERPRETED","record_hash":""};x["record_hash"]=canonical_hash(without(x,"record_hash"));return x
def effect(identity="S6COMEFF_REVIEW_001",effect_value="FAVORABLE",event="EVENT_1",version=1):
 x={"schema_version":"STAGE6_EVENT_COMPANY_EFFECT_V1","company_effect_record_id":identity,"event_id":event,"event_version":version,"event_hash":"1"*64,"exposure_id":"EXP_1","exposure_version":1,"exposure_hash":"2"*64,"company_entity_id":"COMPANY_1","company_event_effect":effect_value,"processor_version":"STAGE6_3I_COMPANY_EFFECT_SYNTHESIZER_V1","policy_id":"S6COMEFFPOL_STAGE6_3I_V1","policy_hash":"3a92f28b24d46a8b7f6ed1ac9a77562355ae751dfce23e23ed4a9ba4dfc21786","authority":"SHADOW_ONLY","record_hash":""};x["record_hash"]=canonical_hash(without(x,"record_hash"));return x
def market(identity="S6MCTX_REVIEW_001",ticker="RELIANCE.NS",asof="2026-09-29T10:00:00Z",cutoff="2026-09-29T09:00:00Z",pit=True):
 return {"market_context_record_id":identity,"processor_version":"STAGE6_4A_MARKET_CONTEXT_MATERIALIZER_V1","policy_id":"S6MCTXPOL_STAGE6_4A_V1","policy_hash":"422fa524a21a09a29ca0caa94a382ea056fba958d7c1a0a05c465740cb791d94","authority":"SHADOW_ONLY","contract_payload":{"schema_version":"STAGE6_MARKET_CONTEXT_V2","market_context_id":identity,"record_hash":"4"*64,"ticker":ticker,"as_of_timestamp":asof,"data_cutoff_timestamp":cutoff,"pit_verified":pit}}
def analogue(identity="S6HAN_REVIEW_001",asof="2026-09-29T10:00:00Z",cutoff="2026-09-29T09:00:00Z",count=1,pit=True):
 return {"processor_version":"STAGE6_4E_HISTORICAL_ANALOGUE_AGGREGATOR_V1","policy_id":"S6ANAGGPOL_STAGE6_4E_V1","policy_hash":"41dacb0dfa0dcf09d5311b78573a50865372ada0bbf917d9c95e03edc4c0173f","aggregation_contract_version":"STAGE6_ANALOGUE_AGGREGATION_CONTRACT_V1","aggregation_contract_hash":"028f3829634793af67c33f7ab041ae8c8732e9d8ea3502c058a478ea9316b981","authority":"SHADOW_ONLY","historical_analogue_payload":{"schema_version":"STAGE6_HISTORICAL_ANALOGUE_V2","historical_analogue_id":identity,"record_hash":"5"*64,"as_of_timestamp":asof,"selection_cutoff":cutoff,"pit_verified":pit,"analogue_count":count,"selected_analogues":[{"id":"A"}]*count}}
def portfolio(identity="S6PORTCTX_REVIEW_001",opened=True,pending=False,asof="2026-09-29T10:00:00Z",cutoff="2026-09-29T09:00:00Z"):
 p={"schema_version":"STAGE6_PORTFOLIO_CONTEXT_V2","portfolio_context_id":identity,"record_hash":"6"*64,"as_of_timestamp":asof,"data_cutoff_timestamp":cutoff,"open_positions":[{"ticker":"RELIANCE.NS"}] if opened else [],"pending_entries":[{"ticker":"RELIANCE.NS"}] if pending else []}
 return {"processor_version":"STAGE6_5D_PORTFOLIO_CONTEXT_ASSEMBLER_V1","policy_id":"S6PORTCTXPOL_STAGE6_5D_V1","policy_hash":"fa76c6f99b6bb7122c59864d725272992a90e0d5c09f4c7b806f42dfea6191c8","assembly_contract_version":"STAGE6_PORTFOLIO_CONTEXT_ASSEMBLY_CONTRACT_V1","assembly_contract_hash":"e980580a573dea1bedd78108e6ac9aaf2d08277728d5c0ef9e12af6db5f3bc8b","authority":"SHADOW_ONLY","portfolio_context":p}
def R():return CTX["record"]
def request(**overrides):
 q={"thesis_id":CTX["thesis"]["thesis_id"],"review_cutoff":"2026-09-29T12:00:00.000000Z","evidence_ids":["S6EV_REVIEW_001"],"company_effect_ids":["S6COMEFF_REVIEW_001"],"market_context_id":"S6MCTX_REVIEW_001","historical_analogue_id":"S6HAN_REVIEW_001","portfolio_context_id":"S6PORTCTX_REVIEW_001"};q.update(overrides);return q

for label,actual,wanted in (("schema",SCHEMA_VERSION,"STAGE6_THESIS_REVIEW_INPUT_SNAPSHOT_V1"),("store",STORE_SCHEMA_VERSION,"STAGE6_6C_THESIS_REVIEW_INPUT_STORE_V1"),("processor",PROCESSOR_VERSION,"STAGE6_6C_THESIS_REVIEW_INPUT_FREEZER_V1"),("policy",POLICY_ID,"S6THREVINPOL_STAGE6_6C_V1"),("contract",CONTRACT_VERSION,"STAGE6_THESIS_REVIEW_INPUT_CONTRACT_V1"),("authority",AUTHORITY,"SHADOW_ONLY"),("baseline",BASELINE_COMMIT,"eac8ae133acb712fbe2777ad025ed98b9d0c05f8")):
 case("IDENTITY",label,lambda actual=actual,wanted=wanted:require(actual==wanted))
case("IDENTITY","baseline parent",lambda:require(git("rev-parse",BASELINE_COMMIT+"^")=="1672ab7ed7322b8dc4406ab5ea556325977bc8cd"))
case("IDENTITY","HEAD descendant safe",lambda:require(git("merge-base","HEAD",BASELINE_COMMIT)==BASELINE_COMMIT))
case("IDENTITY","branch",lambda:require(git("branch","--show-current")=="stage6-persistent-thesis"))
for name,digest in (("trade_thesis.schema.json",TRADE_THESIS_BLOB),("market_context.schema.json",MARKET_BLOB),("historical_analogue.schema.json",ANALOGUE_BLOB),("portfolio_context.schema.json",PORTFOLIO_BLOB)):
 case("FROZEN",name,lambda name=name,digest=digest:require(git_blob(ROOT/"contracts"/name)==digest))
case("IDENTITY","policy hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH_V1))
case("IDENTITY","contract hash",lambda:require(load_contract()[2]==EXPECTED_CONTRACT_HASH_V1))
case("IDENTITY","fixture",lambda:require(fixture()["fixture_version"]=="STAGE6_6C_FIXTURES_V1"))

case("REQUEST","valid",lambda:require(validate_review_request(**request())))
for key in ("thesis_id","review_cutoff","evidence_ids","company_effect_ids"):
 case("REQUEST",key+" required",lambda key=key:expect(ThesisReviewInputIntegrityFailure,lambda:validate_review_request(**request(**{key:None}))))
case("REQUEST","UTC Z required",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:validate_review_request(**request(review_cutoff="2026-09-29T17:30:00+05:30"))))
case("REQUEST","equal cutoff rejected",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["store"].freeze(**request(review_cutoff=CTX["thesis"]["decision_cutoff"]))))
case("REQUEST","earlier cutoff rejected",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["store"].freeze(**request(review_cutoff="2026-09-27T12:00:00Z"))))
case("REQUEST","duplicate evidence rejected",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:validate_review_request(**request(evidence_ids=["A","A"]))))
case("REQUEST","duplicate effects rejected",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:validate_review_request(**request(company_effect_ids=["A","A"]))))

case("SNAPSHOT","valid",lambda:require(validate_review_snapshot(R())==R()))
case("SNAPSHOT","closed fields",lambda:require(set(R())==FIELDS))
for field in sorted(FIELDS):case("CLOSED",field,lambda field=field:expect(ThesisReviewInputIntegrityFailure,lambda:validate_review_snapshot({k:v for k,v in R().items() if k!=field})))
case("CLOSED","extra",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:validate_review_snapshot(R()|{"extra":1})))
for field,wanted in (("thesis_id",None),("thesis_version",1),("recommendation_id","REC_001"),("ticker","RELIANCE.NS"),("prior_decision_cutoff","2026-09-28T12:00:00.000000Z"),("review_cutoff","2026-09-29T12:00:00.000000Z")):
 case("THESIS",field,lambda field=field,wanted=wanted:require(R()[field]==(CTX["thesis"]["thesis_id"] if field=="thesis_id" else wanted)))
case("THESIS","exact binding",lambda:require(R()["previous_thesis_binding"]=={"record_type":"STAGE6_TRADE_THESIS_V2","record_id":CTX["thesis"]["thesis_id"],"record_hash":CTX["thesis"]["record_hash"]}))
case("THESIS","store integrity",lambda:require(CTX["thesis_store"].integrity_check()["result"]=="PASS"))

for prefix in ("new_evidence","company_effect","market_context","historical_analogue","portfolio_context"):
 case("AVAILABILITY",prefix+" available",lambda prefix=prefix:require(R()[prefix+"_status"]=="AVAILABLE"))
case("EVIDENCE","count",lambda:require(R()["factual_delta_metadata"]["new_evidence_count"]==1))
case("EVIDENCE","binding",lambda:require(R()["new_evidence_bindings"][0]["record_id"]=="S6EV_REVIEW_001"))
case("EVIDENCE","old rejected",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["old_evidence_store_factory"]()))
case("EVIDENCE","future rejected",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["future_evidence_store_factory"]()))
case("EVIDENCE","acquisition rejected",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["acquisition_store_factory"]()))
case("EVIDENCE","no text interpretation",lambda:require("payload" not in canonical_json(R())))
for value in ("FAVORABLE","ADVERSE","MIXED","INDETERMINATE","NOT_EVALUATED"):
 case("COMPANY_EFFECT",value+" preserved",lambda value=value:require(CTX["effect_snapshot_factory"](value)["company_effect_summaries"][0]["company_event_effect"]==value))
case("COMPANY_EFFECT","count",lambda:require(R()["factual_delta_metadata"]["company_effect_count"]==1))
for field in ("event_id","event_version","event_hash","exposure_id","exposure_version","exposure_hash","company_entity_id","company_event_effect"):
 case("COMPANY_EFFECT",field+" preserved",lambda field=field:require(R()["company_effect_summaries"][0][field]==CTX["effect"][field]))
case("COMPANY_EFFECT","relevance uninterpreted",lambda:require(R()["company_effect_summaries"][0]["review_relevance"]=="CALLER_SELECTED_UNINTERPRETED"))
case("COMPANY_EFFECT","no scoring",lambda:require(not any("score" in k for k in R())))
case("COMPANY_EFFECT","no thesis mapping",lambda:require(R()["material_change_status"]=="NOT_EVALUATED"))

case("MARKET","exact binding",lambda:require(R()["market_context_binding"]=={"record_type":MARKET_SCHEMA,"record_id":"S6MCTX_REVIEW_001","record_hash":"4"*64}))
case("MARKET","ticker mismatch",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["market_factory"](market(ticker="OTHER"))))
case("MARKET","future rejected",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["market_factory"](market(asof="2026-09-30T00:00:00Z"))))
case("MARKET","cutoff order",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["market_factory"](market(asof="2026-09-29T09:00:00Z",cutoff="2026-09-29T10:00:00Z"))))
case("MARKET","pit required",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["market_factory"](market(pit=False))))
for word in ("stock_returns","technical_context","trend","bullish","bearish"):
 case("MARKET","no "+word,lambda word=word:require(word not in R()))

case("ANALOGUE","exact binding",lambda:require(R()["historical_analogue_binding"]["record_id"]=="S6HAN_REVIEW_001"))
case("ANALOGUE","relevance uninterpreted",lambda:require(R()["historical_analogue_relevance"]=="CALLER_SELECTED_UNINTERPRETED"))
case("ANALOGUE","future rejected",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["analogue_factory"](analogue(asof="2026-09-30T00:00:00Z"))))
case("ANALOGUE","cutoff order",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["analogue_factory"](analogue(asof="2026-09-29T09:00:00Z",cutoff="2026-09-29T10:00:00Z"))))
case("ANALOGUE","pit required",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["analogue_factory"](analogue(pit=False))))
case("ANALOGUE","count consistent",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["analogue_factory"](analogue(count=2)|{"historical_analogue_payload":analogue(count=1)["historical_analogue_payload"]|{"analogue_count":2}})))
for word in ("expected_return","preferred_horizon","ranking","BUY","SELL"):
 case("ANALOGUE","no "+word,lambda word=word:require(word not in canonical_json(R())))

for opened,pending,wanted in ((True,False,"OPEN_POSITION"),(False,True,"PENDING_ENTRY"),(True,True,"OPEN_AND_PENDING"),(False,False,"NOT_PRESENT")):
 case("PORTFOLIO",wanted,lambda opened=opened,pending=pending,wanted=wanted:require(portfolio_presence(portfolio(opened=opened,pending=pending)["portfolio_context"],"RELIANCE.NS")==wanted))
case("PORTFOLIO","exact binding",lambda:require(R()["portfolio_context_binding"]["record_id"]=="S6PORTCTX_REVIEW_001"))
case("PORTFOLIO","future rejected",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["portfolio_factory"](portfolio(asof="2026-09-30T00:00:00Z"))))
case("PORTFOLIO","cutoff order",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["portfolio_factory"](portfolio(asof="2026-09-29T09:00:00Z",cutoff="2026-09-29T10:00:00Z"))))
for word in ("concentration_threshold","correlation_threshold","diversification_score","cash_sufficiency","risk_limit_breach"):
 case("PORTFOLIO","no "+word,lambda word=word:require(word not in canonical_json(R())))

case("BINDINGS","all exact",lambda:require(len(R()["direct_input_bindings"])==6))
case("BINDINGS","paired",lambda:require(all(set(x)=={"record_type","record_id","record_hash"} for x in R()["direct_input_bindings"])))
case("BINDINGS","canonical order",lambda:require(R()["direct_input_bindings"]==sorted(R()["direct_input_bindings"],key=lambda x:(x["record_type"],x["record_id"]))))
case("FACTUAL","elapsed seconds",lambda:require(R()["factual_delta_metadata"]["elapsed_seconds"]==86400))
case("FACTUAL","elapsed days",lambda:require(R()["factual_delta_metadata"]["elapsed_days"]==1))
for key in ("market_context_provided","historical_analogue_provided","portfolio_context_provided"):
 case("FACTUAL",key,lambda key=key:require(R()["factual_delta_metadata"][key] is True))
for key,value in SAFETY.items():case("SAFETY",key,lambda key=key,value=value:require(R()[key]==value))
for prohibited in ("version_2","change_history","previous_version_hash","stop_proposal","target_proposal","quantity_change","BUY","SELL","HOLD"):
 case("BOUNDARY","no "+prohibited,lambda prohibited=prohibited:require(prohibited not in canonical_json(R())))
case("HASH","review prefix",lambda:require(R()["review_snapshot_id"].startswith("S6THREVINPUT_")))
case("HASH","review id",lambda:require(R()["review_snapshot_id"]=="S6THREVINPUT_"+canonical_hash(without(R(),"review_snapshot_id","record_hash"))[:24]))
case("HASH","record hash",lambda:require(R()["record_hash"]==canonical_hash(without(R(),"record_hash"))))
case("HASH","cutoff affects identity",lambda:require(CTX["empty_factory"]("2026-09-29T13:00:00Z")["review_snapshot_id"]!=CTX["empty"]["review_snapshot_id"]))
case("HASH","evidence caller order irrelevant",lambda:require(CTX["evidence_order_factory"](["S6EV_B","S6EV_A"])["review_snapshot_id"]==CTX["evidence_order_factory"](["S6EV_A","S6EV_B"])["review_snapshot_id"]))
case("HASH","effect caller order irrelevant",lambda:require(CTX["effect_order_factory"](["S6COMEFF_B","S6COMEFF_A"])["review_snapshot_id"]==CTX["effect_order_factory"](["S6COMEFF_A","S6COMEFF_B"])["review_snapshot_id"]))

case("STORE","created",lambda:require(CTX["created"]=="CREATED"))
case("STORE","integrity",lambda:require(CTX["store"].integrity_check()["result"]=="PASS"))
case("STORE","idempotent",lambda:require(CTX["store"].freeze(**request())["status"]=="IDEMPOTENT_SUCCESS"))
case("STORE","conflict",lambda:expect(ThesisReviewInputConflict,lambda:CTX["store"].freeze(**request(evidence_ids=[]))))
case("STORE","six bindings",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM thesis_review_input_bindings").fetchone()[0]==6))
case("STORE","eight dependencies",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM thesis_review_input_dependencies").fetchone()[0]==8))
for t in TABLES:
 case("APPEND_ONLY",t+" update",lambda t=t:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"UPDATE {t} SET rowid=rowid")))
 case("APPEND_ONLY",t+" delete",lambda t=t:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"DELETE FROM {t}")))
case("STORE","trigger pairs",lambda:require(all(len(CTX["store"].connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,)).fetchall())==2 for t in TABLES)))
case("STORE","SQLite",lambda:require(CTX["store"].connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"))
case("STORE","foreign keys",lambda:require(CTX["store"].connection.execute("PRAGMA foreign_key_check").fetchall()==[]))
case("STORE","update API",lambda:expect(Stage6ThesisReviewInputError,lambda:CTX["store"].update_record()))
for field in ("new_evidence_status","company_effect_status","market_context_status","historical_analogue_status","portfolio_context_status","portfolio_subject_presence"):
 case("ABSENCE",field+" explicit",lambda field=field:require(CTX["empty"][field]=="NOT_PROVIDED"))
case("ABSENCE","never evidence of absence",lambda:require(CTX["empty"]["material_change_status"]=="NOT_EVALUATED" and CTX["empty"]["portfolio_subject_presence"]=="NOT_PROVIDED"))
for kind in ("evidence","company_effect","market_context","historical_analogue","portfolio_context"):
 case("UPSTREAM_INTEGRITY",kind,lambda kind=kind:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["integrity_failure_factory"](kind)))
for table,statement in (("thesis_review_input_records","UPDATE thesis_review_input_records SET canonical_json='{}'"),("thesis_review_input_bindings","UPDATE thesis_review_input_bindings SET record_hash='"+("0"*64)+"'"),("thesis_review_input_dependencies","UPDATE thesis_review_input_dependencies SET record_hash='"+("0"*64)+"'"),("thesis_review_input_policies","UPDATE thesis_review_input_policies SET canonical_json='{}'"),("thesis_review_input_contracts","UPDATE thesis_review_input_contracts SET canonical_json='{}'")):
 case("TAMPER",table,lambda table=table,statement=statement:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["tamper_factory"](table,statement)))
case("TAMPER","trigger loss",lambda:expect(ThesisReviewInputIntegrityFailure,lambda:CTX["tamper_factory"]("thesis_review_input_records","UPDATE thesis_review_input_records SET thesis_id=thesis_id"),"TRIGGER_MISSING"))
case("STORE","restart integrity",lambda:require(CTX["restart_factory"]()=="PASS"))

def imports():
 found=set()
 for p in (ROOT/"stage6_thesis_review_input").glob("*.py"):
  tree=ast.parse(p.read_text());found|={x.names[0].name for x in ast.walk(tree) if isinstance(x,ast.Import)};found|={str(x.module) for x in ast.walk(tree) if isinstance(x,ast.ImportFrom)}
 return found
for token in ("requests","urllib","httpx","aiohttp","socket","selenium","yfinance","gdelt","openai","transformers","torch","tensorflow","sklearn"):
 case("STATIC","no "+token,lambda token=token:require(not any(x==token or x.startswith(token+".") for x in imports())))
case("STATIC","no Stage5 import",lambda:require(not any("stage5" in x.lower() for x in imports())))
for token in ("latest","datetime.now","utcnow","current system time","automatic evidence","automatic event","automatic context"):
 case("STATIC","no "+token,lambda token=token:require(token not in "\n".join(p.read_text().lower() for p in (ROOT/"stage6_thesis_review_input").glob("*.py"))))

def main():
 temp=tempfile.TemporaryDirectory(prefix="stage6_6c_");CTX["temp"]=temp;seed_store=ThesisSeedStore(Path(temp.name)/"seed.sqlite3");seed=seed_store.freeze(source())["initial_thesis_seed"];thesis_store=TradeThesisStore(Path(temp.name)/"thesis.sqlite3",seed_store);thesis=thesis_store.materialize(seed["seed_record_id"])["trade_thesis"];CTX.update(seed_store=seed_store,thesis_store=thesis_store,thesis=thesis)
 # Focus Stage 6.6C tests on review semantics; immutable upstream validators are already covered by frozen suites.
 store_module.validate_market=lambda x:x;store_module.validate_analogue=lambda x:x;store_module.validate_portfolio_context_wrapper=lambda x:x
 ev=evidence();ef=effect();mk=market();an=analogue();po=portfolio();CTX["effect"]=ef
 stores=[FakeStore("ingestion_records","record_id",[(ev["evidence_id"],ev)]),FakeStore("company_effect_records","company_effect_record_id",[(ef["company_effect_record_id"],ef)]),FakeStore("market_context_records","market_context_record_id",[(mk["market_context_record_id"],mk)]),FakeStore("historical_analogue_records","historical_analogue_id",[(an["historical_analogue_payload"]["historical_analogue_id"],an)]),FakeStore("portfolio_context_records","portfolio_context_id",[(po["portfolio_context"]["portfolio_context_id"],po)])]
 store=ThesisReviewInputStore(Path(temp.name)/"review.sqlite3",thesis_store,evidence_store=stores[0],company_effect_store=stores[1],market_context_store=stores[2],historical_analogue_store=stores[3],portfolio_context_store=stores[4]);CTX["store"]=store;res=store.freeze(**request());CTX["created"]=res["status"];CTX["record"]=res["review_input_snapshot"]
 def one_shot(**kwargs):
  folder=tempfile.TemporaryDirectory();s=ThesisReviewInputStore(Path(folder.name)/"r.sqlite3",thesis_store,**kwargs)
  try:return s.freeze(**request(**{k:None if k.endswith('_id') and k!='thesis_id' else [] for k in ()}))
  finally:s.close();folder.cleanup()
 def evidence_failure(record):
  f=FakeStore("ingestion_records","record_id",[(record["evidence_id"],record)]);s=ThesisReviewInputStore(Path(temp.name)/(record["evidence_id"]+".sqlite3"),thesis_store,evidence_store=f)
  try:return s.freeze(**request(evidence_ids=[record["evidence_id"]],company_effect_ids=[],market_context_id=None,historical_analogue_id=None,portfolio_context_id=None))
  finally:s.close();f.close()
 CTX["old_evidence_store_factory"]=lambda:evidence_failure(evidence("S6EV_OLD","2026-09-28T10:00:00Z"));CTX["future_evidence_store_factory"]=lambda:evidence_failure(evidence("S6EV_FUTURE","2026-09-30T00:00:00Z"));CTX["acquisition_store_factory"]=lambda:evidence_failure(evidence("S6EV_ACQ","2026-09-28T18:00:00Z","ACQUISITION_ATTEMPT"))
 def optional(kind,record):
  table,key={"market":("market_context_records","market_context_record_id"),"analogue":("historical_analogue_records","historical_analogue_id"),"portfolio":("portfolio_context_records","portfolio_context_id")}[kind];identity=record[key.replace("_id","")+"_id"] if False else (record["market_context_record_id"] if kind=="market" else record["historical_analogue_payload"]["historical_analogue_id"] if kind=="analogue" else record["portfolio_context"]["portfolio_context_id"]);f=FakeStore(table,key,[(identity,record)]);kwargs={kind+"_context_store" if kind!="analogue" else "historical_analogue_store":f};s=ThesisReviewInputStore(Path(temp.name)/(kind+identity+".sqlite3"),thesis_store,**kwargs)
  try:return s.freeze(**request(evidence_ids=[],company_effect_ids=[],market_context_id=identity if kind=="market" else None,historical_analogue_id=identity if kind=="analogue" else None,portfolio_context_id=identity if kind=="portfolio" else None))
  finally:s.close();f.close()
 CTX["market_factory"]=lambda x:optional("market",x);CTX["analogue_factory"]=lambda x:optional("analogue",x);CTX["portfolio_factory"]=lambda x:optional("portfolio",x)
 def effect_snapshot(value):
  x=effect("S6COMEFF_"+value,value);f=FakeStore("company_effect_records","company_effect_record_id",[(x["company_effect_record_id"],x)]);s=ThesisReviewInputStore(Path(temp.name)/(value+".sqlite3"),thesis_store,company_effect_store=f)
  try:return s.freeze(**request(evidence_ids=[],company_effect_ids=[x["company_effect_record_id"]],market_context_id=None,historical_analogue_id=None,portfolio_context_id=None))["review_input_snapshot"]
  finally:s.close();f.close()
 CTX["effect_snapshot_factory"]=effect_snapshot
 def empty_snapshot(cutoff):
  s=ThesisReviewInputStore(Path(temp.name)/(cutoff.replace(":","")+".sqlite3"),thesis_store)
  try:return s.freeze(**request(review_cutoff=cutoff,evidence_ids=[],company_effect_ids=[],market_context_id=None,historical_analogue_id=None,portfolio_context_id=None))["review_input_snapshot"]
  finally:s.close()
 CTX["empty_factory"]=empty_snapshot;CTX["empty"]=empty_snapshot("2026-09-29T14:00:00Z")
 def order_snapshot(ids,kind):
  if kind=="evidence":records=[evidence(x,"2026-09-28T18:00:00Z") for x in ids];f=FakeStore("ingestion_records","record_id",[(x["evidence_id"],x) for x in records]);kwargs={"evidence_store":f};q=request(evidence_ids=ids,company_effect_ids=[],market_context_id=None,historical_analogue_id=None,portfolio_context_id=None)
  else:records=[effect(x,"MIXED",event="E"+x[-1]) for x in ids];f=FakeStore("company_effect_records","company_effect_record_id",[(x["company_effect_record_id"],x) for x in records]);kwargs={"company_effect_store":f};q=request(evidence_ids=[],company_effect_ids=ids,market_context_id=None,historical_analogue_id=None,portfolio_context_id=None)
  s=ThesisReviewInputStore(Path(temp.name)/(kind+canonical_hash(ids)+".sqlite3"),thesis_store,**kwargs)
  try:return s.freeze(**q)["review_input_snapshot"]
  finally:s.close();f.close()
 CTX["evidence_order_factory"]=lambda ids:order_snapshot(ids,"evidence");CTX["effect_order_factory"]=lambda ids:order_snapshot(ids,"effect")
 def integrity_failure(kind):
  index={"evidence":0,"company_effect":1,"market_context":2,"historical_analogue":3,"portfolio_context":4}[kind];stores[index].passes=False
  try:
   q=request();
   if kind!="evidence":q["evidence_ids"]=[]
   if kind!="company_effect":q["company_effect_ids"]=[]
   if kind!="market_context":q["market_context_id"]=None
   if kind!="historical_analogue":q["historical_analogue_id"]=None
   if kind!="portfolio_context":q["portfolio_context_id"]=None
   s=ThesisReviewInputStore(Path(temp.name)/("bad_"+kind+".sqlite3"),thesis_store,evidence_store=stores[0],company_effect_store=stores[1],market_context_store=stores[2],historical_analogue_store=stores[3],portfolio_context_store=stores[4]);
   try:return s.freeze(**q)
   finally:s.close()
  finally:stores[index].passes=True
 CTX["integrity_failure_factory"]=integrity_failure
 def tamper(table,statement):
  folder=tempfile.TemporaryDirectory();s=ThesisReviewInputStore(Path(folder.name)/"r.sqlite3",thesis_store,evidence_store=stores[0],company_effect_store=stores[1],market_context_store=stores[2],historical_analogue_store=stores[3],portfolio_context_store=stores[4]);s.freeze(**request())
  try:s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(statement);s.connection.commit();return s.integrity_check()
  finally:s.close();folder.cleanup()
 CTX["tamper_factory"]=tamper
 def restart():
  folder=tempfile.TemporaryDirectory();path=Path(folder.name)/"r.sqlite3";s=ThesisReviewInputStore(path,thesis_store,evidence_store=stores[0],company_effect_store=stores[1],market_context_store=stores[2],historical_analogue_store=stores[3],portfolio_context_store=stores[4]);s.freeze(**request());s.close();s=ThesisReviewInputStore(path,thesis_store,evidence_store=stores[0],company_effect_store=stores[1],market_context_store=stores[2],historical_analogue_store=stores[3],portfolio_context_store=stores[4])
  try:return s.integrity_check()["result"]
  finally:s.close();folder.cleanup()
 CTX["restart_factory"]=restart
 rows=[]
 for i,(group,name,fn) in enumerate(CASES,1):
  try:fn();rows.append({"test_id":i,"test_group":group,"test_name":name,"result":"PASS","detail":""})
  except Exception as exc:rows.append({"test_id":i,"test_group":group,"test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}: {exc}"})
 OUT.parent.mkdir(parents=True,exist_ok=True)
 with OUT.open("w",newline="",encoding="utf-8") as stream:writer=csv.DictWriter(stream,fieldnames=("test_id","test_group","test_name","result","detail"),lineterminator="\n");writer.writeheader();writer.writerows(rows)
 passed=sum(x["result"]=="PASS" for x in rows);print(f"Stage 6.6C: {passed}/{len(rows)} PASS");[print(x) for x in rows if x["result"]!="PASS"]
 store.close();[x.close() for x in stores];thesis_store.close();seed_store.close();temp.cleanup();return 0 if passed==len(rows) and len(rows)>=180 else 1
if __name__=="__main__":raise SystemExit(main())
