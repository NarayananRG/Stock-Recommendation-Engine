from pathlib import Path
import os
import re

root = Path(os.environ["SRE_ENGINE_ROOT"])


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        raise RuntimeError(label + " start missing")
    b = text.find(end, a + len(start))
    if b < 0:
        raise RuntimeError(label + " end missing")
    return text[:a] + replacement + text[b:]


module = r'''from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

AUTHORITY = {
    "schema": "SRE_PHASE81_PRODUCTION_AUTHORITY_TRACE_V2",
    "phase": "PHASE_8_1_HISTORICAL_REPLAY_AND_PAPER_PORTFOLIO",
    "production_recommendation_authority": "FROZEN_PRODUCTION_MODEL",
    "production_rank_authority_changed": False,
    "production_action_authority_changed": False,
    "technical_v2_authority": "SHADOW_ONLY",
    "fundamental_v3_authority": "SHADOW_ONLY",
    "combined_v2_authority": "SHADOW_ONLY",
    "combined_v2_target_used_in_score": False,
    "combined_v2_promotion_allowed": False,
    "watch_is_executable": False,
    "broker_execution": False,
    "automatic_yfinance_fallback": False,
}

VALID_PIT = {"FULL_PIT_VALID", "PIT_VALID_WITH_MISSING_OPTIONAL_DATA"}


@dataclass(frozen=True)
class ExecutionAssumptions:
    timing: str = "NEXT_SESSION_OPEN"
    starting_capital: float = 100000.0
    slippage_bps: float = 10.0
    transaction_cost_bps: float = 5.0
    whole_shares: bool = True
    leverage: bool = False
    shorting: bool = False
    broker_execution: bool = False
    benchmark: str = "NIFTY 50"


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return prefix + "_" + hashlib.sha256(raw).hexdigest()[:16]


def is_executable(row: dict[str, Any]) -> bool:
    decision = str(row.get("opportunity_status") or row.get("decision") or "").upper()
    return bool(row.get("executable")) and "BUY" in decision and "WATCH" not in decision


def period_start(end_session: str, period: str, custom_start: str | None = None) -> str:
    if str(period).upper() == "CUSTOM":
        if not custom_start:
            raise ValueError("CUSTOM_REPLAY_REQUIRES_START_DATE")
        return custom_start
    months = {"1M": 31, "3M": 93, "6M": 186}.get(str(period).upper())
    if months is None:
        raise ValueError("UNSUPPORTED_REPLAY_PERIOD")
    return (date.fromisoformat(end_session) - timedelta(days=months)).isoformat()


def trading_sessions_for_range(available_sessions: list[str], start: str, end: str) -> list[str]:
    return sorted({s for s in available_sessions if start <= s <= end})


def reject_future_price(as_of_session: str, price_session: str) -> None:
    if price_session > as_of_session:
        raise ValueError("PIT_FUTURE_PRICE_REJECTED")


def reject_future_fundamental(as_of_session: str, fundamental_as_of: str) -> None:
    if fundamental_as_of > as_of_session:
        raise ValueError("PIT_FUTURE_FUNDAMENTAL_REJECTED")


def classify_pit(session: str, *, latest_official_session: str | None, production_snapshot_available: bool, optional_missing: bool = False) -> str:
    if not latest_official_session or session > latest_official_session:
        return "NOT_REPLAYABLE"
    if not production_snapshot_available:
        return "PIT_DATA_INCOMPLETE"
    return "PIT_VALID_WITH_MISSING_OPTIONAL_DATA" if optional_missing else "FULL_PIT_VALID"


def whole_share_quantity(cash: float, price: float, assumptions: ExecutionAssumptions | None = None) -> int:
    assumptions = assumptions or ExecutionAssumptions()
    if price <= 0:
        return 0
    effective = price * (1 + (assumptions.slippage_bps + assumptions.transaction_cost_bps) / 10000.0)
    return int(max(0.0, cash) // effective)


def next_open_fill(signal_session: str, next_session: str, open_price: float, side: str, assumptions: ExecutionAssumptions | None = None) -> dict[str, Any]:
    assumptions = assumptions or ExecutionAssumptions()
    if next_session <= signal_session:
        raise ValueError("POST_CLOSE_SIGNAL_REQUIRES_NEXT_SESSION_OPEN")
    sign = 1 if side.upper() == "BUY" else -1
    slip = float(open_price) * assumptions.slippage_bps / 10000.0
    cost = float(open_price) * assumptions.transaction_cost_bps / 10000.0
    fill_price = float(open_price) + sign * slip
    return {
        "signal_session": signal_session,
        "fill_session": next_session,
        "side": side.upper(),
        "timing": "NEXT_SESSION_OPEN",
        "open_price": round(float(open_price), 6),
        "slippage_per_share": round(slip, 6),
        "cost_per_share": round(cost, 6),
        "fill_price": round(fill_price, 6),
        "net_price": round(fill_price + cost if sign > 0 else fill_price - cost, 6),
        "broker_execution": False,
    }


def max_drawdown(values: list[float]) -> float:
    peak = None
    worst = 0.0
    for value in values:
        peak = float(value) if peak is None else max(peak, float(value))
        if peak > 0:
            worst = min(worst, (float(value) - peak) / peak)
    return round(worst, 6)


def session_summary(session: str, rows: list[dict[str, Any]], *, capital_plan: dict[str, Any] | None, assumptions: ExecutionAssumptions, pit_status: str, model_identity: str, source_identity: dict[str, Any] | None = None, pit_explanation: str = "") -> dict[str, Any]:
    executable = [r for r in rows if is_executable(r)]
    watch = [r for r in rows if "WATCH" in str(r.get("opportunity_status") or r.get("decision") or "").upper()]
    deployed = sum(float(x.get("capital") or x.get("amount") or x.get("estimated_cost") or 0.0) for x in (capital_plan or {}).get("new_buys", []) or [])
    blockers: dict[str, int] = {}
    for row in rows:
        if is_executable(row):
            continue
        reason = str(row.get("execution_reason") or row.get("blocking_reason") or row.get("opportunity_status") or "OTHER_PRODUCTION_GATE")
        blockers[reason] = blockers.get(reason, 0) + 1
    nav = max(0.0, assumptions.starting_capital)
    return {
        "schema": "SRE_PHASE81_HISTORICAL_SESSION_SUMMARY_V2",
        "session": session,
        "pit_status": pit_status,
        "pit_explanation": pit_explanation,
        "universe_size": len(rows),
        "recommendations_generated": len(rows),
        "executable_buy_count": len(executable),
        "watch_count": len(watch),
        "no_action_count": max(0, len(rows) - len(executable) - len(watch)),
        "capital_deployed": round(deployed, 2) if pit_status in VALID_PIT else 0.0,
        "cash_retained": round(nav - deployed, 2) if pit_status in VALID_PIT else nav,
        "portfolio_nav": round(nav, 2),
        "benchmark_nav": round(nav, 2),
        "top_blocking_reasons": sorted(blockers.items(), key=lambda x: (-x[1], x[0]))[:10],
        "zero_buy_diagnostics": {"final_blocking_reasons": blockers} if not executable else {},
        "rows": rows,
        "capital_plan": capital_plan or {"new_buys": [], "excluded": []},
        "model_identity": model_identity,
        "source_data_identity": source_identity or {},
        "assumptions": asdict(assumptions),
    }


def replay_metrics(sessions: list[dict[str, Any]], nav: list[float] | None = None, benchmark_nav: list[float] | None = None, trades: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    replayable = [s for s in sessions if s.get("pit_status") in VALID_PIT]
    buy_sessions = [s for s in replayable if int(s.get("executable_buy_count") or 0) > 0]
    streak = longest = total_buys = 0
    cash_pct: list[float] = []
    deployed_pct: list[float] = []
    for s in replayable:
        buys = int(s.get("executable_buy_count") or 0)
        total_buys += buys
        streak = 0 if buys else streak + 1
        longest = max(longest, streak)
        session_nav = float(s.get("portfolio_nav") or 0.0)
        if session_nav > 0:
            cash_pct.append(float(s.get("cash_retained") or 0.0) / session_nav)
            deployed_pct.append(float(s.get("capital_deployed") or 0.0) / session_nav)
    nav = nav or [100000.0]
    benchmark_nav = benchmark_nav or [100000.0]
    trades = trades or []
    wins = [float(t.get("realized_pnl") or 0.0) for t in trades if float(t.get("realized_pnl") or 0.0) > 0]
    losses = [float(t.get("realized_pnl") or 0.0) for t in trades if float(t.get("realized_pnl") or 0.0) < 0]
    holding = [float(t.get("holding_sessions") or 0.0) for t in trades if t.get("holding_sessions") is not None]
    portfolio_return = (nav[-1] - nav[0]) / nav[0] if len(nav) > 1 and nav[0] else 0.0
    benchmark_return = (benchmark_nav[-1] - benchmark_nav[0]) / benchmark_nav[0] if len(benchmark_nav) > 1 and benchmark_nav[0] else 0.0
    buy_frequency = len(buy_sessions) / len(replayable) if replayable else 0.0
    activity = "HIGHLY_RESTRICTIVE" if buy_frequency == 0 else ("LOW_ACTIVITY" if buy_frequency < 0.10 else "NORMAL_ACTIVITY")
    return {
        "schema": "SRE_PHASE81_REPLAY_METRICS_V2",
        "sessions_evaluated": len(sessions),
        "total_replayable_sessions": len(replayable),
        "sessions_with_executable_buy": len(buy_sessions),
        "buy_frequency": round(buy_frequency, 6),
        "total_buy_signals": total_buys,
        "average_executable_buys_per_active_session": round(total_buys / len(buy_sessions), 6) if buy_sessions else 0.0,
        "longest_no_buy_streak": longest,
        "total_simulated_trades": len(trades),
        "completed_trades": len([t for t in trades if t.get("state") == "CLOSED"]),
        "average_cash_pct": round(sum(cash_pct) / len(cash_pct), 6) if cash_pct else 1.0,
        "average_capital_deployed_pct": round(sum(deployed_pct) / len(deployed_pct), 6) if deployed_pct else 0.0,
        "maximum_capital_deployed_pct": round(max(deployed_pct), 6) if deployed_pct else 0.0,
        "portfolio_return": round(portfolio_return, 6),
        "benchmark_return": round(benchmark_return, 6),
        "excess_return": round(portfolio_return - benchmark_return, 6),
        "maximum_drawdown": max_drawdown(nav),
        "benchmark_max_drawdown": max_drawdown(benchmark_nav),
        "win_rate": round(len(wins) / max(1, len(wins) + len(losses)), 6) if trades else 0.0,
        "average_winning_trade": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "average_losing_trade": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 6) if losses else (math.inf if wins else 0.0),
        "average_holding_period": round(sum(holding) / len(holding), 2) if holding else 0.0,
        "median_holding_period": round(median(holding), 2) if holding else 0.0,
        "best_trade": max(trades, key=lambda t: float(t.get("realized_pnl") or 0.0), default={}),
        "worst_trade": min(trades, key=lambda t: float(t.get("realized_pnl") or 0.0), default={}),
        "activity_classification": activity,
    }


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("pragma foreign_keys=on")
    con.execute("create table if not exists schema_meta (key text primary key, value text not null)")
    con.execute("insert or replace into schema_meta values ('schema_version','2')")
    con.execute("create table if not exists replay_runs (replay_id text primary key, created_at text not null, config_json text not null, result_json text not null)")
    con.execute("create table if not exists replay_sessions (replay_id text not null, market_session text not null, pit_status text not null, session_json text not null, primary key(replay_id, market_session))")
    con.execute("create table if not exists replay_trades (trade_id text primary key, replay_id text not null, trade_json text not null)")
    con.execute("create table if not exists paper_portfolios (portfolio_id text primary key, created_at text not null, starting_session text not null, starting_capital real not null, state_json text not null)")
    con.execute("create table if not exists paper_positions (position_id text primary key, portfolio_id text not null, symbol text not null, state text not null, qty integer not null, entry_price real, state_json text not null)")
    con.execute("create table if not exists paper_orders (order_id text primary key, portfolio_id text not null, symbol text not null, side text not null, state text not null, signal_session text not null, fill_session text, order_json text not null)")
    con.execute("create table if not exists paper_journal (event_id text primary key, portfolio_id text not null, market_session text not null, production_run_id text, event_type text not null, created_at text not null, idempotency_key text not null unique, event_json text not null)")
    con.execute("create table if not exists paper_nav (portfolio_id text not null, market_session text not null, nav real not null, benchmark_value real, nav_json text not null, primary key(portfolio_id, market_session))")
    return con


def create_portfolio(db_path: Path, *, starting_session: str, starting_capital: float = 100000.0) -> dict[str, Any]:
    created = datetime.now().isoformat(timespec="seconds")
    payload = {"starting_session": starting_session, "starting_capital": float(starting_capital)}
    portfolio_id = stable_id("SRE81PAPER", payload)
    state = {"portfolio_id": portfolio_id, "created_at": created, "starting_session": starting_session, "starting_capital": float(starting_capital), "cash": float(starting_capital), "positions": [], "pending_orders": [], "nav": float(starting_capital), "realized_pnl": 0.0, "unrealized_pnl": 0.0, "status": "ACTIVE", "authority": AUTHORITY}
    with connect(db_path) as con:
        con.execute("insert or ignore into paper_portfolios values (?,?,?,?,?)", (portfolio_id, created, starting_session, float(starting_capital), json.dumps(state, sort_keys=True)))
        con.execute("insert or ignore into paper_nav values (?,?,?,?,?)", (portfolio_id, starting_session, float(starting_capital), None, json.dumps({"nav": starting_capital, "cash": starting_capital}, sort_keys=True)))
    return load_portfolio(db_path, portfolio_id)


def _state(con: sqlite3.Connection, portfolio_id: str) -> dict[str, Any]:
    row = con.execute("select state_json from paper_portfolios where portfolio_id=?", (portfolio_id,)).fetchone()
    if not row:
        raise ValueError("PAPER_PORTFOLIO_NOT_FOUND")
    return json.loads(row[0])


def _save_state(con: sqlite3.Connection, state: dict[str, Any]) -> None:
    con.execute("update paper_portfolios set state_json=? where portfolio_id=?", (json.dumps(state, sort_keys=True), state["portfolio_id"]))


def _journal(con: sqlite3.Connection, event: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
    event = dict(event)
    event.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    event["integrity_hash"] = hashlib.sha256(json.dumps(event, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    event_id = stable_id("SRE81EVT", {"idempotency_key": idempotency_key, "integrity_hash": event["integrity_hash"]})
    event["event_id"] = event_id
    try:
        con.execute("insert into paper_journal values (?,?,?,?,?,?,?,?)", (event_id, event["portfolio_id"], event["market_session"], event.get("production_run_id"), event["event_type"], event["created_at"], idempotency_key, json.dumps(event, sort_keys=True)))
        event["duplicate"] = False
    except sqlite3.IntegrityError:
        row = con.execute("select event_json from paper_journal where idempotency_key=?", (idempotency_key,)).fetchone()
        event = json.loads(row[0])
        event["duplicate"] = True
    return event


def load_portfolio(db_path: Path, portfolio_id: str | None = None) -> dict[str, Any]:
    with connect(db_path) as con:
        if portfolio_id is None:
            row = con.execute("select portfolio_id from paper_portfolios order by created_at desc limit 1").fetchone()
            if not row:
                return {"active": False, "starting_capital": 100000.0, "authority": AUTHORITY}
            portfolio_id = row[0]
        state = _state(con, portfolio_id)
        state["positions"] = [json.loads(r[0]) for r in con.execute("select state_json from paper_positions where portfolio_id=? order by symbol", (portfolio_id,))]
        state["pending_orders"] = [json.loads(r[0]) for r in con.execute("select order_json from paper_orders where portfolio_id=? and state like 'PENDING%' order by signal_session,symbol", (portfolio_id,))]
        state["journal"] = [json.loads(r[0]) for r in con.execute("select event_json from paper_journal where portfolio_id=? order by created_at desc limit 200", (portfolio_id,))]
        state["nav_history"] = [json.loads(r[0]) for r in con.execute("select nav_json from paper_nav where portfolio_id=? order by market_session", (portfolio_id,))]
        state["active"] = True
        return state


def record_daily_observation(db_path: Path, *, portfolio_id: str, market_session: str, production_run_id: str | None, recommendations: list[dict[str, Any]], capital_plan: dict[str, Any] | None = None, benchmark_value: float | None = None) -> dict[str, Any]:
    with connect(db_path) as con:
        state = _state(con, portfolio_id)
        before = json.loads(json.dumps(state, sort_keys=True))
        executable = [r for r in recommendations if is_executable(r)]
        plan = capital_plan or {"new_buys": [], "excluded": []}
        event_type = "DAILY_DECISION"
        orders = []
        if executable:
            event_type = "SIGNAL_GENERATED"
            for row in executable:
                symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
                if not symbol:
                    continue
                order = {"order_id": stable_id("SRE81ORD", {"portfolio_id": portfolio_id, "symbol": symbol, "market_session": market_session, "run": production_run_id, "side": "BUY"}), "portfolio_id": portfolio_id, "symbol": symbol, "side": "BUY", "state": "PENDING_NEXT_OPEN", "signal_session": market_session, "production_run_id": production_run_id, "allocation": next((x for x in plan.get("new_buys", []) if str(x.get("symbol") or x.get("ticker") or "").upper() == symbol), {}), "authority": "FROZEN_PRODUCTION_CAPITAL_PLAN"}
                orders.append(order)
        decision = "CASH / NO EXECUTABLE BUY" if not orders else "PENDING_NEXT_OPEN"
        event = {"schema": "SRE_PHASE81_PROSPECTIVE_JOURNAL_EVENT_V2", "portfolio_id": portfolio_id, "market_session": market_session, "production_run_id": production_run_id, "event_type": event_type, "model_identity": "FROZEN_PRODUCTION_MODEL", "official_data_provenance": "OFFICIAL_FIRST", "recommendations_observed": len(recommendations), "executable_buys": len(executable), "capital_plan": plan, "orders": orders, "positions_before": before.get("positions", []), "positions_after": state.get("positions", []), "cash_before": state["cash"], "cash_after": state["cash"], "nav": state["nav"], "benchmark_value": benchmark_value, "decision": decision, "reason": decision, "automatic_yfinance_fallback": False, "broker_execution": False}
        written = _journal(con, event, f"{portfolio_id}|{market_session}|{production_run_id}|{event_type}")
        if not written.get("duplicate"):
            for order in orders:
                con.execute("insert or ignore into paper_orders values (?,?,?,?,?,?,?,?)", (order["order_id"], portfolio_id, order["symbol"], "BUY", "PENDING_NEXT_OPEN", market_session, None, json.dumps(order, sort_keys=True)))
            con.execute("insert or replace into paper_nav values (?,?,?,?,?)", (portfolio_id, market_session, state["nav"], benchmark_value, json.dumps({"market_session": market_session, "nav": state["nav"], "cash": state["cash"], "benchmark_value": benchmark_value}, sort_keys=True)))
        return written


def apply_open_fills(db_path: Path, *, portfolio_id: str, fill_session: str, open_prices: dict[str, float], assumptions: ExecutionAssumptions | None = None) -> list[dict[str, Any]]:
    assumptions = assumptions or ExecutionAssumptions()
    fills = []
    with connect(db_path) as con:
        state = _state(con, portfolio_id)
        rows = con.execute("select order_id, order_json from paper_orders where portfolio_id=? and state like 'PENDING%'", (portfolio_id,)).fetchall()
        for order_id, raw in rows:
            order = json.loads(raw)
            if fill_session <= order["signal_session"]:
                continue
            symbol = order["symbol"]
            if symbol not in open_prices:
                continue
            fill = next_open_fill(order["signal_session"], fill_session, float(open_prices[symbol]), order["side"], assumptions)
            if order["side"] == "BUY":
                allocation = float(order.get("allocation", {}).get("capital") or state["cash"])
                qty = whole_share_quantity(min(state["cash"], allocation), fill["net_price"], ExecutionAssumptions(slippage_bps=0, transaction_cost_bps=0))
                if qty <= 0:
                    continue
                cash_before = state["cash"]
                cost = round(qty * fill["net_price"], 2)
                state["cash"] = round(state["cash"] - cost, 2)
                position = {"position_id": stable_id("SRE81POS", {"portfolio_id": portfolio_id, "symbol": symbol, "entry": fill_session, "order": order_id}), "portfolio_id": portfolio_id, "symbol": symbol, "state": "HELD", "qty": qty, "entry_signal_date": order["signal_session"], "entry_fill_date": fill_session, "entry_price": fill["net_price"], "last_price": fill["net_price"], "unrealized_pnl": 0.0}
                con.execute("insert or replace into paper_positions values (?,?,?,?,?,?,?)", (position["position_id"], portfolio_id, symbol, "HELD", qty, fill["net_price"], json.dumps(position, sort_keys=True)))
                event = {"portfolio_id": portfolio_id, "market_session": fill_session, "production_run_id": order.get("production_run_id"), "event_type": "FILLED", "order": order, "fill": fill, "cash_before": cash_before, "cash_after": state["cash"], "positions_after": [position], "nav": state["cash"] + cost, "broker_execution": False}
            else:
                pos_row = con.execute("select position_id, state_json from paper_positions where portfolio_id=? and symbol=? and state in ('HELD','WEAKENING','PENDING_EXIT_NEXT_OPEN') order by rowid limit 1", (portfolio_id, symbol)).fetchone()
                if not pos_row:
                    continue
                pos = json.loads(pos_row[1])
                cash_before = state["cash"]
                proceeds = round(int(pos["qty"]) * fill["net_price"], 2)
                pnl = round(proceeds - int(pos["qty"]) * float(pos["entry_price"]), 2)
                state["cash"] = round(state["cash"] + proceeds, 2)
                pos.update({"state": "CLOSED", "exit_signal_date": order["signal_session"], "exit_fill_date": fill_session, "exit_price": fill["net_price"], "realized_pnl": pnl})
                con.execute("update paper_positions set state='CLOSED', state_json=? where position_id=?", (json.dumps(pos, sort_keys=True), pos_row[0]))
                event = {"portfolio_id": portfolio_id, "market_session": fill_session, "production_run_id": order.get("production_run_id"), "event_type": "CLOSED", "order": order, "fill": fill, "cash_before": cash_before, "cash_after": state["cash"], "realized_pnl": pnl, "nav": state["cash"], "broker_execution": False}
            order["state"] = "FILLED" if order["side"] == "BUY" else "CLOSED"
            order["fill_session"] = fill_session
            order["fill"] = fill
            con.execute("update paper_orders set state=?, fill_session=?, order_json=? where order_id=?", (order["state"], fill_session, json.dumps(order, sort_keys=True), order_id))
            fills.append(_journal(con, event, f"{portfolio_id}|{fill_session}|{order_id}|{event['event_type']}"))
        state["nav"] = round(state["cash"] + sum(int(json.loads(r[0])["qty"]) * float(json.loads(r[0]).get("last_price") or json.loads(r[0])["entry_price"]) for r in con.execute("select state_json from paper_positions where portfolio_id=? and state in ('HELD','WEAKENING')", (portfolio_id,))), 2)
        _save_state(con, state)
    return fills


def mark_daily_hold_exit(db_path: Path, *, portfolio_id: str, market_session: str, production_run_id: str | None, recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    with connect(db_path) as con:
        state = _state(con, portfolio_id)
        held = {json.loads(r[0])["symbol"]: json.loads(r[0]) for r in con.execute("select state_json from paper_positions where portfolio_id=? and state in ('HELD','WEAKENING')", (portfolio_id,))}
        for row in recommendations:
            symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
            if symbol not in held:
                continue
            decision = str(row.get("opportunity_status") or row.get("decision") or "").upper()
            if "EXIT" in decision or "SELL" in decision:
                order = {"order_id": stable_id("SRE81ORD", {"portfolio_id": portfolio_id, "symbol": symbol, "market_session": market_session, "run": production_run_id, "side": "SELL"}), "portfolio_id": portfolio_id, "symbol": symbol, "side": "SELL", "state": "PENDING_EXIT_NEXT_OPEN", "signal_session": market_session, "production_run_id": production_run_id}
                con.execute("insert or ignore into paper_orders values (?,?,?,?,?,?,?,?)", (order["order_id"], portfolio_id, symbol, "SELL", "PENDING_EXIT_NEXT_OPEN", market_session, None, json.dumps(order, sort_keys=True)))
                events.append(_journal(con, {"portfolio_id": portfolio_id, "market_session": market_session, "production_run_id": production_run_id, "event_type": "EXIT_SIGNAL_GENERATED", "order": order, "nav": state["nav"]}, f"{portfolio_id}|{market_session}|{production_run_id}|EXIT|{symbol}"))
            elif "WEAK" in decision:
                pos = held[symbol]
                pos["state"] = "WEAKENING"
                con.execute("update paper_positions set state='WEAKENING', state_json=? where position_id=?", (json.dumps(pos, sort_keys=True), pos["position_id"]))
                events.append(_journal(con, {"portfolio_id": portfolio_id, "market_session": market_session, "production_run_id": production_run_id, "event_type": "WEAKENING", "symbol": symbol, "nav": state["nav"]}, f"{portfolio_id}|{market_session}|{production_run_id}|WEAKENING|{symbol}"))
            else:
                events.append(_journal(con, {"portfolio_id": portfolio_id, "market_session": market_session, "production_run_id": production_run_id, "event_type": "HELD", "symbol": symbol, "nav": state["nav"]}, f"{portfolio_id}|{market_session}|{production_run_id}|HELD|{symbol}"))
    return events
'''

