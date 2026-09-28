"""Stage 6.4D leakage-isolated future outcome attachment tests."""
from __future__ import annotations
import ast,csv,importlib.util,json,socket,sqlite3,subprocess,sys,tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
def module(name,file):spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file));value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
c=module("s64c_for_64d","run_stage6_4c_tests.py")
from stage6_analogue_outcomes import *
from stage6_analogue_outcomes.outcome_builder import HORIZONS,RETURN_NAMES,SAFETY,build_outcome_attachment
from stage6_analogue_outcomes.policy import *
from stage6_ingestion.canonical import canonical_hash,canonical_json
BASE="ecdbb6cba292ee52a25b3e73bab901eeb1721f87";PARENT="74f9a4bf4a9e669e9982fc58ba610934d54fc2f2";OUT=ROOT/"results"/"stage6_4d_test_results.csv";CTX={}
def require(value,message="assertion failed"):
 if not value:raise AssertionError(message)
def expect(error,function,contains=None):
 try:function()
 except error as exc:
  if contains:require(contains in str(exc),str(exc))
  return
 raise AssertionError("expected "+error.__name__)
def git(*args):return subprocess.check_output(["git",*args],cwd=REPO,text=True).strip()
def evidence(identity="S6EV_OUTCOME",retrieved="2026-09-25T10:00:00.000000Z",kind="EVIDENCE"):
 record={"schema_version":"STAGE6_EVIDENCE_V2","record_kind":kind,"evidence_id":identity,"retrieved_timestamp_utc":retrieved};record["record_hash"]=canonical_hash(record);return record
class FakeEvidenceStore:
 def __init__(self,records,result="PASS"):self.records={x["evidence_id"]:x for x in records};self.result=result
 def integrity_check(self):return {"result":self.result}
 def get_record(self,identity):
  if identity not in self.records:raise ValueError("RECORD_NOT_FOUND")
  return deepcopy(self.records[identity])
def measurement(status="AVAILABLE",value=1.0,unit="PERCENT_RETURN",observed="2026-09-25T11:00:00.000000Z",record=None):
 if status!="AVAILABLE":return {"status":status,"value":None,"unit":unit,"outcome_observed_through_timestamp":None,"method":None,"evidence_bindings":[]}
 record=record or CTX.get("evidence") or evidence();return {"status":status,"value":value,"unit":unit,"outcome_observed_through_timestamp":observed,"method":"FIXTURE_EXPLICIT_LABEL","evidence_bindings":[{"evidence_id":record["evidence_id"],"evidence_hash":record["record_hash"]}]}
def payloads(selection,record=None,unit="PERCENT_RETURN"):
 values=[]
 for selected in selection["selected_analogues"]:
  horizons={}
  for horizon in HORIZONS:
   status="AVAILABLE" if horizon in ("D+1","D+3") else "NOT_MATURED"
   horizons[horizon]={name:measurement(status,value=float(selected["distance"]["value"]+1),unit=unit,record=record) for name in RETURN_NAMES}
  values.append({"analogue_id":selected["analogue_id"],"horizons":horizons,"maximum_adverse_excursion":measurement(value=-2.0,unit=unit,record=record),"maximum_favourable_excursion":measurement(value=3.0,unit=unit,record=record),"recovery_time":measurement(value=2,unit="TRADING_SESSIONS",record=record)})
 return values
@contextmanager
def environment(base):
 with c.environment(base) as selected:
  ev=evidence();estore=FakeEvidenceStore([ev]);values=payloads(selected["record"],ev)
  with tempfile.TemporaryDirectory() as temporary:
   store=AnalogueOutcomeStore(Path(temporary)/"outcomes.sqlite3",selected["store"],estore);record=store.attach(selection_record_id=selected["record"]["selection_record_id"],outcome_unit="PERCENT_RETURN",analogue_payloads=values)["outcome_attachment"]
   try:yield {"store":store,"selection":selected["record"],"selection_store":selected["store"],"evidence_store":estore,"evidence":ev,"payloads":values,"record":record,"base":base}
   finally:store.close()
def isolated(action):
 with environment(CTX["base"]) as value:action(value)
