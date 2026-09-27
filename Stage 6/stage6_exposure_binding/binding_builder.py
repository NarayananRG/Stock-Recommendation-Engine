"""Pure deterministic Event-to-Exposure binding construction."""
from __future__ import annotations
from stage6_ingestion.canonical import canonical_hash,utc_timestamp,without

BINDING_SCHEMA_VERSION="STAGE6_EVENT_EXPOSURE_BINDING_V1"

def assertion_hash(assertion:dict)->str:return canonical_hash(assertion)

def binding_identity_payload(*,event:dict,exposure:dict,selected_assertion_hashes:list[str],binding_channel:str,binding_cutoff_timestamp:str,policy_hash:str,processor_version:str,binding_basis:str)->dict:
    return {"schema_version":BINDING_SCHEMA_VERSION,"event_id":event["event_id"],"event_version":event["event_version"],"event_hash":event["record_hash"],"exposure_id":exposure["exposure_id"],"exposure_version":exposure["exposure_version"],"exposure_hash":exposure["record_hash"],"selected_assertion_hashes":sorted(selected_assertion_hashes),"binding_channel":binding_channel,"binding_basis":binding_basis,"binding_cutoff_timestamp":utc_timestamp(binding_cutoff_timestamp,"binding_cutoff_timestamp"),"policy_hash":policy_hash,"processor_version":processor_version}

def deterministic_binding_id(**kwargs)->str:return "S6EXPBIND_"+canonical_hash(binding_identity_payload(**kwargs))[:24]

def build_binding(*,event:dict,exposure:dict,selected_assertions:list[dict],binding_channel:str,binding_cutoff_timestamp:str,policy:dict,policy_hash:str)->dict:
    refs=sorted([{"assertion_hash":assertion_hash(a),"exposure_type":a["exposure_type"],"value_type":a["value_type"],"evidence_ids":sorted(a["evidence_ids"])} for a in selected_assertions],key=lambda x:x["assertion_hash"])
    hashes=[x["assertion_hash"] for x in refs];cutoff=utc_timestamp(binding_cutoff_timestamp,"binding_cutoff_timestamp")
    identity=dict(event=event,exposure=exposure,selected_assertion_hashes=hashes,binding_channel=binding_channel,binding_cutoff_timestamp=cutoff,policy_hash=policy_hash,processor_version=policy["processor_version"],binding_basis=policy["binding_basis"])
    record={"schema_version":BINDING_SCHEMA_VERSION,"binding_id":deterministic_binding_id(**identity),"record_hash":"0"*64,
      "event_id":event["event_id"],"event_version":event["event_version"],"event_hash":event["record_hash"],"event_type":event["event_type"],"event_status":event["event_status"],
      "exposure_id":exposure["exposure_id"],"exposure_version":exposure["exposure_version"],"exposure_hash":exposure["record_hash"],
      "company_entity_id":exposure["company_entity_id"],"sector_entity_id":exposure["sector_entity_id"],"subsector_entity_id":exposure["subsector_entity_id"],
      "binding_channel":binding_channel,"binding_basis":policy["binding_basis"],"selected_assertions":refs,
      "supporting_evidence_ids":sorted({e for ref in refs for e in ref["evidence_ids"]}),"binding_cutoff_timestamp":cutoff,
      "entity_registry_snapshot_id":exposure["entity_registry_snapshot_id"],"entity_registry_version":exposure["entity_registry_version"],"entity_registry_hash":exposure["entity_registry_hash"],
      "semantic_compatibility_status":"NOT_EVALUATED","directional_effect_status":"NOT_EVALUATED","causal_effect_status":"NOT_EVALUATED",
      "policy_id":policy["policy_id"],"policy_hash":policy_hash,"processor_version":policy["processor_version"],"authority":policy["authority"]}
    record["record_hash"]=canonical_hash(without(record,"record_hash"));return record
