"""Deterministic NIFTY 500 PIT reconstruction and free-official data controls.

The module has no trading, recommendation, broker, model-training, or promotion
authority.  It accepts only explicit official evidence and fails closed whenever
coverage, identity, chronology, or normalization semantics are incomplete.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime
from typing import Iterable
from urllib.parse import urlparse

OFFICIAL_HOSTS = {
    "www.niftyindices.com", "niftyindices.com", "www.nseindia.com",
    "nseindia.com", "nsearchives.nseindia.com", "mcp.nseindia.in",
    "www.sebi.gov.in", "sebi.gov.in", "www.incometaxindia.gov.in",
    "incometaxindia.gov.in",
}
AUTHORITY = "SHADOW_ONLY"
PARSER_VERSION = "NIFTY500_FREE_OFFICIAL_V1"


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_official_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS:
        raise ValueError("OFFICIAL_SOURCE_REQUIRED")
    return url


def _day(value: str, field: str = "date") -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except Exception as exc:
        raise ValueError(f"INVALID_{field.upper()}") from exc


def parse_current_anchor(content: bytes, *, source_url: str, retrieved_at: str,
                         as_of_date: str) -> dict:
    require_official_url(source_url)
    _day(as_of_date, "as_of_date")
    try:
        datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError("INVALID_RETRIEVAL_TIMESTAMP") from exc
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = {"Company Name", "Industry", "Symbol", "Series", "ISIN Code"}
    if set(reader.fieldnames or []) != required:
        raise ValueError("UNSUPPORTED_NIFTY500_ANCHOR_SCHEMA")
    rows, symbols, isins = [], set(), set()
    for raw in reader:
        row = {k: str(v or "").strip() for k, v in raw.items()}
        if not row["Company Name"] or not row["Symbol"]:
            raise ValueError("ANCHOR_IDENTITY_INCOMPLETE")
        if row["Symbol"] in symbols:
            raise ValueError("DUPLICATE_ANCHOR_SYMBOL")
        if row["ISIN Code"] and row["ISIN Code"] in isins:
            raise ValueError("DUPLICATE_ANCHOR_ISIN")
        symbols.add(row["Symbol"])
        if row["ISIN Code"]:
            isins.add(row["ISIN Code"])
        rows.append({
            "company_name": row["Company Name"], "industry": row["Industry"],
            "symbol": row["Symbol"], "series": row["Series"],
            "isin": row["ISIN Code"] or None,
        })
    if not 450 <= len(rows) <= 550:
        raise ValueError("ANCHOR_COUNT_OUTSIDE_GOVERNANCE_RANGE")
    rows.sort(key=lambda x: (x["isin"] or "", x["symbol"]))
    return {
        "artifact_type": "NIFTY500_CURRENT_ANCHOR_V1",
        "as_of_date": as_of_date, "as_of_semantics": "LATEST_COMPLETED_NSE_SESSION_AT_RETRIEVAL",
        "constituent_count": len(rows), "missing_isin_count": sum(x["isin"] is None for x in rows),
        "source_url": source_url, "retrieved_at": retrieved_at,
        "source_sha256": bytes_hash(content), "parser_version": PARSER_VERSION,
        "source_classification": "OFFICIAL_PUBLIC_VERIFIED", "constituents": rows,
        "authority": AUTHORITY,
    }


_PRESS_RE = re.compile(
    r'<div class="pressItem" data-date="([^"]+)"[\s\S]*?'
    r'<a href=[\'\"]([^\'\"]+\.pdf)[\'\"][^>]*>([\s\S]*?)</a>', re.I,
)


def parse_press_archive(content: bytes, *, source_url: str,
                        start_date: str, end_date: str) -> list[dict]:
    require_official_url(source_url)
    start, end = _day(start_date), _day(end_date)
    out = []
    for raw_date, href, raw_title in _PRESS_RE.findall(content.decode("utf-8", errors="ignore")):
        try:
            release_date = datetime.strptime(raw_date, "%b %d, %Y").date().isoformat()
        except ValueError:
            continue
        if not start <= release_date <= end:
            continue
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_title)).strip()
        title = title.replace("&amp;", "&").replace("&#39;", "'")
        url = "https://www.niftyindices.com" + href if href.startswith("/") else href
        require_official_url(url)
        out.append({"release_date": release_date, "title": title, "source_url": url})
    seen = set()
    for item in out:
        if item["source_url"] in seen:
            raise ValueError("DUPLICATE_PRESS_RELEASE")
        seen.add(item["source_url"])
    return sorted(out, key=lambda x: (x["release_date"], x["source_url"]))


def equity_maintenance_candidates(releases: list[dict]) -> list[dict]:
    include = re.compile(r"replacement|reconstitution|index maintenance|corporate (?:action )?adjustment|exclusion|scheme|merger|demerger|suspension|delisting", re.I)
    exclude = re.compile(r"fixed income|SME Emerge|Nifty IPO", re.I)
    return [x for x in releases if include.search(x["title"]) and not exclude.search(x["title"])]


def expected_reconstitution_cycles(start_date: str, end_date: str) -> list[dict]:
    start, end = date.fromisoformat(_day(start_date)), date.fromisoformat(_day(end_date))
    cycles = []
    for year in range(start.year, end.year + 1):
        for month, label in ((3, "MARCH"), (9, "SEPTEMBER")):
            marker = date(year, month, 1)
            if start <= marker <= end:
                cycles.append({"cycle_id": f"{year}-{label}", "year": year, "cycle": label,
                               "expected": True, "governance_basis": "OFFICIAL_SEMIANNUAL_REVIEW_SCHEDULE"})
    return cycles


def _nifty500_section(text: str) -> str | None:
    match = re.search(r"(?im)^\s*(?:\d+\)|[a-z]\))?\s*NIFTY\s*500\s*$", text)
    if not match:
        return None
    rest = text[match.end():]
    end = re.search(r"(?im)^\s*(?:\d+\)|[a-z]\))\s*Nifty\s+(?!500\b)", rest)
    return rest[:end.start()] if end else rest[:8000]


def _table_rows(block: str) -> list[dict]:
    rows = []
    lines = block.splitlines()
    normalized = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^\s*\d+\s+", line) and not re.match(r"^\s*\d+\s+.+?\s+[A-Z0-9][A-Z0-9&.\-]{1,}\s*$", line):
            following = index + 1
            while following < len(lines) and not lines[following].strip():
                following += 1
            if following < len(lines) and not re.match(r"^\s*\d+\s+", lines[following]):
                line = line.rstrip() + " " + lines[following].strip()
                index = following
        normalized.append(line)
        index += 1
    for line in normalized:
        match = re.match(r"^\s*(\d+)\s+(.+?)\s+([A-Z0-9][A-Z0-9&.\-]{1,})\s*$", line)
        if match:
            rows.append({"company_name": match.group(2).strip(), "symbol": match.group(3).strip()})
    return rows


def parse_nifty500_replacement(text: str) -> dict:
    section = _nifty500_section(text)
    if section is None:
        raise ValueError("NIFTY500_SECTION_NOT_FOUND")
    split = re.split(r"(?i)The following compan(?:y|ies) (?:are|is) being (excluded|included):", section)
    buckets = {"excluded": [], "included": []}
    for i in range(1, len(split), 2):
        buckets[split[i].lower()].extend(_table_rows(split[i + 1]))
    if not buckets["excluded"] and not buckets["included"]:
        raise ValueError("NIFTY500_TRANSITION_NOT_PARSED")
    if len({x["symbol"] for x in buckets["excluded"]}) != len(buckets["excluded"]):
        raise ValueError("DUPLICATE_EVENT_SYMBOL")
    if len({x["symbol"] for x in buckets["included"]}) != len(buckets["included"]):
        raise ValueError("DUPLICATE_EVENT_SYMBOL")
    return buckets


def make_change_event(*, event_id: str, announcement_date: str, effective_date: str,
                      source_url: str, source_sha256: str, reason: str,
                      event_type: str, excluded: list[dict], included: list[dict],
                      scheduled_cycle: str | None = None) -> dict:
    require_official_url(source_url)
    announced, effective = _day(announcement_date, "announcement_date"), _day(effective_date, "effective_date")
    if effective < announced:
        raise ValueError("EVENT_CHRONOLOGY_INVALID")
    if len(source_sha256) != 64:
        raise ValueError("SOURCE_HASH_INVALID")
    if not excluded and not included:
        raise ValueError("EMPTY_CONSTITUENT_EVENT")
    symbols = [x["symbol"] for x in excluded + included]
    if len(symbols) != len(set(symbols)):
        raise ValueError("AMBIGUOUS_EVENT_IDENTITY")
    return {
        "event_id": event_id, "announcement_date": announced, "effective_date": effective,
        "excluded": excluded, "included": included, "source_url": source_url,
        "source_sha256": source_sha256, "reason": reason, "event_type": event_type,
        "scheduled_cycle": scheduled_cycle, "source_classification": "OFFICIAL_PUBLIC_VERIFIED",
        "identity_basis": "OFFICIAL_SYMBOL_PLUS_EFFECTIVE_PERIOD",
    }


def backward_reconstruct(anchor: dict, events: list[dict]) -> dict:
    members = {x["symbol"]: dict(x) for x in anchor["constituents"]}
    snapshots = [{"as_of_date": anchor["as_of_date"], "constituents": sorted(members), "boundary": "CURRENT_ANCHOR"}]
    gaps = []
    for event in sorted(events, key=lambda x: (x["effective_date"], x["event_id"]), reverse=True):
        missing_added = sorted(x["symbol"] for x in event["included"] if x["symbol"] not in members)
        conflicting_restores = sorted(x["symbol"] for x in event["excluded"] if x["symbol"] in members)
        if missing_added or conflicting_restores:
            gaps.append({"event_id": event["event_id"], "missing_current_inclusion": missing_added,
                         "conflicting_restore": conflicting_restores, "status": "IDENTITY_RESOLUTION_REQUIRED"})
            break
        for item in event["included"]:
            members.pop(item["symbol"])
        for item in event["excluded"]:
            members[item["symbol"]] = {"company_name": item["company_name"], "symbol": item["symbol"],
                                               "isin": item.get("isin"), "industry": None, "series": "EQ"}
        snapshot = {"as_of_date": event["effective_date"], "constituents": sorted(members),
                    "boundary": "IMMEDIATELY_BEFORE_EVENT", "reversed_event_id": event["event_id"]}
        snapshot["snapshot_sha256"] = canonical_hash(snapshot)
        snapshots.append(snapshot)
    payload = {"artifact_type": "NIFTY500_RECONSTRUCTED_PIT_MEMBERSHIP_V1",
               "anchor_sha256": canonical_hash(anchor), "change_ledger_sha256": canonical_hash(events),
               "snapshots": snapshots, "gaps": gaps,
               "status": "COMPLETE_FOR_BOUNDED_PERIOD" if not gaps else "PARTIAL_WITH_GAPS",
               "authority": AUTHORITY}
    payload["artifact_sha256"] = canonical_hash(payload)
    return payload


def reconstruction_completeness(cycles: list[dict], cycle_events: dict[str, dict], *,
                                inspected_releases: int, relevant_releases: int,
                                unresolved_events: list[dict]) -> dict:
    checks = []
    for cycle in cycles:
        event = cycle_events.get(cycle["cycle_id"])
        checks.append({**cycle, "announcement_located": event is not None,
                       "parsed": bool(event), "effective_date_known": bool(event and event.get("effective_date")),
                       "additions_removals_balanced": bool(event and len(event["included"]) == len(event["excluded"])),
                       "identity_complete": bool(event and all(x.get("symbol") for x in event["included"] + event["excluded"])),
                       "transition_applied": bool(event)})
    complete = all(all(x[k] for k in ("announcement_located", "parsed", "effective_date_known", "additions_removals_balanced", "identity_complete", "transition_applied")) for x in checks)
    status = "COMPLETE_FOR_BOUNDED_PERIOD" if complete and not unresolved_events else ("PARTIAL_WITH_GAPS" if checks else "INSUFFICIENT")
    return {"artifact_type": "NIFTY500_RECONSTRUCTION_COMPLETENESS_V1", "cycles": checks,
            "expected_cycle_count": len(checks), "located_cycle_count": sum(x["announcement_located"] for x in checks),
            "inspected_equity_maintenance_releases": inspected_releases,
            "relevant_nifty500_releases": relevant_releases, "unresolved_events": unresolved_events,
            "status": status, "authority": AUTHORITY}


def validate_market_rows(rows: list[dict], *, source_url: str) -> dict:
    require_official_url(source_url)
    seen, dates, symbols = set(), set(), set()
    for row in rows:
        key = (_day(row["date"]), str(row["symbol"]).upper())
        if key in seen:
            raise ValueError("DUPLICATE_SECURITY_SESSION")
        seen.add(key); dates.add(key[0]); symbols.add(key[1])
        o, h, low, close = (float(row[x]) for x in ("open", "high", "low", "close"))
        if min(o, h, low, close) < 0 or h < max(o, low, close) or low > min(o, h, close):
            raise ValueError("INVALID_OHLC")
        if int(row["volume"]) < 0:
            raise ValueError("INVALID_VOLUME")
    return {"row_count": len(rows), "session_count": len(dates), "security_count": len(symbols),
            "first_date": min(dates) if dates else None, "last_date": max(dates) if dates else None,
            "ohlc_complete": all(all(k in x and x[k] is not None for k in ("open", "high", "low", "close")) for x in rows),
            "volume_complete": all("volume" in x and x["volume"] is not None for x in rows),
            "turnover_complete": all(x.get("totalTradedValue") is not None for x in rows),
            "source_url": source_url, "source_classification": "OFFICIAL_PUBLIC_VERIFIED"}


def pit_normalize_price(raw_price: float, price_date: str, feature_date: str,
                        actions: list[dict]) -> float:
    pday, fday = _day(price_date, "price_date"), _day(feature_date, "feature_date")
    if pday > fday:
        raise ValueError("FUTURE_PRICE_NOT_ALLOWED")
    result = float(raw_price)
    for action in sorted(actions, key=lambda x: x["effective_date"]):
        effective = _day(action["effective_date"], "effective_date")
        known = _day(action["known_date"], "known_date")
        if known > fday or effective > fday:
            continue
        if pday < effective:
            factor = action.get("adjustment_factor")
            if factor is None or float(factor) <= 0:
                raise ValueError("CORPORATE_ACTION_TERMS_UNKNOWN")
            result *= float(factor)
    return round(result, 10)


def resolve_identity(periods: list[dict], *, symbol: str, as_of_date: str) -> dict | None:
    day = _day(as_of_date, "as_of_date")
    matches = [x for x in periods if x["symbol"] == symbol and x["effective_from"] <= day <= (x.get("effective_to") or "9999-12-31")]
    if len(matches) > 1:
        raise ValueError("AMBIGUOUS_SYMBOL_PERIOD")
    return matches[0] if matches else None


def feature_readiness(*, ohlc: bool, normalized_prices: bool, volume: bool,
                      turnover: bool, benchmark: bool) -> dict:
    families = {
        "technical": "PIT_SAFE" if ohlc else "NOT_READY",
        "momentum": "PIT_SAFE" if normalized_prices else "NOT_READY",
        "volatility": "PIT_SAFE" if normalized_prices and ohlc else "NOT_READY",
        "liquidity": "FULL_LIQUIDITY_AVAILABLE" if volume and turnover else ("VOLUME_LIQUIDITY_AVAILABLE" if volume else "NOT_READY"),
        "market_index": "PIT_SAFE" if benchmark else "NOT_READY",
        "fundamentals": "OPTIONAL_NOT_ACQUIRED",
        "stage6_events": "OPTIONAL_NOT_ACQUIRED",
    }
    required_ready = all(families[x] == "PIT_SAFE" for x in ("technical", "momentum", "volatility", "market_index")) and families["liquidity"] in {"VOLUME_LIQUIDITY_AVAILABLE", "FULL_LIQUIDITY_AVAILABLE"}
    return {"artifact_type": "FREE_OFFICIAL_FEATURE_PIT_READINESS_V1", "families": families,
            "minimal_required_profile_pit_safe": required_ready, "authority": AUTHORITY}


def readiness_v4(*, gates: dict[str, bool], period: dict | None, hashes: dict,
                 preserved_hashes: dict) -> dict:
    required = {"constituent_reconstruction", "pit_universe", "survivorship", "identity",
                "market_data", "price_adjustment", "execution_costs", "benchmark", "features", "governance"}
    if set(gates) != required:
        raise ValueError("V4_GATE_SET_INVALID")
    failed = sorted(k for k, value in gates.items() if not value)
    ready = not failed and bool(period)
    return {"artifact_type": "ADVANCED_RESEARCH_READINESS_V4",
            "profile": "FREE_OFFICIAL_INDEX_CONSTITUENT_PIT",
            "status": "READY_WITH_RESTRICTED_PERIOD" if ready else "NOT_READY",
            "gates": gates, "failed_gates": failed, "restricted_period": period if ready else None,
            "source_hashes": hashes, "preserved_readiness_hashes": preserved_hashes,
            "training_started": False, "challenger_trained": False, "model_promoted": False,
            "ml_authority": "NONE", "trading_authority": False, "authority": AUTHORITY}


def free_vs_paid_decision(v4: dict, *, remaining_blockers: list[dict]) -> dict:
    if v4["status"] == "READY_WITH_RESTRICTED_PERIOD":
        decision = "FREE_OFFICIAL_DATA_SUFFICIENT_FOR_RESTRICTED_PERIOD"
        minimum = None
    elif len(remaining_blockers) == 1:
        decision = "FREE_OFFICIAL_DATA_PARTIAL_BUT_ONE_GAP_REMAINS"
        minimum = remaining_blockers[0].get("minimum_product")
    else:
        decision = "LICENSED_DATA_REQUIRED_FOR_RESEARCH_READINESS"
        minimum = next((x.get("minimum_product") for x in remaining_blockers if x.get("minimum_product")), None)
    return {"artifact_type": "FREE_VS_PAID_DATA_DECISION_V1", "decision": decision,
            "remaining_blockers": remaining_blockers, "minimum_missing_product": minimum,
            "purchase_performed": False, "authority": AUTHORITY}


def tracked_runtime_artifacts(paths: Iterable[str]) -> list[str]:
    bad = re.compile(r"(?:\.sqlite3?$|\.db$|/raw/|\\raw\\|\.parquet$|__pycache__|\.pyc$)", re.I)
    return sorted(x for x in paths if bad.search(x))
