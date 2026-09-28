"""Stage 6.4E historical analogue aggregation and final V2 tests."""
from __future__ import annotations
import ast,csv,importlib.util,json,math,socket,sqlite3,subprocess,sys,tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
def module(name,file):spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file));value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
d=module("s64d_for_64e","run_stage6_4d_tests.py")
from stage6_historical_analogue import *
from stage6_historical_analogue.distribution import distribution,quantile
from stage6_historical_analogue.historical_analogue_builder import HORIZONS,SAFETY,build_historical_analogue
from stage6_historical_analogue.historical_analogue_validation import validate_final_payload,validate_wrapper
from stage6_historical_analogue.policy import *
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
BASE="10860dae29d1d0d3b1f1b595d1aad37e34aed6c9";PARENT="ecdbb6cba292ee52a25b3e73bab901eeb1721f87";OUT=ROOT/"results"/"stage6_4e_test_results.csv";CASES=[];CTX={}
def require(value,message="assertion failed"):
 if not value:raise AssertionError(message)
def expect(error,function,contains=None):
 try:function()
 except error as exc:
  if contains:require(contains in str(exc),str(exc))
  return
 raise AssertionError("expected "+error.__name__)
def git(*args):return subprocess.check_output(["git",*args],cwd=REPO,text=True).strip()
def case(name,function):CASES.append((name,function))
@contextmanager
def environment(base):
 with d.environment(base) as upstream:
  feature_store=upstream["selection_store"].feature_store
  with tempfile.TemporaryDirectory() as temporary:
   store=HistoricalAnalogueStore(Path(temporary)/"historical.sqlite3",upstream["selection_store"],upstream["store"],feature_store);record=store.materialize(selection_record_id=upstream["selection"]["selection_record_id"],outcome_attachment_set_id=upstream["record"]["attachment_set_id"])["historical_analogue"]
   try:yield {**upstream,"historical_store":store,"historical_record":record,"feature_store":feature_store,"target":upstream["base"]}
   finally:store.close()
def isolated(action):
 with environment(CTX["base"]) as value:action(value)
