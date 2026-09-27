"""Stage 6.3H movement-aware company path effect qualification tests."""
from __future__ import annotations
import ast,csv,importlib.util,json,socket,sqlite3,subprocess,sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location("s63g",Path(__file__).with_name("run_stage6_3g_tests.py"));g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
from stage6_movement_path_effect import *
from stage6_ingestion.canonical import canonical_hash
OUT=ROOT/"results"/"stage6_3h_test_results.csv";BASE_COMMIT="8dc5150020c8a5b2f93e7ca42a8fd25478539417";CHECKS=[]
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
def env(*,event_type="CURRENCY_SHOCK",channel="CURRENCY",types=("CURRENCY",),event_values=("USD","EUR"),event_field="currencies",exposure_entities=("CUR_USD",),movement_direction="STRENGTHEN",movement_inputs=None):
 with g.env(event_type=event_type,channel=channel,types=types,event_values=event_values,event_field=event_field,exposure_entities=exposure_entities) as (movements,matches,evidence,event,exposure,match,root):
  if movement_inputs is None:
   source="CUR_USD" if event_type=="CURRENCY_SHOCK" else exposure_entities[0];reference="CUR_EUR" if event_type=="CURRENCY_SHOCK" else None;movement_inputs=[g.movement(match,evidence,source,reference,direction=movement_direction)]
  elif callable(movement_inputs):movement_inputs=movement_inputs(match,evidence)
  movement_record=movements.qualify_event_movement(match_id=match["match_id"],movement_inputs=movement_inputs)["movement"];store=MovementPathEffectStore(root/"path_effect.sqlite3",movements)
  try:yield store,movements,matches,evidence,event,exposure,match,movement_record,root
  finally:store.close()
def einput(match,movement,evidence,effect="ADVERSE",pair_index=0,name="exposure"):
 pair=eligible_pairs(match,movement,load_policy()[0])[pair_index];return {"source_path_id":pair["source_path_id"],"movement_item_id":pair["movement_item_id"],"effect_direction":effect,"evidence_ids":[evidence[name]["evidence_id"]]}
@check("BASELINE","exact Stage 6.3G baseline and parent")
def _():require(git("rev-parse",BASE_COMMIT)==BASE_COMMIT and git("rev-parse",f"{BASE_COMMIT}^")=="b1c755e03666be30f623acd6ff3e77184a58ea41");subprocess.check_call(["git","merge-base","--is-ancestor",BASE_COMMIT,"HEAD"],cwd=REPO)
@check("CONTRACT","schema store processor policy authority exact")
def _():require((SCHEMA_VERSION,STORE_SCHEMA_VERSION,PROCESSOR_VERSION,POLICY_ID,AUTHORITY)==("STAGE6_MOVEMENT_AWARE_PATH_EFFECT_V1","STAGE6_3H_MOVEMENT_PATH_EFFECT_STORE_V1","STAGE6_3H_MOVEMENT_PATH_EFFECT_EVALUATOR_V1","S6PATHEFFPOL_STAGE6_3H_V1","SHADOW_ONLY"))
@check("POLICY","exact four-rule policy and computed frozen hash")
def _():p,j,h=load_policy();require(validate_policy(p)==p and p["rules"]==EXPECTED_RULES_V1 and h==EXPECTED_POLICY_HASH_V1==canonical_hash(p))
@check("POLICY","semantic policy drift rejected")
def _():
 p,_,_=load_policy()
 for change in (lambda x:x["rules"].pop(),lambda x:x["rules"][0].__setitem__("movement_metric","PRICE"),lambda x:x["rules"][1]["allowed_effect_directions"].pop(),lambda x:x["rules"][2].__setitem__("source_rule_id","RENAMED")):
  q=deepcopy(p);change(q);expect(Stage6MovementPathEffectError,lambda q=q:validate_policy(q))
