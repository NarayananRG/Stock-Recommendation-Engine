from pathlib import Path
import os
import sys
import unittest

ROOT = Path(os.environ["SRE_ENGINE_ROOT"])
sys.path.insert(0, str(ROOT))

from modern_ui.api import ModernAppContext


class SessionTruthTests(unittest.TestCase):
    def test_newer_accepted_live_run_beats_stale_source_cache(self):
        ctx = ModernAppContext.__new__(ModernAppContext)
        ctx.data_source_status = lambda: {
            "mode": "REAL_OFFICIAL_DATA",
            "active": {"latest_session": "2026-10-09"},
        }
        ctx.active_prediction_run = lambda: {
            "run": {
                "run_id": "RUN14",
                "market_session": "2026-10-14",
                "production_authority": "LIVE_DECISION_V1",
                "lane_counts": {"watch": 109, "avoid": 27, "no_opportunity": 64},
            },
            "candidates": [{} for _ in range(200)],
        }
        ctx._read_daily_state = lambda: {
            "last_successful_run": {
                "run_id": "RUN14",
                "market_session": "2026-10-14",
                "provenance": {"latest_official_session": "2026-10-14"},
            }
        }
        ctx.expected_market_session = lambda: {
            "current_calendar_date": "2026-10-14",
            "expected_market_session": "2026-10-14",
        }
        truth = ctx.canonical_ui_state()
        self.assertEqual(truth["latest_official_session"], "2026-10-14")
        self.assertEqual(truth["source_reported_latest_session"], "2026-10-09")
        self.assertEqual(truth["active_analysis_session"], "2026-10-14")
        self.assertEqual(truth["active_run_id"], "RUN14")
        self.assertEqual(truth["data_freshness"], "CURRENT")
        self.assertTrue(truth["analysis_complete"])
        self.assertEqual(truth["lane_counts"]["watch"], 109)

    def test_newer_official_source_marks_old_run_stale(self):
        ctx = ModernAppContext.__new__(ModernAppContext)
        ctx.data_source_status = lambda: {
            "mode": "REAL_OFFICIAL_DATA",
            "active": {"latest_session": "2026-10-15"},
        }
        ctx.active_prediction_run = lambda: {
            "run": {"run_id": "RUN14", "market_session": "2026-10-14", "lane_counts": {}},
            "candidates": [],
        }
        ctx._read_daily_state = lambda: {}
        ctx.expected_market_session = lambda: {
            "current_calendar_date": "2026-10-15",
            "expected_market_session": "2026-10-15",
        }
        truth = ctx.canonical_ui_state()
        self.assertEqual(truth["latest_official_session"], "2026-10-15")
        self.assertEqual(truth["active_analysis_session"], "2026-10-14")
        self.assertTrue(truth["stale_active_run"])


class UxContractTests(unittest.TestCase):
    def setUp(self):
        self.js = (ROOT / "modern_ui/frontend/app.js").read_text(encoding="utf-8")
        self.html = (ROOT / "modern_ui/frontend/index.html").read_text(encoding="utf-8")
        self.css = (ROOT / "modern_ui/frontend/styles.css").read_text(encoding="utf-8")
        self.api = (ROOT / "modern_ui/api.py").read_text(encoding="utf-8")

    def test_overview_no_long_document_injection(self):
        self.assertNotIn("${liveEvidenceHtml(item.live_decision||item)}", self.js)
        self.assertIn("Stocks to review", self.html)
        self.assertIn("repairOverviewUx", self.js)
        self.assertIn("ANALYSIS COMPLETE", self.js)
        self.assertIn("stocks remain on WATCH", self.js)

    def test_human_readable_reasons_primary(self):
        self.assertIn("Business / earnings evidence is incomplete", self.js)
        self.assertIn("Historical PIT valuation comparison is unavailable", self.js)
        self.assertIn("return code?humanReason(code)", self.js)
        self.assertIn("Diagnostics / audit", self.js)

    def test_stock_intelligence_navigation_is_bound(self):
        self.assertIn("data-open-stock-intelligence", self.js)
        self.assertIn("openStock(symbol)", self.js)
        self.assertIn("Browse stocks ->", self.js)

    def test_drawer_layout_is_summary_first(self):
        for token in (
            "decision-summary-grid",
            "Evidence snapshot",
            "Why this decision?",
            "What is missing?",
            "What would change the decision?",
            "diagnostic-details",
        ):
            self.assertIn(token, self.js)
        self.assertIn(".opportunity-detail-v2", self.css)
        self.assertIn("overflow-wrap:anywhere", self.css)

    def test_capital_blockers_use_unique_symbol_semantics(self):
        self.assertIn('summary["blocker_count_semantics"] = "UNIQUE_SYMBOLS"', self.api)
        self.assertIn("blocker_symbols", self.api)
        self.assertIn("Stocks affected", self.js)
        self.assertIn("one stock may appear under more than one reason", self.js)

    def test_consistency_endpoint_exists(self):
        self.assertIn('@app.get("/api/ui-consistency")', self.api)
        self.assertIn("overview_run_id", self.api)
        self.assertIn("opportunities_run_id", self.api)
        self.assertIn("capital_run_id", self.api)
        self.assertIn("today_run_id", self.api)

    def test_existing_full_universe_opportunity_contract_preserved(self):
        self.assertIn("/api/opportunities?limit=200", self.js)
        self.assertIn("state.opportunityItems=d.items||[]", self.js)
        for label in ("Momentum BUY", "Recovery BUY", "Both", "Watch", "Avoid", "No Opportunity", "Executable"):
            self.assertIn(label, self.html)


if __name__ == "__main__":
    unittest.main()
