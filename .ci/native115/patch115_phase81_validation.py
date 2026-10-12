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
