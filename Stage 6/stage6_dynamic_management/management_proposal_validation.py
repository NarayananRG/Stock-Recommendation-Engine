from decimal import Decimal, InvalidOperation

from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from .errors import Stage6DynamicManagementError, DynamicManagementIntegrityFailure
from .management_proposal_builder import SAFETY, build_proposal, canonical_support, factual_changes, thesis_binding
from .policy import *

PROPOSAL_FIELDS = {
    "schema_version", "proposal_id", "thesis_id", "thesis_version", "current_thesis_source", "current_version_record_id",
    "current_thesis_binding", "bound_review_snapshot_binding", "bound_review_assessment_binding", "proposal_cutoff", "thesis_status",
    "proposal_mode", "current_stop", "proposed_stop", "current_target", "proposed_target", "reason_code", "supporting_bindings",
    "factual_change_metadata", "processor_version", "policy_id", "policy_hash", "contract_version", "contract_hash", "authority",
    *SAFETY.keys(), "record_hash",
}


def validate_price(value):
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {"value", "currency"} or value.get("currency") != "INR":
        raise Stage6DynamicManagementError("PRICE_STRUCTURE_INVALID")
    amount = value.get("value")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise Stage6DynamicManagementError("PRICE_VALUE_INVALID")
    try:
        decimal = Decimal(str(amount))
    except InvalidOperation as exc:
        raise Stage6DynamicManagementError("PRICE_VALUE_INVALID") from exc
    if not decimal.is_finite() or decimal <= 0:
        raise Stage6DynamicManagementError("PRICE_VALUE_INVALID")
    return True


def _same(left, right):
    return canonical_json(left) == canonical_json(right)


def validate_mode(mode, current_stop, proposed_stop, current_target, proposed_target):
    if mode not in PROPOSAL_MODES:
        raise Stage6DynamicManagementError("PROPOSAL_MODE_INVALID")
    for price in (current_stop, proposed_stop, current_target, proposed_target):
        validate_price(price)
    stop_changed = not _same(current_stop, proposed_stop); target_changed = not _same(current_target, proposed_target)
    expected = {
        "NO_CHANGE": (False, False), "STOP_CHANGE": (True, False),
        "TARGET_CHANGE": (False, True), "STOP_AND_TARGET_CHANGE": (True, True),
    }[mode]
    if (stop_changed, target_changed) != expected:
        raise Stage6DynamicManagementError("PROPOSAL_MODE_LEVEL_MISMATCH")
    return True


def provenance_universe(thesis, snapshot, assessment):
    direct = snapshot.get("direct_input_bindings")
    if not isinstance(direct, list):
        raise DynamicManagementIntegrityFailure("BOUND_REVIEW_INPUTS_INVALID")
    values = [
        thesis_binding(thesis),
        {"record_type": snapshot["schema_version"], "record_id": snapshot["review_snapshot_id"], "record_hash": snapshot["record_hash"]},
        {"record_type": assessment["schema_version"], "record_id": assessment["assessment_id"], "record_hash": assessment["record_hash"]},
        *direct,
    ]
    return {tuple(item[key] for key in ("record_type", "record_id", "record_hash")) for item in values}


def validate_request(*, thesis, snapshot, assessment, proposal_cutoff, proposal_mode, proposed_stop, proposed_target, reason_code, supporting_bindings):
    if proposal_cutoff != thesis["decision_cutoff"]:
        raise Stage6DynamicManagementError("PROPOSAL_CUTOFF_MUST_EQUAL_THESIS_CUTOFF")
    validate_mode(proposal_mode, thesis["current_stop"], proposed_stop, thesis["current_target"], proposed_target)
    if reason_code not in REASON_CODES:
        raise Stage6DynamicManagementError("PROPOSAL_REASON_CODE_INVALID")
    supports = canonical_support(supporting_bindings)
    if proposal_mode != "NO_CHANGE" and not supports:
        raise Stage6DynamicManagementError("CHANGE_PROPOSAL_SUPPORT_REQUIRED")
    universe = provenance_universe(thesis, snapshot, assessment)
    for item in supports:
        key = tuple(item[field] for field in ("record_type", "record_id", "record_hash"))
        if item["record_type"] not in SUPPORT_TYPES or key not in universe:
            raise Stage6DynamicManagementError("SUPPORT_OUTSIDE_BOUND_PROVENANCE")
    return supports


def validate_proposal(record, source, source_record_id, thesis, snapshot, assessment, policy_hash, contract_hash):
    if not isinstance(record, dict) or set(record) != PROPOSAL_FIELDS:
        raise DynamicManagementIntegrityFailure("PROPOSAL_FIELDS_INVALID")
    validate_request(thesis=thesis, snapshot=snapshot, assessment=assessment, proposal_cutoff=record["proposal_cutoff"], proposal_mode=record["proposal_mode"], proposed_stop=record["proposed_stop"], proposed_target=record["proposed_target"], reason_code=record["reason_code"], supporting_bindings=record["supporting_bindings"])
    expected = build_proposal(source=source, source_record_id=source_record_id, thesis=thesis, snapshot=snapshot, assessment=assessment, proposal_cutoff=record["proposal_cutoff"], proposal_mode=record["proposal_mode"], proposed_stop=record["proposed_stop"], proposed_target=record["proposed_target"], reason_code=record["reason_code"], supporting_bindings=record["supporting_bindings"], policy_hash=policy_hash, contract_hash=contract_hash)
    if record != expected or record["record_hash"] != canonical_hash(without(record, "record_hash")):
        raise DynamicManagementIntegrityFailure("PROPOSAL_REPLAY_MISMATCH")
    if record["factual_change_metadata"] != factual_changes(thesis["current_stop"], record["proposed_stop"], thesis["current_target"], record["proposed_target"]):
        raise DynamicManagementIntegrityFailure("PROPOSAL_FACTUAL_DELTA_INVALID")
    return True
