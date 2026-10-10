from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.acquisition import (  # noqa: E402
    NSE_INTEGRATED_API,
    NSE_LANDING_URL,
    acquire_symbol,
)
from fundamental_research_v2_phase2a.core import TARGET_QUARTER_ENDS  # noqa: E402

PILOT = ("M&M", "IRCTC", "NESTLEIND", "PATANJALI")
OUT = ROOT / "results" / "fundamental_v2_phase2a1_pilot"
OUT.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36"
)

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json,text/plain,*/*",
    "Connection": "keep-alive",
})


def warm() -> None:
    response = session.get(
        NSE_LANDING_URL,
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        timeout=30,
    )
    response.raise_for_status()


def fetch_json(url: str, params: dict, headers: dict):
    merged = dict(headers)
    merged["User-Agent"] = UA
    for attempt in range(4):
        response = session.get(url, params=params, headers=merged, timeout=45)
        if response.status_code in {401, 403, 429} and attempt < 3:
            time.sleep(2 + attempt)
            warm()
            continue
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("NSE_INTEGRATED_RESPONSE_NOT_OBJECT")
        time.sleep(0.75)
        return payload
    raise RuntimeError("NSE_INTEGRATED_RETRY_EXHAUSTED")


def main() -> int:
    warm()

    results = []
    failures = []
    for symbol in PILOT:
        try:
            result = acquire_symbol(symbol, fetch_json=fetch_json, page_size=50, max_pages=10)
            results.append(result)
            (OUT / f"{symbol.replace('&','AND')}_acquisition.json").write_text(
                json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
            )
        except Exception as exc:
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})

    all_events = [event for result in results for event in result["target_events"]]
    by_symbol = {}
    for symbol in PILOT:
        sym_events = [x for x in all_events if x["symbol"] == symbol]
        by_symbol[symbol] = {
            "target_event_count": len(sym_events),
            "quarters": sorted({x["quarter_end"] for x in sym_events}),
            "basis": sorted({x["reporting_basis"] for x in sym_events}),
            "submission_types": sorted({x["submission_type"] for x in sym_events}),
            "missing_target_quarters": sorted(set(TARGET_QUARTER_ENDS) - {x["quarter_end"] for x in sym_events}),
        }

    summary = {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A1_PILOT_RUN_V1",
        "pilot_symbols": list(PILOT),
        "target_quarters": list(TARGET_QUARTER_ENDS),
        "successful_symbols": [x["symbol"] for x in results],
        "failures": failures,
        "event_count": len(all_events),
        "by_symbol": by_symbol,
        "authority": "SHADOW_ONLY",
        "production_model_changed": False,
        "model_training_started": False,
    }
    (OUT / "pilot_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (OUT / "pilot_events.json").write_text(
        json.dumps(all_events, indent=2, sort_keys=True), encoding="utf-8"
    )

    print(json.dumps(summary, indent=2, sort_keys=True))
    if failures:
        return 2
    if not all_events:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
