import hashlib, json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash, canonical_json
from .errors import MorningProposalIntegrityFailure

PROPOSAL_SCHEMA="STAGE6_MORNING_REVALIDATION_PROPOSAL_V1"
STORE_SCHEMA="STAGE6_7B_MORNING_REVALIDATION_PROPOSAL_STORE_V1"
PROCESSOR="STAGE6_7B_MORNING_REVALIDATION_PROPOSER_V1"
POLICY_ID="S6MRPROPPOL_STAGE6_7B_V1"
CONTRACT_VERSION="STAGE6_MORNING_REVALIDATION_PROPOSAL_CONTRACT_V1"
DECISION_ENGINE="STAGE6_MORNING_REVALIDATION_RULES_V1"
MANIFEST_VERSION="STAGE6_7B_DECISION_CODE_MANIFEST_V1"
BASELINE="66c6b7bdbc2fb3dd993e6a2900215a74d5f3c415"
INPUT_SCHEMA="STAGE6_MORNING_REVALIDATION_INPUT_SNAPSHOT_V1"
AUTHORITY="SHADOW_ONLY"
GENERIC_SHADOW_BLOB="d342a11ceef2f5643cb0e49cd789a9b8c3316fd6"
DECISIONS={"ENTRY_VALID","WAIT","CANCEL_ENTRY"}
INVALIDATION_STATUSES={"TRIGGERED","NOT_TRIGGERED","NOT_EVALUATED"}
ASSERTION_ASSESSMENTS={"SUPPORTIVE_MATERIAL","ADVERSE_MATERIAL","NON_MATERIAL","INDETERMINATE"}
ASSERTION_REASONS={"NEW_EVIDENCE","COMPANY_EFFECT","MARKET_CONTEXT","HISTORICAL_ANALOGUE","THESIS_STATE","MULTI_SOURCE_REVALIDATION"}
EXPECTED_POLICY_HASH="998a527039f4c203ad4dfe1a628eea32c66a3e6082e3e10e206c5da10de5000d"
EXPECTED_CONTRACT_HASH="5cd2a04126e39e72afb177e46478539ef2892601010335e1f0588c34c8a59140"

def git_blob(path):
 data=Path(path).read_bytes();return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def _load(name,expected):
 value=json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"));digest=canonical_hash(value)
 if expected!="TO_BE_COMPUTED" and digest!=expected:raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_CONFIGURATION_HASH_INVALID")
 return value,canonical_json(value),digest
def load_policy():
 value,text,digest=_load("morning_revalidation_proposal_policy_v1.json",EXPECTED_POLICY_HASH)
 if tuple(value.get(k) for k in ("policy_id","processor_version","decision_engine_version","development_baseline","authority"))!=(POLICY_ID,PROCESSOR,DECISION_ENGINE,BASELINE,AUTHORITY):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_POLICY_INVALID")
 return value,text,digest
def load_contract():
 value,text,digest=_load("morning_revalidation_proposal_contract_v1.json",EXPECTED_CONTRACT_HASH)
 if tuple(value.get(k) for k in ("contract_version","proposal_schema","store_schema","processor_version","decision_engine_version","decision_code_manifest_version","input_schema","authority"))!=(CONTRACT_VERSION,PROPOSAL_SCHEMA,STORE_SCHEMA,PROCESSOR,DECISION_ENGINE,MANIFEST_VERSION,INPUT_SCHEMA,AUTHORITY):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_CONTRACT_INVALID")
 return value,text,digest
