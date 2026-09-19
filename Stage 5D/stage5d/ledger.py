from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from .ledger_schema import SCHEMA_STATEMENTS, SCHEMA_VERSION, TABLES
from .portfolio_state import OpenPosition, PendingEntryReservation, decimal_value, whole_share_quantity
from .source_contract import canonical_date


EVENT_TYPES = {"PROPOSED", "PENDING_ENTRY", "DECLINED", "CANCELLED", "EXPIRED", "PARTIALLY_FILLED", "FILLED"}
OUTCOME_STATUSES = {"PENDING", "RESOLVED", "CENSORED"}
COST_BASIS_METHOD = "WEIGHTED_AVERAGE_NON_TAX_COST_BASIS"


@dataclass(frozen=True)
class OperationResult:
    status: str
    identity: str


@dataclass(frozen=True)
class DerivedPosition:
    ticker: str
    quantity: int
    cost_basis_total_inr: Decimal
    average_cost_per_share_inr: Decimal


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal values are not valid ledger evidence")
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return format(Decimal(str(value)), "f")
    return value


def canonical_json(payload: Any) -> str:
    return json.dumps(_json_value(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_sha256(canonical_payload: str) -> str:
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def _identity(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _money(value: Any, name: str, *, positive: bool = False, nonnegative: bool = False) -> Decimal:
    try:
        amount = decimal_value(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a finite decimal value") from exc
    if positive and amount <= 0:
        raise ValueError(f"{name} must be positive")
    if nonnegative and amount < 0:
        raise ValueError(f"{name} cannot be negative")
    return amount


def _ticker(value: Any) -> str:
    result = str(value).strip().upper()
    if not result:
        raise ValueError("ticker is required")
    return result


class Stage5DLedger:
    """SQLite evidence ledger. Derived cost basis is not tax accounting."""

    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if self.database_path != ":memory:":
            self.connection.execute("PRAGMA journal_mode = WAL")
        self._initialize_or_validate()

    def __enter__(self) -> "Stage5DLedger":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @property
    def schema_version(self) -> str:
        return str(self.connection.execute("SELECT schema_version FROM ledger_meta WHERE singleton=1").fetchone()[0])

    @property
    def journal_mode(self) -> str:
        return str(self.connection.execute("PRAGMA journal_mode").fetchone()[0]).upper()

    def close(self) -> None:
        self.connection.close()

    def _initialize_or_validate(self) -> None:
        meta_exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_meta'"
        ).fetchone()
        if not meta_exists:
            with self.connection:
                for statement in SCHEMA_STATEMENTS:
                    self.connection.execute(statement)
                self.connection.execute(
                    "INSERT INTO ledger_meta(singleton,schema_version,database_id,created_at_utc) VALUES(1,?,?,?)",
                    (SCHEMA_VERSION, str(uuid.uuid4()), _utc_now()),
                )
            return
        row = self.connection.execute("SELECT schema_version FROM ledger_meta WHERE singleton=1").fetchone()
        if row is None or row[0] != SCHEMA_VERSION:
            actual = None if row is None else row[0]
            raise RuntimeError(f"Unsupported ledger schema {actual!r}; expected {SCHEMA_VERSION}")
        present = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = set(TABLES) - present
        if missing:
            raise RuntimeError(f"Ledger schema is incomplete; missing tables: {sorted(missing)}")

    def _same_or_conflict(self, table: str, identity_column: str, identity: str, digest: str) -> bool:
        row = self.connection.execute(
            f"SELECT payload_sha256 FROM {table} WHERE {identity_column}=?", (identity,)
        ).fetchone()
        if row is None:
            return False
        if row[0] != digest:
            raise ValueError(f"Conflicting immutable {table} identity: {identity}")
        return True

    def persist_allocation_result(self, result: Any) -> OperationResult:
        recommendations = [dict(item) for item in result.recommendations]
        summary = dict(result.portfolio_summary)
        decision_date = canonical_date(summary.get("decision_date"), "decision_date")
        run_payload = {
            "allocation_run_id": result.allocation_run_id,
            "decision_date": decision_date,
            "portfolio_summary": summary,
            "portfolio_snapshot": result.portfolio_snapshot,
            "recommendations": recommendations,
        }
        run_json = canonical_json(run_payload)
        run_hash = payload_sha256(run_json)
        existing = self.connection.execute(
            "SELECT payload_sha256 FROM allocation_runs WHERE allocation_run_id=?", (result.allocation_run_id,)
        ).fetchone()
        if existing is not None:
            if existing[0] != run_hash:
                raise ValueError(f"Conflicting immutable allocation run: {result.allocation_run_id}")
            for recommendation in recommendations:
                rec_json = canonical_json(recommendation)
                self._same_or_conflict("recommendations", "recommendation_id", str(recommendation["recommendation_id"]), payload_sha256(rec_json))
            return OperationResult("IDEMPOTENT_SUCCESS", str(result.allocation_run_id))

        snapshot_json = canonical_json(result.portfolio_snapshot)
        summary_json = canonical_json(summary)
        persisted_at = _utc_now()
        try:
            with self.connection:
                self.connection.execute(
                    """INSERT INTO allocation_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        result.allocation_run_id, decision_date, int(summary["profile_version"]),
                        str(summary["capital_ceiling_inr"]), str(summary["selected_horizon"]),
                        summary.get("management_policy_id"), summary.get("horizon_session_limit"),
                        summary_json, snapshot_json, len(recommendations),
                        sum(item.get("portfolio_action_status") == "ACTIONABLE_BUY" for item in recommendations),
                        run_json, run_hash, persisted_at,
                    ),
                )
                for ordinal, recommendation in enumerate(recommendations, start=1):
                    self._insert_recommendation(recommendation, ordinal, persisted_at)
                    proposed_payload = {
                        "recommendation_id": recommendation["recommendation_id"],
                        "event_type": "PROPOSED",
                        "effective_date": decision_date,
                    }
                    self._insert_event(
                        str(recommendation["recommendation_id"]), "PROPOSED", decision_date,
                        proposed_payload, f"PROPOSED:{recommendation['recommendation_id']}", persisted_at,
                    )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Allocation persistence failed atomically: {exc}") from exc
        return OperationResult("CREATED", str(result.allocation_run_id))

    def _insert_recommendation(self, item: dict[str, Any], ordinal: int, persisted_at: str) -> None:
        rec_json = canonical_json(item)
        rec_hash = payload_sha256(rec_json)
        columns = (
            "recommendation_id", "allocation_run_id", "signal_id", "profile_version", "ordinal", "ticker",
            "signal_date", "decision_date", "deterministic_signal", "setup", "trade_quality", "technical_score",
            "actionability_score", "planned_rr_t1", "planned_rr_t2", "rs60", "market_regime", "market_score",
            "entry_low", "entry_high", "sizing_entry_price", "stop", "target_1", "target_2", "recommended_quantity",
            "estimated_purchase_value_inr", "risk_budget_inr", "risk_per_share_inr", "selected_horizon",
            "management_policy_id", "management_policy_source", "management_policy_max_sessions",
            "management_policy_validation_semantics", "horizon_status", "portfolio_action_status",
            "plain_language_reason", "canonical_payload_json", "payload_sha256", "persisted_at_utc",
        )
        values = (
            item["recommendation_id"], item["allocation_run_id"], item["signal_id"], item["profile_version"], ordinal,
            item["ticker"], item["signal_date"], item["decision_date"], item["deterministic_signal"], item.get("setup"),
            item.get("trade_quality"), item.get("technical_score"), item.get("actionability_score"), item.get("planned_rr_t1"),
            item.get("planned_rr_t2"), item.get("rs60"), item.get("market_regime"), item.get("market_score"),
            item.get("entry_low"), item.get("entry_high"), item.get("sizing_entry_price"), item.get("stop"),
            item.get("target_1"), item.get("target_2"), int(item["recommended_quantity"]),
            str(item["estimated_purchase_value_inr"]), str(item["risk_budget_inr"]),
            None if item.get("risk_per_share_inr") is None else str(item["risk_per_share_inr"]),
            item["selected_horizon"], item.get("management_policy_id"), item.get("management_policy_source"),
            item.get("management_policy_max_sessions"), item.get("management_policy_validation_semantics"),
            item["horizon_status"], item["portfolio_action_status"], item["plain_language_reason"],
            rec_json, rec_hash, persisted_at,
        )
        placeholders = ",".join("?" for _ in columns)
        self.connection.execute(f"INSERT INTO recommendations({','.join(columns)}) VALUES({placeholders})", values)

    def get_allocation_run(self, allocation_run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT canonical_payload_json FROM allocation_runs WHERE allocation_run_id=?", (allocation_run_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def get_recommendation(self, recommendation_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT canonical_payload_json FROM recommendations WHERE recommendation_id=?", (recommendation_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def _recommendation_query(self, where: str, value: str) -> tuple[dict[str, Any], ...]:
        rows = self.connection.execute(
            f"SELECT canonical_payload_json FROM recommendations WHERE {where}=? ORDER BY decision_date, ordinal", (value,)
        )
        return tuple(json.loads(row[0]) for row in rows)

    def recommendations_for_date(self, decision_date: Any) -> tuple[dict[str, Any], ...]:
        return self._recommendation_query("decision_date", canonical_date(decision_date, "decision_date"))

    def recommendations_for_ticker(self, ticker: str) -> tuple[dict[str, Any], ...]:
        return self._recommendation_query("ticker", _ticker(ticker))

    def _insert_event(self, recommendation_id: str, event_type: str, effective_date: str, payload: Any, idempotency_key: str, recorded_at: str | None = None) -> OperationResult:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unknown recommendation event type: {event_type}")
        canonical = canonical_json(payload)
        digest = payload_sha256(canonical)
        row = self.connection.execute("SELECT event_id,payload_sha256 FROM recommendation_events WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is not None:
            if row[1] != digest:
                raise ValueError(f"Conflicting event idempotency key: {idempotency_key}")
            return OperationResult("IDEMPOTENT_SUCCESS", row[0])
        event_id = _identity("S5D2_EVT_", idempotency_key)
        self.connection.execute(
            "INSERT INTO recommendation_events(event_id,recommendation_id,event_type,effective_date,recorded_at_utc,payload_json,payload_sha256,idempotency_key) VALUES(?,?,?,?,?,?,?,?)",
            (event_id, recommendation_id, event_type, effective_date, recorded_at or _utc_now(), canonical, digest, idempotency_key),
        )
        return OperationResult("CREATED", event_id)

    def append_recommendation_event(self, recommendation_id: str, event_type: str, effective_date: Any, payload: Mapping[str, Any], idempotency_key: str) -> OperationResult:
        if self.get_recommendation(recommendation_id) is None:
            raise ValueError(f"Unknown recommendation: {recommendation_id}")
        normalized_payload = {"recommendation_id": recommendation_id, "event_type": event_type, "effective_date": canonical_date(effective_date, "effective_date"), **dict(payload)}
        with self.connection:
            return self._insert_event(recommendation_id, event_type, normalized_payload["effective_date"], normalized_payload, idempotency_key)

    def recommendation_event_history(self, recommendation_id: str) -> tuple[dict[str, Any], ...]:
        rows = self.connection.execute(
            "SELECT event_id,event_type,effective_date,recorded_at_utc,payload_json,idempotency_key FROM recommendation_events WHERE recommendation_id=? ORDER BY event_sequence",
            (recommendation_id,),
        )
        return tuple({"event_id": row[0], "event_type": row[1], "effective_date": row[2], "recorded_at_utc": row[3], "payload": json.loads(row[4]), "idempotency_key": row[5]} for row in rows)

    def mark_pending(self, recommendation_id: str, effective_date: Any, *, reserved_quantity: Any | None = None, reservation_price_basis: Any | None = None, idempotency_key: str) -> OperationResult:
        recommendation = self.get_recommendation(recommendation_id)
        if recommendation is None:
            raise ValueError(f"Unknown recommendation: {recommendation_id}")
        if recommendation["portfolio_action_status"] != "ACTIONABLE_BUY":
            raise ValueError("Only ACTIONABLE_BUY recommendations can become pending entries")
        quantity = whole_share_quantity(reserved_quantity if reserved_quantity is not None else recommendation["recommended_quantity"])
        if quantity > int(recommendation["recommended_quantity"]):
            raise ValueError("Reserved quantity exceeds recommended quantity")
        price = _money(reservation_price_basis if reservation_price_basis is not None else recommendation["sizing_entry_price"], "reservation_price_basis", positive=True)
        payload = {
            "ticker": recommendation["ticker"], "reserved_quantity": quantity,
            "reservation_price_basis": price, "reserved_capital_inr": price * quantity,
            "source_recommendation_id": recommendation_id, "source_signal_id": recommendation["signal_id"],
        }
        return self.append_recommendation_event(recommendation_id, "PENDING_ENTRY", effective_date, payload, idempotency_key)

    def mark_declined(self, recommendation_id: str, effective_date: Any, *, idempotency_key: str, reason: str | None = None) -> OperationResult:
        return self.append_recommendation_event(recommendation_id, "DECLINED", effective_date, {"reason": reason}, idempotency_key)

    def mark_cancelled(self, recommendation_id: str, effective_date: Any, *, idempotency_key: str, reason: str | None = None) -> OperationResult:
        return self.append_recommendation_event(recommendation_id, "CANCELLED", effective_date, {"reason": reason}, idempotency_key)

    def mark_expired(self, recommendation_id: str, effective_date: Any, *, idempotency_key: str, reason: str | None = None) -> OperationResult:
        return self.append_recommendation_event(recommendation_id, "EXPIRED", effective_date, {"reason": reason}, idempotency_key)

    def get_active_pending_reservations(self) -> tuple[PendingEntryReservation, ...]:
        recommendation_ids = [row[0] for row in self.connection.execute("SELECT DISTINCT recommendation_id FROM recommendation_events")]
        reservations: list[PendingEntryReservation] = []
        for recommendation_id in recommendation_ids:
            active: dict[str, Any] | None = None
            for event in self.recommendation_event_history(recommendation_id):
                if event["event_type"] == "PENDING_ENTRY":
                    active = event["payload"]
                elif event["event_type"] == "PARTIALLY_FILLED" and active is not None:
                    active = {**active, **event["payload"]}
                elif event["event_type"] in {"FILLED", "CANCELLED", "EXPIRED"}:
                    active = None
            if active is not None:
                remaining = int(active.get("remaining_quantity", active["reserved_quantity"]))
                if remaining > 0:
                    price = Decimal(str(active["reservation_price_basis"]))
                    reservations.append(PendingEntryReservation.create(active["ticker"], price * remaining, recommendation_id, active.get("source_signal_id")))
        return tuple(sorted(reservations, key=lambda item: (item.ticker, item.source_recommendation_id or "")))

    def append_transaction(self, *, ticker: str, trade_date: Any, side: str, quantity: Any, price_inr: Any, fees_inr: Any = 0, idempotency_key: str, recommendation_id: str | None = None, signal_id: str | None = None, external_reference: str | None = None, notes: str | None = None) -> OperationResult:
        normalized_ticker = _ticker(ticker)
        normalized_date = canonical_date(trade_date, "trade_date")
        normalized_side = str(side).upper()
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        checked_quantity = whole_share_quantity(quantity)
        price = _money(price_inr, "price_inr", positive=True)
        fees = _money(fees_inr, "fees_inr", nonnegative=True)
        if recommendation_id is not None and self.get_recommendation(recommendation_id) is None:
            raise ValueError(f"Unknown recommendation: {recommendation_id}")
        payload = {
            "ticker": normalized_ticker, "trade_date": normalized_date, "side": normalized_side,
            "quantity": checked_quantity, "price_inr": price, "fees_inr": fees,
            "recommendation_id": recommendation_id, "signal_id": signal_id,
            "external_reference": external_reference, "notes": notes,
        }
        canonical = canonical_json(payload)
        digest = payload_sha256(canonical)
        row = self.connection.execute("SELECT transaction_id,payload_sha256 FROM user_transactions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is not None:
            if row[1] != digest:
                raise ValueError(f"Conflicting transaction idempotency key: {idempotency_key}")
            return OperationResult("IDEMPOTENT_SUCCESS", row[0])
        if normalized_side == "SELL":
            position = {item.ticker: item for item in self.derive_positions(normalized_date)}.get(normalized_ticker)
            available = 0 if position is None else position.quantity
            if checked_quantity > available:
                raise ValueError(f"SELL quantity {checked_quantity} exceeds available holdings {available}")
        transaction_id = _identity("S5D2_TXN_", idempotency_key)
        self.connection.execute(
            """INSERT INTO user_transactions(transaction_id,idempotency_key,ticker,trade_date,side,quantity,price_inr,fees_inr,recommendation_id,signal_id,external_reference,notes,canonical_payload_json,payload_sha256,recorded_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (transaction_id, idempotency_key, normalized_ticker, normalized_date, normalized_side, checked_quantity, str(price), str(fees), recommendation_id, signal_id, external_reference, notes, canonical, digest, _utc_now()),
        )
        return OperationResult("CREATED", transaction_id)

    def void_transaction(self, transaction_id: str, *, idempotency_key: str, reason: str) -> OperationResult:
        if not str(reason).strip():
            raise ValueError("void reason is required")
        if self.connection.execute("SELECT 1 FROM user_transactions WHERE transaction_id=?", (transaction_id,)).fetchone() is None:
            raise ValueError(f"Unknown transaction: {transaction_id}")
        payload = {"transaction_id": transaction_id, "reason": str(reason).strip()}
        canonical = canonical_json(payload)
        digest = payload_sha256(canonical)
        row = self.connection.execute("SELECT void_id,payload_sha256 FROM transaction_voids WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is not None:
            if row[1] != digest:
                raise ValueError(f"Conflicting void idempotency key: {idempotency_key}")
            return OperationResult("IDEMPOTENT_SUCCESS", row[0])
        void_id = _identity("S5D2_VOID_", idempotency_key)
        with self.connection:
            self.connection.execute("INSERT INTO transaction_voids(void_id,transaction_id,idempotency_key,reason,voided_at_utc,canonical_payload_json,payload_sha256) VALUES(?,?,?,?,?,?,?)", (void_id, transaction_id, idempotency_key, str(reason).strip(), _utc_now(), canonical, digest))
        return OperationResult("CREATED", void_id)

    def transaction_void_history(self, transaction_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(dict(row) for row in self.connection.execute("SELECT * FROM transaction_voids WHERE transaction_id=? ORDER BY void_sequence", (transaction_id,)))

    def _transactions(self, where: str, value: str) -> tuple[dict[str, Any], ...]:
        return tuple(json.loads(row[0]) | {"transaction_id": row[1]} for row in self.connection.execute(f"SELECT canonical_payload_json,transaction_id FROM user_transactions WHERE {where}=? ORDER BY transaction_sequence", (value,)))

    def transactions_for_ticker(self, ticker: str) -> tuple[dict[str, Any], ...]:
        return self._transactions("ticker", _ticker(ticker))

    def transactions_for_recommendation(self, recommendation_id: str) -> tuple[dict[str, Any], ...]:
        return self._transactions("recommendation_id", recommendation_id)

    def add_opening_position(self, *, ticker: str, effective_date: Any, quantity: Any, average_cost_per_share_inr: Any, idempotency_key: str, notes: str | None = None) -> OperationResult:
        payload = {"ticker": _ticker(ticker), "effective_date": canonical_date(effective_date, "effective_date"), "quantity": whole_share_quantity(quantity), "average_cost_per_share_inr": _money(average_cost_per_share_inr, "average_cost_per_share_inr", nonnegative=True), "notes": notes}
        canonical = canonical_json(payload)
        digest = payload_sha256(canonical)
        row = self.connection.execute("SELECT opening_position_id,payload_sha256 FROM opening_positions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is not None:
            if row[1] != digest:
                raise ValueError(f"Conflicting opening-position idempotency key: {idempotency_key}")
            return OperationResult("IDEMPOTENT_SUCCESS", row[0])
        identity = _identity("S5D2_OPEN_", idempotency_key)
        with self.connection:
            self.connection.execute("INSERT INTO opening_positions(opening_position_id,idempotency_key,ticker,effective_date,quantity,average_cost_per_share_inr,notes,canonical_payload_json,payload_sha256,recorded_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?)", (identity, idempotency_key, payload["ticker"], payload["effective_date"], payload["quantity"], str(payload["average_cost_per_share_inr"]), notes, canonical, digest, _utc_now()))
        return OperationResult("CREATED", identity)

    def derive_positions(self, as_of_date: Any | None = None) -> tuple[DerivedPosition, ...]:
        cutoff = None if as_of_date is None else canonical_date(as_of_date, "as_of_date")
        state: dict[str, list[Any]] = {}
        opening_sql = "SELECT ticker,quantity,average_cost_per_share_inr FROM opening_positions" + (" WHERE effective_date<=?" if cutoff else "") + " ORDER BY effective_date,opening_sequence"
        for row in self.connection.execute(opening_sql, (() if cutoff is None else (cutoff,))):
            ticker = row[0]
            quantity = int(row[1])
            basis = Decimal(row[2]) * quantity
            current = state.setdefault(ticker, [0, Decimal("0")])
            current[0] += quantity
            current[1] += basis
        transaction_sql = """SELECT t.ticker,t.side,t.quantity,t.price_inr,t.fees_inr FROM user_transactions t LEFT JOIN transaction_voids v ON v.transaction_id=t.transaction_id WHERE v.void_id IS NULL"""
        params: tuple[Any, ...] = ()
        if cutoff:
            transaction_sql += " AND t.trade_date<=?"
            params = (cutoff,)
        transaction_sql += " ORDER BY t.trade_date,t.transaction_sequence"
        for row in self.connection.execute(transaction_sql, params):
            ticker, side, quantity = row[0], row[1], int(row[2])
            price, fees = Decimal(row[3]), Decimal(row[4])
            current = state.setdefault(ticker, [0, Decimal("0")])
            if side == "BUY":
                current[0] += quantity
                current[1] += price * quantity + fees
            else:
                if quantity > current[0]:
                    raise ValueError(f"Negative position detected for {ticker}")
                average = current[1] / current[0]
                current[0] -= quantity
                current[1] -= average * quantity
                if current[0] == 0:
                    current[1] = Decimal("0")
        return tuple(DerivedPosition(ticker, int(values[0]), values[1], values[1] / values[0]) for ticker, values in sorted(state.items()) if values[0] > 0)

    def build_allocator_open_positions(self, current_prices: Mapping[str, Any], *, as_of_date: Any | None = None) -> tuple[OpenPosition, ...]:
        prices = {_ticker(key): value for key, value in current_prices.items()}
        result = []
        for position in self.derive_positions(as_of_date):
            if position.ticker not in prices:
                raise ValueError(f"Missing externally supplied current price for {position.ticker}")
            result.append(OpenPosition.create(position.ticker, position.quantity, prices[position.ticker], position.average_cost_per_share_inr))
        return tuple(result)

    def record_recommendation_fill(self, recommendation_id: str, trade_date: Any, quantity: Any, actual_price: Any, fees: Any, idempotency_key: str) -> OperationResult:
        recommendation = self.get_recommendation(recommendation_id)
        if recommendation is None:
            raise ValueError(f"Unknown recommendation: {recommendation_id}")
        if recommendation["portfolio_action_status"] != "ACTIONABLE_BUY":
            raise ValueError("Recommendation is not ACTIONABLE_BUY")
        checked_quantity = whole_share_quantity(quantity)
        already_filled = self.connection.execute("""SELECT COALESCE(SUM(t.quantity),0) FROM user_transactions t LEFT JOIN transaction_voids v ON v.transaction_id=t.transaction_id WHERE t.recommendation_id=? AND t.side='BUY' AND v.void_id IS NULL""", (recommendation_id,)).fetchone()[0]
        remaining_before = int(recommendation["recommended_quantity"]) - int(already_filled)
        existing = self.connection.execute("SELECT transaction_id FROM user_transactions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if existing is None and checked_quantity > remaining_before:
            raise ValueError("Fill quantity exceeds still-unfilled intended quantity")
        normalized_date = canonical_date(trade_date, "trade_date")
        event_key = f"FILL_EVENT:{idempotency_key}"
        try:
            with self.connection:
                tx_result = self.append_transaction(ticker=recommendation["ticker"], trade_date=normalized_date, side="BUY", quantity=checked_quantity, price_inr=actual_price, fees_inr=fees, idempotency_key=idempotency_key, recommendation_id=recommendation_id, signal_id=recommendation["signal_id"])
                remaining_after = max(0, remaining_before - checked_quantity) if tx_result.status == "CREATED" else max(0, int(recommendation["recommended_quantity"]) - int(already_filled))
                event_type = "FILLED" if remaining_after == 0 else "PARTIALLY_FILLED"
                payload = {"recommendation_id": recommendation_id, "event_type": event_type, "effective_date": normalized_date, "filled_quantity": checked_quantity, "remaining_quantity": remaining_after, "ticker": recommendation["ticker"], "reservation_price_basis": recommendation["sizing_entry_price"], "source_signal_id": recommendation["signal_id"]}
                self._insert_event(recommendation_id, event_type, normalized_date, payload, event_key)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Recommendation fill failed atomically: {exc}") from exc
        return tx_result

    def persist_position_snapshots(self, as_of_date: Any, current_prices: Mapping[str, Any], *, management_policy_id: str | None = None, source_recommendation_id: str | None = None, source_signal_id: str | None = None) -> tuple[OperationResult, ...]:
        normalized_date = canonical_date(as_of_date, "as_of_date")
        prices = {_ticker(key): _money(value, "current_market_price_inr", nonnegative=True) for key, value in current_prices.items()}
        results = []
        with self.connection:
            for position in self.derive_positions(normalized_date):
                if position.ticker not in prices:
                    raise ValueError(f"Missing externally supplied current price for {position.ticker}")
                price = prices[position.ticker]
                payload = {"as_of_date": normalized_date, "ticker": position.ticker, "quantity": position.quantity, "average_cost_per_share_inr": position.average_cost_per_share_inr, "current_market_price_inr": price, "market_value_inr": price * position.quantity, "unrealized_pnl_inr": price * position.quantity - position.cost_basis_total_inr, "management_policy_id": management_policy_id, "source_recommendation_id": source_recommendation_id, "source_signal_id": source_signal_id}
                identity_json = canonical_json({key: payload[key] for key in ("as_of_date", "ticker", "source_recommendation_id", "source_signal_id")})
                snapshot_id = _identity("S5D2_SNAP_", identity_json)
                canonical = canonical_json(payload)
                digest = payload_sha256(canonical)
                if self._same_or_conflict("position_state_snapshots", "snapshot_id", snapshot_id, digest):
                    results.append(OperationResult("IDEMPOTENT_SUCCESS", snapshot_id))
                    continue
                self.connection.execute("""INSERT INTO position_state_snapshots(snapshot_id,as_of_date,ticker,quantity,average_cost_per_share_inr,current_market_price_inr,market_value_inr,unrealized_pnl_inr,management_policy_id,source_recommendation_id,source_signal_id,canonical_payload_json,payload_sha256,persisted_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (snapshot_id, normalized_date, position.ticker, position.quantity, str(position.average_cost_per_share_inr), str(price), str(price * position.quantity), str(price * position.quantity - position.cost_basis_total_inr), management_policy_id, source_recommendation_id, source_signal_id, canonical, digest, _utc_now()))
                results.append(OperationResult("CREATED", snapshot_id))
        return tuple(results)

    def position_snapshots(self, as_of_date: Any | None = None) -> tuple[dict[str, Any], ...]:
        if as_of_date is None:
            rows = self.connection.execute("SELECT canonical_payload_json FROM position_state_snapshots ORDER BY snapshot_sequence")
        else:
            rows = self.connection.execute("SELECT canonical_payload_json FROM position_state_snapshots WHERE as_of_date=? ORDER BY snapshot_sequence", (canonical_date(as_of_date, "as_of_date"),))
        return tuple(json.loads(row[0]) for row in rows)

    def append_outcome_version(self, recommendation_id: str, *, as_of_date: Any, outcome_status: str, methodology_version: str, outcome_version: int | None = None, **fields: Any) -> OperationResult:
        if self.get_recommendation(recommendation_id) is None:
            raise ValueError(f"Unknown recommendation: {recommendation_id}")
        status = str(outcome_status).upper()
        if status not in OUTCOME_STATUSES:
            raise ValueError(f"Unknown outcome status: {outcome_status}")
        current = int(self.connection.execute("SELECT COALESCE(MAX(outcome_version),0) FROM recommendation_outcome_versions WHERE recommendation_id=?", (recommendation_id,)).fetchone()[0])
        version = current + 1 if outcome_version is None else int(outcome_version)
        payload = {"recommendation_id": recommendation_id, "outcome_version": version, "as_of_date": canonical_date(as_of_date, "as_of_date"), "outcome_status": status, "methodology_version": str(methodology_version), **fields}
        canonical = canonical_json(payload)
        digest = payload_sha256(canonical)
        existing = self.connection.execute("SELECT payload_sha256 FROM recommendation_outcome_versions WHERE recommendation_id=? AND outcome_version=?", (recommendation_id, version)).fetchone()
        if existing is not None:
            if existing[0] != digest:
                raise ValueError(f"Conflicting outcome version {version} for {recommendation_id}")
            return OperationResult("IDEMPOTENT_SUCCESS", f"{recommendation_id}:{version}")
        if version != current + 1:
            raise ValueError(f"Outcome version must be the next monotonic version {current + 1}")
        allowed = ["entry_filled", "entry_date", "stop_hit", "target_1_hit", "target_2_hit", "max_price_after_signal", "min_price_after_signal", "mfe_pct", "mae_pct", "mfe_r", "mae_r", "time_to_entry_sessions", "time_to_t1_sessions", "time_to_t2_sessions", "holding_sessions", "realized_r", "exit_reason", "source_data_hash"]
        values = [fields.get(name) for name in allowed]
        with self.connection:
            self.connection.execute(f"INSERT INTO recommendation_outcome_versions(recommendation_id,outcome_version,as_of_date,outcome_status,{','.join(allowed)},methodology_version,canonical_payload_json,payload_sha256,persisted_at_utc) VALUES({','.join('?' for _ in range(4 + len(allowed) + 4))})", [recommendation_id, version, payload["as_of_date"], status, *[None if value is None else str(value) if isinstance(value, Decimal) else value for value in values], str(methodology_version), canonical, digest, _utc_now()])
        return OperationResult("CREATED", f"{recommendation_id}:{version}")

    def outcome_history(self, recommendation_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(json.loads(row[0]) for row in self.connection.execute("SELECT canonical_payload_json FROM recommendation_outcome_versions WHERE recommendation_id=? ORDER BY outcome_version", (recommendation_id,)))

    def latest_outcome(self, recommendation_id: str) -> dict[str, Any] | None:
        history = self.outcome_history(recommendation_id)
        return None if not history else history[-1]

    def integrity_check(self) -> dict[str, Any]:
        checks: dict[str, bool] = {}
        issues: list[str] = []
        pragma = [row[0] for row in self.connection.execute("PRAGMA integrity_check")]
        checks["sqlite_integrity"] = pragma == ["ok"]
        if not checks["sqlite_integrity"]:
            issues.extend(str(item) for item in pragma)
        foreign = [tuple(row) for row in self.connection.execute("PRAGMA foreign_key_check")]
        checks["foreign_keys"] = not foreign
        if foreign:
            issues.append(f"foreign key violations: {foreign}")
        hash_tables = {
            "allocation_runs": "canonical_payload_json", "recommendations": "canonical_payload_json",
            "recommendation_events": "payload_json", "user_transactions": "canonical_payload_json",
            "transaction_voids": "canonical_payload_json", "opening_positions": "canonical_payload_json",
            "position_state_snapshots": "canonical_payload_json", "recommendation_outcome_versions": "canonical_payload_json",
        }
        for table, payload_column in hash_tables.items():
            valid = True
            for row in self.connection.execute(f"SELECT {payload_column},payload_sha256 FROM {table}"):
                if payload_sha256(row[0]) != row[1]:
                    valid = False
                    issues.append(f"payload hash mismatch in {table}")
            checks[f"{table}_hashes"] = valid
        orphans = self.connection.execute("SELECT COUNT(*) FROM recommendations r LEFT JOIN allocation_runs a ON a.allocation_run_id=r.allocation_run_id WHERE a.allocation_run_id IS NULL").fetchone()[0]
        checks["recommendation_allocation_links"] = orphans == 0
        try:
            self.derive_positions()
            checks["nonnegative_positions"] = True
        except ValueError as exc:
            checks["nonnegative_positions"] = False
            issues.append(str(exc))
        monotonic = True
        for row in self.connection.execute("SELECT recommendation_id,GROUP_CONCAT(outcome_version,',') FROM recommendation_outcome_versions GROUP BY recommendation_id"):
            versions = [int(item) for item in str(row[1]).split(",")]
            if sorted(versions) != list(range(1, max(versions) + 1)):
                monotonic = False
                issues.append(f"non-monotonic outcomes for {row[0]}")
        checks["outcome_versions_monotonic"] = monotonic
        return {"ok": all(checks.values()), "schema_version": self.schema_version, "checks": checks, "issues": issues}