@check("EVENTS","currency oil gas and generic commodity are eligible")
def _():
 cases=(("CURRENCY_SHOCK","CURRENCY","CURRENCY",("USD","EUR"),"currencies",("CUR_USD",),"STRENGTHEN"),("OIL_SHOCK","COMMODITY","ENERGY_SENSITIVITY",("Crude Oil",),"commodities",("CMD_CRUDE_OIL",),"INCREASE"),("GAS_SHOCK","COMMODITY","ENERGY_SENSITIVITY",("Natural Gas",),"commodities",("CMD_NATURAL_GAS",),"INCREASE"),("COMMODITY_SHOCK","COMMODITY","COMMODITY",("Crude Oil",),"commodities",("CMD_CRUDE_OIL",),"DECREASE"))
 for et,ch,typ,values,field,entities,direction in cases:
  with env(event_type=et,channel=ch,types=(typ,),event_values=values,event_field=field,exposure_entities=entities,movement_direction=direction) as (s,ms,m,evidence,event,exposure,match,movement_record,root):require(len(eligible_pairs(match,movement_record,s.policy))==1 and s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence)])["path_effect"]["path_effect_qualification_status"]=="ALL_ELIGIBLE_PATH_EFFECTS_QUALIFIED")
@check("DIRECTION","all four explicit effects accepted without automatic inference")
def _():
 for effect in ("FAVORABLE","ADVERSE","MIXED","UNKNOWN"):
  with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):r=s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence,effect)])["path_effect"];require(r["effect_items"][0]["effect_direction"]==effect)
@check("ADVERSARIAL","oil increase may be favorable and oil decrease may be adverse")
def _():
 for movement_direction,effect in (("INCREASE","FAVORABLE"),("DECREASE","ADVERSE")):
  with env(event_type="OIL_SHOCK",channel="COMMODITY",types=("ENERGY_SENSITIVITY",),event_values=("Crude Oil",),event_field="commodities",exposure_entities=("CMD_CRUDE_OIL",),movement_direction=movement_direction) as (s,ms,m,evidence,event,exposure,match,movement_record,root):require(s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence,effect)])["path_effect"]["effect_items"][0]["effect_direction"]==effect)
@check("UNKNOWN","unknown movement only permits unknown company path effect")
def _():
 with env(movement_direction="UNKNOWN") as (s,ms,m,evidence,event,exposure,match,movement_record,root):
  for effect in ("FAVORABLE","ADVERSE","MIXED"):expect(Stage6MovementPathEffectError,lambda effect=effect:s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence,effect)]),"REQUIRES_UNKNOWN")
  require(s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence,"UNKNOWN")])["path_effect"]["matched_movement_path_effect_summary"]=="INDETERMINATE")
@check("IDENTITY","absent and explicit unknown are distinct")
def _():
 with env(movement_direction="UNKNOWN") as (s,ms,m,evidence,event,exposure,match,movement_record,root):a=s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[])["path_effect"]
 with env(movement_direction="UNKNOWN") as (s,ms,m,evidence,event,exposure,match,movement_record,root):u=s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence,"UNKNOWN")])["path_effect"]
 require(a["path_effect_record_id"]!=u["path_effect_record_id"] and a["path_effect_qualification_status"]=="UNQUALIFIED")
@check("COMPATIBILITY","currency orientation and commodity PRICE identity preserved exactly")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):item=s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence)])["path_effect"]["path_effect_results"][0];require(item["movement_subject_entity_id"]=="CUR_USD" and item["movement_reference_entity_id"]=="CUR_EUR" and item["movement_metric"]=="RELATIVE_VALUE")
 with env(event_type="OIL_SHOCK",channel="COMMODITY",types=("ENERGY_SENSITIVITY",),event_values=("Crude Oil",),event_field="commodities",exposure_entities=("CMD_CRUDE_OIL",),movement_direction="INCREASE") as (s,ms,m,evidence,event,exposure,match,movement_record,root):require(s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence)])["path_effect"]["path_effect_results"][0]["movement_metric"]=="PRICE")
