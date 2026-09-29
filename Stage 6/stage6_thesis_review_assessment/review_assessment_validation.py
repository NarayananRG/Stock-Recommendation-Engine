from stage6_ingestion.canonical import canonical_hash,without
from .errors import ThesisReviewAssessmentIntegrityFailure
from .policy import *
from .review_assessment_builder import SAFETY,canonical_support,decide
BINDING_FIELDS={"record_type","record_id","record_hash"};INVALIDATION_FIELDS={"condition_index","condition_text","evaluation_status","supporting_bindings"};ASSERTION_FIELDS={"assertion_id","assessment","reason_code","supporting_bindings"}
FIELDS={"schema_version","assessment_id","previous_thesis_binding","review_snapshot_binding","thesis_id","previous_thesis_version","recommendation_id","ticker","prior_decision_cutoff","review_cutoff","invalidation_assessments","change_assertions","material_change_status","review_outcome","target_thesis_status","transition_reason_code","thesis_status_evaluation","next_thesis_version_status","proposed_transition_metadata","review_evidence_ids","decision_semantics_version","processor_version","policy_id","policy_hash","assessment_contract_version","assessment_contract_hash","authority",*SAFETY.keys(),"record_hash"}
PROPOSED_FIELDS={"previous_version","proposed_next_version","previous_version_hash","target_thesis_status","review_cutoff","last_review_date","change_type","change_reason_code","review_evidence_ids","next_version_direct_input_policy"}
def fail(code):raise ThesisReviewAssessmentIntegrityFailure(code)
def binding(x):return isinstance(x,dict) and set(x)==BINDING_FIELDS and all(isinstance(x[k],str) and x[k] for k in BINDING_FIELDS)
def validate_structured(thesis,snapshot,invalidations,assertions):
 if not isinstance(invalidations,list) or not isinstance(assertions,list):fail("STRUCTURED_ASSESSMENT_ARRAY_REQUIRED")
 if len(invalidations)!=len(thesis["invalidation_conditions"]):fail("INVALIDATION_COVERAGE_INVALID")
 indices=[];available={tuple(x[k] for k in ("record_type","record_id","record_hash")) for x in snapshot["direct_input_bindings"] if x["record_type"] in ALLOWED_SUPPORT}
 for x in invalidations:
  if not isinstance(x,dict) or set(x)!=INVALIDATION_FIELDS or type(x["condition_index"]) is not int:fail("INVALIDATION_ASSESSMENT_FIELDS_INVALID")
  i=x["condition_index"];indices.append(i)
  if i<0 or i>=len(thesis["invalidation_conditions"]) or x["condition_text"]!=thesis["invalidation_conditions"][i] or x["evaluation_status"] not in INVALIDATION_STATUSES:fail("INVALIDATION_ASSESSMENT_INVALID")
  supports=x["supporting_bindings"]
  if not isinstance(supports,list) or any(not binding(v) or tuple(v[k] for k in ("record_type","record_id","record_hash")) not in available for v in supports) or len({tuple(v.values()) for v in supports})!=len(supports):fail("INVALIDATION_SUPPORT_INVALID")
  if x["evaluation_status"]=="TRIGGERED" and not supports:fail("TRIGGERED_SUPPORT_REQUIRED")
  if x["evaluation_status"]=="NOT_EVALUATED" and supports:fail("UNEVALUATED_SUPPORT_PROHIBITED")
 if sorted(indices)!=list(range(len(thesis["invalidation_conditions"]))):fail("INVALIDATION_INDEX_COVERAGE_INVALID")
 for x in assertions:
  if not isinstance(x,dict) or set(x)!=ASSERTION_FIELDS or x["assessment"] not in CHANGE_ASSESSMENTS or x["reason_code"] not in REASON_CODES:fail("CHANGE_ASSERTION_INVALID")
  supports=x["supporting_bindings"]
  if not isinstance(supports,list) or not supports or any(not binding(v) or tuple(v[k] for k in ("record_type","record_id","record_hash")) not in available for v in supports) or len({tuple(v.values()) for v in supports})!=len(supports):fail("CHANGE_ASSERTION_SUPPORT_INVALID")
  core={"assessment":x["assessment"],"reason_code":x["reason_code"],"supporting_bindings":canonical_support(supports)}
  if x["assertion_id"]!="S6THASSERT_"+canonical_hash(core)[:24]:fail("CHANGE_ASSERTION_ID_INVALID")
 return True
