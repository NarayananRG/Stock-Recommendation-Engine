import json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6EventMovementError
POLICY_ID="S6MOVPOL_STAGE6_3G_V1";PROCESSOR_VERSION="STAGE6_3G_EVENT_MOVEMENT_QUALIFIER_V1";AUTHORITY="SHADOW_ONLY"
EXPECTED_RULES_V1=[{"rule_id":"S6MOV_CURRENCY_SHOCK_V1","event_type":"CURRENCY_SHOCK","source_rule_id":"S6TRANS_CURRENCY_V1","event_field":"currencies","dimension_type":"CURRENCY","movement_kind":"CURRENCY_PAIR","movement_metric":"RELATIVE_VALUE","reference_requirement":"REQUIRED","allowed_movements":["MIXED","STRENGTHEN","UNKNOWN","WEAKEN"]},{"rule_id":"S6MOV_OIL_SHOCK_V1","event_type":"OIL_SHOCK","source_rule_id":"S6TRANS_COMMODITY_V1","event_field":"commodities","dimension_type":"COMMODITY","movement_kind":"COMMODITY_PRICE","movement_metric":"PRICE","reference_requirement":"PROHIBITED","allowed_movements":["DECREASE","INCREASE","MIXED","UNKNOWN"]},{"rule_id":"S6MOV_GAS_SHOCK_V1","event_type":"GAS_SHOCK","source_rule_id":"S6TRANS_COMMODITY_V1","event_field":"commodities","dimension_type":"COMMODITY","movement_kind":"COMMODITY_PRICE","movement_metric":"PRICE","reference_requirement":"PROHIBITED","allowed_movements":["DECREASE","INCREASE","MIXED","UNKNOWN"]},{"rule_id":"S6MOV_COMMODITY_SHOCK_V1","event_type":"COMMODITY_SHOCK","source_rule_id":"S6TRANS_COMMODITY_V1","event_field":"commodities","dimension_type":"COMMODITY","movement_kind":"COMMODITY_PRICE","movement_metric":"PRICE","reference_requirement":"PROHIBITED","allowed_movements":["DECREASE","INCREASE","MIXED","UNKNOWN"]}]
EXPECTED_POLICY_HASH_V1="55ab067ad7e47f7993b1c1554bdbf39c297018ac2ae58a6cd8370bec4ce26f74"
def validate_policy(policy):
 if set(policy)!={"schema_version","policy_id","policy_version","processor_version","authority","rules"}:raise Stage6EventMovementError("MOVEMENT_POLICY_FIELDS_INVALID")
 if (policy["schema_version"],policy["policy_id"],policy["policy_version"],policy["processor_version"],policy["authority"])!=("STAGE6_3G_EVENT_MOVEMENT_POLICY_V1",POLICY_ID,1,PROCESSOR_VERSION,AUTHORITY):raise Stage6EventMovementError("MOVEMENT_POLICY_IDENTITY_INVALID")
 if policy["rules"]!=EXPECTED_RULES_V1:raise Stage6EventMovementError("MOVEMENT_POLICY_RULESET_MISMATCH")
 return policy
def load_policy():
 policy=json.loads(Path(__file__).with_name("movement_policy_v1.json").read_text());validate_policy(policy);text=canonical_json(policy);digest=canonical_hash(policy)
 if digest!=EXPECTED_POLICY_HASH_V1:raise Stage6EventMovementError("MOVEMENT_POLICY_HASH_MISMATCH")
 return policy,text,digest
