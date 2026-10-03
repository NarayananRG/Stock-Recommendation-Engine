"""Research-only future source registry and fail-closed evidence contract."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from common import parse_time, record, sha256

STATUSES = {"VERIFIED_IMPLEMENTED", "VERIFIED_NOT_IMPLEMENTED", "UNVERIFIED", "NOT_AVAILABLE", "TEST_FIXTURE_ONLY"}


@dataclass(frozen=True)
class FutureSourceRegistry:
    registry_id: str
    sources: tuple[dict, ...]

    @classmethod
    def build(cls, sources: list[dict]) -> "FutureSourceRegistry":
        seen, checked = set(), []
        for source in sources:
            s = dict(source)
            if not s.get("source_id") or not s.get("authority_classification") or not s.get("publisher"):
                raise ValueError("source identity, authority, and publisher required")
            if s.get("implementation_status") not in STATUSES:
                raise ValueError("invalid source implementation status")
            if s["source_id"] in seen:
                raise ValueError("duplicate source")
            if s["implementation_status"].startswith("VERIFIED") and (not s.get("reference") or not s.get("provenance")):
                raise ValueError("verified source requires reference and provenance")
            if s["implementation_status"] == "VERIFIED_IMPLEMENTED" and not s.get("parser_id"):
                raise ValueError("implemented source requires parser identity")
            seen.add(s["source_id"]); checked.append(s)
        return cls("STAGE6_SOURCE_REGISTRY_V2_RESEARCH", tuple(sorted(checked, key=lambda x: x["source_id"])))

    @property
    def registry_hash(self) -> str:
        return sha256({"registry_id": self.registry_id, "authority": "RESEARCH_ONLY_NOT_ACTIVATED", "sources": self.sources})

    def source(self, source_id: str) -> dict:
        matches = [s for s in self.sources if s["source_id"] == source_id]
        if len(matches) != 1:
            raise ValueError("unknown source identity")
        return matches[0]


def validate_evidence(event: dict, registry: FutureSourceRegistry, raw_content: bytes, parser_id: str, cutoff: str) -> dict:
    source = registry.source(event.get("source_id", ""))
    if source["implementation_status"] not in {"VERIFIED_IMPLEMENTED", "TEST_FIXTURE_ONLY"}:
        raise ValueError("unverified or unimplemented source")
    required = {"publisher", "reference", "retrieved_at", "observed_at", "published_at", "raw_content_hash", "parser_id", "parser_code_hash", "event_type", "evidence_class"}
    if required - event.keys():
        raise ValueError("malformed source record")
    if event["publisher"] != source["publisher"] or event["parser_id"] != parser_id or source.get("parser_id") != parser_id:
        raise ValueError("parser or publisher mismatch")
    if hashlib.sha256(raw_content).hexdigest() != event["raw_content_hash"]:
        raise ValueError("content hash mismatch")
    published, observed, retrieved, limit = map(parse_time, (event["published_at"], event["observed_at"], event["retrieved_at"], cutoff))
    if not (published <= observed <= retrieved <= limit):
        raise ValueError("PIT timestamp violation")
    if event["evidence_class"] != "PRIMARY_EVIDENCE":
        raise ValueError("model interpretation cannot masquerade as primary evidence")
    return record("FUTURE_EVIDENCE_RECORD_V1", {**event, "future_registry_hash": registry.registry_hash})


def fixture_connector(payload: bytes, source_id: str = "LOCAL_OFFICIAL_FIXTURE") -> dict:
    return {"source_id": source_id, "raw_content_hash": hashlib.sha256(payload).hexdigest(), "connector_mode": "LOCAL_FIXTURE_ONLY", "network_calls": 0}

