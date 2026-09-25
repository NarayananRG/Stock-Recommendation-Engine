"""Offline-only Stage 6.1A fixture demonstration. No connector or network code."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .evidence_store import IngestionStore
from .fixtures import build_fixture_registries


def run_demo(root: Path | None = None) -> dict:
    registries = build_fixture_registries()
    temporary = None
    if root is None:
        temporary = tempfile.TemporaryDirectory(prefix="stage6_1a_demo_")
        root = Path(temporary.name)
    try:
        with IngestionStore(root / "stage6_ingestion.sqlite3", root / "raw") as store:
            for name in ("entity_v1", "source_v1", "entity_v2", "source_v2"):
                store.import_registry(registries[name])
            evidence = store.capture_evidence(
                idempotency_key="fixture-demo-evidence",
                source_registry_snapshot_id=registries["source_v1"]["registry_snapshot_id"],
                entity_registry_snapshot_id=registries["entity_v1"]["registry_snapshot_id"],
                source_id="S6FIX_SOURCE_OFFICIAL_001",
                source_reference="fixture://synthetic/item-1",
                raw_payload=b"Synthetic fixture payload only.",
                content_type="text/plain",
                publication_timestamp_utc="2026-05-01T09:00:00Z",
                observed_timestamp_utc="2026-05-01T09:01:00Z",
                retrieved_timestamp_utc="2026-05-01T09:02:00Z",
                entity_ids=["S6FIX_COMPANY_001"],
            )
            failure = store.capture_acquisition_failure(
                idempotency_key="fixture-demo-failure",
                source_registry_snapshot_id=registries["source_v2"]["registry_snapshot_id"],
                entity_registry_snapshot_id=registries["entity_v2"]["registry_snapshot_id"],
                source_id="S6FIX_SOURCE_OFFICIAL_001",
                source_reference="fixture://synthetic/missing",
                retrieval_status="NOT_FOUND",
                failure_reason="Synthetic fixture item is absent",
                failure_stage="FIXTURE_LOOKUP",
                attempted_at_utc="2026-08-03T09:00:00Z",
            )
            result = store.integrity_check()
            result.update({
                "fixture_only": True,
                "network_calls": False,
                "evidence_id": evidence["record"]["evidence_id"],
                "acquisition_attempt_id": failure["record"]["evidence_id"],
            })
            return result
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    print(json.dumps(run_demo(), sort_keys=True, separators=(",", ":")))