@check("EVIDENCE","exact Exposure assertion subset enforced")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):expect(Stage6MovementPathEffectError,lambda:s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence,name="other")]),"NOT_ASSERTION_SUBSET")
@check("EVIDENCE","company and movement dimension support enforced")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):
  es=m.qualification_store.transmission_store.binding_store.exposure_store;bad=deepcopy(evidence["exposure"]);bad["entity_ids"]=[x for x in bad["entity_ids"] if x!=match["company_entity_id"]]
  with mock.patch.object(es,"_evidence",return_value=[bad]):expect(Stage6MovementPathEffectError,lambda:s._resolve(movement_record,match,exposure,[einput(match,movement_record,evidence)]),"COMPANY_SUPPORT")
  bad=deepcopy(evidence["exposure"]);bad["entity_ids"]=[x for x in bad["entity_ids"] if x!="CUR_USD"]
  with mock.patch.object(es,"_evidence",return_value=[bad]):expect(Stage6MovementPathEffectError,lambda:s._resolve(movement_record,match,exposure,[einput(match,movement_record,evidence)]),"DIMENSION_SUPPORT")
@check("PIT","Exposure cutoff cannot exceed exact movement cutoff")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):r=s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence)])["path_effect"];require(evidence["exposure"]["retrieved_timestamp_utc"]<=exposure["data_cutoff_timestamp"]<=r["path_effect_cutoff_timestamp"]==movement_record["movement_cutoff_timestamp"])
@check("STATUS","unqualified partial and complete states retain all eligible pairs")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):require(s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[])["path_effect"]["path_effect_qualification_status"]=="UNQUALIFIED")
 factory=lambda match,evidence:[g.movement(match,evidence,"CMD_CRUDE_OIL",direction="INCREASE"),g.movement(match,evidence,"CMD_NATURAL_GAS",direction="DECREASE")]
 with env(event_type="COMMODITY_SHOCK",channel="COMMODITY",types=("COMMODITY","COMMODITY"),event_values=("Crude Oil","Natural Gas"),event_field="commodities",exposure_entities=("CMD_CRUDE_OIL","CMD_NATURAL_GAS"),movement_inputs=factory) as (s,ms,m,evidence,event,exposure,match,movement_record,root):require(s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence,pair_index=0)])["path_effect"]["path_effect_qualification_status"]=="PARTIALLY_QUALIFIED")
 with env(event_type="COMMODITY_SHOCK",channel="COMMODITY",types=("COMMODITY","COMMODITY"),event_values=("Crude Oil","Natural Gas"),event_field="commodities",exposure_entities=("CMD_CRUDE_OIL","CMD_NATURAL_GAS"),movement_inputs=factory) as (s,ms,m,evidence,event,exposure,match,movement_record,root):inputs=[einput(match,movement_record,evidence,pair_index=0),einput(match,movement_record,evidence,pair_index=1)];require(s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=inputs)["path_effect"]["path_effect_qualification_status"]=="ALL_ELIGIBLE_PATH_EFFECTS_QUALIFIED")
@check("SUMMARY","favorable adverse mixed and indeterminate summaries exact")
def _():
 for effect,summary in (("FAVORABLE","FAVORABLE_ONLY"),("ADVERSE","ADVERSE_ONLY"),("MIXED","MIXED_PATH_DIRECTIONS"),("UNKNOWN","INDETERMINATE")):
  with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):require(s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence,effect)])["path_effect"]["matched_movement_path_effect_summary"]==summary)
