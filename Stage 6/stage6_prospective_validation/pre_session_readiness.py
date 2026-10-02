"""Read-only readiness checks before the frozen Stage 6.7 morning pipeline."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .activation import verify_activation_record
from .control_reader import Stage5DControlReader
from .enrollment_validation import validate_control_case
from .errors import ProspectiveIntegrityFailure, Stage6ProspectiveError
from .operations_config import (
    AUTHORITY,
    ENTITY_REGISTRY_V2_HASH,
    ENTITY_REGISTRY_V2_ID,
    OPERATIONAL_SOURCES,
    READINESS_SCHEMA,
    SOURCE_REGISTRY_V2_HASH,
    SOURCE_REGISTRY_V2_ID,
)
from .primary_evidence_capture import (
    _aggregate_capture_cycle_status,
    _parse_utc,
    _utc_text,
    verify_capture_summary_store,
)
from .prospective_store import ProspectiveValidationStore
from .session_calendar import IST, pre_session_deadline_utc
from .source_coverage import attest_sources


def _now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _verify_capture_for_readiness(record, activation, target_session_date, verification_time):
    expected_activation = {
        "record_type": activation["schema_version"],
        "record_id": activation["activation_id"],
        "record_hash": activation["record_hash"],
    }
    if record.get("activation_binding") != expected_activation:
        raise ProspectiveIntegrityFailure("CAPTURE_ACTIVATION_BINDING_MISMATCH")
    if record.get("target_session_date") != target_session_date:
        raise ProspectiveIntegrityFailure("CAPTURE_TARGET_SESSION_MISMATCH")

    deadline, calendar_proof = pre_session_deadline_utc(target_session_date)
    if record.get("target_session_calendar_proof") != calendar_proof:
        raise ProspectiveIntegrityFailure("CAPTURE_CALENDAR_PROOF_MISMATCH")
    if record.get("pre_session_deadline_utc") != _utc_text(deadline):
        raise ProspectiveIntegrityFailure("CAPTURE_DEADLINE_BINDING_MISMATCH")

    observed = _parse_utc(record.get("observed_start_utc"))
    completed = _parse_utc(record.get("completed_utc"))
    if observed.astimezone(IST).date().isoformat() != target_session_date:
        raise ProspectiveIntegrityFailure("CAPTURE_OBSERVED_DATE_MISMATCH")
    if completed.astimezone(IST).date().isoformat() != target_session_date:
        raise ProspectiveIntegrityFailure("CAPTURE_COMPLETED_DATE_MISMATCH")
    if observed > completed:
        raise ProspectiveIntegrityFailure("CAPTURE_TIMESTAMP_ORDER_INVALID")
    if observed >= deadline or completed >= deadline:
        raise ProspectiveIntegrityFailure("CAPTURE_LATE_NOT_ELIGIBLE")
    if completed > verification_time:
        raise ProspectiveIntegrityFailure("CAPTURE_COMPLETED_IN_FUTURE")
    if record.get("prospective_cycle_eligibility") != "ELIGIBLE":
        raise ProspectiveIntegrityFailure("CAPTURE_LATE_NOT_ELIGIBLE")

    if record.get("source_registry_v2_binding") != {
        "record_id": SOURCE_REGISTRY_V2_ID, "record_hash": SOURCE_REGISTRY_V2_HASH,
    }:
        raise ProspectiveIntegrityFailure("CAPTURE_SOURCE_REGISTRY_BINDING_MISMATCH")
    if record.get("entity_registry_v2_binding") != {
        "record_id": ENTITY_REGISTRY_V2_ID, "record_hash": ENTITY_REGISTRY_V2_HASH,
    }:
        raise ProspectiveIntegrityFailure("CAPTURE_ENTITY_REGISTRY_BINDING_MISMATCH")

    results = record.get("source_results")
    if not isinstance(results, list) or len(results) != 2:
        raise ProspectiveIntegrityFailure("CAPTURE_SOURCE_SET_INVALID")
    source_ids = [item.get("source_id") for item in results if isinstance(item, dict)]
    if len(source_ids) != 2 or len(set(source_ids)) != 2 or tuple(sorted(source_ids)) != OPERATIONAL_SOURCES:
        raise ProspectiveIntegrityFailure("CAPTURE_SOURCE_SET_INVALID")
    status, usable = _aggregate_capture_cycle_status(results)
    if (
        record.get("source_coverage_count") != 2
        or record.get("source_invocation_count") != 2
        or record.get("usable_source_count") != usable
        or record.get("capture_cycle_status") != status
    ):
        raise ProspectiveIntegrityFailure("CAPTURE_SOURCE_STATUS_INVALID")
    return status


def _capture_cycle_status(database=None, capture_run_id=None, *, activation=None,
                          target_session_date=None, verification_time=None):
    if database is None and capture_run_id is None:
        return "NOT_CAPTURED"
    if database is None:
        raise Stage6ProspectiveError("CAPTURE_SUMMARY_DATABASE_REQUIRED")
    if not isinstance(capture_run_id, str) or not capture_run_id:
        raise Stage6ProspectiveError("EXACT_CAPTURE_RUN_ID_REQUIRED")
    if activation is None or target_session_date is None or verification_time is None:
        raise Stage6ProspectiveError("CAPTURE_VERIFICATION_CONTEXT_REQUIRED")
    record, _ = verify_capture_summary_store(database, capture_run_id)
    return _verify_capture_for_readiness(
        record, activation, target_session_date, verification_time
    )


def pre_session_check(*, activation_record, prospective_database, control_database,
                      recommendation_id, target_session_date,
                      capture_summary_database=None, capture_run_id=None):
    coverage = None
    supplied_capture = capture_summary_database is not None or capture_run_id is not None
    capture_status = "INVALID" if supplied_capture else "NOT_CAPTURED"
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
        verification_time = _now_utc()
        store = ProspectiveValidationStore(path, activation_record)
        try:
            store.connection.execute("PRAGMA query_only=ON")
            if store.integrity_check()["result"] != "PASS":
                raise ProspectiveIntegrityFailure("PROSPECTIVE_INTEGRITY_FAILURE")
            with Stage5DControlReader(control_database) as control:
                recommendation = control.get_recommendation(recommendation_id)
                pending = control.get_pending_event(recommendation_id)
                origin_run = control.get_origin_run(recommendation["allocation_run_id"])
                origin_row = store.connection.execute(
                    "SELECT canonical_json FROM prospective_sessions WHERE run_id=?",
                    (origin_run["run_id"],),
                ).fetchone()
                if origin_row is None:
                    raise Stage6ProspectiveError("CONTROL_ORIGIN_SESSION_NOT_ENROLLED")
                origin_session = json.loads(origin_row[0])
                target = {"market_session_date": target_session_date}
                calendar_proof = validate_control_case(
                    activation, origin_run, origin_session, target, recommendation, pending
                )
                if store.connection.execute(
                    "SELECT 1 FROM prospective_sessions WHERE market_session_date=?",
                    (target_session_date,),
                ).fetchone():
                    raise Stage6ProspectiveError("TARGET_SESSION_ALREADY_ENROLLED")
                if control.connection.execute(
                    "SELECT 1 FROM stage5d5_live_runs WHERE market_session_date=?",
                    (target_session_date,),
                ).fetchone():
                    raise Stage6ProspectiveError("TARGET_CONTROL_SESSION_ALREADY_COMPLETED")
                deadline, _ = pre_session_deadline_utc(target_session_date)
                if verification_time >= deadline:
                    raise Stage6ProspectiveError("PRE_SESSION_DEADLINE_PASSED")
        finally:
            store.close()

        capture_status = _capture_cycle_status(
            capture_summary_database,
            capture_run_id,
            activation=activation,
            target_session_date=target_session_date,
            verification_time=verification_time,
        )
        return {
            "schema_version": READINESS_SCHEMA,
            "status": "READY_FOR_MORNING_PIPELINE",
            "blocking_reason": None,
            "recommendation_id": recommendation_id,
            "target_session_date": target_session_date,
            "origin_run_id": origin_run["run_id"],
            "origin_session_enrollment_id": origin_session["enrollment_id"],
            "calendar_proof": calendar_proof,
            "operational_primary_sources_expected": 2,
            "sebi_connector_status": "OPERATIONAL",
            "rbi_connector_status": "OPERATIONAL",
            "primary_evidence_capture_status": capture_status,
            "authority": AUTHORITY,
            "trading_authority": False,
            "proposal_generated": False,
        }
    except Exception as exc:
        return {
            "schema_version": READINESS_SCHEMA,
            "status": "BLOCKED",
            "blocking_reason": str(exc),
            "recommendation_id": recommendation_id,
            "target_session_date": target_session_date,
            "operational_primary_sources_expected": (
                None if coverage is None else coverage["operational_primary_count"]
            ),
            "primary_evidence_capture_status": capture_status,
            "authority": AUTHORITY,
            "trading_authority": False,
            "proposal_generated": False,
        }
