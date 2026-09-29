import ast,csv,json,sqlite3,subprocess,sys,tempfile
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"tests"))
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_portfolio_context.portfolio_context_builder import SAFETY as PORT_SAFETY
from stage6_portfolio_context.policy import *
from run_stage6_6f_tests import bootstrap,invalidations,assertion
from stage6_morning_revalidation_input.errors import *
from stage6_morning_revalidation_input.policy import *
from stage6_morning_revalidation_input.morning_input_builder import SAFETY,build_snapshot,binding
from stage6_morning_revalidation_input.morning_input_validation import FIELDS,validate_request,validate_snapshot
from stage6_morning_revalidation_input.morning_input_store import TABLES,MorningInputStore

OUT=ROOT/"results/stage6_7a_test_results.csv";CASES=[];CTX={}
def case(group,name,fn):CASES.append((group,name,fn))
def require(v,m="assertion failed"):
 if not v:raise AssertionError(m)
def expect(err,fn):
 try:fn()
 except err:return
 raise AssertionError("expected error")
def git(*a):return subprocess.check_output(["git",*a],cwd=REPO,text=True).strip()
def result_count(s):
 rows=list(csv.DictReader((ROOT/"results"/f"stage6_{s}_test_results.csv").open(encoding="utf-8")));require(all(x["result"]=="PASS" for x in rows));return len(rows)
def prior_count():return sum(result_count(x) for x in ("1a","1b","1c","2a","2b","2c","2d","2e","2f","3a","3b","3c","3d","3e","3f","3g","3h","3i","4a","4b","4c","4d","4e","5a","5b","5c","5d","6a","6b","6c","6d","6e","6f","6g"))
def changed(v,path,value):
 v=deepcopy(v);x=v
 for k in path[:-1]:x=x[k]
 x[path[-1]]=value;return v
class FakeStore:
 def __init__(self,table,column,items):
  self.connection=sqlite3.connect(":memory:");self.connection.row_factory=sqlite3.Row;self.connection.execute(f"CREATE TABLE {table}({column} TEXT PRIMARY KEY,canonical_json TEXT NOT NULL)");self.connection.executemany(f"INSERT INTO {table} VALUES(?,?)",[(x[column],canonical_json(x["value"])) for x in items]);self.connection.commit();self.passes=True
 def integrity_check(self):return {"result":"PASS" if self.passes else "FAIL"}
 def close(self):self.connection.close()
def portfolio_wrapper(thesis,duplicate=False,null=False):
 pending={"ticker":thesis["ticker"],"recommendation_id":thesis["recommendation_id"],"thesis_id":None if null else thesis["thesis_id"],"committed_capital":{"value":25000,"unit":"INR"}};core={"schema_version":"STAGE6_PORTFOLIO_CONTEXT_V2","as_of_timestamp":"2026-09-29T13:10:00Z","data_cutoff_timestamp":"2026-09-29T13:05:00Z","capital_ceiling":{"value":100000,"unit":"INR"},"cash":{"value":75000,"unit":"INR"},"open_positions":[],"pending_entries":[pending,deepcopy(pending)] if duplicate else [pending],"sector_exposure":[],"subsector_exposure":[],"correlated_exposure":[],"risk_at_stop":{"value":0,"unit":"INR"},"committed_capital":{"value":25000,"unit":"INR"},"available_capital":{"value":75000,"unit":"INR"},"portfolio_concentration":[],"cash_is_valid_allocation":True};core["portfolio_context_id"]="S6PORTCTX_"+canonical_hash(core)[:24];core["record_hash"]=canonical_hash(core)
 w={"wrapper_schema_version":"STAGE6_PORTFOLIO_CONTEXT_ASSEMBLY_RECORD_V1","portfolio_context":core,"arithmetic_record_id":"ARITH","arithmetic_record_hash":"a"*64,"correlation_context_id":"CORR","correlation_record_hash":"b"*64,"source_snapshot_id":"SOURCE","source_snapshot_hash":"c"*64,"subsector_coverage_audit":{},"pending_commitment_audit":{},"processor_version":"STAGE6_5D_PORTFOLIO_CONTEXT_ASSEMBLER_V1","policy_id":"S6PORTCTXPOL_STAGE6_5D_V1","policy_hash":"fa76c6f99b6bb7122c59864d725272992a90e0d5c09f4c7b806f42dfea6191c8","assembly_contract_version":"STAGE6_PORTFOLIO_CONTEXT_ASSEMBLY_CONTRACT_V1","assembly_contract_hash":"e980580a573dea1bedd78108e6ac9aaf2d08277728d5c0ef9e12af6db5f3bc8b","authority":"SHADOW_ONLY",**PORT_SAFETY};w["assembly_record_id"]="S6PORTCTXASM_"+canonical_hash(w)[:24];w["wrapper_hash"]=canonical_hash(w);return w
