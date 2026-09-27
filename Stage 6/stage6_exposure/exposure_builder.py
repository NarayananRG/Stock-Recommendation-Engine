"""Deterministic construction for frozen STAGE6_EXPOSURE_V2."""
from __future__ import annotations
from stage6_ingestion.canonical import canonical_hash, canonical_json, utc_timestamp, without

EXPOSURE_SCHEMA_VERSION="STAGE6_EXPOSURE_V2"

def deterministic_exposure_id(company_entity_id:str)->str:
    if not isinstance(company_entity_id,str) or not company_entity_id: raise ValueError("COMPANY_ENTITY_ID_REQUIRED")
    return "S6EXP_"+canonical_hash({"company_entity_id":company_entity_id})[:24]

def _assertion_key(item:dict)->tuple:
    return (item.get("exposure_type",""),item.get("value_type",""),item.get("effective_date",""),item.get("review_or_expiry_date",""),canonical_hash(item))

def _relationship_key(item:dict)->tuple:
    return (item.get("relationship_type",""),item.get("related_entity_id",""),item.get("effective_date",""),item.get("review_or_expiry_date",""),canonical_hash(item))

def build_exposure(*,company_entity_id:str,exposure_version:int,previous_version_hash:str|None,
                   sector_entity_id:str,subsector_entity_id:str|None,as_of_timestamp:str,
                   data_cutoff_timestamp:str,entity_registry_snapshot_id:str,entity_registry_version:int,
                   entity_registry_hash:str,input_evidence_ids:list[str],assertions:list[dict],
                   relationships:list[dict])->dict:
    normalized_assertions=[]
    for item in assertions:
        copy=dict(item);copy["evidence_ids"]=sorted(copy.get("evidence_ids",[]));normalized_assertions.append(copy)
    normalized_relationships=[]
    for item in relationships:
        copy=dict(item);copy["evidence_ids"]=sorted(copy.get("evidence_ids",[]));normalized_relationships.append(copy)
    record={"schema_version":EXPOSURE_SCHEMA_VERSION,"exposure_id":deterministic_exposure_id(company_entity_id),
        "exposure_version":exposure_version,"company_entity_id":company_entity_id,
        "sector_entity_id":sector_entity_id,"subsector_entity_id":subsector_entity_id,
        "as_of_timestamp":utc_timestamp(as_of_timestamp,"as_of_timestamp"),
        "data_cutoff_timestamp":utc_timestamp(data_cutoff_timestamp,"data_cutoff_timestamp"),
        "entity_registry_snapshot_id":entity_registry_snapshot_id,"entity_registry_version":entity_registry_version,
        "entity_registry_hash":entity_registry_hash,"input_evidence_ids":sorted(input_evidence_ids),
        "assertions":sorted(normalized_assertions,key=_assertion_key),
        "relationships":sorted(normalized_relationships,key=_relationship_key),
        "previous_version_hash":previous_version_hash,"record_hash":"0"*64}
    record["record_hash"]=canonical_hash(without(record,"record_hash"));return record
