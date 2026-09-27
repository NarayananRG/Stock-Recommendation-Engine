"""Stage 6.3B explicit Event-to-Exposure binding acceptance tests."""
from __future__ import annotations
import ast,csv,importlib.util,json,socket,sqlite3,subprocess,sys,tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
STAGE_ROOT=Path(__file__).resolve().parents[1];REPO_ROOT=STAGE_ROOT.parent;sys.path.insert(0,str(STAGE_ROOT))
spec=importlib.util.spec_from_file_location("s62a",Path(__file__).with_name("run_stage6_2a_tests.py"));base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
from stage6_exposure import ExposureStore
from stage6_exposure_binding import *
from stage6_ingestion.canonical import canonical_hash,canonical_json,without

RESULT_PATH=STAGE_ROOT/"results"/"stage6_3b_test_results.csv";BASE_TAG="stage6-3a-pit-exposure-record-foundation-baseline";BASE_COMMIT="a71b6ef8ab3fa0a99bf34635774fcdb4fae526ab";ASOF="2026-05-01T10:30:00.000000Z";CUTOFF="2026-05-01T10:00:00.000000Z";BIND="2026-05-01T10:30:00.000000Z";CHECKS=[]
def check(c,n):
 def reg(f):CHECKS.append((c,n,f));return f
 return reg
def require(v,m="assertion failed"):
 if not v:raise AssertionError(m)
def expect(e,f,s=None):
 try:f()
 except e as x:
  if s:require(s in str(x),f"{s!r} not in {x!r}")
  return
 raise AssertionError("expected "+e.__name__)
def git(*a):return subprocess.check_output(["git",*a],cwd=REPO_ROOT,text=True).strip()
def assertion(eid,kind="INTEREST_RATE_SENSITIVITY",qual=True):return {"exposure_type":kind,"value_type":"QUALITATIVE" if qual else "QUANTITATIVE","measurement":None if qual else {"value":20.0,"unit":"PERCENT_COST","basis":"Synthetic FY2025 cost","declared_unit":None},"qualitative_value":"MEDIUM" if qual else None,"evidence_ids":[eid],"confidence":0.0,"effective_date":"2026-01-01","review_or_expiry_date":"2026-12-31"}

@contextmanager
def env(duplicate=False):
 with base.fresh_environment() as (ing,events,evidence,registries,root):
  ev=base.append(events,evidence,["official1"],status="CANDIDATE")["event"]
  exposures=ExposureStore(root/"exposure.sqlite3",ing);eid=evidence["official1"]["evidence_id"];items=[assertion(eid),assertion(eid,"COMMODITY",False)];
  if duplicate:items=[items[0],deepcopy(items[0])]
  ex=exposures.append_exposure(company_entity_id=base.ENTITY,exposure_version=1,previous_version_hash=None,as_of_timestamp=ASOF,data_cutoff_timestamp=CUTOFF,entity_registry_snapshot_id=registries["entity_v1"]["registry_snapshot_id"],input_evidence_ids=[eid],assertions=items,relationships=[])["exposure"]
  store=BindingStore(root/"binding.sqlite3",events,exposures)
  try:yield ing,events,exposures,evidence,registries,store,ev,ex,root
  finally:store.close();exposures.close()
def append(store,event,exposure,hashes=None,**kw):
 args=dict(event_id=event["event_id"],event_version=event["event_version"],exposure_id=exposure["exposure_id"],exposure_version=exposure["exposure_version"],selected_assertion_hashes=[assertion_hash(exposure["assertions"][0])] if hashes is None else hashes,binding_channel="RATE",binding_cutoff_timestamp=BIND);args.update(kw);return store.append_binding(**args)

