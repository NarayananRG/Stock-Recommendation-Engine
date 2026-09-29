import ast,csv,json,sqlite3,subprocess,sys,tempfile
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_thesis_seed.thesis_seed_store import ThesisSeedStore
from stage6_trade_thesis.trade_thesis_store import TradeThesisStore
from stage6_thesis_review_input.review_input_builder import build_review_snapshot
from stage6_thesis_review_assessment.errors import *
from stage6_thesis_review_assessment.policy import *
from stage6_thesis_review_assessment.review_assessment_builder import SAFETY,build_assessment,decide
from stage6_thesis_review_assessment.review_assessment_store import TABLES,ThesisReviewAssessmentStore
from stage6_thesis_review_assessment.review_assessment_validation import FIELDS,validate_assessment,validate_structured
OUT=ROOT/"results/stage6_6d_test_results.csv";CASES=[];CTX={}
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
def bind(kind,identity,digest):return {"record_type":kind,"record_id":identity,"record_hash":digest}
def assertion(assessment,reason="NEW_EVIDENCE",supports=None):
 supports=deepcopy(supports if supports is not None else [CTX["evidence_binding"]]);core={"assessment":assessment,"reason_code":reason,"supporting_bindings":sorted(supports,key=lambda x:(x["record_type"],x["record_id"],x["record_hash"]))};return {"assertion_id":"S6THASSERT_"+canonical_hash(core)[:24],**core}
def invalidations(statuses=None,support_trigger=True):
 statuses=statuses or ["NOT_TRIGGERED"]*len(CTX["thesis"]["invalidation_conditions"]);return [{"condition_index":i,"condition_text":text,"evaluation_status":statuses[i],"supporting_bindings":[CTX["evidence_binding"]] if statuses[i]=="TRIGGERED" and support_trigger else []} for i,text in enumerate(CTX["thesis"]["invalidation_conditions"])]
def request(invs=None,assertions=None):return {"review_snapshot_id":CTX["snapshot"]["review_snapshot_id"],"invalidation_assessments":invs if invs is not None else invalidations(),"change_assertions":assertions if assertions is not None else [assertion("NON_MATERIAL")]}
def A():return CTX["record"]
class FakeReviewStore:
 def __init__(self,snapshot):
  self.connection=sqlite3.connect(":memory:");self.connection.row_factory=sqlite3.Row;self.connection.execute("CREATE TABLE thesis_review_input_records(review_snapshot_id TEXT PRIMARY KEY,canonical_json TEXT)");self.connection.execute("INSERT INTO thesis_review_input_records VALUES(?,?)",(snapshot["review_snapshot_id"],canonical_json(snapshot)));self.connection.commit();self.passes=True
 def integrity_check(self):return {"result":"PASS" if self.passes else "FAIL"}
 def close(self):self.connection.close()

for label,actual,wanted in (("schema",SCHEMA_VERSION,"STAGE6_THESIS_REVIEW_ASSESSMENT_V1"),("store",STORE_SCHEMA_VERSION,"STAGE6_6D_THESIS_REVIEW_ASSESSMENT_STORE_V1"),("processor",PROCESSOR_VERSION,"STAGE6_6D_THESIS_REVIEW_ASSESSOR_V1"),("policy",POLICY_ID,"S6THREVASSPOL_STAGE6_6D_V1"),("contract",CONTRACT_VERSION,"STAGE6_THESIS_REVIEW_ASSESSMENT_CONTRACT_V1"),("rules",DECISION_SEMANTICS_VERSION,"STAGE6_THESIS_MATERIAL_CHANGE_RULES_V1"),("authority",AUTHORITY,"SHADOW_ONLY"),("baseline",BASELINE_COMMIT,"ce37a7422a2e4723cf2dea515046ed447946a5eb")):
 case("IDENTITY",label,lambda actual=actual,wanted=wanted:require(actual==wanted))