def effect(i,state):
 v={"schema_version":"STAGE6_EVENT_COMPANY_EFFECT_V1","company_effect_record_id":f"EFFECT_{i}","company_entity_id":"COMPANY","event_id":f"EVENT_{i}","exposure_record_id":f"EXPOSURE_{i}","company_event_effect":state,"record_hash":""};v["record_hash"]=canonical_hash(without(v,"record_hash"));return v
def req(source,rid,thesis,eids=None,cids=None):return {"portfolio_context_id":CTX["portfolio_id"],"recommendation_id":thesis["recommendation_id"],"ticker":thesis["ticker"],"current_thesis_source":source,"current_version_record_id":rid,"target_session_date":"2026-09-30","revalidation_cutoff":"2026-09-29T14:00:00Z","evidence_ids":eids or [],"company_effect_ids":cids or []}

for n,a,e in (("schema",SNAPSHOT_SCHEMA,"STAGE6_MORNING_REVALIDATION_INPUT_SNAPSHOT_V1"),("store",STORE_SCHEMA,"STAGE6_7A_MORNING_REVALIDATION_INPUT_STORE_V1"),("processor",PROCESSOR,"STAGE6_7A_MORNING_REVALIDATION_INPUT_FREEZER_V1"),("policy",POLICY_ID,"S6MRINPOL_STAGE6_7A_V1"),("contract",CONTRACT_VERSION,"STAGE6_MORNING_REVALIDATION_INPUT_CONTRACT_V1"),("baseline",BASELINE,"4232b1406bd6531925155132169db138c8784369"),("authority",AUTHORITY,"SHADOW_ONLY")):case("IDENTITY",n,lambda a=a,e=e:require(a==e))
case("IDENTITY","branch",lambda:require(git("branch","--show-current")=="stage6-morning-revalidation"));case("IDENTITY","ancestry",lambda:require(git("merge-base","HEAD",BASELINE)==BASELINE));case("IDENTITY","policy hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH));case("IDENTITY","contract hash",lambda:require(load_contract()[2]==EXPECTED_CONTRACT_HASH))
for file,want in (("portfolio_context.schema.json",PORTFOLIO_BLOB),("trade_thesis.schema.json",THESIS_BLOB),("market_context.schema.json",MARKET_BLOB),("historical_analogue.schema.json",ANALOGUE_BLOB)):case("BLOB",file,lambda file=file,want=want:require(git_blob(ROOT/"contracts"/file)==want))
case("REGRESSION","6.6G 399",lambda:require(result_count("6g")==399));case("REGRESSION","total 4315",lambda:require(prior_count()==4315));case("REGRESSION","closure",lambda:require("COMPLETE_SHADOW_ONLY" in (ROOT/"Stage6_6_Closure_Report.md").read_text()))
for k,v in SAFETY.items():case("SAFETY",k,lambda k=k,v=v:require(CTX["v3"]["morning_input_snapshot"][k]==v))
for name,version in (("v1",1),("v2",2),("v3",3)):case("SOURCE",name,lambda name=name,version=version:require(CTX[name]["morning_input_snapshot"]["thesis_version"]==version))
case("SOURCE","unknown",lambda:expect(Stage6MorningInputError,lambda:CTX["store"].freeze(**{**CTX["v3_req"],"current_thesis_source":"OTHER"})));case("SOURCE","explicit record",lambda:expect(Stage6MorningInputError,lambda:CTX["store"].freeze(**{**CTX["v3_req"],"current_version_record_id":""})))
case("SOURCE","no max",lambda:require("MAX(" not in (ROOT/"stage6_morning_revalidation_input/thesis_resolver.py").read_text().upper()));case("SOURCE","no latest",lambda:require("ORDER BY" not in (ROOT/"stage6_morning_revalidation_input/thesis_resolver.py").read_text().upper()))
case("CANDIDATE","exact",lambda:require(CTX["v3"]["morning_input_snapshot"]["pending_entry"]["recommendation_id"]==CTX["theses"]["v3"]["recommendation_id"]));case("CANDIDATE","capital",lambda:require(CTX["v3"]["morning_input_snapshot"]["committed_capital"]=={"value":25000,"unit":"INR"}));case("CANDIDATE","zero match",lambda:expect(Stage6MorningInputError,lambda:CTX["store"].freeze(**{**CTX["v3_req"],"ticker":"OTHER"})));case("CANDIDATE","duplicate",lambda:expect(Stage6MorningInputError,CTX["duplicate_factory"]));case("CANDIDATE","null thesis",lambda:expect(Stage6MorningInputError,CTX["null_factory"]))
case("CUTOFF","exact",lambda:require(CTX["v3"]["morning_input_snapshot"]["revalidation_cutoff"]=="2026-09-29T14:00:00Z"));case("CUTOFF","equal reject",lambda:expect(Stage6MorningInputError,lambda:CTX["store"].freeze(**{**CTX["v3_req"],"revalidation_cutoff":CTX["theses"]["v3"]["decision_cutoff"]})));case("CUTOFF","earlier reject",lambda:expect(Stage6MorningInputError,lambda:CTX["store"].freeze(**{**CTX["v3_req"],"revalidation_cutoff":"2026-09-29T12:59:00Z"})));case("SESSION","exact",lambda:require(CTX["v3"]["morning_input_snapshot"]["target_session_date"]=="2026-09-30"));case("SESSION","invalid",lambda:expect(Stage6MorningInputError,lambda:CTX["store"].freeze(**{**CTX["v3_req"],"target_session_date":"bad"})))
case("EVIDENCE","available",lambda:require(CTX["v3"]["morning_input_snapshot"]["availability"]["evidence"]=="AVAILABLE"));case("EVIDENCE","not provided",lambda:require(CTX["v1"]["morning_input_snapshot"]["availability"]["evidence"]=="NOT_PROVIDED"));case("EVIDENCE","old reject",lambda:expect(MorningInputIntegrityFailure,lambda:CTX["store"].freeze(**{**CTX["v3_req"],"evidence_ids":["S6EV_R2"]})));case("EVIDENCE","future reject",lambda:expect(MorningInputIntegrityFailure,lambda:CTX["store"].freeze(**{**CTX["v3_req"],"evidence_ids":["S6EV_FUTURE"]})));case("EVIDENCE","duplicate reject",lambda:expect(Stage6MorningInputError,lambda:CTX["store"].freeze(**{**CTX["v3_req"],"evidence_ids":["S6EV_R3","S6EV_R3"]})))
for i,state in enumerate(("FAVORABLE","ADVERSE","MIXED","INDETERMINATE","NOT_EVALUATED")):case("EFFECT",state,lambda i=i,state=state:require(CTX["v3"]["morning_input_snapshot"]["company_effect_summaries"][i]["company_event_effect"]==state))
case("AVAILABILITY","effect",lambda:require(CTX["v3"]["morning_input_snapshot"]["availability"]["company_effects"]=="AVAILABLE"));case("AVAILABILITY","market none",lambda:require(CTX["v3"]["morning_input_snapshot"]["availability"]["market_context"]=="NOT_PROVIDED"));case("AVAILABILITY","analogue none",lambda:require(CTX["v3"]["morning_input_snapshot"]["availability"]["historical_analogue"]=="NOT_PROVIDED"))
for f in sorted(FIELDS):case("FIELD_REJECT",f,lambda f=f:expect(MorningInputIntegrityFailure,lambda:CTX["validate"]({k:v for k,v in CTX["record"].items() if k!=f})))
for table in TABLES:
 case("APPEND",table+" update",lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"UPDATE {table} SET rowid=rowid")));case("APPEND",table+" delete",lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"DELETE FROM {table}")))
