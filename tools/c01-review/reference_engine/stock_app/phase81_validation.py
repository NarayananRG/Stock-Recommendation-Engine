from __future__ import annotations

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
    "production_recommendation_authority": "LIVE_DECISION_V1",
    "production_rank_authority_changed": True,
    "production_action_authority_changed": True,
    "technical_v2_authority": "LIVE_EVIDENCE",
    "fundamental_v3_authority": "LIVE_EVIDENCE",
    "combined_v2_authority": "DIAGNOSTIC_ONLY",
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
    from .live_decision_v1 import BUY_ACTIONS
    return bool(row.get("executable")) and decision in BUY_ACTIONS


def period_start(end_session: str, period: str, custom_start: str | None = None) -> str:
    if str(period).upper() == "CUSTOM":
        if not custom_start:
            raise ValueError("CUSTOM_REPLAY_REQUIRES_START_DATE")
        return custom_start
    months = {"1W": 7, "1M": 31, "3M": 93, "6M": 186, "12M": 366, "24M": 732}.get(str(period).upper())
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
        "momentum_buy_count": sum(r.get("final_action") == "MOMENTUM BUY" for r in rows),
        "recovery_buy_count": sum(r.get("final_action") == "RECOVERY BUY" for r in rows),
        "both_buy_count": sum(r.get("final_action") == "MOMENTUM + RECOVERY BUY" for r in rows),
        "avoid_count": sum(str(r.get("final_action") or "").startswith("AVOID") for r in rows),
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


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, factory=_ClosingConnection)
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


def _canonical_journal_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # DAILY_DECISION/SIGNAL_GENERATED are one forward decision per market
    # session. Preserve the earliest accepted event for audit continuity and
    # hide legacy duplicate rows created with different production run IDs.
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for event in sorted(rows, key=lambda x: str(x.get("created_at") or "")):
        event_type = str(event.get("event_type") or "")
        if event_type in {"DAILY_DECISION", "SIGNAL_GENERATED"}:
            key = (str(event.get("market_session") or ""), "DAILY_SIGNAL")
            if key in seen:
                continue
            seen.add(key)
        result.append(event)
    return sorted(result, key=lambda x: str(x.get("created_at") or ""), reverse=True)

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
        raw_journal = [json.loads(r[0]) for r in con.execute("select event_json from paper_journal where portfolio_id=? order by created_at desc limit 400", (portfolio_id,))]
        state["journal"] = _canonical_journal_rows(raw_journal)[:200]
        state["journal_duplicate_rows_hidden"] = max(0, len(raw_journal) - len(_canonical_journal_rows(raw_journal)))
        state["nav_history"] = [json.loads(r[0]) for r in con.execute("select nav_json from paper_nav where portfolio_id=? order by market_session", (portfolio_id,))]
        state["active"] = True
        return state


