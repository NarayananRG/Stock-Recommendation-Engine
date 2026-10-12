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
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _parse_index_close_report(payload: bytes, expected_session: str) -> tuple[tuple[str, str, str, str], str] | None:
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    for raw in reader:
        row = {_normalize_key(k): v for k, v in raw.items() if k is not None}
        name = str(row.get("indexname") or row.get("index") or "").strip().upper()
        if name != "NIFTY 50":
            continue
        parsed = None
        raw_date = str(row.get("indexdate") or row.get("date") or "").strip()
        if raw_date:
            for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                try:
                    parsed = datetime.strptime(raw_date, fmt).date().isoformat()
                    break
                except ValueError:
                    pass
            if parsed and parsed != expected_session:
                raise RuntimeError(f"OFFICIAL_INDEX_SESSION_MISMATCH:{parsed}:{expected_session}")
        def get(*keys: str) -> str:
            for key in keys:
                val = row.get(key)
                if val not in (None, ""):
                    return str(val).replace(",", "").strip()
            return ""
        vals = (get("openindexvalue", "open"), get("highindexvalue", "high"), get("lowindexvalue", "low"), get("closingindexvalue", "close"))
        if all(vals):
            return vals, parsed or expected_session
    return None


def _fetch_index_from_api(expected_session: str) -> tuple[tuple[str, str, str, str], str, dict[str, Any]]:
    d = datetime.strptime(expected_session, "%Y-%m-%d").strftime("%d-%m-%Y")
    sess = _session()
    try:
        sess.get(NSE + "/", timeout=20)
        url = f"{NSE}/api/historicalOR/indicesHistory?indexType=NIFTY%2050&from={d}&to={d}"
        resp = sess.get(url, timeout=35, headers={**sess.headers, "Accept": "application/json,*/*"})
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        raise OfficialDataNotReady(f"OFFICIAL_NIFTY50_NOT_READY:{type(exc).__name__}:{exc}") from exc
    for raw in payload.get("data", []):
        if str(raw.get("EOD_INDEX_NAME") or "").upper() != "NIFTY 50":
            continue
        raw_date = datetime.strptime(raw["EOD_TIMESTAMP"], "%d-%b-%Y").date().isoformat()
        if raw_date != expected_session:
            continue
        vals = (str(raw["EOD_OPEN_INDEX_VAL"]), str(raw["EOD_HIGH_INDEX_VAL"]), str(raw["EOD_LOW_INDEX_VAL"]), str(raw["EOD_CLOSE_INDEX_VAL"]))
        return vals, raw_date, {"url": url, "http_status": int(resp.status_code), "content_type": str(resp.headers.get("content-type") or ""), "payload_size": len(resp.content)}
    raise OfficialDataNotReady("OFFICIAL_NIFTY50_NOT_READY:NO_ROW")


def _fetch_index(expected_session: str) -> tuple[tuple[str, str, str, str], str, dict[str, Any]]:
    d = datetime.strptime(expected_session, "%Y-%m-%d").strftime("%d%m%Y")
    report = f"{ARCHIVE}/content/indices/ind_close_all_{d}.csv"
    try:
        payload, meta = _download_candidates([report])
        row = _parse_index_close_report(payload, expected_session)
        if row:
            vals, session = row
            return vals, session, meta
    except OfficialDataNotReady:
        pass
    return _fetch_index_from_api(expected_session)


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as h:
        reader = csv.DictReader(h)
        return list(reader.fieldnames or []), list(reader)


def _render_with_session(path: Path, expected_session: str, values: tuple[str, str, str, str, str]) -> bytes:
    fields, rows = _read_rows(path)
    required = ["Date", "Open", "High", "Low", "Close", "Volume"]
    if not all(x in fields for x in required):
        raise RuntimeError(f"LOCAL_MARKET_CSV_SCHEMA_MISMATCH:{path.name}:{fields}")
    out = [row for row in rows if str(row.get("Date") or "")[:10] != expected_session]
    op, hi, lo, cl, vol = values
    out.append({"Date": expected_session, "Open": op, "High": hi, "Low": lo, "Close": cl, "Volume": vol})
    out.sort(key=lambda row: str(row.get("Date") or ""))
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in out:
        writer.writerow({key: row.get(key, "") for key in fields})
    return buf.getvalue().encode("utf-8")


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


