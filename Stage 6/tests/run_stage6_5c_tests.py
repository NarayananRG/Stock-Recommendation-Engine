"""Stage 6.5C point-in-time portfolio correlation acceptance tests."""
from __future__ import annotations

import ast
import csv
import json
import socket
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
from stage6_portfolio_source import PortfolioSourceStore
from stage6_portfolio_arithmetic import PortfolioArithmeticStore
from stage6_portfolio_correlation import *
from stage6_portfolio_correlation.correlation_builder import build_portfolio_correlation, canonicalize_manifest
from stage6_portfolio_correlation.correlation_math import BOUNDARY_TOLERANCE, PRECISION, decimal_value, pearson
from stage6_portfolio_correlation.policy import *

BASE = "31527d4c6f61e467306c62607d5d3ab4dd98a9d5"
PARENT = "93b05ded5042423a6fa208cdb29f5961687fdb9c"
PORTFOLIO_BLOB = "5900278a891dc70c63ce02f69002b5e9dec13799"
HISTORICAL_BLOB = "85a2b0d00cacd6a3caea484e3ef3071eb16fe01d"
MARKET_BLOB = "a141b221228718b8276b3d05b2f028d21adcfc3f"
OUT = ROOT / "results" / "stage6_5c_test_results.csv"
SOURCE_FIXTURE = ROOT / "fixtures" / "stage6_5a" / "portfolio_source_examples.json"
RETURN_FIXTURE = ROOT / "fixtures" / "stage6_5c" / "portfolio_correlation_examples.json"
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
def result_count(name):
    rows = list(csv.DictReader((ROOT / "results" / name).open(encoding="utf-8")))
    return len(rows), sum(row["result"] == "PASS" for row in rows)
def fixture(): return json.loads(SOURCE_FIXTURE.read_text(encoding="utf-8"))["inr"]
def manifest(): return deepcopy(json.loads(RETURN_FIXTURE.read_text(encoding="utf-8"))["two_company_daily"])
def changed(value, path, replacement):
    value = deepcopy(value); target = value
    for key in path[:-1]: target = target[key]
    target[path[-1]] = replacement
    return value


def custom_registry():
    records = deepcopy(REGISTRY["entities"])
    sector = deepcopy(records[1]); sector.update(entity_id="S6FIX_SECTOR_FINANCE", canonical_name="Fixture Finance Sector"); sector.pop("record_hash", None)
    company = deepcopy(records[0]); company.update(entity_id="S6FIX_COMPANY_002", canonical_name="Fixture Finance Limited", legal_name="Fixture Finance Limited", isin="FIXTUREISIN002", sector_entity_id="S6FIX_SECTOR_FINANCE", subsector_entity_id=None, ticker_mappings=[{"exchange":"FIXTURE_EXCHANGE","ticker":"FIX2","effective_from":"2026-01-01","effective_to":None}], aliases=[]); company.pop("record_hash", None)
    records.extend((sector, company))
    return build_entity_registry(records, "2026-01-02T00:00:00Z")


def multi_source():
    value = fixture(); value["source_export_id"] += "_CORR"; value["source_export_hash"] = "b" * 64
    item = deepcopy(value["open_positions"][0])
    item.update(company_entity_id="S6FIX_COMPANY_002", ticker="FIX2", recommendation_id="REC_FIX_002",
                source_position_snapshot_id="POS_FIX_002", source_position_snapshot_hash="7" * 64,
                transaction_fill_ids=["FILL_FIX_003"], quantity=50, sector_entity_id="S6FIX_SECTOR_FINANCE")
    item["source_record_bindings"] = [
        {"record_type":"RECOMMENDATION","record_id":"REC_FIX_002","record_hash":"8"*64,"recorded_or_persisted_at_utc":"2026-04-28T10:00:00Z"},
        {"record_type":"TRANSACTION_FILL","record_id":"FILL_FIX_003","record_hash":"7"*64,"recorded_or_persisted_at_utc":"2026-04-28T10:01:00Z"}]
    value["open_positions"].append(item)
    return value


