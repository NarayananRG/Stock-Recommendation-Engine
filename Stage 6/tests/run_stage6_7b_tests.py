import ast,csv,json,sqlite3,subprocess,sys,tempfile
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"tests"))
import run_stage6_7a_tests as s7a
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_market_context.market_context_builder import SAFETY as MARKET_SAFETY,PAYLOAD_FIELDS
from stage6_morning_revalidation_input.morning_input_store import MorningInputStore
from stage6_morning_revalidation_proposal.errors import *
from stage6_morning_revalidation_proposal.policy import *
from stage6_morning_revalidation_proposal.code_manifest import FILES,build_code_manifest,verify_code_manifest
from stage6_morning_revalidation_proposal.decision_rules import decide,REASONS
from stage6_morning_revalidation_proposal.morning_revalidation_proposal_builder import SAFETY,build_proposal,canonical_assertions,canonical_assessments,support_key
from stage6_morning_revalidation_proposal.morning_revalidation_proposal_validation import validate_inputs,validate_proposal
from stage6_morning_revalidation_proposal.morning_revalidation_proposal_store import TABLES,MorningRevalidationProposalStore

OUT=ROOT/"results/stage6_7b_test_results.csv";CASES=[];CTX={}
def case(group,name,fn):CASES.append((group,name,fn))
def require(value,message="assertion failed"):
 if not value:raise AssertionError(message)
def expect(error,fn):
 try:fn()
 except error:return
 raise AssertionError("expected error")
def git(*args):return subprocess.check_output(["git",f"--git-dir={REPO/'_git'}",f"--work-tree={REPO}",*args],cwd=REPO,text=True).strip()
def result_count(stage):
 rows=list(csv.DictReader((ROOT/"results"/f"stage6_{stage}_test_results.csv").open(encoding="utf-8")));require(all(x["result"]=="PASS" for x in rows));return len(rows)
def prior_count():return sum(result_count(x) for x in ("1a","1b","1c","2a","2b","2c","2d","2e","2f","3a","3b","3c","3d","3e","3f","3g","3h","3i","4a","4b","4c","4d","4e","5a","5b","5c","5d","6a","6b","6c","6d","6e","6f","6g","7a"))
def ib(snapshot):return {"record_type":INPUT_SCHEMA,"record_id":snapshot["morning_snapshot_id"],"record_hash":snapshot["record_hash"]}
def assessments(thesis,status="NOT_TRIGGERED",support=None):return [{"condition_index":i,"condition_text":text,"evaluation_status":status,"supporting_bindings":[] if status=="NOT_EVALUATED" else [deepcopy(support)]} for i,text in enumerate(thesis["invalidation_conditions"])]
def assertion(state,support,reason="MULTI_SOURCE_REVALIDATION"):return {"assessment":state,"reason_code":reason,"supporting_bindings":[deepcopy(support)]}

for name,actual,wanted in (
 ("schema",PROPOSAL_SCHEMA,"STAGE6_MORNING_REVALIDATION_PROPOSAL_V1"),("store",STORE_SCHEMA,"STAGE6_7B_MORNING_REVALIDATION_PROPOSAL_STORE_V1"),("processor",PROCESSOR,"STAGE6_7B_MORNING_REVALIDATION_PROPOSER_V1"),("policy",POLICY_ID,"S6MRPROPPOL_STAGE6_7B_V1"),("contract",CONTRACT_VERSION,"STAGE6_MORNING_REVALIDATION_PROPOSAL_CONTRACT_V1"),("engine",DECISION_ENGINE,"STAGE6_MORNING_REVALIDATION_RULES_V1"),("manifest",MANIFEST_VERSION,"STAGE6_7B_DECISION_CODE_MANIFEST_V1"),("baseline",BASELINE,"66c6b7bdbc2fb3dd993e6a2900215a74d5f3c415"),("authority",AUTHORITY,"SHADOW_ONLY")):case("IDENTITY",name,lambda actual=actual,wanted=wanted:require(actual==wanted))
