from __future__ import annotations

import csv
import io
import json
import os
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests

START = date(2024, 10, 1)
TODAY = date.today()
MAX_WORKERS = 6
BASE = "https://www.nseindia.com"
ARCHIVE = "https://nsearchives.nseindia.com/content/cm"
REPORT_NAME = "CM-UDiFF Common Bhavcopy Final (zip)"
UA = "Stock-Recommendation-Engine Phase6 official market bundle/0.12.0"

OUT = Path(os.environ.get("PHASE6_MARKET_OUT", "phase6_market_bundle")).resolve()
RAW = OUT / "_raw_bhavcopy"
ROOT = OUT / "payload"
OFFICIAL = ROOT / "data" / "official"
CONSTITUENT_DIR = OFFICIAL / "nifty200"
MASTER_DIR = OFFICIAL / "nse" / "security_master"

for p in (RAW, CONSTITUENT_DIR, MASTER_DIR):
    p.mkdir(parents=True, exist_ok=True)


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    })
    return s


def get_first(urls: list[str], *, binary: bool = False) -> tuple[bytes, str]:
    last = None
    s = session()
    for url in urls:
        for attempt in range(4):
            try:
                r = s.get(url, timeout=40)
                if r.status_code in {429, 500, 502, 503, 504}:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.content
                if not data:
                    raise RuntimeError("EMPTY_BODY")
                return data, url
            except Exception as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"DOWNLOAD_FAILED:{urls}:{last}")


