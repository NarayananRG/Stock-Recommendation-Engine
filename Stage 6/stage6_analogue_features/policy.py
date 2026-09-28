import hashlib,json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6AnalogueFeatureError
POLICY_ID="S6ANFEATPOL_STAGE6_4B_V1";PROCESSOR_VERSION="STAGE6_4B_ANALOGUE_FEATURE_FREEZER_V1";AUTHORITY="SHADOW_ONLY";BASELINE_COMMIT="1b698c773cc9c49825781fe50bbe137df5aae679";FEATURE_CONTRACT_VERSION="STAGE6_ANALOGUE_FEATURE_CONTRACT_V1"
EXPECTED_POLICY_HASH_V1="ee9b8a5cfb5500d88e9002ffd984d8e37cc690496201fe7913e164f188281f16";EXPECTED_FEATURE_CONTRACT_HASH_V1="4a263fb50e4db4eb44e2e474087cd0cd1e08a68b02298d019ad9d02e8f45484f";HISTORICAL_BLOB="85a2b0d00cacd6a3caea484e3ef3071eb16fe01d";MARKET_BLOB="a141b221228718b8276b3d05b2f028d21adcfc3f"
def _blob(path):
 data=path.read_bytes();return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def load_policy():
 p=json.loads(Path(__file__).with_name("analogue_feature_policy_v1.json").read_text());digest=canonical_hash(p)
 if (p.get("policy_id"),p.get("processor_version"),p.get("authority"),p.get("development_baseline"))!=(POLICY_ID,PROCESSOR_VERSION,AUTHORITY,BASELINE_COMMIT) or digest!=EXPECTED_POLICY_HASH_V1:raise Stage6AnalogueFeatureError("ANALOGUE_FEATURE_POLICY_INVALID")
 root=Path(__file__).resolve().parents[1]/"contracts"
 if _blob(root/"historical_analogue.schema.json")!=HISTORICAL_BLOB or _blob(root/"market_context.schema.json")!=MARKET_BLOB:raise Stage6AnalogueFeatureError("ANALOGUE_FEATURE_FROZEN_CONTRACT_MISMATCH")
 return p,canonical_json(p),digest
def load_feature_contract():
 c=json.loads(Path(__file__).with_name("analogue_feature_contract_v1.json").read_text());digest=canonical_hash(c)
 if c.get("contract_version")!=FEATURE_CONTRACT_VERSION or digest!=EXPECTED_FEATURE_CONTRACT_HASH_V1:raise Stage6AnalogueFeatureError("ANALOGUE_FEATURE_CONTRACT_INVALID")
 names=[x["name"] for x in c["selection_snapshot_fields"]]
 if names!=["event_type","severity","materiality","stock_return_state","volume","volatility","technical_structure","sector_behaviour","market_regime","commodity_context","currency_context","rate_context"]:raise Stage6AnalogueFeatureError("ANALOGUE_FEATURE_CONTRACT_FIELDS_INVALID")
 return c,canonical_json(c),digest