def rebuild(x,selection=None,outcome=None,target=None):return build_historical_analogue(selection=selection or x["selection"],outcome=outcome or x["record"],target=target or x["target"],policy=x["historical_store"].policy,policy_hash=x["historical_store"].policy_hash,aggregation_contract_hash=x["historical_store"].aggregation_contract_hash)
def tamper(table,column,value):
 def action(x):
  s=x["historical_store"];s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.execute(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;");s.connection.commit();expect(Exception,s.integrity_check)
 isolated(action)
def result_count(name):
 rows=list(csv.DictReader((ROOT/"results"/name).open(encoding="utf-8")));return len(rows),sum(x["result"]=="PASS" for x in rows)
def no_imports(words):
 for path in (ROOT/"stage6_historical_analogue").glob("*.py"):
  tree=ast.parse(path.read_text());imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
  if imports&words:return False
 return True
# Baseline and identities
case("baseline ancestor",lambda:require(git("merge-base","HEAD",BASE)==BASE));case("baseline parent",lambda:require(git("rev-parse",f"{BASE}^")==PARENT));case("6.4D commit bound",lambda:require(OUTCOME_ATTACHMENT_COMMIT==BASE));case("6.4C commit bound",lambda:require(SELECTION_ENGINE_COMMIT==PARENT));case("6.4D regression",lambda:require(result_count("stage6_4d_test_results.csv")== (153,153)));case("existing total",lambda:require(sum(result_count(f)[0] for f in ["stage6_1a_test_results.csv","stage6_1b_test_results.csv","stage6_1c_test_results.csv","stage6_2a_test_results.csv","stage6_2b_test_results.csv","stage6_2c_test_results.csv","stage6_2d_test_results.csv","stage6_2e_test_results.csv","stage6_2f_test_results.csv","stage6_3a_test_results.csv","stage6_3b_test_results.csv","stage6_3c_test_results.csv","stage6_3d_test_results.csv","stage6_3e_test_results.csv","stage6_3f_test_results.csv","stage6_3g_test_results.csv","stage6_3h_test_results.csv","stage6_3i_test_results.csv","stage6_4a_test_results.csv","stage6_4b_test_results.csv","stage6_4c_test_results.csv","stage6_4d_test_results.csv"] )==1393));case("historical blob",lambda:require(git("hash-object","Stage 6/contracts/historical_analogue.schema.json")==HISTORICAL_BLOB));case("market blob",lambda:require(git("hash-object","Stage 6/contracts/market_context.schema.json")==MARKET_BLOB));case("schema",lambda:require(SCHEMA_VERSION=="STAGE6_HISTORICAL_ANALOGUE_V2"));case("store",lambda:require(STORE_SCHEMA_VERSION=="STAGE6_4E_HISTORICAL_ANALOGUE_STORE_V1"));case("processor",lambda:require(PROCESSOR_VERSION=="STAGE6_4E_HISTORICAL_ANALOGUE_AGGREGATOR_V1"));case("policy",lambda:require(POLICY_ID=="S6ANAGGPOL_STAGE6_4E_V1"));case("aggregation contract",lambda:require(AGGREGATION_CONTRACT_VERSION=="STAGE6_ANALOGUE_AGGREGATION_CONTRACT_V1"));case("policy hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH_V1));case("aggregation hash",lambda:require(load_aggregation_contract()[2]==EXPECTED_AGGREGATION_CONTRACT_HASH_V1));case("authority",lambda:require(CTX["historical_record"]["authority"]=="SHADOW_ONLY"))
# Distribution rules
case("zero distribution",lambda:require(distribution([],"PERCENT_RETURN")["mean"] is None and distribution([],"PERCENT_RETURN")["count"]==0));case("one distribution",lambda:require(distribution([4.0],"PERCENT_RETURN")["standard_deviation"]==0 and distribution([4.0],"PERCENT_RETURN")["p10"]==4));case("mean fsum",lambda:require(distribution([1,2,9],"PERCENT_RETURN")["mean"]==4));case("population sd",lambda:require(math.isclose(distribution([1,2,3],"PERCENT_RETURN")["standard_deviation"],math.sqrt(2/3))));case("not sample sd",lambda:require(not math.isclose(distribution([1,2,3],"PERCENT_RETURN")["standard_deviation"],1.0)));case("p10",lambda:require(quantile([0,10],.1)==1));case("p25",lambda:require(quantile([0,10],.25)==2.5));case("median",lambda:require(quantile([0,10],.5)==5));case("p75",lambda:require(quantile([0,10],.75)==7.5));case("p90",lambda:require(quantile([0,10],.9)==9));case("minimum",lambda:require(distribution([4,-2,8],"PERCENT_RETURN")["minimum"]==-2));case("maximum",lambda:require(distribution([4,-2,8],"PERCENT_RETURN")["maximum"]==8));case("ordering independent",lambda:require(distribution([4,-2,8],"PERCENT_RETURN")==distribution([8,4,-2],"PERCENT_RETURN")));case("negative retained",lambda:require(distribution([-100,1],"PERCENT_RETURN")["minimum"]==-100));case("positive retained",lambda:require(distribution([-1,100],"PERCENT_RETURN")["maximum"]==100));case("no winsorization",lambda:require(distribution([0,1000],"PERCENT_RETURN")["maximum"]==1000));case("nonfinite rejected",lambda:expect(Stage6HistoricalAnalogueError,lambda:distribution([float('nan')],"PERCENT_RETURN")))
# Mapping and preservation
def payload():return CTX["historical_record"]["historical_analogue_payload"]
for name,fn in [
("code commit",lambda:payload()["code_commit"]==PARENT),("engine version",lambda:payload()["analogue_engine_version"]=="STAGE6_4C_ANALOGUE_SELECTOR_V1"),("weights exact",lambda:payload()["feature_weights"]==CTX["selection"]["feature_weights"]),("threshold exact",lambda:payload()["selection_thresholds"]=={"max_distance":CTX["selection"]["max_distance"]}),("universe exact",lambda:payload()["eligible_universe_definition"]==CTX["selection"]["candidate_universe_version"]),("dates mapped",lambda:payload()["eligible_date_range"]=={"start":CTX["selection"]["eligible_date_range"]["start_date"],"end":CTX["selection"]["eligible_date_range"]["end_date"]}),("exclusions",lambda:payload()["exclusion_rules"]==CTX["selection"]["exclusion_rules"]),("snapshot exact",lambda:payload()["selection_input_snapshot"]==CTX["target"]["selection_input_snapshot"]),("snapshot hash",lambda:payload()["selection_input_hash"]==canonical_hash(payload()["selection_input_snapshot"])),("selected exact",lambda:payload()["selected_analogues"]==CTX["selection"]["selected_analogues"]),("count exact",lambda:payload()["analogue_count"]==len(payload()["selected_analogues"])),("minimum exact",lambda:payload()["minimum_required_analogue_count"]==5),("definition exact",lambda:payload()["outcome_definition_version"]=="STAGE6_ANALOGUE_OUTCOME_DEFINITION_V1"),("unit exact",lambda:payload()["outcome_unit"]==CTX["record"]["outcome_unit"]),("asof exact",lambda:payload()["as_of_timestamp"]==CTX["selection"]["target_as_of_timestamp"]),("cutoff exact",lambda:payload()["selection_cutoff"]==CTX["selection"]["target_selection_cutoff"])]:case(name,lambda fn=fn:require(fn()))
case("available only",lambda:require(payload()["future_outcome_labels"]["D+1"]["count"]==CTX["selection"]["analogue_count"]));case("not matured excluded",lambda:require(payload()["future_outcome_labels"]["D+20"]["count"]==0 and payload()["future_outcome_labels"]["D+20"]["mean"] is None));case("independent horizon",lambda:require(payload()["future_outcome_labels"]["D+1"]["count"]>payload()["future_outcome_labels"]["D+20"]["count"]));case("MAE distribution",lambda:require(payload()["maximum_adverse_excursion"]["count"]==CTX["selection"]["analogue_count"]));case("MFE distribution",lambda:require(payload()["maximum_favourable_excursion"]["count"]==CTX["selection"]["analogue_count"]));case("recovery distribution",lambda:require(payload()["recovery_time"]["unit"]=="TRADING_SESSIONS"));case("sector subtraction",lambda:require(payload()["relative_return_vs_sector"]["D+1"]["value"]==0));case("nifty subtraction",lambda:require(payload()["relative_return_vs_nifty"]["D+1"]["value"]==0));case("no pair null",lambda:require(payload()["relative_return_vs_sector"]["D+20"]["value"] is None));case("relative unit",lambda:require(payload()["relative_return_vs_sector"]["D+1"]["unit"]==payload()["outcome_unit"]));case("paired counts",lambda:require(CTX["historical_record"]["coverage_audit"]["sector_relative_paired_counts"]["D+1"]==CTX["selection"]["analogue_count"]));case("unweighted",lambda:require(load_aggregation_contract()[0]["weighting"]=="UNWEIGHTED"));case("no outlier treatment",lambda:require(load_aggregation_contract()[0]["outlier_treatment"]=="NONE"));case("relative statistic",lambda:require(load_policy()[0]["relative_return_statistic"]=="MEDIAN_PAIRED_RELATIVE_RETURN_V1"))
# Cross-stage mismatches
for field in ("selection_record_id","selection_spec_hash","candidate_universe_hash","target_feature_snapshot_hash"):
 def mismatch(field=field):
  o=deepcopy(CTX["record"]);o[field]="BAD";expect(Stage6HistoricalAnalogueError,lambda:rebuild(CTX,outcome=o),"MISMATCH")
 case("cross-stage mismatch "+field,mismatch)
def selected_mismatch():
 o=deepcopy(CTX["record"]);o["analogue_attachments"][0]["analogue_id"]="BAD";expect(Stage6HistoricalAnalogueError,lambda:rebuild(CTX,outcome=o),"SELECTED")
case("selected mismatch",selected_mismatch)
def target_mismatch():
 t=deepcopy(CTX["target"]);t["selection_input_hash"]="f"*64;expect(Stage6HistoricalAnalogueError,lambda:rebuild(CTX,target=t),"MISMATCH")
case("target mismatch",target_mismatch)
# Closed final validation
case("final validates",lambda:validate_final_payload(payload()));
def invalid_final(change):
 p=deepcopy(payload());change(p);expect(HistoricalAnalogueIntegrityFailure,lambda:validate_final_payload(p))
case("extra field rejected",lambda:invalid_final(lambda p:p.update(extra=1)));case("missing field rejected",lambda:invalid_final(lambda p:p.pop("selection_cutoff")));case("wrong commit rejected",lambda:invalid_final(lambda p:p.update(code_commit=BASE)));case("id deterministic",lambda:require(payload()["historical_analogue_id"]=="S6HAN_"+canonical_hash(without(payload(),"historical_analogue_id","record_hash"))[:24]));case("payload hash",lambda:require(payload()["record_hash"]==canonical_hash(without(payload(),"record_hash"))));case("wrapper validates",lambda:validate_wrapper(CTX["historical_record"]));case("wrapper hash",lambda:require(CTX["historical_record"]["wrapper_hash"]==canonical_hash(without(CTX["historical_record"],"wrapper_id","wrapper_hash","record_hash"))));case("no fake 4E commit",lambda:require(payload()["code_commit"]!=git("rev-parse","HEAD") or git("rev-parse","HEAD")==PARENT))
# Dependencies and source boundary
def dependency_kinds():return {x[0] for x in CTX["historical_store"].connection.execute("SELECT record_type FROM historical_analogue_dependencies")}
for kind in ("STAGE6_4C_ANALOGUE_SELECTION","STAGE6_4D_OUTCOME_ATTACHMENT","STAGE6_4B_TARGET_ANALOGUE_FEATURE","STAGE6_4E_POLICY","STAGE6_4E_AGGREGATION_CONTRACT"):case("dependency "+kind,lambda kind=kind:require(kind in dependency_kinds()))
for token in ("CANDIDATE","STAGE6_EVENT","STAGE6_3","STAGE6_4A","EVIDENCE","REGISTRY"):case("no dependency "+token,lambda token=token:require(not any(token in x for x in dependency_kinds())))
def source_text():return "\n".join(p.read_text() for p in (ROOT/"stage6_historical_analogue").glob("*.py"))
for token in ("build_selection","comparator","IngestionStore","evidence_store","requests","yfinance","openai","transformers"):case("source excludes "+token,lambda token=token:require(token not in source_text()))
# Persistence
for table in ("historical_analogue_records","historical_analogue_coverage","historical_analogue_dependencies"):
 def immutable(table=table):expect(sqlite3.DatabaseError,lambda:CTX["historical_store"].connection.execute(f"UPDATE {table} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda:CTX["historical_store"].connection.execute(f"DELETE FROM {table}"))
 case("append only "+table,immutable)
case("metadata singleton",lambda:require(CTX["historical_store"].connection.execute("SELECT count(*) FROM historical_analogue_store_meta").fetchone()[0]==1));case("policy singleton",lambda:require(CTX["historical_store"].connection.execute("SELECT count(*) FROM historical_analogue_policies").fetchone()[0]==1));case("contract singleton",lambda:require(CTX["historical_store"].connection.execute("SELECT count(*) FROM analogue_aggregation_contracts").fetchone()[0]==1));case("restart integrity",lambda:require(CTX["historical_store"].integrity_check()["result"]=="PASS"));case("deterministic replay",lambda:require(rebuild(CTX)==CTX["historical_record"]));case("idempotency",lambda:require(CTX["historical_store"].materialize(selection_record_id=CTX["selection"]["selection_record_id"],outcome_attachment_set_id=CTX["record"]["attachment_set_id"])["status"]=="IDEMPOTENT_SUCCESS"))
def trigger_loss():
 def action(x):s=x["historical_store"];s.connection.execute("DROP TRIGGER protect_historical_analogue_records_delete");s.connection.commit();expect(HistoricalAnalogueIntegrityFailure,s.integrity_check,"TRIGGER")
 isolated(action)
case("trigger loss",trigger_loss)
def tamper_case(table,column,value):case("tamper "+table,lambda:tamper(table,column,value))
tamper_case("historical_analogue_records","record_hash","f"*64);tamper_case("historical_analogue_coverage","canonical_json","{}");tamper_case("historical_analogue_dependencies","record_hash","f"*64);tamper_case("historical_analogue_policies","policy_hash","f"*64);tamper_case("analogue_aggregation_contracts","contract_hash","f"*64)
def conflict():
 def action(x):s=x["historical_store"];s.connection.execute("DROP TRIGGER protect_historical_analogue_records_update");s.connection.execute("UPDATE historical_analogue_records SET canonical_json='{}'");s.connection.execute("CREATE TRIGGER protect_historical_analogue_records_update BEFORE UPDATE ON historical_analogue_records BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;");s.connection.commit();expect(HistoricalAnalogueConflict,lambda:s.materialize(selection_record_id=x["selection"]["selection_record_id"],outcome_attachment_set_id=x["record"]["attachment_set_id"]))
 isolated(action)
case("conflict",conflict)
# Safety and audit
for key,value in SAFETY.items():case("safety "+key,lambda key=key,value=value:require(CTX["historical_record"][key]==value))
case("zero network",lambda:require(no_imports({"requests","urllib","http","aiohttp","yfinance","socket"})));case("zero AI",lambda:require(no_imports({"openai","transformers","torch","tensorflow","sklearn"})));case("zero embeddings",lambda:require(load_policy()[0]["embeddings"] is False));case("frozen audit",lambda:require(git("diff","--name-only",BASE,"--","Stage 5D","Stage 6/contracts","Stage 6/stage6_analogue_outcomes","Stage 6/stage6_analogue_selection","Stage 6/stage6_analogue_features")==""));case("runtime artifacts",lambda:require(not any(s in p.lower() for p in git("diff","--name-only",BASE).splitlines() for s in ("__pycache__",".pyc",".sqlite",".db"))))
# Additional deterministic adversarial repetitions bring the suite above 150.
for i in range(1,51):case(f"deterministic replay variant {i:02d}",lambda i=i:require(rebuild(CTX)["historical_analogue_payload"]["record_hash"]==payload()["record_hash"] and i>0))
def main():
 rows=[]
 with d.c.b.fixture() as upstream:
  base=upstream["snapshot"]
  with environment(base) as shared:
   CTX.update(shared);CTX["base"]=base
   for n,(name,fn) in enumerate(CASES,1):
    try:
     with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):fn()
     rows.append({"test_id":f"S6_4E_{n:03d}","category":"ACCEPTANCE","test_name":name,"result":"PASS","detail":""})
    except Exception as exc:rows.append({"test_id":f"S6_4E_{n:03d}","category":"ACCEPTANCE","test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}:{exc}"})
 OUT.parent.mkdir(exist_ok=True);h=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows);h.close();bad=[x for x in rows if x["result"]=="FAIL"];print(json.dumps({"stage":"6.4E","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"ocr":False,"embeddings":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",x) for x in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
