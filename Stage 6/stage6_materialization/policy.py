"""Immutable Stage 6.2D materialization policy loading and validation."""
from __future__ import annotations

import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json

from .errors import Stage6MaterializationError


POLICY_SCHEMA_VERSION = "STAGE6_2D_MATERIALIZATION_POLICY_V1"
POLICY_ID = "S6MATPOL_STAGE6_2D_V1"
POLICY_VERSION = 1
MATERIALIZER_VERSION = "STAGE6_2D_EVENT_MATERIALIZER_V1"
DEFAULT_POLICY_PATH = Path(__file__).with_name("materialization_policy_v1.json")
POLICY_FIELDS = {"schema_version", "policy_id", "policy_version", "materializer_version",
                 "eligible_candidate_status", "event_defaults"}
EXACT_DEFAULTS = {
    "event_status": "CANDIDATE", "direction": "UNKNOWN", "severity": "UNKNOWN",
    "materiality": "UNKNOWN", "confidence": 0.0, "entities": [], "sectors": [],
    "geographies": [], "commodities": [], "currencies": [],
    "corroboration_status": "SINGLE_SOURCE_OFFICIAL", "event_horizon": "UNKNOWN",
    "transmission_channels": [], "causality_assessment": "NO_SUPPORTED_CAUSE_FOUND",
    "evidence_conflicts": [],
}


def validate_policy(policy: dict) -> dict:
    if not isinstance(policy, dict) or set(policy) != POLICY_FIELDS:
        raise Stage6MaterializationError("POLICY_FIELDS_MISMATCH")
    if (policy["schema_version"] != POLICY_SCHEMA_VERSION or policy["policy_id"] != POLICY_ID
            or type(policy["policy_version"]) is not int or policy["policy_version"] != POLICY_VERSION
            or policy["materializer_version"] != MATERIALIZER_VERSION):
        raise Stage6MaterializationError("POLICY_IDENTITY_INVALID")
    if policy["eligible_candidate_status"] != "MATCHED":
        raise Stage6MaterializationError("POLICY_ELIGIBILITY_INVALID")
    if policy["event_defaults"] != EXACT_DEFAULTS:
        raise Stage6MaterializationError("POLICY_EVENT_DEFAULTS_INVALID")
    if type(policy["event_defaults"]["confidence"]) is not float:
        raise Stage6MaterializationError("POLICY_CONFIDENCE_TYPE_INVALID")
    return policy


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> tuple[dict, str, str]:
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage6MaterializationError("POLICY_LOAD_FAILED") from exc
    validate_policy(policy)
    serialized = canonical_json(policy)
    return policy, serialized, canonical_hash(policy)
