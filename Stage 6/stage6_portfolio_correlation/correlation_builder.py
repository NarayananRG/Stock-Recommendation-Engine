from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone

from stage6_ingestion.canonical import canonical_hash
from stage6_portfolio_arithmetic.portfolio_arithmetic_validation import validate_portfolio_arithmetic
from .correlation_math import emit, pearson
from .errors import PortfolioCorrelationIntegrityFailure, Stage6PortfolioCorrelationError
from .policy import (
    AUTHORITY, CORRELATION_CONTRACT_VERSION, EXPECTED_CORRELATION_CONTRACT_HASH_V1,
    EXPECTED_POLICY_HASH_V1, METHOD, POLICY_ID, PROCESSOR_VERSION, SCHEMA_VERSION,
    SOURCE_CONTRACT_HASH, SOURCE_CONTRACT_VERSION, SOURCE_POLICY_HASH, SOURCE_POLICY_ID,
    SOURCE_PROCESSOR_VERSION, SOURCE_SCHEMA_VERSION,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY"}
RETURN_UNITS = {"PERCENT_RETURN", "DECIMAL_RETURN"}
LOOKBACK_UNITS = {"DAYS", "TRADING_SESSIONS"}
SOURCE_SYSTEMS = {"FIXTURE", "PIT_RETURN_EXPORT"}

SAFETY = {
    "portfolio_arithmetic_status": "FROZEN",
    "correlation_input_status": "FROZEN",
    "correlation_status": "EVALUATED",
    "correlation_interpretation_status": "NOT_EVALUATED",
    "correlated_capital_status": "NOT_EVALUATED",
    "portfolio_context_v2_status": "NOT_MATERIALIZED",
    "portfolio_constraints_status": "NOT_EVALUATED",
    "diversification_status": "NOT_EVALUATED",
    "portfolio_influence_status": "NOT_EVALUATED",
    "buy_sell_hold_status": "NOT_EVALUATED",
    "trading_authority": False,
}


def _timestamp(value, field):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Stage6PortfolioCorrelationError(f"{field}: UTC_TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Stage6PortfolioCorrelationError(f"{field}: UTC_TIMESTAMP_REQUIRED") from exc
    if parsed.tzinfo != timezone.utc:
        raise Stage6PortfolioCorrelationError(f"{field}: UTC_TIMESTAMP_REQUIRED")
    return parsed


def _require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise Stage6PortfolioCorrelationError(f"{field}: REQUIRED")
    return value


def _verify_arithmetic(record):
    validate_portfolio_arithmetic(record)
    actual = tuple(record.get(k) for k in (
        "schema_version", "processor_version", "policy_id", "policy_hash",
        "arithmetic_contract_version", "arithmetic_contract_hash", "authority"))
    expected = (SOURCE_SCHEMA_VERSION, SOURCE_PROCESSOR_VERSION, SOURCE_POLICY_ID, SOURCE_POLICY_HASH,
                SOURCE_CONTRACT_VERSION, SOURCE_CONTRACT_HASH, AUTHORITY)
    if actual != expected:
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_ARITHMETIC_IDENTITY_INVALID")


def canonicalize_manifest(manifest: dict, members: list[str], arithmetic: dict) -> dict:
    if not isinstance(manifest, dict):
        raise Stage6PortfolioCorrelationError("RETURN_HISTORY_MANIFEST_REQUIRED")
    required = {"source_system", "source_export_id", "source_export_hash", "source_schema_version",
                "source_dataset_id", "as_of_timestamp", "data_cutoff_timestamp", "return_frequency",
                "return_unit", "lookback_window", "window_start_timestamp", "minimum_observations", "series"}
    if set(manifest) != required:
        raise Stage6PortfolioCorrelationError("RETURN_HISTORY_MANIFEST_FIELDS_MISMATCH")
    value = deepcopy(manifest)
    if value["source_system"] not in SOURCE_SYSTEMS:
        raise Stage6PortfolioCorrelationError("RETURN_HISTORY_SOURCE_SYSTEM_INVALID")
    for field in ("source_export_id", "source_schema_version", "source_dataset_id"):
        _require_text(value[field], field)
    if not isinstance(value["source_export_hash"], str) or not HEX64.fullmatch(value["source_export_hash"]):
        raise Stage6PortfolioCorrelationError("source_export_hash: CANONICAL_HASH_REQUIRED")
    if value["return_frequency"] not in FREQUENCIES:
        raise Stage6PortfolioCorrelationError("RETURN_FREQUENCY_INVALID")
    if value["return_unit"] not in RETURN_UNITS:
        raise Stage6PortfolioCorrelationError("RETURN_UNIT_INVALID")
    lookback = value["lookback_window"]
    if not isinstance(lookback, dict) or set(lookback) != {"value", "unit"} or isinstance(lookback["value"], bool) or not isinstance(lookback["value"], int) or lookback["value"] <= 0 or lookback["unit"] not in LOOKBACK_UNITS:
        raise Stage6PortfolioCorrelationError("LOOKBACK_WINDOW_INVALID")
    minimum = value["minimum_observations"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 2:
        raise Stage6PortfolioCorrelationError("MINIMUM_OBSERVATIONS_INVALID")
    start = _timestamp(value["window_start_timestamp"], "window_start_timestamp")
    cutoff = _timestamp(value["data_cutoff_timestamp"], "data_cutoff_timestamp")
    as_of = _timestamp(value["as_of_timestamp"], "as_of_timestamp")
    portfolio_cutoff = _timestamp(arithmetic["data_cutoff_timestamp"], "portfolio_data_cutoff")
    source_as_of = _timestamp(arithmetic["source_as_of_timestamp"], "portfolio_source_as_of")
    if start > cutoff:
        raise Stage6PortfolioCorrelationError("RETURN_HISTORY_WINDOW_CHRONOLOGY_INVALID")
    if cutoff > portfolio_cutoff:
        raise Stage6PortfolioCorrelationError("RETURN_HISTORY_AFTER_PORTFOLIO_CUTOFF")
    if as_of > source_as_of:
        raise Stage6PortfolioCorrelationError("RETURN_HISTORY_AS_OF_AFTER_PORTFOLIO_AS_OF")
    if not isinstance(value["series"], list):
        raise Stage6PortfolioCorrelationError("RETURN_HISTORY_SERIES_REQUIRED")
    seen = set()
    canonical_series = []
    for series in value["series"]:
        if not isinstance(series, dict) or set(series) != {"company_entity_id", "status", "observations"}:
            raise Stage6PortfolioCorrelationError("RETURN_SERIES_FIELDS_MISMATCH")
        company = _require_text(series["company_entity_id"], "company_entity_id")
        if company in seen:
            raise Stage6PortfolioCorrelationError("DUPLICATE_COMPANY_SERIES")
        seen.add(company)
        status = series["status"]
        if status not in {"AVAILABLE", "MISSING"} or not isinstance(series["observations"], list):
            raise Stage6PortfolioCorrelationError("RETURN_SERIES_STATUS_INVALID")
        if status == "MISSING" and series["observations"]:
            raise Stage6PortfolioCorrelationError("MISSING_SERIES_MUST_BE_EMPTY")
        observations = []
        periods = set()
        for observation in series["observations"]:
            fields = {"period_end_utc", "return_value", "return_unit", "source_record_id",
                      "source_record_hash", "source_recorded_at_utc"}
            if not isinstance(observation, dict) or set(observation) != fields:
                raise Stage6PortfolioCorrelationError("RETURN_OBSERVATION_FIELDS_MISMATCH")
            period = _timestamp(observation["period_end_utc"], "period_end_utc")
            recorded = _timestamp(observation["source_recorded_at_utc"], "source_recorded_at_utc")
            if period < start or period > cutoff:
                raise Stage6PortfolioCorrelationError("RETURN_OBSERVATION_OUTSIDE_WINDOW")
            if recorded > cutoff:
                raise Stage6PortfolioCorrelationError("RETURN_PROVENANCE_AFTER_CUTOFF")
            if observation["period_end_utc"] in periods:
                raise Stage6PortfolioCorrelationError("DUPLICATE_RETURN_PERIOD")
            periods.add(observation["period_end_utc"])
            if observation["return_unit"] != value["return_unit"]:
                raise Stage6PortfolioCorrelationError("MIXED_RETURN_UNIT")
            from .correlation_math import decimal_value
            decimal_value(observation["return_value"])
            _require_text(observation["source_record_id"], "source_record_id")
            if not isinstance(observation["source_record_hash"], str) or not HEX64.fullmatch(observation["source_record_hash"]):
                raise Stage6PortfolioCorrelationError("SOURCE_RECORD_HASH_INVALID")
            observations.append(deepcopy(observation))
        observations.sort(key=lambda x: x["period_end_utc"])
        canonical_series.append({"company_entity_id": company, "status": status, "observations": observations})
    if seen != set(members):
        raise Stage6PortfolioCorrelationError("RETURN_SERIES_MEMBER_COVERAGE_MISMATCH")
    canonical_series.sort(key=lambda x: x["company_entity_id"])
    value["series"] = canonical_series
    return value


def _pair(left, right, series_by_id, manifest):
    left_series, right_series = series_by_id[left], series_by_id[right]
    common = []
    if left_series["status"] == "AVAILABLE" and right_series["status"] == "AVAILABLE":
        a = {x["period_end_utc"]: x["return_value"] for x in left_series["observations"]}
        b = {x["period_end_utc"]: x["return_value"] for x in right_series["observations"]}
        common = sorted(set(a) & set(b))
    actual = len(common)
    value = None
    if left_series["status"] == "MISSING" or right_series["status"] == "MISSING":
        status = "MISSING_SERIES"
        actual = 0
    elif actual < manifest["minimum_observations"]:
        status = "INSUFFICIENT_OBSERVATIONS"
    else:
        result = pearson([a[t] for t in common], [b[t] for t in common])
        if result is None:
            status = "ZERO_VARIANCE"
        else:
            status = "AVAILABLE"
            value = emit(result)
    compatible = {
        "members": [left, right], "method": METHOD, "value": value, "unit": "CORRELATION",
        "return_frequency": manifest["return_frequency"], "lookback_window": deepcopy(manifest["lookback_window"]),
        "minimum_observations": manifest["minimum_observations"], "actual_observations": actual,
        "data_cutoff_timestamp": manifest["data_cutoff_timestamp"],
    }
    return {
        "correlation": compatible, "calculation_status": status,
        "null_reason": None if status == "AVAILABLE" else status,
        "aligned_timestamp_hash": canonical_hash(common), "aligned_observation_count": actual,
        "return_unit": manifest["return_unit"],
        "source_series_hashes": [canonical_hash(left_series), canonical_hash(right_series)],
    }


def build_portfolio_correlation(*, arithmetic_record: dict, return_history_manifest: dict,
                                policy_hash: str, correlation_contract_hash: str) -> dict:
    _verify_arithmetic(arithmetic_record)
    if policy_hash != EXPECTED_POLICY_HASH_V1 or correlation_contract_hash != EXPECTED_CORRELATION_CONTRACT_HASH_V1:
        raise PortfolioCorrelationIntegrityFailure("PORTFOLIO_CORRELATION_CONFIGURATION_IDENTITY_INVALID")
    members = sorted({x["company_entity_id"] for x in arithmetic_record["derived_open_positions"]})
    manifest = canonicalize_manifest(return_history_manifest, members, arithmetic_record)
    manifest_hash = canonical_hash(manifest)
    series_by_id = {x["company_entity_id"]: x for x in manifest["series"]}
    pairs = [_pair(members[i], members[j], series_by_id, manifest)
             for i in range(len(members)) for j in range(i + 1, len(members))]
    core = {
        "schema_version": SCHEMA_VERSION,
        "arithmetic_record_id": arithmetic_record["arithmetic_record_id"],
        "arithmetic_record_hash": arithmetic_record["record_hash"],
        "source_snapshot_id": arithmetic_record["source_snapshot_id"],
        "source_snapshot_hash": arithmetic_record["source_snapshot_hash"],
        "source_as_of_timestamp": arithmetic_record["source_as_of_timestamp"],
        "portfolio_data_cutoff_timestamp": arithmetic_record["data_cutoff_timestamp"],
        "currency": arithmetic_record["currency"],
        "held_member_ids": members,
        "return_history_manifest": manifest,
        "return_history_manifest_hash": manifest_hash,
        "return_frequency": manifest["return_frequency"], "return_unit": manifest["return_unit"],
        "lookback_window": deepcopy(manifest["lookback_window"]),
        "window_start_timestamp": manifest["window_start_timestamp"],
        "correlation_data_cutoff_timestamp": manifest["data_cutoff_timestamp"],
        "minimum_observations": manifest["minimum_observations"],
        "pairwise_correlations": pairs,
        "processor_version": PROCESSOR_VERSION, "policy_id": POLICY_ID, "policy_hash": policy_hash,
        "correlation_contract_version": CORRELATION_CONTRACT_VERSION,
        "correlation_contract_hash": correlation_contract_hash, "authority": AUTHORITY, **SAFETY,
    }
    identity = canonical_hash(core)
    record = {**core, "correlation_context_id": "S6PORTCORR_" + identity[:24]}
    record["record_hash"] = canonical_hash(record)
    return record
