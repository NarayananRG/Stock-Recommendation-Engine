"""Stage 6.3G explicit Event-dimension movement qualification tests."""
from __future__ import annotations
import ast,csv,importlib.util,json,socket,sqlite3,subprocess,sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location("s63e",Path(__file__).with_name("run_stage6_3e_tests.py"));e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
from stage6_event_movement import *
from stage6_ingestion.canonical import canonical_hash
OUT=ROOT/"results"/"stage6_3g_test_results.csv";BASE="stage6-3f-economic-path-direction-semantics-baseline";BASE_COMMIT="b1c755e03666be30f623acd6ff3e77184a58ea41";CHECKS=[]
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
def env(*,event_type="CURRENCY_SHOCK",channel="CURRENCY",types=("CURRENCY",),event_values=("USD","EUR"),event_field="currencies",exposure_entities=("CUR_USD",),qspecs=None,event_evidence_dims=None,event_authority="PRIMARY_OFFICIAL"):
 with e.env(event_type=event_type,channel=channel,types=types,event_values=event_values,event_field=event_field,exposure_entities=exposure_entities,event_evidence_dims=event_evidence_dims,event_authority=event_authority) as values:
  ing,events,exposures,bindings,transmissions,qualifications,matches,evidence,registry,event,exposure,binding,transmission,qualification,root=values
  if qspecs is None:
   mapping={"USD":"CUR_USD","EUR":"CUR_EUR","Crude Oil":"CMD_CRUDE_OIL","Natural Gas":"CMD_NATURAL_GAS"};dtype="CURRENCY" if event_field=="currencies" else "COMMODITY";qspecs=[(v,mapping[v],dtype) for v in event_values]
  qinputs=[e.qinput(evidence,value,entity,dtype) for value,entity,dtype in qspecs];match=matches.match_qualification(qualification_id=qualification["qualification_id"],event_qualifier_inputs=qinputs)["match"];store=EventMovementStore(root/"movement.sqlite3",matches)
  try:yield store,matches,evidence,event,exposure,match,root
  finally:store.close()
def qualifier(match,entity):return next(x for x in match["event_qualifiers"] if x["dimension_entity_id"]==entity)
def movement(match,evidence,source,reference=None,direction="STRENGTHEN",metric=None,name="event"):
 src=qualifier(match,source);ref=qualifier(match,reference) if reference else None
 return {"source_event_qualifier_id":src["event_qualifier_id"],"reference_event_qualifier_id":ref["event_qualifier_id"] if ref else None,"movement_metric":metric or ("RELATIVE_VALUE" if reference else "PRICE"),"movement_direction":direction,"evidence_ids":[evidence[name]["evidence_id"]]}
@check("BASELINE","frozen Stage 6.3F exact ancestor")
def _():require(git("rev-parse",f"{BASE}^{{}}")==BASE_COMMIT);subprocess.check_call(["git","merge-base","--is-ancestor",BASE_COMMIT,"HEAD"],cwd=REPO)
@check("CONTRACT","schema store processor policy authority exact")
def _():require((SCHEMA_VERSION,STORE_SCHEMA_VERSION,PROCESSOR_VERSION,POLICY_ID,AUTHORITY)==("STAGE6_EVENT_DIMENSION_MOVEMENT_V1","STAGE6_3G_EVENT_MOVEMENT_STORE_V1","STAGE6_3G_EVENT_MOVEMENT_QUALIFIER_V1","S6MOVPOL_STAGE6_3G_V1","SHADOW_ONLY"))
@check("POLICY","exact four-rule policy and immutable hash")
def _():p,j,h=load_policy();require(validate_policy(p)==p and p["rules"]==EXPECTED_RULES_V1 and h==EXPECTED_POLICY_HASH_V1==canonical_hash(p))
@check("POLICY","structurally valid semantic drift fails closed")
def _():
 p,_,_=load_policy()
 for change in (lambda x:x["rules"].pop(),lambda x:x["rules"][0].__setitem__("reference_requirement","PROHIBITED"),lambda x:x["rules"][1].__setitem__("movement_metric","SUPPLY"),lambda x:x["rules"][2]["allowed_movements"].pop(),lambda x:x["rules"][3].__setitem__("source_rule_id","RENAMED")):
  q=deepcopy(p);change(q);expect(Stage6EventMovementError,lambda q=q:validate_policy(q))
