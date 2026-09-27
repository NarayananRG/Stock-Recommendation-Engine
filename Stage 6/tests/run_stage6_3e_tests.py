"""Stage 6.3E exact Event-to-Exposure dimension entity matching tests."""
from __future__ import annotations
import ast,csv,importlib.util,json,socket,sqlite3,subprocess,sys,tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT));FIXTURE=ROOT/"fixtures"/"stage6_3e"
spec=importlib.util.spec_from_file_location("s63d",Path(__file__).with_name("run_stage6_3d_tests.py"));d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
from stage6_dimension_matching import *
from stage6_dimension_qualification import DimensionQualificationStore
from stage6_exposure import ExposureStore
from stage6_exposure_binding import BindingStore,assertion_hash
from stage6_ingestion.canonical import canonical_hash
from stage6_ingestion.registry import build_entity_registry
from stage6_transmission import TransmissionStore
OUT=ROOT/"results"/"stage6_3e_test_results.csv";BASE="stage6-3d-exposure-dimension-qualification-baseline";BASE_COMMIT="dd897395ed7bffdfdb2a03fee5fa00343d88d488";ASOF="2026-09-27T10:30:00.000000Z";CUTOFF="2026-09-27T10:00:00.000000Z";CHECKS=[]
def check(c,n):
 def register(f):CHECKS.append((c,n,f));return f
 return register
def require(v,m="assertion failed"):
 if not v:raise AssertionError(m)
def expect(e,f,contains=None):
 try:f()
 except e as x:
  if contains:require(contains in str(x),f"{contains!r} not in {x!r}")
  return x
 raise AssertionError("expected "+e.__name__)
