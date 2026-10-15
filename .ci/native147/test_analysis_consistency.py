from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import unittest

ROOT = Path(os.environ["SRE_ENGINE_ROOT"])
sys.path.insert(0, str(ROOT))

from stock_app.session_consistency import analysis_session_state, reusable_analysis_session
from stock_app.phase81_validation import _canonical_journal_rows

class AnalysisSessionRepairTests(unittest.TestCase):
    def setUp(self):
        self.api=(ROOT/"modern_ui"/"api.py").read_text(encoding="utf-8")
        self.paper=(ROOT/"stock_app"/"phase81_validation.py").read_text(encoding="utf-8")
        self.css=(ROOT/"modern_ui"/"frontend"/"styles.css").read_text(encoding="utf-8")

    def test_stale_session_is_not_ready(self):
        state=analysis_session_state(data_ready=True,target_session="2026-10-15",analysis_session="2026-10-09")
        self.assertFalse(state["analysis_current"])
        self.assertEqual(state["status"],"ANALYSIS_REFRESH_REQUIRED")

    def test_current_session_is_ready(self):
        state=analysis_session_state(data_ready=True,target_session="2026-10-15",analysis_session="2026-10-15")
        self.assertTrue(state["analysis_current"])
        self.assertEqual(state["status"],"READY")
        self.assertTrue(reusable_analysis_session("2026-10-15","2026-10-15"))
        self.assertFalse(reusable_analysis_session("2026-10-09","2026-10-15"))

    def test_daily_success_requires_current_analysis(self):
        self.assertIn("and prior_session_state.get(\"analysis_current\")", self.api)
        self.assertIn("BLOCKED - ANALYSIS SESSION STALE", self.api)
        self.assertIn("actual_analysis_session", self.api)
        self.assertIn("active_analysis = run_session", self.api)

    def test_recommendation_count_uses_active_full_universe(self):
        self.assertIn('"recommendation_scope": "ACTIVE_LIVE_UNIVERSE"', self.api)
        self.assertIn('"recommendation_count": len(rows)', self.api)
        self.assertIn("rows = self.latest_prediction_rows(limit=200)", self.api)

    def test_daily_journal_is_one_event_per_session(self):
        self.assertIn('market_session=? and event_type in (\'DAILY_DECISION\',\'SIGNAL_GENERATED\')', self.paper)
        self.assertNotIn('market_session=? and production_run_id is ? and event_type in (\'DAILY_DECISION\',\'SIGNAL_GENERATED\')', self.paper)
        self.assertIn('f"{portfolio_id}|{market_session}|{event_type}"', self.paper)

    def test_legacy_duplicate_rows_are_hidden(self):
        rows=[
            {"market_session":"2026-10-14","event_type":"DAILY_DECISION","created_at":"2026-10-14T18:00:00","event_id":"a"},
            {"market_session":"2026-10-14","event_type":"DAILY_DECISION","created_at":"2026-10-14T18:05:00","event_id":"b"},
            {"market_session":"2026-10-15","event_type":"DAILY_DECISION","created_at":"2026-10-15T18:00:00","event_id":"c"},
            {"market_session":"2026-10-15","event_type":"FILLED","created_at":"2026-10-15T18:01:00","event_id":"d"},
        ]
        result=_canonical_journal_rows(rows)
        daily=[x for x in result if x["event_type"]=="DAILY_DECISION"]
        self.assertEqual(len(daily),2)
        self.assertEqual({x["event_id"] for x in daily},{"a","c"})
        self.assertEqual(len(result),3)

    def test_modal_layout_is_readable(self):
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))!important", self.css)
        self.assertIn("word-break:normal", self.css)

if __name__=="__main__":
    unittest.main()