@check("BASELINE","6.3A frozen exact ancestor and constants")
def _():require(git("rev-parse",f"{BASE_TAG}^{{}}")==BASE_COMMIT);subprocess.check_call(["git","merge-base","--is-ancestor",BASE_COMMIT,"HEAD"],cwd=REPO_ROOT);require(AUTHORITY=="SHADOW_ONLY" and BINDING_SCHEMA_VERSION=="STAGE6_EVENT_EXPOSURE_BINDING_V1" and STORE_SCHEMA_VERSION=="STAGE6_3B_EVENT_EXPOSURE_BINDING_STORE_V1")
@check("POLICY","policy exact identity hash and enums")
def _():p,j,h=load_policy();require(validate_policy(p)==p and canonical_hash(p)==h and p["supported_event_statuses"]==["CANDIDATE"] and p["supported_binding_channels"]==CHANNELS)
@check("POLICY","policy identity mutation rejected")
def _():
 p,_,_=load_policy()
 for field,value in (("policy_id","X"),("policy_version",2),("processor_version","X"),("authority","LIVE")):
  q=deepcopy(p);q[field]=value;expect(Stage6BindingError,lambda q=q:validate_policy(q),"POLICY")
@check("EVENT","exact candidate Event V1 accepted")
def _():
 with env() as (*_,s,e,x,root):require(append(s,e,x)["binding"]["event_version"]==1)
@check("EVENT","missing exact event and automatic latest prohibited")
def _():
 with env() as (ing,events,exposures,evidence,regs,s,e,x,root):expect(Stage6BindingError,lambda:s.append_binding(event_id=e["event_id"],event_version=2,exposure_id=x["exposure_id"],exposure_version=1,selected_assertion_hashes=[assertion_hash(x["assertions"][0])],binding_channel="RATE",binding_cutoff_timestamp=BIND),"EXACT_EVENT")
@check("EVENT","exact Event V1 V2 and V3 produce distinct bindings")
def _():
 with env() as (ing,events,exposures,evidence,regs,s,e,x,root):
  v2=base.append(events,evidence,["official1"],status="CANDIDATE",event_version=2,previous=e["record_hash"],updated="2026-05-01T10:05:00.000000Z")["event"]
  v3=base.append(events,evidence,["official1"],status="CANDIDATE",event_version=3,previous=v2["record_hash"],updated="2026-05-01T10:10:00.000000Z")["event"]
  ids={append(s,event,x)["binding"]["binding_id"] for event in (e,v2,v3)};require(len(ids)==3)
@check("EVENT","non-candidate statuses rejected by pure contract")
def _():
 with env() as (*_,s,e,x,root):
  p,_,h=load_policy();selected=[x["assertions"][0]]
  for status in ("ACTIVE","RESOLVED","CONFLICTED","RETRACTED"):
   bad=deepcopy(e);bad["event_status"]=status;bad["record_hash"]=canonical_hash(without(bad,"record_hash"));record=build_binding(event=bad,exposure=x,selected_assertions=selected,binding_channel="RATE",binding_cutoff_timestamp=BIND,policy=p,policy_hash=h);expect(Stage6BindingError,lambda r=record,b=bad:validate_binding(r,event=b,exposure=x,expected_policy_hash=h),"STATUS")
@check("EXPOSURE","exact Exposure V1 accepted and missing V2 rejected")
def _():
 with env() as (*_,s,e,x,root):append(s,e,x);expect(Stage6BindingError,lambda:s.append_binding(event_id=e["event_id"],event_version=1,exposure_id=x["exposure_id"],exposure_version=2,selected_assertion_hashes=[assertion_hash(x["assertions"][0])],binding_channel="RATE",binding_cutoff_timestamp=BIND),"EXACT_EXPOSURE")
@check("EXPOSURE","Exposure V2 creates distinct binding")
def _():
 with env() as (ing,events,exposures,evidence,regs,s,e,x,root):
  v2=exposures.append_exposure(company_entity_id=x["company_entity_id"],exposure_version=2,previous_version_hash=x["record_hash"],as_of_timestamp="2026-05-01T10:40:00.000000Z",data_cutoff_timestamp="2026-05-01T10:00:00.000000Z",entity_registry_snapshot_id=x["entity_registry_snapshot_id"],input_evidence_ids=x["input_evidence_ids"],assertions=x["assertions"],relationships=[])["exposure"]
  a=append(s,e,x)["binding"];b=append(s,e,v2,binding_cutoff_timestamp="2026-05-01T10:40:00.000000Z")["binding"];require(a["binding_id"]!=b["binding_id"] and b["exposure_version"]==2)
