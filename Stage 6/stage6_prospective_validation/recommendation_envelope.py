"""Creation-time-only immutable recommendation audit envelopes."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from .cohort_guard import FEATURE_HASHES, MODEL_BUNDLE_HASH, SOURCE_PACKAGE_HASH
from .control_reader import Stage5DControlReader, parse_utc, payload_sha256
from .errors import ProspectiveIntegrityFailure, Stage6ProspectiveError
from .observation_config import AUTHORITY, ENVELOPE_SCHEMA

PROHIBITED_OUTCOME_KEYS = {
    "future_return", "realized_pnl", "realized_p&l", "exit_price", "exit_reason",
    "mfe", "mae", "future_mfe", "future_mae", "checkpoint_outcome", "d+5_result",
    "d+20_result", "d+60_result", "final_outcome", "target_hit_result",
    "realized_holding_return", "holding_return", "stock_return", "nifty_return",
}


def _validate_no_outcomes(value, path="envelope"):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in PROHIBITED_OUTCOME_KEYS or normalized.startswith("future_"):
                raise Stage6ProspectiveError(f"ENVELOPE_FUTURE_OUTCOME_PROHIBITED:{path}.{key}")
            _validate_no_outcomes(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_no_outcomes(child, f"{path}[{index}]")


def _prospective_case(database, recommendation_id):
    path = Path(database).resolve()
    if not path.is_file():
        raise Stage6ProspectiveError("PROSPECTIVE_STORE_REQUIRED")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ProspectiveIntegrityFailure("PROSPECTIVE_STORE_INVALID")
        row = connection.execute("SELECT canonical_json FROM prospective_cases WHERE recommendation_id=?", (recommendation_id,)).fetchone()
        copied = connection.execute("SELECT payload_sha256,canonical_payload_json FROM prospective_control_recommendations WHERE recommendation_id=?", (recommendation_id,)).fetchone()
        if row is None or copied is None:
            raise Stage6ProspectiveError("RECOMMENDATION_NOT_IN_ACTIVE_PROSPECTIVE_COHORT")
        case = json.loads(row[0])
        if (canonical_json(case) != row[0] or case.get("recommendation_id") != recommendation_id
                or case.get("record_hash") != canonical_hash(without(case, "record_hash"))):
            raise ProspectiveIntegrityFailure("PROSPECTIVE_CASE_COPY_INVALID")
        return case, dict(copied), connection.execute("PRAGMA query_only").fetchone()[0] == 1
    finally:
        connection.close()


def _allocation(reader: Stage5DControlReader, allocation_run_id: str):
    row = reader.connection.execute("SELECT * FROM allocation_runs WHERE allocation_run_id=?", (allocation_run_id,)).fetchone()
    if row is None:
        raise Stage6ProspectiveError("ALLOCATION_RUN_NOT_FOUND")
    value = json.loads(row["canonical_payload_json"])
    if canonical_json(value) != row["canonical_payload_json"] or payload_sha256(row["canonical_payload_json"]) != row["payload_sha256"]:
        raise ProspectiveIntegrityFailure("ALLOCATION_RUN_HASH_INVALID")
    snapshot = json.loads(row["portfolio_snapshot_json"])
    if canonical_json(snapshot) != row["portfolio_snapshot_json"] or value.get("portfolio_snapshot") != snapshot:
        raise ProspectiveIntegrityFailure("PORTFOLIO_SNAPSHOT_BINDING_INVALID")
    return dict(row), value, snapshot


def _verify_snapshot(snapshot: dict, origin_run: dict, recommendation: dict):
    required = ("snapshot_id", "snapshot_content_hash", "model_bundle_hash", "source_package_hash",
                "feature_set", "feature_hash", "feature_row", "feature_row_hash", "candidate_input_hash",
                "market_data_manifest_id", "market_data_manifest_hash", "signal_id", "ticker", "candidate_row",
                "protocol_version", "protocol_tag")
    if any(key not in snapshot for key in required):
        raise Stage6ProspectiveError("STAGE4A3_SNAPSHOT_DESCRIPTOR_INCOMPLETE")
    if snapshot["snapshot_content_hash"] != canonical_hash(without(snapshot, "snapshot_content_hash")):
        raise ProspectiveIntegrityFailure("STAGE4A3_SNAPSHOT_HASH_INVALID")
    if snapshot["feature_row_hash"] != canonical_hash(snapshot["feature_row"]):
        raise ProspectiveIntegrityFailure("STAGE4A3_FEATURE_ROW_HASH_INVALID")
    expected = (origin_run["stage4a3_snapshot_id"], MODEL_BUNDLE_HASH, SOURCE_PACKAGE_HASH,
                origin_run["candidate_input_hash"], recommendation["signal_id"], recommendation["ticker"])
    actual = (snapshot["snapshot_id"], snapshot["model_bundle_hash"], snapshot["source_package_hash"],
              snapshot["candidate_input_hash"], snapshot["signal_id"], snapshot["ticker"])
    if (actual != expected or snapshot["feature_hash"] not in FEATURE_HASHES
            or snapshot["protocol_version"] != "STAGE4A3A_V1"
            or snapshot["protocol_tag"] != "stage4a3-prospective-shadow-protocol-baseline"):
        raise ProspectiveIntegrityFailure("STAGE4A3_SNAPSHOT_BINDING_INVALID")


def build_recommendation_envelope(*, control_database, prospective_database, recommendation_id,
                                  cohort_fingerprint, stage4a3_snapshot, creation_context=None):
    case, copied, prospective_query_only = _prospective_case(prospective_database, recommendation_id)
    if (case.get("activation_binding", {}).get("record_id"), case.get("activation_binding", {}).get("record_hash")) != (cohort_fingerprint["activation_id"], cohort_fingerprint["activation_record_hash"]):
        raise ProspectiveIntegrityFailure("PROSPECTIVE_CASE_ACTIVATION_MISMATCH")
    with Stage5DControlReader(control_database) as reader:
        recommendation = reader.get_recommendation(recommendation_id)
        if copied["payload_sha256"] != recommendation["payload_sha256"] or copied["canonical_payload_json"] != recommendation["canonical_payload_json"]:
            raise ProspectiveIntegrityFailure("PROSPECTIVE_RECOMMENDATION_BINDING_INVALID")
        allocation_row, allocation, portfolio_snapshot = _allocation(reader, recommendation["allocation_run_id"])
        origin_run = reader.get_origin_run(recommendation["allocation_run_id"])
        _verify_snapshot(stage4a3_snapshot, origin_run, recommendation)
        if reader.connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise ProspectiveIntegrityFailure("CONTROL_NOT_QUERY_ONLY")
    creation_time = recommendation["persisted_at_utc"]
    parse_utc(creation_time)
    context = creation_context or {}
    context_recorded = context.get("recorded_at_utc")
    if context_recorded is not None and parse_utc(context_recorded) > parse_utc(creation_time):
        raise Stage6ProspectiveError("CREATION_CONTEXT_AFTER_RECOMMENDATION")
    stage6_context = ({
        "availability": "NOT_AVAILABLE_AT_RECOMMENDATION_CREATION",
        "market_context_binding": None, "evidence_event_bindings": [], "trade_thesis_binding": None,
        "known_risks": [], "invalidation_conditions": [],
    } if not context else context)
    record = {
        "schema_version": ENVELOPE_SCHEMA, "envelope_id": "",
        "cohort_fingerprint_binding": {"record_type": cohort_fingerprint["schema_version"], "record_id": cohort_fingerprint["cohort_fingerprint_id"], "record_hash": cohort_fingerprint["record_hash"]},
        "prospective_case_binding": {"record_type": case["schema_version"], "record_id": case["case_id"], "record_hash": case["record_hash"]},
        "recommendation_binding": {"record_type": "STAGE5D_RECOMMENDATION", "record_id": recommendation_id, "record_hash": recommendation["payload_sha256"]},
        "allocation_run_binding": {"record_type": "STAGE5D_ALLOCATION_RUN", "record_id": recommendation["allocation_run_id"], "record_hash": allocation_row["payload_sha256"]},
        "stage4a3_snapshot_binding": {"record_type": "STAGE4A3_SNAPSHOT", "record_id": stage4a3_snapshot["snapshot_id"], "record_hash": stage4a3_snapshot["snapshot_content_hash"]},
        "recommendation_id": recommendation_id, "signal_id": recommendation["signal_id"], "ticker": recommendation["ticker"],
        "signal_date": recommendation["signal_date"], "decision_date": recommendation["decision_date"],
        "recommendation_persisted_at_utc": creation_time,
        "recommendation": json.loads(recommendation["canonical_payload_json"]),
        "portfolio_snapshot": portfolio_snapshot,
        "profile_capital_context": {"profile_version": allocation_row["profile_version"], "capital_ceiling_inr": allocation_row["capital_ceiling_inr"], "selected_horizon": allocation_row["selected_horizon"]},
        "stage4a3": {
            "snapshot_id": stage4a3_snapshot["snapshot_id"], "snapshot_content_hash": stage4a3_snapshot["snapshot_content_hash"],
            "candidate_row": stage4a3_snapshot["candidate_row"], "feature_row_hash": stage4a3_snapshot["feature_row_hash"],
            "feature_set": stage4a3_snapshot["feature_set"], "feature_hash": stage4a3_snapshot["feature_hash"],
            "model_bundle_hash": stage4a3_snapshot["model_bundle_hash"], "source_package_hash": stage4a3_snapshot["source_package_hash"],
            "protocol_version": stage4a3_snapshot["protocol_version"], "protocol_tag": stage4a3_snapshot["protocol_tag"],
            "market_data_manifest_binding": {"record_type": "STAGE4A3_MARKET_DATA_MANIFEST", "record_id": stage4a3_snapshot["market_data_manifest_id"], "record_hash": stage4a3_snapshot["market_data_manifest_hash"]},
            "candidate_input_hash": stage4a3_snapshot["candidate_input_hash"],
        },
        "stage6_creation_context": stage6_context,
        "source_read_modes": {"stage5d": "READ_ONLY_QUERY_ONLY", "prospective_store": "READ_ONLY_QUERY_ONLY"},
        "authority": AUTHORITY, "recommendation_influence": "NONE", "trading_authority": False,
        "record_hash": "",
    }
    _validate_no_outcomes(record)
    if not prospective_query_only:
        raise ProspectiveIntegrityFailure("PROSPECTIVE_STORE_NOT_QUERY_ONLY")
    record["envelope_id"] = "S6PROSENV_" + canonical_hash(without(record, "envelope_id", "record_hash"))[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record


def validate_envelope(record):
    _validate_no_outcomes(record)
    if record.get("schema_version") != ENVELOPE_SCHEMA or record.get("authority") != AUTHORITY or record.get("trading_authority") is not False:
        raise ProspectiveIntegrityFailure("ENVELOPE_CONTRACT_INVALID")
    if record.get("envelope_id") != "S6PROSENV_" + canonical_hash(without(record, "envelope_id", "record_hash"))[:24] or record.get("record_hash") != canonical_hash(without(record, "record_hash")):
        raise ProspectiveIntegrityFailure("ENVELOPE_IDENTITY_INVALID")
    return record
