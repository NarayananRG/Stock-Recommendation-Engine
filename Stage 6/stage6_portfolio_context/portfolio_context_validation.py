import math
import re
from datetime import datetime
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, without
from .errors import PortfolioContextIntegrityFailure
from .policy import *


def _number(value, minimum=None, exclusive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_NUMBER_INVALID")
    if minimum is not None and (value <= minimum if exclusive else value < minimum):
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_NUMBER_RANGE_INVALID")


def _time(value):
    if not isinstance(value, str): raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_TIMESTAMP_INVALID")
    try: datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_TIMESTAMP_INVALID") from exc


def _money(value):
    if not isinstance(value, dict) or set(value) != {"value", "unit"} or value["unit"] not in {"INR", "USD"}:
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_MONEY_INVALID")
    _number(value["value"], 0)


def validate_portfolio_context(payload):
    expected = {"schema_version","portfolio_context_id","as_of_timestamp","data_cutoff_timestamp","capital_ceiling","cash","open_positions","pending_entries","sector_exposure","subsector_exposure","correlated_exposure","risk_at_stop","committed_capital","available_capital","portfolio_concentration","cash_is_valid_allocation","record_hash"}
    if not isinstance(payload, dict) or set(payload) != expected or payload.get("schema_version") != PAYLOAD_SCHEMA_VERSION:
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_SCHEMA_FIELDS_INVALID")
    if git_blob(Path(__file__).resolve().parents[1] / "contracts" / "portfolio_context.schema.json") != PORTFOLIO_CONTEXT_BLOB:
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_FROZEN_SCHEMA_CHANGED")
    if not isinstance(payload["portfolio_context_id"], str) or not payload["portfolio_context_id"]:
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_ID_INVALID")
    if not isinstance(payload["record_hash"], str) or not re.fullmatch(r"[a-f0-9]{64}", payload["record_hash"]):
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_RECORD_HASH_FORMAT_INVALID")
    _time(payload["as_of_timestamp"]); _time(payload["data_cutoff_timestamp"])
    for field in ("capital_ceiling","cash","risk_at_stop","committed_capital","available_capital"): _money(payload[field])
    if payload["cash_is_valid_allocation"] is not True: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CASH_INVALID")
    if not all(isinstance(payload[x], list) for x in ("open_positions","pending_entries","sector_exposure","subsector_exposure","correlated_exposure","portfolio_concentration")):
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_ARRAY_INVALID")
    for item in payload["open_positions"]:
        fields={"ticker","recommendation_id","thesis_id","transaction_or_fill_ids","quantity","current_price","average_cost","market_value","risk_at_stop","sector_entity_id","subsector_entity_id"}
        if not isinstance(item,dict) or set(item)!=fields: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_POSITION_INVALID")
        if not isinstance(item["ticker"],str) or not isinstance(item["recommendation_id"],str) or not (item["thesis_id"] is None or isinstance(item["thesis_id"],str)) or not isinstance(item["sector_entity_id"],str) or not (item["subsector_entity_id"] is None or isinstance(item["subsector_entity_id"],str)): raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_POSITION_STRING_INVALID")
        if not isinstance(item["quantity"],int) or isinstance(item["quantity"],bool) or item["quantity"]<1: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_QUANTITY_INVALID")
        if not isinstance(item["transaction_or_fill_ids"],list) or not item["transaction_or_fill_ids"] or len(item["transaction_or_fill_ids"])!=len(set(item["transaction_or_fill_ids"])): raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_FILL_IDS_INVALID")
        if not all(isinstance(value,str) for value in item["transaction_or_fill_ids"]): raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_FILL_ID_TYPE_INVALID")
        price=item["current_price"]
        if not isinstance(price,dict) or set(price)!={"value","unit","observed_at_utc"} or price["unit"] not in {"INR","USD"}: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_PRICE_INVALID")
        _number(price["value"],0,True); _time(price["observed_at_utc"])
        for field in ("average_cost","market_value","risk_at_stop"): _money(item[field])
    for item in payload["pending_entries"]:
        if not isinstance(item,dict) or set(item)!={"ticker","recommendation_id","thesis_id","committed_capital"}: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_PENDING_INVALID")
        if not isinstance(item["ticker"],str) or not isinstance(item["recommendation_id"],str) or not (item["thesis_id"] is None or isinstance(item["thesis_id"],str)): raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_PENDING_STRING_INVALID")
        _money(item["committed_capital"])
    for field in ("sector_exposure","subsector_exposure","portfolio_concentration"):
        for item in payload[field]:
            if not isinstance(item,dict) or set(item)!={"entity_id","value","unit","denominator_definition"}: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_EXPOSURE_INVALID")
            if not isinstance(item["entity_id"],str): raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_EXPOSURE_ENTITY_INVALID")
            _number(item["value"],0)
            if item["unit"] not in {"INR","USD","FRACTION_OF_CAPITAL","FRACTION_OF_INVESTED_CAPITAL"} or item["denominator_definition"] not in {"CURRENCY_AMOUNT","CAPITAL_CEILING","INVESTED_CAPITAL"}: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_EXPOSURE_UNIT_INVALID")
    for item in payload["correlated_exposure"]:
        fields={"members","method","value","unit","return_frequency","lookback_window","minimum_observations","actual_observations","data_cutoff_timestamp"}
        if not isinstance(item,dict) or set(item)!=fields or not isinstance(item["members"],list) or len(item["members"])<2 or item["unit"]!="CORRELATION": raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CORRELATION_INVALID")
        if not all(isinstance(value,str) for value in item["members"]) or not isinstance(item["method"],str) or not item["method"]: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CORRELATION_IDENTITY_INVALID")
        if item["value"] is not None: _number(item["value"],-1)
        if item["value"] is not None and item["value"]>1: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CORRELATION_RANGE_INVALID")
        if item["return_frequency"] not in {"DAILY","WEEKLY","MONTHLY"} or not isinstance(item["minimum_observations"],int) or item["minimum_observations"]<2 or not isinstance(item["actual_observations"],int) or item["actual_observations"]<0: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CORRELATION_METADATA_INVALID")
        look=item["lookback_window"]
        if not isinstance(look,dict) or set(look)!={"value","unit"} or not isinstance(look["value"],int) or look["value"]<1 or look["unit"] not in {"DAYS","TRADING_SESSIONS"}: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_LOOKBACK_INVALID")
        _time(item["data_cutoff_timestamp"])
    wanted="S6PORTCTX_"+canonical_hash(without(payload,"portfolio_context_id","record_hash"))[:24]
    if payload["portfolio_context_id"]!=wanted or payload["record_hash"]!=canonical_hash(without(payload,"record_hash")): raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_IDENTITY_MISMATCH")
    return payload


def validate_portfolio_context_wrapper(wrapper):
    from .portfolio_context_builder import SAFETY
    expected={"wrapper_schema_version","portfolio_context","arithmetic_record_id","arithmetic_record_hash","correlation_context_id","correlation_record_hash","source_snapshot_id","source_snapshot_hash","subsector_coverage_audit","pending_commitment_audit","processor_version","policy_id","policy_hash","assembly_contract_version","assembly_contract_hash","authority","assembly_record_id","wrapper_hash",*SAFETY.keys()}
    if not isinstance(wrapper,dict) or set(wrapper)!=expected: raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_WRAPPER_FIELDS_INVALID")
    validate_portfolio_context(wrapper["portfolio_context"])
    if tuple(wrapper.get(k) for k in ("wrapper_schema_version","processor_version","policy_id","assembly_contract_version","authority"))!=(WRAPPER_SCHEMA_VERSION,PROCESSOR_VERSION,POLICY_ID,ASSEMBLY_CONTRACT_VERSION,AUTHORITY): raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_WRAPPER_IDENTITY_INVALID")
    if any(wrapper.get(k)!=v for k,v in SAFETY.items()): raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_WRAPPER_SAFETY_INVALID")
    if wrapper["assembly_record_id"]!="S6PORTCTXASM_"+canonical_hash(without(wrapper,"assembly_record_id","wrapper_hash"))[:24] or wrapper["wrapper_hash"]!=canonical_hash(without(wrapper,"wrapper_hash")): raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_WRAPPER_HASH_INVALID")
    return wrapper