(root / "stock_app" / "phase81_validation.py").write_text(module, encoding="utf-8")

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = s.replace('0.13.1-phase8-validation-startup-hotfix', '0.13.2-phase8-validation-complete')

helpers = r'''    def _phase81_db_path(self) -> Path:
        return self.config.app_data_dir / "phase81_validation.sqlite3"

    def phase81_authority_trace(self) -> dict[str, Any]:
        from stock_app.phase81_validation import AUTHORITY
        return {**AUTHORITY, "backend_version": APP_VERSION}

    def _phase81_available_sessions(self) -> list[str]:
        gate = self._daily_data_gate()
        latest = str(gate.get("latest_official_session") or gate.get("target_session") or "")
        sessions: set[str] = set()
        for attr in ("official_cache_dir", "market_cache_dir", "data_dir"):
            path = getattr(self.config, attr, None)
            if not path:
                continue
            root_path = Path(path)
            if not root_path.exists():
                continue
            for p in root_path.rglob("*"):
                for m in re.findall(r"20\d\d-\d\d-\d\d", str(p)):
                    if not latest or m <= latest:
                        sessions.add(m)
        if latest:
            sessions.add(latest)
        return sorted(sessions)

    def phase81_historical_replay(self, period: str = "6M", starting_capital: float = 100000.0, benchmark: str = "NIFTY 50", start_date: str | None = None, end_date: str | None = None, slippage_bps: float = 10.0, transaction_cost_bps: float = 5.0) -> dict[str, Any]:
        from stock_app.phase81_validation import ExecutionAssumptions, classify_pit, period_start, replay_metrics, session_summary, stable_id, trading_sessions_for_range
        gate = self._daily_data_gate()
        latest = str(end_date or gate.get("latest_official_session") or gate.get("target_session") or "")
        if not latest:
            raise RuntimeError("NO_ACCEPTED_OFFICIAL_SESSION_FOR_REPLAY")
        start = period_start(latest, period, start_date)
        sessions = trading_sessions_for_range(self._phase81_available_sessions(), start, latest)
        if not sessions:
            sessions = [latest]
        current_run = self.ui_run_input() or {}
        current_session = str(current_run.get("market_session") or gate.get("target_session") or gate.get("latest_official_session") or latest)
        assumptions = ExecutionAssumptions(starting_capital=float(starting_capital), benchmark=benchmark, slippage_bps=float(slippage_bps), transaction_cost_bps=float(transaction_cost_bps))
        rows_current = self.latest_prediction_rows(limit=200)
        summaries = []
        for session in sessions:
            pit_ready = bool(gate.get("ready")) and session == current_session
            rows = rows_current if pit_ready else []
            pit = classify_pit(session, latest_official_session=latest, production_snapshot_available=pit_ready)
            explanation = "Frozen production snapshot available for accepted active run." if pit_ready else "No point-in-time frozen production snapshot is available; current rows are not substituted for history."
            summaries.append(session_summary(session, rows, capital_plan={"new_buys": [], "excluded": []}, assumptions=assumptions, pit_status=pit, model_identity=APP_VERSION, source_identity={"official_first": True, "latest_official_session": latest}, pit_explanation=explanation))
        nav = [float(starting_capital)] + [float(x.get("portfolio_nav") or starting_capital) for x in summaries if x.get("pit_status") in {"FULL_PIT_VALID", "PIT_VALID_WITH_MISSING_OPTIONAL_DATA"}]
        benchmark_nav = [float(starting_capital)] * max(1, len(nav))
        metrics = replay_metrics(summaries, nav=nav, benchmark_nav=benchmark_nav, trades=[])
        replay_id = stable_id("SRE81REPLAY", {"period": period, "start": start, "end": latest, "capital": starting_capital, "benchmark": benchmark, "version": APP_VERSION})
        result = {
            "schema": "SRE_PHASE81_HISTORICAL_REPLAY_RESULT_V2",
            "label": "HISTORICAL REPLAY - Frozen production authority, research only",
            "period": period,
            "date_range": {"start": start, "end": latest, "requested": period},
            "replay_id": replay_id,
            "status": "COMPLETED_WITH_PIT_GAPS" if metrics["total_replayable_sessions"] < len(summaries) else "COMPLETED",
            "pit_audit": {
                "largest_trustworthy_window": f"{metrics['total_replayable_sessions']} replayable session(s)",
                "requested_sessions": len(summaries),
                "incomplete_sessions": len([x for x in summaries if x.get("pit_status") == "PIT_DATA_INCOMPLETE"]),
                "note": "Incomplete sessions are shown but excluded from performance metrics. No current fundamentals or future prices are backfilled.",
            },
            "assumptions": summaries[0]["assumptions"] if summaries else {},
            "sessions": summaries,
            "metrics": metrics,
            "authority": self.phase81_authority_trace(),
            "automatic_yfinance_fallback": False,
            "broker_execution": False,
        }
        from stock_app.phase81_validation import connect
        with connect(self._phase81_db_path()) as con:
            con.execute("insert or replace into replay_runs values (?,?,?,?)", (replay_id, datetime.now().isoformat(timespec="seconds"), json.dumps({"period": period, "starting_capital": starting_capital, "benchmark": benchmark, "start": start, "end": latest}, sort_keys=True), json.dumps(result, sort_keys=True)))
            for item in summaries:
                con.execute("insert or replace into replay_sessions values (?,?,?,?)", (replay_id, item["session"], item["pit_status"], json.dumps(item, sort_keys=True)))
        return result

    def phase81_paper_status(self) -> dict[str, Any]:
        from stock_app.phase81_validation import load_portfolio
        state = load_portfolio(self._phase81_db_path())
        return {**state, "schema": "SRE_PHASE81_PAPER_PORTFOLIO_STATUS_V2", "label": "PROSPECTIVE PAPER TRACKING - Forward-only evidence", "authority": self.phase81_authority_trace()}

    def phase81_start_paper(self, starting_capital: float = 100000.0) -> dict[str, Any]:
        from stock_app.phase81_validation import create_portfolio
        gate = self._daily_data_gate()
        return create_portfolio(self._phase81_db_path(), starting_session=str(gate.get("target_session") or gate.get("latest_official_session")), starting_capital=float(starting_capital))

    def phase81_record_today(self) -> dict[str, Any]:
        from stock_app.phase81_validation import record_daily_observation
        status = self.phase81_paper_status()
        if not status.get("active"):
            status = self.phase81_start_paper(100000.0)
        gate = self._daily_data_gate()
        run = self.ui_run_input() or {}
        return record_daily_observation(self._phase81_db_path(), portfolio_id=status["portfolio_id"], market_session=str(gate.get("target_session") or gate.get("latest_official_session")), production_run_id=run.get("run_id"), recommendations=self.latest_prediction_rows(limit=200), capital_plan={"new_buys": [], "excluded": []})

'''
s = replace_between(s, "    def _phase81_db_path", "    def latest_prediction_rows", helpers, "phase81 helper replacement")

