"""Stage 6.6A immutable initial-thesis seed acceptance tests."""
from __future__ import annotations
import ast,csv,json,sqlite3,subprocess,sys,tempfile
from copy import deepcopy
from pathlib import Path

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent
sys.path.insert(0,str(ROOT))
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_thesis_seed import *
from stage6_thesis_seed.fill_math import PRECISION,aggregate_fills
from stage6_thesis_seed.policy import *
from stage6_thesis_seed.thesis_seed_builder import SAFETY,build_seed

BASE="8696e7aa4e179cbe4f4fd2413d79643299260f97";STAGE5D5="74b2710f0e19bd403978da81e87f25a3059ace06"
THESIS_BLOB="2cc390a2cb85d938062511408293adcaf84ea288";PORTFOLIO_BLOB="5900278a891dc70c63ce02f69002b5e9dec13799";HISTORICAL_BLOB="85a2b0d00cacd6a3caea484e3ef3071eb16fe01d";MARKET_BLOB="a141b221228718b8276b3d05b2f028d21adcfc3f"
OUT=ROOT/"results"/"stage6_6a_test_results.csv";CASES=[];CTX={}
def case(name,fn):CASES.append((name,fn))
def require(value,message="assertion failed"):
    if not value:raise AssertionError(message)
def expect(error,fn,contains=None):
    try:fn()
    except error as exc:
        if contains:require(contains in str(exc),str(exc))
        return
    raise AssertionError("expected "+error.__name__)
def git(*args):return subprocess.check_output(["git",*args],cwd=REPO,text=True).strip()
def changed(value,path,replacement):
    result=deepcopy(value);target=result
    for key in path[:-1]:target=target[key]
    target[path[-1]]=replacement;return result
def fixture():return deepcopy(json.loads((ROOT/"fixtures"/"stage6_6a"/"initial_thesis_seed_examples.json").read_text(encoding="utf-8"))["examples"][0])
def result_count(name):
    rows=list(csv.DictReader((ROOT/"results"/name).open(encoding="utf-8")));return len(rows),sum(x["result"]=="PASS" for x in rows)

class FakeEvidenceStore:
    def __init__(self,records=(),passes=True):
        self.passes=passes;self.connection=sqlite3.connect(":memory:");self.connection.execute("CREATE TABLE ingestion_records(record_id TEXT PRIMARY KEY,canonical_json TEXT NOT NULL)")
        self.connection.executemany("INSERT INTO ingestion_records VALUES(?,?)",[(x["evidence_id"],canonical_json(x)) for x in records])
    def integrity_check(self):
        if not self.passes:raise RuntimeError("bad evidence store")
        return {"result":"PASS"}
    def close(self):self.connection.close()
def evidence(identity="S6EV_A",retrieved="2026-09-28T10:00:00.000000Z",kind="EVIDENCE"):
    return {"schema_version":"STAGE6_EVIDENCE_V2","record_kind":kind,"evidence_id":identity,"retrieved_timestamp_utc":retrieved,"record_hash":canonical_hash({"id":identity,"kind":kind})}
def make_store(source=None,evidence_store=None):
    folder=tempfile.TemporaryDirectory(prefix="stage6_6a_");store=ThesisSeedStore(Path(folder.name)/"seed.sqlite3",evidence_store);record=store.freeze(source or fixture())["initial_thesis_seed"];return folder,store,record

