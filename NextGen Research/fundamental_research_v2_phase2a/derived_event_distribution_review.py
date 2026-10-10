"""Distribution and sign-transition review for Fundamental Research V2 Phase 2A.5."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Iterable


QUANTILES=(
    ("p01",Decimal("0.01")),
    ("p05",Decimal("0.05")),
    ("p25",Decimal("0.25")),
    ("p50",Decimal("0.50")),
    ("p75",Decimal("0.75")),
    ("p95",Decimal("0.95")),
    ("p99",Decimal("0.99")),
)


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"INVALID_DISTRIBUTION_DECIMAL:{value}") from exc


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(),"f")


def _quantile(values: list[Decimal], q: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered=sorted(values)
    if len(ordered)==1:
        return ordered[0]
    position=q*Decimal(len(ordered)-1)
    lower=int(position)
    upper=min(lower+1,len(ordered)-1)
    fraction=position-Decimal(lower)
    return ordered[lower]+(ordered[upper]-ordered[lower])*fraction


def summarize_group(events: Iterable[dict]) -> dict:
    rows=list(events)
    values=[_decimal(x.get("symmetric_change")) for x in rows]
    directions=Counter(str(x.get("direction")) for x in rows)
    transitions=Counter(str(x.get("sign_transition")) for x in rows)
    quantiles={name:_text(_quantile(values,q)) for name,q in QUANTILES}
    positive_two=sum(1 for x in values if x==Decimal(2))
    negative_two=sum(1 for x in values if x==Decimal(-2))
    unchanged=sum(1 for x in values if x==0)
    sign_crossings=sum(
        count for key,count in transitions.items()
        if key in {"NEGATIVE_TO_POSITIVE","POSITIVE_TO_NEGATIVE"}
    )
    zero_transitions=sum(
        count for key,count in transitions.items()
        if "_TO_ZERO" in key or key.startswith("ZERO_TO_")
    )
    return {
        "count":len(rows),
        "symmetric_change_min":_text(min(values) if values else None),
        **quantiles,
        "symmetric_change_max":_text(max(values) if values else None),
        "symmetric_change_mean":_text(
            sum(values,Decimal(0))/Decimal(len(values)) if values else None
        ),
        "positive_two_boundary_count":positive_two,
        "negative_two_boundary_count":negative_two,
        "zero_change_count":unchanged,
        "sign_crossing_count":sign_crossings,
        "zero_transition_count":zero_transitions,
        "direction_counts":dict(sorted(directions.items())),
        "sign_transition_counts":dict(sorted(transitions.items())),
    }


def review_distributions(events: Iterable[dict], eligibility: dict) -> dict:
    rows=list(events)
    if not rows:
        raise ValueError("DERIVED_EVENT_REVIEW_EMPTY")

    grouped=defaultdict(list)
    feature_grouped=defaultdict(list)
    basis_grouped=defaultdict(list)
    for event in rows:
        key=(event.get("feature"),event.get("comparison"),event.get("reporting_basis"))
        grouped[key].append(event)
        feature_grouped[event.get("feature")].append(event)
        basis_grouped[(event.get("feature"),event.get("reporting_basis"))].append(event)

    feature_comparison_basis=[]
    for (feature,comparison,basis),items in sorted(grouped.items()):
        feature_comparison_basis.append({
            "feature":feature,
            "comparison":comparison,
            "reporting_basis":basis,
            **summarize_group(items),
        })

    feature_summary=[]
    for feature,items in sorted(feature_grouped.items()):
        feature_summary.append({
            "feature":feature,
            **summarize_group(items),
        })

    feature_basis_summary=[]
    for (feature,basis),items in sorted(basis_grouped.items()):
        feature_basis_summary.append({
            "feature":feature,
            "reporting_basis":basis,
            **summarize_group(items),
        })

    rejection_counts=Counter()
    for row in eligibility.get("pit_order_rejections") or []:
        rejection_counts[(
            row.get("feature"),
            row.get("comparison"),
            row.get("reporting_basis"),
        )]+=1
    rejection_summary=[
        {
            "feature":feature,
            "comparison":comparison,
            "reporting_basis":basis,
            "rejection_count":count,
        }
        for (feature,comparison,basis),count in sorted(rejection_counts.items())
    ]

    return {
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_PHASE2A5_DERIVED_EVENT_DISTRIBUTION_REVIEW_V1",
        "authority":"SHADOW_ONLY",
        "derived_event_count":len(rows),
        "pre_pit_candidate_count":int(eligibility.get("pre_pit_candidate_count") or 0),
        "pit_order_rejection_count":int(eligibility.get("pit_order_rejection_count") or 0),
        "feature_summary":feature_summary,
        "feature_basis_summary":feature_basis_summary,
        "feature_comparison_basis_summary":feature_comparison_basis,
        "pit_order_rejection_summary":rejection_summary,
        "absolute_delta_cross_company_distribution_created":False,
        "semantic_good_bad_label_created":False,
        "market_labels_created":False,
        "production_model_changed":False,
        "model_training_started":False,
    }
