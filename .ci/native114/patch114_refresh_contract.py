from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])


def replace_between(text: str, start_marker: str, end_marker: str, new: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(label + " start marker missing")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(label + " end marker missing")
    return text[:start] + new + text[end:]


module = r'''from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

UA = "Stock-Recommendation-Engine/0.12.7 official-first daily refresh"
ARCHIVE = "https://nsearchives.nseindia.com"
NSE = "https://www.nseindia.com"


class OfficialDataNotReady(RuntimeError):
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


def _session():
    import requests
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    })
    return sess


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


def _parse_bhav(payload: bytes, expected_session: str) -> tuple[dict[str, tuple[str, str, str, str, str]], dict[str, Any]]:
    if payload[:4] != b"PK\x03\x04":
        raise RuntimeError("OFFICIAL_BHAVCOPY_NOT_ZIP")
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError("OFFICIAL_BHAVCOPY_NO_CSV")
        text = z.read(names[0]).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fields = list(reader.fieldnames or [])
    required = {"TradDt", "TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"}
    if not required.issubset(set(fields)):
        raise RuntimeError(f"OFFICIAL_BHAVCOPY_SCHEMA_MISMATCH:{fields}")
    rows: dict[str, tuple[str, str, str, str, str]] = {}
    seen_date = None
    for row in reader:
        raw_date = str(row.get("TradDt") or "").strip()[:10]
        if raw_date:
            seen_date = raw_date
        if str(row.get("SctySrs") or "").strip().upper() not in {"EQ", "BE", "RR"}:
            continue
        symbol = str(row.get("TckrSymb") or "").strip().upper()
        if not symbol:
            continue
        try:
            op = float(row["OpnPric"])
            hi = float(row["HghPric"])
            lo = float(row["LwPric"])
            cl = float(row["ClsPric"])
            vol = int(float(row.get("TtlTradgVol") or 0))
        except Exception:
            continue
        if min(op, hi, lo, cl) <= 0 or hi < max(op, lo, cl) or lo > min(op, hi, cl) or vol < 0:
            continue
        rows[symbol] = (f"{op:.10g}", f"{hi:.10g}", f"{lo:.10g}", f"{cl:.10g}", str(vol))
    if seen_date and seen_date != expected_session:
        raise RuntimeError(f"OFFICIAL_BHAVCOPY_SESSION_MISMATCH:{seen_date}:{expected_session}")
    return rows, {"equity_session": seen_date, "schema_headers": fields}


def _normalize_key(value: str) -> str:
