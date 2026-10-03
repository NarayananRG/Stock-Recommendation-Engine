"""Pure, deterministic point-in-time benchmark checkpoint calculations."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext

from stage6_ingestion.canonical import canonical_hash, without
from .control_reader import parse_utc, payload_sha256
from .errors import ProspectiveIntegrityFailure, Stage6ProspectiveError
from .observation_config import AUTHORITY, CHECKPOINT_SCHEMA, CHECKPOINT_TYPES, MEASUREMENT_VERSION
from .recommendation_envelope import validate_envelope

MARKET_CLASSIFICATION = "OUTCOME_MEASUREMENT_ONLY_NOT_STAGE6_EVENT_EVIDENCE"
SECTOR_UNAVAILABLE = "UNAVAILABLE_NO_VERIFIED_SECTOR_BENCHMARK"
ORDINALS = {"D+5": 5, "D+20": 20, "D+60": 60}


def determine_due_checkpoints(*, decision_date, completed_session_dates, existing_checkpoint_types=(), final_exit_completed=False):
    try:
        anchor = date.fromisoformat(decision_date).isoformat()
    except Exception as exc:
        raise Stage6ProspectiveError("DECISION_DATE_INVALID") from exc
    sessions = list(completed_session_dates)
    if sessions != sorted(set(sessions)) or any(date.fromisoformat(item).isoformat() != item or item <= anchor for item in sessions):
        raise Stage6ProspectiveError("COMPLETED_SESSION_SEQUENCE_INVALID")
    existing = set(existing_checkpoint_types)
    if not existing <= set(CHECKPOINT_TYPES):
        raise Stage6ProspectiveError("EXISTING_CHECKPOINT_TYPE_INVALID")
    due = []
    for kind, ordinal in ORDINALS.items():
        if kind not in existing and len(sessions) >= ordinal:
            due.append({"checkpoint_type": kind, "trading_session_ordinal": ordinal, "checkpoint_date": sessions[ordinal-1], "status": "DUE"})
    if final_exit_completed and "FINAL_EXIT" not in existing:
        due.append({"checkpoint_type": "FINAL_EXIT", "trading_session_ordinal": None, "checkpoint_date": None, "status": "DUE_REQUIRES_VERIFIED_EXIT_SESSION"})
    return due


def _decimal(value, name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Stage6ProspectiveError(f"{name}_INVALID") from exc
    if not result.is_finite() or result <= 0:
        raise Stage6ProspectiveError(f"{name}_INVALID")
    return result


def _canon(value: Decimal):
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _return(end, start):
    with localcontext() as context:
        context.prec = 34
        return end / start - Decimal(1)


def _validate_manifest(manifest):
    if manifest.get("classification") != MARKET_CLASSIFICATION:
        raise ProspectiveIntegrityFailure("MARKET_DATA_CLASSIFICATION_INVALID")
    expected = canonical_hash(without(manifest, "manifest_hash"))
    if manifest.get("manifest_hash") != expected or not manifest.get("manifest_id"):
        raise ProspectiveIntegrityFailure("MARKET_DATA_MANIFEST_INVALID")
    rows = manifest.get("observations")
    if not isinstance(rows, list) or not rows:
        raise Stage6ProspectiveError("MARKET_OBSERVATIONS_REQUIRED")
    dates = []
    for row in rows:
        try:
            day = date.fromisoformat(row["session_date"]).isoformat()
        except Exception as exc:
            raise Stage6ProspectiveError("MARKET_SESSION_DATE_INVALID") from exc
        if day != row["session_date"] or day in dates:
            raise Stage6ProspectiveError("MARKET_SESSION_SEQUENCE_INVALID")
        if "observed_at_utc" not in row:
            raise Stage6ProspectiveError("MARKET_OBSERVED_TIMESTAMP_REQUIRED")
        parse_utc(row["observed_at_utc"])
        dates.append(day)
    if dates != sorted(dates):
        raise Stage6ProspectiveError("MARKET_SESSION_SEQUENCE_INVALID")
    return rows


def _thesis_as_of(records, cutoff):
    allowed = {"VALID", "INVALIDATED", "INDETERMINATE", "NOT_AVAILABLE"}
    available = [item for item in records if parse_utc(item["recorded_at_utc"]) <= cutoff]
    if not available:
        return "NOT_AVAILABLE", "NOT_AVAILABLE", []
    available.sort(key=lambda item: item["recorded_at_utc"])
    latest = available[-1]
    if latest.get("current_thesis_state") not in allowed or latest.get("original_thesis_validity_state") not in allowed:
        raise Stage6ProspectiveError("THESIS_STATE_INVALID")
    binding = latest.get("binding")
    if not isinstance(binding, dict) or set(("record_type", "record_id", "record_hash")) - set(binding):
        raise Stage6ProspectiveError("THESIS_BINDING_INVALID")
    return latest["current_thesis_state"], latest["original_thesis_validity_state"], [binding]


def derive_final_exit(control_reader, recommendation_id, checkpoint_cutoff_utc):
    cutoff = parse_utc(checkpoint_cutoff_utc)
    tables = control_reader._tables()
    if not {"user_transactions", "transaction_voids"} <= tables:
        raise Stage6ProspectiveError("FINAL_EXIT_LIFECYCLE_TABLES_REQUIRED")
    voided = set()
    for row in control_reader.connection.execute("SELECT * FROM transaction_voids"):
        payload = json.loads(row["canonical_payload_json"])
        if payload_sha256(row["canonical_payload_json"]) != row["payload_sha256"] or payload.get("transaction_id") != row["transaction_id"]:
            raise ProspectiveIntegrityFailure("TRANSACTION_VOID_HASH_INVALID")
        voided.add(row["transaction_id"])
    rows = control_reader.connection.execute("SELECT * FROM user_transactions WHERE recommendation_id=? ORDER BY trade_date,transaction_sequence", (recommendation_id,)).fetchall()
    active = []
    for row in rows:
        if row["transaction_id"] in voided or parse_utc(row["recorded_at_utc"]) > cutoff:
            continue
        payload = json.loads(row["canonical_payload_json"])
        if payload_sha256(row["canonical_payload_json"]) != row["payload_sha256"]:
            raise ProspectiveIntegrityFailure("TRANSACTION_HASH_INVALID")
        active.append((row, payload))
    if not active or not any(row["side"] == "BUY" for row, _ in active):
        raise Stage6ProspectiveError("FINAL_EXIT_REQUIRES_FILLED_POSITION")
    quantity = sum((row["quantity"] if row["side"] == "BUY" else -row["quantity"]) for row, _ in active)
    if quantity != 0 or active[-1][0]["side"] != "SELL":
        raise Stage6ProspectiveError("FINAL_EXIT_NOT_COMPLETED")
    last = active[-1][0]
    return {"exit_status": "FINAL_EXIT_COMPLETED", "final_exit_date": last["trade_date"],
            "final_exit_transaction_binding": {"record_type": "STAGE5D_USER_TRANSACTION", "record_id": last["transaction_id"], "record_hash": last["payload_sha256"]}}


def build_checkpoint(*, envelope, checkpoint_type, checkpoint_cutoff_utc, market_data_manifest,
                     thesis_records=(), final_exit=None):
    validate_envelope(envelope)
    if checkpoint_type not in CHECKPOINT_TYPES:
        raise Stage6ProspectiveError("CHECKPOINT_TYPE_INVALID")
    cutoff = parse_utc(checkpoint_cutoff_utc)
    rows = _validate_manifest(market_data_manifest)
    if any(parse_utc(row["observed_at_utc"]) > cutoff for row in rows):
        raise Stage6ProspectiveError("FUTURE_MARKET_DATA_CROSSES_CHECKPOINT_CUTOFF")
    anchor_date = envelope["decision_date"]
    anchor_rows = [row for row in rows if row["session_date"] == anchor_date]
    if len(anchor_rows) != 1:
        raise Stage6ProspectiveError("COMMON_RETURN_ANCHOR_REQUIRED")
    after = [row for row in rows if row["session_date"] > anchor_date]
    if checkpoint_type == "FINAL_EXIT":
        if not final_exit or final_exit.get("exit_status") != "FINAL_EXIT_COMPLETED":
            raise Stage6ProspectiveError("FINAL_EXIT_REQUIRES_COMPLETED_LIFECYCLE")
        target_date = final_exit.get("final_exit_date")
        targets = [row for row in after if row["session_date"] == target_date]
        if len(targets) != 1:
            raise Stage6ProspectiveError("FINAL_EXIT_MARKET_SESSION_REQUIRED")
        ordinal = after.index(targets[0]) + 1
    else:
        ordinal = ORDINALS[checkpoint_type]
        if len(after) < ordinal:
            raise Stage6ProspectiveError("CHECKPOINT_SESSION_NOT_COMPLETE")
        target_date = after[ordinal - 1]["session_date"]
    target_rows = [row for row in rows if row["session_date"] == target_date]
    if len(target_rows) != 1:
        raise Stage6ProspectiveError("CHECKPOINT_SESSION_AMBIGUOUS")
    target = target_rows[0]
    if any(row["session_date"] > target_date for row in rows):
        raise Stage6ProspectiveError("FUTURE_MARKET_DATA_CROSSES_CHECKPOINT_CUTOFF")
    if cutoff.date().isoformat() != target_date:
        raise Stage6ProspectiveError("CHECKPOINT_CUTOFF_SESSION_MISMATCH")
    window = [row for row in rows if anchor_date <= row["session_date"] <= target_date]
    for row in window:
        for key in ("stock_close", "stock_high", "stock_low"):
            if row.get(key) is None:
                raise Stage6ProspectiveError("STOCK_OBSERVATION_MISSING_AT_CHECKPOINT")
    anchor = anchor_rows[0]
    if anchor.get("nifty_close") is None or target.get("nifty_close") is None:
        raise Stage6ProspectiveError("NIFTY_BENCHMARK_REQUIRED")
    stock_anchor = _decimal(anchor["stock_close"], "ANCHOR_STOCK_PRICE")
    stock_end = _decimal(target["stock_close"], "CHECKPOINT_STOCK_PRICE")
    nifty_anchor = _decimal(anchor["nifty_close"], "ANCHOR_NIFTY_PRICE")
    nifty_end = _decimal(target["nifty_close"], "CHECKPOINT_NIFTY_PRICE")
    stock_return = _return(stock_end, stock_anchor); nifty_return = _return(nifty_end, nifty_anchor)
    highs = [_decimal(row["stock_high"], "STOCK_HIGH") for row in window]
    lows = [_decimal(row["stock_low"], "STOCK_LOW") for row in window]
    closes = [_decimal(row["stock_close"], "STOCK_CLOSE") for row in window]
    mfe = max(_return(value, stock_anchor) for value in highs)
    mae = min(_return(value, stock_anchor) for value in lows)
    peak = closes[0]; drawdown = Decimal(0)
    for value in closes:
        peak = max(peak, value); drawdown = min(drawdown, _return(value, peak))
    sector_id = anchor.get("sector_benchmark_id")
    if sector_id is None:
        sector = {"sector_benchmark_status": SECTOR_UNAVAILABLE, "sector_benchmark_identifier": None,
                  "anchor_sector_value": None, "checkpoint_sector_value": None, "sector_return": None,
                  "stock_minus_sector": None}
    else:
        if target.get("sector_benchmark_id") != sector_id or anchor.get("sector_close") is None or target.get("sector_close") is None:
            raise Stage6ProspectiveError("VERIFIED_SECTOR_BENCHMARK_INCOMPLETE")
        sector_return = _return(_decimal(target["sector_close"], "CHECKPOINT_SECTOR"), _decimal(anchor["sector_close"], "ANCHOR_SECTOR"))
        sector = {"sector_benchmark_status": "AVAILABLE_VERIFIED", "sector_benchmark_identifier": sector_id,
                  "anchor_sector_value": _canon(_decimal(anchor["sector_close"], "ANCHOR_SECTOR")),
                  "checkpoint_sector_value": _canon(_decimal(target["sector_close"], "CHECKPOINT_SECTOR")),
                  "sector_return": _canon(sector_return), "stock_minus_sector": _canon(stock_return - sector_return)}
    current_thesis, original_validity, thesis_bindings = _thesis_as_of(list(thesis_records), cutoff)
    lifecycle = final_exit or {"exit_status": "OPEN_OR_NOT_FILLED_AS_OF_CHECKPOINT", "final_exit_date": None, "final_exit_transaction_binding": None}
    reference = envelope["recommendation"].get("sizing_entry_price")
    record = {
        "schema_version": CHECKPOINT_SCHEMA, "checkpoint_id": "",
        "recommendation_audit_envelope_binding": {"record_type": envelope["schema_version"], "record_id": envelope["envelope_id"], "record_hash": envelope["record_hash"]},
        "recommendation_id": envelope["recommendation_id"], "recommendation_binding": envelope["recommendation_binding"],
        "signal_id": envelope["signal_id"], "ticker": envelope["ticker"], "original_signal_date": envelope["signal_date"],
        "recommendation_persisted_at_utc": envelope["recommendation_persisted_at_utc"], "checkpoint_type": checkpoint_type,
        "trading_session_ordinal": ordinal, "checkpoint_date": target_date, "checkpoint_cutoff_timestamp": checkpoint_cutoff_utc,
        "original_recommendation_reference_price": None if reference is None else str(reference),
        "original_reference_price_semantics": "STAGE5D_SIZING_ENTRY_PRICE_CONTEXT_NOT_BENCHMARK_RETURN_ANCHOR",
        "return_anchor_date": anchor_date, "anchor_stock_price": _canon(stock_anchor), "checkpoint_stock_price": _canon(stock_end),
        "stock_return": _canon(stock_return), "anchor_nifty_price": _canon(nifty_anchor), "checkpoint_nifty_price": _canon(nifty_end),
        "nifty_return": _canon(nifty_return), "stock_minus_nifty": _canon(stock_return - nifty_return), **sector,
        "mfe": _canon(mfe), "mae": _canon(mae), "maximum_drawdown": _canon(drawdown),
        "current_thesis_state": current_thesis, "original_thesis_validity_state": original_validity,
        "thesis_review_bindings": thesis_bindings, **lifecycle,
        "market_data_manifest_binding": {"record_type": "STAGE6_8C_MARKET_DATA_MANIFEST", "record_id": market_data_manifest["manifest_id"], "record_hash": market_data_manifest["manifest_hash"]},
        "market_data_classification": MARKET_CLASSIFICATION, "measurement_method_version": MEASUREMENT_VERSION,
        "point_in_time_verification_status": "PASS", "authority": AUTHORITY, "recommendation_influence": "NONE",
        "trading_authority": False, "record_hash": "",
    }
    record["checkpoint_id"] = "S6PROSCHK_" + canonical_hash(without(record, "checkpoint_id", "record_hash"))[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record


def validate_checkpoint(record):
    if record.get("schema_version") != CHECKPOINT_SCHEMA or record.get("checkpoint_type") not in CHECKPOINT_TYPES or record.get("authority") != AUTHORITY or record.get("trading_authority") is not False:
        raise ProspectiveIntegrityFailure("CHECKPOINT_CONTRACT_INVALID")
    if record.get("checkpoint_id") != "S6PROSCHK_" + canonical_hash(without(record, "checkpoint_id", "record_hash"))[:24] or record.get("record_hash") != canonical_hash(without(record, "record_hash")):
        raise ProspectiveIntegrityFailure("CHECKPOINT_IDENTITY_INVALID")
    return record
