"""Stage 6.3I unified Event-to-company effect synthesis tests."""
from __future__ import annotations
import ast,csv,importlib.util,json,socket,sqlite3,subprocess,sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
def module(name,file):spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
f=module("s63f","run_stage6_3f_tests.py");h=module("s63h","run_stage6_3h_tests.py")
from stage6_company_effect import *
from stage6_ingestion.canonical import canonical_hash,canonical_json
OUT=ROOT/"results"/"stage6_3i_test_results.csv";BASE="af059d6acd8af023056b28f2cad6ba58a7bce6da";CHECKS=[]
def check(c,n):
 def reg(fn):CHECKS.append((c,n,fn));return fn
 return reg
def require(v,m="assertion failed"):
 if not v:raise AssertionError(m)
def expect(e,fn,contains=None):
 try:fn()
 except e as x:
  if contains:require(contains in str(x))
  return
 raise AssertionError("expected "+e.__name__)
def git(*x):return subprocess.check_output(["git",*x],cwd=REPO,text=True).strip()
@contextmanager
def env3f(effect="FAVORABLE",empty=False,types=("INTEREST_RATE_SENSITIVITY",)):
 with f.env(types=types) as (ds,ms,evidence,event,exposure,match,root):
  inputs=[] if empty else [f.din(match,evidence,effect,i) for i in range(len(match["path_matches"]))];direction=ds.evaluate_direction(match_id=match["match_id"],directional_inputs=inputs)["direction"];store=CompanyEffectStore(root/"company.sqlite3",direction_store=ds)
  try:yield store,ds,evidence,match,direction,root
  finally:store.close()
@contextmanager
def env3h(effect="FAVORABLE",movement_direction="STRENGTHEN",types=("CURRENCY",)):
 with h.env(types=types,movement_direction=movement_direction) as (ps,movs,ms,evidence,event,exposure,match,movement,root):
  inputs=[h.einput(match,movement,evidence,effect,i) for i in range(len(eligible_pairs_h(match,movement,ps.policy)))];path=ps.evaluate_path_effect(movement_record_id=movement["movement_record_id"],effect_inputs=inputs)["path_effect"];store=CompanyEffectStore(root/"company.sqlite3",path_effect_store=ps)
  try:yield store,ps,evidence,match,path,root
  finally:store.close()
def eligible_pairs_h(match,movement,policy):return h.eligible_pairs(match,movement,policy)
@check("BASELINE","exact Stage 6.3H baseline and parent")
def _():require(git("rev-parse",BASE)==BASE and git("rev-parse",f"{BASE}^")=="8dc5150020c8a5b2f93e7ca42a8fd25478539417")
@check("CONTRACT","schema store processor policy authority exact")
def _():require((SCHEMA_VERSION,STORE_SCHEMA_VERSION,PROCESSOR_VERSION,POLICY_ID,AUTHORITY)==("STAGE6_EVENT_COMPANY_EFFECT_V1","STAGE6_3I_COMPANY_EFFECT_STORE_V1","STAGE6_3I_COMPANY_EFFECT_SYNTHESIZER_V1","S6COMEFFPOL_STAGE6_3I_V1","SHADOW_ONLY"))
@check("POLICY","computed policy and exact frozen source hashes")
def _():p,j,d=load_policy();require(d==EXPECTED_POLICY_HASH_V1==canonical_hash(p) and SOURCE_3F_HASH=="fc9c12455b5a23004523591d641620ee8caaad971be505b80128eba0d679998e" and SOURCE_3H_HASH=="727a1bf14fe442cf68cbb6f626c8f122550c53a7be3cf7a1ccfb60dd32848ace")
@check("ROUTING","all ten Events route to exactly one source family")
def _():
 routes={x["event_type"]:x["source_family"] for x in load_policy()[0]["routes"]};require(len(routes)==10 and all(routes[x]=="STAGE6_3F_DIRECTION" for x in ("RATE_HIKE","RATE_CUT","TARIFF_INCREASE","TARIFF_REDUCTION","WAR_ESCALATION","WAR_DEESCALATION")) and all(routes[x]=="STAGE6_3H_MOVEMENT_PATH_EFFECT" for x in ("CURRENCY_SHOCK","OIL_SHOCK","GAS_SHOCK","COMMODITY_SHOCK")))
