"""Controlled Stage 6.8B capture of the two frozen official RSS sources."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from stage6_connectors import RbiRssConnector, SebiRssConnector
from stage6_connectors.live_registries import build_multisource_registries
from stage6_connectors.policy import RBI_ENDPOINT, SEBI_ENDPOINT
from stage6_ingestion import IngestionStore
from stage6_ingestion.canonical import canonical_hash, canonical_json, without

from .activation import verify_activation_record
from .errors import ProspectiveConflict, ProspectiveIntegrityFailure, Stage6ProspectiveError
from .operations_config import ADDITIONAL_SOURCE_STATUS, AUTHORITY, PRIMARY_CAPTURE_SCHEMA
from .source_coverage import attest_sources


SUMMARY_STORE_SCHEMA = "STAGE6_8B_CAPTURE_SUMMARY_STORE_V1"


def _now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _runtime_allowed(root, allow_fixture_runtime=False):
    root = Path(root).resolve()
    if allow_fixture_runtime:
        return root
    approved = Path(__file__).resolve().parents[2] / "Stage 6" / "runtime"
    try:
        root.relative_to(approved.resolve())
    except ValueError as exc:
        raise Stage6ProspectiveError("LIVE_RUNTIME_ROOT_NOT_APPROVED") from exc
    lowered = {part.casefold() for part in root.parts}
    if "fixtures" in lowered or "tests" in lowered:
        raise Stage6ProspectiveError("LIVE_FIXTURE_RUNTIME_PROHIBITED")
    return root


class CaptureSummaryStore:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        new = not self.database.exists()
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        if new:
            self.connection.executescript("""
