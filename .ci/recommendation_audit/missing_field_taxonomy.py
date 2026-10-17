"""Fail-closed missing fundamental field classification for canonical panel rows.

No fabricated values, provider fallback, or scoring changes.
"""
from collections import Counter

SELECTED={"SELECTED","SELECTED_EQUIVALENT_DUPLICATES"}
def classify(row,feature="DEBT_EQUITY_RATIO"):
    if not isinstance(row,dict):raise ValueError("Panel row required")
    status=row.get(feature+"__status")
    value=row.get(feature+"__value")
    if row.get("archive_gap") is True or status=="SOURCE_DOCUMENT_UNAVAILABLE":
        kind="SOURCE_DOCUMENT_UNAVAILABLE"
    elif status is None or status=="NOT_MAPPED_FOR_DOMAIN":
        kind="MAPPING_NOT_AVAILABLE"
    elif status in SELECTED and value is not None:
        kind="AVAILABLE"
    elif status in SELECTED:
        kind="SELECTED_VALUE_MISSING"
    elif status in ("AMBIGUOUS_MULTIPLE_CANDIDATES","AMBIGUOUS","CONFLICTING_FACTS"):
        kind="AMBIGUOUS_FACTS"
    elif status in ("MISSING","NO_ALIGNED_UNDIMENSIONED_CANDIDATE"):
        kind="NO_ELIGIBLE_FACT"
    else:
        kind="UNRESOLVED_STATUS"
    return {"kind":kind,"recoverable_automatically":False,"manual_review":kind not in ("AVAILABLE","SOURCE_DOCUMENT_UNAVAILABLE")}

def summarize(rows,feature="DEBT_EQUITY_RATIO"):
    count=Counter()
    for row in rows:
        result=classify(row,feature)
        count[result["kind"]]+=1
    return {"feature":feature,"rows":sum(count.values()),"statuses":dict(sorted(count.items())),"production_changed":False}