# Baseline, branch, frozen identities, and regression evidence.
case("exact Stage 6.5D ancestor",lambda:require(git("merge-base","HEAD",BASE)==BASE))
case("branch exact",lambda:require(git("branch","--show-current")=="stage6-persistent-thesis"))
case("Stage 6.5D 200",lambda:require(result_count("stage6_5d_test_results.csv")== (200,200)))
PRIOR=[f"stage6_{x}_test_results.csv" for x in ("1a","1b","1c","2a","2b","2c","2d","2e","2f","3a","3b","3c","3d","3e","3f","3g","3h","3i","4a","4b","4c","4d","4e","5a","5b","5c")]
case("prior total 2127",lambda:require(sum(result_count(x)[0] for x in PRIOR)==2127 and sum(result_count(x)[1] for x in PRIOR)==2127))
case("current prior total 2327",lambda:require(sum(result_count(x)[0] for x in PRIOR+["stage6_5d_test_results.csv"])==2327 and sum(result_count(x)[1] for x in PRIOR+["stage6_5d_test_results.csv"])==2327))
for label,path,wanted in (("trade thesis","trade_thesis.schema.json",THESIS_BLOB),("portfolio","portfolio_context.schema.json",PORTFOLIO_BLOB),("historical","historical_analogue.schema.json",HISTORICAL_BLOB),("market","market_context.schema.json",MARKET_BLOB)):
    case(label+" blob",lambda path=path,wanted=wanted:require(git("hash-object",f"Stage 6/contracts/{path}")==wanted))
for label,actual,wanted in (("schema",SCHEMA_VERSION,"STAGE6_INITIAL_THESIS_SEED_V1"),("store",STORE_SCHEMA_VERSION,"STAGE6_6A_INITIAL_THESIS_SEED_STORE_V1"),("processor",PROCESSOR_VERSION,"STAGE6_6A_INITIAL_THESIS_SEED_FREEZER_V1"),("policy",POLICY_ID,"S6THSEEDPOL_STAGE6_6A_V1"),("contract",SEED_CONTRACT_VERSION,"STAGE6_INITIAL_THESIS_SEED_CONTRACT_V1"),("semantics",SEMANTIC_PROJECTION_VERSION,"STAGE6_INITIAL_THESIS_SEMANTICS_V1"),("authority",AUTHORITY,"SHADOW_ONLY"),("baseline",BASELINE_COMMIT,BASE),("Stage 5D.5",STAGE5D5_COMMIT,STAGE5D5)):
    case(label+" identity",lambda actual=actual,wanted=wanted:require(actual==wanted))
case("policy canonical hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH_V1))
case("contract canonical hash",lambda:require(load_seed_contract()[2]==EXPECTED_SEED_CONTRACT_HASH_V1))
case("decimal precision 50",lambda:require(PRECISION==50))

# Source validation and immutable semantics.
case("valid fixture",lambda:require(validate_source(fixture()) is not None))
for field in ("source_export_id","source_database_id","source_schema_version","recommendation_id","ticker","holding_horizon"):
    case(field+" required",lambda field=field:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),[field],""))))
case("export hash required",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["source_export_hash"],"x"))))
case("wrong source rejected",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["source_system"],"LIVE"))))
def production(commit=STAGE5D5):
    x=fixture();x["source_system"]="STAGE5D5_THESIS_SEED_EXPORT";x["source_stage5d5_commit"]=commit;return x
case("exact Stage5D5 export accepted",lambda:require(validate_source(production()) is not None))
case("wrong Stage5D5 commit rejected",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(production("0"*40))))
case("fixture commit prohibited",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["source_stage5d5_commit"],STAGE5D5))))
for field in ("record_type","record_id","record_hash","recorded_at_utc"):
    case("binding "+field+" required",lambda field=field:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["recommendation_binding",field],""))))
case("binding recommendation exact",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["recommendation_binding","record_id"],"OTHER"))))
case("binding future rejected",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["recommendation_binding","recorded_at_utc"],"2026-09-29T00:00:00Z"))))
case("rationale nonempty",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["entry_rationale"],[]))))
case("rationale string nonempty",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["entry_rationale"],[""]))))
case("empty risks explicit accepted",lambda:require(validate_source(changed(fixture(),["known_risks"],[])) is not None))
case("missing risks rejected",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source({k:v for k,v in fixture().items() if k!="known_risks"})))
case("invalidations required",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["invalidation_conditions"],[]))))
for field,value in (("low",0),("high",0),("low",3000),("currency","USD")):
    path=["initial_entry_range",field];replacement=value
    case("entry range rejects "+field+str(value),lambda path=path,replacement=replacement:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),path,replacement))))
for field in ("initial_stop","initial_target"):
    case(field+" nullable",lambda field=field:require(validate_source(changed(fixture(),[field],None)) is not None))
    case(field+" positive",lambda field=field:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),[field,"value"],0))))
    case(field+" INR",lambda field=field:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),[field,"currency"],"USD"))))