@contextmanager
def environment(source=None, returns=None):
    with tempfile.TemporaryDirectory(prefix="stage6_5c_") as folder:
        root = Path(folder)
        source_store = PortfolioSourceStore(root / "source.sqlite3", custom_registry())
        source_record = source_store.freeze(source or multi_source())["portfolio_source_snapshot"]
        arithmetic_store = PortfolioArithmeticStore(root / "arithmetic.sqlite3", source_store)
        arithmetic = arithmetic_store.aggregate(source_snapshot_id=source_record["source_snapshot_id"])["portfolio_arithmetic"]
        correlation_store = PortfolioCorrelationStore(root / "correlation.sqlite3", arithmetic_store)
        correlation = correlation_store.calculate(arithmetic_record_id=arithmetic["arithmetic_record_id"], return_history_manifest=returns or manifest())["portfolio_correlation"]
        try:
            yield {"root": root, "source_store": source_store, "arithmetic_store": arithmetic_store,
                   "arithmetic": arithmetic, "store": correlation_store, "record": correlation}
        finally:
            correlation_store.close(); arithmetic_store.close(); source_store.close()


def build(arithmetic=None, returns=None):
    return build_portfolio_correlation(arithmetic_record=arithmetic or CTX["arithmetic"],
        return_history_manifest=returns or manifest(), policy_hash=CTX["policy_hash"],
        correlation_contract_hash=CTX["contract_hash"])


def missing_manifest():
    value = manifest(); value["series"][1] = {"company_entity_id":"S6FIX_COMPANY_002","status":"MISSING","observations":[]}; return value


def code_text(): return "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "stage6_portfolio_correlation").glob("*.py"))
def imports():
    result=set()
    for path in (ROOT / "stage6_portfolio_correlation").glob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8")); result|={n.names[0].name for n in ast.walk(tree) if isinstance(n,ast.Import)}; result|={str(n.module) for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
    return result


# Baseline, regression, identity, and frozen contracts.
case("exact Stage 6.5B baseline ancestor", lambda: require(git("merge-base", "HEAD", BASE) == BASE))
case("exact Stage 6.5B parent lineage", lambda: require(git("rev-parse", f"{BASE}^") == PARENT))
case("portfolio intelligence branch", lambda: require(git("branch", "--show-current") == "stage6-portfolio-intelligence"))
case("Stage 6.5B regression", lambda: require(result_count("stage6_5b_test_results.csv") == (204, 204)))
PRIOR_FILES = [f"stage6_{x}_test_results.csv" for x in ("1a","1b","1c","2a","2b","2c","2d","2e","2f","3a","3b","3c","3d","3e","3f","3g","3h","3i","4a","4b","4c","4d","4e","5a","5b")]
case("prior regressions 1947", lambda: require(sum(result_count(n)[0] for n in PRIOR_FILES) == 1947 and sum(result_count(n)[1] for n in PRIOR_FILES) == 1947))
case("portfolio contract blob", lambda: require(git("hash-object", "Stage 6/contracts/portfolio_context.schema.json") == PORTFOLIO_BLOB))
case("historical contract blob", lambda: require(git("hash-object", "Stage 6/contracts/historical_analogue.schema.json") == HISTORICAL_BLOB))
case("market contract blob", lambda: require(git("hash-object", "Stage 6/contracts/market_context.schema.json") == MARKET_BLOB))
case("schema identity", lambda: require(SCHEMA_VERSION == "STAGE6_PORTFOLIO_CORRELATION_CONTEXT_V1"))
case("store identity", lambda: require(STORE_SCHEMA_VERSION == "STAGE6_5C_PORTFOLIO_CORRELATION_STORE_V1"))
case("processor identity", lambda: require(PROCESSOR_VERSION == "STAGE6_5C_PORTFOLIO_CORRELATION_CALCULATOR_V1"))
case("policy identity", lambda: require(POLICY_ID == "S6PORTCORRPOL_STAGE6_5C_V1"))
case("correlation contract identity", lambda: require(CORRELATION_CONTRACT_VERSION == "STAGE6_PORTFOLIO_CORRELATION_CONTRACT_V1"))
case("policy canonical hash", lambda: require(load_policy()[2] == EXPECTED_POLICY_HASH_V1))
case("correlation contract canonical hash", lambda: require(load_correlation_contract()[2] == EXPECTED_CORRELATION_CONTRACT_HASH_V1))
case("method identity", lambda: require(METHOD == "PEARSON_PAIRWISE_COMPLETE_V1"))
case("authority SHADOW_ONLY", lambda: require(AUTHORITY == CTX["record"]["authority"] == "SHADOW_ONLY"))

