import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.current_universe_recovery import (  # noqa: E402
    acquisition_gap,
    recovery_summary,
    symbols_from_live_snapshot,
)


def event(symbol, event_id):
    return {
        "symbol": symbol,
        "event_id": event_id,
        "quarter_end": "2026-06-30",
        "submission_type": "ORIGINAL",
        "reporting_basis": "CONSOLIDATED",
        "publication_ts": "2026-07-20T10:00:00+05:30",
        "availability_ts": "2026-07-20T10:00:00+05:30",
        "source_exchange": "NSE",
    }


class CurrentUniverseRecoveryTests(unittest.TestCase):
    def test_uses_actual_snapshot_universe(self):
        snapshot = {"candidates": [{"symbol": "AAA"}, {"symbol": "M&M"}]}
        self.assertEqual(symbols_from_live_snapshot(snapshot), ["AAA", "M&M"])

    def test_rejects_duplicate_snapshot_symbols(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            symbols_from_live_snapshot({"candidates": [{"symbol": "AAA"}, {"symbol": "aaa"}]})

    def test_unverified_events_do_not_count_as_official_coverage(self):
        valid = event("AAA", "a")
        missing_source = dict(event("BBB", "b"), source_exchange=None)
        missing_timestamp = dict(event("CCC", "c"), availability_ts=None)
        self.assertEqual(acquisition_gap(["AAA", "BBB", "CCC"], [valid, missing_source, missing_timestamp]), ["BBB", "CCC"])
        report = recovery_summary(symbols=["AAA", "BBB", "CCC"], existing=[valid, missing_source], recovered=[missing_timestamp])
        self.assertEqual(report["covered_before"], 1)
        self.assertEqual(report["covered_after"], 1)
        self.assertEqual(report["missing_after"], ["BBB", "CCC"])

    def test_rejects_non_dict_event_from_coverage(self):
        invalid = None
        self.assertEqual(acquisition_gap(["AAA", "BBB"], [event("AAA", "a"), invalid]), ["BBB"])

    def test_rejects_unsupported_source_from_coverage(self):
        invalid = dict(event("BBB", "b"), source_exchange="YFINANCE")
        self.assertEqual(acquisition_gap(["AAA", "BBB"], [event("AAA", "a"), invalid]), ["BBB"])

    def test_rejects_missing_quarter_from_coverage(self):
        invalid = dict(event("BBB", "b"), quarter_end=None)
        self.assertEqual(acquisition_gap(["AAA", "BBB"], [event("AAA", "a"), invalid]), ["BBB"])

    def test_rejects_bad_quarter_from_coverage(self):
        invalid = dict(event("BBB", "b"), quarter_end="2026-99-99")
        self.assertEqual(acquisition_gap(["AAA", "BBB"], [event("AAA", "a"), invalid]), ["BBB"])

    def test_rejects_invalid_basis_from_coverage(self):
        invalid = dict(event("BBB", "b"), reporting_basis="UNKNOWN")
        self.assertEqual(acquisition_gap(["AAA", "BBB"], [event("AAA", "a"), invalid]), ["BBB"])

    def test_rejects_invalid_submission_from_coverage(self):
        invalid = dict(event("BBB", "b"), submission_type="DRAFT")
        self.assertEqual(acquisition_gap(["AAA", "BBB"], [event("AAA", "a"), invalid]), ["BBB"])

    def test_rejects_naive_publication_from_coverage(self):
        invalid = dict(event("BBB", "b"), publication_ts="2026-07-20T10:00:00")
        self.assertEqual(acquisition_gap(["AAA", "BBB"], [event("AAA", "a"), invalid]), ["BBB"])

    def test_rejects_invalid_availability_from_coverage(self):
        invalid = dict(event("BBB", "b"), availability_ts="not-a-date")
        self.assertEqual(acquisition_gap(["AAA", "BBB"], [event("AAA", "a"), invalid]), ["BBB"])

    def test_rejects_availability_before_publication_from_coverage(self):
        invalid = dict(event("BBB", "b"), availability_ts="2026-07-19T10:00:00+05:30")
        self.assertEqual(acquisition_gap(["AAA", "BBB"], [event("AAA", "a"), invalid]), ["BBB"])

    def test_rejects_empty_symbol_from_coverage(self):
        invalid = dict(event("BBB", "b"), symbol="")
        self.assertEqual(acquisition_gap(["AAA", "BBB"], [event("AAA", "a"), invalid]), ["BBB"])

    def test_reports_incremental_official_recovery(self):
        before = [event("AAA", "a")]
        recovered = [event("BBB", "b")]
        self.assertEqual(acquisition_gap(["AAA", "BBB"], before), ["BBB"])
        report = recovery_summary(symbols=["AAA", "BBB"], existing=before, recovered=recovered)
        self.assertEqual(report["covered_before"], 1)
        self.assertEqual(report["covered_after"], 2)
        self.assertEqual(report["recovered_symbols"], ["BBB"])
        self.assertFalse(report["automatic_yfinance_fallback"])


if __name__ == "__main__":
    unittest.main()