# Fill rules and arithmetic.
case("zero fills accepted",lambda:require(validate_source(changed(fixture(),["fills"],[])) is not None))
case("one fill accepted",lambda:require(validate_source(changed(fixture(),["fills"],[fixture()["fills"][0]])) is not None))
case("multiple fills accepted",lambda:require(validate_source(fixture()) is not None))
case("duplicate transaction rejected",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["fills",1,"transaction_id"],"TXN_002"))))
case("fill recommendation mismatch",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["fills",0,"recommendation_id"],"OTHER"))))
for value in (0,-1,1.5,True):case("invalid fill quantity "+str(value),lambda value=value:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["fills",0,"quantity"],value))))
for value in (0,-1,float("inf"),float("nan")):case("invalid fill price "+str(value),lambda value=value:expect((ThesisSeedIntegrityFailure,Stage6ThesisSeedError),lambda:validate_source(changed(fixture(),["fills",0,"price"],value))))
case("fill INR exact",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["fills",0,"currency"],"USD"))))
case("fill source exact",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["fills",0,"source_system"],"FIXTURE"))))
case("fill date cutoff",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["fills",0,"fill_date"],"2026-09-29"))))
case("fill provenance cutoff",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["fills",0,"source_recorded_at_utc"],"2026-09-29T00:00:00Z"))))
case("fill hash exact",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["fills",0,"source_record_hash"],"bad"))))
case("aggregate zero null",lambda:require(aggregate_fills([])==(None,None)))
case("aggregate one exact",lambda:require(aggregate_fills([fixture()["fills"][0]])[0]["volume_weighted_average_price"]==2940))
case("aggregate quantity",lambda:require(aggregate_fills(fixture()["fills"])[0]["total_quantity"]==15))
case("aggregate VWAP",lambda:require(aggregate_fills(fixture()["fills"])[0]["volume_weighted_average_price"]==2920))
case("earliest fill date",lambda:require(aggregate_fills(fixture()["fills"])[1]=="2026-09-27"))

# Constructed projection and no-final-thesis boundary.
def R():return CTX["record"]
for field in ("source_system","source_stage5d5_commit","source_export_id","source_export_hash","source_database_id","source_schema_version","recommendation_id","ticker","holding_horizon","entry_rationale","known_risks","initial_entry_range","initial_stop","initial_target","invalidation_conditions","supporting_evidence_ids"):
    case("source preserved "+field,lambda field=field:require(R()[field]==fixture()[field]))
case("fills canonical",lambda:require([x["transaction_id"] for x in R()["original_fill_audit_records"]]==["TXN_001","TXN_002"]))
case("caller order irrelevant",lambda:require(build_seed(changed(fixture(),["fills"],list(reversed(fixture()["fills"]))),[],CTX["policy_hash"],CTX["contract_hash"])["seed_record_id"]==R()["seed_record_id"]))
case("projected fill fields closed",lambda:require(all(set(x)=={"transaction_id","fill_date","quantity","price","currency","source_system"} for x in R()["projected_fill_references"])))
case("audit hashes retained",lambda:require(all("source_record_hash" in x for x in R()["original_fill_audit_records"])))
case("audit hashes not projected",lambda:require(all("source_record_hash" not in x for x in R()["projected_fill_references"])))
case("entry range not fill-derived",lambda:require(R()["initial_entry_range"]==fixture()["initial_entry_range"]))
for field,wanted in (("version",1),("decision_cutoff",fixture()["decision_cutoff"]),("recommendation_id","REC_001"),("ticker","RELIANCE.NS"),("derived_entry_date","2026-09-27"),("holding_horizon",fixture()["holding_horizon"]),("thesis_status","THESIS_UNCHANGED"),("last_review_date","2026-09-28"),("previous_version_hash",None)):
    case("semantic "+field,lambda field=field,wanted=wanted:require(R()["initial_thesis_semantic_projection"][field]==wanted))
