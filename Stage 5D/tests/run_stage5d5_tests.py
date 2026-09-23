"""Stage 5D.5 safety and orchestration tests; no network or live paper state."""
from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
import types
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "Stage 4A.3"))

from live_paper import SCHEMA_VERSION
from live_paper.admission import admission_status, available_slots
from live_paper.news_normalizer import normalize_article
from live_paper.news_provider import _publication, fetch_yfinance_news
from live_paper.nse_session_calendar import DEFAULT_CALENDAR_PATH, load_verified_calendar, verify_scheduled_session
from live_paper.paper_action import record_action, verify_paper_action_market_session
from live_paper.run_after_close import _build_candidates, _collect_news, _existing_run, _holding_observations, _initialize_runs, _run_with_clock, _snapshot, render_report, require_after_close, resolve_snapshot_input_cache, round_trip_market_csv_reads, verify_live_run_integrity
from stage5d.allocator import allocate_candidates
from stage5d.horizon import HorizonPreference
from stage5d.ledger import Stage5DLedger, canonical_json, payload_sha256
from stage5d.management_store import Stage5D3Manager
from stage5d.news_ml_overlay import Stage5D4Overlay
from stage5d.portfolio_state import PendingEntryReservation
from stage5d.source_contract import derive_signal_id, normalize_source_candidate
from stage5d.stage4a3_shadow_adapter import Stage4A3PredictionNotAvailable, Stage4A3ShadowAdapter
from stage5d.user_profile import InvestmentProfile

RESULTS = []


def check(name, condition):
    RESULTS.append((name, "PASS" if condition else "FAIL"))
    if not condition:
        raise AssertionError(name)


def raises(error, func):
    try:
        func()
    except Exception as exc:
        return error in str(exc)
    return False


def candidate(ticker="TEST.NS"):
    return {"Ticker": ticker, "Signal Date": "2026-09-22", "Signal": "BUY", "Setup": "PULLBACK",
            "Trade Quality": "GOOD", "Technical Score": 75, "Actionability Score": 85,
            "Market Regime": "BULL", "Market Score": 70, "Entry Low": 99, "Entry High": 100,
            "Sizing Entry Price": 100, "Stop Loss": 90, "Target 1": 110, "Target 2": 120,
            "R:R T1": 1, "R:R T2": 2, "RS 60D": 5}


def profile():
    return InvestmentProfile(1, "2026-09-22T00:00:00Z", Decimal("100000"), HorizonPreference.THREE_MONTHS)


def recommendation(ledger, ticker="TEST.NS"):
    allocated = allocate_candidates(profile(), [], [candidate(ticker)], decision_date="2026-09-22")
    ledger.persist_allocation_result(allocated)
    return allocated.recommendations[0]


def article(**changes):
    value = {"ticker": "TEST.NS", "headline": "Company announces routine update", "source": "Exchange",
             "source_url": "https://example.invalid/a", "published_at_utc": "2026-09-22T10:00:00Z",
             "observed_at_utc": "2026-09-22T11:00:00Z"}
    return value | changes


class PaperClock:
    day = "2026-09-23"

    @classmethod
    def now(cls, tz):
        return datetime.fromisoformat(cls.day + "T12:00:00").replace(tzinfo=tz)