@check("ASSERTION","one and multiple explicit assertions bind exact refs and evidence")
def _():
 with env() as (*_,s,e,x,root):
  hashes=[assertion_hash(a) for a in x["assertions"]];one=append(s,e,x,[hashes[0]])["binding"];many=append(s,e,x,list(reversed(hashes)),binding_channel="COMMODITY")["binding"];require(len(one["selected_assertions"])==1 and len(many["selected_assertions"])==2 and many["supporting_evidence_ids"]==x["input_evidence_ids"])
@check("ASSERTION","empty duplicate unknown and ambiguous selections rejected")
def _():
 with env() as (*_,s,e,x,root):
  h=assertion_hash(x["assertions"][0]);expect(Stage6BindingError,lambda:append(s,e,x,[]));expect(Stage6BindingError,lambda:append(s,e,x,[h,h]));expect(Stage6BindingError,lambda:append(s,e,x,["f"*64]),"NOT_FOUND")
 with env(True) as (*_,s,e,x,root):expect(Stage6BindingError,lambda:append(s,e,x,[assertion_hash(x["assertions"][0])]),"AMBIGUOUS")
@check("ASSERTION","canonical assertion order independent of caller")
def _():
 with env() as (*_,s,e,x,root):
  p,_,h=load_policy();a=list(x["assertions"]);r1=build_binding(event=e,exposure=x,selected_assertions=a,binding_channel="RATE",binding_cutoff_timestamp=BIND,policy=p,policy_hash=h);r2=build_binding(event=e,exposure=x,selected_assertions=list(reversed(a)),binding_channel="RATE",binding_cutoff_timestamp=BIND,policy=p,policy_hash=h);require(r1==r2)
@check("CHANNEL","all seven explicit channels accepted unknown rejected")
def _():
 for channel in CHANNELS:
  with env() as (*_,s,e,x,root):require(append(s,e,x,binding_channel=channel)["binding"]["binding_channel"]==channel)
 with env() as (*_,s,e,x,root):expect(Stage6BindingError,lambda:append(s,e,x,binding_channel="AUTO"),"CHANNEL")
@check("PIT","event exposure future states rejected and equality accepted")
def _():
 with env() as (*_,s,e,x,root):
  require(append(s,e,x,binding_cutoff_timestamp=ASOF)["binding"])
 with env() as (*_,s,e,x,root):expect(Stage6BindingError,lambda:append(s,e,x,binding_cutoff_timestamp="2026-05-01T09:59:59.000000Z"),"FUTURE")
@check("PIT","assertion expiry boundary accepted stale and premature rejected")
def _():
 with env() as (*_,s,e,x,root):
  x["assertions"][0]["review_or_expiry_date"]="2026-05-01";x["assertions"][0]["effective_date"]="2026-05-01";p,_,h=load_policy();r=build_binding(event=e,exposure=x,selected_assertions=[x["assertions"][0]],binding_channel="RATE",binding_cutoff_timestamp=BIND,policy=p,policy_hash=h);validate_binding(r,event=e,exposure=x,expected_policy_hash=h)
  for start,end in (("2026-05-02","2026-12-31"),("2025-01-01","2026-04-30")):
   y=deepcopy(x);y["assertions"][0]["effective_date"],y["assertions"][0]["review_or_expiry_date"]=start,end;y["assertions"][0]["evidence_ids"]=x["assertions"][0]["evidence_ids"];r=build_binding(event=e,exposure=y,selected_assertions=[y["assertions"][0]],binding_channel="RATE",binding_cutoff_timestamp=BIND,policy=p,policy_hash=h);expect(Stage6BindingError,lambda r=r,y=y:validate_binding(r,event=e,exposure=y,expected_policy_hash=h),"PERIOD")
@check("IDENTITY","same input stable and identity inputs change ID")
def _():
 with env() as (*_,s,e,x,root):
  p,_,h=load_policy();selected=[x["assertions"][0]];base_record=build_binding(event=e,exposure=x,selected_assertions=selected,binding_channel="RATE",binding_cutoff_timestamp=BIND,policy=p,policy_hash=h);require(base_record==build_binding(event=e,exposure=x,selected_assertions=selected,binding_channel="RATE",binding_cutoff_timestamp=BIND,policy=p,policy_hash=h));changed=build_binding(event=e,exposure=x,selected_assertions=selected,binding_channel="MACRO",binding_cutoff_timestamp=BIND,policy=p,policy_hash=h);require(changed["binding_id"]!=base_record["binding_id"])
