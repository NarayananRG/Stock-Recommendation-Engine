from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from stage5d.allocator import AllocationResult, allocate_candidates
from stage5d.horizon import HorizonPreference
from stage5d.ledger import COST_BASIS_METHOD, Stage5DLedger, payload_sha256
from stage5d.ledger_schema import SCHEMA_VERSION, TABLES
from stage5d.portfolio_state import OpenPosition
from stage5d.user_profile import InvestmentProfile


def profile() -> InvestmentProfile:
    return InvestmentProfile(1, "2026-09-13T00:00:00+00:00", Decimal("20000"), HorizonPreference.THREE_MONTHS)


def candidate(ticker: str = "AAA.NS", signal: str = "BUY") -> dict[str, object]:
    return {
        "ticker": ticker, "signal_date": "2026-09-14", "deterministic_signal": signal,
        "setup": "PULLBACK", "trade_quality": "GOOD", "technical_score": 80,
        "actionability_score": 85, "market_regime": "BULLISH", "market_score": 75,
        "entry_low": 99, "entry_high": 100, "sizing_entry_price": 100, "stop": 99,
        "target_1": 110, "target_2": 120, "planned_rr_t1": 10, "planned_rr_t2": 20,
        "rs60": 5, "deterministic_rank": 1,
    }


def allocation(ticker: str = "AAA.NS", signal: str = "BUY") -> AllocationResult:
    return allocate_candidates(profile(), [], [candidate(ticker, signal)])


def raises(call, text: str = "") -> bool:
    try:
        call()
    except (ValueError, RuntimeError) as exc:
        return text.lower() in str(exc).lower()
    return False