def git(*x):return subprocess.check_output(["git",*x],cwd=REPO,text=True).strip()
@contextmanager
def env(*,event_type="CURRENCY_SHOCK",channel="CURRENCY",types=("CURRENCY",),event_values=("USD",),event_field="currencies",exposure_entities=("CUR_USD",),event_evidence_dims=None,event_authority="PRIMARY_OFFICIAL"):
 with d.base.fresh_environment() as (ing,events,old_evidence,registries,root):
  entities=deepcopy(registries["entity_v2"]["entities"])+json.loads((d.FIXTURE/"dimension_entities.json").read_text());registry=build_entity_registry(entities,"2026-09-25T12:00:00Z",registries["entity_v2"]);ing.import_registry(registry);source_snapshot=ing.connection.execute("SELECT snapshot_id FROM registry_snapshots WHERE registry_kind='SOURCE'").fetchone()[0]
  source_name={"PRIMARY_OFFICIAL":"official1","AUTHORITATIVE_INDEPENDENT":"independent1","DISCOVERY":"discovery","UNVERIFIED":"unverified"}[event_authority];event_source=old_evidence[source_name]["source_id"];official_source=old_evidence["official1"]["source_id"]
  def capture(name,source,dims):return ing.capture_evidence(idempotency_key="s63e-"+name,source_registry_snapshot_id=source_snapshot,entity_registry_snapshot_id=registry["registry_snapshot_id"],source_id=source,source_reference="fixture://s63e/"+name,raw_payload=("fixture "+name).encode(),content_type="text/plain",publication_timestamp_utc="2026-09-27T09:00:00Z",observed_timestamp_utc="2026-09-27T09:01:00Z",retrieved_timestamp_utc="2026-09-27T09:02:00Z",entity_ids=sorted([d.base.ENTITY,*dims]))["record"]
  all_dims=["CUR_USD","CUR_EUR","CMD_CRUDE_OIL","CMD_NATURAL_GAS","COUNTRY_US","COUNTRY_CN","COUNTRY_GB"];evidence={"event":capture("event",event_source,all_dims if event_evidence_dims is None else event_evidence_dims),"exposure":capture("exposure",official_source,all_dims),"other":capture("other",official_source,all_dims)}
  fields={"currencies":[],"commodities":[],"geographies":[]};fields[event_field]=list(event_values);corroboration={"PRIMARY_OFFICIAL":"SINGLE_SOURCE_OFFICIAL","AUTHORITATIVE_INDEPENDENT":"SINGLE_SOURCE_INDEPENDENT","DISCOVERY":"DISCOVERY_ONLY","UNVERIFIED":"UNVERIFIED"}[event_authority]
  event=d.base.append(events,evidence,["event"],status="CANDIDATE",event_type=event_type,entity_registry=registry["registry_snapshot_id"],updated="2026-09-27T10:00:00.000000Z",corroboration=corroboration,**fields)["event"]
  exposures=ExposureStore(root/"exposure.sqlite3",ing);items=[d.assertion(evidence["exposure"]["evidence_id"],kind,i) for i,kind in enumerate(types)];exposure=exposures.append_exposure(company_entity_id=d.base.ENTITY,exposure_version=1,previous_version_hash=None,as_of_timestamp=ASOF,data_cutoff_timestamp=CUTOFF,entity_registry_snapshot_id=registry["registry_snapshot_id"],input_evidence_ids=[evidence["exposure"]["evidence_id"]],assertions=items,relationships=[])["exposure"]
  bindings=BindingStore(root/"binding.sqlite3",events,exposures);binding=bindings.append_binding(event_id=event["event_id"],event_version=1,exposure_id=exposure["exposure_id"],exposure_version=1,selected_assertion_hashes=[assertion_hash(a) for a in exposure["assertions"]],binding_channel=channel,binding_cutoff_timestamp=ASOF)["binding"]
  transmissions=TransmissionStore(root/"transmission.sqlite3",bindings);transmission=transmissions.evaluate_binding(binding_id=binding["binding_id"])["transmission"];qualifications=DimensionQualificationStore(root/"qualification.sqlite3",transmissions);qinputs=[]
  for i,entity_id in enumerate(exposure_entities):
   path=transmission["transmission_paths"][i];dtype={"S6TRANS_CURRENCY_V1":"CURRENCY","S6TRANS_COMMODITY_V1":"COMMODITY","S6TRANS_GEOGRAPHY_V1":"COUNTRY","S6TRANS_TRADE_V1":"COUNTRY"}[path["rule_id"]];qinputs.append({"assertion_hash":path["assertion_hash"],"dimension_type":dtype,"dimension_entity_id":entity_id,"evidence_ids":[evidence["exposure"]["evidence_id"]]})
  qualification=qualifications.qualify_transmission(transmission_id=transmission["transmission_id"],qualifier_inputs=qinputs)["qualification"];store=DimensionMatchingStore(root/"matching.sqlite3",qualifications)
  try:yield ing,events,exposures,bindings,transmissions,qualifications,store,evidence,registry,event,exposure,binding,transmission,qualification,root
  finally:store.close();qualifications.close();transmissions.close();bindings.close();exposures.close()
