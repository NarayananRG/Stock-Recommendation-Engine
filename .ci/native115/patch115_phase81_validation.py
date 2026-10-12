from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])


def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(label + " contract missing")
    return text.replace(old, new, 1)


module = r'''from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

AUTHORITY = {
    "schema": "SRE_PHASE81_PRODUCTION_AUTHORITY_TRACE_V1",
    "phase": "PHASE_8_1_HISTORICAL_REPLAY_AND_PAPER_PORTFOLIO",
    "production_recommendation_authority": "FROZEN_PRODUCTION_MODEL",
    "production_path": [
        "official market data",
        "ensure_analysis_run",
        "latest_prediction_rows",
        "production decision",
        "executability",
        "Capital Plan V3 allocation",
    ],
    "technical_v2_authority": "SHADOW_ONLY",
    "fundamental_v3_authority": "SHADOW_ONLY",
    "combined_v2_authority": "SHADOW_ONLY",
    "combined_v2_target_used_in_score": False,
    "combined_v2_promotion_allowed": False,
    "watch_is_executable": False,
    "broker_execution": False,
    "automatic_yfinance_fallback": False,
}


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


def is_executable(row: dict[str, Any]) -> bool:
    decision = str(row.get("opportunity_status") or row.get("decision") or "").upper()
    return bool(row.get("executable")) and "BUY" in decision and "WATCH" not in decision


def classify_pit(session: str, *, latest_official_session: str | None, pit_available: bool, optional_missing: bool = False) -> str:
    if not latest_official_session:
        return "NOT_REPLAYABLE"
    if session > latest_official_session:
        return "NOT_REPLAYABLE"
    if not pit_available:
        return "PIT_DATA_INCOMPLETE"
    if optional_missing:
        return "PIT_VALID_WITH_MISSING_OPTIONAL_DATA"
    return "FULL_PIT_VALID"


def session_summary(
    session: str,
    rows: list[dict[str, Any]],
    *,
    capital_plan: dict[str, Any] | None = None,
    assumptions: ExecutionAssumptions | None = None,
    pit_status: str = "FULL_PIT_VALID",
    model_identity: str = "FROZEN_PRODUCTION_MODEL",
    source_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assumptions = assumptions or ExecutionAssumptions()
    executable = [r for r in rows if is_executable(r)]
    watch = [r for r in rows if "WATCH" in str(r.get("opportunity_status") or "").upper()]
    buy_count = len(executable)
    deployed = 0.0
    if capital_plan:
        deployed = float(sum(float(x.get("capital") or x.get("amount") or x.get("estimated_cost") or 0.0) for x in capital_plan.get("new_buys", []) or []))
    cash = max(0.0, assumptions.starting_capital - deployed)
    blockers: dict[str, int] = {}
    for row in rows:
        if is_executable(row):
            continue
        reason = str(row.get("execution_reason") or row.get("blocking_reason") or row.get("opportunity_status") or "OTHER_PRODUCTION_GATE")
        blockers[reason] = blockers.get(reason, 0) + 1
    return {
        "schema": "SRE_PHASE81_HISTORICAL_SESSION_SUMMARY_V1",
        "session": session,
        "pit_status": pit_status,
        "universe_size": len(rows),
        "recommendations_generated": len(rows),
        "executable_buy_count": buy_count,
        "watch_count": len(watch),
        "no_action_count": max(0, len(rows) - buy_count - len(watch)),
        "capital_deployed": round(deployed, 2),
        "cash_retained": round(cash, 2),
        "portfolio_nav": round(cash + deployed, 2),
        "model_identity": model_identity,
        "source_data_identity": source_identity or {},
        "top_blocking_reasons": sorted(blockers.items(), key=lambda x: (-x[1], x[0]))[:10],
        "rows": rows,
        "capital_plan": capital_plan or {"new_buys": [], "excluded": []},
        "assumptions": asdict(assumptions),
        "authority": AUTHORITY,
    }


def next_open_fill(signal_session: str, next_session: str, open_price: float, side: str, assumptions: ExecutionAssumptions | None = None) -> dict[str, Any]:
    assumptions = assumptions or ExecutionAssumptions()
    if next_session <= signal_session:
        raise ValueError("POST_CLOSE_SIGNAL_REQUIRES_NEXT_SESSION_OPEN")
    sign = 1 if side.upper() == "BUY" else -1
    slippage = float(open_price) * float(assumptions.slippage_bps) / 10000.0
    cost = float(open_price) * float(assumptions.transaction_cost_bps) / 10000.0
    fill = float(open_price) + sign * slippage
    return {
        "signal_session": signal_session,
        "fill_session": next_session,
        "timing": "NEXT_SESSION_OPEN",
        "side": side.upper(),
        "open_price": round(float(open_price), 6),
        "slippage_per_share": round(slippage, 6),
        "cost_per_share": round(cost, 6),
        "fill_price": round(fill, 6),
        "net_price": round(fill + cost if sign > 0 else fill - cost, 6),
        "broker_execution": False,
    }


def whole_share_quantity(cash: float, price: float, assumptions: ExecutionAssumptions | None = None) -> int:
    assumptions = assumptions or ExecutionAssumptions()
    if price <= 0:
        return 0
    effective = price * (1 + (assumptions.slippage_bps + assumptions.transaction_cost_bps) / 10000.0)
    return int(max(0.0, cash) // effective)


def max_drawdown(values: list[float]) -> float:
    peak = None
    worst = 0.0
    for value in values:
        value = float(value)
        peak = value if peak is None else max(peak, value)
        if peak and peak > 0:
            worst = min(worst, (value - peak) / peak)
    return round(worst, 6)


def replay_metrics(sessions: list[dict[str, Any]], nav: list[float] | None = None, benchmark_nav: list[float] | None = None) -> dict[str, Any]:
    replayable = [s for s in sessions if str(s.get("pit_status")) in {"FULL_PIT_VALID", "PIT_VALID_WITH_MISSING_OPTIONAL_DATA"}]
    buy_sessions = [s for s in replayable if int(s.get("executable_buy_count") or 0) > 0]
    streak = 0
    longest = 0
    total_buys = 0
    cash_pct = []
    deployed_pct = []
    for s in replayable:
        buys = int(s.get("executable_buy_count") or 0)
        total_buys += buys
        if buys:
            streak = 0
        else:
            streak += 1
            longest = max(longest, streak)
        nav_value = float(s.get("portfolio_nav") or 100000.0)
        cash = float(s.get("cash_retained") or 0.0)
        deployed = float(s.get("capital_deployed") or 0.0)
        if nav_value > 0:
            cash_pct.append(cash / nav_value)
            deployed_pct.append(deployed / nav_value)
    nav = nav or [100000.0]
    benchmark_nav = benchmark_nav or [100000.0]
    portfolio_return = (nav[-1] - nav[0]) / nav[0] if len(nav) > 1 and nav[0] else 0.0
    benchmark_return = (benchmark_nav[-1] - benchmark_nav[0]) / benchmark_nav[0] if len(benchmark_nav) > 1 and benchmark_nav[0] else 0.0
    buy_frequency = len(buy_sessions) / len(replayable) if replayable else 0.0
    if buy_frequency == 0:
        activity = "HIGHLY_RESTRICTIVE"
    elif buy_frequency < 0.10:
        activity = "LOW_ACTIVITY"
    else:
        activity = "NORMAL_ACTIVITY"
    return {
        "schema": "SRE_PHASE81_REPLAY_METRICS_V1",
        "total_replayable_sessions": len(replayable),
        "sessions_with_executable_buy": len(buy_sessions),
        "buy_frequency": round(buy_frequency, 6),
        "average_executable_buys_per_active_session": round(total_buys / len(buy_sessions), 6) if buy_sessions else 0.0,
        "total_buy_signals": total_buys,
        "longest_no_buy_streak": longest,
        "average_cash_pct": round(sum(cash_pct) / len(cash_pct), 6) if cash_pct else 0.0,
        "average_capital_deployed_pct": round(sum(deployed_pct) / len(deployed_pct), 6) if deployed_pct else 0.0,
        "maximum_capital_deployed_pct": round(max(deployed_pct), 6) if deployed_pct else 0.0,
        "portfolio_return": round(portfolio_return, 6),
        "benchmark_return": round(benchmark_return, 6),
        "excess_return": round(portfolio_return - benchmark_return, 6),
        "maximum_drawdown": max_drawdown(nav),
        "benchmark_max_drawdown": max_drawdown(benchmark_nav),
        "activity_classification": activity,
    }


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("create table if not exists replay_runs (replay_id text primary key, created_at text not null, config_json text not null, result_json text not null)")
    con.execute("create table if not exists paper_portfolios (portfolio_id text primary key, created_at text not null, starting_session text not null, starting_capital real not null, state_json text not null)")
    con.execute("create table if not exists paper_journal (event_id text primary key, portfolio_id text not null, market_session text not null, production_run_id text, created_at text not null, event_json text not null)")
    con.execute("create unique index if not exists idx_paper_journal_idempotency on paper_journal(portfolio_id, market_session, production_run_id)")
    return con


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return prefix + "_" + hashlib.sha256(raw).hexdigest()[:16]


def create_portfolio(db_path: Path, *, starting_session: str, starting_capital: float = 100000.0) -> dict[str, Any]:
    created = datetime.now().isoformat(timespec="seconds")
    payload = {"starting_session": starting_session, "starting_capital": starting_capital, "created_at": created}
    portfolio_id = stable_id("SRE81PAPER", payload)
    state = {
        "portfolio_id": portfolio_id,
        "created_at": created,
        "starting_session": starting_session,
        "starting_capital": starting_capital,        "cash": starting_capital,
        "positions": [],
        "nav": starting_capital,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "status": "ACTIVE",
        "authority": AUTHORITY,
    }
    with connect(db_path) as con:
        con.execute("insert or ignore into paper_portfolios values (?,?,?,?,?)", (portfolio_id, created, starting_session, starting_capital, json.dumps(state, sort_keys=True)))
    return state


def record_daily_observation(db_path: Path, *, portfolio_id: str, market_session: str, production_run_id: str | None, recommendations: list[dict[str, Any]], capital_plan: dict[str, Any] | None = None, benchmark_value: float | None = None) -> dict[str, Any]:
    executable = [r for r in recommendations if is_executable(r)]
    decision = "CASH / NO EXECUTABLE BUY" if not executable else "SIGNAL_GENERATED"
    event = {
        "schema": "SRE_PHASE81_PROSPECTIVE_JOURNAL_EVENT_V1",
        "portfolio_id": portfolio_id,
        "market_session": market_session,
        "production_run_id": production_run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model_identity": "FROZEN_PRODUCTION_MODEL",
        "official_data_provenance": "OFFICIAL_FIRST",
        "recommendations_observed": len(recommendations),
        "executable_buys": len(executable),
        "capital_plan": capital_plan or {"new_buys": [], "excluded": []},
        "orders_simulated": [],
        "positions_before": [],
        "positions_after": [],
        "cash_before": 100000.0,
        "cash_after": 100000.0,
        "nav": 100000.0,
        "benchmark_value": benchmark_value,
        "reason": decision,
        "decision": decision,
        "automatic_yfinance_fallback": False,
        "broker_execution": False,
    }
    event_id = stable_id("SRE81EVT", event)
    event["journal_event_id"] = event_id
    event["integrity_hash"] = hashlib.sha256(json.dumps(event, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    with connect(db_path) as con:
        try:
            con.execute("insert into paper_journal values (?,?,?,?,?,?)", (event_id, portfolio_id, market_session, production_run_id, event["created_at"], json.dumps(event, sort_keys=True)))
            duplicate = False
        except sqlite3.IntegrityError:
            row = con.execute("select event_json from paper_journal where portfolio_id=? and market_session=? and production_run_id is ?", (portfolio_id, market_session, production_run_id)).fetchone()
            event = json.loads(row[0]) if row else event
            duplicate = True
    event["duplicate"] = duplicate
    return event
'''

