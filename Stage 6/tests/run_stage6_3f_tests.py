"""Stage 6.3F evidence-backed economic path direction semantics tests."""
from __future__ import annotations
import ast,csv,importlib.util,json,socket,sqlite3,subprocess,sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location("s63e",Path(__file__).with_name("run_stage6_3e_tests.py"));e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
from stage6_direction_semantics import *
from stage6_ingestion.canonical import canonical_hash
OUT=ROOT/"results"/"stage6_3f_test_results.csv";BASE="stage6-3e-exact-event-exposure-dimension-matching-baseline";BASE_COMMIT="884b35bf86f12b3835c56855fdec2cd61df688ad";CHECKS=[]
def check(c,n):
 def register(f):CHECKS.append((c,n,f));return f
 return register
def require(v,m="assertion failed"):
 if not v:raise AssertionError(m)
def expect(error,fn,contains=None):
 try:fn()
 except error as x:
  if contains:require(contains in str(x),f"{contains!r} not in {x!r}")
  return x
 raise AssertionError("expected "+error.__name__)
def git(*x):return subprocess.check_output(["git",*x],cwd=REPO,text=True).strip()
@contextmanager
def env(*,event_type="RATE_HIKE",channel="RATE",types=("INTEREST_RATE_SENSITIVITY",),event_values=(),event_field="currencies",exposure_entities=(),match_inputs=None,event_match_entity=None):
 with e.env(event_type=event_type,channel=channel,types=types,event_values=event_values,event_field=event_field,exposure_entities=exposure_entities) as values:
  ing,events,exposures,bindings,transmissions,qualifications,matches,evidence,registry,event,exposure,binding,transmission,qualification,root=values
  if match_inputs is None:
   if channel in {"GEOGRAPHY","MACRO"}:match_inputs=[e.qinput(evidence,event_values[0],event_match_entity or exposure_entities[0],"COUNTRY")]
   elif channel=="CURRENCY":match_inputs=[e.qinput(evidence,event_values[0],event_match_entity or exposure_entities[0],"CURRENCY")]
   elif channel=="COMMODITY":match_inputs=[e.qinput(evidence,event_values[0],event_match_entity or exposure_entities[0],"COMMODITY")]
   else:match_inputs=[]
  match=matches.match_qualification(qualification_id=qualification["qualification_id"],event_qualifier_inputs=match_inputs)["match"]
  store=DirectionStore(root/"direction.sqlite3",matches)
  try:yield store,matches,evidence,event,exposure,match,root
  finally:store.close()
def din(match,evidence,effect="ADVERSE",index=0,name="exposure"):
 return {"source_path_id":match["path_matches"][index]["source_path_id"],"effect_direction":effect,"evidence_ids":[evidence[name]["evidence_id"]]}
@check("BASELINE","frozen Stage 6.3E exact ancestor")
def _():require(git("rev-parse",f"{BASE}^{{}}")==BASE_COMMIT);subprocess.check_call(["git","merge-base","--is-ancestor",BASE_COMMIT,"HEAD"],cwd=REPO)
@check("CONTRACT","schema store processor policy authority exact")
def _():require((SCHEMA_VERSION,STORE_SCHEMA_VERSION,PROCESSOR_VERSION,POLICY_ID,AUTHORITY)==("STAGE6_ECONOMIC_PATH_DIRECTION_V1","STAGE6_3F_DIRECTION_STORE_V1","STAGE6_3F_DIRECTION_EVALUATOR_V1","S6DIRPOL_STAGE6_3F_V1","SHADOW_ONLY"))
@check("POLICY","exact six-rule policy and immutable hash")
def _():p,j,h=load_policy();require(validate_policy(p)==p and p["rules"]==EXPECTED_RULES_V1 and h==EXPECTED_POLICY_HASH_V1==canonical_hash(p))
@check("POLICY","semantic policy drift rejected")
def _():
 p,_,_=load_policy()
 for change in (lambda x:x["rules"].pop(),lambda x:x["rules"][0].__setitem__("event_driver_change","DECREASE"),lambda x:x["rules"][2].__setitem__("dimension_requirement","NOT_REQUIRED"),lambda x:x.__setitem__("authority","TRADING")):
  q=deepcopy(p);change(q);expect(Stage6DirectionError,lambda q=q:validate_policy(q))
