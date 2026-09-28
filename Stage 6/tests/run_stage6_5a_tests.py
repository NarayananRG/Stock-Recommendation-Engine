"""Stage 6.5A immutable portfolio constituent source acceptance tests."""
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
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from stage6_ingestion.fixtures import build_fixture_registries
from stage6_ingestion.registry import build_entity_registry
from stage6_portfolio_source import *
from stage6_portfolio_source.policy import *
from stage6_portfolio_source.portfolio_source_builder import build_portfolio_source_snapshot

BASE = "f150608994fbeea3b79d2a078642dee89e4f6a59"
HISTORICAL_ANALOGUE_BLOB = "85a2b0d00cacd6a3caea484e3ef3071eb16fe01d"
MARKET_CONTEXT_BLOB = "a141b221228718b8276b3d05b2f028d21adcfc3f"
OUT = ROOT / "results" / "stage6_5a_test_results.csv"
FIXTURE_PATH = ROOT / "fixtures" / "stage6_5a" / "portfolio_source_examples.json"
REGISTRY = build_fixture_registries()["entity_v1"]
CASES = []
CTX = {}


def case(name, function):
    CASES.append((name, function))


def require(value, message="assertion failed"):
    if not value:
        raise AssertionError(message)


def expect(error, function, contains=None):
    try:
        function()
    except error as exc:
        if contains:
            require(contains in str(exc), str(exc))
        return exc
    raise AssertionError("expected " + error.__name__)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["inr"]


def build(value=None, registry=None):
    return build_portfolio_source_snapshot(
        source_export=value or fixture(), entity_registry=registry or REGISTRY,
        policy_hash=CTX["policy_hash"], constituent_contract_hash=CTX["contract_hash"])


@contextmanager
def environment(value=None, registry=None):
    with tempfile.TemporaryDirectory(prefix="stage6_5a_") as folder:
        store = PortfolioSourceStore(Path(folder) / "portfolio_source.sqlite3", registry or REGISTRY)
        result = store.freeze(value or fixture())
        try:
            yield store, result["portfolio_source_snapshot"]
        finally:
            store.close()


def changed(value, path, replacement):
    value = deepcopy(value)
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    return value


def result_count(name):
    rows = list(csv.DictReader((ROOT / "results" / name).open(encoding="utf-8")))
    return len(rows), sum(row["result"] == "PASS" for row in rows)


def source_text():
    return "\n".join(path.read_text(encoding="utf-8") for path in
                     (ROOT / "stage6_portfolio_source").glob("*.py"))


