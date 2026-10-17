"""Current live-universe reconciliation for official filing acquisition.

The historical Phase 2A research universe is intentionally frozen at 186
symbols.  Production may use a newer universe, so recovery must reconcile the
actual live snapshot without rewriting that frozen research contract.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from .core import dedupe_events, normalize_symbol


def symbols_from_live_snapshot(snapshot: dict) -> list[str]:
    candidates = snapshot.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("LIVE_SNAPSHOT_CANDIDATES_REQUIRED")
    symbols = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("LIVE_SNAPSHOT_CANDIDATE_INVALID")
        symbols.append(normalize_symbol(candidate.get("symbol")))
    if len(symbols) != len(set(symbols)):
        raise ValueError("LIVE_SNAPSHOT_DUPLICATE_SYMBOL")
    return symbols


def symbols_with_events(events: Iterable[dict]) -> set[str]:
    result = set()
    for event in events:
        result.add(normalize_symbol(event.get("symbol")))
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
    event_sources = Counter(str(row.get("source_exchange") or "UNKNOWN") for row in new)
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
