from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

module = r'''from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "SRE_FUNDAMENTAL_INTELLIGENCE_V3"
AUTHORITY = "SHADOW_ONLY"
MIN_READY_SCORE_COVERAGE = 0.60
STALE_FILING_DAYS = 220

CORE_FEATURES = (
    "REVENUE",
    "PAT",
    "PBT",
    "EPS",
    "OPERATING_CASH_FLOW",
    "CASH_AND_EQUIVALENTS",
    "TOTAL_ASSETS",
    "FINANCE_COST",
    "DEBT_EQUITY_RATIO",
)

EXTENDED_FEATURES = (
    "EBITDA",
    "EBIT",
    "TOTAL_EQUITY",
    "CURRENT_ASSETS",
    "CURRENT_LIABILITIES",
    "FREE_CASH_FLOW",
    "ROE",
    "ROCE",
    "ROIC",
    "PE_RATIO",
    "PB_RATIO",
    "EV_EBITDA",
)

PRESENT_STATUSES = {"SELECTED", "SELECTED_EQUIVALENT_DUPLICATES"}


def _symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if text.endswith(suffix):
            text = text[:-3]
    return text


def _dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10] + "T00:00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _candidate_roots(root: Path) -> list[Path]:
    roots = [root.resolve()]
    if root.parent != root:
        roots.append(root.parent.resolve())
    output = []
    for item in roots:
        if item not in output:
            output.append(item)
    return output


def discover_sources(root: Path) -> dict[str, Path | None]:
    panel_candidates = []
    event_candidates = []
    risk_candidates = []
    validation_candidates = []
    for base in _candidate_roots(root):
        research = base / "NextGen Research" / "results"
        panel_candidates.extend([
            research / "fundamental_v2_phase2a4_feature_panel" / "canonical_feature_panel.csv",
            research / "fundamental_v2_phase2a4_feature_panel" / "canonical_feature_panel.jsonl",
        ])
        event_candidates.append(
            research / "fundamental_v2_phase2a5_derived_event_transforms" / "derived_events.jsonl"
        )
        risk_candidates.append(
            research / "fundamental_v2_phase2a7_risk_events" / "risk_event_profiles.jsonl"
        )
        validation_candidates.append(
            research / "fundamental_v2_phase2a9_independent_validation" / "final_decision.json"
        )

    def newest(paths: Iterable[Path]) -> Path | None:
        existing = [p for p in paths if p.exists() and p.is_file()]
        return max(existing, key=lambda p: (p.stat().st_mtime_ns, str(p))) if existing else None

    return {
        "canonical_panel": newest(panel_candidates),
        "derived_events": newest(event_candidates),
        "risk_profiles": newest(risk_candidates),
        "independent_validation": newest(validation_candidates),
    }


def _read_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _usable_feature(row: dict[str, Any], feature: str) -> float | None:
    direct = _num(row.get(feature))
    if direct is not None:
        return direct
    value = _num(row.get(f"{feature}__value"))
    status = str(row.get(f"{feature}__status") or "")
    if value is None:
        return None
    if status and status not in PRESENT_STATUSES:
        return None
    return value


def _cutoff(decision_timestamp: Any) -> datetime:
    return _dt(decision_timestamp) or datetime.now(timezone.utc)


def _pit_rows(
    rows: Iterable[dict[str, Any]],
    symbol: str,
    cutoff: datetime,
    basis_preference: str = "CONSOLIDATED",
) -> tuple[list[dict[str, Any]], str | None]:
    wanted = _symbol(symbol)
    candidates = []
    for row in rows:
        if _symbol(row.get("symbol")) != wanted:
            continue
        available = _dt(row.get("availability_ts") or row.get("effective_availability_ts"))
        if available is None or available > cutoff:
            continue
        candidates.append(row)

    if not candidates:
        return [], None

    bases = {str(x.get("reporting_basis") or "").upper() for x in candidates}
    basis = basis_preference if basis_preference in bases else sorted(bases)[0]
    selected = [x for x in candidates if str(x.get("reporting_basis") or "").upper() == basis]
    selected.sort(key=lambda x: (
        str(x.get("quarter_end") or x.get("current_quarter_end") or ""),
        str(x.get("availability_ts") or x.get("effective_availability_ts") or ""),
    ))
    return selected, basis


def _latest_events(
    rows: Iterable[dict[str, Any]],
    symbol: str,
    cutoff: datetime,
    basis: str | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for row in rows:
        if _symbol(row.get("symbol")) != _symbol(symbol):
            continue
        if basis and str(row.get("reporting_basis") or "").upper() != basis:
            continue
        available = _dt(row.get("effective_availability_ts"))
        if available is None or available > cutoff:
            continue
        feature = str(row.get("feature") or "").upper()
        comparison = str(row.get("comparison") or "").upper()
        if not feature or not comparison:
            continue
        key = (feature, comparison)
        prior = result.get(key)
        if prior is None or str(row.get("current_quarter_end") or "") > str(prior.get("current_quarter_end") or ""):
            result[key] = row
    return result


def _latest_risk(
    rows: Iterable[dict[str, Any]],
    symbol: str,
    cutoff: datetime,
    basis: str | None,
) -> dict[str, Any] | None:
    candidates = []
    for row in rows:
        if _symbol(row.get("symbol")) != _symbol(symbol):
            continue
        if basis and str(row.get("reporting_basis") or "").upper() != basis:
            continue
        available = _dt(row.get("effective_availability_ts"))
        if available is None or available > cutoff:
            continue
        candidates.append(row)
    if not candidates:
        return None
    return max(candidates, key=lambda x: (
        str(x.get("current_quarter_end") or ""),
        str(x.get("effective_availability_ts") or ""),
    ))


def _symmetric_pct(event: dict[str, Any] | None) -> float | None:
    if not event:
        return None
    value = _num(event.get("symmetric_change"))
    return None if value is None else value * 100.0


def _ttm(rows: list[dict[str, Any]], feature: str) -> float | None:
    values = []
    for row in rows[-4:]:
        value = _usable_feature(row, feature)
        if value is None:
            return None
        values.append(value)
    return sum(values) if len(values) == 4 else None


def _ratio(numerator: float | None, denominator: float | None, scale: float = 1.0) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator * scale


def _direction_score(value: float | None, good_scale: float = 20.0) -> float | None:
    if value is None:
        return None
    return max(-1.0, min(1.0, value / good_scale))


def _level_score(value: float | None, target: float, floor: float = 0.0) -> float | None:
    if value is None:
        return None
    if value <= floor:
        return -1.0
    return max(-1.0, min(1.0, (value - floor) / max(1e-9, target - floor)))


def _score(
    latest: dict[str, Any],
    history: list[dict[str, Any]],
    events: dict[tuple[str, str], dict[str, Any]],
    risk: dict[str, Any] | None,
    price: float | None,
) -> dict[str, Any]:
    ttm_revenue = _ttm(history, "REVENUE")
    ttm_pat = _ttm(history, "PAT")
    ttm_pbt = _ttm(history, "PBT")
    ttm_eps = _ttm(history, "EPS")
    pat_margin = _ratio(ttm_pat, ttm_revenue, 100.0)
    pbt_margin = _ratio(ttm_pbt, ttm_revenue, 100.0)
    pe = None if ttm_eps is None or ttm_eps <= 0 or price is None else price / ttm_eps

    latest_ocf = _usable_feature(latest, "OPERATING_CASH_FLOW")
    latest_cash = _usable_feature(latest, "CASH_AND_EQUIVALENTS")
    latest_assets = _usable_feature(latest, "TOTAL_ASSETS")
    debt_equity = _usable_feature(latest, "DEBT_EQUITY_RATIO")
    cash_assets = _ratio(latest_cash, latest_assets, 100.0)

    components: dict[str, dict[str, Any]] = {}

    def add(name: str, value: float | None, weight: float, evidence: Any):
        components[name] = {"signal": value, "weight": weight, "evidence": evidence}

    revenue_yoy = _symmetric_pct(events.get(("REVENUE", "YOY")))
    pat_yoy = _symmetric_pct(events.get(("PAT", "YOY")))
    eps_yoy = _symmetric_pct(events.get(("EPS", "YOY")))
    ocf_yoy = _symmetric_pct(events.get(("OPERATING_CASH_FLOW", "YOY_SAME_QUARTER_ONLY")))
    cash_yoy = _symmetric_pct(events.get(("CASH_AND_EQUIVALENTS", "YOY_SAME_QUARTER_ONLY")))
    finance_qoq = _symmetric_pct(events.get(("FINANCE_COST", "QOQ")))

    add("revenue_growth", _direction_score(revenue_yoy, 25.0), 0.12, revenue_yoy)
    add("pat_growth", _direction_score(pat_yoy, 30.0), 0.12, pat_yoy)
    add("eps_growth", _direction_score(eps_yoy, 30.0), 0.08, eps_yoy)
    add("pat_margin", _level_score(pat_margin, 18.0, 0.0), 0.10, pat_margin)
    add("pbt_margin", _level_score(pbt_margin, 22.0, 0.0), 0.08, pbt_margin)
    add("ocf_direction", _direction_score(ocf_yoy, 30.0), 0.12, ocf_yoy)
    add("ocf_sign", None if latest_ocf is None else (1.0 if latest_ocf > 0 else -1.0), 0.07, latest_ocf)
    add("cash_direction", _direction_score(cash_yoy, 30.0), 0.05, cash_yoy)
    add("cash_assets", _level_score(cash_assets, 12.0, 0.0), 0.04, cash_assets)
    add("finance_cost", None if finance_qoq is None else -_direction_score(finance_qoq, 25.0), 0.05, finance_qoq)
    add("leverage", None if debt_equity is None else max(-1.0, min(1.0, (1.5 - debt_equity) / 1.5)), 0.04, debt_equity)

    risk_signal = None
    profile = str((risk or {}).get("event_profile") or "")
    if profile == "PURE_IMPROVEMENT":
        risk_signal = 1.0
    elif profile == "PURE_DETERIORATION":
        risk_signal = -1.0
    elif profile == "MIXED_DIRECTIONAL":
        risk_signal = -0.1
    elif profile == "NO_DIRECTIONAL_EVIDENCE":
        risk_signal = 0.0
    if risk and risk.get("strong_deterioration_transition"):
        risk_signal = min(risk_signal if risk_signal is not None else 0.0, -1.0)
    if risk and risk.get("strong_improvement_transition"):
        risk_signal = max(risk_signal if risk_signal is not None else 0.0, 1.0)
    add("risk_event_profile", risk_signal, 0.13, profile or None)

    total_weight = sum(float(x["weight"]) for x in components.values())
    used = [x for x in components.values() if x["signal"] is not None]
    used_weight = sum(float(x["weight"]) for x in used)
    weighted = sum(float(x["signal"]) * float(x["weight"]) for x in used)
    coverage = used_weight / total_weight if total_weight else 0.0
    normalized = weighted / used_weight if used_weight else None
    score = None if normalized is None else max(0.0, min(100.0, 50.0 + 50.0 * normalized))

    if score is None:
        label = "UNAVAILABLE"
    elif coverage < MIN_READY_SCORE_COVERAGE:
        label = "LIMITED_COVERAGE"
    elif score >= 72:
        label = "STRONG"
    elif score >= 58:
        label = "POSITIVE"
    elif score >= 42:
        label = "NEUTRAL"
    elif score >= 28:
        label = "WEAK"
    else:
        label = "DETERIORATING"

    return {
        "score": _round(score, 2),
        "label": label,
        "score_component_coverage": _round(coverage, 4),
        "components": components,
        "ttm": {
            "revenue": _round(ttm_revenue, 2),
            "pat": _round(ttm_pat, 2),
            "pbt": _round(ttm_pbt, 2),
            "eps": _round(ttm_eps, 4),
            "pat_margin_pct": _round(pat_margin, 4),
            "pbt_margin_pct": _round(pbt_margin, 4),
        },
        "valuation": {
            "implied_pe_from_ttm_eps": _round(pe, 4),
            "basis": "PRICE_DIVIDED_BY_PIT_TTM_EPS" if pe is not None else "UNAVAILABLE",
            "peer_relative_valuation_available": False,
        },
        "growth": {
            "revenue_yoy_symmetric_pct": _round(revenue_yoy, 4),
            "pat_yoy_symmetric_pct": _round(pat_yoy, 4),
            "eps_yoy_symmetric_pct": _round(eps_yoy, 4),
        },
        "cash_flow": {
            "latest_operating_cash_flow": _round(latest_ocf, 2),
            "ocf_yoy_symmetric_pct": _round(ocf_yoy, 4),
        },
        "balance_sheet": {
            "cash_and_equivalents": _round(latest_cash, 2),
            "total_assets": _round(latest_assets, 2),
            "cash_to_assets_pct": _round(cash_assets, 4),
            "debt_equity_ratio": _round(debt_equity, 4),
        },
    }


def analyze(
    repo_root: Path,
    symbol: str,
    *,
    decision_timestamp: Any,
    latest_price: float | None = None,
    basis_preference: str = "CONSOLIDATED",
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    cutoff = _cutoff(decision_timestamp)
    sources = discover_sources(root)

    panel_rows = _read_rows(sources["canonical_panel"])
    if not panel_rows:
        return {
            "schema": SCHEMA_VERSION,
            "authority": AUTHORITY,
            "status": "NO_PIT_FUNDAMENTAL_DATA",
            "available": False,
            "symbol": _symbol(symbol),
            "decision_timestamp": cutoff.isoformat(),
            "reason": "Canonical official fundamental panel is not present in the connected engine source.",
            "missing_core_features": list(CORE_FEATURES),
            "missing_extended_features": list(EXTENDED_FEATURES),
            "score_component_coverage": 0.0,
            "promotion_allowed": False,
            "production_action_changed": False,
            "production_rank_changed": False,
            "point_in_time_safe": True,
            "sources": {k: str(v) if v else None for k, v in sources.items()},
        }

    history, basis = _pit_rows(panel_rows, symbol, cutoff, basis_preference)
    if not history:
        return {
            "schema": SCHEMA_VERSION,
            "authority": AUTHORITY,
            "status": "NO_PIT_SAFE_PROFILE_BY_DECISION_TIME",
            "available": False,
            "symbol": _symbol(symbol),
            "decision_timestamp": cutoff.isoformat(),
            "reason": "Fundamental records exist, but no filing for this stock was available by the active analysis timestamp.",
            "missing_core_features": list(CORE_FEATURES),
            "missing_extended_features": list(EXTENDED_FEATURES),
            "score_component_coverage": 0.0,
            "promotion_allowed": False,
            "production_action_changed": False,
            "production_rank_changed": False,
            "point_in_time_safe": True,
            "sources": {k: str(v) if v else None for k, v in sources.items()},
        }

    latest = history[-1]
    event_rows = _read_rows(sources["derived_events"])
    risk_rows = _read_rows(sources["risk_profiles"])
    events = _latest_events(event_rows, symbol, cutoff, basis)
    risk = _latest_risk(risk_rows, symbol, cutoff, basis)

    core_present = [feature for feature in CORE_FEATURES if _usable_feature(latest, feature) is not None]
    extended_present = [feature for feature in EXTENDED_FEATURES if _usable_feature(latest, feature) is not None]
    missing_core = [feature for feature in CORE_FEATURES if feature not in core_present]
    missing_extended = [feature for feature in EXTENDED_FEATURES if feature not in extended_present]

    scored = _score(latest, history, events, risk, _num(latest_price))
    available_ts = _dt(latest.get("availability_ts"))
    filing_age = None if available_ts is None else max(0, (cutoff.date() - available_ts.date()).days)
    freshness = "UNAVAILABLE" if filing_age is None else ("STALE" if filing_age > STALE_FILING_DAYS else "CURRENT_FOR_DECISION_TIME")

    domain = str(latest.get("domain") or "UNKNOWN")
    financial_domain = any(token in domain.upper() for token in ("BANK", "FINANC", "INSUR", "NBFC"))
    sector_profile = "FINANCIAL_DOMAIN_CONSERVATIVE" if financial_domain else "GENERAL_CORPORATE"

    independent_validation = None
    path = sources["independent_validation"]
    if path is not None:
        try:
            independent_validation = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            independent_validation = None

    status = "READY" if scored["score_component_coverage"] >= MIN_READY_SCORE_COVERAGE else "LIMITED_COVERAGE"
    return {
        "schema": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "status": status,
        "available": True,
        "symbol": _symbol(symbol),
        "decision_timestamp": cutoff.isoformat(),
        "reporting_basis": basis,
        "domain": domain,
        "sector_profile": sector_profile,
        "quarter_end": latest.get("quarter_end"),
        "effective_availability_ts": latest.get("availability_ts"),
        "filing_age_days_at_decision": filing_age,
        "filing_freshness": freshness,
        "fundamental_score": scored["score"],
        "fundamental_label": scored["label"],
        "score_component_coverage": scored["score_component_coverage"],
        "canonical_core_feature_coverage": _round(len(core_present) / len(CORE_FEATURES), 4),
        "extended_feature_coverage": _round(len(extended_present) / len(EXTENDED_FEATURES), 4),
        "present_core_features": core_present,
        "missing_core_features": missing_core,
        "present_extended_features": extended_present,
        "missing_extended_features": missing_extended,
        "growth": scored["growth"],
        "profitability": scored["ttm"],
        "cash_flow": scored["cash_flow"],
        "balance_sheet": scored["balance_sheet"],
        "valuation": scored["valuation"],
        "risk_event": {
            "available": risk is not None,
            "event_profile": (risk or {}).get("event_profile"),
            "deterioration_evidence_count": (risk or {}).get("deterioration_evidence_count"),
            "improvement_evidence_count": (risk or {}).get("improvement_evidence_count"),
            "strong_deterioration_transition": bool((risk or {}).get("strong_deterioration_transition")),
            "strong_improvement_transition": bool((risk or {}).get("strong_improvement_transition")),
        },
        "score_components": scored["components"],
        "independent_validation": {
            "available": independent_validation is not None,
            "decision": (independent_validation or {}).get("decision"),
            "promotion_authorized": bool((independent_validation or {}).get("promotion_authorized", False)),
        },
        "coverage_explanation": (
            "Fundamental score uses only point-in-time evidence available by the active analysis timestamp. "
            "Missing ROE/ROCE/ROIC/FCF/working-capital/peer-valuation fields remain explicitly unavailable until supported by the official canonical mapping."
        ),
        "promotion_allowed": False,
        "production_action_changed": False,
        "production_rank_changed": False,
        "point_in_time_safe": True,
        "sources": {k: str(v) if v else None for k, v in sources.items()},
    }


def point_in_time_leakage_audit(
    repo_root: Path,
    symbol: str,
    decision_timestamps: Iterable[Any],
    latest_price: float | None = None,
) -> dict[str, Any]:
    results = []
    previous_availability = None
    failures = []
    for value in decision_timestamps:
        cutoff = _cutoff(value)
        result = analyze(repo_root, symbol, decision_timestamp=cutoff, latest_price=latest_price)
        available = _dt(result.get("effective_availability_ts"))
        if available is not None and available > cutoff:
            failures.append({
                "decision_timestamp": cutoff.isoformat(),
                "effective_availability_ts": available.isoformat(),
                "reason": "FUTURE_FILING_LEAKAGE",
            })
        if previous_availability is not None and available is not None and available < previous_availability:
            failures.append({
                "decision_timestamp": cutoff.isoformat(),
                "effective_availability_ts": available.isoformat(),
                "reason": "NON_MONOTONIC_PIT_SELECTION",
            })
        if available is not None:
            previous_availability = available
        results.append({
            "decision_timestamp": cutoff.isoformat(),
            "selected_availability_ts": result.get("effective_availability_ts"),
            "quarter_end": result.get("quarter_end"),
            "status": result.get("status"),
        })
    return {
        "status": "PASS" if not failures else "FAIL",
        "checks": len(results),
        "failures": failures,
        "selections": results,
    }
'''

