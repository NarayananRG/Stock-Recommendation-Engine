from __future__ import annotations

import unittest

from technical_evidence_audit import audit_technical_evidence


def _snapshot(signal=0.25):
    return {
        "run": {"market_session": "2026-10-16"},
        "candidates": [
            {
                "symbol": "TEST",
                "live_decision": {
                    "evidence": {
                        "technical": {
                            "schema": "SRE_TECHNICAL_INTELLIGENCE_V2",
                            "status": "READY",
                            "as_of_session": "2026-10-16",
                            "bars": 220,
                            "technical_score": 55.0,
                            "evidence_coverage": 1.0,
                            "score_components": {"trend": {"signal": signal, "weight": 1.0}},
                            "point_in_time_safe": True,
                        }
                    }
                },
            }
        ],
    }


class TechnicalEvidenceAuditTests(unittest.TestCase):
    def test_accepts_complete_finite_evidence(self):
        self.assertEqual(audit_technical_evidence(_snapshot()), [])

    def test_rejects_boolean_numeric_signal(self):
        self.assertIn("TEST: invalid trend signal", audit_technical_evidence(_snapshot(True)))

    def test_rejects_session_mismatch_and_nonfinite(self):
        value = _snapshot(float("nan"))
        value["candidates"][0]["live_decision"]["evidence"]["technical"]["as_of_session"] = "2026-10-15"
        violations = audit_technical_evidence(value)
        self.assertTrue(any("session" in item for item in violations))
        self.assertTrue(any("non-finite" in item for item in violations))


if __name__ == "__main__":
    unittest.main()