def main():
    check("after_close_pass", require_after_close(datetime(2026, 9, 22, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))) == "2026-09-22")
    check("before_close_rejected", raises("BEFORE_COMPLETED", lambda: require_after_close(datetime(2026, 9, 22, 15, 44, tzinfo=ZoneInfo("Asia/Kolkata")))))
    check("weekend_rejected", raises("BEFORE_COMPLETED", lambda: require_after_close(datetime(2026, 9, 20, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")))))
    check("naive_clock_rejected", raises("timezone-aware", lambda: require_after_close(datetime(2026, 9, 22, 16, 0))))
    dummy_rec = {"ticker": "TEST.NS", "recommendation_id": "R1",
                 "portfolio_action_status": "ACTIONABLE_BUY", "recommended_quantity": 2}
    buy = {"official_paper_action": "BUY", "ml_shadow_classification": "R3_K1_SELECTED"}
    pending = [PendingEntryReservation.create("PEND.NS", 1000, "R2", "S2")]
    check("zero_slots_five_available", available_slots([], []) == 5)
    check("four_open_one_pending_zero", available_slots(["A", "B", "C", "D"], pending) == 0)
    check("five_open_zero_pending_zero", available_slots(["A", "B", "C", "D", "E"], []) == 0)
    check("three_open_one_pending_one", available_slots(["A", "B", "C"], pending) == 1)
    check("partial_fill_no_double_slot", available_slots(["A", "B", "C", "PEND.NS"], pending) == 1)
    check("official_buy_allows", admission_status(dummy_rec, buy, "AVAILABLE", [], []) == "ADMISSION_ALLOWED")
    check("allocator_actionable_official_buy_allows", admission_status(dummy_rec, buy, "AVAILABLE", [], []) == "ADMISSION_ALLOWED")
    check("allocator_insufficient_capital_blocks", admission_status(dummy_rec | {"portfolio_action_status": "WATCH_INSUFFICIENT_CAPITAL"}, buy, "AVAILABLE", [], []) == "BLOCKED_ALLOCATOR_NOT_ACTIONABLE")
    check("allocator_max_positions_blocks", admission_status(dummy_rec | {"portfolio_action_status": "BLOCKED_MAX_POSITIONS"}, buy, "AVAILABLE", [], []) == "BLOCKED_ALLOCATOR_NOT_ACTIONABLE")
    check("allocator_zero_quantity_blocks", admission_status(dummy_rec | {"recommended_quantity": 0}, buy, "AVAILABLE", [], []) == "BLOCKED_ALLOCATOR_NOT_ACTIONABLE")
    check("allocator_other_watch_reasons_block", all(admission_status(dummy_rec | {"portfolio_action_status": reason}, buy, "AVAILABLE", [], []) == "BLOCKED_ALLOCATOR_NOT_ACTIONABLE" for reason in ("WATCH_RISK_BUDGET_TOO_SMALL", "WATCH_POSITION_CAP_TOO_SMALL", "WATCH_INVALID_RISK", "WATCH_HORIZON_MISMATCH", "BLOCKED_EXISTING_POSITION", "BLOCKED_PENDING_ENTRY", "BLOCKED_PORTFOLIO_OVER_CAP", "BLOCKED_COMMITTED_CAPITAL_OVERAGE")))
    check("news_wait_blocks", admission_status(dummy_rec, {"official_paper_action": "WAIT"}, "AVAILABLE", [], []) == "BLOCKED_OFFICIAL_ACTION_NOT_BUY")
    check("news_review_blocks", admission_status(dummy_rec, {"official_paper_action": "REVIEW"}, "AVAILABLE", [], []) == "BLOCKED_OFFICIAL_ACTION_NOT_BUY")
    check("ml_selection_no_influence", admission_status(dummy_rec, buy, "AVAILABLE", [], []) == admission_status(dummy_rec, buy | {"ml_shadow_classification": "R3_K1_NOT_SELECTED"}, "AVAILABLE", [], []))
    check("feed_outage_blocks", admission_status(dummy_rec, buy, "NEWS_DATA_UNAVAILABLE", [], []) == "BLOCKED_NEWS_DATA_UNAVAILABLE")
    check("usable_quarantine_allows_admission", admission_status(dummy_rec, buy, "AVAILABLE_WITH_QUARANTINE", [], []) == "ADMISSION_ALLOWED")
    check("held_ticker_blocks", admission_status(dummy_rec, buy, "AVAILABLE", ["TEST.NS"], []) == "BLOCKED_EXISTING_POSITION")
    check("pending_ticker_blocks", admission_status(dummy_rec, buy, "AVAILABLE", [], [PendingEntryReservation.create("TEST.NS", 1000, "R2")]) == "BLOCKED_DUPLICATE_PENDING_TICKER")
    check("same_pending_recommendation_blocks", admission_status(dummy_rec, buy, "AVAILABLE", [], [PendingEntryReservation.create("TEST.NS", 1000, "R1")]) == "BLOCKED_DUPLICATE_PENDING_RECOMMENDATION")
    check("max_five_blocks", admission_status(dummy_rec, buy, "AVAILABLE", ["A", "B", "C", "D", "E"], []) == "BLOCKED_MAX_PORTFOLIO_SLOTS")
    check("cancelled_slot_freed", available_slots(["A", "B", "C", "D"], []) == 1)
    check("missing_publication_rejected", raises("NEWS_PUBLICATION_TIMESTAMP_MISSING", lambda: _publication(None)))
    check("naive_publication_rejected", raises("UNTRUSTWORTHY", lambda: _publication("2026-09-22T12:00:00")))
    neutral = normalize_article(article())
    check("ambiguous_news_neutral", neutral["sentiment"] == "NEUTRAL" and neutral["materiality"] == "NON_MATERIAL")
    adverse = normalize_article(article(headline="SEBI bars company directors in enforcement action"))
    check("explicit_regulatory_adverse", adverse["category"] == "REGULATORY" and adverse["severity"] == "HIGH" and adverse["materiality"] == "MATERIAL")
    check("observed_timestamp_preserved", neutral["observed_at_utc"] == "2026-09-22T11:00:00.000000Z")
    check("publication_after_observation_rejected", raises("precede", lambda: normalize_article(article(observed_at_utc="2026-09-22T09:00:00Z"))))

    class FakeTicker:
        news = [{"content": {"title": "Routine update", "pubDate": "2026-09-22T10:00:00Z", "provider": {"displayName": "X"}}},
                {"title": "Flat article", "publisher": "Reuters", "link": "https://example.invalid/flat",
                 "providerPublishTime": 1789776000, "relatedTickers": ["TEST.NS"]},
                {"content": {"title": "No publication", "provider": {"displayName": "X"}}}]
    class FakeYfinance:
        Ticker = lambda self, ticker: FakeTicker()
    with patch.dict(sys.modules, {"yfinance": FakeYfinance()}):
        rows, quarantined = fetch_yfinance_news("TEST.NS")
    check("provider_quarantines_missing_publication", len(rows) == 2 and len(quarantined) == 1)
    check("flat_provider_source_and_url", rows[1]["source"] == "Reuters" and rows[1]["source_url"] == "https://example.invalid/flat")
    check("provider_observed_is_acquisition_time", abs((datetime.fromisoformat(rows[0]["observed_at_utc"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()) < 10)
    with patch.dict(sys.modules, {"yfinance": type("EmptyProvider", (), {"Ticker": lambda self, ticker: type("T", (), {"news": []})()})()}):
        check("empty_provider_response_not_no_news", raises("NEWS_DATA_UNAVAILABLE", lambda: fetch_yfinance_news("TEST.NS")))
    with patch("live_paper.run_after_close.fetch_yfinance_news", return_value=([article(), article(published_at_utc=None)], ["PROVIDER_QUARANTINED:example"])):
        usable, rejected, status = _collect_news("TEST.NS")
    check("valid_plus_malformed_news_partial_quarantine", status == "AVAILABLE_WITH_QUARANTINE" and len(rejected) == 2)
    check("malformed_article_excluded_from_overlay_input", len(usable) == 1 and usable[0]["headline"] == article()["headline"])
    check("partial_quarantine_does_not_block_admission", admission_status(dummy_rec, buy, status, [], []) == "ADMISSION_ALLOWED")
    with patch("live_paper.run_after_close.fetch_yfinance_news", return_value=([article(published_at_utc=None)], [])):
        no_usable = _collect_news("TEST.NS")
    check("zero_trustworthy_news_unavailable", no_usable[2] == "NEWS_DATA_UNAVAILABLE" and not no_usable[0])
    with patch("live_paper.run_after_close.fetch_yfinance_news", side_effect=RuntimeError("provider down")):
        feed_down = _collect_news("TEST.NS")
    check("complete_provider_failure_blocks", feed_down[2] == "NEWS_DATA_UNAVAILABLE" and admission_status(dummy_rec, buy, feed_down[2], [], []) == "BLOCKED_NEWS_DATA_UNAVAILABLE")

    import pandas as pd
    from stage4a3.hashing import canonical_json_hash, dataframe_content_hash
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp)
        scanner_manifest = {"Signal Date": "2026-09-22", "Full Input Logical Hash": "FROZEN_CANDIDATES"}
        scanner_market = {"maximum_market_data_date": "2026-09-22", "nifty_maximum_date": "2026-09-22",
                          "missing_tickers": [], "ticker_count_received": 1, "ticker_count_requested": 1,
                          "nifty_valid_sessions": ["2026-09-21", "2026-09-22"], "raw_data_logical_hash": "RAW"}
        scanner_manifest.update({"Candidate Count": 1, "Raw Market Data Hash": "RAW"})
        (snapshot / "candidate_input_manifest.json").write_text(json.dumps(scanner_manifest))
        (snapshot / "snapshot_metadata.json").write_text(json.dumps({"Candidate Input Manifest Hash": canonical_json_hash(scanner_manifest)}))
        (snapshot / "market_data_manifest.json").write_text(json.dumps(scanner_market))
        fake_market_api = types.ModuleType("yfinance")
        fake_market_api.download = Mock(side_effect=RuntimeError("SECOND_MARKET_REFRESH_PROHIBITED"))
        with patch.dict(sys.modules, {"yfinance": fake_market_api}), \
             patch("stage4a3.candidate_input_builder.build_signal_close_input", return_value=(pd.DataFrame([candidate()]), scanner_manifest, scanner_market)), \
             patch("stage4a3.candidate_input_builder.verify_candidate_input"), \
             patch("live_paper.run_after_close.resolve_snapshot_input_cache", return_value=(snapshot, scanner_manifest)):
            scanned, _, _, prior, _ = _build_candidates("2026-09-22", snapshot, ROOT.parent, {"Candidate Count": 1})
            check("scanner_source_normalization_parity", scanned[0] == normalize_source_candidate(candidate()))
            check("scanner_signal_id_parity", scanned[0]["signal_id"] == derive_signal_id(ticker="TEST.NS", signal_date="2026-09-22", signal="BUY", setup="PULLBACK"))
            check("actual_market_predecessor", prior == "2026-09-21")
        with patch.dict(sys.modules, {"yfinance": fake_market_api}), \
             patch("stage4a3.candidate_input_builder.build_signal_close_input", return_value=(pd.DataFrame([candidate()]), scanner_manifest, scanner_market | {"nifty_maximum_date": "2026-09-21"})), \
             patch("stage4a3.candidate_input_builder.verify_candidate_input"), \
             patch("live_paper.run_after_close.resolve_snapshot_input_cache", return_value=(snapshot, scanner_manifest)):
            check("market_date_mismatch_rejected", raises("CANDIDATE_PROVENANCE_MISMATCH", lambda: _build_candidates("2026-09-22", snapshot, ROOT.parent, {"Candidate Count": 1})))
        with patch.dict(sys.modules, {"yfinance": fake_market_api}), \
             patch("stage4a3.candidate_input_builder.build_signal_close_input", return_value=(pd.DataFrame([candidate()]), scanner_manifest, scanner_market | {"missing_tickers": ["OTHER.NS"]})), \
             patch("stage4a3.candidate_input_builder.verify_candidate_input"), \
             patch("live_paper.run_after_close.resolve_snapshot_input_cache", return_value=(snapshot, scanner_manifest)):
            check("incomplete_market_data_rejected", raises("CANDIDATE_PROVENANCE_MISMATCH", lambda: _build_candidates("2026-09-22", snapshot, ROOT.parent, {"Candidate Count": 1})))

    with tempfile.TemporaryDirectory() as tmp:
        precision_root = Path(tmp)
        raw_root = precision_root / "raw_market_data"
        raw_root.mkdir()
        original_precision = pd.DataFrame({"Date": ["2026-09-22"], "Close": [123456789.12345679]})
        market_csv = raw_root / "TCS.NS.csv"
        unrelated_csv = precision_root / "prospective_universe.csv"
        original_precision.to_csv(market_csv, index=False)
        original_precision.to_csv(unrelated_csv, index=False)
        original_reader = pd.read_csv
        ordinary = pd.read_csv(market_csv)
        with round_trip_market_csv_reads(precision_root):
            lossless = pd.read_csv(market_csv)
            unrelated = pd.read_csv(unrelated_csv)
            check("round_trip_scoped_only_to_exact_market_cache", lossless.iloc[0]["Close"] == original_precision.iloc[0]["Close"] and unrelated.iloc[0]["Close"] == ordinary.iloc[0]["Close"])
        check("ordinary_csv_hash_can_differ", dataframe_content_hash(ordinary) != dataframe_content_hash(original_precision))
        check("round_trip_csv_hash_reproduces_original", dataframe_content_hash(lossless) == dataframe_content_hash(original_precision))
        check("pandas_read_csv_restored_after_scope", pd.read_csv is original_reader)

    with tempfile.TemporaryDirectory() as tmp:
        activated = Path(tmp) / "activated"
        root = activated / "Stage 4A.3"
        (root / "prospective/audit").mkdir(parents=True)
        (root / "prospective/audit/activation_record.json").write_text("{}", encoding="utf-8")
        directory = root / "prospective/snapshots/2026/2026-09-22"
        start = datetime.now(timezone.utc) - timedelta(seconds=3)
        created = start + timedelta(seconds=1)
        metadata = {"Snapshot Created UTC": created.isoformat(), "Signal Date": "2026-09-22"}
        observed_cutoffs = []
        def fake_verify_prediction(_signal, cutoff, _directory):
            observed_cutoffs.append(cutoff)
            raise Stage4A3PredictionNotAvailable("fixture has no signal")
        def create_snapshot(*_args, **_kwargs):
            directory.mkdir(parents=True)
            (directory / "snapshot_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        protocol_stub = types.ModuleType("stage4a3.protocol_integrity")
        protocol_stub.verify_runtime_protocol_integrity = lambda *_args: None
        with patch.dict(sys.modules, {"stage4a3.protocol_integrity": protocol_stub}), \
             patch("live_paper.run_after_close.Stage4A3ShadowAdapter", return_value=types.SimpleNamespace(load_verified_prediction=fake_verify_prediction)), \
             patch("live_paper.run_after_close.subprocess.run", side_effect=create_snapshot) as collector:
            found, received = _snapshot("2026-09-22", start, activated)
            check("post_subprocess_snapshot_clock_accepts_new_capture", found == directory.resolve() and received == metadata)
            check("new_snapshot_uses_post_subprocess_cutoff", datetime.fromisoformat(observed_cutoffs[-1].replace("Z", "+00:00")) > created)
            check("new_snapshot_collected_once", collector.call_count == 1 and "--as-of" not in collector.call_args.args[0])
            original_bytes = (directory / "snapshot_metadata.json").read_bytes()
            with patch("live_paper.run_after_close.subprocess.run", side_effect=AssertionError("IMMUTABLE_SNAPSHOT_REWRITTEN")) as forbidden:
                _snapshot("2026-09-22", start + timedelta(seconds=2), activated)
                check("existing_snapshot_reused_without_subprocess", forbidden.call_count == 0 and (directory / "snapshot_metadata.json").read_bytes() == original_bytes)
                check("existing_snapshot_uses_original_verification_cutoff", observed_cutoffs[-1] == (start + timedelta(seconds=2)).isoformat(timespec="microseconds").replace("+00:00", "Z"))
            future = {**metadata, "Snapshot Created UTC": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}
            (directory / "snapshot_metadata.json").write_text(json.dumps(future), encoding="utf-8")
            check("genuine_future_snapshot_rejected", raises("FUTURE_CREATED_SNAPSHOT", lambda: _snapshot("2026-09-22", datetime.now(timezone.utc), activated)))

    with tempfile.TemporaryDirectory() as tmp:
        activated = Path(tmp) / "activated"
        root = activated / "Stage 4A.3"
        (root / "prospective/audit").mkdir(parents=True)
        (root / "prospective/audit/activation_record.json").write_text("{}", encoding="utf-8")
        directory = root / "prospective/snapshots/2026/2026-09-23"
        directory.mkdir(parents=True)
        (directory / "snapshot_metadata.json").write_text(json.dumps({"Signal Date": "2026-09-23"}), encoding="utf-8")
        (directory / "market_data_manifest.json").write_text(json.dumps({
            "maximum_market_data_date": "2026-09-23", "nifty_maximum_date": "2026-09-23",
            "missing_tickers": [], "ticker_count_received": 19, "ticker_count_requested": 19,
            "raw_data_logical_hash": "RAW"}), encoding="utf-8")
        (directory / "candidate_input_manifest.json").write_text(json.dumps({
            "Signal Date": "2026-09-23", "Raw Market Data Hash": "RAW"}), encoding="utf-8")
        protocol_stub = types.ModuleType("stage4a3.protocol_integrity")
        protocol_stub.verify_runtime_protocol_integrity = lambda *_args: None
        session_adapter = types.SimpleNamespace(load_verified_prediction=Mock(side_effect=Stage4A3PredictionNotAvailable("no signal")))
        network = Mock(side_effect=AssertionError("NETWORK_PROHIBITED_FOR_SESSION_VALIDATION"))
        with patch.dict(sys.modules, {"stage4a3.protocol_integrity": protocol_stub}), \
             patch("live_paper.paper_action.Stage4A3ShadowAdapter", return_value=session_adapter), \
             patch("socket.create_connection", network):
            proved_session = verify_paper_action_market_session(activated, "2026-09-23", datetime(2026, 9, 23, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
        check("verified_snapshot_proves_market_session", proved_session["session_date"] == "2026-09-23" and proved_session["evidence_type"] == "STAGE4A3_COMPLETED_SESSION")
        check("market_session_validation_requires_no_network", network.call_count == 0)
        scheduled = verify_paper_action_market_session(activated, "2026-09-24", datetime(2026, 9, 24, 9, 30, tzinfo=ZoneInfo("Asia/Kolkata")))
        check("missing_snapshot_uses_official_schedule", scheduled["evidence_type"] == "NSE_OFFICIAL_SCHEDULED_SESSION")
        check("scheduled_evidence_auditable", scheduled["source_download_ref"] == "NSE/CMTR/71775" and scheduled["source_circular_ref"] == "172/2025" and len(scheduled["calendar_payload_hash"]) == 64)
        (root / "prospective/snapshots/2026/2026-09-24").mkdir(parents=True)
        check("existing_corrupt_snapshot_fails_closed", raises("PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION", lambda: verify_paper_action_market_session(activated, "2026-09-24", datetime(2026, 9, 24, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")))))
        check("corrupt_snapshot_no_calendar_fallback", raises("PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION", lambda: verify_paper_action_market_session(activated, "2026-09-24", datetime(2026, 9, 24, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")))))

    calendar = load_verified_calendar()
    check("official_calendar_identity", calendar["source"]["authority"] == "National Stock Exchange of India Limited" and calendar["segment"] == "CAPITAL MARKET SEGMENT")
    check("official_calendar_integrity", len(calendar["calendar_payload_hash"]) == 64)
    check("calendar_weekday_session", verify_scheduled_session("2026-09-24")["evidence_type"] == "NSE_OFFICIAL_SCHEDULED_SESSION")
    check("calendar_saturday_rejected", raises("PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION", lambda: verify_scheduled_session("2026-09-26")))
    check("calendar_sunday_rejected", raises("PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION", lambda: verify_scheduled_session("2026-09-27")))
    check("official_weekday_holiday_rejected", raises("PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION", lambda: verify_scheduled_session("2026-10-02")))
    check("muhurat_not_guessed", raises("PAPER_ACTION_SPECIAL_SESSION_UNSUPPORTED", lambda: verify_scheduled_session("2026-11-08")))
    check("unsupported_calendar_year_rejected", raises("PAPER_ACTION_MARKET_CALENDAR_UNAVAILABLE", lambda: verify_scheduled_session("2027-01-04")))
    with tempfile.TemporaryDirectory() as tmp:
        tampered = Path(tmp) / "calendar.json"
        value = json.loads(DEFAULT_CALENDAR_PATH.read_text(encoding="utf-8"))
        value["closed_dates"].remove("2026-10-02")
        tampered.write_text(json.dumps(value), encoding="utf-8")
        check("tampered_calendar_rejected", raises("PAPER_ACTION_MARKET_CALENDAR_INTEGRITY_FAILURE", lambda: verify_scheduled_session("2026-09-24", tampered)))
        check("missing_calendar_rejected", raises("PAPER_ACTION_MARKET_CALENDAR_INTEGRITY_FAILURE", lambda: verify_scheduled_session("2026-09-24", Path(tmp) / "missing.json")))
    calendar_network = Mock(side_effect=AssertionError("CALENDAR_NETWORK_PROHIBITED"))
    calendar_download = Mock(side_effect=AssertionError("CALENDAR_YFINANCE_PROHIBITED"))
    calendar_yfinance = types.ModuleType("yfinance")
    calendar_yfinance.download = calendar_download
    with patch("socket.create_connection", calendar_network), patch.dict(sys.modules, {"yfinance": calendar_yfinance}):
        verify_scheduled_session("2026-09-24")
    check("calendar_validation_zero_network_calls", calendar_network.call_count == 0)
    check("calendar_validation_zero_yfinance_downloads", calendar_download.call_count == 0)

    # Clone only the frozen builder's read dependencies into a disposable
    # external checkout. The snapshot/source cache under the real repo is never
    # written or refreshed by this regression fixture.
    from stage4a3.candidate_input_builder import BUILDER_FILES, build_signal_close_input
    from stage4a3.hashing import sha256_file
    with tempfile.TemporaryDirectory() as tmp:
        activated = Path(tmp) / "activated"
        for relative in (*BUILDER_FILES, "Stage 3/stage3/hashing.py", "Stage 4A.3/prospective_universe.csv",
                         "Stage 4A.3/models/frozen_2026/model_bundle_manifest.json",
                         "Stage 4A.3/results/stage4a3_frozen_universe_hash.json"):
            target = activated / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT.parent / relative, target)
        created = "2026-08-28T15:56:37.469844+00:00"
        metadata = {"Snapshot Created UTC": created, "Signal Date": "2026-08-28", "Candidate Count": 0}
        cache = activated / "Stage 4A.3/prospective/input_cache/20260828T155637Z"
        raw = cache / "raw_market_data"
        (raw / "yfinance_internal").mkdir(parents=True)
        universe = pd.read_csv(activated / "Stage 4A.3/prospective_universe.csv")
        tickers = ["^NSEI", *universe["Ticker"].astype(str)]
        for ticker in tickers:
            name = ticker.replace("^", "INDEX_").replace("&", "AND") + ".csv"
            shutil.copyfile(ROOT.parent / "Stage 2.2.2 Final/stage2_2_1/data/frozen" / name, raw / name)
        snapshot = activated / "Stage 4A.3/prospective/snapshots/2026/2026-08-28"
        snapshot.mkdir(parents=True)
        download = Mock(side_effect=RuntimeError("SECOND_MARKET_REFRESH_PROHIBITED"))
        fake_yfinance = types.ModuleType("yfinance")
        fake_yfinance.__version__ = "NO_NETWORK_FIXTURE"
        fake_yfinance.download = download
        fake_yfinance.set_tz_cache_location = lambda *_args: None
        before_hashes = {ticker: sha256_file(raw / (ticker.replace("^", "INDEX_").replace("&", "AND") + ".csv")) for ticker in tickers}
        with patch.dict(sys.modules, {"yfinance": fake_yfinance}), round_trip_market_csv_reads(cache), redirect_stdout(io.StringIO()):
            source_frame, source_manifest, source_market = build_signal_close_input(activated, "2026-08-28", cache, "REFRESH")
        check("fixture_zero_candidate_cohort", len(source_frame) == 0 and source_manifest["Candidate Count"] == 0)
        check("fixture_initial_builder_no_network", download.call_count == 0)
        (snapshot / "candidate_input_manifest.json").write_text(json.dumps(source_manifest), encoding="utf-8")
        original_market = source_market | {"provider_identifier": "ORIGINAL_STAGE4A3_CAPTURE", "download_timestamp_utc": "SNAPSHOT_ORIGINAL_TIME"}
        (snapshot / "market_data_manifest.json").write_text(json.dumps(original_market), encoding="utf-8")
        (snapshot / "snapshot_metadata.json").write_text(json.dumps(metadata | {"Candidate Input Manifest Hash": canonical_json_hash(source_manifest)}), encoding="utf-8")
        check("snapshot_timestamp_resolves_exact_external_cache", resolve_snapshot_input_cache(activated, snapshot, metadata)[0] == cache)
        download.reset_mock()
        with patch.dict(sys.modules, {"yfinance": fake_yfinance}), redirect_stdout(io.StringIO()):
            reconstructed, rebuilt, market, predecessor, returned_cache = _build_candidates("2026-08-28", snapshot, activated, metadata)
        check("complete_snapshot_cache_reconstruction", reconstructed == [] and predecessor == source_market["nifty_valid_sessions"][-2])
        check("candidate_reconstruction_returns_verified_cache", returned_cache == cache)
        check("second_market_refresh_prohibited", download.call_count == 0)
        check("snapshot_candidate_manifest_exact_equality", rebuilt == source_manifest)
        check("snapshot_universe_nifty_signal_and_full_hashes", all(rebuilt[key] == source_manifest[key] for key in ("Frozen Universe Hash", "NIFTY Data Hash", "Candidate Signal-ID Logical Hash", "Full Input Logical Hash")))
        check("snapshot_raw_hash_matches", rebuilt["Raw Market Data Hash"] == source_manifest["Raw Market Data Hash"] == original_market["raw_data_logical_hash"])
        check("snapshot_per_ticker_hashes_match", rebuilt["Per-Ticker Raw Hashes"] == source_manifest["Per-Ticker Raw Hashes"])
        check("snapshot_stable_market_manifest_fields", all(market[key] == source_market[key] for key in ("maximum_market_data_date", "nifty_maximum_date", "ticker_count_requested", "ticker_count_received", "missing_tickers", "raw_data_logical_hash")))
        check("original_snapshot_provider_identity_reported", market["provider_identifier"] == "ORIGINAL_STAGE4A3_CAPTURE")
        check("external_checkout_cache_not_modified", before_hashes == {ticker: sha256_file(raw / (ticker.replace("^", "INDEX_").replace("&", "AND") + ".csv")) for ticker in tickers})
        check("zero_candidate_snapshot_valid", not reconstructed and rebuilt["Candidate Count"] == metadata["Candidate Count"])
        check("missing_exact_cache_directory_fails", raises("SNAPSHOT_INPUT_CACHE_MISSING", lambda: resolve_snapshot_input_cache(activated, snapshot, metadata | {"Snapshot Created UTC": "2026-08-28T15:56:38+00:00"})))
        ticker_path = raw / "TCS.NS.csv"
        ticker_path.unlink()
        download.reset_mock()
        check("missing_ticker_cache_fails_before_download", raises("SNAPSHOT_INPUT_CACHE_INCOMPLETE", lambda: _build_candidates("2026-08-28", snapshot, activated, metadata)) and download.call_count == 0)
        ticker_path.write_bytes(b"")
        check("empty_ticker_cache_fails_before_download", raises("SNAPSHOT_INPUT_CACHE_INCOMPLETE", lambda: _build_candidates("2026-08-28", snapshot, activated, metadata)) and download.call_count == 0)

    # Reuse the frozen indicator engine on a historical *fixture* only. No
    # current-market network call or historical production run occurs here.
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        cache = scratch / "raw_market_data"
        cache.mkdir()
        shutil.copyfile(ROOT.parent / "Stage 2.2.2 Final/stage2_2_1/data/frozen/TCS.NS.csv", cache / "TCS.NS.csv")
        def ledger_for(ticker):
            return type("FixtureLedger", (), {"derive_positions": lambda self: [type("P", (), {"ticker": ticker})()]})()
        fake_ledger = ledger_for("TCS.NS")
        frozen_frame = pd.read_csv(cache / "TCS.NS.csv", parse_dates=["Date"], index_col="Date", float_precision="round_trip")
        holding_manifest = {"Per-Ticker Raw Hashes": {"TCS.NS": dataframe_content_hash(frozen_frame.reset_index())}}
        holding_download = Mock(side_effect=RuntimeError("HOLDING_MARKET_REFRESH_PROHIBITED"))
        holding_yf = types.ModuleType("yfinance")
        holding_yf.download = holding_download
        with patch.dict(sys.modules, {"yfinance": holding_yf}):
            prices, observations = _holding_observations(fake_ledger, "2026-08-28", scratch, holding_manifest)
            missing_session = raises("MISSING_REQUIRED_HOLDING_PRICE_CACHE", lambda: _holding_observations(fake_ledger, "2026-08-27", scratch, holding_manifest))
        check("frozen_holding_price_observation", prices["TCS.NS"] == observations[0]["close"])
        check("frozen_supertrend_and_swing_low", observations[0]["daily_supertrend"] and observations[0]["swing_low_10"])
        check("missing_holding_session_rejected", missing_session)
        check("holding_uses_snapshot_cache_source", observations[0]["source_name"] == "STAGE4A3_SNAPSHOT_CACHE_FROZEN_STAGE2_1_FEATURE_ENGINE")
        check("holding_round_trip_hash_matches_manifest", observations[0]["source_data_hash"] == holding_manifest["Per-Ticker Raw Hashes"]["TCS.NS"])
        check("holding_market_refresh_prohibited", holding_download.call_count == 0)
        (cache / "EMPTY.NS.csv").write_bytes(b"")
        with patch.dict(sys.modules, {"yfinance": holding_yf}):
            check("missing_holding_csv_fails_before_download", raises("MISSING_REQUIRED_HOLDING_PRICE_CACHE", lambda: _holding_observations(ledger_for("MISSING.NS"), "2026-08-28", scratch, {"Per-Ticker Raw Hashes": {"MISSING.NS": "X"}})) and holding_download.call_count == 0)
            check("empty_holding_csv_fails_before_download", raises("MISSING_REQUIRED_HOLDING_PRICE_CACHE", lambda: _holding_observations(ledger_for("EMPTY.NS"), "2026-08-28", scratch, {"Per-Ticker Raw Hashes": {"EMPTY.NS": "X"}})) and holding_download.call_count == 0)
            check("holding_hash_mismatch_fails_closed", raises("HOLDING_MARKET_DATA_PROVENANCE_MISMATCH", lambda: _holding_observations(fake_ledger, "2026-08-28", scratch, {"Per-Ticker Raw Hashes": {"TCS.NS": "WRONG"}})))

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "paper.sqlite3"
        with Stage5DLedger(db) as ledger:
            manager, overlay = Stage5D3Manager(ledger), Stage5D4Overlay(ledger)
            _initialize_runs(ledger)
            rec = recommendation(ledger)
            check("frozen_allocation_actionable", rec["portfolio_action_status"] == "ACTIONABLE_BUY")
            ovr = overlay.evaluate_recommendation_overlay(rec["recommendation_id"], "2026-09-22T12:00:00Z", [])
            check("frozen_overlay_official_buy", ovr["official_paper_action"] == "BUY" and ovr["ml_influence"] == "NONE")
            check("ml_absent_not_blocking", ovr["ml_shadow_classification"] == "ML_NOT_AVAILABLE")
            report = {"run_id": "RUN", "market_session_date": "2026-09-22",
                      "run_started_utc": "2026-09-22T12:00:00Z", "run_completed_utc": "2026-09-22T12:01:00Z",
                      "data_provider": "FIXTURE", "market_data_hash": "HASH", "candidate_input_hash": "HASH",
                      "candidate_count": 1, "stage4a3_snapshot_id": "SNAP",
                      "allocation_run_id": rec["allocation_run_id"], "management_session_run_id": "MGMT",
                      "recommendation_count": 1, "news_status": "AVAILABLE",
                      "recommendations": [{"recommendation": rec, "overlay": ovr, "news_status": "AVAILABLE"}]}
            canonical = canonical_json(report)
            with ledger.connection:
                ledger.connection.execute("""INSERT INTO stage5d5_live_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                          ("RUN", "2026-09-22", "2026-09-22T12:00:00Z", "2026-09-22T12:01:00Z",
                                           "FIXTURE", "HASH", "HASH", 1, "SNAP", rec["allocation_run_id"], "MGMT", 1,
                                           "AVAILABLE", canonical, payload_sha256(canonical)))
            with patch("live_paper.paper_action.datetime", PaperClock):
                PaperClock.day = "2026-09-22"
                pending_action = record_action(ledger, "pending", rec["recommendation_id"])
                check("explicit_pending_created", pending_action["status"] == "CREATED" and len(ledger.get_active_pending_reservations()) == 1)
                check("duplicate_pending_rejected", raises("BLOCKED_DUPLICATE_PENDING_RECOMMENDATION", lambda: record_action(ledger, "pending", rec["recommendation_id"])))
                quantity = min(2, int(rec["recommended_quantity"]))
                check("same_signal_date_fill_rejected", raises("FILL_REQUIRES_FUTURE_ENTRY_SESSION", lambda: record_action(ledger, "fill", rec["recommendation_id"], quantity=1, price="100")))
                check("same_date_fill_no_transaction", not ledger.transactions_for_recommendation(rec["recommendation_id"]))
                before_invalid_transactions = len(ledger.transactions_for_recommendation(rec["recommendation_id"]))
                before_invalid_events = ledger.connection.execute("SELECT count(*) FROM recommendation_events WHERE recommendation_id=?", (rec["recommendation_id"],)).fetchone()[0]
                for invalid_day, name, error in (("2026-09-26", "saturday_fill_rejected", "PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION"),
                                                 ("2026-09-27", "sunday_fill_rejected", "PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION"),
                                                 ("2026-10-02", "official_holiday_fill_rejected", "PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION"),
                                                 ("2027-01-04", "unsupported_year_fill_rejected", "PAPER_ACTION_MARKET_CALENDAR_UNAVAILABLE")):
                    PaperClock.day = invalid_day
                    check(name, raises(error, lambda: record_action(ledger, "fill", rec["recommendation_id"], quantity=1, price="100")))
                check("invalid_session_fill_no_transaction", len(ledger.transactions_for_recommendation(rec["recommendation_id"])) == before_invalid_transactions)
                check("invalid_session_fill_no_lifecycle_mutation", ledger.connection.execute("SELECT count(*) FROM recommendation_events WHERE recommendation_id=?", (rec["recommendation_id"],)).fetchone()[0] == before_invalid_events)
                PaperClock.day = "2026-09-23"
                fill = record_action(ledger, "fill", rec["recommendation_id"], quantity=quantity, price="100")
                check("next_session_fill_before_management_allowed", fill["status"] == "CREATED" and fill["market_session_evidence"]["evidence_type"] == "NSE_OFFICIAL_SCHEDULED_SESSION")
                check("morning_fill_before_snapshot", fill["market_session_evidence"]["session_date"] == "2026-09-23")
                check("fill_uses_lifecycle", ledger._effective_fill_quantity(rec["recommendation_id"]) == quantity)
                check("recommendation_buy_lineage", all(tx["side"] == "BUY" and tx["signal_id"] == rec["signal_id"] for tx in ledger.transactions_for_recommendation(rec["recommendation_id"])))
                check("overfill_rejected", raises("exceeds", lambda: record_action(ledger, "fill", rec["recommendation_id"], quantity=int(rec["recommended_quantity"]) + 1, price="100")))
                today = PaperClock.day
                manager.process_completed_session(today, [{"ticker": "TEST.NS", "session_date": today,
                                                          "open": 100, "high": 105, "low": 95, "close": 100,
                                                          "daily_supertrend": 90, "swing_low_10": 95,
                                                          "source_name": "SYNTHETIC_TEST", "source_data_hash": "TEST"}])
                check("morning_fill_visible_to_after_close_management", manager.states(rec["recommendation_id"])[-1]["session_date"] == today)
                before_transactions = len(ledger.transactions_for_recommendation(rec["recommendation_id"]))
                before_events = ledger.connection.execute("SELECT count(*) FROM recommendation_events WHERE recommendation_id=?", (rec["recommendation_id"],)).fetchone()[0]
                check("fill_after_management_rejected", raises("FILL_SESSION_ALREADY_PROCESSED", lambda: record_action(ledger, "fill", rec["recommendation_id"], quantity=1, price="100")))
                check("rejected_fill_no_transaction", len(ledger.transactions_for_recommendation(rec["recommendation_id"])) == before_transactions)
                check("rejected_fill_no_lifecycle_event", ledger.connection.execute("SELECT count(*) FROM recommendation_events WHERE recommendation_id=?", (rec["recommendation_id"],)).fetchone()[0] == before_events)
                cancelled = record_action(ledger, "cancel", rec["recommendation_id"])
                check("cancel_frees_pending_slot", cancelled["status"] == "CREATED" and not ledger.get_active_pending_reservations())
                check("cancel_prevents_new_fill", raises("FILL_SESSION_ALREADY_PROCESSED", lambda: record_action(ledger, "fill", rec["recommendation_id"], quantity=1, price="100")))
                check("sell_over_managed_quantity_rejected", raises("exceeds", lambda: record_action(ledger, "sell", rec["recommendation_id"], quantity=quantity + 1, price="101")))
                PaperClock.day = "2026-09-26"
                before_invalid_sell = len(ledger.transactions_for_recommendation(rec["recommendation_id"]))
                check("invalid_session_sell_rejected", raises("PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION", lambda: record_action(ledger, "sell", rec["recommendation_id"], quantity=1, price="101")))
                check("invalid_session_sell_no_transaction", len(ledger.transactions_for_recommendation(rec["recommendation_id"])) == before_invalid_sell)
                PaperClock.day = "2026-10-02"
                check("official_holiday_sell_rejected", raises("PAPER_ACTION_REQUIRES_VALID_MARKET_SESSION", lambda: record_action(ledger, "sell", rec["recommendation_id"], quantity=1, price="101")))
                PaperClock.day = "2026-09-24"
                sold = record_action(ledger, "sell", rec["recommendation_id"], quantity=1, price="101")
                check("linked_paper_sell_recorded", sold["status"] == "CREATED" and any(tx["side"] == "SELL" and tx["signal_id"] == rec["signal_id"] for tx in ledger.transactions_for_recommendation(rec["recommendation_id"])))
                check("valid_session_sell_succeeds", sold["status"] == "CREATED" and sold["market_session_evidence"]["evidence_type"] == "NSE_OFFICIAL_SCHEDULED_SESSION")
                admin_rec = recommendation(ledger, "ADMIN.NS")
                declined = record_action(ledger, "decline", admin_rec["recommendation_id"])
                check("decline_admin_action_unchanged", declined["status"] == "CREATED")
            check("ledger_integrity", ledger.integrity_check()["ok"])
            check("overlay_integrity", overlay.integrity_check()["ok"])
            check("management_integrity", manager.integrity_check()["ok"])

    with tempfile.TemporaryDirectory() as tmp:
        with Stage5DLedger(Path(tmp) / "history.sqlite3") as ledger:
            _initialize_runs(ledger)
            for day in ("2026-09-21", "2026-09-22"):
                payload = {"run_id": "RUN_" + day, "market_session_date": day,
                           "run_started_utc": day + "T10:15:00Z", "run_completed_utc": day + "T11:00:00Z",
                           "data_provider": "FIXTURE", "market_data_hash": "M_" + day,
                           "candidate_input_hash": "C_" + day, "candidate_count": 0,
                           "stage4a3_snapshot_id": "S_" + day, "allocation_run_id": "A_" + day,
                           "management_session_run_id": "G_" + day, "recommendation_count": 0,
                           "news_status": "AVAILABLE"}
                serialized = canonical_json(payload)
                with ledger.connection:
                    ledger.connection.execute("INSERT INTO stage5d5_live_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (payload["run_id"], day, payload["run_started_utc"], payload["run_completed_utc"],
                         payload["data_provider"], payload["market_data_hash"], payload["candidate_input_hash"],
                         0, payload["stage4a3_snapshot_id"], payload["allocation_run_id"],
                         payload["management_session_run_id"], 0, "AVAILABLE", serialized, payload_sha256(serialized)))
            verify_live_run_integrity(ledger)
            check("clean_multiday_live_history_integrity", True)
            with ledger.connection:
                ledger.connection.execute("UPDATE stage5d5_live_runs SET canonical_payload_json='{}' WHERE market_session_date='2026-09-21'")
            check("prior_payload_tamper_rejected", raises("LIVE_RUN_INTEGRITY_FAILURE", lambda: verify_live_run_integrity(ledger)))
            with ledger.connection:
                ledger.connection.execute("UPDATE stage5d5_live_runs SET canonical_payload_json=?, data_provider='TAMPER' WHERE market_session_date='2026-09-21'", (canonical_json({"run_id": "RUN_2026-09-21", "market_session_date": "2026-09-21", "run_started_utc": "2026-09-21T10:15:00Z", "run_completed_utc": "2026-09-21T11:00:00Z", "data_provider": "FIXTURE", "market_data_hash": "M_2026-09-21", "candidate_input_hash": "C_2026-09-21", "candidate_count": 0, "stage4a3_snapshot_id": "S_2026-09-21", "allocation_run_id": "A_2026-09-21", "management_session_run_id": "G_2026-09-21", "recommendation_count": 0, "news_status": "AVAILABLE"}),))
            check("prior_typed_column_tamper_rejected", raises("LIVE_RUN_INTEGRITY_FAILURE", lambda: verify_live_run_integrity(ledger)))
            with ledger.connection:
                ledger.connection.execute("UPDATE stage5d5_live_runs SET data_provider='FIXTURE' WHERE market_session_date='2026-09-21'")
                ledger.connection.execute("DELETE FROM stage5d5_meta WHERE singleton=1")
            check("missing_schema_marker_not_recreated", raises("LIVE_RUN_INTEGRITY_FAILURE", lambda: _initialize_runs(ledger)))
            check("missing_schema_marker_integrity_rejected", raises("LIVE_RUN_INTEGRITY_FAILURE", lambda: verify_live_run_integrity(ledger)))

    # End-to-end zero-position fixture: the real frozen allocator, ledger, and
    # Stage 5D.3 are called, but all external data and the clock are synthetic.
    with tempfile.TemporaryDirectory() as tmp:
        fixture_repo = Path(tmp)
        snapshot = fixture_repo / "snapshot"
        snapshot.mkdir()
        (snapshot / "snapshot_manifest.json").write_text(json.dumps({"Snapshot Content Hash": "FIXTURE_HASH"}))
        config = fixture_repo / "config.json"
        config.write_text(json.dumps({"capital_ceiling_inr": "100000", "preferred_horizon": "THREE_MONTHS",
                                      "news_provider": "yfinance", "timezone": "Asia/Kolkata",
                                      "database_path": "Stage 5D/runtime/test.sqlite3"}))
        manifest = {"Full Input Logical Hash": "CANDIDATES"}
        market = {"raw_data_logical_hash": "MARKET", "provider_identifier": "FIXTURE"}
        fixed_profile = profile()
        with patch("live_paper.run_after_close.REPO", fixture_repo), \
             patch("live_paper.run_after_close._profile", return_value=fixed_profile), \
             patch("live_paper.run_after_close._snapshot", return_value=(snapshot, {"Snapshot ID": "SNAP"})), \
             patch("live_paper.run_after_close._build_candidates", return_value=([], manifest, market, "2026-09-21", snapshot)), \
             patch("live_paper.run_after_close._holding_observations", return_value=({}, [])), \
             patch("live_paper.run_after_close.Stage4A3ShadowAdapter"):
            now = datetime(2026, 9, 22, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
            first = _run_with_clock(config, now=now)
            check("one_command_run_created", first["status"] == "CREATED")
            check("zero_position_management_persisted", first["management"]["managed_episode_count"] == 0 and first["management_session_run_id"])
            check("run_immutable_ids", bool(first["run_id"] and first["allocation_run_id"] and first["stage4a3_snapshot_id"]))
            check("machine_report_written", (fixture_repo / "Stage 5D/runtime/reports/2026-09-22/live_paper_report.json").is_file())
            second = _run_with_clock(config, now=now)
            check("same_session_idempotent", second["status"] == "IDEMPOTENT_SUCCESS" and second["run_id"] == first["run_id"])
            check("human_report_rendered", "LIVE PAPER REPORT" in render_report(second) and "PORTFOLIO" in render_report(second))
            with patch("live_paper.run_after_close._build_candidates", return_value=([], manifest | {"Full Input Logical Hash": "CHANGED"}, market, "2026-09-21", snapshot)):
                check("conflicting_same_session_rejected", raises("CONFLICTING_SAME_SESSION_EVIDENCE", lambda: _run_with_clock(config, now=now)))
            changed_profile = InvestmentProfile(2, "2026-09-22T12:00:00Z", Decimal("100000"), HorizonPreference.THREE_MONTHS)
            with patch("live_paper.run_after_close._profile", return_value=changed_profile):
                check("same_session_profile_change_rejected", raises("CONFLICTING_SAME_SESSION_EVIDENCE", lambda: _run_with_clock(config, now=now)))
            with patch("live_paper.run_after_close._build_candidates", return_value=([], manifest, market, "2026-09-23", snapshot)):
                skipped = datetime(2026, 9, 24, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
                check("skipped_market_session_rejected", raises("MISSING_COMPLETED_MARKET_SESSION", lambda: _run_with_clock(config, now=skipped)))
            with Stage5DLedger(fixture_repo / "Stage 5D/runtime/test.sqlite3") as ledger:
                with ledger.connection:
                    ledger.connection.execute("UPDATE stage5d5_live_runs SET news_status='TAMPER' WHERE market_session_date='2026-09-22'")
            check("future_production_run_refuses_prior_tamper", raises("LIVE_RUN_INTEGRITY_FAILURE", lambda: _run_with_clock(config, now=datetime(2026, 9, 24, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")))))

    # A news outage blocks new admission while the frozen daily management run
    # and deterministic recommendation still complete.
    with tempfile.TemporaryDirectory() as tmp:
        fixture_repo = Path(tmp)
        snapshot = fixture_repo / "snapshot"
        snapshot.mkdir()
        (snapshot / "snapshot_manifest.json").write_text(json.dumps({"Snapshot Content Hash": "FIXTURE_HASH"}))
        config = fixture_repo / "config.json"
        config.write_text(json.dumps({"capital_ceiling_inr": "100000", "preferred_horizon": "THREE_MONTHS",
                                      "news_provider": "yfinance", "timezone": "Asia/Kolkata",
                                      "database_path": "Stage 5D/runtime/test.sqlite3"}))
        adapter = Stage4A3ShadowAdapter(ROOT.parent / "Stage 4A.3")
        with patch("live_paper.run_after_close.REPO", fixture_repo), \
             patch("live_paper.run_after_close._profile", return_value=profile()), \
             patch("live_paper.run_after_close._snapshot", return_value=(snapshot, {"Snapshot ID": "SNAP"})), \
             patch("live_paper.run_after_close._build_candidates", return_value=([candidate()], {"Full Input Logical Hash": "CANDIDATES"},
                                                                                  {"raw_data_logical_hash": "MARKET", "provider_identifier": "FIXTURE"}, "2026-09-21", snapshot)), \
             patch("live_paper.run_after_close._holding_observations", return_value=({}, [])), \
             patch("live_paper.run_after_close.Stage4A3ShadowAdapter", return_value=adapter), \
             patch.object(Stage4A3ShadowAdapter, "load_verified_prediction", side_effect=Stage4A3PredictionNotAvailable("no row")), \
             patch("live_paper.run_after_close.fetch_yfinance_news", side_effect=RuntimeError("feed outage")):
            now = datetime(2026, 9, 22, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
            outage = _run_with_clock(config, now=now)
            check("news_outage_does_not_stop_management", outage["management_session_run_id"] and outage["management"]["managed_episode_count"] == 0)
            check("news_outage_blocks_admission", outage["recommendations"][0]["paper_admission"] == "BLOCKED_NEWS_DATA_UNAVAILABLE")
            check("outage_preserves_deterministic_action", outage["recommendations"][0]["overlay"]["official_paper_action"] == "BUY")
            check("unavailable_ml_never_influences", outage["recommendations"][0]["overlay"]["ml_influence"] == "NONE")
            observed = datetime.now(timezone.utc) - timedelta(minutes=2)
            published = observed - timedelta(minutes=10)
            valid = article(published_at_utc=published.isoformat(), observed_at_utc=observed.isoformat())
            partial_repo = fixture_repo / "partial"
            partial_repo.mkdir()
            with patch("live_paper.run_after_close.REPO", partial_repo), \
                 patch("live_paper.run_after_close.fetch_yfinance_news", return_value=([valid, article(published_at_utc=None)], [])):
                partial = _run_with_clock(config, db_override="Stage 5D/runtime/partial.sqlite3", now=now)
            partial_row = partial["recommendations"][0]
            check("partial_news_runner_status", partial_row["news_status"] == "AVAILABLE_WITH_QUARANTINE" and partial["news_status"] == "AVAILABLE_WITH_QUARANTINE")
            check("partial_news_runner_admission", partial_row["paper_admission"] == "ADMISSION_ALLOWED")
            check("partial_news_overlay_only_valid_event", len(partial_row["overlay"]["news_event_ids"]) == 1 and len(partial_row["quarantined_news"]) == 1)
            with Stage5DLedger(partial_repo / "Stage 5D/runtime/partial.sqlite3") as partial_ledger:
                check("partial_news_persisted_only_valid_event", partial_ledger.connection.execute("SELECT count(*) FROM stage5d4_news_events").fetchone()[0] == 1)

    ignored = subprocess.run(["git", "check-ignore", "-q", "Stage 5D/runtime/live_paper.sqlite3"],
                             cwd=ROOT.parent).returncode == 0
    check("runtime_database_gitignored", ignored)
    ignored_report = subprocess.run(["git", "check-ignore", "-q", "Stage 5D/runtime/reports/2026-09-22/live_paper_report.json"],
                                    cwd=ROOT.parent).returncode == 0
    check("runtime_report_gitignored", ignored_report)
    source = (ROOT / "live_paper/run_after_close.py").read_text(encoding="utf-8")
    check("no_automatic_paper_buy_or_sell", ".mark_pending(" not in source and ".record_recommendation_fill(" not in source and ".append_transaction(" not in source)
    paper_source = (ROOT / "live_paper/paper_action.py").read_text(encoding="utf-8")
    check("recommendation_buy_uses_frozen_fill_only", "record_recommendation_fill(" in paper_source and 'side="BUY"' not in paper_source)

    output = ROOT / "results/stage5d5_test_results.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("test", "result"))
        writer.writerows(RESULTS)
    print(json.dumps({"PASS": sum(status == "PASS" for _, status in RESULTS),
                      "FAIL": sum(status == "FAIL" for _, status in RESULTS)}))


if __name__ == "__main__":
    main()
