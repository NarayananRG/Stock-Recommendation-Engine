"""Deterministic synthetic registry fixtures used by tests and the offline demo."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from .registry import build_entity_registry, build_source_registry


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "stage6_1a"


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def build_fixture_registries() -> dict[str, dict]:
    """Build two immutable versions of each entirely synthetic registry."""
    entity_v1 = build_entity_registry(
        _load("entity_records_v1.json"), "2026-01-02T00:00:00Z")
    source_v1 = build_source_registry(
        _load("source_records_v1.json"), "2026-01-02T00:00:00Z")

    entity_records_v2 = deepcopy(entity_v1["entities"])
    company = next(row for row in entity_records_v2 if row["entity_id"] == "S6FIX_COMPANY_001")
    company["entity_record_version"] = 2
    company["previous_version_hash"] = company["record_hash"]
    company["reviewed_at"] = "2026-08-01T00:00:00Z"
    company["legal_name"] = "Fixture Technologies Limited (Synthetic V2)"
    entity_v2 = build_entity_registry(
        entity_records_v2, "2026-08-02T00:00:00Z", entity_v1)

    source_records_v2 = deepcopy(source_v1["sources"])
    source = source_records_v2[0]
    source["source_record_version"] = 2
    source["previous_version_hash"] = source["record_hash"]
    source["reviewed_at_utc"] = "2026-08-01T00:00:00Z"
    source["availability_notes"] = "Fixture V2 availability note; still synthetic."
    source_v2 = build_source_registry(
        source_records_v2, "2026-08-02T00:00:00Z", source_v1)
    return {
        "entity_v1": entity_v1,
        "entity_v2": entity_v2,
        "source_v1": source_v1,
        "source_v2": source_v2,
    }
