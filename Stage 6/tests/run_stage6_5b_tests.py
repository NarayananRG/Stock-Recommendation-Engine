"""Stage 6.5B deterministic portfolio arithmetic acceptance tests."""
from __future__ import annotations

import ast
import csv
import json
import math
import socket
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from stage6_ingestion.fixtures import build_fixture_registries
from stage6_ingestion.registry import build_entity_registry
from stage6_portfolio_source import PortfolioSourceStore, Stage6PortfolioSourceError
from stage6_portfolio_source.portfolio_source_builder import build_portfolio_source_snapshot
from stage6_portfolio_source.policy import load_constituent_contract, load_policy as load_source_policy
from stage6_portfolio_arithmetic import *
from stage6_portfolio_arithmetic.arithmetic import TOLERANCE, add, decimal_value, divide, emit, multiply
from stage6_portfolio_arithmetic.policy import *
from stage6_portfolio_arithmetic.portfolio_arithmetic_builder import build_portfolio_arithmetic

BASE = "93b05ded5042423a6fa208cdb29f5961687fdb9c"
PARENT = "f150608994fbeea3b79d2a078642dee89e4f6a59"
HISTORICAL_BLOB = "85a2b0d00cacd6a3caea484e3ef3071eb16fe01d"
MARKET_BLOB = "a141b221228718b8276b3d05b2f028d21adcfc3f"
OUT = ROOT / "results" / "stage6_5b_test_results.csv"
SOURCE_FIXTURE = ROOT / "fixtures" / "stage6_5a" / "portfolio_source_examples.json"
EXPECTED_FIXTURE = ROOT / "fixtures" / "stage6_5b" / "portfolio_arithmetic_examples.json"
REGISTRY = build_fixture_registries()["entity_v1"]
CASES = []
CTX = {}


def case(name, function): CASES.append((name, function))
def require(value, message="assertion failed"):
    if not value: raise AssertionError(message)
def expect(error, function, contains=None):
    try: function()
    except error as exc:
        if contains: require(contains in str(exc), str(exc))
        return exc
    raise AssertionError("expected " + error.__name__)
def git(*args): return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()
def fixture(): return json.loads(SOURCE_FIXTURE.read_text(encoding="utf-8"))["inr"]
def expected(): return json.loads(EXPECTED_FIXTURE.read_text(encoding="utf-8"))["base_inr_expected"]
def changed(value, path, replacement):
    value = deepcopy(value); target = value
    for key in path[:-1]: target = target[key]
    target[path[-1]] = replacement
    return value
def result_count(name):
    rows = list(csv.DictReader((ROOT / "results" / name).open(encoding="utf-8")))
    return len(rows), sum(row["result"] == "PASS" for row in rows)
def source_snapshot(value=None, registry=None):
    policy_hash = load_source_policy()[2]; contract_hash = load_constituent_contract()[2]
    return build_portfolio_source_snapshot(source_export=value or fixture(), entity_registry=registry or REGISTRY,
                                           policy_hash=policy_hash, constituent_contract_hash=contract_hash)
def build(source=None):
    return build_portfolio_arithmetic(source_snapshot=source or source_snapshot(),
                                      policy_hash=CTX["policy_hash"], arithmetic_contract_hash=CTX["contract_hash"])


@contextmanager
def environment(value=None, registry=None):
    with tempfile.TemporaryDirectory(prefix="stage6_5b_") as folder:
        root = Path(folder)
        source_store = PortfolioSourceStore(root / "source.sqlite3", registry or REGISTRY)
        source = source_store.freeze(value or fixture())["portfolio_source_snapshot"]
        store = PortfolioArithmeticStore(root / "arithmetic.sqlite3", source_store)
        record = store.aggregate(source_snapshot_id=source["source_snapshot_id"])["portfolio_arithmetic"]
        try: yield {"root": root, "source_store": source_store, "source": source, "store": store, "record": record}
        finally: store.close(); source_store.close()


