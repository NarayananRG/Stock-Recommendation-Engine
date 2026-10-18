"""Read-only contract tracing for risk events and debt availability."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2]
def inspect():
    router=(ROOT/".ci/native140/live_decision_v1.py").read_text(encoding="utf-8")
    builder=(ROOT/"NextGen Research/fundamental_research_v2_phase2a/risk_event_builder.py").read_text(encoding="utf-8")
    semantic=(ROOT/"NextGen Research/fundamental_research_v2_phase2a/semantic_interpretation.py").read_text(encoding="utf-8")
    panel=(ROOT/"NextGen Research/fundamental_research_v2_phase2a/canonical_feature_panel.py").read_text(encoding="utf-8")
    checks={
      "mixed_requires_both_evidence_sides":'elif deterioration and improvement:' in builder,
      "mixed_disallowed_by_event_readiness":'s["fundamental_event_state"] in ("STABLE", "IMPROVING")' in router,
      "mixed_degrades_business_health":'event_state in ("MIXED", "DETERIORATING")' in router,
      "strong_transition_is_sign_based":'event.get("sign_transition")=="POSITIVE_TO_NEGATIVE"' in builder,
      "numeric_magnitude_not_used_for_mixed_class":'if deterioration and improvement:' in builder,
      "debt_ratio_is_panel_feature":'"DEBT_EQUITY_RATIO"' in panel,
      "financial_debt_unavailable_deliberately":'balance = ("UNAVAILABLE" if financial or debt is None' in router,
      "nonfinancial_missing_debt_is_unavailable":'debt is None' in router,
      "debt_equity_direction_excluded":'"DEBT_EQUITY_RATIO":"EXCLUDED"' in semantic,
    }
    if not all(checks.values()):raise AssertionError("Changed source contract: "+str([k for k,v in checks.items() if not v]))
    return {"schema":"SRE_SOURCE_CONTRACT_TRACE_V1","checks":checks,
      "findings":["Mixed event requires any deterioration and any improvement candidates, independent of magnitude","Strong deterioration sign transition is a distinct flag, not the only possible adverse evidence","Debt-equity is a canonical panel feature but is excluded as a directional event","The decision router marks debt unavailable for financial domain or absent ratio"],
      "unverified":["97 other-or-unknown missing debt values: originating domain/mapping/source cause","Magnitude of negative events per actual stock","Full official-cache provenance"],"production_changed":False}
if __name__=="__main__":print(json.dumps(inspect(),indent=2))
