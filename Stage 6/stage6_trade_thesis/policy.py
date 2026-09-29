import hashlib
import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import TradeThesisIntegrityFailure

SCHEMA_VERSION="STAGE6_TRADE_THESIS_V2"
WRAPPER_SCHEMA_VERSION="STAGE6_6B_TRADE_THESIS_MATERIALIZATION_RECORD_V1"
STORE_SCHEMA_VERSION="STAGE6_6B_TRADE_THESIS_STORE_V1"
PROCESSOR_VERSION="STAGE6_6B_INITIAL_THESIS_MATERIALIZER_V1"
POLICY_ID="S6THMATPOL_STAGE6_6B_V1"
MATERIALIZATION_CONTRACT_VERSION="STAGE6_INITIAL_THESIS_MATERIALIZATION_CONTRACT_V1"
THESIS_ENGINE_VERSION="STAGE6_INITIAL_THESIS_SEMANTICS_V1"
SEED_SCHEMA_VERSION="STAGE6_INITIAL_THESIS_SEED_V1"
AUTHORITY="SHADOW_ONLY"
BASELINE_COMMIT="1672ab7ed7322b8dc4406ab5ea556325977bc8cd"
TRADE_THESIS_BLOB="2cc390a2cb85d938062511408293adcaf84ea288"
EXPECTED_POLICY_HASH_V1="442121024d87770aff31ed8f48c5e38e24befc90e76571e949b616fa57f5597a"
EXPECTED_MATERIALIZATION_CONTRACT_HASH_V1="0ede3b7df01144028d27b339fb32b2251aed4fe486e762f08d276b2e01a1830b"

def git_blob(path):
    data=Path(path).read_bytes()
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def _load(name,expected):
    value=json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"));digest=canonical_hash(value)
    if expected!="TO_BE_COMPUTED" and digest!=expected:raise TradeThesisIntegrityFailure("TRADE_THESIS_CONFIGURATION_HASH_INVALID")
    return value,canonical_json(value),digest

def load_policy():
    value,text,digest=_load("initial_trade_thesis_policy_v1.json",EXPECTED_POLICY_HASH_V1)
    if tuple(value.get(k) for k in ("policy_id","processor_version","development_baseline","thesis_engine_version","authority"))!=(POLICY_ID,PROCESSOR_VERSION,BASELINE_COMMIT,THESIS_ENGINE_VERSION,AUTHORITY):raise TradeThesisIntegrityFailure("TRADE_THESIS_POLICY_INVALID")
    schema=Path(__file__).resolve().parents[1]/"contracts"/"trade_thesis.schema.json"
    if git_blob(schema)!=TRADE_THESIS_BLOB:raise TradeThesisIntegrityFailure("TRADE_THESIS_FROZEN_SCHEMA_CHANGED")
    return value,text,digest

def load_materialization_contract():
    value,text,digest=_load("initial_trade_thesis_materialization_contract_v1.json",EXPECTED_MATERIALIZATION_CONTRACT_HASH_V1)
    expected=(MATERIALIZATION_CONTRACT_VERSION,SCHEMA_VERSION,WRAPPER_SCHEMA_VERSION,STORE_SCHEMA_VERSION,THESIS_ENGINE_VERSION,AUTHORITY)
    if tuple(value.get(k) for k in ("contract_version","schema_version","wrapper_schema_version","store_schema_version","thesis_engine_version","authority"))!=expected:raise TradeThesisIntegrityFailure("TRADE_THESIS_CONTRACT_INVALID")
    return value,text,digest
