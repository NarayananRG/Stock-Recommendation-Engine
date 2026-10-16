from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA_VERSION = 3
PIT_VALID = {"FULL_PIT_VALID", "PIT_VALID_WITH_OPTIONAL_GAPS"}
BUY_ACTIONS = {"MOMENTUM BUY", "RECOVERY BUY", "MOMENTUM + RECOVERY BUY"}


@dataclass(frozen=True)
class ExecutionAssumptions:
    starting_capital: float = 100000.0
    slippage_bps: float = 10.0
    transaction_cost_bps: float = 5.0
    whole_shares: bool = True
    entry: str = "NEXT_OFFICIAL_OPEN"
    exit: str = "NEXT_OFFICIAL_OPEN"
    broker_execution: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{hashlib.sha256(_json(parts).encode()).hexdigest()[:24]}"


def evidence_hash(row: dict[str, Any]) -> str:
    evidence = row.get("evidence") or (row.get("live_decision") or {}).get("evidence") or {}
    return hashlib.sha256(_json(evidence).encode()).hexdigest()


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def pit_price_bars(bars: Iterable[dict[str, Any]], session: str) -> list[dict[str, Any]]:
    """Return only market observations known at the historical decision cutoff."""
    return [dict(bar) for bar in bars if str(bar.get("date") or "")[:10] <= session]


def pit_filings(filings: Iterable[dict[str, Any]], decision_cutoff: str) -> list[dict[str, Any]]:
    """Reject filings whose effective availability timestamp is after the cutoff."""
    return [
        dict(filing)
        for filing in filings
        if str(filing.get("effective_availability_ts") or "") <= decision_cutoff
    ]


def pit_valuation_observations(observations: Iterable[dict[str, Any]], session: str) -> list[dict[str, Any]]:
    """Historical valuation references may contain only earlier observations."""
    return [dict(row) for row in observations if str(row.get("session") or "") < session]


def freeze_point_in_time_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    """Detach a historical decision snapshot from mutable current evidence."""
    frozen = json.loads(_json(value))
    frozen["snapshot_sha256"] = hashlib.sha256(_json(frozen).encode()).hexdigest()
    return frozen


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args: Any) -> bool | None:
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None, factory=_ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    con.execute("pragma journal_mode=WAL")
    con.execute("pragma synchronous=FULL")
    migrate(con)
    return con


