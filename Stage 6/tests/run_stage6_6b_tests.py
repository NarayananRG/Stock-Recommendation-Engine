import ast
import csv
import json
import sqlite3
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent
sys.path.insert(0,str(ROOT))

from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from stage6_thesis_seed.thesis_seed_store import ThesisSeedStore
from stage6_trade_thesis.errors import Stage6TradeThesisError,TradeThesisConflict,TradeThesisIntegrityFailure
from stage6_trade_thesis.policy import *
from stage6_trade_thesis.trade_thesis_builder import SAFETY,build_materialization_record,build_trade_thesis
from stage6_trade_thesis.trade_thesis_store import TABLES,TradeThesisStore
from stage6_trade_thesis.trade_thesis_validation import THESIS_FIELDS,WRAPPER_FIELDS,validate_materialization_record,validate_trade_thesis

OUT=ROOT/"results"/"stage6_6b_test_results.csv";CASES=[];CTX={}
def case(group,name,fn):CASES.append((group,name,fn))
def require(value,message="assertion failed"):
    if not value:raise AssertionError(message)
def expect(exc,fn,contains=None):
    try:fn()
    except exc as caught:
        if contains is not None:require(contains in str(caught),f"{contains!r} not in {caught!r}")
        return
    raise AssertionError(f"expected {exc}")
def changed(value,path,replacement):
    out=deepcopy(value);cursor=out
    for key in path[:-1]:cursor=cursor[key]
    cursor[path[-1]]=replacement;return out
def git(*args):return subprocess.check_output(["git",*args],cwd=REPO,text=True).strip()
def seed_source():return json.loads((ROOT/"fixtures"/"stage6_6a"/"initial_thesis_seed_examples.json").read_text(encoding="utf-8"))["examples"][0]
def fixture():return json.loads((ROOT/"fixtures"/"stage6_6b"/"initial_trade_thesis_examples.json").read_text(encoding="utf-8"))

# Immutable identities and baseline ancestry.
for label,actual,wanted in (("schema",SCHEMA_VERSION,"STAGE6_TRADE_THESIS_V2"),("wrapper",WRAPPER_SCHEMA_VERSION,"STAGE6_6B_TRADE_THESIS_MATERIALIZATION_RECORD_V1"),("store",STORE_SCHEMA_VERSION,"STAGE6_6B_TRADE_THESIS_STORE_V1"),("processor",PROCESSOR_VERSION,"STAGE6_6B_INITIAL_THESIS_MATERIALIZER_V1"),("policy",POLICY_ID,"S6THMATPOL_STAGE6_6B_V1"),("contract",MATERIALIZATION_CONTRACT_VERSION,"STAGE6_INITIAL_THESIS_MATERIALIZATION_CONTRACT_V1"),("semantics",THESIS_ENGINE_VERSION,"STAGE6_INITIAL_THESIS_SEMANTICS_V1"),("authority",AUTHORITY,"SHADOW_ONLY"),("baseline",BASELINE_COMMIT,"1672ab7ed7322b8dc4406ab5ea556325977bc8cd"),("blob",TRADE_THESIS_BLOB,"2cc390a2cb85d938062511408293adcaf84ea288")):
    case("IDENTITY",label,lambda actual=actual,wanted=wanted:require(actual==wanted))