@check("FIXTURE","synthetic direction examples cover the required adversarial set")
def _():
 data=json.loads((ROOT/"fixtures"/"stage6_3f"/"directional_examples.json").read_text());pairs={(x["event_type"],x["effect_direction"]) for x in data["examples"]};require(data["fixture_only"] and not data["investment_claims"] and {("RATE_HIKE","ADVERSE"),("RATE_HIKE","FAVORABLE"),("RATE_CUT","FAVORABLE"),("RATE_CUT","ADVERSE"),("TARIFF_INCREASE","ADVERSE"),("TARIFF_REDUCTION","FAVORABLE"),("WAR_ESCALATION","ADVERSE"),("WAR_ESCALATION","FAVORABLE"),("WAR_DEESCALATION","FAVORABLE"),("WAR_DEESCALATION","ADVERSE"),("RATE_HIKE","UNKNOWN"),("RATE_HIKE","MIXED")}<=pairs)
@check("RATE","rate hike supports explicit adverse without automatic inference")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):r=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence)])["direction"];require(r["matched_path_direction_summary"]=="ADVERSE_ONLY" and r["direction_qualification_status"]=="ALL_ELIGIBLE_PATHS_QUALIFIED" and r["direction_qualifiers"][0]["event_driver_change"]=="INCREASE")
@check("ADVERSARIAL","rate hike may be explicitly favorable; type does not imply effect")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):r=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,"FAVORABLE")])["direction"];require(r["matched_path_direction_summary"]=="FAVORABLE_ONLY")
@check("RATE","rate cut supports explicit favorable and adverse")
def _():
 for effect,summary in (("FAVORABLE","FAVORABLE_ONLY"),("ADVERSE","ADVERSE_ONLY")):
  with env(event_type="RATE_CUT") as (s,m,evidence,event,exposure,match,root):require(s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,effect)])["direction"]["matched_path_direction_summary"]==summary)
@check("UNQUALIFIED","eligible path without declaration stays unqualified and indeterminate")
def _():
 with env(event_type="RATE_CUT") as (s,m,evidence,event,exposure,match,root):r=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[])["direction"];require((r["direction_qualification_status"],r["matched_path_direction_summary"],r["qualified_path_ids"])==("UNQUALIFIED","INDETERMINATE",[]))
@check("TARIFF","exact tariff dimension match accepts explicit direction")
def _():
 with env(event_type="TARIFF_INCREASE",channel="MACRO",types=("IMPORT_DEPENDENCY",),event_values=("China",),event_field="geographies",exposure_entities=("COUNTRY_CN",)) as (s,m,evidence,event,exposure,match,root):r=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,"ADVERSE")])["direction"];require(r["matched_path_direction_summary"]=="ADVERSE_ONLY" and r["direction_qualifiers"][0]["matched_dimension_entity_ids"]==["COUNTRY_CN"])
@check("WAR","war escalation and de-escalation remain explicit not inverse inferred")
def _():
 for et,effect in (("WAR_ESCALATION","FAVORABLE"),("WAR_DEESCALATION","ADVERSE")):
  with env(event_type=et,channel="GEOGRAPHY",types=("REVENUE_GEOGRAPHY",),event_values=("United States",),event_field="geographies",exposure_entities=("COUNTRY_US",)) as (s,m,evidence,event,exposure,match,root):r=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,effect)])["direction"];require(r["direction_qualifiers"][0]["effect_direction"]==effect)
@check("ELIGIBILITY","all six exact V1 event types are independently eligible")
def _():
 for et in ("RATE_HIKE","RATE_CUT"):
  with env(event_type=et) as (s,m,evidence,event,exposure,match,root):require(s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,"FAVORABLE")])["direction"]["direction_qualification_status"]=="ALL_ELIGIBLE_PATHS_QUALIFIED")
 for et,ch,typ,value,entity in (("TARIFF_INCREASE","MACRO","IMPORT_DEPENDENCY","China","COUNTRY_CN"),("TARIFF_REDUCTION","MACRO","IMPORT_DEPENDENCY","China","COUNTRY_CN"),("WAR_ESCALATION","GEOGRAPHY","REVENUE_GEOGRAPHY","United States","COUNTRY_US"),("WAR_DEESCALATION","GEOGRAPHY","REVENUE_GEOGRAPHY","United States","COUNTRY_US")):
  with env(event_type=et,channel=ch,types=(typ,),event_values=(value,),event_field="geographies",exposure_entities=(entity,)) as (s,m,evidence,event,exposure,match,root):require(s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,"FAVORABLE")])["direction"]["direction_qualification_status"]=="ALL_ELIGIBLE_PATHS_QUALIFIED")
