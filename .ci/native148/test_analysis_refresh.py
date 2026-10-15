from pathlib import Path
import os
import sys
import unittest

ROOT=Path(os.environ["SRE_ENGINE_ROOT"])
sys.path.insert(0,str(ROOT))

class RepairTests(unittest.TestCase):
    def setUp(self):
        self.api=(ROOT/"modern_ui"/"api.py").read_text(encoding="utf-8")
        self.js=(ROOT/"modern_ui"/"frontend"/"app.js").read_text(encoding="utf-8")

    def test_status_restores_official_diagnostics(self):
        for token in (
            '"current_calendar_date": gate.get("current_calendar_date")',
            '"expected_market_session": gate.get("expected_market_session")',
            '"refresh_label": refresh_label',
            '"source_detail": source_detail',
        ):
            self.assertIn(token,self.api)

    def test_stale_analysis_is_not_green_ready(self):
        self.assertIn('run_status = "ANALYSIS REFRESH REQUIRED"',self.api)
        self.assertIn("analysisStale",self.js)
        self.assertIn("analysis-refresh-hint",self.js)

    def test_previous_recommendations_are_labeled_stale(self):
        self.assertIn("'previous '",self.js)
        self.assertIn('"recommendation_session": session_state.get("analysis_session")',self.api)

    def test_provider_policy_unchanged(self):
        self.assertIn('"automatic_yfinance_fallback": False',self.api)

if __name__=="__main__":
    unittest.main()
