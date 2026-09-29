from copy import deepcopy
from stage6_ingestion.canonical import canonical_hash, without
from .policy import *
from .decision_rules import decide

SAFETY={"morning_input_status":"FROZEN","portfolio_context_status":"FROZEN","current_thesis_status":"FROZEN","entry_revalidation_status":"EVALUATED","proposal_status":"SHADOW_PROPOSAL_ONLY","stage5d_mutation_status":"PROHIBITED","portfolio_mutation_status":"PROHIBITED","thesis_mutation_status":"PROHIBITED","execution_status":"NOT_AUTHORIZED","order_creation_status":"NOT_AUTHORIZED","order_cancellation_status":"NOT_AUTHORIZED","quantity_change_status":"NOT_AUTHORIZED","network_calls":0,"external_api_calls":0,"live_news_searches":0,"market_data_downloads":0,"stage5d_live_database_calls":0,"broker_calls":0,"scheduler_calls":0,"exchange_calendar_calls":0,"llm":False,"nlp":False,"ml":False,"ocr":False,"embeddings":False,"semantic_similarity":False,"trading_authority":False}
def binding(t,i,h):return {"record_type":t,"record_id":i,"record_hash":h}
def support_key(x):return (x["record_type"],x["record_id"],x["record_hash"])
def canonical_assessments(values):return sorted(deepcopy(values),key=lambda x:x["condition_index"])
def canonical_assertions(values):
 out=deepcopy(values)
 for x in out:x["supporting_bindings"]=sorted(x["supporting_bindings"],key=support_key)
 return sorted(out,key=lambda x:(x["assessment"],x["reason_code"],tuple(support_key(y) for y in x["supporting_bindings"])))
def build_proposal(*,snapshot,thesis,portfolio,invalidation_assessments,change_assertions,policy_hash,contract_hash,manifest):
 ia=canonical_assessments(invalidation_assessments);ca=canonical_assertions(change_assertions);decision,reason=decide(thesis["thesis_status"],ia,ca,snapshot["availability"]["market_context"])
 sb=[]
 for item in [*ia,*ca]:sb.extend(item["supporting_bindings"])
 supports=sorted({support_key(x):x for x in sb}.values(),key=support_key);evidence_ids=sorted({x["record_id"] for x in supports if x["record_type"]=="STAGE6_EVIDENCE_V2"})
 morning=binding(INPUT_SCHEMA,snapshot["morning_snapshot_id"],snapshot["record_hash"]);tb=deepcopy(snapshot["current_thesis_binding"]);pb=deepcopy(snapshot["portfolio_context_binding"])
 policy_binding=binding("STAGE6_7B_POLICY",POLICY_ID,policy_hash);contract_binding=binding("STAGE6_7B_PROPOSAL_CONTRACT",CONTRACT_VERSION,contract_hash);code_binding=binding(MANIFEST_VERSION,MANIFEST_VERSION,manifest["decision_code_hash"])
 record={"schema_version":PROPOSAL_SCHEMA,"proposal_id":"","decision_scope":"NEW_ENTRY","morning_snapshot_binding":morning,"portfolio_context_binding":pb,"current_thesis_binding":tb,"target_session_date":snapshot["target_session_date"],"proposal_cutoff":snapshot["revalidation_cutoff"],"recommendation_id":snapshot["recommendation_id"],"ticker":snapshot["ticker"],"thesis_id":snapshot["thesis_id"],"thesis_version":snapshot["thesis_version"],"thesis_status":snapshot["thesis_status"],"committed_capital":deepcopy(snapshot["committed_capital"]),"invalidation_assessments":ia,"morning_change_assertions":ca,"proposal_decision":decision,"proposal_reason_code":reason,"support_bindings":supports,"supporting_evidence_ids":evidence_ids,"market_context_id":None if snapshot["market_context_binding"] is None else snapshot["market_context_binding"]["record_id"],"historical_analogue_id":None if snapshot["historical_analogue_binding"] is None else snapshot["historical_analogue_binding"]["record_id"],"direct_dependencies":[morning,tb,pb,policy_binding,contract_binding,code_binding],"decision_engine_version":DECISION_ENGINE,"decision_code_manifest_version":MANIFEST_VERSION,"decision_code_hash":manifest["decision_code_hash"],"processor_version":PROCESSOR,"policy_id":POLICY_ID,"policy_hash":policy_hash,"contract_version":CONTRACT_VERSION,"contract_hash":contract_hash,"authority":AUTHORITY,**SAFETY,"record_hash":""}
 record["proposal_id"]="S6MORNPROP_"+canonical_hash(without(record,"proposal_id","record_hash"))[:24];record["record_hash"]=canonical_hash(without(record,"record_hash"));return record