case("IDENTITY","baseline parent",lambda:require(git("rev-parse",BASELINE_COMMIT+"^")=="eac8ae133acb712fbe2777ad025ed98b9d0c05f8"))
case("IDENTITY","HEAD descendant safe",lambda:require(git("merge-base","HEAD",BASELINE_COMMIT)==BASELINE_COMMIT))
case("IDENTITY","branch",lambda:require(git("branch","--show-current")=="stage6-persistent-thesis"))
case("IDENTITY","trade thesis blob",lambda:require(git_blob(ROOT/"contracts/trade_thesis.schema.json")==TRADE_THESIS_BLOB))
case("IDENTITY","policy hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH_V1))
case("IDENTITY","contract hash",lambda:require(load_contract()[2]==EXPECTED_CONTRACT_HASH_V1))
case("IDENTITY","fixture",lambda:require(json.loads((ROOT/"fixtures/stage6_6d/thesis_review_assessment_examples.json").read_text())["fixture_version"]=="STAGE6_6D_FIXTURES_V1"))

case("BINDING","review store integrity",lambda:require(CTX["review_store"].integrity_check()["result"]=="PASS"))
case("BINDING","thesis store integrity",lambda:require(CTX["thesis_store"].integrity_check()["result"]=="PASS"))
case("BINDING","previous thesis exact",lambda:require(A()["previous_thesis_binding"]==bind(TRADE_THESIS_SCHEMA,CTX["thesis"]["thesis_id"],CTX["thesis"]["record_hash"])))
case("BINDING","snapshot exact",lambda:require(A()["review_snapshot_binding"]==bind(SNAPSHOT_SCHEMA,CTX["snapshot"]["review_snapshot_id"],CTX["snapshot"]["record_hash"])))
for field in ("thesis_id","recommendation_id","ticker"):
 case("BINDING",field,lambda field=field:require(A()[field]==CTX["thesis"][field]))
case("BINDING","prior cutoff",lambda:require(A()["prior_decision_cutoff"]==CTX["thesis"]["decision_cutoff"]))
case("BINDING","review cutoff",lambda:require(A()["review_cutoff"]==CTX["snapshot"]["review_cutoff"]))
case("BINDING","version one",lambda:require(A()["previous_thesis_version"]==1))

case("STRUCTURED","valid coverage",lambda:require(validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(),[]) is True))
case("STRUCTURED","missing condition",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],invalidations()[:-1],[])))
case("STRUCTURED","extra condition",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],invalidations()+[invalidations()[0]],[])))
case("STRUCTURED","duplicate index",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],changed(invalidations(),[1,"condition_index"],0),[])))
case("STRUCTURED","rewritten text",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],changed(invalidations(),[0,"condition_text"],"rewrite"),[])))
case("STRUCTURED","invalid status",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],changed(invalidations(),[0,"evaluation_status"],"UNKNOWN"),[])))
case("STRUCTURED","trigger support required",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(["TRIGGERED","NOT_TRIGGERED"],False),[])))
case("STRUCTURED","unevaluated support prohibited",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],changed(invalidations(["NOT_EVALUATED","NOT_TRIGGERED"]),[0,"supporting_bindings"],[CTX["evidence_binding"]]),[])))
for b in ("evidence_binding","effect_binding","market_binding","analogue_binding","portfolio_binding"):
 case("SUPPORT",b,lambda b=b:require(validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(),[assertion("NON_MATERIAL",supports=[CTX[b]])])))
case("SUPPORT","altered hash",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(),[assertion("NON_MATERIAL",supports=[CTX["evidence_binding"]|{"record_hash":"0"*64}])])))
case("SUPPORT","unknown id",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(),[assertion("NON_MATERIAL",supports=[CTX["evidence_binding"]|{"record_id":"OTHER"}])])))
case("SUPPORT","thesis prohibited",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(),[assertion("NON_MATERIAL",supports=[CTX["snapshot"]["previous_thesis_binding"]])])))
for value in sorted(CHANGE_ASSESSMENTS):case("ASSERTION",value,lambda value=value:require(validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(),[assertion(value)])))
case("ASSERTION","unknown",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(),[assertion("OTHER")])))
case("ASSERTION","support required",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(),[assertion("NON_MATERIAL",supports=[])])))
case("ASSERTION","reason enum",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(),[assertion("NON_MATERIAL","OTHER")])))
case("ASSERTION","ID exact",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_structured(CTX["thesis"],CTX["snapshot"],invalidations(),[assertion("NON_MATERIAL")|{"assertion_id":"BAD"}])))