# Exact 6.5B boundary and member universe.
case("exact arithmetic ID", lambda: require(CTX["record"]["arithmetic_record_id"] == CTX["arithmetic"]["arithmetic_record_id"]))
case("exact arithmetic hash", lambda: require(CTX["record"]["arithmetic_record_hash"] == CTX["arithmetic"]["record_hash"]))
case("arithmetic integrity required", lambda: require(CTX["arithmetic_store"].integrity_check()["result"] == "PASS"))
case("arithmetic schema exact", lambda: require(CTX["arithmetic"]["schema_version"] == SOURCE_SCHEMA_VERSION))
case("arithmetic processor exact", lambda: require(CTX["arithmetic"]["processor_version"] == SOURCE_PROCESSOR_VERSION))
case("arithmetic policy exact", lambda: require((CTX["arithmetic"]["policy_id"], CTX["arithmetic"]["policy_hash"]) == (SOURCE_POLICY_ID, SOURCE_POLICY_HASH)))
case("arithmetic contract exact", lambda: require((CTX["arithmetic"]["arithmetic_contract_version"], CTX["arithmetic"]["arithmetic_contract_hash"]) == (SOURCE_CONTRACT_VERSION, SOURCE_CONTRACT_HASH)))
case("arithmetic authority exact", lambda: require(CTX["arithmetic"]["authority"] == "SHADOW_ONLY"))
case("source binding preserved", lambda: require(CTX["record"]["source_snapshot_id"] == CTX["arithmetic"]["source_snapshot_id"]))
case("source as-of preserved", lambda: require(CTX["record"]["source_as_of_timestamp"] == CTX["arithmetic"]["source_as_of_timestamp"]))
case("portfolio cutoff preserved", lambda: require(CTX["record"]["portfolio_data_cutoff_timestamp"] == CTX["arithmetic"]["data_cutoff_timestamp"]))
case("currency preserved", lambda: require(CTX["record"]["currency"] == CTX["arithmetic"]["currency"]))
case("unique held companies", lambda: require(CTX["record"]["held_member_ids"] == ["S6FIX_COMPANY_001", "S6FIX_COMPANY_002"]))
case("same company deduplicated", lambda: require(len(CTX["record"]["held_member_ids"]) == len(set(CTX["record"]["held_member_ids"]))))
case("ticker not member", lambda: require("FIX2" not in CTX["record"]["held_member_ids"]))
case("pending excluded", lambda: require(set(CTX["record"]["held_member_ids"]) == {x["company_entity_id"] for x in CTX["arithmetic"]["derived_open_positions"]}))

def arithmetic_with_members(count):
    value=deepcopy(CTX["arithmetic"]); template=deepcopy(value["derived_open_positions"][0]); value["derived_open_positions"]=[]
    for index in range(count):
        item=deepcopy(template); item["company_entity_id"]=f"COMPANY_{index:03d}"; item["ticker"]=f"T{index}"; item["recommendation_id"]=f"R{index}"; value["derived_open_positions"].append(item)
    value["arithmetic_record_id"]="S6PORTARITH_"+canonical_hash(without(value,"arithmetic_record_id","record_hash"))[:24]; value["record_hash"]=canonical_hash(without(value,"record_hash")); return value
def manifest_for_members(members):
    value=manifest(); value["series"]=[]
    for company in members:
        series=deepcopy(manifest()["series"][0]); series["company_entity_id"]=company; value["series"].append(series)
    return value
case("zero holdings zero pairs", lambda: require(build(arithmetic_with_members(0), manifest_for_members([]))["pairwise_correlations"] == []))
case("one company zero pairs", lambda: require(build(arithmetic_with_members(1), manifest_for_members(["COMPANY_000"]))["pairwise_correlations"] == []))
case("two companies one pair", lambda: require(len(CTX["record"]["pairwise_correlations"]) == 1))
case("three companies three pairs", lambda: require(len(build(arithmetic_with_members(3), manifest_for_members(["COMPANY_000","COMPANY_001","COMPANY_002"]))["pairwise_correlations"]) == 3))
case("canonical pair ordering", lambda: require(CTX["record"]["pairwise_correlations"][0]["correlation"]["members"] == sorted(CTX["record"]["held_member_ids"])))
case("pair universe deterministic", lambda: require(build()["pairwise_correlations"] == build()["pairwise_correlations"]))