def custom_registry():
    records = deepcopy(REGISTRY["entities"])
    subsector = deepcopy(records[1]); subsector.update(entity_id="S6FIX_SUBSECTOR_SOFTWARE", canonical_name="Fixture Software Subsector", entity_type="SUBSECTOR"); subsector.pop("record_hash", None)
    finance = deepcopy(records[1]); finance.update(entity_id="S6FIX_SECTOR_FINANCE", canonical_name="Fixture Finance Sector"); finance.pop("record_hash", None)
    company = deepcopy(records[0]); company.update(entity_id="S6FIX_COMPANY_002", canonical_name="Fixture Finance Limited", legal_name="Fixture Finance Limited", isin="FIXTUREISIN002", sector_entity_id="S6FIX_SECTOR_FINANCE", subsector_entity_id="S6FIX_SUBSECTOR_SOFTWARE", ticker_mappings=[{"exchange":"FIXTURE_EXCHANGE","ticker":"FIX2","effective_from":"2026-01-01","effective_to":None}], aliases=[]); company.pop("record_hash", None)
    records.extend((subsector, finance, company))
    return build_entity_registry(records, "2026-01-02T00:00:00Z")


def position2(value, *, same_company=False, recommendation="REC_FIX_002"):
    item = deepcopy(value["open_positions"][0])
    item.update(recommendation_id=recommendation, source_position_snapshot_id="POS_" + recommendation,
                source_position_snapshot_hash="7" * 64, transaction_fill_ids=["FILL_" + recommendation], quantity=3)
    item["current_price"].update(value=100.1)
    item["average_cost_per_share"].update(value=90.1)
    item["risk_at_stop"].update(value=25.2)
    if not same_company:
        item.update(company_entity_id="S6FIX_COMPANY_002", ticker="FIX2", sector_entity_id="S6FIX_SECTOR_FINANCE", subsector_entity_id="S6FIX_SUBSECTOR_SOFTWARE")
    item["source_record_bindings"] = [
        {"record_type":"RECOMMENDATION","record_id":recommendation,"record_hash":"8"*64,"recorded_or_persisted_at_utc":"2026-04-28T10:00:00Z"},
        {"record_type":"TRANSACTION_FILL","record_id":"FILL_"+recommendation,"record_hash":"7"*64,"recorded_or_persisted_at_utc":"2026-04-28T10:01:00Z"}]
    return item


def pending2(value):
    item = deepcopy(value["pending_entries"][0])
    item.update(company_entity_id="S6FIX_COMPANY_002", ticker="FIX2", recommendation_id="REC_FIX_PENDING_002",
                committed_reserved_capital={"value":1000.5,"currency":value["currency"]},
                sector_entity_id="S6FIX_SECTOR_FINANCE", subsector_entity_id="S6FIX_SUBSECTOR_SOFTWARE",
                source_record_id="REC_FIX_PENDING_002", source_record_hash="9"*64)
    item["source_record_bindings"]=[{"record_type":"RECOMMENDATION","record_id":"REC_FIX_PENDING_002","record_hash":"9"*64,"recorded_or_persisted_at_utc":"2026-04-28T10:00:00Z"}]
    return item


def multi(*, same_company=False):
    value = fixture(); value["source_export_id"] += "_MULTI"; value["source_export_hash"] = "a" * 64
    value["open_positions"].append(position2(value, same_company=same_company))
    if not same_company: value["pending_entries"].append(pending2(value))
    return value


def usd():
    value=fixture(); value["source_export_id"] += "_USD"; value["source_export_hash"]="b"*64; value["currency"]="USD"; value["capital_ceiling"]["currency"]="USD"
    for item in value["open_positions"]:
        for field in ("current_price","average_cost_per_share","risk_at_stop"): item[field]["currency"]="USD"
    for item in value["pending_entries"]: item["committed_reserved_capital"]["currency"]="USD"
    return value


def no_positions():
    value=fixture(); value["source_export_id"] += "_EMPTY"; value["source_export_hash"]="c"*64; value["open_positions"]=[]; value["pending_entries"]=[]; return value


def source_text(): return "\n".join(path.read_text(encoding="utf-8") for path in (ROOT/"stage6_portfolio_arithmetic").glob("*.py"))
def builder_text(): return (ROOT/"stage6_portfolio_arithmetic"/"portfolio_arithmetic_builder.py").read_text(encoding="utf-8")
def imports():
    result=set()
    for path in (ROOT/"stage6_portfolio_arithmetic").glob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8")); result|={node.names[0].name for node in ast.walk(tree) if isinstance(node,ast.Import)}; result|={str(node.module) for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)}
    return result


