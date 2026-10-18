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

    # Batch of 25 independently named coverage eligibility checks.
    def test_bundle25_missing_publication(self):
        candidate = dict(event('BBB','b'),publication_ts=None)
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_invalid_publication(self):
        candidate = dict(event('BBB','b'),publication_ts='invalid')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_naive_availability(self):
        candidate = dict(event('BBB','b'),availability_ts='2026-07-20T10:00:00')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_empty_availability(self):
        candidate = dict(event('BBB','b'),availability_ts='')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_wrong_exchange(self):
        candidate = dict(event('BBB','b'),source_exchange='OTHER')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_non_string_exchange(self):
        candidate = dict(event('BBB','b'),source_exchange=123)
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_invalid_basis_number(self):
        candidate = dict(event('BBB','b'),reporting_basis=99)
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_invalid_submission_number(self):
        candidate = dict(event('BBB','b'),submission_type=99)
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_missing_reporting_basis(self):
        candidate = dict(event('BBB','b'),reporting_basis=None)
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_missing_submission_type(self):
        candidate = dict(event('BBB','b'),submission_type=None)
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_invalid_quarter_text(self):
        candidate = dict(event('BBB','b'),quarter_end='tomorrow')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_impossible_leap_day(self):
        candidate = dict(event('BBB','b'),quarter_end='2025-02-29')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_invalid_date_type(self):
        candidate = dict(event('BBB','b'),quarter_end=20260630)
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_timestamp_missing_offset(self):
        candidate = dict(event('BBB','b'),publication_ts='2026-07-20T10:00:00')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_publication_after_availability_different_offset(self):
        candidate = dict(event('BBB','b'),publication_ts='2026-07-20T11:00:00+05:30',availability_ts='2026-07-20T04:00:00+00:00')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), ['BBB'])

    def test_bundle25_valid_bse(self):
        candidate = dict(event('BBB','b'),source_exchange='BSE')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), [])

    def test_bundle25_valid_revised(self):
        candidate = dict(event('BBB','b'),submission_type='REVISED')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), [])

    def test_bundle25_valid_standalone(self):
        candidate = dict(event('BBB','b'),reporting_basis='STANDALONE')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), [])

    def test_bundle25_valid_utc(self):
        candidate = dict(event('BBB','b'),publication_ts='2026-07-20T04:30:00Z',availability_ts='2026-07-20T04:30:00Z')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), [])

    def test_bundle25_valid_later_availability(self):
        candidate = dict(event('BBB','b'),availability_ts='2026-07-21T10:00:00+05:30')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), [])

    def test_bundle25_valid_lowercase_exchange(self):
        candidate = dict(event('BBB','b'),source_exchange='bse')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), [])

    def test_bundle25_valid_exchange_whitespace(self):
        candidate = dict(event('BBB','b'),source_exchange=' NSE ')
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), [])

    def test_bundle25_valid_symbol_alias(self):
        candidate = dict(event('MANDM','b'))
        self.assertEqual(acquisition_gap(['AAA', 'M&M'], [event('AAA','a'), candidate]), [])

    def test_bundle25_valid_symbol_case(self):
        candidate = dict(event('bbb','b'))
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate]), [])

    def test_bundle25_valid_duplicate_events(self):
        candidate = dict(event('BBB','b'))
        self.assertEqual(acquisition_gap(['AAA', 'BBB'], [event('AAA','a'), candidate, candidate]), [])

    def test_rejects_non_mapping_live_snapshot(self):
        for snapshot in (None, [], "invalid"):
            with self.subTest(snapshot=snapshot), self.assertRaisesRegex(ValueError, "LIVE_SNAPSHOT_INVALID"):
                symbols_from_live_snapshot(snapshot)

    def test_rejects_missing_or_nonstring_live_symbol(self):
        for symbol in (None, 42, "", "  "):
            with self.subTest(symbol=symbol), self.assertRaisesRegex(ValueError, "LIVE_SNAPSHOT_SYMBOL_REQUIRED"):
                symbols_from_live_snapshot({"candidates": [{"symbol": symbol}]})

    def test_source_summary_handles_malformed_recovery_event(self):
        report = recovery_summary(symbols=["AAA"], existing=[event("AAA", "a")], recovered=[None])
        self.assertEqual(report["recovered_event_source_counts"], {"INVALID_EVENT": 1})

    def test_invalid_existing_rows_do_not_crash_recovery(self):
        valid = event("AAA", "a")
        invalid = dict(event("BBB", "b"), quarter_end="20260630")
        report = recovery_summary(
            symbols=["AAA", "BBB"], existing=[valid, invalid, None], recovered=[]
        )
        self.assertEqual(report["covered_before"], 1)
        self.assertEqual(report["covered_after"], 1)
        self.assertEqual(report["missing_after"], ["BBB"])

    def test_compact_quarter_date_is_not_canonical(self):
        compact = dict(event("BBB", "b"), quarter_end="20260630")
        self.assertEqual(acquisition_gap(["BBB"], [compact]), ["BBB"])

    def test_numeric_filing_symbol_is_not_coverage(self):
        numeric = dict(event("BBB", "b"), symbol=123)
        self.assertEqual(acquisition_gap(["BBB"], [numeric]), ["BBB"])

    def test_canonical_revision_from_phase2a_counts_as_covered(self):
        revised = dict(event("BBB", "b"), submission_type="REVISION")
        self.assertEqual(acquisition_gap(["BBB"], [revised]), [])
        report = recovery_summary(symbols=["BBB"], existing=[], recovered=[revised])
        self.assertEqual(report["covered_after"], 1)
        self.assertEqual(report["recovered_symbols"], ["BBB"])

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
