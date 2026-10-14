from pathlib import Path
import os
import unittest

ROOT = Path(os.environ["SRE_ENGINE_ROOT"])

class DecisionClarityUxTests(unittest.TestCase):
    def setUp(self):
        self.js = (ROOT / "modern_ui/frontend/app.js").read_text(encoding="utf-8")
        self.css = (ROOT / "modern_ui/frontend/styles.css").read_text(encoding="utf-8")
        self.api = (ROOT / "modern_ui/api.py").read_text(encoding="utf-8")
        self.live = (ROOT / "stock_app/live_decision_v1.py").read_text(encoding="utf-8")

    def test_release_identity(self):
        self.assertIn('APP_VERSION = "0.14.3-decision-clarity-ux"', self.api)
        self.assertIn('MODEL = "0.14.3-decision-clarity-ux"', self.live)

    def test_opportunity_table_explains_evidence_not_just_technical_state(self):
        self.assertIn("decisionEvidenceSummary", self.js)
        self.assertIn("domains reported", self.js)
        self.assertIn("decisionBasisText", self.js)
        self.assertIn("Thesis present; qualification incomplete", self.js)

    def test_decision_contract_makes_target_independence_explicit(self):
        self.assertIn("Desired return is planning context only", self.js)
        self.assertIn("Technical READY alone is not a BUY", self.js)
        self.assertIn("Your desired return affects planning context only", self.js)

    def test_analogue_count_semantics_explained(self):
        self.assertIn("Historical analogue pool means all eligible past comparison cases", self.js)
        self.assertIn("Matched analogues are the smaller subset", self.js)

    def test_capital_plan_does_not_force_recommendation_count(self):
        self.assertIn("does not force five stocks", self.js)
        self.assertIn("will not manufacture five recommendations", self.js)

    def test_clarity_styles_present(self):
        self.assertIn(".decision-guide", self.css)
        self.assertIn(".decision-contract-note", self.css)
        self.assertIn(".evidence-cell", self.css)

if __name__ == "__main__":
    unittest.main()
