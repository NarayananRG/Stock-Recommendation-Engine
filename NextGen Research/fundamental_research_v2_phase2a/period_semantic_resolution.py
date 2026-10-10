"""Period-aware semantic resolution for Fundamental Research V2 Phase 2A.2.

This stage proposes deterministic canonical selections from the observed official
XBRL pilot. It remains SHADOW_ONLY and does not change production authority.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Iterable

from .ambiguity_resolution import normalized_numeric_value
from .canonical_mapping_audit import classify_domain, enrich_candidate_facts


# Concept priority is semantic, not value-driven. Narrow/component concepts are
# not silently substituted for totals when an explicit total concept exists.
DOMAIN_RULES = {
    "IND_AS_CORPORATE": {
        "REVENUE": ["RevenueFromOperations"],
        "PAT": ["ProfitLossForPeriod", "ProfitLossForPeriodFromContinuingOperations"],
        "PBT": ["ProfitBeforeTax", "ProfitBeforeExceptionalItemsAndTax"],
        "TAX": ["TaxExpense"],
        "FINANCE_COST": ["FinanceCosts"],
        "DEPRECIATION": ["DepreciationDepletionAndAmortisationExpense"],
        "OPERATING_CASH_FLOW": ["CashFlowsFromUsedInOperatingActivities"],
        "CASH_AND_EQUIVALENTS": ["CashAndCashEquivalentsCashFlowStatement"],
        "TOTAL_ASSETS": ["Assets"],
        "DEBT_EQUITY_RATIO": ["DebtEquityRatio"],
        "EPS": [
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
            "BasicEarningsLossPerShareFromContinuingOperations",
        ],
    },
    "BANK": {
        # Financial institutions use total Income as the domain topline.
        "REVENUE": ["Income"],
        "PAT": ["ProfitLossForPeriod", "ProfitLossForPeriodFromContinuingOperations"],
        "PBT": ["ProfitBeforeTax", "ProfitBeforeExceptionalItemsAndTax"],
        "TAX": ["TaxExpense"],
        "FINANCE_COST": ["FinanceCosts"],
        "DEPRECIATION": ["DepreciationDepletionAndAmortisationExpense"],
        "OPERATING_CASH_FLOW": ["CashFlowsFromUsedInOperatingActivities"],
        "CASH_AND_EQUIVALENTS": ["CashAndCashEquivalentsCashFlowStatement"],
        "TOTAL_ASSETS": ["Assets"],
        "DEBT_EQUITY_RATIO": ["DebtEquityRatio"],
        "EPS": [
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
            "BasicEarningsLossPerShareFromContinuingOperations",
        ],
    },
    "NBFC": {
        # As with banks, use total Income as the domain topline rather than
        # pretending RevenueFromOperations is semantically identical.
        "REVENUE": ["Income"],
        "PAT": ["ProfitLossForPeriod", "ProfitLossForPeriodFromContinuingOperations"],
        "PBT": ["ProfitBeforeTax", "ProfitBeforeExceptionalItemsAndTax"],
        "TAX": ["TaxExpense"],
        "FINANCE_COST": ["FinanceCosts"],
        "DEPRECIATION": ["DepreciationDepletionAndAmortisationExpense"],
        "OPERATING_CASH_FLOW": ["CashFlowsFromUsedInOperatingActivities"],
        "CASH_AND_EQUIVALENTS": ["CashAndCashEquivalentsCashFlowStatement"],
        "TOTAL_ASSETS": ["Assets"],
        "DEBT_EQUITY_RATIO": ["DebtEquityRatio"],
        "EPS": [
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
            "BasicEarningsLossPerShareFromContinuingOperations",
        ],
    },
}

INSTANT_FEATURES = {"CASH_AND_EQUIVALENTS", "TOTAL_ASSETS", "DEBT_EQUITY_RATIO"}
QUARTER_FEATURES = {
    "REVENUE", "PAT", "PBT", "TAX", "FINANCE_COST", "DEPRECIATION", "EPS"
}
CUMULATIVE_FEATURES = {"OPERATING_CASH_FLOW"}


def expected_cumulative_bucket(quarter_end: str) -> str:
    month = date.fromisoformat(quarter_end).month
    if month == 3:
        return "ANNUAL_LIKE"
    if month == 6:
        return "QUARTER_LIKE"
    if month == 9:
        return "HALF_YEAR_LIKE"
    if month == 12:
        return "NINE_MONTH_LIKE"
    raise ValueError(f"UNSUPPORTED_QUARTER_END_MONTH:{month}")


def expected_period(row: dict, *, feature: str, quarter_end: str) -> bool:
    if not row.get("end_aligned_to_quarter") or not row.get("undimensioned"):
        return False

    if feature in INSTANT_FEATURES:
        return row.get("period_kind") == "INSTANT"

    if feature in QUARTER_FEATURES:
        return (
            row.get("period_kind") == "DURATION"
            and row.get("duration_bucket") == "QUARTER_LIKE"
        )

    if feature in CUMULATIVE_FEATURES:
        return (
            row.get("period_kind") == "DURATION"
            and row.get("duration_bucket") == expected_cumulative_bucket(quarter_end)
        )

    return False


def _compact(row: dict) -> dict:
    return {
        "concept_local_name": row.get("concept_local_name"),
        "context_ref": row.get("context_ref"),
        "period_kind": row.get("period_kind"),
        "duration_days": row.get("duration_days"),
        "duration_bucket": row.get("duration_bucket"),
        "unit_measures": row.get("unit_measures"),
        "raw_value": row.get("raw_value"),
        "scale": row.get("scale"),
        "normalized_value": normalized_numeric_value(row),
    }


def resolve_feature(document: dict, *, feature: str) -> dict:
    domain = classify_domain(
        document.get("domain_source_url") or document.get("source_url")
    )
    rules = DOMAIN_RULES.get(domain, {})
    priority = rules.get(feature)
    if not priority:
        return {
            "status": "NO_DOMAIN_RULE",
            "domain": domain,
            "feature": feature,
            "selected": None,
            "evidence": [],
        }

    rows = [
        x for x in enrich_candidate_facts(document)
        if x["feature"] == feature
        and expected_period(x, feature=feature, quarter_end=document["quarter_end"])
    ]
    if not rows:
        return {
            "status": "MISSING_EXPECTED_PERIOD",
            "domain": domain,
            "feature": feature,
            "selected": None,
            "evidence": [],
        }

    for concept in priority:
        concept_rows = [x for x in rows if x.get("concept_local_name") == concept]
        if not concept_rows:
            continue

        signatures = {
            (
                normalized_numeric_value(x),
                tuple(x.get("unit_measures") or []),
            )
            for x in concept_rows
        }
        if len(signatures) == 1 and next(iter(signatures))[0] is not None:
            chosen = sorted(concept_rows, key=lambda x: str(x.get("context_ref")))[0]
            return {
                "status": (
                    "SELECTED_EQUIVALENT_DUPLICATES"
                    if len(concept_rows) > 1 else "SELECTED"
                ),
                "domain": domain,
                "feature": feature,
                "selected_concept": concept,
                "selected": _compact(chosen),
                "evidence": [_compact(x) for x in concept_rows],
            }

        return {
            "status": "AMBIGUOUS_WITHIN_PREFERRED_CONCEPT",
            "domain": domain,
            "feature": feature,
            "selected_concept": concept,
            "selected": None,
            "evidence": [_compact(x) for x in concept_rows],
        }

    return {
        "status": "NO_PRIORITY_CONCEPT_PRESENT",
        "domain": domain,
        "feature": feature,
        "selected": None,
        "evidence": [_compact(x) for x in rows],
    }


def resolve_documents(documents: Iterable[dict]) -> dict:
    docs = list(documents)
    per_document = []
    status_counts = Counter()
    domain_feature_status = defaultdict(Counter)
    selected_concepts = defaultdict(Counter)

    all_features = sorted(next(iter(DOMAIN_RULES.values())).keys())

    for document in docs:
        doc_key = "|".join([
            str(document.get("symbol")),
            str(document.get("quarter_end")),
            str(document.get("reporting_basis")),
        ])
        feature_results = {}
        for feature in all_features:
            result = resolve_feature(document, feature=feature)
            feature_results[feature] = result
            status_counts[result["status"]] += 1
            key = (result["domain"], feature)
            domain_feature_status[key][result["status"]] += 1
            if result.get("selected_concept"):
                selected_concepts[key][result["selected_concept"]] += 1

        per_document.append({
            "document_key": doc_key,
            "symbol": document.get("symbol"),
            "quarter_end": document.get("quarter_end"),
            "reporting_basis": document.get("reporting_basis"),
            "domain": classify_domain(document.get("source_url")),
            "features": feature_results,
        })

    domain_feature_summary = []
    freeze_candidates = []
    blocked = []
    for domain, feature in sorted(domain_feature_status):
        counts = domain_feature_status[(domain, feature)]
        concepts = selected_concepts[(domain, feature)]
        selected_count = counts.get("SELECTED", 0) + counts.get("SELECTED_EQUIVALENT_DUPLICATES", 0)
        hard_ambiguity = counts.get("AMBIGUOUS_WITHIN_PREFERRED_CONCEPT", 0)
        missing = (
            counts.get("MISSING_EXPECTED_PERIOD", 0)
            + counts.get("NO_PRIORITY_CONCEPT_PRESENT", 0)
            + counts.get("NO_DOMAIN_RULE", 0)
        )
        row = {
            "domain": domain,
            "feature": feature,
            "status_counts": dict(counts),
            "selected_concepts": dict(concepts),
            "selected_document_count": selected_count,
            "missing_or_unresolved_count": missing,
            "hard_ambiguity_count": hard_ambiguity,
        }
        domain_feature_summary.append(row)

        # Mapping freeze means "when this fact is present, this concept/period
        # rule is deterministic". It does NOT claim complete quarter coverage.
        if selected_count > 0 and hard_ambiguity == 0 and len(concepts) == 1:
            freeze_candidates.append({
                **row,
                "status": "CANDIDATE_FOR_PERIOD_AWARE_MAPPING_FREEZE",
            })
        elif selected_count > 0 or hard_ambiguity > 0:
            blocked.append({
                **row,
                "status": "BLOCKED_PENDING_MORE_EVIDENCE_OR_RULE",
            })

    return {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A2_PERIOD_SEMANTIC_RESOLUTION_V1",
        "document_count": len(docs),
        "status_counts": dict(status_counts),
        "domain_feature_summary": domain_feature_summary,
        "freeze_candidates": freeze_candidates,
        "blocked_domain_features": blocked,
        "per_document": per_document,
        "authority": "SHADOW_ONLY",
        "mapping_frozen": False,
        "production_model_changed": False,
        "model_training_started": False,
    }
