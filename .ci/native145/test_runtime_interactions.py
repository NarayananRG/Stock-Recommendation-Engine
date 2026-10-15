from pathlib import Path
import os
import unittest

ROOT = Path(os.environ["SRE_ENGINE_ROOT"])

class RuntimeInteractionBootstrapTests(unittest.TestCase):
    def setUp(self):
        front = ROOT / "modern_ui" / "frontend"
        self.index = (front / "index.html").read_text(encoding="utf-8")
        self.js = (front / "interaction-bootstrap.js").read_text(encoding="utf-8")
        self.api = (ROOT / "modern_ui" / "api.py").read_text(encoding="utf-8")
        self.live = (ROOT / "stock_app" / "live_decision_v1.py").read_text(encoding="utf-8")

    def test_release_identity(self):
        self.assertIn('APP_VERSION = "0.14.5-runtime-interaction-bootstrap"', self.api)
        self.assertIn('MODEL = "0.14.5-runtime-interaction-bootstrap"', self.live)

    def test_separate_script_is_loaded(self):
        self.assertIn('/assets/interaction-bootstrap.js', self.index)

    def test_browse_is_hard_enabled_and_direct_navigation_exists(self):
        self.assertIn("text.includes('browse stocks')", self.js)
        self.assertIn("el.disabled = false", self.js)
        self.assertIn("directPage(name)", self.js)
        self.assertIn("opportunitiesPage", self.js)

    def test_critical_actions_are_independent(self):
        for token in ("runMonitoring", "runPostCloseDaily", "buildCapitalPlan", "heroOpen"):
            self.assertIn(token, self.js)
        self.assertIn("fallbackPostClose", self.js)
        self.assertIn("document.addEventListener('click', handleClick, true)", self.js)

if __name__ == "__main__":
    unittest.main()
