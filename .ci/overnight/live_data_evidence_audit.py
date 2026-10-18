"""Fail-closed evidence audit for current SRE universe; never fetches or trades.

Usage:
  python .ci/overnight/live_data_evidence_audit.py --input path/to/snapshot.json --output path/to/report.json

Expected input JSON:
{
  "as_of": "2026-10-16",
  "symbols": ["AAA", "BBB"],
  "daily_bars": [{"symbol":"AAA","date":"2026-10-16","source_exchange":"NSE",
                  "open":100,"high":102,"low":99,"close":101,"volume":1000}],
  "filings": [{"symbol":"AAA","source_exchange":"NSE","quarter_end":"2026-06-30",
              "reporting_basis":"CONSOLIDATED","submission_type":"ORIGINAL",
              "publication_ts":"2026-07-20T10:00:00+05:30",
              "availability_ts":"2026-07-20T10:00:00+05:30"}]
}
No input, empty universe, or malformed data is NEVER counted as passing coverage.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

def audit(snapshot: object) -> dict:
    if not isinstance(snapshot, dict):
        raise ValueError("SNAPSHOT_OBJECT_REQUIRED")
    as_of = date.fromisoformat(snapshot["as_of"])
    symbols = snapshot.get("symbols")
    if not isinstance(symbols, list) or not symbols or any(not isinstance(s, str) or not s.strip() for s in symbols):
        raise ValueError("NONEMPTY_SYMBOL_UNIVERSE_REQUIRED")
    universe = [s.strip().upper() for s in symbols]
    if len(set(universe)) != len(universe):
        raise ValueError("DUPLICATE_UNIVERSE_SYMBOLS")
    bars = snapshot.get("daily_bars")
    filings = snapshot.get("filings")
    if not isinstance(bars, list) or not isinstance(filings, list):
        raise ValueError("BARS_AND_FILINGS_LISTS_REQUIRED")
    valid_bars = set()
    invalid_bars = 0
    for row in bars:
        try:
            if not isinstance(row, dict):
                raise ValueError()
            symbol = row["symbol"].strip().upper()
            traded = date.fromisoformat(row["date"])
            source = row["source_exchange"].strip().upper()
            prices = [float(row[k]) for k in ("open", "high", "low", "close")]
            volume = float(row["volume"])
            o, h, l, c = prices
            if (symbol not in universe or traded != as_of or source not in {"NSE", "BSE"}
                or not all(math.isfinite(x) and x > 0 for x in prices)
                or not math.isfinite(volume) or volume < 0
                or h < max(o, c, l) or l > min(o, c, h)):
                raise ValueError()
            valid_bars.add(symbol)
        except (KeyError, AttributeError, ValueError, TypeError, OverflowError):
            invalid_bars += 1
    from datetime import datetime
    valid_filings = set()
    invalid_filings = 0
    for row in filings:
        try:
            if not isinstance(row, dict):
                raise ValueError()
            symbol = row["symbol"].strip().upper()
            quarter = date.fromisoformat(row["quarter_end"])
            source = row["source_exchange"].strip().upper()
            basis = row["reporting_basis"].strip().upper()
            submission = row["submission_type"].strip().upper()
            published = datetime.fromisoformat(row["publication_ts"].replace("Z", "+00:00"))
            available = datetime.fromisoformat(row["availability_ts"].replace("Z", "+00:00"))
            if (symbol not in universe or source not in {"NSE", "BSE"}
                or basis not in {"STANDALONE", "CONSOLIDATED"}
                or submission not in {"ORIGINAL", "REVISION", "REVISED"}
                or published.tzinfo is None or available.tzinfo is None
                or available < published or quarter > published.date() or available.date() > as_of):
                raise ValueError()
            valid_filings.add(symbol)
        except (KeyError, AttributeError, ValueError, TypeError, OverflowError):
            invalid_filings += 1
    expected = set(universe)
    missing_daily = sorted(expected - valid_bars)
    missing_filings = sorted(expected - valid_filings)
    return {
        "schema": "SRE_LIVE_DATA_EVIDENCE_AUDIT_V1",
        "as_of": as_of.isoformat(),
        "authority": "AUDIT_ONLY",
        "universe_count": len(expected),
        "daily_covered": len(valid_bars),
        "filing_covered": len(valid_filings),
        "missing_daily": missing_daily,
        "missing_filings": missing_filings,
        "invalid_daily_rows": invalid_bars,
        "invalid_filing_rows": invalid_filings,
        "complete": not missing_daily and not missing_filings and not invalid_bars and not invalid_filings,
        "limitations": ["One as_of snapshot only; no holiday-calendar or corporate-action continuity validation",
                        "Filing records are schema-checked, not authenticated against exchange manifests",
                        "Does not validate statement metrics, investment rules, or trading performance"],
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["complete"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
