"""Controlled Stage 6.8B capture of the two frozen official RSS sources."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from stage6_connectors import RbiRssConnector, SebiRssConnector
from stage6_connectors.live_registries import build_multisource_registries
from stage6_connectors.policy import RBI_ENDPOINT, SEBI_ENDPOINT
from stage6_ingestion import IngestionStore
from stage6_ingestion.canonical import canonical_hash, canonical_json, without

from .activation import verify_activation_record
from .errors import ProspectiveConflict, ProspectiveIntegrityFailure, Stage6ProspectiveError
from .operations_config import (
    ADDITIONAL_SOURCE_STATUS,
    AUTHORITY,
    CAPTURE_SUMMARY_STORE_SCHEMA,
    ENTITY_REGISTRY_V2_HASH,
    ENTITY_REGISTRY_V2_ID,
    PRIMARY_CAPTURE_SCHEMA,
    SOURCE_REGISTRY_V2_HASH,
    SOURCE_REGISTRY_V2_ID,
)
from .session_calendar import IST, pre_session_deadline_utc
from .source_coverage import attest_sources


USABLE_RETRIEVAL_STATUSES = frozenset({"RETRIEVED", "PARTIAL"})
EXPECTED_SUMMARY_TRIGGERS = frozenset({
    "protect_capture_summary_meta_update",
    "protect_capture_summary_meta_delete",
    "protect_capture_summaries_update",
    "protect_capture_summaries_delete",
})


def _clock_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_text(value):
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value, error="CAPTURE_TIMESTAMP_INVALID"):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone")
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProspectiveIntegrityFailure(error) from exc


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


def _aggregate_capture_cycle_status(source_results):
    usable = sum(item.get("retrieval_status") in USABLE_RETRIEVAL_STATUSES for item in source_results)
    return ("AVAILABLE" if usable == 2 else "PARTIAL" if usable == 1 else "FAILED"), usable


def _validate_capture_target(activation, target_session_date, now_utc):
    if not isinstance(target_session_date, str) or not target_session_date:
        raise Stage6ProspectiveError("TARGET_SESSION_DATE_REQUIRED")
    try:
        target_date = date.fromisoformat(target_session_date)
        activation_date = date.fromisoformat(activation["activation_date_ist"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Stage6ProspectiveError("TARGET_SESSION_DATE_INVALID") from exc
    if target_date.isoformat() != target_session_date:
        raise Stage6ProspectiveError("TARGET_SESSION_DATE_INVALID")
    if target_date <= activation_date:
        raise Stage6ProspectiveError("TARGET_SESSION_NOT_AFTER_ACTIVATION")
    deadline, proof = pre_session_deadline_utc(target_session_date)
    if now_utc.astimezone(IST).date() != target_date:
        raise Stage6ProspectiveError("CAPTURE_TARGET_LOCAL_DATE_MISMATCH")
    if now_utc >= deadline:
        raise Stage6ProspectiveError("CAPTURE_DEADLINE_PASSED")
    return deadline, proof


def _validate_summary_record(record, row=None):
    if not isinstance(record, dict):
        raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_RECORD_INVALID")
    expected_capture_id = "S6PROSCAP_" + canonical_hash(
        without(record, "capture_run_id", "record_hash")
    )[:24]
    required = (
        record.get("schema_version") == PRIMARY_CAPTURE_SCHEMA,
        record.get("authority") == AUTHORITY,
        record.get("trading_authority") is False,
        record.get("record_hash") == canonical_hash(without(record, "record_hash")),
        isinstance(record.get("capture_run_id"), str),
        record.get("capture_run_id") == expected_capture_id,
    )
    if not all(required):
        raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_RECORD_INVALID")
    if row is not None and (
        record["capture_run_id"] != row["capture_run_id"]
        or record["record_hash"] != row["record_hash"]
        or canonical_json(record) != row["canonical_json"]
    ):
        raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_RECORD_INVALID")
    return record


def _verify_summary_connection(connection, require_query_only=True):
    connection.row_factory = sqlite3.Row
    if require_query_only:
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_QUERY_ONLY_REQUIRED")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_SQLITE_INVALID")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_FOREIGN_KEY_INVALID")
    meta = connection.execute("SELECT * FROM capture_summary_meta").fetchall()
    if len(meta) != 1 or tuple(meta[0]) != (1, CAPTURE_SUMMARY_STORE_SCHEMA, AUTHORITY, 0):
        raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_METADATA_INVALID")
    actual = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    if actual != EXPECTED_SUMMARY_TRIGGERS:
        raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_TRIGGER_INVALID")
    count = 0
    for row in connection.execute("SELECT * FROM capture_summaries"):
        try:
            record = json.loads(row["canonical_json"])
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_CANONICAL_JSON_INVALID") from exc
        _validate_summary_record(record, row)
        count += 1
    return count


class CaptureSummaryStore:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        new = not self.database.exists()
        self.connection = sqlite3.connect(self.database)
        self.connection.row_factory = sqlite3.Row
        if new:
            self.connection.executescript("""