path = root / "stock_app" / "fundamental_v3.py"
path.write_text(module, encoding="utf-8")

phase = root / "phase5"
phase.mkdir(parents=True, exist_ok=True)
(phase / "fundamental_intelligence_v3_policy.json").write_text(
    """{
  "schema": "SRE_PHASE5_FUNDAMENTAL_INTELLIGENCE_V3_POLICY",
  "release": "0.11.0-phase5-fundamental-v3",
  "authority": "SHADOW_ONLY",
  "point_in_time_required": true,
  "canonical_source": "official Phase 2A XBRL/PIT feature panel and event profiles",
  "production_recommendation_authority_changed": false,
  "production_rank_authority_changed": false,
  "missing_data_policy": "Never zero-fill or invent unsupported fundamentals. Explicitly expose missing core and extended features.",
  "score_policy": "Fundamental V3 score is explanatory/shadow evidence only until independent validation and later combined-prediction promotion gates pass.",
  "extended_features_requested": ["ROE","ROCE","ROIC","FREE_CASH_FLOW","working capital","peer valuation"],
  "extended_feature_rule": "Show unavailable until the official canonical mapping supports the metric without leakage or semantic ambiguity.",
  "ui_cleanup_bundled": [
    "Distinguish frozen-engine historical observations from Technical V2 regime-matched analogues",
    "Clarify technical-only and fundamental-coverage-required labels without changing raw model state",
    "Rename Technical V2 evidence coverage to score-component coverage and show external-context coverage separately",
    "Render downside as a negative price-risk direction instead of a positive-looking percentage"
  ]
}
""",
    encoding="utf-8",
)

assert "SRE_FUNDAMENTAL_INTELLIGENCE_V3" in path.read_text(encoding="utf-8")
assert "promotion_allowed" in path.read_text(encoding="utf-8")
print("Phase 5 Fundamental Intelligence V3 core written")
