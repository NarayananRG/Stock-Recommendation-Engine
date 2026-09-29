from stage6_ingestion.canonical import canonical_hash, without
from .correlation_builder import SAFETY
from .errors import PortfolioCorrelationIntegrityFailure
from .policy import AUTHORITY, CORRELATION_CONTRACT_VERSION, METHOD, POLICY_ID, PROCESSOR_VERSION, SCHEMA_VERSION


def validate_portfolio_correlation(record):
    expected = {
        "schema_version", "correlation_context_id", "record_hash", "arithmetic_record_id",
        "arithmetic_record_hash", "source_snapshot_id", "source_snapshot_hash", "source_as_of_timestamp",
        "portfolio_data_cutoff_timestamp", "currency", "held_member_ids", "return_history_manifest",
        "return_history_manifest_hash", "return_frequency", "return_unit", "lookback_window",
        "window_start_timestamp", "correlation_data_cutoff_timestamp", "minimum_observations",
        "pairwise_correlations", "processor_version", "policy_id", "policy_hash",
        "correlation_contract_version", "correlation_contract_hash", "authority", *SAFETY.keys(),
    }
    if not isinstance(record, dict) or set(record) != expected:
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_FIELDS_MISMATCH")
    if tuple(record.get(k) for k in ("schema_version", "processor_version", "policy_id",
                                     "correlation_contract_version", "authority")) != (
            SCHEMA_VERSION, PROCESSOR_VERSION, POLICY_ID, CORRELATION_CONTRACT_VERSION, AUTHORITY):
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_IDENTITY_INVALID")
    if any(record.get(k) != v for k, v in SAFETY.items()):
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_SAFETY_INVALID")
    if record["return_history_manifest_hash"] != canonical_hash(record["return_history_manifest"]):
        raise PortfolioCorrelationIntegrityFailure("RETURN_HISTORY_MANIFEST_HASH_MISMATCH")
    if record["held_member_ids"] != sorted(set(record["held_member_ids"])):
        raise PortfolioCorrelationIntegrityFailure("HELD_MEMBER_UNIVERSE_INVALID")
    for wrapper in record["pairwise_correlations"]:
        correlation = wrapper["correlation"]
        if correlation["method"] != METHOD or correlation["unit"] != "CORRELATION":
            raise PortfolioCorrelationIntegrityFailure("PAIR_IDENTITY_INVALID")
        if correlation["members"] != sorted(correlation["members"]) or len(correlation["members"]) != 2:
            raise PortfolioCorrelationIntegrityFailure("PAIR_MEMBERS_INVALID")
    wanted_id = "S6PORTCORR_" + canonical_hash(without(record, "correlation_context_id", "record_hash"))[:24]
    if record["correlation_context_id"] != wanted_id:
        raise PortfolioCorrelationIntegrityFailure("CORRELATION_CONTEXT_ID_MISMATCH")
    if record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_RECORD_HASH_MISMATCH")
    if any(k in record for k in ("portfolio_context", "correlated_capital", "clusters", "buy_sell_hold")):
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_PROHIBITED_OUTPUT")
    return record
