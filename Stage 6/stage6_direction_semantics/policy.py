import json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6DirectionError
POLICY_ID="S6DIRPOL_STAGE6_3F_V1";PROCESSOR_VERSION="STAGE6_3F_DIRECTION_EVALUATOR_V1";AUTHORITY="SHADOW_ONLY"
EXPECTED_RULES_V1=[{"rule_id":"S6DIR_RATE_HIKE_V1","event_type":"RATE_HIKE","source_rule_id":"S6TRANS_RATE_V1","event_driver_change":"INCREASE","dimension_requirement":"NOT_REQUIRED"},{"rule_id":"S6DIR_RATE_CUT_V1","event_type":"RATE_CUT","source_rule_id":"S6TRANS_RATE_V1","event_driver_change":"DECREASE","dimension_requirement":"NOT_REQUIRED"},{"rule_id":"S6DIR_TARIFF_INCREASE_V1","event_type":"TARIFF_INCREASE","source_rule_id":"S6TRANS_TRADE_V1","event_driver_change":"INCREASE","dimension_requirement":"EXACT_ENTITY_MATCH_REQUIRED"},{"rule_id":"S6DIR_TARIFF_REDUCTION_V1","event_type":"TARIFF_REDUCTION","source_rule_id":"S6TRANS_TRADE_V1","event_driver_change":"DECREASE","dimension_requirement":"EXACT_ENTITY_MATCH_REQUIRED"},{"rule_id":"S6DIR_WAR_ESCALATION_V1","event_type":"WAR_ESCALATION","source_rule_id":"S6TRANS_GEOGRAPHY_V1","event_driver_change":"ESCALATE","dimension_requirement":"EXACT_ENTITY_MATCH_REQUIRED"},{"rule_id":"S6DIR_WAR_DEESCALATION_V1","event_type":"WAR_DEESCALATION","source_rule_id":"S6TRANS_GEOGRAPHY_V1","event_driver_change":"DEESCALATE","dimension_requirement":"EXACT_ENTITY_MATCH_REQUIRED"}]
EXPECTED_POLICY_HASH_V1="fc9c12455b5a23004523591d641620ee8caaad971be505b80128eba0d679998e"
def validate_policy(policy):
 if set(policy)!={"schema_version","policy_id","policy_version","processor_version","authority","rules"}:raise Stage6DirectionError("DIRECTION_POLICY_FIELDS_INVALID")
 if (policy["schema_version"],policy["policy_id"],policy["policy_version"],policy["processor_version"],policy["authority"])!=("STAGE6_3F_DIRECTION_POLICY_V1",POLICY_ID,1,PROCESSOR_VERSION,AUTHORITY):raise Stage6DirectionError("DIRECTION_POLICY_IDENTITY_INVALID")
 if policy["rules"]!=EXPECTED_RULES_V1:raise Stage6DirectionError("DIRECTION_POLICY_RULESET_MISMATCH")
 return policy
def load_policy():
 policy=json.loads(Path(__file__).with_name("direction_policy_v1.json").read_text());validate_policy(policy);text=canonical_json(policy);digest=canonical_hash(policy)
 if digest!=EXPECTED_POLICY_HASH_V1:raise Stage6DirectionError("DIRECTION_POLICY_HASH_MISMATCH")
 return policy,text,digest
