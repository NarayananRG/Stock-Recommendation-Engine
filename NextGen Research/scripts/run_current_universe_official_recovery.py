from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
import sys

import requests

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from fundamental_research_v2_phase2a.acquisition import (  # noqa: E402
    NSE_LANDING_URL,
    acquire_symbol,
)
from fundamental_research_v2_phase2a.core import rebind_event_availability  # noqa: E402
from fundamental_research_v2_phase2a.current_universe_recovery import (  # noqa: E402
    acquisition_gap,
    merge_official_events,
    recovery_summary,
    symbols_from_live_snapshot,
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155 Safari/537.36"
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--snapshot", type=Path, required=True)
    result.add_argument("--existing-events", type=Path, required=True)
    result.add_argument("--out", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    existing = json.loads(args.existing_events.read_text(encoding="utf-8"))
    symbols = symbols_from_live_snapshot(snapshot)
    missing = acquisition_gap(symbols, existing)
    args.out.mkdir(parents=True, exist_ok=True)
    cache = args.out / "by_symbol"
    cache.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json,text/plain,*/*",
    })

    def warm() -> None:
        response = session.get(NSE_LANDING_URL, timeout=30)
        response.raise_for_status()

    def fetch_json(url: str, params: dict, headers: dict):
        merged_headers = {**headers, "User-Agent": UA}
        last = None
        for attempt in range(5):
            try:
                response = session.get(url, params=params, headers=merged_headers, timeout=45)
                if response.status_code in {401, 403, 429, 500, 502, 503, 504} and attempt < 4:
                    time.sleep(1 + attempt)
                    warm()
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("NSE_INTEGRATED_RESPONSE_NOT_OBJECT")
                return payload
            except Exception as exc:  # retain exact terminal failure in report
                last = exc
        raise last or RuntimeError("NSE_INTEGRATED_RETRY_EXHAUSTED")

    if missing:
        warm()
    recovered = []
    failures = []
    for index, symbol in enumerate(missing, start=1):
        path = cache / (symbol.replace("&", "AND").replace("/", "_") + ".json")
        try:
            if path.exists():
                result = json.loads(path.read_text(encoding="utf-8"))
            else:
                result = acquire_symbol(symbol, fetch_json=fetch_json, page_size=50, max_pages=10)
                path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            recovered.extend(rebind_event_availability(row) for row in result.get("target_events", []))
            print(f"[{index}/{len(missing)}] {symbol}: {result.get('target_event_count', 0)} target events", flush=True)
        except Exception as exc:
            failures.append({"symbol": symbol, "reason": f"{type(exc).__name__}: {exc}"})
            print(f"[{index}/{len(missing)}] {symbol}: FAILED {failures[-1]['reason']}", flush=True)

    merged = merge_official_events(existing, recovered)
    report = recovery_summary(symbols=symbols, existing=existing, recovered=recovered)
    report.update({
        "run_id": (snapshot.get("run") or {}).get("run_id"),
        "market_session": (snapshot.get("run") or {}).get("market_session"),
        "snapshot_candidate_count": len(symbols),
        "acquisition_failures": failures,
        "source_priority": ["NSE", "BSE", "COMPANY_IR"],
        "sources_attempted": ["NSE"],
    })
    (args.out / "all_target_events_merged.json").write_text(
        json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8"
    )
    (args.out / "recovery_summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