CREATE TABLE capture_summary_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),schema_version TEXT NOT NULL,authority TEXT NOT NULL,trading_authority INTEGER NOT NULL CHECK(trading_authority=0));
CREATE TABLE capture_summaries(capture_run_id TEXT PRIMARY KEY,record_hash TEXT UNIQUE NOT NULL,canonical_json TEXT NOT NULL);
CREATE TRIGGER protect_capture_summary_meta_update BEFORE UPDATE ON capture_summary_meta BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;
CREATE TRIGGER protect_capture_summary_meta_delete BEFORE DELETE ON capture_summary_meta BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;
CREATE TRIGGER protect_capture_summaries_update BEFORE UPDATE ON capture_summaries BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;
CREATE TRIGGER protect_capture_summaries_delete BEFORE DELETE ON capture_summaries BEGIN SELECT RAISE(ABORT,'IMMUTABLE');END;
""")
            self.connection.execute(
                "INSERT INTO capture_summary_meta VALUES(1,?,?,0)",
                (CAPTURE_SUMMARY_STORE_SCHEMA, AUTHORITY),
            )
            self.connection.commit()
        self.integrity_check()

    def close(self):
        self.connection.close()

    def persist(self, record):
        _validate_summary_record(record)
        existing = self.connection.execute(
            "SELECT canonical_json FROM capture_summaries WHERE capture_run_id=?",
            (record["capture_run_id"],),
        ).fetchone()
        text = canonical_json(record)
        if existing:
            if existing[0] == text:
                return "IDEMPOTENT_SUCCESS"
            raise ProspectiveConflict("CAPTURE_SUMMARY_CONFLICT")
        with self.connection:
            self.connection.execute(
                "INSERT INTO capture_summaries VALUES(?,?,?)",
                (record["capture_run_id"], record["record_hash"], text),
            )
        return "CREATED"

    def integrity_check(self):
        count = _verify_summary_connection(self.connection, require_query_only=False)
        return {"result": "PASS", "summaries": count}


def verify_capture_summary_store(database, capture_run_id):
    """Read and verify one exact capture summary without mutating the store."""
    if not isinstance(capture_run_id, str) or not capture_run_id:
        raise Stage6ProspectiveError("EXACT_CAPTURE_RUN_ID_REQUIRED")
    path = Path(database) if database is not None else None
    if path is None or not path.is_file():
        raise Stage6ProspectiveError("CAPTURE_SUMMARY_DATABASE_REQUIRED")
    connection = None
    try:
        connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        count = _verify_summary_connection(connection)
        row = connection.execute(
            "SELECT * FROM capture_summaries WHERE capture_run_id=?", (capture_run_id,)
        ).fetchone()
        if row is None:
            raise Stage6ProspectiveError("CAPTURE_RUN_ID_NOT_FOUND")
        record = _validate_summary_record(json.loads(row["canonical_json"]), row)
        return record, {"result": "PASS", "summaries": count, "query_only": True}
    except (sqlite3.Error, json.JSONDecodeError, KeyError, TypeError) as exc:
        if isinstance(exc, (ProspectiveIntegrityFailure, Stage6ProspectiveError)):
            raise
        raise ProspectiveIntegrityFailure("CAPTURE_SUMMARY_STORE_INVALID") from exc
    finally:
        if connection is not None:
            connection.close()


def capture_primary_evidence(*, activation_record, runtime_root, target_session_date=None,
                             live=False, _fixture_transports=None,
                             _allow_fixture_runtime=False):
    if not isinstance(target_session_date, str) or not target_session_date:
        raise Stage6ProspectiveError("TARGET_SESSION_DATE_REQUIRED")
    if not live:
        return {
            "status": "LIVE_FLAG_REQUIRED", "network_request_count": 0,
            "target_session_date": target_session_date, "authority": AUTHORITY,
            "trading_authority": False,
        }
    if _fixture_transports is not None and not _allow_fixture_runtime:
        raise Stage6ProspectiveError("FIXTURE_TRANSPORT_PROHIBITED_IN_LIVE_MODE")

    activation = verify_activation_record(activation_record)
    observed_start_dt = _clock_utc()
    deadline, calendar_proof = _validate_capture_target(
        activation, target_session_date, observed_start_dt
    )
    coverage = attest_sources(activation_record)
    root = _runtime_allowed(runtime_root, _allow_fixture_runtime)
    root.mkdir(parents=True, exist_ok=True)
    observed_start = _utc_text(observed_start_dt)
    registries = build_multisource_registries()
    if (
        registries["source_v2"]["registry_snapshot_id"] != SOURCE_REGISTRY_V2_ID
        or registries["source_v2"]["registry_hash"] != SOURCE_REGISTRY_V2_HASH
        or registries["entity_v2"]["registry_snapshot_id"] != ENTITY_REGISTRY_V2_ID
        or registries["entity_v2"]["registry_hash"] != ENTITY_REGISTRY_V2_HASH
    ):
        raise ProspectiveIntegrityFailure("CAPTURE_REGISTRY_V2_BINDING_INVALID")

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
            evidence = result["record"]
            results.append({
                "source_id": source_id,
                "retrieval_status": evidence["retrieval_status"],
                "record_id": evidence["evidence_id"],
                "record_hash": evidence["record_hash"],
                "record_kind": evidence["record_kind"],
            })
            contacted_hosts.append(endpoint.host)
            request_count += int(getattr(connector.transport, "request_count", 0))
        integrity = store.integrity_check()

    completed_dt = _clock_utc()
    completed = _utc_text(completed_dt)
    capture_status, usable_count = _aggregate_capture_cycle_status(results)
    same_target_morning = (
        observed_start_dt.astimezone(IST).date().isoformat() == target_session_date
        and completed_dt.astimezone(IST).date().isoformat() == target_session_date
        and observed_start_dt <= completed_dt
        and observed_start_dt < deadline
        and completed_dt < deadline
    )
    eligibility = "ELIGIBLE" if same_target_morning else "LATE_NOT_ELIGIBLE"
    record = {
        "schema_version": PRIMARY_CAPTURE_SCHEMA,
        "capture_run_id": "",
        "target_session_date": target_session_date,
        "target_session_calendar_proof": calendar_proof,
        "pre_session_deadline_utc": _utc_text(deadline),
        "prospective_cycle_eligibility": eligibility,
        "activation_binding": {
            "record_type": activation["schema_version"],
            "record_id": activation["activation_id"],
            "record_hash": activation["record_hash"],
        },
        "observed_start_utc": observed_start,
        "completed_utc": completed,
        "entity_registry_v2_binding": {
            "record_id": ENTITY_REGISTRY_V2_ID, "record_hash": ENTITY_REGISTRY_V2_HASH,
        },
        "source_registry_v2_binding": {
            "record_id": SOURCE_REGISTRY_V2_ID, "record_hash": SOURCE_REGISTRY_V2_HASH,
        },
        "source_results": results,
        "source_coverage_count": coverage["operational_primary_count"],
        "usable_source_count": usable_count,
        "capture_cycle_status": capture_status,
        "coverage_gaps": [ADDITIONAL_SOURCE_STATUS],
        "source_invocation_count": 2,
        "network_request_count": request_count,
        "contacted_hosts": contacted_hosts,
        "ingestion_integrity": integrity["result"],
        "authority": AUTHORITY,
        "trading_authority": False,
        "broker_calls": 0,
        "stage5d_mutation_status": "PROHIBITED",
        "record_hash": "",
    }
    record["capture_run_id"] = "S6PROSCAP_" + canonical_hash(
        without(record, "capture_run_id", "record_hash")
    )[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    summaries = CaptureSummaryStore(root / "stage6_primary_capture_summaries.sqlite3")
    try:
        persistence = summaries.persist(record)
        summary_integrity = summaries.integrity_check()
    finally:
        summaries.close()
    return {
        "status": persistence,
        "summary": record,
        "ingestion_integrity": integrity,
        "summary_integrity": summary_integrity,
    }
