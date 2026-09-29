import re
from stage6_ingestion.canonical import canonical_hash,parse_utc,utc_timestamp,without
from .errors import ThesisReviewInputIntegrityFailure
from .policy import *
from .review_input_builder import SAFETY

HASH=re.compile(r"[a-f0-9]{64}");BINDING_FIELDS={"record_type","record_id","record_hash"}
FIELDS={"schema_version","review_snapshot_id","previous_thesis_binding","thesis_id","thesis_version","recommendation_id","ticker","prior_decision_cutoff","review_cutoff","new_evidence_status","new_evidence_bindings","company_effect_status","company_effect_bindings","company_effect_summaries","market_context_status","market_context_binding","historical_analogue_status","historical_analogue_binding","historical_analogue_relevance","portfolio_context_status","portfolio_context_binding","portfolio_subject_presence","direct_input_bindings","factual_delta_metadata","processor_version","policy_id","policy_hash","review_input_contract_version","review_input_contract_hash","authority",*SAFETY.keys(),"record_hash"}
SUMMARY_FIELDS={"company_effect_record_id","event_id","event_version","event_hash","exposure_id","exposure_version","exposure_hash","company_entity_id","company_event_effect","review_relevance"};META_FIELDS={"new_evidence_count","company_effect_count","market_context_provided","historical_analogue_provided","portfolio_context_provided","elapsed_seconds","elapsed_days"}
def fail(code):raise ThesisReviewInputIntegrityFailure(code)
def is_binding(x,kind=None):return isinstance(x,dict) and set(x)==BINDING_FIELDS and isinstance(x["record_id"],str) and bool(x["record_id"]) and bool(HASH.fullmatch(str(x["record_hash"]))) and isinstance(x["record_type"],str) and (kind is None or x["record_type"]==kind)
def validate_review_request(*,thesis_id,review_cutoff,evidence_ids,company_effect_ids,market_context_id,historical_analogue_id,portfolio_context_id):
 if not isinstance(thesis_id,str) or not thesis_id:fail("PREVIOUS_THESIS_ID_REQUIRED")
 if not isinstance(review_cutoff,str) or not review_cutoff.endswith("Z"):fail("REVIEW_CUTOFF_UTC_REQUIRED")
 try:utc_timestamp(review_cutoff,"review_cutoff")
 except Exception as exc:raise ThesisReviewInputIntegrityFailure("REVIEW_CUTOFF_UTC_REQUIRED") from exc
 for name,values in (("evidence",evidence_ids),("company_effect",company_effect_ids)):
  if not isinstance(values,list) or any(not isinstance(x,str) or not x for x in values) or len(values)!=len(set(values)):fail(f"{name.upper()}_IDS_INVALID")
 for name,value in (("market_context",market_context_id),("historical_analogue",historical_analogue_id),("portfolio_context",portfolio_context_id)):
  if value is not None and (not isinstance(value,str) or not value):fail(f"{name.upper()}_ID_INVALID")
 return True
