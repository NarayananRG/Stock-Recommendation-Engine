"""Explicit Stage 6.8B prospective operations CLI; imports have no side effects."""
from __future__ import annotations

import argparse
import json

from .operations_config import AUTHORITY, DAILY_OPERATOR
from .pre_session_readiness import pre_session_check
from .primary_evidence_capture import capture_primary_evidence
from .prospective_store import ProspectiveValidationStore
from .runtime_status import prospective_status
from .source_coverage import attest_sources


def enroll_control(*, activation_record, prospective_database, control_database, run_id):
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("EXACT_RUN_ID_REQUIRED")
    store = ProspectiveValidationStore(prospective_database, activation_record)
    try:
        result = store.enroll_session(control_database=control_database, run_id=run_id)
        integrity = store.integrity_check()
        session = result["session"]
        return {
            "status": result["status"], "session_enrollment_id": session["enrollment_id"],
            "session_ordinal": session["session_ordinal_since_activation"],
            "market_session_date": session["market_session_date"],
            "candidate_count": session["candidate_count"], "recommendation_count": session["recommendation_count"],
            "zero_candidate": session["zero_candidate_flag"], "zero_recommendation": session["zero_recommendation_flag"],
            "record_hash": session["record_hash"], "sessions_completed": integrity["sessions"],
            "minimum_sessions": 20, "sessions_display": f"{integrity['sessions']}/20",
            "integrity_result": integrity["result"], "authority": AUTHORITY, "trading_authority": False,
        }
    finally:
        store.close()


def _parser():
    parser = argparse.ArgumentParser(description="Stage 6.8B prospective shadow-validation daily operator")
    parser.add_argument("--operator-version", action="version", version=DAILY_OPERATOR)
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("--activation-record", required=True);status.add_argument("--prospective-db");status.add_argument("--control-db")
    attest = commands.add_parser("attest-sources");attest.add_argument("--activation-record", required=True)
    capture = commands.add_parser("capture-primary-evidence")
    capture.add_argument("--activation-record", required=True);capture.add_argument("--runtime-root", required=True);capture.add_argument("--live", action="store_true")
    enroll = commands.add_parser("enroll-control")
    enroll.add_argument("--activation-record", required=True);enroll.add_argument("--prospective-db", required=True);enroll.add_argument("--control-db", required=True);enroll.add_argument("--run-id", required=True)
    ready = commands.add_parser("pre-session-check")
    ready.add_argument("--activation-record", required=True);ready.add_argument("--prospective-db", required=True);ready.add_argument("--control-db", required=True);ready.add_argument("--recommendation-id", required=True);ready.add_argument("--target-session-date", required=True);ready.add_argument("--capture-summary-db");ready.add_argument("--capture-run-id")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "status":
            result = prospective_status(activation_record=args.activation_record, prospective_database=args.prospective_db, control_database=args.control_db)
        elif args.command == "attest-sources":
            result = attest_sources(args.activation_record)
        elif args.command == "capture-primary-evidence":
            result = capture_primary_evidence(activation_record=args.activation_record, runtime_root=args.runtime_root, live=args.live)
        elif args.command == "enroll-control":
            result = enroll_control(activation_record=args.activation_record, prospective_database=args.prospective_db, control_database=args.control_db, run_id=args.run_id)
        else:
            result = pre_session_check(activation_record=args.activation_record, prospective_database=args.prospective_db, control_database=args.control_db, recommendation_id=args.recommendation_id, target_session_date=args.target_session_date, capture_summary_database=args.capture_summary_db, capture_run_id=args.capture_run_id)
        print(json.dumps(result, sort_keys=True));return 0 if result.get("status") != "BLOCKED" else 1
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc), "authority": AUTHORITY, "trading_authority": False}, sort_keys=True));return 1


if __name__ == "__main__":
    raise SystemExit(main())
