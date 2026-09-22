"""Stage 5D.5 safety and orchestration tests; no network or live paper state."""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "Stage 4A.3"))

from live_paper import SCHEMA_VERSION
from live_paper.admission import admission_status, available_slots
from live_paper.news_normalizer import normalize_article
from live_paper.news_provider import _publication, fetch_yfinance_news
from live_paper.paper_action import record_action
from live_paper.run_after_close import _build_candidates, _collect_news, _existing_run, _holding_observations, _initialize_runs, _run_with_clock, render_report, require_after_close, verify_live_run_integrity
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


def recommendation(ledger):
    allocated = allocate_candidates(profile(), [], [candidate()], decision_date="2026-09-22")
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
    from stage4a3.hashing import canonical_json_hash
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp)
        scanner_manifest = {"Signal Date": "2026-09-22", "Full Input Logical Hash": "FROZEN_CANDIDATES"}
        scanner_market = {"maximum_market_data_date": "2026-09-22", "nifty_maximum_date": "2026-09-22",
                          "missing_tickers": [], "ticker_count_received": 1, "ticker_count_requested": 1,
                          "nifty_valid_sessions": ["2026-09-21", "2026-09-22"]}
        (snapshot / "candidate_input_manifest.json").write_text(json.dumps(scanner_manifest))
        (snapshot / "snapshot_metadata.json").write_text(json.dumps({"Candidate Input Manifest Hash": canonical_json_hash(scanner_manifest)}))
        with patch("stage4a3.candidate_input_builder.build_signal_close_input", return_value=(pd.DataFrame([candidate()]), scanner_manifest, scanner_market)), \
             patch("stage4a3.candidate_input_builder.verify_candidate_input"):
            scanned, _, _, prior = _build_candidates("2026-09-22", snapshot, snapshot)
            check("scanner_source_normalization_parity", scanned[0] == normalize_source_candidate(candidate()))
            check("scanner_signal_id_parity", scanned[0]["signal_id"] == derive_signal_id(ticker="TEST.NS", signal_date="2026-09-22", signal="BUY", setup="PULLBACK"))
            check("actual_market_predecessor", prior == "2026-09-21")
        with patch("stage4a3.candidate_input_builder.build_signal_close_input", return_value=(pd.DataFrame([candidate()]), scanner_manifest, scanner_market | {"nifty_maximum_date": "2026-09-21"})), \
             patch("stage4a3.candidate_input_builder.verify_candidate_input"):
            check("market_date_mismatch_rejected", raises("MARKET_DATE_MISMATCH", lambda: _build_candidates("2026-09-22", snapshot, snapshot)))
        with patch("stage4a3.candidate_input_builder.build_signal_close_input", return_value=(pd.DataFrame([candidate()]), scanner_manifest, scanner_market | {"missing_tickers": ["OTHER.NS"]})), \
             patch("stage4a3.candidate_input_builder.verify_candidate_input"):
            check("incomplete_market_data_rejected", raises("INCOMPLETE_MARKET_DATA", lambda: _build_candidates("2026-09-22", snapshot, snapshot)))

    # Reuse the frozen indicator engine on a historical *fixture* only. No
    # current-market network call or historical production run occurs here.
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        cache = scratch / "raw_market_data"
        cache.mkdir()
        shutil.copyfile(ROOT.parent / "Stage 2.2.2 Final/stage2_2_1/data/frozen/TCS.NS.csv", cache / "TCS.NS.csv")
        fake_ledger = type("FixtureLedger", (), {"derive_positions": lambda self: [type("P", (), {"ticker": "TCS.NS"})()]})()
        with patch.dict(sys.modules, {"yfinance": types.ModuleType("yfinance")}):
            prices, observations = _holding_observations(fake_ledger, "2026-08-28", scratch)
            missing_session = raises("MISSING_REQUIRED_HOLDING_PRICE", lambda: _holding_observations(fake_ledger, "2026-08-27", scratch))
        check("frozen_holding_price_observation", prices["TCS.NS"] == observations[0]["close"])
        check("frozen_supertrend_and_swing_low", observations[0]["daily_supertrend"] and observations[0]["swing_low_10"])
        check("missing_holding_session_rejected", missing_session)

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
                PaperClock.day = "2026-09-23"
                fill = record_action(ledger, "fill", rec["recommendation_id"], quantity=quantity, price="100")
                check("next_session_fill_before_management_allowed", fill["status"] == "CREATED")
                check("fill_uses_lifecycle", ledger._effective_fill_quantity(rec["recommendation_id"]) == quantity)
                check("recommendation_buy_lineage", all(tx["side"] == "BUY" and tx["signal_id"] == rec["signal_id"] for tx in ledger.transactions_for_recommendation(rec["recommendation_id"])))
                check("overfill_rejected", raises("exceeds", lambda: record_action(ledger, "fill", rec["recommendation_id"], quantity=int(rec["recommended_quantity"]) + 1, price="100")))
                today = PaperClock.day
                manager.process_completed_session(today, [{"ticker": "TEST.NS", "session_date": today,
                                                          "open": 100, "high": 105, "low": 95, "close": 100,
                                                          "daily_supertrend": 90, "swing_low_10": 95,
                                                          "source_name": "SYNTHETIC_TEST", "source_data_hash": "TEST"}])
                before_transactions = len(ledger.transactions_for_recommendation(rec["recommendation_id"]))
                before_events = ledger.connection.execute("SELECT count(*) FROM recommendation_events WHERE recommendation_id=?", (rec["recommendation_id"],)).fetchone()[0]
                check("fill_after_management_rejected", raises("FILL_SESSION_ALREADY_PROCESSED", lambda: record_action(ledger, "fill", rec["recommendation_id"], quantity=1, price="100")))
                check("rejected_fill_no_transaction", len(ledger.transactions_for_recommendation(rec["recommendation_id"])) == before_transactions)
                check("rejected_fill_no_lifecycle_event", ledger.connection.execute("SELECT count(*) FROM recommendation_events WHERE recommendation_id=?", (rec["recommendation_id"],)).fetchone()[0] == before_events)
                cancelled = record_action(ledger, "cancel", rec["recommendation_id"])
                check("cancel_frees_pending_slot", cancelled["status"] == "CREATED" and not ledger.get_active_pending_reservations())
                check("cancel_prevents_new_fill", raises("FILL_SESSION_ALREADY_PROCESSED", lambda: record_action(ledger, "fill", rec["recommendation_id"], quantity=1, price="100")))
                check("sell_over_managed_quantity_rejected", raises("exceeds", lambda: record_action(ledger, "sell", rec["recommendation_id"], quantity=quantity + 1, price="101")))
                sold = record_action(ledger, "sell", rec["recommendation_id"], quantity=1, price="101")
                check("linked_paper_sell_recorded", sold["status"] == "CREATED" and any(tx["side"] == "SELL" and tx["signal_id"] == rec["signal_id"] for tx in ledger.transactions_for_recommendation(rec["recommendation_id"])))
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
             patch("live_paper.run_after_close._build_candidates", return_value=([], manifest, market, "2026-09-21")), \
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
            with patch("live_paper.run_after_close._build_candidates", return_value=([], manifest | {"Full Input Logical Hash": "CHANGED"}, market, "2026-09-21")):
                check("conflicting_same_session_rejected", raises("CONFLICTING_SAME_SESSION_EVIDENCE", lambda: _run_with_clock(config, now=now)))
            changed_profile = InvestmentProfile(2, "2026-09-22T12:00:00Z", Decimal("100000"), HorizonPreference.THREE_MONTHS)
            with patch("live_paper.run_after_close._profile", return_value=changed_profile):
                check("same_session_profile_change_rejected", raises("CONFLICTING_SAME_SESSION_EVIDENCE", lambda: _run_with_clock(config, now=now)))
            with patch("live_paper.run_after_close._build_candidates", return_value=([], manifest, market, "2026-09-23")):
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
                                                                                  {"raw_data_logical_hash": "MARKET", "provider_identifier": "FIXTURE"}, "2026-09-21")), \
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
