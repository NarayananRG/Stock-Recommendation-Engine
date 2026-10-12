from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

module = r'''from __future__ import annotations

import math
from statistics import pstdev
from typing import Any

SCHEMA_VERSION = "SRE_COMBINED_PREDICTION_V2"
AUTHORITY = "SHADOW_ONLY"
WEIGHTS = {
    "frozen_engine": 0.40,
    "technical_v2": 0.30,
    "fundamental_v3": 0.25,
    "market_context": 0.05,
}
MIN_READY_COVERAGE = 0.65


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _confidence_score(label: Any) -> float:
    text = str(label or "").upper()
    if "HIGH" in text:
        return 90.0
    if "MEDIUM" in text:
        return 65.0
    if "LOW" in text:
        return 35.0
    return 20.0


def _frozen_component(pred: dict[str, Any] | None) -> dict[str, Any]:
    pred = pred or {}
    er = _num(pred.get("expected_return"))
    pp = _num(pred.get("profit_probability"))
    if pp is not None and pp > 1.0:
        pp = pp / 100.0
    dr = _num(pred.get("downside_risk"))

    evidence = []
    if er is not None:
        # -25% => 0, 0% => 50, +25% => 100.
        evidence.append(("expected_return", _clamp(50.0 + er * 200.0), 0.45))
    if pp is not None:
        evidence.append(("profit_probability", _clamp(pp * 100.0), 0.35))
    if pred.get("confidence_label"):
        evidence.append(("confidence", _confidence_score(pred.get("confidence_label")), 0.20))

    if not evidence:
        return {"available": False, "score": None, "coverage": 0.0}

    total = sum(w for _, _, w in evidence)
    score = sum(v * w for _, v, w in evidence) / total
    return {
        "available": True,
        "score": round(score, 4),
        "coverage": round(total, 4),
        "expected_return": er,
        "profit_probability": pp,
        "downside_risk": dr,
        "confidence_label": pred.get("confidence_label"),
        "opportunity_status": pred.get("opportunity_status"),
        "sample_size": pred.get("sample_size"),
    }


def _technical_component(technical: dict[str, Any] | None) -> dict[str, Any]:
    technical = technical or {}
    score = _num(technical.get("technical_score"))
    coverage = _num(technical.get("evidence_coverage"))
    return {
        "available": score is not None,
        "score": None if score is None else round(_clamp(score), 4),
        "coverage": 0.0 if score is None else round(_clamp(coverage or 0.0, 0.0, 1.0), 4),
        "label": technical.get("technical_label"),
        "analogue_status": (technical.get("historical_analogues") or {}).get("status"),
        "analogue_sample_size": (technical.get("historical_analogues") or {}).get("sample_size"),
    }


def _fundamental_component(fundamental: dict[str, Any] | None) -> dict[str, Any]:
    fundamental = fundamental or {}
    score = _num(fundamental.get("fundamental_score"))
    coverage = _num(fundamental.get("score_component_coverage"))
    return {
        "available": bool(fundamental.get("available")) and score is not None,
        "score": None if score is None else round(_clamp(score), 4),
        "coverage": 0.0 if score is None else round(_clamp(coverage or 0.0, 0.0, 1.0), 4),
        "label": fundamental.get("fundamental_label"),
        "filing_freshness": fundamental.get("filing_freshness"),
        "point_in_time_safe": fundamental.get("point_in_time_safe"),
    }


def _market_component(technical: dict[str, Any] | None) -> dict[str, Any]:
    context = (technical or {}).get("market_context") or {}
    regime = str(context.get("nifty_regime") or "").upper()
    if not regime or regime == "UNAVAILABLE":
        return {"available": False, "score": None, "coverage": 0.0, "regime": regime or "UNAVAILABLE"}

    if "BULL" in regime:
        score = 70.0
    elif "BEAR" in regime:
        score = 30.0
    else:
        score = 50.0

    vix = context.get("india_vix") or {}
    if vix.get("available"):
        vix_regime = str(vix.get("regime") or "").upper()
        if "HIGH" in vix_regime or "ELEVATED" in vix_regime:
            score -= 8.0
        elif "LOW" in vix_regime:
            score += 5.0
    return {
        "available": True,
        "score": round(_clamp(score), 4),
        "coverage": 1.0,
        "regime": regime,
        "india_vix_available": bool(vix.get("available")),
    }


def combine(
    prediction: dict[str, Any] | None,
    technical_v2: dict[str, Any] | None,
    fundamental_v3: dict[str, Any] | None,
    *,
    analysis_data_current: bool | None = None,
) -> dict[str, Any]:
    components = {
        "frozen_engine": _frozen_component(prediction),
        "technical_v2": _technical_component(technical_v2),
        "fundamental_v3": _fundamental_component(fundamental_v3),
        "market_context": _market_component(technical_v2),
    }

    used = []
    available_weight = 0.0
    quality_weight = 0.0
    for name, weight in WEIGHTS.items():
        item = components[name]
        if not item["available"] or item["score"] is None:
            continue
        used.append((name, float(item["score"]), weight))
        available_weight += weight
        quality_weight += weight * float(item.get("coverage") or 0.0)

    if not used:
        return {
            "schema": SCHEMA_VERSION,
            "authority": AUTHORITY,
            "status": "NO_COMBINABLE_EVIDENCE",
            "available": False,
            "combined_score": None,
            "combined_label": "UNAVAILABLE",
            "shadow_decision": "NO_SIGNAL",
            "confidence": 0.0,
            "evidence_coverage": 0.0,
            "component_agreement": 0.0,
            "components": components,
            "target_used_in_score": False,
            "promotion_allowed": False,
            "production_action_changed": False,
            "production_rank_changed": False,
        }

    normalized_score = sum(score * weight for _, score, weight in used) / available_weight
    scores = [score for _, score, _ in used]
    dispersion = pstdev(scores) if len(scores) > 1 else 0.0
    agreement = _clamp(1.0 - dispersion / 45.0, 0.0, 1.0)
    coverage = _clamp(available_weight, 0.0, 1.0)
    evidence_quality = _clamp(quality_weight / max(available_weight, 1e-9), 0.0, 1.0)
    confidence = _clamp(coverage * (0.55 + 0.45 * agreement) * evidence_quality, 0.0, 1.0)

    # Freshness is a confidence governor, not a hidden directional score.
    if analysis_data_current is False:
        confidence *= 0.70

    score = round(_clamp(normalized_score), 4)
    confidence = round(confidence, 4)
    agreement = round(agreement, 4)
    coverage = round(coverage, 4)

    if coverage < MIN_READY_COVERAGE:
        label = "LIMITED_COVERAGE"
        decision = "WATCH"
    elif score >= 72.0 and confidence >= 0.60:
        label = "STRONG_POSITIVE"
        decision = "RESEARCH_BUY_CANDIDATE"
    elif score >= 58.0:
        label = "POSITIVE"
        decision = "WATCH_POSITIVE"
    elif score >= 42.0:
        label = "NEUTRAL"
        decision = "WATCH"
    elif score >= 28.0:
        label = "WEAK"
        decision = "WATCH_NEGATIVE"
    else:
        label = "DETERIORATING"
        decision = "RESEARCH_AVOID"

    ranked = sorted(
        (
            {"component": name, "score": round(component_score, 2), "weight": weight}
            for name, component_score, weight in used
        ),
        key=lambda x: (-x["weight"], -x["score"], x["component"]),
    )

    reasons = []
    for item in ranked:
        if item["score"] >= 65:
            reasons.append(f'{item["component"].upper()}_POSITIVE')
        elif item["score"] <= 35:
            reasons.append(f'{item["component"].upper()}_NEGATIVE')
    if analysis_data_current is False:
        reasons.append("MARKET_DATA_NOT_CURRENT")
    if components["fundamental_v3"]["available"] is False:
        reasons.append("FUNDAMENTAL_EVIDENCE_UNAVAILABLE")
    if components["technical_v2"]["available"] is False:
        reasons.append("TECHNICAL_EVIDENCE_UNAVAILABLE")

    return {
        "schema": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "status": "READY" if coverage >= MIN_READY_COVERAGE else "LIMITED_COVERAGE",
        "available": True,
        "combined_score": score,
        "combined_label": label,
        "shadow_decision": decision,
        "confidence": confidence,
        "evidence_coverage": coverage,
        "component_agreement": agreement,
        "evidence_quality": round(evidence_quality, 4),
        "components": components,
        "component_ranking": ranked,
        "reason_codes": reasons,
        "analysis_data_current": analysis_data_current,
        "target_used_in_score": False,
        "promotion_allowed": False,
        "production_action_changed": False,
        "production_rank_changed": False,
        "notes": (
            "Combined Prediction V2 is explanatory shadow evidence only. "
            "The user desired-return target is deliberately excluded from the score."
        ),
    }
'''

