"""Creation-time-only immutable recommendation audit envelopes."""
from __future__ import annotations

import json
from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from .cohort_guard import FEATURE_HASHES, MODEL_BUNDLE_HASH, SOURCE_PACKAGE_HASH
from .control_reader import Stage5DControlReader, parse_utc, payload_sha256
from .errors import ProspectiveIntegrityFailure, Stage6ProspectiveError
from .observation_config import AUTHORITY, ENVELOPE_SCHEMA
from .activation import verify_activation_record
from .verified_inputs import ProspectiveStoreReader, Stage4A3SnapshotResolver, Stage6ContextReader

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


def _verify_test_snapshot(snapshot: dict, origin_run: dict, recommendation: dict):
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
                                  cohort_fingerprint, activation_record=None,
                                  stage4a3_root=None, stage4a3_prospective_root=None,
                                  stage4a3_snapshot=None, creation_context=None,
                                  stage6_context_database=None, stage6_context_binding=None,
                                  test_only_adapter=False):
    if activation_record is None:
        if not test_only_adapter:
            raise Stage6ProspectiveError("VERIFIED_ACTIVATION_RECORD_REQUIRED")
        activation = {"activation_id": cohort_fingerprint["activation_id"], "record_hash": cohort_fingerprint["activation_record_hash"], "activation_date_ist": "1900-01-01", "activated_at_utc": "1900-01-01T00:00:00Z"}
    else:
        activation = verify_activation_record(activation_record)
    if (activation["activation_id"], activation["record_hash"]) != (cohort_fingerprint["activation_id"], cohort_fingerprint["activation_record_hash"]):
        raise ProspectiveIntegrityFailure("PROSPECTIVE_ACTIVATION_MISMATCH")
    with Stage5DControlReader(control_database) as reader:
        recommendation = reader.get_recommendation(recommendation_id)
        allocation_row, allocation, portfolio_snapshot = _allocation(reader, recommendation["allocation_run_id"])
        origin_run = reader.get_origin_run(recommendation["allocation_run_id"])
        control_database_id = reader.database_id()
        if test_only_adapter:
            if stage4a3_snapshot is None:
                raise Stage6ProspectiveError("TEST_SNAPSHOT_DESCRIPTOR_REQUIRED")
            _verify_test_snapshot(stage4a3_snapshot, origin_run, recommendation)
            snapshot = stage4a3_snapshot
        else:
            if stage4a3_snapshot is not None:
                raise Stage6ProspectiveError("CALLER_SUPPLIED_STAGE4A3_SNAPSHOT_PROHIBITED")
            snapshot = Stage4A3SnapshotResolver(stage4a3_root, stage4a3_prospective_root).resolve(origin_run, recommendation)
        if reader.connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise ProspectiveIntegrityFailure("CONTROL_NOT_QUERY_ONLY")
    with ProspectiveStoreReader(prospective_database, activation) as prospective:
        origin_session = prospective.origin_session(origin_run, control_database_id)
        case_status, case_binding = prospective.case_at_creation(recommendation_id, recommendation["persisted_at_utc"])
        prospective_query_only = prospective.connection.execute("PRAGMA query_only").fetchone()[0] == 1
    creation_time = recommendation["persisted_at_utc"]
    parse_utc(creation_time)
    if creation_context is not None and not test_only_adapter:
        raise Stage6ProspectiveError("CALLER_SUPPLIED_STAGE6_CONTEXT_PROHIBITED")
    context = creation_context or {}
    if stage6_context_database is not None or stage6_context_binding is not None:
        if not stage6_context_database or not stage6_context_binding:
            raise Stage6ProspectiveError("VERIFIED_STAGE6_CONTEXT_BINDING_REQUIRED")
        with Stage6ContextReader(stage6_context_database) as context_reader:
            resolved, binding = context_reader.resolve(stage6_context_binding, cutoff_utc=creation_time, recommendation_id=recommendation_id, signal_id=recommendation["signal_id"], ticker=recommendation["ticker"])
        context = {"availability": "AVAILABLE_VERIFIED_AT_RECOMMENDATION_CREATION", "record_binding": binding, "record": resolved}
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
        "prospective_origin_session_binding": {"record_type": origin_session["schema_version"], "record_id": origin_session["enrollment_id"], "record_hash": origin_session["record_hash"]},
        "prospective_case_status": case_status,
        "prospective_case_binding": case_binding,
        "recommendation_binding": {"record_type": "STAGE5D_RECOMMENDATION", "record_id": recommendation_id, "record_hash": recommendation["payload_sha256"]},
        "allocation_run_binding": {"record_type": "STAGE5D_ALLOCATION_RUN", "record_id": recommendation["allocation_run_id"], "record_hash": allocation_row["payload_sha256"]},
        "stage4a3_snapshot_binding": {"record_type": "STAGE4A3_SNAPSHOT", "record_id": snapshot["snapshot_id"], "record_hash": snapshot["snapshot_content_hash"]},
        "recommendation_id": recommendation_id, "signal_id": recommendation["signal_id"], "ticker": recommendation["ticker"],
        "signal_date": recommendation["signal_date"], "decision_date": recommendation["decision_date"],
        "recommendation_persisted_at_utc": creation_time,
        "recommendation": json.loads(recommendation["canonical_payload_json"]),
        "portfolio_snapshot": portfolio_snapshot,
        "profile_capital_context": {"profile_version": allocation_row["profile_version"], "capital_ceiling_inr": allocation_row["capital_ceiling_inr"], "selected_horizon": allocation_row["selected_horizon"]},
        "stage4a3": {
            "snapshot_id": snapshot["snapshot_id"], "snapshot_content_hash": snapshot["snapshot_content_hash"],
            "candidate_row": snapshot["candidate_row"], "feature_row_hash": snapshot["feature_row_hash"],
            "feature_row_content_hash": snapshot.get("feature_row_content_hash", snapshot["feature_row_hash"]),
            "feature_set": snapshot["feature_set"], "feature_hash": snapshot["feature_hash"],
            "model_bundle_hash": snapshot["model_bundle_hash"], "source_package_hash": snapshot.get("source_package_hash", SOURCE_PACKAGE_HASH),
            "protocol_version": snapshot["protocol_version"], "protocol_tag": snapshot["protocol_tag"],
            "market_data_manifest_binding": {"record_type": "STAGE4A3_MARKET_DATA_MANIFEST", "record_id": snapshot["market_data_manifest_id"], "record_hash": snapshot["market_data_manifest_hash"]},
            "candidate_input_hash": snapshot["candidate_input_hash"],
            "snapshot_directory_verification": snapshot.get("snapshot_directory_verification", "TEST_ONLY_ADAPTER"),
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
