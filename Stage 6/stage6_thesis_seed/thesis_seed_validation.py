import math
import re
from datetime import date

from stage6_ingestion.canonical import canonical_hash, parse_utc, utc_timestamp, without
from .errors import ThesisSeedIntegrityFailure
from .fill_math import aggregate_fills, canonicalize_fills, decimal_value
from .policy import *
from .thesis_seed_builder import SAFETY

HASH=re.compile(r"[a-f0-9]{64}")
SOURCE_FIELDS={"source_system","source_stage5d5_commit","source_export_id","source_export_hash","source_database_id","source_schema_version","decision_cutoff","recommendation_binding","recommendation_id","ticker","holding_horizon","entry_rationale","known_risks","initial_entry_range","fills","initial_stop","initial_target","invalidation_conditions","supporting_evidence_ids"}
FILL_FIELDS={"transaction_id","recommendation_id","fill_date","quantity","price","currency","source_system","source_record_hash","source_recorded_at_utc"}
BINDING_FIELDS={"record_type","record_id","record_hash","recorded_at_utc"}

def fail(code): raise ThesisSeedIntegrityFailure(code)
def nonempty(value,field):
    if not isinstance(value,str) or not value:fail(f"{field.upper()}_REQUIRED")
def timestamp(value,field):
    try:return utc_timestamp(value,field)
    except Exception as exc:raise ThesisSeedIntegrityFailure(f"{field.upper()}_INVALID") from exc
def price(value,field):
    if value is None:return
    if not isinstance(value,dict) or set(value)!={"value","currency"} or value.get("currency")!="INR" or decimal_value(value.get("value"),field)<=0:fail(f"{field.upper()}_INVALID")
def string_array(value,field,allow_empty):
    if not isinstance(value,list) or (not allow_empty and not value) or any(not isinstance(x,str) or not x for x in value):fail(f"{field.upper()}_INVALID")

def validate_source(source):
    if not isinstance(source,dict) or set(source)!=SOURCE_FIELDS:fail("SOURCE_EXPORT_FIELDS_INVALID")
    if source["source_system"] not in {"FIXTURE","STAGE5D5_THESIS_SEED_EXPORT"}:fail("SOURCE_SYSTEM_INVALID")
    if source["source_system"]=="STAGE5D5_THESIS_SEED_EXPORT" and source["source_stage5d5_commit"]!=STAGE5D5_COMMIT:fail("STAGE5D5_COMMIT_MISMATCH")
    if source["source_system"]=="FIXTURE" and source["source_stage5d5_commit"] is not None:fail("FIXTURE_STAGE5D5_COMMIT_INVALID")
    for field in ("source_export_id","source_database_id","source_schema_version","recommendation_id","ticker","holding_horizon"):nonempty(source[field],field)
    if not isinstance(source["source_export_hash"],str) or not HASH.fullmatch(source["source_export_hash"]):fail("SOURCE_EXPORT_HASH_INVALID")
    cutoff=timestamp(source["decision_cutoff"],"decision_cutoff")
    binding=source["recommendation_binding"]
    if not isinstance(binding,dict) or set(binding)!=BINDING_FIELDS or binding.get("record_type")!="RECOMMENDATION" or binding.get("record_id")!=source["recommendation_id"] or not HASH.fullmatch(str(binding.get("record_hash",""))):fail("RECOMMENDATION_BINDING_INVALID")
    if parse_utc(timestamp(binding["recorded_at_utc"],"recommendation_recorded_at_utc"),"recommendation")>parse_utc(cutoff,"cutoff"):fail("RECOMMENDATION_AFTER_CUTOFF")
    string_array(source["entry_rationale"],"entry_rationale",False);string_array(source["known_risks"],"known_risks",True);string_array(source["invalidation_conditions"],"invalidation_conditions",False)
    entry=source["initial_entry_range"]
    if not isinstance(entry,dict) or set(entry)!={"low","high","currency"} or entry.get("currency")!="INR":fail("INITIAL_ENTRY_RANGE_INVALID")
    low,high=decimal_value(entry.get("low"),"entry_low"),decimal_value(entry.get("high"),"entry_high")
    if low<=0 or high<=0 or low>high:fail("INITIAL_ENTRY_RANGE_INVALID")
    price(source["initial_stop"],"initial_stop");price(source["initial_target"],"initial_target")
    if not isinstance(source["fills"],list):fail("FILLS_INVALID")
    ids=[]
    for fill in source["fills"]:
        if not isinstance(fill,dict) or set(fill)!=FILL_FIELDS:fail("FILL_FIELDS_INVALID")
        nonempty(fill["transaction_id"],"transaction_id");ids.append(fill["transaction_id"])
        if fill["recommendation_id"]!=source["recommendation_id"]:fail("FILL_RECOMMENDATION_MISMATCH")
        if type(fill["quantity"]) is not int or fill["quantity"]<=0:fail("FILL_QUANTITY_INVALID")
        if decimal_value(fill["price"],"fill_price")<=0:fail("FILL_PRICE_INVALID")
        if fill["currency"]!="INR" or fill["source_system"]!="STAGE5D5_FROZEN_PRODUCTION_CONTROL":fail("FILL_SOURCE_INVALID")
        try:fill_date=date.fromisoformat(fill["fill_date"])
        except Exception as exc:raise ThesisSeedIntegrityFailure("FILL_DATE_INVALID") from exc
        if fill_date>date.fromisoformat(cutoff[:10]):fail("FILL_AFTER_CUTOFF")
        if not HASH.fullmatch(str(fill["source_record_hash"])):fail("FILL_RECORD_HASH_INVALID")
        if parse_utc(timestamp(fill["source_recorded_at_utc"],"fill_recorded_at_utc"),"fill")>parse_utc(cutoff,"cutoff"):fail("FILL_PROVENANCE_AFTER_CUTOFF")
    if len(ids)!=len(set(ids)):fail("DUPLICATE_TRANSACTION_ID")
    evidence=source["supporting_evidence_ids"]
    if not isinstance(evidence,list) or any(not isinstance(x,str) or not x for x in evidence) or len(evidence)!=len(set(evidence)):fail("SUPPORTING_EVIDENCE_IDS_INVALID")
    return source

