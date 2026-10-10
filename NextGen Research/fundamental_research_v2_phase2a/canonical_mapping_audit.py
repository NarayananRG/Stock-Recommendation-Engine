"""Evidence-first canonical mapping audit for Fundamental Research V2 Phase 2A.2."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Iterable

FEATURE_CANDIDATES = {
    "REVENUE": {"RevenueFromOperations", "Income"},
    "PAT": {"ProfitLossForPeriod", "ProfitLossForPeriodFromContinuingOperations"},
    "PBT": {"ProfitBeforeTax", "ProfitBeforeExceptionalItemsAndTax"},
    "TAX": {"TaxExpense", "CurrentTax", "DeferredTax"},
    "FINANCE_COST": {"FinanceCosts"},
    "DEPRECIATION": {"DepreciationDepletionAndAmortisationExpense"},
    "OPERATING_CASH_FLOW": {"CashFlowsFromUsedInOperatingActivities", "CashFlowsFromUsedInOperations"},
    "CASH_AND_EQUIVALENTS": {"CashAndCashEquivalentsCashFlowStatement"},
    "TOTAL_ASSETS": {"Assets"},
    "DEBT_EQUITY_RATIO": {"DebtEquityRatio"},
    "EPS": {
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsLossPerShareFromContinuingOperations",
    },
}


def classify_domain(source_url: str | None) -> str:
    text = str(source_url or "").upper()
    if "NBFC" in text:
        return "NBFC"
    if "BANK" in text:
        return "BANK"
    if "INDAS" in text:
        return "IND_AS_CORPORATE"
    return "UNKNOWN"


def duration_days(context: dict) -> int | None:
    start = context.get("start_date")
    end = context.get("end_date")
    if not start or not end:
        return None
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def classify_context(context: dict, *, quarter_end: str) -> dict:
    dims = context.get("dimensions") or []
    instant = context.get("instant")
    start = context.get("start_date")
    end = context.get("end_date")
    days = duration_days(context)

    if instant:
        period_kind = "INSTANT"
        aligned = instant == quarter_end
        duration_bucket = None
    elif start and end and days is not None:
        period_kind = "DURATION"
        aligned = end == quarter_end
        if 75 <= days <= 110:
            duration_bucket = "QUARTER_LIKE"
        elif 150 <= days <= 210:
            duration_bucket = "HALF_YEAR_LIKE"
        elif 240 <= days <= 300:
            duration_bucket = "NINE_MONTH_LIKE"
        elif 330 <= days <= 400:
            duration_bucket = "ANNUAL_LIKE"
        else:
            duration_bucket = "OTHER_DURATION"
    else:
        period_kind = "UNKNOWN"
        aligned = False
        duration_bucket = None

    return {
        "period_kind": period_kind,
        "duration_days": days,
        "duration_bucket": duration_bucket,
        "end_aligned_to_quarter": aligned,
        "dimension_count": len(dims),
        "undimensioned": len(dims) == 0,
    }


def enrich_candidate_facts(document: dict) -> list[dict]:
    contexts = {x["context_id"]: x for x in document.get("contexts", [])}
    units = {x["unit_id"]: x for x in document.get("units", [])}
    concept_to_features: dict[str, list[str]] = defaultdict(list)
    for feature, concepts in FEATURE_CANDIDATES.items():
        for concept in concepts:
            concept_to_features[concept].append(feature)

    rows = []
    for fact in document.get("numeric_facts", []):
        concept = fact.get("concept_local_name")
        features = concept_to_features.get(concept, [])
        if not features:
            continue
        context = contexts.get(fact.get("context_ref"))
        if context is None:
            context_class = {
                "period_kind": "UNKNOWN",
                "duration_days": None,
                "duration_bucket": None,
                "end_aligned_to_quarter": False,
                "dimension_count": None,
                "undimensioned": False,
            }
        else:
            context_class = classify_context(context, quarter_end=document["quarter_end"])

        unit = units.get(fact.get("unit_ref")) if fact.get("unit_ref") else None
        for feature in features:
            rows.append({
                "feature": feature,
                "symbol": document.get("symbol"),
                "quarter_end": document.get("quarter_end"),
                "reporting_basis": document.get("reporting_basis"),
                "submission_type": document.get("submission_type"),
                "domain": classify_domain(document.get("source_url")),
                "source_event_id": document.get("source_event_id"),
                "availability_ts": document.get("availability_ts"),
                "concept_namespace": fact.get("concept_namespace"),
                "concept_local_name": concept,
                "context_ref": fact.get("context_ref"),
                "unit_ref": fact.get("unit_ref"),
                "unit_measures": (unit or {}).get("measures"),
                "decimals": fact.get("decimals"),
                "scale": fact.get("scale"),
                "raw_value": fact.get("raw_value"),
                **context_class,
            })
    return rows


def deterministic_candidate_status(rows: Iterable[dict]) -> dict:
    items = list(rows)
    if not items:
        return {"status": "MISSING", "eligible_count": 0, "eligible": []}

    # This stage only assesses structural eligibility. It does not declare a
    # final canonical fact when multiple values/concepts survive.
    aligned_undimensioned = [
        x for x in items
        if x.get("end_aligned_to_quarter") and x.get("undimensioned")
    ]
    if not aligned_undimensioned:
        return {
            "status": "NO_ALIGNED_UNDIMENSIONED_CANDIDATE",
            "eligible_count": 0,
            "eligible": [],
        }

    signatures = {
        (
            x.get("concept_local_name"),
            x.get("context_ref"),
            tuple(x.get("unit_measures") or []),
            x.get("raw_value"),
        )
        for x in aligned_undimensioned
    }
    status = "SINGLE_STRUCTURAL_CANDIDATE" if len(signatures) == 1 else "AMBIGUOUS_MULTIPLE_CANDIDATES"
    return {
        "status": status,
        "eligible_count": len(aligned_undimensioned),
        "eligible": aligned_undimensioned,
    }


def audit_documents(documents: Iterable[dict]) -> dict:
    docs = list(documents)
    all_rows = []
    per_document = []
    context_profile = Counter()
    domain_feature_docs: dict[tuple[str, str], set[str]] = defaultdict(set)

    for document in docs:
        doc_key = "|".join([
            str(document.get("symbol")),
            str(document.get("quarter_end")),
            str(document.get("reporting_basis")),
        ])
        rows = enrich_candidate_facts(document)
        all_rows.extend(rows)

        features = {}
        for feature in FEATURE_CANDIDATES:
            feature_rows = [x for x in rows if x["feature"] == feature]
            result = deterministic_candidate_status(feature_rows)
            features[feature] = {
                "status": result["status"],
                "candidate_count": len(feature_rows),
                "eligible_count": result["eligible_count"],
                "eligible": result["eligible"],
            }
            if feature_rows:
                domain_feature_docs[(classify_domain(document.get("source_url")), feature)].add(doc_key)

        for row in rows:
            context_profile[(
                row["feature"],
                row["domain"],
                row["period_kind"],
                row["duration_bucket"],
                row["end_aligned_to_quarter"],
                row["undimensioned"],
            )] += 1

        per_document.append({
            "document_key": doc_key,
            "symbol": document.get("symbol"),
            "quarter_end": document.get("quarter_end"),
            "reporting_basis": document.get("reporting_basis"),
            "domain": classify_domain(document.get("source_url")),
            "features": features,
        })

    profile_rows = []
    for key, count in sorted(context_profile.items()):
        feature, domain, period_kind, duration_bucket, aligned, undimensioned = key
        profile_rows.append({
            "feature": feature,
            "domain": domain,
            "period_kind": period_kind,
            "duration_bucket": duration_bucket,
            "end_aligned_to_quarter": aligned,
            "undimensioned": undimensioned,
            "fact_count": count,
        })

    feature_domain_coverage = []
    domains = sorted({classify_domain(x.get("source_url")) for x in docs})
    for domain in domains:
        domain_docs = [
            x for x in docs if classify_domain(x.get("source_url")) == domain
        ]
        domain_keys = {
            "|".join([str(x.get("symbol")), str(x.get("quarter_end")), str(x.get("reporting_basis"))])
            for x in domain_docs
        }
        for feature in FEATURE_CANDIDATES:
            covered = domain_feature_docs.get((domain, feature), set())
            feature_domain_coverage.append({
                "domain": domain,
                "feature": feature,
                "document_count": len(domain_keys),
                "documents_with_candidate": len(covered),
                "document_coverage": (len(covered) / len(domain_keys)) if domain_keys else 0.0,
            })

    status_counts = Counter()
    for doc in per_document:
        for feature_info in doc["features"].values():
            status_counts[feature_info["status"]] += 1

    return {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A2_CANONICAL_MAPPING_AUDIT_V1",
        "document_count": len(docs),
        "candidate_fact_count": len(all_rows),
        "status_counts": dict(status_counts),
        "per_document": per_document,
        "context_profile": profile_rows,
        "feature_domain_coverage": feature_domain_coverage,
        "authority": "SHADOW_ONLY",
        "production_model_changed": False,
        "model_training_started": False,
    }
