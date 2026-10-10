"""Scaled mapping validation helpers for Fundamental Research V2 Phase 2A.3."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .core import effective_availability_ts
from .canonical_mapping_audit import classify_domain
from .period_semantic_resolution import resolve_feature


def latest_event_groups(events: Iterable[dict]) -> list[dict]:
    """Select the latest PIT-qualified filing per symbol/quarter/basis.

    Unlike the Phase 2A.2 pilot selector, this intentionally retains groups
    whose latest event lacks an XBRL URL so that the gap is visible instead of
    silently falling back to an earlier filing version.
    """
    grouped: dict[tuple[str, str, str], dict] = {}
    for raw in events:
        event = dict(raw)
        symbol = event.get("symbol")
        quarter = event.get("quarter_end")
        basis = event.get("reporting_basis")
        if not symbol or not quarter or not basis:
            continue
        key = (symbol, quarter, basis)
        current = grouped.get(key)
        if current is None or effective_availability_ts(event) > effective_availability_ts(current):
            grouped[key] = event
    return [grouped[key] for key in sorted(grouped)]


def frozen_features_for_domain(mapping_contract: dict, domain: str) -> dict[str, str]:
    mappings = mapping_contract.get("domain_mappings") or {}
    values = mappings.get(domain) or {}
    return {str(k): str(v) for k, v in values.items()}


def compact_document_resolution(document: dict, mapping_contract: dict) -> dict:
    domain = classify_domain(document.get("source_url"))
    frozen = frozen_features_for_domain(mapping_contract, domain)

    features = {}
    hard_failures = []
    coverage_gaps = []

    if not frozen:
        hard_failures.append({
            "code": "NO_FROZEN_MAPPING_FOR_DOMAIN",
            "domain": domain,
        })

    for feature, expected_concept in sorted(frozen.items()):
        result = resolve_feature(document, feature=feature)
        selected = result.get("selected")
        selected_concept = result.get("selected_concept")

        if result["status"] in {"SELECTED", "SELECTED_EQUIVALENT_DUPLICATES"}:
            if selected_concept != expected_concept:
                hard_failures.append({
                    "code": "FROZEN_MAPPING_CONCEPT_MISMATCH",
                    "feature": feature,
                    "expected_concept": expected_concept,
                    "selected_concept": selected_concept,
                })
            features[feature] = {
                "status": result["status"],
                "expected_concept": expected_concept,
                "selected_concept": selected_concept,
                "selected": selected,
            }
        elif result["status"] == "MISSING_EXPECTED_PERIOD":
            coverage_gaps.append({
                "code": "MISSING_EXPECTED_PERIOD",
                "feature": feature,
                "expected_concept": expected_concept,
            })
            features[feature] = {
                "status": result["status"],
                "expected_concept": expected_concept,
                "selected_concept": None,
                "selected": None,
            }
        elif result["status"] == "NO_PRIORITY_CONCEPT_PRESENT":
            coverage_gaps.append({
                "code": "FROZEN_CONCEPT_NOT_PRESENT",
                "feature": feature,
                "expected_concept": expected_concept,
            })
            features[feature] = {
                "status": result["status"],
                "expected_concept": expected_concept,
                "selected_concept": None,
                "selected": None,
            }
        else:
            hard_failures.append({
                "code": "SCALED_SEMANTIC_AMBIGUITY",
                "feature": feature,
                "expected_concept": expected_concept,
                "resolver_status": result["status"],
                "evidence": result.get("evidence", [])[:12],
            })
            features[feature] = {
                "status": result["status"],
                "expected_concept": expected_concept,
                "selected_concept": selected_concept,
                "selected": selected,
            }

    return {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A3_COMPACT_DOCUMENT_RESOLUTION_V1",
        "source_event_id": document.get("source_event_id"),
        "provider_seq_id": document.get("provider_seq_id"),
        "symbol": document.get("symbol"),
        "quarter_end": document.get("quarter_end"),
        "reporting_basis": document.get("reporting_basis"),
        "submission_type": document.get("submission_type"),
        "availability_ts": document.get("availability_ts"),
        "source_url": document.get("source_url"),
        "source_content_sha256": document.get("source_content_sha256"),
        "source_document_kind": document.get("source_document_kind"),
        "domain": domain,
        "all_fact_count": document.get("all_fact_count"),
        "numeric_fact_count": document.get("numeric_fact_count"),
        "context_count": document.get("context_count"),
        "unit_count": document.get("unit_count"),
        "features": features,
        "hard_failures": hard_failures,
        "coverage_gaps": coverage_gaps,
        "authority": "SHADOW_ONLY",
        "production_model_changed": False,
        "model_training_started": False,
    }


def summarize_resolutions(resolutions: Iterable[dict], *, expected_document_count: int, retrieval_failures: list[dict], url_gaps: list[dict]) -> dict:
    rows = list(resolutions)
    domain_docs = defaultdict(int)
    domain_feature_selected = defaultdict(int)
    domain_feature_missing = defaultdict(int)
    hard = []

    for row in rows:
        domain = row.get("domain") or "UNKNOWN"
        domain_docs[domain] += 1
        hard.extend(
            {
                "symbol": row.get("symbol"),
                "quarter_end": row.get("quarter_end"),
                "reporting_basis": row.get("reporting_basis"),
                **failure,
            }
            for failure in row.get("hard_failures", [])
        )
        for feature, info in (row.get("features") or {}).items():
            if info.get("status") in {"SELECTED", "SELECTED_EQUIVALENT_DUPLICATES"}:
                domain_feature_selected[(domain, feature)] += 1
            else:
                domain_feature_missing[(domain, feature)] += 1

    coverage = []
    keys = sorted(set(domain_feature_selected) | set(domain_feature_missing))
    for domain, feature in keys:
        selected = domain_feature_selected[(domain, feature)]
        missing = domain_feature_missing[(domain, feature)]
        coverage.append({
            "domain": domain,
            "feature": feature,
            "selected_document_count": selected,
            "missing_document_count": missing,
            "selection_rate_among_parsed": selected / (selected + missing) if selected + missing else 0.0,
        })

    if retrieval_failures:
        status = "INCOMPLETE_RETRIEVAL"
    elif hard:
        status = "FAIL_SCALED_MAPPING_AMBIGUITY"
    elif url_gaps or any(x["missing_document_count"] for x in coverage):
        status = "PASS_WITH_QUANTIFIED_COVERAGE_GAPS"
    else:
        status = "PASS_FULL_MAPPING_COVERAGE"

    return {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A3_SCALED_MAPPING_VALIDATION_SUMMARY_V1",
        "authority": "SHADOW_ONLY",
        "expected_document_count": expected_document_count,
        "parsed_document_count": len(rows),
        "latest_event_xbrl_url_gap_count": len(url_gaps),
        "retrieval_failure_count": len(retrieval_failures),
        "semantic_hard_failure_count": len(hard),
        "domain_document_counts": dict(sorted(domain_docs.items())),
        "feature_coverage": coverage,
        "xbrl_url_gaps": url_gaps,
        "retrieval_failures": retrieval_failures,
        "semantic_hard_failures": hard,
        "status": status,
        "mapping_frozen_for_research": True,
        "production_model_changed": False,
        "model_training_started": False,
    }
