"""Deterministic registry snapshot builders, verifiers, and PIT resolvers."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import re

from .canonical import canonical_hash, parse_utc, utc_timestamp, without
from .errors import IntegrityFailure, ResolutionError, Stage6IngestionError


HASH_FIELDS = ("previous_version_hash", "record_hash")

ENTITY_FIELDS = {
    "entity_id", "canonical_name", "legal_name", "entity_type", "country",
    "ticker_mappings", "aliases", "isin", "sector_entity_id", "subsector_entity_id",
    "relationships", "entity_record_version", "effective_from", "reviewed_at",
    "previous_version_hash", "record_hash",
}
SOURCE_FIELDS = {
    "source_id", "source_name", "authority_level", "publisher_type", "jurisdiction",
    "coverage", "expected_latency", "supports_machine_access", "historical_depth",
    "requires_auth", "cost_class", "terms_notes", "enabled", "verification_status",
    "source_record_version", "effective_from", "effective_to", "reviewed_at_utc",
    "access_method", "machine_endpoint_type", "licensing_or_terms_status",
    "automation_allowed_status", "rate_limit_notes", "availability_notes",
    "previous_version_hash", "record_hash",
}
ENTITY_TYPES = {"COMPANY", "INDEX", "SECTOR", "SUBSECTOR", "COMMODITY", "CURRENCY",
                "COUNTRY", "REGULATOR", "GOVERNMENT_BODY", "PERSON", "CORPORATE_GROUP"}
AUTHORITY_LEVELS = {"PRIMARY_OFFICIAL", "AUTHORITATIVE_INDEPENDENT", "DISCOVERY", "UNVERIFIED"}
VERIFICATION_STATUSES = {"VERIFIED", "PENDING_REVIEW", "DISABLED", "REJECTED"}
ALIAS_TYPES = {"LEGAL", "FORMER_NAME", "TRADE_NAME", "ABBREVIATION", "COMMON_NAME", "OTHER"}
RELATIONSHIP_TYPES = {"PARENT", "SUBSIDIARY", "CORPORATE_GROUP_MEMBER"}
COST_CLASSES = {"FREE", "FREEMIUM", "PAID", "UNKNOWN"}
ACCESS_METHODS = {"MANUAL_DOWNLOAD", "PUBLIC_API", "MACHINE_FEED", "WEB_PUBLICATION", "OTHER", "NONE"}
ENDPOINT_TYPES = {"REST", "RSS_ATOM", "BULK_FILE", "WEBSOCKET", "GRAPHQL", "HTML", "OTHER", "NONE"}
LICENSING_STATUSES = {"REVIEWED_ALLOWED", "REVIEWED_RESTRICTED", "PENDING_REVIEW", "UNKNOWN"}
AUTOMATION_STATUSES = {"ALLOWED", "RESTRICTED", "PROHIBITED", "UNKNOWN"}
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _date(value: str, field: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise Stage6IngestionError(f"INVALID_DATE:{field}") from exc
    if parsed.isoformat() != value:
        raise Stage6IngestionError(f"INVALID_DATE:{field}")
    return parsed


def _active_date(start: str, end: str | None, cutoff: date) -> bool:
    lower = _date(start, "effective_from")
    upper = _date(end, "effective_to") if end else None
    if upper and lower > upper:
        raise IntegrityFailure("INVALID_EFFECTIVE_PERIOD")
    return lower <= cutoff and (upper is None or cutoff <= upper)


def _record_hash(record: dict) -> str:
    return canonical_hash(without(record, "record_hash"))


def _prepare_records(records: list[dict], version_field: str) -> list[dict]:
    prepared = []
    for raw in records:
        record = deepcopy(raw)
        record.pop("record_hash", None)
        if type(record.get(version_field)) is not int or record[version_field] < 1:
            raise Stage6IngestionError(f"INVALID_{version_field.upper()}")
        previous = record.get("previous_version_hash")
        if previous is not None and (not isinstance(previous, str) or not SHA256_PATTERN.fullmatch(previous)):
            raise Stage6IngestionError("INVALID_PREVIOUS_VERSION_HASH")
        record["record_hash"] = _record_hash(record)
        prepared.append(record)
    return prepared


def _required_string(record: dict, field: str) -> None:
    if not isinstance(record.get(field), str) or not record[field]:
        raise IntegrityFailure(f"REGISTRY_FIELD_INVALID:{field}")


def _nullable_string(record: dict, field: str) -> None:
    if record.get(field) is not None and not isinstance(record[field], str):
        raise IntegrityFailure(f"REGISTRY_FIELD_INVALID:{field}")


def _hash_or_null(value: object, field: str) -> None:
    if value is not None and (not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value)):
        raise IntegrityFailure(f"REGISTRY_HASH_FIELD_INVALID:{field}")


def _unique_strings(value: object, field: str, *, non_empty: bool) -> None:
    if not isinstance(value, list) or (non_empty and not value):
        raise IntegrityFailure(f"REGISTRY_STRING_ARRAY_INVALID:{field}")
    if any(not isinstance(item, str) or not item for item in value) or len(value) != len(set(value)):
        raise IntegrityFailure(f"REGISTRY_STRING_ARRAY_INVALID:{field}")


def _validate_period(item: dict, prefix: str) -> None:
    start = _date(item["effective_from"], f"{prefix}.effective_from")
    end = _date(item["effective_to"], f"{prefix}.effective_to") if item.get("effective_to") is not None else None
    if end is not None and start > end:
        raise IntegrityFailure("INVALID_EFFECTIVE_PERIOD")


def _validate_record_shape(record: dict, records_key: str) -> None:
    expected = ENTITY_FIELDS if records_key == "entities" else SOURCE_FIELDS
    if not isinstance(record, dict) or set(record) != expected:
        raise IntegrityFailure("REGISTRY_RECORD_FIELDS_MISMATCH")
    if records_key == "entities":
        for field in ("entity_id", "canonical_name", "entity_type", "effective_from", "reviewed_at"):
            _required_string(record, field)
        if record["entity_type"] not in ENTITY_TYPES:
            raise IntegrityFailure("ENTITY_TYPE_INVALID")
        if record["entity_type"] == "COMPANY" and not record.get("legal_name"):
            raise IntegrityFailure("COMPANY_LEGAL_NAME_REQUIRED")
        for field in ("legal_name", "country", "isin", "sector_entity_id", "subsector_entity_id"):
            _nullable_string(record, field)
        if (not isinstance(record["ticker_mappings"], list)
                or not isinstance(record["aliases"], list)
                or not isinstance(record["relationships"], list)):
            raise IntegrityFailure("ENTITY_MAPPING_LIST_INVALID")
        for mapping in record["ticker_mappings"]:
            if not isinstance(mapping, dict):
                raise IntegrityFailure("TICKER_MAPPING_FIELDS_MISMATCH")
            if set(mapping) != {"exchange", "ticker", "effective_from", "effective_to"}:
                raise IntegrityFailure("TICKER_MAPPING_FIELDS_MISMATCH")
            _required_string(mapping, "exchange")
            _required_string(mapping, "ticker")
            _validate_period(mapping, "ticker")
        for alias in record["aliases"]:
            if not isinstance(alias, dict):
                raise IntegrityFailure("ALIAS_FIELDS_MISMATCH")
            if set(alias) != {"alias", "alias_type", "effective_from", "effective_to"}:
                raise IntegrityFailure("ALIAS_FIELDS_MISMATCH")
            _required_string(alias, "alias")
            if alias["alias_type"] not in ALIAS_TYPES:
                raise IntegrityFailure("ALIAS_TYPE_INVALID")
            _validate_period(alias, "alias")
        for relationship in record["relationships"]:
            if (not isinstance(relationship, dict)
                    or set(relationship) != {"relationship_type", "related_entity_id", "effective_from",
                                             "effective_to", "evidence_ids"}):
                raise IntegrityFailure("RELATIONSHIP_FIELDS_MISMATCH")
            if relationship["relationship_type"] not in RELATIONSHIP_TYPES:
                raise IntegrityFailure("RELATIONSHIP_TYPE_INVALID")
            _required_string(relationship, "related_entity_id")
            _unique_strings(relationship["evidence_ids"], "relationship.evidence_ids", non_empty=False)
            _validate_period(relationship, "relationship")
    else:
        for field in ("source_id", "source_name", "authority_level", "publisher_type",
                      "expected_latency", "cost_class", "effective_from", "reviewed_at_utc"):
            _required_string(record, field)
        if record["authority_level"] not in AUTHORITY_LEVELS:
            raise IntegrityFailure("SOURCE_AUTHORITY_INVALID")
        if record["verification_status"] not in VERIFICATION_STATUSES:
            raise IntegrityFailure("SOURCE_VERIFICATION_STATUS_INVALID")
        for field in ("enabled", "supports_machine_access", "requires_auth"):
            if type(record[field]) is not bool:
                raise IntegrityFailure(f"SOURCE_BOOLEAN_INVALID:{field}")
        _unique_strings(record["jurisdiction"], "jurisdiction", non_empty=True)
        _unique_strings(record["coverage"], "coverage", non_empty=True)
        if record["cost_class"] not in COST_CLASSES:
            raise IntegrityFailure("SOURCE_COST_CLASS_INVALID")
        if record["access_method"] not in ACCESS_METHODS:
            raise IntegrityFailure("SOURCE_ACCESS_METHOD_INVALID")
        if record["machine_endpoint_type"] not in ENDPOINT_TYPES:
            raise IntegrityFailure("SOURCE_ENDPOINT_TYPE_INVALID")
        if record["licensing_or_terms_status"] not in LICENSING_STATUSES:
            raise IntegrityFailure("SOURCE_LICENSING_STATUS_INVALID")
        if record["automation_allowed_status"] not in AUTOMATION_STATUSES:
            raise IntegrityFailure("SOURCE_AUTOMATION_STATUS_INVALID")
        if not isinstance(record["terms_notes"], str):
            raise IntegrityFailure("SOURCE_TERMS_NOTES_INVALID")
        for field in ("historical_depth", "effective_to", "rate_limit_notes", "availability_notes"):
            _nullable_string(record, field)
    _hash_or_null(record["previous_version_hash"], "previous_version_hash")
    if not isinstance(record["record_hash"], str) or not SHA256_PATTERN.fullmatch(record["record_hash"]):
        raise IntegrityFailure("REGISTRY_RECORD_HASH_FORMAT_INVALID")


def _build_registry(kind: str, schema_version: str, prefix: str, records_key: str,
                    version_field: str, records: list[dict], as_of_timestamp: str,
                    prior: dict | None) -> dict:
    normalized_as_of = utc_timestamp(as_of_timestamp, "as_of_timestamp")
    version = 1 if prior is None else int(prior["registry_version"]) + 1
    previous_hash = None if prior is None else str(prior["registry_hash"])
    payload = {
        "schema_version": schema_version,
        "registry_version": version,
        "as_of_timestamp": normalized_as_of,
        "previous_registry_hash": previous_hash,
        records_key: _prepare_records(records, version_field),
    }
    identity_hash = canonical_hash(payload)
    payload["registry_snapshot_id"] = prefix + identity_hash[:24]
    payload["registry_hash"] = canonical_hash(payload)
    verifier = verify_entity_registry if kind == "ENTITY" else verify_source_registry
    verifier(payload, prior)
    return payload


def build_entity_registry(records: list[dict], as_of_timestamp: str, prior: dict | None = None) -> dict:
    return _build_registry("ENTITY", "STAGE6_ENTITY_REGISTRY_V1", "S6ENTREG_", "entities",
                           "entity_record_version", records, as_of_timestamp, prior)


def build_source_registry(records: list[dict], as_of_timestamp: str, prior: dict | None = None) -> dict:
    return _build_registry("SOURCE", "STAGE6_SOURCE_REGISTRY_V1", "S6SRCREG_", "sources",
                           "source_record_version", records, as_of_timestamp, prior)


def _verify_chain(snapshot: dict, prior: dict | None) -> None:
    if prior is None and snapshot.get("registry_version") != 1:
        previous = snapshot.get("previous_registry_hash")
        if not isinstance(previous, str) or not SHA256_PATTERN.fullmatch(previous):
            raise IntegrityFailure("REGISTRY_PREVIOUS_HASH_MISMATCH")
        return
    expected_version = 1 if prior is None else int(prior["registry_version"]) + 1
    expected_previous = None if prior is None else prior["registry_hash"]
    if snapshot.get("registry_version") != expected_version:
        raise IntegrityFailure("REGISTRY_VERSION_GAP")
    if snapshot.get("previous_registry_hash") != expected_previous:
        raise IntegrityFailure("REGISTRY_PREVIOUS_HASH_MISMATCH")
    if prior is not None and parse_utc(snapshot["as_of_timestamp"], "as_of_timestamp") < parse_utc(prior["as_of_timestamp"], "prior.as_of_timestamp"):
        raise IntegrityFailure("REGISTRY_ASOF_CHRONOLOGY_INVALID")


def _verify_registry(snapshot: dict, schema: str, prefix: str, records_key: str,
                     id_key: str, version_field: str, prior: dict | None) -> dict:
    expected_root = {"schema_version", "registry_snapshot_id", "registry_version", "as_of_timestamp",
                     "previous_registry_hash", "registry_hash", records_key}
    if not isinstance(snapshot, dict) or set(snapshot) != expected_root:
        raise IntegrityFailure("REGISTRY_ROOT_FIELDS_MISMATCH")
    if snapshot.get("schema_version") != schema:
        raise IntegrityFailure("REGISTRY_SCHEMA_MISMATCH")
    _verify_chain(snapshot, prior)
    as_of = parse_utc(snapshot["as_of_timestamp"], "as_of_timestamp")
    _required_string(snapshot, "registry_snapshot_id")
    if type(snapshot["registry_version"]) is not int or snapshot["registry_version"] < 1:
        raise IntegrityFailure("REGISTRY_VERSION_INVALID")
    _hash_or_null(snapshot["previous_registry_hash"], "previous_registry_hash")
    if not isinstance(snapshot["registry_hash"], str) or not SHA256_PATTERN.fullmatch(snapshot["registry_hash"]):
        raise IntegrityFailure("REGISTRY_HASH_FORMAT_INVALID")
    records = snapshot.get(records_key)
    if not isinstance(records, list):
        raise IntegrityFailure("REGISTRY_RECORDS_INVALID")
    if any(not isinstance(record, dict) for record in records):
        raise IntegrityFailure("REGISTRY_RECORDS_INVALID")
    identities = [record.get(id_key) for record in records]
    if None in identities or len(identities) != len(set(identities)):
        raise IntegrityFailure("DUPLICATE_REGISTRY_IDENTITY")
    for record in records:
        _validate_record_shape(record, records_key)
        if record.get("record_hash") != _record_hash(record):
            raise IntegrityFailure("REGISTRY_RECORD_HASH_MISMATCH")
        if type(record.get(version_field)) is not int or record[version_field] < 1:
            raise IntegrityFailure("REGISTRY_RECORD_VERSION_INVALID")
        parse_utc(record["effective_from"], "record.effective_from")
        reviewed_field = "reviewed_at" if records_key == "entities" else "reviewed_at_utc"
        if parse_utc(record[reviewed_field], reviewed_field) > as_of:
            raise IntegrityFailure("REGISTRY_REVIEW_FROM_FUTURE")
        if records_key == "sources" and record.get("effective_to"):
            if parse_utc(record["effective_from"], "effective_from") > parse_utc(record["effective_to"], "effective_to"):
                raise IntegrityFailure("INVALID_EFFECTIVE_PERIOD")
        if records_key == "entities":
            for mapping in [*record.get("ticker_mappings", []), *record.get("aliases", [])]:
                _active_date(mapping["effective_from"], mapping.get("effective_to"), _date(mapping["effective_from"], "effective_from"))
    identity_payload = without(snapshot, "registry_snapshot_id", "registry_hash")
    if snapshot.get("registry_snapshot_id") != prefix + canonical_hash(identity_payload)[:24]:
        raise IntegrityFailure("REGISTRY_SNAPSHOT_ID_MISMATCH")
    if snapshot.get("registry_hash") != canonical_hash(without(snapshot, "registry_hash")):
        raise IntegrityFailure("REGISTRY_HASH_MISMATCH")
    return snapshot


def _verify_record_lineage(snapshot: dict, prior: dict | None, records_key: str,
                           id_key: str, version_field: str) -> None:
    if prior is None:
        if snapshot["registry_version"] == 1:
            for record in snapshot[records_key]:
                if record[version_field] != 1 or record["previous_version_hash"] is not None:
                    raise IntegrityFailure("INITIAL_RECORD_LINEAGE_INVALID")
        return
    old = {record[id_key]: record for record in prior[records_key]}
    for record in snapshot[records_key]:
        previous = old.get(record[id_key])
        if previous is None:
            if record[version_field] != 1 or record["previous_version_hash"] is not None:
                raise IntegrityFailure("NEW_RECORD_LINEAGE_INVALID")
            continue
        changed = without(record, "record_hash") != without(previous, "record_hash")
        if changed:
            if (record[version_field] != previous[version_field] + 1
                    or record["previous_version_hash"] != previous["record_hash"]):
                raise IntegrityFailure("RECORD_LINEAGE_INVALID")
        elif (record[version_field] != previous[version_field]
              or record["previous_version_hash"] != previous["previous_version_hash"]):
            raise IntegrityFailure("UNCHANGED_RECORD_LINEAGE_INVALID")


def verify_entity_registry(snapshot: dict, prior: dict | None = None) -> dict:
    verified = _verify_registry(snapshot, "STAGE6_ENTITY_REGISTRY_V1", "S6ENTREG_", "entities",
                                "entity_id", "entity_record_version", prior)
    _verify_record_lineage(verified, prior, "entities", "entity_id", "entity_record_version")
    # Detect overlapping ticker mappings that can resolve two entities at once.
    mappings: list[tuple[str, str, date, date | None, str]] = []
    for entity in verified["entities"]:
        for item in entity.get("ticker_mappings", []):
            start = _date(item["effective_from"], "ticker.effective_from")
            end = _date(item["effective_to"], "ticker.effective_to") if item.get("effective_to") else None
            key = (str(item["exchange"]).upper(), str(item["ticker"]).upper())
            for exchange, ticker, other_start, other_end, other_entity in mappings:
                overlaps = (end is None or other_start <= end) and (other_end is None or start <= other_end)
                if key == (exchange, ticker) and overlaps and other_entity != entity["entity_id"]:
                    raise IntegrityFailure("AMBIGUOUS_TICKER_MAPPING")
            mappings.append((*key, start, end, entity["entity_id"]))
    return verified


def verify_source_registry(snapshot: dict, prior: dict | None = None) -> dict:
    verified = _verify_registry(snapshot, "STAGE6_SOURCE_REGISTRY_V1", "S6SRCREG_", "sources",
                                "source_id", "source_record_version", prior)
    _verify_record_lineage(verified, prior, "sources", "source_id", "source_record_version")
    return verified


def resolve_entity(snapshot: dict, entity_id: str, cutoff_timestamp: str) -> dict:
    verify_entity_registry(snapshot)
    cutoff = parse_utc(cutoff_timestamp, "cutoff_timestamp")
    matches = [item for item in snapshot["entities"] if item["entity_id"] == entity_id
               and parse_utc(item["effective_from"], "effective_from") <= cutoff]
    if not matches:
        raise ResolutionError("ENTITY_NOT_FOUND")
    if len(matches) != 1:
        raise ResolutionError("ENTITY_RESOLUTION_AMBIGUOUS")
    return matches[0]


def _resolve_mapping(snapshot: dict, field: str, value_key: str, value: str,
                     cutoff_timestamp: str, exchange: str | None = None) -> dict:
    verify_entity_registry(snapshot)
    cutoff = parse_utc(cutoff_timestamp, "cutoff_timestamp").date()
    matches = []
    for entity in snapshot["entities"]:
        for item in entity.get(field, []):
            if str(item[value_key]).casefold() != value.casefold():
                continue
            if exchange is not None and str(item["exchange"]).casefold() != exchange.casefold():
                continue
            if _active_date(item["effective_from"], item.get("effective_to"), cutoff):
                matches.append(entity)
    if not matches:
        raise ResolutionError("ENTITY_NOT_FOUND")
    if len(matches) != 1:
        raise ResolutionError("ENTITY_RESOLUTION_AMBIGUOUS")
    return matches[0]


def resolve_ticker(snapshot: dict, exchange: str, ticker: str, cutoff_timestamp: str) -> dict:
    return _resolve_mapping(snapshot, "ticker_mappings", "ticker", ticker, cutoff_timestamp, exchange)


def resolve_alias(snapshot: dict, alias: str, cutoff_timestamp: str) -> dict:
    return _resolve_mapping(snapshot, "aliases", "alias", alias, cutoff_timestamp)


def resolve_source_record(snapshot: dict, source_id: str, cutoff_timestamp: str,
                          require_usable: bool = True) -> dict:
    verify_source_registry(snapshot)
    cutoff = parse_utc(cutoff_timestamp, "cutoff_timestamp")
    matches = [item for item in snapshot["sources"] if item["source_id"] == source_id]
    if len(matches) != 1:
        raise ResolutionError("SOURCE_NOT_FOUND")
    item = matches[0]
    start = parse_utc(item["effective_from"], "effective_from")
    end = parse_utc(item["effective_to"], "effective_to") if item.get("effective_to") else None
    if cutoff < start or (end and cutoff > end):
        raise ResolutionError("SOURCE_OUTSIDE_EFFECTIVE_INTERVAL")
    if require_usable and (not item["enabled"] or item["verification_status"] != "VERIFIED"):
        raise ResolutionError("SOURCE_DISABLED_OR_UNVERIFIED")
    return item


def assert_source_approved_for_automated_ingestion(source: dict) -> dict:
    if (source["enabled"] is not True
            or source["verification_status"] != "VERIFIED"
            or source["automation_allowed_status"] != "ALLOWED"
            or source["licensing_or_terms_status"] != "REVIEWED_ALLOWED"):
        raise ResolutionError("SOURCE_NOT_APPROVED_FOR_AUTOMATION")
    return source
