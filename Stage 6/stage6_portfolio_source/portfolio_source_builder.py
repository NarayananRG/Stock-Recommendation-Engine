from __future__ import annotations

import math
import re

from stage6_ingestion.canonical import canonical_hash, parse_utc, utc_timestamp, without
from stage6_ingestion.registry import resolve_entity, resolve_ticker, verify_entity_registry
from .errors import Stage6PortfolioSourceError
from .policy import (
    AUTHORITY, CONSTITUENT_CONTRACT_VERSION, POLICY_ID, PROCESSOR_VERSION,
    SCHEMA_VERSION, STAGE5D5_REFERENCE_COMMIT,
)

HASH = re.compile(r"^[0-9a-f]{64}$")
CURRENCIES = {"INR", "USD"}
SOURCE_SYSTEMS = {"FIXTURE", "STAGE5D5_PAPER_EXPORT"}
SAFETY = {
    "portfolio_arithmetic_status": "NOT_EVALUATED",
    "market_value_status": "NOT_EVALUATED",
    "cash_status": "NOT_EVALUATED",
    "committed_capital_status": "NOT_EVALUATED",
    "available_capital_status": "NOT_EVALUATED",
    "aggregate_risk_status": "NOT_EVALUATED",
    "sector_exposure_status": "NOT_EVALUATED",
    "subsector_exposure_status": "NOT_EVALUATED",
    "correlation_status": "NOT_EVALUATED",
    "concentration_status": "NOT_EVALUATED",
    "portfolio_context_v2_status": "NOT_MATERIALIZED",
    "portfolio_influence_status": "NOT_EVALUATED",
    "buy_sell_hold_status": "NOT_EVALUATED",
    "trading_authority": False,
}


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Stage6PortfolioSourceError(f"PORTFOLIO_SOURCE_REQUIRED:{field}")
    return value.strip()


def _hash(value: object, field: str) -> str:
    value = _required(value, field)
    if not HASH.fullmatch(value):
        raise Stage6PortfolioSourceError(f"PORTFOLIO_SOURCE_HASH_INVALID:{field}")
    return value