# Manifest identity, coverage, chronology, and observations.
case("explicit manifest required", lambda: expect(Stage6PortfolioCorrelationError, lambda: build_portfolio_correlation(arithmetic_record=CTX["arithmetic"], return_history_manifest=None, policy_hash=CTX["policy_hash"], correlation_contract_hash=CTX["contract_hash"])))
for field in ("source_export_id", "source_schema_version", "source_dataset_id"):
    case(field + " required", lambda field=field: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),[field],"")), "REQUIRED"))
case("export hash required", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["source_export_hash"],"bad"))))
case("FIXTURE source accepted", lambda: require(CTX["record"]["return_history_manifest"]["source_system"] == "FIXTURE"))
case("PIT export source accepted", lambda: require(build(returns=changed(manifest(),["source_system"],"PIT_RETURN_EXPORT"))["return_history_manifest"]["source_system"] == "PIT_RETURN_EXPORT"))
case("unknown source rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["source_system"],"LIVE"))))
case("exact company coverage", lambda: require({x["company_entity_id"] for x in CTX["record"]["return_history_manifest"]["series"]} == set(CTX["record"]["held_member_ids"])))
case("extra company rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=manifest_for_members(["S6FIX_COMPANY_001","S6FIX_COMPANY_002","EXTRA"]))))
case("missing company rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=manifest_for_members(["S6FIX_COMPANY_001"]))))
def duplicate_series():
    value=manifest(); value["series"].append(deepcopy(value["series"][0])); return value
case("duplicate company rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=duplicate_series()), "DUPLICATE"))
case("missing series explicit", lambda: require(build(returns=missing_manifest())["pairwise_correlations"][0]["calculation_status"] == "MISSING_SERIES"))
case("missing series requires empty", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["series",0,"status"],"MISSING")), "MUST_BE_EMPTY"))
case("percent return accepted", lambda: require(CTX["record"]["return_unit"] == "PERCENT_RETURN"))
def decimal_manifest():
    value=manifest(); value["return_unit"]="DECIMAL_RETURN"
    for series in value["series"]:
        for obs in series["observations"]: obs["return_unit"]="DECIMAL_RETURN"
    return value
case("decimal return accepted", lambda: require(build(returns=decimal_manifest())["return_unit"] == "DECIMAL_RETURN"))
case("mixed unit rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["series",0,"observations",0,"return_unit"],"DECIMAL_RETURN")), "MIXED"))
case("no unit conversion", lambda: require(CTX["record"]["return_history_manifest"]["series"][0]["observations"][0]["return_value"] == 1))
for frequency in ("DAILY","WEEKLY","MONTHLY"):
    case(frequency + " accepted", lambda frequency=frequency: require(build(returns=changed(manifest(),["return_frequency"],frequency))["return_frequency"] == frequency))
case("invalid frequency rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["return_frequency"],"HOURLY"))))
case("no resampling", lambda: require("resample" not in code_text().lower()))
case("positive lookback required", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["lookback_window","value"],0))))
for unit in ("DAYS","TRADING_SESSIONS"):
    case(unit + " lookback accepted", lambda unit=unit: require(build(returns=changed(manifest(),["lookback_window","unit"],unit))["lookback_window"]["unit"] == unit))
