from pathlib import Path
import os
import unittest

ROOT = Path(os.environ["SRE_ENGINE_ROOT"])

class RuntimeInteractionBootstrapTests(unittest.TestCase):
    def setUp(self):
        front = ROOT / "modern_ui" / "frontend"
        self.index = (front / "index.html").read_text(encoding="utf-8")
        self.app = (front / "app.js").read_text(encoding="utf-8")
        self.js = (front / "interaction-bootstrap.js").read_text(encoding="utf-8")
        self.api = (ROOT / "modern_ui" / "api.py").read_text(encoding="utf-8")
        self.live = (ROOT / "stock_app" / "live_decision_v1.py").read_text(encoding="utf-8")

    def test_release_identity(self):
        self.assertIn('APP_VERSION = "0.14.5-runtime-interaction-bootstrap"', self.api)
        self.assertIn('MODEL = "0.14.5-runtime-interaction-bootstrap"', self.live)

    def test_separate_script_is_loaded(self):
        self.assertIn('/assets/interaction-bootstrap.js', self.index)

    def test_navigation_bridge_matches_canonical_page_contract(self):
        self.assertIn("window.switchPage = function switchPage(name)", self.js)
        self.assertIn("window.setPage(name)", self.js)
        self.assertIn("`page-${name}`", self.js)
        self.assertIn("active-page", self.js)

    def test_bootstrap_cannot_starve_or_swallow_interactions(self):
        self.assertNotIn("MutationObserver", self.js)
        self.assertNotIn("stopImmediatePropagation", self.js)
        self.assertNotIn("addEventListener('click'", self.js)
        self.assertNotIn("data-browse-stocks", self.js)

    def test_zero_buy_hero_remains_enabled_after_dashboard_render(self):
        self.assertIn("e.id==='heroOpen'||e.dataset?.browseStocks==='true'", self.app)
        self.assertIn("e.disabled=false;e.removeAttribute('disabled')", self.app)

    def test_stock_intelligence_runtime_was_not_deleted_by_drawer_overlay(self):
        self.assertIn("async function openStock(symbol)", self.app)
        self.assertIn("function renderStock(d)", self.app)
        self.assertIn("/api/stocks/${encodeURIComponent(symbol)}?limit=5000", self.app)
        self.assertIn("modalClose();openStock(sym)", self.app)

if __name__ == "__main__":
    unittest.main()