def _number(value: object, field: str, *, positive: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Stage6PortfolioSourceError(f"PORTFOLIO_SOURCE_NUMBER_INVALID:{field}")
    if (positive and value <= 0) or (not positive and value < 0):
        raise Stage6PortfolioSourceError(f"PORTFOLIO_SOURCE_NUMBER_RANGE:{field}")
    return value


def _money(value: object, currency: str, field: str, *, positive: bool = False) -> dict:
    if not isinstance(value, dict) or set(value) != {"value", "currency"}:
        raise Stage6PortfolioSourceError(f"PORTFOLIO_SOURCE_MONEY_INVALID:{field}")
    if value["currency"] != currency:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_MIXED_CURRENCY")
    return {"value": _number(value["value"], field, positive=positive), "currency": currency}


def _at_or_before(value: object, cutoff: str, field: str) -> str:
    normalized = utc_timestamp(value, field)
    if parse_utc(normalized, field) > parse_utc(cutoff, "data_cutoff_timestamp"):
        raise Stage6PortfolioSourceError(f"PORTFOLIO_SOURCE_FUTURE_FACT:{field}")
    return normalized


def _bindings(values: object, cutoff: str) -> list[dict]:
    if not isinstance(values, list) or not values:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_BINDINGS_REQUIRED")
    result = []
    for item in values:
        if not isinstance(item, dict) or set(item) != {
            "record_type", "record_id", "record_hash", "recorded_or_persisted_at_utc"}:
            raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_BINDING_INVALID")
        result.append({
            "record_type": _required(item["record_type"], "record_type"),
            "record_id": _required(item["record_id"], "record_id"),
            "record_hash": _hash(item["record_hash"], "record_hash"),
            "recorded_or_persisted_at_utc": _at_or_before(
                item["recorded_or_persisted_at_utc"], cutoff, "recorded_or_persisted_at_utc"),
        })
    keys = [(x["record_type"], x["record_id"]) for x in result]
    if len(keys) != len(set(keys)):
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_DUPLICATE_BINDING")
    return sorted(result, key=lambda x: (x["record_type"], x["record_id"], x["record_hash"]))


def _entity_bindings(registry: dict, company_id: str, exchange: str, ticker: str,
                     sector_id: str, subsector_id: str | None, cutoff: str) -> tuple[list[dict], dict]:
    company = resolve_entity(registry, company_id, cutoff)
    mapped = resolve_ticker(registry, exchange, ticker, cutoff)
    if company["entity_type"] != "COMPANY" or mapped["entity_id"] != company_id:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_COMPANY_BINDING_INVALID")
    sector = resolve_entity(registry, sector_id, cutoff)
    if sector["entity_type"] != "SECTOR" or company.get("sector_entity_id") != sector_id:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_SECTOR_BINDING_INVALID")
    entities = [company, sector]
    if subsector_id is not None:
        subsector_id = _required(subsector_id, "subsector_entity_id")
        subsector = resolve_entity(registry, subsector_id, cutoff)
        if subsector["entity_type"] != "SUBSECTOR" or company.get("subsector_entity_id") != subsector_id:
            raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_SUBSECTOR_BINDING_INVALID")
        entities.append(subsector)
    return sorted([{
        "entity_id": x["entity_id"], "entity_type": x["entity_type"],
        "entity_record_version": x["entity_record_version"], "record_hash": x["record_hash"]}
        for x in entities], key=lambda x: x["entity_id"]), company


def _position(item: dict, currency: str, cutoff: str, registry: dict) -> dict:
    required = {"company_entity_id", "exchange", "ticker", "recommendation_id", "thesis_id",
                "transaction_fill_ids", "quantity", "current_price", "average_cost_per_share",
                "risk_at_stop", "sector_entity_id", "subsector_entity_id",
                "source_position_snapshot_id", "source_position_snapshot_hash", "source_record_bindings"}
    if not isinstance(item, dict) or set(item) != required:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_POSITION_FIELDS_INVALID")
    quantity = item["quantity"]
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_QUANTITY_INVALID")
    fills = item["transaction_fill_ids"]
    if not isinstance(fills, list) or not fills or any(not isinstance(x, str) or not x.strip() for x in fills):
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_FILL_IDS_REQUIRED")
    fills = sorted(x.strip() for x in fills)
    if len(fills) != len(set(fills)):
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_DUPLICATE_FILL_ID")
    current = item["current_price"]
    if not isinstance(current, dict) or set(current) != {"value", "currency", "observed_at_utc"}:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_CURRENT_PRICE_INVALID")
    risk = item["risk_at_stop"]
    if not isinstance(risk, dict) or set(risk) != {"value", "currency", "observed_at_utc", "method"}:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_RISK_INVALID")
    company_id = _required(item["company_entity_id"], "company_entity_id")
    exchange = _required(item["exchange"], "exchange")
    ticker = _required(item["ticker"], "ticker")
    sector_id = _required(item["sector_entity_id"], "sector_entity_id")
    entity_bindings, _ = _entity_bindings(registry, company_id, exchange, ticker, sector_id,
                                           item["subsector_entity_id"], cutoff)
    recommendation_id = _required(item["recommendation_id"], "recommendation_id")
    bindings = _bindings(item["source_record_bindings"], cutoff)
    binding_keys = {(x["record_type"], x["record_id"]) for x in bindings}
    if ("RECOMMENDATION", recommendation_id) not in binding_keys:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_RECOMMENDATION_BINDING_REQUIRED")
    if any(("TRANSACTION_FILL", fill_id) not in binding_keys for fill_id in fills):
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_FILL_BINDING_REQUIRED")
    return {
        "company_entity_id": company_id, "exchange": exchange, "ticker": ticker,
        "recommendation_id": recommendation_id,
        "thesis_id": None if item["thesis_id"] is None else _required(item["thesis_id"], "thesis_id"),
        "transaction_fill_ids": fills, "quantity": quantity,
        "current_price": {**_money({"value": current["value"], "currency": current["currency"]}, currency, "current_price", positive=True),
                          "observed_at_utc": _at_or_before(current["observed_at_utc"], cutoff, "current_price.observed_at_utc")},
        "average_cost_per_share": _money(item["average_cost_per_share"], currency, "average_cost_per_share"),
        "risk_at_stop": {**_money({"value": risk["value"], "currency": risk["currency"]}, currency, "risk_at_stop"),
                         "observed_at_utc": _at_or_before(risk["observed_at_utc"], cutoff, "risk_at_stop.observed_at_utc"),
                         "method": _required(risk["method"], "risk_at_stop.method")},
        "sector_entity_id": sector_id, "subsector_entity_id": item["subsector_entity_id"],
        "source_position_snapshot_id": _required(item["source_position_snapshot_id"], "source_position_snapshot_id"),
        "source_position_snapshot_hash": _hash(item["source_position_snapshot_hash"], "source_position_snapshot_hash"),
        "source_record_bindings": bindings,
        "entity_record_bindings": entity_bindings,
    }


def _pending(item: dict, currency: str, cutoff: str, registry: dict) -> dict:
    required = {"company_entity_id", "exchange", "ticker", "recommendation_id", "thesis_id",
                "committed_reserved_capital", "sector_entity_id", "subsector_entity_id",
                "source_record_id", "source_record_hash", "source_effective_or_recorded_timestamp",
                "source_record_bindings"}
    if not isinstance(item, dict) or set(item) != required:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_PENDING_FIELDS_INVALID")
    company_id = _required(item["company_entity_id"], "company_entity_id")
    exchange = _required(item["exchange"], "exchange")
    ticker = _required(item["ticker"], "ticker")
    sector_id = _required(item["sector_entity_id"], "sector_entity_id")
    entity_bindings, _ = _entity_bindings(registry, company_id, exchange, ticker, sector_id,
                                           item["subsector_entity_id"], cutoff)
    source_record_id = _required(item["source_record_id"], "source_record_id")
    source_record_hash = _hash(item["source_record_hash"], "source_record_hash")
    bindings = _bindings(item["source_record_bindings"], cutoff)
    if not any(x["record_id"] == source_record_id and x["record_hash"] == source_record_hash
               for x in bindings):
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_PENDING_RECORD_BINDING_REQUIRED")
    return {
        "company_entity_id": company_id, "exchange": exchange, "ticker": ticker,
        "recommendation_id": _required(item["recommendation_id"], "recommendation_id"),
        "thesis_id": None if item["thesis_id"] is None else _required(item["thesis_id"], "thesis_id"),
        "committed_reserved_capital": _money(item["committed_reserved_capital"], currency, "committed_reserved_capital"),
        "sector_entity_id": sector_id, "subsector_entity_id": item["subsector_entity_id"],
        "source_record_id": source_record_id,
        "source_record_hash": source_record_hash,
        "source_effective_or_recorded_timestamp": _at_or_before(item["source_effective_or_recorded_timestamp"], cutoff, "source_effective_or_recorded_timestamp"),
        "source_record_bindings": bindings,
        "entity_record_bindings": entity_bindings,
    }


def build_portfolio_source_snapshot(*, source_export: dict, entity_registry: dict,
                                    policy_hash: str, constituent_contract_hash: str) -> dict:
    verify_entity_registry(entity_registry)
    required = {"source_system", "source_stage5d5_commit", "source_export_id", "source_export_hash",
                "source_database_id", "source_schema_version", "as_of_timestamp", "data_cutoff_timestamp",
                "currency", "capital_ceiling", "open_positions", "pending_entries"}
    if not isinstance(source_export, dict) or set(source_export) != required:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_EXPORT_FIELDS_INVALID")
    system = _required(source_export["source_system"], "source_system")
    if system not in SOURCE_SYSTEMS:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_SYSTEM_INVALID")
    commit = _required(source_export["source_stage5d5_commit"], "source_stage5d5_commit")
    if system == "STAGE5D5_PAPER_EXPORT" and commit != STAGE5D5_REFERENCE_COMMIT:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_STAGE5D5_COMMIT_INVALID")
    as_of = utc_timestamp(source_export["as_of_timestamp"], "as_of_timestamp")
    cutoff = utc_timestamp(source_export["data_cutoff_timestamp"], "data_cutoff_timestamp")
    if parse_utc(cutoff, "data_cutoff_timestamp") > parse_utc(as_of, "as_of_timestamp"):
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_CUTOFF_AFTER_ASOF")
    if parse_utc(entity_registry["as_of_timestamp"], "registry.as_of_timestamp") > parse_utc(cutoff, "data_cutoff_timestamp"):
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_REGISTRY_FROM_FUTURE")
    currency = _required(source_export["currency"], "currency")
    if currency not in CURRENCIES:
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_CURRENCY_INVALID")
    if not isinstance(source_export["open_positions"], list) or not isinstance(source_export["pending_entries"], list):
        raise Stage6PortfolioSourceError("PORTFOLIO_SOURCE_CONSTITUENTS_INVALID")
    positions = [_position(x, currency, cutoff, entity_registry) for x in source_export["open_positions"]]
    pending = [_pending(x, currency, cutoff, entity_registry) for x in source_export["pending_entries"]]
    positions.sort(key=lambda x: (x["company_entity_id"], x["ticker"], x["recommendation_id"]))
    pending.sort(key=lambda x: (x["company_entity_id"], x["ticker"], x["recommendation_id"]))
    for values, label in ((positions, "POSITION"), (pending, "PENDING")):
        keys = [(x["company_entity_id"], x["ticker"], x["recommendation_id"]) for x in values]
        if len(keys) != len(set(keys)):
            raise Stage6PortfolioSourceError(f"PORTFOLIO_SOURCE_DUPLICATE_{label}")
    core = {
        "schema_version": SCHEMA_VERSION, "source_system": system,
        "source_stage5d5_commit": commit,
        "source_export_id": _required(source_export["source_export_id"], "source_export_id"),
        "source_export_hash": _hash(source_export["source_export_hash"], "source_export_hash"),
        "source_database_id": _required(source_export["source_database_id"], "source_database_id"),
        "source_schema_version": _required(source_export["source_schema_version"], "source_schema_version"),
        "as_of_timestamp": as_of, "data_cutoff_timestamp": cutoff, "currency": currency,
        "capital_ceiling": _money(source_export["capital_ceiling"], currency, "capital_ceiling"),
        "open_positions": positions, "pending_entries": pending,
        "entity_registry_snapshot_id": entity_registry["registry_snapshot_id"],
        "entity_registry_hash": entity_registry["registry_hash"],
        "entity_registry_version": entity_registry["registry_version"],
        "processor_version": PROCESSOR_VERSION, "policy_id": POLICY_ID, "policy_hash": policy_hash,
        "constituent_contract_version": CONSTITUENT_CONTRACT_VERSION,
        "constituent_contract_hash": constituent_contract_hash, "authority": AUTHORITY, **SAFETY,
    }
    identity = canonical_hash(core)
    record = {**core, "source_snapshot_id": "S6PORTSRC_" + identity[:24]}
    record["record_hash"] = canonical_hash(record)
    return record
