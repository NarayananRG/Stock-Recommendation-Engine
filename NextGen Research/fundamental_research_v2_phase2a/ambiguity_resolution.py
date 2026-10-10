"""Ambiguity-resolution audit for Fundamental Research V2 Phase 2A.2.

This stage diagnoses structural ambiguity only. It does not freeze mappings and
does not promote any fundamental feature into production authority.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Iterable

from .canonical_mapping_audit import FEATURE_CANDIDATES, enrich_candidate_facts


DURATION_FEATURES = {
    "REVENUE", "PAT", "PBT", "TAX", "FINANCE_COST",
    "DEPRECIATION", "OPERATING_CASH_FLOW", "EPS",
}
INSTANT_FEATURES = {"CASH_AND_EQUIVALENTS", "TOTAL_ASSETS", "DEBT_EQUITY_RATIO"}


def normalized_numeric_value(row: dict) -> str | None:
    raw = row.get("raw_value")
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).replace(",", ""))
    except InvalidOperation:
        return None

    sign = str(row.get("sign") or "").strip()
    if sign == "-":
        value = -value

    scale_raw = row.get("scale")
    if scale_raw not in (None, ""):
        try:
            value = value * (Decimal(10) ** int(scale_raw))
        except (ValueError, InvalidOperation):
            return None
    return format(value.normalize(), "f")


def expected_period_eligible(row: dict, *, feature: str) -> bool:
    if not row.get("end_aligned_to_quarter") or not row.get("undimensioned"):
        return False

    if feature in INSTANT_FEATURES:
        return row.get("period_kind") == "INSTANT"

    if feature in DURATION_FEATURES:
        return row.get("period_kind") == "DURATION"

    return False


def diagnose_feature_rows(rows: Iterable[dict], *, feature: str) -> dict:
    items = list(rows)
    eligible = [x for x in items if expected_period_eligible(x, feature=feature)]

    if not items:
        return {
            "status": "MISSING",
            "reason_codes": ["NO_CANDIDATE_FACT"],
            "candidate_count": 0,
            "eligible_count": 0,
            "eligible": [],
        }

    if not eligible:
        return {
            "status": "NO_EXPECTED_PERIOD_CANDIDATE",
            "reason_codes": ["NO_ALIGNED_UNDIMENSIONED_EXPECTED_PERIOD"],
            "candidate_count": len(items),
            "eligible_count": 0,
            "eligible": [],
        }

    concepts = sorted({x.get("concept_local_name") for x in eligible})
    contexts = sorted({x.get("context_ref") for x in eligible})
    buckets = sorted({str(x.get("duration_bucket")) for x in eligible})
    units = sorted({tuple(x.get("unit_measures") or []) for x in eligible})
    values = sorted({
        (normalized_numeric_value(x), tuple(x.get("unit_measures") or []))
        for x in eligible
    })

    reason_codes = []
    if len(concepts) > 1:
        reason_codes.append("MULTIPLE_CONCEPTS")
    if len(contexts) > 1:
        reason_codes.append("MULTIPLE_CONTEXTS")
    if feature in DURATION_FEATURES and len(buckets) > 1:
        reason_codes.append("MULTIPLE_DURATION_BUCKETS")
    if len(units) > 1:
        reason_codes.append("MULTIPLE_UNITS")

    comparable_values = {x for x in values if x[0] is not None}
    all_values_parse = len(comparable_values) == len(values)
    if len(eligible) > 1 and len(comparable_values) == 1 and all_values_parse:
        reason_codes.append("EQUIVALENT_NUMERIC_DUPLICATES")
    elif len(comparable_values) > 1:
        reason_codes.append("COMPETING_NUMERIC_VALUES")

    if len(eligible) == 1:
        status = "SINGLE_EXPECTED_PERIOD_CANDIDATE"
    elif "EQUIVALENT_NUMERIC_DUPLICATES" in reason_codes and "MULTIPLE_UNITS" not in reason_codes:
        status = "EQUIVALENT_DUPLICATE_CANDIDATES"
    else:
        status = "GENUINE_AMBIGUITY"

    return {
        "status": status,
        "reason_codes": reason_codes,
        "candidate_count": len(items),
        "eligible_count": len(eligible),
        "concepts": concepts,
        "contexts": contexts,
        "duration_buckets": buckets,
        "units": [list(x) for x in units],
        "normalized_value_count": len(comparable_values),
        "eligible": eligible,
    }


def audit_ambiguities(documents: Iterable[dict]) -> dict:
    docs = list(documents)
    per_document = []
    status_counts = Counter()
    reason_counts = Counter()
    domain_feature_status = defaultdict(Counter)
    domain_feature_concepts = defaultdict(Counter)

    for document in docs:
        rows = enrich_candidate_facts(document)
        key = "|".join([
            str(document.get("symbol")),
            str(document.get("quarter_end")),
            str(document.get("reporting_basis")),
        ])
        by_feature = defaultdict(list)
        for row in rows:
            by_feature[row["feature"]].append(row)

        feature_results = {}
        for feature in FEATURE_CANDIDATES:
            result = diagnose_feature_rows(by_feature.get(feature, []), feature=feature)
            # Avoid bloating the summary artifacts with every raw row while
            # retaining enough evidence for targeted review.
            compact = dict(result)
            compact["eligible"] = [
                {
                    "concept_local_name": x.get("concept_local_name"),
                    "context_ref": x.get("context_ref"),
                    "period_kind": x.get("period_kind"),
                    "duration_days": x.get("duration_days"),
                    "duration_bucket": x.get("duration_bucket"),
                    "unit_measures": x.get("unit_measures"),
                    "raw_value": x.get("raw_value"),
                    "scale": x.get("scale"),
                    "normalized_value": normalized_numeric_value(x),
                }
                for x in result.get("eligible", [])
            ]
            feature_results[feature] = compact
            status_counts[result["status"]] += 1
            for reason in result["reason_codes"]:
                reason_counts[reason] += 1

            domain = document.get("source_url", "")
            from .canonical_mapping_audit import classify_domain
            d = classify_domain(domain)
            domain_feature_status[(d, feature)][result["status"]] += 1
            for concept in result.get("concepts", []):
                domain_feature_concepts[(d, feature)][concept] += 1

        per_document.append({
            "document_key": key,
            "symbol": document.get("symbol"),
            "quarter_end": document.get("quarter_end"),
            "reporting_basis": document.get("reporting_basis"),
            "source_url": document.get("source_url"),
            "features": feature_results,
        })

    domain_feature_summary = []
    keys = sorted(set(domain_feature_status) | set(domain_feature_concepts))
    for domain, feature in keys:
        domain_feature_summary.append({
            "domain": domain,
            "feature": feature,
            "status_counts": dict(domain_feature_status[(domain, feature)]),
            "concept_counts": dict(domain_feature_concepts[(domain, feature)]),
        })

    freeze_candidates = []
    blocked = []
    for row in domain_feature_summary:
        statuses = row["status_counts"]
        domain = row["domain"]
        feature = row["feature"]
        nonmissing = sum(
            count for status, count in statuses.items()
            if status not in {"MISSING", "NO_EXPECTED_PERIOD_CANDIDATE"}
        )
        genuine = statuses.get("GENUINE_AMBIGUITY", 0)
        single = statuses.get("SINGLE_EXPECTED_PERIOD_CANDIDATE", 0)
        equiv = statuses.get("EQUIVALENT_DUPLICATE_CANDIDATES", 0)
        concepts = row["concept_counts"]

        # This is only a freeze *candidate*, never an automatic freeze.
        if nonmissing > 0 and genuine == 0 and len(concepts) == 1:
            freeze_candidates.append({
                "domain": domain,
                "feature": feature,
                "observed_nonmissing_documents": nonmissing,
                "single_count": single,
                "equivalent_duplicate_count": equiv,
                "sole_observed_concept": next(iter(concepts)),
                "status": "CANDIDATE_FOR_MAPPING_FREEZE_REVIEW",
            })
        elif nonmissing > 0:
            blocked.append({
                "domain": domain,
                "feature": feature,
                "observed_nonmissing_documents": nonmissing,
                "genuine_ambiguity_count": genuine,
                "observed_concepts": concepts,
                "status": "BLOCKED_PENDING_RULE_OR_MORE_EVIDENCE",
            })

    return {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A2_AMBIGUITY_RESOLUTION_AUDIT_V1",
        "document_count": len(docs),
        "status_counts": dict(status_counts),
        "reason_counts": dict(reason_counts),
        "domain_feature_summary": domain_feature_summary,
        "freeze_candidates": freeze_candidates,
        "blocked_domain_features": blocked,
        "per_document": per_document,
        "authority": "SHADOW_ONLY",
        "mapping_frozen": False,
        "production_model_changed": False,
        "model_training_started": False,
    }
