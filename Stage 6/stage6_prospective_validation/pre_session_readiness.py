"""Read-only readiness checks before the frozen Stage 6.7 morning pipeline."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash, canonical_json, without

from .activation import verify_activation_record
from .control_reader import Stage5DControlReader
from .enrollment_validation import validate_control_case
from .errors import ProspectiveIntegrityFailure, Stage6ProspectiveError
from .operations_config import AUTHORITY, READINESS_SCHEMA
from .prospective_store import ProspectiveValidationStore
from .session_calendar import pre_session_deadline_utc
from .source_coverage import attest_sources


def _now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _capture_cycle_status(database=None, capture_run_id=None):
    if database is None or capture_run_id is None:
        return "NOT_CAPTURED"
    path = Path(database)
    if not path.is_file():
        return "NOT_CAPTURED"
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT canonical_json FROM capture_summaries WHERE capture_run_id=?", (capture_run_id,)).fetchone()
        if row is None:
            return "NOT_CAPTURED"
        record = json.loads(row[0])
        if canonical_json(record) != row[0] or record.get("capture_run_id") != capture_run_id or record.get("record_hash") != canonical_hash(without(record, "record_hash")):
            raise ProspectiveIntegrityFailure("CAPTURE_READINESS_STATUS_INVALID")
        results = record["source_results"]
        success = sum(item["retrieval_status"] in {"RETRIEVED", "PARTIAL", "QUARANTINED"} for item in results)
        return "AVAILABLE" if success == 2 else "PARTIAL" if success == 1 else "FAILED"
    except (sqlite3.Error, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProspectiveIntegrityFailure("CAPTURE_READINESS_STATUS_INVALID") from exc
    finally:
        connection.close()


def pre_session_check(*, activation_record, prospective_database, control_database,
                      recommendation_id, target_session_date,
                      capture_summary_database=None, capture_run_id=None):
    coverage = None
    try:
        if not isinstance(recommendation_id, str) or not recommendation_id:
            raise Stage6ProspectiveError("CONTROL_RECOMMENDATION_ID_REQUIRED")
        if not isinstance(target_session_date, str) or not target_session_date:
            raise Stage6ProspectiveError("TARGET_SESSION_DATE_REQUIRED")
        activation = verify_activation_record(activation_record)
        coverage = attest_sources(activation_record)
        path = Path(prospective_database)
        if not path.is_file():
            raise Stage6ProspectiveError("PROSPECTIVE_DATABASE_REQUIRED")
        store = ProspectiveValidationStore(path, activation_record)
        try:
            store.connection.execute("PRAGMA query_only=ON")
            if store.integrity_check()["result"] != "PASS":
                raise ProspectiveIntegrityFailure("PROSPECTIVE_INTEGRITY_FAILURE")
            with Stage5DControlReader(control_database) as control:
                recommendation = control.get_recommendation(recommendation_id)
                pending = control.get_pending_event(recommendation_id)
                origin_run = control.get_origin_run(recommendation["allocation_run_id"])
                origin_row = store.connection.execute("SELECT canonical_json FROM prospective_sessions WHERE run_id=?", (origin_run["run_id"],)).fetchone()
                if origin_row is None:
                    raise Stage6ProspectiveError("CONTROL_ORIGIN_SESSION_NOT_ENROLLED")
                origin_session = json.loads(origin_row[0])
                target = {"market_session_date": target_session_date}
                calendar_proof = validate_control_case(activation, origin_run, origin_session, target, recommendation, pending)
                if store.connection.execute("SELECT 1 FROM prospective_sessions WHERE market_session_date=?", (target_session_date,)).fetchone():
                    raise Stage6ProspectiveError("TARGET_SESSION_ALREADY_ENROLLED")
                if control.connection.execute("SELECT 1 FROM stage5d5_live_runs WHERE market_session_date=?", (target_session_date,)).fetchone():
                    raise Stage6ProspectiveError("TARGET_CONTROL_SESSION_ALREADY_COMPLETED")
                deadline, _ = pre_session_deadline_utc(target_session_date)
                if _now_utc() >= deadline:
                    raise Stage6ProspectiveError("PRE_SESSION_DEADLINE_PASSED")
        finally:
            store.close()
        capture_status = _capture_cycle_status(capture_summary_database, capture_run_id)
        return {
            "schema_version": READINESS_SCHEMA, "status": "READY_FOR_MORNING_PIPELINE",
            "blocking_reason": None, "recommendation_id": recommendation_id,
            "target_session_date": target_session_date, "origin_run_id": origin_run["run_id"],
            "origin_session_enrollment_id": origin_session["enrollment_id"],
            "calendar_proof": calendar_proof, "operational_primary_sources_expected": 2,
            "sebi_connector_status": "OPERATIONAL", "rbi_connector_status": "OPERATIONAL",
            "primary_evidence_capture_status": capture_status,
            "authority": AUTHORITY, "trading_authority": False, "proposal_generated": False,
        }
    except Exception as exc:
        return {
            "schema_version": READINESS_SCHEMA, "status": "BLOCKED",
            "blocking_reason": str(exc), "recommendation_id": recommendation_id,
            "target_session_date": target_session_date,
            "operational_primary_sources_expected": None if coverage is None else coverage["operational_primary_count"],
            "primary_evidence_capture_status": _capture_cycle_status(capture_summary_database, capture_run_id),
            "authority": AUTHORITY, "trading_authority": False, "proposal_generated": False,
        }