@check("FIXTURE","synthetic fixture covers currency commodity mixed and unknown examples")
def _():
 data=json.loads((ROOT/"fixtures"/"stage6_3g"/"movement_examples.json").read_text());require(data["fixture_only"] and not data["investment_claims"] and {"CUR_USD","CUR_EUR","CUR_JPY","CMD_CRUDE_OIL","CMD_NATURAL_GAS"}==set(data["entities"]) and {x["movement"] for x in data["examples"]}>={"STRENGTHEN","WEAKEN","INCREASE","DECREASE","MIXED","UNKNOWN"})
@check("CURRENCY","explicit strengthen and weaken preserve exact orientation")
def _():
 for direction in ("STRENGTHEN","WEAKEN"):
  with env() as (s,m,evidence,event,exposure,match,root):r=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR",direction)])["movement"];item=r["movement_items"][0];require(item["movement_direction"]==direction and item["source_dimension_entity_id"]=="CUR_USD" and item["reference_dimension_entity_id"]=="CUR_EUR" and r["movement_qualification_status"]=="ALL_ELIGIBLE_SUBJECTS_QUALIFIED")
@check("CURRENCY","mixed and unknown are explicit qualified declarations")
def _():
 for direction in ("MIXED","UNKNOWN"):
  with env() as (s,m,evidence,event,exposure,match,root):r=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR",direction)])["movement"];require(r["movement_items"][0]["movement_direction"]==direction and r["movement_qualification_status"]=="ALL_ELIGIBLE_SUBJECTS_QUALIFIED")
@check("CURRENCY","reference required and same subject reference rejected")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):
  x=movement(match,evidence,"CUR_USD","CUR_EUR");x["reference_event_qualifier_id"]=None;expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[x]),"REFERENCE_REQUIRED");x=movement(match,evidence,"CUR_USD","CUR_EUR");x["reference_event_qualifier_id"]=x["source_event_qualifier_id"];expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[x]),"MUST_DIFFER")
@check("CURRENCY","reference must be exact qualifier and metric enum exact")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):
  x=movement(match,evidence,"CUR_USD","CUR_EUR");x["reference_event_qualifier_id"]="MISSING";expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[x]),"REFERENCE_QUALIFIER_NOT_FOUND");x=movement(match,evidence,"CUR_USD","CUR_EUR",metric="PRICE");expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[x]),"METRIC_INVALID");x=movement(match,evidence,"CUR_USD","CUR_EUR",direction="INCREASE");expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[x]),"DIRECTION_INVALID")
@check("CURRENCY","no reverse pair is synthesized")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):r=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR")])["movement"];require(len(r["movement_items"])==1 and r["movement_items"][0]["source_dimension_entity_id"]=="CUR_USD")
@check("CURRENCY","explicit reverse ordered pairs may coexist without consistency inference")
def _():
 with env(types=("CURRENCY","CURRENCY"),exposure_entities=("CUR_USD","CUR_EUR")) as (s,m,evidence,event,exposure,match,root):inputs=[movement(match,evidence,"CUR_USD","CUR_EUR","STRENGTHEN"),movement(match,evidence,"CUR_EUR","CUR_USD","STRENGTHEN")];r=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=list(reversed(inputs)))["movement"];require(len(r["movement_items"])==2 and r["movement_qualification_status"]=="ALL_ELIGIBLE_SUBJECTS_QUALIFIED")
@check("COMMODITY","oil price increase decrease mixed and unknown accepted")
def _():
 for direction in ("INCREASE","DECREASE","MIXED","UNKNOWN"):
  with env(event_type="OIL_SHOCK",channel="COMMODITY",types=("ENERGY_SENSITIVITY",),event_values=("Crude Oil",),event_field="commodities",exposure_entities=("CMD_CRUDE_OIL",)) as (s,m,evidence,event,exposure,match,root):r=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CMD_CRUDE_OIL",direction=direction)])["movement"];require(r["movement_items"][0]["movement_direction"]==direction and r["movement_items"][0]["movement_metric"]=="PRICE")
