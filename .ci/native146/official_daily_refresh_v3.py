from __future__ import annotations

import csv
import io
import json
import os
import shutil
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

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
        return vals, raw_date, {"url": url, "http_status": int(resp.status_code), "content_type": str(resp.headers.get("content-type") or ""), "payload_size": len(resp.content)}
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


def _validate_history(path: Path, expected_session: str) -> None:
    fields, rows = _read_rows(path)
    required = {"Date", "Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(fields)):
        raise RuntimeError(f"LOCAL_MARKET_CSV_SCHEMA_MISMATCH:{path.name}:{fields}")
    dates = [str(row.get("Date") or "")[:10] for row in rows if row.get("Date")]
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


def _commit_transaction(
    root: Path,
    planned: list[tuple[Path, bytes]],
    manifest_payload: bytes,
    expected_session: str,
    stock_files: list[Path],
    index_path: Path,
) -> None:
    token = uuid4().hex
    staging = root / f".sre-refresh-staging-{token}"
    rollback = root / f".sre-refresh-rollback-{token}"
    staging.mkdir()
    rollback.mkdir()
    manifest_path = root / ".sre_official_refresh_manifest.json"
    all_planned = [*planned, (manifest_path, manifest_payload)]
    committed: list[tuple[Path, Path | None]] = []
    try:
        staged: list[tuple[Path, Path]] = []
        for target, payload in all_planned:
            staged_path = staging / target.name
            staged_path.write_bytes(payload)
            if target != manifest_path:
                _validate_history(staged_path, expected_session)
            staged.append((target, staged_path))

        for target, staged_path in staged:
            backup = None
            if target.exists():
                backup = rollback / target.name
                shutil.copy2(target, backup)
            os.replace(staged_path, target)
            committed.append((target, backup))

        for path in stock_files:
            _validate_history(path, expected_session)
        _validate_history(index_path, expected_session)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("session") != expected_session:
            raise RuntimeError("LOCAL_MANIFEST_SESSION_MISMATCH")
        if manifest.get("automatic_yfinance_fallback") is not False:
            raise RuntimeError("LOCAL_MANIFEST_PROVIDER_POLICY_MISMATCH")
    except Exception:
        for target, backup in reversed(committed):
            try:
                if backup and backup.exists():
                    shutil.copy2(backup, target)
                else:
                    target.unlink(missing_ok=True)
            except Exception:
                pass
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(rollback, ignore_errors=True)


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
        return _contract(expected_session=expected_session, status="OFFICIAL_NOT_READY", stage="index_download", reason_code="OFFICIAL_INDEX_NOT_PUBLISHED", reason_detail=str(exc), source_url_or_provider="NSE_INDEX_REPORT_AND_API", http_status=200 if "http=200" in str(exc) else None, equity_session=bhav_parse.get("equity_session"), stock_files_expected=stock_files_expected, schema_headers=bhav_parse.get("schema_headers"))
    except OfficialDataParseError as exc:
        return _contract(expected_session=expected_session, status="OFFICIAL_SCHEMA_ERROR", stage="index_parse", reason_code="OFFICIAL_INDEX_SCHEMA_CHANGED", reason_detail=str(exc), source_url_or_provider="NSE_INDEX_REPORT_AND_API", equity_session=bhav_parse.get("equity_session"), stock_files_expected=stock_files_expected, schema_headers=bhav_parse.get("schema_headers"))
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

    manifest = {
        "schema": "SRE_OFFICIAL_DAILY_REFRESH_V3",
        "session": expected_session,
        "source": "NSE_CM_UDIFF_AND_NIFTY50_OFFICIAL",
        "bhavcopy_url": bhav_meta.get("url"),
        "index_url_or_provider": index_meta.get("url") or "NSE_INDEX_API",
        "equity_session": bhav_parse.get("equity_session"),
        "index_session": index_session,
        "stock_files": stock_files_expected,
        "matched": matched,
        "coverage": round(coverage, 6),
        "full_universe_verified": True,
        "duplicate_sessions_rejected": True,
        "future_sessions_rejected": True,
        "transactional_rollback": True,
        "automatic_yfinance_fallback": False,
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        _commit_transaction(
            root,
            planned,
            (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
            expected_session,
            stock_files,
            index_path,
        )
    except Exception as exc:
        return _contract(expected_session=expected_session, status="LOCAL_PERSISTENCE_FAILED", stage="commit_and_reread", reason_code="LOCAL_TRANSACTION_ROLLED_BACK", reason_detail=str(exc), equity_session=bhav_parse.get("equity_session"), index_session=index_session, stock_files_expected=stock_files_expected, stock_files_matched=matched, stock_coverage=round(coverage, 6), persisted=False, schema_headers=bhav_parse.get("schema_headers"))
    return _contract(expected_session=expected_session, status="REFRESHED_AND_VERIFIED", stage="verified", source_url_or_provider=bhav_meta.get("url"), http_status=bhav_meta.get("http_status"), reason_code="OK", reason_detail="Official NSE equity and NIFTY 50 data persisted and reread", equity_session=bhav_parse.get("equity_session"), index_session=index_session, stock_files_expected=stock_files_expected, stock_files_matched=matched, stock_coverage=round(coverage, 6), persisted=True, verified_latest_session=expected_session, payload_size=bhav_meta.get("payload_size"), content_type=bhav_meta.get("content_type"), filename=bhav_meta.get("filename"), schema_headers=bhav_parse.get("schema_headers"))
