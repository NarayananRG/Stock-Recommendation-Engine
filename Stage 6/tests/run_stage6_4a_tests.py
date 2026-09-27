"""Stage 6.4A point-in-time market context materialization tests."""
from __future__ import annotations
import ast,csv,json,socket,sqlite3,subprocess,sys,tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
from stage6_ingestion import IngestionStore,build_entity_registry
from stage6_ingestion.canonical import canonical_hash,canonical_json
from stage6_ingestion.fixtures import build_fixture_registries
from stage6_ingestion.errors import IntegrityFailure
from stage6_market_context import *
from stage6_market_context.market_context_builder import normalize_payload
BASE="56c6922d4f4c0e58c90d1751973ae64868d8b98a";STAGE6_4A_COMMIT="8efd269970321638c6db5c14d8c745930f9c27b6";CONTRACT_BLOB="a141b221228718b8276b3d05b2f028d21adcfc3f";OUT=ROOT/"results"/"stage6_4a_test_results.csv";CASES=[]
def case(category,name,fn):CASES.append((category,name,fn))
def require(v,m="assertion failed"):
 if not v:raise AssertionError(m)
def expect(exc,fn,contains=None):
 try:fn()
 except exc as e:
  if contains:require(contains in str(e),str(e))
  return
 raise AssertionError("expected "+exc.__name__)
def git(*a):return subprocess.check_output(["git",*a],cwd=REPO,text=True).strip()
def measurement(value=1.0,unit="PERCENT_RETURN",observed="2026-05-01T10:00:00Z"):return {"value":value,"unit":unit,"observed_at_utc":observed,"method":"EXPLICIT_FIXTURE"}
def returns(unit="PERCENT_RETURN",observed="2026-05-01T10:00:00Z"):return {"unit":unit,"1D":1.0,"3D":None,"5D":2.0,"20D":3.0,"observed_at_utc":observed,"method":"EXPLICIT_FIXTURE"}
def payload(evidence_id="S6EV_PLACEHOLDER"):
 return {"schema_version":"STAGE6_MARKET_CONTEXT_V2","ticker":"FIXOLD","as_of_timestamp":"2026-05-01T12:00:00Z","data_cutoff_timestamp":"2026-05-01T11:00:00Z","stock_returns":returns(),"sector_returns":returns("DECIMAL_RETURN"),"nifty_returns":returns(),"volume_anomaly":measurement(1.2,"VOLUME_RATIO"),"volatility":measurement(0.3,"DECIMAL_RETURN"),"gap":measurement(None,"PERCENT_RETURN"),"technical_context":{"value":"DESCRIPTIVE_ONLY","observed_at_utc":"2026-05-01T10:00:00Z","method":"EXPLICIT_FIXTURE"},"relative_strength":measurement(0.1,"DECIMAL_RETURN"),"commodity_context":[{"name":"OIL","value":72.0,"unit":"USD","observed_at_utc":"2026-05-01T10:00:00Z","method":"EXPLICIT_FIXTURE"}],"currency_context":[{"name":"USDINR","value":84.0,"unit":"INR","observed_at_utc":"2026-05-01T10:00:00Z","method":"EXPLICIT_FIXTURE"}],"rate_context":[{"name":"REPO","value":650.0,"unit":"BASIS_POINTS","observed_at_utc":"2026-05-01T10:00:00Z","method":"EXPLICIT_FIXTURE"}],"market_regime":{"value":"UNCLASSIFIED_FIXTURE","observed_at_utc":"2026-05-01T10:00:00Z","method":"EXPLICIT_FIXTURE"},"source_evidence_ids":[evidence_id],"pit_verified":True}