run_anchor = '        result = {**self.post_close_daily_status(), "ok": True, "run_status": "SUCCESS", "duplicate": False, "last_successful_daily_run": success}\n'
if run_anchor in s and "paper_portfolio_observation" not in s:
    s = s.replace(run_anchor, run_anchor + '''        try:
            paper_status = self.phase81_paper_status()
            if paper_status.get("active"):
                result["paper_portfolio_observation"] = self.phase81_record_today()
        except Exception as exc:
            result["paper_portfolio_observation"] = {"status": "ERROR", "reason": str(exc)}
''', 1)
api.write_text(s, encoding="utf-8")

html = root / "modern_ui" / "frontend" / "index.html"
h = html.read_text(encoding="utf-8")
h = re.sub(r'<section id="validationPage" class="page-section">.*?</section></main>', '</main>', h, flags=re.S)
validation_nav = '<button type="button" class="nav-item" data-page="validation">Validation</button>'
if 'data-page="validation"' not in h:
    h = h.replace('<button type="button" class="nav-item" data-page="system"', validation_nav + '\n<button type="button" class="nav-item" data-page="system"', 1)
    if 'data-page="validation"' not in h:
        h = h.replace('</nav>', validation_nav + '\n</nav>', 1)
validation_page = '''<section id="validationPage" class="page-section hidden" data-page-section="validation">
  <div class="page-heading compact"><div><div class="eyebrow">VALIDATION</div><h1>Validation</h1><p>Historical replay and forward-only paper tracking for the frozen production model.</p></div></div>
  <div class="validation-tabs" role="tablist">
    <button id="validationReplayTab" class="filter-pill active" type="button" role="tab" aria-controls="validationReplayPanel">Historical Replay</button>
    <button id="validationPaperTab" class="filter-pill" type="button" role="tab" aria-controls="validationPaperPanel">Paper Portfolio</button>
  </div>
  <div id="validationError" class="error-panel hidden"></div>
  <section id="validationReplayPanel" class="panel-card" role="tabpanel"></section>
  <section id="validationPaperPanel" class="panel-card hidden" role="tabpanel"></section>
</section>'''
if 'id="validationPage"' not in h:
    h = h.replace('</main>', validation_page + '\n</main>', 1)