def parse_members(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig")
    rows = []
    seen = set()
    for row in csv.DictReader(io.StringIO(text)):
        symbol = str(row.get("Symbol") or row.get("SYMBOL") or "").strip().upper()
        isin = str(row.get("ISIN Code") or row.get("ISIN CODE") or row.get("ISIN") or "").strip().upper()
        company = str(row.get("Company Name") or row.get("COMPANY NAME") or "").strip()
        industry = str(row.get("Industry") or row.get("INDUSTRY") or "").strip()
        series = str(row.get("Series") or row.get("SERIES") or "EQ").strip().upper() or "EQ"
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        rows.append({"symbol": symbol, "isin": isin, "company": company, "industry": industry, "series": series})
    if not 190 <= len(rows) <= 210:
        raise RuntimeError(f"NIFTY200_MEMBER_COUNT_INVALID:{len(rows)}")
    return rows


def parse_master(data: bytes) -> dict[str, dict[str, str]]:
    rows = {}
    for row in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
        symbol = str(row.get("SYMBOL") or "").strip().upper()
        if not symbol:
            continue
        rows.setdefault(symbol, {
            "isin": str(row.get("ISIN NUMBER") or row.get("ISIN") or "").strip().upper(),
            "series": str(row.get(" SERIES") or row.get("SERIES") or "").strip().upper(),
            "company": str(row.get("NAME OF COMPANY") or "").strip(),
        })
    return rows


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def bhav_name(d: date) -> str:
    return f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def fetch_bhav(d: date) -> dict:
    name = bhav_name(d)
    path = RAW / name
    if path.exists() and path.stat().st_size > 1000:
        return {"date": d.isoformat(), "status": "ACQUIRED", "path": str(path)}

    direct = f"{ARCHIVE}/{name}"
    descriptor = json.dumps([{
        "name": REPORT_NAME,
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
    urls = [direct, f"{BASE}/api/reports?{query}"]
    s = session()
    last = None
    for url in urls:
        for attempt in range(4):
            try:
                r = s.get(url, timeout=45, headers={**s.headers, "Accept": "application/zip,application/octet-stream,*/*"})
                body = r.content
                is_zip = len(body) >= 4 and body[:4] == b"PK\x03\x04"
                if r.ok and is_zip:
                    path.write_bytes(body)
                    return {"date": d.isoformat(), "status": "ACQUIRED", "path": str(path), "source": url}
                if r.status_code in {400, 404}:
                    break
                if r.status_code in {429, 500, 502, 503, 504}:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                last = f"HTTP_{r.status_code}"
                break
            except Exception as exc:
                last = repr(exc)
                time.sleep(0.6 * (attempt + 1))
    return {"date": d.isoformat(), "status": "NO_REPORT", "error": last}


def parse_zip(path: Path, member_symbols: set[str]) -> dict[str, list[list[str]]]:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError(f"NO_CSV_IN_ZIP:{path.name}")
        content = z.read(names[0]).decode("utf-8-sig")
    out: dict[str, list[list[str]]] = defaultdict(list)
    reader = csv.DictReader(io.StringIO(content))
    fields = set(reader.fieldnames or [])
    required = {"TradDt","TckrSymb","SctySrs","OpnPric","HghPric","LwPric","ClsPric","TtlTradgVol"}
    if not required.issubset(fields):
        raise RuntimeError(f"UDIFF_SCHEMA_MISMATCH:{path.name}")
    for row in reader:
        symbol = str(row["TckrSymb"]).strip().upper()
        if symbol not in member_symbols:
            continue
        series = str(row["SctySrs"]).strip().upper()
        if series not in {"EQ", "BE", "RR"}:
            continue
        vals = [
            str(row["TradDt"]).strip(),
            str(row["OpnPric"]).strip(),
            str(row["HghPric"]).strip(),
            str(row["LwPric"]).strip(),
            str(row["ClsPric"]).strip(),
            str(row["TtlTradgVol"]).strip(),
        ]
        try:
            op, hi, lo, cl = map(float, vals[1:5])
            vol = int(float(vals[5] or 0))
        except Exception:
            continue
        if min(op, hi, lo, cl) <= 0 or hi < max(op, lo, cl) or lo > min(op, hi, cl) or vol < 0:
            continue
        out[symbol].append(vals)
    return out


def acquire_index(index_name: str, start: date, end: date) -> list[dict]:
    s = session()
    rows: dict[str, dict] = {}
    cur = start
    while cur <= end:
        chunk_end = min(end, cur + timedelta(days=80))
        url = (
            f"{BASE}/api/historicalOR/indicesHistory?indexType={requests.utils.quote(index_name)}"
            f"&from={cur.strftime('%d-%m-%Y')}&to={chunk_end.strftime('%d-%m-%Y')}"
        )
        last = None
        for attempt in range(5):
            try:
                r = s.get(url, timeout=40, headers={**s.headers, "Accept":"application/json,*/*"})
                if r.status_code in {429,500,502,503,504}:
                    time.sleep(1.0*(attempt+1)); continue
                r.raise_for_status()
                payload = r.json()
                for raw in payload.get("data", []):
                    if raw.get("EOD_INDEX_NAME") != index_name:
                        continue
                    d = datetime.strptime(raw["EOD_TIMESTAMP"], "%d-%b-%Y").date().isoformat()
                    rows[d] = {
                        "Date": d,
                        "Open": raw["EOD_OPEN_INDEX_VAL"],
                        "High": raw["EOD_HIGH_INDEX_VAL"],
                        "Low": raw["EOD_LOW_INDEX_VAL"],
                        "Close": raw["EOD_CLOSE_INDEX_VAL"],
                        "Volume": "0",
                    }
                last = None
                break
            except Exception as exc:
                last = exc
                time.sleep(0.8*(attempt+1))
        if last is not None:
            raise RuntimeError(f"INDEX_DOWNLOAD_FAILED:{cur}:{chunk_end}:{last}")
        cur = chunk_end + timedelta(days=1)
    return [rows[k] for k in sorted(rows)]


def main():
    constituent_data, constituent_source = get_first([
        "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv",
    ])
    members = parse_members(constituent_data)

    master_data, master_source = get_first([
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
    ])
    master = parse_master(master_data)

    # Fill missing identity fields from the official security master.
    for m in members:
        x = master.get(m["symbol"], {})
        m["isin"] = m["isin"] or x.get("isin", "")
        m["series"] = m["series"] or x.get("series", "") or "EQ"
        m["company"] = m["company"] or x.get("company", "")

    identity = sum(1 for m in members if m["isin"]) / len(members)
    if identity < 0.98:
        raise RuntimeError(f"IDENTITY_COVERAGE_TOO_LOW:{identity}")

    const_file = CONSTITUENT_DIR / f"ind_nifty200list_{TODAY:%Y%m%d}.csv"
    const_file.write_bytes(constituent_data)
    master_file = MASTER_DIR / f"EQUITY_L_{TODAY:%Y%m%d}.csv"
    master_file.write_bytes(master_data)

    days = list(weekdays(START, TODAY))
    attempts = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_bhav, d): d for d in days}
        for i, future in enumerate(as_completed(futures), 1):
            attempts.append(future.result())
            if i % 50 == 0:
                ok = sum(x["status"] == "ACQUIRED" for x in attempts)
                print(f"bhavcopy {i}/{len(days)} acquired={ok}", flush=True)

    acquired = sorted((x for x in attempts if x["status"] == "ACQUIRED"), key=lambda x: x["date"])
    if len(acquired) < 450:
        raise RuntimeError(f"INSUFFICIENT_SESSION_HISTORY:{len(acquired)}")
    latest = acquired[-1]["date"]
    latest_date = date.fromisoformat(latest)
    if (TODAY - latest_date).days > 7:
        raise RuntimeError(f"LATEST_OFFICIAL_SESSION_TOO_OLD:{latest}")

    symbols = {m["symbol"] for m in members}
    histories: dict[str, list[list[str]]] = defaultdict(list)
    for i, item in enumerate(acquired, 1):
        parsed = parse_zip(Path(item["path"]), symbols)
        for symbol, rows in parsed.items():
            histories[symbol].extend(rows)
        if i % 100 == 0:
            print(f"parse {i}/{len(acquired)}", flush=True)

    covered = [s for s in sorted(symbols) if len(histories.get(s, [])) >= 150]
    coverage = len(covered) / len(symbols)
    if coverage < 0.95:
        missing = sorted(symbols - set(covered))
        raise RuntimeError(f"NIFTY200_HISTORY_COVERAGE_TOO_LOW:{coverage}:{missing[:30]}")

    cache = ROOT / "data" / "normalized" / "nse_official" / "equity_bhavcopy" / f"expanded_universe_{latest.replace('-','_')}"
    cache.mkdir(parents=True, exist_ok=True)
    for symbol in sorted(symbols):
        rows = sorted(histories.get(symbol, []), key=lambda x: x[0])
        if not rows:
            continue
        with (cache / f"{symbol}.NS.csv").open("w", newline="", encoding="utf-8") as h:
            w = csv.writer(h)
            w.writerow(["Date","Open","High","Low","Close","Volume"])
            w.writerows(rows)

    nifty = acquire_index("NIFTY 50", START, TODAY)
    if len(nifty) < 450:
        raise RuntimeError(f"NIFTY50_HISTORY_TOO_SHORT:{len(nifty)}")
    with (cache / "INDEX_NSEI.csv").open("w", newline="", encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=["Date","Open","High","Low","Close","Volume"])
        w.writeheader(); w.writerows(nifty)

    manifest = {
        "schema":"SRE_PHASE6_OFFICIAL_NIFTY200_MARKET_BUNDLE_V1",
        "source":"NSE_PUBLIC_CM_UDIFF_COMMON_BHAVCOPY_FINAL",
        "constituent_source":constituent_source,
        "security_master_source":master_source,
        "authority":"DATA_FOUNDATION_ONLY_NO_SCORE_CHANGE",
        "automatic_yfinance_fallback":False,
        "synthetic_data":False,
        "start_session":acquired[0]["date"],
        "latest_session":latest,
        "acquired_sessions":len(acquired),
        "nifty200_members":len(members),
        "identity_coverage":round(identity,6),
        "history_covered_members":len(covered),
        "history_coverage":round(coverage,6),
        "minimum_bars_for_covered_member":min(len(histories[s]) for s in covered),
        "index_rows":len(nifty),
        "price_normalization":"RAW_OFFICIAL_OHLCV; corporate-action normalization remains separately governed",
    }
    (ROOT/"phase6_official_market_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

    # Cleanup raw files before packaging; release contains normalized histories only.
    for p in RAW.glob("*"):
        p.unlink()
    RAW.rmdir()

    print(json.dumps(manifest,indent=2),flush=True)


if __name__ == "__main__":
    main()
