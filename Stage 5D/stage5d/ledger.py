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
            raise ValueError("non-finite numeric values are not valid ledger evidence")
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

    def _same_or_conflict(self, table: str, identity_column: str, identity: str, digest: str, canonical: str | None = None) -> bool:
        row = self.connection.execute(
            f"SELECT payload_sha256,canonical_payload_json FROM {table} WHERE {identity_column}=?", (identity,)
        ).fetchone()
        if row is None:
            return False
        if row[0] != digest or (canonical is not None and row[1] != canonical):
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
            "SELECT payload_sha256,canonical_payload_json FROM allocation_runs WHERE allocation_run_id=?", (result.allocation_run_id,)
        ).fetchone()
        if existing is not None:
            if existing[0] != run_hash or existing[1] != run_json:
                raise ValueError(f"Conflicting immutable allocation run: {result.allocation_run_id}")
            actual_children = {
                row[0]: (row[1], row[2])
                for row in self.connection.execute(
                    "SELECT recommendation_id,payload_sha256,canonical_payload_json FROM recommendations WHERE allocation_run_id=?",
                    (result.allocation_run_id,),
                )
            }
            expected_children: dict[str, tuple[str, str]] = {}
            for recommendation in recommendations:
                rec_json = canonical_json(recommendation)
                recommendation_id = str(recommendation["recommendation_id"])
                expected_children[recommendation_id] = (payload_sha256(rec_json), rec_json)
                if not self._same_or_conflict("recommendations", "recommendation_id", recommendation_id, expected_children[recommendation_id][0], rec_json):
                    raise ValueError(f"Allocation run {result.allocation_run_id} is missing recommendation {recommendation_id}")
            if actual_children != expected_children:
                raise ValueError(f"Allocation run {result.allocation_run_id} child evidence is incomplete or conflicting")
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
        row = self.connection.execute("SELECT event_id,payload_sha256,payload_json FROM recommendation_events WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is not None:
            if row[1] != digest or row[2] != canonical:
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
        _, terminal = self._active_pending_state(recommendation_id)
        if terminal:
            raise ValueError("Terminal recommendation lifecycle cannot be reactivated as pending")
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

    def _active_pending_state(self, recommendation_id: str) -> tuple[dict[str, Any] | None, bool]:
        active: dict[str, Any] | None = None
        terminal = False
        for event in self.recommendation_event_history(recommendation_id):
            event_type = event["event_type"]
            if event_type == "PENDING_ENTRY":
                if terminal:
                    raise ValueError(f"Invalid pending reactivation found for terminal recommendation {recommendation_id}")
                active = event["payload"]
            elif event_type == "PARTIALLY_FILLED":
                if terminal:
                    raise ValueError(f"Invalid partial fill found after terminal recommendation {recommendation_id}")
                active = {**(active or {}), **event["payload"]}
            elif event_type in {"FILLED", "CANCELLED", "EXPIRED", "DECLINED"}:
                active = None
                terminal = True
        return active, terminal

    def get_active_pending_reservations(self) -> tuple[PendingEntryReservation, ...]:
        recommendation_ids = [row[0] for row in self.connection.execute("SELECT DISTINCT recommendation_id FROM recommendation_events")]
        reservations: list[PendingEntryReservation] = []
        for recommendation_id in recommendation_ids:
            active, _ = self._active_pending_state(recommendation_id)
            if active is not None:
                remaining = int(active.get("remaining_quantity", active.get("reserved_quantity", 0)))
                if remaining > 0:
                    price = Decimal(str(active["reservation_price_basis"]))
                    reservations.append(PendingEntryReservation.create(active["ticker"], price * remaining, recommendation_id, active.get("source_signal_id")))
        return tuple(sorted(reservations, key=lambda item: (item.ticker, item.source_recommendation_id or "")))

    def _append_transaction_no_commit(self, *, ticker: str, trade_date: Any, side: str, quantity: Any, price_inr: Any, fees_inr: Any = 0, idempotency_key: str, recommendation_id: str | None = None, signal_id: str | None = None, external_reference: str | None = None, notes: str | None = None) -> OperationResult:
        normalized_ticker = _ticker(ticker)
        normalized_date = canonical_date(trade_date, "trade_date")
        normalized_side = str(side).upper()
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        checked_quantity = whole_share_quantity(quantity)
        price = _money(price_inr, "price_inr", positive=True)
        fees = _money(fees_inr, "fees_inr", nonnegative=True)
        if recommendation_id is not None:
            recommendation = self.get_recommendation(recommendation_id)
            if recommendation is None:
                raise ValueError(f"Unknown recommendation: {recommendation_id}")
            if normalized_ticker != _ticker(recommendation["ticker"]):
                raise ValueError("Transaction ticker does not match linked recommendation ticker")
            expected_signal_id = str(recommendation["signal_id"])
            if signal_id is None:
                signal_id = expected_signal_id
            elif str(signal_id) != expected_signal_id:
                raise ValueError("Transaction signal_id does not match linked recommendation signal_id")
        payload = {
            "ticker": normalized_ticker, "trade_date": normalized_date, "side": normalized_side,
            "quantity": checked_quantity, "price_inr": price, "fees_inr": fees,
            "recommendation_id": recommendation_id, "signal_id": signal_id,
            "external_reference": external_reference, "notes": notes,
        }
        canonical = canonical_json(payload)
        digest = payload_sha256(canonical)
        row = self.connection.execute("SELECT transaction_id,payload_sha256,canonical_payload_json FROM user_transactions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is not None:
            if row[1] != digest or row[2] != canonical:
                raise ValueError(f"Conflicting transaction idempotency key: {idempotency_key}")
            return OperationResult("IDEMPOTENT_SUCCESS", row[0])
        transaction_id = _identity("S5D2_TXN_", idempotency_key)
        self.connection.execute(
            """INSERT INTO user_transactions(transaction_id,idempotency_key,ticker,trade_date,side,quantity,price_inr,fees_inr,recommendation_id,signal_id,external_reference,notes,canonical_payload_json,payload_sha256,recorded_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (transaction_id, idempotency_key, normalized_ticker, normalized_date, normalized_side, checked_quantity, str(price), str(fees), recommendation_id, signal_id, external_reference, notes, canonical, digest, _utc_now()),
        )
        self._replay_positions()
        return OperationResult("CREATED", transaction_id)

    def append_transaction(self, *, ticker: str, trade_date: Any, side: str, quantity: Any, price_inr: Any, fees_inr: Any = 0, idempotency_key: str, recommendation_id: str | None = None, signal_id: str | None = None, external_reference: str | None = None, notes: str | None = None) -> OperationResult:
        with self.connection:
            return self._append_transaction_no_commit(
                ticker=ticker, trade_date=trade_date, side=side, quantity=quantity,
                price_inr=price_inr, fees_inr=fees_inr, idempotency_key=idempotency_key,
                recommendation_id=recommendation_id, signal_id=signal_id,
                external_reference=external_reference, notes=notes,
            )

    def void_transaction(self, transaction_id: str, *, idempotency_key: str, reason: str) -> OperationResult:
        if not str(reason).strip():
            raise ValueError("void reason is required")
        if self.connection.execute("SELECT 1 FROM user_transactions WHERE transaction_id=?", (transaction_id,)).fetchone() is None:
            raise ValueError(f"Unknown transaction: {transaction_id}")
        payload = {"transaction_id": transaction_id, "reason": str(reason).strip()}
        canonical = canonical_json(payload)
        digest = payload_sha256(canonical)
        row = self.connection.execute("SELECT void_id,payload_sha256,canonical_payload_json FROM transaction_voids WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is not None:
            if row[1] != digest or row[2] != canonical:
                raise ValueError(f"Conflicting void idempotency key: {idempotency_key}")
            return OperationResult("IDEMPOTENT_SUCCESS", row[0])
        prior_void = self.connection.execute("SELECT void_id FROM transaction_voids WHERE transaction_id=?", (transaction_id,)).fetchone()
        if prior_void is not None:
            raise ValueError(f"Transaction {transaction_id} is already voided")
        void_id = _identity("S5D2_VOID_", idempotency_key)
        with self.connection:
            self.connection.execute("INSERT INTO transaction_voids(void_id,transaction_id,idempotency_key,reason,voided_at_utc,canonical_payload_json,payload_sha256) VALUES(?,?,?,?,?,?,?)", (void_id, transaction_id, idempotency_key, str(reason).strip(), _utc_now(), canonical, digest))
            self._replay_positions()
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
        row = self.connection.execute("SELECT opening_position_id,payload_sha256,canonical_payload_json FROM opening_positions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is not None:
            if row[1] != digest or row[2] != canonical:
                raise ValueError(f"Conflicting opening-position idempotency key: {idempotency_key}")
            return OperationResult("IDEMPOTENT_SUCCESS", row[0])
        identity = _identity("S5D2_OPEN_", idempotency_key)
        with self.connection:
            self.connection.execute("INSERT INTO opening_positions(opening_position_id,idempotency_key,ticker,effective_date,quantity,average_cost_per_share_inr,notes,canonical_payload_json,payload_sha256,recorded_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?)", (identity, idempotency_key, payload["ticker"], payload["effective_date"], payload["quantity"], str(payload["average_cost_per_share_inr"]), notes, canonical, digest, _utc_now()))
        return OperationResult("CREATED", identity)

    def _chronological_events(self, as_of_date: str | None = None) -> tuple[sqlite3.Row, ...]:
        sql = """
            SELECT effective_date AS event_date, 0 AS event_order, opening_sequence AS stable_sequence,
                   'OPENING' AS event_kind, ticker, quantity, average_cost_per_share_inr AS price_inr, '0' AS fees_inr
            FROM opening_positions
            WHERE (? IS NULL OR effective_date <= ?)
            UNION ALL
            SELECT t.trade_date AS event_date, 1 AS event_order, t.transaction_sequence AS stable_sequence,
                   t.side AS event_kind, t.ticker, t.quantity, t.price_inr, t.fees_inr
            FROM user_transactions t
            WHERE (? IS NULL OR t.trade_date <= ?)
              AND NOT EXISTS (SELECT 1 FROM transaction_voids v WHERE v.transaction_id=t.transaction_id)
            ORDER BY event_date, event_order, stable_sequence
        """
        return tuple(self.connection.execute(sql, (as_of_date, as_of_date, as_of_date, as_of_date)))

    def _replay_positions(self, as_of_date: str | None = None) -> tuple[DerivedPosition, ...]:
        state: dict[str, list[Any]] = {}
        for row in self._chronological_events(as_of_date):
            event_date, event_kind, ticker, quantity = row[0], row[3], row[4], int(row[5])
            price, fees = Decimal(row[6]), Decimal(row[7])
            current = state.setdefault(ticker, [0, Decimal("0")])
            if event_kind in {"OPENING", "BUY"}:
                current[0] += quantity
                current[1] += price * quantity + (fees if event_kind == "BUY" else Decimal("0"))
            else:
                if quantity > current[0]:
                    raise ValueError(f"SELL quantity exceeds available holdings; chronology would create negative holdings for {ticker} on {event_date}")
                average = current[1] / current[0]
                current[0] -= quantity
                current[1] -= average * quantity
                if current[0] == 0:
                    current[1] = Decimal("0")
        return tuple(DerivedPosition(ticker, int(values[0]), values[1], values[1] / values[0]) for ticker, values in sorted(state.items()) if values[0] > 0)

    def derive_positions(self, as_of_date: Any | None = None) -> tuple[DerivedPosition, ...]:
        cutoff = None if as_of_date is None else canonical_date(as_of_date, "as_of_date")
        return self._replay_positions(cutoff)

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
        active_pending, terminal = self._active_pending_state(recommendation_id)
        known_fill = self.connection.execute("SELECT transaction_id FROM user_transactions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if terminal and known_fill is None:
            raise ValueError("Cannot record a fill after a terminal recommendation lifecycle event")
        checked_quantity = whole_share_quantity(quantity)
        already_filled = self.connection.execute("""SELECT COALESCE(SUM(t.quantity),0) FROM user_transactions t LEFT JOIN transaction_voids v ON v.transaction_id=t.transaction_id WHERE t.recommendation_id=? AND t.side='BUY' AND v.void_id IS NULL""", (recommendation_id,)).fetchone()[0]
        remaining_before = int(recommendation["recommended_quantity"]) - int(already_filled)
        existing = known_fill
        if existing is None and checked_quantity > remaining_before:
            raise ValueError("Fill quantity exceeds still-unfilled intended quantity")
        normalized_date = canonical_date(trade_date, "trade_date")
        event_key = f"FILL_EVENT:{idempotency_key}"
        if known_fill is not None:
            with self.connection:
                repeated = self._append_transaction_no_commit(
                    ticker=recommendation["ticker"], trade_date=normalized_date, side="BUY",
                    quantity=checked_quantity, price_inr=actual_price, fees_inr=fees,
                    idempotency_key=idempotency_key, recommendation_id=recommendation_id,
                    signal_id=recommendation["signal_id"],
                )
                if self.connection.execute("SELECT 1 FROM recommendation_events WHERE idempotency_key=?", (event_key,)).fetchone() is None:
                    raise ValueError("Existing recommendation fill is missing its lifecycle event")
            return repeated
        try:
            with self.connection:
                tx_result = self._append_transaction_no_commit(ticker=recommendation["ticker"], trade_date=normalized_date, side="BUY", quantity=checked_quantity, price_inr=actual_price, fees_inr=fees, idempotency_key=idempotency_key, recommendation_id=recommendation_id, signal_id=recommendation["signal_id"])
                remaining_after = max(0, remaining_before - checked_quantity) if tx_result.status == "CREATED" else max(0, int(recommendation["recommended_quantity"]) - int(already_filled))
                event_type = "FILLED" if remaining_after == 0 else "PARTIALLY_FILLED"
                reservation_basis = (
                    active_pending.get("reservation_price_basis")
                    if active_pending is not None and active_pending.get("reservation_price_basis") is not None
                    else recommendation["sizing_entry_price"]
                )
                payload = {
                    "recommendation_id": recommendation_id, "event_type": event_type,
                    "effective_date": normalized_date, "filled_quantity": checked_quantity,
                    "remaining_quantity": remaining_after, "reserved_quantity": int(recommendation["recommended_quantity"]),
                    "ticker": recommendation["ticker"], "reservation_price_basis": reservation_basis,
                    "reserved_capital_inr": Decimal(str(reservation_basis)) * remaining_after,
                    "source_recommendation_id": recommendation_id, "source_signal_id": recommendation["signal_id"],
                }
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
                if self._same_or_conflict("position_state_snapshots", "snapshot_id", snapshot_id, digest, canonical):
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
        methodology = str(methodology_version).strip()
        if not methodology:
            raise ValueError("methodology_version must be non-empty")
        allowed = ["entry_filled", "entry_date", "stop_hit", "target_1_hit", "target_2_hit", "max_price_after_signal", "min_price_after_signal", "mfe_pct", "mae_pct", "mfe_r", "mae_r", "time_to_entry_sessions", "time_to_t1_sessions", "time_to_t2_sessions", "holding_sessions", "realized_r", "exit_reason", "source_data_hash"]
        unknown = set(fields) - set(allowed)
        if unknown:
            raise ValueError(f"Unknown outcome fields: {sorted(unknown)}")
        normalized_fields = dict(fields)
        for name in ("entry_filled", "stop_hit", "target_1_hit", "target_2_hit"):
            value = normalized_fields.get(name)
            if value is not None and (not isinstance(value, (bool, int)) or value not in (True, False, 0, 1)):
                raise ValueError(f"{name} must be True, False, 0, 1, or None")
            if value is not None:
                normalized_fields[name] = bool(value)
        if normalized_fields.get("entry_date") is not None:
            normalized_fields["entry_date"] = canonical_date(normalized_fields["entry_date"], "entry_date")
        for name in ("time_to_entry_sessions", "time_to_t1_sessions", "time_to_t2_sessions", "holding_sessions"):
            value = normalized_fields.get(name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be an integer >= 0")
        for name in ("max_price_after_signal", "min_price_after_signal", "mfe_pct", "mae_pct", "mfe_r", "mae_r", "realized_r"):
            if normalized_fields.get(name) is not None:
                normalized_fields[name] = _money(normalized_fields[name], name)
        fields = normalized_fields
        current = int(self.connection.execute("SELECT COALESCE(MAX(outcome_version),0) FROM recommendation_outcome_versions WHERE recommendation_id=?", (recommendation_id,)).fetchone()[0])
        version = current + 1 if outcome_version is None else int(outcome_version)
        payload = {"recommendation_id": recommendation_id, "outcome_version": version, "as_of_date": canonical_date(as_of_date, "as_of_date"), "outcome_status": status, "methodology_version": methodology, **fields}
        canonical = canonical_json(payload)
        digest = payload_sha256(canonical)
        existing = self.connection.execute("SELECT payload_sha256,canonical_payload_json FROM recommendation_outcome_versions WHERE recommendation_id=? AND outcome_version=?", (recommendation_id, version)).fetchone()
        if existing is not None:
            if existing[0] != digest or existing[1] != canonical:
                raise ValueError(f"Conflicting outcome version {version} for {recommendation_id}")
            return OperationResult("IDEMPOTENT_SUCCESS", f"{recommendation_id}:{version}")
        if version != current + 1:
            raise ValueError(f"Outcome version must be the next monotonic version {current + 1}")
        values = [fields.get(name) for name in allowed]
        with self.connection:
            self.connection.execute(f"INSERT INTO recommendation_outcome_versions(recommendation_id,outcome_version,as_of_date,outcome_status,{','.join(allowed)},methodology_version,canonical_payload_json,payload_sha256,persisted_at_utc) VALUES({','.join('?' for _ in range(4 + len(allowed) + 4))})", [recommendation_id, version, payload["as_of_date"], status, *[None if value is None else str(value) if isinstance(value, Decimal) else value for value in values], methodology, canonical, digest, _utc_now()])
        return OperationResult("CREATED", f"{recommendation_id}:{version}")

    def outcome_history(self, recommendation_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(json.loads(row[0]) for row in self.connection.execute("SELECT canonical_payload_json FROM recommendation_outcome_versions WHERE recommendation_id=? ORDER BY outcome_version", (recommendation_id,)))

    def latest_outcome(self, recommendation_id: str) -> dict[str, Any] | None:
        history = self.outcome_history(recommendation_id)
        return None if not history else history[-1]

    def integrity_check(self) -> dict[str, Any]:
        checks: dict[str, bool] = {}
        issues: list[str] = []

        def same(typed: Any, evidence: Any, kind: str = "text") -> bool:
            if typed is None or evidence is None:
                return typed is None and evidence is None
            try:
                if kind == "decimal":
                    return Decimal(str(typed)) == Decimal(str(evidence))
                if kind == "int":
                    return not isinstance(evidence, bool) and int(typed) == int(evidence)
                if kind == "bool":
                    typed_boolean = int(typed)
                    return typed_boolean in (0, 1) and isinstance(evidence, bool) and bool(typed_boolean) == evidence
                return str(typed) == str(evidence)
            except (ValueError, TypeError, ArithmeticError):
                return False

        def payload_rows(table: str, payload_column: str, mappings: Mapping[str, tuple[str, str]]) -> bool:
            valid = True
            for row in self.connection.execute(f"SELECT * FROM {table}"):
                try:
                    payload = json.loads(row[payload_column])
                except (TypeError, json.JSONDecodeError):
                    valid = False
                    issues.append(f"invalid canonical payload JSON in {table}")
                    continue
                if not isinstance(payload, dict):
                    valid = False
                    issues.append(f"canonical payload is not an object in {table}")
                    continue
                for column, (payload_key, kind) in mappings.items():
                    if not same(row[column], payload.get(payload_key), kind):
                        valid = False
                        issues.append(f"typed column mismatch in {table}.{column}")
            return valid

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

        allocation_columns_valid = True
        allocation_children_valid = True
        for row in self.connection.execute("SELECT * FROM allocation_runs"):
            try:
                payload = json.loads(row["canonical_payload_json"])
                summary = payload["portfolio_summary"]
                embedded = payload["recommendations"]
            except (KeyError, TypeError, json.JSONDecodeError):
                allocation_columns_valid = allocation_children_valid = False
                issues.append("invalid allocation canonical payload structure")
                continue
            comparisons = (
                same(row["allocation_run_id"], payload.get("allocation_run_id")),
                same(row["decision_date"], payload.get("decision_date")),
                same(row["profile_version"], summary.get("profile_version"), "int"),
                same(row["capital_ceiling_inr"], summary.get("capital_ceiling_inr"), "decimal"),
                same(row["selected_horizon"], summary.get("selected_horizon")),
                same(row["management_policy_id"], summary.get("management_policy_id")),
                same(row["horizon_session_limit"], summary.get("horizon_session_limit"), "int"),
                canonical_json(json.loads(row["portfolio_summary_json"])) == canonical_json(summary),
                canonical_json(json.loads(row["portfolio_snapshot_json"])) == canonical_json(payload.get("portfolio_snapshot")),
            )
            if not all(comparisons):
                allocation_columns_valid = False
                issues.append(f"typed column mismatch in allocation_runs {row['allocation_run_id']}")
            actual = list(self.connection.execute("SELECT recommendation_id,ordinal,canonical_payload_json,payload_sha256,portfolio_action_status FROM recommendations WHERE allocation_run_id=? ORDER BY ordinal", (row["allocation_run_id"],)))
            embedded_ids = [str(item.get("recommendation_id")) for item in embedded]
            child_ids = [item["recommendation_id"] for item in actual]
            actionable = sum(item["portfolio_action_status"] == "ACTIONABLE_BUY" for item in actual)
            child_content_matches = len(actual) == len(embedded) and all(
                child["ordinal"] == ordinal
                and child["recommendation_id"] == evidence.get("recommendation_id")
                and child["canonical_payload_json"] == canonical_json(evidence)
                and child["payload_sha256"] == payload_sha256(canonical_json(evidence))
                for ordinal, (child, evidence) in enumerate(zip(actual, embedded), start=1)
            )
            if not (
                row["recommendation_count"] == len(actual) == len(embedded)
                and row["actionable_recommendation_count"] == actionable
                and embedded_ids == child_ids
                and child_content_matches
            ):
                allocation_children_valid = False
                issues.append(f"allocation child mismatch in {row['allocation_run_id']}")
        checks["allocation_typed_columns"] = allocation_columns_valid
        checks["allocation_child_consistency"] = allocation_children_valid

        recommendation_mappings = {
            "recommendation_id": ("recommendation_id", "text"), "allocation_run_id": ("allocation_run_id", "text"),
            "signal_id": ("signal_id", "text"), "profile_version": ("profile_version", "int"),
            "ticker": ("ticker", "text"), "signal_date": ("signal_date", "text"), "decision_date": ("decision_date", "text"),
            "deterministic_signal": ("deterministic_signal", "text"), "setup": ("setup", "text"), "trade_quality": ("trade_quality", "text"),
            "technical_score": ("technical_score", "decimal"), "actionability_score": ("actionability_score", "decimal"),
            "planned_rr_t1": ("planned_rr_t1", "decimal"), "planned_rr_t2": ("planned_rr_t2", "decimal"), "rs60": ("rs60", "decimal"),
            "market_regime": ("market_regime", "text"), "market_score": ("market_score", "decimal"),
            "entry_low": ("entry_low", "decimal"), "entry_high": ("entry_high", "decimal"), "sizing_entry_price": ("sizing_entry_price", "decimal"),
            "stop": ("stop", "decimal"), "target_1": ("target_1", "decimal"), "target_2": ("target_2", "decimal"),
            "recommended_quantity": ("recommended_quantity", "int"), "estimated_purchase_value_inr": ("estimated_purchase_value_inr", "decimal"),
            "risk_budget_inr": ("risk_budget_inr", "decimal"), "risk_per_share_inr": ("risk_per_share_inr", "decimal"),
            "selected_horizon": ("selected_horizon", "text"), "management_policy_id": ("management_policy_id", "text"),
            "management_policy_source": ("management_policy_source", "text"), "management_policy_max_sessions": ("management_policy_max_sessions", "int"),
            "management_policy_validation_semantics": ("management_policy_validation_semantics", "text"), "horizon_status": ("horizon_status", "text"),
            "portfolio_action_status": ("portfolio_action_status", "text"), "plain_language_reason": ("plain_language_reason", "text"),
        }
        checks["recommendation_typed_columns"] = payload_rows("recommendations", "canonical_payload_json", recommendation_mappings)
        checks["event_typed_columns"] = payload_rows("recommendation_events", "payload_json", {
            "recommendation_id": ("recommendation_id", "text"), "event_type": ("event_type", "text"), "effective_date": ("effective_date", "text"),
        })
        checks["transaction_typed_columns"] = payload_rows("user_transactions", "canonical_payload_json", {
            "ticker": ("ticker", "text"), "trade_date": ("trade_date", "text"), "side": ("side", "text"), "quantity": ("quantity", "int"),
            "price_inr": ("price_inr", "decimal"), "fees_inr": ("fees_inr", "decimal"), "recommendation_id": ("recommendation_id", "text"),
            "signal_id": ("signal_id", "text"), "external_reference": ("external_reference", "text"), "notes": ("notes", "text"),
        })
        checks["void_typed_columns"] = payload_rows("transaction_voids", "canonical_payload_json", {
            "transaction_id": ("transaction_id", "text"), "reason": ("reason", "text"),
        })
        checks["opening_position_typed_columns"] = payload_rows("opening_positions", "canonical_payload_json", {
            "ticker": ("ticker", "text"), "effective_date": ("effective_date", "text"), "quantity": ("quantity", "int"),
            "average_cost_per_share_inr": ("average_cost_per_share_inr", "decimal"), "notes": ("notes", "text"),
        })
        checks["snapshot_typed_columns"] = payload_rows("position_state_snapshots", "canonical_payload_json", {
            "as_of_date": ("as_of_date", "text"), "ticker": ("ticker", "text"), "quantity": ("quantity", "int"),
            "average_cost_per_share_inr": ("average_cost_per_share_inr", "decimal"), "current_market_price_inr": ("current_market_price_inr", "decimal"),
            "market_value_inr": ("market_value_inr", "decimal"), "unrealized_pnl_inr": ("unrealized_pnl_inr", "decimal"),
            "management_policy_id": ("management_policy_id", "text"), "source_recommendation_id": ("source_recommendation_id", "text"),
            "source_signal_id": ("source_signal_id", "text"),
        })
        checks["outcome_typed_columns"] = payload_rows("recommendation_outcome_versions", "canonical_payload_json", {
            "recommendation_id": ("recommendation_id", "text"), "outcome_version": ("outcome_version", "int"), "as_of_date": ("as_of_date", "text"),
            "outcome_status": ("outcome_status", "text"), "entry_filled": ("entry_filled", "bool"), "entry_date": ("entry_date", "text"),
            "stop_hit": ("stop_hit", "bool"), "target_1_hit": ("target_1_hit", "bool"), "target_2_hit": ("target_2_hit", "bool"),
            "max_price_after_signal": ("max_price_after_signal", "decimal"), "min_price_after_signal": ("min_price_after_signal", "decimal"),
            "mfe_pct": ("mfe_pct", "decimal"), "mae_pct": ("mae_pct", "decimal"), "mfe_r": ("mfe_r", "decimal"), "mae_r": ("mae_r", "decimal"),
            "time_to_entry_sessions": ("time_to_entry_sessions", "int"), "time_to_t1_sessions": ("time_to_t1_sessions", "int"),
            "time_to_t2_sessions": ("time_to_t2_sessions", "int"), "holding_sessions": ("holding_sessions", "int"), "realized_r": ("realized_r", "decimal"),
            "exit_reason": ("exit_reason", "text"), "methodology_version": ("methodology_version", "text"), "source_data_hash": ("source_data_hash", "text"),
        })

        identity_valid = True
        identity_queries = (
            ("recommendation_events", "event_id", "idempotency_key", "S5D2_EVT_"),
            ("user_transactions", "transaction_id", "idempotency_key", "S5D2_TXN_"),
            ("transaction_voids", "void_id", "idempotency_key", "S5D2_VOID_"),
            ("opening_positions", "opening_position_id", "idempotency_key", "S5D2_OPEN_"),
        )
        for table, identity_column, key_column, prefix in identity_queries:
            for row in self.connection.execute(f"SELECT {identity_column},{key_column} FROM {table}"):
                if row[0] != _identity(prefix, row[1]):
                    identity_valid = False
                    issues.append(f"identity mismatch in {table}")
        for row in self.connection.execute("SELECT snapshot_id,as_of_date,ticker,source_recommendation_id,source_signal_id FROM position_state_snapshots"):
            identity_payload = canonical_json({"as_of_date": row[1], "ticker": row[2], "source_recommendation_id": row[3], "source_signal_id": row[4]})
            if row[0] != _identity("S5D2_SNAP_", identity_payload):
                identity_valid = False
                issues.append("identity mismatch in position_state_snapshots")
        checks["derived_identities"] = identity_valid
        transaction_lineage = True
        for row in self.connection.execute("""SELECT t.transaction_id,t.ticker,t.signal_id,r.ticker,r.signal_id FROM user_transactions t JOIN recommendations r ON r.recommendation_id=t.recommendation_id WHERE t.recommendation_id IS NOT NULL"""):
            if row[1] != row[3] or row[2] != row[4]:
                transaction_lineage = False
                issues.append(f"recommendation lineage mismatch in transaction {row[0]}")
        checks["transaction_recommendation_lineage"] = transaction_lineage
        snapshot_lineage = True
        for row in self.connection.execute("""SELECT s.snapshot_id,s.ticker,s.source_signal_id,r.ticker,r.signal_id FROM position_state_snapshots s JOIN recommendations r ON r.recommendation_id=s.source_recommendation_id WHERE s.source_recommendation_id IS NOT NULL"""):
            if row[1] != row[3] or (row[2] is not None and row[2] != row[4]):
                snapshot_lineage = False
                issues.append(f"recommendation lineage mismatch in snapshot {row[0]}")
        checks["snapshot_recommendation_lineage"] = snapshot_lineage
        repeated_voids = self.connection.execute("SELECT COUNT(*) FROM (SELECT transaction_id FROM transaction_voids GROUP BY transaction_id HAVING COUNT(*)>1)").fetchone()[0]
        checks["single_effective_void_per_transaction"] = repeated_voids == 0
        if repeated_voids:
            issues.append("multiple effective voids exist for one or more transactions")
        orphans = self.connection.execute("SELECT COUNT(*) FROM recommendations r LEFT JOIN allocation_runs a ON a.allocation_run_id=r.allocation_run_id WHERE a.allocation_run_id IS NULL").fetchone()[0]
        checks["recommendation_allocation_links"] = orphans == 0
        try:
            self._replay_positions()
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