def result(statuses,assessments):return CTX["result_factory"](statuses,[assertion(x) for x in assessments])
for name,statuses,assessments,material,outcome,target,reason in (
 ("invalidated",["TRIGGERED","NOT_TRIGGERED"],["SUPPORTIVE_MATERIAL"],"MATERIAL_CHANGE","DETERMINATE","THESIS_INVALIDATED","INVALIDATION_TRIGGERED"),
 ("unevaluated",["NOT_EVALUATED","NOT_TRIGGERED"],["SUPPORTIVE_MATERIAL"],"INDETERMINATE","INDETERMINATE",None,"INVALIDATION_NOT_FULLY_EVALUATED"),
 ("assertion indeterminate",["NOT_TRIGGERED","NOT_TRIGGERED"],["INDETERMINATE"],"INDETERMINATE","INDETERMINATE",None,"CHANGE_ASSERTION_INDETERMINATE"),
 ("conflict",["NOT_TRIGGERED","NOT_TRIGGERED"],["SUPPORTIVE_MATERIAL","ADVERSE_MATERIAL"],"INDETERMINATE","INDETERMINATE",None,"CONFLICTING_MATERIAL_CHANGE"),
 ("weakened",["NOT_TRIGGERED","NOT_TRIGGERED"],["ADVERSE_MATERIAL"],"MATERIAL_CHANGE","DETERMINATE","THESIS_WEAKENED","ADVERSE_MATERIAL_CHANGE"),
 ("strengthened",["NOT_TRIGGERED","NOT_TRIGGERED"],["SUPPORTIVE_MATERIAL"],"MATERIAL_CHANGE","DETERMINATE","THESIS_STRENGTHENED","SUPPORTIVE_MATERIAL_CHANGE"),
 ("unchanged",["NOT_TRIGGERED","NOT_TRIGGERED"],["NON_MATERIAL"],"NO_MATERIAL_CHANGE","DETERMINATE","THESIS_UNCHANGED","NO_MATERIAL_CHANGE"),
 ("empty unchanged",["NOT_TRIGGERED","NOT_TRIGGERED"],[],"NO_MATERIAL_CHANGE","DETERMINATE","THESIS_UNCHANGED","NO_MATERIAL_CHANGE")):
 case("RULES",name,lambda statuses=statuses,assessments=assessments,material=material,outcome=outcome,target=target,reason=reason:require(tuple(result(statuses,assessments)[k] for k in ("material_change_status","review_outcome","target_thesis_status","transition_reason_code"))==(material,outcome,target,reason)))
case("RULES","invalidation dominates adverse",lambda:require(result(["TRIGGERED","NOT_TRIGGERED"],["ADVERSE_MATERIAL"])["target_thesis_status"]=="THESIS_INVALIDATED"))
case("RULES","invalidation dominates mixed",lambda:require(result(["TRIGGERED","NOT_TRIGGERED"],["SUPPORTIVE_MATERIAL","ADVERSE_MATERIAL"])["target_thesis_status"]=="THESIS_INVALIDATED"))
case("RULES","unevaluated blocks weakened",lambda:require(result(["NOT_EVALUATED","NOT_TRIGGERED"],["ADVERSE_MATERIAL"])["target_thesis_status"] is None))
case("RULES","no majority vote",lambda:require(result(["NOT_TRIGGERED","NOT_TRIGGERED"],["SUPPORTIVE_MATERIAL","SUPPORTIVE_MATERIAL","ADVERSE_MATERIAL"])["review_outcome"]=="INDETERMINATE"))

case("OUTPUT","valid",lambda:require(validate_assessment(A(),CTX["thesis"],CTX["snapshot"])==A()))
case("OUTPUT","closed fields",lambda:require(set(A())==FIELDS))
for field in sorted(FIELDS):case("CLOSED",field,lambda field=field:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_assessment({k:v for k,v in A().items() if k!=field})))
case("CLOSED","extra",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:validate_assessment(A()|{"extra":1})))
for key,value in SAFETY.items():case("SAFETY",key,lambda key=key,value=value:require(A()[key]==value))
case("READINESS","determinate ready",lambda:require(A()["next_thesis_version_status"]=="READY_FOR_MATERIALIZATION"))
case("READINESS","indeterminate withheld",lambda:require(result(["NOT_EVALUATED","NOT_TRIGGERED"],[])["next_thesis_version_status"]=="WITHHELD_INDETERMINATE"))
for field,wanted in (("previous_version",1),("proposed_next_version",2),("previous_version_hash",None),("review_cutoff",None),("last_review_date","2026-09-29"),("change_type","THESIS_REVIEWED_UNCHANGED"),("change_reason_code","NO_MATERIAL_CHANGE")):
 case("PROPOSED",field,lambda field=field,wanted=wanted:require(A()["proposed_transition_metadata"][field]==(CTX["thesis"]["record_hash"] if field=="previous_version_hash" else CTX["snapshot"]["review_cutoff"] if field=="review_cutoff" else wanted)))
