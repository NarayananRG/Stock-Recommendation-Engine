from .policy import ASSERTION_ASSESSMENTS, DECISIONS

REASONS={
 "CURRENT_THESIS_INVALIDATED","INVALIDATION_TRIGGERED","INVALIDATION_NOT_FULLY_EVALUATED",
 "MARKET_CONTEXT_NOT_PROVIDED","CHANGE_ASSERTION_INDETERMINATE","CONFLICTING_MATERIAL_CHANGE",
 "ADVERSE_MATERIAL_CHANGE","SUPPORTIVE_REVALIDATION","NO_MATERIAL_ENTRY_BLOCKER",
}
def decide(thesis_status,invalidation_assessments,change_assertions,market_availability):
 states=[x["evaluation_status"] for x in invalidation_assessments];changes=[x["assessment"] for x in change_assertions]
 if thesis_status=="THESIS_INVALIDATED":return "CANCEL_ENTRY","CURRENT_THESIS_INVALIDATED"
 if "TRIGGERED" in states:return "CANCEL_ENTRY","INVALIDATION_TRIGGERED"
 if "NOT_EVALUATED" in states:return "WAIT","INVALIDATION_NOT_FULLY_EVALUATED"
 if market_availability!="AVAILABLE":return "WAIT","MARKET_CONTEXT_NOT_PROVIDED"
 if "INDETERMINATE" in changes:return "WAIT","CHANGE_ASSERTION_INDETERMINATE"
 supportive="SUPPORTIVE_MATERIAL" in changes;adverse="ADVERSE_MATERIAL" in changes
 if supportive and adverse:return "WAIT","CONFLICTING_MATERIAL_CHANGE"
 if adverse:return "WAIT","ADVERSE_MATERIAL_CHANGE"
 if supportive:return "ENTRY_VALID","SUPPORTIVE_REVALIDATION"
 return "ENTRY_VALID","NO_MATERIAL_ENTRY_BLOCKER"
