import re
from datetime import date

from stage6_ingestion.canonical import canonical_hash, parse_utc, without
from .errors import TradeThesisIntegrityFailure
from .policy import *
from .trade_thesis_builder import SAFETY

HASH=re.compile(r"[a-f0-9]{64}")
THESIS_FIELDS={"schema_version","thesis_id","version","thesis_engine_version","code_commit","decision_cutoff","input_records","recommendation_id","ticker","entry_date","holding_horizon","entry_rationale","supporting_evidence","known_risks","initial_entry_range","fill_references","aggregate_fill","initial_stop","current_stop","initial_target","current_target","invalidation_conditions","thesis_status","last_review_date","change_history","previous_version_hash","record_hash","authority_mode"}
BINDING_FIELDS={"record_id","record_hash","record_type"}
FILL_FIELDS={"transaction_id","fill_date","quantity","price","currency","source_system"}
CHANGE_FIELDS={"version","changed_at_utc","decision_cutoff","change_type","reason","evidence_ids","input_records"}
WRAPPER_FIELDS={"schema_version","materialization_record_id","seed_binding","trade_thesis","policy_id","policy_hash","materialization_contract_version","materialization_contract_hash","processor_version","code_commit","trade_thesis_schema_blob","authority",*SAFETY.keys(),"record_hash"}

def fail(code):raise TradeThesisIntegrityFailure(code)
def strings(value,empty=False):return isinstance(value,list) and (empty or bool(value)) and all(isinstance(x,str) and x for x in value)
def binding(value):return isinstance(value,dict) and set(value)==BINDING_FIELDS and all(isinstance(value.get(x),str) and value[x] for x in BINDING_FIELDS) and HASH.fullmatch(value["record_hash"])
def positive(value):return type(value) in (int,float) and not isinstance(value,bool) and value>0
def price(value):return value is None or (isinstance(value,dict) and set(value)=={"value","currency"} and positive(value["value"]) and value["currency"]=="INR")