def qinput(evidence,value="USD",entity="CUR_USD",dtype="CURRENCY",name="event"):return {"dimension_type":dtype,"event_dimension_value":value,"dimension_entity_id":entity,"evidence_ids":[evidence[name]["evidence_id"]]}
@check("BASELINE","frozen Stage 6.3D exact ancestor")
def _():require(git("rev-parse",f"{BASE}^{{}}")==BASE_COMMIT);subprocess.check_call(["git","merge-base","--is-ancestor",BASE_COMMIT,"HEAD"],cwd=REPO)
@check("CONTRACT","schema store processor policy and authority exact")
def _():require((SCHEMA_VERSION,STORE_SCHEMA_VERSION,PROCESSOR_VERSION,POLICY_ID,AUTHORITY)==("STAGE6_EVENT_EXPOSURE_DIMENSION_MATCH_V1","STAGE6_3E_DIMENSION_MATCH_STORE_V1","STAGE6_3E_DIMENSION_MATCHER_V1","S6DIMMATCHPOL_STAGE6_3E_V1","SHADOW_ONLY"))
@check("POLICY","exact five-rule policy and frozen hash")
def _():p,j,h=load_policy();require(validate_policy(p)==p and p["rules"]==EXPECTED_RULES_V1 and h==EXPECTED_POLICY_HASH_V1==canonical_hash(p))
@check("POLICY","all valid-looking V1 semantic drift rejected")
def _():
 p,_,_=load_policy()
 for change in (lambda q:q["rules"].pop(),lambda q:q["rules"].append(deepcopy(q["rules"][0])),lambda q:q["rules"][1].__setitem__("event_field","geographies"),lambda q:q["rules"][0].__setitem__("dimension_type","COUNTRY"),lambda q:q["rules"][4].__setitem__("event_field","currencies"),lambda q:q["rules"][3].__setitem__("dimension_mode","EXPLICIT_REQUIRED"),lambda q:q["rules"][0].__setitem__("source_rule_id","RENAMED")):
  x=deepcopy(p);change(x);expect(Stage6DimensionMatchingError,lambda x=x:validate_policy(x))
@check("CURRENCY","exact Event and Exposure entity overlap")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,q,root):m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])["match"];require(m["path_matches"][0]["dimension_match_status"]=="EXACT_ENTITY_MATCH" and m["path_matches"][0]["matched_dimension_entity_ids"]==["CUR_USD"] and m["dimension_compatibility_status"]=="ALL_REQUIRED_DIMENSIONS_MATCH")
@check("CURRENCY","fully qualified distinct entities are definitive no-match")
def _():
 with env(exposure_entities=("CUR_EUR",)) as (*_,s,e,r,event,exposure,binding,t,q,root):m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])["match"];require(m["path_matches"][0]["dimension_match_status"]=="NO_ENTITY_MATCH" and m["dimension_compatibility_status"]=="NO_REQUIRED_DIMENSIONS_MATCH")
@check("STATUS","partial Event coverage permits known exact overlap")
def _():
 with env(event_values=("USD","EUR")) as (*_,s,e,r,event,exposure,binding,t,q,root):m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])["match"];require(m["event_dimension_qualification_status"]=="PARTIALLY_QUALIFIED" and m["path_matches"][0]["dimension_match_status"]=="EXACT_ENTITY_MATCH")
@check("STATUS","partial Event coverage without overlap remains indeterminate")
def _():
 with env(event_values=("USD","EUR"),exposure_entities=("CUR_EUR",)) as (*_,s,e,r,event,exposure,binding,t,q,root):m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])["match"];require(m["path_matches"][0]["dimension_match_status"]=="INDETERMINATE" and m["dimension_compatibility_status"]=="INDETERMINATE_DIMENSION_MATCH")
@check("STATUS","missing Event or Exposure qualification remains indeterminate")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,q,root):require(s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[])["match"]["path_matches"][0]["dimension_match_status"]=="INDETERMINATE")
 with env(exposure_entities=()) as (*_,s,e,r,event,exposure,binding,t,q,root):require(s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])["match"]["path_matches"][0]["dimension_match_status"]=="INDETERMINATE")
@check("COMMODITY","exact commodity entity overlap")
def _():
 with env(event_type="OIL_SHOCK",channel="COMMODITY",types=("ENERGY_SENSITIVITY",),event_values=("Crude Oil",),event_field="commodities",exposure_entities=("CMD_CRUDE_OIL",)) as (*_,s,e,r,event,exposure,binding,t,q,root):require(s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e,"Crude Oil","CMD_CRUDE_OIL","COMMODITY")])["match"]["path_matches"][0]["dimension_match_status"]=="EXACT_ENTITY_MATCH")