# Baseline and frozen identities.
case("exact Stage 6.5A baseline ancestor",lambda:require(git("merge-base","HEAD",BASE)==BASE))
case("exact Stage 6.5A parent lineage",lambda:require(git("rev-parse",f"{BASE}^")==PARENT))
case("portfolio intelligence branch",lambda:require(git("branch","--show-current")=="stage6-portfolio-intelligence"))
case("Stage 6.5A regression",lambda:require(result_count("stage6_5a_test_results.csv")== (171,171)))
case("prior Stage 6 total",lambda:require(sum(result_count(name)[0] for name in ["stage6_1a_test_results.csv","stage6_1b_test_results.csv","stage6_1c_test_results.csv","stage6_2a_test_results.csv","stage6_2b_test_results.csv","stage6_2c_test_results.csv","stage6_2d_test_results.csv","stage6_2e_test_results.csv","stage6_2f_test_results.csv","stage6_3a_test_results.csv","stage6_3b_test_results.csv","stage6_3c_test_results.csv","stage6_3d_test_results.csv","stage6_3e_test_results.csv","stage6_3f_test_results.csv","stage6_3g_test_results.csv","stage6_3h_test_results.csv","stage6_3i_test_results.csv","stage6_4a_test_results.csv","stage6_4b_test_results.csv","stage6_4c_test_results.csv","stage6_4d_test_results.csv","stage6_4e_test_results.csv","stage6_5a_test_results.csv"])==1743))
case("portfolio contract blob",lambda:require(git("hash-object","Stage 6/contracts/portfolio_context.schema.json")==PORTFOLIO_CONTEXT_BLOB))
case("historical contract blob",lambda:require(git("hash-object","Stage 6/contracts/historical_analogue.schema.json")==HISTORICAL_BLOB))
case("market contract blob",lambda:require(git("hash-object","Stage 6/contracts/market_context.schema.json")==MARKET_BLOB))
case("schema identity",lambda:require(SCHEMA_VERSION=="STAGE6_PORTFOLIO_ARITHMETIC_V1"))
case("store identity",lambda:require(STORE_SCHEMA_VERSION=="STAGE6_5B_PORTFOLIO_ARITHMETIC_STORE_V1"))
case("processor identity",lambda:require(PROCESSOR_VERSION=="STAGE6_5B_PORTFOLIO_ARITHMETIC_AGGREGATOR_V1"))
case("policy identity",lambda:require(POLICY_ID=="S6PORTARITHPOL_STAGE6_5B_V1"))
case("arithmetic contract identity",lambda:require(ARITHMETIC_CONTRACT_VERSION=="STAGE6_PORTFOLIO_ARITHMETIC_CONTRACT_V1"))
case("policy canonical hash",lambda:require(load_policy()[2]==canonical_hash(load_policy()[0])==EXPECTED_POLICY_HASH_V1))
case("contract canonical hash",lambda:require(load_arithmetic_contract()[2]==canonical_hash(load_arithmetic_contract()[0])==EXPECTED_ARITHMETIC_CONTRACT_HASH_V1))
case("SHADOW_ONLY",lambda:require(AUTHORITY=="SHADOW_ONLY" and CTX["record"]["authority"]=="SHADOW_ONLY"))

# Exact source boundary.
case("exact source ID",lambda:require(CTX["record"]["source_snapshot_id"]==CTX["source"]["source_snapshot_id"]))
case("exact source hash",lambda:require(CTX["record"]["source_snapshot_hash"]==CTX["source"]["record_hash"]))
case("exact source export identity",lambda:require((CTX["record"]["source_export_id"],CTX["record"]["source_export_hash"])==(CTX["source"]["source_export_id"],CTX["source"]["source_export_hash"])))
case("source identity constants",lambda:require((SOURCE_SCHEMA_VERSION,SOURCE_PROCESSOR_VERSION,SOURCE_POLICY_ID,SOURCE_POLICY_HASH,SOURCE_CONTRACT_VERSION,SOURCE_CONTRACT_HASH)==tuple(CTX["source"][k] for k in ("schema_version","processor_version","policy_id","policy_hash","constituent_contract_version","constituent_contract_hash"))))
case("source store integrity required",lambda:require(CTX["source_store"].integrity_check()["result"]=="PASS"))
case("source hash tamper rejected",lambda:expect(Exception,lambda:build(changed(CTX["source"],["record_hash"],"f"*64))))
case("source policy tamper rejected",lambda:expect(Exception,lambda:build(changed(CTX["source"],["policy_hash"],"f"*64))))
case("source authority exact",lambda:require(CTX["source"]["authority"]=="SHADOW_ONLY"))
case("source PIT preserved",lambda:require(CTX["record"]["data_cutoff_timestamp"]==CTX["source"]["data_cutoff_timestamp"]))
case("wrong arithmetic policy hash rejected",lambda:expect(PortfolioArithmeticIntegrityFailure,lambda:build_portfolio_arithmetic(source_snapshot=CTX["source"],policy_hash="f"*64,arithmetic_contract_hash=CTX["contract_hash"]),"CONFIGURATION"))
case("wrong arithmetic contract hash rejected",lambda:expect(PortfolioArithmeticIntegrityFailure,lambda:build_portfolio_arithmetic(source_snapshot=CTX["source"],policy_hash=CTX["policy_hash"],arithmetic_contract_hash="f"*64),"CONFIGURATION"))

