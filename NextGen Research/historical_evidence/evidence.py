"""Deterministic offline evidence handling for the bounded 2016-2026 study.

No network client, model-training code, recommendation logic, or production
authority is present here.  Facts are accepted only with explicit provenance.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime
from pathlib import Path

from common import parse_date, parse_time, record, sha256

AUTHORITY = "RESEARCH_ONLY"
ELIGIBILITY = {
    "VERIFIED_ELIGIBLE", "VERIFIED_NOT_YET_LISTED", "VERIFIED_DELISTED",
    "UNKNOWN_HISTORICAL_ELIGIBILITY",
}


def _digest(content: bytes, expected: str | None) -> str:
    actual = hashlib.sha256(content).hexdigest()
    if expected and expected.lower() != actual:
        raise ValueError("SOURCE_HASH_MISMATCH")
    return actual


def _iso(value: str, label: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except Exception as exc:
        raise ValueError(f"INVALID_{label.upper()}") from exc


def parse_dated_security_snapshot(content: bytes, *, report_date: str,
                                  source_reference: str,
                                  source_hash: str | None = None) -> list[dict]:
    """Parse an exact-date NSE-style snapshot; observation date is mandatory."""
    report_date = _iso(report_date, "report_date")
    digest = _digest(content, source_hash)
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = {"SYMBOL", "NAME OF COMPANY", "SERIES", "DATE OF LISTING", "ISIN NUMBER"}
    if not reader.fieldnames or required - {x.strip() for x in reader.fieldnames}:
        raise ValueError("UNSUPPORTED_DATED_SECURITY_MASTER_STRUCTURE")
    rows = []
    for raw in reader:
        row = {str(k).strip(): str(v or "").strip() for k, v in raw.items()}
        if not row["SYMBOL"] or not row["ISIN NUMBER"]:
            raise ValueError("MISSING_OFFICIAL_SECURITY_IDENTITY")
        listing = datetime.strptime(row["DATE OF LISTING"], "%d-%b-%Y").date().isoformat()
        rows.append({
            "security_id": f"NSE:{row['ISIN NUMBER']}", "isin": row["ISIN NUMBER"],
            "symbol": row["SYMBOL"], "company_name": row["NAME OF COMPANY"],
            "series": row["SERIES"], "listing_date": listing,
            "snapshot_date": report_date, "status": "VERIFIED_AT_SNAPSHOT_DATE",
            "source_reference": source_reference, "source_file_sha256": digest,
            "authority_scope": AUTHORITY,
        })
    identities = [r["security_id"] for r in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("DUPLICATE_SECURITY_IDENTITY")
    return sorted(rows, key=lambda r: r["security_id"])


def classify_historical_eligibility(security: dict, query_date: str,
                                    exact_snapshot_ids: set[str] | None = None) -> str:
    """Classify conservatively; current presence is never backfilled."""
    day = parse_date(query_date)
    listing = parse_date(security.get("listing_date"))
    delisting = parse_date(security.get("delisting_date"))
    if listing and day < listing:
        return "VERIFIED_NOT_YET_LISTED"
    if delisting and day >= delisting:
        return "VERIFIED_DELISTED"
    if exact_snapshot_ids is not None and security.get("security_id") in exact_snapshot_ids:
        return "VERIFIED_ELIGIBLE"
    return "UNKNOWN_HISTORICAL_ELIGIBILITY"


def build_identity_history(rows: list[dict]) -> list[dict]:
    required = {"isin", "symbol", "effective_from", "source_reference", "source_file_sha256"}
    normalized = []
    for raw in rows:
        if required - raw.keys() or len(raw.get("source_file_sha256", "")) != 64:
            raise ValueError("IDENTITY_EVIDENCE_INCOMPLETE")
        row = dict(raw)
        row["effective_from"] = _iso(row["effective_from"], "effective_from")
        if row.get("effective_to"):
            row["effective_to"] = _iso(row["effective_to"], "effective_to")
            if row["effective_to"] < row["effective_from"]:
                raise ValueError("IDENTITY_PERIOD_INVALID")
        normalized.append(row)
    for i, left in enumerate(normalized):
        for right in normalized[i + 1:]:
            ls, le = left["effective_from"], left.get("effective_to") or "9999-12-31"
            rs, re = right["effective_from"], right.get("effective_to") or "9999-12-31"
            overlap = max(ls, rs) <= min(le, re)
            if overlap and left["symbol"] == right["symbol"] and left["isin"] != right["isin"]:
                raise ValueError("CONFLICTING_SYMBOL_IDENTITY")
            if overlap and left["isin"] == right["isin"] and left["symbol"] != right["symbol"]:
                raise ValueError("CONFLICTING_ISIN_SYMBOL_PERIOD")
    return sorted(normalized, key=lambda r: (r["isin"], r["effective_from"]))


def parse_index_change_events(content: bytes, *, source_reference: str,
                              source_hash: str | None = None) -> list[dict]:
    digest = _digest(content, source_hash)
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = {"index_id", "symbol", "isin", "change", "effective_date", "official_document_sha256"}
    if not reader.fieldnames or required - set(reader.fieldnames):
        raise ValueError("INDEX_CHANGE_STRUCTURE_INVALID")
    out = []
    for row in reader:
        if row["change"] not in {"ADD", "REMOVE"} or not row["isin"] or len(row["official_document_sha256"]) != 64:
            raise ValueError("INDEX_CHANGE_INVALID")
        out.append({**row, "effective_date": _iso(row["effective_date"], "effective_date"),
                    "source_reference": source_reference, "source_file_sha256": row["official_document_sha256"].lower(),
                    "normalized_fixture_sha256": digest,
                    "coverage_semantics": "CHANGE_EVENT_ONLY"})
    return sorted(out, key=lambda r: (r["effective_date"], r["index_id"], r["symbol"], r["change"]))


def index_membership_status(events: list[dict], *, index_id: str, isin: str,
                            query_date: str, snapshot_members: set[str] | None = None,
                            snapshot_date: str | None = None) -> str:
    day = _iso(query_date, "query_date")
    if snapshot_date == day and snapshot_members is not None:
        return "VERIFIED_AT_SNAPSHOT_DATE" if isin in snapshot_members else "VERIFIED_NOT_MEMBER_AT_SNAPSHOT_DATE"
    # Change notices without an anchored starting snapshot cannot prove continuous membership.
    if any(e["index_id"] == index_id and e["isin"] == isin and e["effective_date"] == day for e in events):
        return "VERIFIED_CHANGE_EVENT"
    return "UNKNOWN"


def parse_sector_evidence(content: bytes, *, snapshot_date: str,
                          source_reference: str, source_hash: str | None = None) -> list[dict]:
    digest = _digest(content, source_hash)
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = {"isin", "sector"}
    if not reader.fieldnames or required - set(reader.fieldnames):
        raise ValueError("SECTOR_EVIDENCE_STRUCTURE_INVALID")
    day = _iso(snapshot_date, "snapshot_date")
    return sorted([{"isin": r["isin"], "sector": r["sector"], "snapshot_date": day,
                    "status": "SNAPSHOT_ONLY", "source_reference": source_reference,
                    "source_file_sha256": digest} for r in reader if r["isin"] and r["sector"]],
                  key=lambda r: r["isin"])


def sector_status(rows: list[dict], isin: str, query_date: str) -> dict:
    day = _iso(query_date, "query_date")
    match = [r for r in rows if r["isin"] == isin and r["snapshot_date"] == day]
    return {"status": "SNAPSHOT_ONLY", "sector": match[0]["sector"]} if len(match) == 1 else {"status": "UNKNOWN", "sector": None}


def parse_corporate_actions(content: bytes, *, source_reference: str,
                            retrieved_at: str, source_hash: str | None = None) -> list[dict]:
    digest = _digest(content, source_hash)
    parse_time(retrieved_at)
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = {"SYMBOL", "SERIES", "SECURITY", "RECORD_DATE", "EX_DATE", "PURPOSE", "ISIN", "STATUS"}
    if not reader.fieldnames or required - set(reader.fieldnames):
        raise ValueError("CORPORATE_ACTION_STRUCTURE_INVALID")
    out = []
    for row in reader:
        if not row["ISIN"] or not row["EX_DATE"] or row["STATUS"] not in {"ACTIVE", "CANCELLED"}:
            raise ValueError("CORPORATE_ACTION_RECORD_INVALID")
        out.append({
            "security_id": f"NSE:{row['ISIN']}", "isin": row["ISIN"], "symbol": row["SYMBOL"],
            "series": row["SERIES"], "security_description": row["SECURITY"],
            "record_date": _iso(row["RECORD_DATE"], "record_date") if row["RECORD_DATE"] else None,
            "effective_date": _iso(row["EX_DATE"], "ex_date"), "action_description": row["PURPOSE"],
            "status": row["STATUS"], "structured_terms": None,
            "source_reference": source_reference, "source_file_sha256": digest,
            "retrieved_at": retrieved_at, "evidence_scope": "STRUCTURE_VERIFIED_FIXTURE_ONLY",
        })
    return sorted(out, key=lambda r: (r["effective_date"], r["security_id"]))


def load_historical_cost_book(path: str | Path) -> dict:
    book = json.loads(Path(path).read_text(encoding="utf-8"))
    if book.get("artifact_id") != "INDIA_EQUITY_COST_SCHEDULE_HISTORY_V2":
        raise ValueError("HISTORICAL_COST_BOOK_REQUIRED")
    body = {k: v for k, v in book.items() if k != "canonical_hash"}
    if sha256(body) != book.get("canonical_hash"):
        raise ValueError("COST_BOOK_HASH_MISMATCH")
    periods = book["periods"]
    for i, period in enumerate(periods):
        if period["effective_to"] < period["effective_from"]:
            raise ValueError("COST_PERIOD_INVALID")
        if i and periods[i - 1]["effective_to"] >= period["effective_from"]:
            raise ValueError("COST_PERIOD_OVERLAP")
    return book


def select_historical_cost_period(book: dict, session_date: str) -> dict:
    day = _iso(session_date, "session_date")
    matches = [p for p in book["periods"] if p["effective_from"] <= day <= p["effective_to"]]
    if len(matches) != 1:
        raise ValueError("COST_SCHEDULE_NOT_VERIFIED_FOR_DATE")
    return matches[0]


def component_applicability(period: dict, component: str, side: str) -> dict:
    if side not in {"BUY", "SELL"}:
        raise ValueError("INVALID_SIDE")
    matches = [c for c in period["components"] if c["component"] == component]
    if len(matches) != 1 or matches[0]["status"] != "VERIFIED":
        raise ValueError("COST_COMPONENT_NOT_VERIFIED")
    item = matches[0]
    return {**item, "applies": side in item["sides"]}


def build_execution_coverage_matrix(book: dict, start_year: int = 2016, end_year: int = 2026) -> dict:
    names = ["NSE_EXCHANGE_TRANSACTION_CHARGE", "SEBI_TURNOVER_FEE", "STT_DELIVERY", "STAMP_DUTY_DELIVERY", "GST_TREATMENT"]
    years = []
    for year in range(start_year, end_year + 1):
        periods = [p for p in book["periods"] if p["effective_from"][:4] <= str(year) <= p["effective_to"][:4]]
        components = {name: "UNVERIFIED" for name in names}
        for name in names:
            statuses = {c["status"] for p in periods for c in p["components"] if c["component"] == name}
            if statuses == {"VERIFIED"}:
                components[name] = "VERIFIED"
            elif "VERIFIED" in statuses:
                components[name] = "PARTIAL_VERIFIED"
        status = "COMPLETE_VERIFIED" if all(v == "VERIFIED" for v in components.values()) else "PARTIAL_VERIFIED" if any(v != "UNVERIFIED" for v in components.values()) else "UNVERIFIED"
        years.append({"year": year, "components": components, "brokerage": "EXTERNALLY_CONFIGURABLE", "status": status})
    return record("EXECUTION_COST_COVERAGE_MATRIX_V1", {"research_period": f"{start_year}-01-01..{end_year}-10-03", "years": years, "authority_scope": AUTHORITY})


def build_pit_coverage_audit(securities: list[dict], delistings: list[dict], *,
                             exact_snapshots: dict[int, set[str]], source_ids: list[str]) -> dict:
    years = []
    by_isin = {d.get("isin"): d for d in delistings if d.get("isin")}
    for year in range(2016, 2027):
        query = f"{year}-10-03" if year == 2026 else f"{year}-12-31"
        statuses = []
        for row in securities:
            merged = {**row}
            if row.get("isin") in by_isin:
                merged["delisting_date"] = by_isin[row["isin"]]["effective_delisting_date"]
            statuses.append(classify_historical_eligibility(merged, query, exact_snapshots.get(year)))
        eligible = statuses.count("VERIFIED_ELIGIBLE")
        unknown = statuses.count("UNKNOWN_HISTORICAL_ELIGIBILITY")
        not_yet = statuses.count("VERIFIED_NOT_YET_LISTED")
        delisted = statuses.count("VERIFIED_DELISTED")
        quality = "PARTIAL_USE_WITH_CAUTION" if eligible else "INSUFFICIENT"
        known_delisted_total = sum(parse_date(d.get("effective_delisting_date")) <= parse_date(query) for d in delistings if d.get("effective_delisting_date"))
        years.append({
            "year": year, "as_of_date": query, "known_listed_securities": sum(parse_date(r["listing_date"]) <= parse_date(query) for r in securities),
            "known_delisted_securities": known_delisted_total, "verified_eligibility_count": eligible,
            "verified_not_yet_listed_count": not_yet, "unknown_eligibility_count": unknown,
            "historical_index_membership_coverage": "CHANGE_EVENTS_ONLY" if year == 2020 else "DATA_GAP",
            "historical_sector_coverage": "UNKNOWN", "symbol_history_coverage": "PARTIAL_EVENT_EVIDENCE",
            "evidence_sources_used": source_ids, "cross_sectional_research_status": quality,
            "criteria": "SUFFICIENT requires exact-date comprehensive master, stable identity, and bounded unknown share; no year meets it.",
        })
    return record("PIT_UNIVERSE_COVERAGE_AUDIT_V1", {
        "research_period": "2016-01-01..2026-10-03", "years": years,
        "dated_security_master_status": "DATED_SECURITY_MASTER_DATA_GAP",
        "survivorship_bias_fully_solved": False, "authority_scope": AUTHORITY,
    })


def advanced_research_readiness(pit_audit: dict, cost_matrix: dict, *, leakage_safe: bool,
                                governance_ready: bool, benchmark_prices_available: bool) -> dict:
    safe_years = []
    for pit, costs in zip(pit_audit["years"], cost_matrix["years"]):
        if pit["cross_sectional_research_status"] != "INSUFFICIENT" and costs["status"] == "COMPLETE_VERIFIED":
            safe_years.append(pit["year"])
    gates = {
        "pit_universe_coverage_sufficient": bool(safe_years),
        "survivorship_distortion_materially_reduced": pit_audit["survivorship_bias_fully_solved"],
        "identity_history_sufficient": False,
        "execution_cost_coverage_sufficient": bool(safe_years),
        "benchmark_prices_available": benchmark_prices_available,
        "index_membership_available_when_required": False,
        "features_pit_safe": leakage_safe,
        "calibration_and_challenger_governance_ready": governance_ready,
    }
    status = "READY_WITH_RESTRICTED_PERIOD" if safe_years and leakage_safe and governance_ready else "NOT_READY"
    return record("ADVANCED_RESEARCH_READINESS_V1", {
        "status": status, "safe_years": safe_years, "recommended_safe_research_period": None,
        "gates": gates, "training_started": False, "challenger_trained": False,
        "authority_scope": AUTHORITY, "trading_authority": False, "ml_authority": "NONE",
        "reason": "No year has comprehensive dated investable-universe evidence; advanced cross-sectional research remains blocked.",
    })
