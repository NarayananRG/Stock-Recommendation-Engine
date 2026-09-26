"""Runtime enforcement of the frozen STAGE6_EVENT_V1 contract."""
from __future__ import annotations

import re

from stage6_ingestion.canonical import canonical_hash, parse_utc, utc_timestamp, without

from .errors import EventIntegrityFailure, Stage6EventError


HASH = re.compile(r"^[a-f0-9]{64}$")
EVENT_FIELDS = {
    "schema_version", "event_id", "event_version", "previous_event_version_hash",
    "record_hash", "event_type", "event_status", "direction", "severity",
    "materiality", "confidence", "entities", "sectors", "geographies",
    "commodities", "currencies", "source_evidence_ids", "corroboration_status",
    "first_known_timestamp", "last_updated_timestamp", "entity_resolution_version",
    "event_horizon", "transmission_channels", "causality_assessment", "evidence_conflicts",
}
EVENT_TYPES = {
    "EARNINGS_BEAT", "EARNINGS_MISS", "GUIDANCE_RAISE", "GUIDANCE_CUT", "ORDER_WIN",
    "ORDER_LOSS", "CUSTOMER_LOSS", "MANAGEMENT_CHANGE", "PROMOTER_EVENT",
    "GOVERNANCE_ALLEGATION", "FRAUD_ALLEGATION", "SHORT_SELLER_ALLEGATION",
    "REGULATORY_ACTION", "LEGAL_EVENT", "DEBT_STRESS", "CREDIT_UPGRADE",
    "CREDIT_DOWNGRADE", "RATING_UPGRADE", "RATING_DOWNGRADE", "DEFAULT_EVENT",
    "INSOLVENCY_EVENT", "CYBERSECURITY_EVENT", "PRODUCT_RECALL", "CAPITAL_RAISE",
    "MERGER", "ACQUISITION", "DEMERGER", "TARIFF_INCREASE", "TARIFF_REDUCTION",
    "TAX_OR_DUTY_CHANGE", "TRADE_RESTRICTION", "SANCTION", "WAR_ESCALATION",
    "WAR_DEESCALATION", "OIL_SHOCK", "GAS_SHOCK", "COMMODITY_SHOCK", "RATE_HIKE",
    "RATE_CUT", "LIQUIDITY_EVENT", "CURRENCY_SHOCK", "SUPPLY_CHAIN_DISRUPTION",
    "NATURAL_DISASTER", "GOVERNMENT_POLICY", "SECTOR_REGULATION", "OTHER",
}
ENUMS = {
    "event_status": {"CANDIDATE", "ACTIVE", "RESOLVED", "RETRACTED", "CONFLICTED"},
    "direction": {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"},
    "severity": {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"},
    "materiality": {"NON_MATERIAL", "MATERIAL", "HIGH", "CRITICAL", "UNKNOWN"},
    "corroboration_status": {"CONFIRMED", "CORROBORATED", "SINGLE_SOURCE_OFFICIAL",
                              "SINGLE_SOURCE_INDEPENDENT", "DISCOVERY_ONLY", "UNVERIFIED",
                              "CONFLICTING_EVIDENCE"},
    "event_horizon": {"INTRADAY", "DAYS", "WEEKS", "MONTHS", "LONG_TERM", "UNKNOWN"},
    "causality_assessment": {"CONFIRMED_CAUSE", "PLAUSIBLE_CONTRIBUTOR",
                              "CORRELATED_MARKET_MOVE", "NO_SUPPORTED_CAUSE_FOUND"},
}
TRANSMISSION = {"MACRO", "COMMODITY", "CURRENCY", "RATE", "SECTOR",
                "COMPANY_EXPOSURE", "MARKET_REACTION", "THESIS"}
ARRAY_FIELDS = ("entities", "sectors", "geographies", "commodities", "currencies",
                "source_evidence_ids", "transmission_channels")


def _strings(values: object, field: str, *, nonempty: bool = False) -> list[str]:
    if (not isinstance(values, list) or (nonempty and not values)
            or any(not isinstance(value, str) or not value for value in values)
            or len(values) != len(set(values))):
        raise Stage6EventError(f"EVENT_ARRAY_INVALID:{field}")
    return values


def validate_event(record: dict, *, verify_hash: bool = True) -> dict:
    if not isinstance(record, dict) or set(record) != EVENT_FIELDS:
        raise Stage6EventError("EVENT_FIELDS_MISMATCH")
    if record["schema_version"] != "STAGE6_EVENT_V1":
        raise Stage6EventError("EVENT_SCHEMA_VERSION_INVALID")
    if not isinstance(record["event_id"], str) or not record["event_id"]:
        raise Stage6EventError("EVENT_ID_INVALID")
    if type(record["event_version"]) is not int or record["event_version"] < 1:
        raise Stage6EventError("EVENT_VERSION_INVALID")
    previous = record["previous_event_version_hash"]
    if previous is not None and (not isinstance(previous, str) or not HASH.fullmatch(previous)):
        raise Stage6EventError("PREVIOUS_EVENT_HASH_INVALID")
    if record["event_version"] == 1 and previous is not None:
        raise Stage6EventError("EVENT_V1_PREDECESSOR_MUST_BE_NULL")
    if record["event_version"] > 1 and previous is None:
        raise Stage6EventError("EVENT_PREDECESSOR_REQUIRED")
    if record["event_type"] not in EVENT_TYPES:
        raise Stage6EventError("EVENT_TYPE_INVALID")
    for field, values in ENUMS.items():
        if record[field] not in values:
            raise Stage6EventError(f"EVENT_ENUM_INVALID:{field}")
    confidence = record["confidence"]
    if type(confidence) not in (int, float) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise Stage6EventError("EVENT_CONFIDENCE_INVALID")
    for field in ARRAY_FIELDS:
        _strings(record[field], field, nonempty=field == "source_evidence_ids")
    if any(value not in TRANSMISSION for value in record["transmission_channels"]):
        raise Stage6EventError("EVENT_TRANSMISSION_INVALID")
    if not isinstance(record["entity_resolution_version"], str) or not record["entity_resolution_version"]:
        raise Stage6EventError("ENTITY_RESOLUTION_VERSION_INVALID")
    first = utc_timestamp(record["first_known_timestamp"], "first_known_timestamp")
    updated = utc_timestamp(record["last_updated_timestamp"], "last_updated_timestamp")
    if first != record["first_known_timestamp"] or updated != record["last_updated_timestamp"]:
        raise Stage6EventError("EVENT_TIMESTAMP_NOT_CANONICAL")
    if parse_utc(first, "first_known_timestamp") > parse_utc(updated, "last_updated_timestamp"):
        raise Stage6EventError("EVENT_CHRONOLOGY_INVALID")
    conflicts = record["evidence_conflicts"]
    if not isinstance(conflicts, list):
        raise Stage6EventError("EVENT_CONFLICTS_INVALID")
    for conflict in conflicts:
        if not isinstance(conflict, dict) or set(conflict) != {"evidence_ids", "description", "status"}:
            raise Stage6EventError("EVENT_CONFLICT_FIELDS_INVALID")
        ids = _strings(conflict["evidence_ids"], "conflict.evidence_ids")
        if len(ids) < 2 or not isinstance(conflict["description"], str) or not conflict["description"]:
            raise Stage6EventError("EVENT_CONFLICT_INVALID")
        if conflict["status"] not in {"OPEN", "RESOLVED"}:
            raise Stage6EventError("EVENT_CONFLICT_STATUS_INVALID")
        if not set(ids).issubset(record["source_evidence_ids"]):
            raise Stage6EventError("CONFLICT_EVIDENCE_NOT_EVENT_DEPENDENCY")
    if not isinstance(record["record_hash"], str) or not HASH.fullmatch(record["record_hash"]):
        raise Stage6EventError("EVENT_RECORD_HASH_INVALID")
    if verify_hash and canonical_hash(without(record, "record_hash")) != record["record_hash"]:
        raise EventIntegrityFailure("EVENT_RECORD_HASH_MISMATCH")
    return record