def validate_assessment(r,thesis=None,snapshot=None):
 if not isinstance(r,dict) or set(r)!=FIELDS:fail("THESIS_REVIEW_ASSESSMENT_FIELDS_INVALID")
 identity=tuple(r.get(k) for k in ("schema_version","decision_semantics_version","processor_version","policy_id","policy_hash","assessment_contract_version","assessment_contract_hash","authority"))
 if identity!=(SCHEMA_VERSION,DECISION_SEMANTICS_VERSION,PROCESSOR_VERSION,POLICY_ID,EXPECTED_POLICY_HASH_V1,CONTRACT_VERSION,EXPECTED_CONTRACT_HASH_V1,AUTHORITY):fail("THESIS_REVIEW_ASSESSMENT_IDENTITY_INVALID")
 if not binding(r["previous_thesis_binding"]) or r["previous_thesis_binding"]["record_type"]!=TRADE_THESIS_SCHEMA or not binding(r["review_snapshot_binding"]) or r["review_snapshot_binding"]["record_type"]!=SNAPSHOT_SCHEMA:fail("THESIS_REVIEW_ASSESSMENT_BINDING_INVALID")
 if r["previous_thesis_version"]!=1:fail("THESIS_REVIEW_PREVIOUS_VERSION_INVALID")
 wanted=decide(r["invalidation_assessments"],r["change_assertions"])
 if tuple(r[k] for k in ("material_change_status","review_outcome","target_thesis_status","transition_reason_code"))!=wanted:fail("THESIS_REVIEW_DECISION_INVALID")
 determinate=r["review_outcome"]=="DETERMINATE"
 if r["thesis_status_evaluation"]!=("EVALUATED" if determinate else "INDETERMINATE") or r["next_thesis_version_status"]!=("READY_FOR_MATERIALIZATION" if determinate else "WITHHELD_INDETERMINATE"):fail("THESIS_REVIEW_READINESS_INVALID")
 supports=[b for x in [*r["invalidation_assessments"],*r["change_assertions"]] for b in x["supporting_bindings"]];evidence=sorted({b["record_id"] for b in supports if b["record_type"]=="STAGE6_EVIDENCE_V2"})
 if r["review_evidence_ids"]!=evidence:fail("THESIS_REVIEW_EVIDENCE_IDS_INVALID")
 if determinate:
  p=r["proposed_transition_metadata"]
  if not isinstance(p,dict) or set(p)!=PROPOSED_FIELDS or p["previous_version"]!=1 or p["proposed_next_version"]!=2 or p["previous_version_hash"]!=r["previous_thesis_binding"]["record_hash"] or p["target_thesis_status"]!=r["target_thesis_status"] or p["review_cutoff"]!=r["review_cutoff"] or p["last_review_date"]!=r["review_cutoff"][:10] or p["change_reason_code"]!=r["transition_reason_code"] or p["review_evidence_ids"]!=evidence or p["next_version_direct_input_policy"]!=[TRADE_THESIS_SCHEMA,SNAPSHOT_SCHEMA,SCHEMA_VERSION]:fail("THESIS_REVIEW_PROPOSED_TRANSITION_INVALID")
 else:
  if r["proposed_transition_metadata"] is not None or r["target_thesis_status"] is not None:fail("THESIS_REVIEW_INDETERMINATE_TRANSITION_INVALID")
 for key,value in SAFETY.items():
  if r.get(key)!=value:fail("THESIS_REVIEW_ASSESSMENT_SAFETY_INVALID")
 if r["assessment_id"]!="S6THREVASS_"+canonical_hash(without(r,"assessment_id","record_hash"))[:24] or r["record_hash"]!=canonical_hash(without(r,"record_hash")):fail("THESIS_REVIEW_ASSESSMENT_HASH_INVALID")
 if thesis is not None and snapshot is not None:
  validate_structured(thesis,snapshot,r["invalidation_assessments"],r["change_assertions"])
  if (r["thesis_id"],r["recommendation_id"],r["ticker"],r["prior_decision_cutoff"],r["previous_thesis_binding"]['record_id'],r["previous_thesis_binding"]['record_hash'],r["review_snapshot_binding"]['record_id'],r["review_snapshot_binding"]['record_hash'],r["review_cutoff"])!=(thesis["thesis_id"],thesis["recommendation_id"],thesis["ticker"],thesis["decision_cutoff"],thesis["thesis_id"],thesis["record_hash"],snapshot["review_snapshot_id"],snapshot["record_hash"],snapshot["review_cutoff"]):fail("THESIS_REVIEW_CROSS_BINDING_INVALID")
 return r
