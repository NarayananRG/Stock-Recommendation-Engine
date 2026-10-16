"""Validation V2: forward-only paper portfolio and truthful replay primitives.

This module is deliberately independent of legacy Phase 8.1 tables.  It consumes
LIVE_DECISION_V1 outputs; it never changes production recommendation authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA_VERSION = 2
BUY_ACTIONS = {"MOMENTUM BUY", "RECOVERY BUY", "MOMENTUM + RECOVERY BUY", "BOTH BUY"}
OPEN_POSITION_STATES = {"HELD", "WEAKENING"}
PENDING_STATES = {"PENDING_NEXT_OPEN", "PENDING_EXIT_NEXT_OPEN"}


@dataclass(frozen=True)
class ExecutionAssumptions:
    slippage_bps: float = 10.0
    transaction_cost_bps: float = 5.0
    whole_shares: bool = True
    broker_execution: bool = False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return prefix + "_" + hashlib.sha256(raw).hexdigest()[:20]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("pragma foreign_keys=on")
    con.execute("pragma journal_mode=WAL")
    con.execute(
        """create table if not exists v2_meta(
            key text primary key,
            value text not null
        )"""
    )
    con.execute(
        """create table if not exists v2_portfolios(
            portfolio_id text primary key,
            created_at text not null,
            start_session text not null,
            start_production_run_id text,
            starting_capital real not null,
            app_version text not null,
            model_version text not null,
            evidence_version text not null,
            status text not null,
            state_json text not null
        )"""
    )
    con.execute(
        """create table if not exists v2_orders(
            order_id text primary key,
            portfolio_id text not null,
            symbol text not null,
            side text not null,
            state text not null,
            signal_session text not null,
            fill_session text,
            production_run_id text,
            order_json text not null,
            foreign key(portfolio_id) references v2_portfolios(portfolio_id)
        )"""
    )
    con.execute(
        """create table if not exists v2_positions(
            position_id text primary key,
            portfolio_id text not null,
            symbol text not null,
            state text not null,
            qty integer not null,
            entry_price real not null,
            state_json text not null,
            foreign key(portfolio_id) references v2_portfolios(portfolio_id)
        )"""
    )
    con.execute(
        """create table if not exists v2_journal(
            event_id text primary key,
            portfolio_id text not null,
            market_session text not null,
            production_run_id text,
            event_type text not null,
            idempotency_key text not null unique,
            created_at text not null,
            event_json text not null,
            foreign key(portfolio_id) references v2_portfolios(portfolio_id)
        )"""
    )
    con.execute(
        """create table if not exists v2_nav(
            portfolio_id text not null,
            market_session text not null,
            nav real not null,
            cash real not null,
            invested_value real not null,
            benchmark_value real,
            valuation_quality text not null,
            nav_json text not null,
            primary key(portfolio_id, market_session),
            foreign key(portfolio_id) references v2_portfolios(portfolio_id)
        )"""
    )
    con.execute(
        """create table if not exists v2_replays(
            replay_id text primary key,
            created_at text not null,
            config_json text not null,
            result_json text not null
        )"""
    )
    con.execute("insert or replace into v2_meta(key,value) values('schema_version',?)", (str(SCHEMA_VERSION),))
    return con


def create_portfolio(
    db_path: Path,
    *,
    start_session: str,
    starting_capital: float,
    start_production_run_id: str | None,
    app_version: str,
    model_version: str,
    evidence_version: str,
) -> dict[str, Any]:
    if not math.isfinite(float(starting_capital)) or float(starting_capital) <= 0:
        raise ValueError("STARTING_CAPITAL_MUST_BE_POSITIVE")
    created_at = _now()
    payload = {
        "start_session": start_session,
        "start_production_run_id": start_production_run_id,
        "starting_capital": float(starting_capital),
        "app_version": app_version,
        "model_version": model_version,
        "evidence_version": evidence_version,
        "created_at": created_at,
    }
    portfolio_id = _stable_id("SREV2P", payload)
    state = {
        "schema": "SRE_VALIDATION_V2_PAPER_STATE",
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": portfolio_id,
        "created_at": created_at,
        "start_session": start_session,
        "start_production_run_id": start_production_run_id,
        "starting_capital": float(starting_capital),
        "cash": float(starting_capital),
        "nav": float(starting_capital),
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "status": "ACTIVE",
        "app_version": app_version,
        "model_version": model_version,
        "evidence_version": evidence_version,
        "broker_execution": False,
    }
    with connect(db_path) as con:
        con.execute(
            "insert into v2_portfolios values(?,?,?,?,?,?,?,?,?,?)",
            (
                portfolio_id,
                created_at,
                start_session,
                start_production_run_id,
                float(starting_capital),
                app_version,
                model_version,
                evidence_version,
                "ACTIVE",
                _json(state),
            ),
        )
        con.execute(
            "insert into v2_nav values(?,?,?,?,?,?,?,?)",
            (
                portfolio_id,
                start_session,
                float(starting_capital),
                float(starting_capital),
                0.0,
                None,
                "STARTING_CASH",
                _json({"session": start_session, "nav": starting_capital, "cash": starting_capital}),
            ),
        )
    return load_portfolio(db_path, portfolio_id)


def list_portfolios(db_path: Path) -> list[dict[str, Any]]:
    with connect(db_path) as con:
        rows = con.execute(
            "select portfolio_id,created_at,start_session,start_production_run_id,starting_capital,app_version,model_version,evidence_version,status "
            "from v2_portfolios order by created_at desc"
        ).fetchall()
    keys = [
        "portfolio_id", "created_at", "start_session", "start_production_run_id",
        "starting_capital", "app_version", "model_version", "evidence_version", "status",
    ]
    return [dict(zip(keys, row)) for row in rows]


def _load_state(con: sqlite3.Connection, portfolio_id: str) -> dict[str, Any]:
    row = con.execute("select state_json from v2_portfolios where portfolio_id=?", (portfolio_id,)).fetchone()
    if not row:
        raise ValueError("V2_PORTFOLIO_NOT_FOUND")
    return json.loads(row[0])


def _save_state(con: sqlite3.Connection, state: dict[str, Any]) -> None:
    con.execute(
        "update v2_portfolios set status=?,state_json=? where portfolio_id=?",
        (state.get("status", "ACTIVE"), _json(state), state["portfolio_id"]),
    )


def load_portfolio(db_path: Path, portfolio_id: str | None = None) -> dict[str, Any]:
    with connect(db_path) as con:
        if portfolio_id is None:
            row = con.execute(
                "select portfolio_id from v2_portfolios where status='ACTIVE' order by created_at desc limit 1"
            ).fetchone()
            if not row:
                return {
                    "schema": "SRE_VALIDATION_V2_PAPER_STATUS",
                    "schema_version": SCHEMA_VERSION,
                    "active": False,
                    "legacy_v1_excluded": True,
                }
            portfolio_id = row[0]
        state = _load_state(con, portfolio_id)
        positions = [
            json.loads(r[0])
            for r in con.execute(
                "select state_json from v2_positions where portfolio_id=? and state!='CLOSED' order by symbol",
                (portfolio_id,),
            )
        ]
        orders = [
            json.loads(r[0])
            for r in con.execute(
                "select order_json from v2_orders where portfolio_id=? and state in ('PENDING_NEXT_OPEN','PENDING_EXIT_NEXT_OPEN') "
                "order by signal_session,symbol",
                (portfolio_id,),
            )
        ]
        journal = [
            json.loads(r[0])
            for r in con.execute(
                "select event_json from v2_journal where portfolio_id=? order by created_at desc,event_id desc limit 500",
                (portfolio_id,),
            )
        ]
        nav_history = [
            json.loads(r[0])
            for r in con.execute(
                "select nav_json from v2_nav where portfolio_id=? order by market_session",
                (portfolio_id,),
            )
        ]
    return {
        **state,
        "schema": "SRE_VALIDATION_V2_PAPER_STATUS",
        "schema_version": SCHEMA_VERSION,
        "active": state.get("status") == "ACTIVE",
        "positions": positions,
        "pending_orders": orders,
        "journal": journal,
        "nav_history": nav_history,
        "legacy_v1_excluded": True,
    }


def _journal(
    con: sqlite3.Connection,
    *,
    portfolio_id: str,
    market_session: str,
    production_run_id: str | None,
    event_type: str,
    idempotency_key: str,
    event: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    existing = con.execute(
        "select event_json from v2_journal where idempotency_key=?", (idempotency_key,)
    ).fetchone()
    if existing:
        value = json.loads(existing[0])
        value["duplicate"] = True
        return value, True
    created_at = _now()
    full = {
        **event,
        "schema": "SRE_VALIDATION_V2_JOURNAL_EVENT",
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": portfolio_id,
        "market_session": market_session,
        "production_run_id": production_run_id,
        "event_type": event_type,
        "created_at": created_at,
        "broker_execution": False,
    }
    event_id = _stable_id("SREV2E", {"idempotency_key": idempotency_key, "event": full})
    full["event_id"] = event_id
    full["integrity_hash"] = hashlib.sha256(_json(full).encode("utf-8")).hexdigest()
    con.execute(
        "insert into v2_journal values(?,?,?,?,?,?,?,?)",
        (event_id, portfolio_id, market_session, production_run_id, event_type, idempotency_key, created_at, _json(full)),
    )
    return full, False


def _final_action(row: dict[str, Any]) -> str:
    live = row.get("live_decision") or {}
    return str(live.get("final_action") or row.get("final_action") or row.get("opportunity_status") or "").upper()


def _is_executable_buy(row: dict[str, Any]) -> bool:
    live = row.get("live_decision") or {}
    executable = live.get("executable")
    if executable is None:
        executable = row.get("executable")
    return executable is True and _final_action(row) in BUY_ACTIONS


def record_signal_session(
    db_path: Path,
    *,
    portfolio_id: str,
    market_session: str,
    production_run_id: str,
    app_version: str,
    model_version: str,
    evidence_version: str,
    recommendations: list[dict[str, Any]],
    capital_plan: dict[str, Any],
    official_data_ready: bool,
    analysis_session_current: bool,
) -> dict[str, Any]:
    key = f"{portfolio_id}|{market_session}|{production_run_id}|DAILY_SIGNAL"
    with connect(db_path) as con:
        state = _load_state(con, portfolio_id)
        if not official_data_ready:
            event, _ = _journal(
                con,
                portfolio_id=portfolio_id,
                market_session=market_session,
                production_run_id=production_run_id,
                event_type="NO_ACTION_OFFICIAL_DATA_NOT_READY",
                idempotency_key=key,
                event={"decision": "NO PAPER ACTION — OFFICIAL DATA NOT READY"},
            )
            return event
        if not analysis_session_current:
            event, _ = _journal(
                con,
                portfolio_id=portfolio_id,
                market_session=market_session,
                production_run_id=production_run_id,
                event_type="NO_ACTION_ANALYSIS_NOT_CURRENT",
                idempotency_key=key,
                event={"decision": "NO PAPER ACTION — ANALYSIS SESSION NOT CURRENT"},
            )
            return event

        existing = con.execute("select event_json from v2_journal where idempotency_key=?", (key,)).fetchone()
        if existing:
            event = json.loads(existing[0])
            event["duplicate"] = True
            return event

        held = {
            r[0]
            for r in con.execute(
                "select symbol from v2_positions where portfolio_id=? and state in ('HELD','WEAKENING')",
                (portfolio_id,),
            )
        }
        pending = {
            r[0]
            for r in con.execute(
                "select symbol from v2_orders where portfolio_id=? and state in ('PENDING_NEXT_OPEN','PENDING_EXIT_NEXT_OPEN')",
                (portfolio_id,),
            )
        }
        allocation_by_symbol = {
            str(x.get("symbol") or x.get("ticker") or "").upper(): x
            for x in (capital_plan.get("new_buys") or [])
        }
        orders: list[dict[str, Any]] = []
        for row in recommendations:
            if not _is_executable_buy(row):
                continue
            symbol = str(row.get("symbol") or row.get("ticker") or "").upper().replace(".NS", "")
            if not symbol or symbol in held or symbol in pending:
                continue
            allocation = allocation_by_symbol.get(symbol)
            if not allocation:
                continue
            amount = float(allocation.get("estimated_cost") or allocation.get("capital") or 0.0)
            if not math.isfinite(amount) or amount <= 0:
                continue
            live = row.get("live_decision") or {}
            order = {
                "order_id": _stable_id(
                    "SREV2O",
                    {
                        "portfolio_id": portfolio_id,
                        "symbol": symbol,
                        "side": "BUY",
                        "signal_session": market_session,
                        "production_run_id": production_run_id,
                    },
                ),
                "portfolio_id": portfolio_id,
                "symbol": symbol,
                "side": "BUY",
                "state": "PENDING_NEXT_OPEN",
                "signal_session": market_session,
                "production_run_id": production_run_id,
                "allocation": allocation,
                "reserved_capital": amount,
                "final_action": _final_action(row),
                "strategy_style": live.get("strategy_style") or row.get("strategy_style"),
                "confidence": live.get("confidence") or row.get("confidence_label"),
                "entry_thesis": live,
                "app_version": app_version,
                "model_version": model_version,
                "evidence_version": evidence_version,
                "authority": "LIVE_DECISION_V1",
            }
            con.execute(
                "insert into v2_orders values(?,?,?,?,?,?,?,?)",
                (
                    order["order_id"],
                    portfolio_id,
                    symbol,
                    "BUY",
                    "PENDING_NEXT_OPEN",
                    market_session,
                    None,
                    production_run_id,
                    _json(order),
                ),
            )
            orders.append(order)

        event, _ = _journal(
            con,
            portfolio_id=portfolio_id,
            market_session=market_session,
            production_run_id=production_run_id,
            event_type="BUY_SIGNAL" if orders else "DAILY_DECISION",
            idempotency_key=key,
            event={
                "decision": "PENDING_NEXT_OPEN" if orders else "CASH / NO ALLOCATED EXECUTABLE BUY",
                "orders": orders,
                "executable_buy_count": sum(1 for r in recommendations if _is_executable_buy(r)),
                "allocated_buy_count": len(orders),
                "app_version": app_version,
                "model_version": model_version,
                "evidence_version": evidence_version,
            },
        )
        _save_state(con, state)
        return event


def _execution_price(open_price: float, side: str, assumptions: ExecutionAssumptions) -> tuple[float, float]:
    if not math.isfinite(float(open_price)) or float(open_price) <= 0:
        raise ValueError("INVALID_OFFICIAL_OPEN")
    direction = 1.0 if side == "BUY" else -1.0
    slip = float(open_price) * float(assumptions.slippage_bps) / 10000.0
    fill = float(open_price) + direction * slip
    fee = fill * float(assumptions.transaction_cost_bps) / 10000.0
    net = fill + fee if side == "BUY" else fill - fee
    return fill, net


def apply_next_open_fills(
    db_path: Path,
    *,
    portfolio_id: str,
    fill_session: str,
    official_open_prices: dict[str, float],
    assumptions: ExecutionAssumptions | None = None,
) -> list[dict[str, Any]]:
    assumptions = assumptions or ExecutionAssumptions()
    events: list[dict[str, Any]] = []
    with connect(db_path) as con:
        state = _load_state(con, portfolio_id)
        rows = con.execute(
            "select order_id,order_json from v2_orders where portfolio_id=? and state in ('PENDING_NEXT_OPEN','PENDING_EXIT_NEXT_OPEN') "
            "order by signal_session,order_id",
            (portfolio_id,),
        ).fetchall()
        for order_id, raw in rows:
            order = json.loads(raw)
            if fill_session <= str(order["signal_session"]):
                continue
            symbol = order["symbol"]
            if symbol not in official_open_prices:
                continue
            fill_price, net_price = _execution_price(float(official_open_prices[symbol]), order["side"], assumptions)
            event_key = f"{portfolio_id}|{order_id}|{fill_session}|FILL"
            if con.execute("select 1 from v2_journal where idempotency_key=?", (event_key,)).fetchone():
                continue

            if order["side"] == "BUY":
                reserved = min(float(state["cash"]), float(order.get("reserved_capital") or 0.0))
                qty = int(reserved // net_price)
                if qty <= 0:
                    continue
                total_cost = round(qty * net_price, 2)
                state["cash"] = round(float(state["cash"]) - total_cost, 2)
                position = {
                    "position_id": _stable_id(
                        "SREV2POS",
                        {"portfolio_id": portfolio_id, "order_id": order_id, "fill_session": fill_session},
                    ),
                    "portfolio_id": portfolio_id,
                    "symbol": symbol,
                    "state": "HELD",
                    "qty": qty,
                    "entry_signal_session": order["signal_session"],
                    "entry_fill_session": fill_session,
                    "official_open": float(official_open_prices[symbol]),
                    "entry_fill_price": fill_price,
                    "entry_price": net_price,
                    "last_price": net_price,
                    "last_valuation_session": fill_session,
                    "unrealized_pnl": 0.0,
                    "entry_thesis": order.get("entry_thesis") or {},
                    "strategy_style": order.get("strategy_style"),
                    "confidence": order.get("confidence"),
                    "production_run_id": order.get("production_run_id"),
                    "app_version": order.get("app_version"),
                    "model_version": order.get("model_version"),
                    "evidence_version": order.get("evidence_version"),
                }
                con.execute(
                    "insert into v2_positions values(?,?,?,?,?,?,?)",
                    (
                        position["position_id"],
                        portfolio_id,
                        symbol,
                        "HELD",
                        qty,
                        net_price,
                        _json(position),
                    ),
                )
                event_type = "BUY_FILLED"
                event_payload = {
                    "symbol": symbol,
                    "qty": qty,
                    "signal_session": order["signal_session"],
                    "fill_session": fill_session,
                    "official_open": official_open_prices[symbol],
                    "fill_price": fill_price,
                    "net_price": net_price,
                    "total_cost": total_cost,
                    "cash_after": state["cash"],
                }
                order["state"] = "FILLED"
            else:
                pos_row = con.execute(
                    "select position_id,state_json from v2_positions where portfolio_id=? and symbol=? and state in ('HELD','WEAKENING') "
                    "order by rowid limit 1",
                    (portfolio_id, symbol),
                ).fetchone()
                if not pos_row:
                    continue
                position = json.loads(pos_row[1])
                qty = int(position["qty"])
                proceeds = round(qty * net_price, 2)
                pnl = round(proceeds - qty * float(position["entry_price"]), 2)
                state["cash"] = round(float(state["cash"]) + proceeds, 2)
                state["realized_pnl"] = round(float(state.get("realized_pnl") or 0.0) + pnl, 2)
                position.update(
                    {
                        "state": "CLOSED",
                        "exit_signal_session": order["signal_session"],
                        "exit_fill_session": fill_session,
                        "official_exit_open": float(official_open_prices[symbol]),
                        "exit_fill_price": fill_price,
                        "exit_price": net_price,
                        "realized_pnl": pnl,
                    }
                )
                con.execute(
                    "update v2_positions set state='CLOSED',state_json=? where position_id=?",
                    (_json(position), pos_row[0]),
                )
                event_type = "EXIT_FILLED"
                event_payload = {
                    "symbol": symbol,
                    "qty": qty,
                    "signal_session": order["signal_session"],
                    "fill_session": fill_session,
                    "official_open": official_open_prices[symbol],
                    "fill_price": fill_price,
                    "net_price": net_price,
                    "proceeds": proceeds,
                    "realized_pnl": pnl,
                    "cash_after": state["cash"],
                }
                order["state"] = "CLOSED"

            order["fill_session"] = fill_session
            order["official_open"] = float(official_open_prices[symbol])
            order["fill_price"] = fill_price
            order["net_price"] = net_price
            con.execute(
                "update v2_orders set state=?,fill_session=?,order_json=? where order_id=?",
                (order["state"], fill_session, _json(order), order_id),
            )
            event, _ = _journal(
                con,
                portfolio_id=portfolio_id,
                market_session=fill_session,
                production_run_id=order.get("production_run_id"),
                event_type=event_type,
                idempotency_key=event_key,
                event=event_payload,
            )
            events.append(event)
        _save_state(con, state)
    return events


def queue_exit(
    db_path: Path,
    *,
    portfolio_id: str,
    symbol: str,
    market_session: str,
    production_run_id: str,
    reason: str,
) -> dict[str, Any]:
    symbol = symbol.upper().replace(".NS", "")
    with connect(db_path) as con:
        pos = con.execute(
            "select position_id,state_json from v2_positions where portfolio_id=? and symbol=? and state in ('HELD','WEAKENING') "
            "order by rowid limit 1",
            (portfolio_id, symbol),
        ).fetchone()
        if not pos:
            raise ValueError("OPEN_POSITION_NOT_FOUND")
        order_id = _stable_id(
            "SREV2O",
            {
                "portfolio_id": portfolio_id,
                "symbol": symbol,
                "side": "SELL",
                "signal_session": market_session,
                "production_run_id": production_run_id,
            },
        )
        existing = con.execute("select order_json from v2_orders where order_id=?", (order_id,)).fetchone()
        if existing:
            return json.loads(existing[0])
        order = {
            "order_id": order_id,
            "portfolio_id": portfolio_id,
            "symbol": symbol,
            "side": "SELL",
            "state": "PENDING_EXIT_NEXT_OPEN",
            "signal_session": market_session,
            "production_run_id": production_run_id,
            "reason": reason,
            "authority": "LIVE_DECISION_V1_MONITOR",
        }
        con.execute(
            "insert into v2_orders values(?,?,?,?,?,?,?,?)",
            (order_id, portfolio_id, symbol, "SELL", "PENDING_EXIT_NEXT_OPEN", market_session, None, production_run_id, _json(order)),
        )
        position = json.loads(pos[1])
        position["state"] = "WEAKENING"
        con.execute(
            "update v2_positions set state='WEAKENING',state_json=? where position_id=?",
            (_json(position), pos[0]),
        )
        _journal(
            con,
            portfolio_id=portfolio_id,
            market_session=market_session,
            production_run_id=production_run_id,
            event_type="EXIT_SIGNAL",
            idempotency_key=f"{portfolio_id}|{order_id}|EXIT_SIGNAL",
            event={"symbol": symbol, "reason": reason, "order": order},
        )
        return order


def mark_to_market(
    db_path: Path,
    *,
    portfolio_id: str,
    market_session: str,
    official_close_prices: dict[str, float],
    benchmark_value: float | None = None,
) -> dict[str, Any]:
    with connect(db_path) as con:
        state = _load_state(con, portfolio_id)
        positions = con.execute(
            "select position_id,state_json from v2_positions where portfolio_id=? and state in ('HELD','WEAKENING')",
            (portfolio_id,),
        ).fetchall()
        market_value = 0.0
        unrealized = 0.0
        stale: list[str] = []
        for position_id, raw in positions:
            pos = json.loads(raw)
            symbol = pos["symbol"]
            close = official_close_prices.get(symbol)
            if close is None or not math.isfinite(float(close)) or float(close) <= 0:
                stale.append(symbol)
                mark = float(pos.get("last_price") or pos["entry_price"])
            else:
                mark = float(close)
                pos["last_price"] = mark
                pos["last_valuation_session"] = market_session
            value = int(pos["qty"]) * mark
            pnl = round(int(pos["qty"]) * (mark - float(pos["entry_price"])), 2)
            pos["market_value"] = round(value, 2)
            pos["unrealized_pnl"] = pnl
            market_value += value
            unrealized += pnl
            con.execute(
                "update v2_positions set state_json=? where position_id=?",
                (_json(pos), position_id),
            )
        state["unrealized_pnl"] = round(unrealized, 2)
        state["nav"] = round(float(state["cash"]) + market_value, 2)
        invested = round(market_value, 2)
        quality = "CURRENT_OFFICIAL_MARKS" if not stale else "STALE_MARK"
        nav_row = {
            "session": market_session,
            "nav": state["nav"],
            "cash": state["cash"],
            "invested_value": invested,
            "realized_pnl": state.get("realized_pnl", 0.0),
            "unrealized_pnl": state["unrealized_pnl"],
            "benchmark_value": benchmark_value,
            "valuation_quality": quality,
            "stale_symbols": stale,
        }
        con.execute(
            "insert or replace into v2_nav values(?,?,?,?,?,?,?,?)",
            (portfolio_id, market_session, state["nav"], state["cash"], invested, benchmark_value, quality, _json(nav_row)),
        )
        _save_state(con, state)
        return nav_row


def benchmark_nav_series(starting_capital: float, closes: list[tuple[str, float]]) -> list[dict[str, Any]]:
    valid = [(s, float(v)) for s, v in closes if math.isfinite(float(v)) and float(v) > 0]
    if not valid:
        return []
    units = float(starting_capital) / valid[0][1]
    return [
        {"session": session, "benchmark_close": close, "benchmark_nav": round(units * close, 2)}
        for session, close in valid
    ]


def max_drawdown(values: Iterable[float]) -> float | None:
    peak: float | None = None
    worst = 0.0
    seen = False
    for raw in values:
        value = float(raw)
        if not math.isfinite(value) or value <= 0:
            continue
        seen = True
        peak = value if peak is None else max(peak, value)
        if peak:
            worst = min(worst, (value - peak) / peak)
    return round(worst, 8) if seen else None


def replay_metrics(
    *,
    starting_capital: float,
    nav_series: list[dict[str, Any]],
    benchmark_series: list[dict[str, Any]],
    filled_entries: int,
    filled_exits: int,
    closed_trade_pnls: list[float],
) -> dict[str, Any]:
    valid_nav = [float(x["nav"]) for x in nav_series if x.get("nav") is not None]
    benchmark_by_session = {x["session"]: float(x["benchmark_nav"]) for x in benchmark_series}
    aligned = [
        (x["session"], float(x["nav"]), benchmark_by_session[x["session"]])
        for x in nav_series
        if x.get("nav") is not None and x.get("session") in benchmark_by_session
    ]
    portfolio_return = None
    benchmark_return = None
    excess = None
    if len(valid_nav) >= 2 and float(starting_capital) > 0:
        portfolio_return = valid_nav[-1] / float(starting_capital) - 1.0
    if len(aligned) >= 2 and aligned[0][2] > 0:
        benchmark_return = aligned[-1][2] / aligned[0][2] - 1.0
    if portfolio_return is not None and benchmark_return is not None:
        excess = portfolio_return - benchmark_return
    wins = sum(1 for p in closed_trade_pnls if p > 0)
    win_rate = (wins / len(closed_trade_pnls)) if closed_trade_pnls else None
    return {
        "portfolio_return": None if portfolio_return is None else round(portfolio_return, 8),
        "benchmark_return": None if benchmark_return is None else round(benchmark_return, 8),
        "excess_return": None if excess is None else round(excess, 8),
        "maximum_drawdown": max_drawdown(valid_nav),
        "benchmark_max_drawdown": max_drawdown(x["benchmark_nav"] for x in benchmark_series),
        "filled_entries": int(filled_entries),
        "filled_exits": int(filled_exits),
        "closed_trades": len(closed_trade_pnls),
        "win_rate": None if win_rate is None else round(win_rate, 8),
    }


def classify_replay_session(
    *,
    market_data_ready: bool,
    fundamental_pit_ready: bool,
    valuation_pit_ready: bool,
    production_reconstruction_ready: bool,
    optional_gaps: bool = False,
) -> str:
    if not (market_data_ready and fundamental_pit_ready and valuation_pit_ready and production_reconstruction_ready):
        return "NOT_REPLAYABLE"
    return "PIT_VALID_WITH_OPTIONAL_GAPS" if optional_gaps else "FULL_PIT_VALID"
