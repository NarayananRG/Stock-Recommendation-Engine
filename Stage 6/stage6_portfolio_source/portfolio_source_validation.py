from __future__ import annotations

from stage6_ingestion.canonical import canonical_hash, without
from .errors import PortfolioSourceIntegrityFailure
from .portfolio_source_builder import SAFETY
from .policy import (
    AUTHORITY, CONSTITUENT_CONTRACT_VERSION, POLICY_ID, PROCESSOR_VERSION, SCHEMA_VERSION,
)


def validate_portfolio_source_snapshot(record: dict) -> dict:
    root = {
        "schema_version", "source_snapshot_id", "record_hash", "source_system",
        "source_stage5d5_commit", "source_export_id", "source_export_hash", "source_database_id",
        "source_schema_version", "as_of_timestamp", "data_cutoff_timestamp", "currency",
        "capital_ceiling", "open_positions", "pending_entries", "entity_registry_snapshot_id",
        "entity_registry_hash", "entity_registry_version", "processor_version", "policy_id",
        "policy_hash", "constituent_contract_version", "constituent_contract_hash", "authority",
        *SAFETY.keys(),
    }
    if not isinstance(record, dict) or set(record) != root:
        raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_RECORD_FIELDS_MISMATCH")
    identities = tuple(record.get(key) for key in (
        "schema_version", "processor_version", "policy_id", "constituent_contract_version", "authority"))
    if identities != (SCHEMA_VERSION, PROCESSOR_VERSION, POLICY_ID, CONSTITUENT_CONTRACT_VERSION, AUTHORITY):
        raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_RECORD_IDENTITY_INVALID")
    if any(record.get(key) != value for key, value in SAFETY.items()):
        raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_SAFETY_INVALID")
    expected_id = "S6PORTSRC_" + canonical_hash(without(record, "source_snapshot_id", "record_hash"))[:24]
    if record["source_snapshot_id"] != expected_id:
        raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_SNAPSHOT_ID_MISMATCH")
    if record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_RECORD_HASH_MISMATCH")
    if any(key in record for key in (
        "market_value", "cash", "invested_capital", "committed_capital", "available_capital",
        "aggregate_risk_at_stop", "sector_exposure", "subsector_exposure", "correlated_exposure",
        "portfolio_concentration")):
        raise PortfolioSourceIntegrityFailure("PORTFOLIO_SOURCE_AGGREGATE_FIELD_PROHIBITED")
    return record
