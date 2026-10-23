from __future__ import annotations

import csv
import io
import json
import os
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from uuid import uuid4
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import hmac
from urllib.parse import urlparse
from .official_cache_guard import cache_guard, publish_batch, CommittedPublicationNeedsRecovery
from .exchange_calendar import is_trading_day

UA = "Stock-Recommendation-Engine/0.14.6 official-first daily refresh"
ARCHIVE = "https://nsearchives.nseindia.com"
NSE = "https://www.nseindia.com"


class OfficialDataNotReady(RuntimeError):
    pass


class OfficialDataParseError(RuntimeError):
    pass


def _contract(
    *,
    expected_session: str,
    status: str,
    stage: str,
    source: str = "NSE_OFFICIAL",
    source_url_or_provider: str | None = None,
    http_status: int | None = None,
    reason_code: str | None = None,
    reason_detail: str | None = None,
    equity_session: str | None = None,
    index_session: str | None = None,
    stock_files_expected: int | None = None,
    stock_files_matched: int | None = None,
    stock_coverage: float | None = None,
    persisted: bool = False,
    verified_latest_session: str | None = None,
    payload_size: int | None = None,
    content_type: str | None = None,
    filename: str | None = None,
    schema_headers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "expected_session": expected_session,
        "status": status,
        "stage": stage,
        "source": source,
        "source_url_or_provider": source_url_or_provider,
        "http_status": http_status,
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "equity_session": equity_session,
        "index_session": index_session,
        "stock_files_expected": stock_files_expected,
        "stock_files_matched": stock_files_matched,
        "stock_coverage": stock_coverage,
        "persisted": persisted,
        "verified_latest_session": verified_latest_session,
        "payload_size": payload_size,
        "content_type": content_type,
        "downloaded_filename": filename,
        "schema_headers": schema_headers,
        "automatic_yfinance_fallback": False,
    }


class _Response:
    def __init__(self, status_code: int, headers: Any, content: bytes):
        self.status_code = int(status_code)
        self.headers = headers
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP_{self.status_code}")

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))


class _OfficialSession:
    def __init__(self):
        self.headers = {
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        }
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def get(self, url: str, *, timeout: int, headers: dict[str, str] | None = None) -> _Response:
        request = Request(url, headers={**self.headers, **(headers or {})})
        try:
            with self._opener.open(request, timeout=timeout) as response:
                if not _official_url(response.geturl()):
                    raise RuntimeError('C01_UNTRUSTED_OFFICIAL_REDIRECT')
                return _Response(response.status, response.headers, response.read())
        except HTTPError as exc:
            return _Response(exc.code, exc.headers, exc.read())


def _session() -> _OfficialSession:
    return _OfficialSession()



class OfficialRowConflict(RuntimeError):
    pass


def _official_url(url):
    p = urlparse(str(url or ""))
    return p.scheme == "https" and p.hostname in {"nsearchives.nseindia.com", "www.nseindia.com", "nseindia.com"} and not p.username and not p.password and p.port in (None, 443)


def _day(value):
    if not isinstance(value, str) or len(value) != 10 or date.fromisoformat(value).isoformat() != value:
        raise RuntimeError("C01_NONCANONICAL_SESSION")
    return value


def _numbers(values):
    try:
        numbers = tuple(Decimal(str(v)) for v in values)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError("C01_NON_NUMERIC_OHLCV") from exc
    if len(numbers) != 5 or not all(v.is_finite() for v in numbers):
        raise RuntimeError("C01_NONFINITE_OHLCV")
    op, hi, lo, cl, vol = numbers
    if min(op, hi, lo, cl) <= 0 or hi < max(op, lo, cl) or lo > min(op, hi, cl) or vol < 0 or vol != vol.to_integral_value():
        raise RuntimeError("C01_INVALID_OHLCV")
    return numbers


def _row_hash(session, values):
    normalized = [format(v.normalize(), "f") for v in _numbers(values)]
    return sha256(json.dumps([session, normalized], separators=(",", ":")).encode()).hexdigest()


