"""Stage 6.5D final Portfolio Context V2 assembly acceptance tests."""
from __future__ import annotations
import ast,csv,json,socket,subprocess,sys,tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]; REPO=ROOT.parent
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/"tests"))
import run_stage6_5c_tests as prior
from stage6_ingestion.canonical import canonical_hash,canonical_json,without
from stage6_portfolio_source import PortfolioSourceStore
from stage6_portfolio_arithmetic import PortfolioArithmeticStore
from stage6_portfolio_correlation import PortfolioCorrelationStore
from stage6_portfolio_correlation.correlation_builder import build_portfolio_correlation
from stage6_portfolio_context import *
from stage6_portfolio_context.portfolio_context_builder import SAFETY,assemble_portfolio_context
from stage6_portfolio_context.policy import *

BASE="a8f282e6b5c5ccccbdfb594a1744a504f14d91ad"; PARENT="31527d4c6f61e467306c62607d5d3ab4dd98a9d5"
PORTFOLIO_BLOB="5900278a891dc70c63ce02f69002b5e9dec13799"; HISTORICAL_BLOB="85a2b0d00cacd6a3caea484e3ef3071eb16fe01d"; MARKET_BLOB="a141b221228718b8276b3d05b2f028d21adcfc3f"
OUT=ROOT/"results"/"stage6_5d_test_results.csv"; CASES=[]; CTX={}
def case(name,fn):CASES.append((name,fn))
def require(value,message="assertion failed"):
    if not value:raise AssertionError(message)
def expect(error,fn,contains=None):
    try:fn()
    except error as exc:
        if contains:require(contains in str(exc),str(exc))
        return exc
    raise AssertionError("expected "+error.__name__)
def git(*args):return subprocess.check_output(["git",*args],cwd=REPO,text=True).strip()
def result_count(name):
    rows=list(csv.DictReader((ROOT/"results"/name).open(encoding="utf-8")));return len(rows),sum(r["result"]=="PASS" for r in rows)
def changed(value,path,replacement):
    value=deepcopy(value);target=value
    for key in path[:-1]:target=target[key]
    target[path[-1]]=replacement;return value

@contextmanager
def environment(source=None,returns=None):
    with tempfile.TemporaryDirectory(prefix="stage6_5d_") as folder:
        root=Path(folder); source_store=PortfolioSourceStore(root/"source.sqlite3",prior.custom_registry())
        source_record=source_store.freeze(source or prior.multi_source())["portfolio_source_snapshot"]
        arithmetic_store=PortfolioArithmeticStore(root/"arithmetic.sqlite3",source_store)
        arithmetic=arithmetic_store.aggregate(source_snapshot_id=source_record["source_snapshot_id"])["portfolio_arithmetic"]
        correlation_store=PortfolioCorrelationStore(root/"correlation.sqlite3",arithmetic_store)
        correlation=correlation_store.calculate(arithmetic_record_id=arithmetic["arithmetic_record_id"],return_history_manifest=returns or prior.manifest())["portfolio_correlation"]
        store=PortfolioContextStore(root/"context.sqlite3",arithmetic_store,correlation_store)
        wrapper=store.assemble(arithmetic_record_id=arithmetic["arithmetic_record_id"],correlation_context_id=correlation["correlation_context_id"])["portfolio_context_assembly"]
        try:yield {"root":root,"source_store":source_store,"arithmetic_store":arithmetic_store,"correlation_store":correlation_store,"store":store,"arithmetic":arithmetic,"correlation":correlation,"wrapper":wrapper,"payload":wrapper["portfolio_context"]}
        finally:store.close();correlation_store.close();arithmetic_store.close();source_store.close()

def build(a=None,c=None):return assemble_portfolio_context(arithmetic_record=a or CTX["arithmetic"],correlation_record=c or CTX["correlation"],policy_hash=CTX["policy_hash"],assembly_contract_hash=CTX["contract_hash"])
def rehash_correlation(value):
    value=deepcopy(value);value["correlation_context_id"]="S6PORTCORR_"+canonical_hash(without(value,"correlation_context_id","record_hash"))[:24];value["record_hash"]=canonical_hash(without(value,"record_hash"));return value