def validate_trade_thesis(record,seed=None):
    if not isinstance(record,dict) or set(record)!=THESIS_FIELDS:fail("TRADE_THESIS_FIELDS_INVALID")
    if (record["schema_version"],record["version"],record["thesis_engine_version"],record["code_commit"],record["authority_mode"])!=(SCHEMA_VERSION,1,THESIS_ENGINE_VERSION,BASELINE_COMMIT,AUTHORITY):fail("TRADE_THESIS_IDENTITY_INVALID")
    try:parse_utc(record["decision_cutoff"],"decision_cutoff");date.fromisoformat(record["last_review_date"])
    except Exception as exc:raise TradeThesisIntegrityFailure("TRADE_THESIS_TIME_INVALID") from exc
    if record["entry_date"] is not None:
        try:date.fromisoformat(record["entry_date"])
        except Exception as exc:raise TradeThesisIntegrityFailure("TRADE_THESIS_ENTRY_DATE_INVALID") from exc
    if not isinstance(record["input_records"],list) or len(record["input_records"])!=1 or not binding(record["input_records"][0]) or record["input_records"][0]["record_type"]!=SEED_SCHEMA_VERSION:fail("TRADE_THESIS_INPUT_INVALID")
    for field in ("recommendation_id","ticker","holding_horizon"):
        if not isinstance(record[field],str) or not record[field]:fail("TRADE_THESIS_REQUIRED_VALUE_INVALID")
    for field,allow_empty in (("entry_rationale",False),("supporting_evidence",True),("known_risks",True),("invalidation_conditions",False)):
        if not strings(record[field],allow_empty):fail("TRADE_THESIS_LIST_INVALID")
        if field=="supporting_evidence" and len(record[field])!=len(set(record[field])):fail("TRADE_THESIS_EVIDENCE_DUPLICATE")
    r=record["initial_entry_range"]
    if not isinstance(r,dict) or set(r)!={"low","high","currency"} or not positive(r["low"]) or not positive(r["high"]) or r["low"]>r["high"] or r["currency"]!="INR":fail("TRADE_THESIS_RANGE_INVALID")
    if not isinstance(record["fill_references"],list):fail("TRADE_THESIS_FILLS_INVALID")
    for fill in record["fill_references"]:
        if not isinstance(fill,dict) or set(fill)!=FILL_FIELDS or type(fill["quantity"]) is not int or fill["quantity"]<=0 or not positive(fill["price"]) or fill["currency"]!="INR" or fill["source_system"]!="STAGE5D5_FROZEN_PRODUCTION_CONTROL":fail("TRADE_THESIS_FILL_INVALID")
        try:date.fromisoformat(fill["fill_date"])
        except Exception as exc:raise TradeThesisIntegrityFailure("TRADE_THESIS_FILL_DATE_INVALID") from exc
    aggregate=record["aggregate_fill"]
    if aggregate is not None and (not isinstance(aggregate,dict) or set(aggregate)!={"total_quantity","volume_weighted_average_price","currency"} or type(aggregate["total_quantity"]) is not int or aggregate["total_quantity"]<=0 or not positive(aggregate["volume_weighted_average_price"]) or aggregate["currency"]!="INR"):fail("TRADE_THESIS_AGGREGATE_INVALID")
    if not all(price(record[x]) for x in ("initial_stop","current_stop","initial_target","current_target")):fail("TRADE_THESIS_PRICE_INVALID")
    if record["thesis_status"]!="THESIS_UNCHANGED" or record["previous_version_hash"] is not None:fail("TRADE_THESIS_INITIAL_STATE_INVALID")
    if not isinstance(record["change_history"],list) or len(record["change_history"])!=1:fail("TRADE_THESIS_CHANGE_HISTORY_INVALID")
    change=record["change_history"][0]
    if not isinstance(change,dict) or set(change)!=CHANGE_FIELDS or (change["version"],change["changed_at_utc"],change["decision_cutoff"],change["change_type"],change["reason"],change["input_records"])!=(1,record["decision_cutoff"],record["decision_cutoff"],"INITIAL_THESIS_CREATED","INITIAL_BASELINE_FROM_IMMUTABLE_SEED",record["input_records"]) or change["evidence_ids"]!=record["supporting_evidence"]:fail("TRADE_THESIS_CHANGE_HISTORY_INVALID")
    if record["thesis_id"]!="S6THESIS_"+canonical_hash(without(record,"thesis_id","record_hash"))[:24] or record["record_hash"]!=canonical_hash(without(record,"record_hash")):fail("TRADE_THESIS_HASH_INVALID")
    if seed is not None:
        from .trade_thesis_builder import build_trade_thesis
        if build_trade_thesis(seed)!=record:fail("TRADE_THESIS_SEED_REPLAY_MISMATCH")
    return record

def validate_materialization_record(record,seed=None):
    if not isinstance(record,dict) or set(record)!=WRAPPER_FIELDS:fail("TRADE_THESIS_WRAPPER_FIELDS_INVALID")
    expected=(WRAPPER_SCHEMA_VERSION,POLICY_ID,MATERIALIZATION_CONTRACT_VERSION,PROCESSOR_VERSION,BASELINE_COMMIT,TRADE_THESIS_BLOB,AUTHORITY)
    if tuple(record.get(x) for x in ("schema_version","policy_id","materialization_contract_version","processor_version","code_commit","trade_thesis_schema_blob","authority"))!=expected:fail("TRADE_THESIS_WRAPPER_IDENTITY_INVALID")
    if not HASH.fullmatch(str(record.get("policy_hash",""))) or not HASH.fullmatch(str(record.get("materialization_contract_hash",""))):fail("TRADE_THESIS_WRAPPER_DEPENDENCY_HASH_INVALID")
    for key,value in SAFETY.items():
        if record.get(key)!=value:fail("TRADE_THESIS_WRAPPER_SAFETY_INVALID")
    validate_trade_thesis(record["trade_thesis"],seed)
    if record["seed_binding"]!=record["trade_thesis"]["input_records"][0]:fail("TRADE_THESIS_WRAPPER_SEED_BINDING_INVALID")
    if record["materialization_record_id"]!="S6THMAT_"+canonical_hash(without(record,"materialization_record_id","record_hash"))[:24] or record["record_hash"]!=canonical_hash(without(record,"record_hash")):fail("TRADE_THESIS_WRAPPER_HASH_INVALID")
    return record