def _provenance(meta, payload=None):
    if not _official_url(meta.get("url")) or meta.get("http_status") != 200:
        raise RuntimeError("C01_INCOMPLETE_OFFICIAL_PROVENANCE")
    digest = meta.get("source_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise RuntimeError("C01_MISSING_SOURCE_SHA256")
    if payload is None:
        payload = meta.get("_raw_payload")
    if not isinstance(payload, bytes):
        raise RuntimeError("C01_SOURCE_ARTIFACT_UNAVAILABLE")
    if sha256(payload).hexdigest() != digest:
        raise RuntimeError("C01_SOURCE_SHA256_MISMATCH")
    timestamp = datetime.fromisoformat(meta["retrieved_at"])
    if timestamp.tzinfo is None or timestamp > datetime.now(timezone.utc):
        raise RuntimeError("C01_INVALID_RETRIEVAL_TIME")
    # No publication time is inferred from retrieval or HTTP Last-Modified.
    return {k: meta.get(k) for k in ("url", "source_sha256", "retrieved_at", "source_publication_time", "http_last_modified")}


def _verify_correction(authorization, trust, session, file_name, old_file_hash, old_row_hash, new_row_hash, source_hash):
    """Offline two-reviewer approval; disabled unless callers supply both trust keys.

    These are local reviewer signatures, NOT an exchange signature. Reviewers
    attest independent official-source verification outside normal refresh.
    The production GUI does not expose this interface or configure keys.
    """
    if not isinstance(authorization, dict) or not isinstance(trust, dict):
        raise OfficialRowConflict("C01_EXISTING_ROW_CONFLICT_REQUIRES_VERIFIED_CORRECTION")
    body = authorization.get("body", {})
    if body.get("schema") != "SRE_C01_REVIEWED_CORRECTION_V1" or body.get("session") != session:
        raise OfficialRowConflict("C01_WRONG_CORRECTION_SCOPE")
    expires = datetime.fromisoformat(body["expires_at"])
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise OfficialRowConflict("C01_CORRECTION_EXPIRED")
    if not body.get("reason") or not body.get("independent_official_evidence"):
        raise OfficialRowConflict("C01_MISSING_INDEPENDENT_REVIEW")
    evidence = body["independent_official_evidence"]
    if not _official_url(evidence.get("url")) or len(evidence.get("source_sha256", "")) != 64 or any(c not in "0123456789abcdef" for c in evidence.get("source_sha256", "")):
        raise OfficialRowConflict("C01_INVALID_INDEPENDENT_SOURCE_EVIDENCE")
    ids = body.get("reviewers", [])
    if len(ids) != 2 or len(set(ids)) != 2:
        raise OfficialRowConflict("C01_TWO_INDEPENDENT_REVIEWERS_REQUIRED")
    keys = [trust.get(i) for i in ids]
    if any(not isinstance(k, bytes) or len(k) < 32 for k in keys) or keys[0] == keys[1]:
        raise OfficialRowConflict("C01_MISSING_INDEPENDENT_TRUST_KEYS")
    message = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    for identifier, key in zip(ids, keys):
        supplied = authorization.get("signatures", {}).get(identifier, "")
        if not isinstance(supplied, str) or not hmac.compare_digest(hmac.new(key, message, "sha256").hexdigest(), supplied):
            raise OfficialRowConflict("C01_UNAUTHENTICATED_CORRECTION")
    expected = {"file": file_name, "old_file_sha256": old_file_hash, "old_row_sha256": old_row_hash, "new_row_sha256": new_row_hash, "source_sha256": source_hash}
    if expected not in body.get("changes", []):
        raise OfficialRowConflict("C01_CORRECTION_ROW_OR_SOURCE_MISMATCH")
    return {"authorization_sha256": sha256(message).hexdigest(), "reviewers": ids, "reason": body["reason"], "independent_official_evidence": evidence, "signed_authorization": authorization}

def _download_candidates(urls: list[str], *, timeout: int = 40) -> tuple[bytes, dict[str, Any]]:
    import time
    sess = _session()
    errors: list[str] = []
    last_http: int | None = None
    last_content_type: str | None = None
    for url in urls:
        for attempt in range(4):
            try:
                resp = sess.get(
                    url,
                    timeout=timeout,
                    headers={**sess.headers, "Accept": "application/zip,text/csv,application/json,*/*"},
                )
                last_http = int(resp.status_code)
                last_content_type = str(resp.headers.get("content-type") or "")
                if resp.status_code in {429, 500, 502, 503, 504}:
                    errors.append(f"{url}:HTTP_{resp.status_code}:attempt_{attempt + 1}")
                    time.sleep(0.8 * (attempt + 1))
                    continue
                if resp.status_code in {400, 404}:
                    errors.append(f"{url}:HTTP_{resp.status_code}")
                    break
                if resp.status_code in {401, 403}:
                    errors.append(f"{url}:HTTP_{resp.status_code}")
                    break
                resp.raise_for_status()
                if not resp.content:
                    errors.append(f"{url}:EMPTY_BODY")
                    break
                name = url.split("?")[0].rstrip("/").split("/")[-1]
                return resp.content, {
                    "url": url,
                    "http_status": last_http,
                    "content_type": last_content_type,
                    "filename": name,
                    "payload_size": len(resp.content),
                    "source_sha256": sha256(resp.content).hexdigest(),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "source_publication_time": None,
                    "http_last_modified": resp.headers.get("last-modified"),
                    "_raw_payload": resp.content,
                }
            except Exception as exc:
                errors.append(f"{url}:{type(exc).__name__}:{exc}")
                time.sleep(0.5 * (attempt + 1))
    detail = " | ".join(errors[-8:]) or "NO_OFFICIAL_RESPONSE"
    if any("HTTP_400" in x or "HTTP_404" in x for x in errors):
        raise OfficialDataNotReady("OFFICIAL_REPORT_NOT_READY:" + detail)
    raise RuntimeError("OFFICIAL_DOWNLOAD_FAILED:" + detail)


def _bhavcopy_candidates(expected_session: str) -> list[str]:
    d = datetime.strptime(expected_session, "%Y-%m-%d")
    name = f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    descriptor = json.dumps([{
        "name": "CM-UDiFF Common Bhavcopy Final (zip)",
        "type": "daily-reports",
        "category": "capital-market",
        "section": "equities",
    }], separators=(",", ":"))
    query = urlencode({
        "archives": descriptor,
        "date": d.strftime("%d-%b-%Y"),
        "type": "Equities",
        "mode": "single",
    })
    return [f"{ARCHIVE}/content/cm/{name}", f"{NSE}/api/reports?{query}"]


def _parse_bhav(payload, expected_session):
    _day(expected_session)
    if payload[:4] != b"PK\x03\x04":
        raise RuntimeError("OFFICIAL_BHAVCOPY_NOT_ZIP")
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1 or z.getinfo(names[0]).file_size > 64 * 1024 * 1024:
            raise RuntimeError("C01_AMBIGUOUS_OR_OVERSIZED_BHAVCOPY")
        text = z.read(names[0]).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text));fields = list(reader.fieldnames or [])
    required = {"TradDt", "TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"}
    if not required.issubset(fields):raise RuntimeError("OFFICIAL_BHAVCOPY_SCHEMA_MISMATCH")
    rows = {}; identities = {}; rejected = {}; seen = set(); ambiguous = set()
    for row in reader:
        if str(row.get("SctySrs") or "").strip().upper() not in {"EQ", "BE", "RR"}:continue
        session = _day(str(row.get("TradDt") or "").strip())
        if session != expected_session:raise RuntimeError("OFFICIAL_BHAVCOPY_SESSION_MISMATCH")
        seen.add(session);symbol = str(row.get("TckrSymb") or "").strip().upper()
        if not symbol:continue
        if symbol in rows or symbol in rejected:ambiguous.add(symbol)
        try:
            values = _numbers(tuple(row.get(k) for k in ("OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol")))
        except RuntimeError as exc:
            rejected[symbol] = str(exc);continue
        rows[symbol] = tuple(format(v, "f") for v in values)
        identities[symbol] = {"symbol": symbol, "isin": row.get("ISIN") or row.get("ISINCode") or None, "series": row.get("SctySrs")}
    for symbol in ambiguous:rows.pop(symbol, None)
    if seen != {expected_session}:raise RuntimeError("C01_EMPTY_OFFICIAL_SESSION")
    return rows, {"equity_session": expected_session, "schema_headers": fields, "identities": identities, "ambiguous_symbols": sorted(ambiguous), "rejected_symbols": rejected}