case("current stop initial",lambda:require(R()["initial_thesis_semantic_projection"]["current_stop"]==R()["initial_stop"]))
case("current target initial",lambda:require(R()["initial_thesis_semantic_projection"]["current_target"]==R()["initial_target"]))
for field,wanted in (("version",1),("change_type","INITIAL_THESIS_CREATED"),("reason","INITIAL_BASELINE_FROM_IMMUTABLE_SEED"),("changed_at_semantic",fixture()["decision_cutoff"]),("evidence_ids",[])):
    case("change semantic "+field,lambda field=field,wanted=wanted:require(R()["initial_thesis_semantic_projection"]["initial_change_semantics"][field]==wanted))
for prohibited in ("thesis_id","code_commit","change_history","input_records"):
    case("no final "+prohibited,lambda prohibited=prohibited:require(prohibited not in R()))
case("Trade Thesis V2 not materialized",lambda:require(R()["trade_thesis_v2_status"]=="NOT_MATERIALIZED"))
case("deterministic seed ID",lambda:require(R()["seed_record_id"]=="S6THSEED_"+canonical_hash(without(R(),"seed_record_id","record_hash"))[:24]))
case("deterministic record hash",lambda:require(R()["record_hash"]==canonical_hash(without(R(),"record_hash"))))
for key,value in SAFETY.items():case("safety "+key,lambda key=key,value=value:require(R()[key]==value))

# Evidence binding and PIT.
def evidence_freeze(record,passes=True):
    source=fixture();source["supporting_evidence_ids"]=[record["evidence_id"]];store=FakeEvidenceStore([record],passes);folder=tempfile.TemporaryDirectory();seed=ThesisSeedStore(Path(folder.name)/"x.sqlite3",store)
    try:return seed.freeze(source)["initial_thesis_seed"]
    finally:seed.close();store.close();folder.cleanup()
case("empty evidence accepted",lambda:require(R()["evidence_bindings"]==[]))
case("evidence exact binding",lambda:require(evidence_freeze(evidence())["evidence_bindings"]==[{"record_type":"STAGE6_EVIDENCE_V2","record_id":"S6EV_A","record_hash":evidence()["record_hash"]}]))
case("future evidence rejected",lambda:expect(ThesisSeedIntegrityFailure,lambda:evidence_freeze(evidence(retrieved="2026-09-29T00:00:00Z"))))
case("acquisition attempt rejected",lambda:expect(ThesisSeedIntegrityFailure,lambda:evidence_freeze(evidence(kind="ACQUISITION_ATTEMPT"))))
case("evidence store integrity required",lambda:expect(ThesisSeedIntegrityFailure,lambda:evidence_freeze(evidence(),False)))
case("duplicate evidence IDs rejected",lambda:expect(ThesisSeedIntegrityFailure,lambda:validate_source(changed(fixture(),["supporting_evidence_ids"],["A","A"]))))
def missing_evidence():
    source=fixture();source["supporting_evidence_ids"]=["S6EV_MISSING"];backing=FakeEvidenceStore([]);folder=tempfile.TemporaryDirectory();store=ThesisSeedStore(Path(folder.name)/"x.sqlite3",backing)
    try:return store.freeze(source)
    finally:store.close();backing.close();folder.cleanup()
case("missing evidence rejected",lambda:expect(Stage6ThesisSeedError,missing_evidence))

# Persistence, restart, conflicts, append-only and tamper detection.
case("created status",lambda:require(CTX["created"]=="CREATED"))
case("store integrity",lambda:require(CTX["store"].integrity_check()["result"]=="PASS"))
case("idempotent exact",lambda:require(CTX["store"].freeze(fixture())["status"]=="IDEMPOTENT_SUCCESS"))
case("export conflict",lambda:expect(ThesisSeedConflict,lambda:CTX["store"].freeze(changed(fixture(),["source_export_hash"],"f"*64))))
for table in ("thesis_seed_store_meta","thesis_seed_policies","thesis_seed_contracts","thesis_seed_records","thesis_seed_fills","thesis_seed_source_bindings","thesis_seed_dependencies"):
    case(table+" update blocked",lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"UPDATE {table} SET rowid=rowid")))
    case(table+" delete blocked",lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"DELETE FROM {table}")))
