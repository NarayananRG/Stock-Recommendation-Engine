from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from stage5d.allocator import allocate_candidates
from stage5d.horizon import HorizonPreference
from stage5d.ledger import Stage5DLedger
from stage5d.ledger_schema import SCHEMA_VERSION
from stage5d.management_store import STAGE5D3_SCHEMA_VERSION, STAGE5D3_TABLES, Stage5D3Manager
from stage5d.news_ml_overlay import (
    FROZEN_ML_MODEL_BUNDLE_HASH,
    FROZEN_ML_PROTOCOL_COMMIT,
    FROZEN_ML_PROTOCOL_ID,
    NEWS_CATEGORIES,
    STAGE5D4_SCHEMA_VERSION,
    STAGE5D4_TABLES,
    Stage5D4Overlay,
    evaluate_news_overlay,
    normalize_news_event,
)
from stage5d.overlay_contract import ml_shadow_contract_payload, news_contract_payload, schema_payload
from stage5d.stage4a3_shadow_adapter import Stage4A3ShadowAdapter
from stage5d.user_profile import InvestmentProfile

STAGE4A3_ROOT = REPO / "Stage 4A.3"
sys.path.insert(0, str(STAGE4A3_ROOT))
from stage4a3.immutable_ledger import write_snapshot
from stage4a3.snapshot_contract import PREDICTION_COLUMNS


def profile() -> InvestmentProfile:
    return InvestmentProfile(1, "2026-09-01T00:00:00+00:00", Decimal("20000"), HorizonPreference.THREE_MONTHS)


def candidate(ticker: str = "AAA.NS", signal: str = "BUY") -> dict[str, object]:
    actionable = signal in {"BUY", "STRONG BUY"}
    return {
        "ticker": ticker, "signal_date": "2026-09-14", "deterministic_signal": signal,
        "setup": "PULLBACK", "trade_quality": "GOOD", "technical_score": 80 if actionable else None,
        "actionability_score": 85 if actionable else None, "market_regime": "BULLISH", "market_score": 75,
        "entry_low": 99 if actionable else None, "entry_high": 100 if actionable else None,
        "sizing_entry_price": 100 if actionable else None, "stop": 90 if actionable else None,
        "target_1": 110 if actionable else None, "target_2": 120 if actionable else None,
        "planned_rr_t1": 1 if actionable else None, "planned_rr_t2": 2 if actionable else None,
        "rs60": 5 if actionable else None, "deterministic_rank": 1,
    }


def news(
    event_id: str = "NEWS_1", *, ticker: str = "AAA.NS", category: str = "REGULATORY",
    sentiment: str = "NEGATIVE", severity: str = "HIGH", materiality: str = "MATERIAL",
    published: str = "2026-09-14T10:00:00Z", observed: str | None = None,
) -> dict[str, object]:
    return {
        "event_id": event_id, "ticker": ticker, "headline": f"{category} event {event_id}",
        "source": "TEST_WIRE", "source_url": None, "published_at_utc": published,
        "observed_at_utc": observed or published, "event_date": published[:10], "category": category,
        "sentiment": sentiment, "severity": severity, "materiality": materiality,
        "confidence": "0.90", "summary": f"Explicit {category.lower()} evidence.", "source_hash": None,
    }