@check("DUPLICATE","duplicate path movement declaration rejected")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):x=einput(match,movement_record,evidence);expect(Stage6MovementPathEffectError,lambda:s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[x,x]),"DUPLICATE")
@check("IDENTITY","canonical order idempotency and distinct conflict")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):x=einput(match,movement_record,evidence);s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[x]);require(s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[x])["status"]=="IDEMPOTENT_SUCCESS");expect(MovementPathEffectConflict,lambda:s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[]))
@check("DEPENDENCY","exact direct dependencies exclude Stage 6.3F")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):r=s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence)])["path_effect"];types={x[0] for x in s.connection.execute("SELECT record_type FROM movement_path_effect_dependencies WHERE path_effect_record_id=?",(r["path_effect_record_id"],))};require(types=={"STAGE6_3G_EVENT_MOVEMENT","STAGE6_3E_DIMENSION_MATCH","STAGE6_EXPOSURE","MOVEMENT_PATH_EFFECT_POLICY","EVIDENCE"} and s.integrity_check()["result"]=="PASS")
@check("CARDINALITY","metadata constraint and policy singleton fail closed")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):expect(sqlite3.IntegrityError,lambda:s.connection.execute("INSERT INTO movement_path_effect_store_meta VALUES(2,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASE_COMMIT,PROCESSOR_VERSION,AUTHORITY)));s.connection.execute("INSERT INTO movement_path_effect_policies VALUES(?,?,?)",("FAKE","f"*64,"{}"));s.connection.commit();expect(MovementPathEffectIntegrityFailure,s.integrity_check,"POLICY")
@check("APPEND_ONLY","all tables immutable and trigger loss detected")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):
  s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence)])
  for table in ("movement_path_effect_store_meta","movement_path_effect_policies","movement_path_effect_records","movement_path_effect_items","movement_path_effect_evidence","movement_path_effect_results","movement_path_effect_dependencies"):expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"UPDATE {table} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda table=table:s.connection.execute(f"DELETE FROM {table}"))
  s.connection.execute("DROP TRIGGER protect_movement_path_effect_records_delete");s.connection.commit();expect(MovementPathEffectIntegrityFailure,s.integrity_check,"TRIGGER")
@check("RESTART","closed store reopens and deterministic replay passes")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence)]);s.close();r=MovementPathEffectStore(root/"path_effect.sqlite3",ms);require(r.integrity_check()["result"]=="PASS");r.close()
@check("TAMPER","record item evidence policy result and dependency tamper detected")
def _():
 for table,column,value in (("movement_path_effect_records","movement_record_hash","f"*64),("movement_path_effect_items","effect_direction","FAVORABLE"),("movement_path_effect_evidence","evidence_hash","f"*64),("movement_path_effect_results","effect_direction","FAVORABLE"),("movement_path_effect_policies","policy_hash","f"*64),("movement_path_effect_dependencies","record_type","PATH_EFFECT_POLICY")):
  with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence)]);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.commit();expect(Exception,s.integrity_check)
@check("SAFETY","all downstream statuses remain not evaluated and trading false")
def _():
 with env() as (s,ms,m,evidence,event,exposure,match,movement_record,root):r=s.evaluate_path_effect(movement_record_id=movement_record["movement_record_id"],effect_inputs=[einput(match,movement_record,evidence)])["path_effect"];require(all(r[k]=="NOT_EVALUATED" for k in ("overall_company_effect_status","stock_direction_status","market_reaction_status","magnitude_status","expected_return_status","causal_effect_status","portfolio_influence_status")) and r["trading_authority"] is False)
@check("BOUNDARY","only additive Stage 6.3H files with zero network AI or trading")
def _():
 frozen=("Stage 5D","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/stage6_lifecycle","Stage 6/stage6_exposure","Stage 6/stage6_exposure_binding","Stage 6/stage6_transmission","Stage 6/stage6_dimension_qualification","Stage 6/stage6_dimension_matching","Stage 6/stage6_direction_semantics","Stage 6/stage6_event_movement","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/scripts/validate_stage6_0.py");require(git("diff","--name-only",BASE_COMMIT,"--",*frozen)=="")
 prohibited={"socket","requests","urllib","http","aiohttp","openai","transformers","re"}
 for p in (ROOT/"stage6_movement_path_effect").glob("*.py"):
  tree=ast.parse(p.read_text());imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports&prohibited)
def main():
 rows=[]
 for i,(category,name,fn) in enumerate(CHECKS,1):
  try:
   with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):fn()
   rows.append({"test_id":f"S6_3H_{i:03d}","category":category,"test_name":name,"result":"PASS","detail":""})
  except Exception as x:rows.append({"test_id":f"S6_3H_{i:03d}","category":category,"test_name":name,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 OUT.parent.mkdir(exist_ok=True);h=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows);h.close();bad=[x for x in rows if x["result"]=="FAIL"];print(json.dumps({"stage":"6.3H","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",x) for x in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
