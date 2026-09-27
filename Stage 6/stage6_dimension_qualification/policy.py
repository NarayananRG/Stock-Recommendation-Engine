import json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6DimensionError
POLICY_ID="S6DIMPOL_STAGE6_3D_V1";PROCESSOR_VERSION="STAGE6_3D_DIMENSION_QUALIFIER_V1";AUTHORITY="SHADOW_ONLY";SUPPORTED_DIMENSIONS=["COMMODITY","COUNTRY","CURRENCY"]
EXPECTED_RULES_V1=[{"source_rule_id":"S6TRANS_COMMODITY_V1","dimension_mode":"EXPLICIT_REQUIRED","dimension_type":"COMMODITY"},{"source_rule_id":"S6TRANS_CURRENCY_V1","dimension_mode":"EXPLICIT_REQUIRED","dimension_type":"CURRENCY"},{"source_rule_id":"S6TRANS_GEOGRAPHY_V1","dimension_mode":"EXPLICIT_REQUIRED","dimension_type":"COUNTRY"},{"source_rule_id":"S6TRANS_RATE_V1","dimension_mode":"NOT_REQUIRED","dimension_type":None},{"source_rule_id":"S6TRANS_TRADE_V1","dimension_mode":"EXPLICIT_REQUIRED","dimension_type":"COUNTRY"}]
EXPECTED_POLICY_HASH_V1="bd57553eaa0185612aeb73baf03b242b9a16db1c3b4a113fad70eb5a21e0e2a3"
def validate_policy(p):
 if set(p)!={"schema_version","policy_id","policy_version","processor_version","authority","supported_dimension_types","rules"}:raise Stage6DimensionError("DIMENSION_POLICY_FIELDS_INVALID")
 if (p["schema_version"],p["policy_id"],p["policy_version"],p["processor_version"],p["authority"],p["supported_dimension_types"]) != ("STAGE6_3D_DIMENSION_POLICY_V1",POLICY_ID,1,PROCESSOR_VERSION,AUTHORITY,SUPPORTED_DIMENSIONS):raise Stage6DimensionError("DIMENSION_POLICY_IDENTITY_INVALID")
 if p["rules"]!=EXPECTED_RULES_V1:raise Stage6DimensionError("DIMENSION_POLICY_RULESET_MISMATCH")
 return p
def load_policy():
 p=json.loads(Path(__file__).with_name("qualification_policy_v1.json").read_text());validate_policy(p);s=canonical_json(p);h=canonical_hash(p)
 if h!=EXPECTED_POLICY_HASH_V1:raise Stage6DimensionError("DIMENSION_POLICY_HASH_MISMATCH")
 return p,s,h
