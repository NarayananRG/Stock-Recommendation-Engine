"""Continuity findings review for Fundamental Research V2 Phase 2A.4."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from .canonical_feature_panel import FEATURES, TARGET_QUARTERS

PRESENT_STATUSES={"SELECTED","SELECTED_EQUIVALENT_DUPLICATES"}
ADJACENT_PAIRS=tuple(zip(TARGET_QUARTERS[:-1],TARGET_QUARTERS[1:]))
YOY_PAIRS=tuple((TARGET_QUARTERS[i],TARGET_QUARTERS[i+4]) for i in range(len(TARGET_QUARTERS)-4))


def _feature_state(row: dict | None, feature: str) -> str:
    if row is None:
        return "ROW_ABSENT"
    if row.get("archive_gap"):
        return "ARCHIVE_GAP"
    status=row.get(f"{feature}__status")
    value=row.get(f"{feature}__value")
    if status=="NOT_MAPPED_FOR_DOMAIN":
        return "NOT_MAPPED_FOR_DOMAIN"
    if status in PRESENT_STATUSES and value not in (None,""):
        return "PRESENT"
    return "MISSING_IN_MAPPED_SCOPE"


def review_continuity(rows: Iterable[dict]) -> dict:
    items=list(rows)
    by_history=defaultdict(list)
    for row in items:
        by_history[(row.get("symbol"),row.get("reporting_basis"))].append(row)

    feature_rows=[]
    quarter_rows=[]
    history_feature_rows=[]

    for feature in FEATURES:
        global_counts=Counter()
        for row in items:
            global_counts[_feature_state(row,feature)]+=1

        for basis in sorted({x.get("reporting_basis") for x in items}):
            basis_items=[x for x in items if x.get("reporting_basis")==basis]
            counts=Counter(_feature_state(x,feature) for x in basis_items)

            history_count=0
            histories_with_2=0
            histories_with_4=0
            histories_with_6=0
            adjacent_pairs_present=0
            adjacent_pair_opportunities=0
            adjacent_pairs_archive_blocked=0
            yoy_pairs_present=0
            yoy_pair_opportunities=0
            yoy_pairs_archive_blocked=0

            for (symbol,hbasis),history in by_history.items():
                if hbasis!=basis:
                    continue
                qmap={x.get("quarter_end"):x for x in history}
                states={q:_feature_state(qmap.get(q),feature) for q in TARGET_QUARTERS}
                mapped_history=any(
                    state not in {"NOT_MAPPED_FOR_DOMAIN","ROW_ABSENT"}
                    for state in states.values()
                )
                if not mapped_history:
                    continue

                history_count+=1
                present_count=sum(1 for state in states.values() if state=="PRESENT")
                histories_with_2+=int(present_count>=2)
                histories_with_4+=int(present_count>=4)
                histories_with_6+=int(present_count==6)

                history_feature_rows.append({
                    "symbol":symbol,
                    "reporting_basis":basis,
                    "feature":feature,
                    "present_quarter_count":present_count,
                    "present_quarters":[q for q in TARGET_QUARTERS if states[q]=="PRESENT"],
                    "missing_quarters":[q for q in TARGET_QUARTERS if states[q]=="MISSING_IN_MAPPED_SCOPE"],
                    "archive_gap_quarters":[q for q in TARGET_QUARTERS if states[q]=="ARCHIVE_GAP"],
                    "row_absent_quarters":[q for q in TARGET_QUARTERS if states[q]=="ROW_ABSENT"],
                })

                for left,right in ADJACENT_PAIRS:
                    pair=(states[left],states[right])
                    if "NOT_MAPPED_FOR_DOMAIN" in pair or "ROW_ABSENT" in pair:
                        continue
                    adjacent_pair_opportunities+=1
                    if "ARCHIVE_GAP" in pair:
                        adjacent_pairs_archive_blocked+=1
                    elif pair==("PRESENT","PRESENT"):
                        adjacent_pairs_present+=1

                for left,right in YOY_PAIRS:
                    pair=(states[left],states[right])
                    if "NOT_MAPPED_FOR_DOMAIN" in pair or "ROW_ABSENT" in pair:
                        continue
                    yoy_pair_opportunities+=1
                    if "ARCHIVE_GAP" in pair:
                        yoy_pairs_archive_blocked+=1
                    elif pair==("PRESENT","PRESENT"):
                        yoy_pairs_present+=1

            mapped_rows=counts["PRESENT"]+counts["MISSING_IN_MAPPED_SCOPE"]
            feature_rows.append({
                "feature":feature,
                "reporting_basis":basis,
                "row_count":len(basis_items),
                "present_row_count":counts["PRESENT"],
                "missing_mapped_row_count":counts["MISSING_IN_MAPPED_SCOPE"],
                "not_mapped_row_count":counts["NOT_MAPPED_FOR_DOMAIN"],
                "archive_gap_row_count":counts["ARCHIVE_GAP"],
                "mapped_scope_row_count":mapped_rows,
                "mapped_scope_present_rate":(
                    counts["PRESENT"]/mapped_rows if mapped_rows else None
                ),
                "mapped_history_count":history_count,
                "histories_with_at_least_2_present":histories_with_2,
                "histories_with_at_least_4_present":histories_with_4,
                "histories_with_all_6_present":histories_with_6,
                "adjacent_pair_opportunity_count":adjacent_pair_opportunities,
                "adjacent_pair_present_count":adjacent_pairs_present,
                "adjacent_pair_archive_blocked_count":adjacent_pairs_archive_blocked,
                "adjacent_pair_present_rate":(
                    adjacent_pairs_present/(
                        adjacent_pair_opportunities-adjacent_pairs_archive_blocked
                    )
                    if adjacent_pair_opportunities>adjacent_pairs_archive_blocked else None
                ),
                "yoy_pair_opportunity_count":yoy_pair_opportunities,
                "yoy_pair_present_count":yoy_pairs_present,
                "yoy_pair_archive_blocked_count":yoy_pairs_archive_blocked,
                "yoy_pair_present_rate":(
                    yoy_pairs_present/(yoy_pair_opportunities-yoy_pairs_archive_blocked)
                    if yoy_pair_opportunities>yoy_pairs_archive_blocked else None
                ),
            })

        for quarter in TARGET_QUARTERS:
            qitems=[x for x in items if x.get("quarter_end")==quarter]
            counts=Counter(_feature_state(x,feature) for x in qitems)
            mapped=counts["PRESENT"]+counts["MISSING_IN_MAPPED_SCOPE"]
            quarter_rows.append({
                "feature":feature,
                "quarter_end":quarter,
                "row_count":len(qitems),
                "present_row_count":counts["PRESENT"],
                "missing_mapped_row_count":counts["MISSING_IN_MAPPED_SCOPE"],
                "not_mapped_row_count":counts["NOT_MAPPED_FOR_DOMAIN"],
                "archive_gap_row_count":counts["ARCHIVE_GAP"],
                "mapped_scope_present_rate":counts["PRESENT"]/mapped if mapped else None,
            })

    overall=[]
    for feature in FEATURES:
        counts=Counter(_feature_state(x,feature) for x in items)
        mapped=counts["PRESENT"]+counts["MISSING_IN_MAPPED_SCOPE"]
        overall.append({
            "feature":feature,
            "present_row_count":counts["PRESENT"],
            "missing_mapped_row_count":counts["MISSING_IN_MAPPED_SCOPE"],
            "not_mapped_row_count":counts["NOT_MAPPED_FOR_DOMAIN"],
            "archive_gap_row_count":counts["ARCHIVE_GAP"],
            "mapped_scope_present_rate":counts["PRESENT"]/mapped if mapped else None,
        })

    return {
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A4_CONTINUITY_FINDINGS_REVIEW_V1",
        "authority":"SHADOW_ONLY",
        "panel_row_count":len(items),
        "history_count":len(by_history),
        "target_quarters":list(TARGET_QUARTERS),
        "adjacent_quarter_pairs":[list(x) for x in ADJACENT_PAIRS],
        "yoy_quarter_pairs":[list(x) for x in YOY_PAIRS],
        "overall_feature_continuity":overall,
        "basis_feature_continuity":feature_rows,
        "quarter_feature_continuity":quarter_rows,
        "history_feature_continuity":history_feature_rows,
        "derived_growth_features_created":False,
        "production_model_changed":False,
        "model_training_started":False,
    }