def record_daily_observation(db_path: Path, *, portfolio_id: str, market_session: str, production_run_id: str | None, recommendations: list[dict[str, Any]], capital_plan: dict[str, Any] | None = None, benchmark_value: float | None = None) -> dict[str, Any]:
    with connect(db_path) as con:
        state = _state(con, portfolio_id)
        previous = con.execute("select event_json from paper_journal where portfolio_id=? and market_session=? and event_type in ('DAILY_DECISION','SIGNAL_GENERATED') order by created_at limit 1", (portfolio_id, market_session)).fetchone()
        if previous:
            return {**json.loads(previous[0]), "duplicate": True}
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
                allocation = order["allocation"]
                already_held = con.execute("select 1 from paper_positions where portfolio_id=? and symbol=? and state!='CLOSED'", (portfolio_id, symbol)).fetchone()
                already_pending = con.execute("select 1 from paper_orders where portfolio_id=? and symbol=? and state like 'PENDING%'", (portfolio_id, symbol)).fetchone()
                if already_held or already_pending:
                    continue
                if not allocation or float(allocation.get("estimated_cost") or 0) <= 0:
                    continue
                order["allocation"]["capital"] = allocation["estimated_cost"]
                order["authority"] = "LIVE_DECISION_V1"
                order["entry_thesis"] = row.get("live_decision") or {}
                order.update({key: row.get(key) for key in ("strategy_style", "primary_style", "momentum_thesis", "recovery_thesis", "business_health", "technical_state")})
                order["fundamental_state"] = row.get("business_health")
                orders.append(order)
        decision = "CASH / NO EXECUTABLE BUY" if not orders else "PENDING_NEXT_OPEN"
        event = {"schema": "SRE_PHASE81_PROSPECTIVE_JOURNAL_EVENT_V2", "portfolio_id": portfolio_id, "market_session": market_session, "production_run_id": production_run_id, "event_type": event_type, "model_identity": "0.14.0-live-dual-strategy-v1", "official_data_provenance": "OFFICIAL_FIRST", "recommendations_observed": len(recommendations), "executable_buys": len(executable), "capital_plan": plan, "orders": orders, "positions_before": before.get("positions", []), "positions_after": state.get("positions", []), "cash_before": state["cash"], "cash_after": state["cash"], "nav": state["nav"], "benchmark_value": benchmark_value, "decision": decision, "reason": decision, "automatic_yfinance_fallback": False, "broker_execution": False}
        written = _journal(con, event, f"{portfolio_id}|{market_session}|{event_type}")
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
                position.update({key: order.get(key) for key in ("strategy_style", "primary_style", "momentum_thesis", "recovery_thesis", "fundamental_state", "technical_state", "entry_thesis")})
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
            price = row.get("latest_close")
            if price is not None and math.isfinite(float(price)) and float(price) > 0 and str(row.get("market_session") or market_session) == market_session:
                held[symbol].update(last_price=float(price), last_valuation_session=market_session,
                                    unrealized_pnl=round(int(held[symbol]["qty"]) * (float(price) - float(held[symbol]["entry_price"])), 2))
                con.execute("update paper_positions set state_json=? where position_id=?", (json.dumps(held[symbol], sort_keys=True), held[symbol]["position_id"]))
            decision = str(row.get("opportunity_status") or row.get("decision") or "").upper()
            if row.get("live_decision"):
                from .live_decision_v1 import monitor
                held[symbol]["sessions_held"] = row.get("holding_sessions")
                decision, thesis_reason = monitor(held[symbol], row["live_decision"])
                row = {**row, "monitoring_reason": thesis_reason}
            if "EXIT" in decision or "SELL" in decision:
                order = {"order_id": stable_id("SRE81ORD", {"portfolio_id": portfolio_id, "symbol": symbol, "market_session": market_session, "run": production_run_id, "side": "SELL"}), "portfolio_id": portfolio_id, "symbol": symbol, "side": "SELL", "state": "PENDING_EXIT_NEXT_OPEN", "signal_session": market_session, "production_run_id": production_run_id}
                con.execute("insert or ignore into paper_orders values (?,?,?,?,?,?,?,?)", (order["order_id"], portfolio_id, symbol, "SELL", "PENDING_EXIT_NEXT_OPEN", market_session, None, json.dumps(order, sort_keys=True)))
                events.append(_journal(con, {"portfolio_id": portfolio_id, "market_session": market_session, "production_run_id": production_run_id, "event_type": "EXIT_SIGNAL_GENERATED", "reason": row.get("monitoring_reason") or decision, "entry_thesis": held[symbol].get("entry_thesis"), "order": order, "nav": state["nav"]}, f"{portfolio_id}|{market_session}|{production_run_id}|EXIT|{symbol}"))
            elif "WEAK" in decision:
                pos = held[symbol]
                pos["state"] = "WEAKENING"
                con.execute("update paper_positions set state='WEAKENING', state_json=? where position_id=?", (json.dumps(pos, sort_keys=True), pos["position_id"]))
                events.append(_journal(con, {"portfolio_id": portfolio_id, "market_session": market_session, "production_run_id": production_run_id, "event_type": "WEAKENING", "reason": row.get("monitoring_reason") or decision, "entry_thesis": held[symbol].get("entry_thesis"), "symbol": symbol, "nav": state["nav"]}, f"{portfolio_id}|{market_session}|{production_run_id}|WEAKENING|{symbol}"))
            else:
                events.append(_journal(con, {"portfolio_id": portfolio_id, "market_session": market_session, "production_run_id": production_run_id, "event_type": "HELD", "reason": row.get("monitoring_reason") or decision, "entry_thesis": held[symbol].get("entry_thesis"), "symbol": symbol, "nav": state["nav"]}, f"{portfolio_id}|{market_session}|{production_run_id}|HELD|{symbol}"))
        state["nav"] = round(float(state["cash"]) + sum(int(p["qty"]) * float(p.get("last_price") or p["entry_price"]) for p in held.values()), 2)
        state["valuation_quality"] = "CURRENT_OFFICIAL_MARKS" if all(p.get("last_valuation_session") == market_session for p in held.values()) else "PARTIAL_OR_STALE_MARKS"
        _save_state(con, state)
    return events
