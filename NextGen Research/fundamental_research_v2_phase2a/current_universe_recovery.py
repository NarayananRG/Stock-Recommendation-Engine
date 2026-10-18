"""Current live-universe reconciliation for official filing acquisition.

The historical Phase 2A research universe is intentionally frozen at 186
symbols.  Production may use a newer universe, so recovery must reconcile the
actual live snapshot without rewriting that frozen research contract.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Iterable

from .core import dedupe_events, normalize_symbol


def symbols_from_live_snapshot(snapshot: dict) -> list[str]:
    if not isinstance(snapshot, dict):
        raise ValueError("LIVE_SNAPSHOT_INVALID")
    candidates = snapshot.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("LIVE_SNAPSHOT_CANDIDATES_REQUIRED")
    symbols = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("LIVE_SNAPSHOT_CANDIDATE_INVALID")
        symbol = candidate.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("LIVE_SNAPSHOT_SYMBOL_REQUIRED")
        symbols.append(normalize_symbol(symbol))
    if len(symbols) != len(set(symbols)):
        raise ValueError("LIVE_SNAPSHOT_DUPLICATE_SYMBOL")
    return symbols


def _valid_official_event(event: object) -> bool:
    """Conservative eligibility for *coverage counts*, not filing authentication."""
    if not isinstance(event, dict):
        return False
    if str(event.get("source_exchange") or "").strip().upper() not in {"NSE", "BSE"}:
        return False
    try:
        normalize_symbol(event.get("symbol"))
        date.fromisoformat(str(event.get("quarter_end") or ""))
        if str(event.get("reporting_basis") or "").strip().upper() not in {"STANDALONE", "CONSOLIDATED"}:
            return False
        if str(event.get("submission_type") or "").strip().upper() not in {"ORIGINAL", "REVISED"}:
            return False
        timestamps = []
        for field in ("publication_ts", "availability_ts"):
            raw = event.get(field)
            if not isinstance(raw, str):
                return False
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if ts.tzinfo is None or ts.utcoffset() is None:
                return False
            timestamps.append(ts)
        if timestamps[1] < timestamps[0]:
            return False
    except (ValueError, TypeError, OverflowError):
        return False
    return True


def symbols_with_events(events: Iterable[dict]) -> set[str]:
    result = set()
    for event in events:
        if _valid_official_event(event):
            result.add(normalize_symbol(event["symbol"]))
    return result


def acquisition_gap(symbols: Iterable[str], events: Iterable[dict]) -> list[str]:
    requested = {normalize_symbol(symbol) for symbol in symbols}
    covered = symbols_with_events(events)
    return sorted(requested - covered)


def merge_official_events(existing: Iterable[dict], recovered: Iterable[dict]) -> list[dict]:
    """Merge immutable filing events while preserving originals and revisions."""
    return dedupe_events([*existing, *recovered])


def recovery_summary(*, symbols: Iterable[str], existing: Iterable[dict], recovered: Iterable[dict]) -> dict:
    requested = sorted({normalize_symbol(symbol) for symbol in symbols})
    old = list(existing)
    new = list(recovered)
    merged = merge_official_events(old, new)
    before = symbols_with_events(old)
    after = symbols_with_events(merged)
    recovered_symbols = sorted((after - before) & set(requested))
    event_sources = Counter(str(row.get("source_exchange") or "UNKNOWN") if isinstance(row, dict) else "INVALID_EVENT" for row in new)
    return {
        "artifact_type": "CURRENT_LIVE_UNIVERSE_OFFICIAL_FILING_RECOVERY_V1",
        "authority": "SHADOW_ONLY",
        "target_symbol_count": len(requested),
        "covered_before": len(set(requested) & before),
        "covered_after": len(set(requested) & after),
        "missing_before": sorted(set(requested) - before),
        "missing_after": sorted(set(requested) - after),
        "recovered_symbols": recovered_symbols,
        "recovered_event_count": len(new),
        "recovered_event_source_counts": dict(sorted(event_sources.items())),
        "frozen_historical_universe_changed": False,
        "production_model_changed": False,
        "automatic_yfinance_fallback": False,
    }