def code_text():return "\n".join(p.read_text(encoding="utf-8") for p in (ROOT/"stage6_portfolio_context").glob("*.py"))
def imports():
    result=set()
    for path in (ROOT/"stage6_portfolio_context").glob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"));result|={n.names[0].name for n in ast.walk(tree) if isinstance(n,ast.Import)};result|={str(n.module) for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
    return result

# Baseline and identities.
case("exact Stage 6.5C ancestor",lambda:require(git("merge-base","HEAD",BASE)==BASE))
case("exact Stage 6.5C parent",lambda:require(git("rev-parse",f"{BASE}^")==PARENT))
case("branch exact",lambda:require(git("branch","--show-current")=="stage6-portfolio-intelligence"))
case("Stage 6.5C 180",lambda:require(result_count("stage6_5c_test_results.csv")== (180,180)))
PRIOR=[f"stage6_{x}_test_results.csv" for x in ("1a","1b","1c","2a","2b","2c","2d","2e","2f","3a","3b","3c","3d","3e","3f","3g","3h","3i","4a","4b","4c","4d","4e","5a","5b","5c")]
case("prior total 2127",lambda:require(sum(result_count(x)[0] for x in PRIOR)==2127 and sum(result_count(x)[1] for x in PRIOR)==2127))
case("portfolio blob",lambda:require(git("hash-object","Stage 6/contracts/portfolio_context.schema.json")==PORTFOLIO_BLOB))
case("historical blob",lambda:require(git("hash-object","Stage 6/contracts/historical_analogue.schema.json")==HISTORICAL_BLOB))
case("market blob",lambda:require(git("hash-object","Stage 6/contracts/market_context.schema.json")==MARKET_BLOB))
for name,actual,wanted in (("payload schema",PAYLOAD_SCHEMA_VERSION,"STAGE6_PORTFOLIO_CONTEXT_V2"),("store",STORE_SCHEMA_VERSION,"STAGE6_5D_PORTFOLIO_CONTEXT_STORE_V1"),("processor",PROCESSOR_VERSION,"STAGE6_5D_PORTFOLIO_CONTEXT_ASSEMBLER_V1"),("policy",POLICY_ID,"S6PORTCTXPOL_STAGE6_5D_V1"),("assembly contract",ASSEMBLY_CONTRACT_VERSION,"STAGE6_PORTFOLIO_CONTEXT_ASSEMBLY_CONTRACT_V1"),("authority",AUTHORITY,"SHADOW_ONLY")):case(name+" identity",lambda actual=actual,wanted=wanted:require(actual==wanted))
case("policy hash",lambda:require(load_policy()[2]==EXPECTED_POLICY_HASH_V1))
case("contract hash",lambda:require(load_assembly_contract()[2]==EXPECTED_ASSEMBLY_CONTRACT_HASH_V1))

# Exact upstream binding.
W=lambda:CTX["wrapper"];P=lambda:CTX["payload"];A=lambda:CTX["arithmetic"];C=lambda:CTX["correlation"]
for label,wkey,source in (("arithmetic ID","arithmetic_record_id",lambda:A()["arithmetic_record_id"]),("arithmetic hash","arithmetic_record_hash",lambda:A()["record_hash"]),("correlation ID","correlation_context_id",lambda:C()["correlation_context_id"]),("correlation hash","correlation_record_hash",lambda:C()["record_hash"]),("source snapshot ID","source_snapshot_id",lambda:A()["source_snapshot_id"]),("source snapshot hash","source_snapshot_hash",lambda:A()["source_snapshot_hash"])):case("exact "+label,lambda wkey=wkey,source=source:require(W()[wkey]==source()))
case("6.5B integrity",lambda:require(CTX["arithmetic_store"].integrity_check()["result"]=="PASS"))
case("6.5C integrity",lambda:require(CTX["correlation_store"].integrity_check()["result"]=="PASS"))
for field,a_field,c_field in (("arithmetic record","arithmetic_record_id","arithmetic_record_id"),("arithmetic hash","record_hash","arithmetic_record_hash"),("snapshot ID","source_snapshot_id","source_snapshot_id"),("snapshot hash","source_snapshot_hash","source_snapshot_hash"),("source as-of","source_as_of_timestamp","source_as_of_timestamp"),("cutoff","data_cutoff_timestamp","portfolio_data_cutoff_timestamp"),("currency","currency","currency")):
    case(field+" cross-stage",lambda a_field=a_field,c_field=c_field:require(A()[a_field]==C()[c_field]))