@check("COUNTRY","geography and trade exact overlap without role inference")
def _():
 for et,ch,typ,value,entity in (("WAR_ESCALATION","GEOGRAPHY","REVENUE_GEOGRAPHY","United States","COUNTRY_US"),("TARIFF_INCREASE","MACRO","IMPORT_DEPENDENCY","China","COUNTRY_CN")):
  with env(event_type=et,channel=ch,types=(typ,),event_values=(value,),event_field="geographies",exposure_entities=(entity,)) as (*_,s,e,r,event,exposure,binding,t,q,root):m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e,value,entity,"COUNTRY")])["match"];require(m["path_matches"][0]["dimension_match_status"]=="EXACT_ENTITY_MATCH" and m["trade_role_semantics_status"]=="NOT_EVALUATED")
@check("RATE","qualifier prohibited and dimension not required only")
def _():
 with env(event_type="RATE_HIKE",channel="RATE",types=("INTEREST_RATE_SENSITIVITY",),event_values=(),event_field="currencies",exposure_entities=()) as (*_,s,e,r,event,exposure,binding,t,q,root):m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[])["match"];require(m["path_matches"][0]["dimension_match_status"]=="NOT_REQUIRED" and m["dimension_compatibility_status"]=="DIMENSION_NOT_REQUIRED_ONLY");expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)]),"NOT_ALLOWED")
@check("NO_PATH","no compatible path produces exact root status and rejects input")
def _():
 with env(event_type="RATE_HIKE",channel="COMMODITY",types=("INTEREST_RATE_SENSITIVITY",),event_values=(),event_field="commodities",exposure_entities=()) as (*_,s,e,r,event,exposure,binding,t,q,root):m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[])["match"];require(m["dimension_compatibility_status"]=="NO_COMPATIBLE_PATHS" and m["path_matches"]==[] and m["event_qualifiers"]==[]);expect(Stage6DimensionMatchingError,lambda:s._resolve(q,t,binding,event,r,s.qualification_store.transmission_store.binding_store.event_store.ingestion_store,[qinput(e)]))
@check("VALIDATION","raw value type entity and future entity fail closed")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,q,root):
  expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e,"US Dollar")]),"VALUE_NOT_PRESENT");expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e,dtype="COUNTRY")]),"TYPE_POLICY");expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e,entity="COUNTRY_US")]),"ENTITY_TYPE");expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e,entity="CUR_FUTURE")]),"RESOLUTION");expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e,entity="MISSING")]),"RESOLUTION")
@check("EVIDENCE","Event subset and entity support are mandatory")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,q,root):expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e,name="other")]),"NOT_EVENT_SUBSET")
 with env(event_evidence_dims=[]) as (*_,s,e,r,event,exposure,binding,t,q,root):expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)]),"SUPPORT_MISSING")
@check("EVIDENCE","official and independent accepted; discovery and unverified rejected")
def _():
 for authority in ("PRIMARY_OFFICIAL","AUTHORITATIVE_INDEPENDENT"):
  with env(event_authority=authority) as (*_,s,e,r,event,exposure,binding,t,q,root):s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])
 for authority in ("DISCOVERY","UNVERIFIED"):
  with env(event_authority=authority) as (*_,s,e,r,event,exposure,binding,t,q,root):expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)]),"AUTHORITY")
@check("MULTIPLE","multiple Event values and entities are fully qualified canonically")
def _():
 with env(event_values=("USD","EUR"),exposure_entities=("CUR_USD",)) as (*_,s,e,r,event,exposure,binding,t,q,root):inputs=[qinput(e,"USD","CUR_USD"),qinput(e,"EUR","CUR_EUR")];m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=list(reversed(inputs)))["match"];require(m["event_dimension_qualification_status"]=="ALL_QUALIFIED" and m["qualified_event_dimension_values"]==["EUR","USD"] and [x["dimension_entity_id"] for x in m["event_qualifiers"]]==["CUR_EUR","CUR_USD"])