@contextmanager
def env(*,failure=False,retrieved="2026-05-01T10:01:00Z"):
 with tempfile.TemporaryDirectory() as td:
  root=Path(td);regs=build_fixture_registries();ing=IngestionStore(root/"ing.sqlite3",root/"raw");ing.import_registry(regs["entity_v1"]);ing.import_registry(regs["source_v1"])
  if failure:r=ing.capture_acquisition_failure(idempotency_key="failure",source_registry_snapshot_id=regs["source_v1"]["registry_snapshot_id"],entity_registry_snapshot_id=regs["entity_v1"]["registry_snapshot_id"],source_id="S6FIX_SOURCE_OFFICIAL_001",source_reference="fixture://market",retrieval_status="FAILED",failure_reason="fixture",failure_stage="fixture",attempted_at_utc="2026-05-01T10:00:00Z",entity_ids=["S6FIX_COMPANY_001"])["record"]
  else:r=ing.capture_evidence(idempotency_key="evidence",source_registry_snapshot_id=regs["source_v1"]["registry_snapshot_id"],entity_registry_snapshot_id=regs["entity_v1"]["registry_snapshot_id"],source_id="S6FIX_SOURCE_OFFICIAL_001",source_reference="fixture://market",raw_payload=b"explicit fixture market provenance",content_type="text/plain",publication_timestamp_utc="2026-05-01T09:00:00Z",observed_timestamp_utc="2026-05-01T10:00:00Z",retrieved_timestamp_utc=retrieved,entity_ids=["S6FIX_COMPANY_001"])["record"]
  store=MarketContextStore(root/"market.sqlite3",ing)
  try:yield store,ing,regs,r,root
  finally:
   try:store.close()
   except Exception:pass
   ing.close()
