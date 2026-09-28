import math
from copy import deepcopy

from stage6_ingestion.canonical import canonical_hash, parse_utc, without

from .errors import Stage6AnalogueOutcomeError
from .policy import OUTCOME_DEFINITION_VERSION, SCHEMA_VERSION, SELECTION_ENGINE_COMMIT

HORIZONS = ("D+1", "D+3", "D+5", "D+10", "D+20")
RETURN_NAMES = ("stock_return", "sector_return", "nifty_return")
STATUSES = {"AVAILABLE", "NOT_MATURED", "MISSING"}
SAFETY = {
    "outcome_attachment_status": "EVALUATED",
    "outcome_distribution_status": "NOT_EVALUATED",
    "relative_return_status": "NOT_EVALUATED",
    "final_historical_analogue_status": "NOT_MATERIALIZED",
    "expected_return_status": "NOT_EVALUATED",
    "target_price_status": "NOT_EVALUATED",
    "security_ranking_status": "NOT_EVALUATED",
    "portfolio_influence_status": "NOT_EVALUATED",
    "buy_sell_hold_status": "NOT_EVALUATED",
    "trading_authority": False,
}


def _measurement(raw, *, unit, anchor, cutoff, evidence_records, kind):
    required = {"status", "value", "unit", "outcome_observed_through_timestamp", "method", "evidence_bindings"}
    if not isinstance(raw, dict) or set(raw) != required or raw.get("status") not in STATUSES or raw.get("unit") != unit:
        raise Stage6AnalogueOutcomeError(f"ANALOGUE_OUTCOME_MEASUREMENT_INVALID:{kind}")
    status = raw["status"]
    if status != "AVAILABLE":
        if raw["value"] is not None or raw["outcome_observed_through_timestamp"] is not None or raw["method"] is not None or raw["evidence_bindings"] != []:
            raise Stage6AnalogueOutcomeError(f"ANALOGUE_OUTCOME_NULL_STATUS_INVALID:{kind}")
        return deepcopy(raw)
    value = raw["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Stage6AnalogueOutcomeError(f"ANALOGUE_OUTCOME_VALUE_INVALID:{kind}")
    if kind == "maximum_adverse_excursion" and value > 0:
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_MAE_SIGN_INVALID")
    if kind == "maximum_favourable_excursion" and value < 0:
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_MFE_SIGN_INVALID")
    if kind == "recovery_time" and (type(value) is not int or value < 0):
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_RECOVERY_VALUE_INVALID")
    observed = raw["outcome_observed_through_timestamp"]
    if parse_utc(observed, f"{kind}.observed") <= parse_utc(anchor, "anchor"):
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_NOT_AFTER_ANCHOR")
    if parse_utc(observed, f"{kind}.observed") > parse_utc(cutoff, "target_cutoff"):
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_AFTER_TARGET_CUTOFF")
    if not isinstance(raw["method"], str) or not raw["method"]:
        raise Stage6AnalogueOutcomeError(f"ANALOGUE_OUTCOME_METHOD_REQUIRED:{kind}")
    bindings = raw["evidence_bindings"]
    if not isinstance(bindings, list) or not bindings:
        raise Stage6AnalogueOutcomeError(f"ANALOGUE_OUTCOME_EVIDENCE_REQUIRED:{kind}")
    normalized = []
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {"evidence_id", "evidence_hash"}:
            raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_EVIDENCE_BINDING_INVALID")
        evidence = evidence_records.get(binding["evidence_id"])
        if evidence is None or evidence.get("record_hash") != binding["evidence_hash"]:
            raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_EVIDENCE_HASH_INVALID")
        if evidence.get("schema_version") != "STAGE6_EVIDENCE_V2" or evidence.get("record_kind") != "EVIDENCE":
            raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_EVIDENCE_KIND_INVALID")
        retrieved = evidence.get("retrieved_timestamp_utc")
        if retrieved is None or parse_utc(retrieved, "evidence.retrieved") > parse_utc(cutoff, "target_cutoff"):
            raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_EVIDENCE_AFTER_TARGET_CUTOFF")
        normalized.append(deepcopy(binding))
    normalized.sort(key=lambda item: (item["evidence_id"], item["evidence_hash"]))
    if len({item["evidence_id"] for item in normalized}) != len(normalized):
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_DUPLICATE_EVIDENCE")
    result = deepcopy(raw)
    result["evidence_bindings"] = normalized
    return result


def _attachment(selected, raw, *, rank, outcome_unit, cutoff, evidence_records):
    required = {"analogue_id", "horizons", "maximum_adverse_excursion", "maximum_favourable_excursion", "recovery_time"}
    if not isinstance(raw, dict) or set(raw) != required or raw.get("analogue_id") != selected["analogue_id"]:
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_ATTACHMENT_INVALID")
    if not isinstance(raw["horizons"], dict) or set(raw["horizons"]) != set(HORIZONS):
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_HORIZONS_INVALID")
    horizons = {}
    for horizon in HORIZONS:
        values = raw["horizons"][horizon]
        if not isinstance(values, dict) or set(values) != set(RETURN_NAMES):
            raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_HORIZON_MEASUREMENTS_INVALID")
        horizons[horizon] = {name: _measurement(values[name], unit=outcome_unit, anchor=selected["historical_as_of_timestamp"], cutoff=cutoff, evidence_records=evidence_records, kind=f"{horizon}.{name}") for name in RETURN_NAMES}
    return {
        "analogue_id": selected["analogue_id"],
        "selection_rank": rank,
        "entity_id": selected["entity_id"],
        "event_id": selected["event_id"],
        "historical_as_of_timestamp": selected["historical_as_of_timestamp"],
        "similarity_score": deepcopy(selected["similarity_score"]),
        "distance": deepcopy(selected["distance"]),
        "input_snapshot_hash": selected["input_snapshot_hash"],
        "outcome_anchor": selected["historical_as_of_timestamp"],
        "horizons": horizons,
        "maximum_adverse_excursion": _measurement(raw["maximum_adverse_excursion"], unit=outcome_unit, anchor=selected["historical_as_of_timestamp"], cutoff=cutoff, evidence_records=evidence_records, kind="maximum_adverse_excursion"),
        "maximum_favourable_excursion": _measurement(raw["maximum_favourable_excursion"], unit=outcome_unit, anchor=selected["historical_as_of_timestamp"], cutoff=cutoff, evidence_records=evidence_records, kind="maximum_favourable_excursion"),
        "recovery_time": _measurement(raw["recovery_time"], unit="TRADING_SESSIONS", anchor=selected["historical_as_of_timestamp"], cutoff=cutoff, evidence_records=evidence_records, kind="recovery_time"),
    }


def _coverage(attachments):
    horizon_counts = {horizon: 0 for horizon in HORIZONS}
    measurement_counts = {f"{horizon}.{name}": 0 for horizon in HORIZONS for name in RETURN_NAMES}
    for attachment in attachments:
        for horizon in HORIZONS:
            available = []
            for name in RETURN_NAMES:
                is_available = attachment["horizons"][horizon][name]["status"] == "AVAILABLE"
                measurement_counts[f"{horizon}.{name}"] += int(is_available)
                available.append(is_available)
            horizon_counts[horizon] += int(all(available))
    return {
        "available_horizon_counts": horizon_counts,
        "available_measurement_counts": measurement_counts,
        "mae_available_count": sum(item["maximum_adverse_excursion"]["status"] == "AVAILABLE" for item in attachments),
        "mfe_available_count": sum(item["maximum_favourable_excursion"]["status"] == "AVAILABLE" for item in attachments),
        "recovery_available_count": sum(item["recovery_time"]["status"] == "AVAILABLE" for item in attachments),
    }


def build_outcome_attachment(*, selection, payloads, outcome_unit, evidence_records, policy, policy_hash, outcome_definition_hash):
    if outcome_unit not in policy["supported_outcome_units"]:
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_UNIT_INVALID")
    selected = selection["selected_analogues"]
    if not isinstance(payloads, list):
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_PAYLOADS_INVALID")
    ids = [payload.get("analogue_id") for payload in payloads if isinstance(payload, dict)]
    expected_ids = [item["analogue_id"] for item in selected]
    if len(ids) != len(payloads) or len(ids) != len(set(ids)):
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_DUPLICATE_ATTACHMENT_ID")
    if set(ids) != set(expected_ids):
        raise Stage6AnalogueOutcomeError("ANALOGUE_OUTCOME_SELECTED_COVERAGE_INVALID")
    payload_by_id = {item["analogue_id"]: item for item in payloads}
    attachments = [_attachment(item, payload_by_id[item["analogue_id"]], rank=rank, outcome_unit=outcome_unit, cutoff=selection["target_selection_cutoff"], evidence_records=evidence_records) for rank, item in enumerate(selected, 1)]
    evidence_bindings = sorted({(binding["evidence_id"], binding["evidence_hash"]) for attachment in attachments for measurement in list(attachment["horizons"].values()) + [{"mae": attachment["maximum_adverse_excursion"], "mfe": attachment["maximum_favourable_excursion"], "recovery": attachment["recovery_time"]}] for value in measurement.values() for binding in value["evidence_bindings"]})
    core = {
        "schema_version": SCHEMA_VERSION,
        "selection_record_id": selection["selection_record_id"],
        "selection_record_hash": selection["record_hash"],
        "selection_engine_commit": SELECTION_ENGINE_COMMIT,
        "selection_spec_hash": selection["selection_spec_hash"],
        "candidate_universe_hash": selection["candidate_universe_hash"],
        "target_feature_snapshot_id": selection["target_feature_snapshot_id"],
        "target_feature_snapshot_hash": selection["target_feature_snapshot_hash"],
        "target_selection_input_hash": selection["target_selection_input_hash"],
        "target_as_of_timestamp": selection["target_as_of_timestamp"],
        "target_selection_cutoff": selection["target_selection_cutoff"],
        "selected_analogue_count": selection["analogue_count"],
        "minimum_required_analogue_count": selection["minimum_required_analogue_count"],
        "outcome_definition_version": OUTCOME_DEFINITION_VERSION,
        "outcome_definition_hash": outcome_definition_hash,
        "policy_id": policy["policy_id"],
        "policy_hash": policy_hash,
        "processor_version": policy["processor_version"],
        "authority": policy["authority"],
        "outcome_unit": outcome_unit,
        "analogue_attachments": attachments,
        "evidence_bindings": [{"evidence_id": item[0], "evidence_hash": item[1]} for item in evidence_bindings],
        "coverage_summary": _coverage(attachments),
        "attachment_coverage_status": "NO_SELECTED_ANALOGUES" if not selected else "COMPLETE",
        "pit_verified": True,
        "leakage_status": "PASS",
        **SAFETY,
    }
    attachment_hash = canonical_hash(core)
    record = {**core, "attachment_set_id": "S6ANOUT_" + attachment_hash[:24], "attachment_set_hash": attachment_hash, "logical_attachment_key": "S6ANOUTLOG_" + canonical_hash({"selection_record_id": selection["selection_record_id"], "policy_hash": policy_hash, "outcome_definition_hash": outcome_definition_hash})[:24], "record_hash": "0" * 64}
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