@check("IDEMPOTENCY","exact replay succeeds without duplicate")
def _():
 with env() as (*_,s,e,x,root):append(s,e,x);require(append(s,e,x)["status"]=="IDEMPOTENT_SUCCESS" and s.connection.execute("SELECT COUNT(*) FROM binding_records").fetchone()[0]==1)
@check("DEPENDENCY","exact event exposure registry policy and evidence set")
def _():
 with env() as (*_,s,e,x,root):append(s,e,x);types=[r[0] for r in s.connection.execute("SELECT dependency_record_type FROM binding_dependencies ORDER BY dependency_record_type")];require(types==["BINDING_POLICY","ENTITY_REGISTRY_SNAPSHOT","EVIDENCE","STAGE6_EVENT","STAGE6_EXPOSURE"])
@check("DEPENDENCY","missing extra wrong hash type and ID fail integrity")
def _():
 sqls=("DELETE FROM binding_dependencies WHERE dependency_record_type='STAGE6_EVENT'","UPDATE binding_dependencies SET dependency_record_hash='"+("f"*64)+"' WHERE dependency_record_type='STAGE6_EXPOSURE'","UPDATE binding_dependencies SET dependency_record_type='WRONG' WHERE dependency_record_type='EVIDENCE'","UPDATE binding_dependencies SET dependency_record_id='WRONG' WHERE dependency_record_type='BINDING_POLICY'","INSERT INTO binding_dependencies SELECT binding_id,'EVIDENCE','EXTRA','"+("f"*64)+"' FROM binding_records")
 for sql in sqls:
  with env() as (*_,s,e,x,root):append(s,e,x);s.connection.execute("DROP TRIGGER protect_binding_dependencies_update");s.connection.execute("DROP TRIGGER protect_binding_dependencies_delete");s.connection.execute(sql);s.connection.commit();expect(BindingIntegrityFailure,s.integrity_check)
@check("POLICY","internally consistent wrong policy hash fails exact policy binding")
def _():
 with env() as (*_,s,e,x,root):
  p,_,h=load_policy();r=build_binding(event=e,exposure=x,selected_assertions=[x["assertions"][0]],binding_channel="RATE",binding_cutoff_timestamp=BIND,policy=p,policy_hash=h);r["policy_hash"]="f"*64;r["binding_id"]=deterministic_binding_id(event=e,exposure=x,selected_assertion_hashes=[r["selected_assertions"][0]["assertion_hash"]],binding_channel="RATE",binding_cutoff_timestamp=BIND,policy_hash=r["policy_hash"],processor_version=PROCESSOR_VERSION,binding_basis=r["binding_basis"]);r["record_hash"]=canonical_hash(without(r,"record_hash"));expect(BindingIntegrityFailure,lambda:validate_binding(r,event=e,exposure=x,expected_policy_hash=h),"POLICY_HASH")
@check("IDENTITY","valid-looking event exposure and assertion hash tampering fails upstream binding")
def _():
 with env() as (*_,s,e,x,root):
  p,_,h=load_policy();original=build_binding(event=e,exposure=x,selected_assertions=[x["assertions"][0]],binding_channel="RATE",binding_cutoff_timestamp=BIND,policy=p,policy_hash=h)
  for field in ("event_hash","exposure_hash"):
   r=deepcopy(original);r[field]="f"*64;r["record_hash"]=canonical_hash(without(r,"record_hash"));expect(BindingIntegrityFailure,lambda r=r:validate_binding(r,event=e,exposure=x,expected_policy_hash=h),"MISMATCH")
  r=deepcopy(original);r["selected_assertions"][0]["assertion_hash"]="f"*64;r["record_hash"]=canonical_hash(without(r,"record_hash"));expect(Stage6BindingError,lambda:validate_binding(r,event=e,exposure=x,expected_policy_hash=h),"NOT_FOUND")
@check("APPEND_ONLY","all tables block update delete and missing trigger detected")
def _():
 with env() as (*_,s,e,x,root):
  append(s,e,x)
  for table in ("binding_store_meta","binding_policies","binding_records","binding_assertions","binding_dependencies"):expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"UPDATE {table} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"DELETE FROM {table}"))
  s.connection.execute("DROP TRIGGER protect_binding_records_delete");s.connection.commit();expect(BindingIntegrityFailure,s.integrity_check,"TRIGGER")
