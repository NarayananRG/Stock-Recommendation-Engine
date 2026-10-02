"""Read-only prospective cohort status reporting."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, without

from .activation import verify_activation_record
from .control_reader import Stage5DControlReader
from .errors import ProspectiveIntegrityFailure
from .policy import COMPONENT
from .prospective_store import ProspectiveValidationStore
from .source_coverage import attest_sources


def _read_prospective(path, activation_record):
    path = Path(path)
    empty = {"sessions": 0, "cases": 0, "paired": 0, "control_only": 0, "outcomes": 0,
             "last_session_date": None, "database_status": "NOT_PRESENT"}
    if not path.exists():
        return empty
    if not path.is_file():
        raise ProspectiveIntegrityFailure("PROSPECTIVE_DATABASE_INVALID")
    store = ProspectiveValidationStore(path, activation_record)
    connection = store.connection
    try:
        connection.execute("PRAGMA query_only=ON")
        if store.integrity_check()["result"] != "PASS":
            raise ProspectiveIntegrityFailure("PROSPECTIVE_DATABASE_INTEGRITY_FAILURE")
        sessions = connection.execute("SELECT count(*) FROM prospective_sessions").fetchone()[0]
        rows = connection.execute("SELECT state,canonical_json FROM prospective_cases").fetchall()
        for row in rows:
            record = json.loads(row["canonical_json"])
            if record.get("record_hash") != canonical_hash(without(record, "record_hash")) or row["state"] != record.get("case_state"):
                raise ProspectiveIntegrityFailure("PROSPECTIVE_CASE_STATUS_INVALID")
        last = connection.execute("SELECT max(market_session_date) FROM prospective_sessions").fetchone()[0]
        return {"sessions": sessions, "cases": len(rows),
                "paired": sum(row["state"] == "PAIRED_SHADOW_AVAILABLE" for row in rows),
                "control_only": sum(row["state"] == "CONTROL_ONLY_PENDING_SHADOW" for row in rows),
                "outcomes": sum(json.loads(row["canonical_json"]).get("outcome_status") != "NOT_ATTACHED" for row in rows),
                "last_session_date": last, "database_status": "READ_ONLY_VERIFIED"}
    except (sqlite3.Error, json.JSONDecodeError, KeyError, TypeError) as exc:
        if isinstance(exc, ProspectiveIntegrityFailure):
            raise
        raise ProspectiveIntegrityFailure("PROSPECTIVE_STATUS_READ_FAILURE") from exc
    finally:
        store.close()


def prospective_status(*, activation_record, prospective_database=None, control_database=None):
    activation = verify_activation_record(activation_record)
    cohort = _read_prospective(prospective_database, activation_record) if prospective_database else {
        "sessions": 0, "cases": 0, "paired": 0, "control_only": 0, "outcomes": 0,
        "last_session_date": None, "database_status": "NOT_SUPPLIED"}
    minimum = activation["minimum_completed_control_sessions"]
    last_control = None
    control_status = "NOT_SUPPLIED"
    if control_database is not None:
        with Stage5DControlReader(control_database) as control:
            last_control = control.connection.execute("SELECT max(market_session_date) FROM stage5d5_live_runs").fetchone()[0]
            control_status = "READ_ONLY_VERIFIED"
    coverage = attest_sources(activation_record)
    return {
        "activation_status": "ACTIVE", "activation_id": activation["activation_id"],
        "activation_hash": activation["record_hash"], "protocol_hash": activation["protocol_hash"],
        "activation_date_ist": activation["activation_date_ist"], "component_under_test": COMPONENT,
        "completed_prospective_sessions": cohort["sessions"], "minimum_completed_control_sessions": minimum,
        "remaining_sessions": max(0, minimum - cohort["sessions"]),
        "observation_window_status": "MINIMUM_WINDOW_REACHED" if cohort["sessions"] >= minimum else "ACTIVE_COLLECTING",
        "case_count": cohort["cases"], "paired_case_count": cohort["paired"],
        "control_only_case_count": cohort["control_only"], "outcome_count": cohort["outcomes"],
        "last_enrolled_session_date": cohort["last_session_date"], "last_stage5d5_control_date": last_control,
        "prospective_database_status": cohort["database_status"], "control_database_status": control_status,
        "source_coverage_status": "PASS", "operational_primary_source_count": coverage["operational_primary_count"],
        "authority": "SHADOW_ONLY", "trading_authority": False,
    }
