"""Shared acquisition flow for the two immutable official RSS definitions."""
from __future__ import annotations

from stage6_ingestion.canonical import canonical_hash, parse_utc, sha256_bytes, utc_timestamp
from stage6_ingestion.errors import IntegrityFailure
from stage6_ingestion.registry import assert_source_approved_for_automated_ingestion, resolve_entity, resolve_source_record

from .policy import endpoint_for_source
from .rss_common import feed_metadata
from .transport import ControlledHttpsTransport, TransportFailure


HTTP_FAILURE_STATUS = {401: "ACCESS_DENIED", 403: "ACCESS_DENIED", 404: "NOT_FOUND"}
APPROVED_ENTITY_BINDINGS = {
    "SEBI_OFFICIAL_RSS": "SEBI_REGULATOR_IN",
    "RBI_OFFICIAL_PRESS_RELEASES_RSS": "RBI_REGULATOR_IN",
}
IDEMPOTENCY_PREFIXES = {
    "SEBI_OFFICIAL_RSS": "S6_1B_SEBI_",
    "RBI_OFFICIAL_PRESS_RELEASES_RSS": "S6_1C_RBI_",
}


class OfficialRssConnector:
    def __init__(self, store, source_id: str, transport=None):
        if source_id not in APPROVED_ENTITY_BINDINGS:
            raise ValueError("SOURCE_CONNECTOR_NOT_APPROVED")
        self.store = store
        self.source_id = source_id
        self.entity_id = APPROVED_ENTITY_BINDINGS[source_id]
        self.endpoint = endpoint_for_source(source_id)
        self.transport = transport or ControlledHttpsTransport(endpoint=self.endpoint)

    def _approve_before_network(self, source_snapshot_id: str, entity_snapshot_id: str, cutoff: str) -> None:
        source_registry = self.store._verify_persisted_registry_chain("SOURCE", source_snapshot_id)
        entity_registry = self.store._verify_persisted_registry_chain("ENTITY", entity_snapshot_id)
        cutoff_value = parse_utc(cutoff, "acquisition_cutoff")
        if (parse_utc(source_registry["as_of_timestamp"], "source_registry.as_of_timestamp") > cutoff_value
                or parse_utc(entity_registry["as_of_timestamp"], "entity_registry.as_of_timestamp") > cutoff_value):
            raise IntegrityFailure("REGISTRY_SNAPSHOT_FROM_FUTURE")
        source = resolve_source_record(source_registry, self.source_id, cutoff, require_usable=False)
        assert_source_approved_for_automated_ingestion(source)
        resolve_entity(entity_registry, self.entity_id, cutoff)

    def _key(self, kind: str, source_snapshot_id: str, entity_snapshot_id: str,
             observed: str, retrieved: str, discriminator: str) -> str:
        return IDEMPOTENCY_PREFIXES[self.source_id] + canonical_hash({
            "kind": kind, "source_registry_snapshot_id": source_snapshot_id,
            "entity_registry_snapshot_id": entity_snapshot_id, "source_id": self.source_id,
            "observed_timestamp_utc": observed, "retrieved_timestamp_utc": retrieved,
            "discriminator": discriminator,
        })[:32]

    def acquire(self, *, source_registry_snapshot_id: str, entity_registry_snapshot_id: str,
                observed_timestamp_utc: str) -> dict:
        observed = utc_timestamp(observed_timestamp_utc, "observed_timestamp_utc")
        self._approve_before_network(source_registry_snapshot_id, entity_registry_snapshot_id, observed)
        try:
            response = self.transport.fetch()
        except TransportFailure as exc:
            key = self._key("FAILURE", source_registry_snapshot_id, entity_registry_snapshot_id,
                            observed, observed, exc.code)
            persisted = self.store.capture_acquisition_failure(
                idempotency_key=key, source_registry_snapshot_id=source_registry_snapshot_id,
                entity_registry_snapshot_id=entity_registry_snapshot_id, source_id=self.source_id,
                source_reference=self.endpoint.url, retrieval_status="FAILED", failure_reason=exc.code,
                failure_stage="HTTP_TRANSPORT", attempted_at_utc=observed, entity_ids=[self.entity_id])
            return {"outcome": "ACQUISITION_ATTEMPT", "reason": exc.code, **persisted}
        retrieved = utc_timestamp(response.retrieved_timestamp_utc, "retrieved_timestamp_utc")
        if response.status != 200:
            failure_status = HTTP_FAILURE_STATUS.get(response.status, "FAILED")
            reason = f"HTTP_STATUS_{response.status}"
            key = self._key("FAILURE", source_registry_snapshot_id, entity_registry_snapshot_id,
                            observed, retrieved, reason)
            persisted = self.store.capture_acquisition_failure(
                idempotency_key=key, source_registry_snapshot_id=source_registry_snapshot_id,
                entity_registry_snapshot_id=entity_registry_snapshot_id, source_id=self.source_id,
                source_reference=self.endpoint.url, retrieval_status=failure_status, failure_reason=reason,
                failure_stage="HTTP_STATUS", attempted_at_utc=observed, entity_ids=[self.entity_id])
            return {"outcome": "ACQUISITION_ATTEMPT", "reason": reason, **persisted}
        metadata = feed_metadata(response.body, response.headers.get("content-type", ""),
                                 observed, truncated=response.truncated)
        retrieval_status = "RETRIEVED" if metadata["valid"] else "QUARANTINED"
        payload_hash = sha256_bytes(response.body)
        key = self._key("EVIDENCE", source_registry_snapshot_id, entity_registry_snapshot_id,
                        observed, retrieved, payload_hash)
        persisted = self.store.capture_evidence(
            idempotency_key=key, source_registry_snapshot_id=source_registry_snapshot_id,
            entity_registry_snapshot_id=entity_registry_snapshot_id, source_id=self.source_id,
            source_reference=self.endpoint.url, raw_payload=response.body,
            content_type=response.headers.get("content-type", "application/octet-stream"),
            publication_timestamp_utc=metadata["publication"], observed_timestamp_utc=observed,
            retrieved_timestamp_utc=retrieved, entity_ids=[self.entity_id], retrieval_status=retrieval_status,
            raw_title=metadata["title"], language=None, document_version=None, event_candidate_ids=[])
        return {"outcome": retrieval_status, "reason": metadata["reason"], **persisted}
