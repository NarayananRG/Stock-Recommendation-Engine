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
from fundamental_research_v2_phase2a.core import TARGET_QUARTER_ENDS, coverage_audit  # noqa: E402
from fundamental_research_v2_phase2a.validation import validate_pit_events  # noqa: E402

UNIVERSE_PATH = ROOT / "fundamental_research_v2_phase2a" / "phase2a1_universe_resolution.json"
PILOT_VALIDATION = ROOT / "results" / "fundamental_v2_phase2a1_pilot" / "pilot_pit_validation.json"
OUT = ROOT / "results" / "fundamental_v2_phase2a1_scaled"
BY_SYMBOL = OUT / "by_symbol"
OUT.mkdir(parents=True, exist_ok=True)
BY_SYMBOL.mkdir(parents=True, exist_ok=True)

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
    for attempt in range(5):
        response = session.get(url, params=params, headers=merged, timeout=45)
        if response.status_code in {401, 403, 429} and attempt < 4:
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


def safe_name(symbol: str) -> str:
    return symbol.replace("&", "AND").replace("/", "_")


def load_universe() -> list[str]:
    doc = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    symbols = doc.get("canonical_symbols")
    if not isinstance(symbols, list) or len(symbols) != 186:
        raise RuntimeError("CANONICAL_186_UNIVERSE_CONTRACT_FAILED")
    if len(set(symbols)) != 186:
        raise RuntimeError("CANONICAL_UNIVERSE_DUPLICATES")
    return [str(x) for x in symbols]


def pilot_gate() -> None:
    if not PILOT_VALIDATION.exists():
        raise RuntimeError("PILOT_VALIDATION_MISSING_RUN_VALIDATOR_FIRST")
    report = json.loads(PILOT_VALIDATION.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise RuntimeError("PILOT_PIT_VALIDATION_NOT_PASS")


def write_checkpoint(symbols: list[str], completed: list[str], failures: list[dict]) -> None:
    payload = {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A1_SCALE_CHECKPOINT_V1",
        "target_symbol_count": len(symbols),
        "completed_symbol_count": len(completed),
        "completed_symbols": completed,
        "failure_count": len(failures),
        "failures": failures,
        "authority": "SHADOW_ONLY",
    }
    (OUT / "scale_checkpoint.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def main() -> int:
    pilot_gate()
    symbols = load_universe()
    warm()

    results = []
    failures = []
    completed = []

    for index, symbol in enumerate(symbols, start=1):
        path = BY_SYMBOL / f"{safe_name(symbol)}_acquisition.json"
        try:
            if path.exists():
                result = json.loads(path.read_text(encoding="utf-8"))
            else:
                result = acquire_symbol(symbol, fetch_json=fetch_json, page_size=50, max_pages=10)
                path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            results.append(result)
            completed.append(symbol)
            print(f"[{index:03d}/{len(symbols)}] {symbol}: {result.get('target_event_count', 0)} target events")
        except Exception as exc:
            failure = {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}
            failures.append(failure)
            print(f"[{index:03d}/{len(symbols)}] {symbol}: FAIL {failure['error']}")
        write_checkpoint(symbols, completed, failures)

    all_events = [event for result in results for event in result.get("target_events", [])]
    (OUT / "all_target_events.json").write_text(
        json.dumps(all_events, indent=2, sort_keys=True), encoding="utf-8"
    )

    validation = validate_pit_events(
        all_events,
        required_symbols=[x["symbol"] for x in results],
        require_all_target_quarters=False,
    )
    (OUT / "scaled_pit_validation.json").write_text(
        json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8"
    )

    coverage = coverage_audit(all_events, target_symbols=symbols)
    period_counts = {
        period: len({
            event["symbol"] for event in all_events
            if event.get("quarter_end") == period
        })
        for period in TARGET_QUARTER_ENDS
    }
    coverage["target_quarter_symbol_counts"] = period_counts
    coverage["target_quarter_missing_counts"] = {
        period: len(symbols) - count for period, count in period_counts.items()
    }
    (OUT / "scaled_coverage_audit.json").write_text(
        json.dumps(coverage, indent=2, sort_keys=True), encoding="utf-8"
    )

    missing_by_symbol = {}
    target = set(TARGET_QUARTER_ENDS)
    for symbol in symbols:
        present = {
            e["quarter_end"] for e in all_events
            if e.get("symbol") == symbol and e.get("quarter_end") in target
        }
        missing = sorted(target - present)
        if missing:
            missing_by_symbol[symbol] = missing

    summary = {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A1_SCALED_RECOVERY_V1",
        "target_symbol_count": len(symbols),
        "successful_symbol_count": len(results),
        "failed_symbol_count": len(failures),
        "failures": failures,
        "target_event_count": len(all_events),
        "symbols_with_any_missing_target_quarter": len(missing_by_symbol),
        "missing_target_quarters_by_symbol": missing_by_symbol,
        "target_quarter_symbol_counts": period_counts,
        "pit_validation_status": validation["status"],
        "pit_validation_failure_count": validation["failure_count"],
        "authority": "SHADOW_ONLY",
        "production_model_changed": False,
        "model_training_started": False,
    }
    (OUT / "scaled_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))

    if validation["status"] != "PASS":
        return 4
    if failures:
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