def validate_review_snapshot(r):
 if not isinstance(r,dict) or set(r)!=FIELDS:fail("THESIS_REVIEW_FIELDS_INVALID")
 if tuple(r.get(k) for k in ("schema_version","processor_version","policy_id","policy_hash","review_input_contract_version","review_input_contract_hash","authority"))!=(SCHEMA_VERSION,PROCESSOR_VERSION,POLICY_ID,EXPECTED_POLICY_HASH_V1,CONTRACT_VERSION,EXPECTED_CONTRACT_HASH_V1,AUTHORITY):fail("THESIS_REVIEW_IDENTITY_INVALID")
 if not is_binding(r["previous_thesis_binding"],TRADE_THESIS_SCHEMA) or r["previous_thesis_binding"]["record_id"]!=r["thesis_id"] or r["thesis_version"]!=1:fail("PREVIOUS_THESIS_BINDING_INVALID")
 try:prior=parse_utc(r["prior_decision_cutoff"],"prior");review=parse_utc(r["review_cutoff"],"review")
 except Exception as exc:raise ThesisReviewInputIntegrityFailure("THESIS_REVIEW_TIMESTAMP_INVALID") from exc
 if review<=prior:fail("REVIEW_CUTOFF_NOT_AFTER_PREVIOUS")
 pairs=(("new_evidence_status","new_evidence_bindings",EVIDENCE_SCHEMA),("company_effect_status","company_effect_bindings",COMPANY_EFFECT_SCHEMA))
 for status,items,kind in pairs:
  if r[status]!=("AVAILABLE" if r[items] else "NOT_PROVIDED") or not all(is_binding(x,kind) for x in r[items]):fail("THESIS_REVIEW_AVAILABILITY_INVALID")
 if r["new_evidence_bindings"]!=sorted(r["new_evidence_bindings"],key=lambda x:x["record_id"]):fail("THESIS_REVIEW_EVIDENCE_ORDER_INVALID")
 if len({x["record_id"] for x in r["new_evidence_bindings"]})!=len(r["new_evidence_bindings"]):fail("THESIS_REVIEW_EVIDENCE_DUPLICATE")
 if len(r["company_effect_summaries"])!=len(r["company_effect_bindings"]):fail("THESIS_REVIEW_EFFECT_COVERAGE_INVALID")
 allowed={"FAVORABLE","ADVERSE","MIXED","INDETERMINATE","NOT_EVALUATED"}
 for x in r["company_effect_summaries"]:
  if not isinstance(x,dict) or set(x)!=SUMMARY_FIELDS or x["company_event_effect"] not in allowed or x["review_relevance"]!="CALLER_SELECTED_UNINTERPRETED":fail("THESIS_REVIEW_EFFECT_SUMMARY_INVALID")
 if [x["company_effect_record_id"] for x in r["company_effect_summaries"]]!=[x["record_id"] for x in r["company_effect_bindings"]]:fail("THESIS_REVIEW_EFFECT_BINDING_MISMATCH")
 options=(("market_context",MARKET_SCHEMA),("historical_analogue",ANALOGUE_SCHEMA),("portfolio_context",PORTFOLIO_SCHEMA))
 for prefix,kind in options:
  status=r[prefix+"_status"];value=r[prefix+"_binding"]
  if status not in {"AVAILABLE","NOT_PROVIDED"} or (status=="AVAILABLE")!=(value is not None) or (value is not None and not is_binding(value,kind)):fail("THESIS_REVIEW_OPTIONAL_INPUT_INVALID")
 if r["historical_analogue_relevance"]!=("CALLER_SELECTED_UNINTERPRETED" if r["historical_analogue_binding"] else "NOT_PROVIDED"):fail("THESIS_REVIEW_ANALOGUE_RELEVANCE_INVALID")
 if r["portfolio_subject_presence"] not in {"OPEN_POSITION","PENDING_ENTRY","OPEN_AND_PENDING","NOT_PRESENT","NOT_PROVIDED"}:fail("THESIS_REVIEW_PORTFOLIO_PRESENCE_INVALID")
 expected=sorted([r["previous_thesis_binding"],*r["new_evidence_bindings"],*r["company_effect_bindings"],*([r["market_context_binding"]] if r["market_context_binding"] else []),*([r["historical_analogue_binding"]] if r["historical_analogue_binding"] else []),*([r["portfolio_context_binding"]] if r["portfolio_context_binding"] else [])],key=lambda x:(x["record_type"],x["record_id"]))
 if r["direct_input_bindings"]!=expected or len({(x["record_type"],x["record_id"]) for x in expected})!=len(expected):fail("THESIS_REVIEW_DIRECT_INPUT_INVALID")
 meta=r["factual_delta_metadata"]
 if not isinstance(meta,dict) or set(meta)!=META_FIELDS or meta["new_evidence_count"]!=len(r["new_evidence_bindings"]) or meta["company_effect_count"]!=len(r["company_effect_bindings"]) or meta["market_context_provided"]!=(r["market_context_binding"] is not None) or meta["historical_analogue_provided"]!=(r["historical_analogue_binding"] is not None) or meta["portfolio_context_provided"]!=(r["portfolio_context_binding"] is not None):fail("THESIS_REVIEW_FACTUAL_METADATA_INVALID")
 seconds=(review-prior).total_seconds()
 if meta["elapsed_seconds"]!=seconds or meta["elapsed_days"]!=seconds/86400:fail("THESIS_REVIEW_ELAPSED_INVALID")
 for key,value in SAFETY.items():
  if r.get(key)!=value:fail("THESIS_REVIEW_SAFETY_INVALID")
 if r["review_snapshot_id"]!="S6THREVINPUT_"+canonical_hash(without(r,"review_snapshot_id","record_hash"))[:24] or r["record_hash"]!=canonical_hash(without(r,"record_hash")):fail("THESIS_REVIEW_HASH_INVALID")
 return r