@check("DUPLICATE","duplicate raw values and stable entities rejected")
def _():
 with env(event_values=("USD","EUR")) as (*_,s,e,r,event,exposure,binding,t,q,root):a=qinput(e);expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[a,a]),"DUPLICATE_EVENT_DIMENSION_VALUE");expect(Stage6DimensionMatchingError,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[a,qinput(e,"EUR","CUR_USD")]),"DUPLICATE_EVENT_DIMENSION_ENTITY")
@check("AGGREGATE","all partial and no required-path aggregates replay exactly")
def _():
 with env(types=("CURRENCY","CURRENCY"),exposure_entities=("CUR_USD","CUR_EUR")) as (*_,s,e,r,event,exposure,binding,t,q,root):m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])["match"];require(m["dimension_compatibility_status"]=="PARTIAL_REQUIRED_DIMENSIONS_MATCH")
 with env(types=("CURRENCY","CURRENCY"),exposure_entities=("CUR_USD","CUR_USD")) as (*_,s,e,r,event,exposure,binding,t,q,root):require(s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])["match"]["dimension_compatibility_status"]=="ALL_REQUIRED_DIMENSIONS_MATCH")
 with env(types=("CURRENCY","CURRENCY"),exposure_entities=("CUR_EUR","CUR_EUR")) as (*_,s,e,r,event,exposure,binding,t,q,root):require(s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])["match"]["dimension_compatibility_status"]=="NO_REQUIRED_DIMENSIONS_MATCH")
@check("IDENTITY","canonical order idempotency and distinct-input conflict")
def _():
 with env(event_values=("USD","EUR")) as (*_,s,e,r,event,exposure,binding,t,q,root):inputs=[qinput(e),qinput(e,"EUR","CUR_EUR")];first=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=inputs);require(s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=list(reversed(inputs)))["status"]=="IDEMPOTENT_SUCCESS");expect(DimensionMatchingConflict,lambda:s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)]))
@check("DEPENDENCY","exact Stage-qualified dependency set and hashes")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,q,root):m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])["match"];types={x[0] for x in s.connection.execute("SELECT record_type FROM dimension_match_dependencies WHERE match_id=?",(m["match_id"],))};require(types=={"STAGE6_3D_DIMENSION_QUALIFICATION","STAGE6_3C_TRANSMISSION","STAGE6_3B_EVENT_EXPOSURE_BINDING","STAGE6_EVENT","EVENT_ENTITY_REGISTRY_SNAPSHOT","DIMENSION_MATCHING_POLICY","EVIDENCE"} and s.integrity_check()["result"]=="PASS")
@check("DEPENDENCY","generic dependency type tamper fails integrity")
def _():
 for source,replacement in (("STAGE6_3D_DIMENSION_QUALIFICATION","DIMENSION_QUALIFICATION"),("STAGE6_3C_TRANSMISSION","TRANSMISSION"),("STAGE6_3B_EVENT_EXPOSURE_BINDING","EVENT_EXPOSURE_BINDING"),("STAGE6_EVENT","EVENT")):
  with env() as (*_,s,e,r,event,exposure,binding,t,q,root):s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)]);s.connection.execute("DROP TRIGGER protect_dimension_match_dependencies_update");s.connection.execute("UPDATE dimension_match_dependencies SET record_type=? WHERE record_type=?",(replacement,source));s.connection.execute("CREATE TRIGGER protect_dimension_match_dependencies_update BEFORE UPDATE ON dimension_match_dependencies BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END");s.connection.commit();expect(DimensionMatchingIntegrityFailure,s.integrity_check,"DEPENDENCY")