def validate_seed(record):
    if not isinstance(record,dict) or record.get("schema_version")!=SCHEMA_VERSION:fail("THESIS_SEED_SCHEMA_INVALID")
    if tuple(record.get(x) for x in ("processor_version","policy_id","seed_contract_version","authority"))!=(PROCESSOR_VERSION,POLICY_ID,SEED_CONTRACT_VERSION,AUTHORITY):fail("THESIS_SEED_IDENTITY_INVALID")
    for key,value in SAFETY.items():
        if record.get(key)!=value:fail("THESIS_SEED_SAFETY_INVALID")
    if record.get("seed_record_id")!="S6THSEED_"+canonical_hash(without(record,"seed_record_id","record_hash"))[:24] or record.get("record_hash")!=canonical_hash(without(record,"record_hash")):fail("THESIS_SEED_HASH_INVALID")
    if record["projected_fill_references"]!=[{k:x[k] for k in ("transaction_id","fill_date","quantity","price","currency","source_system")} for x in canonicalize_fills(record["original_fill_audit_records"])]:fail("THESIS_SEED_FILL_PROJECTION_INVALID")
    aggregate,entry_date=aggregate_fills(record["original_fill_audit_records"])
    if record["aggregate_fill"]!=aggregate or record["derived_entry_date"]!=entry_date:fail("THESIS_SEED_AGGREGATE_INVALID")
    semantic=record["initial_thesis_semantic_projection"]
    if semantic["version"]!=1 or semantic["semantic_projection_version"]!=SEMANTIC_PROJECTION_VERSION or semantic["thesis_status"]!="THESIS_UNCHANGED" or semantic["current_stop"]!=record["initial_stop"] or semantic["current_target"]!=record["initial_target"] or semantic["previous_version_hash"] is not None or semantic["last_review_date"]!=record["decision_cutoff"][:10]:fail("THESIS_SEED_SEMANTIC_INVALID")
    change=semantic["initial_change_semantics"]
    if change!={"version":1,"change_type":"INITIAL_THESIS_CREATED","reason":"INITIAL_BASELINE_FROM_IMMUTABLE_SEED","changed_at_semantic":record["decision_cutoff"],"evidence_ids":record["supporting_evidence_ids"]}:fail("THESIS_SEED_CHANGE_SEMANTICS_INVALID")
    return record
