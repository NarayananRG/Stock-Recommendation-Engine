"""Frozen local policy identity for Stage 6.2F."""
from __future__ import annotations

import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json

from .errors import Stage6LifecycleError


POLICY_SCHEMA_VERSION = "STAGE6_2F_LIFECYCLE_POLICY_V1"
POLICY_ID = "S6LIFEPOL_STAGE6_2F_V1"
POLICY_VERSION = 1
PROCESSOR_VERSION = "STAGE6_2F_EVENT_LIFECYCLE_V1"
SUPPORTED_DIRECTIVES = ("APPLY_CORRECTION", "RETRACT_EVENT", "RESOLVE_CONFLICT")
TRUSTWORTHY = ("AUTHORITATIVE_INDEPENDENT", "PRIMARY_OFFICIAL")
AUTHORITY = "SHADOW_ONLY"
FIELDS = {"schema_version", "policy_id", "policy_version", "processor_version",
          "supported_directives", "trustworthy_authorities", "authority"}


def validate_policy(record: dict) -> dict:
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise Stage6LifecycleError("LIFECYCLE_POLICY_FIELDS_MISMATCH")
    if (record["schema_version"], record["policy_id"], record["policy_version"],
            record["processor_version"], record["authority"]) != (
            POLICY_SCHEMA_VERSION, POLICY_ID, POLICY_VERSION, PROCESSOR_VERSION, AUTHORITY):
        raise Stage6LifecycleError("LIFECYCLE_POLICY_IDENTITY_INVALID")
    if tuple(record["supported_directives"]) != SUPPORTED_DIRECTIVES:
        raise Stage6LifecycleError("LIFECYCLE_POLICY_DIRECTIVES_INVALID")
    if tuple(record["trustworthy_authorities"]) != TRUSTWORTHY:
        raise Stage6LifecycleError("LIFECYCLE_POLICY_AUTHORITIES_INVALID")
    return record


def load_policy() -> tuple[dict, str, str]:
    try:
        record = json.loads(Path(__file__).with_name("lifecycle_policy_v1.json").read_text(encoding="utf-8"))
        validate_policy(record)
        serialized = canonical_json(record)
        return record, serialized, canonical_hash(record)
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage6LifecycleError("LIFECYCLE_POLICY_LOAD_FAILED") from exc