@check("COMMODITY","gas and generic commodity shock supported independently")
def _():
 for et,value,entity in (("GAS_SHOCK","Natural Gas","CMD_NATURAL_GAS"),("COMMODITY_SHOCK","Crude Oil","CMD_CRUDE_OIL")):
  with env(event_type=et,channel="COMMODITY",types=("ENERGY_SENSITIVITY",),event_values=(value,),event_field="commodities",exposure_entities=(entity,)) as (s,m,evidence,event,exposure,match,root):require(s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,entity,direction="INCREASE")])["movement"]["movement_qualification_status"]=="ALL_ELIGIBLE_SUBJECTS_QUALIFIED")
@check("COMMODITY","reference metric and enum restrictions enforced")
def _():
 with env(event_type="OIL_SHOCK",channel="COMMODITY",types=("ENERGY_SENSITIVITY",),event_values=("Crude Oil",),event_field="commodities",exposure_entities=("CMD_CRUDE_OIL",)) as (s,m,evidence,event,exposure,match,root):
  x=movement(match,evidence,"CMD_CRUDE_OIL",direction="INCREASE");x["reference_event_qualifier_id"]=x["source_event_qualifier_id"];expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[x]),"REFERENCE_PROHIBITED");x=movement(match,evidence,"CMD_CRUDE_OIL",direction="INCREASE",metric="SUPPLY");expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[x]),"METRIC_INVALID");x=movement(match,evidence,"CMD_CRUDE_OIL",direction="STRENGTHEN");expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[x]),"DIRECTION_INVALID")
@check("ELIGIBILITY","unsupported rate and tariff Events have no targets")
def _():
 for et,ch,typ,values,field,entities,qspecs in (("RATE_HIKE","RATE","INTEREST_RATE_SENSITIVITY",(),"currencies",(),[]),("TARIFF_INCREASE","MACRO","IMPORT_DEPENDENCY",("China",),"geographies",("COUNTRY_CN",),[("China","COUNTRY_CN","COUNTRY")])):
  with env(event_type=et,channel=ch,types=(typ,),event_values=values,event_field=field,exposure_entities=entities,qspecs=qspecs) as (s,m,evidence,event,exposure,match,root):r=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[])["movement"];require(r["movement_qualification_status"]=="NO_ELIGIBLE_MOVEMENT_TARGETS" and r["movement_items"]==[]);expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[{"bad":1}]),"NO_ELIGIBLE")
@check("ELIGIBILITY","no-match and indeterminate subjects are prohibited")
def _():
 for exposure_entity,qspecs in (("CUR_EUR",[("USD","CUR_USD","CURRENCY")]),("CUR_USD",[])):
  with env(event_values=("USD",),exposure_entities=(exposure_entity,),qspecs=qspecs) as (s,m,evidence,event,exposure,match,root):r=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[])["movement"];require(r["movement_qualification_status"]=="NO_ELIGIBLE_MOVEMENT_TARGETS")
@check("STATUS","unqualified partial and all-qualified subject partitions exact")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):require(s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[])["movement"]["movement_qualification_status"]=="UNQUALIFIED")
 with env(event_type="COMMODITY_SHOCK",channel="COMMODITY",types=("COMMODITY","COMMODITY"),event_values=("Crude Oil","Natural Gas"),event_field="commodities",exposure_entities=("CMD_CRUDE_OIL","CMD_NATURAL_GAS")) as (s,m,evidence,event,exposure,match,root):one=movement(match,evidence,"CMD_CRUDE_OIL",direction="INCREASE");require(s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[one])["movement"]["movement_qualification_status"]=="PARTIALLY_QUALIFIED")
 with env(event_type="COMMODITY_SHOCK",channel="COMMODITY",types=("COMMODITY","COMMODITY"),event_values=("Crude Oil","Natural Gas"),event_field="commodities",exposure_entities=("CMD_CRUDE_OIL","CMD_NATURAL_GAS")) as (s,m,evidence,event,exposure,match,root):inputs=[movement(match,evidence,"CMD_CRUDE_OIL",direction="INCREASE"),movement(match,evidence,"CMD_NATURAL_GAS",direction="DECREASE")];require(s.qualify_event_movement(match_id=match["match_id"],movement_inputs=inputs)["movement"]["movement_qualification_status"]=="ALL_ELIGIBLE_SUBJECTS_QUALIFIED")