def imports():
    result = set()
    for path in (ROOT / "stage6_portfolio_source").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        result |= {node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import)}
        result |= {str(node.module) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    return result


def extra_position(value, recommendation="REC_FIX_000"):
    item = deepcopy(value["open_positions"][0])
    item["recommendation_id"] = recommendation
    item["source_position_snapshot_id"] = "POS_" + recommendation
    item["source_position_snapshot_hash"] = "7" * 64
    item["transaction_fill_ids"] = ["FILL_" + recommendation]
    item["source_record_bindings"] = [{
        "record_type": "RECOMMENDATION", "record_id": recommendation,
        "record_hash": "8" * 64, "recorded_or_persisted_at_utc": "2026-04-28T10:00:00Z"}, {
        "record_type": "TRANSACTION_FILL", "record_id": "FILL_" + recommendation,
        "record_hash": "7" * 64, "recorded_or_persisted_at_utc": "2026-04-28T10:01:00Z"}]
    return item


def extra_pending(value, recommendation="REC_FIX_PENDING_000"):
    item = deepcopy(value["pending_entries"][0])
    item["recommendation_id"] = recommendation
    item["source_record_id"] = recommendation
    item["source_record_hash"] = "9" * 64
    item["source_record_bindings"] = [{
        "record_type": "RECOMMENDATION", "record_id": recommendation,
        "record_hash": "9" * 64, "recorded_or_persisted_at_utc": "2026-04-28T10:00:00Z"}]
    return item


# Baseline, identities, and frozen contracts.
case("exact Stage 6.4E baseline ancestor", lambda: require(git("merge-base", "HEAD", BASE) == BASE))
case("portfolio intelligence branch", lambda: require(git("branch", "--show-current") == "stage6-portfolio-intelligence"))
case("Stage 6.4E regression evidence", lambda: require(result_count("stage6_4e_test_results.csv") == (179, 179)))
case("existing total regression evidence", lambda: require(sum(result_count(name)[0] for name in [
    "stage6_1a_test_results.csv", "stage6_1b_test_results.csv", "stage6_1c_test_results.csv",
    "stage6_2a_test_results.csv", "stage6_2b_test_results.csv", "stage6_2c_test_results.csv",
    "stage6_2d_test_results.csv", "stage6_2e_test_results.csv", "stage6_2f_test_results.csv",
    "stage6_3a_test_results.csv", "stage6_3b_test_results.csv", "stage6_3c_test_results.csv",
    "stage6_3d_test_results.csv", "stage6_3e_test_results.csv", "stage6_3f_test_results.csv",
    "stage6_3g_test_results.csv", "stage6_3h_test_results.csv", "stage6_3i_test_results.csv",
    "stage6_4a_test_results.csv", "stage6_4b_test_results.csv", "stage6_4c_test_results.csv",
    "stage6_4d_test_results.csv", "stage6_4e_test_results.csv"]) == 1572))
case("portfolio contract blob exact", lambda: require(git("hash-object", "Stage 6/contracts/portfolio_context.schema.json") == PORTFOLIO_CONTEXT_BLOB))
case("historical contract blob exact", lambda: require(git("hash-object", "Stage 6/contracts/historical_analogue.schema.json") == HISTORICAL_ANALOGUE_BLOB))
case("market contract blob exact", lambda: require(git("hash-object", "Stage 6/contracts/market_context.schema.json") == MARKET_CONTEXT_BLOB))
case("source schema identity", lambda: require(SCHEMA_VERSION == "STAGE6_PORTFOLIO_SOURCE_SNAPSHOT_V1"))
case("store identity", lambda: require(STORE_SCHEMA_VERSION == "STAGE6_5A_PORTFOLIO_SOURCE_STORE_V1"))
case("processor identity", lambda: require(PROCESSOR_VERSION == "STAGE6_5A_PORTFOLIO_SOURCE_FREEZER_V1"))
case("policy identity", lambda: require(POLICY_ID == "S6PORTSRCPOL_STAGE6_5A_V1"))
case("constituent contract identity", lambda: require(CONSTITUENT_CONTRACT_VERSION == "STAGE6_PORTFOLIO_CONSTITUENT_CONTRACT_V1"))
case("policy canonical hash", lambda: require(load_policy()[2] == canonical_hash(load_policy()[0]) == EXPECTED_POLICY_HASH_V1))
case("contract canonical hash", lambda: require(load_constituent_contract()[2] == canonical_hash(load_constituent_contract()[0]) == EXPECTED_CONSTITUENT_CONTRACT_HASH_V1))
case("authority shadow only", lambda: require(AUTHORITY == "SHADOW_ONLY"))
case("Stage5D5 reference exact", lambda: require(STAGE5D5_REFERENCE_COMMIT == "74b2710f0e19bd403978da81e87f25a3059ace06"))

# Source export and chronology.
case("fixture source accepted", lambda: validate_portfolio_source_snapshot(build()))
def paper_export():
    value = fixture(); value["source_system"] = "STAGE5D5_PAPER_EXPORT"; return value
case("Stage5D5 paper export accepted", lambda: validate_portfolio_source_snapshot(build(paper_export())))
case("wrong Stage5D5 commit rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(paper_export(), ["source_stage5d5_commit"], "0" * 40)), "COMMIT"))
case("source export ID required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["source_export_id"], "")), "REQUIRED"))
case("source export hash required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["source_export_hash"], "")), "REQUIRED"))
case("source export hash exact length", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["source_export_hash"], "a" * 63)), "HASH"))
case("source database identity required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["source_database_id"], "")), "REQUIRED"))
case("source schema identity required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["source_schema_version"], "")), "REQUIRED"))
case("cutoff before as-of accepted", lambda: require(build()["data_cutoff_timestamp"] < build()["as_of_timestamp"]))
case("cutoff equal as-of accepted", lambda: validate_portfolio_source_snapshot(build(changed(fixture(), ["as_of_timestamp"], fixture()["data_cutoff_timestamp"]))))
case("cutoff after as-of rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["data_cutoff_timestamp"], "2026-05-02T00:00:00Z")), "CUTOFF"))
case("future price observation rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "current_price", "observed_at_utc"], "2026-05-02T00:00:00Z")), "FUTURE"))
case("future risk observation rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "risk_at_stop", "observed_at_utc"], "2026-05-02T00:00:00Z")), "FUTURE"))
case("future source binding rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "source_record_bindings", 0, "recorded_or_persisted_at_utc"], "2026-05-02T00:00:00Z")), "FUTURE"))
case("future pending source timestamp rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["pending_entries", 0, "source_effective_or_recorded_timestamp"], "2026-05-02T00:00:00Z")), "FUTURE"))
case("future registry rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["data_cutoff_timestamp"], "2025-12-01T00:00:00Z")), "REGISTRY"))

# Currency and numeric facts.
case("INR accepted", lambda: require(build()["currency"] == "INR"))
def usd():
    value = fixture(); value["source_export_id"] += "_USD"; value["currency"] = "USD"
    value["capital_ceiling"]["currency"] = "USD"
    for item in value["open_positions"]:
        item["current_price"]["currency"] = "USD"; item["average_cost_per_share"]["currency"] = "USD"; item["risk_at_stop"]["currency"] = "USD"
    for item in value["pending_entries"]: item["committed_reserved_capital"]["currency"] = "USD"
    return value
case("USD accepted", lambda: require(build(usd())["currency"] == "USD"))
case("unsupported currency rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["currency"], "EUR")), "CURRENCY"))
case("mixed current price currency rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "current_price", "currency"], "USD")), "MIXED"))
case("mixed risk currency rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "risk_at_stop", "currency"], "USD")), "MIXED"))
case("mixed pending currency rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["pending_entries", 0, "committed_reserved_capital", "currency"], "USD")), "MIXED"))
case("no FX conversion", lambda: require("exchange_rate" not in source_text() and build(usd())["capital_ceiling"]["value"] == fixture()["capital_ceiling"]["value"]))
case("capital ceiling zero accepted", lambda: require(build(changed(fixture(), ["capital_ceiling", "value"], 0))["capital_ceiling"]["value"] == 0))
case("capital ceiling negative rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["capital_ceiling", "value"], -1)), "RANGE"))
case("capital ceiling nonfinite rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["capital_ceiling", "value"], math.inf)), "NUMBER"))
case("positive whole quantity accepted", lambda: require(build()["open_positions"][0]["quantity"] == 100))
for name, quantity in (("zero quantity", 0), ("negative quantity", -1), ("fractional quantity", 1.5), ("boolean quantity", True)):
    case(name + " rejected", lambda quantity=quantity: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "quantity"], quantity)), "QUANTITY"))
case("positive current price accepted", lambda: require(build()["open_positions"][0]["current_price"]["value"] == 125.5))
for name, price in (("zero current price", 0), ("negative current price", -1), ("nonfinite current price", float("nan")), ("boolean current price", True)):
    case(name + " rejected", lambda price=price: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "current_price", "value"], price))))
case("average cost preserved", lambda: require(build()["open_positions"][0]["average_cost_per_share"]["value"] == 110.0))
case("average cost zero accepted", lambda: require(build(changed(fixture(), ["open_positions", 0, "average_cost_per_share", "value"], 0))["open_positions"][0]["average_cost_per_share"]["value"] == 0))
case("negative average cost rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "average_cost_per_share", "value"], -1))))
case("explicit risk preserved", lambda: require(build()["open_positions"][0]["risk_at_stop"]["value"] == 750.0))
case("risk method required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "risk_at_stop", "method"], "")), "REQUIRED"))
case("risk zero accepted", lambda: require(build(changed(fixture(), ["open_positions", 0, "risk_at_stop", "value"], 0))["open_positions"][0]["risk_at_stop"]["value"] == 0))
case("negative risk rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "risk_at_stop", "value"], -1))))
case("pending reservation preserved", lambda: require(build()["pending_entries"][0]["committed_reserved_capital"]["value"] == 25000.0))
case("pending reservation zero accepted", lambda: require(build(changed(fixture(), ["pending_entries", 0, "committed_reserved_capital", "value"], 0))["pending_entries"][0]["committed_reserved_capital"]["value"] == 0))
case("pending reservation negative rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["pending_entries", 0, "committed_reserved_capital", "value"], -1))))

# Identities, registry PIT, canonicalization, and provenance.
case("recommendation ID required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "recommendation_id"], "")), "REQUIRED"))
case("fill list required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "transaction_fill_ids"], [])), "FILL"))
case("fill IDs unique", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "transaction_fill_ids"], ["A", "A"])), "DUPLICATE"))
case("recommendation binding required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "source_record_bindings"], [x for x in fixture()["open_positions"][0]["source_record_bindings"] if x["record_type"] != "RECOMMENDATION"])), "RECOMMENDATION_BINDING"))
case("fill binding required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "source_record_bindings"], [x for x in fixture()["open_positions"][0]["source_record_bindings"] if x["record_id"] != "FILL_FIX_001"])), "FILL_BINDING"))
case("pending record binding required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["pending_entries", 0, "source_record_hash"], "a" * 64)), "PENDING_RECORD_BINDING"))
case("ticker PIT resolution", lambda: require(build()["open_positions"][0]["company_entity_id"] == "S6FIX_COMPANY_001"))
case("historical ticker accepted", lambda: require(build()["open_positions"][0]["ticker"] == "FIXOLD"))
case("future ticker rejected", lambda: expect(Exception, lambda: build(changed(fixture(), ["open_positions", 0, "ticker"], "FIXNEW"))))
def future_export():
    value = fixture(); value["as_of_timestamp"] = "2026-08-03T00:00:00Z"; value["data_cutoff_timestamp"] = "2026-08-02T00:00:00Z"
    value["open_positions"][0]["current_price"]["observed_at_utc"] = "2026-08-01T00:00:00Z"
    value["open_positions"][0]["risk_at_stop"]["observed_at_utc"] = "2026-08-01T00:00:00Z"
    return value
case("expired ticker rejected", lambda: expect(Exception, lambda: build(future_export())))
case("company type required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "company_entity_id"], "S6FIX_SECTOR_TECH"))))
case("sector type required", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "sector_entity_id"], "S6FIX_INDEX_001"))))
case("subsector absent accepted when registry relation absent", lambda: require(build()["open_positions"][0]["subsector_entity_id"] is None))
case("invented subsector rejected", lambda: expect(Exception, lambda: build(changed(fixture(), ["open_positions", 0, "subsector_entity_id"], "S6FIX_INDEX_001"))))
def ambiguous_registry():
    records = deepcopy(REGISTRY["entities"])
    company = deepcopy(records[0]); company["entity_id"] = "S6FIX_COMPANY_002"; company["isin"] = "FIXTUREISIN002"
    company["canonical_name"] = "Ambiguous Fixture Company"; company["legal_name"] = "Ambiguous Fixture Company Limited"
    company.pop("record_hash")
    records.append(company)
    return build_entity_registry(records, "2026-01-02T00:00:00Z")
case("ambiguous ticker rejected", lambda: expect(Exception, ambiguous_registry))
case("registry hash exact", lambda: require(build()["entity_registry_hash"] == REGISTRY["registry_hash"]))
case("registry snapshot exact", lambda: require(build()["entity_registry_snapshot_id"] == REGISTRY["registry_snapshot_id"]))
case("paired source bindings", lambda: require(all(set(x) == {"record_type", "record_id", "record_hash", "recorded_or_persisted_at_utc"} for x in build()["open_positions"][0]["source_record_bindings"])))
case("unpaired source binding rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "source_record_bindings", 0], {"record_id": "A", "record_hash": "a" * 64})), "BINDING"))
case("duplicate binding rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions", 0, "source_record_bindings"], [fixture()["open_positions"][0]["source_record_bindings"][0]] * 2)), "DUPLICATE"))
case("fill ordering canonical", lambda: require(build()["open_positions"][0]["transaction_fill_ids"] == sorted(fixture()["open_positions"][0]["transaction_fill_ids"])))
case("binding ordering canonical", lambda: require(build()["open_positions"][0]["source_record_bindings"] == sorted(build()["open_positions"][0]["source_record_bindings"], key=lambda x: (x["record_type"], x["record_id"], x["record_hash"]))))
def order_independent():
    value = fixture(); value["open_positions"].append(extra_position(value)); value["pending_entries"].append(extra_pending(value))
    reverse = deepcopy(value); reverse["open_positions"].reverse(); reverse["pending_entries"].reverse()
    return build(value)["record_hash"] == build(reverse)["record_hash"]
case("caller order does not alter identity", lambda: require(order_independent()))
case("open position ordering canonical", lambda: require(order_independent()))
case("pending ordering canonical", lambda: require(order_independent()))
case("duplicate logical open position rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["open_positions"], fixture()["open_positions"] * 2)), "DUPLICATE_POSITION"))
case("duplicate pending entry rejected", lambda: expect(Stage6PortfolioSourceError, lambda: build(changed(fixture(), ["pending_entries"], fixture()["pending_entries"] * 2)), "DUPLICATE_PENDING"))
case("null thesis accepted", lambda: require(build()["open_positions"][0]["thesis_id"] is None))
case("no fake thesis generated", lambda: require(build()["pending_entries"][0]["thesis_id"] is None))
case("deterministic snapshot ID", lambda: require(build()["source_snapshot_id"] == build()["source_snapshot_id"]))
case("deterministic record hash", lambda: require(build()["record_hash"] == build()["record_hash"]))
case("snapshot ID content addressed", lambda: require(build()["source_snapshot_id"] == "S6PORTSRC_" + canonical_hash(without(build(), "source_snapshot_id", "record_hash"))[:24]))
case("record hash content addressed", lambda: require(build()["record_hash"] == canonical_hash(without(build(), "record_hash"))))

# No calculations or later-stage authority.
PROHIBITED = ("market_value", "cash", "invested_capital", "committed_capital", "available_capital",
              "aggregate_risk_at_stop", "sector_exposure", "subsector_exposure", "correlated_exposure",
              "portfolio_concentration", "portfolio_score", "capital_adequacy")
for field in PROHIBITED:
    case("no calculated " + field, lambda field=field: require(field not in build()))
case("no quantity-price multiplication", lambda: require(str(100 * 125.5) not in canonical_json(build())))
case("no final Portfolio V2", lambda: require(build()["schema_version"] != "STAGE6_PORTFOLIO_CONTEXT_V2"))
case("no Stage 6.4 dependency", lambda: require("historical_analogue" not in source_text() and "stage6_4" not in source_text()))
for key, value in SAFETY.items():
    case("safety " + key, lambda key=key, value=value: require(build()[key] == value))

# Persistence, idempotency, append-only behavior, and tamper checks.
case("idempotency", lambda: require(CTX["store"].freeze(fixture())["status"] == "IDEMPOTENT_SUCCESS"))
def conflict():
    value = fixture(); value["source_export_hash"] = "f" * 64
    expect(PortfolioSourceConflict, lambda: CTX["store"].freeze(value), "CONFLICT")
case("conflicting source export rejected", conflict)
def later_export():
    value = fixture(); value["source_export_id"] += "_LATER"; value["source_export_hash"] = "e" * 64
    require(CTX["store"].freeze(value)["status"] == "CREATED")
case("later export creates new snapshot", later_export)
case("metadata singleton", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_source_store_meta").fetchone()[0] == 1))
case("policy singleton", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_source_policies").fetchone()[0] == 1))
case("contract singleton", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_constituent_contracts").fetchone()[0] == 1))
for table in ("portfolio_source_store_meta", "portfolio_source_policies", "portfolio_constituent_contracts",
              "portfolio_source_snapshots", "portfolio_source_positions", "portfolio_source_pending_entries",
              "portfolio_source_bindings", "portfolio_source_dependencies"):
    case("append only " + table, lambda table=table: expect(sqlite3.DatabaseError, lambda: CTX["store"].connection.execute(f"UPDATE {table} SET rowid=rowid"), "IMMUTABLE"))
    case("delete rejected " + table, lambda table=table: expect(sqlite3.DatabaseError, lambda: CTX["store"].connection.execute(f"DELETE FROM {table}"), "IMMUTABLE"))
case("restart integrity", lambda: require(CTX["store"].integrity_check()["result"] == "PASS"))
case("deterministic replay", lambda: require(build() == CTX["record"]))
case("position exact coverage", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_source_positions").fetchone()[0] >= 1))
case("pending exact coverage", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_source_pending_entries").fetchone()[0] >= 1))
case("source binding exact coverage", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_source_bindings").fetchone()[0] >= 4))
case("registry dependency stored", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_source_dependencies WHERE record_type='ENTITY_REGISTRY'").fetchone()[0] >= 1))
case("entity dependencies stored", lambda: require(CTX["store"].connection.execute("SELECT count(*) FROM portfolio_source_dependencies WHERE record_type='ENTITY_RECORD'").fetchone()[0] >= 2))


def isolated_tamper(table, column, value):
    with environment() as (store, _):
        store.connection.execute(f"DROP TRIGGER protect_{table}_update")
        store.connection.execute(f"UPDATE {table} SET {column}=?", (value,))
        store.connection.execute(f"CREATE TRIGGER protect_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END;")
        store.connection.commit()
        expect(Exception, store.integrity_check)


for name, table, column, value in (
    ("snapshot tamper", "portfolio_source_snapshots", "record_hash", "f" * 64),
    ("position tamper", "portfolio_source_positions", "canonical_json", "{}"),
    ("pending tamper", "portfolio_source_pending_entries", "canonical_json", "{}"),
    ("binding tamper", "portfolio_source_bindings", "record_hash", "f" * 64),
    ("dependency tamper", "portfolio_source_dependencies", "record_hash", "f" * 64),
    ("policy tamper", "portfolio_source_policies", "policy_hash", "f" * 64),
    ("contract tamper", "portfolio_constituent_contracts", "contract_hash", "f" * 64),
):
    case(name + " detected", lambda table=table, column=column, value=value: isolated_tamper(table, column, value))


def trigger_loss():
    with environment() as (store, _):
        store.connection.execute("DROP TRIGGER protect_portfolio_source_snapshots_delete")
        store.connection.commit()
        expect(PortfolioSourceIntegrityFailure, store.integrity_check, "TRIGGER")
case("trigger-loss detection", trigger_loss)

# Isolation and safety audits.
case("zero Stage 5D mutation", lambda: require(git("diff", "--name-only", BASE, "--", "Stage 5D") == ""))
case("no Stage 5D runtime import", lambda: require("stage5d" not in " ".join(imports()).lower()))
case("no live SQLite opening", lambda: require("Stage 5D" not in source_text() and "live_paper" not in source_text()))
case("zero network imports", lambda: require(not any(token in " ".join(imports()).lower() for token in ("requests", "urllib", "http", "aiohttp", "yfinance", "socket"))))
case("zero external API strings", lambda: require(not any(token in source_text().lower() for token in ("https://", "api.", "broker", "yfinance"))))
case("zero AI imports", lambda: require(not any(token in " ".join(imports()).lower() for token in ("openai", "transformers", "torch", "tensorflow", "sklearn"))))
case("trading authority false", lambda: require(build()["trading_authority"] is False))
case("fixture-only tests", lambda: require(load_policy()[0]["fixture_only_tests"] is True))
case("no runtime artifacts in diff", lambda: require(not any(token in path.lower() for path in git("diff", "--name-only", BASE).splitlines() for token in (".sqlite", ".db", ".wal", ".shm", "__pycache__", ".pyc"))))
case("frozen prior stages unchanged", lambda: require(git("diff", "--name-only", BASE, "--", "Stage 6/contracts", "Stage 6/stage6_ingestion", "Stage 6/stage6_historical_analogue", "Stage 6/stage6_market_context") == ""))


def main():
    policy, _, policy_hash = load_policy(); contract, _, contract_hash = load_constituent_contract()
    CTX.update(policy=policy, policy_hash=policy_hash, contract=contract, contract_hash=contract_hash)
    rows = []
    with environment() as (store, record):
        CTX.update(store=store, record=record)
        for number, (name, function) in enumerate(CASES, 1):
            try:
                with mock.patch.object(socket, "socket", side_effect=AssertionError("NETWORK_CALL_PROHIBITED")):
                    function()
                rows.append({"test_id": f"S6_5A_{number:03d}", "category": "ACCEPTANCE", "test_name": name, "result": "PASS", "detail": ""})
            except Exception as exc:
                rows.append({"test_id": f"S6_5A_{number:03d}", "category": "ACCEPTANCE", "test_name": name, "result": "FAIL", "detail": f"{type(exc).__name__}:{exc}"})
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    failed = [row for row in rows if row["result"] == "FAIL"]
    print(json.dumps({"stage": "6.5A", "tests": len(rows), "passed": len(rows)-len(failed), "failed": len(failed),
                      "result": "FAIL" if failed else "PASS", "policy_hash": policy_hash,
                      "constituent_contract_hash": contract_hash, "authority": AUTHORITY,
                      "network_calls": 0, "external_apis": 0, "ai": False, "trading_authority": False},
                     sort_keys=True, separators=(",", ":")))
    for row in failed: print("FAIL", row)
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(main())