(root / "stock_app" / "phase81_validation.py").write_text(module, encoding="utf-8")

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = s.replace('APP_VERSION = "0.12.7-phase7-official-source-diagnostics-hotfix"', 'APP_VERSION = "0.13.0-phase8-validation"')
anchor = '''    def latest_prediction_rows(self, limit: int = 20) -> list[dict[str, Any]]:
'''
helpers = r'''    def _phase81_db_path(self) -> Path:
        return self.config.app_data_dir / "phase81_validation.sqlite3"

    def phase81_authority_trace(self) -> dict[str, Any]:
        from stock_app.phase81_validation import AUTHORITY
        return {**AUTHORITY, "backend_version": APP_VERSION}

    def phase81_historical_replay(self, period: str = "6M", starting_capital: float = 100000.0, benchmark: str = "NIFTY 50") -> dict[str, Any]:
        from stock_app.phase81_validation import ExecutionAssumptions, replay_metrics, session_summary, stable_id
        gate = self._daily_data_gate()
        assumptions = ExecutionAssumptions(starting_capital=float(starting_capital), benchmark=benchmark)
        rows = self.latest_prediction_rows(limit=200)
        run = self.ui_run_input()
        session = gate.get("latest_official_session") or gate.get("target_session")
        source = gate.get("source") or {}
        summary = session_summary(
            str(session or "UNKNOWN"),
            rows,
            capital_plan={"new_buys": [], "excluded": []},
            assumptions=assumptions,
            pit_status="FULL_PIT_VALID" if gate.get("ready") else "PIT_DATA_INCOMPLETE",
            model_identity=APP_VERSION,
            source_identity={"mode": source.get("mode"), "latest_official_session": gate.get("latest_official_session")},
        )
        metrics = replay_metrics([summary], nav=[float(starting_capital), float(summary["portfolio_nav"])], benchmark_nav=[float(starting_capital), float(starting_capital)])
        result = {
            "schema": "SRE_PHASE81_HISTORICAL_REPLAY_RESULT_V1",
            "label": "HISTORICAL REPLAY - Not prospective evidence",
            "period": period,
            "date_range": {"end": session, "requested": period},
            "replay_id": stable_id("SRE81REPLAY", {"period": period, "capital": starting_capital, "benchmark": benchmark, "session": session, "version": APP_VERSION}),
            "status": "COMPLETED_WITH_AVAILABLE_PIT_WINDOW",
            "pit_audit": {
                "default_window_note": "Only sessions with PIT-safe production inputs are replayable. Missing historical PIT fundamentals are not backfilled from current data.",
                "largest_trustworthy_window": "current accepted official session" if gate.get("ready") else "none",
            },
            "assumptions": summary["assumptions"],
            "sessions": [summary],
            "metrics": metrics,
            "authority": self.phase81_authority_trace(),
            "automatic_yfinance_fallback": False,
            "broker_execution": False,
        }
        from stock_app.phase81_validation import connect
        with connect(self._phase81_db_path()) as con:
            con.execute("insert or replace into replay_runs values (?,?,?,?)", (result["replay_id"], datetime.now().isoformat(timespec="seconds"), json.dumps({"period": period, "starting_capital": starting_capital, "benchmark": benchmark}, sort_keys=True), json.dumps(result, sort_keys=True)))
        return result

    def phase81_paper_status(self) -> dict[str, Any]:
        from stock_app.phase81_validation import connect
        with connect(self._phase81_db_path()) as con:
            row = con.execute("select state_json from paper_portfolios order by created_at desc limit 1").fetchone()
            events = [json.loads(x[0]) for x in con.execute("select event_json from paper_journal order by created_at desc limit 50").fetchall()]
        if not row:
            return {"schema": "SRE_PHASE81_PAPER_PORTFOLIO_STATUS_V1", "active": False, "label": "PROSPECTIVE PAPER TRACKING - Forward-only evidence", "starting_capital": 100000.0, "authority": self.phase81_authority_trace()}
        state = json.loads(row[0])
        return {**state, "schema": "SRE_PHASE81_PAPER_PORTFOLIO_STATUS_V1", "active": True, "label": "PROSPECTIVE PAPER TRACKING - Forward-only evidence", "journal": events, "authority": self.phase81_authority_trace()}

    def phase81_start_paper(self, starting_capital: float = 100000.0) -> dict[str, Any]:
