"""Stage 6.3D evidence-backed exposure-dimension qualification acceptance tests."""
from __future__ import annotations
import ast,csv,importlib.util,json,socket,sqlite3,subprocess,sys,tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location("s62a",Path(__file__).with_name("run_stage6_2a_tests.py"));base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
from stage6_dimension_qualification import *
from stage6_exposure import ExposureStore
from stage6_exposure_binding import BindingStore,assertion_hash
from stage6_ingestion.canonical import canonical_hash,without
from stage6_ingestion.registry import build_entity_registry
from stage6_transmission import TransmissionStore

OUT=ROOT/"results"/"stage6_3d_test_results.csv";FIXTURE=ROOT/"fixtures"/"stage6_3d";BASE="stage6-3c-deterministic-transmission-semantics-baseline";COMMIT="1f98a158d3d47f14d0ec50e298d8e5fcc6314ab7";ASOF="2026-09-27T10:30:00.000000Z";CUTOFF="2026-09-27T10:00:00.000000Z";CHECKS=[]
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
def assertion(eid,kind,index=0):
 return {"exposure_type":kind,"value_type":"QUALITATIVE","measurement":None,"qualitative_value":"HIGH" if index else "MEDIUM","evidence_ids":[eid],"confidence":0.0,"effective_date":"2026-01-01","review_or_expiry_date":"2026-12-31"}

@contextmanager
def env(*,event_type="CURRENCY_SHOCK",channel="CURRENCY",types=("CURRENCY",),evidence_dimensions=None):
 with base.fresh_environment() as (ing,events,old_evidence,registries,root):
  records=deepcopy(registries["entity_v2"]["entities"])+json.loads((FIXTURE/"dimension_entities.json").read_text())
  registry=build_entity_registry(records,"2026-09-25T12:00:00Z",registries["entity_v2"]);ing.import_registry(registry)
  source_snapshot=ing.connection.execute("SELECT snapshot_id FROM registry_snapshots WHERE registry_kind='SOURCE'").fetchone()[0];source_id=old_evidence["official1"]["source_id"]
  evidence={}
  for name,dims in (evidence_dimensions or json.loads((FIXTURE/"evidence_entity_bindings.json").read_text())).items():
   evidence[name]=ing.capture_evidence(idempotency_key="s63d-"+name,source_registry_snapshot_id=source_snapshot,entity_registry_snapshot_id=registry["registry_snapshot_id"],source_id=source_id,source_reference="fixture://s63d/"+name,raw_payload=("dimension "+name).encode(),content_type="text/plain",publication_timestamp_utc="2026-09-27T09:00:00Z",observed_timestamp_utc="2026-09-27T09:01:00Z",retrieved_timestamp_utc="2026-09-27T09:02:00Z",entity_ids=sorted([base.ENTITY,*dims]))["record"]
  event=base.append(events,evidence,["e1"],status="CANDIDATE",event_type=event_type,entity_registry=registry["registry_snapshot_id"],updated="2026-09-27T10:00:00.000000Z")["event"]
  exposures=ExposureStore(root/"exposure.sqlite3",ing);items=[assertion(evidence["e1"]["evidence_id"],t,i) for i,t in enumerate(types)];exposure=exposures.append_exposure(company_entity_id=base.ENTITY,exposure_version=1,previous_version_hash=None,as_of_timestamp=ASOF,data_cutoff_timestamp=CUTOFF,entity_registry_snapshot_id=registry["registry_snapshot_id"],input_evidence_ids=[evidence["e1"]["evidence_id"]],assertions=items,relationships=[])["exposure"]
  bindings=BindingStore(root/"binding.sqlite3",events,exposures);binding=bindings.append_binding(event_id=event["event_id"],event_version=1,exposure_id=exposure["exposure_id"],exposure_version=1,selected_assertion_hashes=[assertion_hash(a) for a in exposure["assertions"]],binding_channel=channel,binding_cutoff_timestamp=ASOF)["binding"]
  transmissions=TransmissionStore(root/"transmission.sqlite3",bindings);transmission=transmissions.evaluate_binding(binding_id=binding["binding_id"])["transmission"];store=DimensionQualificationStore(root/"dimension.sqlite3",transmissions)
  try:yield ing,events,exposures,bindings,transmissions,store,evidence,registry,event,exposure,binding,transmission,root
  finally:store.close();transmissions.close();bindings.close();exposures.close()
def input_for(transmission,evidence,dimension_type="CURRENCY",dimension_id="CUR_USD",index=0,evidence_name="e1"):
 p=transmission["transmission_paths"][index];return {"assertion_hash":p["assertion_hash"],"dimension_type":dimension_type,"dimension_entity_id":dimension_id,"evidence_ids":[evidence[evidence_name]["evidence_id"]]}

@check("BASELINE","frozen Stage 6.3C exact ancestor")
def _():require(git("rev-parse",f"{BASE}^{{}}")==COMMIT);subprocess.check_call(["git","merge-base","--is-ancestor",COMMIT,"HEAD"],cwd=REPO)
@check("CONTRACT","schema store processor policy and authority exact")
def _():require((SCHEMA_VERSION,STORE_SCHEMA_VERSION,PROCESSOR_VERSION,POLICY_ID,AUTHORITY)==("STAGE6_EXPOSURE_DIMENSION_QUALIFICATION_V1","STAGE6_3D_DIMENSION_QUALIFICATION_STORE_V1","STAGE6_3D_DIMENSION_QUALIFIER_V1","S6DIMPOL_STAGE6_3D_V1","SHADOW_ONLY"))
@check("POLICY","exact five-rule policy and immutable canonical hash")
def _():p,j,h=load_policy();require(validate_policy(p)==p and h==EXPECTED_POLICY_HASH_V1==canonical_hash(p) and p["rules"]==EXPECTED_RULES_V1)
@check("POLICY","identity rules and dimensions fail closed on drift")
def _():
 p,_,_=load_policy()
 for change in (lambda q:q.__setitem__("authority","LIVE"),lambda q:q["rules"].pop(),lambda q:q["rules"][0].__setitem__("dimension_type","COUNTRY"),lambda q:q["supported_dimension_types"].append("SECTOR")):
  q=deepcopy(p);change(q);expect(Stage6DimensionError,lambda q=q:validate_policy(q))
@check("CURRENCY","explicit supported entity and evidence qualifies currency path")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,root):x=s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e)])["qualification"];require(x["path_qualification_status"]=="ALL_REQUIRED_PATHS_QUALIFIED" and x["qualifiers"][0]["dimension_entity_type"]=="CURRENCY")
@check("COMMODITY","commodity policy requires commodity entity")
def _():
 with env(event_type="OIL_SHOCK",channel="COMMODITY",types=("ENERGY_SENSITIVITY",)) as (*_,s,e,r,event,exposure,binding,t,root):x=s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e,"COMMODITY","CMD_CRUDE_OIL")])["qualification"];require(x["path_qualification_status"]=="ALL_REQUIRED_PATHS_QUALIFIED")
@check("COUNTRY","geography and trade policies require country entity")
def _():
 for et,ch,typ in (("WAR_ESCALATION","GEOGRAPHY","REVENUE_GEOGRAPHY"),("TARIFF_INCREASE","MACRO","IMPORT_DEPENDENCY")):
  with env(event_type=et,channel=ch,types=(typ,)) as (*_,s,e,r,event,exposure,binding,t,root):require(s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e,"COUNTRY","COUNTRY_US")])["qualification"]["path_qualification_status"]=="ALL_REQUIRED_PATHS_QUALIFIED")
@check("RATE","rate path needs no qualifier and rejects one")
def _():
 with env(event_type="RATE_HIKE",channel="RATE",types=("INTEREST_RATE_SENSITIVITY",)) as (*_,s,e,r,event,exposure,binding,t,root):require(s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[])["qualification"]["path_qualification_status"]=="ALL_REQUIRED_PATHS_QUALIFIED");expect(Stage6DimensionError,lambda:s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e)]),"NOT_ALLOWED")
@check("NO_PATH","unsupported event-channel permits only empty qualification")
def _():
 with env(event_type="RATE_HIKE",channel="COMMODITY",types=("INTEREST_RATE_SENSITIVITY",)) as (*_,s,e,r,event,exposure,binding,t,root):require(s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[])["qualification"]["path_qualification_status"]=="NO_COMPATIBLE_PATHS");expect(Stage6DimensionError,lambda:s._resolve(t,binding,exposure,[{"assertion_hash":"f"*64,"dimension_type":"CURRENCY","dimension_entity_id":"CUR_USD","evidence_ids":[e["e1"]["evidence_id"]]}]))