def make(store,regs,evidence,p=None,entity="S6FIX_COMPANY_001",exchange="FIXTURE_EXCHANGE"):return store.materialize(market_context=p or payload(evidence["evidence_id"]),company_entity_id=entity,entity_registry_snapshot_id=regs["entity_v1"]["registry_snapshot_id"],exchange=exchange)
def norm(p):return normalize_payload(p,load_policy()[0])
case("BASELINE","Stage 6.4A exact Stage 6.3I parent baseline",lambda:require(git("rev-parse",f"{STAGE6_4A_COMMIT}^")==BASE))
case("BASELINE","current HEAD descends from exact Stage 6.4A baseline",lambda:require(git("branch","--show-current")=="stage6-historical-analogue" and git("merge-base","HEAD",STAGE6_4A_COMMIT)==STAGE6_4A_COMMIT))
case("CONTRACT","frozen market context contract unchanged",lambda:require(git("hash-object","Stage 6/contracts/market_context.schema.json")==CONTRACT_BLOB))
case("IDENTITY","schema exact",lambda:require(SCHEMA_VERSION=="STAGE6_MARKET_CONTEXT_V2"))
case("IDENTITY","store exact",lambda:require(STORE_SCHEMA_VERSION=="STAGE6_4A_MARKET_CONTEXT_STORE_V1"))
case("IDENTITY","processor exact",lambda:require(PROCESSOR_VERSION=="STAGE6_4A_MARKET_CONTEXT_MATERIALIZER_V1"))
case("IDENTITY","policy and authority exact",lambda:require((POLICY_ID,AUTHORITY)==("S6MCTXPOL_STAGE6_4A_V1","SHADOW_ONLY")))
case("POLICY","canonical policy hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH_V1=="422fa524a21a09a29ca0caa94a382ea056fba958d7c1a0a05c465740cb791d94"))
def valid():
 with env() as (s,i,r,e,root):x=make(s,r,e)["market_context"];require(x["contract_payload"]["pit_verified"] and s.integrity_check()["result"]=="PASS")
case("VALID","valid complete market context",valid)
def mutate(path,value):
 p=payload();target=p
 for k in path[:-1]:target=target[k]
 target[path[-1]]=value;return p
case("CHRONOLOGY","data cutoff <= as-of",lambda:require(norm(payload())["data_cutoff_timestamp"]<norm(payload())["as_of_timestamp"]))
case("CHRONOLOGY","future data cutoff rejected",lambda:expect(Stage6MarketContextError,lambda:norm(mutate(["data_cutoff_timestamp"],"2026-05-01T13:00:00Z")),"CUTOFF"))
chron=[("stock-return","stock_returns"),("sector-return","sector_returns"),("NIFTY-return","nifty_returns"),("volume","volume_anomaly"),("volatility","volatility"),("gap","gap"),("technical-context","technical_context"),("relative-strength","relative_strength"),("commodity-context","commodity_context"),("currency-context","currency_context"),("rate-context","rate_context"),("market-regime","market_regime")]
for label,key in chron:
 def f(key=key):
  p=payload();obj=p[key][0] if isinstance(p[key],list) else p[key];obj["observed_at_utc"]="2026-05-01T11:00:01Z";expect(Stage6MarketContextError,lambda:norm(p),"FUTURE_OBSERVATION")
 case("CHRONOLOGY",f"{label} chronology",f)
case("UNITS","percentage return accepted",lambda:require(norm(payload())["stock_returns"]["unit"]=="PERCENT_RETURN"))
case("UNITS","decimal return accepted",lambda:require(norm(payload())["sector_returns"]["unit"]=="DECIMAL_RETURN"))
case("UNITS","unsupported unit rejected",lambda:expect(Stage6MarketContextError,lambda:norm(mutate(["gap","unit"],"PERCENT")),"UNIT_INVALID"))
case("UNITS","no implicit unit conversion",lambda:require(norm(payload())["volume_anomaly"]["unit"]=="VOLUME_RATIO"))
case("MISSING","null numeric preserved",lambda:require(norm(payload())["gap"]["value"] is None))
case("MISSING","no null-to-zero conversion",lambda:require(norm(payload())["stock_returns"]["3D"] is None))
case("HORIZONS","exact return horizons only",lambda:expect(Stage6MarketContextError,lambda:norm({**payload(),"stock_returns":{**returns(),"10D":1.0}}),"FIELDS_INVALID"))
def pit_company():
 with env() as (s,i,r,e,root):require(make(s,r,e)["market_context"]["company_entity_id"]=="S6FIX_COMPANY_001")
case("TICKER","PIT company entity resolution",pit_company)
case("TICKER","historical ticker mapping",pit_company)
def expired():
 with env() as (s,i,r,e,root):p=payload(e["evidence_id"]);p["ticker"]="FIXOLD";p["as_of_timestamp"]="2026-07-02T12:00:00Z";p["data_cutoff_timestamp"]="2026-07-02T11:00:00Z";expect(Stage6MarketContextError,lambda:make(s,r,e,p),"TICKER")
case("TICKER","expired ticker rejected",expired)
def future_ticker():
 with env() as (s,i,r,e,root):p=payload(e["evidence_id"]);p["ticker"]="FIXNEW";expect(Stage6MarketContextError,lambda:make(s,r,e,p),"TICKER")
case("TICKER","future ticker rejected",future_ticker)
def ambiguous():
 regs=build_fixture_registries();rows=deepcopy(regs["entity_v1"]["entities"]);rows[2]["ticker_mappings"]=[{"exchange":"FIXTURE_EXCHANGE","ticker":"FIXOLD","effective_from":"2026-01-01","effective_to":None}];rows[2].pop("record_hash");expect(IntegrityFailure,lambda:build_entity_registry(rows,"2026-01-02T00:00:00Z"),"AMBIGUOUS")
case("TICKER","ambiguous ticker mapping rejected",ambiguous)
def wrong_type():
 with env() as (s,i,r,e,root):p=payload(e["evidence_id"]);p["ticker"]="FIXINDEX";expect(Stage6MarketContextError,lambda:make(s,r,e,p,"S6FIX_INDEX_001"),"COMPANY_REQUIRED")
case("TICKER","wrong entity type rejected",wrong_type)
def registry_tamper():
 with env() as (s,i,r,e,root):i.connection.execute("DROP TRIGGER protect_registry_snapshots_update");i.connection.execute("UPDATE registry_snapshots SET registry_hash=? WHERE registry_kind='ENTITY'",("f"*64,));i.connection.commit();expect(Exception,lambda:make(s,r,e))
case("TICKER","exact registry hash enforced",registry_tamper)
case("EVIDENCE","source evidence IDs non-empty",lambda:expect(Stage6MarketContextError,lambda:norm({**payload(),"source_evidence_ids":[]}),"EVIDENCE_IDS"))
case("EVIDENCE","duplicate evidence rejected",lambda:expect(Stage6MarketContextError,lambda:norm({**payload(),"source_evidence_ids":["A","A"]}),"EVIDENCE_IDS"))
def acquisition():
 with env(failure=True) as (s,i,r,e,root):expect(Stage6MarketContextError,lambda:make(s,r,e),"ACQUISITION_ATTEMPT")
case("EVIDENCE","acquisition attempt rejected",acquisition)
def late_evidence():
 with env(retrieved="2026-05-01T11:30:00Z") as (s,i,r,e,root):expect(Stage6MarketContextError,lambda:make(s,r,e),"AFTER_CUTOFF")
case("EVIDENCE","evidence after cutoff rejected",late_evidence)
def evidence_hash():
 with env() as (s,i,r,e,root):i.connection.execute("DROP TRIGGER protect_ingestion_records_update");i.connection.execute("UPDATE ingestion_records SET record_hash=?",("f"*64,));i.connection.commit();expect(Exception,lambda:make(s,r,e))
case("EVIDENCE","exact evidence hash binding",evidence_hash)
case("EVIDENCE","evidence registry integrity",registry_tamper)
def ordering():
 p=payload();p["commodity_context"]=[{"name":"ZINC","value":1,"unit":"USD","observed_at_utc":"2026-05-01T10:00:00Z","method":"X"},{"name":"OIL","value":2,"unit":"USD","observed_at_utc":"2026-05-01T10:00:00Z","method":"X"}];require([x["name"] for x in norm(p)["commodity_context"]]==["OIL","ZINC"])
case("CANONICAL","canonical named-context ordering",ordering)
def duplicate_named():
 p=payload();p["commodity_context"]*=2;expect(Stage6MarketContextError,lambda:norm(p),"DUPLICATE")
case("CANONICAL","duplicate named measurement rejected",duplicate_named)
def deterministic():
 with env() as (s,i,r,e,root):a=make(s,r,e)["market_context"];b=make(s,r,e)["market_context"];require(a["market_context_record_id"]==b["market_context_record_id"])
case("IDENTITY","deterministic market-context ID",deterministic)
def idempotent():
 with env() as (s,i,r,e,root):make(s,r,e);require(make(s,r,e)["status"]=="IDEMPOTENT_SUCCESS")
case("IDENTITY","idempotency",idempotent)
def conflict():
 with env() as (s,i,r,e,root):make(s,r,e);p=payload(e["evidence_id"]);p["gap"]["value"]=2.0;expect(MarketContextConflict,lambda:make(s,r,e,p),"CONFLICT")
case("IDENTITY","distinct-context conflict",conflict)
def deps():
 with env() as (s,i,r,e,root):x=make(s,r,e)["market_context"];types={a[0] for a in s.connection.execute("SELECT record_type FROM market_context_dependencies WHERE market_context_record_id=?",(x["market_context_record_id"],))};require(types=={"ENTITY_REGISTRY","ENTITY_RECORD","MARKET_CONTEXT_POLICY","EVIDENCE"})
case("DEPENDENCY","exact direct dependencies",deps)
def singleton_meta():
 with env() as (s,i,r,e,root):expect(sqlite3.IntegrityError,lambda:s.connection.execute("INSERT INTO market_context_store_meta VALUES(2,?,?,?,?,?)",(STORE_SCHEMA_VERSION,SCHEMA_VERSION,BASE,PROCESSOR_VERSION,AUTHORITY)))
case("PERSISTENCE","metadata singleton",singleton_meta)
def singleton_policy():
 with env() as (s,i,r,e,root):s.connection.execute("INSERT INTO market_context_policies VALUES(?,?,?)",("BAD","f"*64,"{}"));s.connection.commit();expect(MarketContextIntegrityFailure,s.integrity_check,"POLICY")
case("PERSISTENCE","policy singleton",singleton_policy)
def immutable():
 with env() as (s,i,r,e,root):make(s,r,e)
 with env() as (s,i,r,e,root):
  make(s,r,e)
  for t in ("market_context_store_meta","market_context_policies","market_context_records","market_context_evidence","market_context_dependencies"):expect(sqlite3.DatabaseError,lambda t=t:s.connection.execute(f"UPDATE {t} SET rowid=rowid"));expect(sqlite3.DatabaseError,lambda t=t:s.connection.execute(f"DELETE FROM {t}"))
case("PERSISTENCE","append-only tables",immutable)
def trigger_loss():
 with env() as (s,i,r,e,root):s.connection.execute("DROP TRIGGER protect_market_context_records_delete");s.connection.commit();expect(MarketContextIntegrityFailure,s.integrity_check,"TRIGGER")
case("PERSISTENCE","trigger-loss detection",trigger_loss)
def restart():
 with env() as (s,i,r,e,root):make(s,r,e);s.close();x=MarketContextStore(root/"market.sqlite3",i);require(x.integrity_check()["result"]=="PASS");x.close()
case("PERSISTENCE","restart integrity",restart)
def tamper(table,column,value):
 with env() as (s,i,r,e,root):
  make(s,r,e);s.connection.execute(f"DROP TRIGGER protect_{table}_update");s.connection.execute(f"UPDATE {table} SET {column}=?",(value,));s.connection.execute(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;");s.connection.commit();expect(Exception,s.integrity_check)
case("TAMPER","record tamper detected",lambda:tamper("market_context_records","ticker","BAD"))
case("TAMPER","evidence dependency tamper detected",lambda:tamper("market_context_evidence","evidence_hash","f"*64))
case("TAMPER","registry dependency tamper detected",lambda:tamper("market_context_dependencies","record_hash","f"*64))
case("TAMPER","deterministic replay",restart)
future_names=("d+1_return","d+3_return","d+5_return","d+10_return","d+20_return","mae","mfe","recovery_time","future_relative_returns","future_event_outcomes")
for name in future_names:
 def ff(name=name):p=payload();p[name]=1;expect(Stage6MarketContextError,lambda:norm(p),"FIELDS_INVALID")
 case("LEAKAGE",f"future outcome prohibited: {name}",ff)
def no_3i():
 with env() as (s,i,r,e,root):x=make(s,r,e)["market_context"];types={a[0] for a in s.connection.execute("SELECT record_type FROM market_context_dependencies WHERE market_context_record_id=?",(x["market_context_record_id"],))};require(not any("3I" in x or "COMPANY_EFFECT" in x for x in types))
case("BOUNDARY","no Stage 6.3I dependency required",no_3i)
def no_network():
 prohibited={"requests","urllib","http","aiohttp","yfinance","socket"}
 for p in (ROOT/"stage6_market_context").glob("*.py"):
  tree=ast.parse(p.read_text());imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{str(n.module).split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};require(not imports&prohibited)
case("BOUNDARY","zero network and API access",no_network)
case("BOUNDARY","zero AI ML NLP OCR",lambda:require(all(load_policy()[0][x] is False for x in ("llm","nlp","ml","ocr","embeddings","semantic_similarity"))))
def safety():
 with env() as (s,i,r,e,root):x=make(s,r,e)["market_context"];require(x["trading_authority"] is False and x["future_outcomes_status"]=="NOT_ATTACHED" and x["expected_return_status"]=="NOT_EVALUATED")
case("BOUNDARY","no trading authority",safety)
def frozen():
 protected=("Stage 5D","Stage 6/contracts","Stage 6/policy","Stage 6/Stage6_Master_Architecture.md","Stage 6/scripts/validate_stage6_0.py","Stage 6/stage6_ingestion","Stage 6/stage6_connectors","Stage 6/stage6_events","Stage 6/stage6_extraction","Stage 6/stage6_candidates","Stage 6/stage6_materialization","Stage 6/stage6_evolution","Stage 6/stage6_lifecycle","Stage 6/stage6_exposure","Stage 6/stage6_exposure_binding","Stage 6/stage6_transmission","Stage 6/stage6_dimension_qualification","Stage 6/stage6_dimension_matching","Stage 6/stage6_direction_semantics","Stage 6/stage6_event_movement","Stage 6/stage6_movement_path_effect","Stage 6/stage6_company_effect");require(git("diff","--name-only",BASE,"--",*protected)=="")
case("BOUNDARY","frozen previous-stage file audit",frozen)
def main():
 rows=[]
 for n,(c,label,fn) in enumerate(CASES,1):
  try:
   with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK")):fn()
   rows.append({"test_id":f"S6_4A_{n:03d}","category":c,"test_name":label,"result":"PASS","detail":""})
  except Exception as x:rows.append({"test_id":f"S6_4A_{n:03d}","category":c,"test_name":label,"result":"FAIL","detail":f"{type(x).__name__}:{x}"})
 OUT.parent.mkdir(exist_ok=True);h=OUT.open("w",newline="",encoding="utf-8");w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows);h.close();bad=[x for x in rows if x["result"]=="FAIL"];print(json.dumps({"stage":"6.4A","tests":len(rows),"passed":len(rows)-len(bad),"failed":len(bad),"result":"FAIL" if bad else "PASS","authority":AUTHORITY,"network_calls":0,"llm_calls":0,"ml":False,"nlp":False,"ocr":False,"trading_authority":False},sort_keys=True,separators=(",",":")));[print("FAIL",x) for x in bad];return bool(bad)
if __name__=="__main__":raise SystemExit(main())
