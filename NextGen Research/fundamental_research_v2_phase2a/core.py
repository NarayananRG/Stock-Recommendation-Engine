"""Deterministic controls for Fundamental Research V2 Phase 2A.

This lane only establishes point-in-time (PIT) filing history and continuity.
It has no model-training, recommendation, promotion, or trading authority.

The primary design rule is fail-closed: a filing may be used only when its
publication timestamp, reporting basis, identity and source provenance are
explicit. Revisions are retained as separate knowledge events; history is
never silently rewritten.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Iterable, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

AUTHORITY = "SHADOW_ONLY"
SOURCE_PRIORITY = ("NSE", "BSE")
TARGET_QUARTER_ENDS = (
    "2025-03-31",
    "2025-06-30",
    "2025-09-30",
    "2025-12-31",
    "2026-03-31",
    "2026-06-30",
)
OFFICIAL_FUNDAMENTAL_HOSTS = {
    "nseindia.com",
    "www.nseindia.com",
    "nsearchives.nseindia.com",
    "bseindia.com",
    "www.bseindia.com",
}
SYMBOL_ALIASES = {
    # Historical local research used both aliases. NSE's exchange symbol is M&M.
    "MANDM": "M&M",
    "M&M": "M&M",
}
IST = ZoneInfo("Asia/Kolkata")


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def require_official_fundamental_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_FUNDAMENTAL_HOSTS:
        raise ValueError("OFFICIAL_NSE_OR_BSE_SOURCE_REQUIRED")
    return url


def normalize_symbol(value: str) -> str:
    symbol = re.sub(r"\s+", "", str(value or "").strip().upper())
    if not symbol:
        raise ValueError("SYMBOL_REQUIRED")
    return SYMBOL_ALIASES.get(symbol, symbol)


def normalize_basis(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).upper().replace("NON-CONSOLIDATED", "STANDALONE")
    if text in {"CONSOLIDATED", "CONSOL"}:
        return "CONSOLIDATED"
    if text in {"STANDALONE", "NON CONSOLIDATED", "NONCONSOLIDATED"}:
        return "STANDALONE"
    raise ValueError("REPORTING_BASIS_REQUIRED")


def _parse_date(value: str, field: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field.upper()}_REQUIRED")
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"INVALID_{field.upper()}")


def _parse_ts(value: str | None, field: str) -> str | None:
    raw = str(value or "").strip()
    if not raw or raw == "-":
        return None
    parsed = None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%d-%b-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError(f"INVALID_{field.upper()}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    else:
        parsed = parsed.astimezone(IST)
    return parsed.isoformat()


def _first(row: dict, *keys: str) -> str | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return str(row[key])
    return None


def _submission(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).upper()
    if text in {"ORIGINAL", "ORIGINAL SUBMISSION"}:
        return "ORIGINAL"
    if text in {"REVISION", "REVISED", "RESUBMISSION", "RE-SUBMISSION"}:
        return "REVISION"
    raise ValueError("UNSUPPORTED_SUBMISSION_TYPE")


def _accounting_family(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip()).upper()
    return text or None


def build_filing_event(row: dict, *, source_url: str, source_sha256: str, source_exchange: str = "NSE") -> dict:
    """Normalize one exchange filing row into an immutable PIT knowledge event."""
    require_official_fundamental_url(source_url)
    exchange = str(source_exchange or "").strip().upper()
    if exchange not in SOURCE_PRIORITY:
        raise ValueError("UNSUPPORTED_OFFICIAL_EXCHANGE")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(source_sha256 or "")):
        raise ValueError("SOURCE_SHA256_REQUIRED")

    symbol = normalize_symbol(_first(row, "Symbol", "symbol", "TckrSymb") or "")
    quarter_end = _parse_date(_first(row, "Quarter End Date", "quarter_end", "Period Ended") or "", "quarter_end")
    submission = _submission(_first(row, "Type of Submission", "submission_type") or "")
    basis = normalize_basis(_first(row, "CONSOLIDATED / Standalone", "Consolidated / Standalone", "basis") or "")
    broadcast_ts = _parse_ts(
        _first(row, "BROADCAST DATE/TIME", "Broadcast Date/Time", "broadcast_ts"),
        "broadcast_ts",
    )
    revised_ts = _parse_ts(
        _first(row, "Revised DATE/TIME", "Revised Date/Time", "revised_ts"),
        "revised_ts",
    )
    creation_ts = _parse_ts(
        _first(row, "Creation DATE/TIME", "Creation Date/Time", "creation_ts"),
        "creation_ts",
    )
    if submission == "ORIGINAL":
        if broadcast_ts is None:
            raise ValueError("ORIGINAL_BROADCAST_TIMESTAMP_REQUIRED")
        publication_ts = broadcast_ts
    else:
        if revised_ts is None:
            raise ValueError("REVISION_TIMESTAMP_REQUIRED")
        publication_ts = revised_ts

    # NSE creation_Date is the exchange dissemination/creation time and is
    # normally a few seconds after broadcast_Date/revised_Date. For PIT
    # availability, prefer that later public-facing timestamp when present.
    availability_ts = creation_ts or publication_ts

    if datetime.fromisoformat(publication_ts).date() < date.fromisoformat(quarter_end):
        raise ValueError("PUBLICATION_PRECEDES_QUARTER_END")

    event = {
        "artifact_type": "FUNDAMENTAL_PIT_FILING_EVENT_V2A",
        "symbol": symbol,
        "company_name": (_first(row, "Company Name", "company_name") or "").strip() or None,
        "quarter_end": quarter_end,
        "submission_type": submission,
        "reporting_basis": basis,
        "audited_status": (_first(row, "Audited / Unaudited", "audited_status") or "").strip().upper() or None,
        "accounting_family": _accounting_family(_first(row, "IND AS/ NON IND AS", "Accounting Standard", "accounting_family")),
        "broadcast_ts": broadcast_ts,
        "revised_ts": revised_ts,
        "creation_ts": creation_ts,
        "publication_ts": publication_ts,
        "availability_ts": availability_ts,
        "revision_remarks": (_first(row, "Revision Remarks", "revision_remarks") or "").strip() or None,
        "source_exchange": exchange,
        "source_url": source_url,
        "source_sha256": source_sha256.lower(),
        "authority": AUTHORITY,
    }
    event["event_id"] = canonical_hash({k: event[k] for k in (
        "symbol", "quarter_end", "submission_type", "reporting_basis",
        "publication_ts", "availability_ts", "source_exchange", "source_sha256",
    )})
    return event


def dedupe_events(events: Iterable[dict]) -> list[dict]:
    """Deduplicate exact events while detecting alias-created semantic duplicates."""
    by_id: dict[str, dict] = {}
    semantic: dict[tuple, str] = {}
    for raw in events:
        item = dict(raw)
        item["symbol"] = normalize_symbol(item["symbol"])
        event_id = item.get("event_id") or canonical_hash(item)
        item["event_id"] = event_id
        key = (
            item["symbol"], item["quarter_end"], item["submission_type"],
            item["reporting_basis"], item["publication_ts"], item.get("source_exchange"),
        )
        if key in semantic and semantic[key] != event_id:
            raise ValueError("SEMANTIC_DUPLICATE_FILING_EVENT")
        semantic[key] = event_id
        by_id.setdefault(event_id, item)
    return sorted(by_id.values(), key=lambda x: (x["publication_ts"], x["symbol"], x["quarter_end"], x["event_id"]))


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(IST)


def select_latest_available_filing(
    events: Sequence[dict], *, symbol: str, decision_ts: str, reporting_basis: str | None = None
) -> dict | None:
    """Return the latest period/revision actually known by the decision timestamp."""
    sym = normalize_symbol(symbol)
    cutoff = _dt(decision_ts)
    basis = normalize_basis(reporting_basis) if reporting_basis else None
    eligible = []
    for item in events:
        if normalize_symbol(item["symbol"]) != sym:
            continue
        if basis and normalize_basis(item["reporting_basis"]) != basis:
            continue
        available_at = item.get("availability_ts") or item["publication_ts"]
        if _dt(available_at) <= cutoff:
            eligible.append(item)
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda x: (
            x["quarter_end"],
            _dt(x.get("availability_ts") or x["publication_ts"]),
            x.get("event_id", ""),
        ),
    )


def first_decision_after_publication(event: dict, decision_timestamps: Sequence[str]) -> str | None:
    publication = _dt(event.get("availability_ts") or event["publication_ts"])
    later = sorted(_dt(x) for x in decision_timestamps if _dt(x) > publication)
    return later[0].isoformat() if later else None


def growth_continuity(prior: dict, current: dict, *, explicit_basis_bridge: bool = False) -> dict:
    """Decide whether growth may be computed between two filings."""
    reasons: list[str] = []
    if normalize_symbol(prior["symbol"]) != normalize_symbol(current["symbol"]):
        reasons.append("SYMBOL_MISMATCH")
    if current["quarter_end"] <= prior["quarter_end"]:
        reasons.append("NON_FORWARD_PERIOD")
    prior_basis = normalize_basis(prior["reporting_basis"])
    current_basis = normalize_basis(current["reporting_basis"])
    if prior_basis != current_basis and not explicit_basis_bridge:
        reasons.append("REPORTING_BASIS_SWITCH")
    prior_family = _accounting_family(prior.get("accounting_family"))
    current_family = _accounting_family(current.get("accounting_family"))
    if prior_family and current_family and prior_family != current_family:
        reasons.append("ACCOUNTING_FAMILY_SWITCH")
    return {
        "allowed": not reasons,
        "reasons": reasons,
        "prior_quarter_end": prior["quarter_end"],
        "current_quarter_end": current["quarter_end"],
        "authority": AUTHORITY,
    }


def publication_age_bucket(decisions_since_publication: int) -> str:
    n = int(decisions_since_publication)
    if n < 0:
        raise ValueError("NEGATIVE_EVENT_AGE")
    if n == 0:
        return "EVENT_DECISION_0"
    if n <= 5:
        return "DECISIONS_1_5"
    if n <= 20:
        return "DECISIONS_6_20"
    if n <= 63:
        return "DECISIONS_21_63"
    return "DECISIONS_64_PLUS"


def coverage_audit(events: Sequence[dict], *, target_symbols: Sequence[str]) -> dict:
    canonical_targets = sorted({normalize_symbol(x) for x in target_symbols})
    normalized = dedupe_events(events)
    period_symbols = {
        period: sorted({x["symbol"] for x in normalized if x["quarter_end"] == period})
        for period in TARGET_QUARTER_ENDS
    }
    period_coverage = {
        period: (len(set(symbols) & set(canonical_targets)) / len(canonical_targets) if canonical_targets else 0.0)
        for period, symbols in period_symbols.items()
    }
    revisions = [x for x in normalized if x["submission_type"] == "REVISION"]
    return {
        "artifact_type": "FUNDAMENTAL_PIT_COVERAGE_AUDIT_V2A",
        "target_symbol_count": len(canonical_targets),
        "event_count": len(normalized),
        "target_quarter_coverage": period_coverage,
        "covered_target_quarters": sum(v > 0 for v in period_coverage.values()),
        "all_target_quarters_present": all(v > 0 for v in period_coverage.values()),
        "revision_event_count": len(revisions),
        "original_and_revision_events_preserved": bool(revisions) or True,
        "authority": AUTHORITY,
    }


def phase2a_readiness(*, coverage: dict, timestamp_integrity: bool, continuity_audited: bool,
                      parser_breadth_audited: bool, source_manifest_complete: bool) -> dict:
    gates = {
        "current_pit_quarter_coverage": bool(coverage.get("all_target_quarters_present")),
        "timestamp_integrity": bool(timestamp_integrity),
        "continuity_audited": bool(continuity_audited),
        "parser_breadth_audited": bool(parser_breadth_audited),
        "source_manifest_complete": bool(source_manifest_complete),
    }
    failed = sorted(k for k, ok in gates.items() if not ok)
    return {
        "artifact_type": "FUNDAMENTAL_RESEARCH_V2_PHASE2A_READINESS_V1",
        "status": "READY_FOR_EVENT_DECAY_RESEARCH" if not failed else "NOT_READY",
        "gates": gates,
        "failed_gates": failed,
        "model_training_started": False,
        "production_model_changed": False,
        "promotion_allowed": False,
        "authority": AUTHORITY,
    }
