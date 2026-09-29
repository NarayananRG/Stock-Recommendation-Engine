from copy import deepcopy
from stage6_ingestion.canonical import canonical_hash,without
from .policy import *
SAFETY={"previous_thesis_status":"FROZEN","review_snapshot_status":"FROZEN","structured_assertions_status":"FROZEN","stop_change_status":"NOT_EVALUATED","target_change_status":"NOT_EVALUATED","portfolio_action_status":"NOT_EVALUATED","replacement_status":"NOT_EVALUATED","buy_sell_hold_status":"NOT_EVALUATED","trading_authority":False,"network_calls":0,"external_api_calls":0,"market_data_downloads":0,"stage5d_live_database_calls":0,"broker_calls":0,"auto_news_lookup":0,"auto_latest_context_lookup":0,"llm":False,"nlp":False,"ml":False,"ocr":False,"embeddings":False,"semantic_similarity":False}
def binding(kind,identity,digest):return {"record_type":kind,"record_id":identity,"record_hash":digest}
def canonical_support(values):return sorted(deepcopy(values),key=lambda x:(x["record_type"],x["record_id"],x["record_hash"]))
def normalize_invalidations(thesis,values):
 out=[{"condition_index":x["condition_index"],"condition_text":x["condition_text"],"evaluation_status":x["evaluation_status"],"supporting_bindings":canonical_support(x["supporting_bindings"])} for x in values];return sorted(out,key=lambda x:x["condition_index"])
def normalize_assertions(values):
 out=[]
 for value in values:
  core={"assessment":value["assessment"],"reason_code":value["reason_code"],"supporting_bindings":canonical_support(value["supporting_bindings"])};wanted="S6THASSERT_"+canonical_hash(core)[:24]
  out.append({"assertion_id":wanted,**core})
 return sorted(out,key=lambda x:(x["assessment"],x["reason_code"],canonical_hash(x["supporting_bindings"]),x["assertion_id"]))
def decide(invalidations,assertions):
 states={x["evaluation_status"] for x in invalidations};assessments={x["assessment"] for x in assertions}
 if "TRIGGERED" in states:return ("MATERIAL_CHANGE","DETERMINATE","THESIS_INVALIDATED","INVALIDATION_TRIGGERED")
 if "NOT_EVALUATED" in states:return ("INDETERMINATE","INDETERMINATE",None,"INVALIDATION_NOT_FULLY_EVALUATED")
 if "INDETERMINATE" in assessments:return ("INDETERMINATE","INDETERMINATE",None,"CHANGE_ASSERTION_INDETERMINATE")
 supportive="SUPPORTIVE_MATERIAL" in assessments;adverse="ADVERSE_MATERIAL" in assessments
 if supportive and adverse:return ("INDETERMINATE","INDETERMINATE",None,"CONFLICTING_MATERIAL_CHANGE")
 if adverse:return ("MATERIAL_CHANGE","DETERMINATE","THESIS_WEAKENED","ADVERSE_MATERIAL_CHANGE")
 if supportive:return ("MATERIAL_CHANGE","DETERMINATE","THESIS_STRENGTHENED","SUPPORTIVE_MATERIAL_CHANGE")
 return ("NO_MATERIAL_CHANGE","DETERMINATE","THESIS_UNCHANGED","NO_MATERIAL_CHANGE")
def build_assessment(*,thesis,snapshot,invalidation_assessments,change_assertions,policy_hash,contract_hash):
 invalidations=normalize_invalidations(thesis,invalidation_assessments);assertions=normalize_assertions(change_assertions);material,outcome,target,reason=decide(invalidations,assertions);determinate=outcome=="DETERMINATE"
 thesis_binding=binding(TRADE_THESIS_SCHEMA,thesis["thesis_id"],thesis["record_hash"]);snapshot_binding=binding(SNAPSHOT_SCHEMA,snapshot["review_snapshot_id"],snapshot["record_hash"]);used=[b for x in [*invalidations,*assertions] for b in x["supporting_bindings"]];evidence=sorted({x["record_id"] for x in used if x["record_type"]=="STAGE6_EVIDENCE_V2"});change_types={"THESIS_INVALIDATED":"THESIS_INVALIDATED_REVIEW","THESIS_WEAKENED":"THESIS_WEAKENED_REVIEW","THESIS_STRENGTHENED":"THESIS_STRENGTHENED_REVIEW","THESIS_UNCHANGED":"THESIS_REVIEWED_UNCHANGED"}
 proposed={"previous_version":1,"proposed_next_version":2,"previous_version_hash":thesis["record_hash"],"target_thesis_status":target,"review_cutoff":snapshot["review_cutoff"],"last_review_date":snapshot["review_cutoff"][:10],"change_type":change_types[target],"change_reason_code":reason,"review_evidence_ids":evidence,"next_version_direct_input_policy":[TRADE_THESIS_SCHEMA,SNAPSHOT_SCHEMA,SCHEMA_VERSION]} if determinate else None
 record={"schema_version":SCHEMA_VERSION,"assessment_id":"","previous_thesis_binding":thesis_binding,"review_snapshot_binding":snapshot_binding,"thesis_id":thesis["thesis_id"],"previous_thesis_version":thesis["version"],"recommendation_id":thesis["recommendation_id"],"ticker":thesis["ticker"],"prior_decision_cutoff":thesis["decision_cutoff"],"review_cutoff":snapshot["review_cutoff"],"invalidation_assessments":invalidations,"change_assertions":assertions,"material_change_status":material,"review_outcome":outcome,"target_thesis_status":target,"transition_reason_code":reason,"thesis_status_evaluation":"EVALUATED" if determinate else "INDETERMINATE","next_thesis_version_status":"READY_FOR_MATERIALIZATION" if determinate else "WITHHELD_INDETERMINATE","proposed_transition_metadata":proposed,"review_evidence_ids":evidence,"decision_semantics_version":DECISION_SEMANTICS_VERSION,"processor_version":PROCESSOR_VERSION,"policy_id":POLICY_ID,"policy_hash":policy_hash,"assessment_contract_version":CONTRACT_VERSION,"assessment_contract_hash":contract_hash,"authority":AUTHORITY,**SAFETY,"record_hash":""}
 record["assessment_id"]="S6THREVASS_"+canonical_hash(without(record,"assessment_id","record_hash"))[:24];record["record_hash"]=canonical_hash(without(record,"record_hash"));return record