@check("INELIGIBLE","tariff no-match and indeterminate paths cannot be directed")
def _():
 for entity,inputs in (("COUNTRY_US",None),("COUNTRY_CN",[])):
  with env(event_type="TARIFF_INCREASE",channel="MACRO",types=("IMPORT_DEPENDENCY",),event_values=("China",),event_field="geographies",exposure_entities=(entity,),match_inputs=inputs,event_match_entity="COUNTRY_CN") as (s,m,evidence,event,exposure,match,root):require(s.evaluate_direction(match_id=match["match_id"],directional_inputs=[])["direction"]["direction_qualification_status"]=="NO_ELIGIBLE_PATHS");expect(Stage6DirectionError,lambda:s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence)]),"NO_ELIGIBLE")
@check("UNSUPPORTED","currency commodity and sanction paths are not eligible")
def _():
 cases=(("CURRENCY_SHOCK","CURRENCY","CURRENCY",("USD",),"currencies",("CUR_USD",),["USD","CUR_USD","CURRENCY"]),("OIL_SHOCK","COMMODITY","ENERGY_SENSITIVITY",("Crude Oil",),"commodities",("CMD_CRUDE_OIL",),["Crude Oil","CMD_CRUDE_OIL","COMMODITY"]),("SANCTION","GEOGRAPHY","REVENUE_GEOGRAPHY",("United States",),"geographies",("COUNTRY_US",),["United States","COUNTRY_US","COUNTRY"]))
 for et,ch,typ,values,field,entities,q in cases:
  with env(event_type=et,channel=ch,types=(typ,),event_values=values,event_field=field,exposure_entities=entities) as (s,m,evidence,event,exposure,match,root):require(match["path_matches"][0]["dimension_match_status"]=="EXACT_ENTITY_MATCH" and s.evaluate_direction(match_id=match["match_id"],directional_inputs=[])["direction"]["matched_path_direction_summary"]=="NOT_EVALUATED")
@check("DIRECTIONS","mixed and unknown are preserved exactly")
def _():
 for effect in ("MIXED","UNKNOWN"):
  with env() as (s,m,evidence,event,exposure,match,root):r=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,effect)])["direction"];require(r["matched_path_direction_summary"]==("MIXED_PATH_DIRECTIONS" if effect=="MIXED" else "INDETERMINATE"))
@check("DIRECTIONS","absent and explicit unknown have distinct deterministic identities")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):absent=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[])["direction"]
 with env() as (s,m,evidence,event,exposure,match,root):unknown=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,"UNKNOWN")])["direction"]
 require(absent["direction_record_id"]!=unknown["direction_record_id"] and absent["path_direction_results"][0]["effect_direction"] is None and unknown["path_direction_results"][0]["effect_direction"]=="UNKNOWN")
@check("MULTIPATH","partial qualification and mixed complete summary exact")
def _():
 with env(types=("INTEREST_RATE_SENSITIVITY","DEBT_SENSITIVITY")) as (s,m,evidence,event,exposure,match,root):
  one=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,"FAVORABLE",0)])["direction"];require(one["direction_qualification_status"]=="PARTIALLY_QUALIFIED" and one["matched_path_direction_summary"]=="INDETERMINATE")
 with env(types=("INTEREST_RATE_SENSITIVITY","DEBT_SENSITIVITY")) as (s,m,evidence,event,exposure,match,root):
  inputs=[din(match,evidence,"FAVORABLE",0),din(match,evidence,"ADVERSE",1)];r=s.evaluate_direction(match_id=match["match_id"],directional_inputs=list(reversed(inputs)))["direction"];require(r["direction_qualification_status"]=="ALL_ELIGIBLE_PATHS_QUALIFIED" and r["matched_path_direction_summary"]=="MIXED_PATH_DIRECTIONS")
