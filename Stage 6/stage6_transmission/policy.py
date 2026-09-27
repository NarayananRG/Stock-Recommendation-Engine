import json
from pathlib import Path
from stage6_ingestion.canonical import canonical_hash,canonical_json
from .errors import Stage6TransmissionError
POLICY_ID="S6TRANSPOL_STAGE6_3C_V1";PROCESSOR_VERSION="STAGE6_3C_TRANSMISSION_EVALUATOR_V1";AUTHORITY="SHADOW_ONLY"
RULE_FIELDS={"rule_id","event_types","binding_channel","allowed_exposure_types","dimension_match_mode"}
def validate_policy(p):
 if set(p)!={"schema_version","policy_id","policy_version","processor_version","authority","rules"} or (p["schema_version"],p["policy_id"],p["policy_version"],p["processor_version"],p["authority"])!=("STAGE6_3C_TRANSMISSION_POLICY_V1",POLICY_ID,1,PROCESSOR_VERSION,AUTHORITY):raise Stage6TransmissionError("TRANSMISSION_POLICY_IDENTITY_INVALID")
 if not isinstance(p["rules"],list) or p["rules"]!=sorted(p["rules"],key=lambda x:x.get("rule_id","")):raise Stage6TransmissionError("TRANSMISSION_POLICY_RULE_ORDER_INVALID")
 owners=set();ids=set()
 for r in p["rules"]:
  if set(r)!=RULE_FIELDS or r["rule_id"] in ids or r["event_types"]!=sorted(set(r["event_types"])) or r["allowed_exposure_types"]!=sorted(set(r["allowed_exposure_types"])) or r["dimension_match_mode"] not in {"NOT_REQUIRED","NOT_EVALUATED"}:raise Stage6TransmissionError("TRANSMISSION_POLICY_RULE_INVALID")
  ids.add(r["rule_id"])
  for e in r["event_types"]:
   if (e,r["binding_channel"]) in owners:raise Stage6TransmissionError("TRANSMISSION_POLICY_RULE_AMBIGUOUS")
   owners.add((e,r["binding_channel"]))
 return p
def load_policy():
 p=json.loads(Path(__file__).with_name("transmission_policy_v1.json").read_text());validate_policy(p);return p,canonical_json(p),canonical_hash(p)