def mismatched(field,replacement):return build(c=rehash_correlation(changed(C(),[field],replacement)))
for field in ("arithmetic_record_id","arithmetic_record_hash","source_snapshot_id","source_snapshot_hash","source_as_of_timestamp","portfolio_data_cutoff_timestamp","currency"):
    case(field+" mismatch rejected",lambda field=field:expect(PortfolioContextIntegrityFailure,lambda:mismatched(field,"MISMATCH"),"CROSS_STAGE"))

# Closed payload projection.
case("schema exact",lambda:require(P()["schema_version"]=="STAGE6_PORTFOLIO_CONTEXT_V2"))
for label,pfield,afield in (("as-of","as_of_timestamp","source_as_of_timestamp"),("cutoff","data_cutoff_timestamp","data_cutoff_timestamp"),("capital ceiling","capital_ceiling","capital_ceiling"),("cash","cash","cash"),("risk aggregate","risk_at_stop","aggregate_risk_at_stop"),("committed capital","committed_capital","committed_capital"),("available capital","available_capital","available_capital")):
    case(label+" exact",lambda pfield=pfield,afield=afield:require(P()[pfield]==A()[afield]))
case("open position count",lambda:require(len(P()["open_positions"])==len(A()["derived_open_positions"])))
for index in range(2):
    for pfield,afield in (("ticker","ticker"),("recommendation_id","recommendation_id"),("thesis_id","thesis_id"),("transaction_or_fill_ids","transaction_fill_ids"),("quantity","quantity"),("current_price","current_price"),("average_cost","average_cost_per_share"),("market_value","market_value"),("sector_entity_id","sector_entity_id"),("subsector_entity_id","subsector_entity_id")):
        case(f"position {index} {pfield}",lambda index=index,pfield=pfield,afield=afield:require(P()["open_positions"][index][pfield]==A()["derived_open_positions"][index][afield]))
case("risk money projection",lambda:require(P()["open_positions"][0]["risk_at_stop"]=={k:A()["derived_open_positions"][0]["risk_at_stop"][k] for k in ("value","unit")}))
case("risk timestamp stripped",lambda:require("observed_at_utc" not in P()["open_positions"][0]["risk_at_stop"]))
case("risk method stripped",lambda:require("method" not in P()["open_positions"][0]["risk_at_stop"]))
case("company ID excluded",lambda:require("company_entity_id" not in P()["open_positions"][0]))
case("source position excluded",lambda:require("source_position_snapshot_id" not in P()["open_positions"][0]))
case("position order preserved",lambda:require([x["ticker"] for x in P()["open_positions"]]==[x["ticker"] for x in A()["derived_open_positions"]]))
case("pending count",lambda:require(len(P()["pending_entries"])==len(A()["pending_entry_projection"])))
for pfield in ("ticker","recommendation_id","thesis_id","committed_capital"):case("pending "+pfield,lambda pfield=pfield:require(P()["pending_entries"][0][pfield]==A()["pending_entry_projection"][0][pfield]))
case("pending fields closed",lambda:require(set(P()["pending_entries"][0])=={"ticker","recommendation_id","thesis_id","committed_capital"}))
case("pending order preserved",lambda:require([x["ticker"] for x in P()["pending_entries"]]==[x["ticker"] for x in A()["pending_entry_projection"]]))
def empty_source():
    value=prior.fixture();value["source_export_id"]+="_EMPTY_65D";value["source_export_hash"]="c"*64;value["open_positions"]=[];value["pending_entries"]=[];return value
def empty_manifest():
    value=prior.manifest();value["source_export_id"]+="_EMPTY";value["source_export_hash"]="d"*64;value["series"]=[];return value
def empty_payload():
    with environment(empty_source(),empty_manifest()) as env:return deepcopy(env["payload"])
case("zero-position portfolio valid",lambda:require(empty_payload()["open_positions"]==[]))
case("zero-pending portfolio valid",lambda:require(empty_payload()["pending_entries"]==[]))
case("zero-correlation portfolio valid",lambda:require(empty_payload()["correlated_exposure"]==[]))
def one_source():
    value=prior.fixture();value["source_export_id"]+="_ONE_65D";value["source_export_hash"]="e"*64;return value