@check("RESTART","clean integrity selected assertion and typed tamper")
def _():
 with env() as (*_,s,e,x,root):append(s,e,x);require(s.integrity_check()["result"]=="PASS")
 for table,column,value in (("binding_assertions","exposure_type","TAMPER"),("binding_records","record_hash","f"*64),("binding_records","canonical_json","{}")):
  with env() as (*_,s,e,x,root):append(s,e,x);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.commit();expect(BindingIntegrityFailure,s.integrity_check)
@check("RESTART","metadata policy and upstream tamper detected")
def _():
 for target in ("meta","policy","event","exposure"):
  with env() as (ing,events,exposures,evidence,regs,s,e,x,root):
   append(s,e,x)
   if target=="meta":s.connection.execute("DROP TRIGGER protect_binding_store_meta_update");s.connection.execute("UPDATE binding_store_meta SET authority='LIVE'")
   elif target=="policy":s.connection.execute("DROP TRIGGER protect_binding_policies_update");s.connection.execute("UPDATE binding_policies SET policy_hash=?",("f"*64,))
   elif target=="event":events.connection.execute("DROP TRIGGER protect_event_records_update");events.connection.execute("UPDATE event_records SET record_hash=?",("f"*64,))
   else:exposures.connection.execute("DROP TRIGGER protect_exposure_records_update");exposures.connection.execute("UPDATE exposure_records SET record_hash=?",("f"*64,))
   (s.connection if target in {"meta","policy"} else events.connection if target=="event" else exposures.connection).commit();expect(Exception,s.integrity_check)
@check("BOUNDARY","safety fields exact and no automatic mapping or direction fields")
def _():
 with env() as (*_,s,e,x,root):r=append(s,e,x)["binding"];require((r["semantic_compatibility_status"],r["directional_effect_status"],r["causal_effect_status"])==("NOT_EVALUATED",)*3)
 text="\n".join(p.read_text().casefold() for p in (STAGE_ROOT/"stage6_exposure_binding").glob("*.py"));
 for token in ("event_type_to_exposure_type","impact_direction","stock_direction","expected_return","beneficiary","loser","trade_signal"):require(token not in text)
@check("NETWORK_AI_TRADING","zero network AI NLP ML OCR and trading implementation")
def _():
 prohibited={"socket","requests","urllib","http","aiohttp","openai","transformers"};text=""
 for p in (STAGE_ROOT/"stage6_exposure_binding").glob("*.py"):
  src=p.read_text();text+=src.casefold();tree=ast.parse(src);imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports&prohibited)
 for token in ("semantic similarity","embedding","ocr","position sizing","portfolio mutation","broker"):require(token not in text)
@check("NETWORK_AI_TRADING","socket sentinel")
def _():
 with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):
  with env() as (*_,s,e,x,root):append(s,e,x)
@check("BOUNDARY","all frozen paths unchanged")
def _():require(git("diff","--name-only",BASE_TAG,"--","Stage 5D","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/stage6_lifecycle","Stage 6/stage6_exposure","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/scripts/validate_stage6_0.py")=="")
def main():
 rows=[]
 for i,(c,n,f) in enumerate(CHECKS,1):
  try:
   with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):f()
   rows.append({"test_id":f"S6_3B_{i:03d}","category":c,"test_name":n,"result":"PASS","detail":""})
  except Exception as x:rows.append({"test_id":f"S6_3B_{i:03d}","category":c,"test_name":n,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 RESULT_PATH.parent.mkdir(parents=True,exist_ok=True)
 with RESULT_PATH.open("w",encoding="utf-8",newline="") as h:w=csv.DictWriter(h,fieldnames=["test_id","category","test_name","result","detail"],lineterminator="\n");w.writeheader();w.writerows(rows)
 bad=[x for x in rows if x["result"]!="PASS"];print(json.dumps({"stage":"6.3B","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"automatic_mapping":False},sort_keys=True,separators=(",",":")))
 for x in bad:print("FAIL",x["test_id"],x["test_name"],x["detail"])
 return bool(bad)
if __name__=="__main__":raise SystemExit(main())