@check("ENTITY","wrong missing and future-ineligible dimension entities reject")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,root):
  expect(Stage6DimensionError,lambda:s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e,"COUNTRY","COUNTRY_US")]),"POLICY_MISMATCH");expect(Stage6DimensionError,lambda:s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e,"CURRENCY","COUNTRY_US")]),"TYPE_MISMATCH");expect(Stage6DimensionError,lambda:s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e,"CURRENCY","CUR_FUTURE")]),"RESOLUTION");expect(Stage6DimensionError,lambda:s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e,"CURRENCY","MISSING")]),"RESOLUTION")
@check("EVIDENCE","qualifier evidence must be assertion evidence subset")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,root):expect(Stage6DimensionError,lambda:s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e,evidence_name="e2")]),"SUBSET")
@check("EVIDENCE","every qualifier evidence record must explicitly name dimension")
def _():
 with env(evidence_dimensions={"e1":[],"e2":[]}) as (*_,s,e,r,event,exposure,binding,t,root):expect(Stage6DimensionError,lambda:s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e)]),"SUPPORT_MISSING")
@check("MULTI_DIMENSION","one path accepts multiple independently evidenced dimensions")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,root):inputs=[input_for(t,e,"CURRENCY","CUR_USD"),input_for(t,e,"CURRENCY","CUR_EUR")];x=s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=list(reversed(inputs)))["qualification"];require([q["dimension_entity_id"] for q in x["qualifiers"]]==["CUR_EUR","CUR_USD"] and x["path_qualification_status"]=="ALL_REQUIRED_PATHS_QUALIFIED")
@check("STATUS","zero partial and all required path statuses exact")
def _():
 with env(types=("CURRENCY","CURRENCY")) as (*_,s,e,r,event,exposure,binding,t,root):
  require(build_qualification(transmission=t,binding=binding,exposure=exposure,qualifier_items=[],policy=s.policy,policy_hash=s.policy_hash)["path_qualification_status"]=="UNQUALIFIED");one=input_for(t,e,index=0);partial=build_qualification(transmission=t,binding=binding,exposure=exposure,qualifier_items=s._resolve(t,binding,exposure,[one])[0],policy=s.policy,policy_hash=s.policy_hash);require(partial["path_qualification_status"]=="PARTIALLY_QUALIFIED");inputs=[input_for(t,e,index=i,dimension_id="CUR_USD" if i==0 else "CUR_EUR") for i in range(2)];require(s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=inputs)["qualification"]["path_qualification_status"]=="ALL_REQUIRED_PATHS_QUALIFIED")
@check("CANONICAL","caller order is canonical and duplicate qualifier rejected")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,root):
  a=input_for(t,e,"CURRENCY","CUR_USD");b=input_for(t,e,"CURRENCY","CUR_EUR");x=s._resolve(t,binding,exposure,[a,b])[0];y=s._resolve(t,binding,exposure,[b,a])[0];require(build_qualification(transmission=t,binding=binding,exposure=exposure,qualifier_items=x,policy=s.policy,policy_hash=s.policy_hash)==build_qualification(transmission=t,binding=binding,exposure=exposure,qualifier_items=y,policy=s.policy,policy_hash=s.policy_hash));expect(Stage6DimensionError,lambda:s._resolve(t,binding,exposure,[a,a]),"DUPLICATE")
@check("IDEMPOTENCY","exact replay succeeds and distinct set conflicts")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,root):a=input_for(t,e);s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[a]);require(s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[a])["status"]=="IDEMPOTENT_SUCCESS");expect(DimensionConflict,lambda:s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e,dimension_id="CUR_EUR")]))
@check("DEPENDENCY","exact complete upstream evidence registry and policy dependencies")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,root):x=s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e)])["qualification"];types={z[0] for z in s.connection.execute("SELECT record_type FROM dimension_dependencies WHERE qualification_id=?",(x["qualification_id"],))};require(types=={"TRANSMISSION","EVENT_EXPOSURE_BINDING","STAGE6_EXPOSURE","ENTITY_REGISTRY_SNAPSHOT","DIMENSION_QUALIFICATION_POLICY","EVIDENCE"} and s.integrity_check()["result"]=="PASS")
@check("APPEND_ONLY","all tables protected and trigger loss detected")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,root):
  s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e)])
  for table in ("dimension_store_meta","dimension_policies","dimension_records","dimension_qualifiers","dimension_qualifier_evidence","dimension_dependencies"):expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"UPDATE {table} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"DELETE FROM {table}"))
  s.connection.execute("DROP TRIGGER protect_dimension_records_delete");s.connection.commit();expect(DimensionIntegrityFailure,s.integrity_check,"TRIGGER")