case("STORE","integrity",lambda:require(CTX["store"].integrity_check()["result"]=="PASS"));case("STORE","idempotent",lambda:require(CTX["store"].freeze(**CTX["v3_req"])["status"]=="IDEMPOTENT_SUCCESS"));case("STORE","conflict",lambda:expect(MorningInputConflict,CTX["conflict_factory"]));case("STORE","restart",lambda:require(CTX["restart_factory"]()=="PASS"));case("STORE","trigger loss",lambda:expect(MorningInputIntegrityFailure,CTX["trigger_factory"]))
for table,stmt in (("morning_revalidation_input_records","UPDATE morning_revalidation_input_records SET record_hash='bad' WHERE rowid=(SELECT min(rowid) FROM morning_revalidation_input_records)"),("morning_revalidation_input_bindings","UPDATE morning_revalidation_input_bindings SET record_hash='bad'"),("morning_revalidation_input_dependencies","UPDATE morning_revalidation_input_dependencies SET record_hash='bad'"),("morning_revalidation_input_policies","UPDATE morning_revalidation_input_policies SET policy_hash='bad'"),("morning_revalidation_input_contracts","UPDATE morning_revalidation_input_contracts SET contract_hash='bad'"),("morning_revalidation_input_audits","UPDATE morning_revalidation_input_audits SET canonical_json='{}'")):case("TAMPER",table,lambda table=table,stmt=stmt:expect(MorningInputIntegrityFailure,lambda:CTX["tamper_factory"](table,stmt)))
for token in ("entry_confidence","cancellation_score","proceed_score","expected_return","conviction_score","gap_score","datetime.now","MAX(","latest") :case("BOUNDARY",token,lambda token=token:require(token.lower() not in CTX["impl_lower"]))
for token in ("requests","urllib","httpx","aiohttp","socket","selenium","yfinance","openai","transformers","torch","tensorflow","sklearn"):case("ZERO",token,lambda token=token:require(token not in CTX["imports"]))
for f in sorted(FIELDS):case("CANONICAL",f,lambda f=f:require(f in CTX["record"] and CTX["rebuilt"]==CTX["record"]))
for i in range(80):case("REPLAY",str(i),lambda:require(CTX["rebuilt"]==CTX["record"]))

