import json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6DimensionMatchingError
POLICY_ID="S6DIMMATCHPOL_STAGE6_3E_V1";PROCESSOR_VERSION="STAGE6_3E_DIMENSION_MATCHER_V1";AUTHORITY="SHADOW_ONLY"
EXPECTED_RULES_V1=[{"source_rule_id":"S6TRANS_COMMODITY_V1","dimension_mode":"EXPLICIT_REQUIRED","event_field":"commodities","dimension_type":"COMMODITY"},{"source_rule_id":"S6TRANS_CURRENCY_V1","dimension_mode":"EXPLICIT_REQUIRED","event_field":"currencies","dimension_type":"CURRENCY"},{"source_rule_id":"S6TRANS_GEOGRAPHY_V1","dimension_mode":"EXPLICIT_REQUIRED","event_field":"geographies","dimension_type":"COUNTRY"},{"source_rule_id":"S6TRANS_RATE_V1","dimension_mode":"NOT_REQUIRED","event_field":None,"dimension_type":None},{"source_rule_id":"S6TRANS_TRADE_V1","dimension_mode":"EXPLICIT_REQUIRED","event_field":"geographies","dimension_type":"COUNTRY"}]
EXPECTED_POLICY_HASH_V1="5eec539293a0a95dc174c912ddda178b274655451204eb41a516c7f0de26131d"
def validate_policy(policy):
 if set(policy)!={"schema_version","policy_id","policy_version","processor_version","authority","rules"}:raise Stage6DimensionMatchingError("MATCH_POLICY_FIELDS_INVALID")
 if (policy["schema_version"],policy["policy_id"],policy["policy_version"],policy["processor_version"],policy["authority"])!=("STAGE6_3E_DIMENSION_MATCH_POLICY_V1",POLICY_ID,1,PROCESSOR_VERSION,AUTHORITY):raise Stage6DimensionMatchingError("MATCH_POLICY_IDENTITY_INVALID")
 if policy["rules"]!=EXPECTED_RULES_V1:raise Stage6DimensionMatchingError("MATCH_POLICY_RULESET_MISMATCH")
 return policy
def load_policy():
 policy=json.loads(Path(__file__).with_name("matching_policy_v1.json").read_text());validate_policy(policy);text=canonical_json(policy);digest=canonical_hash(policy)
 if digest!=EXPECTED_POLICY_HASH_V1:raise Stage6DimensionMatchingError("MATCH_POLICY_HASH_MISMATCH")
 return policy,text,digest
