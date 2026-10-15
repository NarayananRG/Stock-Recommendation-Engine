from pathlib import Path
import os
import unittest

ROOT=Path(os.environ["SRE_ENGINE_ROOT"])

class PresentationStatusTests(unittest.TestCase):
    def setUp(self):
        self.api=(ROOT/"modern_ui"/"api.py").read_text(encoding="utf-8")
        self.js=(ROOT/"modern_ui"/"frontend"/"app.js").read_text(encoding="utf-8")

    def test_release_and_canonical_status(self):
        self.assertIn('APP_VERSION = "0.14.10-recommendation-presentation-status-repair"',self.api)
        self.assertIn('"production_decision_status": production_decision_status',self.api)
        self.assertIn('"live_buy_count": live_buy_count',self.api)

    def test_capital_heading_is_dynamic(self):
        self.assertIn("Why other stocks were not allocated",self.js)
        self.assertIn("buys.length?'Why other stocks were not allocated':'Why no capital was deployed'",self.js)

    def test_rationale_is_deduplicated(self):
        self.assertIn("function capitalRationale(b)",self.js)
        self.assertIn("Revenue, PAT and EPS trends are improving.",self.js)
        self.assertIn("Confidence: ",self.js)
        self.assertIn("Technical: ",self.js)

    def test_overview_uses_canonical_truth(self):
        self.assertIn("function sre151DecisionStatus",self.js)
        self.assertIn("sre151ApplyOverviewStatus(data?.ui_state||{})",self.js)
        self.assertIn("BUY OPPORTUNITIES",self.js)
        self.assertIn("ANALYSIS COMPLETE",self.js)

    def test_policy_presentation_only(self):
        policy=(ROOT/"phase7"/"recommendation_presentation_status_01410.json").read_text(encoding="utf-8")
        self.assertIn('"recommendation_logic_changed": false',policy)
        self.assertIn('"model_or_threshold_changed": false',policy)
        self.assertIn('"allocation_policy_changed": false',policy)
        self.assertIn('"provider_policy_changed": false',policy)

if __name__=="__main__":
    unittest.main()