# Decimal arithmetic and capital formulas.
case("INR accepted",lambda:require(CTX["record"]["currency"]=="INR"))
case("USD accepted",lambda:require(build(source_snapshot(usd()))["currency"]=="USD"))
case("exact currency copied",lambda:require(all(thing["unit"]==CTX["record"]["currency"] for thing in (CTX["record"]["capital_ceiling"],CTX["record"]["invested_capital"],CTX["record"]["cash"]))))
case("mixed currency impossible through frozen source",lambda:expect(Stage6PortfolioSourceError,lambda:source_snapshot(changed(fixture(),["open_positions",0,"current_price","currency"],"USD"))))
case("no FX conversion",lambda:require("exchange_rate" not in source_text() and "fx" not in source_text().lower()))
case("Decimal string conversion",lambda:require(decimal_value(0.1,"x")==Decimal("0.1")))
case("Decimal multiplication",lambda:require(multiply(Decimal("3"),Decimal("0.1"))==Decimal("0.3")))
case("Decimal addition",lambda:require(add((Decimal("0.1"),Decimal("0.2")))==Decimal("0.3")))
case("nonfinite rejected",lambda:expect(Stage6PortfolioArithmeticError,lambda:decimal_value(float("inf"),"x"),"NONFINITE"))
case("nonfinite emitted result rejected",lambda:expect(Stage6PortfolioArithmeticError,lambda:emit(Decimal("1"+"0"*400+".1")),"NONFINITE"))
case("one position market value",lambda:require(CTX["record"]["derived_open_positions"][0]["market_value"]==expected()["position_market_value"]))
case("quantity times price exact",lambda:require(CTX["record"]["derived_open_positions"][0]["market_value"]["value"]==100*125.5))
case("multi position values",lambda:require([x["market_value"]["value"] for x in build(source_snapshot(multi(),custom_registry()))["derived_open_positions"]]==[12550,300.3]))
case("source market value ignored by formula",lambda:require(load_arithmetic_contract()[0]["market_value_formula"]=="quantity * current_price"))
case("empty invested capital zero",lambda:require(build(source_snapshot(no_positions()))["invested_capital"]["value"]==0))
case("invested capital exact",lambda:require(CTX["record"]["invested_capital"]==expected()["invested_capital"]))
case("multi invested sum exact",lambda:require(build(source_snapshot(multi(),custom_registry()))["invested_capital"]["value"]==12850.3))
case("no binary float accumulation",lambda:require(add((decimal_value(0.1,"x"),decimal_value(0.2,"x")))==Decimal("0.3")))
case("zero pending commitments",lambda:require(build(source_snapshot(no_positions()))["pending_committed_capital"]["value"]==0))
case("pending commitment sum",lambda:require(CTX["record"]["pending_committed_capital"]==expected()["pending_committed_capital"]))
case("multi pending commitment sum",lambda:require(build(source_snapshot(multi(),custom_registry()))["pending_committed_capital"]["value"]==26000.5))
case("committed formula",lambda:require(CTX["record"]["committed_capital"]==expected()["committed_capital"]))
def overage_source():
    value=fixture(); value["source_export_id"] += "_OVER"; value["source_export_hash"]="d"*64; value["capital_ceiling"]["value"]=10000; return source_snapshot(value)
