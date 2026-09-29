import hashlib
import json
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import ThesisSeedIntegrityFailure

SCHEMA_VERSION="STAGE6_INITIAL_THESIS_SEED_V1"
STORE_SCHEMA_VERSION="STAGE6_6A_INITIAL_THESIS_SEED_STORE_V1"
PROCESSOR_VERSION="STAGE6_6A_INITIAL_THESIS_SEED_FREEZER_V1"
POLICY_ID="S6THSEEDPOL_STAGE6_6A_V1"
SEED_CONTRACT_VERSION="STAGE6_INITIAL_THESIS_SEED_CONTRACT_V1"
SEMANTIC_PROJECTION_VERSION="STAGE6_INITIAL_THESIS_SEMANTICS_V1"
AUTHORITY="SHADOW_ONLY"
BASELINE_COMMIT="8696e7aa4e179cbe4f4fd2413d79643299260f97"
STAGE5D5_COMMIT="74b2710f0e19bd403978da81e87f25a3059ace06"
TRADE_THESIS_BLOB="2cc390a2cb85d938062511408293adcaf84ea288"
EXPECTED_POLICY_HASH_V1="81b02ab33eb8709f8c6a10556d63b218b4831db4f448ea7f4926140010b09bcf"
EXPECTED_SEED_CONTRACT_HASH_V1="e8bcbfb921c20a42e925eff22174be17c530b197f8b657dc4c506a1d79b20391"

def git_blob(path):
    data=Path(path).read_bytes()
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def _load(name,expected):
    value=json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
    digest=canonical_hash(value)
    if expected!="TO_BE_COMPUTED" and digest!=expected:
        raise ThesisSeedIntegrityFailure("THESIS_SEED_CONFIGURATION_HASH_INVALID")
    return value,canonical_json(value),digest

def load_policy():
    value,text,digest=_load("initial_thesis_seed_policy_v1.json",EXPECTED_POLICY_HASH_V1)
    if tuple(value.get(k) for k in ("policy_id","processor_version","development_baseline","authority"))!=(POLICY_ID,PROCESSOR_VERSION,BASELINE_COMMIT,AUTHORITY):
        raise ThesisSeedIntegrityFailure("THESIS_SEED_POLICY_INVALID")
    schema=Path(__file__).resolve().parents[1]/"contracts"/"trade_thesis.schema.json"
    if git_blob(schema)!=TRADE_THESIS_BLOB:
        raise ThesisSeedIntegrityFailure("TRADE_THESIS_FROZEN_SCHEMA_CHANGED")
    return value,text,digest

def load_seed_contract():
    value,text,digest=_load("initial_thesis_seed_contract_v1.json",EXPECTED_SEED_CONTRACT_HASH_V1)
    if tuple(value.get(k) for k in ("contract_version","schema_version","semantic_projection_version","store_schema_version","authority"))!=(SEED_CONTRACT_VERSION,SCHEMA_VERSION,SEMANTIC_PROJECTION_VERSION,STORE_SCHEMA_VERSION,AUTHORITY):
        raise ThesisSeedIntegrityFailure("THESIS_SEED_CONTRACT_INVALID")
    return value,text,digest
