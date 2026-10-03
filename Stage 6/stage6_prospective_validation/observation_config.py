"""Frozen identities for the additive Stage 6.8C observation layer."""
from __future__ import annotations

import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import ProspectiveIntegrityFailure

OBSERVATION_POLICY = "S6PROSOBSPOL_STAGE6_8C_V1"
OBSERVATION_CONTRACT = "STAGE6_8C_PROSPECTIVE_OBSERVATION_CONTRACT_V1"
OBSERVATION_STORE_SCHEMA = "STAGE6_8C_PROSPECTIVE_OBSERVATION_STORE_V1"
COHORT_SCHEMA = "STAGE6_8C_COHORT_FINGERPRINT_V1"
ENVELOPE_SCHEMA = "STAGE6_8C_RECOMMENDATION_AUDIT_ENVELOPE_V1"
CHECKPOINT_SCHEMA = "STAGE6_8C_BENCHMARK_CHECKPOINT_V1"
MEASUREMENT_VERSION = "STAGE6_8C_COMMON_CLOSE_DECIMAL_V1"
AUTHORITY = "SHADOW_ONLY"
CHECKPOINT_TYPES = ("D+5", "D+20", "D+60", "FINAL_EXIT")
EXPECTED_POLICY_HASH = "78f0d43da4826896801f030646622fe1324101b592cd178642c67120bdfbfa94"
EXPECTED_CONTRACT_HASH = "8f7fce02be208cfbe2c0c6e95f5127323b5b871c50ff3fa68a451c418ace093e"


def _load(name: str, expected: str):
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if expected != "TO_BE_COMPUTED" and digest != expected:
        raise ProspectiveIntegrityFailure("STAGE6_8C_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def load_observation_policy():
    value, text, digest = _load("prospective_observation_policy_v1.json", EXPECTED_POLICY_HASH)
    expected = (OBSERVATION_POLICY, AUTHORITY, False, "NONE", "PROHIBITED", "PROHIBITED")
    actual = tuple(value.get(key) for key in (
        "policy_id", "authority", "trading_authority", "recommendation_influence",
        "model_retraining", "model_promotion"))
    if actual != expected or tuple(value.get("checkpoint_types", ())) != CHECKPOINT_TYPES:
        raise ProspectiveIntegrityFailure("STAGE6_8C_POLICY_INVALID")
    return value, text, digest


def load_observation_contract():
    value, text, digest = _load("prospective_observation_contract_v1.json", EXPECTED_CONTRACT_HASH)
    expected = (OBSERVATION_CONTRACT, OBSERVATION_STORE_SCHEMA, COHORT_SCHEMA,
                ENVELOPE_SCHEMA, CHECKPOINT_SCHEMA, AUTHORITY, False)
    actual = tuple(value.get(key) for key in (
        "contract_version", "store_schema", "cohort_schema", "envelope_schema",
        "checkpoint_schema", "authority", "trading_authority"))
    if actual != expected or tuple(value.get("checkpoint_types", ())) != CHECKPOINT_TYPES:
        raise ProspectiveIntegrityFailure("STAGE6_8C_CONTRACT_INVALID")
    return value, text, digest
