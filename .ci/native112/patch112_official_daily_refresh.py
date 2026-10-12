from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])


def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(label + " contract missing")
    return text.replace(old, new, 1)


module = r'''from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from datetime import date, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

UA = "Stock-Recommendation-Engine/0.12.5 official-first daily refresh"
ARCHIVE = "https://nsearchives.nseindia.com"
NSE = "https://www.nseindia.com"


class OfficialDataNotReady(RuntimeError):
    pass


def _request(url: str, *, timeout: int = 35) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/zip,text/csv,application/json,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except HTTPError as exc:
        if exc.code in {400, 404}:
            raise OfficialDataNotReady(f"OFFICIAL_REPORT_NOT_READY:HTTP_{exc.code}:{url}") from exc
        raise
    except URLError as exc:
        raise RuntimeError(f"OFFICIAL_NETWORK_ERROR:{exc}") from exc
    if not body:
        raise OfficialDataNotReady(f"OFFICIAL_REPORT_EMPTY:{url}")
    return body


def _parse_bhav(payload: bytes, expected_session: str) -> dict[str, tuple[str, str, str, str, str]]:
    if payload[:4] != b"PK\x03\x04":
        raise RuntimeError("OFFICIAL_BHAVCOPY_NOT_ZIP")
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError("OFFICIAL_BHAVCOPY_NO_CSV")
        text = z.read(names[0]).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fields = set(reader.fieldnames or [])
    required = {"TradDt", "TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"}
    if not required.issubset(fields):
        raise RuntimeError(f"OFFICIAL_BHAVCOPY_SCHEMA_MISMATCH:{sorted(fields)}")
    rows: dict[str, tuple[str, str, str, str, str]] = {}
    seen_date = None
    for row in reader:
        raw_date = str(row.get("TradDt") or "").strip()[:10]
        if raw_date:
            seen_date = raw_date
        series = str(row.get("SctySrs") or "").strip().upper()
        if series not in {"EQ", "BE", "RR"}:
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
    return rows


def _normalize_key(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _parse_index_close_report(payload: bytes, expected_session: str) -> tuple[str, str, str, str] | None:
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    for raw in reader:
        row = {_normalize_key(k): v for k, v in raw.items() if k is not None}
        name = str(row.get("indexname") or row.get("index") or "").strip().upper()
        if name != "NIFTY 50":
            continue
        raw_date = str(row.get("indexdate") or row.get("date") or "").strip()
        if raw_date:
            parsed = None
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
        op = get("openindexvalue", "open")
        hi = get("highindexvalue", "high")
        lo = get("lowindexvalue", "low")
        cl = get("closingindexvalue", "close")
        if all((op, hi, lo, cl)):
            return op, hi, lo, cl
    return None


def _fetch_index_from_api(expected_session: str) -> tuple[str, str, str, str]:
    d = datetime.strptime(expected_session, "%Y-%m-%d").strftime("%d-%m-%Y")
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    headers = {
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        opener.open(Request(NSE + "/", headers=headers), timeout=20).read(256)
        url = f"{NSE}/api/historicalOR/indicesHistory?indexType={quote('NIFTY 50')}&from={d}&to={d}"
        body = opener.open(Request(url, headers={**headers, "Accept": "application/json,*/*"}), timeout=30).read()
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise OfficialDataNotReady(f"OFFICIAL_NIFTY50_NOT_READY:{exc}") from exc
    for raw in payload.get("data", []):
        if str(raw.get("EOD_INDEX_NAME") or "").upper() != "NIFTY 50":
            continue
        raw_date = datetime.strptime(raw["EOD_TIMESTAMP"], "%d-%b-%Y").date().isoformat()
        if raw_date != expected_session:
            continue
        return (
            str(raw["EOD_OPEN_INDEX_VAL"]),
            str(raw["EOD_HIGH_INDEX_VAL"]),
            str(raw["EOD_LOW_INDEX_VAL"]),
            str(raw["EOD_CLOSE_INDEX_VAL"]),
        )
    raise OfficialDataNotReady("OFFICIAL_NIFTY50_NOT_READY:NO_ROW")


def _fetch_index(expected_session: str) -> tuple[str, str, str, str]:
    d = datetime.strptime(expected_session, "%Y-%m-%d").strftime("%d%m%Y")
    report = f"{ARCHIVE}/content/indices/ind_close_all_{d}.csv"
    try:
        row = _parse_index_close_report(_request(report), expected_session)
        if row:
            return row
    except OfficialDataNotReady:
        pass
    return _fetch_index_from_api(expected_session)


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as h:
        reader = csv.DictReader(h)
        fields = list(reader.fieldnames or [])
        return fields, list(reader)


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


def _write_atomic(path: Path, payload: bytes) -> None:
    tmp = path.with_name(path.name + ".sre-refresh.tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def refresh_official_session(cache_roots: list[str], expected_session: str) -> dict[str, Any]:
    roots = [Path(p) for p in cache_roots if p and Path(p).exists()]
    root = next((p for p in roots if len(list(p.glob("*.NS.csv"))) >= 190), None)
    if root is None:
        return {"status": "ERROR", "reason": "OFFICIAL_CACHE_ROOT_NOT_FOUND", "automatic_yfinance_fallback": False}

    name = f"BhavCopy_NSE_CM_0_0_0_{expected_session.replace('-', '')}_F_0000.csv.zip"
    bhav_url = f"{ARCHIVE}/content/cm/{name}"
    try:
        bhav_rows = _parse_bhav(_request(bhav_url), expected_session)
        nifty = _fetch_index(expected_session)
    except OfficialDataNotReady as exc:
        return {
            "status": "NOT_READY",
            "reason": str(exc),
            "expected_session": expected_session,
            "source": "NSE_OFFICIAL",
            "automatic_yfinance_fallback": False,
        }

    stock_files = sorted(root.glob("*.NS.csv"))
    planned: list[tuple[Path, bytes]] = []
    matched = 0
    missing: list[str] = []
    for path in stock_files:
        symbol = path.name[:-7].upper() if path.name.upper().endswith(".NS.CSV") else path.stem.upper()
        values = bhav_rows.get(symbol)
        if values is None:
            missing.append(symbol)
            continue
        planned.append((path, _render_with_session(path, expected_session, values)))
        matched += 1

    coverage = matched / max(1, len(stock_files))
    if len(stock_files) < 190 or coverage < 0.95:
        return {
            "status": "ERROR",
            "reason": "OFFICIAL_SESSION_COVERAGE_TOO_LOW",
            "expected_session": expected_session,
            "stock_files": len(stock_files),
            "matched": matched,
            "coverage": round(coverage, 6),
            "missing": missing[:30],
            "automatic_yfinance_fallback": False,
        }

    index_path = root / "INDEX_NSEI.csv"
    if not index_path.exists():
        return {"status": "ERROR", "reason": "OFFICIAL_INDEX_CACHE_MISSING", "automatic_yfinance_fallback": False}
    planned.append((index_path, _render_with_session(index_path, expected_session, (*nifty, "0"))))

    for path, payload in planned:
        _write_atomic(path, payload)

    manifest = {
        "schema": "SRE_OFFICIAL_DAILY_REFRESH_V1",
        "session": expected_session,
        "source": "NSE_CM_UDIFF_AND_NIFTY50_OFFICIAL",
        "bhavcopy_url": bhav_url,
        "stock_files": len(stock_files),
        "matched": matched,
        "coverage": round(coverage, 6),
        "automatic_yfinance_fallback": False,
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_atomic(root / ".sre_official_refresh_manifest.json", (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    return {"status": "REFRESHED", **manifest}
'''
mod = root / "stock_app" / "official_daily_refresh.py"
mod.write_text(module, encoding="utf-8")