def snapshot_fixture(
    case_root: Path, recommendations: list[dict[str, object]], *,
    r3_selected: list[bool] | None = None, r0_selected: list[bool] | None = None,
    created: str = "2026-09-14T15:00:00Z", protocol_commit: str = FROZEN_ML_PROTOCOL_COMMIT,
    model_bundle_hash: str = FROZEN_ML_MODEL_BUNDLE_HASH, signal_ids: list[str] | None = None,
    tickers: list[str] | None = None,
) -> tuple[Stage4A3ShadowAdapter, Path]:
    selected3 = r3_selected or [True] * len(recommendations)
    selected0 = r0_selected or [False] * len(recommendations)
    ids = signal_ids or [str(item["signal_id"]) for item in recommendations]
    names = tickers or [str(item["ticker"]) for item in recommendations]
    snapshot_id = "SNAP_" + case_root.name.upper()
    rows: list[dict[str, object]] = []
    for index, rec in enumerate(recommendations):
        row: dict[str, object] = {
            "Protocol Version": "STAGE4A3A_V1", "Protocol Commit": protocol_commit,
            "Protocol Tag": "stage4a3-prospective-shadow-protocol-baseline", "Snapshot ID": snapshot_id,
            "Signal Date": rec["signal_date"], "Snapshot Created UTC": created,
            "Snapshot Created Asia/Kolkata": "2026-09-14T20:30:00+05:30", "Signal ID": ids[index],
            "Ticker": names[index], "Original Signal": rec["deterministic_signal"], "Signal": rec["deterministic_signal"],
            "Setup": "PULLBACK", "Market Regime": "BULLISH", "Trade Quality": "GOOD",
            "Actionability Score": 85, "Technical Score": 80, "Planned Entry": 100,
            "Initial Stop": 90, "Original T1": 110, "Original T2": 120, "Dataset Cohort": "BASELINE_PRIMARY",
            "Feature Row Hash": (str(index + 1) * 64)[:64], "Model Bundle Hash": model_bundle_hash,
            "Prediction Semantics": "SHADOW_ONLY_NO_TRADING_EFFECT",
        }
        for code in range(6):
            row[f"R{code} Score"] = 0.51 + code * 0.01 + index * 0.001
            row[f"R{code} Same-Date Rank"] = index + 1
            row[f"R{code}_K1 Selected"] = selected0[index] if code == 0 else (selected3[index] if code == 3 else False)
            row[f"R{code}_K2 Selected"] = index < 2
        rows.append(row)
    predictions = pd.DataFrame(rows, columns=PREDICTION_COLUMNS)
    features = pd.DataFrame([{"Signal ID": ids[i], "Ticker": names[i], "Feature Row Hash": rows[i]["Feature Row Hash"]} for i in range(len(rows))])
    metadata = {"Snapshot ID": snapshot_id, "Snapshot Created UTC": created, "Signal Date": recommendations[0]["signal_date"], "Candidate Count": len(rows)}
    snapshot_root, audit_root = case_root / "snapshots", case_root / "audit"
    write_snapshot(snapshot_root, audit_root, str(recommendations[0]["signal_date"]), metadata, predictions, features,
                   {"source": "TEMP_TEST_FIXTURE"}, "0" * 64, protocol_commit, model_bundle_hash,
                   candidate_input_manifest={"source": "TEMP_TEST_FIXTURE"})
    directory = snapshot_root / str(recommendations[0]["signal_date"])[:4] / str(recommendations[0]["signal_date"])
    return Stage4A3ShadowAdapter(STAGE4A3_ROOT, snapshot_root), directory


def raises(call, text: str = "") -> bool:
    try:
        call()
    except (TypeError, ValueError, RuntimeError) as exc:
        return text.lower() in str(exc).lower()
    return False


def changed(base: str, paths: list[str]) -> str:
    return subprocess.check_output(["git", "diff", "--name-only", base, "--", *paths], cwd=REPO, text=True).strip()


