import hashlib
import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import RecursiveThesisIntegrityFailure

REVIEW_SCHEMA = "STAGE6_RECURSIVE_THESIS_REVIEW_INPUT_V1"
ASSESSMENT_SCHEMA = "STAGE6_RECURSIVE_THESIS_REVIEW_ASSESSMENT_V1"
WRAPPER_SCHEMA = "STAGE6_6F_RECURSIVE_TRADE_THESIS_VERSION_RECORD_V1"
STORE_SCHEMA = "STAGE6_6F_RECURSIVE_THESIS_STORE_V1"
PROCESSOR = "STAGE6_6F_RECURSIVE_THESIS_REVIEW_ENGINE_V1"
POLICY_ID = "S6THRECPOL_STAGE6_6F_V1"
CONTRACT_VERSION = "STAGE6_RECURSIVE_THESIS_REVIEW_CONTRACT_V1"
SEMANTICS = "STAGE6_THESIS_MATERIAL_CHANGE_RULES_V1"
SEMANTIC_COMMIT = "3b094f4167e78de7699742080e0a163e7550bc0e"
BASELINE = "11f90c3263476f9b396b2beefebcd4f3ddb147b7"
AUTHORITY = "SHADOW_ONLY"
THESIS_SCHEMA = "STAGE6_TRADE_THESIS_V2"
THESIS_BLOB = "2cc390a2cb85d938062511408293adcaf84ea288"
SOURCE_TYPES = {"STAGE6_6E", "STAGE6_6F"}
AVAILABLE = {"AVAILABLE", "NOT_PROVIDED"}
SUPPORT_TYPES = {"STAGE6_EVIDENCE_V2", "STAGE6_EVENT_COMPANY_EFFECT_V1", "STAGE6_MARKET_CONTEXT_V2", "STAGE6_HISTORICAL_ANALOGUE_V2", "STAGE6_PORTFOLIO_CONTEXT_V2"}
INVALIDATION_STATES = {"TRIGGERED", "NOT_TRIGGERED", "NOT_EVALUATED"}
ASSERTION_STATES = {"SUPPORTIVE_MATERIAL", "ADVERSE_MATERIAL", "NON_MATERIAL", "INDETERMINATE"}
REASON_CODES = {"NEW_EVIDENCE", "COMPANY_EFFECT", "MARKET_CONTEXT", "HISTORICAL_ANALOGUE", "PORTFOLIO_CONTEXT", "INVALIDATION_CONDITION", "MULTI_SOURCE_REVIEW"}
CHANGE_TYPES = {"THESIS_STRENGTHENED": "THESIS_STRENGTHENED_REVIEW", "THESIS_UNCHANGED": "THESIS_REVIEWED_UNCHANGED", "THESIS_WEAKENED": "THESIS_WEAKENED_REVIEW", "THESIS_INVALIDATED": "THESIS_INVALIDATED_REVIEW"}
EXPECTED_POLICY_HASH = "b5e7c05a71f2bd0872791d9a447f02af73de5851d5811db9026f796bb60fc38d"
EXPECTED_CONTRACT_HASH = "27d4b49a172f08a852720435cdbb3a0015f48058eade1d6155357fa45d073f24"


def git_blob(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _load(name, expected):
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if expected != "TO_BE_COMPUTED" and digest != expected:
        raise RecursiveThesisIntegrityFailure("RECURSIVE_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def load_policy():
    value, text, digest = _load("recursive_thesis_policy_v1.json", EXPECTED_POLICY_HASH)
    wanted = (POLICY_ID, PROCESSOR, BASELINE, SEMANTIC_COMMIT, SEMANTICS, AUTHORITY)
    actual = tuple(value.get(key) for key in ("policy_id", "processor_version", "development_baseline", "semantic_code_commit", "decision_semantics", "authority"))
    if actual != wanted or value.get("current_source_types") != ["STAGE6_6E", "STAGE6_6F"] or value.get("automatic_current_selection") is not False:
        raise RecursiveThesisIntegrityFailure("RECURSIVE_POLICY_INVALID")
    schema = Path(__file__).resolve().parents[1] / "contracts" / "trade_thesis.schema.json"
    if git_blob(schema) != THESIS_BLOB:
        raise RecursiveThesisIntegrityFailure("TRADE_THESIS_FROZEN_SCHEMA_CHANGED")
    return value, text, digest


def load_contract():
    value, text, digest = _load("recursive_thesis_contract_v1.json", EXPECTED_CONTRACT_HASH)
    wanted = (CONTRACT_VERSION, REVIEW_SCHEMA, ASSESSMENT_SCHEMA, WRAPPER_SCHEMA, STORE_SCHEMA, PROCESSOR, SEMANTICS, SEMANTIC_COMMIT, THESIS_SCHEMA, THESIS_BLOB, AUTHORITY)
    actual = tuple(value.get(key) for key in ("contract_version", "review_schema", "assessment_schema", "wrapper_schema", "store_schema", "processor_version", "decision_semantics", "semantic_code_commit", "trade_thesis_schema", "trade_thesis_schema_blob", "authority"))
    if actual != wanted:
        raise RecursiveThesisIntegrityFailure("RECURSIVE_CONTRACT_INVALID")
    return value, text, digest