@check("SYNTHESIS","no eligible incomplete unknown favorable adverse mixed rules exact")
def _():
 require(synthesize([])=="NOT_EVALUATED" and synthesize([{"effect_direction":None}])=="INDETERMINATE" and synthesize([{"effect_direction":"UNKNOWN"}])=="INDETERMINATE" and synthesize([{"effect_direction":"FAVORABLE"}])=="FAVORABLE" and synthesize([{"effect_direction":"ADVERSE"}])=="ADVERSE" and synthesize([{"effect_direction":"FAVORABLE"},{"effect_direction":"ADVERSE"}])=="MIXED" and synthesize([{"effect_direction":"MIXED"}])=="MIXED")
@check("SOURCE_3F","exact 6.3F source normalizes and synthesizes")
def _():
 for effect in ("FAVORABLE","ADVERSE","MIXED","UNKNOWN"):
  with env3f(effect) as (s,ds,evidence,match,source,root):r=s.synthesize_company_effect(source_family="STAGE6_3F_DIRECTION",source_record_id=source["direction_record_id"])["company_effect"];require(r["company_event_effect"]=={"FAVORABLE":"FAVORABLE","ADVERSE":"ADVERSE","MIXED":"MIXED","UNKNOWN":"INDETERMINATE"}[effect])
@check("SOURCE_3H","exact 6.3H source normalizes and synthesizes")
def _():
 for effect in ("FAVORABLE","ADVERSE","MIXED","UNKNOWN"):
  with env3h(effect) as (s,ps,evidence,match,source,root):r=s.synthesize_company_effect(source_family="STAGE6_3H_MOVEMENT_PATH_EFFECT",source_record_id=source["path_effect_record_id"])["company_effect"];require(r["company_event_effect"]=={"FAVORABLE":"FAVORABLE","ADVERSE":"ADVERSE","MIXED":"MIXED","UNKNOWN":"INDETERMINATE"}[effect])
@check("INCOMPLETE","unqualified eligible units remain indeterminate")
def _():
 with env3f(empty=True) as (s,ds,evidence,match,source,root):require(s.synthesize_company_effect(source_family="STAGE6_3F_DIRECTION",source_record_id=source["direction_record_id"])["company_effect"]["company_event_effect"]=="INDETERMINATE")
@check("ROUTING","wrong and unsupported source families fail closed")
def _():
 with env3f() as (s,ds,evidence,match,source,root):expect(Stage6CompanyEffectError,lambda:s.synthesize_company_effect(source_family="STAGE6_3H_MOVEMENT_PATH_EFFECT",source_record_id=source["direction_record_id"]));expect(Stage6CompanyEffectError,lambda:s.synthesize_company_effect(source_family="OTHER",source_record_id="X"),"UNSUPPORTED")
@check("SUMMARY","tampered upstream summary fails independent consistency check")
def _():
 with env3f() as (s,ds,evidence,match,source,root):bad=deepcopy(source);bad["matched_path_direction_summary"]="ADVERSE_ONLY";expect(ValueError,lambda:build_company_effect(source_family="STAGE6_3F_DIRECTION",source=bad,match=match,policy=s.policy,policy_hash=s.policy_hash),"INCONSISTENT")
@check("IDENTITY","deterministic identity and idempotency")
def _():
 with env3f() as (s,ds,evidence,match,source,root):a=s.synthesize_company_effect(source_family="STAGE6_3F_DIRECTION",source_record_id=source["direction_record_id"]);b=s.synthesize_company_effect(source_family="STAGE6_3F_DIRECTION",source_record_id=source["direction_record_id"]);require(b["status"]=="IDEMPOTENT_SUCCESS" and a["company_effect"]["record_hash"]==b["company_effect"]["record_hash"])
@check("DEPENDENCY","exact family-specific direct dependencies and no evidence duplication")
def _():
 with env3f() as (s,ds,evidence,match,source,root):r=s.synthesize_company_effect(source_family="STAGE6_3F_DIRECTION",source_record_id=source["direction_record_id"])["company_effect"];types={x[0] for x in s.connection.execute("SELECT record_type FROM company_effect_dependencies WHERE company_effect_record_id=?",(r["company_effect_record_id"],))};require(types=={"STAGE6_3F_DIRECTION","STAGE6_3E_DIMENSION_MATCH","COMPANY_EFFECT_POLICY"})
 with env3h() as (s,ps,evidence,match,source,root):r=s.synthesize_company_effect(source_family="STAGE6_3H_MOVEMENT_PATH_EFFECT",source_record_id=source["path_effect_record_id"])["company_effect"];types={x[0] for x in s.connection.execute("SELECT record_type FROM company_effect_dependencies WHERE company_effect_record_id=?",(r["company_effect_record_id"],))};require(types=={"STAGE6_3H_MOVEMENT_PATH_EFFECT","STAGE6_3E_DIMENSION_MATCH","COMPANY_EFFECT_POLICY"})
