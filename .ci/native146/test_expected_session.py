from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path


ENGINE = Path(os.environ["SRE_ENGINE_ROOT"])
sys.path.insert(0, str(ENGINE))
from modern_ui.api import ModernAppContext  # noqa: E402


class ExpectedSessionTests(unittest.TestCase):
    def gate_for(self, result_status: str, *, latest: str = "2026-10-14", refresh_status: str = "ERROR"):
        ctx = object.__new__(ModernAppContext)
        ctx.expected_market_session = lambda: {
            "current_calendar_date": "2026-10-15",
            "expected_market_session": "2026-10-15",
            "basis": "TEST",
        }
        source = {"mode": "REAL_OFFICIAL_DATA", "active": {"latest_session": latest, "history_coverage": 1.0}}
        ctx.data_source_status = lambda: source
        ctx._refresh_official_first_market_data = lambda: {
            "status": refresh_status,
            "source": source,
            "refresh_result": {"status": result_status, "reason_detail": "deterministic diagnostic"},
            "automatic_yfinance_fallback": False,
        }
        return ModernAppContext._daily_data_gate(ctx)

    def test_pre_publication_window_uses_previous_completed_session(self):
        result = ModernAppContext.expected_market_session(datetime.fromisoformat("2026-10-15T17:17:00+05:30"))
        self.assertEqual(result["expected_market_session"], "2026-10-14")
        self.assertEqual(result["basis"], "TRADING_DAY_BEFORE_OFFICIAL_PUBLICATION_WINDOW")

    def test_after_publication_window_uses_today(self):
        result = ModernAppContext.expected_market_session(datetime.fromisoformat("2026-10-15T18:01:00+05:30"))
        self.assertEqual(result["expected_market_session"], "2026-10-15")
        self.assertEqual(result["basis"], "TRADING_DAY_AFTER_OFFICIAL_PUBLICATION_WINDOW")

    def test_weekend_uses_previous_completed_session(self):
        result = ModernAppContext.expected_market_session(datetime.fromisoformat("2026-10-17T20:00:00+05:30"))
        self.assertEqual(result["expected_market_session"], "2026-10-16")

    def test_official_exchange_holiday_uses_previous_session(self):
        result = ModernAppContext.expected_market_session(datetime.fromisoformat("2026-10-20T20:00:00+05:30"))
        self.assertEqual(result["expected_market_session"], "2026-10-19")
        self.assertEqual(result["calendar"], "NSE_OFFICIAL_HOLIDAY_TABLE_2026_V2")

    def test_no_automatic_yfinance_fallback(self):
        source = (ENGINE / "modern_ui" / "api.py").read_text(encoding="utf-8")
        self.assertIn('"automatic_yfinance_fallback": False', source)

    def test_ui_diagnostic_categories_are_distinct(self):
        cases = {
            "OFFICIAL_NOT_READY": "NOT YET PUBLISHED",
            "OFFICIAL_DOWNLOAD_FAILED": "DOWNLOAD ERROR",
            "OFFICIAL_SCHEMA_ERROR": "PARSE ERROR",
            "OFFICIAL_COVERAGE_FAILED": "COVERAGE ERROR",
            "LOCAL_VERIFICATION_FAILED": "LOCAL VERIFICATION ERROR",
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                gate = self.gate_for(status)
                self.assertEqual(gate["data_freshness"], expected)
                self.assertFalse(gate["ready"])

    def test_ready_requires_official_equity_and_index_verified_session(self):
        gate = self.gate_for("REFRESHED_AND_VERIFIED", latest="2026-10-15", refresh_status="PASS")
        self.assertEqual(gate["data_freshness"], "READY")
        self.assertTrue(gate["ready"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