@check("MULTIPATH","all favorable and all adverse summaries are unweighted")
def _():
 for effect,summary in (("FAVORABLE","FAVORABLE_ONLY"),("ADVERSE","ADVERSE_ONLY")):
  with env(types=("INTEREST_RATE_SENSITIVITY","DEBT_SENSITIVITY")) as (s,m,evidence,event,exposure,match,root):inputs=[din(match,evidence,effect,0),din(match,evidence,effect,1)];require(s.evaluate_direction(match_id=match["match_id"],directional_inputs=inputs)["direction"]["matched_path_direction_summary"]==summary)
@check("VALIDATION","input shape direction path and duplicates fail closed")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):
  good=din(match,evidence);expect(Stage6DirectionError,lambda:s.evaluate_direction(match_id=match["match_id"],directional_inputs={}),"INPUTS_INVALID");bad=dict(good);bad["extra"]=1;expect(Stage6DirectionError,lambda:s.evaluate_direction(match_id=match["match_id"],directional_inputs=[bad]),"FIELDS_INVALID");bad=dict(good,effect_direction="POSITIVE");expect(Stage6DirectionError,lambda:s.evaluate_direction(match_id=match["match_id"],directional_inputs=[bad]),"EFFECT_DIRECTION");expect(Stage6DirectionError,lambda:s.evaluate_direction(match_id=match["match_id"],directional_inputs=[good,good]),"DUPLICATE")
@check("EVIDENCE","direction evidence must be exact assertion evidence subset")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):expect(Stage6DirectionError,lambda:s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,name="other")]),"NOT_ASSERTION_SUBSET")
@check("EVIDENCE","company and exact matched dimension support are mandatory")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):
  exposure_store=m.qualification_store.transmission_store.binding_store.exposure_store;bad=deepcopy(evidence["exposure"]);bad["entity_ids"]=[x for x in bad["entity_ids"] if x!=match["company_entity_id"]]
  with mock.patch.object(exposure_store,"_evidence",return_value=[bad]):expect(Stage6DirectionError,lambda:s._resolve(match,event,exposure,[din(match,evidence)]),"COMPANY_SUPPORT")
 with env(event_type="TARIFF_INCREASE",channel="MACRO",types=("IMPORT_DEPENDENCY",),event_values=("China",),event_field="geographies",exposure_entities=("COUNTRY_CN",)) as (s,m,evidence,event,exposure,match,root):
  exposure_store=m.qualification_store.transmission_store.binding_store.exposure_store;bad=deepcopy(evidence["exposure"]);bad["entity_ids"]=[x for x in bad["entity_ids"] if x!="COUNTRY_CN"]
  with mock.patch.object(exposure_store,"_evidence",return_value=[bad]):expect(Stage6DirectionError,lambda:s._resolve(match,event,exposure,[din(match,evidence)]),"DIMENSION_SUPPORT")
@check("PIT","evidence and exposure cutoffs do not exceed exact match cutoff")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):r=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence)])["direction"];require(evidence["exposure"]["retrieved_timestamp_utc"]<=exposure["data_cutoff_timestamp"]<=r["direction_cutoff_timestamp"]==match["match_cutoff_timestamp"])
@check("IDENTITY","canonical order idempotency and conflicting direction fail")
def _():
 with env(types=("INTEREST_RATE_SENSITIVITY","DEBT_SENSITIVITY")) as (s,m,evidence,event,exposure,match,root):
  inputs=[din(match,evidence,"FAVORABLE",0),din(match,evidence,"ADVERSE",1)];first=s.evaluate_direction(match_id=match["match_id"],directional_inputs=inputs);require(s.evaluate_direction(match_id=match["match_id"],directional_inputs=list(reversed(inputs)))["status"]=="IDEMPOTENT_SUCCESS");expect(DirectionConflict,lambda:s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence,"FAVORABLE",0)]))
