"""Independent OOS validation and final decision for Fundamental Research V2 Phase 2A.9."""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean,median
from typing import Iterable

HORIZONS=(21,63,126)
MIN_PER_COHORT=30


def _stats(values):
    clean=[float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not clean:
        return {"count":0,"mean":None,"median":None,"positive_rate":None}
    return {
        "count":len(clean),
        "mean":mean(clean),
        "median":median(clean),
        "positive_rate":sum(x>0 for x in clean)/len(clean),
    }


def _split_name(quarter: str) -> str:
    return "DEVELOPMENT" if str(quarter)<="2025-12-31" else "OUT_OF_SAMPLE"


def validation_table(outcomes: Iterable[dict]):
    groups=defaultdict(list)
    for row in outcomes:
        if not row.get("mature"):
            continue
        profile=row.get("event_profile")
        if profile not in {"PURE_DETERIORATION","PURE_IMPROVEMENT"}:
            continue
        split=_split_name(row.get("current_quarter_end"))
        horizon=int(row.get("horizon_sessions"))
        groups[(split,horizon,profile)].append(row.get("forward_return"))

    table=[]
    for split in ("DEVELOPMENT","OUT_OF_SAMPLE"):
        for horizon in HORIZONS:
            det=_stats(groups[(split,horizon,"PURE_DETERIORATION")])
            imp=_stats(groups[(split,horizon,"PURE_IMPROVEMENT")])
            eligible=det["count"]>=MIN_PER_COHORT and imp["count"]>=MIN_PER_COHORT
            mean_effect=None
            median_effect=None
            support=False
            if det["mean"] is not None and imp["mean"] is not None:
                mean_effect=det["mean"]-imp["mean"]
                median_effect=det["median"]-imp["median"]
                support=mean_effect<0 and median_effect<0
            table.append({
                "split":split,
                "horizon_sessions":horizon,
                "pure_deterioration":det,
                "pure_improvement":imp,
                "eligible_for_validation":eligible,
                "mean_effect_deterioration_minus_improvement":mean_effect,
                "median_effect_deterioration_minus_improvement":median_effect,
                "directional_support":support,
            })
    return table


def final_decision(outcomes: Iterable[dict], matched_event_rate: float):
    rows=list(outcomes)
    table=validation_table(rows)
    oos=[x for x in table if x["split"]=="OUT_OF_SAMPLE" and x["eligible_for_validation"]]
    dev=[x for x in table if x["split"]=="DEVELOPMENT" and x["eligible_for_validation"]]
    oos_supported=[x for x in oos if x["directional_support"]]
    dev_supported=[x for x in dev if x["directional_support"]]

    if matched_event_rate<0.75:
        decision="DO_NOT_PROMOTE_INSUFFICIENT_OFFICIAL_PRICE_COVERAGE"
        reason="Matched event coverage is below the pre-committed 75% official-price threshold."
    elif not oos:
        decision="DO_NOT_PROMOTE_INSUFFICIENT_MATURE_OOS"
        reason="No OOS horizon has at least 30 mature pure-deterioration and 30 pure-improvement events."
    elif (
        len(oos)>=2
        and len(oos_supported)==len(oos)
        and (not dev or len(dev_supported)>=max(1,(len(dev)+1)//2))
    ):
        decision="VALIDATED_RISK_FILTER_CANDIDATE_SHADOW_ONLY"
        reason="At least two eligible OOS horizons show lower deterioration mean and median returns, with no material development contradiction."
    elif oos_supported:
        decision="PROMISING_RISK_FILTER_CANDIDATE_NOT_VALIDATED"
        reason="Some OOS evidence supports the deterioration hypothesis, but the full pre-committed validation rule is not met."
    else:
        decision="RISK_FILTER_NOT_SUPPORTED_BY_INDEPENDENT_VALIDATION"
        reason="Eligible OOS evidence does not consistently show lower future returns for pure deterioration events."

    return {
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A9_FINAL_DECISION_V1",
        "authority":"SHADOW_ONLY",
        "decision":decision,
        "decision_reason":reason,
        "matched_event_rate":matched_event_rate,
        "minimum_per_cohort":MIN_PER_COHORT,
        "validation_table":table,
        "eligible_oos_horizon_count":len(oos),
        "supported_oos_horizon_count":len(oos_supported),
        "eligible_development_horizon_count":len(dev),
        "supported_development_horizon_count":len(dev_supported),
        "statistical_significance_claimed":False,
        "model_training_started":False,
        "production_model_changed":False,
        "promotion_authorized":False,
        "fundamental_v2_research_cycle_closed":True,
    }