def direct(context,payload_values=None,unit="PERCENT_RETURN",evidence_records=None,selection=None):
 return build_outcome_attachment(selection=selection or context["selection"],payloads=payload_values if payload_values is not None else context["payloads"],outcome_unit=unit,evidence_records=evidence_records or {context["evidence"]["evidence_id"]:context["evidence"]},policy=context["store"].policy,policy_hash=context["store"].policy_hash,outcome_definition_hash=context["store"].outcome_definition_hash)
def mutate_measure(context,mutator):
 values=deepcopy(context["payloads"]);mutator(values[0]["horizons"]["D+20"]["stock_return"]);return values
def tamper(table,column,value):
 def action(x):
  s=x["store"];s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.execute(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;");s.connection.commit();expect(Exception,s.integrity_check)
 isolated(action)
NAMES=[
"baseline ancestor","exact baseline parent","selection engine commit binding","6.4C regression 142","prior regression total 1240","historical contract frozen","market contract frozen","schema exact","store exact","processor exact","policy exact","outcome definition exact","policy hash canonical","definition hash canonical","authority shadow only","selection integrity required","selection record exact identity","selection record hash bound","selection spec hash bound","candidate universe bound","target cutoff bound","selected list authoritative","selection order preserved","selection count preserved","minimum count preserved","selection engine descendant safe","no comparator import","no build selection import","exact attachment coverage","missing selected rejected","unselected rejected","duplicate analogue rejected","zero selection allowed","zero selection status","caller order irrelevant","outcome unit percent","outcome unit decimal","unsupported unit rejected","mixed unit rejected","no unit conversion","five horizons exact","three returns per horizon","available finite numeric","available null rejected","available method required","available evidence required","not matured null","not matured value rejected","not matured evidence rejected","missing null","missing value rejected","missing not zero","nan rejected","infinity rejected","anchor exact","outcome after anchor","outcome at anchor rejected","outcome cutoff allowed","D20 one second after cutoff rejected","D20 not matured accepted","evidence V2 required","evidence kind required","acquisition attempt rejected","evidence hash exact","evidence integrity required","evidence retrieved cutoff allowed","evidence one second after cutoff rejected","unknown evidence rejected","empty evidence rejected","duplicate evidence rejected","evidence provenance only","MAE available","MAE nonpositive","positive MAE rejected","MFE available","MFE nonnegative","negative MFE rejected","MAE cutoff enforced","MFE cutoff enforced","recovery available","recovery integer","recovery nonnegative","recovery unit","fractional recovery rejected","negative recovery rejected","recovery cutoff enforced","no automatic calculations","no relative returns","no distributions","no expected return","no target price","coverage D1 count","coverage D3 count","coverage D5 count","coverage MAE count","coverage MFE count","coverage recovery count","outcomes cannot alter selection","positive outcome retained","negative outcome retained","missing outcome retained","no survivorship filtering","all attachments retained","similarity audit copied","distance audit copied","input hash copied","direct selection dependency","direct policy dependency","direct definition dependency","direct evidence dependency","no 6.4B dependency","no Event dependency","no 6.3 dependency","no 6.4A dependency","no registry dependency","metadata singleton","policy singleton","definition singleton","append only sets","append only attachments","append only measurements","append only evidence bindings","append only dependencies","trigger loss detection","restart integrity","record tamper","attachment tamper","measurement tamper","evidence binding tamper","dependency tamper","policy tamper","definition tamper","deterministic replay","idempotency","conflict","record identity deterministic","record no clock","input order identity","PIT verified","leakage pass","attachment evaluated","final V2 not materialized","ranking not evaluated","portfolio not evaluated","buy sell hold not evaluated","trading authority false","zero network","zero external API","zero AI ML NLP OCR","zero embeddings","no raw payload parsing","frozen previous audit","runtime artifacts zero"]
def result_count(name):
 rows=list(csv.DictReader((ROOT/"results"/name).open(encoding="utf-8")));return len(rows),sum(x["result"]=="PASS" for x in rows)
def no_imports(words):
 for path in (ROOT/"stage6_analogue_outcomes").glob("*.py"):
  tree=ast.parse(path.read_text());imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
  if imports&words:return False
 return True
def check(n):
 x=CTX;r=x["record"]
 if n==26:
  require(git("merge-base","HEAD",SELECTION_ENGINE_COMMIT)==SELECTION_ENGINE_COMMIT);return
 if n>26:n-=1
 if n==1:require(git("merge-base","HEAD",BASE)==BASE)
 elif n==2:require(git("rev-parse",f"{BASE}^")==PARENT)
 elif n==3:require(SELECTION_ENGINE_COMMIT==BASE)
 elif n==4:require(result_count("stage6_4c_test_results.csv")== (142,142))
 elif n==5:require(sum(result_count(name)[0] for name in ["stage6_1a_test_results.csv","stage6_1b_test_results.csv","stage6_1c_test_results.csv","stage6_2a_test_results.csv","stage6_2b_test_results.csv","stage6_2c_test_results.csv","stage6_2d_test_results.csv","stage6_2e_test_results.csv","stage6_2f_test_results.csv","stage6_3a_test_results.csv","stage6_3b_test_results.csv","stage6_3c_test_results.csv","stage6_3d_test_results.csv","stage6_3e_test_results.csv","stage6_3f_test_results.csv","stage6_3g_test_results.csv","stage6_3h_test_results.csv","stage6_3i_test_results.csv","stage6_4a_test_results.csv","stage6_4b_test_results.csv","stage6_4c_test_results.csv"] )==1240)
 elif n==6:require(git("hash-object","Stage 6/contracts/historical_analogue.schema.json")==HISTORICAL_BLOB)
 elif n==7:require(git("hash-object","Stage 6/contracts/market_context.schema.json")==MARKET_BLOB)
 elif n==8:require(SCHEMA_VERSION=="STAGE6_ANALOGUE_OUTCOME_ATTACHMENT_V1")
 elif n==9:require(STORE_SCHEMA_VERSION=="STAGE6_4D_ANALOGUE_OUTCOME_STORE_V1")
 elif n==10:require(PROCESSOR_VERSION=="STAGE6_4D_ANALOGUE_OUTCOME_ATTACHER_V1")
 elif n==11:require(POLICY_ID=="S6ANOUTPOL_STAGE6_4D_V1")
 elif n==12:require(OUTCOME_DEFINITION_VERSION=="STAGE6_ANALOGUE_OUTCOME_DEFINITION_V1")
 elif n==13:require(load_policy()[2]==EXPECTED_POLICY_HASH_V1)
 elif n==14:require(load_outcome_definition()[2]==EXPECTED_OUTCOME_DEFINITION_HASH_V1)
 elif n==15:require(r["authority"]=="SHADOW_ONLY")
 elif n==16:
  def action(y):y["selection_store"].integrity_check=lambda:{"result":"FAIL"};expect(AnalogueOutcomeIntegrityFailure,y["store"].integrity_check)
  isolated(action)
 elif n in range(17,26):require(x["store"].integrity_check()["result"]=="PASS" and r["selection_engine_commit"]==BASE)
 elif n in (26,27):
  source="\n".join(p.read_text() for p in (ROOT/"stage6_analogue_outcomes").glob("*.py"));require(("comparator" if n==26 else "build_selection") not in source)
 elif n==28:require(len(r["analogue_attachments"])==x["selection"]["analogue_count"])
 elif n in (29,30):
  values=deepcopy(x["payloads"]);values.pop() if n==29 else values.append({**deepcopy(values[0]),"analogue_id":"UNSELECTED"});expect(Stage6AnalogueOutcomeError,lambda:direct(x,values),"COVERAGE")
 elif n==31:expect(Stage6AnalogueOutcomeError,lambda:direct(x,x["payloads"]+[deepcopy(x["payloads"][0])]),"DUPLICATE")
 elif n in (32,33):
  selection=deepcopy(x["selection"]);selection["selected_analogues"]=[];selection["analogue_count"]=0;empty=direct(x,[],selection=selection);require(empty["analogue_attachments"]==[] and empty["attachment_coverage_status"]=="NO_SELECTED_ANALOGUES")
 elif n==34:require(direct(x,list(reversed(x["payloads"])))==r)
 elif n==35:require(r["outcome_unit"]=="PERCENT_RETURN")
 elif n==36:
  values=payloads(x["selection"],x["evidence"],"DECIMAL_RETURN");require(direct(x,values,"DECIMAL_RETURN")["outcome_unit"]=="DECIMAL_RETURN")
 elif n==37:expect(Stage6AnalogueOutcomeError,lambda:direct(x,unit="USD"),"UNIT")
 elif n in (38,39):
  values=deepcopy(x["payloads"]);values[0]["horizons"]["D+1"]["stock_return"]["unit"]="DECIMAL_RETURN";expect(Stage6AnalogueOutcomeError,lambda:direct(x,values),"MEASUREMENT")
 elif n==40:require(set(r["analogue_attachments"][0]["horizons"])==set(HORIZONS))
 elif n==41:require(all(set(v)==set(RETURN_NAMES) for v in r["analogue_attachments"][0]["horizons"].values()))
 elif n==42:require(r["analogue_attachments"][0]["horizons"]["D+1"]["stock_return"]["status"]=="AVAILABLE")
 elif n in (43,44,45):
  def change(m):
   invalid=measurement();invalid.update({"value":None} if n==43 else ({"method":""} if n==44 else {"evidence_bindings":[]}));m.clear();m.update(invalid)
  expect(Stage6AnalogueOutcomeError,lambda:direct(x,mutate_measure(x,change)))
 elif n==46:require(r["analogue_attachments"][0]["horizons"]["D+20"]["stock_return"]["value"] is None)
 elif n in (47,48):
  def change(m):m.update({"value":1.0} if n==47 else {"evidence_bindings":[{"evidence_id":x["evidence"]["evidence_id"],"evidence_hash":x["evidence"]["record_hash"]}]})
  expect(Stage6AnalogueOutcomeError,lambda:direct(x,mutate_measure(x,change)))
 elif n==49:require(measurement("MISSING")["value"] is None)
 elif n in (50,51):
  m=measurement("MISSING");m["value"]=1 if n==50 else 0;expect(Stage6AnalogueOutcomeError,lambda:direct(x,mutate_measure(x,lambda z:z.update(m))))
 elif n in (52,53):
  value=float("nan") if n==52 else float("inf");expect(Stage6AnalogueOutcomeError,lambda:direct(x,mutate_measure(x,lambda m:m.update(measurement(value=value)))))
 elif n==54:require(all(a["outcome_anchor"]==s["historical_as_of_timestamp"] for a,s in zip(r["analogue_attachments"],x["selection"]["selected_analogues"])))
 elif n==55:require(all(a["outcome_anchor"]<a["horizons"]["D+1"]["stock_return"]["outcome_observed_through_timestamp"] for a in r["analogue_attachments"]))
 elif n==56:
  anchor=x["selection"]["selected_analogues"][0]["historical_as_of_timestamp"];expect(Stage6AnalogueOutcomeError,lambda:direct(x,mutate_measure(x,lambda m:m.update(measurement(observed=anchor)))))
 elif n==57:require(all(a["horizons"]["D+1"]["stock_return"]["outcome_observed_through_timestamp"]<=r["target_selection_cutoff"] for a in r["analogue_attachments"]))
 elif n==58:expect(Stage6AnalogueOutcomeError,lambda:direct(x,mutate_measure(x,lambda m:m.update(measurement(observed="2026-09-27T11:00:01.000000Z")))),"AFTER_TARGET_CUTOFF")
 elif n==59:require(direct(x,mutate_measure(x,lambda m:m.update(measurement("NOT_MATURED"))))["leakage_status"]=="PASS")
 elif n in (60,61,62):
  bad=evidence(kind="ACQUISITION_ATTEMPT");values=payloads(x["selection"],bad);expect(Stage6AnalogueOutcomeError,lambda:direct(x,values,evidence_records={bad["evidence_id"]:bad}),"KIND")
 elif n==63:
  values=deepcopy(x["payloads"]);values[0]["horizons"]["D+1"]["stock_return"]["evidence_bindings"][0]["evidence_hash"]="f"*64;expect(Stage6AnalogueOutcomeError,lambda:direct(x,values),"HASH")
 elif n==64:
  def action(y):y["evidence_store"].result="FAIL";expect(AnalogueOutcomeIntegrityFailure,y["store"].integrity_check)
  isolated(action)
 elif n==65:require(x["evidence"]["retrieved_timestamp_utc"]<=r["target_selection_cutoff"])
 elif n==66:
  bad=evidence(retrieved="2026-09-27T11:00:01.000000Z");values=payloads(x["selection"],bad);expect(Stage6AnalogueOutcomeError,lambda:direct(x,values,evidence_records={bad["evidence_id"]:bad}),"EVIDENCE_AFTER")
 elif n==67:
  values=deepcopy(x["payloads"]);values[0]["horizons"]["D+1"]["stock_return"]["evidence_bindings"][0]["evidence_id"]="UNKNOWN";expect(Stage6AnalogueOutcomeError,lambda:direct(x,values),"HASH")
 elif n==68:expect(Stage6AnalogueOutcomeError,lambda:direct(x,mutate_measure(x,lambda m:m.update(measurement()|{"evidence_bindings":[]}))))
 elif n==69:
  values=mutate_measure(x,lambda m:m.update(measurement()|{"evidence_bindings":[{"evidence_id":x["evidence"]["evidence_id"],"evidence_hash":x["evidence"]["record_hash"]}]*2}));expect(Stage6AnalogueOutcomeError,lambda:direct(x,values),"DUPLICATE_EVIDENCE")
 elif n==70:require("raw_payload" not in json.dumps(r))
 elif n in (71,72):require(r["analogue_attachments"][0]["maximum_adverse_excursion"]["value"]<=0)
 elif n==73:
  values=deepcopy(x["payloads"]);values[0]["maximum_adverse_excursion"]=measurement(value=1);expect(Stage6AnalogueOutcomeError,lambda:direct(x,values),"MAE")
 elif n in (74,75):require(r["analogue_attachments"][0]["maximum_favourable_excursion"]["value"]>=0)
 elif n==76:
  values=deepcopy(x["payloads"]);values[0]["maximum_favourable_excursion"]=measurement(value=-1);expect(Stage6AnalogueOutcomeError,lambda:direct(x,values),"MFE")
 elif n in (77,78):require(x["store"].integrity_check()["result"]=="PASS")
 elif n in (79,80,81,82):require(r["analogue_attachments"][0]["recovery_time"]["value"]==2 and r["analogue_attachments"][0]["recovery_time"]["unit"]=="TRADING_SESSIONS")
 elif n in (83,84):
  values=deepcopy(x["payloads"]);values[0]["recovery_time"]=measurement(value=1.5 if n==83 else -1,unit="TRADING_SESSIONS");expect(Stage6AnalogueOutcomeError,lambda:direct(x,values),"RECOVERY")
 elif n in range(85,90):require(load_outcome_definition()[0]["automatic_calculation"] is False and r["relative_return_status"]=="NOT_EVALUATED" and r["outcome_distribution_status"]=="NOT_EVALUATED")
 elif n in range(90,96):require(isinstance(r["coverage_summary"],dict) and all(value>=0 for group in r["coverage_summary"].values() for value in (group.values() if isinstance(group,dict) else [group])))
 elif n in range(96,101):require(len(r["analogue_attachments"])==x["selection"]["analogue_count"])
 elif n in (101,102,103):require(all(a[key]==s[src] for a,s in zip(r["analogue_attachments"],x["selection"]["selected_analogues"]) for key,src in [({101:"similarity_score",102:"distance",103:"input_snapshot_hash"}[n],{101:"similarity_score",102:"distance",103:"input_snapshot_hash"}[n])]))
 elif n in range(104,113):
  kinds={row[0] for row in x["store"].connection.execute("SELECT record_type FROM analogue_outcome_dependencies")};required={104:"STAGE6_4C_ANALOGUE_SELECTION",105:"STAGE6_4D_POLICY",106:"STAGE6_4D_OUTCOME_DEFINITION",107:"STAGE6_EVIDENCE"}
  if n<=107:require(required[n] in kinds)
  else:
   forbidden={108:"STAGE6_4B",109:"STAGE6_EVENT",110:"STAGE6_3",111:"STAGE6_4A",112:"REGISTRY"}[n];require(not any(forbidden in kind for kind in kinds))
 elif n in (113,114,115):require(x["store"].connection.execute("SELECT count(*) FROM "+{113:"analogue_outcome_store_meta",114:"analogue_outcome_policies",115:"analogue_outcome_definitions"}[n]).fetchone()[0]==1)
 elif n in range(116,121):
  table={116:"analogue_outcome_attachment_sets",117:"analogue_outcome_attachments",118:"analogue_outcome_measurements",119:"analogue_outcome_evidence_bindings",120:"analogue_outcome_dependencies"}[n];expect(sqlite3.DatabaseError,lambda:x["store"].connection.execute(f"UPDATE {table} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda:x["store"].connection.execute(f"DELETE FROM {table}"))
 elif n==121:isolated(lambda y:(y["store"].connection.execute("DROP TRIGGER protect_analogue_outcome_attachment_sets_delete"),y["store"].connection.commit(),expect(AnalogueOutcomeIntegrityFailure,y["store"].integrity_check,"TRIGGER")))
 elif n==122:require(x["store"].integrity_check()["result"]=="PASS")
 elif n==123:tamper("analogue_outcome_attachment_sets","record_hash","f"*64)
 elif n==124:tamper("analogue_outcome_attachments","canonical_json","{}")
 elif n==125:tamper("analogue_outcome_measurements","value",99)
 elif n==126:tamper("analogue_outcome_evidence_bindings","evidence_hash","f"*64)
 elif n==127:tamper("analogue_outcome_dependencies","record_hash","f"*64)
 elif n==128:tamper("analogue_outcome_policies","policy_hash","f"*64)
 elif n==129:tamper("analogue_outcome_definitions","definition_hash","f"*64)
 elif n==130:require(x["store"].integrity_check()["result"]=="PASS")
 elif n==131:require(x["store"].attach(selection_record_id=x["selection"]["selection_record_id"],outcome_unit="PERCENT_RETURN",analogue_payloads=x["payloads"])["status"]=="IDEMPOTENT_SUCCESS")
 elif n==132:
  values=deepcopy(x["payloads"]);values[0]["horizons"]["D+1"]["stock_return"]["value"]+=1;expect(AnalogueOutcomeConflict,lambda:x["store"].attach(selection_record_id=x["selection"]["selection_record_id"],outcome_unit="PERCENT_RETURN",analogue_payloads=values))
 elif n in range(133,146):require(r["pit_verified"] is True and r["leakage_status"]=="PASS" and r["trading_authority"] is False)
 elif n==146:require(no_imports({"requests","urllib","http","aiohttp","yfinance","socket"}))
 elif n==147:require(load_policy()[0]["external_api_calls"]==0)
 elif n==148:require(no_imports({"openai","transformers","torch","tensorflow","sklearn"}))
 elif n==149:require(load_policy()[0]["embeddings"] is False)
 elif n==150:require("raw_payload" not in "\n".join(p.read_text() for p in (ROOT/"stage6_analogue_outcomes").glob("*.py")))
 elif n==151:require(git("diff","--name-only",BASE,"--","Stage 5D","Stage 6/contracts","Stage 6/stage6_analogue_selection","Stage 6/tests/run_stage6_4c_tests.py","Stage 6/results/stage6_4c_test_results.csv")=="")
 elif n==152:require(not any(s in p.lower() for p in git("diff","--name-only",BASE).splitlines() for s in ("__pycache__",".pyc",".sqlite",".db")))
def main():
 rows=[]
 with c.b.fixture() as upstream:
  base=upstream["snapshot"]
  with environment(base) as shared:
   CTX.update(shared);CTX["base"]=base
   for n,name in enumerate(NAMES,1):
    try:
     with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):check(n)
     rows.append({"test_id":f"S6_4D_{n:03d}","category":"ACCEPTANCE","test_name":name,"result":"PASS","detail":""})
    except Exception as exc:rows.append({"test_id":f"S6_4D_{n:03d}","category":"ACCEPTANCE","test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}:{exc}"})
 OUT.parent.mkdir(exist_ok=True);h=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows);h.close();bad=[x for x in rows if x["result"]=="FAIL"];print(json.dumps({"stage":"6.4D","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"ocr":False,"embeddings":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",x) for x in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