case("BASELINE","branch",lambda:require(git("branch","--show-current")=="stage6-morning-revalidation"))
case("BASELINE","exact parent",lambda:require(git("rev-parse",f"{BASELINE}^")=="4232b1406bd6531925155132169db138c8784369"))
case("BASELINE","descendant safe",lambda:require(git("merge-base","HEAD",BASELINE)==BASELINE))
case("BASELINE","7A count",lambda:require(result_count("7a")==305));case("BASELINE","prior count",lambda:require(prior_count()-305==4315));case("BASELINE","combined",lambda:require(prior_count()==4620))
case("IDENTITY","policy hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH));case("IDENTITY","contract hash",lambda:require(load_contract()[2]==EXPECTED_CONTRACT_HASH));case("IDENTITY","manifest hash",lambda:require(build_code_manifest()["decision_code_hash"]==CTX["code_hash"]))
case("FROZEN","generic shadow",lambda:require(git_blob(ROOT/"contracts/shadow_decision.schema.json")==GENERIC_SHADOW_BLOB))
case("FROZEN","7A unchanged",lambda:require(not git("diff","--name-only",BASELINE,"--","Stage 6/stage6_morning_revalidation_input","Stage 6/tests/run_stage6_7a_tests.py","Stage 6/results/stage6_7a_contract.json")))
for key,value in SAFETY.items():case("SAFETY",key,lambda key=key,value=value:require(CTX["record"][key]==value))
for decision in ("ENTRY_VALID","WAIT","CANCEL_ENTRY"):case("VOCAB",decision,lambda decision=decision:require(decision in DECISIONS))
for decision in ("PRICE_OUTSIDE_ENTRY_RANGE","NO_NEW_POSITION","HOLD","REDUCE","EXIT","BUY"):case("VOCAB_PROHIBITED",decision,lambda decision=decision:require(decision not in DECISIONS))
for status in sorted(INVALIDATION_STATUSES):case("INVALIDATION_STATUS",status,lambda status=status:require(status in INVALIDATION_STATUSES))
for state in sorted(ASSERTION_ASSESSMENTS):case("ASSERTION_STATUS",state,lambda state=state:require(state in ASSERTION_ASSESSMENTS))
for reason in sorted(ASSERTION_REASONS):case("ASSERTION_REASON",reason,lambda reason=reason:require(reason in ASSERTION_REASONS))
for reason in sorted(REASONS):case("PROPOSAL_REASON",reason,lambda reason=reason:require(reason in REASONS))

RULES=(
 ("invalidated","THESIS_INVALIDATED",["NOT_TRIGGERED"],[],"AVAILABLE","CANCEL_ENTRY","CURRENT_THESIS_INVALIDATED"),
 ("triggered","THESIS_ACTIVE",["TRIGGERED"],[],"AVAILABLE","CANCEL_ENTRY","INVALIDATION_TRIGGERED"),
 ("incomplete","THESIS_ACTIVE",["NOT_EVALUATED"],[],"AVAILABLE","WAIT","INVALIDATION_NOT_FULLY_EVALUATED"),
 ("missing market","THESIS_ACTIVE",["NOT_TRIGGERED"],[],"NOT_PROVIDED","WAIT","MARKET_CONTEXT_NOT_PROVIDED"),
 ("indeterminate","THESIS_ACTIVE",["NOT_TRIGGERED"],["INDETERMINATE"],"AVAILABLE","WAIT","CHANGE_ASSERTION_INDETERMINATE"),
 ("conflict","THESIS_ACTIVE",["NOT_TRIGGERED"],["SUPPORTIVE_MATERIAL","ADVERSE_MATERIAL"],"AVAILABLE","WAIT","CONFLICTING_MATERIAL_CHANGE"),
 ("adverse","THESIS_ACTIVE",["NOT_TRIGGERED"],["ADVERSE_MATERIAL"],"AVAILABLE","WAIT","ADVERSE_MATERIAL_CHANGE"),
 ("supportive","THESIS_ACTIVE",["NOT_TRIGGERED"],["SUPPORTIVE_MATERIAL"],"AVAILABLE","ENTRY_VALID","SUPPORTIVE_REVALIDATION"),
 ("nonmaterial","THESIS_ACTIVE",["NOT_TRIGGERED"],["NON_MATERIAL"],"AVAILABLE","ENTRY_VALID","NO_MATERIAL_ENTRY_BLOCKER"),
 ("zero","THESIS_ACTIVE",["NOT_TRIGGERED"],[],"AVAILABLE","ENTRY_VALID","NO_MATERIAL_ENTRY_BLOCKER"),
 ("strengthened","THESIS_STRENGTHENED",["NOT_TRIGGERED"],[],"AVAILABLE","ENTRY_VALID","NO_MATERIAL_ENTRY_BLOCKER"),
 ("weakened","THESIS_WEAKENED",["NOT_TRIGGERED"],[],"AVAILABLE","ENTRY_VALID","NO_MATERIAL_ENTRY_BLOCKER"),
)
for name,thesis,states,changes,market,want,reason in RULES:
 case("RULE",name+" decision",lambda thesis=thesis,states=states,changes=changes,market=market,want=want:require(decide(thesis,[{"evaluation_status":x} for x in states],[{"assessment":x} for x in changes],market)[0]==want))
 case("RULE",name+" reason",lambda thesis=thesis,states=states,changes=changes,market=market,reason=reason:require(decide(thesis,[{"evaluation_status":x} for x in states],[{"assessment":x} for x in changes],market)[1]==reason))

case("COPY","session",lambda:require(CTX["record"]["target_session_date"]==CTX["snapshot"]["target_session_date"]));case("COPY","cutoff",lambda:require(CTX["record"]["proposal_cutoff"]==CTX["snapshot"]["revalidation_cutoff"]));
for key in ("recommendation_id","ticker","thesis_id","thesis_version","thesis_status","committed_capital"):case("COPY",key,lambda key=key:require(CTX["record"][key]==CTX["snapshot"][key]))
case("CONTEXT","market copied",lambda:require(CTX["record"]["market_context_id"]==CTX["snapshot"]["market_context_binding"]["record_id"]));case("CONTEXT","analogue null",lambda:require(CTX["record"]["historical_analogue_id"] is None));case("CONTEXT","missing market null",lambda:require(CTX["missing_market"]["market_context_id"] is None))
case("SUPPORT","snapshot",lambda:require(support_key(ib(CTX["snapshot"])) in {support_key(x) for x in CTX["record"]["support_bindings"]}));case("SUPPORT","evidence only IDs",lambda:require(CTX["evidence_record"]["supporting_evidence_ids"]==[CTX["evidence_binding"]["record_id"]]));case("SUPPORT","non evidence excluded",lambda:require(CTX["record"]["supporting_evidence_ids"]==[]))
case("DEPENDENCY","six",lambda:require(len(CTX["record"]["direct_dependencies"])==6));case("DEPENDENCY","types",lambda:require({x["record_type"] for x in CTX["record"]["direct_dependencies"]}=={INPUT_SCHEMA,"STAGE6_TRADE_THESIS_V2","STAGE6_PORTFOLIO_CONTEXT_V2","STAGE6_7B_POLICY","STAGE6_7B_PROPOSAL_CONTRACT",MANIFEST_VERSION}))
for forbidden in ("STAGE6_EVIDENCE_V2","STAGE6_EVENT_COMPANY_EFFECT_V1","STAGE6_MARKET_CONTEXT_V2","STAGE6_HISTORICAL_ANALOGUE_V2"):case("DEPENDENCY_EXCLUDE",forbidden,lambda forbidden=forbidden:require(forbidden not in {x["record_type"] for x in CTX["record"]["direct_dependencies"]}))
case("STORE","integrity",lambda:require(CTX["store"].integrity_check()["result"]=="PASS"));case("STORE","idempotent",lambda:require(CTX["store"].propose(**CTX["request"])["status"]=="IDEMPOTENT_SUCCESS"));case("STORE","conflict",lambda:expect(MorningProposalConflict,CTX["conflict"]));case("STORE","restart",lambda:require(CTX["restart"]()=="PASS"));case("STORE","trigger loss",lambda:expect(Exception,CTX["trigger_loss"]));case("STORE","one per snapshot",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM morning_revalidation_proposals").fetchone()[0]==1))
for table in TABLES:
 case("APPEND_ONLY",table+" update",lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"UPDATE {table} SET rowid=rowid")))
 case("APPEND_ONLY",table+" delete",lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"DELETE FROM {table}")))