def one_manifest():
    value=prior.manifest();value["source_export_id"]+="_ONE";value["source_export_hash"]="f"*64;value["series"]=[value["series"][0]];return value
def one_payload():
    with environment(one_source(),one_manifest()) as env:return deepcopy(env["payload"])
case("one company concentration one",lambda:require(one_payload()["portfolio_concentration"][0]["value"]==1))
case("one company no self-correlation",lambda:require(one_payload()["correlated_exposure"]==[]))

for output,source,identity in (("sector_exposure","held_sector_exposure","sector_entity_id"),("subsector_exposure","held_subsector_exposure","subsector_entity_id"),("portfolio_concentration","held_company_concentration","company_entity_id")):
    case(output+" count",lambda output=output,source=source:require(len(P()[output])==len(A()[source])))
    case(output+" entity mapping",lambda output=output,source=source,identity=identity:require([x["entity_id"] for x in P()[output]]==[x[identity] for x in A()[source]]))
    case(output+" fraction mapping",lambda output=output,source=source:require([x["value"] for x in P()[output]]==[x["fraction_of_invested_capital"]["value"] for x in A()[source]]))
    case(output+" unit",lambda output=output:require(all(x["unit"]=="FRACTION_OF_INVESTED_CAPITAL" for x in P()[output])))
    case(output+" denominator",lambda output=output:require(all(x["denominator_definition"]=="INVESTED_CAPITAL" for x in P()[output])))
case("held market value not final exposure",lambda:require(all("held_market_value" not in x for x in P()["sector_exposure"])))
case("no synthetic subsector",lambda:require(all(x["entity_id"] not in {"UNKNOWN","OTHER"} for x in P()["subsector_exposure"])))
case("no concentration labels",lambda:require(not any("label" in x for x in P()["portfolio_concentration"])))

# Correlation mapping including null and negative.
case("correlation count",lambda:require(len(P()["correlated_exposure"])==len(C()["pairwise_correlations"])))
case("correlation exact projection",lambda:require(P()["correlated_exposure"]==[x["correlation"] for x in C()["pairwise_correlations"]]))
case("wrapper audit stripped",lambda:require("calculation_status" not in P()["correlated_exposure"][0]))
for field in ("members","method","value","unit","return_frequency","lookback_window","minimum_observations","actual_observations","data_cutoff_timestamp"):case("correlation "+field,lambda field=field:require(P()["correlated_exposure"][0][field]==C()["pairwise_correlations"][0]["correlation"][field]))
def correlation_for(returns):return build(c=build_portfolio_correlation(arithmetic_record=A(),return_history_manifest=returns,policy_hash=CTX["correlation_store"].policy_hash,correlation_contract_hash=CTX["correlation_store"].contract_hash))["portfolio_context"]
def negative_manifest():
    value=prior.manifest(); values=[x["return_value"] for x in value["series"][1]["observations"]][::-1]
    for observation,replacement in zip(value["series"][1]["observations"],values):observation["return_value"]=replacement
    return value
case("negative correlation preserved",lambda:require(correlation_for(negative_manifest())["correlated_exposure"][0]["value"]==-1))
case("null insufficient preserved",lambda:require(correlation_for(changed(prior.manifest(),["minimum_observations"],4))["correlated_exposure"][0]["value"] is None))
case("null pair retained",lambda:require(len(correlation_for(changed(prior.manifest(),["minimum_observations"],4))["correlated_exposure"])==1))
case("missing null retained",lambda:require(correlation_for(prior.missing_manifest())["correlated_exposure"][0]["value"] is None))
case("correlation order preserved",lambda:require(P()["correlated_exposure"]==[x["correlation"] for x in C()["pairwise_correlations"]]))

