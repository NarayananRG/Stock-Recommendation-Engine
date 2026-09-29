import hashlib,json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import ThesisReviewAssessmentIntegrityFailure
SCHEMA_VERSION="STAGE6_THESIS_REVIEW_ASSESSMENT_V1";STORE_SCHEMA_VERSION="STAGE6_6D_THESIS_REVIEW_ASSESSMENT_STORE_V1";PROCESSOR_VERSION="STAGE6_6D_THESIS_REVIEW_ASSESSOR_V1";POLICY_ID="S6THREVASSPOL_STAGE6_6D_V1";CONTRACT_VERSION="STAGE6_THESIS_REVIEW_ASSESSMENT_CONTRACT_V1";DECISION_SEMANTICS_VERSION="STAGE6_THESIS_MATERIAL_CHANGE_RULES_V1";AUTHORITY="SHADOW_ONLY";BASELINE_COMMIT="ce37a7422a2e4723cf2dea515046ed447946a5eb";TRADE_THESIS_SCHEMA="STAGE6_TRADE_THESIS_V2";SNAPSHOT_SCHEMA="STAGE6_THESIS_REVIEW_INPUT_SNAPSHOT_V1";TRADE_THESIS_BLOB="2cc390a2cb85d938062511408293adcaf84ea288"
EXPECTED_POLICY_HASH_V1="b7d448703bc55f3fa057a573e3e81f816cf9ebf7b07ddb2722df79d65468d14d";EXPECTED_CONTRACT_HASH_V1="93090f6e1045c68fabdc82b75ee060d3140837889060e91e140f84f0897ad5b4"
ALLOWED_SUPPORT={"STAGE6_EVIDENCE_V2","STAGE6_EVENT_COMPANY_EFFECT_V1","STAGE6_MARKET_CONTEXT_V2","STAGE6_HISTORICAL_ANALOGUE_V2","STAGE6_PORTFOLIO_CONTEXT_V2"};INVALIDATION_STATUSES={"TRIGGERED","NOT_TRIGGERED","NOT_EVALUATED"};CHANGE_ASSESSMENTS={"SUPPORTIVE_MATERIAL","ADVERSE_MATERIAL","NON_MATERIAL","INDETERMINATE"};REASON_CODES={"NEW_EVIDENCE","COMPANY_EFFECT","MARKET_CONTEXT","HISTORICAL_ANALOGUE","PORTFOLIO_CONTEXT","INVALIDATION_CONDITION","MULTI_SOURCE_REVIEW"}
def git_blob(path):
 data=Path(path).read_bytes();return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def _load(name,expected):
 value=json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"));digest=canonical_hash(value)
 if expected!="TO_BE_COMPUTED" and digest!=expected:raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_CONFIGURATION_HASH_INVALID")
 return value,canonical_json(value),digest
def load_policy():
 value,text,digest=_load("thesis_review_assessment_policy_v1.json",EXPECTED_POLICY_HASH_V1)
 if tuple(value.get(k) for k in ("policy_id","processor_version","development_baseline","decision_semantics_version","authority"))!=(POLICY_ID,PROCESSOR_VERSION,BASELINE_COMMIT,DECISION_SEMANTICS_VERSION,AUTHORITY):raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_POLICY_INVALID")
 schema=Path(__file__).resolve().parents[1]/"contracts"/"trade_thesis.schema.json"
 if git_blob(schema)!=TRADE_THESIS_BLOB:raise ThesisReviewAssessmentIntegrityFailure("TRADE_THESIS_FROZEN_SCHEMA_CHANGED")
 return value,text,digest
def load_contract():
 value,text,digest=_load("thesis_review_assessment_contract_v1.json",EXPECTED_CONTRACT_HASH_V1)
 if tuple(value.get(k) for k in ("contract_version","schema_version","store_schema_version","decision_semantics_version","authority"))!=(CONTRACT_VERSION,SCHEMA_VERSION,STORE_SCHEMA_VERSION,DECISION_SEMANTICS_VERSION,AUTHORITY):raise ThesisReviewAssessmentIntegrityFailure("THESIS_REVIEW_ASSESSMENT_CONTRACT_INVALID")
 return value,text,digest
