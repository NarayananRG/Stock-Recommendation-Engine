"""Official NSE Integrated Filing metadata acquisition for Phase 2A.1.

Network access is intentionally isolated from PIT normalization. Raw responses are
hash-bound before rows are normalized, and only official NSE URLs are accepted.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Callable, Iterable
from urllib.parse import urlencode

from .core import AUTHORITY, TARGET_QUARTER_ENDS, build_filing_event, normalize_symbol

NSE_LANDING_URL = "https://www.nseindia.com/companies-listing/corporate-integrated-filing"
NSE_INTEGRATED_API = "https://www.nseindia.com/api/integrated-filing-results"
DEFAULT_PAGE_SIZE = 50


def build_query(*, symbol: str, page: int = 1, size: int = DEFAULT_PAGE_SIZE,
                from_date: date | None = None, to_date: date | None = None) -> dict:
    if page < 1 or size < 1 or size > 500:
        raise ValueError("INVALID_PAGINATION")
    if (from_date is None) ^ (to_date is None):
        raise ValueError("BOTH_DATE_BOUNDS_REQUIRED")
    payload = {
        "index": "equities",
        "symbol": normalize_symbol(symbol),
        "period_ended": "all",
        "type": "Integrated Filing- Financials",
        "page": page,
        "size": size,
    }
    if from_date is not None and to_date is not None:
        if to_date < from_date:
            raise ValueError("INVALID_DATE_RANGE")
        payload["from_date"] = from_date.strftime("%d-%m-%Y")
        payload["to_date"] = to_date.strftime("%d-%m-%Y")
    return payload


def query_url(payload: dict) -> str:
    return NSE_INTEGRATED_API + "?" + urlencode(payload)


def raw_payload_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def extract_rows(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValueError("INVALID_INTEGRATED_FILING_PAYLOAD")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("INVALID_INTEGRATED_FILING_DATA")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("INVALID_INTEGRATED_FILING_ROW")
    return rows


def _pick(row: dict, *keys: str):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def map_nse_row(row: dict) -> dict:
    """Map the observed NSE Integrated Filing API fields to the Phase 2A contract.

    Live inspection on 2026-10-01 observed: seq_Id, symbol, smName, qe_Date,
    consolidated, type_Sub, xbrl, xbrlFileSize, ixbrl, broadcast_Date,
    creation_Date, revised_Date and revision_Remark. Older/generic aliases are
    retained only as compatibility fallbacks.
    """
    broadcast = _pick(
        row,
        "broadcast_Date",
        "broadcastDate",
        "broadCastDate",
        "broadcast_dttm",
        "broadcastDateTime",
        "BROADCAST DATE/TIME",
    )
    creation = _pick(row, "creation_Date", "creationDate", "creation_ts")
    return {
        "Symbol": _pick(row, "symbol", "Symbol"),
        "Company Name": _pick(row, "smName", "companyName", "company_Name", "Company Name"),
        "Quarter End Date": _pick(row, "qe_Date", "quarterEndDate", "Quarter End Date"),
        "Type of Submission": _pick(row, "type_Sub", "typeOfSubmission", "Type of Submission"),
        "Audited / Unaudited": _pick(row, "audited", "Audited / Unaudited"),
        "CONSOLIDATED / Standalone": _pick(
            row,
            "consolidated",
            "Consolidated / Standalone",
            "CONSOLIDATED / Standalone",
        ),
        # broadcast_Date is the primary official table timestamp. creation_Date
        # is retained only as a fallback when NSE omits broadcast_Date.
        "BROADCAST DATE/TIME": broadcast or creation,
        "Creation DATE/TIME": creation,
        "Revised DATE/TIME": _pick(
            row,
            "revised_Date",
            "revisedDate",
            "revised_dttm",
            "revisedDateTime",
            "Revised DATE/TIME",
        ),
        "Revision Remarks": _pick(
            row,
            "revision_Remark",
            "revisionRemarks",
            "remarks",
            "Revision Remarks",
        ),
        "IND AS/ NON IND AS": _pick(
            row,
            "accountingStandard",
            "indAs",
            "ind_As",
            "IND AS/ NON IND AS",
        ),
        "seq_id": _pick(row, "seq_Id", "seqId", "seqNumber"),
        "xbrl": _pick(row, "xbrl", "XBRL"),
        "ixbrl": _pick(row, "ixbrl", "iXBRL"),
        "details": _pick(row, "details", "fileName", "Details"),
    }


def normalize_response(payload: object, *, source_url: str = NSE_INTEGRATED_API) -> dict:
    rows = extract_rows(payload)
    source_sha = raw_payload_hash(payload)
    events, rejected = [], []
    for index, raw in enumerate(rows):
        mapped = map_nse_row(raw)
        try:
            event = build_filing_event(mapped, source_url=source_url, source_sha256=source_sha, source_exchange="NSE")
            event["provider_seq_id"] = mapped.get("seq_id")
            event["creation_ts"] = mapped.get("Creation DATE/TIME")
            event["xbrl_url"] = mapped.get("xbrl")
            event["ixbrl_url"] = mapped.get("ixbrl")
            event["details_url"] = mapped.get("details")
            events.append(event)
        except Exception as exc:
            rejected.append({"row_index": index, "reason": f"{type(exc).__name__}: {exc}"})
    return {
        "artifact_type": "FUNDAMENTAL_PHASE2A1_NSE_RESPONSE_V1",
        "source_url": source_url,
        "raw_payload_sha256": source_sha,
        "raw_row_count": len(rows),
        "normalized_event_count": len(events),
        "rejected_row_count": len(rejected),
        "events": events,
        "rejected_rows": rejected,
        "authority": AUTHORITY,
    }


def target_quarter_filter(events: Iterable[dict]) -> list[dict]:
    wanted = set(TARGET_QUARTER_ENDS)
    return [dict(x) for x in events if x.get("quarter_end") in wanted]


def acquire_symbol(
    symbol: str, *,
    fetch_json: Callable[[str, dict, dict], object],
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = 25,
) -> dict:
    """Acquire all target filing metadata for one symbol through an injected HTTP client.

    fetch_json(url, params, headers) must perform the network request. Injection keeps
    tests deterministic and makes session/cookie handling a caller concern.
    """
    if max_pages < 1:
        raise ValueError("INVALID_MAX_PAGES")
    sym = normalize_symbol(symbol)
    pages, events, raw_hashes = [], [], []
    for page in range(1, max_pages + 1):
        params = build_query(symbol=sym, page=page, size=page_size)
        payload = fetch_json(
            NSE_INTEGRATED_API,
            params,
            {"Referer": NSE_LANDING_URL, "Accept": "application/json,text/plain,*/*"},
        )
        normalized = normalize_response(payload)
        pages.append({
            "page": page,
            "raw_payload_sha256": normalized["raw_payload_sha256"],
            "raw_row_count": normalized["raw_row_count"],
            "rejected_row_count": normalized["rejected_row_count"],
        })
        raw_hashes.append(normalized["raw_payload_sha256"])
        events.extend(normalized["events"])
        if normalized["raw_row_count"] < page_size:
            break
    else:
        raise ValueError("MAX_PAGE_LIMIT_REACHED")
    target = target_quarter_filter(events)
    return {
        "artifact_type": "FUNDAMENTAL_PHASE2A1_SYMBOL_ACQUISITION_V1",
        "symbol": sym,
        "pages": pages,
        "page_count": len(pages),
        "source_payload_hashes": raw_hashes,
        "all_event_count": len(events),
        "target_event_count": len(target),
        "target_events": target,
        "authority": AUTHORITY,
    }


def acquire_marketwide(
    *, fetch_json: Callable[[str, dict, dict], object],
    page_size: int = 500,
    max_pages: int = 100,
) -> dict:
    """Acquire market-wide Integrated Filing metadata before audited-universe intersection."""
    if max_pages < 1:
        raise ValueError("INVALID_MAX_PAGES")
    pages, events, rejected = [], [], 0
    for page in range(1, max_pages + 1):
        params = build_query(page=page, size=page_size)
        payload = fetch_json(
            NSE_INTEGRATED_API,
            params,
            {"Referer": NSE_LANDING_URL, "Accept": "application/json,text/plain,*/*"},
        )
        normalized = normalize_response(payload)
        pages.append({
            "page": page,
            "raw_payload_sha256": normalized["raw_payload_sha256"],
            "raw_row_count": normalized["raw_row_count"],
            "rejected_row_count": normalized["rejected_row_count"],
        })
        rejected += normalized["rejected_row_count"]
        events.extend(normalized["events"])
        if normalized["raw_row_count"] < page_size:
            break
    else:
        raise ValueError("MAX_PAGE_LIMIT_REACHED")
    target = target_quarter_filter(events)
    return {
        "artifact_type": "FUNDAMENTAL_PHASE2A1_MARKETWIDE_ACQUISITION_V1",
        "page_count": len(pages),
        "pages": pages,
        "all_event_count": len(events),
        "target_event_count": len(target),
        "target_events": target,
        "rejected_row_count": rejected,
        "audited_universe_intersection_performed": False,
        "authority": AUTHORITY,
    }
