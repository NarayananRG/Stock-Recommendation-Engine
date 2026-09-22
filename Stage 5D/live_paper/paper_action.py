"""Explicit, user-recorded paper lifecycle actions; never broker orders."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

_STAGE = Path(__file__).resolve().parents[1]
if str(_STAGE) not in sys.path:
    sys.path.insert(0, str(_STAGE))

from live_paper.admission import admission_status, available_slots
from live_paper.run_after_close import STAGE_ROOT, _config, _database_path, _existing_run, _initialize_runs, verify_live_run_integrity
from stage5d.ledger import Stage5DLedger
from stage5d.management_store import Stage5D3Manager
from stage5d.news_ml_overlay import Stage5D4Overlay
from stage5d.portfolio_state import whole_share_quantity


def _latest_report(ledger: Stage5DLedger) -> dict:
    row = ledger.connection.execute(
        "SELECT market_session_date FROM stage5d5_live_runs ORDER BY market_session_date DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("No completed live-paper report exists")
    return _existing_run(ledger, str(row[0]))


def _report_recommendation(report: dict, recommendation_id: str) -> dict:
    matches = [item for item in report["recommendations"]
               if item["recommendation"]["recommendation_id"] == recommendation_id]
    if len(matches) != 1:
        raise ValueError("Recommendation is not in the latest completed live-paper report")
    return matches[0]


def _linked_managed_quantity(ledger: Stage5DLedger, recommendation: dict) -> int:
    total = 0
    for transaction in ledger.transactions_for_recommendation(recommendation["recommendation_id"]):
        if transaction["ticker"] != recommendation["ticker"] or transaction["signal_id"] != recommendation["signal_id"]:
            raise RuntimeError("INCONSISTENT_TRANSACTION_LINEAGE")
        if ledger.transaction_void_history(transaction["transaction_id"]):
            continue
        total += int(transaction["quantity"]) * (1 if transaction["side"] == "BUY" else -1)
    if total < 0:
        raise RuntimeError("INCONSISTENT_MANAGED_QUANTITY")
    return total


def record_action(ledger: Stage5DLedger, action: str, recommendation_id: str,
                  *, quantity: int | None = None, price: str | None = None,
                  idempotency_key: str | None = None) -> dict:
    recommendation = ledger.get_recommendation(recommendation_id)
    if recommendation is None:
        raise ValueError("Unknown recommendation")
    manager, overlay = Stage5D3Manager(ledger), Stage5D4Overlay(ledger)
    verify_live_run_integrity(ledger)
    if not ledger.integrity_check()["ok"] or not manager.integrity_check()["ok"] or not overlay.integrity_check()["ok"]:
        raise RuntimeError("DATABASE_INTEGRITY_FAILURE")
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    key = idempotency_key or f"S5D5:{action}:{recommendation_id}:{today}:{quantity}:{price}"
    if action == "pending":
        ledger.connection.execute("BEGIN IMMEDIATE")
        try:
            report = _latest_report(ledger)
            item = _report_recommendation(report, recommendation_id)
            positions = ledger.derive_positions()
            pending = ledger.get_active_pending_reservations()
            status = admission_status(recommendation, item["overlay"], item["news_status"],
                                      (position.ticker for position in positions), pending)
            if status != "ADMISSION_ALLOWED":
                raise ValueError(status)
            if available_slots((position.ticker for position in positions), pending) <= 0:
                raise ValueError("BLOCKED_MAX_PORTFOLIO_SLOTS")
            result = ledger.mark_pending(recommendation_id, today, idempotency_key=key)
        except Exception:
            ledger.connection.rollback()
            raise
    elif action == "fill":
        if quantity is None or price is None:
            raise ValueError("fill requires --qty and --price")
        if today <= max(str(recommendation["signal_date"]), str(recommendation["decision_date"])):
            raise ValueError("FILL_REQUIRES_FUTURE_ENTRY_SESSION")
        if manager.connection.execute("SELECT 1 FROM management_session_runs WHERE session_date=?", (today,)).fetchone():
            raise ValueError("FILL_SESSION_ALREADY_PROCESSED")
        pending = ledger.get_active_pending_reservations()
        if not any(item.source_recommendation_id == recommendation_id for item in pending):
            raise ValueError("Recommendation must be explicitly PENDING before a fill")
        positions = ledger.derive_positions()
        if len({position.ticker for position in positions} |
               {item.ticker for item in pending}) > 5:
            raise ValueError("BLOCKED_MAX_PORTFOLIO_SLOTS")
        result = ledger.record_recommendation_fill(recommendation_id, today,
                                                   whole_share_quantity(quantity), Decimal(price), 0, key)
    elif action in {"cancel", "decline"}:
        if action == "cancel":
            result = ledger.mark_cancelled(recommendation_id, today, idempotency_key=key)
        else:
            result = ledger.mark_declined(recommendation_id, today, idempotency_key=key)
    elif action == "sell":
        if quantity is None or price is None:
            raise ValueError("sell requires --qty and --price")
        checked = whole_share_quantity(quantity)
        managed = _linked_managed_quantity(ledger, recommendation)
        current = next((item.quantity for item in ledger.derive_positions()
                        if item.ticker == recommendation["ticker"]), 0)
        latest = manager.states(recommendation_id)
        if not latest or latest[-1]["episode_status"] in {"CLOSED_RECORDED", "RECONCILIATION_REQUIRED"}:
            raise ValueError("No reconciled managed episode is available for this SELL")
        if checked > managed or checked > current:
            raise ValueError("SELL quantity exceeds managed/current holding quantity")
        result = ledger.append_transaction(ticker=recommendation["ticker"], trade_date=today,
                                           side="SELL", quantity=checked, price_inr=Decimal(price),
                                           idempotency_key=key, recommendation_id=recommendation_id,
                                           signal_id=recommendation["signal_id"])
    else:
        raise ValueError("Unsupported paper action")
    return {"status": result.status, "identity": result.identity, "action": action,
            "recommendation_id": recommendation_id, "paper_only": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pending", "fill", "cancel", "decline", "sell"))
    parser.add_argument("recommendation_id")
    parser.add_argument("--qty", type=int)
    parser.add_argument("--price")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--config", type=Path, default=STAGE_ROOT / "live_paper/config.json")
    parser.add_argument("--db")
    args = parser.parse_args()
    config = _config(args.config)
    database = _database_path(config, args.db)
    if not database.is_file():
        parser.error("Live-paper database does not exist; run the after-close command first")
    try:
        with Stage5DLedger(database) as ledger:
            _initialize_runs(ledger)
            print(json.dumps(record_action(ledger, args.action, args.recommendation_id,
                                           quantity=args.qty, price=args.price,
                                           idempotency_key=args.idempotency_key), indent=2))
    except Exception as exc:
        print(f"PAPER_ACTION_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
