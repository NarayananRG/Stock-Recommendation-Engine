"""Conservative semantic interpretation audit for Fundamental Research V2 Phase 2A.6."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

POLICIES={
    "REVENUE":"DIRECT_DIRECTIONAL",
    "PAT":"PROFIT_SIGN_AWARE",
    "PBT":"PROFIT_SIGN_AWARE",
    "EPS":"PROFIT_SIGN_AWARE",
    "OPERATING_CASH_FLOW":"CASHFLOW_SIGN_AWARE",
    "FINANCE_COST":"INVERSE_DIRECTIONAL_WITH_SIGN_GUARD",
    "TAX":"CONTEXT_ONLY",
    "DEPRECIATION":"CONTEXT_ONLY",
    "CASH_AND_EQUIVALENTS":"CONTEXT_ONLY",
    "TOTAL_ASSETS":"CONTEXT_ONLY",
    "DEBT_EQUITY_RATIO":"EXCLUDED",
}

STRONG_SIGN_TRANSITIONS={"NEGATIVE_TO_POSITIVE","POSITIVE_TO_NEGATIVE"}


def semantic_class(event: dict) -> tuple[str,str]:
    feature=event.get("feature")
    policy=POLICIES.get(feature)
    if policy is None:
        raise ValueError(f"SEMANTIC_POLICY_MISSING:{feature}")

    direction=event.get("direction")
    transition=event.get("sign_transition")

    if policy=="EXCLUDED":
        return "EXCLUDED","FEATURE_EXCLUDED"

    if policy=="CONTEXT_ONLY":
        return "CONTEXT_ONLY","DIRECTION_NOT_INTRINSICALLY_GOOD_OR_BAD"

    if direction=="UNCHANGED":
        return "NEUTRAL","UNCHANGED_VALUE"

    if policy=="DIRECT_DIRECTIONAL":
        if transition!="POSITIVE_TO_POSITIVE":
            return "CONTEXT_REVIEW_REQUIRED","NON_POSITIVE_OR_SIGN_TRANSITION"
        return (
            ("IMPROVEMENT_CANDIDATE","DIRECT_INCREASE")
            if direction=="INCREASE"
            else ("DETERIORATION_CANDIDATE","DIRECT_DECREASE")
        )

    if policy in {"PROFIT_SIGN_AWARE","CASHFLOW_SIGN_AWARE"}:
        if transition=="NEGATIVE_TO_POSITIVE":
            return "IMPROVEMENT_CANDIDATE","STRONG_NEGATIVE_TO_POSITIVE"
        if transition=="POSITIVE_TO_NEGATIVE":
            return "DETERIORATION_CANDIDATE","STRONG_POSITIVE_TO_NEGATIVE"
        return (
            ("IMPROVEMENT_CANDIDATE","NUMERIC_INCREASE")
            if direction=="INCREASE"
            else ("DETERIORATION_CANDIDATE","NUMERIC_DECREASE")
        )

    if policy=="INVERSE_DIRECTIONAL_WITH_SIGN_GUARD":
        if transition!="POSITIVE_TO_POSITIVE":
            return "CONTEXT_REVIEW_REQUIRED","NON_POSITIVE_FINANCE_COST"
        return (
            ("DETERIORATION_CANDIDATE","FINANCE_COST_INCREASE")
            if direction=="INCREASE"
            else ("IMPROVEMENT_CANDIDATE","FINANCE_COST_DECREASE")
        )

    raise ValueError(f"UNHANDLED_SEMANTIC_POLICY:{policy}")


def semantic_audit(events: Iterable[dict]) -> dict:
    rows=list(events)
    if not rows:
        raise ValueError("SEMANTIC_AUDIT_EMPTY")

    class_counts=Counter()
    reason_counts=Counter()
    feature_counts=defaultdict(Counter)
    comparison_counts=defaultdict(Counter)
    strong_sign_counts=defaultdict(Counter)
    examples=[]

    for event in rows:
        semantic,reason=semantic_class(event)
        feature=event.get("feature")
        comparison=event.get("comparison")
        class_counts[semantic]+=1
        reason_counts[reason]+=1
        feature_counts[feature][semantic]+=1
        comparison_counts[comparison][semantic]+=1

        if event.get("sign_transition") in STRONG_SIGN_TRANSITIONS:
            strong_sign_counts[feature][event.get("sign_transition")]+=1

        if len(examples)<100 and semantic in {
            "CONTEXT_REVIEW_REQUIRED",
            "DETERIORATION_CANDIDATE",
            "IMPROVEMENT_CANDIDATE",
        }:
            examples.append({
                "symbol":event.get("symbol"),
                "reporting_basis":event.get("reporting_basis"),
                "feature":feature,
                "comparison":comparison,
                "current_quarter_end":event.get("current_quarter_end"),
                "sign_transition":event.get("sign_transition"),
                "direction":event.get("direction"),
                "semantic_class":semantic,
                "semantic_reason":reason,
                "effective_availability_ts":event.get("effective_availability_ts"),
            })

    return {
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A6_SEMANTIC_COVERAGE_AUDIT_V1",
        "authority":"SHADOW_ONLY",
        "derived_event_count":len(rows),
        "policy_count":len(POLICIES),
        "semantic_class_counts":dict(sorted(class_counts.items())),
        "semantic_reason_counts":dict(sorted(reason_counts.items())),
        "feature_semantic_counts":{
            feature:dict(sorted(counts.items()))
            for feature,counts in sorted(feature_counts.items())
        },
        "comparison_semantic_counts":{
            comparison:dict(sorted(counts.items()))
            for comparison,counts in sorted(comparison_counts.items())
        },
        "strong_sign_transition_counts":{
            feature:dict(sorted(counts.items()))
            for feature,counts in sorted(strong_sign_counts.items())
        },
        "sample_interpreted_events":examples,
        "trading_signal_created":False,
        "composite_score_created":False,
        "market_labels_created":False,
        "production_model_changed":False,
        "model_training_started":False,
    }
