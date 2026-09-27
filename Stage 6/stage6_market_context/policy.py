import hashlib,json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6MarketContextError
POLICY_ID="S6MCTXPOL_STAGE6_4A_V1";PROCESSOR_VERSION="STAGE6_4A_MARKET_CONTEXT_MATERIALIZER_V1";AUTHORITY="SHADOW_ONLY";BASELINE_COMMIT="56c6922d4f4c0e58c90d1751973ae64868d8b98a"
EXPECTED_POLICY_HASH_V1="422fa524a21a09a29ca0caa94a382ea056fba958d7c1a0a05c465740cb791d94"
EXPECTED_CONTRACT_GIT_BLOB_HASH="a141b221228718b8276b3d05b2f028d21adcfc3f"
def _contract_blob_hash():
 data=(Path(__file__).resolve().parents[1]/"contracts"/"market_context.schema.json").read_bytes();return hashlib.sha1(b"blob "+str(len(data)).encode("ascii")+b"\0"+data).hexdigest()
def validate_policy(p):
 expected=json.loads(Path(__file__).with_name("market_context_policy_v1.json").read_text(encoding="utf-8"))
 if p!=expected:raise Stage6MarketContextError("MARKET_CONTEXT_POLICY_RULESET_MISMATCH")
 if (p.get("policy_id"),p.get("processor_version"),p.get("authority"),p.get("baseline_commit"))!=(POLICY_ID,PROCESSOR_VERSION,AUTHORITY,BASELINE_COMMIT):raise Stage6MarketContextError("MARKET_CONTEXT_POLICY_IDENTITY_INVALID")
 return p
def load_policy():
 p=json.loads(Path(__file__).with_name("market_context_policy_v1.json").read_text(encoding="utf-8"));validate_policy(p);digest=canonical_hash(p)
 if digest!=EXPECTED_POLICY_HASH_V1:raise Stage6MarketContextError("MARKET_CONTEXT_POLICY_HASH_MISMATCH")
 if _contract_blob_hash()!=EXPECTED_CONTRACT_GIT_BLOB_HASH or p["contract_git_blob_hash"]!=EXPECTED_CONTRACT_GIT_BLOB_HASH:raise Stage6MarketContextError("MARKET_CONTEXT_FROZEN_CONTRACT_MISMATCH")
 return p,canonical_json(p),digest