case("IDENTITY","HEAD contains baseline",lambda:require(git("merge-base","HEAD",BASELINE_COMMIT)==BASELINE_COMMIT))
case("IDENTITY","baseline exact parent",lambda:require(git("rev-parse",BASELINE_COMMIT+"^")=="8696e7aa4e179cbe4f4fd2413d79643299260f97"))
case("IDENTITY","branch exact",lambda:require(git("branch","--show-current")=="stage6-persistent-thesis"))
case("IDENTITY","frozen schema hash",lambda:require(git_blob(ROOT/"contracts"/"trade_thesis.schema.json")==TRADE_THESIS_BLOB))
case("IDENTITY","policy hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH_V1))
case("IDENTITY","contract hash",lambda:require(load_materialization_contract()[2]==EXPECTED_MATERIALIZATION_CONTRACT_HASH_V1))
case("IDENTITY","fixture version",lambda:require(fixture()["fixture_version"]=="STAGE6_6B_FIXTURES_V1"))

# Final projection and exact frozen schema closure.
def T():return CTX["thesis"]
def W():return CTX["wrapper"]
case("MATERIALIZE","valid thesis",lambda:require(validate_trade_thesis(T(),CTX["seed"])==T()))
case("MATERIALIZE","valid wrapper",lambda:require(validate_materialization_record(W(),CTX["seed"])==W()))
case("MATERIALIZE","closed thesis fields",lambda:require(set(T())==THESIS_FIELDS))
case("MATERIALIZE","closed wrapper fields",lambda:require(set(W())==WRAPPER_FIELDS))
for field in sorted(THESIS_FIELDS):
    case("SCHEMA",field+" required",lambda field=field:expect(TradeThesisIntegrityFailure,lambda:validate_trade_thesis({k:v for k,v in T().items() if k!=field})))
case("SCHEMA","extra thesis field rejected",lambda:expect(TradeThesisIntegrityFailure,lambda:validate_trade_thesis(T()|{"extra":1})))
for field in sorted(WRAPPER_FIELDS):
    case("WRAPPER",field+" required",lambda field=field:expect(TradeThesisIntegrityFailure,lambda:validate_materialization_record({k:v for k,v in W().items() if k!=field})))
case("WRAPPER","extra wrapper field rejected",lambda:expect(TradeThesisIntegrityFailure,lambda:validate_materialization_record(W()|{"extra":1})))

semantic_map={"decision_cutoff":"decision_cutoff","recommendation_id":"recommendation_id","ticker":"ticker","entry_date":"derived_entry_date","holding_horizon":"holding_horizon","entry_rationale":"entry_rationale","supporting_evidence":"supporting_evidence_ids","known_risks":"known_risks","initial_entry_range":"initial_entry_range","fill_references":"projected_fill_references","aggregate_fill":"aggregate_fill","initial_stop":"initial_stop","current_stop":"current_stop","initial_target":"initial_target","current_target":"current_target","invalidation_conditions":"invalidation_conditions","thesis_status":"thesis_status","last_review_date":"last_review_date","previous_version_hash":"previous_version_hash"}
for target,source in semantic_map.items():case("PROJECTION",target+" exact",lambda target=target,source=source:require(T()[target]==CTX["seed"]["initial_thesis_semantic_projection"][source]))
case("PROJECTION","one input",lambda:require(len(T()["input_records"])==1))
case("PROJECTION","input seed type",lambda:require(T()["input_records"][0]["record_type"]=="STAGE6_INITIAL_THESIS_SEED_V1"))
case("PROJECTION","input seed id",lambda:require(T()["input_records"][0]["record_id"]==CTX["seed"]["seed_record_id"]))
case("PROJECTION","input seed hash",lambda:require(T()["input_records"][0]["record_hash"]==CTX["seed"]["record_hash"]))
case("PROJECTION","version one",lambda:require(T()["version"]==1))
case("PROJECTION","code is baseline",lambda:require(T()["code_commit"]==BASELINE_COMMIT))
case("PROJECTION","current stop equals initial",lambda:require(T()["current_stop"]==T()["initial_stop"]))
case("PROJECTION","current target equals initial",lambda:require(T()["current_target"]==T()["initial_target"]))
case("PROJECTION","one change",lambda:require(len(T()["change_history"])==1))
for field,wanted in (("version",1),("changed_at_utc",seed_source()["decision_cutoff"]),("decision_cutoff",seed_source()["decision_cutoff"]),("change_type","INITIAL_THESIS_CREATED"),("reason","INITIAL_BASELINE_FROM_IMMUTABLE_SEED"),("evidence_ids",[]),("input_records",None)):
    case("CHANGE_HISTORY",field+" exact",lambda field=field,wanted=wanted:require(T()["change_history"][0][field]==(T()["input_records"] if field=="input_records" else wanted)))
case("HASH","thesis prefix",lambda:require(T()["thesis_id"].startswith("S6THESIS_")))
case("HASH","deterministic thesis id",lambda:require(T()["thesis_id"]=="S6THESIS_"+canonical_hash(without(T(),"thesis_id","record_hash"))[:24]))
case("HASH","deterministic thesis hash",lambda:require(T()["record_hash"]==canonical_hash(without(T(),"record_hash"))))
case("HASH","deterministic wrapper id",lambda:require(W()["materialization_record_id"]=="S6THMAT_"+canonical_hash(without(W(),"materialization_record_id","record_hash"))[:24]))
case("HASH","deterministic wrapper hash",lambda:require(W()["record_hash"]==canonical_hash(without(W(),"record_hash"))))
case("HASH","repeat thesis identical",lambda:require(build_trade_thesis(CTX["seed"])==T()))
case("HASH","repeat wrapper identical",lambda:require(build_materialization_record(CTX["seed"],CTX["store"].policy_hash,CTX["store"].contract_hash)==W()))

# Type, range, timestamp, history, provenance, and tamper rejection.
for path,value in ((["version"],2),(["schema_version"],"OTHER"),(["thesis_engine_version"],"OTHER"),(["code_commit"],"0"*40),(["authority_mode"],"LIVE"),(["recommendation_id"],""),(["ticker"],""),(["holding_horizon"],""),(["entry_rationale"],[]),(["entry_rationale"],[""]),(["supporting_evidence"],["A","A"]),(["known_risks"],[""]),(["invalidation_conditions"],[]),(["initial_entry_range","low"],0),(["initial_entry_range","high"],0),(["initial_entry_range","currency"],"USD"),(["initial_stop","value"],0),(["current_stop","currency"],"USD"),(["initial_target","value"],0),(["current_target","currency"],"USD"),(["thesis_status"],"THESIS_STRENGTHENED"),(["previous_version_hash"],"0"*64),(["change_history"],[]),(["change_history",0,"version"],2),(["change_history",0,"change_type"],"REVIEW"),(["change_history",0,"reason"],"OTHER"),(["change_history",0,"changed_at_utc"],"2020-01-01T00:00:00Z"),(["input_records"],[]),(["input_records",0,"record_type"],"OTHER"),(["input_records",0,"record_hash"],"0"*64),(["record_hash"],"0"*64)):
    case("REJECTION","/".join(map(str,path)),lambda path=path,value=value:expect(TradeThesisIntegrityFailure,lambda:validate_trade_thesis(changed(T(),path,value))))
for path,value in ((["policy_id"],"OTHER"),(["processor_version"],"OTHER"),(["code_commit"],"0"*40),(["trade_thesis_schema_blob"],"0"*40),(["authority"],"LIVE"),(["policy_hash"],"0"*64),(["seed_binding","record_hash"],"0"*64),(["record_hash"],"0"*64)):
    case("WRAPPER_REJECTION","/".join(map(str,path)),lambda path=path,value=value:expect(TradeThesisIntegrityFailure,lambda:validate_materialization_record(changed(W(),path,value))))

# Persistence, exact direct dependencies, append-only protection, replay.
case("STORE","created",lambda:require(CTX["created"]=="CREATED"))
case("STORE","integrity",lambda:require(CTX["store"].integrity_check()["result"]=="PASS"))
case("STORE","idempotent",lambda:require(CTX["store"].materialize(CTX["seed"]["seed_record_id"])["status"]=="IDEMPOTENT_SUCCESS"))
case("STORE","one record",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM trade_thesis_records").fetchone()[0]==1))
case("STORE","one audit",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM trade_thesis_audits").fetchone()[0]==1))
case("STORE","three dependencies",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM trade_thesis_dependencies").fetchone()[0]==3))
for kind in (SEED_SCHEMA_VERSION,"STAGE6_6B_POLICY","STAGE6_6B_MATERIALIZATION_CONTRACT"):
    case("DEPENDENCY",kind,lambda kind=kind:require(CTX["store"].connection.execute("SELECT count(*) FROM trade_thesis_dependencies WHERE record_type=?",(kind,)).fetchone()[0]==1))
for forbidden in ("EVENT","EXPOSURE_GRAPH","MARKET_CONTEXT","STAGE6_PORTFOLIO_CONTEXT_V2","STAGE6_HISTORICAL_ANALOGUE_V2","STAGE5D5"):
    case("DEPENDENCY","no "+forbidden,lambda forbidden=forbidden:require(CTX["store"].connection.execute("SELECT count(*) FROM trade_thesis_dependencies WHERE record_type=?",(forbidden,)).fetchone()[0]==0))
for table in TABLES:
    case("APPEND_ONLY",table+" update",lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"UPDATE {table} SET rowid=rowid")))
    case("APPEND_ONLY",table+" delete",lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"DELETE FROM {table}")))
