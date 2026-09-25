"""SEBI RSS acquisition into the immutable Stage 6.1A evidence store."""
from __future__ import annotations

from datetime import timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from stage6_ingestion.canonical import canonical_hash, parse_utc, sha256_bytes, utc_timestamp
from stage6_ingestion.errors import IntegrityFailure
from stage6_ingestion.registry import (
    assert_source_approved_for_automated_ingestion, resolve_entity, resolve_source_record,
)

from .live_registries import SEBI_ENTITY_ID, SEBI_SOURCE_ID
from .policy import SEBI_RSS_URL
from .transport import ControlledHttpsTransport, TransportFailure, TransportResponse


ALLOWED_CONTENT_TYPES = {"application/rss+xml", "application/xml", "text/xml"}
HTTP_FAILURE_STATUS = {401: "ACCESS_DENIED", 403: "ACCESS_DENIED", 404: "NOT_FOUND"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _feed_metadata(body: bytes, content_type: str, observed: str, *, truncated: bool) -> dict:
    media_type = content_type.split(";", 1)[0].strip().casefold()
    if truncated:
        return {"valid": False, "reason": "TRUNCATED_PAYLOAD", "publication": None, "title": None}
    if media_type not in ALLOWED_CONTENT_TYPES:
        return {"valid": False, "reason": "CONTENT_TYPE_REJECTED", "publication": None, "title": None}
    lowered = body.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        return {"valid": False, "reason": "XML_EXTERNAL_OR_ENTITY_DECLARATION_REJECTED", "publication": None, "title": None}
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return {"valid": False, "reason": "MALFORMED_XML", "publication": None, "title": None}
    root_name = _local_name(root.tag)
    if root_name == "rss":
        channel = next((child for child in root if _local_name(child.tag) == "channel"), None)
        if channel is None:
            return {"valid": False, "reason": "RSS_CHANNEL_MISSING", "publication": None, "title": None}
        title_node = next((child for child in channel if _local_name(child.tag) == "title"), None)
        # Prefer the RSS channel publication timestamp when both are present. Some feeds expose
        # a timezone-less lastBuildDate alongside a fully qualified pubDate.
        date_node = next((child for child in channel if _local_name(child.tag) == "pubdate"), None)
        if date_node is None:
            date_node = next((child for child in channel if _local_name(child.tag) == "lastbuilddate"), None)
    elif root_name == "feed":
        channel = root
        title_node = next((child for child in channel if _local_name(child.tag) == "title"), None)
        date_node = next((child for child in channel if _local_name(child.tag) in {"updated", "published"}), None)
    else:
        return {"valid": False, "reason": "RSS_ROOT_REJECTED", "publication": None, "title": None}
    title = title_node.text.strip() if title_node is not None and title_node.text else None
    publication = None
    if date_node is not None and date_node.text and date_node.text.strip():
        raw_date = date_node.text.strip()
        try:
            if root_name == "rss":
                parsed = parsedate_to_datetime(raw_date)
                if parsed.tzinfo is None:
                    raise ValueError("timezone required")
                publication = parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            else:
                publication = utc_timestamp(raw_date, "feed.publication")
        except (TypeError, ValueError):
            return {"valid": False, "reason": "PUBLISHER_TIMESTAMP_INVALID", "publication": None, "title": title}
        if parse_utc(publication, "feed.publication") > parse_utc(observed, "observed"):
            return {"valid": False, "reason": "PUBLISHER_TIMESTAMP_FROM_FUTURE", "publication": None, "title": title}
    return {"valid": True, "reason": None, "publication": publication, "title": title}


class SebiRssConnector:
    def __init__(self, store, transport=None):
        self.store = store
        self.transport = transport or ControlledHttpsTransport()

    def _approve_before_network(self, source_snapshot_id: str, entity_snapshot_id: str, cutoff: str) -> None:
        source_registry = self.store._verify_persisted_registry_chain("SOURCE", source_snapshot_id)
        entity_registry = self.store._verify_persisted_registry_chain("ENTITY", entity_snapshot_id)
        cutoff_value = parse_utc(cutoff, "acquisition_cutoff")
        if (parse_utc(source_registry["as_of_timestamp"], "source_registry.as_of_timestamp") > cutoff_value
                or parse_utc(entity_registry["as_of_timestamp"], "entity_registry.as_of_timestamp") > cutoff_value):
            raise IntegrityFailure("REGISTRY_SNAPSHOT_FROM_FUTURE")
        source = resolve_source_record(source_registry, SEBI_SOURCE_ID, cutoff, require_usable=False)
        assert_source_approved_for_automated_ingestion(source)
        resolve_entity(entity_registry, SEBI_ENTITY_ID, cutoff)

    @staticmethod
    def _key(kind: str, source_snapshot_id: str, entity_snapshot_id: str,
             observed: str, retrieved: str, discriminator: str) -> str:
        return "S6_1B_SEBI_" + canonical_hash({
            "kind": kind,
            "source_registry_snapshot_id": source_snapshot_id,
            "entity_registry_snapshot_id": entity_snapshot_id,
            "source_id": SEBI_SOURCE_ID,
            "observed_timestamp_utc": observed,
            "retrieved_timestamp_utc": retrieved,
            "discriminator": discriminator,
        })[:32]

    def acquire(self, *, source_registry_snapshot_id: str, entity_registry_snapshot_id: str,
                observed_timestamp_utc: str) -> dict:
        observed = utc_timestamp(observed_timestamp_utc, "observed_timestamp_utc")
        self._approve_before_network(source_registry_snapshot_id, entity_registry_snapshot_id, observed)
        try:
            response = self.transport.fetch()
        except TransportFailure as exc:
            failure_status = "FAILED"
            key = self._key("FAILURE", source_registry_snapshot_id, entity_registry_snapshot_id,
                            observed, observed, exc.code)
            persisted = self.store.capture_acquisition_failure(
                idempotency_key=key,
                source_registry_snapshot_id=source_registry_snapshot_id,
                entity_registry_snapshot_id=entity_registry_snapshot_id,
                source_id=SEBI_SOURCE_ID,
                source_reference=SEBI_RSS_URL,
                retrieval_status=failure_status,
                failure_reason=exc.code,
                failure_stage="HTTP_TRANSPORT",
                attempted_at_utc=observed,
                entity_ids=[SEBI_ENTITY_ID],
            )
            return {"outcome": "ACQUISITION_ATTEMPT", "reason": exc.code, **persisted}
        retrieved = utc_timestamp(response.retrieved_timestamp_utc, "retrieved_timestamp_utc")
        if response.status != 200:
            failure_status = HTTP_FAILURE_STATUS.get(response.status, "FAILED")
            reason = f"HTTP_STATUS_{response.status}"
            key = self._key("FAILURE", source_registry_snapshot_id, entity_registry_snapshot_id,
                            observed, retrieved, reason)
            persisted = self.store.capture_acquisition_failure(
                idempotency_key=key,
                source_registry_snapshot_id=source_registry_snapshot_id,
                entity_registry_snapshot_id=entity_registry_snapshot_id,
                source_id=SEBI_SOURCE_ID,
                source_reference=SEBI_RSS_URL,
                retrieval_status=failure_status,
                failure_reason=reason,
                failure_stage="HTTP_STATUS",
                attempted_at_utc=observed,
                entity_ids=[SEBI_ENTITY_ID],
            )
            return {"outcome": "ACQUISITION_ATTEMPT", "reason": reason, **persisted}
        metadata = _feed_metadata(
            response.body, response.headers.get("content-type", ""), observed, truncated=response.truncated)
        retrieval_status = "RETRIEVED" if metadata["valid"] else "QUARANTINED"
        payload_hash = sha256_bytes(response.body)
        key = self._key("EVIDENCE", source_registry_snapshot_id, entity_registry_snapshot_id,
                        observed, retrieved, payload_hash)
        persisted = self.store.capture_evidence(
            idempotency_key=key,
            source_registry_snapshot_id=source_registry_snapshot_id,
            entity_registry_snapshot_id=entity_registry_snapshot_id,
            source_id=SEBI_SOURCE_ID,
            source_reference=SEBI_RSS_URL,
            raw_payload=response.body,
            content_type=response.headers.get("content-type", "application/octet-stream"),
            publication_timestamp_utc=metadata["publication"],
            observed_timestamp_utc=observed,
            retrieved_timestamp_utc=retrieved,
            entity_ids=[SEBI_ENTITY_ID],
            retrieval_status=retrieval_status,
            raw_title=metadata["title"],
            language=None,
            document_version=None,
            event_candidate_ids=[],
        )
        return {"outcome": retrieval_status, "reason": metadata["reason"], **persisted}


__all__ = ["SEBI_SOURCE_ID", "SebiRssConnector", "TransportResponse"]
