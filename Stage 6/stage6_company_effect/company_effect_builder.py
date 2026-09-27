from stage6_ingestion.canonical import canonical_hash,without
SCHEMA_VERSION="STAGE6_EVENT_COMPANY_EFFECT_V1"
SUMMARY_MAP={"NOT_EVALUATED":"NOT_EVALUATED","INDETERMINATE":"INDETERMINATE","FAVORABLE_ONLY":"FAVORABLE","ADVERSE_ONLY":"ADVERSE","MIXED_PATH_DIRECTIONS":"MIXED"}
def unit_id(source_family,source_id,source_hash,path_id,movement_id):return "S6COMEFFUNIT_"+canonical_hash({"source_family":source_family,"source_record_id":source_id,"source_record_hash":source_hash,"source_path_id":path_id,"movement_item_id":movement_id})[:24]
def normalize(source_family,source):
 if source_family=="STAGE6_3F_DIRECTION":results=source["path_direction_results"];sid=source["direction_record_id"];sh=source["record_hash"]
 else:results=source["path_effect_results"];sid=source["path_effect_record_id"];sh=source["record_hash"]
 units=[]
 for x in results:
  if x["eligibility_status"]!="ELIGIBLE":continue
  mid=x.get("movement_item_id");units.append({"normalized_unit_id":unit_id(source_family,sid,sh,x["source_path_id"],mid),"source_family":source_family,"source_record_id":sid,"source_record_hash":sh,"source_path_id":x["source_path_id"],"movement_item_id":mid,"effect_direction":x["effect_direction"],"qualification_state":"QUALIFIED" if x["effect_direction"] is not None else "UNQUALIFIED"})
 return sorted(units,key=lambda x:(x["source_path_id"],x["movement_item_id"] or ""))
def synthesize(units):
 if not units:return "NOT_EVALUATED"
 if any(x["effect_direction"] is None for x in units):return "INDETERMINATE"
 effects={x["effect_direction"] for x in units}
 if "UNKNOWN" in effects:return "INDETERMINATE"
 if effects=={"FAVORABLE"}:return "FAVORABLE"
 if effects=={"ADVERSE"}:return "ADVERSE"
 return "MIXED"
def build_company_effect(*,source_family,source,match,policy,policy_hash):
 units=normalize(source_family,source);effect=synthesize(units);summary=source["matched_path_direction_summary"] if source_family=="STAGE6_3F_DIRECTION" else source["matched_movement_path_effect_summary"]
 if SUMMARY_MAP.get(summary)!=effect:raise ValueError("UPSTREAM_SUMMARY_INCONSISTENT")
 sid=source["direction_record_id"] if source_family=="STAGE6_3F_DIRECTION" else source["path_effect_record_id"]
 out={"schema_version":SCHEMA_VERSION,"company_effect_record_id":"","record_hash":"0"*64,"source_family":source_family,"source_record_id":sid,"source_record_hash":source["record_hash"],"match_id":match["match_id"],"match_hash":match["record_hash"],"event_id":match["event_id"],"event_version":match["event_version"],"event_hash":match["event_hash"],"event_type":source["event_type"],"exposure_id":match["exposure_id"],"exposure_version":match["exposure_version"],"exposure_hash":match["exposure_hash"],"company_entity_id":match["company_entity_id"],"normalized_effect_units":units,"company_event_effect":effect,"stock_direction_status":"NOT_EVALUATED","market_reaction_status":"NOT_EVALUATED","magnitude_status":"NOT_EVALUATED","expected_return_status":"NOT_EVALUATED","causal_effect_status":"NOT_EVALUATED","portfolio_influence_status":"NOT_EVALUATED","security_ranking_status":"NOT_EVALUATED","trading_authority":False,"policy_id":policy["policy_id"],"policy_hash":policy_hash,"processor_version":policy["processor_version"],"authority":policy["authority"]};out["company_effect_record_id"]="S6COMEFF_"+canonical_hash({"schema_version":SCHEMA_VERSION,"source_family":source_family,"source_record_id":sid,"source_record_hash":source["record_hash"],"match_id":match["match_id"],"match_hash":match["record_hash"],"units":units,"policy_hash":policy_hash,"processor_version":policy["processor_version"]})[:24];out["record_hash"]=canonical_hash(without(out,"record_hash"));return out