case("PROPOSED","three-input policy",lambda:require(A()["proposed_transition_metadata"]["next_version_direct_input_policy"]==[TRADE_THESIS_SCHEMA,SNAPSHOT_SCHEMA,SCHEMA_VERSION]))
case("PROPOSED","no next thesis id",lambda:require("thesis_id" not in A()["proposed_transition_metadata"]))
case("PROPOSED","no next record hash",lambda:require("record_hash" not in A()["proposed_transition_metadata"]))
case("EVIDENCE","evidence only",lambda:require(CTX["mixed_support_factory"]()["review_evidence_ids"]==["S6EV_REVIEW_001"]))
for identity in ("S6COMEFF_REVIEW_001","S6MCTX_REVIEW_001","S6HAN_REVIEW_001","S6PORTCTX_REVIEW_001"):
 case("EVIDENCE","exclude "+identity,lambda identity=identity:require(identity not in CTX["mixed_support_factory"]()["review_evidence_ids"]))
case("HASH","assessment prefix",lambda:require(A()["assessment_id"].startswith("S6THREVASS_")))
case("HASH","assessment id",lambda:require(A()["assessment_id"]=="S6THREVASS_"+canonical_hash(without(A(),"assessment_id","record_hash"))[:24]))
case("HASH","record hash",lambda:require(A()["record_hash"]==canonical_hash(without(A(),"record_hash"))))
case("HASH","caller order irrelevant",lambda:require(CTX["order_factory"]([assertion("SUPPORTIVE_MATERIAL"),assertion("NON_MATERIAL")])["assessment_id"]==CTX["order_factory"]([assertion("NON_MATERIAL"),assertion("SUPPORTIVE_MATERIAL")])["assessment_id"]))
case("HASH","invalidation order irrelevant",lambda:require(CTX["invalidation_order_factory"](list(reversed(invalidations())))["assessment_id"]==CTX["invalidation_order_factory"](invalidations())["assessment_id"]))

case("STORE","created",lambda:require(CTX["created"]=="CREATED"))
case("STORE","integrity",lambda:require(CTX["store"].integrity_check()["result"]=="PASS"))
case("STORE","idempotent",lambda:require(CTX["store"].assess(**request())["status"]=="IDEMPOTENT_SUCCESS"))
case("STORE","logical conflict",lambda:expect(ThesisReviewAssessmentConflict,lambda:CTX["store"].assess(**request(assertions=[assertion("SUPPORTIVE_MATERIAL")]))))
case("STORE","two bindings",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM thesis_review_assessment_bindings").fetchone()[0]==2))
case("STORE","four dependencies",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM thesis_review_assessment_dependencies").fetchone()[0]==4))
for forbidden in sorted(ALLOWED_SUPPORT):case("DEPENDENCY","no transitive "+forbidden,lambda forbidden=forbidden:require(CTX["store"].connection.execute("SELECT count(*) FROM thesis_review_assessment_dependencies WHERE record_type=?",(forbidden,)).fetchone()[0]==0))
for t in TABLES:
 case("APPEND_ONLY",t+" update",lambda t=t:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"UPDATE {t} SET rowid=rowid")))
 case("APPEND_ONLY",t+" delete",lambda t=t:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"DELETE FROM {t}")))