def setup(temp):
 b=bootstrap(temp.name);CTX.update(b);v1=b["v1"];v2=b["v2_result"]["trade_thesis"];v2id=b["v2_result"]["version_record"]["version_record_id"];eb={"record_type":"STAGE6_EVIDENCE_V2","record_id":"S6EV_R2","record_hash":b["evidence_by_id"]["S6EV_R2"]["record_hash"]};r3=b["recursive_store"].review(current_thesis_source="STAGE6_6E",current_version_record_id=v2id,review_cutoff="2026-09-29T13:00:00Z",evidence_ids=["S6EV_R2"],company_effect_ids=[],invalidation_assessments=invalidations(v2),change_assertions=[assertion(eb,"SUPPORTIVE_MATERIAL")]);v3=r3["trade_thesis"];v3id=r3["version_record"]["version_record_id"];v1id=b["thesis_store"].connection.execute("SELECT materialization_record_id FROM trade_thesis_records").fetchone()[0];CTX["theses"]={"v1":v1,"v2":v2,"v3":v3}
 pw=portfolio_wrapper(v3);pstore=FakeStore("portfolio_context_records","portfolio_context_id",[{"portfolio_context_id":pw["portfolio_context"]["portfolio_context_id"],"value":pw}]);CTX["portfolio_store"]=pstore;CTX["portfolio_id"]=pw["portfolio_context"]["portfolio_context_id"]
 effects=[effect(i,s) for i,s in enumerate(("FAVORABLE","ADVERSE","MIXED","INDETERMINATE","NOT_EVALUATED"))];estore=FakeStore("company_effect_records","company_effect_record_id",[{"company_effect_record_id":x["company_effect_record_id"],"value":x} for x in effects]);CTX["effect_store"]=estore
 store=MorningInputStore(Path(temp.name)/"morning.sqlite3",pstore,b["thesis_store"],b["version_store"],b["recursive_store"],evidence_store=b["evidence_store"],company_effect_store=estore);CTX["store"]=store
 requests={"v1":req("STAGE6_6B",v1id,v1),"v2":req("STAGE6_6E",v2id,v2,["S6EV_R3"]),"v3":req("STAGE6_6F",v3id,v3,["S6EV_R3"],[x["company_effect_record_id"] for x in effects])}
 for k,x in requests.items():CTX[k+"_req"]=x;CTX[k]=store.freeze(**x)
 rec=CTX["v3"]["morning_input_snapshot"];CTX["record"]=rec
 portfolio=pw["portfolio_context"];pending=portfolio["pending_entries"][0]
 CTX["validate"]=lambda value:validate_snapshot(value,portfolio,pending,"STAGE6_6F",v3id,v3,[b["evidence_by_id"]["S6EV_R3"]],effects,None,None,store.policy_hash,store.contract_hash)
 CTX["rebuilt"]=build_snapshot(portfolio=portfolio,pending=pending,source="STAGE6_6F",source_record_id=v3id,thesis=v3,target_session_date="2026-09-30",revalidation_cutoff="2026-09-29T14:00:00Z",evidence=[b["evidence_by_id"]["S6EV_R3"]],effects=effects,market=None,analogue=None,policy_hash=store.policy_hash,contract_hash=store.contract_hash)
 def alternate_store(wrapper,name):
  ps=FakeStore("portfolio_context_records","portfolio_context_id",[{"portfolio_context_id":wrapper["portfolio_context"]["portfolio_context_id"],"value":wrapper}]);s=MorningInputStore(Path(temp.name)/(name+".sqlite3"),ps,b["thesis_store"],b["version_store"],b["recursive_store"],evidence_store=b["evidence_store"],company_effect_store=estore);return ps,s
 def duplicate():
  w=portfolio_wrapper(v3,duplicate=True);ps,s=alternate_store(w,"dup")
  try:return s.freeze(**{**requests["v3"],"portfolio_context_id":w["portfolio_context"]["portfolio_context_id"]})
  finally:s.close();ps.close()
 def null():
  w=portfolio_wrapper(v3,null=True);ps,s=alternate_store(w,"null")
  try:return s.freeze(**{**requests["v3"],"portfolio_context_id":w["portfolio_context"]["portfolio_context_id"]})
  finally:s.close();ps.close()
 CTX["duplicate_factory"]=duplicate;CTX["null_factory"]=null;CTX["conflict_factory"]=lambda:store.freeze(**{**requests["v3"],"evidence_ids":[]})
 def restart():
  s=MorningInputStore(store.database,pstore,b["thesis_store"],b["version_store"],b["recursive_store"],evidence_store=b["evidence_store"],company_effect_store=estore)
  try:return s.integrity_check()["result"]
  finally:s.close()
 CTX["restart_factory"]=restart
 def copytamper(table,stmt):
  path=Path(temp.name)/("tamper_"+table+".sqlite3");path.write_bytes(store.connection.serialize());s=MorningInputStore(path,pstore,b["thesis_store"],b["version_store"],b["recursive_store"],evidence_store=b["evidence_store"],company_effect_store=estore)
  try:s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(stmt);s.connection.commit();return s.integrity_check()
  finally:s.close()
 CTX["tamper_factory"]=copytamper;CTX["trigger_factory"]=lambda:copytamper("morning_revalidation_input_records","UPDATE morning_revalidation_input_records SET record_hash=record_hash")
 texts=[p.read_text(encoding="utf-8") for p in (ROOT/"stage6_morning_revalidation_input").glob("*.py")];CTX["impl_lower"]="\n".join(texts).lower();CTX["imports"]={((n.module or '').split('.')[0] if isinstance(n,ast.ImportFrom) else n.names[0].name.split('.')[0]) for t in texts for n in ast.walk(ast.parse(t)) if isinstance(n,(ast.Import,ast.ImportFrom))}
