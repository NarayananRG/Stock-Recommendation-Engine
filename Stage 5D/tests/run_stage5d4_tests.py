from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

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
from stage5d.user_profile import InvestmentProfile


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
    published: str = "2026-09-14T10:00:00Z",
) -> dict[str, object]:
    return {
        "event_id": event_id, "ticker": ticker, "headline": f"{category} event {event_id}",
        "source": "TEST_WIRE", "source_url": None, "published_at_utc": published,
        "observed_at_utc": published, "event_date": published[:10], "category": category,
        "sentiment": sentiment, "severity": severity, "materiality": materiality,
        "confidence": "0.90", "summary": f"Explicit {category.lower()} evidence.", "source_hash": None,
    }


def ml(rec: dict[str, object], prediction_id: str = "ML_1", probability: str = "0.79", **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "ml_prediction_id": prediction_id, "recommendation_id": rec["recommendation_id"],
        "signal_id": rec["signal_id"], "ticker": rec["ticker"],
        "protocol_id": FROZEN_ML_PROTOCOL_ID, "model_bundle_hash": FROZEN_ML_MODEL_BUNDLE_HASH,
        "protocol_commit": FROZEN_ML_PROTOCOL_COMMIT, "snapshot_signal_date": rec["signal_date"],
        "snapshot_content_hash": "a" * 64,
        "prediction_at_utc": "2026-09-14T15:00:00Z", "probability": probability,
        "eligibility_status": "ELIGIBLE",
    }
    value.update(changes)
    return value


def raises(call, text: str = "") -> bool:
    try:
        call()
    except (ValueError, RuntimeError) as exc:
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

        with_ml = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T16:00:00Z", [], ml(rec))
        check(39, "ML prediction persisted", ledger.connection.execute("SELECT COUNT(*) FROM stage5d4_ml_predictions WHERE ml_prediction_id='ML_1'").fetchone()[0] == 1)
        missing_ml = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T16:01:00Z", [])
        check(40, "ML unavailable handled", missing_ml["ml_shadow_classification"] == "ML_NOT_AVAILABLE" and missing_ml["official_paper_action"] == "BUY")
        high_ml = with_ml
        low_ml = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T16:02:00Z", [], ml(rec, "ML_LOW", "0.10"))
        check(41, "ML high score cannot change official action", high_ml["official_paper_action"] == high_ml["deterministic_action"] == "BUY")
        check(42, "ML low score cannot change official action", low_ml["official_paper_action"] == low_ml["deterministic_action"] == "BUY")
        check(43, "ML cannot change quantity", high_ml["official_quantity"] == low_ml["official_quantity"] == rec["recommended_quantity"])
        check(44, "ML cannot change stop", Decimal(str(high_ml["official_stop"])) == Decimal(str(low_ml["official_stop"])) == Decimal(str(rec["stop"])))
        check(45, "ML cannot change target", Decimal(str(high_ml["official_target_1"])) == Decimal(str(low_ml["official_target_1"])) == Decimal(str(rec["target_1"])) and Decimal(str(high_ml["official_target_2"])) == Decimal(str(low_ml["official_target_2"])) == Decimal(str(rec["target_2"])))
        check(46, "ML cannot change horizon", high_ml["official_horizon"] == low_ml["official_horizon"] == rec["selected_horizon"])
        check(47, "ML cannot change ranking identity", high_ml["official_ranking_identity"] == low_ml["official_ranking_identity"] == rec["allocation_run_id"])
        stored_ml = json.loads(ledger.connection.execute("SELECT canonical_payload_json FROM stage5d4_ml_predictions WHERE ml_prediction_id='ML_1'").fetchone()[0])
        check(48, "frozen Stage 4A.3 identity persisted", high_ml["ml_protocol_id"] == FROZEN_ML_PROTOCOL_ID and stored_ml["model_bundle_hash"] == FROZEN_ML_MODEL_BUNDLE_HASH and stored_ml["protocol_commit"] == FROZEN_ML_PROTOCOL_COMMIT and stored_ml["snapshot_content_hash"] == "a" * 64)
        wrong_protocol = ml(rec, "ML_BAD", protocol_id="OTHER")
        check(49, "non-frozen ML protocol rejected", raises(lambda: overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T16:03:00Z", [], wrong_protocol), "not from the frozen"))
        future_ml = ml(rec, "ML_FUTURE", prediction_at_utc="2026-09-15T00:00:00Z")
        check(50, "future ML prediction rejected", raises(lambda: overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T16:03:00Z", [], future_ml), "later than"))

        combined_event = news("COMBINED", category="REGULATORY")
        combined = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T17:00:00Z", [combined_event], ml(rec, "ML_COMBINED"))
        check(51, "deterministic news and ML record persisted", combined["official_paper_action"] == "WAIT" and combined["ml_shadow_classification"] == "ML_SUPPORTS")
        repeated = overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T17:00:00Z", [combined_event], ml(rec, "ML_COMBINED"))
        check(52, "exact overlay rerun idempotent", repeated["status"] == "IDEMPOTENT_SUCCESS" and repeated["overlay_id"] == combined["overlay_id"])
        altered = news("ALTERED", severity="MEDIUM")
        check(53, "conflicting overlay rejected", raises(lambda: overlay.evaluate_recommendation_overlay(rec_id, "2026-09-14T17:00:00Z", [altered], ml(rec, "ML_COMBINED")), "conflicting immutable Stage 5D.4 overlay"))
        stored = overlay.get_overlay(combined["overlay_id"])
        check(54, "overlay recommendation lineage verified", stored["recommendation_id"] == rec_id)
        check(55, "overlay signal lineage verified", stored["signal_id"] == rec["signal_id"])
        check(56, "overlay ticker lineage verified", stored["ticker"] == rec["ticker"])
        check(57, "overlay cutoff binding verified", stored["decision_cutoff_utc"] == "2026-09-14T17:00:00.000000Z")
        check(58, "R0 evidence preserved", stored["research_views"]["R0"]["action"] == "BUY")
        check(59, "R1 evidence preserved", stored["research_views"]["R1"]["action"] == "WAIT")
        check(60, "R2 shadow evidence preserved", stored["research_views"]["R2"]["research_only"] and stored["research_views"]["R2"]["ml_shadow"] == "ML_SUPPORTS")
        check(61, "R3 shadow evidence preserved", stored["research_views"]["R3"]["research_only"] and stored["research_views"]["R3"]["action"] == "WAIT")

        second_allocation = allocate_candidates(profile(), [], [candidate("BBB.NS")])
        ledger.persist_allocation_result(second_allocation)
        rec2 = dict(second_allocation.recommendations[0])
        batch = overlay.evaluate_daily_overlays(
            [rec_id, str(rec2["recommendation_id"])], "2026-09-14T18:00:00Z",
            {"AAA.NS": [news("BATCH_A")], "BBB.NS": [news("BATCH_B", ticker="BBB.NS", sentiment="POSITIVE", category="LARGE_ORDER")]},
            {rec_id: ml(rec, "ML_BATCH_A"), str(rec2["recommendation_id"]): ml(rec2, "ML_BATCH_B", "0.50")},
        )
        check(62, "batch API evaluates multiple recommendations", len(batch) == 2 and {item["ticker"] for item in batch} == {"AAA.NS", "BBB.NS"})
        integrity = overlay.integrity_check()
        check(63, "Stage 5D.4 immutable integrity checks pass", integrity["ok"], json.dumps(integrity, sort_keys=True))
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
