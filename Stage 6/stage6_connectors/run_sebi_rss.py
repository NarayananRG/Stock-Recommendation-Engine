"""Explicit opt-in live SEBI RSS smoke runner. No action occurs on import."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from stage6_ingestion.evidence_store import IngestionStore

from .live_registries import SEBI_SOURCE_ID, build_live_registries
from .sebi_rss import SebiRssConnector
from .transport import ControlledHttpsTransport, utc_now


def run_live(runtime_root: Path) -> dict:
    registries = build_live_registries()
    database = runtime_root / "stage6_1b.sqlite3"
    raw_root = runtime_root / "raw"
    transport = ControlledHttpsTransport()
    with IngestionStore(database, raw_root) as store:
        store.import_registry(registries["entity_v1"])
        store.import_registry(registries["source_v1"])
        result = SebiRssConnector(store, transport).acquire(
            source_registry_snapshot_id=registries["source_v1"]["registry_snapshot_id"],
            entity_registry_snapshot_id=registries["entity_v1"]["registry_snapshot_id"],
            observed_timestamp_utc=utc_now(),
        )
        record = result["record"]
    with IngestionStore(database, raw_root) as reopened:
        integrity = reopened.integrity_check()
    network_failure = result.get("reason") in {"TIMEOUT", "DNS_FAILURE", "TLS_FAILURE", "NETWORK_FAILURE"}
    return {
        "stage": "6.1B",
        "authority": "SHADOW_ONLY",
        "live_smoke_test_status": "NOT_RUN_NETWORK_UNAVAILABLE" if network_failure else (
            "PASS" if result["outcome"] == "RETRIEVED" else "FAIL"),
        "network_requests": transport.request_count,
        "network_hosts_contacted": ["www.sebi.gov.in"] if transport.request_count else [],
        "source_id": SEBI_SOURCE_ID,
        "record_id": record["evidence_id"],
        "record_kind": record["record_kind"],
        "retrieval_status": record["retrieval_status"],
        "connector_reason": result.get("reason"),
        "raw_payload_hash": record["raw_payload_hash"],
        "source_registry_snapshot_id": record["source_registry_snapshot_id"],
        "entity_registry_snapshot_id": record["entity_registry_snapshot_id"],
        "full_store_integrity": integrity["result"],
        "trading_decisions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled one-shot SEBI RSS live smoke")
    parser.add_argument("--live", action="store_true", help="explicitly permit the fixed SEBI HTTPS request")
    parser.add_argument("--runtime-root", type=Path, default=Path(__file__).resolve().parents[1] / "runtime" / "stage6_1b")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; the connector never runs implicitly")
    result = run_live(args.runtime_root)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if (result["full_store_integrity"] == "PASS"
                 and result["live_smoke_test_status"] == "PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
