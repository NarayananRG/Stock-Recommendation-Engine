from stage6_ingestion.canonical import canonical_hash, without
from .errors import Stage6MorningProposalError, MorningProposalIntegrityFailure
from .policy import *
from .decision_rules import REASONS
from .morning_revalidation_proposal_builder import SAFETY, build_proposal, canonical_assertions, canonical_assessments, support_key

ASSESSMENT_FIELDS={"condition_index","condition_text","evaluation_status","supporting_bindings"};ASSERTION_FIELDS={"assessment","reason_code","supporting_bindings"};BINDING_FIELDS={"record_type","record_id","record_hash"}
def _bindings(values,universe,required,code):
 if not isinstance(values,list) or (required and not values):raise Stage6MorningProposalError(code+"_SUPPORT_REQUIRED")
 keys=[]
 for value in values:
  if not isinstance(value,dict) or set(value)!=BINDING_FIELDS:raise Stage6MorningProposalError(code+"_SUPPORT_INVALID")
  key=support_key(value)
  if key not in universe:raise Stage6MorningProposalError(code+"_SUPPORT_OUTSIDE_SNAPSHOT")
  keys.append(key)
 if len(keys)!=len(set(keys)):raise Stage6MorningProposalError(code+"_SUPPORT_DUPLICATE")
def validate_inputs(thesis,assessments,assertions,universe):
 conditions=thesis["invalidation_conditions"]
 if not isinstance(assessments,list) or len(assessments)!=len(conditions):raise Stage6MorningProposalError("INVALIDATION_COVERAGE_INVALID")
 seen=[]
 for value in assessments:
  if not isinstance(value,dict) or set(value)!=ASSESSMENT_FIELDS:raise Stage6MorningProposalError("INVALIDATION_ASSESSMENT_FIELDS_INVALID")
  i=value["condition_index"]
  if type(i) is not int or i<0 or i>=len(conditions):raise Stage6MorningProposalError("INVALIDATION_INDEX_INVALID")
  if value["condition_text"]!=conditions[i]:raise Stage6MorningProposalError("INVALIDATION_TEXT_INVALID")
  if value["evaluation_status"] not in INVALIDATION_STATUSES:raise Stage6MorningProposalError("INVALIDATION_STATUS_INVALID")
  _bindings(value["supporting_bindings"],universe,value["evaluation_status"]!="NOT_EVALUATED","INVALIDATION")
  seen.append(i)
 if sorted(seen)!=list(range(len(conditions))) or len(seen)!=len(set(seen)):raise Stage6MorningProposalError("INVALIDATION_INDEX_COVERAGE_INVALID")
 if not isinstance(assertions,list):raise Stage6MorningProposalError("CHANGE_ASSERTIONS_INVALID")
 for value in assertions:
  if not isinstance(value,dict) or set(value)!=ASSERTION_FIELDS:raise Stage6MorningProposalError("CHANGE_ASSERTION_FIELDS_INVALID")
  if value["assessment"] not in ASSERTION_ASSESSMENTS:raise Stage6MorningProposalError("CHANGE_ASSERTION_ASSESSMENT_INVALID")
  if value["reason_code"] not in ASSERTION_REASONS:raise Stage6MorningProposalError("CHANGE_ASSERTION_REASON_INVALID")
  _bindings(value["supporting_bindings"],universe,True,"CHANGE_ASSERTION")
 return canonical_assessments(assessments),canonical_assertions(assertions)
def validate_proposal(record,snapshot,thesis,portfolio,assessments,assertions,policy_hash,contract_hash,manifest):
 if record.get("schema_version")!=PROPOSAL_SCHEMA or record.get("proposal_decision") not in DECISIONS or record.get("proposal_reason_code") not in REASONS:raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_IDENTITY_INVALID")
 if any(record.get(k)!=v for k,v in SAFETY.items()):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_SAFETY_INVALID")
 expected=build_proposal(snapshot=snapshot,thesis=thesis,portfolio=portfolio,invalidation_assessments=assessments,change_assertions=assertions,policy_hash=policy_hash,contract_hash=contract_hash,manifest=manifest)
 if record!=expected or record["record_hash"]!=canonical_hash(without(record,"record_hash")):raise MorningProposalIntegrityFailure("MORNING_PROPOSAL_REPLAY_MISMATCH")
 return True