def migrate(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        create table if not exists validation_schema_meta_v2 (
          key text primary key, value text not null
        );
        create table if not exists paper_v2_portfolios (
          portfolio_id text primary key, created_at text not null, status text not null,
          starting_capital real not null, starting_session text not null,
          starting_run_id text not null, app_version text not null,
          production_model_version text not null, evidence_pipeline_version text not null,
          router_sha256 text not null, state_json text not null
        );
        create unique index if not exists paper_v2_one_active
          on paper_v2_portfolios(status) where status='ACTIVE';
        create table if not exists paper_v2_positions (
          position_id text primary key, portfolio_id text not null, symbol text not null,
          state text not null, qty integer not null, entry_price real not null,
          position_json text not null,
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create index if not exists paper_v2_positions_lookup
          on paper_v2_positions(portfolio_id,symbol,state);
        create table if not exists paper_v2_orders (
          order_id text primary key, portfolio_id text not null, symbol text not null,
          side text not null, state text not null, signal_session text not null,
          fill_session text, reserved_capital real not null default 0,
          order_json text not null,
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create index if not exists paper_v2_orders_lookup
          on paper_v2_orders(portfolio_id,state,signal_session);
        create table if not exists paper_v2_journal (
          event_id text primary key, portfolio_id text not null, market_session text not null,
          production_run_id text not null, event_type text not null,
          idempotency_key text not null unique, created_at text not null, event_json text not null,
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create table if not exists paper_v2_nav (
          portfolio_id text not null, market_session text not null, nav_json text not null,
          primary key(portfolio_id,market_session),
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create table if not exists paper_v2_session_commits (
          portfolio_id text not null, market_session text not null, production_run_id text not null,
          result_json text not null, committed_at text not null,
          primary key(portfolio_id,market_session),
          foreign key(portfolio_id) references paper_v2_portfolios(portfolio_id)
        );
        create table if not exists replay_v2_runs (
          replay_id text primary key, created_at text not null, config_json text not null,
          result_json text not null
        );
        create table if not exists replay_v2_sessions (
          replay_id text not null, market_session text not null, replayability text not null,
          coverage_json text not null, session_json text,
          primary key(replay_id,market_session)
        );
        """
    )
    con.execute(
        "insert into validation_schema_meta_v2(key,value) values('schema_version',?) "
        "on conflict(key) do update set value=excluded.value",
        (str(SCHEMA_VERSION),),
    )


def legacy_portfolios(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as con:
        exists = con.execute(
            "select 1 from sqlite_master where type='table' and name='paper_portfolios'"
        ).fetchone()
        if not exists:
            return []
        return [
            {
                "portfolio_id": row[0],
                "created_at": row[1],
                "starting_session": row[2],
                "starting_capital": row[3],
                "classification": "LEGACY_VALIDATION_V1",
                "read_only": True,
                "excluded_from_v2_performance": True,
            }
            for row in con.execute(
                "select portfolio_id,created_at,starting_session,starting_capital "
                "from paper_portfolios order by created_at desc"
            )
        ]


def create_portfolio(
    db_path: Path,
    *,
    starting_session: str,
    starting_run_id: str,
    starting_capital: float = 100000.0,
    app_version: str,
    production_model_version: str,
    evidence_pipeline_version: str,
    router_sha256: str,
) -> dict[str, Any]:
    if not starting_session or not starting_run_id:
        raise ValueError("CURRENT_ACCEPTED_PRODUCTION_RUN_REQUIRED")
    if not math.isfinite(float(starting_capital)) or float(starting_capital) <= 0:
        raise ValueError("STARTING_CAPITAL_MUST_BE_POSITIVE")
    created = _now()
    portfolio_id = stable_id("SREVP2", created, uuid.uuid4().hex, starting_run_id)
    state = {
        "portfolio_id": portfolio_id,
        "created_at": created,
        "status": "ACTIVE",
        "starting_capital": round(float(starting_capital), 2),
        "cash": round(float(starting_capital), 2),
        "nav": round(float(starting_capital), 2),
        "invested_value": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "exposure": 0.0,
        "valuation_quality": "CURRENT_OFFICIAL_MARKS",
    }
    with _connect(db_path) as con:
        con.execute("begin immediate")
        try:
            con.execute("update paper_v2_portfolios set status='PREVIOUS' where status='ACTIVE'")
            con.execute(
                "insert into paper_v2_portfolios values(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    portfolio_id, created, "ACTIVE", state["starting_capital"], starting_session,
                    starting_run_id, app_version, production_model_version,
                    evidence_pipeline_version, router_sha256, _json(state),
                ),
            )
            con.execute(
                "insert into paper_v2_nav values(?,?,?)",
                (portfolio_id, starting_session, _json({"market_session": starting_session, **state})),
            )
            con.commit()
        except Exception:
            con.rollback()
            raise
    return load_portfolio(db_path, portfolio_id)


def _portfolio_row(con: sqlite3.Connection, portfolio_id: str) -> sqlite3.Row:
    row = con.execute("select * from paper_v2_portfolios where portfolio_id=?", (portfolio_id,)).fetchone()
    if not row:
        raise ValueError("PAPER_V2_PORTFOLIO_NOT_FOUND")
    return row


def _loads_rows(rows: Iterable[sqlite3.Row], column: str) -> list[dict[str, Any]]:
    return [json.loads(row[column]) for row in rows]


def list_portfolios(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as con:
        return [
            {
                "portfolio_id": row["portfolio_id"], "created_at": row["created_at"],
                "status": row["status"], "starting_capital": row["starting_capital"],
                "starting_session": row["starting_session"], "starting_run_id": row["starting_run_id"],
                "app_version": row["app_version"], "production_model_version": row["production_model_version"],
                "evidence_pipeline_version": row["evidence_pipeline_version"],
            }
            for row in con.execute("select * from paper_v2_portfolios order by created_at desc")
        ]


def load_portfolio(db_path: Path, portfolio_id: str | None = None) -> dict[str, Any]:
    with _connect(db_path) as con:
        if portfolio_id is None:
            found = con.execute("select portfolio_id from paper_v2_portfolios where status='ACTIVE'").fetchone()
            if not found:
                return {
                    "active": False,
                    "schema": "SRE_PAPER_PORTFOLIO_V2",
                    "starting_capital": 100000.0,
                    "portfolios": list_portfolios(db_path),
                    "legacy_portfolios": legacy_portfolios(db_path),
                }
            portfolio_id = found[0]
        row = _portfolio_row(con, portfolio_id)
        state = json.loads(row["state_json"])
        positions = _loads_rows(
            con.execute("select position_json from paper_v2_positions where portfolio_id=? order by symbol,position_id", (portfolio_id,)),
            "position_json",
        )
        pending = _loads_rows(
            con.execute("select order_json from paper_v2_orders where portfolio_id=? and state like 'PENDING%' order by signal_session,symbol", (portfolio_id,)),
            "order_json",
        )
        journal = _loads_rows(
            con.execute("select event_json from paper_v2_journal where portfolio_id=? order by created_at desc,event_id desc limit 500", (portfolio_id,)),
            "event_json",
        )
        nav = _loads_rows(
            con.execute("select nav_json from paper_v2_nav where portfolio_id=? order by market_session", (portfolio_id,)),
            "nav_json",
        )
        pending_capital = round(sum(float(x.get("reserved_capital") or 0) for x in pending if x.get("side") == "BUY"), 2)
        return {
            **state,
            "schema": "SRE_PAPER_PORTFOLIO_V2",
            "active": row["status"] == "ACTIVE",
            "read_only": row["status"] != "ACTIVE",
            "starting_session": row["starting_session"],
            "starting_run_id": row["starting_run_id"],
            "app_version": row["app_version"],
            "production_model_version": row["production_model_version"],
            "evidence_pipeline_version": row["evidence_pipeline_version"],
            "router_sha256": row["router_sha256"],
            "positions": positions,
            "pending_orders": pending,
            "pending_capital": pending_capital,
            "journal": journal,
            "nav_history": nav,
            "portfolios": list_portfolios(db_path),
            "legacy_portfolios": legacy_portfolios(db_path),
        }


def _event(
    con: sqlite3.Connection,
    *,
    portfolio_id: str,
    session: str,
    run_id: str,
    event_type: str,
    symbol: str = "PORTFOLIO",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = f"{portfolio_id}|{session}|{run_id}|{event_type}|{symbol}"
    event = {
        "schema": "SRE_PAPER_JOURNAL_V2",
        "event_id": stable_id("SREV2", key),
        "portfolio_id": portfolio_id,
        "market_session": session,
        "production_run_id": run_id,
        "event_type": event_type,
        "symbol": symbol,
        "created_at": _now(),
        **(payload or {}),
    }
    con.execute(
        "insert or ignore into paper_v2_journal values(?,?,?,?,?,?,?,?)",
        (event["event_id"], portfolio_id, session, run_id, event_type, key, event["created_at"], _json(event)),
    )
    saved = con.execute("select event_json from paper_v2_journal where idempotency_key=?", (key,)).fetchone()
    return json.loads(saved[0])


def _fill_terms(open_price: float, side: str, assumptions: ExecutionAssumptions) -> dict[str, float]:
    price = float(open_price)
    slip = price * assumptions.slippage_bps / 10000.0
    fill = price + slip if side == "BUY" else price - slip
    cost = price * assumptions.transaction_cost_bps / 10000.0
    return {
        "official_open": round(price, 6),
        "simulated_fill_price": round(fill, 6),
        "transaction_cost_per_share": round(cost, 6),
        "net_price": round(fill + cost if side == "BUY" else fill - cost, 6),
    }


def _revalue(con: sqlite3.Connection, portfolio_id: str, state: dict[str, Any], session: str) -> None:
    positions = _loads_rows(
        con.execute("select position_json from paper_v2_positions where portfolio_id=? and state!='CLOSED'", (portfolio_id,)),
        "position_json",
    )
    invested = sum(int(p["qty"]) * float(p.get("current_mark_price") or p["entry_price"]) for p in positions)
    unrealized = sum(float(p.get("unrealized_pnl") or 0) for p in positions)
    current = all(p.get("current_mark_session") == session for p in positions)
    state.update(
        invested_value=round(invested, 2),
        unrealized_pnl=round(unrealized, 2),
        nav=round(float(state["cash"]) + invested, 2),
        valuation_quality="CURRENT_OFFICIAL_MARKS" if current else "STALE_MARK",
    )
    state["exposure"] = round(invested / state["nav"], 6) if state["nav"] else 0.0


def process_paper_session(
    db_path: Path,
    *,
    portfolio_id: str,
    expected_session: str,
    latest_official_session: str,
    official_freshness: str,
    production_session: str,
    production_run_id: str,
    app_version: str,
    production_model_version: str,
    evidence_pipeline_version: str,
    candidates: list[dict[str, Any]],
    allocation_plan: dict[str, Any],
    official_opens: dict[str, float],
    official_closes: dict[str, float],
    monitoring: dict[str, dict[str, Any]] | None = None,
    assumptions: ExecutionAssumptions | None = None,
    crash_hook: str | None = None,
) -> dict[str, Any]:
    assumptions = assumptions or ExecutionAssumptions()
    if latest_official_session != expected_session or official_freshness != "PASS":
        return {"status": "NO PAPER ACTION — OFFICIAL DATA NOT READY", "recorded": False}
    if production_session != expected_session or not production_run_id:
        return {"status": "NO PAPER ACTION — PRODUCTION ANALYSIS NOT CURRENT", "recorded": False}
    monitoring = monitoring or {}
    with _connect(db_path) as con:
        con.execute("begin immediate")
        try:
            portfolio = _portfolio_row(con, portfolio_id)
            if portfolio["status"] != "ACTIVE":
                raise ValueError("PAPER_V2_PORTFOLIO_IS_READ_ONLY")
            duplicate = con.execute(
                "select result_json from paper_v2_session_commits where portfolio_id=? and market_session=?",
                (portfolio_id, expected_session),
            ).fetchone()
            if duplicate:
                result = json.loads(duplicate[0])
                result["duplicate"] = True
                con.rollback()
                return result
            state = json.loads(portfolio["state_json"])
            fills: list[dict[str, Any]] = []
            orders = con.execute(
                "select * from paper_v2_orders where portfolio_id=? and state like 'PENDING%' order by signal_session,order_id",
                (portfolio_id,),
            ).fetchall()
            for stored in orders:
                order = json.loads(stored["order_json"])
                if order["signal_session"] >= expected_session:
                    continue
                open_price = _finite(official_opens.get(order["symbol"]))
                if open_price is None or open_price <= 0:
                    continue
                terms = _fill_terms(open_price, order["side"], assumptions)
                if order["side"] == "BUY":
                    budget = min(float(state["cash"]), float(order["reserved_capital"]))
                    qty = int(budget // terms["net_price"])
                    if qty <= 0:
                        continue
                    total = round(qty * terms["net_price"], 2)
                    state["cash"] = round(float(state["cash"]) - total, 2)
                    position = {
                        "position_id": stable_id("SREVP2POS", portfolio_id, order["symbol"], order["order_id"]),
                        "portfolio_id": portfolio_id, "symbol": order["symbol"], "qty": qty, "state": "HOLD",
                        "entry_signal_session": order["signal_session"], "entry_fill_session": expected_session,
                        "entry_price": terms["net_price"], "current_mark_session": expected_session,
                        "current_mark_price": terms["net_price"], "current_state": "HOLD",
                        "current_thesis_health": "ENTRY", "unrealized_pnl": 0.0,
                        "strategy": order.get("strategy"), "confidence": order.get("confidence"),
                        "thesis_snapshot": order.get("thesis_snapshot"), "evidence_hash": order.get("evidence_hash"),
                    }
                    con.execute(
                        "insert into paper_v2_positions values(?,?,?,?,?,?,?)",
                        (position["position_id"], portfolio_id, position["symbol"], "HOLD", qty, position["entry_price"], _json(position)),
                    )
                    event_type = "BUY FILLED"
                    payload = {"order_id": order["order_id"], "signal_session": order["signal_session"], "fill_session": expected_session, "quantity": qty, "total_cost": total, **terms}
                else:
                    found = con.execute(
                        "select * from paper_v2_positions where portfolio_id=? and symbol=? and state!='CLOSED' order by rowid limit 1",
                        (portfolio_id, order["symbol"]),
                    ).fetchone()
                    if not found:
                        continue
                    position = json.loads(found["position_json"])
                    proceeds = round(int(position["qty"]) * terms["net_price"], 2)
                    pnl = round(proceeds - int(position["qty"]) * float(position["entry_price"]), 2)
                    state["cash"] = round(float(state["cash"]) + proceeds, 2)
                    state["realized_pnl"] = round(float(state.get("realized_pnl") or 0) + pnl, 2)
                    position.update(state="CLOSED", current_state="CLOSED", exit_signal_session=order["signal_session"], exit_fill_session=expected_session, exit_price=terms["net_price"], realized_pnl=pnl)
                    con.execute("update paper_v2_positions set state='CLOSED',position_json=? where position_id=?", (_json(position), found["position_id"]))
                    event_type = "EXIT FILLED"
                    payload = {"order_id": order["order_id"], "signal_session": order["signal_session"], "fill_session": expected_session, "quantity": position["qty"], "proceeds": proceeds, "realized_pnl": pnl, **terms}
                order.update(state="FILLED", fill_session=expected_session, fill=terms)
                con.execute(
                    "update paper_v2_orders set state='FILLED',fill_session=?,reserved_capital=0,order_json=? where order_id=?",
                    (expected_session, _json(order), order["order_id"]),
                )
                fills.append(_event(con, portfolio_id=portfolio_id, session=expected_session, run_id=production_run_id, event_type=event_type, symbol=order["symbol"], payload=payload))
            if crash_hook == "AFTER_FILL_JOURNAL":
                raise RuntimeError("SIMULATED_CRASH_AFTER_FILL_JOURNAL")

            active_positions = con.execute(
                "select * from paper_v2_positions where portfolio_id=? and state!='CLOSED' order by symbol",
                (portfolio_id,),
            ).fetchall()
            pending_exit_symbols = {
                row[0] for row in con.execute(
                    "select symbol from paper_v2_orders where portfolio_id=? and state='PENDING_EXIT_NEXT_OPEN'",
                    (portfolio_id,),
                )
            }
            monitoring_events = []
            for stored in active_positions:
                position = json.loads(stored["position_json"])
                symbol = position["symbol"]
                mark = _finite(official_closes.get(symbol))
                if mark is not None and mark > 0:
                    position["current_mark_session"] = expected_session
                    position["current_mark_price"] = mark
                    position["unrealized_pnl"] = round(int(position["qty"]) * (mark - float(position["entry_price"])), 2)
                else:
                    position["mark_status"] = "STALE MARK"
                monitor = monitoring.get(symbol) or {"state": "HOLD", "reason": "No exit or weakening signal"}
                monitor_state = str(monitor.get("state") or "HOLD").upper()
                if monitor_state not in {"HOLD", "WEAKENING", "EXIT SIGNAL"}:
                    monitor_state = "HOLD"
                position["current_state"] = monitor_state
                position["current_thesis_health"] = monitor.get("reason") or monitor_state
                db_state = "PENDING_EXIT_NEXT_OPEN" if monitor_state == "EXIT SIGNAL" else monitor_state
                if monitor_state == "EXIT SIGNAL" and symbol not in pending_exit_symbols:
                    order_id = stable_id("SREVP2ORD", portfolio_id, symbol, expected_session, production_run_id, "SELL")
                    order = {"order_id": order_id, "portfolio_id": portfolio_id, "symbol": symbol, "side": "SELL", "state": "PENDING_EXIT_NEXT_OPEN", "signal_session": expected_session, "production_run_id": production_run_id}
                    con.execute("insert into paper_v2_orders values(?,?,?,?,?,?,?,?,?)", (order_id, portfolio_id, symbol, "SELL", order["state"], expected_session, None, 0.0, _json(order)))
                    monitoring_events.append(_event(con, portfolio_id=portfolio_id, session=expected_session, run_id=production_run_id, event_type="EXIT SIGNAL", symbol=symbol, payload={"reason": position["current_thesis_health"], "order_id": order_id}))
                else:
                    monitoring_events.append(_event(con, portfolio_id=portfolio_id, session=expected_session, run_id=production_run_id, event_type=monitor_state, symbol=symbol, payload={"reason": position["current_thesis_health"]}))
                con.execute("update paper_v2_positions set state=?,position_json=? where position_id=?", (db_state, _json(position), stored["position_id"]))

            held = {row[0] for row in con.execute("select symbol from paper_v2_positions where portfolio_id=? and state!='CLOSED'", (portfolio_id,))}
            pending = {row[0] for row in con.execute("select symbol from paper_v2_orders where portfolio_id=? and state like 'PENDING%'", (portfolio_id,))}
            reserved = float(con.execute("select coalesce(sum(reserved_capital),0) from paper_v2_orders where portfolio_id=? and state='PENDING_NEXT_OPEN'", (portfolio_id,)).fetchone()[0])
            available = max(0.0, float(state["cash"]) - reserved)
            allocations = {str(x.get("symbol") or x.get("ticker") or "").upper(): x for x in allocation_plan.get("new_buys", [])}
            new_orders = []
            for row in candidates:
                live = row.get("live_decision") or row
                symbol = str(row.get("symbol") or row.get("ticker") or "").upper().replace(".NS", "")
                action = str(live.get("final_action") or row.get("final_action") or row.get("opportunity_status") or "").upper()
                if not symbol or action not in BUY_ACTIONS or live.get("executable", row.get("executable")) is not True:
                    continue
                if str(row.get("market_session") or production_session) != expected_session or symbol in held or symbol in pending:
                    continue
                allocation = allocations.get(symbol)
                capital = _finite((allocation or {}).get("estimated_cost") or (allocation or {}).get("capital"))
                if capital is None or capital <= 0 or capital > available + 0.005:
                    continue
                available -= capital
                order_id = stable_id("SREVP2ORD", portfolio_id, symbol, expected_session, production_run_id, "BUY")
                order = {
                    "order_id": order_id, "portfolio_id": portfolio_id, "symbol": symbol, "side": "BUY",
                    "state": "PENDING_NEXT_OPEN", "signal_session": expected_session,
                    "production_run_id": production_run_id, "live_decision_v1_action": action,
                    "strategy": live.get("strategy_style") or row.get("strategy_style"),
                    "confidence": live.get("confidence") or row.get("confidence_label"),
                    "reserved_capital": round(capital, 2), "allocation": allocation,
                    "thesis_snapshot": {"momentum": live.get("momentum_thesis"), "recovery": live.get("recovery_thesis"), "invalidation": live.get("invalidation")},
                    "evidence_snapshot": live.get("evidence") or row.get("evidence") or {},
                    "evidence_hash": evidence_hash(row), "app_version": app_version,
                    "production_model_version": production_model_version,
                    "evidence_pipeline_version": evidence_pipeline_version,
                }
                con.execute("insert into paper_v2_orders values(?,?,?,?,?,?,?,?,?)", (order_id, portfolio_id, symbol, "BUY", order["state"], expected_session, None, capital, _json(order)))
                new_orders.append(order)
                _event(con, portfolio_id=portfolio_id, session=expected_session, run_id=production_run_id, event_type="BUY SIGNAL", symbol=symbol, payload={"order_id": order_id, "allocation": allocation, "action": action, "evidence_hash": order["evidence_hash"]})
            _revalue(con, portfolio_id, state, expected_session)
            con.execute("update paper_v2_portfolios set state_json=? where portfolio_id=?", (_json(state), portfolio_id))
            nav_record = {"market_session": expected_session, "cash": state["cash"], "invested_value": state["invested_value"], "nav": state["nav"], "realized_pnl": state["realized_pnl"], "unrealized_pnl": state["unrealized_pnl"], "valuation_quality": state["valuation_quality"]}
            con.execute("insert or replace into paper_v2_nav values(?,?,?)", (portfolio_id, expected_session, _json(nav_record)))
            result = {"status": "RECORDED", "recorded": True, "duplicate": False, "market_session": expected_session, "production_run_id": production_run_id, "fills": fills, "monitoring_events": monitoring_events, "new_orders": new_orders, **nav_record}
            con.execute("insert into paper_v2_session_commits values(?,?,?,?,?)", (portfolio_id, expected_session, production_run_id, _json(result), _now()))
            con.commit()
            return result
        except Exception:
            con.rollback()
            raise


def max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return round(worst, 6)


def run_replay(
    *,
    requested_period: str,
    sessions: list[str],
    starting_capital: float,
    assumptions: ExecutionAssumptions,
    session_provider: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    state: dict[str, Any] = {"cash": float(starting_capital), "positions": {}, "pending": [], "trades": [], "realized_pnl": 0.0}
    coverage: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    benchmark_units: float | None = None
    benchmark_complete = True
    buy_signals = filled_entries = exits = cash_streak = longest_cash = 0
    for session in sessions:
        package = freeze_point_in_time_snapshot(session_provider(session, state))
        replayability = package.get("replayability") or "NOT_REPLAYABLE"
        coverage_row = {
            "date": session,
            "market_data_status": package.get("market_data_status", "MISSING"),
            "fundamental_pit_status": package.get("fundamental_pit_status", "MISSING"),
            "valuation_pit_status": package.get("valuation_pit_status", "MISSING"),
            "universe_status": package.get("universe_status", "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS"),
            "live_decision_v1_run_status": package.get("live_decision_v1_run_status", "NOT_RUN"),
            "replayability": replayability,
        }
        coverage.append(coverage_row)
        if replayability not in PIT_VALID:
            continue
        opens = package.get("opens") or {}
        closes = package.get("closes") or {}
        remaining = []
        for order in state["pending"]:
            if order["signal_session"] >= session or _finite(opens.get(order["symbol"])) is None:
                remaining.append(order)
                continue
            terms = _fill_terms(float(opens[order["symbol"]]), order["side"], assumptions)
            if order["side"] == "BUY":
                qty = int(min(state["cash"], order["capital"]) // terms["net_price"])
                if qty <= 0:
                    continue
                total = round(qty * terms["net_price"], 2)
                state["cash"] -= total
                state["positions"][order["symbol"]] = {"symbol": order["symbol"], "qty": qty, "entry_price": terms["net_price"], "entry_session": session, "signal_session": order["signal_session"], "last_price": terms["net_price"]}
                filled_entries += 1
            else:
                pos = state["positions"].pop(order["symbol"], None)
                if pos:
                    proceeds = round(pos["qty"] * terms["net_price"], 2)
                    pnl = round(proceeds - pos["qty"] * pos["entry_price"], 2)
                    state["cash"] += proceeds
                    state["realized_pnl"] += pnl
                    state["trades"].append({**pos, "exit_session": session, "exit_price": terms["net_price"], "realized_pnl": pnl, "state": "CLOSED"})
                    exits += 1
        state["pending"] = remaining
        rows = package.get("rows") or []
        by_symbol = {str(r.get("symbol") or "").upper(): r for r in rows}
        pending_symbols = {o["symbol"] for o in state["pending"]}
        for symbol, pos in list(state["positions"].items()):
            mark = _finite(closes.get(symbol))
            if mark is not None:
                pos["last_price"] = mark
            action = str((by_symbol.get(symbol) or {}).get("monitoring_action") or "HOLD").upper()
            if action == "EXIT SIGNAL" and symbol not in pending_symbols:
                state["pending"].append({"symbol": symbol, "side": "SELL", "signal_session": session, "capital": 0})
                pending_symbols.add(symbol)
        plan = package.get("allocation_plan") or {"new_buys": []}
        allocations = {str(x.get("symbol") or "").upper(): x for x in plan.get("new_buys", [])}
        reserved = sum(float(o.get("capital") or 0) for o in state["pending"] if o["side"] == "BUY")
        available = max(0.0, state["cash"] - reserved)
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            live = row.get("live_decision") or row
            action = str(live.get("final_action") or row.get("final_action") or "").upper()
            allocation = allocations.get(symbol)
            capital = _finite((allocation or {}).get("estimated_cost") or (allocation or {}).get("capital"))
            if action not in BUY_ACTIONS or live.get("executable", row.get("executable")) is not True or not capital:
                continue
            buy_signals += 1
            if symbol in state["positions"] or symbol in pending_symbols or capital > available + 0.005:
                continue
            state["pending"].append({"symbol": symbol, "side": "BUY", "signal_session": session, "capital": capital})
            pending_symbols.add(symbol)
            available -= capital
        invested = sum(p["qty"] * p["last_price"] for p in state["positions"].values())
        unrealized = sum(p["qty"] * (p["last_price"] - p["entry_price"]) for p in state["positions"].values())
        nav = round(state["cash"] + invested, 2)
        benchmark_close = _finite(package.get("benchmark_close"))
        if benchmark_close is None or benchmark_close <= 0:
            benchmark_complete = False
            benchmark_nav = None
        else:
            if benchmark_units is None:
                benchmark_units = starting_capital / benchmark_close
            benchmark_nav = round(benchmark_units * benchmark_close, 2)
        cash_streak = cash_streak + 1 if not state["positions"] else 0
        longest_cash = max(longest_cash, cash_streak)
        series.append({"date": session, "portfolio_nav": nav, "benchmark_nav": benchmark_nav, "cash": round(state["cash"], 2), "invested_value": round(invested, 2), "realized_pnl": round(state["realized_pnl"], 2), "unrealized_pnl": round(unrealized, 2), "exposure": round(invested / nav, 6) if nav else 0.0})
    portfolio_values = [x["portfolio_nav"] for x in series]
    benchmark_values = [x["benchmark_nav"] for x in series if x["benchmark_nav"] is not None]
    portfolio_return = round(portfolio_values[-1] / starting_capital - 1, 6) if portfolio_values else None
    benchmark_return = round(benchmark_values[-1] / starting_capital - 1, 6) if benchmark_complete and benchmark_values else None
    closed = state["trades"]
    wins = [x for x in closed if x["realized_pnl"] > 0]
    replayable_dates = [x["date"] for x in series]
    metrics = {
        "start_nav": starting_capital if series else None,
        "end_nav": portfolio_values[-1] if portfolio_values else None,
        "portfolio_return": portfolio_return,
        "benchmark_return": benchmark_return,
        "excess_return": round(portfolio_return - benchmark_return, 6) if portfolio_return is not None and benchmark_return is not None else None,
        "max_drawdown": max_drawdown(portfolio_values),
        "buy_signals": buy_signals,
        "filled_entries": filled_entries,
        "exits": exits,
        "closed_trades": len(closed),
        "realized_pnl": round(state["realized_pnl"], 2) if series else None,
        "unrealized_pnl": series[-1]["unrealized_pnl"] if series else None,
        "cash": series[-1]["cash"] if series else None,
        "exposure": series[-1]["exposure"] if series else None,
        "win_rate": round(len(wins) / len(closed), 6) if len(closed) >= 3 else None,
        "longest_cash_only_period": longest_cash if series else None,
        "buy_frequency": round(buy_signals / len(series), 6) if series else None,
    }
    return {
        "schema": "SRE_POINT_IN_TIME_HISTORICAL_REPLAY_V2",
        "label": "POINT-IN-TIME HISTORICAL SIMULATION",
        "requested_period": requested_period,
        "requested_range": {"start": sessions[0] if sessions else None, "end": sessions[-1] if sessions else None},
        "trustworthy_replayable_range": {"start": replayable_dates[0] if replayable_dates else None, "end": replayable_dates[-1] if replayable_dates else None},
        "sessions_replayed": len(series),
        "sessions_excluded": len(coverage) - len(series),
        "pit_completeness": "COMPLETE" if coverage and len(series) == len(coverage) else ("PARTIAL" if series else "NOT REPLAYABLE"),
        "survivorship_bias_warning": any(x["universe_status"] == "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS" for x in coverage),
        "execution_assumptions": asdict(assumptions),
        "coverage": coverage,
        "series": series,
        "trades": closed,
        "metrics": metrics,
        "benchmark_status": "ACTUAL_NIFTY_50" if benchmark_complete and series else "NOT AVAILABLE — INCOMPLETE NIFTY 50 HISTORY",
    }


def persist_replay(db_path: Path, result: dict[str, Any], config: dict[str, Any]) -> str:
    replay_id = stable_id("SREVR2", config, result.get("coverage"))
    with _connect(db_path) as con:
        con.execute("begin immediate")
        try:
            con.execute("insert or replace into replay_v2_runs values(?,?,?,?)", (replay_id, _now(), _json(config), _json({**result, "replay_id": replay_id})))
            for row in result.get("coverage", []):
                session = next((x for x in result.get("series", []) if x["date"] == row["date"]), None)
                con.execute("insert or replace into replay_v2_sessions values(?,?,?,?,?)", (replay_id, row["date"], row["replayability"], _json(row), _json(session) if session else None))
            con.commit()
        except Exception:
            con.rollback()
            raise
    return replay_id