@check("CARDINALITY","metadata constraint and policy singleton fail closed")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,q,root):expect(sqlite3.IntegrityError,lambda:s.connection.execute("INSERT INTO dimension_match_store_meta VALUES(2,?,?,?,?,?)",(STORE_SCHEMA_VERSION,BASE_COMMIT,SCHEMA_VERSION,PROCESSOR_VERSION,AUTHORITY)));s.connection.execute("INSERT INTO dimension_match_policies VALUES(?,?,?)",("FAKE","f"*64,"{}"));s.connection.commit();expect(DimensionMatchingIntegrityFailure,s.integrity_check,"POLICY")
@check("APPEND_ONLY","all tables immutable and trigger loss detected")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,q,root):
  s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])
  for table in ("dimension_match_store_meta","dimension_match_policies","dimension_match_records","event_dimension_qualifiers","event_dimension_qualifier_evidence","dimension_path_matches","dimension_match_dependencies"):expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"UPDATE {table} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"DELETE FROM {table}"))
  s.connection.execute("DROP TRIGGER protect_dimension_match_records_delete");s.connection.commit();expect(DimensionMatchingIntegrityFailure,s.integrity_check,"TRIGGER")
@check("RESTART","closed store reopens and deterministic integrity passes")
def _():
 with env() as (ing,events,exposures,bindings,transmissions,qualifications,s,e,r,event,exposure,binding,t,q,root):s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)]);s.close();reopened=DimensionMatchingStore(root/"matching.sqlite3",qualifications);require(reopened.integrity_check()["result"]=="PASS");reopened.close()
@check("TAMPER","root qualifier evidence path policy and dependency tamper fail")
def _():
 for table,column,value in (("dimension_match_records","record_hash","f"*64),("event_dimension_qualifiers","dimension_entity_id","CUR_EUR"),("event_dimension_qualifier_evidence","evidence_hash","f"*64),("dimension_path_matches","dimension_match_status","NO_ENTITY_MATCH"),("dimension_match_policies","policy_hash","f"*64),("dimension_match_dependencies","record_hash","f"*64)):
  with env() as (*_,s,e,r,event,exposure,binding,t,q,root):s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)]);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.commit();expect(Exception,s.integrity_check)
@check("BOUNDARY","no frozen changes text inference direction magnitude AI or trading")
def _():
 require(git("diff","--name-only",BASE,"--","Stage 5D","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/stage6_lifecycle","Stage 6/stage6_exposure","Stage 6/stage6_exposure_binding","Stage 6/stage6_transmission","Stage 6/stage6_dimension_qualification","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/scripts/validate_stage6_0.py")=="")
 prohibited={"socket","requests","urllib","http","aiohttp","openai","transformers","re"};text=""
 for p in (ROOT/"stage6_dimension_matching").glob("*.py"):
  src=p.read_text();text+=src.casefold();tree=ast.parse(src);imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports&prohibited)
 for token in ("aliases","canonical_name","raw_payload","semantic similarity","embedding","ocr","expected_return","beneficiary","loser","buy","sell","broker","portfolio mutation"):require(token not in text)
@check("NETWORK_AI_TRADING","socket sentinel and all safety statuses exact")
def _():
 with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):
  with env() as (*_,s,e,r,event,exposure,binding,t,q,root):m=s.match_qualification(qualification_id=q["qualification_id"],event_qualifier_inputs=[qinput(e)])["match"];require(all(m[k]=="NOT_EVALUATED" for k in ("semantic_compatibility_status","trade_role_semantics_status","directional_effect_status","magnitude_status","causal_effect_status")))
def main():
 rows=[]
 for i,(c,n,f) in enumerate(CHECKS,1):
  try:
   with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):f()
   rows.append({"test_id":f"S6_3E_{i:03d}","category":c,"test_name":n,"result":"PASS","detail":""})
  except Exception as x:rows.append({"test_id":f"S6_3E_{i:03d}","category":c,"test_name":n,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 OUT.parent.mkdir(exist_ok=True);h=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows);h.close();bad=[x for x in rows if x["result"]=="FAIL"];print(json.dumps({"stage":"6.3E","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",x) for x in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
