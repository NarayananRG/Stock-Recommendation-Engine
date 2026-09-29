import json

from stage6_recursive_thesis.current_thesis_resolver import resolve_stage6e
from .errors import Stage6DynamicManagementError, DynamicManagementIntegrityFailure
from .policy import AUTHORITY, SOURCE_TYPES


def _integrity(store, code):
    if store is None:
        raise DynamicManagementIntegrityFailure(code)
    try:
        result = store.integrity_check()
    except Exception as exc:
        raise DynamicManagementIntegrityFailure(code) from exc
    if result.get("result") != "PASS":
        raise DynamicManagementIntegrityFailure(code)


def validate_source_request(source, version_record_id):
    if source not in SOURCE_TYPES:
        raise Stage6DynamicManagementError("CURRENT_THESIS_SOURCE_INVALID")
    if not isinstance(version_record_id, str) or not version_record_id:
        raise Stage6DynamicManagementError("CURRENT_VERSION_RECORD_ID_REQUIRED")


def _binding(record_type, record_id, record_hash):
    return {"record_type": record_type, "record_id": record_id, "record_hash": record_hash}


def resolve_current(source, version_record_id, stage6e_store, recursive_store):
    validate_source_request(source, version_record_id)
    if source == "STAGE6_6E":
        try:
            wrapper, thesis = resolve_stage6e(stage6e_store, version_record_id)
            _, snapshot, assessment = stage6e_store._chain(wrapper["assessment_binding"]["record_id"])
        except Exception as exc:
            raise DynamicManagementIntegrityFailure("STAGE6_6E_SOURCE_INTEGRITY_REQUIRED") from exc
        review_binding = wrapper["review_snapshot_binding"]
        assessment_binding = wrapper["assessment_binding"]
        if review_binding != _binding("STAGE6_THESIS_REVIEW_INPUT_SNAPSHOT_V1", snapshot["review_snapshot_id"], snapshot["record_hash"]):
            raise DynamicManagementIntegrityFailure("STAGE6_6E_REVIEW_PROVENANCE_INVALID")
        if assessment_binding != _binding("STAGE6_THESIS_REVIEW_ASSESSMENT_V1", assessment["assessment_id"], assessment["record_hash"]):
            raise DynamicManagementIntegrityFailure("STAGE6_6E_ASSESSMENT_PROVENANCE_INVALID")
    else:
        _integrity(recursive_store, "STAGE6_6F_SOURCE_INTEGRITY_REQUIRED")
        row = recursive_store.connection.execute("SELECT canonical_json FROM recursive_thesis_versions WHERE version_record_id=?", (version_record_id,)).fetchone()
        if row is None:
            raise Stage6DynamicManagementError("CURRENT_STAGE6_6F_VERSION_NOT_FOUND")
        wrapper = json.loads(row[0]); thesis = wrapper["trade_thesis"]
        if type(thesis.get("version")) is not int or thesis["version"] < 3 or thesis.get("authority_mode") != AUTHORITY:
            raise DynamicManagementIntegrityFailure("CURRENT_STAGE6_6F_IDENTITY_INVALID")
        snapshot_row = recursive_store.connection.execute("SELECT canonical_json FROM recursive_review_snapshots WHERE review_snapshot_id=?", (wrapper["review_snapshot_binding"]["record_id"],)).fetchone()
        assessment_row = recursive_store.connection.execute("SELECT canonical_json FROM recursive_review_assessments WHERE assessment_id=?", (wrapper["assessment_binding"]["record_id"],)).fetchone()
        if snapshot_row is None or assessment_row is None:
            raise DynamicManagementIntegrityFailure("STAGE6_6F_REVIEW_PROVENANCE_MISSING")
        snapshot = json.loads(snapshot_row[0]); assessment = json.loads(assessment_row[0])
        review_binding = wrapper["review_snapshot_binding"]; assessment_binding = wrapper["assessment_binding"]
        if review_binding != _binding("STAGE6_RECURSIVE_THESIS_REVIEW_INPUT_V1", snapshot["review_snapshot_id"], snapshot["record_hash"]):
            raise DynamicManagementIntegrityFailure("STAGE6_6F_REVIEW_PROVENANCE_INVALID")
        if assessment_binding != _binding("STAGE6_RECURSIVE_THESIS_REVIEW_ASSESSMENT_V1", assessment["assessment_id"], assessment["record_hash"]):
            raise DynamicManagementIntegrityFailure("STAGE6_6F_ASSESSMENT_PROVENANCE_INVALID")
    if thesis.get("schema_version") != "STAGE6_TRADE_THESIS_V2" or thesis.get("authority_mode") != AUTHORITY:
        raise DynamicManagementIntegrityFailure("CURRENT_TRADE_THESIS_IDENTITY_INVALID")
    return wrapper, thesis, snapshot, assessment
