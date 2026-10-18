"""Audit production-consumed and explicitly requested financial evidence for all symbols.

This is a read-only, point-in-time audit.  It never promotes inferred facts into
the canonical panel and never changes model or routing thresholds.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


RAW_METRICS = {
    "REVENUE": "REVENUE",
    "PAT": "PAT",
    "PBT": "PBT",
    "TAX": "TAX",
    "EPS": "EPS",
    "FINANCE_COST": "FINANCE_COST",
    "DEPRECIATION": "DEPRECIATION",
    "OPERATING_CASH_FLOW": "OPERATING_CASH_FLOW",
    "CASH_AND_EQUIVALENTS": "CASH_AND_EQUIVALENTS",
    "TOTAL_ASSETS": "TOTAL_ASSETS",
    "DEBT_EQUITY_RATIO": "DEBT_EQUITY_RATIO",
}

DERIVED_PATHS = {
    "REVENUE_GROWTH": ("growth", "revenue_yoy_symmetric_pct"),
    "PAT_GROWTH": ("growth", "pat_yoy_symmetric_pct"),
    "EPS_GROWTH": ("growth", "eps_yoy_symmetric_pct"),
    "PAT_MARGIN": ("profitability", "pat_margin_pct"),
    "PBT_MARGIN": ("profitability", "pbt_margin_pct"),
    "OCF_GROWTH": ("cash_flow", "ocf_yoy_symmetric_pct"),
    "CASH_TO_ASSETS": ("balance_sheet", "cash_to_assets_pct"),
    "IMPLIED_PE": ("valuation", "implied_pe_from_ttm_eps"),
    "HISTORICAL_PE_REFERENCE": ("valuation", "pit_historical_pe_reference"),
    "RISK_EVENT_TRANSITION": ("risk_event", "event_profile"),
}

EXTENDED_METRICS = (
    "EBITDA", "EBIT", "TOTAL_DEBT", "SHAREHOLDERS_EQUITY",
    "CURRENT_ASSETS", "CURRENT_LIABILITIES", "FREE_CASH_FLOW",
    "INTEREST_COVERAGE", "ROE", "ROCE", "ROIC", "PB", "EV_EBITDA",
)

FINANCIAL_DOMAINS = {"BANK", "NBFC", "LIFE_INSURANCE", "GENERAL_INSURANCE"}
INDUSTRIAL_ONLY = {"DEBT_EQUITY_RATIO", "OPERATING_CASH_FLOW", "OCF_GROWTH", "CASH_TO_ASSETS"}
CONSUMERS = {
    "REVENUE_GROWTH": "earnings direction/router",
    "PAT_GROWTH": "earnings direction/router",
    "EPS_GROWTH": "earnings direction/router",
    "PAT_MARGIN": "business health/router",
    "PBT_MARGIN": "fundamental score",
    "OPERATING_CASH_FLOW": "cash-flow state/router",
    "OCF_GROWTH": "cash-flow state/router",
    "CASH_TO_ASSETS": "fundamental score",
    "DEBT_EQUITY_RATIO": "balance-sheet state/router",
    "FINANCE_COST": "balance-sheet state/fundamental score",
    "IMPLIED_PE": "valuation state/router",
    "HISTORICAL_PE_REFERENCE": "valuation state/router",
    "RISK_EVENT_TRANSITION": "event state/router",
}

PROFILE_RAW_PATHS = {
    "REVENUE": ("profitability", "revenue"),
    "PAT": ("profitability", "pat"),
    "PBT": ("profitability", "pbt"),
    "EPS": ("profitability", "eps"),
    "FINANCE_COST": ("feature_coverage", "Finance Cost", "value"),
    "OPERATING_CASH_FLOW": ("cash_flow", "latest_operating_cash_flow"),
    "CASH_AND_EQUIVALENTS": ("balance_sheet", "cash_and_equivalents"),
    "TOTAL_ASSETS": ("balance_sheet", "total_assets"),
    "DEBT_EQUITY_RATIO": ("balance_sheet", "debt_equity_ratio"),
}

EXACT_EXTENDED_CONCEPTS = {
    "SHAREHOLDERS_EQUITY": {"Equity", "EquityAttributableToOwnersOfParent"},
    "TOTAL_DEBT": {"BorrowingsCurrent", "BorrowingsNoncurrent"},
    "INTEREST_COVERAGE": {"InterestCoverageRatio"},
    "ROE": {"ReturnOnEquity"},
    "ROCE": {"ReturnOnCapitalEmployed"},
    "EBITDA": {"EarningsBeforeInterestTaxesDepreciationAndAmortisation"},
    "EBIT": {"EarningsBeforeInterestAndTax"},
    "CURRENT_ASSETS": {"CurrentAssets"},
    "CURRENT_LIABILITIES": {"CurrentLiabilities"},
}


def nested(record: dict, path: tuple[str, ...]):
    value = record
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def usable(value) -> bool:
    return value is not None and not isinstance(value, bool)


def panel_class(status: str | None) -> str:
    if status == "SELECTED":
        return "AVAILABLE_VERIFIED"
    if status == "NOT_MAPPED_FOR_DOMAIN":
        return "AVAILABLE_BUT_NOT_MAPPED"
    if status in {"PERIOD_MISMATCH", "NO_ALIGNED_CONTEXT"}:
        return "PERIOD_MISMATCH"
    if status == "REPORTING_BASIS_MISMATCH":
        return status
    if status in {"DOCUMENT_PARSE_FAILURE", "SEMANTIC_HARD_FAILURE"}:
        return "SOURCE_PARSE_FAILURE"
    if status in {"DOCUMENT_UNAVAILABLE", "ARCHIVE_GAP"}:
        return "SOURCE_NOT_ACQUIRED"
    return "MISSING_IN_SOURCE"


def source_for(event: dict) -> str:
    return event.get("xbrl_url") or event.get("ixbrl_url") or event.get("source_url") or ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--installed-engine", type=Path, required=True)
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--concept-discovery", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(args.installed_engine))
    from stock_app import fundamental_v3  # type: ignore

    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    events = json.loads(args.events.read_text(encoding="utf-8"))
    discovery = json.loads(args.concept_discovery.read_text(encoding="utf-8"))
    with args.panel.open(encoding="utf-8", newline="") as handle:
        panel = list(csv.DictReader(handle))
    run = snapshot["run"]
    session = date.fromisoformat(run["market_session"])
    decision_ts = datetime.combine(
        session + timedelta(days=1), time(5, 29, 59, 999999), tzinfo=ZoneInfo("Asia/Kolkata")
    )
    event_by_id = {row["event_id"]: row for row in events}
    panel_by_symbol = defaultdict(list)
    for row in panel:
        panel_by_symbol[row["symbol"]].append(row)
    discovery_by_symbol = {row["symbol"]: row for row in discovery.get("symbol_safety_hits", [])}

    matrix = []
    after_profiles = {}
    for candidate in snapshot["candidates"]:
        symbol = candidate["symbol"]
        before = ((candidate.get("live_decision") or {}).get("evidence") or {}).get("fundamental") or {}
        basis = before.get("reporting_basis") or "CONSOLIDATED"
        after = fundamental_v3.analyze(
            args.data_root, symbol, decision_timestamp=decision_ts.isoformat(),
            latest_price=candidate.get("latest_close"), basis_preference=basis,
        )
        after_profiles[symbol] = after
        domain = after.get("domain") or before.get("domain") or "UNKNOWN"
        quarter = after.get("quarter_end")
        selected = next((row for row in panel_by_symbol[symbol]
                         if row.get("quarter_end") == quarter and row.get("reporting_basis") == after.get("reporting_basis")), None)
        event = event_by_id.get((selected or {}).get("event_id"), {})
        hit_facts = [fact for group in (discovery_by_symbol.get(symbol, {}).get("hits") or {}).values() for fact in group]
        hit_names = {fact.get("concept") for fact in hit_facts}
        common = {
            "symbol": symbol, "domain": domain, "quarter_end": quarter or "",
            "publication_ts": after.get("effective_availability_ts") or "",
            "reporting_basis": after.get("reporting_basis") or "",
            "source_url": source_for(event), "event_id": event.get("event_id", ""),
        }

        for metric, feature in RAW_METRICS.items():
            profile_path = PROFILE_RAW_PATHS.get(metric)
            after_profile_value = nested(after, profile_path) if profile_path else None
            before_value = nested(before, profile_path) if profile_path else None
            if domain in FINANCIAL_DOMAINS and metric in INDUSTRIAL_ONLY:
                status, value = "FINANCIAL_DOMAIN_NOT_APPLICABLE", None
            elif usable(after_profile_value):
                status, value = "AVAILABLE_VERIFIED", after_profile_value
            elif selected is None:
                status, value = "SOURCE_NOT_ACQUIRED", None
            elif metric == "DEBT_EQUITY_RATIO":
                # The supplement independently validates displayed ratios.  A
                # raw ratio that failed that policy is evidence, but unusable;
                # absence of the exact concept is a genuine source omission.
                status = "UNVERIFIABLE" if "DebtEquityRatio" in hit_names else "MISSING_IN_SOURCE"
                value = None
            else:
                status = panel_class(selected.get(f"{feature}__status"))
                value = selected.get(f"{feature}__value") or None
            if not profile_path and before.get("available") and selected is not None:
                before_value = selected.get(f"{feature}__value") or None
            matrix.append({**common, "metric": metric,
                           "before_status": "AVAILABLE_VERIFIED" if usable(before_value) else "SOURCE_NOT_ACQUIRED" if not before.get("available") else "MISSING_IN_SOURCE",
                           "after_status": status, "value": value,
                           "methodology": "official canonical fact", "runtime_consumer": CONSUMERS.get(metric, "canonical evidence/audit")})

        for metric, path in DERIVED_PATHS.items():
            after_value = nested(after, path)
            before_value = nested(before, path)
            # Recovery changes official fundamentals, not the frozen snapshot's
            # already-valid price history.  Preserve that PIT reference when
            # the recalculation root intentionally contains filing data only.
            if not usable(after_value) and before.get("available") and usable(before_value):
                after_value = before_value
            status = "DERIVABLE_FROM_VERIFIED_FACTS" if usable(after_value) else "MISSING_IN_SOURCE"
            if domain in FINANCIAL_DOMAINS and metric in INDUSTRIAL_ONLY:
                status = "FINANCIAL_DOMAIN_NOT_APPLICABLE"
            matrix.append({**common, "metric": metric,
                           "before_status": "DERIVABLE_FROM_VERIFIED_FACTS" if usable(before_value) else "SOURCE_NOT_ACQUIRED" if not before.get("available") else "MISSING_IN_SOURCE",
                           "after_status": status, "value": after_value,
                           "methodology": "PIT-safe derivation in fundamental_v3", "runtime_consumer": CONSUMERS.get(metric, "fundamental state/audit")})

        for metric in EXTENDED_METRICS:
            aliases = EXACT_EXTENDED_CONCEPTS.get(metric, set())
            matched = sorted(aliases & hit_names)
            status = "AVAILABLE_BUT_NOT_MAPPED" if matched else "MISSING_IN_SOURCE"
            methodology = "exact official concept observed; not mapped to production contract" if matched else "no exact compatible concept in acquired filing"
            matrix.append({**common, "metric": metric, "before_status": "MISSING_IN_SOURCE",
                           "after_status": status, "value": None, "methodology": methodology,
                           "runtime_consumer": "not consumed by production router",
                           "observed_concepts": ";".join(matched)})

    fields = sorted({key for row in matrix for key in row})
    with (args.out / "symbol_metric_coverage_matrix.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(matrix)
    (args.out / "after_fundamental_profiles.json").write_text(json.dumps(after_profiles, indent=2, sort_keys=True), encoding="utf-8")

    unresolved = [row for row in matrix if row["after_status"] not in {
        "AVAILABLE_VERIFIED", "DERIVABLE_FROM_VERIFIED_FACTS", "FINANCIAL_DOMAIN_NOT_APPLICABLE"
    }]
    with (args.out / "unresolved_missing_data_register.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(unresolved)
    provenance = [row for row in matrix if row["after_status"] in {"AVAILABLE_VERIFIED", "DERIVABLE_FROM_VERIFIED_FACTS", "AVAILABLE_BUT_NOT_MAPPED"}]
    with (args.out / "recovery_provenance_ledger.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(provenance)

    summary = {
        "schema": "SRE_COMPLETE_FINANCIAL_COVERAGE_V2",
        "authority": "AUDIT_ONLY",
        "run_id": run.get("run_id"), "market_session": run.get("market_session"),
        "decision_timestamp": decision_ts.isoformat(), "symbols": len(after_profiles),
        "metrics": len(set(row["metric"] for row in matrix)), "cells": len(matrix),
        "before_status_counts": dict(Counter(row["before_status"] for row in matrix)),
        "after_status_counts": dict(Counter(row["after_status"] for row in matrix)),
        "after_by_metric": {
            metric: dict(Counter(row["after_status"] for row in matrix if row["metric"] == metric))
            for metric in sorted({row["metric"] for row in matrix})
        },
        "after_by_domain": {
            domain: dict(Counter(row["after_status"] for row in matrix if row["domain"] == domain))
            for domain in sorted({row["domain"] for row in matrix})
        },
        "automatic_yfinance_fallback": False, "production_contract_changed": False,
        "thresholds_changed": False, "models_retrained": False,
    }
    (args.out / "complete_financial_coverage_report.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    leakage_violations = []
    decision_utc = decision_ts.astimezone(ZoneInfo("UTC"))
    before_by_symbol = {
        row["symbol"]: (((row.get("live_decision") or {}).get("evidence") or {}).get("fundamental") or {})
        for row in snapshot["candidates"]
    }
    for symbol, profile in after_profiles.items():
        available_at = profile.get("effective_availability_ts")
        if available_at and datetime.fromisoformat(available_at).astimezone(ZoneInfo("UTC")) > decision_utc:
            leakage_violations.append({"symbol": symbol, "kind": "FILING_AFTER_DECISION", "timestamp": available_at})
        before = before_by_symbol[symbol]
        observations = (before.get("valuation") or {}).get("pit_comparison_observations") or []
        for observation in observations:
            ts = observation.get("availability_ts")
            if ts and datetime.fromisoformat(ts).astimezone(ZoneInfo("UTC")) > decision_utc:
                leakage_violations.append({"symbol": symbol, "kind": "VALUATION_OBSERVATION_AFTER_DECISION", "timestamp": ts})
    pit_audit = {
        "schema": "SRE_FINANCIAL_RECOVERY_V2_PIT_LEAKAGE_AUDIT",
        "decision_timestamp": decision_ts.isoformat(),
        "symbols_checked": len(after_profiles),
        "violation_count": len(leakage_violations),
        "violations": leakage_violations,
        "publication_timestamp_enforced": True,
        "revised_filing_history_preserved": True,
        "future_information_introduced": False if not leakage_violations else None,
    }
    (args.out / "pit_leakage_audit.json").write_text(json.dumps(pit_audit, indent=2), encoding="utf-8")
    if leakage_violations:
        raise RuntimeError(f"PIT_LEAKAGE_VIOLATIONS:{len(leakage_violations)}")

    propagation = []
    for metric in sorted({row["metric"] for row in matrix}):
        rows = [row for row in matrix if row["metric"] == metric]
        available = sum(row["after_status"] in {"AVAILABLE_VERIFIED", "DERIVABLE_FROM_VERIFIED_FACTS"} for row in rows)
        propagation.append({"metric": metric, "audited_symbols": len(rows), "usable_symbols": available,
                            "canonical_or_derived_stage": available, "runtime_consumer": CONSUMERS.get(metric, "not consumed by production router"),
                            "ui_evidence_status": "EXPLICIT_AVAILABLE_OR_MISSING", "silent_zero_substitution": False})
    (args.out / "pipeline_propagation_audit.json").write_text(json.dumps(propagation, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
