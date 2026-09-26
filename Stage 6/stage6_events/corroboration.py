"""Frozen corroboration and conservative materiality gates."""
from __future__ import annotations

from .errors import Stage6EventError


TRUSTWORTHY = {"PRIMARY_OFFICIAL", "AUTHORITATIVE_INDEPENDENT"}


def enforce_evidence_policy(event: dict, evidence: list[dict]) -> None:
    by_source = {item["source_id"]: item for item in evidence}
    authorities = {item["authority_level"] for item in evidence}
    trustworthy_sources = {item["source_id"] for item in evidence if item["authority_level"] in TRUSTWORTHY}
    official_sources = {item["source_id"] for item in evidence if item["authority_level"] == "PRIMARY_OFFICIAL"}
    independent_sources = {item["source_id"] for item in evidence if item["authority_level"] == "AUTHORITATIVE_INDEPENDENT"}
    status = event["corroboration_status"]

    if status == "SINGLE_SOURCE_OFFICIAL" and not (len(by_source) == 1 and authorities == {"PRIMARY_OFFICIAL"}):
        raise Stage6EventError("SINGLE_SOURCE_OFFICIAL_POLICY_FAILED")
    if status == "SINGLE_SOURCE_INDEPENDENT" and not (len(by_source) == 1 and authorities == {"AUTHORITATIVE_INDEPENDENT"}):
        raise Stage6EventError("SINGLE_SOURCE_INDEPENDENT_POLICY_FAILED")
    if status == "CORROBORATED" and len(trustworthy_sources) < 2:
        raise Stage6EventError("CORROBORATION_INDEPENDENCE_FAILED")
    if status == "CONFIRMED":
        official_entities = {entity_id for item in evidence if item["authority_level"] == "PRIMARY_OFFICIAL"
                             for entity_id in item["entity_ids"]}
        if not official_sources or not event["entities"] or not set(event["entities"]).issubset(official_entities):
            raise Stage6EventError("CONFIRMED_PRIMARY_EVIDENCE_REQUIRED")
    if status == "DISCOVERY_ONLY" and authorities != {"DISCOVERY"}:
        raise Stage6EventError("DISCOVERY_ONLY_POLICY_FAILED")
    if status == "UNVERIFIED" and authorities != {"UNVERIFIED"}:
        raise Stage6EventError("UNVERIFIED_POLICY_FAILED")
    if status == "CONFLICTING_EVIDENCE":
        if event["event_status"] != "CONFLICTED" or not event["evidence_conflicts"]:
            raise Stage6EventError("CONFLICTING_EVIDENCE_MUST_BE_EXPLICIT")
    elif event["event_status"] == "CONFLICTED" or any(c["status"] == "OPEN" for c in event["evidence_conflicts"]):
        raise Stage6EventError("OPEN_CONFLICT_REQUIRES_CONFLICTING_STATUS")

    materiality = event["materiality"]
    primary_or_corroborated = bool(official_sources) or len(trustworthy_sources) >= 2
    if materiality == "MATERIAL" and not primary_or_corroborated:
        raise Stage6EventError("MATERIALITY_EVIDENCE_GATE_FAILED")
    if materiality == "HIGH":
        if not event["entities"] or not primary_or_corroborated or any(c["status"] == "OPEN" for c in event["evidence_conflicts"]):
            raise Stage6EventError("HIGH_MATERIALITY_GATE_FAILED")
    if materiality == "CRITICAL":
        corroborators = trustworthy_sources - official_sources
        if not event["entities"] or not official_sources or not corroborators or any(c["status"] == "OPEN" for c in event["evidence_conflicts"]):
            raise Stage6EventError("CRITICAL_MATERIALITY_GATE_FAILED")

    if event["causality_assessment"] != "NO_SUPPORTED_CAUSE_FOUND":
        raise Stage6EventError("STAGE6_2A_CAUSALITY_PROHIBITED")
    if event["transmission_channels"]:
        raise Stage6EventError("STAGE6_2A_TRANSMISSION_PROHIBITED")