for table,stmt in (
 ("morning_revalidation_proposals","UPDATE morning_revalidation_proposals SET canonical_json='{}'"),("morning_revalidation_invalidation_assessments","UPDATE morning_revalidation_invalidation_assessments SET canonical_json='{}'"),("morning_revalidation_change_assertions","UPDATE morning_revalidation_change_assertions SET canonical_json='{}'"),("morning_revalidation_support_bindings","UPDATE morning_revalidation_support_bindings SET record_hash='bad'"),("morning_revalidation_dependencies","UPDATE morning_revalidation_dependencies SET record_hash='bad'"),("morning_revalidation_proposal_policies","UPDATE morning_revalidation_proposal_policies SET policy_hash='bad'"),("morning_revalidation_proposal_contracts","UPDATE morning_revalidation_proposal_contracts SET contract_hash='bad'"),("morning_revalidation_code_manifests","UPDATE morning_revalidation_code_manifests SET decision_code_hash='bad'"),("morning_revalidation_audits","UPDATE morning_revalidation_audits SET canonical_json='{}'")):
 case("TAMPER",table,lambda table=table,stmt=stmt:expect(Exception,lambda:CTX["tamper"](table,stmt)))
case("TAMPER","proposal decision column",lambda:expect(Exception,lambda:CTX["tamper"]("morning_revalidation_proposals","UPDATE morning_revalidation_proposals SET decision='WAIT'")))
case("VALIDATION","missing assessment",lambda:expect(Stage6MorningProposalError,lambda:validate_inputs(CTX["thesis"],CTX["ia"][:-1],[],CTX["universe"])));case("VALIDATION","duplicate assessment",lambda:expect(Stage6MorningProposalError,lambda:validate_inputs(CTX["thesis"],[CTX["ia"][0],CTX["ia"][0]],[],CTX["universe"])));case("VALIDATION","changed text",lambda:expect(Stage6MorningProposalError,lambda:validate_inputs(CTX["thesis"],[{**CTX["ia"][0],"condition_text":"changed"},CTX["ia"][1]],[],CTX["universe"])));case("VALIDATION","extra index",lambda:expect(Stage6MorningProposalError,lambda:validate_inputs(CTX["thesis"],[*CTX["ia"],{**CTX["ia"][0],"condition_index":2}],[],CTX["universe"])))
case("VALIDATION","trigger support",lambda:expect(Stage6MorningProposalError,lambda:validate_inputs(CTX["thesis"],assessments(CTX["thesis"],"TRIGGERED",ib(CTX["snapshot"]))[:-1]+[{**CTX["ia"][1],"evaluation_status":"TRIGGERED","supporting_bindings":[]}],[],CTX["universe"])));case("VALIDATION","not-triggered support",lambda:expect(Stage6MorningProposalError,lambda:validate_inputs(CTX["thesis"],[{**x,"supporting_bindings":[]} for x in CTX["ia"]],[],CTX["universe"])));case("VALIDATION","not-evaluated empty",lambda:require(validate_inputs(CTX["thesis"],assessments(CTX["thesis"],"NOT_EVALUATED"),[],CTX["universe"])[0][0]["evaluation_status"]=="NOT_EVALUATED"))
case("VALIDATION","external support",lambda:expect(Stage6MorningProposalError,lambda:validate_inputs(CTX["thesis"],CTX["ia"],[assertion("NON_MATERIAL",{"record_type":"OTHER","record_id":"X","record_hash":"a"*64})],CTX["universe"])));case("VALIDATION","altered hash",lambda:expect(Stage6MorningProposalError,lambda:validate_inputs(CTX["thesis"],CTX["ia"],[assertion("NON_MATERIAL",{**ib(CTX["snapshot"]),"record_hash":"a"*64})],CTX["universe"])));case("VALIDATION","duplicate support",lambda:expect(Stage6MorningProposalError,lambda:validate_inputs(CTX["thesis"],CTX["ia"],[{"assessment":"NON_MATERIAL","reason_code":"NEW_EVIDENCE","supporting_bindings":[ib(CTX["snapshot"]),ib(CTX["snapshot"])]}],CTX["universe"])))
case("CANONICAL","assessment order",lambda:require(canonical_assessments(list(reversed(CTX["ia"])))==CTX["ia"]));case("CANONICAL","assertion order",lambda:require(canonical_assertions(list(reversed(CTX["unordered_assertions"])))==canonical_assertions(CTX["unordered_assertions"])));case("CANONICAL","caller order ID",lambda:require(CTX["order_a"]["proposal_id"]==CTX["order_b"]["proposal_id"]));case("CANONICAL","caller order hash",lambda:require(CTX["order_a"]["record_hash"]==CTX["order_b"]["record_hash"]))
case("MANIFEST","four files",lambda:require(tuple(x["relative_path"] for x in CTX["manifest"]["files"])==tuple(sorted(FILES))));case("MANIFEST","blob replay",lambda:require(all(git_blob(ROOT/"stage6_morning_revalidation_proposal"/x["relative_path"])==x["git_blob_sha1"] for x in CTX["manifest"]["files"])));case("MANIFEST","verify",lambda:require(verify_code_manifest(CTX["manifest"])==CTX["manifest"]));case("MANIFEST","deterministic",lambda:require(build_code_manifest()==CTX["manifest"]))
for token in ("confidence","PRICE_OUTSIDE_ENTRY_RANGE","NO_NEW_POSITION","datetime.now","datetime.utcnow","MAX(","ORDER BY version DESC","expected_return","gap threshold","majority","weighting") :case("BOUNDARY",token,lambda token=token:require(token.lower() not in CTX["semantic_lower"]))
for token in ("requests","urllib","httpx","aiohttp","socket","selenium","yfinance","openai","transformers","torch","tensorflow","sklearn","pandas_datareader"):case("ZERO",token,lambda token=token:require(token not in CTX["imports"]))
for i in range(150):case("DETERMINISTIC_REPLAY",str(i),lambda:require(build_proposal(snapshot=CTX["snapshot"],thesis=CTX["thesis"],portfolio=CTX["portfolio"],invalidation_assessments=CTX["ia"],change_assertions=CTX["assertions"],policy_hash=CTX["store"].policy_hash,contract_hash=CTX["store"].contract_hash,manifest=CTX["manifest"])==CTX["record"]))
case("CLOSURE","status",lambda:require("STAGE6_7_STATUS = COMPLETE_SHADOW_ONLY" in (ROOT/"Stage6_7_Closure_Report.md").read_text(encoding="utf-8")));case("CLOSURE","next",lambda:require("NEXT_STAGE = STAGE6_8_PROSPECTIVE_SHADOW_VALIDATION" in (ROOT/"Stage6_7_Closure_Report.md").read_text(encoding="utf-8")));case("CLOSURE","8 deferred",lambda:require("has not started" in (ROOT/"Stage6_7_Closure_Report.md").read_text(encoding="utf-8")))