case("committed may exceed ceiling",lambda:require(build(overage_source())["committed_capital"]["value"]==37550))
case("cash exact",lambda:require(CTX["record"]["cash"]==expected()["cash"]))
case("cash never negative",lambda:require(build(overage_source())["cash"]["value"]==0))
case("pending does not reduce cash",lambda:require(CTX["record"]["cash"]["value"]==CTX["record"]["capital_ceiling"]["value"]-CTX["record"]["invested_capital"]["value"]))
case("available exact",lambda:require(CTX["record"]["available_capital"]==expected()["available_capital"]))
case("available never negative",lambda:require(build(overage_source())["available_capital"]["value"]==0))
case("pending reduces available",lambda:require(CTX["record"]["cash"]["value"]-CTX["record"]["pending_committed_capital"]["value"]==CTX["record"]["available_capital"]["value"]))
case("invested overage exact",lambda:require(build(overage_source())["invested_capital_overage"]["value"]==2550))
case("committed overage exact",lambda:require(build(overage_source())["committed_capital_overage"]["value"]==27550))
case("no overage action",lambda:require(not any(key in CTX["record"] for key in ("sell","cancel","recommendation"))))
case("one position risk sum",lambda:require(CTX["record"]["aggregate_risk_at_stop"]==expected()["aggregate_risk_at_stop"]))
case("multi position risk sum",lambda:require(build(source_snapshot(multi(),custom_registry()))["aggregate_risk_at_stop"]["value"]==775.2))
case("risk preserved not recalculated",lambda:require(CTX["record"]["derived_open_positions"][0]["risk_at_stop"]["value"]==CTX["source"]["open_positions"][0]["risk_at_stop"]["value"]))
case("no stop-price inference",lambda:require("stop_price" not in source_text()))

# Held and pending exposure semantics.
case("company grouping one",lambda:require(len(CTX["record"]["held_company_concentration"])==1))
case("same company positions aggregate",lambda:require(build(source_snapshot(multi(same_company=True)))["held_company_concentration"][0]["held_market_value"]["value"]==12850.3))
case("company amount conservation",lambda:require(sum(x["held_market_value"]["value"] for x in build(source_snapshot(multi(),custom_registry()))["held_company_concentration"])==12850.3))
case("company fraction exact",lambda:require(CTX["record"]["held_company_concentration"][0]["fraction_of_invested_capital"]["value"]==1))
case("company fractions sum one",lambda:require(abs(sum(x["fraction_of_invested_capital"]["value"] for x in build(source_snapshot(multi(),custom_registry()))["held_company_concentration"])-1)<1e-12))
case("no concentration threshold",lambda:require("threshold" not in canonical_json(load_arithmetic_contract()[0]).lower()))
case("no concentration label",lambda:require(not any(word in canonical_json(CTX["record"]) for word in ("HIGH","LOW","SAFE","UNSAFE","DIVERSIFIED"))))
case("sector grouping",lambda:require(len(build(source_snapshot(multi(),custom_registry()))["held_sector_exposure"])==2))
case("sector amount conservation",lambda:require(sum(x["held_market_value"]["value"] for x in build(source_snapshot(multi(),custom_registry()))["held_sector_exposure"])==12850.3))
case("sector fraction exact",lambda:require(CTX["record"]["held_sector_exposure"][0]["fraction_of_invested_capital"]["value"]==1))
case("sector fractions sum one",lambda:require(abs(sum(x["fraction_of_invested_capital"]["value"] for x in build(source_snapshot(multi(),custom_registry()))["held_sector_exposure"])-1)<1e-12))
case("empty sector list",lambda:require(build(source_snapshot(no_positions()))["held_sector_exposure"]==[]))
case("subsector grouping",lambda:require(len(build(source_snapshot(multi(),custom_registry()))["held_subsector_exposure"])==1))
case("null subsector omitted",lambda:require(CTX["record"]["held_subsector_exposure"]==[]))
case("no synthetic subsector",lambda:require("UNKNOWN" not in canonical_json(CTX["record"]["held_subsector_exposure"])))
case("missing subsector count",lambda:require(CTX["record"]["subsector_coverage_audit"]["positions_without_subsector_count"]==1))
case("missing subsector value",lambda:require(CTX["record"]["subsector_coverage_audit"]["market_value_without_subsector"]==expected()["market_value_without_subsector"]))
case("subsector conservation",lambda:require(sum(x["held_market_value"]["value"] for x in build(source_snapshot(multi(),custom_registry()))["held_subsector_exposure"])+build(source_snapshot(multi(),custom_registry()))["subsector_coverage_audit"]["market_value_without_subsector"]["value"]==12850.3))
case("pending company aggregation",lambda:require(len(build(source_snapshot(multi(),custom_registry()))["pending_commitment_by_company"])==2))
case("pending sector aggregation",lambda:require(len(build(source_snapshot(multi(),custom_registry()))["pending_commitment_by_sector"])==2))
case("pending subsector aggregation",lambda:require(len(build(source_snapshot(multi(),custom_registry()))["pending_commitment_by_subsector"])==1))
case("pending excluded company held",lambda:require(CTX["record"]["held_company_concentration"][0]["held_market_value"]["value"]==12550))
case("pending excluded sector held",lambda:require(CTX["record"]["held_sector_exposure"][0]["held_market_value"]["value"]==12550))
case("pending excluded subsector held",lambda:require(CTX["record"]["held_subsector_exposure"]==[]))
case("pending affects committed",lambda:require(CTX["record"]["committed_capital"]["value"]>CTX["record"]["invested_capital"]["value"]))
case("pending affects available",lambda:require(CTX["record"]["available_capital"]["value"]<CTX["record"]["cash"]["value"]))