case("window start required", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["window_start_timestamp"],None))))
case("return cutoff required", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["data_cutoff_timestamp"],None))))
case("return cutoff before portfolio", lambda: require(CTX["record"]["correlation_data_cutoff_timestamp"] <= CTX["record"]["portfolio_data_cutoff_timestamp"]))
case("future return cutoff rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["data_cutoff_timestamp"],"2026-05-02T00:00:00Z")), "AFTER_PORTFOLIO"))
case("return as-of chronology", lambda: require(CTX["record"]["return_history_manifest"]["as_of_timestamp"] <= CTX["record"]["source_as_of_timestamp"]))
case("future return as-of rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["as_of_timestamp"],"2026-05-02T00:00:00Z")), "AFTER_PORTFOLIO"))
case("observation after cutoff rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["series",0,"observations",0,"period_end_utc"],"2026-05-02T00:00:00Z"))))
case("observation before window rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["series",0,"observations",0,"period_end_utc"],"2026-03-01T00:00:00Z"))))
case("future provenance rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["series",0,"observations",0,"source_recorded_at_utc"],"2026-05-02T00:00:00Z")), "PROVENANCE"))
case("observation canonical ordering", lambda: require(CTX["record"]["return_history_manifest"]["series"][0]["observations"] == sorted(CTX["record"]["return_history_manifest"]["series"][0]["observations"],key=lambda x:x["period_end_utc"])))
def duplicate_period():
    value=manifest(); value["series"][0]["observations"].append(deepcopy(value["series"][0]["observations"][0])); return value
case("duplicate period rejected", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=duplicate_period()), "DUPLICATE"))
def reversed_input():
    value=manifest(); value["series"].reverse()
    for series in value["series"]: series["observations"].reverse()
    return value
case("caller observation order irrelevant", lambda: require(build(returns=reversed_input())["record_hash"] == CTX["record"]["record_hash"]))
case("manifest hash deterministic", lambda: require(build(returns=reversed_input())["return_history_manifest_hash"] == CTX["record"]["return_history_manifest_hash"]))

# Alignment, minimums, explicit Pearson, and null behavior.
case("exact timestamp intersection", lambda: require(CTX["record"]["pairwise_correlations"][0]["aligned_observation_count"] == 3))
case("actual observations exact", lambda: require(CTX["record"]["pairwise_correlations"][0]["correlation"]["actual_observations"] == 3))
case("aligned timestamp hash deterministic", lambda: require(len(CTX["record"]["pairwise_correlations"][0]["aligned_timestamp_hash"]) == 64))
for token in ("forward_fill","backfill","interpolate","nearest","fillna","union"):
    case("no " + token, lambda token=token: require(token not in code_text().lower()))
case("minimum integer", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["minimum_observations"],2.5))))
case("minimum at least two", lambda: expect(Stage6PortfolioCorrelationError, lambda: build(returns=changed(manifest(),["minimum_observations"],1))))
case("minimum copied exactly", lambda: require(CTX["record"]["minimum_observations"] == 3))
case("below minimum null", lambda: require(build(returns=changed(manifest(),["minimum_observations"],4))["pairwise_correlations"][0]["correlation"]["value"] is None))
case("below minimum reason", lambda: require(build(returns=changed(manifest(),["minimum_observations"],4))["pairwise_correlations"][0]["null_reason"] == "INSUFFICIENT_OBSERVATIONS"))
case("null not zero", lambda: require(build(returns=changed(manifest(),["minimum_observations"],4))["pairwise_correlations"][0]["correlation"]["value"] != 0))
case("Decimal string input", lambda: require(decimal_value(0.1) == Decimal("0.1")))
case("Decimal precision 50", lambda: require(PRECISION == 50))
case("perfect positive", lambda: require(pearson([1,2,3],[2,4,6]) == Decimal(1)))
case("perfect negative", lambda: require(pearson([1,2,3],[6,4,2]) == Decimal(-1)))
case("uncorrelated fixture", lambda: require(abs(pearson([-1,0,1],[1,-2,1])) == 0))
case("record positive correlation", lambda: require(CTX["record"]["pairwise_correlations"][0]["correlation"]["value"] == 1))
case("explicit mean formula", lambda: require("mean_x = sum(x, ZERO) / n" in code_text()))
case("explicit centered numerator", lambda: require("numerator = sum" in code_text()))
case("explicit denominator", lambda: require("denominator = (sx * sy).sqrt()" in code_text()))
case("no NumPy", lambda: require("numpy" not in imports()))
case("no Pandas", lambda: require("pandas" not in imports()))
case("ddof absent", lambda: require("ddof" not in code_text()))
def zero_variance(side):
    value=manifest()
    for obs in value["series"][side]["observations"]: obs["return_value"]=5
    return build(returns=value)["pairwise_correlations"][0]
case("zero variance X null", lambda: require(zero_variance(0)["correlation"]["value"] is None))
case("zero variance Y null", lambda: require(zero_variance(1)["correlation"]["value"] is None))
case("zero variance reason", lambda: require(zero_variance(0)["null_reason"] == "ZERO_VARIANCE"))
case("correlation bounded", lambda: require(-1 <= CTX["record"]["pairwise_correlations"][0]["correlation"]["value"] <= 1))
case("boundary tolerance frozen", lambda: require(BOUNDARY_TOLERANCE == Decimal("1E-24")))
case("signed negative retained", lambda: require(pearson([1,2,3],[3,2,1]) == Decimal(-1)))
case("no absolute transform", lambda: require("abs(result)" not in code_text()))