def write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> int:
    rows: list[dict[str, object]] = []

    def check(number: int, name: str, passed: bool, details: str = "") -> None:
        rows.append({"Test Number": number, "Test": name, "Status": "PASS" if passed else "FAIL", "Details": details})

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "stage5d4.sqlite3"
        ledger = Stage5DLedger(db)
        stage3 = Stage5D3Manager(ledger)
        overlay = Stage5D4Overlay(ledger)
        check(1, "Stage 5D.4 schema initializes", overlay.schema_version == STAGE5D4_SCHEMA_VERSION and all(ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() for table in STAGE5D4_TABLES))
        check(2, "Stage 5D.2 schema unchanged", ledger.schema_version == SCHEMA_VERSION == "STAGE5D2_SCHEMA_V1")
        check(3, "Stage 5D.3 schema unchanged", stage3.schema_version == STAGE5D3_SCHEMA_VERSION and tuple(STAGE5D3_TABLES) == ("stage5d3_meta", "management_session_runs", "management_episodes", "daily_market_observations", "management_state_versions"))

        allocation = allocate_candidates(profile(), [], [candidate()])
        ledger.persist_allocation_result(allocation)
        rec = dict(allocation.recommendations[0])
        rec_id = str(rec["recommendation_id"])
        created = overlay.persist_news_events([news()])
        check(4, "news event persistence", created[0].status == "CREATED" and ledger.connection.execute("SELECT COUNT(*) FROM stage5d4_news_events").fetchone()[0] == 1)
        replay = overlay.persist_news_events([news()])
        check(5, "exact news replay idempotent", replay[0].status == "IDEMPOTENT_SUCCESS")
        conflict = news(); conflict["headline"] = "Conflicting headline"
        check(6, "conflicting news event rejected", raises(lambda: overlay.persist_news_events([conflict]), "conflicting immutable news"))
        check(7, "minimum news categories supported", set({"EARNINGS","GUIDANCE","REGULATORY","LEGAL","GOVERNANCE","FRAUD_ALLEGATION","PROMOTER","MANAGEMENT_CHANGE","CREDIT_RATING","DEBT_LIQUIDITY","LARGE_ORDER","ORDER_CANCELLATION","CORPORATE_ACTION","M_AND_A","CAPITAL_RAISE","PRODUCT","MACRO_SECTOR","OTHER"}).issubset(NEWS_CATEGORIES))

        positive = normalize_news_event(news("POS", sentiment="POSITIVE", severity="HIGH", category="LARGE_ORDER"))
        check(8, "positive news cannot create BUY from WAIT", evaluate_news_overlay("WAIT", [positive])["official_paper_action"] == "WAIT")
        check(9, "positive news cannot create BUY from WATCH", evaluate_news_overlay("WATCH", [positive])["official_paper_action"] == "WATCH")
        check(10, "positive news cannot create BUY from AVOID", evaluate_news_overlay("AVOID", [positive])["official_paper_action"] == "AVOID")
        check(11, "positive news cannot upgrade BUY", evaluate_news_overlay("BUY", [positive])["official_paper_action"] == "BUY")
        positive_strong = evaluate_news_overlay("STRONG BUY", [positive])
        check(12, "positive news cannot upgrade STRONG BUY", positive_strong["official_paper_action"] == "STRONG BUY" and positive_strong["news_event_ids"] == ["POS"])
        low = normalize_news_event(news("LOW", severity="LOW"))
        medium = normalize_news_event(news("MED", severity="MEDIUM"))
        high = normalize_news_event(news("HIGH", severity="HIGH"))
        critical = normalize_news_event(news("CRIT", severity="CRITICAL"))
        check(13, "LOW adverse leaves action unchanged", evaluate_news_overlay("BUY", [low])["official_paper_action"] == "BUY")
        check(14, "MEDIUM adverse triggers REVIEW", evaluate_news_overlay("BUY", [medium])["official_paper_action"] == "REVIEW")
        check(15, "HIGH adverse triggers WAIT", evaluate_news_overlay("BUY", [high])["official_paper_action"] == "WAIT")
        check(16, "CRITICAL adverse triggers WAIT", evaluate_news_overlay("BUY", [critical])["official_paper_action"] == "WAIT")
        check(17, "highest material severity wins", evaluate_news_overlay("BUY", [medium, critical])["news_risk_level"] == "CRITICAL")
        check(18, "positive event cannot cancel CRITICAL adverse", evaluate_news_overlay("BUY", [critical, positive])["official_paper_action"] == "WAIT")

        cutoff = "2026-09-14T15:30:00Z"
        future = news("FUTURE", published="2026-09-15T09:00:00Z")
        future_only = overlay.evaluate_recommendation_overlay(rec_id, cutoff, [future])
        check(19, "future-published news excluded", future_only["news_event_ids"] == [])
        check(20, "future-published news cannot change official action", future_only["official_paper_action"] == "BUY")
        exact_event = news("EXACT", published=cutoff)
        exact_overlay = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T15:31:00Z", [exact_event])
        check(21, "exact cutoff timestamp included", exact_overlay["news_event_ids"] == ["EXACT"])
        no_time = news("NO_TIME"); no_time.pop("published_at_utc")
        check(22, "publication timestamp required", raises(lambda: normalize_news_event(no_time), "published_at_utc is required"))
        naive = news("NAIVE", published="2026-09-14T10:00:00")
        check(23, "publication timestamp timezone required", raises(lambda: normalize_news_event(naive), "timezone"))

        reason_cases = [
            (24, "REGULATORY", "MATERIAL_REGULATORY_RISK"),
            (25, "LEGAL", "MATERIAL_LEGAL_RISK"),
            (26, "GOVERNANCE", "GOVERNANCE_RISK"),
            (27, "CREDIT_RATING", "CREDIT_DETERIORATION"),
            (28, "EARNINGS", "EARNINGS_MISS"),
            (29, "GUIDANCE", "GUIDANCE_CUT"),
            (30, "PROMOTER", "PROMOTER_RISK"),
            (31, "ORDER_CANCELLATION", "ORDER_CANCELLATION"),
            (32, "MANAGEMENT_CHANGE", "MANAGEMENT_UNCERTAINTY"),
        ]
        for number, category, reason in reason_cases:
            result = evaluate_news_overlay("BUY", [normalize_news_event(news(f"R{number}", category=category))])
            check(number, f"{category} deterministic reason code", reason in result["news_reason_codes"])
        check(33, "deterministic BUY plus no news remains BUY", evaluate_news_overlay("BUY", [])["official_paper_action"] == "BUY")
        check(34, "deterministic BUY plus high adverse downgrades", evaluate_news_overlay("BUY", [high])["official_paper_action"] == "WAIT")
        check(35, "deterministic WAIT remains WAIT", evaluate_news_overlay("WAIT", [high])["official_paper_action"] == "WAIT")
        check(36, "deterministic AVOID remains AVOID", evaluate_news_overlay("AVOID", [high])["official_paper_action"] == "AVOID")
        check(37, "existing HOLD plus high adverse becomes RISK_HOLD", evaluate_news_overlay("HOLD", [high])["official_paper_action"] == "RISK_HOLD")
        event_row = ledger.connection.execute("SELECT canonical_payload_json FROM stage5d4_news_events WHERE event_id='NEWS_1'").fetchone()
        event_payload = json.loads(event_row[0])
        check(38, "news source traceability persisted", all(event_payload.get(key) for key in ("event_id","headline","source","published_at_utc","category","severity")))

        adapter_high, snapshot_high = snapshot_fixture(Path(tmp) / "high", [rec], r3_selected=[True], r0_selected=[False])
        with_ml = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T16:00:00Z", [], adapter_high, snapshot_high)
        check(39, "verified Stage 4A.3 prediction persisted", ledger.connection.execute("SELECT COUNT(*) FROM stage5d4_ml_predictions").fetchone()[0] == 1)
        missing_ml = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T16:01:00Z", [])
        check(40, "ML unavailable handled", missing_ml["ml_shadow_classification"] == "ML_NOT_AVAILABLE" and missing_ml["official_paper_action"] == "BUY")
        high_ml = with_ml
        adapter_low, snapshot_low = snapshot_fixture(Path(tmp) / "low", [rec], r3_selected=[False], r0_selected=[True])
        low_ml = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T16:02:00Z", [], adapter_low, snapshot_low)
        check(41, "R3_K1 selected cannot change official action", high_ml["official_paper_action"] == high_ml["deterministic_action"] == "BUY")
        check(42, "R3_K1 not selected cannot change official action", low_ml["official_paper_action"] == low_ml["deterministic_action"] == "BUY")
        check(43, "ML cannot change quantity", high_ml["official_quantity"] == low_ml["official_quantity"] == rec["recommended_quantity"])
        check(44, "ML cannot change stop", Decimal(str(high_ml["official_stop"])) == Decimal(str(low_ml["official_stop"])) == Decimal(str(rec["stop"])))
        check(45, "ML cannot change target", Decimal(str(high_ml["official_target_1"])) == Decimal(str(low_ml["official_target_1"])) == Decimal(str(rec["target_1"])) and Decimal(str(high_ml["official_target_2"])) == Decimal(str(low_ml["official_target_2"])) == Decimal(str(rec["target_2"])))
        check(46, "ML cannot change horizon", high_ml["official_horizon"] == low_ml["official_horizon"] == rec["selected_horizon"])
        check(47, "ML cannot change ranking identity", high_ml["official_ranking_identity"] == low_ml["official_ranking_identity"] == rec["allocation_run_id"])
        stored_ml = json.loads(ledger.connection.execute("SELECT canonical_payload_json FROM stage5d4_ml_predictions ORDER BY persisted_at_utc LIMIT 1").fetchone()[0])
        check(48, "frozen Stage 4A.3 identity persisted", high_ml["ml_protocol_id"] == FROZEN_ML_PROTOCOL_ID and stored_ml["model_bundle_hash"] == FROZEN_ML_MODEL_BUNDLE_HASH and stored_ml["protocol_commit"] == FROZEN_ML_PROTOCOL_COMMIT and len(stored_ml["snapshot_content_hash"]) == 64)
        fake = {"protocol_id": FROZEN_ML_PROTOCOL_ID, "probability": "0.99", "snapshot_content_hash": "a" * 64}
        check(49, "caller-invented ML dictionary rejected", raises(lambda: overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T16:03:00Z", [], fake), "Stage4A3ShadowAdapter"))
        adapter_future, snapshot_future = snapshot_fixture(Path(tmp) / "futureml", [rec], created="2026-09-15T00:00:00Z")
        check(50, "future-created snapshot rejected", raises(lambda: overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T16:03:00Z", [], adapter_future, snapshot_future), "after the decision cutoff"))

        combined_event = news("COMBINED", category="REGULATORY")
        combined = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T17:00:00Z", [combined_event], adapter_high, snapshot_high)
        check(51, "deterministic news and ML record persisted", combined["official_paper_action"] == "WAIT" and combined["ml_shadow_classification"] == "R3_K1_SELECTED")
        repeated = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T17:00:00Z", [combined_event], adapter_high, snapshot_high)
        check(52, "exact overlay rerun idempotent", repeated["status"] == "IDEMPOTENT_SUCCESS" and repeated["overlay_id"] == combined["overlay_id"])
        altered = news("ALTERED", severity="MEDIUM")
        check(53, "conflicting overlay rejected", raises(lambda: overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T17:00:00Z", [altered], adapter_high, snapshot_high), "conflicting immutable Stage 5D.4 overlay"))
        stored = overlay.get_overlay(combined["overlay_id"])
        check(54, "overlay recommendation lineage verified", stored["recommendation_id"] == rec_id)
        check(55, "overlay signal lineage verified", stored["signal_id"] == rec["signal_id"])
        check(56, "overlay ticker lineage verified", stored["ticker"] == rec["ticker"])
        check(57, "overlay cutoff binding verified", stored["decision_cutoff_utc"] == "2026-09-14T17:00:00.000000Z")
        check(58, "R0 evidence preserved", stored["research_views"]["R0"]["action"] == "BUY")
        check(59, "R1 evidence preserved", stored["research_views"]["R1"]["action"] == "WAIT")
        check(60, "R2 shadow evidence preserved", stored["research_views"]["R2"]["research_only"] and stored["research_views"]["R2"]["ml_shadow"] == "R3_K1_SELECTED")
        check(61, "R3 shadow evidence preserved", stored["research_views"]["R3"]["research_only"] and stored["research_views"]["R3"]["action"] == "WAIT")

        second_allocation = allocate_candidates(profile(), [], [candidate("BBB.NS")])
        ledger.persist_allocation_result(second_allocation)
        rec2 = dict(second_allocation.recommendations[0])
        adapter_batch, snapshot_batch = snapshot_fixture(Path(tmp) / "batch", [rec, rec2], r3_selected=[True, False], r0_selected=[False, True])
        batch = overlay.evaluate_daily_overlays(
            [rec_id, str(rec2["recommendation_id"])], "2026-09-14T18:00:00Z",
            {"AAA.NS": [news("BATCH_A")], "BBB.NS": [news("BATCH_B", ticker="BBB.NS", sentiment="POSITIVE", category="LARGE_ORDER")]},
            adapter_batch, {rec_id: snapshot_batch, str(rec2["recommendation_id"]): snapshot_batch},
        )
        check(62, "batch API evaluates multiple recommendations", len(batch) == 2 and {item["ticker"] for item in batch} == {"AAA.NS", "BBB.NS"})
        integrity = overlay.integrity_check()
        check(63, "Stage 5D.4 immutable integrity checks pass", integrity["ok"], json.dumps(integrity, sort_keys=True))

        observed_future = news("OBS_FUTURE", published="2026-09-14T10:00:00Z", observed="2026-09-14T19:00:00Z")
        observed_future_result = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T18:30:00Z", [observed_future])
        check(81, "published before cutoff observed after cutoff excluded", observed_future_result["news_event_ids"] == [])
        check(82, "future-observed event cannot downgrade BUY", observed_future_result["official_paper_action"] == "BUY")
        observed_exact = news("OBS_EXACT", published="2026-09-14T10:00:00Z", observed="2026-09-14T18:31:00Z")
        observed_exact_result = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T18:31:00Z", [observed_exact])
        check(83, "published before cutoff observed exactly at cutoff included", observed_exact_result["news_event_ids"] == ["OBS_EXACT"])
        both_exact = news("BOTH_EXACT", published="2026-09-14T18:32:00Z", observed="2026-09-14T18:32:00Z")
        both_exact_result = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T18:32:00Z", [both_exact])
        check(84, "published and observed exactly at cutoff included", both_exact_result["news_event_ids"] == ["BOTH_EXACT"])
        check(85, "real R3 score read", high_ml["r3_score"] == format(0.54, ".17g"))
        check(86, "real R3 same-date rank read", high_ml["r3_same_date_rank"] == 1)
        check(87, "real R3_K1 selection read", high_ml["r3_k1_selected"] is True and high_ml["ml_primary_selected"] is True)
        check(88, "real R0 comparator selection read", high_ml["r0_k1_selected"] is False and high_ml["ml_comparator_selected"] is False)
        check(89, "frozen policy and comparator persisted", stored_ml["primary_policy"] == "R3_K1" and stored_ml["primary_comparator"] == "R0_K1")
        check(90, "no invented probability persisted", "probability" not in stored_ml and "ml_probability" not in with_ml)

        tampered_candidate_root = Path(tmp) / "tampered_candidate"
        adapter_tampered_candidate, dir_tampered_candidate = snapshot_fixture(tampered_candidate_root, [rec])
        with (dir_tampered_candidate / "candidate_predictions.csv.gz").open("ab") as handle:
            handle.write(b"TAMPER")
        check(91, "tampered candidate_predictions rejected", raises(lambda: adapter_tampered_candidate.load_verified_prediction(rec, "2026-09-14T16:00:00Z", dir_tampered_candidate), "SHA-256"))

        tampered_manifest_root = Path(tmp) / "tampered_manifest"
        adapter_tampered_manifest, dir_tampered_manifest = snapshot_fixture(tampered_manifest_root, [rec])
        manifest_path = dir_tampered_manifest / "snapshot_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")); manifest["files"][0]["sha256"] = "f" * 64
        write_json(manifest_path, manifest)
        check(92, "tampered snapshot manifest rejected", raises(lambda: adapter_tampered_manifest.load_verified_prediction(rec, "2026-09-14T16:00:00Z", dir_tampered_manifest), "SHA-256"))

        bad_commit_adapter, bad_commit_dir = snapshot_fixture(Path(tmp) / "bad_commit", [rec], protocol_commit="b" * 40)
        check(93, "wrong protocol commit rejected", raises(lambda: bad_commit_adapter.load_verified_prediction(rec, "2026-09-14T16:00:00Z", bad_commit_dir), "protocol commit"))
        bad_bundle_adapter, bad_bundle_dir = snapshot_fixture(Path(tmp) / "bad_bundle", [rec], model_bundle_hash="c" * 64)
        check(94, "wrong model bundle rejected", raises(lambda: bad_bundle_adapter.load_verified_prediction(rec, "2026-09-14T16:00:00Z", bad_bundle_dir), "model bundle"))
        bad_signal_adapter, bad_signal_dir = snapshot_fixture(Path(tmp) / "bad_signal", [rec], signal_ids=["WRONG_SIGNAL"])
        check(95, "direct adapter reports missing Signal ID prediction", raises(lambda: bad_signal_adapter.load_verified_prediction(rec, "2026-09-14T16:00:00Z", bad_signal_dir), "no matching Signal ID prediction"))
        bad_ticker_adapter, bad_ticker_dir = snapshot_fixture(Path(tmp) / "bad_ticker", [rec], tickers=["WRONG.NS"])
        check(96, "wrong ticker rejected", raises(lambda: bad_ticker_adapter.load_verified_prediction(rec, "2026-09-14T16:00:00Z", bad_ticker_dir), "ticker lineage"))
        check(97, "snapshot content and chain hashes persisted", len(stored_ml["snapshot_content_hash"]) == 64 and len(stored_ml["snapshot_chain_hash"]) == 64)
        check(98, "R3 selection maps only to frozen shadow classification", high_ml["ml_shadow_classification"] == "R3_K1_SELECTED" and low_ml["ml_shadow_classification"] == "R3_K1_NOT_SELECTED")
        check(99, "R3 selection maps only to experimental action", high_ml["ml_experimental_action"] == "SELECT" and low_ml["ml_experimental_action"] == "NOT_SELECT")
        final_integrity = overlay.integrity_check()
        check(100, "typed payload and dual-cutoff integrity pass", final_integrity["ok"] and all(final_integrity["checks"].get(name) for name in ("pragma_integrity_check", "pragma_foreign_key_check", "news_typed_payload_binding", "ml_typed_payload_binding", "overlay_typed_payload_binding", "news_cutoff_binding")), json.dumps(final_integrity, sort_keys=True))

        missing_observed = news("MISSING_OBSERVED")
        missing_observed.pop("observed_at_utc")
        check(101, "missing observed_at_utc rejected", raises(lambda: normalize_news_event(missing_observed), "observed_at_utc is required"))
        check(102, "missing observed timestamp cannot inherit publication timestamp", "observed_at_utc" not in missing_observed and raises(lambda: normalize_news_event(missing_observed), "observed_at_utc is required"))

        unavailable_adapter, unavailable_dir = snapshot_fixture(Path(tmp) / "unavailable", [rec], signal_ids=["OTHER_SIGNAL"])
        ml_rows_before = ledger.connection.execute("SELECT COUNT(*) FROM stage5d4_ml_predictions").fetchone()[0]
        unavailable = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T18:33:00Z", [], unavailable_adapter, unavailable_dir)
        check(103, "verified snapshot with no matching Signal ID is ML_NOT_AVAILABLE", unavailable["ml_shadow_classification"] == "ML_NOT_AVAILABLE" and unavailable["ml_experimental_action"] == "NOT_AVAILABLE" and unavailable["ml_influence"] == "NONE")
        check(104, "missing ML row does not alter official paper action", unavailable["official_paper_action"] == unavailable["deterministic_action"] == "BUY")
        check(105, "missing ML row creates no ML prediction record", ledger.connection.execute("SELECT COUNT(*) FROM stage5d4_ml_predictions").fetchone()[0] == ml_rows_before)

        duplicate_adapter, duplicate_dir = snapshot_fixture(Path(tmp) / "duplicate", [rec, rec])
        check(106, "duplicate matching Signal ID still fails", raises(lambda: overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T18:34:00Z", [], duplicate_adapter, duplicate_dir), "duplicate matching Signal ID"))

        corrupt_absent_adapter, corrupt_absent_dir = snapshot_fixture(Path(tmp) / "corrupt_absent", [rec], signal_ids=["OTHER_SIGNAL"])
        with (corrupt_absent_dir / "candidate_predictions.csv.gz").open("ab") as handle:
            handle.write(b"TAMPER")
        check(107, "corrupted snapshot with absent Signal ID fails before unavailable handling", raises(lambda: overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T18:35:00Z", [], corrupt_absent_adapter, corrupt_absent_dir), "SHA-256"))
        ledger.close()
        reopened = Stage5DLedger(db); reopened_overlay = Stage5D4Overlay(reopened)
        check(80, "Stage 5D.4 evidence survives close and reopen", reopened_overlay.get_overlay(combined["overlay_id"])["official_paper_action"] == "WAIT")
        reopened.close()

    source = (ROOT / "stage5d/news_ml_overlay.py").read_text(encoding="utf-8")
    tracked = subprocess.check_output(["git", "ls-files"], cwd=REPO, text=True).splitlines()
    check(64, "no performance-peeking report produced", not any("performance" in path.lower() and "stage5d4" in path.lower() for path in tracked))
    check(65, "no Stage 4A.3 writes", changed("stage5d3-daily-position-monitor-baseline", ["Stage 4A.3"]) == "")
    check(66, "no model refit", ".fit(" not in source and "refit(" not in source)
    check(67, "no model training", "sklearn" not in source and "xgboost" not in source and "lightgbm" not in source)
    check(68, "Stage 4A.3 changed files = 0", changed("stage5d3-daily-position-monitor-baseline", ["Stage 4A.3"]) == "")
    check(69, "Stage 2.2.2 changed files = 0", changed("stage5d3-daily-position-monitor-baseline", ["Stage 2.2.2 Final"]) == "")
    check(70, "Stage 2B.1 changed files = 0", changed("stage5d3-daily-position-monitor-baseline", ["Stage 2B.1"]) == "")
    stage5d1_semantic = [
        "Stage 5D/stage5d/__init__.py", "Stage 5D/stage5d/allocator.py", "Stage 5D/stage5d/horizon.py",
        "Stage 5D/stage5d/portfolio_state.py", "Stage 5D/stage5d/recommendation_contract.py",
        "Stage 5D/stage5d/source_contract.py", "Stage 5D/stage5d/user_profile.py",
    ]
    check(71, "Stage 5D.1 semantic files changed = 0", changed("stage5d3-daily-position-monitor-baseline", stage5d1_semantic) == "")
    check(72, "Stage 5D.2 ledger files changed = 0", changed("stage5d3-daily-position-monitor-baseline", ["Stage 5D/stage5d/ledger.py", "Stage 5D/stage5d/ledger_schema.py"]) == "")
    stage5d3_semantic = [
        "Stage 5D/stage5d/management_contract.py", "Stage 5D/stage5d/management_policy.py",
        "Stage 5D/stage5d/management_store.py", "Stage 5D/stage5d/market_observation.py",
        "Stage 5D/stage5d/position_monitor.py",
    ]
    check(73, "Stage 5D.3 semantic files changed = 0", changed("stage5d3-daily-position-monitor-baseline", stage5d3_semantic) == "")
    r1 = subprocess.run([sys.executable, str(ROOT / "tests/run_stage5d1_tests.py")], cwd=REPO, text=True, capture_output=True)
    r2 = subprocess.run([sys.executable, str(ROOT / "tests/run_stage5d2_tests.py")], cwd=REPO, text=True, capture_output=True)
    r3 = subprocess.run([sys.executable, str(ROOT / "tests/run_stage5d3_tests.py")], cwd=REPO, text=True, capture_output=True)
    check(74, "Stage 5D.1 80/80 regression PASS", r1.returncode == 0 and '"PASS": 80' in r1.stdout, (r1.stdout + r1.stderr)[-500:])
    check(75, "Stage 5D.2 129/129 regression PASS", r2.returncode == 0 and '"PASS": 129' in r2.stdout, (r2.stdout + r2.stderr)[-500:])
    check(76, "Stage 5D.3 130/130 regression PASS", r3.returncode == 0 and '"PASS": 130' in r3.stdout, (r3.stdout + r3.stderr)[-500:])
    check(77, "no runtime SQLite database committed", not any(path.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm")) for path in tracked))
    check(78, "Stage 5D.4 core has no network dependency", all(token not in source for token in ("requests", "urllib", "http.client", "socket")))
    check(79, "Stage 5D.4 core has no execution API", all(token not in source for token in ("record_recommendation_fill", "record_user_sell", "place_order", "broker")))

    results = ROOT / "results"
    ordered = sorted(rows, key=lambda item: int(item["Test Number"]))
    with (results / "stage5d4_test_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ordered[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(ordered)
    write_json(results / "stage5d4_schema.json", schema_payload())
    write_json(results / "stage5d4_news_contract.json", news_contract_payload())
    write_json(results / "stage5d4_ml_shadow_contract.json", ml_shadow_contract_payload())
    counts = {status: sum(row["Status"] == status for row in rows) for status in ("PASS", "FAIL")}
    print(json.dumps(counts, sort_keys=True))
    for row in ordered:
        if row["Status"] == "FAIL":
            print(json.dumps(row, sort_keys=True))
    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