case("APPEND_ONLY","API update prohibited",lambda:expect(Stage6TradeThesisError,lambda:CTX["store"].update_record()))
case("STORE","all trigger pairs",lambda:require(all(len(CTX["store"].connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(t,)).fetchall())==2 for t in TABLES)))
case("STORE","SQLite integrity",lambda:require(CTX["store"].connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"))
case("STORE","foreign keys",lambda:require(CTX["store"].connection.execute("PRAGMA foreign_key_check").fetchall()==[]))

def tamper(table,statement):
    folder=tempfile.TemporaryDirectory();seed_store=ThesisSeedStore(Path(folder.name)/"seed.sqlite3");seed=seed_store.freeze(seed_source())["initial_thesis_seed"];store=TradeThesisStore(Path(folder.name)/"thesis.sqlite3",seed_store);store.materialize(seed["seed_record_id"])
    try:
        store.connection.execute(f"DROP TRIGGER protect_{table}_update");store.connection.execute(statement);store.connection.commit();return store.integrity_check()
    finally:store.close();seed_store.close();folder.cleanup()
case("TAMPER","trigger loss",lambda:expect(TradeThesisIntegrityFailure,lambda:tamper("trade_thesis_records","UPDATE trade_thesis_records SET thesis_id=thesis_id"),"TRIGGER_MISSING"))
case("TAMPER","canonical record",lambda:expect(TradeThesisIntegrityFailure,lambda:tamper("trade_thesis_records","UPDATE trade_thesis_records SET canonical_json='{}'")))
case("TAMPER","typed record",lambda:expect(TradeThesisIntegrityFailure,lambda:tamper("trade_thesis_records","UPDATE trade_thesis_records SET thesis_hash='"+("0"*64)+"'")))
case("TAMPER","dependency",lambda:expect(TradeThesisIntegrityFailure,lambda:tamper("trade_thesis_dependencies","UPDATE trade_thesis_dependencies SET record_hash='"+("0"*64)+"'")))
case("TAMPER","audit",lambda:expect(TradeThesisIntegrityFailure,lambda:tamper("trade_thesis_audits","UPDATE trade_thesis_audits SET canonical_json='{}'")))
case("TAMPER","policy",lambda:expect(TradeThesisIntegrityFailure,lambda:tamper("trade_thesis_policies","UPDATE trade_thesis_policies SET canonical_json='{}'")))
case("TAMPER","contract",lambda:expect(TradeThesisIntegrityFailure,lambda:tamper("trade_thesis_contracts","UPDATE trade_thesis_contracts SET canonical_json='{}'")))

# Static zero-authority boundaries.
def imports():
    found=set()
    for path in (ROOT/"stage6_trade_thesis").glob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"));found|={x.names[0].name for x in ast.walk(tree) if isinstance(x,ast.Import)};found|={str(x.module) for x in ast.walk(tree) if isinstance(x,ast.ImportFrom)}
    return found
for token in ("requests","urllib","httpx","aiohttp","socket","selenium","yfinance","gdelt","openai","transformers","torch","tensorflow","sklearn"):
    case("SAFETY","no import "+token,lambda token=token:require(not any(x==token or x.startswith(token+".") for x in imports())))
for key,value in SAFETY.items():case("SAFETY",key,lambda key=key,value=value:require(W()[key]==value))
case("SAFETY","policy zero network",lambda:require(load_policy()[0]["network_calls"]==0 and load_policy()[0]["external_apis"]==0))
case("SAFETY","policy zero AI",lambda:require(load_policy()[0]["ai"] is False))
case("SAFETY","policy no trading",lambda:require(load_policy()[0]["trading_authority"] is False))
case("SAFETY","no Stage 5 imports",lambda:require(not any("stage5" in x.lower() for x in imports())))
case("SAFETY","no later thesis operation",lambda:require(T()["change_history"][0]["change_type"]=="INITIAL_THESIS_CREATED" and len(T()["change_history"])==1))

def main():
    temp=tempfile.TemporaryDirectory(prefix="stage6_6b_");CTX["temp"]=temp;seed_store=ThesisSeedStore(Path(temp.name)/"seed.sqlite3");CTX["seed_store"]=seed_store;CTX["seed"]=seed_store.freeze(seed_source())["initial_thesis_seed"]
    store=TradeThesisStore(Path(temp.name)/"thesis.sqlite3",seed_store);CTX["store"]=store;result=store.materialize(CTX["seed"]["seed_record_id"]);CTX["created"]=result["status"];CTX["wrapper"]=result["materialization_record"];CTX["thesis"]=result["trade_thesis"]
    rows=[]
    for index,(group,name,fn) in enumerate(CASES,1):
        try:fn();rows.append({"test_id":index,"test_group":group,"test_name":name,"result":"PASS","detail":""})
        except Exception as exc:rows.append({"test_id":index,"test_group":group,"test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}: {exc}"})
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=("test_id","test_group","test_name","result","detail"),lineterminator="\n");writer.writeheader();writer.writerows(rows)
    passed=sum(x["result"]=="PASS" for x in rows);print(f"Stage 6.6B: {passed}/{len(rows)} PASS")
    for row in rows:
        if row["result"]!="PASS":print(row)
    store.close();seed_store.close();temp.cleanup();return 0 if passed==len(rows) and len(rows)>=160 else 1
if __name__=="__main__":raise SystemExit(main())