# Schema, identities, wrapper, and safety.
case("cash valid true",lambda:require(P()["cash_is_valid_allocation"] is True))
case("final schema validates",lambda:require(validate_portfolio_context(P())==P()))
case("wrapper validates",lambda:require(validate_portfolio_context_wrapper(W())==W()))
case("extra final field rejected",lambda:expect(PortfolioContextIntegrityFailure,lambda:validate_portfolio_context({**P(),"extra":1})))
def missing_field():v=deepcopy(P());v.pop("cash");return validate_portfolio_context(v)
case("missing required rejected",lambda:expect(PortfolioContextIntegrityFailure,missing_field))
case("money units valid",lambda:require(all(P()[x]["unit"] in {"INR","USD"} for x in ("capital_ceiling","cash","risk_at_stop","committed_capital","available_capital"))))
case("correlation unit exact",lambda:require(P()["correlated_exposure"][0]["unit"]=="CORRELATION"))
case("deterministic context ID",lambda:require(build()["portfolio_context"]["portfolio_context_id"]==P()["portfolio_context_id"]))
case("deterministic record hash",lambda:require(build()["portfolio_context"]["record_hash"]==P()["record_hash"]))
case("deterministic wrapper ID",lambda:require(build()["assembly_record_id"]==W()["assembly_record_id"]))
case("deterministic wrapper hash",lambda:require(build()["wrapper_hash"]==W()["wrapper_hash"]))
for key,value in SAFETY.items():case("safety "+key,lambda key=key,value=value:require(W()[key]==value))
case("subsector audit outside payload",lambda:require("subsector_coverage_audit" in W() and "subsector_coverage_audit" not in P()))
case("pending audit outside payload",lambda:require("pending_commitment_audit" in W() and "pending_commitment_audit" not in P()))

# Deliberate no-recalculation/no-authority boundary.
for token in ("Decimal","pearson","intersection","minimum_observations <","quantity *","held_market_value +","sum(","max_correlation","mean_correlation","absolute_correlation","diversification_score","correlated_capital","replacement_proposal","BUY","SELL","HOLD"):
    case("assembly boundary excludes "+token,lambda token=token:require(token not in (ROOT/"stage6_portfolio_context"/"portfolio_context_builder.py").read_text(encoding="utf-8")))
case("no historical analogue import",lambda:require(not any("analogue" in x.lower() for x in imports())))
case("no Stage 5D import",lambda:require(not any("stage5" in x.lower() for x in imports())))
case("no 6.5A direct import",lambda:require(not any("stage6_portfolio_source" in x for x in imports())))
case("no registry import",lambda:require(not any(x.endswith("registry") for x in imports())))
case("no return history direct access",lambda:require("return_history_manifest" not in (ROOT/"stage6_portfolio_context"/"portfolio_context_builder.py").read_text(encoding="utf-8")))

# Persistence and tamper controls.
case("store integrity",lambda:require(CTX["store"].integrity_check()["result"]=="PASS"))
case("idempotency",lambda:require(CTX["store"].assemble(arithmetic_record_id=A()["arithmetic_record_id"],correlation_context_id=C()["correlation_context_id"])["status"]=="IDEMPOTENT_SUCCESS"))
def conflict():
    with environment() as e:
        c=e["store"].connection;c.execute("DROP TRIGGER protect_portfolio_context_records_update");c.execute("UPDATE portfolio_context_records SET canonical_json='{}'");c.commit()
        return expect(PortfolioContextConflict,lambda:e["store"].assemble(arithmetic_record_id=e["arithmetic"]["arithmetic_record_id"],correlation_context_id=e["correlation"]["correlation_context_id"]))
case("conflict handling",lambda:require(conflict()))
case("exact four dependencies",lambda:require(CTX["store"].connection.execute("SELECT COUNT(*) FROM portfolio_context_dependencies").fetchone()[0]==4))
case("dependency identities",lambda:require({r[0] for r in CTX["store"].connection.execute("SELECT record_type FROM portfolio_context_dependencies")}=={"STAGE6_5B_PORTFOLIO_ARITHMETIC","STAGE6_5C_PORTFOLIO_CORRELATION","STAGE6_5D_POLICY","STAGE6_5D_ASSEMBLY_CONTRACT"}))
case("metadata singleton",lambda:require(CTX["store"].connection.execute("SELECT COUNT(*) FROM portfolio_context_store_meta").fetchone()[0]==1))
case("policy singleton",lambda:require(CTX["store"].connection.execute("SELECT COUNT(*) FROM portfolio_context_policies").fetchone()[0]==1))
case("contract singleton",lambda:require(CTX["store"].connection.execute("SELECT COUNT(*) FROM portfolio_context_assembly_contracts").fetchone()[0]==1))
for table in ("portfolio_context_store_meta","portfolio_context_policies","portfolio_context_assembly_contracts","portfolio_context_records","portfolio_context_dependencies","portfolio_context_audits"):
    case("append only "+table,lambda table=table:expect(Exception,lambda:CTX["store"].connection.execute(f"UPDATE {table} SET rowid=rowid"),"IMMUTABLE"))
