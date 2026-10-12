from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

module = root / "stock_app" / "combined_prediction_v2.py"
s = module.read_text(encoding="utf-8")

if "def _component_interpretation(" not in s:
    anchor = "\n\ndef combine(\n"
    helper = r'''

def _component_interpretation(name: str, item: dict[str, Any]) -> dict[str, Any]:
    label = name.replace("_", " ").title()
    available = bool(item.get("available"))
    score = _num(item.get("score"))
    coverage = _num(item.get("coverage")) or 0.0
    if not available or score is None:
        return {
            "component": name,
            "label": label,
            "available": False,
            "stance": "UNAVAILABLE",
            "summary": f"{label} evidence is unavailable for this run.",
            "score": None,
            "coverage": 0.0,
        }
    if score >= 68:
        stance = "SUPPORTIVE"
    elif score <= 38:
        stance = "CAUTIONARY"
    else:
        stance = "MIXED"
    if coverage < 0.35:
        coverage_label = "limited"
    elif coverage < 0.70:
        coverage_label = "partial"
    else:
        coverage_label = "broad"
    return {
        "component": name,
        "label": label,
        "available": True,
        "stance": stance,
        "summary": f"{label} is {stance.lower()} with {coverage_label} evidence coverage.",
        "score": round(score, 4),
        "coverage": round(_clamp(coverage, 0.0, 1.0), 4),
    }


def _explainability_pack(
    components: dict[str, dict[str, Any]],
    *,
    combined_score: float | None,
    confidence: float,
    agreement: float,
    coverage: float,
    analysis_data_current: bool | None,
) -> dict[str, Any]:
    interpreted = [_component_interpretation(name, components[name]) for name in WEIGHTS]
    supportive = [x for x in interpreted if x["stance"] == "SUPPORTIVE"]
    cautionary = [x for x in interpreted if x["stance"] == "CAUTIONARY"]
    unavailable = [x for x in interpreted if not x["available"]]
    warnings: list[str] = []
    if coverage < MIN_READY_COVERAGE:
        warnings.append("LIMITED_COMBINED_EVIDENCE_COVERAGE")
    if agreement < 0.55:
        warnings.append("COMPONENT_DISAGREEMENT_HIGH")
    if confidence < 0.45:
        warnings.append("LOW_SHADOW_CONFIDENCE")
    if analysis_data_current is False:
        warnings.append("MARKET_DATA_NOT_CURRENT")
    if unavailable:
        warnings.append("SOME_COMPONENTS_UNAVAILABLE")
    if supportive and cautionary:
        consensus = "MIXED_EVIDENCE"
    elif supportive:
        consensus = "MOSTLY_SUPPORTIVE"
    elif cautionary:
        consensus = "MOSTLY_CAUTIONARY"
    else:
        consensus = "NO_CLEAR_DIRECTION"
    headline = "Combined V2 is shadow-only explanatory evidence."
    if combined_score is not None:
        headline = f"Combined V2 shadow score {round(combined_score, 1)}/100 with {consensus.lower().replace('_', ' ')}."
    return {
        "schema": "SRE_COMBINED_V2_EXPLAINABILITY_V1",
        "authority": AUTHORITY,
        "consensus": consensus,
        "headline": headline,
        "component_summaries": interpreted,
        "supportive_components": [x["component"] for x in supportive],
        "cautionary_components": [x["component"] for x in cautionary],
        "unavailable_components": [x["component"] for x in unavailable],
        "warnings": warnings,
        "target_policy": "Desired return is excluded from Combined V2 scoring and confidence.",
        "production_authority_changed": False,
        "ranking_authority_changed": False,
        "promotion_allowed": False,
    }
'''
    s = s.replace(anchor, helper + anchor, 1)

old_no_evidence = '''            "production_rank_changed": False,
        }
'''
new_no_evidence = '''            "production_rank_changed": False,
            "explainability": _explainability_pack(
                components,
                combined_score=None,
                confidence=0.0,
                agreement=0.0,
                coverage=0.0,
                analysis_data_current=analysis_data_current,
            ),
        }
'''
if old_no_evidence not in s:
    raise RuntimeError("Combined V2 no-evidence return contract missing")
s = s.replace(old_no_evidence, new_no_evidence, 1)

old_ready = '''        "notes": (
            "Combined Prediction V2 is explanatory shadow evidence only. "
            "The user desired-return target is deliberately excluded from the score."
        ),
    }
'''
new_ready = '''        "notes": (
            "Combined Prediction V2 is explanatory shadow evidence only. "
            "The user desired-return target is deliberately excluded from the score."
        ),
        "explainability": _explainability_pack(
            components,
            combined_score=score,
            confidence=confidence,
            agreement=agreement,
            coverage=coverage,
            analysis_data_current=analysis_data_current,
        ),
    }
'''
if old_ready not in s:
    raise RuntimeError("Combined V2 ready return contract missing")
s = s.replace(old_ready, new_ready, 1)

module.write_text(s, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")

if "combinedV2Explainability" not in t:
    old = """  $('#combinedV2Decision').textContent=(x.shadow_decision||'NO SIGNAL').replaceAll('_',' ');
  $('#combinedV2Reasons').textContent=(x.reason_codes||[]).length?(x.reason_codes||[]).map(function(v){return String(v).replaceAll('_',' ');}).join(' · '):'Target never enters the Combined V2 score.';
}
"""
    new = """  $('#combinedV2Decision').textContent=(x.shadow_decision||'NO SIGNAL').replaceAll('_',' ');
  const exp=x.explainability||{};
  const warnings=(exp.warnings||[]).map(function(v){return String(v).replaceAll('_',' ');});
  const reasons=(x.reason_codes||[]).map(function(v){return String(v).replaceAll('_',' ');});
  $('#combinedV2Reasons').innerHTML='<span class=\"combinedV2Explainability\">'+escapeHtml(exp.headline||'Target never enters the Combined V2 score.')+'</span>'+(warnings.length?'<span>'+escapeHtml('Warnings: '+warnings.join(' · '))+'</span>':'')+(reasons.length?'<span>'+escapeHtml('Signals: '+reasons.join(' · '))+'</span>':'');
}
"""
    if old not in t:
        raise RuntimeError("Combined V2 UI reason renderer contract missing")
    t = t.replace(old, new, 1)
    js.write_text(t, encoding="utf-8")

css = root / "modern_ui" / "frontend" / "styles.css"
c = css.read_text(encoding="utf-8")
if ".combinedV2Explainability" not in c:
    c += "\n.combinedV2Explainability{font-weight:750;color:var(--text)}#combinedV2Reasons{display:grid;gap:4px;line-height:1.35}\n"
    css.write_text(c, encoding="utf-8")

phase = root / "phase7"
phase.mkdir(parents=True, exist_ok=True)
(phase / "combined_v2_explainability_policy.json").write_text(
    """{
  "schema": "SRE_PHASE7_COMBINED_V2_EXPLAINABILITY_POLICY",
  "authority": "SHADOW_ONLY",
  "production_recommendation_authority_changed": false,
  "production_rank_authority_changed": false,
  "active_model_changed": false,
  "desired_return_target_used_in_score": false,
  "automatic_yfinance_fallback": false,
  "purpose": "Improve Combined V2 interpretation, disagreement visibility, and evidence coverage disclosure without promoting shadow evidence."
}
""",
    encoding="utf-8",
)

check = module.read_text(encoding="utf-8")
assert "SRE_COMBINED_V2_EXPLAINABILITY_V1" in check
assert '"target_used_in_score": False' in check
assert '"production_rank_changed": False' in check
print("Phase 7 Combined V2 explainability overlay applied")
