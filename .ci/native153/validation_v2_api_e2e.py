from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

engine = Path(os.environ["SRE_ENGINE_ROOT"]).resolve()
port = int(os.environ.get("SRE_V2_API_E2E_PORT", "8897"))
app_data = Path(tempfile.mkdtemp(prefix="sre-v2-api-e2e-"))
env = dict(os.environ)
env["SRE_BROWSER_PORT"] = str(port)
env["SRE_BROWSER_APP_DATA"] = str(app_data)
env["SRE_EXPECTED_SESSION_NOW"] = "2026-10-15T19:15:00+05:30"

proc = subprocess.Popen(
    [sys.executable, ".ci/native145/serve_runtime.py"],
    cwd=str(Path.cwd()),
    env=env,
)
base = "http://127.0.0.1:" + str(port)


def request(path: str, method: str = "GET"):
    req = urllib.request.Request(base + path, method=method)
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


try:
    for _ in range(160):
        try:
            health = request("/api/health")
            if health.get("status") == "ok":
                break
        except Exception:
            time.sleep(0.25)
    else:
        raise RuntimeError("Validation V2 FastAPI runtime did not start")

    if health.get("app_version") != "0.14.12-validation-v2":
        raise AssertionError("Wrong V2 backend version: " + str(health.get("app_version")))

    before = request("/api/post-close-daily-flow")
    expected = before.get("expected_market_session") or before.get("target_session")
    official = before.get("latest_available_official_session")
    if expected != "2026-10-15" or official != expected:
        raise AssertionError("Official session fixture is not current: " + json.dumps(before, default=str))

    run_result = request("/api/post-close-daily-flow?force=true", "POST")
    after = request("/api/post-close-daily-flow")
    if after.get("active_analysis_session") != expected or after.get("analysis_current") is not True:
        raise AssertionError("Production analysis did not become current: " + json.dumps(after, default=str))

    opportunities = request("/api/opportunities?limit=200")
    items = opportunities.get("items") or []
    buys = [
        row for row in items
        if (row.get("live_decision") or {}).get("executable") is True
        and str((row.get("live_decision") or {}).get("final_action") or "").endswith("BUY")
    ]
    if not buys:
        raise AssertionError("Accepted 0.14.11 evidence base produced no current executable BUY for V2 paper E2E")

    start = request("/api/validation/paper-portfolio/start?starting_capital=100000", "POST")
    if not start.get("active") or not start.get("portfolio_id"):
        raise AssertionError("V2 paper portfolio did not start: " + json.dumps(start, default=str))
    if float(start.get("cash") or 0) != 100000:
        raise AssertionError("V2 starting cash mismatch")

    first = request("/api/validation/paper-portfolio/record-today", "POST")
    if first.get("status") != "RECORDED":
        raise AssertionError("V2 paper session was not recorded: " + json.dumps(first, default=str))
    status1 = request("/api/validation/paper-portfolio")
    if status1.get("legacy_v1_excluded") is not True:
        raise AssertionError("Legacy Validation V1 was not excluded")
    pending1 = [x for x in (status1.get("pending_orders") or []) if x.get("side") == "BUY"]
    if not pending1:
        raise AssertionError("Current executable LIVE_DECISION_V1 BUYs did not become V2 pending next-open orders")
    if any(x.get("state") != "PENDING_NEXT_OPEN" for x in pending1):
        raise AssertionError("V2 BUY order is not next-open pending: " + json.dumps(pending1, default=str))
    journal_count = len(status1.get("journal") or [])
    order_count = len(status1.get("pending_orders") or [])

    second = request("/api/validation/paper-portfolio/record-today", "POST")
    status2 = request("/api/validation/paper-portfolio")
    if len(status2.get("journal") or []) != journal_count:
        raise AssertionError("Duplicate V2 daily record created extra journal events")
    if len(status2.get("pending_orders") or []) != order_count:
        raise AssertionError("Duplicate V2 daily record created extra pending orders")

    legacy = request("/api/validation/legacy/paper-portfolio")
    if legacy.get("read_only") is not True or legacy.get("excluded_from_v2_performance") is not True:
        raise AssertionError("Legacy validation endpoint is not explicitly read-only/excluded")

    replay = request(
        "/api/validation/historical-replay?period=1M&starting_capital=100000"
        "&start_date=2026-10-15&end_date=2026-10-15&slippage_bps=10&transaction_cost_bps=5",
        "POST",
    )
    if replay.get("schema") != "SRE_VALIDATION_V2_HISTORICAL_REPLAY":
        raise AssertionError("Historical Replay V2 schema missing: " + json.dumps(replay, default=str)[:2000])
    if replay.get("status") != "COMPLETED":
        raise AssertionError("Historical Replay V2 did not reconstruct the accepted session: " + str(replay.get("status")))
    if replay.get("survivorship_bias_warning") is not True:
        raise AssertionError("Historical replay survivorship-bias warning missing")
    benchmark = replay.get("benchmark") or {}
    if benchmark.get("source") != "OFFICIAL_INDEX_HISTORY" or benchmark.get("flat_placeholder") is not False:
        raise AssertionError("Historical replay benchmark is not actual official NIFTY history")
    sessions = replay.get("sessions") or []
    if len(sessions) != 1 or sessions[0].get("pit_status") == "NOT_REPLAYABLE":
        raise AssertionError("Accepted historical session is not replayable: " + json.dumps(sessions, default=str))
    if int(sessions[0].get("reconstructed_symbols") or 0) < 190:
        raise AssertionError("Historical replay reconstructed fewer than 190 symbols")
    if replay.get("automatic_yfinance_fallback") is not False:
        raise AssertionError("Automatic yfinance fallback changed")

    print("0.14.12 VALIDATION V2 REAL FASTAPI E2E PASS")
    print("Current BUY -> pending next-open PASS; duplicate-safe PASS; legacy isolation PASS; one-session PIT replay PASS")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