case("SQLite integrity",lambda:require(CTX["store"].connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"))
case("foreign keys",lambda:require(CTX["store"].connection.execute("PRAGMA foreign_key_check").fetchall()==[]))
def restart():
    with PortfolioContextStore(CTX["root"]/"context.sqlite3",CTX["arithmetic_store"],CTX["correlation_store"]) as s:return s.integrity_check()["result"]
case("restart integrity",lambda:require(restart()=="PASS"))
def tamper(table,column):
    with environment() as e:
        c=e["store"].connection;c.execute(f"DROP TRIGGER protect_{table}_update");c.execute(f"UPDATE {table} SET {column}='tampered'");c.commit();return expect(PortfolioContextIntegrityFailure,e["store"].integrity_check)
case("trigger loss",lambda:require(tamper("portfolio_context_records","wrapper_hash")))
case("payload tamper",lambda:require(tamper("portfolio_context_records","canonical_json")))
case("dependency tamper",lambda:require(tamper("portfolio_context_dependencies","record_hash")))
case("wrapper audit tamper",lambda:require(tamper("portfolio_context_audits","canonical_json")))
case("policy tamper",lambda:require(tamper("portfolio_context_policies","canonical_json")))
case("contract tamper",lambda:require(tamper("portfolio_context_assembly_contracts","canonical_json")))
def upstream_tamper(which):
    with environment() as e:
        upstream=e[which+"_store"]
        table="portfolio_arithmetic_records" if which=="arithmetic" else "portfolio_correlation_records"
        upstream.connection.execute(f"DROP TRIGGER protect_{table}_update");upstream.connection.execute(f"UPDATE {table} SET canonical_json='{{}}'");upstream.connection.commit()
        return expect(PortfolioContextIntegrityFailure,e["store"].integrity_check)
case("6.5B tamper detected upstream",lambda:require(upstream_tamper("arithmetic")))
case("6.5C tamper detected upstream",lambda:require(upstream_tamper("correlation")))
case("canonical replay",lambda:require(CTX["store"].connection.execute("SELECT canonical_json FROM portfolio_context_records").fetchone()[0]==canonical_json(W())))
case("deterministic replay",lambda:require(CTX["store"].integrity_check()["portfolio_context_records"]==1))

# Offline/static safety.
case("no network imports",lambda:require(not ({"requests","urllib","httpx","yfinance","pandas_datareader"}&imports())))
case("no AI imports",lambda:require(not ({"openai","transformers","torch","tensorflow","sklearn","spacy"}&imports())))
case("no broker imports",lambda:require(not ({"kiteconnect","ib_insync","alpaca_trade_api"}&imports())))
def blocked_network():
    with mock.patch.object(socket,"create_connection",side_effect=AssertionError("network called")):require(build()["wrapper_hash"]==W()["wrapper_hash"])
case("zero network execution",blocked_network)
case("trading authority false",lambda:require(W()["trading_authority"] is False))
case("V2 materialized",lambda:require(W()["portfolio_context_v2_status"]=="MATERIALIZED"))

def run():
    with environment() as env:
        CTX.update(env,policy_hash=load_policy()[2],contract_hash=load_assembly_contract()[2]);rows=[]
        for index,(name,fn) in enumerate(CASES,1):
            try:fn();result="PASS";detail=""
            except Exception as exc:result="FAIL";detail=f"{type(exc).__name__}: {exc}"
            rows.append({"test_id":index,"test_name":name,"result":result,"detail":detail})
        OUT.parent.mkdir(parents=True,exist_ok=True)
        with OUT.open("w",newline="",encoding="utf-8") as handle:
            writer=csv.DictWriter(handle,fieldnames=("test_id","test_name","result","detail"));writer.writeheader();writer.writerows(rows)
        passed=sum(x["result"]=="PASS" for x in rows);print(f"Stage 6.5D: {passed}/{len(rows)} PASS")
        for row in rows:
            if row["result"]=="FAIL":print(f"FAIL {row['test_id']} {row['test_name']}: {row['detail']}")
        return 0 if passed==len(rows) and len(rows)>=150 else 1
if __name__=="__main__":raise SystemExit(run())
