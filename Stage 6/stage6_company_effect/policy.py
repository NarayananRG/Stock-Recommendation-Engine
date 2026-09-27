import json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6CompanyEffectError
POLICY_ID="S6COMEFFPOL_STAGE6_3I_V1";PROCESSOR_VERSION="STAGE6_3I_COMPANY_EFFECT_SYNTHESIZER_V1";AUTHORITY="SHADOW_ONLY";SOURCE_3F_HASH="fc9c12455b5a23004523591d641620ee8caaad971be505b80128eba0d679998e";SOURCE_3H_HASH="727a1bf14fe442cf68cbb6f626c8f122550c53a7be3cf7a1ccfb60dd32848ace"
EXPECTED_POLICY_HASH_V1="3a92f28b24d46a8b7f6ed1ac9a77562355ae751dfce23e23ed4a9ba4dfc21786"
def validate_policy(p):
 if set(p)!={"schema_version","policy_id","policy_version","processor_version","authority","source_policies","routes","allowed_normalized_effects","synthesis_rules","weighting"}:raise Stage6CompanyEffectError("COMPANY_EFFECT_POLICY_FIELDS_INVALID")
 if (p["schema_version"],p["policy_id"],p["policy_version"],p["processor_version"],p["authority"],p["weighting"])!=("STAGE6_3I_COMPANY_EFFECT_POLICY_V1",POLICY_ID,1,PROCESSOR_VERSION,AUTHORITY,"NONE"):raise Stage6CompanyEffectError("COMPANY_EFFECT_POLICY_IDENTITY_INVALID")
 expected=json.loads(Path(__file__).with_name("company_effect_policy_v1.json").read_text())
 if p!=expected:raise Stage6CompanyEffectError("COMPANY_EFFECT_POLICY_RULESET_MISMATCH")
 return p
def load_policy():
 p=json.loads(Path(__file__).with_name("company_effect_policy_v1.json").read_text());validate_policy(p);text=canonical_json(p);digest=canonical_hash(p)
 if digest!=EXPECTED_POLICY_HASH_V1:raise Stage6CompanyEffectError("COMPANY_EFFECT_POLICY_HASH_MISMATCH")
 return p,text,digest
