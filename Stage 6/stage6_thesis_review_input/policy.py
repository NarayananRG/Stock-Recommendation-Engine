import hashlib,json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import ThesisReviewInputIntegrityFailure

SCHEMA_VERSION="STAGE6_THESIS_REVIEW_INPUT_SNAPSHOT_V1";STORE_SCHEMA_VERSION="STAGE6_6C_THESIS_REVIEW_INPUT_STORE_V1";PROCESSOR_VERSION="STAGE6_6C_THESIS_REVIEW_INPUT_FREEZER_V1";POLICY_ID="S6THREVINPOL_STAGE6_6C_V1";CONTRACT_VERSION="STAGE6_THESIS_REVIEW_INPUT_CONTRACT_V1";AUTHORITY="SHADOW_ONLY";BASELINE_COMMIT="eac8ae133acb712fbe2777ad025ed98b9d0c05f8"
TRADE_THESIS_SCHEMA="STAGE6_TRADE_THESIS_V2";TRADE_THESIS_BLOB="2cc390a2cb85d938062511408293adcaf84ea288";MARKET_SCHEMA="STAGE6_MARKET_CONTEXT_V2";MARKET_BLOB="a141b221228718b8276b3d05b2f028d21adcfc3f";ANALOGUE_SCHEMA="STAGE6_HISTORICAL_ANALOGUE_V2";ANALOGUE_BLOB="85a2b0d00cacd6a3caea484e3ef3071eb16fe01d";PORTFOLIO_SCHEMA="STAGE6_PORTFOLIO_CONTEXT_V2";PORTFOLIO_BLOB="5900278a891dc70c63ce02f69002b5e9dec13799";COMPANY_EFFECT_SCHEMA="STAGE6_EVENT_COMPANY_EFFECT_V1";EVIDENCE_SCHEMA="STAGE6_EVIDENCE_V2"
EXPECTED_POLICY_HASH_V1="19bd78286ae13c08beb63640aa6784203ac19daab60e8c06fc57bd8f59d45c5a";EXPECTED_CONTRACT_HASH_V1="6cfeb431a74ef6cdef6305cd2880f9488de380b246a65c13b1b4ed6165dfef7d"
def git_blob(path):
 data=Path(path).read_bytes();return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def _load(name,expected):
 value=json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"));digest=canonical_hash(value)
 if expected!="TO_BE_COMPUTED" and digest!=expected:raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_CONFIGURATION_HASH_INVALID")
 return value,canonical_json(value),digest
def _blobs():
 root=Path(__file__).resolve().parents[1]/"contracts"
 expected={"trade_thesis.schema.json":TRADE_THESIS_BLOB,"market_context.schema.json":MARKET_BLOB,"historical_analogue.schema.json":ANALOGUE_BLOB,"portfolio_context.schema.json":PORTFOLIO_BLOB}
 if any(git_blob(root/name)!=digest for name,digest in expected.items()):raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_FROZEN_SCHEMA_CHANGED")
def load_policy():
 value,text,digest=_load("thesis_review_input_policy_v1.json",EXPECTED_POLICY_HASH_V1);_blobs()
 if tuple(value.get(k) for k in ("policy_id","processor_version","development_baseline","authority"))!=(POLICY_ID,PROCESSOR_VERSION,BASELINE_COMMIT,AUTHORITY):raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_POLICY_INVALID")
 return value,text,digest
def load_contract():
 value,text,digest=_load("thesis_review_input_contract_v1.json",EXPECTED_CONTRACT_HASH_V1)
 if tuple(value.get(k) for k in ("contract_version","schema_version","store_schema_version","authority"))!=(CONTRACT_VERSION,SCHEMA_VERSION,STORE_SCHEMA_VERSION,AUTHORITY):raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_CONTRACT_INVALID")
 return value,text,digest