@check("EVIDENCE","movement evidence must belong to exact Event")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR",name="other")]),"NOT_EVENT_SUBSET")
@check("EVIDENCE","subject and currency reference entity support mandatory")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):
  event_store=m.qualification_store.transmission_store.binding_store.event_store;bad=deepcopy(evidence["event"]);bad["entity_ids"]=[x for x in bad["entity_ids"] if x!="CUR_USD"]
  with mock.patch.object(event_store,"_load_evidence",return_value=[bad]):expect(Stage6EventMovementError,lambda:s._resolve(match,event,m._chain(match["qualification_id"])[5],[movement(match,evidence,"CUR_USD","CUR_EUR")]),"SUBJECT_SUPPORT")
  bad=deepcopy(evidence["event"]);bad["entity_ids"]=[x for x in bad["entity_ids"] if x!="CUR_EUR"]
  with mock.patch.object(event_store,"_load_evidence",return_value=[bad]):expect(Stage6EventMovementError,lambda:s._resolve(match,event,m._chain(match["qualification_id"])[5],[movement(match,evidence,"CUR_USD","CUR_EUR")]),"REFERENCE_SUPPORT")
@check("EVIDENCE","primary official and authoritative independent evidence accepted")
def _():
 for authority in ("PRIMARY_OFFICIAL","AUTHORITATIVE_INDEPENDENT"):
  with env(event_authority=authority) as (s,m,evidence,event,exposure,match,root):s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR")])
@check("PIT","evidence Event and movement cutoffs are exact")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):r=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR")])["movement"];require(evidence["event"]["retrieved_timestamp_utc"]<=event["last_updated_timestamp"]<=r["movement_cutoff_timestamp"]==match["match_cutoff_timestamp"])
@check("IDENTITY","absent and explicit unknown have distinct identities")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):a=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[])["movement"]
 with env() as (s,m,evidence,event,exposure,match,root):u=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR","UNKNOWN")])["movement"]
 require(a["movement_record_id"]!=u["movement_record_id"] and a["movement_qualification_status"]=="UNQUALIFIED" and u["movement_qualification_status"]=="ALL_ELIGIBLE_SUBJECTS_QUALIFIED")
@check("IDENTITY","canonical order idempotency and distinct movement conflict")
def _():
 with env(types=("CURRENCY","CURRENCY"),exposure_entities=("CUR_USD","CUR_EUR")) as (s,m,evidence,event,exposure,match,root):inputs=[movement(match,evidence,"CUR_USD","CUR_EUR"),movement(match,evidence,"CUR_EUR","CUR_USD","WEAKEN")];first=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=inputs);require(s.qualify_event_movement(match_id=match["match_id"],movement_inputs=list(reversed(inputs)))["status"]=="IDEMPOTENT_SUCCESS");expect(EventMovementConflict,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[inputs[0]]))
@check("DUPLICATE","commodity subject and currency ordered pair duplicates rejected")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):x=movement(match,evidence,"CUR_USD","CUR_EUR");expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[x,x]),"DUPLICATE")
 with env(event_type="OIL_SHOCK",channel="COMMODITY",types=("ENERGY_SENSITIVITY",),event_values=("Crude Oil",),event_field="commodities",exposure_entities=("CMD_CRUDE_OIL",)) as (s,m,evidence,event,exposure,match,root):x=movement(match,evidence,"CMD_CRUDE_OIL",direction="INCREASE");expect(Stage6EventMovementError,lambda:s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[x,x]),"DUPLICATE")
