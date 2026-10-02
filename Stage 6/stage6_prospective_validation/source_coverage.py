"""Deterministic attestation of the frozen Stage 6.1C operational source set."""
from __future__ import annotations

from datetime import datetime, timezone

from stage6_connectors import RbiRssConnector, SebiRssConnector
from stage6_connectors.live_registries import build_multisource_registries
from stage6_connectors.policy import APPROVED_ENDPOINTS
from stage6_ingestion.canonical import canonical_hash, without
from stage6_ingestion.registry import verify_entity_registry, verify_source_registry

from .activation import verify_activation_record
from .errors import ProspectiveIntegrityFailure
from .operations_config import (
    ADDITIONAL_SOURCE_STATUS, AUTHORITY, OPERATIONAL_SOURCES, SOURCE_COVERAGE_SCHEMA,
    YFINANCE_STATUS, load_operations_contract, load_operations_policy,
)


def _now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _binding(record_type, record_id, record_hash):
    return {"record_type": record_type, "record_id": record_id, "record_hash": record_hash}


def attest_sources(activation_record):
    activation = verify_activation_record(activation_record)
    policy, _, policy_hash = load_operations_policy()
    contract, _, contract_hash = load_operations_contract()
    registries = build_multisource_registries()
    verify_entity_registry(registries["entity_v1"])
    verify_source_registry(registries["source_v1"])
    verify_entity_registry(registries["entity_v2"], registries["entity_v1"])
    verify_source_registry(registries["source_v2"], registries["source_v1"])
    endpoints = {item.source_id: item for item in APPROVED_ENDPOINTS}
    sources = {item["source_id"]: item for item in registries["source_v2"]["sources"]}
    connectors = {"SEBI_OFFICIAL_RSS": SebiRssConnector, "RBI_OFFICIAL_PRESS_RELEASES_RSS": RbiRssConnector}
    if tuple(sorted(endpoints)) != OPERATIONAL_SOURCES or tuple(sorted(sources)) != OPERATIONAL_SOURCES:
        raise ProspectiveIntegrityFailure("ACTIVATED_V1_SOURCE_SET_CHANGED")
    rows = []
    for source_id in OPERATIONAL_SOURCES:
        source = sources[source_id]
        endpoint = endpoints[source_id]
        required = (
            source["authority_level"] == "PRIMARY_OFFICIAL",
            source["verification_status"] == "VERIFIED",
            source["enabled"] is True,
            source["automation_allowed_status"] == "ALLOWED",
            source["licensing_or_terms_status"] == "REVIEWED_ALLOWED",
            source["supports_machine_access"] is True,
            source["requires_auth"] is False,
            source["cost_class"] == "FREE",
            source_id in connectors,
        )
        if not all(required):
            raise ProspectiveIntegrityFailure("OPERATIONAL_SOURCE_CAPABILITY_INVALID")
        rows.append({
            "source_id": source_id, "source_record_version": source["source_record_version"],
            "source_record_hash": source["record_hash"], "authority_level": source["authority_level"],
            "publisher_type": source["publisher_type"], "endpoint": endpoint.url,
            "verification_status": source["verification_status"], "enabled": source["enabled"],
            "automation_status": source["automation_allowed_status"],
            "licensing_status": source["licensing_or_terms_status"],
            "supports_machine_access": source["supports_machine_access"],
            "requires_auth": source["requires_auth"], "cost_class": source["cost_class"],
            "connector_implementation_status": "IMPLEMENTED_FROZEN_STAGE6_1",
        })
    record = {
        "schema_version": SOURCE_COVERAGE_SCHEMA, "generated_at_utc": _now_utc(),
        "activation_binding": _binding(activation["schema_version"], activation["activation_id"], activation["record_hash"]),
        "operations_policy_binding": _binding(policy["policy_id"], policy["policy_id"], policy_hash),
        "operations_contract_binding": _binding(contract["contract_version"], contract["contract_version"], contract_hash),
        "entity_registry_v2_binding": _binding("STAGE6_ENTITY_REGISTRY_V1", registries["entity_v2"]["registry_snapshot_id"], registries["entity_v2"]["registry_hash"]),
        "source_registry_v2_binding": _binding("STAGE6_SOURCE_REGISTRY_V1", registries["source_v2"]["registry_snapshot_id"], registries["source_v2"]["registry_hash"]),
        "operational_sources": rows, "operational_primary_count": len(rows),
        "activated_v1_operational_primary_source_set": list(OPERATIONAL_SOURCES),
        "additional_primary_source_connector_status": ADDITIONAL_SOURCE_STATUS,
        "coverage_gap_meaning": "OPERATIONAL_COVERAGE_LIMITATION_NOT_NO_NEWS_OR_NO_RISK",
        "yfinance_stage6_evidence_status": YFINANCE_STATUS,
        "yfinance_stage4a3_status": "STAGE4A3_MARKET_DATA_DEPENDENCY_FROZEN_OUTSIDE_STAGE6_EVIDENCE",
        "yfinance_stage5d_status": "STAGE5D_CONTROL_DEPENDENCY_FROZEN_OUTSIDE_STAGE6_EVIDENCE",
        "stage6_event_evidence_source_status": "ONLY_REGISTERED_PRIMARY_OFFICIAL_SOURCES",
        "authority": AUTHORITY, "trading_authority": False, "record_hash": "",
    }
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record


def verify_source_attestation(record, activation_record):
    expected = attest_sources(activation_record)
    expected["generated_at_utc"] = record.get("generated_at_utc")
    expected["record_hash"] = canonical_hash(without(expected, "record_hash"))
    if record != expected or record.get("record_hash") != canonical_hash(without(record, "record_hash")):
        raise ProspectiveIntegrityFailure("SOURCE_COVERAGE_ATTESTATION_INVALID")
    return True