# Final-compatible projection and deliberate non-authority.
PAIR = lambda: CTX["record"]["pairwise_correlations"][0]
case("final members", lambda: require(PAIR()["correlation"]["members"] == ["S6FIX_COMPANY_001","S6FIX_COMPANY_002"]))
case("method exact", lambda: require(PAIR()["correlation"]["method"] == METHOD))
case("unit correlation", lambda: require(PAIR()["correlation"]["unit"] == "CORRELATION"))
case("return frequency exact", lambda: require(PAIR()["correlation"]["return_frequency"] == "DAILY"))
case("lookback exact", lambda: require(PAIR()["correlation"]["lookback_window"] == manifest()["lookback_window"]))
case("minimum exact", lambda: require(PAIR()["correlation"]["minimum_observations"] == 3))
case("cutoff exact", lambda: require(PAIR()["correlation"]["data_cutoff_timestamp"] == manifest()["data_cutoff_timestamp"]))
case("missing gives null", lambda: require(build(returns=missing_manifest())["pairwise_correlations"][0]["correlation"]["value"] is None))
case("missing reason exact", lambda: require(build(returns=missing_manifest())["pairwise_correlations"][0]["null_reason"] == "MISSING_SERIES"))
case("deterministic context ID", lambda: require(build()["correlation_context_id"] == CTX["record"]["correlation_context_id"]))
case("deterministic record hash", lambda: require(build()["record_hash"] == CTX["record"]["record_hash"]))
case("record validates", lambda: require(validate_portfolio_correlation(CTX["record"]) == CTX["record"]))
case("correlation evaluated", lambda: require(CTX["record"]["correlation_status"] == "EVALUATED"))
case("interpretation not evaluated", lambda: require(CTX["record"]["correlation_interpretation_status"] == "NOT_EVALUATED"))
case("correlated capital not evaluated", lambda: require(CTX["record"]["correlated_capital_status"] == "NOT_EVALUATED"))
case("Portfolio Context not materialized", lambda: require(CTX["record"]["portfolio_context_v2_status"] == "NOT_MATERIALIZED"))
case("constraints not evaluated", lambda: require(CTX["record"]["portfolio_constraints_status"] == "NOT_EVALUATED"))
case("influence not evaluated", lambda: require(CTX["record"]["portfolio_influence_status"] == "NOT_EVALUATED"))
case("BUY SELL HOLD not evaluated", lambda: require(CTX["record"]["buy_sell_hold_status"] == "NOT_EVALUATED"))
case("trading authority false", lambda: require(CTX["record"]["trading_authority"] is False))
for token in ("HIGH_CORRELATION","LOW_CORRELATION","cluster","diversification_score","beta","NIFTY","covariance","correlated_capital_amount","BUY","SELL","HOLD"):
    case("prohibited semantic absent " + token, lambda token=token: require(token not in canonical_json(CTX["record"])))

# Persistence, append-only behavior, conflict, and deterministic replay.
case("store integrity", lambda: require(CTX["store"].integrity_check()["result"] == "PASS"))
case("idempotency", lambda: require(CTX["store"].calculate(arithmetic_record_id=CTX["arithmetic"]["arithmetic_record_id"], return_history_manifest=manifest())["status"] == "IDEMPOTENT_SUCCESS"))
case("exact direct dependencies", lambda: require({r[0] for r in CTX["store"].connection.execute("SELECT record_type FROM portfolio_correlation_dependencies")} == {"STAGE6_5B_PORTFOLIO_ARITHMETIC","STAGE6_5C_POLICY","STAGE6_5C_CORRELATION_CONTRACT"}))
case("no transitive dependencies", lambda: require(CTX["store"].connection.execute("SELECT COUNT(*) FROM portfolio_correlation_dependencies").fetchone()[0] == 3))
def conflict():
    value=manifest(); value["series"][0]["observations"][0]["return_value"]=99
    return CTX["store"].calculate(arithmetic_record_id=CTX["arithmetic"]["arithmetic_record_id"], return_history_manifest=value)
case("export ID conflict", lambda: expect(PortfolioCorrelationConflict, conflict))
for table in ("portfolio_correlation_store_meta","portfolio_correlation_policies","portfolio_correlation_contracts","portfolio_correlation_records","portfolio_correlation_series","portfolio_correlation_observations","portfolio_correlation_pairs","portfolio_correlation_source_bindings","portfolio_correlation_dependencies"):
    case("append-only " + table, lambda table=table: expect(Exception, lambda: CTX["store"].connection.execute(f"UPDATE {table} SET rowid=rowid"), "IMMUTABLE"))