CREATE TABLE capture_summary_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),schema_version TEXT NOT NULL,authority TEXT NOT NULL);
CREATE TABLE capture_summaries(capture_run_id TEXT PRIMARY KEY,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TRIGGER protect_capture_summary_meta_update BEFORE UPDATE ON capture_summary_meta BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;
CREATE TRIGGER protect_capture_summary_meta_delete BEFORE DELETE ON capture_summary_meta BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;
CREATE TRIGGER protect_capture_summaries_update BEFORE UPDATE ON capture_summaries BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;
CREATE TRIGGER protect_capture_summaries_delete BEFORE DELETE ON capture_summaries BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;
""")
            self.connection.execute("INSERT INTO capture_summary_meta VALUES(1,?,?)", (SUMMARY_STORE_SCHEMA, AUTHORITY))
            self.connection.commit()
        self.integrity_check()

    def close(self):
        self.connection.close()

    def persist(self, record):
        existing = self.connection.execute("SELECT canonical_json FROM capture_summaries WHERE capture_run_id=?", (record["capture_run_id"],)).fetchone()
        text = canonical_json(record)
        if existing:
            if existing[0] == text:
                return "IDEMPOTENT_SUCCESS"
            raise ProspectiveConflict("CAPTURE_SUMMARY_CONFLICT")
        with self.connection:
            self.connection.execute("INSERT INTO capture_summaries VALUES(?,?,?)", (record["capture_run_id"], record["record_hash"], text))
        return "CREATED"

    def integrity_check(self):
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_SQLITE_INVALID")
        meta = self.connection.execute("SELECT * FROM capture_summary_meta").fetchall()
        if len(meta) != 1 or tuple(meta[0]) != (1, SUMMARY_STORE_SCHEMA, AUTHORITY):
            raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_METADATA_INVALID")
        expected = {"protect_capture_summary_meta_update", "protect_capture_summary_meta_delete",
                    "protect_capture_summaries_update", "protect_capture_summaries_delete"}
        actual = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if actual != expected:
            raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_TRIGGER_INVALID")
        for row in self.connection.execute("SELECT * FROM capture_summaries"):
            value = json.loads(row["canonical_json"])
            if canonical_json(value) != row["canonical_json"] or value["capture_run_id"] != row["capture_run_id"] or value["record_hash"] != row["record_hash"] or value["record_hash"] != canonical_hash(without(value, "record_hash")):
                raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_RECORD_INVALID")
        return {"result": "PASS", "summaries": self.connection.execute("SELECT count(*) FROM capture_summaries").fetchone()[0]}


def capture_primary_evidence(*, activation_record, runtime_root, live=False,
                             _fixture_transports=None, _allow_fixture_runtime=False):
    if not live:
        return {"status": "LIVE_FLAG_REQUIRED", "network_request_count": 0, "authority": AUTHORITY,
                "trading_authority": False}
    if _fixture_transports is not None and not _allow_fixture_runtime:
        raise Stage6ProspectiveError("FIXTURE_TRANSPORT_PROHIBITED_IN_LIVE_MODE")
    activation = verify_activation_record(activation_record)
    coverage = attest_sources(activation_record)
    root = _runtime_allowed(runtime_root, _allow_fixture_runtime)
    root.mkdir(parents=True, exist_ok=True)
    observed_start = _now_utc()
    registries = build_multisource_registries()
    database = root / "stage6_primary_evidence.sqlite3"
    raw_root = root / "stage6_primary_raw"
    transports = _fixture_transports or {}
    with IngestionStore(database, raw_root) as store:
        for key in ("entity_v1", "source_v1", "entity_v2", "source_v2"):
            store.import_registry(registries[key])
        connectors = (
            ("SEBI_OFFICIAL_RSS", SEBI_ENDPOINT, SebiRssConnector(store, transports.get("SEBI_OFFICIAL_RSS"))),
            ("RBI_OFFICIAL_PRESS_RELEASES_RSS", RBI_ENDPOINT, RbiRssConnector(store, transports.get("RBI_OFFICIAL_PRESS_RELEASES_RSS"))),
        )
        results = []
        contacted_hosts = []
        request_count = 0
        for source_id, endpoint, connector in connectors:
            result = connector.acquire(
                source_registry_snapshot_id=registries["source_v2"]["registry_snapshot_id"],
                entity_registry_snapshot_id=registries["entity_v2"]["registry_snapshot_id"],
                observed_timestamp_utc=observed_start,
            )
            record = result["record"]
            results.append({"source_id": source_id, "retrieval_status": record["retrieval_status"],
                            "record_id": record["evidence_id"], "record_hash": record["record_hash"],
                            "record_kind": record["record_kind"]})
            contacted_hosts.append(endpoint.host)
            request_count += int(getattr(connector.transport, "request_count", 0))
        integrity = store.integrity_check()
    completed = _now_utc()
    record = {
        "schema_version": PRIMARY_CAPTURE_SCHEMA, "capture_run_id": "",
        "activation_binding": {"record_type": activation["schema_version"], "record_id": activation["activation_id"], "record_hash": activation["record_hash"]},
        "observed_start_utc": observed_start, "completed_utc": completed,
        "entity_registry_v2_binding": {"record_id": registries["entity_v2"]["registry_snapshot_id"], "record_hash": registries["entity_v2"]["registry_hash"]},
        "source_registry_v2_binding": {"record_id": registries["source_v2"]["registry_snapshot_id"], "record_hash": registries["source_v2"]["registry_hash"]},
        "source_results": results, "source_coverage_count": coverage["operational_primary_count"],
        "coverage_gaps": [ADDITIONAL_SOURCE_STATUS], "source_invocation_count": 2,
        "network_request_count": request_count, "contacted_hosts": contacted_hosts,
        "ingestion_integrity": integrity["result"], "authority": AUTHORITY,
        "trading_authority": False, "broker_calls": 0, "stage5d_mutation_status": "PROHIBITED",
        "record_hash": "",
    }
    record["capture_run_id"] = "S6PROSCAP_" + canonical_hash(without(record, "capture_run_id", "record_hash"))[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    summaries = CaptureSummaryStore(root / "stage6_primary_capture_summaries.sqlite3")
    try:
        persistence = summaries.persist(record)
        summary_integrity = summaries.integrity_check()
    finally:
        summaries.close()
    return {"status": persistence, "summary": record, "ingestion_integrity": integrity,
            "summary_integrity": summary_integrity}