path = root / "stock_app" / "combined_prediction_v2.py"
path.write_text(module, encoding="utf-8")

phase = root / "phase6"
phase.mkdir(parents=True, exist_ok=True)
(phase / "combined_prediction_v2_policy.json").write_text(
    """{
  "schema": "SRE_PHASE6_COMBINED_PREDICTION_V2_POLICY",
  "release": "0.12.0-phase6-combined-prediction-v2",
  "authority": "SHADOW_ONLY",
  "components": {
    "frozen_engine": 0.40,
    "technical_v2": 0.30,
    "fundamental_v3": 0.25,
    "market_context": 0.05
  },
  "desired_return_target_used_in_score": false,
  "minimum_ready_coverage": 0.65,
  "promotion_allowed": false,
  "production_recommendation_authority_changed": false,
  "production_rank_authority_changed": false,
  "overview_policy": {
    "target_badges_require_explicit_user_target": true,
    "restored_target_must_be_labeled": true,
    "top_opportunity_requires_model_executable_buy": true,
    "watch_only_hero_label": "TOP WATCH CANDIDATE",
    "no_buy_hero_label": "NO ACTIONABLE OPPORTUNITY"
  },
  "market_data_policy": {
    "target_universe": "NIFTY 200",
    "official_first": true,
    "automatic_yfinance_fallback": false,
    "current_market_history_required": true
  }
}
""",
    encoding="utf-8",
)

assert "target_used_in_score" in path.read_text(encoding="utf-8")
assert 'AUTHORITY = "SHADOW_ONLY"' in path.read_text(encoding="utf-8")
print("Phase 6 Combined Prediction V2 core written")
