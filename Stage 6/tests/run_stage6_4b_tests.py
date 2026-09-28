"""Stage 6.4B leakage-safe analogue feature snapshot tests."""
from __future__ import annotations
import ast,csv,importlib.util,json,socket,sqlite3,subprocess,sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
def module(name,file):spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
i=module("s63i_for_64b","run_stage6_3i_tests.py");a=module("s64a_for_64b","run_stage6_4a_tests.py")
from stage6_analogue_features import *
from stage6_analogue_features.feature_builder import FIELDS,SAFETY,build_feature_snapshot,selection_snapshot
from stage6_ingestion.canonical import canonical_hash,canonical_json
BASE="1b698c773cc9c49825781fe50bbe137df5aae679";IMPL="8efd269970321638c6db5c14d8c745930f9c27b6";PARENT="56c6922d4f4c0e58c90d1751973ae64868d8b98a";OUT=ROOT/"results"/"stage6_4b_test_results.csv";CASES=[];CTX={}
def case(c,n,fn):CASES.append((c,n,fn))
def require(v,m="assertion failed"):
 if not v:raise AssertionError(m)
def expect(e,fn,contains=None):
 try:fn()
 except e as x:
  if contains:require(contains in str(x),str(x))
  return
 raise AssertionError("expected "+e.__name__)
def git(*x):return subprocess.check_output(["git",*x],cwd=REPO,text=True).strip()
def market_payload(evidence):
 p=a.payload(evidence["evidence_id"]);p["ticker"]="FIXNEW";p["as_of_timestamp"]="2026-09-27T12:00:00Z";p["data_cutoff_timestamp"]="2026-09-27T11:00:00Z";return p
@contextmanager
def fixture(family="3f"):
 cm=i.env3f() if family=="3f" else i.env3h()
 with cm as values:
  ce,up,evidence,match,source,root=values;sf="STAGE6_3F_DIRECTION" if family=="3f" else "STAGE6_3H_MOVEMENT_PATH_EFFECT";sid=source["direction_record_id"] if family=="3f" else source["path_effect_record_id"];effect=ce.synthesize_company_effect(source_family=sf,source_record_id=sid)["company_effect"]
  event_store=(up.matching_store.qualification_store.transmission_store.binding_store.event_store if family=="3f" else up.movement_store.matching_store.qualification_store.transmission_store.binding_store.event_store)
  with a.env() as (mc,ing,regs,mevidence,mroot):
   market=a.make(mc,regs,mevidence,market_payload(mevidence))["market_context"];fs=AnalogueFeatureStore(root/"feature.sqlite3",ce,mc,event_store);snap=fs.freeze(company_effect_record_id=effect["company_effect_record_id"],market_context_record_id=market["market_context_record_id"])["feature_snapshot"]
   try:yield {"store":fs,"ce":ce,"mc":mc,"event_store":event_store,"effect":effect,"market":market,"event":event_store.get_event(effect["event_id"],effect["event_version"]),"source":source,"snapshot":snap,"root":root}
   finally:fs.close()