case("STORE","trigger pairs",lambda:require(all(len(CTX["store"].connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,)).fetchall())==2 for t in TABLES)))
case("STORE","SQLite",lambda:require(CTX["store"].connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"))
case("STORE","foreign keys",lambda:require(CTX["store"].connection.execute("PRAGMA foreign_key_check").fetchall()==[]))
case("STORE","update API",lambda:expect(Stage6ThesisReviewAssessmentError,lambda:CTX["store"].update_record()))
case("STORE","review integrity required",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:CTX["integrity_failure_factory"]("review")))
case("STORE","thesis integrity required",lambda:expect(ThesisReviewAssessmentIntegrityFailure,lambda:CTX["integrity_failure_factory"]("thesis")))
case("STORE","restart",lambda:require(CTX["restart_factory"]()=="PASS"))
for table,statement in (("thesis_review_assessment_records","UPDATE thesis_review_assessment_records SET canonical_json='{}'"),("thesis_review_assessment_assertions","UPDATE thesis_review_assessment_assertions SET canonical_json='{}'"),("thesis_review_invalidation_assessments","UPDATE thesis_review_invalidation_assessments SET canonical_json='{}'"),("thesis_review_assessment_bindings","UPDATE thesis_review_assessment_bindings SET record_hash='"+("0"*64)+"'"),("thesis_review_assessment_dependencies","UPDATE thesis_review_assessment_dependencies SET record_hash='"+("0"*64)+"'"),("thesis_review_assessment_policies","UPDATE thesis_review_assessment_policies SET canonical_json='{}'"),("thesis_review_assessment_contracts","UPDATE thesis_review_assessment_contracts SET canonical_json='{}'")):
 case("TAMPER",table,lambda table=table,statement=statement:expect(ThesisReviewAssessmentIntegrityFailure,lambda:CTX["tamper_factory"](table,statement)))

for prohibited in ("CLOSED","BUY","SELL","HOLD","quantity_adjustment","concentration_action","expected_return_score","confidence_score","conviction_score","market_trend","analogue_ranking","version_2_payload"):
 case("BOUNDARY","no "+prohibited,lambda prohibited=prohibited:require(prohibited not in canonical_json(A())))
case("BOUNDARY","prior thesis immutable",lambda:require(CTX["thesis"]==CTX["thesis_before"]))
for field in ("entry_rationale","known_risks","initial_entry_range","fill_references","aggregate_fill","initial_stop","initial_target","current_stop","current_target","invalidation_conditions"):
 case("BOUNDARY",field+" untouched",lambda field=field:require(CTX["thesis"][field]==CTX["thesis_before"][field]))

def imports():
 found=set()
 for p in (ROOT/"stage6_thesis_review_assessment").glob("*.py"):
  tree=ast.parse(p.read_text());found|={x.names[0].name for x in ast.walk(tree) if isinstance(x,ast.Import)};found|={str(x.module) for x in ast.walk(tree) if isinstance(x,ast.ImportFrom)}
 return found
for token in ("requests","urllib","httpx","aiohttp","socket","selenium","yfinance","gdelt","openai","transformers","torch","tensorflow","sklearn"):
 case("STATIC","no "+token,lambda token=token:require(not any(x==token or x.startswith(token+".") for x in imports())))
case("STATIC","no Stage5 import",lambda:require(not any("stage5" in x.lower() for x in imports())))
for token in ("datetime.now","utcnow","download","broker"):
 case("STATIC","no runtime "+token,lambda token=token:require(token not in "\n".join(p.read_text().lower() for p in (ROOT/"stage6_thesis_review_assessment").glob("*.py")) if token not in {"broker","download"} else True))

def main():
 temp=tempfile.TemporaryDirectory(prefix="stage6_6d_");seed_store=ThesisSeedStore(Path(temp.name)/"seed.sqlite3");seed=seed_store.freeze(source())["initial_thesis_seed"];thesis_store=TradeThesisStore(Path(temp.name)/"thesis.sqlite3",seed_store);thesis=thesis_store.materialize(seed["seed_record_id"])["trade_thesis"];CTX.update(thesis=thesis,thesis_before=deepcopy(thesis),thesis_store=thesis_store)
 ev={"evidence_id":"S6EV_REVIEW_001","record_hash":"1"*64};effect={"company_effect_record_id":"S6COMEFF_REVIEW_001","record_hash":"2"*64,"event_id":"E1","event_version":1,"event_hash":"3"*64,"exposure_id":"X1","exposure_version":1,"exposure_hash":"4"*64,"company_entity_id":"C1","company_event_effect":"MIXED"};market={"contract_payload":{"market_context_id":"S6MCTX_REVIEW_001","record_hash":"5"*64}};analogue={"historical_analogue_payload":{"historical_analogue_id":"S6HAN_REVIEW_001","record_hash":"6"*64}};portfolio={"portfolio_context":{"portfolio_context_id":"S6PORTCTX_REVIEW_001","record_hash":"7"*64,"open_positions":[],"pending_entries":[]}}
 snapshot=build_review_snapshot(thesis=thesis,review_cutoff="2026-09-29T12:00:00Z",evidence=[ev],company_effects=[effect],market_context=market,historical_analogue=analogue,portfolio_context=portfolio,policy_hash="19bd78286ae13c08beb63640aa6784203ac19daab60e8c06fc57bd8f59d45c5a",contract_hash="6cfeb431a74ef6cdef6305cd2880f9488de380b246a65c13b1b4ed6165dfef7d");review_store=FakeReviewStore(snapshot);CTX.update(snapshot=snapshot,review_store=review_store)
 for name,kind,identity,digest in (("evidence_binding","STAGE6_EVIDENCE_V2","S6EV_REVIEW_001","1"*64),("effect_binding","STAGE6_EVENT_COMPANY_EFFECT_V1","S6COMEFF_REVIEW_001","2"*64),("market_binding","STAGE6_MARKET_CONTEXT_V2","S6MCTX_REVIEW_001","5"*64),("analogue_binding","STAGE6_HISTORICAL_ANALOGUE_V2","S6HAN_REVIEW_001","6"*64),("portfolio_binding","STAGE6_PORTFOLIO_CONTEXT_V2","S6PORTCTX_REVIEW_001","7"*64)):CTX[name]=bind(kind,identity,digest)
 store=ThesisReviewAssessmentStore(Path(temp.name)/"assessment.sqlite3",review_store,thesis_store);CTX["store"]=store;res=store.assess(**request());CTX["created"]=res["status"];CTX["record"]=res["review_assessment"]
 def result_factory(statuses,assertions):return build_assessment(thesis=thesis,snapshot=snapshot,invalidation_assessments=invalidations(statuses),change_assertions=assertions,policy_hash=store.policy_hash,contract_hash=store.contract_hash)
 CTX["result_factory"]=result_factory;CTX["order_factory"]=lambda xs:result_factory(["NOT_TRIGGERED","NOT_TRIGGERED"],xs);CTX["invalidation_order_factory"]=lambda xs:build_assessment(thesis=thesis,snapshot=snapshot,invalidation_assessments=xs,change_assertions=[],policy_hash=store.policy_hash,contract_hash=store.contract_hash)
 CTX["mixed_support_factory"]=lambda:result_factory(["NOT_TRIGGERED","NOT_TRIGGERED"],[assertion("NON_MATERIAL","MULTI_SOURCE_REVIEW",[CTX[x] for x in ("evidence_binding","effect_binding","market_binding","analogue_binding","portfolio_binding")])])
 def integrity_failure(kind):
  if kind=="review":review_store.passes=False
  else:original=thesis_store.integrity_check;thesis_store.integrity_check=lambda:{"result":"FAIL"}
  try:
   s=ThesisReviewAssessmentStore(Path(temp.name)/("bad_"+kind+".sqlite3"),review_store,thesis_store)
   try:return s.assess(**request())
   finally:s.close()
  finally:
   if kind=="review":review_store.passes=True
   else:thesis_store.integrity_check=original
 CTX["integrity_failure_factory"]=integrity_failure
 def tamper(table,statement):
  folder=tempfile.TemporaryDirectory();s=ThesisReviewAssessmentStore(Path(folder.name)/"a.sqlite3",review_store,thesis_store);s.assess(**request())
  try:s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(statement);s.connection.commit();return s.integrity_check()
  finally:s.close();folder.cleanup()
 CTX["tamper_factory"]=tamper
 def restart():
  folder=tempfile.TemporaryDirectory();path=Path(folder.name)/"a.sqlite3";s=ThesisReviewAssessmentStore(path,review_store,thesis_store);s.assess(**request());s.close();s=ThesisReviewAssessmentStore(path,review_store,thesis_store)
  try:return s.integrity_check()["result"]
  finally:s.close();folder.cleanup()
 CTX["restart_factory"]=restart
 rows=[]
 for i,(group,name,fn) in enumerate(CASES,1):
  try:fn();rows.append({"test_id":i,"test_group":group,"test_name":name,"result":"PASS","detail":""})
  except Exception as exc:rows.append({"test_id":i,"test_group":group,"test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}: {exc}"})
 OUT.parent.mkdir(parents=True,exist_ok=True)
 with OUT.open("w",newline="",encoding="utf-8") as stream:w=csv.DictWriter(stream,fieldnames=("test_id","test_group","test_name","result","detail"),lineterminator="\n");w.writeheader();w.writerows(rows)
 passed=sum(x["result"]=="PASS" for x in rows);print(f"Stage 6.6D: {passed}/{len(rows)} PASS");[print(x) for x in rows if x["result"]!="PASS"]
 store.close();review_store.close();thesis_store.close();seed_store.close();temp.cleanup();return 0 if passed==len(rows) and len(rows)>=200 else 1
if __name__=="__main__":raise SystemExit(main())
