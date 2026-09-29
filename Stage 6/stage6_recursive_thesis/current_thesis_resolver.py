import json

from stage6_trade_thesis_version.trade_thesis_version_validation import validate_version_record
from .errors import Stage6RecursiveThesisError, RecursiveThesisIntegrityFailure
from .policy import SOURCE_TYPES, WRAPPER_SCHEMA, AUTHORITY


def _require_integrity(store, code):
    if store is None:
        raise RecursiveThesisIntegrityFailure(code)
    try:
        result = store.integrity_check()
    except Exception as exc:
        raise RecursiveThesisIntegrityFailure(code) from exc
    if result.get("result") != "PASS":
        raise RecursiveThesisIntegrityFailure(code)


def resolve_stage6e(stage6e_store, version_record_id):
    _require_integrity(stage6e_store, "STAGE6_6E_SOURCE_INTEGRITY_REQUIRED")
    row = stage6e_store.connection.execute(
        "SELECT canonical_json FROM trade_thesis_version_records WHERE version_record_id=?", (version_record_id,)
    ).fetchone()
    if row is None:
        raise Stage6RecursiveThesisError("CURRENT_STAGE6_6E_VERSION_NOT_FOUND")
    wrapper = json.loads(row[0])
    assessment_id = wrapper["assessment_binding"]["record_id"]
    previous, snapshot, assessment = stage6e_store._chain(assessment_id)
    validate_version_record(wrapper, previous, snapshot, assessment, stage6e_store.policy_hash, stage6e_store.contract_hash)
    thesis = wrapper["trade_thesis"]
    if thesis["version"] != 2 or thesis["authority_mode"] != AUTHORITY:
        raise RecursiveThesisIntegrityFailure("CURRENT_STAGE6_6E_IDENTITY_INVALID")
    return wrapper, thesis


def validate_source_request(source, version_record_id):
    if source not in SOURCE_TYPES:
        raise Stage6RecursiveThesisError("CURRENT_THESIS_SOURCE_INVALID")
    if not isinstance(version_record_id, str) or not version_record_id:
        raise Stage6RecursiveThesisError("CURRENT_VERSION_RECORD_ID_REQUIRED")
    return True


def resolve_current(source, version_record_id, stage6e_store, recursive_store):
    validate_source_request(source, version_record_id)
    if source == "STAGE6_6E":
        return resolve_stage6e(stage6e_store, version_record_id)
    recursive_store.integrity_check()
    row = recursive_store.connection.execute(
        "SELECT canonical_json FROM recursive_thesis_versions WHERE version_record_id=?", (version_record_id,)
    ).fetchone()
    if row is None:
        raise Stage6RecursiveThesisError("CURRENT_STAGE6_6F_VERSION_NOT_FOUND")
    wrapper = json.loads(row[0])
    thesis = wrapper["trade_thesis"]
    if wrapper.get("schema_version") != WRAPPER_SCHEMA or type(thesis.get("version")) is not int or thesis["version"] < 3 or thesis.get("authority_mode") != AUTHORITY:
        raise RecursiveThesisIntegrityFailure("CURRENT_STAGE6_6F_IDENTITY_INVALID")
    return wrapper, thesis
