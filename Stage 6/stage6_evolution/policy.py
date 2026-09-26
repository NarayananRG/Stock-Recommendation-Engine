"""Immutable Stage 6.2E evolution policy."""
from __future__ import annotations

import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json

from .errors import Stage6EvolutionError


POLICY_SCHEMA_VERSION = "STAGE6_2E_EVOLUTION_POLICY_V1"
POLICY_ID = "S6EVOPOL_STAGE6_2E_V1"
POLICY_VERSION = 1
EVOLVER_VERSION = "STAGE6_2E_EVENT_EVOLVER_V1"
SUPPORTED_DIRECTIVES = ["ADD_SUPPORT", "OPEN_CONFLICT"]
TRUSTWORTHY_AUTHORITIES = ["AUTHORITATIVE_INDEPENDENT", "PRIMARY_OFFICIAL"]
MAX_CONFLICT_DESCRIPTION = 1000
DEFAULT_POLICY_PATH = Path(__file__).with_name("evolution_policy_v1.json")
POLICY_FIELDS = {"schema_version", "policy_id", "policy_version", "evolver_version",
                 "supported_directives", "trustworthy_authorities",
                 "maximum_conflict_description_characters"}


def validate_policy(policy: dict) -> dict:
    if not isinstance(policy, dict) or set(policy) != POLICY_FIELDS:
        raise Stage6EvolutionError("EVOLUTION_POLICY_FIELDS_MISMATCH")
    if (policy["schema_version"] != POLICY_SCHEMA_VERSION or policy["policy_id"] != POLICY_ID
            or type(policy["policy_version"]) is not int or policy["policy_version"] != POLICY_VERSION
            or policy["evolver_version"] != EVOLVER_VERSION):
        raise Stage6EvolutionError("EVOLUTION_POLICY_IDENTITY_INVALID")
    if policy["supported_directives"] != SUPPORTED_DIRECTIVES:
        raise Stage6EvolutionError("EVOLUTION_POLICY_DIRECTIVES_INVALID")
    if policy["trustworthy_authorities"] != TRUSTWORTHY_AUTHORITIES:
        raise Stage6EvolutionError("EVOLUTION_POLICY_AUTHORITIES_INVALID")
    if (type(policy["maximum_conflict_description_characters"]) is not int
            or policy["maximum_conflict_description_characters"] != MAX_CONFLICT_DESCRIPTION):
        raise Stage6EvolutionError("EVOLUTION_POLICY_DESCRIPTION_LIMIT_INVALID")
    return policy


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> tuple[dict, str, str]:
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage6EvolutionError("EVOLUTION_POLICY_LOAD_FAILED") from exc
    validate_policy(policy)
    serialized = canonical_json(policy)
    return policy, serialized, canonical_hash(policy)
