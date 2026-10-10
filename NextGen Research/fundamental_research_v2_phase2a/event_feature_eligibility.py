"""Event-feature eligibility audit for Fundamental Research V2 Phase 2A.5."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

TARGET_QUARTERS=(
    "2025-03-31",
    "2025-06-30",
    "2025-09-30",
    "2025-12-31",
    "2026-03-31",
    "2026-06-30",
)

FEATURE_POLICIES={
    "REVENUE":{"comparisons":("QOQ","YOY"),"class":"QUARTER_FLOW_HIGH_CONTINUITY"},
    "PAT":{"comparisons":("QOQ","YOY"),"class":"QUARTER_FLOW_HIGH_CONTINUITY_DOMAIN_SCOPED"},
    "PBT":{"comparisons":("QOQ","YOY"),"class":"QUARTER_FLOW_HIGH_CONTINUITY_DOMAIN_SCOPED"},
    "TAX":{"comparisons":("QOQ","YOY"),"class":"QUARTER_FLOW_HIGH_CONTINUITY"},
    "FINANCE_COST":{"comparisons":("QOQ","YOY"),"class":"QUARTER_FLOW_HIGH_CONTINUITY_DOMAIN_SCOPED"},
    "DEPRECIATION":{"comparisons":("QOQ","YOY"),"class":"QUARTER_FLOW_HIGH_CONTINUITY_DOMAIN_SCOPED"},
    "EPS":{"comparisons":("QOQ","YOY"),"class":"QUARTER_FLOW_HIGH_CONTINUITY_DOMAIN_SCOPED"},
    "OPERATING_CASH_FLOW":{"comparisons":("YOY_SAME_QUARTER_ONLY",),"class":"SPARSE_CUMULATIVE_FLOW"},
    "CASH_AND_EQUIVALENTS":{"comparisons":("YOY_SAME_QUARTER_ONLY",),"class":"SPARSE_STOCK"},
    "TOTAL_ASSETS":{"comparisons":("YOY_SAME_QUARTER_ONLY",),"class":"SPARSE_STOCK"},
    "DEBT_EQUITY_RATIO":{"comparisons":(),"class":"UNAVAILABLE_IN_FROZEN_MAPPING"},
}

PRESENT={"SELECTED","SELECTED_EQUIVALENT_DUPLICATES"}
QOQ_PAIRS=tuple(zip(TARGET_QUARTERS[:-1],TARGET_QUARTERS[1:]))
YOY_PAIRS=tuple((TARGET_QUARTERS[i],TARGET_QUARTERS[i+4]) for i in range(len(TARGET_QUARTERS)-4))


def usable(row: dict | None, feature: str) -> bool:
    if not row or row.get("archive_gap"):
        return False
    return (
        row.get(f"{feature}__status") in PRESENT
        and row.get(f"{feature}__value") not in (None,"")
    )


def eligibility_audit(rows: Iterable[dict]) -> dict:
    items=list(rows)
    by_history=defaultdict(list)
    for row in items:
        by_history[(row.get("symbol"),row.get("reporting_basis"))].append(row)

    by_feature=[]
    by_feature_basis=[]
    eligible_events=[]

    for feature,policy in FEATURE_POLICIES.items():
        feature_counts=Counter()
        basis_counts=defaultdict(Counter)

        if not policy["comparisons"]:
            by_feature.append({
                "feature":feature,
                "policy_class":policy["class"],
                "allowed_comparisons":[],
                "qoq_eligible_count":0,
                "yoy_eligible_count":0,
                "excluded":True,
            })
            continue

        for (symbol,basis),history in sorted(by_history.items()):
            qmap={row.get("quarter_end"):row for row in history}

            if "QOQ" in policy["comparisons"]:
                for previous_q,current_q in QOQ_PAIRS:
                    previous=qmap.get(previous_q)
                    current=qmap.get(current_q)
                    if usable(previous,feature) and usable(current,feature):
                        feature_counts["QOQ"]+=1
                        basis_counts[basis]["QOQ"]+=1
                        eligible_events.append({
                            "symbol":symbol,
                            "reporting_basis":basis,
                            "feature":feature,
                            "comparison":"QOQ",
                            "previous_quarter_end":previous_q,
                            "current_quarter_end":current_q,
                            "previous_event_id":previous.get("event_id"),
                            "current_event_id":current.get("event_id"),
                            "effective_availability_ts":current.get("availability_ts"),
                        })

            if (
                "YOY" in policy["comparisons"]
                or "YOY_SAME_QUARTER_ONLY" in policy["comparisons"]
            ):
                comparison=(
                    "YOY_SAME_QUARTER_ONLY"
                    if "YOY_SAME_QUARTER_ONLY" in policy["comparisons"]
                    else "YOY"
                )
                for previous_q,current_q in YOY_PAIRS:
                    previous=qmap.get(previous_q)
                    current=qmap.get(current_q)
                    if usable(previous,feature) and usable(current,feature):
                        feature_counts["YOY"]+=1
                        basis_counts[basis]["YOY"]+=1
                        eligible_events.append({
                            "symbol":symbol,
                            "reporting_basis":basis,
                            "feature":feature,
                            "comparison":comparison,
                            "previous_quarter_end":previous_q,
                            "current_quarter_end":current_q,
                            "previous_event_id":previous.get("event_id"),
                            "current_event_id":current.get("event_id"),
                            "effective_availability_ts":current.get("availability_ts"),
                        })

        by_feature.append({
            "feature":feature,
            "policy_class":policy["class"],
            "allowed_comparisons":list(policy["comparisons"]),
            "qoq_eligible_count":feature_counts["QOQ"],
            "yoy_eligible_count":feature_counts["YOY"],
            "excluded":False,
        })
        for basis,counts in sorted(basis_counts.items()):
            by_feature_basis.append({
                "feature":feature,
                "reporting_basis":basis,
                "qoq_eligible_count":counts["QOQ"],
                "yoy_eligible_count":counts["YOY"],
            })

    eligible_events.sort(key=lambda x:(
        x["feature"],x["comparison"],x["symbol"],x["reporting_basis"],x["current_quarter_end"]
    ))
    return {
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A5_EVENT_FEATURE_ELIGIBILITY_AUDIT_V1",
        "authority":"SHADOW_ONLY",
        "panel_row_count":len(items),
        "history_count":len(by_history),
        "feature_policy_count":len(FEATURE_POLICIES),
        "feature_eligibility":by_feature,
        "feature_basis_eligibility":by_feature_basis,
        "eligible_event_count":len(eligible_events),
        "eligible_events":eligible_events,
        "derived_feature_values_created":False,
        "production_model_changed":False,
        "model_training_started":False,
    }
