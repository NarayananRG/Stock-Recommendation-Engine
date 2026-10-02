"""Canonical Stage 6.8B operations identities and configuration."""
from __future__ import annotations

import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import ProspectiveIntegrityFailure


OPERATIONS_CONTRACT = "STAGE6_8B_PROSPECTIVE_OPERATIONS_CONTRACT_V1"
DAILY_OPERATOR = "STAGE6_8B_DAILY_OPERATOR_V1"
SOURCE_COVERAGE_SCHEMA = "STAGE6_8B_SOURCE_COVERAGE_V1"
PRIMARY_CAPTURE_SCHEMA = "STAGE6_8B_PRIMARY_EVIDENCE_CAPTURE_V2"
CAPTURE_SUMMARY_STORE_SCHEMA = "STAGE6_8B_CAPTURE_SUMMARY_STORE_V2"
READINESS_SCHEMA = "STAGE6_8B_PRE_SESSION_READINESS_V1"
OPERATIONS_POLICY = "S6PROSOPSPOL_STAGE6_8B_V1"
BASELINE = "95696d7e616a798d87c81936125bacdb9f441f2e"
AUTHORITY = "SHADOW_ONLY"
OPERATIONAL_SOURCES = ("RBI_OFFICIAL_PRESS_RELEASES_RSS", "SEBI_OFFICIAL_RSS")
ADDITIONAL_SOURCE_STATUS = "NOT_IMPLEMENTED_IN_ACTIVATED_V1"
YFINANCE_STATUS = "NOT_APPROVED_NOT_REGISTERED"
SOURCE_REGISTRY_V2_ID = "S6SRCREG_39b7deae3a0e811e7327af2c"
SOURCE_REGISTRY_V2_HASH = "7d91f4c72365757b6cdfaef0c4027c46bfbdb11c3541c229e828f9ee28d58e90"
ENTITY_REGISTRY_V2_ID = "S6ENTREG_2aed0e083e1186bcade4ede9"
ENTITY_REGISTRY_V2_HASH = "23438181ad6b3cea20c1bc2f4b3cd4236f5f3a1d5bbfcbb5c8cf0b3d0a2a258f"
EXPECTED_POLICY_HASH = "582825a16b9ae40821dacb89c7e5711fd16998153557f2fc6315ca75e5088ec9"
EXPECTED_CONTRACT_HASH = "97f9eb9e551d9104291a21f7c9f935390fbd1359a6d472581ff6ce6a612eb9a4"


def _load(name, expected):
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if expected != "TO_BE_COMPUTED" and digest != expected:
        raise ProspectiveIntegrityFailure("STAGE6_8B_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def load_operations_policy():
    value, text, digest = _load("prospective_operations_policy_v1.json", EXPECTED_POLICY_HASH)
    expected = (OPERATIONS_POLICY, DAILY_OPERATOR, SOURCE_COVERAGE_SCHEMA, PRIMARY_CAPTURE_SCHEMA,
                READINESS_SCHEMA, BASELINE, AUTHORITY, False)
    actual = tuple(value.get(key) for key in (
        "policy_id", "daily_operator", "source_coverage", "primary_evidence_capture",
        "pre_session_readiness", "baseline", "authority", "trading_authority"))
    if (
        actual != expected
        or tuple(value.get("operational_primary_sources", ())) != OPERATIONAL_SOURCES
        or value.get("capture_summary_store") != CAPTURE_SUMMARY_STORE_SCHEMA
        or tuple(value.get("usable_retrieval_statuses", ())) != ("PARTIAL", "RETRIEVED")
        or tuple(value.get("unusable_retrieval_statuses", ()))
        != ("ACCESS_DENIED", "FAILED", "NOT_FOUND", "QUARANTINED")
    ):
        raise ProspectiveIntegrityFailure("STAGE6_8B_POLICY_INVALID")
    return value, text, digest


def load_operations_contract():
    value, text, digest = _load("prospective_operations_contract_v1.json", EXPECTED_CONTRACT_HASH)
    expected = (OPERATIONS_CONTRACT, DAILY_OPERATOR, SOURCE_COVERAGE_SCHEMA, PRIMARY_CAPTURE_SCHEMA,
                READINESS_SCHEMA, AUTHORITY, False)
    actual = tuple(value.get(key) for key in (
        "contract_version", "daily_operator", "source_coverage_schema", "capture_summary_schema",
        "pre_session_readiness_schema", "authority", "trading_authority"))
    if (
        actual != expected
        or value.get("capture_summary_store_schema") != CAPTURE_SUMMARY_STORE_SCHEMA
        or value.get("target_session_date_required") is not True
        or value.get("same_session_morning_required") is not True
        or tuple(value.get("capture_source_set", ())) != OPERATIONAL_SOURCES
    ):
        raise ProspectiveIntegrityFailure("STAGE6_8B_CONTRACT_INVALID")
    return value, text, digest


def verify_operations_configuration():
    policy, _, policy_hash = load_operations_policy()
    contract, _, contract_hash = load_operations_contract()
    return {"result": "PASS", "policy_id": policy["policy_id"], "policy_hash": policy_hash,
            "contract_version": contract["contract_version"], "contract_hash": contract_hash,
            "authority": AUTHORITY, "trading_authority": False}