def refresh_official_session(cache_roots: list[str], expected_session: str) -> dict[str, Any]:
    roots = [Path(p) for p in cache_roots if p and Path(p).exists()]
    root = next((p for p in roots if len(list(p.glob("*.NS.csv"))) >= 190), None)
    if root is None:
        return _contract(expected_session=expected_session, status="LOCAL_VERIFICATION_FAILED", stage="cache_root", reason_code="OFFICIAL_CACHE_ROOT_NOT_FOUND", reason_detail="No official cache root with at least 190 *.NS.csv files was found")

    stock_files = sorted(root.glob("*.NS.csv"))
    stock_files_expected = len(stock_files)
    try:
        bhav_payload, bhav_meta = _download_candidates(_bhavcopy_candidates(expected_session))
    except OfficialDataNotReady as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_NOT_READY", stage="equity_download", reason_code="OFFICIAL_REPORT_NOT_READY", reason_detail=str(exc), stock_files_expected=stock_files_expected)
    except Exception as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_DOWNLOAD_FAILED", stage="equity_download", reason_code="OFFICIAL_DOWNLOAD_FAILED", reason_detail=str(exc), stock_files_expected=stock_files_expected)

    try:
        bhav_rows, bhav_parse = _parse_bhav(bhav_payload, expected_session)
    except Exception as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_SCHEMA_ERROR", stage="equity_parse", reason_code="OFFICIAL_BHAVCOPY_SCHEMA_ERROR", reason_detail=str(exc), source_url_or_provider=bhav_meta.get("url"), http_status=bhav_meta.get("http_status"), payload_size=bhav_meta.get("payload_size"), content_type=bhav_meta.get("content_type"), filename=bhav_meta.get("filename"), stock_files_expected=stock_files_expected)

    try:
        nifty, index_session, index_meta = _fetch_index(expected_session)
    except OfficialDataNotReady as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_NOT_READY", stage="index_download", reason_code="OFFICIAL_INDEX_NOT_READY", reason_detail=str(exc), source_url_or_provider=bhav_meta.get("url"), http_status=bhav_meta.get("http_status"), equity_session=bhav_parse.get("equity_session"), stock_files_expected=stock_files_expected, schema_headers=bhav_parse.get("schema_headers"))
    except Exception as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_INDEX_FAILED", stage="index_download", reason_code="OFFICIAL_INDEX_FAILED", reason_detail=str(exc), source_url_or_provider=bhav_meta.get("url"), http_status=bhav_meta.get("http_status"), equity_session=bhav_parse.get("equity_session"), stock_files_expected=stock_files_expected, schema_headers=bhav_parse.get("schema_headers"))

    planned: list[tuple[Path, bytes]] = []
    missing: list[str] = []
    for path in stock_files:
        symbol = path.name[:-7].upper() if path.name.upper().endswith(".NS.CSV") else path.stem.upper()
        values = bhav_rows.get(symbol)
        if values is None:
            missing.append(symbol)
            continue
        try:
            planned.append((path, _render_with_session(path, expected_session, values)))
        except Exception as exc:
            return _contract(expected_session=expected_session, status="LOCAL_PERSISTENCE_FAILED", stage="stage_equity", reason_code="LOCAL_MARKET_CSV_RENDER_FAILED", reason_detail=str(exc), equity_session=bhav_parse.get("equity_session"), index_session=index_session, stock_files_expected=stock_files_expected, stock_files_matched=len(planned), stock_coverage=round(len(planned) / max(1, stock_files_expected), 6), schema_headers=bhav_parse.get("schema_headers"))

    matched = len(planned)
    coverage = matched / max(1, stock_files_expected)
    if stock_files_expected < 190 or coverage < 0.95:
        return _contract(expected_session=expected_session, status="OFFICIAL_COVERAGE_FAILED", stage="coverage", reason_code="OFFICIAL_SESSION_COVERAGE_TOO_LOW", reason_detail=f"Matched {matched}/{stock_files_expected}; missing sample: {missing[:30]}", equity_session=bhav_parse.get("equity_session"), index_session=index_session, stock_files_expected=stock_files_expected, stock_files_matched=matched, stock_coverage=round(coverage, 6), schema_headers=bhav_parse.get("schema_headers"))

    index_path = root / "INDEX_NSEI.csv"
    if not index_path.exists():
        return _contract(expected_session=expected_session, status="OFFICIAL_INDEX_FAILED", stage="index_cache", reason_code="OFFICIAL_INDEX_CACHE_MISSING", reason_detail=str(index_path), equity_session=bhav_parse.get("equity_session"), index_session=index_session, stock_files_expected=stock_files_expected, stock_files_matched=matched, stock_coverage=round(coverage, 6), schema_headers=bhav_parse.get("schema_headers"))
    try:
        planned.append((index_path, _render_with_session(index_path, expected_session, (*nifty, "0"))))
    except Exception as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_INDEX_FAILED", stage="stage_index", reason_code="OFFICIAL_INDEX_RENDER_FAILED", reason_detail=str(exc), equity_session=bhav_parse.get("equity_session"), index_session=index_session, stock_files_expected=stock_files_expected, stock_files_matched=matched, stock_coverage=round(coverage, 6), schema_headers=bhav_parse.get("schema_headers"))

    staged_latest = [_last_session(path) for path, _ in planned[: min(5, len(planned))]]
    if any(session and session > expected_session for session in staged_latest):
        return _contract(expected_session=expected_session, status="LOCAL_VERIFICATION_FAILED", stage="stage_verify", reason_code="LOCAL_CACHE_HAS_FUTURE_SESSION", reason_detail=str(staged_latest), equity_session=bhav_parse.get("equity_session"), index_session=index_session, stock_files_expected=stock_files_expected, stock_files_matched=matched, stock_coverage=round(coverage, 6), schema_headers=bhav_parse.get("schema_headers"))

    try:
        for path, payload in planned:
            _write_atomic(path, payload)
    except Exception as exc:
        return _contract(expected_session=expected_session, status="LOCAL_PERSISTENCE_FAILED", stage="commit", reason_code="LOCAL_ATOMIC_WRITE_FAILED", reason_detail=str(exc), equity_session=bhav_parse.get("equity_session"), index_session=index_session, stock_files_expected=stock_files_expected, stock_files_matched=matched, stock_coverage=round(coverage, 6), schema_headers=bhav_parse.get("schema_headers"))

    verified = _last_session(stock_files[0]) if stock_files else None
    verified_index = _last_session(index_path)
    if verified != expected_session or verified_index != expected_session:
        return _contract(expected_session=expected_session, status="LOCAL_VERIFICATION_FAILED", stage="reread", reason_code="LOCAL_REREAD_SESSION_MISMATCH", reason_detail=f"equity={verified} index={verified_index}", equity_session=bhav_parse.get("equity_session"), index_session=index_session, stock_files_expected=stock_files_expected, stock_files_matched=matched, stock_coverage=round(coverage, 6), persisted=True, verified_latest_session=verified, schema_headers=bhav_parse.get("schema_headers"))

    manifest = {
        "schema": "SRE_OFFICIAL_DAILY_REFRESH_V2",
        "session": expected_session,
        "source": "NSE_CM_UDIFF_AND_NIFTY50_OFFICIAL",
        "bhavcopy_url": bhav_meta.get("url"),
        "index_url_or_provider": index_meta.get("url") or "NSE_INDEX_API",
        "stock_files": stock_files_expected,
        "matched": matched,
        "coverage": round(coverage, 6),
        "automatic_yfinance_fallback": False,
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_atomic(root / ".sre_official_refresh_manifest.json", (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    return _contract(expected_session=expected_session, status="REFRESHED_AND_VERIFIED", stage="verified", source_url_or_provider=bhav_meta.get("url"), http_status=bhav_meta.get("http_status"), reason_code="OK", reason_detail="Official NSE equity and NIFTY 50 data persisted and reread", equity_session=bhav_parse.get("equity_session"), index_session=index_session, stock_files_expected=stock_files_expected, stock_files_matched=matched, stock_coverage=round(coverage, 6), persisted=True, verified_latest_session=expected_session, payload_size=bhav_meta.get("payload_size"), content_type=bhav_meta.get("content_type"), filename=bhav_meta.get("filename"), schema_headers=bhav_parse.get("schema_headers"))
'''

(root / "stock_app" / "official_daily_refresh.py").write_text(module, encoding="utf-8")

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
daily_block = r'''    def _refresh_official_first_market_data(self) -> dict[str, Any]:
        expected = self.expected_market_session()["expected_market_session"]
        try:
            before = self.data_source_status()
            active_before = dict(before.get("active") or {})
            if before.get("mode") == "REAL_OFFICIAL_DATA" and active_before.get("latest_session") == expected:
                return {
                    "status": "PASS",
                    "refresh_result": {
                        "expected_session": expected,
                        "status": "ALREADY_CURRENT",
                        "stage": "precheck",
                        "source": "LOCAL_OFFICIAL_CACHE",
                        "source_url_or_provider": None,
                        "http_status": None,
                        "reason_code": "LOCAL_OFFICIAL_CACHE_CURRENT",
                        "reason_detail": f"Local official cache already contains {expected}",
                        "equity_session": expected,
                        "index_session": expected,
                        "stock_files_expected": None,
                        "stock_files_matched": None,
                        "stock_coverage": active_before.get("history_coverage"),
                        "persisted": True,
                        "verified_latest_session": expected,
                        "automatic_yfinance_fallback": False,
                    },
                    "source": before,
                    "automatic_yfinance_fallback": False,
                }
            from stock_app.official_daily_refresh import refresh_official_session
            refresh = refresh_official_session(list(active_before.get("cache_roots") or []), expected)
            if refresh.get("status") == "REFRESHED_AND_VERIFIED":
                for attr in ("_cache", "cache", "_history_cache", "_data_cache"):
                    value = getattr(self.prices, attr, None)
                    if isinstance(value, dict):
                        value.clear()
            source = self.data_source_status()
            latest = (source.get("active") or {}).get("latest_session")
            if source.get("mode") == "REAL_OFFICIAL_DATA" and latest == expected:
                status = "PASS"
            elif refresh.get("status") == "OFFICIAL_NOT_READY":
                status = "NOT_READY"
            else:
                status = "ERROR"
            if status == "PASS" and refresh.get("status") != "REFRESHED_AND_VERIFIED":
                refresh = {**refresh, "status": "LOCAL_VERIFICATION_FAILED", "reason_code": "REFRESH_VERIFICATION_CONTRACT_MISMATCH", "reason_detail": "PASS requires REFRESHED_AND_VERIFIED or ALREADY_CURRENT"}
                status = "ERROR"
            return {
                "status": status,
                "refresh_result": refresh,
                "source": source,
                "automatic_yfinance_fallback": False,
            }
        except Exception as exc:
            source = self.data_source_status()
            return {
                "status": "ERROR",
                "error": str(exc),
                "refresh_result": {
                    "expected_session": expected,
                    "status": "OFFICIAL_DOWNLOAD_FAILED",
                    "stage": "exception",
                    "source": "NSE_OFFICIAL",
                    "reason_code": type(exc).__name__,
                    "reason_detail": str(exc),
                    "automatic_yfinance_fallback": False,
                },
                "source": source,
                "automatic_yfinance_fallback": False,
            }

    def _daily_data_gate(self) -> dict[str, Any]:
        expected = self.expected_market_session()
        refresh = self._refresh_official_first_market_data()
        source = refresh.get("source") or self.data_source_status()
        active = dict(source.get("active") or {})
        latest = active.get("latest_session")
        refresh_result = dict(refresh.get("refresh_result") or {})
        status = str(refresh_result.get("status") or "").upper()
        ready = bool(source.get("mode") == "REAL_OFFICIAL_DATA" and latest == expected["expected_market_session"] and refresh.get("status") == "PASS")
        if ready:
            freshness_gate = "PASS"
            freshness_status = "CURRENT"
            blocked = None
        elif status == "OFFICIAL_NOT_READY":
            freshness_gate = "BLOCKED"
            freshness_status = "OFFICIAL DATA NOT READY"
            blocked = "OFFICIAL_DATA_NOT_READY"
        else:
            freshness_gate = "BLOCKED"
            freshness_status = "OFFICIAL SOURCE ERROR" if refresh.get("status") == "ERROR" else "OFFICIAL DATA NOT READY"
            blocked = "OFFICIAL_SOURCE_ERROR" if refresh.get("status") == "ERROR" else "OFFICIAL_DATA_NOT_READY"
        detail = refresh.get("error") or refresh_result.get("reason_detail") or refresh_result.get("reason_code")
        if not detail:
            detail = "No official refresh detail was returned"
        return {
            "source": source,
            **expected,
            "target_session": expected["expected_market_session"],
            "latest_official_session": latest,
            "data_freshness": freshness_status,
            "freshness_gate": freshness_gate,
            "official_mode": source.get("mode") == "REAL_OFFICIAL_DATA",
            "analysis_data_current": ready,
            "universe_coverage": active.get("history_coverage"),
            "identity_coverage": active.get("identity_coverage"),
            "ready": ready,
            "blocked_reason": blocked,
            "refresh_error_detail": detail,
            "refresh_status": refresh,
        }

'''
s = replace_between(s, "    def _refresh_official_first_market_data", "    def post_close_daily_status", daily_block, "daily refresh gate")

status_block = r'''    def post_close_daily_status(self) -> dict[str, Any]:
        gate = self._daily_data_gate()
        state = self._read_daily_state()
        latest_success = state.get("last_successful_run")
        refresh_result = ((gate.get("refresh_status") or {}).get("refresh_result") or {})
        refresh_status = str(refresh_result.get("status") or "")
        if refresh_status in {"REFRESHED_AND_VERIFIED"}:
            refresh_label = "REFRESHED & VERIFIED"
        elif refresh_status == "ALREADY_CURRENT":
            refresh_label = "ALREADY CURRENT"
        elif refresh_status == "OFFICIAL_NOT_READY":
            refresh_label = "NOT READY"
        elif refresh_status:
            refresh_label = "FAILED"
        else:
            refresh_label = "UNKNOWN"
        source_detail = refresh_result.get("reason_detail") or gate.get("refresh_error_detail") or "No official refresh detail was returned"
        if refresh_status in {"REFRESHED_AND_VERIFIED", "ALREADY_CURRENT"}:
            source_detail = f"NSE OFFICIAL - {refresh_result.get('verified_latest_session') or gate.get('latest_official_session') or gate.get('target_session')}"
        return {
            "schema": "SRE_POST_CLOSE_DAILY_FLOW_STATUS_V2",
            "authority": "FROZEN_PRODUCTION_RECOMMENDATIONS_UNCHANGED",
            "current_calendar_date": gate.get("current_calendar_date"),
            "expected_market_session": gate.get("expected_market_session"),
            "target_session": gate["target_session"],
            "latest_available_official_session": gate["latest_official_session"],
            "active_analysis_session": None if not self.ui_run_input() else self.ui_run_input().get("market_session"),
            "data_freshness": gate["data_freshness"],
            "freshness_gate": gate["freshness_gate"],
            "universe_coverage": gate["universe_coverage"],
            "identity_coverage": gate["identity_coverage"],
            "run_status": "READY" if gate["ready"] else ("BLOCKED - OFFICIAL SOURCE ERROR" if gate.get("blocked_reason") == "OFFICIAL_SOURCE_ERROR" else "BLOCKED - OFFICIAL DATA NOT READY"),
            "recommendation_count": len(self.latest_prediction_rows(limit=100)),
            "executable_count": len([x for x in self.latest_prediction_rows(limit=100) if x.get("executable")]),
            "shadow_analysis_status": "Technical V2/Fundamental V3/Combined V2 remain SHADOW_ONLY",
            "validation_snapshot_status": "SUPPORTED_WHEN_MONITORING_ROWS_EXIST",
            "last_successful_daily_run": latest_success,
            "last_result": state.get("last_result"),
            "refresh_label": refresh_label,
            "source_detail": source_detail,
            "refresh_error_detail": gate.get("refresh_error_detail"),
            "refresh_status": gate.get("refresh_status"),
            "no_yfinance": True,
            "automatic_yfinance_fallback": False,
        }

'''
s = replace_between(s, "    def post_close_daily_status", "    def run_post_close_daily_flow", status_block, "daily status")
api.write_text(s, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
t = replace_between(
    t,
    "function renderPostCloseDaily",
    "function renderToday",
    """function renderPostCloseDaily(x){const el=$('#postCloseDailyStatus');if(!el)return;x=x||{};const last=x.last_successful_daily_run||{};const blocked=String(x.run_status||'').startsWith('BLOCKED');const error=String(x.run_status||'').includes('SOURCE ERROR')||String(x.refresh_label||'').includes('FAILED');const cls=error?'error':(blocked?'blocked':(String(x.freshness_gate||'')==='PASS'?'success':'idle'));const ring=document.querySelector('.today-banner .action-ring');if(ring){ring.classList.remove('success','blocked','error','idle');ring.classList.add(cls);const span=ring.querySelector('span');if(span)span.textContent=cls==='success'?'✓':(cls==='error'?'!':(cls==='blocked'?'!':'•'))}el.className='daily-flow-grid '+cls;el.innerHTML=[['Current date',x.current_calendar_date||'—'],['Expected session',x.expected_market_session||x.target_session||'—'],['Latest official session',x.latest_available_official_session||'—'],['Active analysis session',x.active_analysis_session||'—'],['Data freshness',(x.freshness_gate||'—')+' / '+(x.data_freshness||'—')],['Run status',x.run_status||'—'],['Refresh',x.refresh_label||'—'],['Source detail',x.source_detail||x.refresh_error_detail||'—'],['Recommendations',String((blocked?'previous ':'')+(x.recommendation_count??0))],['Executable',String((blocked?'previous ':'')+(x.executable_count??0))],['Shadow analysis',x.shadow_analysis_status||'—'],['Validation snapshot',x.validation_snapshot_status||'—'],['Last successful run',last.run_id?last.run_id+' · '+(last.market_session||'—'):'—']].map(([k,v])=>`<div><span>${escapeHtml(k)}</span><strong>${escapeHtml(String(v))}</strong></div>`).join('')}
""",
    "post-close renderer",
)
js.write_text(t, encoding="utf-8")
css = root / "modern_ui" / "frontend" / "styles.css"
c = css.read_text(encoding="utf-8")
if ".daily-flow-grid.error" not in c:
    c += """
.action-ring.success{background:rgba(15,118,110,.12);color:#0f766e}.action-ring.blocked{background:rgba(217,119,6,.14);color:#b45309}.action-ring.error{background:rgba(185,28,28,.12);color:#b91c1c}.action-ring.idle{background:rgba(100,116,139,.12);color:#64748b}
.daily-flow-grid.blocked>div{border-color:rgba(217,119,6,.28);background:rgba(254,243,199,.34)}.daily-flow-grid.error>div{border-color:rgba(185,28,28,.24);background:rgba(254,226,226,.36)}.daily-flow-grid.success>div{border-color:rgba(15,118,110,.22);background:rgba(204,251,241,.26)}
"""
css.write_text(c, encoding="utf-8")

policy = root / "phase7" / "refresh_contract_0127.json"
policy.write_text("""{
  "schema": "SRE_PHASE7_REFRESH_CONTRACT_0127",
  "release": "0.12.7-phase7-official-source-diagnostics-hotfix",
  "statuses": [
    "ALREADY_CURRENT",
    "REFRESHED_AND_VERIFIED",
    "OFFICIAL_NOT_READY",
    "OFFICIAL_DOWNLOAD_FAILED",
    "OFFICIAL_SCHEMA_ERROR",
    "OFFICIAL_COVERAGE_FAILED",
    "OFFICIAL_INDEX_FAILED",
    "LOCAL_PERSISTENCE_FAILED",
    "LOCAL_VERIFICATION_FAILED"
  ],
  "refreshed_and_verified_requires_latest_equals_expected": true,
  "partial_update_safety": "stage_then_atomic_write_no_equity_commit_before_index",
  "automatic_yfinance_fallback": false,
  "production_recommendation_authority_changed": false,
  "production_rank_authority_changed": false,
  "technical_v2_authority": "SHADOW_ONLY",
  "fundamental_v3_authority": "SHADOW_ONLY",
  "combined_v2_authority": "SHADOW_ONLY"
}
""", encoding="utf-8")

assert "REFRESHED_AND_VERIFIED" in (root / "stock_app" / "official_daily_refresh.py").read_text(encoding="utf-8")
assert "refresh_label" in api.read_text(encoding="utf-8")
assert "refresh_label" in js.read_text(encoding="utf-8")
assert "import yfinance" not in (root / "stock_app" / "official_daily_refresh.py").read_text(encoding="utf-8").lower()
print("0.12.7 refresh contract consistency hotfix applied")
