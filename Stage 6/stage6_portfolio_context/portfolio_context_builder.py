from copy import deepcopy

from stage6_ingestion.canonical import canonical_hash
from stage6_portfolio_arithmetic.portfolio_arithmetic_validation import validate_portfolio_arithmetic
from stage6_portfolio_correlation.correlation_validation import validate_portfolio_correlation
from .errors import PortfolioContextIntegrityFailure
from .policy import *

SAFETY = {
    "portfolio_source_status": "FROZEN",
    "portfolio_arithmetic_status": "FROZEN",
    "correlation_status": "FROZEN",
    "portfolio_context_v2_status": "MATERIALIZED",
    "portfolio_context_schema_validation": "PASS",
    "correlation_interpretation_status": "NOT_EVALUATED",
    "portfolio_constraints_status": "NOT_EVALUATED",
    "diversification_status": "NOT_EVALUATED",
    "expected_return_interaction_status": "NOT_EVALUATED",
    "portfolio_influence_status": "NOT_EVALUATED",
    "replacement_status": "NOT_EVALUATED",
    "buy_sell_hold_status": "NOT_EVALUATED",
    "trading_authority": False,
}


def _verify_sources(arithmetic, correlation):
    validate_portfolio_arithmetic(arithmetic)
    validate_portfolio_correlation(correlation)
    arithmetic_identity = tuple(arithmetic.get(k) for k in (
        "schema_version", "processor_version", "policy_id", "policy_hash",
        "arithmetic_contract_version", "arithmetic_contract_hash", "authority"))
    if arithmetic_identity != (ARITHMETIC_SCHEMA, ARITHMETIC_PROCESSOR, ARITHMETIC_POLICY_ID,
            ARITHMETIC_POLICY_HASH, ARITHMETIC_CONTRACT_VERSION, ARITHMETIC_CONTRACT_HASH, AUTHORITY):
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_ARITHMETIC_IDENTITY_INVALID")
    correlation_identity = tuple(correlation.get(k) for k in (
        "schema_version", "processor_version", "policy_id", "policy_hash",
        "correlation_contract_version", "correlation_contract_hash", "authority"))
    if correlation_identity != (CORRELATION_SCHEMA, CORRELATION_PROCESSOR, CORRELATION_POLICY_ID,
            CORRELATION_POLICY_HASH, CORRELATION_CONTRACT_VERSION, CORRELATION_CONTRACT_HASH, AUTHORITY):
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CORRELATION_IDENTITY_INVALID")
    pairs = (
        (correlation["arithmetic_record_id"], arithmetic["arithmetic_record_id"]),
        (correlation["arithmetic_record_hash"], arithmetic["record_hash"]),
        (correlation["source_snapshot_id"], arithmetic["source_snapshot_id"]),
        (correlation["source_snapshot_hash"], arithmetic["source_snapshot_hash"]),
        (correlation["source_as_of_timestamp"], arithmetic["source_as_of_timestamp"]),
        (correlation["portfolio_data_cutoff_timestamp"], arithmetic["data_cutoff_timestamp"]),
        (correlation["currency"], arithmetic["currency"]),
    )
    if any(left != right for left, right in pairs):
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CROSS_STAGE_BINDING_MISMATCH")
    if arithmetic["cash_is_valid_allocation"] is not True:
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CASH_ALLOCATION_INVALID")


def _position(item):
    return {
        "ticker": item["ticker"], "recommendation_id": item["recommendation_id"],
        "thesis_id": item["thesis_id"], "transaction_or_fill_ids": deepcopy(item["transaction_fill_ids"]),
        "quantity": item["quantity"], "current_price": deepcopy(item["current_price"]),
        "average_cost": deepcopy(item["average_cost_per_share"]),
        "market_value": deepcopy(item["market_value"]),
        "risk_at_stop": {"value": item["risk_at_stop"]["value"], "unit": item["risk_at_stop"]["unit"]},
        "sector_entity_id": item["sector_entity_id"], "subsector_entity_id": item["subsector_entity_id"],
    }


def _pending(item):
    return {k: deepcopy(item[k]) for k in ("ticker", "recommendation_id", "thesis_id", "committed_capital")}


def _exposure(items, identity):
    return [{"entity_id": item[identity], "value": item["fraction_of_invested_capital"]["value"],
             "unit": "FRACTION_OF_INVESTED_CAPITAL", "denominator_definition": "INVESTED_CAPITAL"}
            for item in items]


def assemble_portfolio_context(*, arithmetic_record, correlation_record, policy_hash, assembly_contract_hash):
    _verify_sources(arithmetic_record, correlation_record)
    if policy_hash != EXPECTED_POLICY_HASH_V1 or assembly_contract_hash != EXPECTED_ASSEMBLY_CONTRACT_HASH_V1:
        raise PortfolioContextIntegrityFailure("PORTFOLIO_CONTEXT_CONFIGURATION_IDENTITY_INVALID")
    core = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "as_of_timestamp": arithmetic_record["source_as_of_timestamp"],
        "data_cutoff_timestamp": arithmetic_record["data_cutoff_timestamp"],
        "capital_ceiling": deepcopy(arithmetic_record["capital_ceiling"]),
        "cash": deepcopy(arithmetic_record["cash"]),
        "open_positions": [_position(x) for x in arithmetic_record["derived_open_positions"]],
        "pending_entries": [_pending(x) for x in arithmetic_record["pending_entry_projection"]],
        "sector_exposure": _exposure(arithmetic_record["held_sector_exposure"], "sector_entity_id"),
        "subsector_exposure": _exposure(arithmetic_record["held_subsector_exposure"], "subsector_entity_id"),
        "correlated_exposure": [deepcopy(x["correlation"]) for x in correlation_record["pairwise_correlations"]],
        "risk_at_stop": deepcopy(arithmetic_record["aggregate_risk_at_stop"]),
        "committed_capital": deepcopy(arithmetic_record["committed_capital"]),
        "available_capital": deepcopy(arithmetic_record["available_capital"]),
        "portfolio_concentration": _exposure(arithmetic_record["held_company_concentration"], "company_entity_id"),
        "cash_is_valid_allocation": True,
    }
    context_id = "S6PORTCTX_" + canonical_hash(core)[:24]
    payload = {**core, "portfolio_context_id": context_id}
    payload["record_hash"] = canonical_hash(payload)
    from .portfolio_context_validation import validate_portfolio_context
    validate_portfolio_context(payload)
    wrapper_core = {
        "wrapper_schema_version": WRAPPER_SCHEMA_VERSION,
        "portfolio_context": payload,
        "arithmetic_record_id": arithmetic_record["arithmetic_record_id"],
        "arithmetic_record_hash": arithmetic_record["record_hash"],
        "correlation_context_id": correlation_record["correlation_context_id"],
        "correlation_record_hash": correlation_record["record_hash"],
        "source_snapshot_id": arithmetic_record["source_snapshot_id"],
        "source_snapshot_hash": arithmetic_record["source_snapshot_hash"],
        "subsector_coverage_audit": deepcopy(arithmetic_record["subsector_coverage_audit"]),
        "pending_commitment_audit": {
            "pending_committed_capital": deepcopy(arithmetic_record["pending_committed_capital"]),
            "pending_commitment_by_company": deepcopy(arithmetic_record["pending_commitment_by_company"]),
            "pending_commitment_by_sector": deepcopy(arithmetic_record["pending_commitment_by_sector"]),
            "pending_commitment_by_subsector": deepcopy(arithmetic_record["pending_commitment_by_subsector"]),
        },
        "processor_version": PROCESSOR_VERSION, "policy_id": POLICY_ID, "policy_hash": policy_hash,
        "assembly_contract_version": ASSEMBLY_CONTRACT_VERSION,
        "assembly_contract_hash": assembly_contract_hash, "authority": AUTHORITY, **SAFETY,
    }
    wrapper_id = "S6PORTCTXASM_" + canonical_hash(wrapper_core)[:24]
    wrapper = {**wrapper_core, "assembly_record_id": wrapper_id}
    wrapper["wrapper_hash"] = canonical_hash(wrapper)
    return wrapper
