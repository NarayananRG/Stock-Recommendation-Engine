"""Deterministic authoritative-data ingestion and readiness primitives.

This module is deliberately offline and has no production, trading, ML, or
broker authority. Unknown source structures and incomplete PIT evidence fail
closed instead of being guessed or backfilled.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path
from typing import Iterable

from common import file_sha256, parse_date, record, sha256

SOURCE_CLASSES = {
    "OFFICIAL_PUBLIC_VERIFIED", "OFFICIAL_LICENSED_VERIFIED",
    "OFFICIAL_SUBSCRIPTION_REQUIRED", "OFFICIAL_MANUAL_ACQUISITION_REQUIRED",
    "OFFICIAL_AUTOMATION_RESTRICTED", "SECONDARY_UNVERIFIED", "NOT_AVAILABLE",
}
ACQUISITION_STATES = {
    "PUBLICLY_ACQUIRED", "SUBSCRIPTION_REQUIRED", "MANUAL_REQUEST_REQUIRED",
    "AUTOMATION_RESTRICTED", "NOT_RELEVANT", "NOT_AVAILABLE",
}
PROFILES = {"EXCHANGE_WIDE_PIT", "INDEX_CONSTITUENT_PIT"}
HASH_FIELDS = {"source_hash", "source_file_sha256"}


def _digest(content: bytes, expected: str | None = None) -> str:
    actual = hashlib.sha256(content).hexdigest()
    if expected and expected.lower() != actual:
        raise ValueError("SOURCE_HASH_MISMATCH")
    return actual


def _date(value: str, name: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except Exception as exc:
        raise ValueError(f"INVALID_{name.upper()}") from exc


def validate_product(product: dict) -> dict:
    required = {
        "product_id", "provider", "product_name", "dataset_purpose", "market_scope",
        "historical_coverage_advertised", "granularity", "fields_advertised",
        "delivery_format", "source_classification", "machine_readable",
        "acquisition_mechanism", "licence_status", "redistribution_status",
        "raw_data_commit_allowed", "derived_data_commit_allowed", "usage_scope",
        "official_reference", "verification_date", "research_profiles",
        "readiness_gates", "acquisition_status",
    }
    if required - product.keys():
        raise ValueError("PRODUCT_METADATA_INCOMPLETE")
    if product["source_classification"] not in SOURCE_CLASSES:
        raise ValueError("INVALID_SOURCE_CLASSIFICATION")
    if product["acquisition_status"] not in ACQUISITION_STATES:
        raise ValueError("INVALID_ACQUISITION_STATUS")
    if product["source_classification"] == "OFFICIAL_SUBSCRIPTION_REQUIRED" and product["acquisition_status"] == "PUBLICLY_ACQUIRED":
        raise ValueError("SUBSCRIPTION_PRODUCT_NOT_PUBLICLY_ACQUIRED")
    if product["source_classification"] == "SECONDARY_UNVERIFIED" and product.get("verified", False):
        raise ValueError("UNVERIFIED_SOURCE_CANNOT_BECOME_VERIFIED")
    if not set(product["research_profiles"]).issubset(PROFILES):
        raise ValueError("INVALID_RESEARCH_PROFILE")
    return dict(product)


def archive_entry(*, archive_id: str, source_id: str, publisher: str,
                  source_reference: str, original_filename: str, retrieved_at: str,
                  content: bytes, local_path: str, licence_classification: str,
                  report_date: str | None = None) -> dict:
    if not all([archive_id, source_id, publisher, source_reference, original_filename, retrieved_at, local_path]):
        raise ValueError("MISSING_SOURCE_PROVENANCE")
    if licence_classification not in SOURCE_CLASSES:
        raise ValueError("INVALID_SOURCE_CLASSIFICATION")
    return {
        "archive_id": archive_id, "source_id": source_id, "official_publisher": publisher,
        "source_reference": source_reference, "original_filename": original_filename,
        "report_or_effective_date": _date(report_date, "report_date") if report_date else None,
        "retrieved_at": retrieved_at, "byte_length": len(content), "sha256": _digest(content),
        "local_relative_storage_path": local_path, "licence_classification": licence_classification,
        "redistribution_status": "RESTRICTED_OR_UNKNOWN", "raw_data_commit_allowed": False,
        "derived_data_commit_allowed": True, "usage_scope": "RESEARCH_ONLY",
        "raw_file_committed": False,
    }


def _rows(content: bytes, required: set[str], *, allowed: set[str]) -> tuple[list[dict], str]:
    digest = _digest(content)
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    headers = set(reader.fieldnames or [])
    if not headers or required - headers or headers - allowed:
        raise ValueError("UNSUPPORTED_OFFICIAL_DATA_SCHEMA")
    return [{str(k): str(v or "").strip() for k, v in row.items()} for row in reader], digest


SECURITY_HEADERS = {"snapshot_date", "security_id", "isin", "symbol", "company", "series", "listing_date", "trading_status"}
INDEX_HEADERS = {"index_id", "snapshot_date", "security_id", "isin", "symbol", "company", "weight", "market_cap"}
ACTION_HEADERS = {"security_id", "isin", "symbol", "action_type", "record_date", "effective_date", "description"}
IDENTITY_HEADERS = {"security_id", "isin", "symbol", "company", "series", "effective_from", "effective_to"}


def parse_security_snapshot(content: bytes, *, archive_id: str, source_hash: str | None = None) -> list[dict]:
    rows, digest = _rows(content, SECURITY_HEADERS, allowed=SECURITY_HEADERS)
    if source_hash and source_hash != digest:
        raise ValueError("SOURCE_HASH_MISMATCH")
    out, identities = [], set()
    for row in rows:
        if not row["security_id"] or not row["isin"] or not row["symbol"]:
            raise ValueError("MISSING_OFFICIAL_SECURITY_IDENTITY")
        if row["security_id"] in identities or any(x["isin"] == row["isin"] for x in out):
            raise ValueError("DUPLICATE_ISIN_CONFLICT")
        identities.add(row["security_id"])
        out.append({**row, "snapshot_date": _date(row["snapshot_date"], "snapshot_date"),
                    "listing_date": _date(row["listing_date"], "listing_date"),
                    "source_archive_id": archive_id, "source_hash": digest,
                    "parser_version": "OFFICIAL_SECURITY_MASTER_CSV_V1"})
    return sorted(out, key=lambda x: x["security_id"])


def parse_index_snapshot(content: bytes, *, archive_id: str, source_hash: str | None = None) -> list[dict]:
    required = INDEX_HEADERS - {"weight", "market_cap"}
    rows, digest = _rows(content, required, allowed=INDEX_HEADERS)
    if source_hash and source_hash != digest:
        raise ValueError("SOURCE_HASH_MISMATCH")
    out, keys = [], set()
    for row in rows:
        if not row["index_id"] or not row["isin"]:
            raise ValueError("INDEX_CONSTITUENT_IDENTITY_REQUIRED")
        key = (row["index_id"], row["snapshot_date"], row["isin"])
        if key in keys:
            raise ValueError("DUPLICATE_INDEX_CONSTITUENT")
        keys.add(key)
        out.append({**row, "snapshot_date": _date(row["snapshot_date"], "snapshot_date"),
                    "source_archive_id": archive_id, "source_hash": digest,
                    "parser_version": "OFFICIAL_INDEX_CONSTITUENT_CSV_V1"})
    return sorted(out, key=lambda x: (x["index_id"], x["snapshot_date"], x["isin"]))


def build_membership_periods(snapshots: list[dict]) -> list[dict]:
    """Bound membership only between adjacent official snapshots; no gap backfill."""
    grouped: dict[tuple[str, str], list[dict]] = {}
    all_dates: dict[str, list[str]] = {}
    for row in snapshots:
        grouped.setdefault((row["index_id"], row["isin"]), []).append(row)
        all_dates.setdefault(row["index_id"], []).append(row["snapshot_date"])
    out = []
    for (index_id, isin), items in grouped.items():
        by_date = {x["snapshot_date"]: x for x in items}
        dates = sorted(set(all_dates[index_id]))
        for left, right in zip(dates, dates[1:]):
            if left in by_date and right in by_date:
                row = by_date[left]
                out.append({
                    "index_id": index_id, "security_id": row["security_id"], "isin": isin,
                    "symbol": row["symbol"], "effective_from": left, "effective_to": right,
                    "evidence_basis": "BOUNDED_BY_OFFICIAL_SNAPSHOTS",
                    "source_archive_ids": sorted({by_date[left]["source_archive_id"], by_date[right]["source_archive_id"]}),
                    "source_hashes": sorted({by_date[left]["source_hash"], by_date[right]["source_hash"]}),
                    "parser_version": "PIT_INDEX_MEMBERSHIP_PERIOD_V1",
                })
    return sorted(out, key=lambda x: (x["index_id"], x["isin"], x["effective_from"]))


def parse_corporate_actions(content: bytes, *, archive_id: str) -> list[dict]:
    rows, digest = _rows(content, ACTION_HEADERS, allowed=ACTION_HEADERS)
    out = []
    for row in rows:
        if not row["isin"] or not row["action_type"] or not row["effective_date"]:
            raise ValueError("CORPORATE_ACTION_RECORD_INVALID")
        out.append({**row, "record_date": _date(row["record_date"], "record_date") if row["record_date"] else None,
                    "effective_date": _date(row["effective_date"], "effective_date"),
                    "source_archive_id": archive_id, "source_hash": digest,
                    "parser_version": "OFFICIAL_CORPORATE_ACTION_CSV_V1"})
    return sorted(out, key=lambda x: (x["effective_date"], x["isin"]))


def parse_identity_periods(content: bytes, *, archive_id: str) -> list[dict]:
    rows, digest = _rows(content, IDENTITY_HEADERS, allowed=IDENTITY_HEADERS)
    out = []
    for row in rows:
        if not row["isin"] or not row["symbol"]:
            raise ValueError("IDENTITY_EVIDENCE_INCOMPLETE")
        start = _date(row["effective_from"], "effective_from")
        end = _date(row["effective_to"], "effective_to") if row["effective_to"] else None
        if end and end < start:
            raise ValueError("IDENTITY_PERIOD_INVALID")
        out.append({**row, "effective_from": start, "effective_to": end,
                    "source_archive_id": archive_id, "source_hash": digest,
                    "parser_version": "SECURITY_IDENTITY_PERIOD_CSV_V1"})
    for i, left in enumerate(out):
        for right in out[i + 1:]:
            if left["isin"] != right["isin"]:
                continue
            le, re = left["effective_to"] or "9999-12-31", right["effective_to"] or "9999-12-31"
            if max(left["effective_from"], right["effective_from"]) <= min(le, re) and left["symbol"] != right["symbol"]:
                raise ValueError("CONFLICTING_ISIN_SYMBOL_PERIOD")
    return sorted(out, key=lambda x: (x["isin"], x["effective_from"]))


def identity_on(periods: list[dict], isin: str, query_date: str) -> dict | None:
    day = _date(query_date, "query_date")
    matches = [x for x in periods if x["isin"] == isin and x["effective_from"] <= day <= (x["effective_to"] or "9999-12-31")]
    if len(matches) > 1:
        raise ValueError("AMBIGUOUS_SECURITY_IDENTITY")
    return matches[0] if matches else None


def materialize_universe(*, profile: str, as_of_date: str,
                         securities: list[dict] | None = None,
                         index_membership: list[dict] | None = None) -> dict:
    if profile not in PROFILES:
        raise ValueError("UNSUPPORTED_RESEARCH_PROFILE")
    day = _date(as_of_date, "as_of_date")
    unknowns, members, source_ids = [], [], set()
    if profile == "EXCHANGE_WIDE_PIT":
        exact = [x for x in (securities or []) if x["snapshot_date"] == day]
        if not exact:
            unknowns.append("NO_EXACT_DATED_SECURITY_MASTER")
        else:
            for x in exact:
                if x["listing_date"] <= day and x["trading_status"] in {"ACTIVE", "ELIGIBLE"}:
                    members.append({"security_id": x["security_id"], "isin": x["isin"], "symbol": x["symbol"], "membership_evidence": "EXACT_OFFICIAL_SNAPSHOT"})
                    source_ids.add(x["source_archive_id"])
    else:
        for x in index_membership or []:
            if x["effective_from"] <= day <= x["effective_to"]:
                members.append({"security_id": x["security_id"], "isin": x["isin"], "symbol": x["symbol"], "membership_evidence": x["evidence_basis"]})
                source_ids.update(x["source_archive_ids"])
        if not members:
            unknowns.append("NO_SUPPORTED_INDEX_MEMBERSHIP_ON_DATE")
    payload = {"profile": profile, "as_of_date": day, "universe_definition": profile,
               "source_snapshot_ids": sorted(source_ids), "securities": sorted(members, key=lambda x: x["security_id"]),
               "known_exclusions": [], "unknowns": unknowns}
    return record("PIT_RESEARCH_UNIVERSE_V1", {**payload, "dataset_hash": sha256(payload)})


def survivorship_assessment(*, year: int, historical_ids: Iterable[str],
                            current_ids: Iterable[str], delisted_ids: Iterable[str],
                            unknown_membership: int, unknown_identity: int,
                            evidence_source_count: int, policy: dict) -> dict:
    historical, current, delisted = set(historical_ids), set(current_ids), set(delisted_ids)
    total = len(historical) + int(unknown_membership)
    known = len(historical)
    coverage = 0.0 if total == 0 else round(known / total, 6)
    unknown_share = 1.0 if total == 0 else round(int(unknown_membership) / total, 6)
    identity_coverage = 0.0 if known == 0 else round((known - int(unknown_identity)) / known, 6)
    criteria = policy["thresholds"]
    reduced = (
        total > 0 and unknown_share <= criteria["maximum_unknown_universe_share"]
        and identity_coverage >= criteria["minimum_security_identity_coverage"]
        and len(delisted & historical) >= criteria["minimum_known_non_survivors"]
        and evidence_source_count >= criteria["minimum_evidence_source_count"]
    )
    return record("SURVIVORSHIP_COVERAGE_ASSESSMENT_V1", {
        "year": year, "universe_count": total, "known_historical_members": known,
        "current_survivors": len(historical & current), "known_delisted_non_surviving": len(historical & delisted),
        "unknown_membership": int(unknown_membership), "unknown_identity_count": int(unknown_identity),
        "coverage_percentage": round(coverage * 100, 4), "unknown_share": unknown_share,
        "identity_coverage": identity_coverage, "evidence_source_count": evidence_source_count,
        "survivorship_distortion_materially_reduced": reduced,
        "criterion_classification": "RESEARCH_GOVERNANCE_THRESHOLD",
        "policy_hash": sha256(policy),
    })


def market_data_readiness(*, ohlc: bool, volume: bool, turnover: bool,
                          trading_days: bool, adjustment_state: str,
                          official_provenance: bool) -> dict:
    allowed = {"RAW_UNADJUSTED", "SPLIT_ADJUSTED", "DIVIDEND_ADJUSTED", "TOTAL_RETURN_ADJUSTED", "UNKNOWN"}
    if adjustment_state not in allowed:
        raise ValueError("UNSUPPORTED_ADJUSTMENT_STATE")
    gates = {"ohlc": ohlc, "volume": volume, "turnover": turnover,
             "trading_day_availability": trading_days, "adjustment_semantics_explicit": adjustment_state != "UNKNOWN",
             "official_provenance": official_provenance}
    return record("MARKET_DATA_SOURCE_READINESS_V1", {
        "status": "SUFFICIENT" if all(gates.values()) else "INSUFFICIENT",
        "gates": gates, "price_adjustment_state": adjustment_state,
        "frozen_stage4_data_replaced": False,
    })


def feature_pit_readiness(features: list[dict]) -> dict:
    allowed = {"PIT_SAFE_NOW", "REQUIRES_NEW_SOURCE", "REQUIRES_EFFECTIVE_DATE_LOGIC", "UNAVAILABLE", "OPTIONAL_FUTURE_FEATURE_FAMILY"}
    for item in features:
        if item.get("status") not in allowed or "required_for_minimal_profile" not in item:
            raise ValueError("FEATURE_READINESS_INVALID")
    blockers = [x["family"] for x in features if x["required_for_minimal_profile"] and x["status"] != "PIT_SAFE_NOW"]
    return record("NEXTGEN_FEATURE_PIT_READINESS_V1", {
        "features": features, "minimal_profile_pit_safe": not blockers,
        "blocking_required_feature_families": blockers,
        "fundamentals_policy": "OPTIONAL_FUTURE_FEATURE_FAMILY",
    })


def readiness_v3(*, profiles: dict[str, dict], v1_hash: str, v2_hash: str) -> dict:
    decisions = {}
    for profile in sorted(PROFILES):
        evidence = profiles.get(profile, {})
        required = ["universe", "identity", "survivorship", "market_data", "costs", "benchmark", "features"]
        if profile == "INDEX_CONSTITUENT_PIT":
            required.append("index_membership")
        failed = [gate for gate in required if not evidence.get("gates", {}).get(gate, False)]
        period = evidence.get("period") if not failed else None
        partial = bool(evidence.get("partial_year", False))
        if partial and period:
            failed.append("PARTIAL_YEAR_NOT_ELIGIBLE")
            period = None
        decisions[profile] = {
            "status": "READY_WITH_RESTRICTED_PERIOD" if period and not failed else "NOT_READY",
            "restricted_period": period, "failed_gates": sorted(set(failed)),
            "source_manifests": evidence.get("source_manifests", []),
            "security_coverage": evidence.get("security_coverage"),
            "identity_coverage": evidence.get("identity_coverage"),
            "survivorship_assessment": evidence.get("survivorship_assessment"),
        }
    ready_periods = [x["restricted_period"] for x in decisions.values() if x["status"] == "READY_WITH_RESTRICTED_PERIOD"]
    return record("ADVANCED_RESEARCH_READINESS_V3", {
        "status": "READY_WITH_RESTRICTED_PERIOD" if ready_periods else "NOT_READY",
        "reason": None if ready_periods else "OFFICIAL_DATA_ACQUISITION_REQUIRED",
        "profiles": decisions, "fully_research_eligible_period": ready_periods[0] if len(ready_periods) == 1 else None,
        "preserved_v1_file_sha256": v1_hash, "preserved_v2_file_sha256": v2_hash,
        "training_started": False, "challenger_trained": False, "model_promoted": False,
        "trading_authority": False, "ml_authority": "NONE",
    })


def write_derived(path: str | Path, value: object) -> None:
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ingest_file(kind: str, source: str | Path, *, archive_id: str) -> list[dict]:
    content = Path(source).read_bytes()
    parsers = {
        "NSE_SECURITY_MASTER": parse_security_snapshot,
        "NIFTY_CONSTITUENTS": parse_index_snapshot,
        "NSE_CORPORATE_ACTIONS": parse_corporate_actions,
        "SECURITY_IDENTITY": parse_identity_periods,
    }
    if kind not in parsers:
        raise ValueError("UNSUPPORTED_OFFICIAL_DATA_SOURCE")
    return parsers[kind](content, archive_id=archive_id)
