from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from decimal import Decimal

from stage6_ingestion.canonical import canonical_hash, without
from stage6_portfolio_source.portfolio_source_validation import validate_portfolio_source_snapshot
from .arithmetic import ONE, TOLERANCE, ZERO, add, decimal_value, divide, emit, fraction, money, multiply
from .errors import PortfolioArithmeticIntegrityFailure
from .policy import (
    ARITHMETIC_CONTRACT_VERSION, AUTHORITY, EXPECTED_ARITHMETIC_CONTRACT_HASH_V1,
    EXPECTED_POLICY_HASH_V1, POLICY_ID, PROCESSOR_VERSION, SCHEMA_VERSION,
    SOURCE_CONTRACT_HASH, SOURCE_CONTRACT_VERSION, SOURCE_POLICY_HASH, SOURCE_POLICY_ID,
    SOURCE_PROCESSOR_VERSION, SOURCE_SCHEMA_VERSION,
)

SAFETY = {
    "portfolio_arithmetic_status": "EVALUATED",
    "market_value_status": "EVALUATED",
    "cash_status": "EVALUATED",
    "committed_capital_status": "EVALUATED",
    "available_capital_status": "EVALUATED",
    "aggregate_risk_status": "EVALUATED",
    "sector_exposure_status": "EVALUATED",
    "subsector_exposure_status": "EVALUATED",
    "concentration_status": "EVALUATED",
    "correlation_status": "NOT_EVALUATED",
    "portfolio_context_v2_status": "NOT_MATERIALIZED",
    "portfolio_constraints_status": "NOT_EVALUATED",
    "portfolio_influence_status": "NOT_EVALUATED",
    "buy_sell_hold_status": "NOT_EVALUATED",
    "trading_authority": False,
}


def _verify_source(source: dict) -> None:
    validate_portfolio_source_snapshot(source)
    identities = tuple(source.get(key) for key in (
        "schema_version", "processor_version", "policy_id", "policy_hash",
        "constituent_contract_version", "constituent_contract_hash", "authority"))
    expected = (SOURCE_SCHEMA_VERSION, SOURCE_PROCESSOR_VERSION, SOURCE_POLICY_ID, SOURCE_POLICY_HASH,
                SOURCE_CONTRACT_VERSION, SOURCE_CONTRACT_HASH, AUTHORITY)
    if identities != expected:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_SOURCE_IDENTITY_INVALID")


def _held_exposures(amounts: dict[str, Decimal], invested: Decimal, id_field: str, currency: str) -> list[dict]:
    output = []
    for identity in sorted(amounts):
        amount = amounts[identity]
        output.append({id_field: identity, "held_market_value": money(amount, currency),
                       "fraction_of_invested_capital": fraction(divide(amount, invested))})
    return output


def _pending_aggregates(amounts: dict[str, Decimal], id_field: str, currency: str) -> list[dict]:
    return [{id_field: identity, "committed_capital": money(amounts[identity], currency)}
            for identity in sorted(amounts)]


def build_portfolio_arithmetic(*, source_snapshot: dict, policy_hash: str,
                               arithmetic_contract_hash: str) -> dict:
    _verify_source(source_snapshot)
    if policy_hash != EXPECTED_POLICY_HASH_V1 or arithmetic_contract_hash != EXPECTED_ARITHMETIC_CONTRACT_HASH_V1:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_CONFIGURATION_IDENTITY_INVALID")
    currency = source_snapshot["currency"]
    capital_ceiling = decimal_value(source_snapshot["capital_ceiling"]["value"], "capital_ceiling")
    derived_positions = []
    company = defaultdict(lambda: ZERO)
    sector = defaultdict(lambda: ZERO)
    subsector = defaultdict(lambda: ZERO)
    missing_subsector_count = 0
    missing_subsector_value = ZERO
    risks = []
    market_values = []
    for item in source_snapshot["open_positions"]:
        quantity = decimal_value(item["quantity"], "quantity")
        current_price = decimal_value(item["current_price"]["value"], "current_price")
        market_value = multiply(quantity, current_price)
        market_values.append(market_value)
        risk = decimal_value(item["risk_at_stop"]["value"], "risk_at_stop")
        risks.append(risk)
        company[item["company_entity_id"]] = add((company[item["company_entity_id"]], market_value))
        sector[item["sector_entity_id"]] = add((sector[item["sector_entity_id"]], market_value))
        if item["subsector_entity_id"] is None:
            missing_subsector_count += 1
            missing_subsector_value = add((missing_subsector_value, market_value))
        else:
            subsector[item["subsector_entity_id"]] = add((subsector[item["subsector_entity_id"]], market_value))
        derived_positions.append({
            "company_entity_id": item["company_entity_id"], "ticker": item["ticker"],
            "recommendation_id": item["recommendation_id"], "thesis_id": item["thesis_id"],
            "transaction_fill_ids": deepcopy(item["transaction_fill_ids"]), "quantity": item["quantity"],
            "current_price": {"value": item["current_price"]["value"], "unit": currency,
                              "observed_at_utc": item["current_price"]["observed_at_utc"]},
            "average_cost_per_share": {"value": item["average_cost_per_share"]["value"], "unit": currency},
            "market_value": money(market_value, currency),
            "risk_at_stop": {"value": item["risk_at_stop"]["value"], "unit": currency,
                             "observed_at_utc": item["risk_at_stop"]["observed_at_utc"],
                             "method": item["risk_at_stop"]["method"]},
            "sector_entity_id": item["sector_entity_id"], "subsector_entity_id": item["subsector_entity_id"],
            "source_position_snapshot_id": item["source_position_snapshot_id"],
            "source_position_snapshot_hash": item["source_position_snapshot_hash"],
        })
    derived_positions.sort(key=lambda x: (x["company_entity_id"], x["ticker"], x["recommendation_id"]))
    invested = add(market_values)

    pending_positions = []
    pending_company = defaultdict(lambda: ZERO)
    pending_sector = defaultdict(lambda: ZERO)
    pending_subsector = defaultdict(lambda: ZERO)
    pending_values = []
    for item in source_snapshot["pending_entries"]:
        amount = decimal_value(item["committed_reserved_capital"]["value"], "pending_committed_capital")
        pending_values.append(amount)
        pending_company[item["company_entity_id"]] = add((pending_company[item["company_entity_id"]], amount))
        pending_sector[item["sector_entity_id"]] = add((pending_sector[item["sector_entity_id"]], amount))
        if item["subsector_entity_id"] is not None:
            pending_subsector[item["subsector_entity_id"]] = add((pending_subsector[item["subsector_entity_id"]], amount))
        pending_positions.append({
            "company_entity_id": item["company_entity_id"], "ticker": item["ticker"],
            "recommendation_id": item["recommendation_id"], "thesis_id": item["thesis_id"],
            "committed_capital": money(amount, currency), "sector_entity_id": item["sector_entity_id"],
            "subsector_entity_id": item["subsector_entity_id"], "source_record_id": item["source_record_id"],
            "source_record_hash": item["source_record_hash"],
        })
    pending_positions.sort(key=lambda x: (x["company_entity_id"], x["ticker"], x["recommendation_id"]))
    pending_committed = add(pending_values)
    committed = add((invested, pending_committed))
    cash = max(ZERO, add((capital_ceiling, -invested)))
    available = max(ZERO, add((capital_ceiling, -committed)))
    invested_overage = max(ZERO, add((invested, -capital_ceiling)))
    committed_overage = max(ZERO, add((committed, -capital_ceiling)))
    aggregate_risk = add(risks)
    company_exposure = [] if invested == ZERO else _held_exposures(company, invested, "company_entity_id", currency)
    sector_exposure = [] if invested == ZERO else _held_exposures(sector, invested, "sector_entity_id", currency)
    subsector_exposure = [] if invested == ZERO else _held_exposures(subsector, invested, "subsector_entity_id", currency)
    if add(company.values()) != invested or add(sector.values()) != invested:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_EXPOSURE_CONSERVATION_FAILED")
    if add((add(subsector.values()), missing_subsector_value)) != invested:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_SUBSECTOR_CONSERVATION_FAILED")
    if invested != ZERO:
        for exposures in (company_exposure, sector_exposure):
            total = add(decimal_value(x["fraction_of_invested_capital"]["value"], "fraction") for x in exposures)
            if abs(total - ONE) > TOLERANCE:
                raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_FRACTION_CONSERVATION_FAILED")
    core = {
        "schema_version": SCHEMA_VERSION,
        "source_snapshot_id": source_snapshot["source_snapshot_id"],
        "source_snapshot_hash": source_snapshot["record_hash"],
        "source_export_id": source_snapshot["source_export_id"],
        "source_export_hash": source_snapshot["source_export_hash"],
        "source_as_of_timestamp": source_snapshot["as_of_timestamp"],
        "data_cutoff_timestamp": source_snapshot["data_cutoff_timestamp"],
        "currency": currency, "capital_ceiling": money(capital_ceiling, currency),
        "derived_open_positions": derived_positions, "pending_entry_projection": pending_positions,
        "invested_capital": money(invested, currency),
        "pending_committed_capital": money(pending_committed, currency),
        "committed_capital": money(committed, currency), "cash": money(cash, currency),
        "available_capital": money(available, currency),
        "invested_capital_overage": money(invested_overage, currency),
        "committed_capital_overage": money(committed_overage, currency),
        "aggregate_risk_at_stop": money(aggregate_risk, currency),
        "held_company_concentration": company_exposure, "held_sector_exposure": sector_exposure,
        "held_subsector_exposure": subsector_exposure,
        "subsector_coverage_audit": {"positions_without_subsector_count": missing_subsector_count,
                                     "market_value_without_subsector": money(missing_subsector_value, currency)},
        "pending_commitment_by_company": _pending_aggregates(pending_company, "company_entity_id", currency),
        "pending_commitment_by_sector": _pending_aggregates(pending_sector, "sector_entity_id", currency),
        "pending_commitment_by_subsector": _pending_aggregates(pending_subsector, "subsector_entity_id", currency),
        "cash_is_valid_allocation": True, "processor_version": PROCESSOR_VERSION,
        "policy_id": POLICY_ID, "policy_hash": policy_hash,
        "arithmetic_contract_version": ARITHMETIC_CONTRACT_VERSION,
        "arithmetic_contract_hash": arithmetic_contract_hash, "authority": AUTHORITY, **SAFETY,
    }
    identity = canonical_hash(core)
    record = {**core, "arithmetic_record_id": "S6PORTARITH_" + identity[:24]}
    record["record_hash"] = canonical_hash(record)
    return record