def main() -> int:
    rows: list[dict[str, object]] = []

    def check(number: int, name: str, passed: bool, details: str = "") -> None:
        rows.append({"Test Number": number, "Test": name, "Status": "PASS" if passed else "FAIL", "Details": details})

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "core.sqlite3"
        ledger = Stage5DLedger(db)
        check(1, "fresh database initializes schema v1", ledger.schema_version == SCHEMA_VERSION and all(ledger.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() for table in TABLES))
        check(2, "foreign keys enabled", ledger.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1)
        result = allocation()
        rec_id = str(result.recommendations[0]["recommendation_id"])
        original = deepcopy(result.recommendations[0])
        check(3, "allocation result persists", ledger.persist_allocation_result(result).status == "CREATED" and ledger.get_allocation_run(result.allocation_run_id) is not None)
        stored = ledger.get_recommendation(rec_id)
        check(4, "recommendation fields round-trip", stored is not None and stored["recommendation_id"] == original["recommendation_id"] and stored["ticker"] == original["ticker"] and Decimal(stored["sizing_entry_price"]) == Decimal(str(original["sizing_entry_price"])) and set(stored) == set(original))
        zero = allocate_candidates(profile(), [], [], decision_date="2026-09-15")
        ledger.persist_allocation_result(zero)
        check(5, "zero-candidate day persists", ledger.get_allocation_run(zero.allocation_run_id)["recommendations"] == [] and ledger.connection.execute("SELECT recommendation_count FROM allocation_runs WHERE allocation_run_id=?", (zero.allocation_run_id,)).fetchone()[0] == 0)
        check(6, "identical allocation re-persist is idempotent", ledger.persist_allocation_result(result).status == "IDEMPOTENT_SUCCESS")
        changed_recs = [dict(result.recommendations[0])]
        changed_recs[0]["plain_language_reason"] = "tampered"
        changed_result = AllocationResult(result.allocation_run_id, tuple(changed_recs), result.portfolio_summary, result.portfolio_snapshot)
        check(7, "conflicting same allocation_run_id fails", raises(lambda: ledger.persist_allocation_result(changed_result), "conflicting"))
        other = allocation("BBB.NS")
        conflicting_rec = dict(other.recommendations[0]); conflicting_rec["recommendation_id"] = rec_id
        conflicting_child = AllocationResult(other.allocation_run_id, (conflicting_rec,), other.portfolio_summary, other.portfolio_snapshot)
        check(8, "conflicting same recommendation_id fails", raises(lambda: ledger.persist_allocation_result(conflicting_child), "atomically"))
        atomic = allocation("CCC.NS")
        duplicate = AllocationResult(atomic.allocation_run_id, (atomic.recommendations[0], atomic.recommendations[0]), atomic.portfolio_summary, atomic.portfolio_snapshot)
        check(9, "allocation persistence atomic rollback on child failure", raises(lambda: ledger.persist_allocation_result(duplicate), "atomically") and ledger.get_allocation_run(atomic.allocation_run_id) is None)
        ledger.mark_declined(rec_id, "2026-09-14", idempotency_key="decline-core")
        check(10, "recommendation remains immutable after later events", ledger.get_recommendation(rec_id) == stored)
        ledger.close()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "tx.sqlite3")
        result = allocation(); ledger.persist_allocation_result(result); rec_id = str(result.recommendations[0]["recommendation_id"])
        buy = ledger.append_transaction(ticker="AAA.NS", trade_date="2026-09-15", side="BUY", quantity=10, price_inr="100.25", fees_inr="2.50", idempotency_key="buy-1", recommendation_id=rec_id)
        check(11, "BUY transaction persists", buy.status == "CREATED" and ledger.transactions_for_ticker("AAA.NS")[0]["price_inr"] == "100.25")
        sell = ledger.append_transaction(ticker="AAA.NS", trade_date="2026-09-16", side="SELL", quantity=2, price_inr=105, fees_inr=1, idempotency_key="sell-1")
        check(12, "SELL transaction persists", sell.status == "CREATED" and ledger.transactions_for_ticker("AAA.NS")[-1]["side"] == "SELL")
        check(13, "fractional quantity rejected", raises(lambda: ledger.append_transaction(ticker="X", trade_date="2026-09-15", side="BUY", quantity=1.5, price_inr=1, idempotency_key="bad-q1"), "whole-share"))
        check(14, "zero/negative quantity rejected", all(raises(lambda q=q: ledger.append_transaction(ticker="X", trade_date="2026-09-15", side="BUY", quantity=q, price_inr=1, idempotency_key=f"bad-q{q}"), "whole-share") for q in (0, -1)))
        check(15, "zero/negative price rejected", all(raises(lambda p=p: ledger.append_transaction(ticker="X", trade_date="2026-09-15", side="BUY", quantity=1, price_inr=p, idempotency_key=f"bad-p{p}"), "positive") for p in (0, -1)))
        check(16, "negative fees rejected", raises(lambda: ledger.append_transaction(ticker="X", trade_date="2026-09-15", side="BUY", quantity=1, price_inr=1, fees_inr=-1, idempotency_key="bad-fee"), "negative"))
        check(17, "duplicate transaction idempotency key identical is idempotent", ledger.append_transaction(ticker="AAA.NS", trade_date="2026-09-15", side="BUY", quantity=10, price_inr="100.25", fees_inr="2.50", idempotency_key="buy-1", recommendation_id=rec_id).status == "IDEMPOTENT_SUCCESS")
        check(18, "duplicate transaction idempotency key conflicting fails", raises(lambda: ledger.append_transaction(ticker="AAA.NS", trade_date="2026-09-15", side="BUY", quantity=9, price_inr="100.25", fees_inr="2.50", idempotency_key="buy-1", recommendation_id=rec_id), "conflicting"))
        check(19, "SELL above position quantity rejected", raises(lambda: ledger.append_transaction(ticker="AAA.NS", trade_date="2026-09-17", side="SELL", quantity=99, price_inr=105, idempotency_key="oversell"), "exceeds"))
        check(20, "no negative derived positions", all(item.quantity >= 0 for item in ledger.derive_positions()))
        check(21, "transaction linkage does not mutate recommendation", ledger.get_recommendation(rec_id) == json.loads(ledger.connection.execute("SELECT canonical_payload_json FROM recommendations WHERE recommendation_id=?", (rec_id,)).fetchone()[0]))
        ledger.void_transaction(sell.identity, idempotency_key="void-1", reason="mistake")
        check(22, "transaction void excludes original transaction", ledger.derive_positions()[0].quantity == 10)
        corrected = ledger.append_transaction(ticker="AAA.NS", trade_date="2026-09-16", side="SELL", quantity=3, price_inr=105, idempotency_key="sell-corrected")
        check(23, "corrected transaction can be appended after void", corrected.status == "CREATED" and ledger.derive_positions()[0].quantity == 7)
        check(24, "void history remains queryable", len(ledger.transaction_void_history(sell.identity)) == 1)
        ledger.close()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "positions.sqlite3")
        ledger.add_opening_position(ticker="TCS.NS", effective_date="2026-09-01", quantity=10, average_cost_per_share_inr=100, idempotency_key="open")
        check(25, "opening position import works", ledger.derive_positions()[0].quantity == 10)
        ledger.append_transaction(ticker="TCS.NS", trade_date="2026-09-02", side="BUY", quantity=10, price_inr=120, fees_inr=0, idempotency_key="pos-buy")
        check(26, "BUY increases quantity", ledger.derive_positions()[0].quantity == 20)
        ledger.append_transaction(ticker="TCS.NS", trade_date="2026-09-03", side="SELL", quantity=5, price_inr=130, fees_inr=0, idempotency_key="pos-sell")
        position = ledger.derive_positions()[0]
        check(27, "SELL decreases quantity", position.quantity == 15)
        check(28, "weighted-average cost basis correct", position.average_cost_per_share_inr == Decimal("110"))
        check(29, "SELL reduces basis using weighted average", position.cost_basis_total_inr == Decimal("1650") and COST_BASIS_METHOD == "WEIGHTED_AVERAGE_NON_TAX_COST_BASIS")
        adapter = ledger.build_allocator_open_positions({"TCS.NS": Decimal("140")})
        check(30, "build_allocator_open_positions returns Stage 5D.1 OpenPosition", isinstance(adapter[0], OpenPosition) and adapter[0].cost_basis_per_share_inr == Decimal("110"))
        check(31, "missing current price rejected clearly", raises(lambda: ledger.build_allocator_open_positions({}), "missing externally supplied"))
        before = ledger.transactions_for_ticker("TCS.NS")
        ledger.build_allocator_open_positions({"TCS.NS": 999})
        check(32, "current prices do not rewrite transaction history", before == ledger.transactions_for_ticker("TCS.NS"))
        ledger.close()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "pending.sqlite3")
        result = allocation(); ledger.persist_allocation_result(result); rec_id = str(result.recommendations[0]["recommendation_id"]); rec = result.recommendations[0]
        pending = ledger.mark_pending(rec_id, "2026-09-14", idempotency_key="pending")
        check(33, "actionable recommendation can become PENDING_ENTRY", pending.status == "CREATED")
        reservations = ledger.get_active_pending_reservations()
        check(34, "pending reservation returned to allocator", len(reservations) == 1 and reservations[0].source_recommendation_id == rec_id)
        ledger.record_recommendation_fill(rec_id, "2026-09-15", 10, 101, 0, "fill-part")
        remaining = ledger.get_active_pending_reservations()
        check(35, "partial fill reduces pending reservation", remaining[0].reserved_capital_inr == Decimal(str((rec["recommended_quantity"] - 10) * rec["sizing_entry_price"])))
        ledger.record_recommendation_fill(rec_id, "2026-09-16", rec["recommended_quantity"] - 10, 102, 0, "fill-rest")
        check(36, "full fill removes pending reservation", ledger.get_active_pending_reservations() == ())
        result2 = allocation("BBB.NS"); ledger.persist_allocation_result(result2); rec2 = str(result2.recommendations[0]["recommendation_id"])
        ledger.mark_pending(rec2, "2026-09-14", idempotency_key="pending2"); ledger.mark_cancelled(rec2, "2026-09-15", idempotency_key="cancel2")
        check(37, "cancelled recommendation removes pending reservation", all(item.source_recommendation_id != rec2 for item in ledger.get_active_pending_reservations()))
        result3 = allocation("CCC.NS"); ledger.persist_allocation_result(result3); rec3 = str(result3.recommendations[0]["recommendation_id"])
        ledger.mark_pending(rec3, "2026-09-14", idempotency_key="pending3"); ledger.mark_expired(rec3, "2026-09-15", idempotency_key="expire3")
        check(38, "expired recommendation removes pending reservation", all(item.source_recommendation_id != rec3 for item in ledger.get_active_pending_reservations()))
        result4 = allocation("DDD.NS"); ledger.persist_allocation_result(result4); rec4 = str(result4.recommendations[0]["recommendation_id"])
        count_before = ledger.connection.execute("SELECT COUNT(*) FROM user_transactions").fetchone()[0]
        ledger.mark_declined(rec4, "2026-09-14", idempotency_key="decline4")
        check(39, "declined recommendation creates no transaction", ledger.connection.execute("SELECT COUNT(*) FROM user_transactions").fetchone()[0] == count_before)
        fresh = allocation("EEE.NS"); ledger.persist_allocation_result(fresh)
        check(40, "recommendation persistence alone creates no BUY", ledger.transactions_for_recommendation(str(fresh.recommendations[0]["recommendation_id"])) == ())
        ledger.close()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "outcomes.sqlite3")
        result = allocation(); ledger.persist_allocation_result(result); rec_id = str(result.recommendations[0]["recommendation_id"])
        v1 = ledger.append_outcome_version(rec_id, as_of_date="2026-09-20", outcome_status="PENDING", methodology_version="M1", entry_filled=False)
        check(41, "outcome version 1 persists", v1.status == "CREATED" and ledger.latest_outcome(rec_id)["outcome_version"] == 1)
        v2 = ledger.append_outcome_version(rec_id, as_of_date="2026-09-21", outcome_status="RESOLVED", methodology_version="M1", entry_filled=True, target_1_hit=True)
        check(42, "outcome version 2 appends", v2.status == "CREATED" and len(ledger.outcome_history(rec_id)) == 2)
        check(43, "version 1 remains immutable", ledger.outcome_history(rec_id)[0]["outcome_status"] == "PENDING")
        check(44, "latest_outcome returns highest version", ledger.latest_outcome(rec_id)["outcome_version"] == 2)
        check(45, "conflicting same version rejected", raises(lambda: ledger.append_outcome_version(rec_id, as_of_date="2026-09-22", outcome_status="CENSORED", methodology_version="M1", outcome_version=2), "conflicting"))
        check(46, "outcome may exist even if user never bought", ledger.transactions_for_recommendation(rec_id) == () and ledger.latest_outcome(rec_id) is not None)
        ledger.append_transaction(ticker="AAA.NS", trade_date="2026-09-22", side="BUY", quantity=1, price_inr=99, idempotency_key="separate-user", recommendation_id=rec_id)
        check(47, "actual user PnL data remains separate from recommendation outcome", "price_inr" in ledger.transactions_for_recommendation(rec_id)[0] and "price_inr" not in ledger.latest_outcome(rec_id))
        ledger.close()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "snapshots.sqlite3")
        ledger.add_opening_position(ticker="INFY.NS", effective_date="2026-09-01", quantity=2, average_cost_per_share_inr=100, idempotency_key="snap-open")
        snap = ledger.persist_position_snapshots("2026-09-20", {"INFY.NS": 110})
        check(48, "position-state snapshot persists", snap[0].status == "CREATED" and ledger.position_snapshots()[0]["market_value_inr"] == "220")
        check(49, "identical snapshot idempotent", ledger.persist_position_snapshots("2026-09-20", {"INFY.NS": 110})[0].status == "IDEMPOTENT_SUCCESS")
        check(50, "conflicting snapshot identity rejected", raises(lambda: ledger.persist_position_snapshots("2026-09-20", {"INFY.NS": 111}), "conflicting"))
        check(51, "snapshot does not alter transaction source of truth", ledger.transactions_for_ticker("INFY.NS") == () and ledger.derive_positions()[0].quantity == 2)
        report = ledger.integrity_check()
        check(52, "PRAGMA integrity_check passes", report["checks"]["sqlite_integrity"])
        check(53, "foreign-key check passes", report["checks"]["foreign_keys"])
        ledger.close()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "integrity.sqlite3")
        result = allocation(); ledger.persist_allocation_result(result); rec_id = str(result.recommendations[0]["recommendation_id"])
        ledger.append_transaction(ticker="AAA.NS", trade_date="2026-09-15", side="BUY", quantity=1, price_inr=100, idempotency_key="integrity-buy")
        ledger.append_outcome_version(rec_id, as_of_date="2026-09-20", outcome_status="PENDING", methodology_version="M1")
        report = ledger.integrity_check()
        check(54, "stored recommendation hashes verify", report["checks"]["recommendations_hashes"])
        check(55, "stored allocation hashes verify", report["checks"]["allocation_runs_hashes"])
        check(56, "transaction hashes verify", report["checks"]["user_transactions_hashes"])
        check(57, "outcome hashes verify", report["checks"]["recommendation_outcome_versions_hashes"])
        with ledger.connection:
            ledger.connection.execute("UPDATE recommendations SET canonical_payload_json='{}' WHERE recommendation_id=?", (rec_id,))
        check(58, "integrity report catches deliberate tamper in isolated database", not ledger.integrity_check()["ok"])
        ledger.close()

    def changed(path: str) -> str:
        return subprocess.check_output(["git", "diff", "--name-only", "stage5d1-portfolio-allocator-baseline", "--", path], cwd=REPO, text=True).strip()

    changed_4a3, changed_222, changed_2b1 = changed("Stage 4A.3"), changed("Stage 2.2.2 Final"), changed("Stage 2B.1")
    check(59, "Stage 4A.3 changed files = 0", changed_4a3 == "", changed_4a3)
    check(60, "Stage 2.2.2 changed files = 0", changed_222 == "", changed_222)
    check(61, "Stage 2B.1 changed files = 0", changed_2b1 == "", changed_2b1)
    regression = subprocess.run([sys.executable, str(ROOT / "tests" / "run_stage5d1_tests.py")], cwd=REPO, text=True, capture_output=True)
    check(62, "frozen Stage 5D.1 allocator behavioral regression suite still passes", regression.returncode == 0 and '"FAIL": 0' in regression.stdout and '"PASS": 80' in regression.stdout, (regression.stdout + regression.stderr).strip())
    base_candidate = candidate(); ml_candidate = deepcopy(base_candidate); ml_candidate.update({"ml_probability": 0.99, "confidence": "HIGH", "R3 Score": 1})
    check(63, "ML fields still do not affect Stage 5D.1 decisions", allocate_candidates(profile(), [], [base_candidate]) == allocate_candidates(profile(), [], [ml_candidate]))
    tracked = subprocess.check_output(["git", "ls-files"], cwd=REPO, text=True).splitlines()
    check(64, "no runtime database committed to Git", not any(item.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm")) for item in tracked))

    with tempfile.TemporaryDirectory() as tmp:
        durability_path = Path(tmp) / "durability.sqlite3"
        ledger = Stage5DLedger(durability_path)
        ledger.add_opening_position(ticker="DUR.NS", effective_date="2026-09-01", quantity=10, average_cost_per_share_inr=90, idempotency_key="dur-open")
        buy = ledger.append_transaction(ticker="DUR.NS", trade_date="2026-09-02", side="BUY", quantity=5, price_inr=100, idempotency_key="dur-buy")
        sell = ledger.append_transaction(ticker="DUR.NS", trade_date="2026-09-03", side="SELL", quantity=2, price_inr=110, idempotency_key="dur-sell")
        fill_result = allocation("FILL.NS"); ledger.persist_allocation_result(fill_result)
        fill_rec = str(fill_result.recommendations[0]["recommendation_id"])
        ledger.record_recommendation_fill(fill_rec, "2026-09-04", 1, 100, 0, "dur-fill")
        failed_result = allocation("FAIL.NS"); ledger.persist_allocation_result(failed_result)
        failed_rec = str(failed_result.recommendations[0]["recommendation_id"])
        ledger.connection.execute("""CREATE TRIGGER force_fill_event_failure BEFORE INSERT ON recommendation_events WHEN NEW.idempotency_key='FILL_EVENT:failed-fill' BEGIN SELECT RAISE(ABORT,'forced fill event failure'); END""")
        failed_atomic = raises(lambda: ledger.record_recommendation_fill(failed_rec, "2026-09-04", 1, 100, 0, "failed-fill"), "atomically")
        before_reopen = ledger.derive_positions()
        ledger.close()
        ledger = Stage5DLedger(durability_path)
        check(65, "standalone BUY survives close/reopen", any(item["transaction_id"] == buy.identity for item in ledger.transactions_for_ticker("DUR.NS")))
        check(66, "standalone SELL survives close/reopen", any(item["transaction_id"] == sell.identity for item in ledger.transactions_for_ticker("DUR.NS")))
        check(67, "position state survives close/reopen", ledger.derive_positions() == before_reopen)
        check(68, "transaction idempotency survives reopen", ledger.append_transaction(ticker="DUR.NS", trade_date="2026-09-02", side="BUY", quantity=5, price_inr=100, idempotency_key="dur-buy").status == "IDEMPOTENT_SUCCESS")
        fill_events = [event for event in ledger.recommendation_event_history(fill_rec) if event["event_type"] in {"PARTIALLY_FILLED", "FILLED"}]
        check(69, "recommendation fill transaction+event survive reopen", len(ledger.transactions_for_recommendation(fill_rec)) == 1 and len(fill_events) == 1)
        failed_events = [event for event in ledger.recommendation_event_history(failed_rec) if event["event_type"] in {"PARTIALLY_FILLED", "FILLED"}]
        check(70, "failed fill writes neither transaction nor event after reopen", failed_atomic and ledger.transactions_for_recommendation(failed_rec) == () and failed_events == [])
        ledger.close()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "chronology.sqlite3")
        ledger.add_opening_position(ticker="CHRON.NS", effective_date="2026-09-01", quantity=10, average_cost_per_share_inr=100, idempotency_key="chron-open")
        ledger.append_transaction(ticker="CHRON.NS", trade_date="2026-09-20", side="SELL", quantity=8, price_inr=120, idempotency_key="chron-later-sell")
        tx_count = ledger.connection.execute("SELECT COUNT(*) FROM user_transactions").fetchone()[0]
        rejected_backdated = raises(lambda: ledger.append_transaction(ticker="CHRON.NS", trade_date="2026-09-10", side="SELL", quantity=5, price_inr=110, idempotency_key="chron-backdated"), "chronology")
        check(71, "backdated SELL that breaks later chronology rejected", rejected_backdated)
        check(72, "failed backdated SELL leaves DB unchanged", ledger.connection.execute("SELECT COUNT(*) FROM user_transactions").fetchone()[0] == tx_count and not ledger.transactions_for_ticker("CHRON.NS")[-1]["trade_date"] == "2026-09-10")
        ledger.append_transaction(ticker="VOID.NS", trade_date="2026-09-01", side="BUY", quantity=10, price_inr=100, idempotency_key="void-buy")
        ledger.append_transaction(ticker="VOID.NS", trade_date="2026-09-02", side="SELL", quantity=10, price_inr=110, idempotency_key="void-sell")
        void_buy_id = ledger.transactions_for_ticker("VOID.NS")[0]["transaction_id"]
        unsafe_void = raises(lambda: ledger.void_transaction(void_buy_id, idempotency_key="unsafe-void", reason="would break history"), "chronology")
        check(73, "voiding BUY that would invalidate later SELL rejected", unsafe_void)
        check(74, "failed void leaves original transaction active", ledger.transaction_void_history(void_buy_id) == () and len(ledger.transactions_for_ticker("VOID.NS")) == 2)
        ledger.add_opening_position(ticker="SAFE.NS", effective_date="2026-09-01", quantity=10, average_cost_per_share_inr=100, idempotency_key="safe-open")
        safe_buy = ledger.append_transaction(ticker="SAFE.NS", trade_date="2026-09-02", side="BUY", quantity=1, price_inr=100, idempotency_key="safe-buy")
        ledger.void_transaction(safe_buy.identity, idempotency_key="safe-void", reason="duplicate")
        same_void_idempotent = ledger.void_transaction(safe_buy.identity, idempotency_key="safe-void", reason="duplicate").status == "IDEMPOTENT_SUCCESS"
        check(75, "second distinct void of already-void transaction rejected", same_void_idempotent and raises(lambda: ledger.void_transaction(safe_buy.identity, idempotency_key="safe-void-2", reason="again"), "already voided"))
        ledger.close()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "linkage.sqlite3")
        result = allocation("LINK.NS"); ledger.persist_allocation_result(result); rec = result.recommendations[0]; rec_id = str(rec["recommendation_id"])
        check(76, "recommendation-linked wrong ticker rejected", raises(lambda: ledger.append_transaction(ticker="WRONG.NS", trade_date="2026-09-15", side="BUY", quantity=1, price_inr=100, recommendation_id=rec_id, idempotency_key="wrong-ticker"), "ticker"))
        check(77, "supplied wrong Signal ID rejected", raises(lambda: ledger.append_transaction(ticker="LINK.NS", trade_date="2026-09-15", side="BUY", quantity=1, price_inr=100, recommendation_id=rec_id, signal_id="SIG_WRONG", idempotency_key="wrong-signal"), "signal_id"))
        inherited = ledger.append_transaction(ticker="LINK.NS", trade_date="2026-09-15", side="BUY", quantity=1, price_inr=100, recommendation_id=rec_id, idempotency_key="inherit-signal")
        inherited_payload = [item for item in ledger.transactions_for_recommendation(rec_id) if item["transaction_id"] == inherited.identity][0]
        check(78, "omitted Signal ID inherits recommendation Signal ID", inherited_payload["signal_id"] == rec["signal_id"])
        ledger.close()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "pending-hardening.sqlite3")
        custom = allocation("CUSTOM.NS"); ledger.persist_allocation_result(custom); custom_rec = str(custom.recommendations[0]["recommendation_id"])
        ledger.mark_pending(custom_rec, "2026-09-14", reservation_price_basis=95, idempotency_key="custom-pending")
        ledger.record_recommendation_fill(custom_rec, "2026-09-15", 10, 96, 0, "custom-partial")
        custom_reservation = [item for item in ledger.get_active_pending_reservations() if item.source_recommendation_id == custom_rec][0]
        expected_custom = Decimal("95") * (int(custom.recommendations[0]["recommended_quantity"]) - 10)
        check(79, "custom pending price basis survives partial fill", custom_reservation.reserved_capital_inr == expected_custom)
        implicit = allocation("IMPLICIT.NS"); ledger.persist_allocation_result(implicit); implicit_rec = str(implicit.recommendations[0]["recommendation_id"])
        ledger.record_recommendation_fill(implicit_rec, "2026-09-15", 10, 101, 0, "implicit-partial")
        implicit_reservation = [item for item in ledger.get_active_pending_reservations() if item.source_recommendation_id == implicit_rec][0]
        expected_implicit = Decimal(str(implicit.recommendations[0]["sizing_entry_price"])) * (int(implicit.recommendations[0]["recommended_quantity"]) - 10)
        check(80, "partial fill without prior PENDING_ENTRY creates remaining reservation", implicit_reservation.reserved_capital_inr == expected_implicit)
        declined = allocation("DECLINE.NS"); ledger.persist_allocation_result(declined); declined_rec = str(declined.recommendations[0]["recommendation_id"])
        ledger.mark_pending(declined_rec, "2026-09-14", idempotency_key="decline-pending"); ledger.mark_declined(declined_rec, "2026-09-15", idempotency_key="decline-terminal")
        check(81, "DECLINED clears pending reservation", all(item.source_recommendation_id != declined_rec for item in ledger.get_active_pending_reservations()))
        check(82, "terminal recommendation cannot be re-pended", raises(lambda: ledger.mark_pending(declined_rec, "2026-09-16", idempotency_key="decline-reactivate"), "terminal"))
        ledger.close()

    def tamper_ledger() -> tuple[tempfile.TemporaryDirectory[str], Stage5DLedger, AllocationResult, str]:
        directory = tempfile.TemporaryDirectory()
        ledger = Stage5DLedger(Path(directory.name) / "tamper.sqlite3")
        result = allocation(); ledger.persist_allocation_result(result)
        return directory, ledger, result, str(result.recommendations[0]["recommendation_id"])

    directory, ledger, result, rec_id = tamper_ledger()
    ledger.add_opening_position(ticker="AAA.NS", effective_date="2026-09-01", quantity=10, average_cost_per_share_inr=90, idempotency_key="tamper-open")
    transaction = ledger.append_transaction(ticker="AAA.NS", trade_date="2026-09-15", side="BUY", quantity=1, price_inr=100, idempotency_key="tamper-tx")
    with ledger.connection: ledger.connection.execute("UPDATE user_transactions SET quantity=999 WHERE transaction_id=?", (transaction.identity,))
    check(83, "typed-only transaction quantity tamper detected", not ledger.integrity_check()["checks"]["transaction_typed_columns"])
    ledger.close(); directory.cleanup()
    directory, ledger, result, rec_id = tamper_ledger()
    transaction = ledger.append_transaction(ticker="AAA.NS", trade_date="2026-09-15", side="BUY", quantity=1, price_inr=100, idempotency_key="tamper-price")
    with ledger.connection: ledger.connection.execute("UPDATE user_transactions SET price_inr='999' WHERE transaction_id=?", (transaction.identity,))
    check(84, "typed-only transaction price tamper detected", not ledger.integrity_check()["checks"]["transaction_typed_columns"])
    ledger.close(); directory.cleanup()
    directory, ledger, result, rec_id = tamper_ledger()
    with ledger.connection: ledger.connection.execute("UPDATE recommendations SET ticker='TAMPER.NS' WHERE recommendation_id=?", (rec_id,))
    check(85, "typed-only recommendation tamper detected", not ledger.integrity_check()["checks"]["recommendation_typed_columns"])
    ledger.close(); directory.cleanup()
    directory, ledger, result, rec_id = tamper_ledger()
    with ledger.connection: ledger.connection.execute("UPDATE recommendation_events SET event_type='DECLINED' WHERE recommendation_id=?", (rec_id,))
    check(86, "typed-only event lifecycle tamper detected", not ledger.integrity_check()["checks"]["event_typed_columns"])
    ledger.close(); directory.cleanup()
    directory, ledger, result, rec_id = tamper_ledger()
    ledger.connection.execute("PRAGMA foreign_keys=OFF")
    with ledger.connection:
        ledger.connection.execute("DELETE FROM recommendation_events WHERE recommendation_id=?", (rec_id,))
        ledger.connection.execute("DELETE FROM recommendations WHERE recommendation_id=?", (rec_id,))
    check(87, "missing recommendation child detected", not ledger.integrity_check()["checks"]["allocation_child_consistency"] and raises(lambda: ledger.persist_allocation_result(result), "missing recommendation"))
    ledger.close(); directory.cleanup()
    directory, ledger, result, rec_id = tamper_ledger()
    with ledger.connection: ledger.connection.execute("UPDATE allocation_runs SET recommendation_count=99 WHERE allocation_run_id=?", (result.allocation_run_id,))
    check(88, "wrong allocation recommendation_count detected", not ledger.integrity_check()["checks"]["allocation_child_consistency"])
    ledger.close(); directory.cleanup()
    directory, ledger, result, rec_id = tamper_ledger()
    with ledger.connection: ledger.connection.execute("UPDATE allocation_runs SET actionable_recommendation_count=0 WHERE allocation_run_id=?", (result.allocation_run_id,))
    check(89, "wrong actionable recommendation count detected", not ledger.integrity_check()["checks"]["allocation_child_consistency"])
    ledger.close(); directory.cleanup()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "outcome-validation.sqlite3")
        result = allocation(); ledger.persist_allocation_result(result); rec_id = str(result.recommendations[0]["recommendation_id"])
        check(90, "unknown outcome field rejected", raises(lambda: ledger.append_outcome_version(rec_id, as_of_date="2026-09-20", outcome_status="PENDING", methodology_version="M1", invented_field=1), "unknown outcome"))
        check(91, "invalid outcome boolean rejected", raises(lambda: ledger.append_outcome_version(rec_id, as_of_date="2026-09-20", outcome_status="PENDING", methodology_version="M1", entry_filled="yes"), "entry_filled"))
        check(92, "negative session count rejected", raises(lambda: ledger.append_outcome_version(rec_id, as_of_date="2026-09-20", outcome_status="PENDING", methodology_version="M1", holding_sessions=-1), "integer"))
        check(93, "non-finite outcome numeric rejected", raises(lambda: ledger.append_outcome_version(rec_id, as_of_date="2026-09-20", outcome_status="PENDING", methodology_version="M1", mfe_pct=float("nan")), "finite"))
        ledger.append_outcome_version(rec_id, as_of_date="2026-09-20", outcome_status="PENDING", methodology_version="M1", entry_date="2026-09-19T15:30:00+05:30")
        check(94, "entry_date canonicalized", ledger.latest_outcome(rec_id)["entry_date"] == "2026-09-19")
        ledger.close()

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Stage5DLedger(Path(tmp) / "unified-replay.sqlite3")
        ledger.append_transaction(ticker="ORDER.NS", trade_date="2026-09-01", side="BUY", quantity=10, price_inr=200, idempotency_key="order-buy")
        ledger.append_transaction(ticker="ORDER.NS", trade_date="2026-09-05", side="SELL", quantity=10, price_inr=210, idempotency_key="order-sell")
        ledger.add_opening_position(ticker="ORDER.NS", effective_date="2026-09-10", quantity=10, average_cost_per_share_inr=100, idempotency_key="order-open")
        check(95, "unified chronology handles opening + transactions by effective date", ledger.derive_positions()[0].average_cost_per_share_inr == Decimal("100"))
        ledger.add_opening_position(ticker="SAME.NS", effective_date="2026-09-20", quantity=2, average_cost_per_share_inr=50, idempotency_key="same-open")
        same_sell = ledger.append_transaction(ticker="SAME.NS", trade_date="2026-09-20", side="SELL", quantity=2, price_inr=55, idempotency_key="same-sell")
        check(96, "same-day opening is available before same-day transaction", same_sell.status == "CREATED" and all(item.ticker != "SAME.NS" for item in ledger.derive_positions()))
        ledger.close()

    check(97, "Stage 4A.3 changed files = 0 after hardening", changed_4a3 == "", changed_4a3)
    check(98, "Stage 2.2.2 changed files = 0 after hardening", changed_222 == "", changed_222)
    check(99, "Stage 2B.1 changed files = 0 after hardening", changed_2b1 == "", changed_2b1)
    frozen_semantic_files = ["Stage 5D/stage5d/allocator.py", "Stage 5D/stage5d/horizon.py", "Stage 5D/stage5d/portfolio_state.py", "Stage 5D/stage5d/source_contract.py", "Stage 5D/stage5d/user_profile.py", "Stage 5D/stage5d/recommendation_contract.py"]
    semantic_changes = subprocess.check_output(["git", "diff", "--name-only", "stage5d1-portfolio-allocator-baseline", "--", *frozen_semantic_files], cwd=REPO, text=True).strip()
    check(100, "frozen Stage 5D.1 semantic files changed = 0", semantic_changes == "", semantic_changes)
    check(101, "frozen Stage 5D.1 80/80 regression PASS", regression.returncode == 0 and '"FAIL": 0' in regression.stdout and '"PASS": 80' in regression.stdout, (regression.stdout + regression.stderr).strip())
    check(102, "ML user-facing influence remains NO", allocate_candidates(profile(), [], [base_candidate]) == allocate_candidates(profile(), [], [ml_candidate]))
    check(103, "no runtime SQLite DB tracked by Git after hardening", not any(item.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm")) for item in tracked))

    results = ROOT / "results"
    results.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: int(row["Test Number"]))
    with (results / "stage5d2_test_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ordered[0]))
        writer.writeheader(); writer.writerows(ordered)
    schema = {
        "schema_version": SCHEMA_VERSION, "engine": "SQLite via Python standard-library sqlite3",
        "journal_mode_file_backed": "WAL", "foreign_keys": True, "tables": list(TABLES),
        "money_storage": "canonical decimal strings", "runtime_database": "Stage 5D/data/stage5d.sqlite3 (gitignored)",
        "schema_change_for_stage5d2a": False,
        "hardening_implementation": "Python transaction ownership, unified chronological replay, and integrity validation",
    }
    (results / "stage5d2_schema.json").write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    contract = {
        "contract": "STAGE5D2_INTEGRITY_CONTRACT_V1", "schema_version": SCHEMA_VERSION,
        "canonical_json": "sort_keys=true,separators=(',', ':'),ensure_ascii=false,UTF-8",
        "hash": "SHA256", "immutable_entities": ["allocation_runs", "recommendations", "position_state_snapshots", "recommendation_outcome_versions"],
        "append_only_entities": ["recommendation_events", "user_transactions", "transaction_voids", "opening_positions"],
        "allocation_atomicity": True, "recommendation_fill_atomicity": True,
        "standalone_transaction_durability": "PUBLIC_APPEND_TRANSACTION_OWNS_AND_COMMITS_ATOMIC_TRANSACTION",
        "chronological_replay": "DATE_ASC_OPENING_BEFORE_TRANSACTION_SAME_DAY_THEN_STABLE_SEQUENCE",
        "retroactive_transaction_safety": "INSERT_THEN_REPLAY_COMPLETE_HISTORY_OR_ROLLBACK",
        "void_chronology_safety": "STAGE_VOID_THEN_REPLAY_COMPLETE_HISTORY_OR_ROLLBACK",
        "one_effective_void_per_transaction": True,
        "recommendation_linkage": "TICKER_AND_SIGNAL_ID_MUST_MATCH; OMITTED_SIGNAL_ID_INHERITED",
        "pending_terminal_states": ["DECLINED", "CANCELLED", "EXPIRED", "FILLED"],
        "partial_fill_without_pending": "CREATES_REMAINING_RESERVATION_AT_RECOMMENDATION_SIZING_PRICE",
        "custom_pending_price_basis_preserved": True,
        "position_source_of_truth": "opening positions plus non-void BUY minus non-void SELL",
        "cost_basis_method": COST_BASIS_METHOD, "tax_accounting": False,
        "outcome_versions": "strictly monotonic per recommendation; exact duplicates idempotent",
        "integrity_checks": ["PRAGMA integrity_check", "PRAGMA foreign_key_check", "payload hashes", "typed-column-to-payload binding", "derived identities", "recommendation lineage", "allocation child counts and embedded evidence", "nonnegative chronological positions", "single effective void", "outcome version continuity"],
        "outcome_input_validation": "ALLOWLISTED_FIELDS_CANONICAL_DATES_STRICT_BOOLEANS_NONNEGATIVE_SESSION_COUNTS_FINITE_DECIMALS",
        "broker_integration": False, "automatic_execution": False, "ml_user_facing_influence": False,
    }
    (results / "stage5d2_integrity_contract.json").write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = {status: sum(row["Status"] == status for row in rows) for status in ("PASS", "FAIL")}
    print(json.dumps(counts, sort_keys=True))
    if counts["FAIL"]:
        for row in ordered:
            if row["Status"] == "FAIL":
                print(json.dumps(row, sort_keys=True))
    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
