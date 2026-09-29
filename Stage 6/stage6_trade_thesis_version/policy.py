import hashlib
import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import TradeThesisVersionIntegrityFailure

SCHEMA_VERSION = "STAGE6_TRADE_THESIS_V2"
WRAPPER_SCHEMA_VERSION = "STAGE6_6E_TRADE_THESIS_VERSION_RECORD_V1"
STORE_SCHEMA_VERSION = "STAGE6_6E_TRADE_THESIS_VERSION_STORE_V1"
PROCESSOR_VERSION = "STAGE6_6E_TRADE_THESIS_VERSION_MATERIALIZER_V1"
POLICY_ID = "S6THVERPOL_STAGE6_6E_V1"
CONTRACT_VERSION = "STAGE6_TRADE_THESIS_VERSION_MATERIALIZATION_CONTRACT_V1"
THESIS_ENGINE_VERSION = "STAGE6_THESIS_MATERIAL_CHANGE_RULES_V1"
AUTHORITY = "SHADOW_ONLY"
DEVELOPMENT_BASELINE = "16346dee8270135a7f43f1140f920531d33f6cbd"
RUNTIME_SEMANTIC_COMMIT = "3b094f4167e78de7699742080e0a163e7550bc0e"
TRADE_THESIS_BLOB = "2cc390a2cb85d938062511408293adcaf84ea288"
PREVIOUS_SCHEMA = "STAGE6_TRADE_THESIS_V2"
SNAPSHOT_SCHEMA = "STAGE6_THESIS_REVIEW_INPUT_SNAPSHOT_V1"
ASSESSMENT_SCHEMA = "STAGE6_THESIS_REVIEW_ASSESSMENT_V1"
ELIGIBLE_STATUSES = {
    "THESIS_STRENGTHENED",
    "THESIS_UNCHANGED",
    "THESIS_WEAKENED",
    "THESIS_INVALIDATED",
}
CHANGE_TYPES = {
    "THESIS_STRENGTHENED": "THESIS_STRENGTHENED_REVIEW",
    "THESIS_UNCHANGED": "THESIS_REVIEWED_UNCHANGED",
    "THESIS_WEAKENED": "THESIS_WEAKENED_REVIEW",
    "THESIS_INVALIDATED": "THESIS_INVALIDATED_REVIEW",
}
EXPECTED_POLICY_HASH_V1 = "8c565125e7eeed5d456b52ff9c0d858e3af37dd39749145bfe258bd0a6380ef1"
EXPECTED_CONTRACT_HASH_V1 = "a8254cc2035bd6e22386919c0dfac5fab8a7a9c02982280126a62282124307ab"


def git_blob(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _load(name, expected):
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if expected != "TO_BE_COMPUTED" and digest != expected:
        raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def load_policy():
    value, text, digest = _load("trade_thesis_version_policy_v1.json", EXPECTED_POLICY_HASH_V1)
    wanted = (POLICY_ID, PROCESSOR_VERSION, DEVELOPMENT_BASELINE, RUNTIME_SEMANTIC_COMMIT, THESIS_ENGINE_VERSION, AUTHORITY)
    actual = tuple(value.get(key) for key in ("policy_id", "processor_version", "development_baseline", "runtime_semantic_commit", "thesis_engine_version", "authority"))
    if actual != wanted:
        raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_POLICY_INVALID")
    schema = Path(__file__).resolve().parents[1] / "contracts" / "trade_thesis.schema.json"
    if git_blob(schema) != TRADE_THESIS_BLOB:
        raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_FROZEN_SCHEMA_CHANGED")
    return value, text, digest


def load_contract():
    value, text, digest = _load("trade_thesis_version_materialization_contract_v1.json", EXPECTED_CONTRACT_HASH_V1)
    wanted = (CONTRACT_VERSION, WRAPPER_SCHEMA_VERSION, SCHEMA_VERSION, STORE_SCHEMA_VERSION, PROCESSOR_VERSION, THESIS_ENGINE_VERSION, RUNTIME_SEMANTIC_COMMIT, AUTHORITY)
    actual = tuple(value.get(key) for key in ("contract_version", "wrapper_schema_version", "payload_schema_version", "store_schema_version", "processor_version", "thesis_engine_version", "runtime_semantic_commit", "authority"))
    if actual != wanted:
        raise TradeThesisVersionIntegrityFailure("TRADE_THESIS_VERSION_CONTRACT_INVALID")
    return value, text, digest