def market_record(ticker):
 p={"schema_version":"STAGE6_MARKET_CONTEXT_V2","market_context_id":"S6MCTX_TEST","ticker":ticker,"as_of_timestamp":"2026-09-29T13:55:00Z","data_cutoff_timestamp":"2026-09-29T13:50:00Z","stock_returns":{},"sector_returns":{},"nifty_returns":{},"volume_anomaly":{},"volatility":{},"gap":{},"technical_context":{},"relative_strength":{},"commodity_context":[],"currency_context":[],"rate_context":[],"market_regime":{},"source_evidence_ids":["S6EV_R3"],"pit_verified":True};require(set(p)==PAYLOAD_FIELDS)
 r={"market_context_record_id":p["market_context_id"],"contract_payload":p,**MARKET_SAFETY,"record_hash":""};r["record_hash"]=canonical_hash(without(r,"record_hash"));return r
def setup(temp):
 s7a.setup(temp);base=s7a.CTX;theses=base["theses"];market=market_record(theses["v3"]["ticker"]);mstore=s7a.FakeStore("market_context_records","market_context_record_id",[{"market_context_record_id":market["market_context_record_id"],"value":market}]);CTX["market_store"]=mstore
 morning=MorningInputStore(Path(temp.name)/"morning7b.sqlite3",base["portfolio_store"],base["thesis_store"],base["version_store"],base["recursive_store"],evidence_store=base["evidence_store"],company_effect_store=base["effect_store"],market_context_store=mstore);CTX["morning_store"]=morning
 snapshots={}
 for name in ("v1","v2","v3"):snapshots[name]=morning.freeze(**{**base[name+"_req"],"market_context_id":market["market_context_record_id"]})["morning_input_snapshot"]
 snapshot=snapshots["v3"];thesis=theses["v3"];portfolio=base["portfolio_store"].connection.execute("SELECT canonical_json FROM portfolio_context_records").fetchone();portfolio=json.loads(portfolio[0])["portfolio_context"];support=ib(snapshot);ia=assessments(thesis,"NOT_TRIGGERED",support);assertions=[assertion("SUPPORTIVE_MATERIAL",support)]
 store=MorningRevalidationProposalStore(Path(temp.name)/"proposal.sqlite3",morning);request={"morning_snapshot_id":snapshot["morning_snapshot_id"],"invalidation_assessments":ia,"morning_change_assertions":assertions};record=store.propose(**request)["proposal"]
 universe={(INPUT_SCHEMA,snapshot["morning_snapshot_id"],snapshot["record_hash"]),*(support_key(x) for x in snapshot["direct_input_bindings"])};manifest=build_code_manifest();CTX.update({"store":store,"snapshot":snapshot,"thesis":thesis,"portfolio":portfolio,"ia":ia,"assertions":assertions,"record":record,"request":request,"universe":universe,"manifest":manifest,"code_hash":manifest["decision_code_hash"]})
 def run_scenario(name,snap,th,iax,ax,input_store=morning):
  s=MorningRevalidationProposalStore(Path(temp.name)/(name+".sqlite3"),input_store)
  try:return s.propose(morning_snapshot_id=snap["morning_snapshot_id"],invalidation_assessments=iax,morning_change_assertions=ax)["proposal"]
  finally:s.close()
 CTX["missing_market"]=run_scenario("missing",base["v1"]["morning_input_snapshot"],theses["v1"],assessments(theses["v1"],"NOT_TRIGGERED",ib(base["v1"]["morning_input_snapshot"])),[],base["store"])
 eb=snapshot["evidence_bindings"][0];CTX["evidence_binding"]=eb;CTX["evidence_record"]=run_scenario("evidence",snapshots["v2"],theses["v2"],assessments(theses["v2"],"NOT_TRIGGERED",ib(snapshots["v2"])),[assertion("NON_MATERIAL",eb,"NEW_EVIDENCE")])
 unordered=[assertion("ADVERSE_MATERIAL",support,"COMPANY_EFFECT"),assertion("SUPPORTIVE_MATERIAL",support,"NEW_EVIDENCE")];CTX["unordered_assertions"]=unordered;CTX["order_a"]=build_proposal(snapshot=snapshot,thesis=thesis,portfolio=portfolio,invalidation_assessments=ia,change_assertions=unordered,policy_hash=store.policy_hash,contract_hash=store.contract_hash,manifest=manifest);CTX["order_b"]=build_proposal(snapshot=snapshot,thesis=thesis,portfolio=portfolio,invalidation_assessments=list(reversed(ia)),change_assertions=list(reversed(unordered)),policy_hash=store.policy_hash,contract_hash=store.contract_hash,manifest=manifest)
 CTX["conflict"]=lambda:store.propose(morning_snapshot_id=snapshot["morning_snapshot_id"],invalidation_assessments=ia,morning_change_assertions=[])
 def restart():
  s=MorningRevalidationProposalStore(store.database,morning)
  try:return s.integrity_check()["result"]
  finally:s.close()
 CTX["restart"]=restart
 def tamper(table,stmt):
  path=Path(temp.name)/("tamper_"+table+".sqlite3");path.write_bytes(store.connection.serialize());s=MorningRevalidationProposalStore(path,morning)
  try:s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(stmt);s.connection.commit();return s.integrity_check()
  finally:s.close()
 CTX["tamper"]=tamper;CTX["trigger_loss"]=lambda:tamper("morning_revalidation_proposals","UPDATE morning_revalidation_proposals SET record_hash=record_hash")
 texts=[p.read_text(encoding="utf-8") for p in (ROOT/"stage6_morning_revalidation_proposal").glob("*.py")];CTX["semantic_lower"]="\n".join(texts).lower();CTX["imports"]={((n.module or "").split(".")[0] if isinstance(n,ast.ImportFrom) else alias.name.split(".")[0]) for text in texts for n in ast.walk(ast.parse(text)) if isinstance(n,(ast.Import,ast.ImportFrom)) for alias in ([n.names[0]] if isinstance(n,ast.Import) else [None])}
