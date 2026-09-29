from copy import deepcopy

from stage6_ingestion.canonical import canonical_hash, without
from stage6_thesis_seed.thesis_seed_validation import validate_seed
from .policy import *

SAFETY={"network_calls":0,"external_api_calls":0,"stage5d_live_database_calls":0,"broker_calls":0,"market_data_downloads":0,"llm":False,"nlp":False,"ml":False,"ocr":False,"embeddings":False,"semantic_similarity":False,"buy_sell_hold_status":"NOT_EVALUATED","dynamic_management_status":"NOT_EVALUATED","trading_authority":False}

def _binding(seed):
    return {"record_id":seed["seed_record_id"],"record_hash":seed["record_hash"],"record_type":SEED_SCHEMA_VERSION}

def build_trade_thesis(seed):
    validate_seed(seed);semantic=deepcopy(seed["initial_thesis_semantic_projection"]);binding=_binding(seed)
    change=semantic["initial_change_semantics"]
    thesis={"schema_version":SCHEMA_VERSION,"thesis_id":"","version":1,"thesis_engine_version":THESIS_ENGINE_VERSION,"code_commit":BASELINE_COMMIT,"decision_cutoff":semantic["decision_cutoff"],"input_records":[binding],"recommendation_id":semantic["recommendation_id"],"ticker":semantic["ticker"],"entry_date":semantic["derived_entry_date"],"holding_horizon":semantic["holding_horizon"],"entry_rationale":semantic["entry_rationale"],"supporting_evidence":semantic["supporting_evidence_ids"],"known_risks":semantic["known_risks"],"initial_entry_range":semantic["initial_entry_range"],"fill_references":semantic["projected_fill_references"],"aggregate_fill":semantic["aggregate_fill"],"initial_stop":semantic["initial_stop"],"current_stop":semantic["current_stop"],"initial_target":semantic["initial_target"],"current_target":semantic["current_target"],"invalidation_conditions":semantic["invalidation_conditions"],"thesis_status":semantic["thesis_status"],"last_review_date":semantic["last_review_date"],"change_history":[{"version":change["version"],"changed_at_utc":change["changed_at_semantic"],"decision_cutoff":semantic["decision_cutoff"],"change_type":change["change_type"],"reason":change["reason"],"evidence_ids":change["evidence_ids"],"input_records":[binding]}],"previous_version_hash":semantic["previous_version_hash"],"record_hash":"","authority_mode":AUTHORITY}
    thesis["thesis_id"]="S6THESIS_"+canonical_hash(without(thesis,"thesis_id","record_hash"))[:24]
    thesis["record_hash"]=canonical_hash(without(thesis,"record_hash"))
    return thesis

def build_materialization_record(seed,policy_hash,contract_hash):
    thesis=build_trade_thesis(seed)
    record={"schema_version":WRAPPER_SCHEMA_VERSION,"materialization_record_id":"","seed_binding":_binding(seed),"trade_thesis":thesis,"policy_id":POLICY_ID,"policy_hash":policy_hash,"materialization_contract_version":MATERIALIZATION_CONTRACT_VERSION,"materialization_contract_hash":contract_hash,"processor_version":PROCESSOR_VERSION,"code_commit":BASELINE_COMMIT,"trade_thesis_schema_blob":TRADE_THESIS_BLOB,"authority":AUTHORITY,**SAFETY,"record_hash":""}
    record["materialization_record_id"]="S6THMAT_"+canonical_hash(without(record,"materialization_record_id","record_hash"))[:24]
    record["record_hash"]=canonical_hash(without(record,"record_hash"))
    return record