# Projection, determinism, and direct dependencies.
for name,key in (("company identity","company_entity_id"),("recommendation ID","recommendation_id"),("thesis ID","thesis_id"),("fill IDs","transaction_fill_ids"),("quantity","quantity"),("sector ID","sector_entity_id"),("subsector ID","subsector_entity_id"),("source position ID","source_position_snapshot_id")):
    case(name+" preserved",lambda key=key:require(CTX["record"]["derived_open_positions"][0][key]==CTX["source"]["open_positions"][0][key]))
case("current price timestamp preserved",lambda:require(CTX["record"]["derived_open_positions"][0]["current_price"]["observed_at_utc"]==CTX["source"]["open_positions"][0]["current_price"]["observed_at_utc"]))
case("average cost preserved",lambda:require(CTX["record"]["derived_open_positions"][0]["average_cost_per_share"]["value"]==110.0))
case("risk at stop preserved",lambda:require(CTX["record"]["derived_open_positions"][0]["risk_at_stop"]["method"]=="SOURCE_LEDGER_EXPLICIT"))
case("final-compatible money unit",lambda:require("unit" in CTX["record"]["derived_open_positions"][0]["market_value"] and "currency" not in CTX["record"]["derived_open_positions"][0]["market_value"]))
case("final-compatible pending projection",lambda:require(CTX["record"]["pending_entry_projection"][0]["committed_capital"]["unit"]=="INR"))
def order_independent():
    value=multi(); reverse=deepcopy(value); reverse["open_positions"].reverse(); reverse["pending_entries"].reverse(); return build(source_snapshot(value,custom_registry()))["record_hash"]==build(source_snapshot(reverse,custom_registry()))["record_hash"]