@check("CARDINALITY","metadata policy and append-only controls")
def _():
 with env3f() as (s,ds,evidence,match,source,root):s.synthesize_company_effect(source_family="STAGE6_3F_DIRECTION",source_record_id=source["direction_record_id"]);expect(sqlite3.IntegrityError,lambda:s.connection.execute("INSERT INTO company_effect_store_meta VALUES(2,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASE,PROCESSOR_VERSION,AUTHORITY)));s.connection.execute("INSERT INTO company_effect_policies VALUES(?,?,?)",("FAKE","f"*64,"{}"));s.connection.commit();expect(CompanyEffectIntegrityFailure,s.integrity_check,"POLICY")
@check("APPEND_ONLY","all tables immutable trigger loss and restart detected")
def _():
 with env3f() as (s,ds,evidence,match,source,root):
  s.synthesize_company_effect(source_family="STAGE6_3F_DIRECTION",source_record_id=source["direction_record_id"])
  for t in ("company_effect_store_meta","company_effect_policies","company_effect_records","company_effect_units","company_effect_dependencies"):expect(sqlite3.DatabaseError,lambda t=t:s.connection.execute(f"UPDATE {t} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda t=t:s.connection.execute(f"DELETE FROM {t}"))
  s.close();r=CompanyEffectStore(root/"company.sqlite3",direction_store=ds);require(r.integrity_check()["result"]=="PASS");r.connection.execute("DROP TRIGGER protect_company_effect_records_delete");r.connection.commit();expect(CompanyEffectIntegrityFailure,r.integrity_check,"TRIGGER");r.close()
@check("TAMPER","record unit policy and dependency tamper fail")
def _():
 for table,column,value in (("company_effect_records","source_record_hash","f"*64),("company_effect_units","effect_direction","ADVERSE"),("company_effect_policies","policy_hash","f"*64),("company_effect_dependencies","record_type","DIRECTION")):
  with env3f() as (s,ds,evidence,match,source,root):s.synthesize_company_effect(source_family="STAGE6_3F_DIRECTION",source_record_id=source["direction_record_id"]);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.commit();expect(Exception,s.integrity_check)
@check("SAFETY","downstream states remain unevaluated with no trading authority")
def _():
 with env3f() as (s,ds,evidence,match,source,root):r=s.synthesize_company_effect(source_family="STAGE6_3F_DIRECTION",source_record_id=source["direction_record_id"])["company_effect"];require(all(r[k]=="NOT_EVALUATED" for k in ("stock_direction_status","market_reaction_status","magnitude_status","expected_return_status","causal_effect_status","portfolio_influence_status","security_ranking_status")) and r["trading_authority"] is False)
@check("BOUNDARY","only additive 6.3I with zero network AI weighting or trading")
def _():
 frozen=("Stage 5D","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/stage6_lifecycle","Stage 6/stage6_exposure","Stage 6/stage6_exposure_binding","Stage 6/stage6_transmission","Stage 6/stage6_dimension_qualification","Stage 6/stage6_dimension_matching","Stage 6/stage6_direction_semantics","Stage 6/stage6_event_movement","Stage 6/stage6_movement_path_effect","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/scripts/validate_stage6_0.py");require(git("diff","--name-only",BASE,"--",*frozen)=="")
 prohibited={"socket","requests","urllib","http","aiohttp","openai","transformers","re"}
 for p in (ROOT/"stage6_company_effect").glob("*.py"):
  tree=ast.parse(p.read_text());imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports&prohibited)
def main():
 rows=[]
 for i,(c,n,fn) in enumerate(CHECKS,1):
  try:
   with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):fn()
   rows.append({"test_id":f"S6_3I_{i:03d}","category":c,"test_name":n,"result":"PASS","detail":""})
  except Exception as x:rows.append({"test_id":f"S6_3I_{i:03d}","category":c,"test_name":n,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 OUT.parent.mkdir(exist_ok=True);hnd=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(hnd,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows);hnd.close();bad=[x for x in rows if x["result"]=="FAIL"];print(json.dumps({"stage":"6.3I","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",x) for x in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