@check("DEPENDENCY","exact Stage-qualified dependency set and full integrity")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):r=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence)])["direction"];types={x[0] for x in s.connection.execute("SELECT record_type FROM direction_dependencies WHERE direction_record_id=?",(r["direction_record_id"],))};require(types=={"STAGE6_3E_DIMENSION_MATCH","STAGE6_3D_DIMENSION_QUALIFICATION","STAGE6_3C_TRANSMISSION","STAGE6_3B_EVENT_EXPOSURE_BINDING","STAGE6_EVENT","STAGE6_EXPOSURE","DIRECTION_POLICY","EVIDENCE"} and s.integrity_check()["result"]=="PASS")
@check("CARDINALITY","metadata and policy singletons fail closed")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):expect(sqlite3.IntegrityError,lambda:s.connection.execute("INSERT INTO direction_store_meta VALUES(2,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASE_COMMIT,PROCESSOR_VERSION,AUTHORITY)));s.connection.execute("INSERT INTO direction_policies VALUES(?,?,?)",("FAKE","f"*64,"{}"));s.connection.commit();expect(DirectionIntegrityFailure,s.integrity_check,"POLICY")
@check("APPEND_ONLY","all direction tables immutable and trigger loss detected")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):
  s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence)])
  for table in ("direction_store_meta","direction_policies","direction_records","direction_qualifiers","direction_qualifier_evidence","direction_path_results","direction_dependencies"):expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"UPDATE {table} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"DELETE FROM {table}"))
  s.connection.execute("DROP TRIGGER protect_direction_records_delete");s.connection.commit();expect(DirectionIntegrityFailure,s.integrity_check,"TRIGGER")
@check("RESTART","closed store reopens and verifies deterministically")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence)]);s.close();r=DirectionStore(root/"direction.sqlite3",m);require(r.integrity_check()["result"]=="PASS");r.close()
@check("TAMPER","root qualifier evidence path policy and dependency tamper fail")
def _():
 for table,column,value in (("direction_records","record_hash","f"*64),("direction_qualifiers","effect_direction","UNKNOWN"),("direction_qualifier_evidence","evidence_hash","f"*64),("direction_path_results","eligibility_status","NOT_ELIGIBLE"),("direction_policies","policy_hash","f"*64),("direction_dependencies","record_hash","f"*64)):
  with env() as (s,m,evidence,event,exposure,match,root):s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence)]);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.commit();expect(Exception,s.integrity_check)
@check("SAFETY","all non-path economic and trading semantics remain not evaluated")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):r=s.evaluate_direction(match_id=match["match_id"],directional_inputs=[din(match,evidence)])["direction"];require(r["directional_scope"]=="MATCHED_EXPOSURE_PATH_ONLY" and all(r[k]=="NOT_EVALUATED" for k in ("overall_company_effect_status","stock_direction_status","market_reaction_status","magnitude_status","expected_return_status","causal_effect_status","trade_role_semantics_status")))
@check("BOUNDARY","only additive Stage 6.3F files; zero network AI ML NLP trading")
def _():
 require(git("diff","--name-only",BASE,"--","Stage 5D","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/stage6_lifecycle","Stage 6/stage6_exposure","Stage 6/stage6_exposure_binding","Stage 6/stage6_transmission","Stage 6/stage6_dimension_qualification","Stage 6/stage6_dimension_matching","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/scripts/validate_stage6_0.py")=="")
 prohibited={"socket","requests","urllib","http","aiohttp","openai","transformers","re"};text=""
 for p in (ROOT/"stage6_direction_semantics").glob("*.py"):
  src=p.read_text();text+=src.casefold();tree=ast.parse(src);imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports&prohibited)
 for token in ("semantic similarity","embedding","ocr","expected return","buy","sell","broker","portfolio mutation","automatic direction","inverse semantics"):require(token not in text)
def main():
 rows=[]
 for i,(category,name,fn) in enumerate(CHECKS,1):
  try:
   with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):fn()
   rows.append({"test_id":f"S6_3F_{i:03d}","category":category,"test_name":name,"result":"PASS","detail":""})
  except Exception as x:rows.append({"test_id":f"S6_3F_{i:03d}","category":category,"test_name":name,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 OUT.parent.mkdir(exist_ok=True);h=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows);h.close();bad=[x for x in rows if x["result"]=="FAIL"];print(json.dumps({"stage":"6.3F","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",x) for x in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