case("all trigger pairs present",lambda:require(all(len(CTX["store"].connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,)).fetchall())==2 for t in ("thesis_seed_store_meta","thesis_seed_policies","thesis_seed_contracts","thesis_seed_records","thesis_seed_fills","thesis_seed_source_bindings","thesis_seed_evidence_bindings","thesis_seed_dependencies"))))
case("source binding persisted",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM thesis_seed_source_bindings").fetchone()[0]==1))
case("fills persisted",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM thesis_seed_fills").fetchone()[0]==2))
case("policy dependency",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM thesis_seed_dependencies WHERE record_type='STAGE6_6A_POLICY'").fetchone()[0]==1))
case("contract dependency",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM thesis_seed_dependencies WHERE record_type='STAGE6_6A_SEED_CONTRACT'").fetchone()[0]==1))
for forbidden in ("STAGE6_PORTFOLIO_CONTEXT_V2","STAGE6_HISTORICAL_ANALOGUE_V2","EVENT","EXPOSURE_GRAPH","MARKET_CONTEXT"):
    case("no dependency "+forbidden,lambda forbidden=forbidden:require(CTX["store"].connection.execute("SELECT count(*) FROM thesis_seed_dependencies WHERE record_type=?",(forbidden,)).fetchone()[0]==0))
def restart():
    CTX["store"].close();CTX["store"]=ThesisSeedStore(CTX["db"]);return CTX["store"].integrity_check()["result"]
case("restart integrity",lambda:require(restart()=="PASS"))
def tamper(table,statement,with_evidence=False):
    backing=None;source=fixture()
    if with_evidence:
        item=evidence();backing=FakeEvidenceStore([item]);source["supporting_evidence_ids"]=[item["evidence_id"]]
    folder=tempfile.TemporaryDirectory();store=ThesisSeedStore(Path(folder.name)/"tamper.sqlite3",backing);store.freeze(source)
    try:
        store.connection.execute(f"DROP TRIGGER protect_{table}_update");store.connection.execute(statement);store.connection.commit()
        return store.integrity_check()
    finally:store.close();folder.cleanup();backing.close() if backing else None
case("trigger-loss detection",lambda:expect(ThesisSeedIntegrityFailure,lambda:tamper("thesis_seed_records","UPDATE thesis_seed_records SET source_export_hash=source_export_hash"),"TRIGGER_MISSING"))
case("seed tamper detection",lambda:expect(ThesisSeedIntegrityFailure,lambda:tamper("thesis_seed_records","UPDATE thesis_seed_records SET canonical_json='{}'")))
case("typed seed tamper detection",lambda:expect(ThesisSeedIntegrityFailure,lambda:tamper("thesis_seed_records","UPDATE thesis_seed_records SET source_export_hash='"+("0"*64)+"'")))
case("fill tamper detection",lambda:expect(ThesisSeedIntegrityFailure,lambda:tamper("thesis_seed_fills","UPDATE thesis_seed_fills SET canonical_json='{}'")))
case("source-binding tamper detection",lambda:expect(ThesisSeedIntegrityFailure,lambda:tamper("thesis_seed_source_bindings","UPDATE thesis_seed_source_bindings SET record_hash='"+("0"*64)+"'")))
case("dependency tamper detection",lambda:expect(ThesisSeedIntegrityFailure,lambda:tamper("thesis_seed_dependencies","UPDATE thesis_seed_dependencies SET record_hash='"+("0"*64)+"'")))
case("evidence-binding tamper detection",lambda:expect(ThesisSeedIntegrityFailure,lambda:tamper("thesis_seed_evidence_bindings","UPDATE thesis_seed_evidence_bindings SET record_hash='"+("0"*64)+"'",True)))
case("policy tamper detection",lambda:expect(ThesisSeedIntegrityFailure,lambda:tamper("thesis_seed_policies","UPDATE thesis_seed_policies SET canonical_json='{}'")))
case("contract tamper detection",lambda:expect(ThesisSeedIntegrityFailure,lambda:tamper("thesis_seed_contracts","UPDATE thesis_seed_contracts SET canonical_json='{}'")))
case("SQLite integrity checked",lambda:require(CTX["store"].connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"))
case("foreign keys checked",lambda:require(CTX["store"].connection.execute("PRAGMA foreign_key_check").fetchall()==[]))
case("rationale order preserved",lambda:require(R()["entry_rationale"]==fixture()["entry_rationale"]))
case("risk order preserved",lambda:require(R()["known_risks"]==fixture()["known_risks"]))
case("invalidations not evaluated",lambda:require(R()["thesis_review_status"]=="NOT_EVALUATED" and R()["invalidation_conditions"]==fixture()["invalidation_conditions"]))
case("no fee fields",lambda:require(not any(k in canonical_json(R()["aggregate_fill"]).lower() for k in ("fee","commission","slippage"))))

# Static authority/network/AI/runtime boundaries.
def source_text():return "\n".join(p.read_text(encoding="utf-8") for p in (ROOT/"stage6_thesis_seed").glob("*.py"))
def imports():
    found=set()
    for path in (ROOT/"stage6_thesis_seed").glob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"));found|={x.names[0].name for x in ast.walk(tree) if isinstance(x,ast.Import)};found|={str(x.module) for x in ast.walk(tree) if isinstance(x,ast.ImportFrom)}
    return found
for token in ("requests","urllib","httpx","aiohttp","socket","selenium","yfinance","gdelt","openai","transformers","torch","tensorflow","sklearn"):
    case("no prohibited import "+token,lambda token=token:require(not any(x==token or x.startswith(token+".") for x in imports())))
case("broker calls zero",lambda:require(R()["broker_calls"]==0))
case("embeddings disabled",lambda:require(R()["embeddings"] is False))
case("no BUY SELL HOLD decision",lambda:require(R()["buy_sell_hold_status"]=="NOT_EVALUATED"))
case("no Stage5 runtime import",lambda:require(not any("stage5" in x.lower() for x in imports())))
case("no live SQLite path",lambda:require("Stage 5D" not in source_text()))
case("only stdlib and ingestion canonical import",lambda:require(imports()<={"ast","copy","decimal","hashlib","json","math","pathlib","re","sqlite3","datetime","stage6_ingestion.canonical","errors","fill_math","policy","thesis_seed_builder","thesis_seed_store","thesis_seed_validation"}))
case("fixture only policy",lambda:require(load_policy()[0]["accepted_source_systems"]==["FIXTURE","STAGE5D5_THESIS_SEED_EXPORT"]))
case("zero network policy",lambda:require(load_policy()[0]["network_calls"]==0 and load_policy()[0]["external_apis"]==0))
case("zero AI policy",lambda:require(load_policy()[0]["ai"] is False))
case("trading false policy",lambda:require(load_policy()[0]["trading_authority"] is False))

def main():
    temp=tempfile.TemporaryDirectory(prefix="stage6_6a_main_");CTX["temp"]=temp;CTX["db"]=Path(temp.name)/"seed.sqlite3";CTX["store"]=ThesisSeedStore(CTX["db"]);CTX["policy_hash"]=CTX["store"].policy_hash;CTX["contract_hash"]=CTX["store"].contract_hash
    result=CTX["store"].freeze(fixture());CTX["created"]=result["status"];CTX["record"]=result["initial_thesis_seed"]
    rows=[]
    for index,(name,fn) in enumerate(CASES,1):
        try:fn();rows.append({"test_id":index,"test_name":name,"result":"PASS","detail":""})
        except Exception as exc:rows.append({"test_id":index,"test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}: {exc}"})
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=("test_id","test_name","result","detail"));writer.writeheader();writer.writerows(rows)
    passed=sum(x["result"]=="PASS" for x in rows);print(f"Stage 6.6A: {passed}/{len(rows)} PASS")
    for row in rows:
        if row["result"]!="PASS":print(row)
    try:CTX["store"].close()
    except Exception:pass
    temp.cleanup();return 0 if passed==len(rows) and len(rows)>=150 else 1
if __name__=="__main__":raise SystemExit(main())