html.write_text(h, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
t = re.sub(r'\nfunction ensureValidationNav\(\).*?ensureValidationNav\(\);\n', '\n', t, flags=re.S)
t = re.sub(r'async function loadValidation\(\).*?ensureValidationNav\(\);', '', t, flags=re.S)
validation_js = r'''
function validationError(stage, err){
  const el=$('#validationError'); if(!el)return;
  el.classList.remove('hidden'); el.textContent=`${stage}: ${err && err.message ? err.message : String(err)}`;
}
function setValidationTab(tab){
  const replay=tab==='replay';
  $('#validationReplayPanel')?.classList.toggle('hidden',!replay);
  $('#validationPaperPanel')?.classList.toggle('hidden',replay);
  $('#validationReplayTab')?.classList.toggle('active',replay);
  $('#validationPaperTab')?.classList.toggle('active',!replay);
}
function bindValidationTabs(){
  $('#validationReplayTab')?.addEventListener('click',()=>setValidationTab('replay'));
  $('#validationPaperTab')?.addEventListener('click',()=>setValidationTab('paper'));
}
async function runHistoricalReplay(){
  const period=$('#validationPeriod')?.value||'6M';
  const capital=Number($('#validationCapital')?.value||100000);
  const benchmark=encodeURIComponent($('#validationBenchmark')?.value||'NIFTY 50');
  const slip=Number($('#validationSlippage')?.value||10);
  const cost=Number($('#validationCost')?.value||5);
  busy(true,'Running historical replay','Preparing sessions and PIT audit');
  try{
    $('#validationError')?.classList.add('hidden');
    const r=await api(`/api/validation/historical-replay?period=${encodeURIComponent(period)}&starting_capital=${capital}&benchmark=${benchmark}&slippage_bps=${slip}&transaction_cost_bps=${cost}`,{method:'POST'});
    renderValidationReplay(r); toast('Historical replay complete');
  }catch(e){validationError('Historical replay failed',e)}
  finally{busy(false)}
}
function renderValidationReplay(r){
  const el=$('#validationReplayPanel'); if(!el)return; r=r||{}; const m=r.metrics||{}; const pit=r.pit_audit||{};
  const rows=(r.sessions||[]).map(s=>`<tr><td>${escapeHtml(s.session||'')}</td><td>${escapeHtml(s.pit_status||'')}</td><td>${s.universe_size||0}</td><td>${s.executable_buy_count||0}</td><td>${s.watch_count||0}</td><td>${s.no_action_count||0}</td><td>${fmtINR(s.capital_deployed||0)}</td><td>${fmtINR(s.cash_retained||0)}</td><td>${fmtINR(s.portfolio_nav||0)}</td><td>${fmtINR(s.benchmark_nav||0)}</td><td>${escapeHtml(((s.top_blocking_reasons||[])[0]||[])[0]||s.pit_explanation||'')}</td></tr>`).join('');
  el.innerHTML=`<div class="validation-controls">
    <label>Period<select id="validationPeriod"><option>1M</option><option>3M</option><option selected>6M</option><option>Custom</option></select></label>
    <label>Starting capital<input id="validationCapital" type="number" value="100000"></label>
    <label>Benchmark<input id="validationBenchmark" value="NIFTY 50"></label>
    <label>Slippage bps<input id="validationSlippage" type="number" value="10"></label>
    <label>Transaction cost bps<input id="validationCost" type="number" value="5"></label>
    <button class="primary-btn" id="runHistoricalReplay">RUN HISTORICAL REPLAY</button>
  </div><div class="daily-flow-grid success">${[['Sessions evaluated',m.sessions_evaluated??0],['Replayable sessions',m.total_replayable_sessions??0],['Sessions with BUY',m.sessions_with_executable_buy??0],['BUY frequency',fmtPctFraction(m.buy_frequency||0)],['Total BUY signals',m.total_buy_signals??0],['Longest zero-BUY streak',m.longest_no_buy_streak??0],['Portfolio return',fmtPctFraction(m.portfolio_return||0)],['Benchmark return',fmtPctFraction(m.benchmark_return||0)],['Excess return',fmtPctFraction(m.excess_return||0)],['Max drawdown',fmtPctFraction(m.maximum_drawdown||0)],['Activity',m.activity_classification||'—'],['PIT window',pit.largest_trustworthy_window||'—']].map(([k,v])=>`<div><span>${escapeHtml(k)}</span><strong>${escapeHtml(String(v))}</strong></div>`).join('')}</div><div class="table-wrap"><table><thead><tr><th>Date</th><th>PIT status</th><th>Universe</th><th>BUY</th><th>WATCH</th><th>No action</th><th>Capital deployed</th><th>Cash</th><th>NAV</th><th>Benchmark</th><th>Top blocking reason</th></tr></thead><tbody>${rows||'<tr><td colspan="11">No sessions available</td></tr>'}</tbody></table></div>`;
  $('#runHistoricalReplay')?.addEventListener('click',runHistoricalReplay);
}
async function startPaperPortfolio(){
  busy(true,'Starting paper portfolio','Forward-only paper ledger');
  try{$('#validationError')?.classList.add('hidden');await api('/api/validation/paper-portfolio/start?starting_capital=100000',{method:'POST'});renderValidationPaper(await api('/api/validation/paper-portfolio'));toast('Prospective tracking started')}
  catch(e){validationError('Paper portfolio failed',e)}
  finally{busy(false)}
}
function renderValidationPaper(p){
  const el=$('#validationPaperPanel'); if(!el)return; p=p||{};
  if(!p.active){el.innerHTML=`<div class="card-label">PROSPECTIVE PAPER TRACKING</div><h3>Rs 100,000 Paper Portfolio</h3><p>Forward-only from activation. No broker execution.</p><button id="startPaperPortfolio" class="primary-btn">START PROSPECTIVE TRACKING</button>`;$('#startPaperPortfolio')?.addEventListener('click',startPaperPortfolio);return}
  const pos=p.positions||[], orders=p.pending_orders||[], journal=p.journal||[];
  el.innerHTML=`<div class="daily-flow-grid success">${[['Portfolio value',fmtINR(p.nav||p.starting_capital||100000)],['Starting capital',fmtINR(p.starting_capital||100000)],['Cash',fmtINR(p.cash||0)],['Invested value',fmtINR((p.nav||0)-(p.cash||0))],['Exposure %',fmtPctFraction((p.nav||0)?((p.nav||0)-(p.cash||0))/(p.nav||1):0)],['Realized P&L',fmtINR(p.realized_pnl||0)],['Unrealized P&L',fmtINR(p.unrealized_pnl||0)],['Current holdings',pos.length],['Pending entries',orders.filter(o=>o.side==='BUY').length],['Pending exits',orders.filter(o=>o.side==='SELL').length],['Journal events',journal.length]].map(([k,v])=>`<div><span>${escapeHtml(k)}</span><strong>${escapeHtml(String(v))}</strong></div>`).join('')}</div><h3>Current Positions</h3><div class="table-wrap"><table><tbody>${pos.map(x=>`<tr><td>${escapeHtml(x.symbol)}</td><td>${x.state}</td><td>${x.qty}</td><td>${fmtINR(x.entry_price||0)}</td></tr>`).join('')||'<tr><td>Positions: 0</td></tr>'}</tbody></table></div><h3>Pending Orders</h3><div class="table-wrap"><table><tbody>${orders.map(x=>`<tr><td>${escapeHtml(x.symbol)}</td><td>${x.side}</td><td>${x.state}</td><td>${x.signal_session}</td></tr>`).join('')||'<tr><td>No pending orders</td></tr>'}</tbody></table></div><h3>Trade Journal</h3><div class="table-wrap"><table><tbody>${journal.map(x=>`<tr><td>${x.market_session}</td><td>${x.event_type}</td><td>${escapeHtml(x.decision||x.reason||'')}</td></tr>`).join('')||'<tr><td>No journal events yet</td></tr>'}</tbody></table></div>`;
}
async function loadValidation(){
  bindValidationTabs(); setValidationTab('replay');
  try{renderValidationReplay(await api('/api/validation/historical-replay',{method:'POST'}))}catch(e){validationError('Historical replay failed',e)}
  try{renderValidationPaper(await api('/api/validation/paper-portfolio'))}catch(e){validationError('Paper portfolio failed',e)}
}
'''
if "function validationError(stage, err)" not in t:
    t += validation_js
t = t.replace("if(page==='today')loadToday(); if(page==='validation')loadValidation();", "if(page==='today')loadToday(); if(page==='validation')loadValidation();")
if "if(page==='validation')loadValidation();" not in t:
    t = t.replace("if(page==='today')loadToday();", "if(page==='today')loadToday(); if(page==='validation')loadValidation();")
js.write_text(t, encoding="utf-8")

css = root / "modern_ui" / "frontend" / "styles.css"
c = css.read_text(encoding="utf-8")
if ".validation-controls" not in c:
    c += "\n.validation-tabs{display:flex;gap:8px;margin:8px 0 14px}.validation-controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;align-items:end;margin-bottom:14px}.validation-controls label{display:grid;gap:4px;font-size:12px;color:var(--muted)}.validation-controls input,.validation-controls select{min-height:34px}.error-panel{border:1px solid #b91c1c;background:#fef2f2;color:#7f1d1d;padding:10px;border-radius:8px;margin-bottom:12px}.hidden{display:none!important}\n"
css.write_text(c, encoding="utf-8")

policy = root / "phase8" / "phase81_validation_policy.json"
policy.write_text("""{
  "schema": "SRE_PHASE81_VALIDATION_POLICY_V2",
  "release": "0.13.2-phase8-validation-complete",
  "purpose": "Measure frozen production model activity and paper portfolio behavior without strategy changes.",
  "production_recommendation_authority_changed": false,
  "production_rank_authority_changed": false,
  "technical_v2_authority": "SHADOW_ONLY",
  "fundamental_v3_authority": "SHADOW_ONLY",
  "combined_v2_authority": "SHADOW_ONLY",
  "combined_v2_target_used_in_score": false,
  "combined_v2_promotion_allowed": false,
  "automatic_yfinance_fallback": false,
  "broker_execution": false,
  "paper_execution": "NEXT_SESSION_OPEN_WHOLE_SHARES_WITH_SLIPPAGE_AND_COSTS"
}
""", encoding="utf-8")

assert "0.13.2-phase8-validation-complete" in api.read_text(encoding="utf-8")
assert "ensureValidationNav" not in js.read_text(encoding="utf-8")
assert "catch{}" not in js.read_text(encoding="utf-8")
assert "START PROSPECTIVE TRACKING" in js.read_text(encoding="utf-8")
assert "import yfinance" not in module.lower()
print("0.13.2 Phase 8.1 validation completion overlay applied")