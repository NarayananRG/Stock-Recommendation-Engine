import hashlib,json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import MorningInputIntegrityFailure

SNAPSHOT_SCHEMA="STAGE6_MORNING_REVALIDATION_INPUT_SNAPSHOT_V1"
STORE_SCHEMA="STAGE6_7A_MORNING_REVALIDATION_INPUT_STORE_V1"
PROCESSOR="STAGE6_7A_MORNING_REVALIDATION_INPUT_FREEZER_V1"
POLICY_ID="S6MRINPOL_STAGE6_7A_V1"
CONTRACT_VERSION="STAGE6_MORNING_REVALIDATION_INPUT_CONTRACT_V1"
BASELINE="4232b1406bd6531925155132169db138c8784369"
AUTHORITY="SHADOW_ONLY"
PORTFOLIO_SCHEMA="STAGE6_PORTFOLIO_CONTEXT_V2";PORTFOLIO_BLOB="5900278a891dc70c63ce02f69002b5e9dec13799"
THESIS_SCHEMA="STAGE6_TRADE_THESIS_V2";THESIS_BLOB="2cc390a2cb85d938062511408293adcaf84ea288"
MARKET_BLOB="a141b221228718b8276b3d05b2f028d21adcfc3f";ANALOGUE_BLOB="85a2b0d00cacd6a3caea484e3ef3071eb16fe01d"
SOURCE_TYPES={"STAGE6_6B","STAGE6_6E","STAGE6_6F"};AVAILABLE={"AVAILABLE","NOT_PROVIDED"}
EXPECTED_POLICY_HASH="7f7fd729c0d57bcb909ea0c83b869e807d9db89a2bc52f5eb99d286d46e2bc20";EXPECTED_CONTRACT_HASH="169a9cce2c33855c4866029c9b9ca889fb253a4b50ee7cd2eee03a110aa33f70"

def git_blob(path):
 data=Path(path).read_bytes();return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def _load(name,expected):
 value=json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"));digest=canonical_hash(value)
 if expected!="TO_BE_COMPUTED" and digest!=expected:raise MorningInputIntegrityFailure("MORNING_INPUT_CONFIGURATION_HASH_INVALID")
 return value,canonical_json(value),digest
def _blobs():
 root=Path(__file__).resolve().parents[1]/"contracts";pairs=(("portfolio_context.schema.json",PORTFOLIO_BLOB),("trade_thesis.schema.json",THESIS_BLOB),("market_context.schema.json",MARKET_BLOB),("historical_analogue.schema.json",ANALOGUE_BLOB))
 if any(git_blob(root/name)!=wanted for name,wanted in pairs):raise MorningInputIntegrityFailure("FROZEN_SCHEMA_CHANGED")
def load_policy():
 value,text,digest=_load("morning_revalidation_input_policy_v1.json",EXPECTED_POLICY_HASH);_blobs()
 if tuple(value.get(k) for k in ("policy_id","processor_version","development_baseline","authority"))!=(POLICY_ID,PROCESSOR,BASELINE,AUTHORITY) or value.get("thesis_sources")!=["STAGE6_6B","STAGE6_6E","STAGE6_6F"]:raise MorningInputIntegrityFailure("MORNING_INPUT_POLICY_INVALID")
 return value,text,digest
def load_contract():
 value,text,digest=_load("morning_revalidation_input_contract_v1.json",EXPECTED_CONTRACT_HASH);_blobs()
 if tuple(value.get(k) for k in ("contract_version","snapshot_schema","store_schema","processor_version","authority"))!=(CONTRACT_VERSION,SNAPSHOT_SCHEMA,STORE_SCHEMA,PROCESSOR,AUTHORITY):raise MorningInputIntegrityFailure("MORNING_INPUT_CONTRACT_INVALID")
 return value,text,digest