def main():
 temp=tempfile.TemporaryDirectory();failed=0;rows=[]
 try:
  setup(temp)
  for i,(group,name,fn) in enumerate(CASES,1):
   try:fn();result,detail="PASS",""
   except Exception as exc:result,detail="FAIL",f"{type(exc).__name__}: {exc}";failed+=1
   rows.append({"test_id":i,"test_group":group,"test_name":name,"result":result,"detail":detail})
  OUT.parent.mkdir(parents=True,exist_ok=True)
  with OUT.open("w",newline="",encoding="utf-8") as handle:writer=csv.DictWriter(handle,fieldnames=("test_id","test_group","test_name","result","detail"),lineterminator="\n");writer.writeheader();writer.writerows(rows)
  print(f"Stage 6.7B: {len(rows)-failed}/{len(rows)} PASS"+(f", {failed} FAIL" if failed else ""));[print((x["test_id"],x["test_group"],x["test_name"],x["detail"])) for x in rows if x["result"]=="FAIL"];return 1 if failed else 0
 finally:
  for key in ("store","morning_store","market_store"):
   try:CTX[key].close()
   except Exception:pass
  for key in ("store","effect_store","portfolio_store","recursive_store","version_store","assessment_store","review_store","evidence_store","thesis_store","seed_store"):
   try:s7a.CTX[key].close()
   except Exception:pass
  temp.cleanup()
if __name__=="__main__":raise SystemExit(main())