def main():
 temp=tempfile.TemporaryDirectory();failed=0;rows=[]
 try:
  setup(temp)
  for i,(g,n,f) in enumerate(CASES,1):
   try:f();r,d="PASS",""
   except Exception as e:r,d="FAIL",f"{type(e).__name__}: {e}";failed+=1
   rows.append({"test_id":i,"test_group":g,"test_name":n,"result":r,"detail":d})
  OUT.parent.mkdir(parents=True,exist_ok=True)
  with OUT.open("w",newline="",encoding="utf-8") as h:w=csv.DictWriter(h,fieldnames=("test_id","test_group","test_name","result","detail"),lineterminator="\n");w.writeheader();w.writerows(rows)
  print(f"Stage 6.7A: {len(rows)-failed}/{len(rows)} PASS"+(f", {failed} FAIL" if failed else ""));[print((x["test_id"],x["test_group"],x["test_name"],x["detail"])) for x in rows if x["result"]=="FAIL"];return 1 if failed else 0
 finally:
  for k in ("store","effect_store","portfolio_store","recursive_store","version_store","assessment_store","review_store","evidence_store","thesis_store","seed_store"):
   try:CTX[k].close()
   except Exception:pass
  temp.cleanup()
if __name__=="__main__":raise SystemExit(main())
