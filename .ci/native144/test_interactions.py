from pathlib import Path
import os
import unittest

ROOT = Path(os.environ['SRE_ENGINE_ROOT'])

class InteractionHotfixTests(unittest.TestCase):
    def setUp(self):
        self.js=(ROOT/'modern_ui'/'frontend'/'app.js').read_text(encoding='utf-8')
        self.api=(ROOT/'modern_ui'/'api.py').read_text(encoding='utf-8')
        self.live=(ROOT/'stock_app'/'live_decision_v1.py').read_text(encoding='utf-8')

    def test_release_identity(self):
        self.assertIn('APP_VERSION = "0.14.4-interaction-hotfix"', self.api)
        self.assertIn('MODEL = "0.14.4-interaction-hotfix"', self.live)

    def test_browse_stocks_is_reenabled(self):
        self.assertIn("e.disabled=false", self.js)
        self.assertIn("e.removeAttribute('disabled')", self.js)
        self.assertIn("switchPage('opportunities')", self.js)

    def test_critical_actions_have_delegated_fallback(self):
        self.assertIn('function ui144RunAction(event)', self.js)
        for token in ("id==='runMonitoring'", "id==='runPostCloseDaily'", "id==='buildCapitalPlan'", "id==='heroOpen'"):
            self.assertIn(token, self.js)
        self.assertIn("document.addEventListener('click',ui144RunAction,true)", self.js)

if __name__ == '__main__':
    unittest.main()
