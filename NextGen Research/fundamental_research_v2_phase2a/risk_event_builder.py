"""Filing-event risk profiles for Fundamental Research V2 Phase 2A.7."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from .semantic_interpretation import semantic_class

STRONG_FEATURES={"PAT","PBT","EPS","OPERATING_CASH_FLOW"}


def build_risk_profiles(events: Iterable[dict]) -> list[dict]:
    grouped=defaultdict(list)
    for event in events:
        key=(
            event.get("symbol"),
            event.get("reporting_basis"),
            event.get("current_event_id"),
            event.get("current_quarter_end"),
            event.get("effective_availability_ts"),
        )
        grouped[key].append(event)

    profiles=[]
    for key,items in sorted(grouped.items(),key=lambda x:tuple(str(v) for v in x[0])):
        symbol,basis,event_id,quarter,availability=key
        deterioration=[]
        improvement=[]
        context=[]
        neutral=[]
        strong_det=[]
        strong_imp=[]

        for event in items:
            semantic,reason=semantic_class(event)
            evidence={
                "feature":event.get("feature"),
                "comparison":event.get("comparison"),
                "direction":event.get("direction"),
                "sign_transition":event.get("sign_transition"),
                "symmetric_change":event.get("symmetric_change"),
                "semantic_class":semantic,
                "semantic_reason":reason,
            }
            if semantic=="DETERIORATION_CANDIDATE":
                deterioration.append(evidence)
            elif semantic=="IMPROVEMENT_CANDIDATE":
                improvement.append(evidence)
            elif semantic in {"CONTEXT_ONLY","CONTEXT_REVIEW_REQUIRED"}:
                context.append(evidence)
            else:
                neutral.append(evidence)

            if event.get("feature") in STRONG_FEATURES:
                if event.get("sign_transition")=="POSITIVE_TO_NEGATIVE":
                    strong_det.append(evidence)
                elif event.get("sign_transition")=="NEGATIVE_TO_POSITIVE":
                    strong_imp.append(evidence)

        if deterioration and not improvement:
            profile="PURE_DETERIORATION"
        elif improvement and not deterioration:
            profile="PURE_IMPROVEMENT"
        elif deterioration and improvement:
            profile="MIXED_DIRECTIONAL"
        else:
            profile="NO_DIRECTIONAL_EVIDENCE"

        profiles.append({
            "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A7_RISK_EVENT_PROFILE_V1",
            "authority":"SHADOW_ONLY",
            "symbol":symbol,
            "reporting_basis":basis,
            "current_event_id":event_id,
            "current_quarter_end":quarter,
            "effective_availability_ts":availability,
            "event_profile":profile,
            "deterioration_evidence_count":len(deterioration),
            "improvement_evidence_count":len(improvement),
            "context_evidence_count":len(context),
            "neutral_evidence_count":len(neutral),
            "deterioration_evidence":deterioration,
            "improvement_evidence":improvement,
            "strong_deterioration_transition":bool(strong_det),
            "strong_improvement_transition":bool(strong_imp),
            "strong_deterioration_evidence":strong_det,
            "strong_improvement_evidence":strong_imp,
            "trading_signal_created":False,
            "composite_score_created":False,
        })
    return profiles


def summarize_profiles(profiles: Iterable[dict]) -> dict:
    rows=list(profiles)
    classes=Counter(x["event_profile"] for x in rows)
    quarters=Counter((x["current_quarter_end"],x["event_profile"]) for x in rows)
    basis=Counter((x["reporting_basis"],x["event_profile"]) for x in rows)
    return {
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A7_RISK_EVENT_BUILDER_SUMMARY_V1",
        "authority":"SHADOW_ONLY",
        "event_profile_count":len(rows),
        "profile_class_counts":dict(sorted(classes.items())),
        "quarter_profile_counts":[
            {"quarter_end":q,"event_profile":p,"count":n}
            for (q,p),n in sorted(quarters.items())
        ],
        "basis_profile_counts":[
            {"reporting_basis":b,"event_profile":p,"count":n}
            for (b,p),n in sorted(basis.items())
        ],
        "strong_deterioration_event_count":sum(bool(x["strong_deterioration_transition"]) for x in rows),
        "strong_improvement_event_count":sum(bool(x["strong_improvement_transition"]) for x in rows),
        "primary_deterioration_count":classes["PURE_DETERIORATION"],
        "primary_improvement_count":classes["PURE_IMPROVEMENT"],
        "mixed_event_count":classes["MIXED_DIRECTIONAL"],
        "trading_signal_created":False,
        "composite_score_created":False,
        "market_labels_created":False,
        "production_model_changed":False,
        "model_training_started":False,
    }
