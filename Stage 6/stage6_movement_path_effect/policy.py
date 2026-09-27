import json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6MovementPathEffectError
POLICY_ID="S6PATHEFFPOL_STAGE6_3H_V1";PROCESSOR_VERSION="STAGE6_3H_MOVEMENT_PATH_EFFECT_EVALUATOR_V1";AUTHORITY="SHADOW_ONLY"
EXPECTED_RULES_V1=[{"rule_id":"S6PATHEFF_CURRENCY_SHOCK_V1","event_type":"CURRENCY_SHOCK","source_rule_id":"S6TRANS_CURRENCY_V1","movement_kind":"CURRENCY_PAIR","movement_metric":"RELATIVE_VALUE","allowed_effect_directions":["ADVERSE","FAVORABLE","MIXED","UNKNOWN"]},{"rule_id":"S6PATHEFF_OIL_SHOCK_V1","event_type":"OIL_SHOCK","source_rule_id":"S6TRANS_COMMODITY_V1","movement_kind":"COMMODITY_PRICE","movement_metric":"PRICE","allowed_effect_directions":["ADVERSE","FAVORABLE","MIXED","UNKNOWN"]},{"rule_id":"S6PATHEFF_GAS_SHOCK_V1","event_type":"GAS_SHOCK","source_rule_id":"S6TRANS_COMMODITY_V1","movement_kind":"COMMODITY_PRICE","movement_metric":"PRICE","allowed_effect_directions":["ADVERSE","FAVORABLE","MIXED","UNKNOWN"]},{"rule_id":"S6PATHEFF_COMMODITY_SHOCK_V1","event_type":"COMMODITY_SHOCK","source_rule_id":"S6TRANS_COMMODITY_V1","movement_kind":"COMMODITY_PRICE","movement_metric":"PRICE","allowed_effect_directions":["ADVERSE","FAVORABLE","MIXED","UNKNOWN"]}]
EXPECTED_POLICY_HASH_V1="727a1bf14fe442cf68cbb6f626c8f122550c53a7be3cf7a1ccfb60dd32848ace"
def validate_policy(policy):
 if set(policy)!={"schema_version","policy_id","policy_version","processor_version","authority","rules"}:raise Stage6MovementPathEffectError("PATH_EFFECT_POLICY_FIELDS_INVALID")
 if (policy["schema_version"],policy["policy_id"],policy["policy_version"],policy["processor_version"],policy["authority"])!=("STAGE6_3H_MOVEMENT_PATH_EFFECT_POLICY_V1",POLICY_ID,1,PROCESSOR_VERSION,AUTHORITY):raise Stage6MovementPathEffectError("PATH_EFFECT_POLICY_IDENTITY_INVALID")
 if policy["rules"]!=EXPECTED_RULES_V1:raise Stage6MovementPathEffectError("PATH_EFFECT_POLICY_RULESET_MISMATCH")
 return policy
def load_policy():
 policy=json.loads(Path(__file__).with_name("path_effect_policy_v1.json").read_text());validate_policy(policy);text=canonical_json(policy);digest=canonical_hash(policy)
 if digest!=EXPECTED_POLICY_HASH_V1:raise Stage6MovementPathEffectError("PATH_EFFECT_POLICY_HASH_MISMATCH")
 return policy,text,digest
