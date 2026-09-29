import hashlib
import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import DynamicManagementIntegrityFailure

PROPOSAL_SCHEMA = "STAGE6_DYNAMIC_MANAGEMENT_PROPOSAL_V1"
STORE_SCHEMA = "STAGE6_6G_DYNAMIC_MANAGEMENT_STORE_V1"
PROCESSOR = "STAGE6_6G_DYNAMIC_MANAGEMENT_PROPOSER_V1"
POLICY_ID = "S6MGMTPOPPOL_STAGE6_6G_V1"
CONTRACT_VERSION = "STAGE6_DYNAMIC_MANAGEMENT_PROPOSAL_CONTRACT_V1"
BASELINE = "db01e70880b9744f7383dcc1a8afabbf10fe70cd"
BASELINE_PARENT = "11f90c3263476f9b396b2beefebcd4f3ddb147b7"
AUTHORITY = "SHADOW_ONLY"
THESIS_SCHEMA = "STAGE6_TRADE_THESIS_V2"
THESIS_BLOB = "2cc390a2cb85d938062511408293adcaf84ea288"
SOURCE_TYPES = {"STAGE6_6E", "STAGE6_6F"}
PROPOSAL_MODES = {"NO_CHANGE", "STOP_CHANGE", "TARGET_CHANGE", "STOP_AND_TARGET_CHANGE"}
REASON_CODES = {
    "NO_CHANGE_REVIEW", "THESIS_STATUS_REVIEW", "RISK_CONTROL_REVIEW",
    "MARKET_CONTEXT_REVIEW", "PORTFOLIO_CONTEXT_REVIEW", "MULTI_SOURCE_MANAGEMENT_REVIEW",
}
SUPPORT_TYPES = {
    THESIS_SCHEMA,
    "STAGE6_THESIS_REVIEW_INPUT_SNAPSHOT_V1", "STAGE6_THESIS_REVIEW_ASSESSMENT_V1",
    "STAGE6_RECURSIVE_THESIS_REVIEW_INPUT_V1", "STAGE6_RECURSIVE_THESIS_REVIEW_ASSESSMENT_V1",
    "STAGE6_EVIDENCE_V2", "STAGE6_EVENT_COMPANY_EFFECT_V1", "STAGE6_MARKET_CONTEXT_V2",
    "STAGE6_HISTORICAL_ANALOGUE_V2", "STAGE6_PORTFOLIO_CONTEXT_V2",
}
EXPECTED_POLICY_HASH = "969dd43863c80b799e0458d3f4ac2aa418b7e70fd00ca79da5108ab75a0a0983"
EXPECTED_CONTRACT_HASH = "2f53cef597e6a4a99f4caefb76aa96f6c3934531f422c636f205292e4071860a"


def git_blob(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _load(name, expected):
    value = json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest = canonical_hash(value)
    if expected != "TO_BE_COMPUTED" and digest != expected:
        raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_CONFIGURATION_HASH_INVALID")
    return value, canonical_json(value), digest


def load_policy():
    value, text, digest = _load("dynamic_management_policy_v1.json", EXPECTED_POLICY_HASH)
    actual = tuple(value.get(key) for key in ("policy_id", "processor_version", "development_baseline", "authority"))
    if actual != (POLICY_ID, PROCESSOR, BASELINE, AUTHORITY):
        raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_POLICY_INVALID")
    if value.get("source_types") != ["STAGE6_6E", "STAGE6_6F"] or value.get("automatic_current_selection") is not False or value.get("automatic_proposal_generation") is not False:
        raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_POLICY_INVALID")
    schema = Path(__file__).resolve().parents[1] / "contracts" / "trade_thesis.schema.json"
    if git_blob(schema) != THESIS_BLOB:
        raise DynamicManagementIntegrityFailure("TRADE_THESIS_FROZEN_SCHEMA_CHANGED")
    return value, text, digest


def load_contract():
    value, text, digest = _load("dynamic_management_proposal_contract_v1.json", EXPECTED_CONTRACT_HASH)
    actual = tuple(value.get(key) for key in ("contract_version", "proposal_schema", "store_schema", "processor_version", "authority", "trade_thesis_schema", "trade_thesis_schema_blob"))
    if actual != (CONTRACT_VERSION, PROPOSAL_SCHEMA, STORE_SCHEMA, PROCESSOR, AUTHORITY, THESIS_SCHEMA, THESIS_BLOB):
        raise DynamicManagementIntegrityFailure("DYNAMIC_MANAGEMENT_CONTRACT_INVALID")
    return value, text, digest
