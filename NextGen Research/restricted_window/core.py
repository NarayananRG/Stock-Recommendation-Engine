"""Fail-closed controls for the free-official 2024-2026 research audit.

This module has no model-training, recommendation, trading, broker, or
promotion authority.  It parses already acquired official public evidence and
produces deterministic research-governance classifications only.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta
from typing import Iterable

AUTHORITY = "SHADOW_ONLY"
TARGET_START = "2024-10-01"
TARGET_END = "2026-10-01"
DECISION_STATES = {
    "FREE_OFFICIAL_DATA_SUFFICIENT",
    "FREE_OFFICIAL_DATA_SUFFICIENT_FOR_RESTRICTED_PERIOD",
    "FREE_OFFICIAL_RECONSTRUCTION_INCOMPLETE",
    "FREE_OFFICIAL_SOURCE_ACCESS_BLOCKED",
    "LICENSED_DATA_REQUIRED_FOR_RESEARCH_READINESS",
}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def parse_effective_date(text: str) -> str | None:
    """Parse official effective-date prose, including w.e.f. variants."""
    month = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    patterns = [
        rf"(?:w\s*\.\s*e\s*\.\s*f\s*\.?|effective\s+from)\s*:?-?\s*({month}\s+\d{{1,2}}(?:st|nd|rd|th)?\s*,?\s*\d{{4}})",
        rf"(?:w\s*\.\s*e\s*\.\s*f\s*\.?|effective\s+from)\s*:?-?\s*(\d{{1,2}}(?:st|nd|rd|th)?\s+{month}\s*,?\s*\d{{4}})",
        rf"effective\s+from\s+(\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{4}})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        raw = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", match.group(1), flags=re.I)
        raw = re.sub(r"\s+", " ", raw.replace(",", " ")).strip()
        for fmt in ("%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                pass
    return None


def free_vs_paid_decision_v2(*, ready: bool, unrestricted: bool = False,
                             blockers: list[dict]) -> dict:
    """Apply evidence-based free-vs-paid semantics; blocker count is irrelevant."""
    if ready:
        decision = "FREE_OFFICIAL_DATA_SUFFICIENT" if unrestricted else "FREE_OFFICIAL_DATA_SUFFICIENT_FOR_RESTRICTED_PERIOD"
    elif any(not item.get("free_routes_exhausted", False) for item in blockers):
        decision = "FREE_OFFICIAL_RECONSTRUCTION_INCOMPLETE"
    elif any(item.get("source_access_blocked", False) for item in blockers):
        decision = "FREE_OFFICIAL_SOURCE_ACCESS_BLOCKED"
    elif blockers and all(item.get("licensed_only_proven", False) for item in blockers):
        decision = "LICENSED_DATA_REQUIRED_FOR_RESEARCH_READINESS"
    else:
        decision = "FREE_OFFICIAL_RECONSTRUCTION_INCOMPLETE"
    if decision not in DECISION_STATES:
        raise AssertionError("INVALID_DECISION_STATE")
    return {
        "artifact_type": "FREE_VS_PAID_DATA_DECISION_V2",
        "decision": decision,
        "remaining_blockers": blockers,
        "blocker_count_not_used_as_paid_rule": True,
        "purchase_performed": False,
        "authority": AUTHORITY,
    }


def parse_udiff_csv(content: bytes, *, expected_date: str | None = None,
                    strict_ohlc: bool = True) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = {"TradDt", "FinInstrmTp", "ISIN", "TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol", "TtlTrfVal", "TtlNbOfTxsExctd"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError("UNSUPPORTED_UDIFF_SCHEMA")
    rows, seen = [], set()
    for raw in reader:
        day = raw["TradDt"].strip()
        if expected_date and day != expected_date:
            raise ValueError("SESSION_DATE_MISMATCH")
        symbol, series = raw["TckrSymb"].strip(), raw["SctySrs"].strip()
        key = (day, symbol, series, raw["ISIN"].strip())
        if key in seen:
            raise ValueError("DUPLICATE_SECURITY_SESSION")
        seen.add(key)
        values = [float(raw[x] or 0) for x in ("OpnPric", "HghPric", "LwPric", "ClsPric")]
        opn, high, low, close = values
        ohlc_valid = not (min(values) < 0 or high < max(opn, low, close) or low > min(opn, high, close))
        if strict_ohlc and not ohlc_valid:
            raise ValueError("INVALID_OHLC")
        volume = int(float(raw["TtlTradgVol"] or 0))
        turnover = float(raw["TtlTrfVal"] or 0)
        trades = int(float(raw["TtlNbOfTxsExctd"] or 0))
        if volume < 0 or turnover < 0 or trades < 0:
            raise ValueError("INVALID_ACTIVITY")
        rows.append({
            "date": day, "instrument_type": raw["FinInstrmTp"].strip(),
            "isin": raw["ISIN"].strip() or None, "symbol": symbol,
            "series": series, "open": opn, "high": high, "low": low,
            "close": close, "volume": volume, "turnover": turnover,
            "trades": trades, "ohlc_valid": ohlc_valid,
        })
    return rows


def build_calendar(start: str, end: str, holidays: dict[str, str],
                   acquired_sessions: Iterable[str], special_sessions: Iterable[str]) -> dict:
    start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    acquired, special = set(acquired_sessions), set(special_sessions)
    sessions, weekends, excluded = [], [], []
    day = start_day
    while day <= end_day:
        iso = day.isoformat()
        if iso in special:
            sessions.append(iso)
        elif day.weekday() >= 5:
            weekends.append(iso)
        elif iso in holidays:
            excluded.append({"date": iso, "description": holidays[iso]})
        else:
            sessions.append(iso)
        day += timedelta(days=1)
    missing = sorted(set(sessions) - acquired)
    unexpected = sorted(acquired - set(sessions))
    return {
        "artifact_type": "NSE_RESTRICTED_TRADING_CALENDAR_V1",
        "start_date": start, "end_date": end,
        "trading_sessions": sessions, "expected_session_count": len(sessions),
        "weekend_exclusion_count": len(weekends), "official_holidays": excluded,
        "special_trading_sessions": sorted(special),
        "missing_acquired_sessions": missing, "unexpected_acquired_sessions": unexpected,
        "status": "COMPLETE_VERIFIED" if not missing and not unexpected else "INCOMPLETE",
        "source": "NSE_HOLIDAY_MASTER_PLUS_OFFICIAL_INDEX_AND_BHAVCOPY_CROSSCHECK",
        "authority": AUTHORITY,
    }


def parse_benchmark_payload(payloads: list[dict], index_name: str) -> list[dict]:
    rows = {}
    for payload in payloads:
        for raw in payload.get("data", []):
            if raw.get("EOD_INDEX_NAME") != index_name:
                raise ValueError("BENCHMARK_IDENTITY_MISMATCH")
            day = datetime.strptime(raw["EOD_TIMESTAMP"], "%d-%b-%Y").date().isoformat()
            row = {
                "date": day, "open": float(raw["EOD_OPEN_INDEX_VAL"]),
                "high": float(raw["EOD_HIGH_INDEX_VAL"]), "low": float(raw["EOD_LOW_INDEX_VAL"]),
                "close": float(raw["EOD_CLOSE_INDEX_VAL"]),
            }
            if row["high"] < max(row["open"], row["low"], row["close"]) or row["low"] > min(row["open"], row["high"], row["close"]):
                raise ValueError("INVALID_BENCHMARK_OHLC")
            if day in rows and rows[day] != row:
                raise ValueError("CONFLICTING_BENCHMARK_SESSION")
            rows[day] = row
    return [rows[x] for x in sorted(rows)]


def classify_corporate_action(subject: str) -> str:
    value = subject.lower()
    if "split" in value or "sub-division" in value or "sub division" in value:
        return "SPLIT"
    if "bonus" in value:
        return "BONUS"
    if "demerger" in value:
        return "DEMERGER"
    if "merger" in value or "amalgamation" in value:
        return "MERGER"
    if "rights" in value:
        return "RIGHTS"
    if "face value" in value:
        return "FACE_VALUE_ADJUSTMENT"
    if "dividend" in value:
        return "DIVIDEND"
    return "OTHER"


def split_or_bonus_factor(subject: str) -> float | None:
    kind = classify_corporate_action(subject)
    if kind == "BONUS":
        match = re.search(r"bonus\s+(\d+)\s*:\s*(\d+)", subject, re.I)
        if match:
            new, old = map(int, match.groups())
            return old / (old + new)
    if kind in {"SPLIT", "FACE_VALUE_ADJUSTMENT"}:
        match = re.search(r"(?:from|fv)\s*(?:rs\.?|re\.?)?\s*(\d+(?:\.\d+)?)\D+(?:to|into)\s*(?:rs\.?|re\.?)?\s*(\d+(?:\.\d+)?)", subject, re.I)
        if match:
            old, new = map(float, match.groups())
            if old > 0 and new > 0:
                return new / old
    return None


def apply_pit_adjustment(price: float, price_date: str, feature_date: str,
                         actions: list[dict]) -> float:
    if date.fromisoformat(price_date) > date.fromisoformat(feature_date):
        raise ValueError("FUTURE_PRICE_NOT_ALLOWED")
    value = float(price)
    for action in sorted(actions, key=lambda x: x["effective_date"]):
        if action["known_date"] > feature_date or action["effective_date"] > feature_date:
            continue
        if price_date < action["effective_date"]:
            factor = action.get("adjustment_factor")
            if factor is None or float(factor) <= 0:
                raise ValueError("MATERIAL_ACTION_TERMS_UNRESOLVED")
            value *= float(factor)
    return round(value, 10)


def readiness_v5(gates: dict[str, bool], period: dict | None,
                 preserved_hashes: dict[str, str]) -> dict:
    required = {"constituent_reconstruction", "identity", "survivorship", "market_data",
                "price_adjustment", "execution_costs", "benchmark", "features",
                "governance", "source_usage_rights"}
    if set(gates) != required:
        raise ValueError("V5_GATE_SET_INVALID")
    failed = sorted(key for key, value in gates.items() if not value)
    ready = not failed and period is not None
    return {
        "artifact_type": "ADVANCED_RESEARCH_READINESS_V5",
        "profile": "FREE_OFFICIAL_RESTRICTED_NIFTY500_PIT",
        "status": "READY_WITH_RESTRICTED_PERIOD" if ready else "NOT_READY",
        "gates": gates, "failed_gates": failed,
        "restricted_period": period if ready else None,
        "preserved_readiness_hashes": preserved_hashes,
        "training_started": False, "challenger_trained": False,
        "model_promoted": False, "trading_authority": False,
        "ml_authority": "NONE", "authority": AUTHORITY,
    }


def tracked_runtime_artifacts(paths: Iterable[str]) -> list[str]:
    bad = re.compile(r"(?:\.zip$|\.sqlite3?$|\.db$|\.parquet$|/raw/|\\raw\\|__pycache__|\.pyc$)", re.I)
    return sorted(path for path in paths if bad.search(path))