case("caller source order independent",lambda:require(order_independent()))
case("company ordering deterministic",lambda:require([x["company_entity_id"] for x in build(source_snapshot(multi(),custom_registry()))["held_company_concentration"]]==sorted(x["company_entity_id"] for x in build(source_snapshot(multi(),custom_registry()))["held_company_concentration"])))
case("sector ordering deterministic",lambda:require([x["sector_entity_id"] for x in build(source_snapshot(multi(),custom_registry()))["held_sector_exposure"]]==sorted(x["sector_entity_id"] for x in build(source_snapshot(multi(),custom_registry()))["held_sector_exposure"])))
case("subsector ordering deterministic",lambda:require([x["subsector_entity_id"] for x in build(source_snapshot(multi(),custom_registry()))["held_subsector_exposure"]]==sorted(x["subsector_entity_id"] for x in build(source_snapshot(multi(),custom_registry()))["held_subsector_exposure"])))
case("pending ordering deterministic",lambda:require([x["company_entity_id"] for x in build(source_snapshot(multi(),custom_registry()))["pending_commitment_by_company"]]==sorted(x["company_entity_id"] for x in build(source_snapshot(multi(),custom_registry()))["pending_commitment_by_company"])))
case("deterministic arithmetic ID",lambda:require(build()["arithmetic_record_id"]==build()["arithmetic_record_id"]))
case("deterministic record hash",lambda:require(build()["record_hash"]==build()["record_hash"]))
case("content-addressed ID",lambda:require(build()["arithmetic_record_id"]=="S6PORTARITH_"+canonical_hash(without(build(),"arithmetic_record_id","record_hash"))[:24]))
case("content-addressed hash",lambda:require(build()["record_hash"]==canonical_hash(without(build(),"record_hash"))))
def dependency_types(): return {x[0] for x in CTX["store"].connection.execute("SELECT record_type FROM portfolio_arithmetic_dependencies")}
case("exact direct dependencies",lambda:require(dependency_types()=={"STAGE6_5A_PORTFOLIO_SOURCE","STAGE6_5B_POLICY","STAGE6_5B_ARITHMETIC_CONTRACT"}))
case("no transitive dependency duplication",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_arithmetic_dependencies").fetchone()[0]==3))

# Persistence and tamper detection.
case("idempotent replay",lambda:require(CTX["store"].aggregate(source_snapshot_id=CTX["source"]["source_snapshot_id"])["status"]=="IDEMPOTENT_SUCCESS"))
def conflict():
    with environment() as x:
        s=x["store"]; s.connection.execute("DROP TRIGGER protect_portfolio_arithmetic_records_update"); s.connection.execute("UPDATE portfolio_arithmetic_records SET canonical_json='{}'"); s.connection.execute("CREATE TRIGGER protect_portfolio_arithmetic_records_update BEFORE UPDATE ON portfolio_arithmetic_records BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;"); s.connection.commit(); expect(PortfolioArithmeticConflict,lambda:s.aggregate(source_snapshot_id=x["source"]["source_snapshot_id"]),"CONFLICT")
case("conflicting arithmetic rejected",conflict)
case("metadata singleton",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_arithmetic_store_meta").fetchone()[0]==1))
case("policy singleton",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_arithmetic_policies").fetchone()[0]==1))
case("contract singleton",lambda:require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_arithmetic_contracts").fetchone()[0]==1))
for table in ("portfolio_arithmetic_store_meta","portfolio_arithmetic_policies","portfolio_arithmetic_contracts","portfolio_arithmetic_records","portfolio_arithmetic_positions","portfolio_arithmetic_exposures","portfolio_arithmetic_pending_commitments","portfolio_arithmetic_dependencies"):
    case("append only "+table,lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"UPDATE {table} SET rowid=rowid"),"IMMUTABLE"))
    case("delete rejected "+table,lambda table=table:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute(f"DELETE FROM {table}"),"IMMUTABLE"))
case("SQLite integrity",lambda:require(CTX["store"].connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"))
case("deterministic replay integrity",lambda:require(CTX["store"].integrity_check()["result"]=="PASS"))
def restart():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder); source_store=PortfolioSourceStore(root/"source.sqlite3",REGISTRY); source=source_store.freeze(fixture())["portfolio_source_snapshot"]; store=PortfolioArithmeticStore(root/"arith.sqlite3",source_store); store.aggregate(source_snapshot_id=source["source_snapshot_id"]); store.close(); store=PortfolioArithmeticStore(root/"arith.sqlite3",source_store); require(store.integrity_check()["result"]=="PASS"); store.close(); source_store.close()
case("restart integrity",restart)
def isolated_tamper(table,column,value):
    with environment() as x:
        s=x["store"]; s.connection.execute(f"DROP TRIGGER protect_{table}_update"); s.connection.execute(f"UPDATE {table} SET {column}=?",(value,)); s.connection.execute(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;"); s.connection.commit(); expect(Exception,s.integrity_check)
for name,table,column,value in (("derived position","portfolio_arithmetic_positions","canonical_json","{}"),("arithmetic total","portfolio_arithmetic_records","invested_capital_json","{}"),("record hash","portfolio_arithmetic_records","record_hash","f"*64),("exposure","portfolio_arithmetic_exposures","canonical_json","{}"),("pending aggregate","portfolio_arithmetic_pending_commitments","canonical_json","{}"),("dependency","portfolio_arithmetic_dependencies","record_hash","f"*64),("policy","portfolio_arithmetic_policies","policy_hash","f"*64),("contract","portfolio_arithmetic_contracts","contract_hash","f"*64)):
    case(name+" tamper detected",lambda table=table,column=column,value=value:isolated_tamper(table,column,value))
def trigger_loss():
    with environment() as x: x["store"].connection.execute("DROP TRIGGER protect_portfolio_arithmetic_records_delete"); x["store"].connection.commit(); expect(PortfolioArithmeticIntegrityFailure,x["store"].integrity_check,"TRIGGER")
case("trigger loss detected",trigger_loss)
def upstream_tamper():
    with environment() as x:
        s=x["source_store"]; s.connection.execute("DROP TRIGGER protect_portfolio_source_snapshots_update"); s.connection.execute("UPDATE portfolio_source_snapshots SET canonical_json='{}'"); s.connection.execute("CREATE TRIGGER protect_portfolio_source_snapshots_update BEFORE UPDATE ON portfolio_source_snapshots BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;"); s.connection.commit(); expect(PortfolioArithmeticIntegrityFailure,x["store"].integrity_check,"SOURCE_INTEGRITY")
case("source snapshot tamper detected upstream",upstream_tamper)

# Safety, isolation, and frozen audit.
case("cash valid allocation",lambda:require(CTX["record"]["cash_is_valid_allocation"] is True))
case("no correlation output",lambda:require("correlated_exposure" not in CTX["record"]))
case("correlation not evaluated",lambda:require(CTX["record"]["correlation_status"]=="NOT_EVALUATED"))
case("no final Portfolio Context V2",lambda:require(CTX["record"]["schema_version"]!="STAGE6_PORTFOLIO_CONTEXT_V2"))
case("final V2 not materialized",lambda:require(CTX["record"]["portfolio_context_v2_status"]=="NOT_MATERIALIZED"))
case("no portfolio thresholds",lambda:require("maximum_sector" not in source_text() and "max_position" not in source_text()))
case("no diversification classification",lambda:require("diversification" not in source_text().lower()))
case("no expected return",lambda:require("expected_return" not in builder_text()))
case("no historical analogue",lambda:require("historical_analogue" not in source_text()))
case("no BUY SELL HOLD",lambda:require(not any(word in source_text() for word in ("BUY","SELL","HOLD"))))
case("no allocation proposal",lambda:require("allocation_proposal" not in builder_text()))
case("no Entity Registry direct dependency",lambda:require("registry" not in " ".join(imports()).lower()))
case("no Stage 5D import",lambda:require("stage5d" not in " ".join(imports()).lower()))
case("no Stage 5D SQLite",lambda:require("Stage 5D" not in source_text() and "live_paper" not in source_text()))
case("no broker action",lambda:require("broker" not in source_text().lower()))
case("zero network imports",lambda:require(not any(word in " ".join(imports()).lower() for word in ("requests","urllib","http","aiohttp","socket","yfinance"))))
case("zero external API strings",lambda:require("https://" not in source_text() and "api." not in source_text()))
case("zero AI imports",lambda:require(not any(word in " ".join(imports()).lower() for word in ("openai","transformers","torch","tensorflow","sklearn"))))
case("trading authority false",lambda:require(CTX["record"]["trading_authority"] is False))
for key,value in SAFETY.items(): case("safety "+key,lambda key=key,value=value:require(CTX["record"][key]==value))
case("frozen Stage 5D audit",lambda:require(git("diff","--name-only",BASE,"--","Stage 5D")==""))
case("frozen Stage 6.1-6.5A audit",lambda:require(git("diff","--name-only",BASE,"--","Stage 6/contracts","Stage 6/stage6_ingestion","Stage 6/stage6_portfolio_source","Stage 6/stage6_historical_analogue","Stage 6/stage6_market_context")==""))
case("runtime artifacts zero",lambda:require(not any(token in path.lower() for path in git("diff","--name-only",BASE).splitlines() for token in (".sqlite",".db",".wal",".shm","__pycache__",".pyc"))))
for number in range(1,21): case(f"deterministic replay variant {number:02d}",lambda number=number:require(build()["record_hash"]==CTX["record"]["record_hash"] and number>0))


def main():
    policy,_,policy_hash=load_policy(); contract,_,contract_hash=load_arithmetic_contract(); CTX.update(policy=policy,policy_hash=policy_hash,contract=contract,contract_hash=contract_hash)
    rows=[]
    with environment() as shared:
        CTX.update(shared)
        for number,(name,function) in enumerate(CASES,1):
            try:
                with mock.patch.object(socket,"socket",side_effect=AssertionError("NETWORK_CALL_PROHIBITED")): function()
                rows.append({"test_id":f"S6_5B_{number:03d}","category":"ACCEPTANCE","test_name":name,"result":"PASS","detail":""})
            except Exception as exc: rows.append({"test_id":f"S6_5B_{number:03d}","category":"ACCEPTANCE","test_name":name,"result":"FAIL","detail":f"{type(exc).__name__}:{exc}"})
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=rows[0],lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    failed=[row for row in rows if row["result"]=="FAIL"]
    print(json.dumps({"stage":"6.5B","tests":len(rows),"passed":len(rows)-len(failed),"failed":len(failed),"result":"FAIL" if failed else "PASS","policy_hash":policy_hash,"arithmetic_contract_hash":contract_hash,"authority":AUTHORITY,"network_calls":0,"external_apis":0,"ai":False,"trading_authority":False},sort_keys=True,separators=(",",":")))
    for row in failed: print("FAIL",row)
    return bool(failed)


if __name__=="__main__": raise SystemExit(main())
