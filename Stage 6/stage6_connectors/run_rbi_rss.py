"""Explicit opt-in live RBI Press Releases RSS smoke runner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from stage6_ingestion.evidence_store import IngestionStore

from .live_registries import RBI_SOURCE_ID, build_multisource_registries
from .policy import RBI_ENDPOINT
from .rbi_rss import RbiRssConnector
from .transport import ControlledHttpsTransport, utc_now


def run_live(runtime_root: Path) -> dict:
    registries = build_multisource_registries()
    database = runtime_root / "stage6_1c.sqlite3"
    raw_root = runtime_root / "raw"
    transport = ControlledHttpsTransport(endpoint=RBI_ENDPOINT)
    with IngestionStore(database, raw_root) as store:
        for version in ("v1", "v2"):
            store.import_registry(registries[f"entity_{version}"])
            store.import_registry(registries[f"source_{version}"])
        result = RbiRssConnector(store, transport).acquire(
            source_registry_snapshot_id=registries["source_v2"]["registry_snapshot_id"],
            entity_registry_snapshot_id=registries["entity_v2"]["registry_snapshot_id"],
            observed_timestamp_utc=utc_now(),
        )
        record = result["record"]
    with IngestionStore(database, raw_root) as reopened:
        integrity = reopened.integrity_check()
    network_failure = result.get("reason") in {"TIMEOUT", "DNS_FAILURE", "TLS_FAILURE", "NETWORK_FAILURE"}
    return {
        "stage": "6.1C",
        "authority": "SHADOW_ONLY",
        "live_smoke_test_status": "NOT_RUN_NETWORK_UNAVAILABLE" if network_failure else (
            "PASS" if result["outcome"] == "RETRIEVED" else "FAIL"),
        "requested_url": RBI_ENDPOINT.url,
        "final_url": transport.final_url,
        "redirects": transport.redirect_history,
        "network_requests": transport.request_count,
        "network_hosts_contacted": [RBI_ENDPOINT.host] if transport.request_count else [],
        "source_id": RBI_SOURCE_ID,
        "record_id": record["evidence_id"],
        "record_kind": record["record_kind"],
        "retrieval_status": record["retrieval_status"],
        "connector_reason": result.get("reason"),
        "raw_payload_hash": record["raw_payload_hash"],
        "source_registry_snapshot_id": record["source_registry_snapshot_id"],
        "source_registry_version": record["source_registry_version"],
        "entity_registry_snapshot_id": record["entity_registry_snapshot_id"],
        "entity_registry_version": record["entity_registry_version"],
        "source_record_version": record["source_record_version"],
        "full_store_integrity": integrity["result"],
        "trading_decisions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled one-shot RBI Press Releases RSS live smoke")
    parser.add_argument("--live", action="store_true", help="explicitly permit the fixed RBI HTTPS request")
    parser.add_argument("--runtime-root", type=Path,
                        default=Path(__file__).resolve().parents[1] / "runtime" / "stage6_1c_rbi")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; the connector never runs implicitly")
    result = run_live(args.runtime_root)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if (result["full_store_integrity"] == "PASS"
                 and result["live_smoke_test_status"] == "PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
