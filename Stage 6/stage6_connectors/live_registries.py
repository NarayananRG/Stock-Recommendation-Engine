"""Deterministic operational V1→V2 registries for approved RSS connectors."""
from __future__ import annotations

from copy import deepcopy

from stage6_ingestion.registry import build_entity_registry, build_source_registry


SEBI_SOURCE_ID = "SEBI_OFFICIAL_RSS"
SEBI_ENTITY_ID = "SEBI_REGULATOR_IN"
RBI_SOURCE_ID = "RBI_OFFICIAL_PRESS_RELEASES_RSS"
RBI_ENTITY_ID = "RBI_REGULATOR_IN"
REGISTRY_REVIEWED_AT_UTC = "2026-09-25T14:29:18Z"
REGISTRY_EFFECTIVE_FROM_UTC = "2026-09-25T00:00:00Z"
RBI_REVIEWED_AT_UTC = "2026-09-26T06:49:51Z"
RBI_EFFECTIVE_FROM_UTC = "2026-09-26T00:00:00Z"

_ENTITY_RECORDS = [{
    "entity_id": SEBI_ENTITY_ID,
    "canonical_name": "Securities and Exchange Board of India",
    "legal_name": "Securities and Exchange Board of India",
    "entity_type": "REGULATOR",
    "country": "IN",
    "ticker_mappings": [],
    "aliases": [{
        "alias": "SEBI", "alias_type": "ABBREVIATION",
        "effective_from": "1992-04-12", "effective_to": None,
    }],
    "isin": None,
    "sector_entity_id": None,
    "subsector_entity_id": None,
    "relationships": [],
    "entity_record_version": 1,
    "effective_from": REGISTRY_EFFECTIVE_FROM_UTC,
    "reviewed_at": REGISTRY_REVIEWED_AT_UTC,
    "previous_version_hash": None,
}]

_SOURCE_RECORDS = [{
    "source_id": SEBI_SOURCE_ID,
    "source_name": "SEBI Official RSS Feed",
    "authority_level": "PRIMARY_OFFICIAL",
    "publisher_type": "REGULATOR",
    "jurisdiction": ["IN"],
    "coverage": ["SEBI_PRESS_RELEASES", "SEBI_CIRCULARS", "SEBI_ORDERS_RULINGS", "SEBI_REGULATORY_PUBLICATIONS"],
    "expected_latency": "AS_PUBLISHED_BY_SEBI_RSS",
    "supports_machine_access": True,
    "historical_depth": "CURRENT_FEED_WINDOW_AS_PUBLISHED",
    "requires_auth": False,
    "cost_class": "FREE",
    "terms_notes": (
        "Reviewed the official SEBI RSS documentation at https://www.sebi.gov.in/rss.html on "
        "2026-09-25 UTC. It describes RSS as an open method of automatically feeding updated "
        "SEBI headlines, links, and summaries and publishes the official /sebirss.xml subscription URL."
    ),
    "enabled": True,
    "verification_status": "VERIFIED",
    "source_record_version": 1,
    "effective_from": REGISTRY_EFFECTIVE_FROM_UTC,
    "effective_to": None,
    "reviewed_at_utc": REGISTRY_REVIEWED_AT_UTC,
    "access_method": "MACHINE_FEED",
    "machine_endpoint_type": "RSS_ATOM",
    "licensing_or_terms_status": "REVIEWED_ALLOWED",
    "automation_allowed_status": "ALLOWED",
    "rate_limit_notes": "Stage 6.1B performs one request only per explicit operator invocation; no scheduler.",
    "availability_notes": "Official HTTPS RSS endpoint: https://www.sebi.gov.in/sebirss.xml",
    "previous_version_hash": None,
}]


def build_live_registries() -> dict[str, dict]:
    return {
        "entity_v1": build_entity_registry(deepcopy(_ENTITY_RECORDS), REGISTRY_REVIEWED_AT_UTC),
        "source_v1": build_source_registry(deepcopy(_SOURCE_RECORDS), REGISTRY_REVIEWED_AT_UTC),
    }


_RBI_ENTITY_RECORD = {
    "entity_id": RBI_ENTITY_ID,
    "canonical_name": "Reserve Bank of India",
    "legal_name": "Reserve Bank of India",
    "entity_type": "REGULATOR",
    "country": "IN",
    "ticker_mappings": [],
    "aliases": [{
        "alias": "RBI", "alias_type": "ABBREVIATION",
        "effective_from": "1935-04-01", "effective_to": None,
    }],
    "isin": None,
    "sector_entity_id": None,
    "subsector_entity_id": None,
    "relationships": [],
    "entity_record_version": 1,
    "effective_from": RBI_EFFECTIVE_FROM_UTC,
    "reviewed_at": RBI_REVIEWED_AT_UTC,
    "previous_version_hash": None,
}

_RBI_SOURCE_RECORD = {
    "source_id": RBI_SOURCE_ID,
    "source_name": "RBI Official Press Releases RSS",
    "authority_level": "PRIMARY_OFFICIAL",
    "publisher_type": "CENTRAL_BANK",
    "jurisdiction": ["IN"],
    "coverage": ["RBI_PRESS_RELEASES"],
    "expected_latency": "AS_PUBLISHED_BY_RBI_RSS",
    "supports_machine_access": True,
    "historical_depth": "CURRENT_FEED_WINDOW_AS_PUBLISHED",
    "requires_auth": False,
    "cost_class": "FREE",
    "terms_notes": (
        "Reviewed the official RBI RSS documentation at https://www.rbi.org.in/Scripts/rss.aspx on "
        "2026-09-26 UTC. It describes RSS feeds as automatic site updates and explicitly lists a "
        "Press Releases feed at https://rbi.org.in/pressreleases_rss.xml. Approval is limited to "
        "one controlled retrieval of that exact RSS endpoint and does not permit scraping linked pages."
    ),
    "enabled": True,
    "verification_status": "VERIFIED",
    "source_record_version": 1,
    "effective_from": RBI_EFFECTIVE_FROM_UTC,
    "effective_to": None,
    "reviewed_at_utc": RBI_REVIEWED_AT_UTC,
    "access_method": "MACHINE_FEED",
    "machine_endpoint_type": "RSS_ATOM",
    "licensing_or_terms_status": "REVIEWED_ALLOWED",
    "automation_allowed_status": "ALLOWED",
    "rate_limit_notes": "Stage 6.1C performs one request only per explicit operator invocation; no scheduler.",
    "availability_notes": (
        "Official HTTPS endpoint https://rbi.org.in/pressreleases_rss.xml returned HTTP 200 directly "
        "with no redirect during controlled discovery on 2026-09-26 UTC."
    ),
    "previous_version_hash": None,
}


def build_multisource_registries() -> dict[str, dict]:
    v1 = build_live_registries()
    entity_records = deepcopy(v1["entity_v1"]["entities"])
    entity_records.append(deepcopy(_RBI_ENTITY_RECORD))
    source_records = deepcopy(v1["source_v1"]["sources"])
    source_records.append(deepcopy(_RBI_SOURCE_RECORD))
    return {
        **v1,
        "entity_v2": build_entity_registry(entity_records, RBI_REVIEWED_AT_UTC, v1["entity_v1"]),
        "source_v2": build_source_registry(source_records, RBI_REVIEWED_AT_UTC, v1["source_v1"]),
    }