def c():return CTX
case("BASELINE","exact correction baseline",lambda:require(git("merge-base","HEAD",BASE)==BASE))
case("BASELINE","correction parent exact",lambda:require(git("rev-parse",f"{BASE}^")==IMPL))
case("BASELINE","6.4A implementation parent exact",lambda:require(git("rev-parse",f"{IMPL}^")==PARENT))
case("CONTRACT","historical analogue contract frozen",lambda:require(git("hash-object","Stage 6/contracts/historical_analogue.schema.json")=="85a2b0d00cacd6a3caea484e3ef3071eb16fe01d"))
case("CONTRACT","market context contract frozen",lambda:require(git("hash-object","Stage 6/contracts/market_context.schema.json")=="a141b221228718b8276b3d05b2f028d21adcfc3f"))
case("IDENTITY","schema exact",lambda:require(SCHEMA_VERSION=="STAGE6_ANALOGUE_FEATURE_SNAPSHOT_V1"))
case("IDENTITY","store exact",lambda:require(STORE_SCHEMA_VERSION=="STAGE6_4B_ANALOGUE_FEATURE_STORE_V1"))
case("IDENTITY","processor policy authority exact",lambda:require((PROCESSOR_VERSION,POLICY_ID,AUTHORITY)==("STAGE6_4B_ANALOGUE_FEATURE_FREEZER_V1","S6ANFEATPOL_STAGE6_4B_V1","SHADOW_ONLY")))
case("IDENTITY","feature contract version exact",lambda:require(FEATURE_CONTRACT_VERSION=="STAGE6_ANALOGUE_FEATURE_CONTRACT_V1"))
case("IDENTITY","policy canonical hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH_V1=="ee9b8a5cfb5500d88e9002ffd984d8e37cc690496201fe7913e164f188281f16"))
case("IDENTITY","feature contract canonical hash",lambda:require(load_feature_contract()[2]==EXPECTED_FEATURE_CONTRACT_HASH_V1=="4a263fb50e4db4eb44e2e474087cd0cd1e08a68b02298d019ad9d02e8f45484f"))
case("UPSTREAM","exact 6.3I identity hash",lambda:require(c()["snapshot"]["company_effect_record_hash"]==c()["effect"]["record_hash"]))
case("UPSTREAM","exact 6.4A identity hash",lambda:require(c()["snapshot"]["market_context_record_hash"]==c()["market"]["record_hash"]))
case("UPSTREAM","exact Event identity version hash",lambda:require((c()["snapshot"]["event_id"],c()["snapshot"]["event_version"],c()["snapshot"]["event_hash"])==(c()["event"]["event_id"],c()["event"]["event_version"],c()["event"]["record_hash"])))
case("UPSTREAM","same company required",lambda:require(c()["effect"]["company_entity_id"]==c()["market"]["company_entity_id"]==c()["snapshot"]["company_entity_id"]))
case("UPSTREAM","ticker-only join absent",lambda:require("ticker" not in c()["snapshot"] and c()["snapshot"]["company_entity_id"]==c()["effect"]["company_entity_id"]))
mapping=(("event_type",lambda s,e,m:s["event_type"]==e["event_type"]),("severity",lambda s,e,m:s["severity"]==e["severity"]),("materiality",lambda s,e,m:s["materiality"]==e["materiality"]),("stock returns",lambda s,e,m:s["stock_return_state"]["returns"]==m["stock_returns"]),("gap",lambda s,e,m:s["stock_return_state"]["gap"]==m["gap"]),("volume",lambda s,e,m:s["volume"]==m["volume_anomaly"]),("volatility",lambda s,e,m:s["volatility"]==m["volatility"]),("technical context",lambda s,e,m:s["technical_structure"]==m["technical_context"]),("sector returns",lambda s,e,m:s["sector_behaviour"]["sector_returns"]==m["sector_returns"]),("NIFTY returns",lambda s,e,m:s["sector_behaviour"]["nifty_returns"]==m["nifty_returns"]),("relative strength",lambda s,e,m:s["sector_behaviour"]["relative_strength"]==m["relative_strength"]),("market regime",lambda s,e,m:s["market_regime"]==m["market_regime"]),("commodity",lambda s,e,m:s["commodity_context"]==m["commodity_context"]),("currency",lambda s,e,m:s["currency_context"]==m["currency_context"]),("rate",lambda s,e,m:s["rate_context"]==m["rate_context"]))
for name,fn in mapping:case("MAPPING",f"{name} exact",lambda fn=fn:require(fn(c()["snapshot"]["selection_input_snapshot"],c()["event"],c()["market"]["contract_payload"])))
for name in ("direction","confidence","causality_assessment"):
 case("EXCLUSION",f"Event {name} excluded",lambda name=name:require(name not in c()["snapshot"]["selection_input_snapshot"]))
case("MAPPING","exactly 12 top-level fields",lambda:require(tuple(c()["snapshot"]["selection_input_snapshot"])==FIELDS and len(FIELDS)==12))
case("AUDIT","company effect retained audit-only",lambda:require(c()["snapshot"]["company_event_effect"]==c()["effect"]["company_event_effect"]))
case("AUDIT","company effect excluded from selection",lambda:require("company_event_effect" not in c()["snapshot"]["selection_input_snapshot"]))
case("PIT","selection cutoff equals market cutoff",lambda:require(c()["snapshot"]["selection_cutoff"]==c()["market"]["contract_payload"]["data_cutoff_timestamp"]))
case("PIT","Event first-known chronology",lambda:require(c()["event"]["first_known_timestamp"]<=c()["event"]["last_updated_timestamp"]))
case("PIT","Event last-updated cutoff",lambda:require(c()["event"]["last_updated_timestamp"]<=c()["snapshot"]["selection_cutoff"]))
case("PIT","6.3F source cutoff",lambda:require(c()["source"]["direction_cutoff_timestamp"]==c()["snapshot"]["company_effect_source_cutoff"]<=c()["snapshot"]["selection_cutoff"]))
def hcut():
 with fixture("3h") as x:require(x["source"]["path_effect_cutoff_timestamp"]==x["snapshot"]["company_effect_source_cutoff"]<=x["snapshot"]["selection_cutoff"])
case("PIT","6.3H source cutoff",hcut)
def future_event():
 x=c();e=deepcopy(x["event"]);e["last_updated_timestamp"]="2026-09-27T11:00:01Z";expect(Stage6AnalogueFeatureError,lambda:build_feature_snapshot(effect=x["effect"],market=x["market"],event=e,source_cutoff=x["snapshot"]["company_effect_source_cutoff"],policy=x["store"].policy,policy_hash=x["store"].policy_hash,feature_contract_hash=x["store"].feature_contract_hash),"CHRONOLOGY")
case("PIT","future Event timestamp rejected",future_event)
def future_source():
 x=c();expect(Stage6AnalogueFeatureError,lambda:build_feature_snapshot(effect=x["effect"],market=x["market"],event=x["event"],source_cutoff="2026-09-27T11:00:01Z",policy=x["store"].policy,policy_hash=x["store"].policy_hash,feature_contract_hash=x["store"].feature_contract_hash),"FUTURE")
case("PIT","future company effect cutoff rejected",future_source)
case("PIT","exact 6.4A prevents future observations",lambda:require(c()["mc"].integrity_check()["result"]=="PASS"))
case("NULL","null preservation",lambda:require(c()["snapshot"]["selection_input_snapshot"]["stock_return_state"]["gap"]["value"] is None))
case("NULL","no null imputation",lambda:require(c()["snapshot"]["selection_input_snapshot"]["stock_return_state"]["returns"]["3D"] is None))
case("UNITS","unit preservation",lambda:require(c()["snapshot"]["selection_input_snapshot"]["volume"]["unit"]==c()["market"]["contract_payload"]["volume_anomaly"]["unit"]))
case("UNITS","no conversion",lambda:require(c()["snapshot"]["selection_input_snapshot"]["stock_return_state"]["returns"]["unit"]=="PERCENT_RETURN"))
for key in ("commodity_context","currency_context","rate_context"):case("CANONICAL",f"{key} canonical ordering",lambda key=key:require(c()["snapshot"]["selection_input_snapshot"][key]==sorted(c()["snapshot"]["selection_input_snapshot"][key],key=lambda x:(x["name"].casefold(),x["unit"],x["observed_at_utc"],x["method"]))))
case("HASH","deterministic selection-input hash",lambda:require(c()["snapshot"]["selection_input_hash"]==canonical_hash(c()["snapshot"]["selection_input_snapshot"])))
case("HASH","deterministic feature-snapshot hash",lambda:require(c()["snapshot"]["feature_snapshot_id"]=="S6ANFEAT_"+c()["snapshot"]["feature_snapshot_hash"][:24]))
def ordering():
 x=c();p=deepcopy(x["market"]["contract_payload"]);p["commodity_context"]=list(reversed(p["commodity_context"]));require(selection_snapshot(x["event"],p)==x["snapshot"]["selection_input_snapshot"])
case("HASH","caller ordering independence",ordering)
for name in ("D+1","D+3","D+5","D+10","D+20","MAE","MFE","recovery_time","future_relative_return","expected_return","target_price"):
 case("LEAKAGE",f"{name} prohibited",lambda name=name:require(name not in json.dumps(c()["snapshot"]["selection_input_snapshot"])))
for k,v in (("similarity_metric_status","NOT_EVALUATED"),("feature_weights_status","NOT_DEFINED"),("feature_normalization_status","NOT_APPLIED"),("analogue_selection_status","NOT_EVALUATED")):case("DEFERRED",f"{k} exact",lambda k=k,v=v:require(c()["snapshot"][k]==v))
def deps():
 x=c();types={r[0] for r in x["store"].connection.execute("SELECT record_type FROM analogue_feature_dependencies WHERE feature_snapshot_id=?",(x["snapshot"]["feature_snapshot_id"],))};require(types=={"STAGE6_3I_COMPANY_EFFECT","STAGE6_4A_MARKET_CONTEXT","STAGE6_EVENT","STAGE6_4B_POLICY","STAGE6_4B_FEATURE_CONTRACT"})
case("DEPENDENCY","exact direct dependencies",deps)
case("DEPENDENCY","no transitive dependency duplication",lambda:require(not ({"STAGE6_3F_DIRECTION","STAGE6_3H_MOVEMENT_PATH_EFFECT","EVIDENCE","ENTITY_REGISTRY","SOURCE_REGISTRY"}&{r[0] for r in c()["store"].connection.execute("SELECT record_type FROM analogue_feature_dependencies")})))
def singleton(x,table,values):
 x["store"].connection.execute(f"INSERT INTO {table} VALUES({','.join('?' for _ in values)})",values);x["store"].connection.commit();expect(AnalogueFeatureIntegrityFailure,x["store"].integrity_check)
case("PERSISTENCE","metadata singleton",lambda:expect(sqlite3.IntegrityError,lambda:c()["store"].connection.execute("INSERT INTO analogue_feature_store_meta VALUES(2,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASE,PROCESSOR_VERSION,AUTHORITY))))
case("PERSISTENCE","policy singleton",lambda:isolated(lambda x:singleton(x,"analogue_feature_policies",("BAD","f"*64,"{}"))))
case("PERSISTENCE","feature-contract singleton",lambda:isolated(lambda x:singleton(x,"analogue_feature_contracts",("BAD","e"*64,"{}"))))
def immutable():
 for t in ("analogue_feature_store_meta","analogue_feature_policies","analogue_feature_contracts","analogue_feature_snapshots","analogue_feature_dependencies"):expect(sqlite3.DatabaseError,lambda t=t:c()["store"].connection.execute(f"UPDATE {t} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda t=t:c()["store"].connection.execute(f"DELETE FROM {t}"))
case("PERSISTENCE","append-only enforcement",immutable)
def isolated(action):
 with fixture() as x:action(x)
case("PERSISTENCE","trigger loss",lambda:isolated(lambda x:(x["store"].connection.execute("DROP TRIGGER protect_analogue_feature_snapshots_delete"),x["store"].connection.commit(),expect(AnalogueFeatureIntegrityFailure,x["store"].integrity_check,"TRIGGER"))))
case("PERSISTENCE","restart integrity",lambda:require(c()["store"].integrity_check()["result"]=="PASS"))
def tamper(table,column,value):
 def go(x):
  s=x["store"];s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.execute(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;");s.connection.commit();expect(Exception,s.integrity_check)
 isolated(go)
case("TAMPER","snapshot tamper",lambda:tamper("analogue_feature_snapshots","selection_input_hash","f"*64))
case("TAMPER","policy tamper",lambda:tamper("analogue_feature_policies","policy_hash","f"*64))
case("TAMPER","feature-contract tamper",lambda:tamper("analogue_feature_contracts","contract_hash","f"*64))
case("TAMPER","dependency tamper",lambda:tamper("analogue_feature_dependencies","record_hash","f"*64))
case("REPLAY","deterministic replay",lambda:require(c()["store"].integrity_check()["result"]=="PASS"))
case("IDENTITY","idempotency",lambda:require(c()["store"].freeze(company_effect_record_id=c()["effect"]["company_effect_record_id"],market_context_record_id=c()["market"]["market_context_record_id"])["status"]=="IDEMPOTENT_SUCCESS"))
def conflict():
 def go(x):
  s=x["store"];s.connection.execute("DROP TRIGGER protect_analogue_feature_snapshots_update");s.connection.execute("UPDATE analogue_feature_snapshots SET canonical_json=?",("{}",));s.connection.execute("CREATE TRIGGER protect_analogue_feature_snapshots_update BEFORE UPDATE ON analogue_feature_snapshots BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;");s.connection.commit();expect(AnalogueFeatureConflict,lambda:s.freeze(company_effect_record_id=x["effect"]["company_effect_record_id"],market_context_record_id=x["market"]["market_context_record_id"]),"CONFLICT")
 isolated(go)
case("IDENTITY","conflict handling",conflict)
for k,v in SAFETY.items():case("SAFETY",f"{k} exact",lambda k=k,v=v:require(c()["snapshot"][k]==v))
def no_network():
 prohibited={"requests","urllib","http","aiohttp","yfinance","socket","openai","transformers"}
 for p in (ROOT/"stage6_analogue_features").glob("*.py"):
  tree=ast.parse(p.read_text());imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports&prohibited)
case("BOUNDARY","zero network API",no_network)
case("BOUNDARY","zero AI ML NLP OCR embeddings",lambda:require(all(load_policy()[0][x] is False for x in ("llm","nlp","ml","ocr","embeddings","semantic_similarity"))))
case("BOUNDARY","trading authority false",lambda:require(c()["snapshot"]["trading_authority"] is False))
def frozen():
 protected=("Stage 5D","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/scripts/validate_stage6_0.py","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/stage6_lifecycle","Stage 6/stage6_exposure","Stage 6/stage6_exposure_binding","Stage 6/stage6_transmission","Stage 6/stage6_dimension_qualification","Stage 6/stage6_dimension_matching","Stage 6/stage6_direction_semantics","Stage 6/stage6_event_movement","Stage 6/stage6_movement_path_effect","Stage 6/stage6_company_effect","Stage 6/stage6_market_context","Stage 6/tests/run_stage6_4a_tests.py","Stage 6/results/stage6_4a_test_results.csv");require(git("diff","--name-only",BASE,"--",*protected)=="")
case("BOUNDARY","frozen baseline audit",frozen)
def main():
 rows=[]
 with fixture() as shared:
  CTX.update(shared)
  for n,(cat,name,fn) in enumerate(CASES,1):
   try:
    with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):fn()
    rows.append({"test_id":f"S6_4B_{n:03d}","category":cat,"test_name":name,"result":"PASS","detail":""})
   except Exception as x:rows.append({"test_id":f"S6_4B_{n:03d}","category":cat,"test_name":name,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 OUT.parent.mkdir(exist_ok=True);h=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows);h.close();bad=[x for x in rows if x["result"]=="FAIL"];print(json.dumps({"stage":"6.4B","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"ocr":False,"embeddings":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",x) for x in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