case("SQLite integrity", lambda: require(CTX["store"].connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"))
def restart_integrity():
    with PortfolioCorrelationStore(CTX["root"] / "correlation.sqlite3", CTX["arithmetic_store"]) as reopened: return reopened.integrity_check()["result"]
case("restart integrity", lambda: require(restart_integrity() == "PASS"))

def tamper(table, column, where="1=1"):
    with environment() as env:
        connection=env["store"].connection
        connection.execute(f"DROP TRIGGER protect_{table}_update")
        connection.execute(f"UPDATE {table} SET {column}='tampered' WHERE {where}")
        connection.commit()
        return expect(PortfolioCorrelationIntegrityFailure, env["store"].integrity_check)
case("trigger loss detection", lambda: require(tamper("portfolio_correlation_records","record_hash")))
case("series tamper detection", lambda: require(tamper("portfolio_correlation_series","canonical_json")))
case("observation tamper detection", lambda: require(tamper("portfolio_correlation_observations","canonical_json")))
case("pair tamper detection", lambda: require(tamper("portfolio_correlation_pairs","canonical_json")))
case("source binding tamper detection", lambda: require(tamper("portfolio_correlation_source_bindings","canonical_json")))
case("dependency tamper detection", lambda: require(tamper("portfolio_correlation_dependencies","record_hash")))
case("policy tamper detection", lambda: require(tamper("portfolio_correlation_policies","canonical_json")))
case("contract tamper detection", lambda: require(tamper("portfolio_correlation_contracts","canonical_json")))
case("deterministic replay", lambda: require(CTX["store"].integrity_check()["portfolio_correlation_records"] == 1))

# Static boundaries and network denial.
case("no final Portfolio Context V2", lambda: require("STAGE6_PORTFOLIO_CONTEXT_V2" not in canonical_json(CTX["record"])))
case("no direct 6.5A import", lambda: require(not any("stage6_portfolio_source" in x for x in imports())))
case("no Stage 5D import", lambda: require(not any("stage5" in x.lower() for x in imports())))
case("no Stage 6.4 import", lambda: require(not any("analogue" in x.lower() or "market_context" in x.lower() for x in imports())))
case("no Entity Registry import", lambda: require(not any("registry" in x.lower() for x in imports())))
case("no position weighting", lambda: require("held_market_value" not in code_text()))
case("no risk weighting", lambda: require("risk_at_stop" not in code_text()))
case("no market data download", lambda: require(not ({"requests","urllib","httpx","yfinance","pandas_datareader"} & imports())))
case("zero AI imports", lambda: require(not ({"openai","transformers","torch","tensorflow","sklearn","spacy"} & imports())))
case("no broker imports", lambda: require(not ({"kiteconnect","ib_insync","alpaca_trade_api"} & imports())))
def blocked_network():
    with mock.patch.object(socket, "create_connection", side_effect=AssertionError("network called")):
        require(build()["record_hash"] == CTX["record"]["record_hash"])
case("zero network execution", blocked_network)
case("fixture only", lambda: require(CTX["record"]["return_history_manifest"]["source_system"] == "FIXTURE"))


def run():
    policy_hash = load_policy()[2]; contract_hash = load_correlation_contract()[2]
    with environment() as env:
        CTX.update(env, policy_hash=policy_hash, contract_hash=contract_hash)
        rows=[]
        for index,(name,function) in enumerate(CASES,1):
            try: function(); result="PASS"; detail=""
            except Exception as exc: result="FAIL"; detail=f"{type(exc).__name__}: {exc}"
            rows.append({"test_id":index,"test_name":name,"result":result,"detail":detail})
        OUT.parent.mkdir(parents=True,exist_ok=True)
        with OUT.open("w",newline="",encoding="utf-8") as handle:
            writer=csv.DictWriter(handle,fieldnames=("test_id","test_name","result","detail")); writer.writeheader(); writer.writerows(rows)
        passed=sum(r["result"]=="PASS" for r in rows)
        print(f"Stage 6.5C: {passed}/{len(rows)} PASS")
        for row in rows:
            if row["result"]=="FAIL": print(f"FAIL {row['test_id']} {row['test_name']}: {row['detail']}")
        return 0 if passed==len(rows) and len(rows)>=150 else 1


if __name__ == "__main__": raise SystemExit(run())