@check("TAMPER","root qualifier evidence and dependency tamper fail integrity")
def _():
 for table,column,value in (("dimension_records","record_hash","f"*64),("dimension_qualifiers","dimension_type","COUNTRY"),("dimension_qualifier_evidence","evidence_hash","f"*64),("dimension_dependencies","record_hash","f"*64)):
  with env() as (*_,s,e,r,event,exposure,binding,t,root):s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e)]);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.commit();expect(Exception,s.integrity_check)
@check("UPSTREAM_TAMPER","transmission binding exposure and policy tamper fail closed")
def _():
 for target in ("transmission","binding","exposure","policy"):
  with env() as (ing,events,exposures,bindings,transmissions,s,e,r,event,exposure,binding,t,root):
   s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e)])
   if target=="transmission":transmissions.connection.execute("DROP TRIGGER protect_transmission_records_update");transmissions.connection.execute("UPDATE transmission_records SET record_hash=?",("f"*64,));transmissions.connection.commit()
   elif target=="binding":bindings.connection.execute("DROP TRIGGER protect_binding_records_update");bindings.connection.execute("UPDATE binding_records SET record_hash=?",("f"*64,));bindings.connection.commit()
   elif target=="exposure":exposures.connection.execute("DROP TRIGGER protect_exposure_records_update");exposures.connection.execute("UPDATE exposure_records SET record_hash=?",("f"*64,));exposures.connection.commit()
   else:s.connection.execute("DROP TRIGGER protect_dimension_policies_update");s.connection.execute("UPDATE dimension_policies SET policy_hash=?",("f"*64,));s.connection.commit()
   expect(Exception,s.integrity_check)
@check("SAFETY","all evaluation and influence fields remain NOT_EVALUATED or absent")
def _():
 with env() as (*_,s,e,r,event,exposure,binding,t,root):x=s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e)])["qualification"];require(all(x[k]=="NOT_EVALUATED" for k in ("semantic_compatibility_status","directional_effect_status","magnitude_status","causal_effect_status")) and "trade_action" not in x and "ml_score" not in x)
@check("BOUNDARY","frozen code unchanged and no network AI ML NLP trading implementation")
def _():
 require(git("diff","--name-only",BASE,"--","Stage 5D","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/stage6_lifecycle","Stage 6/stage6_exposure","Stage 6/stage6_exposure_binding","Stage 6/stage6_transmission","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/scripts/validate_stage6_0.py")=="")
 prohibited={"socket","requests","urllib","http","aiohttp","openai","transformers"};text=""
 for p in (ROOT/"stage6_dimension_qualification").glob("*.py"):
  src=p.read_text();text+=src.casefold();tree=ast.parse(src);imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports&prohibited)
 for token in ("semantic similarity","embedding","ocr","expected_return","stock_direction","broker","portfolio mutation","raw_payload","canonical_name","aliases",'["currencies"]','["commodities"]','["geographies"]'):require(token not in text)
@check("ZERO_NETWORK","socket sentinel covers full qualification chain")
def _():
 with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):
  with env() as (*_,s,e,r,event,exposure,binding,t,root):s.qualify_transmission(transmission_id=t["transmission_id"],qualifier_inputs=[input_for(t,e)])

def main():
 rows=[]
 for i,(c,n,f) in enumerate(CHECKS,1):
  try:
   with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):f()
   rows.append({"test_id":f"S6_3D_{i:03d}","category":c,"test_name":n,"result":"PASS","detail":""})
  except Exception as x:rows.append({"test_id":f"S6_3D_{i:03d}","category":c,"test_name":n,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 OUT.parent.mkdir(exist_ok=True);h=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows);h.close();bad=[r for r in rows if r["result"]=="FAIL"];print(json.dumps({"stage":"6.3D","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",r) for r in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
