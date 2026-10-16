from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

root = Path(os.environ["SRE_ENGINE_ROOT"]).resolve()
sys.path.insert(0, str(root))

from stock_app.validation_v2 import (  # noqa: E402
    ExecutionAssumptions,
    create_portfolio,
    load_portfolio,
    process_paper_session,
    run_replay,
)

app_data = Path(os.environ["SRE_V2_E2E_APP_DATA"]).resolve()
app_data.mkdir(parents=True, exist_ok=True)
db = app_data / "phase81_validation.sqlite3"
frontend = root / "modern_ui" / "frontend"
app = FastAPI()
app.mount("/assets", StaticFiles(directory=frontend), name="assets")


def buy(symbol: str, session: str) -> dict:
    return {
        "symbol": symbol,
        "market_session": session,
        "live_decision": {
            "final_action": "RECOVERY BUY", "executable": True,
            "strategy_style": "RECOVERY", "confidence": "HIGH",
            "recovery_thesis": f"{symbol} deterministic recovery thesis",
            "evidence": {"symbol": symbol, "session": session},
        },
    }


@app.get("/")
def index():
    return FileResponse(frontend / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "app_version": "0.14.13-paper-trading-repair"}


@app.get("/api/validation/paper-portfolio")
def paper_status(portfolio_id: str | None = None):
    return load_portfolio(db, portfolio_id)


@app.post("/api/validation/paper-portfolio/start")
def paper_start(starting_capital: float = 100000.0):
    portfolio = create_portfolio(
        db, starting_session="2026-10-15", starting_run_id="RUN-D0",
        starting_capital=starting_capital, app_version="0.14.13-paper-trading-repair",
        production_model_version="LIVE_DECISION_V1", evidence_pipeline_version="EVIDENCE-V2",
        router_sha256="fixture-router-sha",
    )
    process_paper_session(
        db, portfolio_id=portfolio["portfolio_id"], expected_session="2026-10-15",
        latest_official_session="2026-10-15", official_freshness="PASS",
        production_session="2026-10-15", production_run_id="RUN-D0",
        app_version="0.14.13-paper-trading-repair", production_model_version="LIVE_DECISION_V1",
        evidence_pipeline_version="EVIDENCE-V2",
        candidates=[buy("HINDZINC", "2026-10-15"), buy("GODREJCP", "2026-10-15")],
        allocation_plan={"new_buys": [{"symbol": "HINDZINC", "estimated_cost": 40000}, {"symbol": "GODREJCP", "estimated_cost": 30000}]},
        official_opens={}, official_closes={},
    )
    return load_portfolio(db)


@app.post("/api/validation/paper-portfolio/advance")
def paper_advance(session: str = Query("2026-10-16")):
    portfolio = load_portfolio(db)
    return process_paper_session(
        db, portfolio_id=portfolio["portfolio_id"], expected_session=session,
        latest_official_session=session, official_freshness="PASS",
        production_session=session, production_run_id="RUN-D1",
        app_version="0.14.13-paper-trading-repair", production_model_version="LIVE_DECISION_V1",
        evidence_pipeline_version="EVIDENCE-V2", candidates=[], allocation_plan={"new_buys": []},
        official_opens={"HINDZINC": 500, "GODREJCP": 1000},
        official_closes={"HINDZINC": 510, "GODREJCP": 990},
    )


@app.post("/api/validation/historical-replay")
def historical_replay(period: str = "3M", starting_capital: float = 100000.0, slippage_bps: float = 10, transaction_cost_bps: float = 5):
    sessions = ["2026-10-15", "2026-10-16", "2026-10-17"]
    packages = {
        sessions[0]: {"rows": [buy("HINDZINC", sessions[0])], "opens": {"HINDZINC": 490}, "closes": {"HINDZINC": 500}, "benchmark_close": 100, "allocation_plan": {"new_buys": [{"symbol": "HINDZINC", "estimated_cost": 50000}]}},
        sessions[1]: {"rows": [], "opens": {"HINDZINC": 500}, "closes": {"HINDZINC": 510}, "benchmark_close": 105, "allocation_plan": {"new_buys": []}},
        sessions[2]: {"rows": [], "opens": {}, "closes": {"HINDZINC": 520}, "benchmark_close": 110, "allocation_plan": {"new_buys": []}},
    }
    def provider(session, state):
        return {"replayability": "PIT_VALID_WITH_OPTIONAL_GAPS", "market_data_status": "PASS", "fundamental_pit_status": "PASS", "valuation_pit_status": "MISSING_OPTIONAL", "universe_status": "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS", "live_decision_v1_run_status": "PASS", **packages[session]}
    return run_replay(requested_period=period, sessions=sessions, starting_capital=starting_capital, assumptions=ExecutionAssumptions(starting_capital=starting_capital, slippage_bps=slippage_bps, transaction_cost_bps=transaction_cost_bps), session_provider=provider)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["SRE_V2_E2E_PORT"]), log_level="warning")
