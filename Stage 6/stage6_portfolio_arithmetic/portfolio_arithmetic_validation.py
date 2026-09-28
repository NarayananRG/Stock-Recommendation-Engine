from __future__ import annotations

from stage6_ingestion.canonical import canonical_hash, without
from .errors import PortfolioArithmeticIntegrityFailure
from .portfolio_arithmetic_builder import SAFETY
from .policy import ARITHMETIC_CONTRACT_VERSION, AUTHORITY, POLICY_ID, PROCESSOR_VERSION, SCHEMA_VERSION


def validate_portfolio_arithmetic(record: dict) -> dict:
    expected = {
        "schema_version", "arithmetic_record_id", "record_hash", "source_snapshot_id",
        "source_snapshot_hash", "source_export_id", "source_export_hash", "source_as_of_timestamp",
        "data_cutoff_timestamp", "currency", "capital_ceiling", "derived_open_positions",
        "pending_entry_projection", "invested_capital", "pending_committed_capital",
        "committed_capital", "cash", "available_capital", "invested_capital_overage",
        "committed_capital_overage", "aggregate_risk_at_stop", "held_company_concentration",
        "held_sector_exposure", "held_subsector_exposure", "subsector_coverage_audit",
        "pending_commitment_by_company", "pending_commitment_by_sector",
        "pending_commitment_by_subsector", "cash_is_valid_allocation", "processor_version",
        "policy_id", "policy_hash", "arithmetic_contract_version", "arithmetic_contract_hash",
        "authority", *SAFETY.keys(),
    }
    if not isinstance(record, dict) or set(record) != expected:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_FIELDS_MISMATCH")
    identity = tuple(record.get(key) for key in (
        "schema_version", "processor_version", "policy_id", "arithmetic_contract_version", "authority"))
    if identity != (SCHEMA_VERSION, PROCESSOR_VERSION, POLICY_ID, ARITHMETIC_CONTRACT_VERSION, AUTHORITY):
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_IDENTITY_INVALID")
    if any(record.get(key) != value for key, value in SAFETY.items()):
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_SAFETY_INVALID")
    if record["cash_is_valid_allocation"] is not True:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_CASH_INVARIANT_INVALID")
    wanted_id = "S6PORTARITH_" + canonical_hash(without(record, "arithmetic_record_id", "record_hash"))[:24]
    if record["arithmetic_record_id"] != wanted_id:
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_RECORD_ID_MISMATCH")
    if record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_RECORD_HASH_MISMATCH")
    if any(key in record for key in ("correlated_exposure", "portfolio_context", "buy_sell_hold",
                                      "allocation_proposal", "expected_return")):
        raise PortfolioArithmeticIntegrityFailure("PORTFOLIO_ARITHMETIC_PROHIBITED_OUTPUT")
    return record