@check("DEPENDENCY","exact direct dependency set excludes 6.3F and transitive chain")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):r=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR")])["movement"];types={x[0] for x in s.connection.execute("SELECT record_type FROM event_movement_dependencies WHERE movement_record_id=?",(r["movement_record_id"],))};require(types=={"STAGE6_3E_DIMENSION_MATCH","STAGE6_EVENT","EVENT_ENTITY_REGISTRY_SNAPSHOT","EVENT_MOVEMENT_POLICY","EVIDENCE"} and s.integrity_check()["result"]=="PASS")
@check("CARDINALITY","metadata constraint and policy singleton fail closed")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):expect(sqlite3.IntegrityError,lambda:s.connection.execute("INSERT INTO event_movement_store_meta VALUES(2,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASE_COMMIT,PROCESSOR_VERSION,AUTHORITY)));s.connection.execute("INSERT INTO event_movement_policies VALUES(?,?,?)",("FAKE","f"*64,"{}"));s.connection.commit();expect(EventMovementIntegrityFailure,s.integrity_check,"POLICY")
@check("APPEND_ONLY","all movement tables immutable and trigger loss detected")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):
  s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR")])
  for table in ("event_movement_store_meta","event_movement_policies","event_movement_records","event_movement_items","event_movement_evidence","event_movement_dependencies"):expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"UPDATE {table} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"DELETE FROM {table}"))
  s.connection.execute("DROP TRIGGER protect_event_movement_records_delete");s.connection.commit();expect(EventMovementIntegrityFailure,s.integrity_check,"TRIGGER")
@check("RESTART","closed movement store reopens and replays identically")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR")]);s.close();r=EventMovementStore(root/"movement.sqlite3",m);require(r.integrity_check()["result"]=="PASS");r.close()
@check("TAMPER","record item evidence policy and dependency tamper fail integrity")
def _():
 for table,column,value in (("event_movement_records","match_hash","f"*64),("event_movement_records","event_hash","f"*64),("event_movement_records","event_entity_registry_hash","f"*64),("event_movement_items","movement_direction","WEAKEN"),("event_movement_items","reference_dimension_entity_id","CUR_USD"),("event_movement_evidence","evidence_hash","f"*64),("event_movement_policies","policy_hash","f"*64),("event_movement_dependencies","record_type","MOVEMENT_POLICY")):
  with env() as (s,m,evidence,event,exposure,match,root):s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR")]);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.commit();expect(Exception,s.integrity_check)
@check("SAFETY","movement scope and all downstream semantic statuses remain unevaluated")
def _():
 with env() as (s,m,evidence,event,exposure,match,root):r=s.qualify_event_movement(match_id=match["match_id"],movement_inputs=[movement(match,evidence,"CUR_USD","CUR_EUR")])["movement"];require(r["movement_scope"]=="EVENT_DIMENSION_ONLY" and all(r[k]=="NOT_EVALUATED" for k in ("aggregate_event_movement_status","path_effect_direction_status","overall_company_effect_status","stock_direction_status","market_reaction_status","magnitude_status","expected_return_status")))
@check("BOUNDARY","only additive 6.3G code with zero network AI path-effect or trading")
def _():
 frozen=("Stage 5D","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/stage6_lifecycle","Stage 6/stage6_exposure","Stage 6/stage6_exposure_binding","Stage 6/stage6_transmission","Stage 6/stage6_dimension_qualification","Stage 6/stage6_dimension_matching","Stage 6/stage6_direction_semantics","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/scripts/validate_stage6_0.py");require(git("diff","--name-only",BASE,"--",*frozen)=="")
 prohibited={"socket","requests","urllib","http","aiohttp","openai","transformers","re"};text=""
 for p in (ROOT/"stage6_event_movement").glob("*.py"):
  src=p.read_text();text+=src.casefold();tree=ast.parse(src);imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports&prohibited)
 for token in ("semantic similarity","embedding","ocr","bullish","bearish","buy","sell","hold","broker","portfolio mutation","favorable","adverse"):require(token not in text)
def main():
 rows=[]
 for i,(category,name,fn) in enumerate(CHECKS,1):
  try:
   with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):fn()
   rows.append({"test_id":f"S6_3G_{i:03d}","category":category,"test_name":name,"result":"PASS","detail":""})
  except Exception as x:rows.append({"test_id":f"S6_3G_{i:03d}","category":category,"test_name":name,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 OUT.parent.mkdir(exist_ok=True);h=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows);h.close();bad=[x for x in rows if x["result"]=="FAIL"];print(json.dumps({"stage":"6.3G","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",x) for x in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