def _normalize_key(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _parse_index_close_report(payload: bytes, expected_session: str) -> tuple[tuple[str, str, str, str], str] | None:
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    fields = list(reader.fieldnames or [])
    normalized_fields = {_normalize_key(field) for field in fields}
    if not ({"indexname", "index"} & normalized_fields):
        raise OfficialDataParseError(f"OFFICIAL_INDEX_SCHEMA_CHANGED:MISSING_INDEX_NAME:{fields}")
    required_groups = [
        {"openindexvalue", "open"},
        {"highindexvalue", "high"},
        {"lowindexvalue", "low"},
        {"closingindexvalue", "close"},
    ]
    if any(not (group & normalized_fields) for group in required_groups):
        raise OfficialDataParseError(f"OFFICIAL_INDEX_SCHEMA_CHANGED:MISSING_OHLC:{fields}")
    names: set[str] = set()
    available_sessions: set[str] = set()
    for raw in reader:
        row = {_normalize_key(k): v for k, v in raw.items() if k is not None}
        name = " ".join(str(row.get("indexname") or row.get("index") or "").split()).upper()
        if name:
            names.add(name)
        if name != "NIFTY 50":
            continue
        parsed = None
        raw_date = str(row.get("indexdate") or row.get("date") or "").strip()
        if not raw_date:
            raise OfficialDataParseError("C01_MISSING_INDEX_SESSION")
        if raw_date:
            for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                try:
                    parsed = datetime.strptime(raw_date, fmt).date().isoformat()
                    break
                except ValueError:
                    pass
            if not parsed:
                raise OfficialDataParseError(f"OFFICIAL_INDEX_DATE_FORMAT_CHANGED:{raw_date}")
            available_sessions.add(parsed)
            if parsed != expected_session:
                continue
        def get(*keys: str) -> str:
            for key in keys:
                val = row.get(key)
                if val not in (None, ""):
                    return str(val).replace(",", "").strip()
            return ""
        vals = (get("openindexvalue", "open"), get("highindexvalue", "high"), get("lowindexvalue", "low"), get("closingindexvalue", "close"))
        if not all(vals):
            raise OfficialDataParseError("OFFICIAL_INDEX_SCHEMA_CHANGED:EMPTY_NIFTY50_OHLC")
        try:
            numeric = tuple(str(float(value)) for value in vals)
        except ValueError as exc:
            raise OfficialDataParseError(f"OFFICIAL_INDEX_SCHEMA_CHANGED:NON_NUMERIC_OHLC:{vals}") from exc
        return numeric, parsed or expected_session
    if available_sessions:
        latest = max(available_sessions)
        raise OfficialDataNotReady(
            f"OFFICIAL_NIFTY50_NOT_PUBLISHED:requested={expected_session}:latest={latest}"
        )
    sample = sorted(names)[:8]
    raise OfficialDataNotReady(
        f"OFFICIAL_NIFTY50_ROW_MISSING:requested={expected_session}:available_names={sample}"
    )


def _fetch_index_from_api(expected_session: str) -> tuple[tuple[str, str, str, str], str, dict[str, Any]]:
    d = datetime.strptime(expected_session, "%Y-%m-%d").strftime("%d-%m-%Y")
    sess = _session()
    url = f"{NSE}/api/historicalOR/indicesHistory?indexType=NIFTY%2050&from={d}&to={d}"
    try:
        warm = sess.get(NSE + "/", timeout=20)
        warm.raise_for_status()
        resp = sess.get(url, timeout=35, headers={**sess.headers, "Accept": "application/json,*/*"})
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"OFFICIAL_INDEX_DOWNLOAD_ERROR:{type(exc).__name__}:{exc}") from exc
    try:
        payload = resp.json()
    except Exception as exc:
        raise OfficialDataParseError(
            f"OFFICIAL_INDEX_JSON_INVALID:http={resp.status_code}:content_type={resp.headers.get('content-type')}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        shape = type(payload).__name__ if not isinstance(payload, dict) else sorted(payload.keys())
        raise OfficialDataParseError(f"OFFICIAL_INDEX_SCHEMA_CHANGED:EXPECTED_DATA_LIST:{shape}")
    data = payload["data"]
    if not data:
        raise OfficialDataNotReady(
            f"OFFICIAL_NIFTY50_NOT_PUBLISHED:requested={expected_session}:http={resp.status_code}:rows=0"
        )
    available_sessions: set[str] = set()
    available_names: set[str] = set()
    required = {"EOD_INDEX_NAME", "EOD_TIMESTAMP", "EOD_OPEN_INDEX_VAL", "EOD_HIGH_INDEX_VAL", "EOD_LOW_INDEX_VAL", "EOD_CLOSE_INDEX_VAL"}
    for raw in data:
        if not isinstance(raw, dict):
            raise OfficialDataParseError("OFFICIAL_INDEX_SCHEMA_CHANGED:ROW_NOT_OBJECT")
        missing = sorted(required - set(raw))
        if missing:
            raise OfficialDataParseError(f"OFFICIAL_INDEX_SCHEMA_CHANGED:MISSING_FIELDS:{missing}")
        name = " ".join(str(raw.get("EOD_INDEX_NAME") or "").split()).upper()
        if name:
            available_names.add(name)
        if name != "NIFTY 50":
            continue
        try:
            raw_date = datetime.strptime(str(raw["EOD_TIMESTAMP"]).upper(), "%d-%b-%Y").date().isoformat()
        except ValueError as exc:
            raise OfficialDataParseError(
                f"OFFICIAL_INDEX_DATE_FORMAT_CHANGED:{raw.get('EOD_TIMESTAMP')}"
            ) from exc
        available_sessions.add(raw_date)
        if raw_date != expected_session:
            continue
        try:
            vals = tuple(str(float(raw[key])) for key in (
                "EOD_OPEN_INDEX_VAL", "EOD_HIGH_INDEX_VAL", "EOD_LOW_INDEX_VAL", "EOD_CLOSE_INDEX_VAL"
            ))
        except (TypeError, ValueError) as exc:
            raise OfficialDataParseError("OFFICIAL_INDEX_SCHEMA_CHANGED:NON_NUMERIC_OHLC") from exc
        return vals, raw_date, {"url": url, "http_status": int(resp.status_code), "content_type": str(resp.headers.get("content-type") or ""), "payload_size": len(resp.content), "source_sha256": sha256(resp.content).hexdigest(), "retrieved_at": datetime.now(timezone.utc).isoformat(), "source_publication_time": None, "_raw_payload": resp.content}
    if available_sessions:
        raise OfficialDataNotReady(
            f"OFFICIAL_NIFTY50_NOT_PUBLISHED:requested={expected_session}:latest={max(available_sessions)}"
        )
    raise OfficialDataNotReady(
        f"OFFICIAL_NIFTY50_ROW_MISSING:requested={expected_session}:available_names={sorted(available_names)[:8]}"
    )


def _fetch_index(expected_session: str) -> tuple[tuple[str, str, str, str], str, dict[str, Any]]:
    d = datetime.strptime(expected_session, "%Y-%m-%d").strftime("%d%m%Y")
    report = f"{ARCHIVE}/content/indices/ind_close_all_{d}.csv"
    report_error: Exception | None = None
    try:
        payload, meta = _download_candidates([report])
        row = _parse_index_close_report(payload, expected_session)
        if row:
            vals, session = row
            return vals, session, meta
    except (OfficialDataNotReady, OfficialDataParseError, RuntimeError) as exc:
        report_error = exc
    try:
        return _fetch_index_from_api(expected_session)
    except OfficialDataNotReady as api_exc:
        report_detail = str(report_error) if report_error else "no report result"
        raise OfficialDataNotReady(f"{api_exc}; report={report_detail}") from api_exc
    except OfficialDataParseError as api_exc:
        report_detail = str(report_error) if report_error else "no report result"
        raise OfficialDataParseError(f"{api_exc}; report={report_detail}") from api_exc


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as h:
        reader = csv.DictReader(h)
        return list(reader.fieldnames or []), list(reader)


def _render_with_session(path, expected_session, values, *, authorization=None, trust=None, source_hash=None, audit=None):
    _day(expected_session);_numbers(values)
    fields, rows = _read_rows(path)
    if not {"Date", "Open", "High", "Low", "Close", "Volume"}.issubset(fields):raise RuntimeError("LOCAL_MARKET_CSV_SCHEMA_MISMATCH")
    dates = [_day(r.get("Date")) for r in rows]
    if len(set(dates)) != len(dates):raise RuntimeError("LOCAL_CACHE_DUPLICATE_SESSION")
    if dates and max(dates) > expected_session:raise RuntimeError("LOCAL_CACHE_FUTURE_SESSION")
    for row in rows:_numbers(tuple(row[k] for k in ("Open", "High", "Low", "Close", "Volume")))
    existing = next((r for r in rows if r["Date"] == expected_session), None)
    raw = path.read_bytes();new_hash = _row_hash(expected_session, values)
    old_hash = _row_hash(expected_session, tuple(existing[k] for k in ("Open", "High", "Low", "Close", "Volume"))) if existing else None
    review = None
    if existing:
        if old_hash == new_hash:
            if audit is not None:audit.append({"file": path.name, "session": expected_session, "action": "IDENTICAL_DUPLICATE", "old_row_sha256": old_hash, "new_row_sha256": new_hash})
            return raw
        review = _verify_correction(authorization, trust, expected_session, path.name, sha256(raw).hexdigest(), old_hash, new_hash, source_hash)
    newline = "\r\n" if b"\r\n" in raw else "\n"
    row = dict(existing) if existing else {k: "" for k in fields}
    row.update(dict(zip(("Date", "Open", "High", "Low", "Close", "Volume"), (expected_session, *values))))
    out = io.StringIO(newline="");writer = csv.DictWriter(out, fieldnames=fields, lineterminator=newline);writer.writerow(row)
    if existing:
        # Retain every other raw record, BOM and newline spelling unchanged.
        bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
        text = raw.decode("utf-8-sig");lines = text.splitlines(keepends=True);reader = csv.DictReader(io.StringIO(text, newline=""));start = reader.line_num
        if start == 0:reader.fieldnames;start = reader.line_num
        for old in reader:
            end = reader.line_num
            if old["Date"] == expected_session:
                result = bom + ("".join(lines[:start]) + out.getvalue() + "".join(lines[end:])).encode("utf-8");break
            start = end
        else:raise RuntimeError("C01_CORRECTION_RECORD_NOT_FOUND")
    else:
        separator = b"" if raw.endswith((b"\n", b"\r")) else newline.encode()
        result = raw + separator + out.getvalue().encode()
    if audit is not None:audit.append({"file": path.name, "session": expected_session, "action": "REVIEWED_CORRECTION" if existing else "APPEND", "old_row_sha256": old_hash, "new_row_sha256": new_hash, "source_sha256": source_hash, "review": review})
    return result


def _last_session(path: Path) -> str | None:
    try:
        _, rows = _read_rows(path)
    except Exception:
        return None
    dates = sorted({str(row.get("Date") or "")[:10] for row in rows if row.get("Date")})
    return dates[-1] if dates else None


def _write_atomic(path: Path, payload: bytes) -> None:
    tmp = path.with_name(path.name + ".sre-refresh.tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def _validate_history(path: Path, expected_session: str) -> None:
    fields, rows = _read_rows(path)
    required = {"Date", "Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(fields)):
        raise RuntimeError(f"LOCAL_MARKET_CSV_SCHEMA_MISMATCH:{path.name}:{fields}")
    for row in rows:
        _day(row.get("Date"))
        _numbers(tuple(row.get(k) for k in ("Open", "High", "Low", "Close", "Volume")))
    dates = [row["Date"] for row in rows]
    if not dates:
        raise RuntimeError(f"LOCAL_CACHE_EMPTY:{path.name}")
    duplicates = sorted(day for day, count in Counter(dates).items() if count > 1)
    if duplicates:
        raise RuntimeError(f"LOCAL_CACHE_DUPLICATE_SESSION:{path.name}:{duplicates[:5]}")
    future = sorted(day for day in dates if day > expected_session)
    if future:
        raise RuntimeError(f"LOCAL_CACHE_FUTURE_SESSION:{path.name}:{future[:5]}")
    if max(dates) != expected_session:
        raise RuntimeError(f"LOCAL_CACHE_LATEST_MISMATCH:{path.name}:{max(dates)}:{expected_session}")


def _commit_transaction(root, planned, manifest_payload, expected_session, stock_files, index_path, source_artifacts=None):
    def validate(path):
        if path.name.endswith(".csv"):_validate_history(path, expected_session)
        else:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("session") != expected_session or manifest.get("automatic_yfinance_fallback") is not False:raise RuntimeError("C01_MANIFEST_CONTRACT_FAILED")
    return publish_batch(root, [*planned, (root / ".sre_official_refresh_manifest.json", manifest_payload)], validate, source_artifacts)


def refresh_official_session(cache_roots, expected_session, *, correction_authorization=None, correction_trust=None):
    try:
        _day(expected_session)
        if not is_trading_day(date.fromisoformat(expected_session)):raise RuntimeError("C01_NOT_AN_OFFICIAL_TRADING_DAY")
    except Exception as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_SCHEMA_ERROR", stage="session", reason_code="C01_SESSION_REJECTED", reason_detail=str(exc))
    roots = [Path(p) for p in cache_roots if p and Path(p).exists()]
    root = next((p for p in roots if len(list(p.glob("*.NS.csv"))) >= 190), None)
    if root is None:return _contract(expected_session=expected_session, status="LOCAL_VERIFICATION_FAILED", stage="cache_root", reason_code="OFFICIAL_CACHE_ROOT_NOT_FOUND")
    try:
        bhav_payload, bhav_meta = _download_candidates(_bhavcopy_candidates(expected_session))
    except OfficialDataNotReady as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_NOT_READY", stage="equity_download", reason_code="OFFICIAL_REPORT_NOT_READY", reason_detail=str(exc))
    except Exception as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_DOWNLOAD_FAILED", stage="equity_download", reason_code="OFFICIAL_DOWNLOAD_FAILED", reason_detail=str(exc))
    try:
        equity_provenance = _provenance(bhav_meta, bhav_payload)
        bhav_rows, bhav_parse = _parse_bhav(bhav_payload, expected_session)
    except Exception as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_SCHEMA_ERROR", stage="equity_parse_or_provenance", reason_code="C01_OFFICIAL_INPUT_REJECTED", reason_detail=str(exc))
    try:
        nifty, index_session, index_meta = _fetch_index(expected_session)
    except OfficialDataNotReady as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_NOT_READY", stage="index_download", reason_code="OFFICIAL_INDEX_NOT_PUBLISHED", reason_detail=str(exc))
    except OfficialDataParseError as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_SCHEMA_ERROR", stage="index_parse", reason_code="OFFICIAL_INDEX_SCHEMA_CHANGED", reason_detail=str(exc))
    except Exception as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_INDEX_FAILED", stage="index_download", reason_code="OFFICIAL_INDEX_DOWNLOAD_FAILED", reason_detail=str(exc))
    try:
        index_provenance = _provenance(index_meta)
        _numbers((*nifty, "0"))
        if index_session != expected_session:raise RuntimeError("C01_INDEX_SESSION_MISMATCH")
    except Exception as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_SCHEMA_ERROR", stage="index_parse_or_provenance", reason_code="C01_OFFICIAL_INPUT_REJECTED", reason_detail=str(exc))
    try:
        with cache_guard(root):
            stock_files = sorted(root.glob("*.NS.csv"));index_path = root / "INDEX_NSEI.csv"
            if not index_path.exists():raise RuntimeError("OFFICIAL_INDEX_CACHE_MISSING")
            missing = [p.stem[:-3] for p in stock_files if p.stem[:-3] not in bhav_rows]
            if missing:
                return _contract(expected_session=expected_session, status="OFFICIAL_COVERAGE_FAILED", stage="coverage", reason_code="C01_INCOMPLETE_BATCH", reason_detail=",".join(missing), stock_files_expected=len(stock_files), stock_files_matched=len(stock_files)-len(missing), stock_coverage=(len(stock_files)-len(missing))/len(stock_files))
            planned = [];audit = []
            for path in [*stock_files, index_path]:
                symbol = path.name[:-7] if path.name.endswith(".NS.csv") else "NIFTY 50"
                values = bhav_rows[symbol] if path != index_path else (*nifty, "0")
                source = equity_provenance if path != index_path else index_provenance
                data = _render_with_session(path, expected_session, values, authorization=correction_authorization, trust=correction_trust, source_hash=source["source_sha256"], audit=audit)
                audit[-1].update({"symbol": symbol, "isin": bhav_parse.get("identities", {}).get(symbol, {}).get("isin"), "provenance": source})
                planned.append((path, data))
            changed = any(path.read_bytes() != payload for path, payload in planned)
            if not changed:
                result = _contract(expected_session=expected_session, status="ALREADY_CURRENT", stage="verified_duplicate", persisted=True, verified_latest_session=expected_session, equity_session=expected_session, index_session=expected_session, stock_files_expected=len(stock_files), stock_files_matched=len(stock_files), stock_coverage=1.0)
                result["provenance"] = {"equity": equity_provenance, "index": index_provenance};return result
            manifest = {"schema": "SRE_OFFICIAL_DAILY_REFRESH_C01_V1", "session": expected_session, "source": "NSE_CM_UDIFF_AND_NIFTY50_OFFICIAL", "bhavcopy_url": equity_provenance["url"], "index_url_or_provider": index_provenance["url"], "equity_session": expected_session, "index_session": expected_session, "stock_files": len(stock_files), "matched": len(stock_files), "coverage": 1.0, "full_universe_verified": True, "duplicate_sessions_rejected": True, "future_sessions_rejected": True, "transactional_rollback": True, "automatic_yfinance_fallback": False, "refreshed_at": datetime.now(timezone.utc).isoformat(), "provenance": {"equity": equity_provenance, "index": index_provenance}, "rows": audit}
            transaction = _commit_transaction(root, planned, (json.dumps(manifest, indent=2)+"\n").encode(), expected_session, stock_files, index_path, {"equity.zip": bhav_payload, "index-source.bin": index_meta["_raw_payload"]})
            result = _contract(expected_session=expected_session, status="REFRESHED_AND_VERIFIED", stage="verified", source_url_or_provider=equity_provenance["url"], http_status=200, equity_session=expected_session, index_session=expected_session, stock_files_expected=len(stock_files), stock_files_matched=len(stock_files), stock_coverage=1.0, persisted=True, verified_latest_session=expected_session)
            result.update(transaction_id=transaction, provenance=manifest["provenance"]);return result
    except CommittedPublicationNeedsRecovery as exc:
        return _contract(expected_session=expected_session, status="LOCAL_PERSISTENCE_FAILED", stage="commit_finalization", reason_code="C01_COMMITTED_RECOVERY_REQUIRED", reason_detail=str(exc), persisted=True)
    except OfficialRowConflict as exc:
        return _contract(expected_session=expected_session, status="LOCAL_VERIFICATION_FAILED", stage="existing_row", reason_code="C01_EXISTING_ROW_CONFLICT", reason_detail=str(exc))
    except Exception as exc:
        return _contract(expected_session=expected_session, status="LOCAL_PERSISTENCE_FAILED", stage="validation_or_commit", reason_code="C01_BATCH_NOT_PUBLISHED", reason_detail=str(exc))