api = root / "modern_ui" / "api.py"
s = api.read_text(encoding="utf-8")
s = repl(
    s,
    'APP_VERSION = "0.12.4-phase7-session-freshness-windows-hardening"',
    'APP_VERSION = "0.12.6-phase7-upgrade-startup-hotfix"',
    "backend version",
)
old = '''    def _refresh_official_first_market_data(self) -> dict[str, Any]:
        # Local desktop builds can only use configured official data providers.
        # No automatic yfinance fallback is permitted.
        try:
            return {"status": "PASS", "source": self.data_source_status(), "automatic_yfinance_fallback": False}
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc), "automatic_yfinance_fallback": False}
'''
new = '''    def _refresh_official_first_market_data(self) -> dict[str, Any]:
        # Refresh the expected completed NSE session from official sources only.
        # There is deliberately no automatic yfinance fallback.
        expected = self.expected_market_session()["expected_market_session"]
        try:
            before = self.data_source_status()
            active = dict(before.get("active") or {})
            if before.get("mode") == "REAL_OFFICIAL_DATA" and active.get("latest_session") == expected:
                return {
                    "status": "PASS",
                    "refresh_result": "ALREADY_CURRENT",
                    "source": before,
                    "automatic_yfinance_fallback": False,
                }
            from stock_app.official_daily_refresh import refresh_official_session
            refresh = refresh_official_session(list(active.get("cache_roots") or []), expected)
            # Price/history readers may cache parsed frames. Clear only cache-like
            # dictionaries after an official refresh; no scoring state is changed.
            if refresh.get("status") == "REFRESHED":
                for attr in ("_cache", "cache", "_history_cache", "_data_cache"):
                    value = getattr(self.prices, attr, None)
                    if isinstance(value, dict):
                        value.clear()
            source = self.data_source_status()
            latest = (source.get("active") or {}).get("latest_session")
            if source.get("mode") == "REAL_OFFICIAL_DATA" and latest == expected:
                status = "PASS"
            elif refresh.get("status") == "NOT_READY":
                status = "NOT_READY"
            else:
                status = "ERROR"
            return {
                "status": status,
                "refresh_result": refresh,
                "source": source,
                "automatic_yfinance_fallback": False,
            }
        except Exception as exc:
            return {
                "status": "ERROR",
                "error": str(exc),
                "source": self.data_source_status(),
                "automatic_yfinance_fallback": False,
            }
'''
s = repl(s, old, new, "official refresh implementation")
api.write_text(s, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
t = t.replace(
    "['Run status',x.run_status||'—']",
    "['Run status',x.run_status||'—'],['Refresh',x.last_result?.refresh_status?.refresh_result?.status||x.last_result?.refresh_status?.refresh_result||'official-first']",
)
js.write_text(t, encoding="utf-8")

policy = root / "phase7" / "official_daily_refresh_0125.json"
policy.write_text("""{
  "schema": "SRE_PHASE7_OFFICIAL_DAILY_REFRESH_0125",
  "release": "0.12.6-phase7-upgrade-startup-hotfix",
  "source_priority": ["NSE_OFFICIAL_CM_UDIFF", "NSE_OFFICIAL_NIFTY50"],
  "automatic_yfinance_fallback": false,
  "minimum_stock_coverage": 0.95,
  "requires_index_session_match": true,
  "production_recommendation_authority_changed": false,
  "production_rank_authority_changed": false,
  "technical_v2_authority": "SHADOW_ONLY",
  "fundamental_v3_authority": "SHADOW_ONLY",
  "combined_v2_authority": "SHADOW_ONLY"
}
""", encoding="utf-8")

assert "official_daily_refresh" in api.read_text(encoding="utf-8")
assert "ALREADY_CURRENT" in api.read_text(encoding="utf-8")
assert "automatic_yfinance_fallback" in mod.read_text(encoding="utf-8")
assert "import yfinance" not in module.lower()
print("0.12.5 official daily refresh hotfix applied")
