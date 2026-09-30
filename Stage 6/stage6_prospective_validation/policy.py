import json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import ProspectiveIntegrityFailure

PROTOCOL_ID="STAGE6_PROSPECTIVE_VALIDATION_PROTOCOL_V1";ACTIVATION_SCHEMA="STAGE6_PROSPECTIVE_ACTIVATION_V1";SESSION_SCHEMA="STAGE6_PROSPECTIVE_SESSION_ENROLLMENT_V1";CASE_SCHEMA="STAGE6_PROSPECTIVE_CASE_ENROLLMENT_V1";STORE_SCHEMA="STAGE6_8A_PROSPECTIVE_VALIDATION_STORE_V1";PROCESSOR="STAGE6_8A_PROSPECTIVE_VALIDATION_ENROLLER_V1";POLICY_ID="S6PROSVALPOL_STAGE6_8A_V1";CONTRACT_VERSION="STAGE6_PROSPECTIVE_VALIDATION_ENROLLMENT_CONTRACT_V1";AUTHORITY="SHADOW_ONLY";BASELINE="241256fa5e27838b40367dce24ae39fba88d3cee";BRANCH="stage6-prospective-shadow-validation";CONTROL_TAG="stage5d5-live-paper-runner-baseline";CONTROL_COMMIT="74b2710f0e19bd403978da81e87f25a3059ace06";CONTROL_SCHEMA="STAGE5D5_SCHEMA_V1";COMPONENT="MORNING_REVALIDATION_V1";MINIMUM_SESSIONS=20
SHADOW_SCHEMA="STAGE6_MORNING_REVALIDATION_PROPOSAL_V1";SHADOW_POLICY="S6MRPROPPOL_STAGE6_7B_V1";SHADOW_POLICY_HASH="998a527039f4c203ad4dfe1a628eea32c66a3e6082e3e10e206c5da10de5000d";SHADOW_CONTRACT="STAGE6_MORNING_REVALIDATION_PROPOSAL_CONTRACT_V1";SHADOW_CONTRACT_HASH="5cd2a04126e39e72afb177e46478539ef2892601010335e1f0588c34c8a59140";SHADOW_ENGINE="STAGE6_MORNING_REVALIDATION_RULES_V1";SHADOW_CODE_HASH="ecb321e2c2a351a7b201178da31f8b5fb1f68c55964c9410d4edb06cfdc3e277"
EXPECTED_PROTOCOL_HASH="6f769ef1799bbac7084f4a60f9ff879db9c223f1420d1f905c6f899862b8084f";EXPECTED_POLICY_HASH="74a7655d8ffb34483b8b66197a2d46a66cbe35022a32b0de72fca9a05d743a40";EXPECTED_CONTRACT_HASH="106c4001a98acc6eb036791342c48af0c568e655fe99d8fdddf3185e73adf644"
CASE_STATES={"CONTROL_ONLY_PENDING_SHADOW","PAIRED_SHADOW_AVAILABLE","SHADOW_OUTPUT_MISSING","INELIGIBLE_PRE_ACTIVATION","INVALID_CONTROL_EVIDENCE","INVALID_SHADOW_EVIDENCE"}
def _load(name,expected):
 value=json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"));digest=canonical_hash(value)
 if expected!="TO_BE_COMPUTED" and digest!=expected:raise ProspectiveIntegrityFailure("PROSPECTIVE_CONFIGURATION_HASH_INVALID")
 return value,canonical_json(value),digest
def load_protocol():
 v,t,h=_load("prospective_validation_protocol_v1.json",EXPECTED_PROTOCOL_HASH)
 if (v.get("protocol_id"),v.get("component_under_test"),v.get("minimum_completed_control_sessions"),v.get("performance_based_early_stopping"),v.get("authority"))!=(PROTOCOL_ID,COMPONENT,MINIMUM_SESSIONS,"PROHIBITED",AUTHORITY):raise ProspectiveIntegrityFailure("PROSPECTIVE_PROTOCOL_INVALID")
 return v,t,h
def load_policy():
 v,t,h=_load("prospective_validation_policy_v1.json",EXPECTED_POLICY_HASH)
 if tuple(v.get(k) for k in ("policy_id","processor_version","development_baseline","branch","stage5d_control_tag","stage5d_control_commit","authority"))!=(POLICY_ID,PROCESSOR,BASELINE,BRANCH,CONTROL_TAG,CONTROL_COMMIT,AUTHORITY):raise ProspectiveIntegrityFailure("PROSPECTIVE_POLICY_INVALID")
 return v,t,h
def load_contract():
 v,t,h=_load("prospective_validation_enrollment_contract_v1.json",EXPECTED_CONTRACT_HASH)
 if tuple(v.get(k) for k in ("contract_version","activation_schema","session_schema","case_schema","store_schema","processor_version","control_schema","shadow_schema","authority"))!=(CONTRACT_VERSION,ACTIVATION_SCHEMA,SESSION_SCHEMA,CASE_SCHEMA,STORE_SCHEMA,PROCESSOR,CONTROL_SCHEMA,SHADOW_SCHEMA,AUTHORITY):raise ProspectiveIntegrityFailure("PROSPECTIVE_CONTRACT_INVALID")
 return v,t,h
