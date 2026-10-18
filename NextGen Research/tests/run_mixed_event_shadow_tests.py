from __future__ import annotations

import importlib.util
from datetime import date
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("mixed_shadow", ROOT / "scripts" / "evaluate_mixed_event_shadow.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def fundamental(*, strong=False, freshness="CURRENT_FOR_DECISION_TIME", positive=0.7, negative=-0.2):
    return {
        "risk_event": {"event_profile": "MIXED_DIRECTIONAL", "strong_deterioration_transition": strong},
        "filing_freshness": freshness,
        "point_in_time_safe": True,
        "score_components": {
            "earnings": {"signal": positive, "weight": 0.6},
            "cash_flow": {"signal": negative, "weight": 0.4},
        },
    }


def run_tests():
    assert MODULE.classify_mixed_event(fundamental())["classification"] == "MIXED_POSITIVE_BALANCE"
    assert MODULE.classify_mixed_event(fundamental(strong=True))["classification"] == "MIXED_RISK_BLOCKED"
    assert MODULE.classify_mixed_event(fundamental(freshness="STALE"))["classification"] == "MIXED_RISK_BLOCKED"
    payload = {
        "run": {"run_id": "r1", "market_session": "2026-10-16"},
        "candidates": [{"symbol": "TEST", "rank": 1, "live_decision": {"final_action": "WATCH", "evidence": {"fundamental": fundamental()}}}],
    }

    class MemoryPath:
        name = "one.json"

        def read_text(self, encoding="utf-8"):
            return json.dumps(payload)

        def __lt__(self, other):
            return self.name < other.name

    result = MODULE.evaluate_snapshots([MemoryPath()], date(2026, 10, 18))
    assert result["production_action_changes"] == 0
    assert result["production_rank_changes"] == 0
    assert result["historical_validation"]["matured_out_of_sample_cohorts"] == 0
    assert result["historical_validation"]["outcome_quality_comparison_available"] is False
    assert result["historical_validation"]["forward_outcome_evidence_supplied"] is False
    assert "No independently verified" in result["promotion_blocker"]
    # Elapsed weekdays do not prove that any 20-session outcome is available.
    class LaterSession(MemoryPath):
        name = "two.json"
        def read_text(self, encoding="utf-8"):
            later = json.loads(super().read_text(encoding=encoding))
            later["run"]["market_session"] = "2027-02-26"
            later["run"]["run_id"] = "r2"
            return json.dumps(later)
    long_calendar = MODULE.evaluate_snapshots([MemoryPath(), LaterSession()], date(2027, 3, 1))
    assert long_calendar["historical_validation"]["calendar_weekdays_elapsed_upper_bound"] > 20
    assert long_calendar["historical_validation"]["matured_out_of_sample_cohorts"] == 0
    assert long_calendar["historical_validation"]["outcome_quality_comparison_available"] is False
    malformed = fundamental(strong="False")
    assert MODULE.classify_mixed_event(malformed)["classification"] == "MIXED_POSITIVE_BALANCE"
    assert MODULE.classify_mixed_event(malformed)["strong_deterioration_transition"] is False
    malformed["structural_deterioration"] = "False"
    assert MODULE.classify_mixed_event(malformed)["classification"] == "MIXED_POSITIVE_BALANCE"
    assert result["promotion_allowed"] is False
    print("mixed-event shadow tests: PASS")


if __name__ == "__main__":
    run_tests()
