from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])


def repl(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(label + " contract missing")
    return text.replace(old, new, 1)


mod = root / "stock_app" / "official_daily_refresh.py"
s = mod.read_text(encoding="utf-8")

# Replace urllib-only transport with the same requests.Session pattern that the
# Phase 6 official-market bundle has already proven on GitHub Actions.
start = s.index("def _request(")
end = s.index("\ndef _parse_bhav", start)
new_transport = r'''def _session():
    import requests
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    })
    return sess


def _download_candidates(urls: list[str], *, timeout: int = 40) -> tuple[bytes, str]:
    import time
    sess = _session()
    errors: list[str] = []
    for url in urls:
        for attempt in range(4):
            try:
                resp = sess.get(
                    url,
                    timeout=timeout,
                    headers={**sess.headers, "Accept": "application/zip,text/csv,application/json,*/*"},
                )
                if resp.status_code in {429, 500, 502, 503, 504}:
                    errors.append(f"{url}:HTTP_{resp.status_code}:attempt_{attempt+1}")
                    time.sleep(0.8 * (attempt + 1))
                    continue
                if resp.status_code in {400, 404}:
                    errors.append(f"{url}:HTTP_{resp.status_code}")
                    break
                resp.raise_for_status()
                if not resp.content:
                    errors.append(f"{url}:EMPTY_BODY")
                    break
                return resp.content, url
            except Exception as exc:
                errors.append(f"{url}:{type(exc).__name__}:{exc}")
                time.sleep(0.5 * (attempt + 1))
    detail = " | ".join(errors[-8:])
    if any("HTTP_400" in x or "HTTP_404" in x for x in errors):
        raise OfficialDataNotReady("OFFICIAL_REPORT_NOT_READY:" + detail)
    raise RuntimeError("OFFICIAL_DOWNLOAD_FAILED:" + detail)


def _bhavcopy_candidates(expected_session: str) -> list[str]:
    from urllib.parse import urlencode
    d = datetime.strptime(expected_session, "%Y-%m-%d")
    name = f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    direct = f"{ARCHIVE}/content/cm/{name}"
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
    return [direct, f"{NSE}/api/reports?{query}"]
'''
s = s[:start] + new_transport + s[end:]

# Replace index fetch path with requests + official close report/API fallback.
start = s.index("def _fetch_index_from_api")
end = s.index("\ndef _read_rows", start)
new_index = r'''def _fetch_index_from_api(expected_session: str) -> tuple[str, str, str, str]:
    d = datetime.strptime(expected_session, "%Y-%m-%d").strftime("%d-%m-%Y")
    sess = _session()
    errors: list[str] = []
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
        payload, _ = _download_candidates([report])
        row = _parse_index_close_report(payload, expected_session)
        if row:
            return row
    except OfficialDataNotReady:
        pass
    return _fetch_index_from_api(expected_session)
'''
s = s[:start] + new_index + s[end:]

# Switch bhavcopy fetch to candidate list and report actual source.
old = '''    name = f"BhavCopy_NSE_CM_0_0_0_{expected_session.replace('-', '')}_F_0000.csv.zip"
    bhav_url = f"{ARCHIVE}/content/cm/{name}"
    try:
        bhav_rows = _parse_bhav(_request(bhav_url), expected_session)
        nifty = _fetch_index(expected_session)
    except OfficialDataNotReady as exc:
'''
new = '''    bhav_candidates = _bhavcopy_candidates(expected_session)
    try:
        bhav_payload, bhav_url = _download_candidates(bhav_candidates)
        bhav_rows = _parse_bhav(bhav_payload, expected_session)
        nifty = _fetch_index(expected_session)
    except OfficialDataNotReady as exc:
'''
s = repl(s, old, new, "bhavcopy candidate transport")

# Catch all operational failures inside the refresh result so the UI gets the
# exact source failure instead of losing the latest-session context.
needle = '''    except OfficialDataNotReady as exc:
        return {
            "status": "NOT_READY",
            "reason": str(exc),
            "expected_session": expected_session,
            "source": "NSE_OFFICIAL",
            "automatic_yfinance_fallback": False,
        }

    stock_files = sorted(root.glob("*.NS.csv"))
'''
replacement = '''    except OfficialDataNotReady as exc:
        return {
            "status": "NOT_READY",
            "reason": str(exc),
            "expected_session": expected_session,
            "source": "NSE_OFFICIAL",
            "automatic_yfinance_fallback": False,
        }
    except Exception as exc:
        return {
            "status": "ERROR",
            "reason": f"{type(exc).__name__}: {exc}",
            "expected_session": expected_session,
            "source": "NSE_OFFICIAL",
            "automatic_yfinance_fallback": False,
        }

    stock_files = sorted(root.glob("*.NS.csv"))
'''
s = repl(s, needle, replacement, "operational error visibility")
mod.write_text(s, encoding="utf-8")

api = root / "modern_ui" / "api.py"
a = api.read_text(encoding="utf-8")
a = repl(
    a,
    'APP_VERSION = "0.12.6-phase7-upgrade-startup-hotfix"',
    'APP_VERSION = "0.12.7-phase7-official-source-diagnostics-hotfix"',
    "backend version",
)

# Keep the latest known local official session visible even if the network
# refresh itself errors.
old = '''        if refresh.get("status") == "ERROR":
            return {
                "source": {},
                **expected,
                "target_session": expected["expected_market_session"],
                "latest_official_session": None,
                "data_freshness": "OFFICIAL SOURCE ERROR",
                "freshness_gate": "BLOCKED",
                "official_mode": False,
                "analysis_data_current": False,
                "universe_coverage": None,
                "identity_coverage": None,
                "ready": False,
                "blocked_reason": "OFFICIAL_SOURCE_ERROR",
                "refresh_status": refresh,
            }
'''
new = '''        if refresh.get("status") == "ERROR":
            source = refresh.get("source") or self.data_source_status()
            active = dict(source.get("active") or {})
            detail = refresh.get("error") or (refresh.get("refresh_result") or {}).get("reason") or "UNKNOWN_OFFICIAL_SOURCE_ERROR"
            return {
                "source": source,
                **expected,
                "target_session": expected["expected_market_session"],
                "latest_official_session": active.get("latest_session"),
                "data_freshness": "OFFICIAL SOURCE ERROR",
                "freshness_gate": "BLOCKED",
                "official_mode": source.get("mode") == "REAL_OFFICIAL_DATA",
                "analysis_data_current": False,
                "universe_coverage": active.get("history_coverage"),
                "identity_coverage": active.get("identity_coverage"),
                "ready": False,
                "blocked_reason": "OFFICIAL_SOURCE_ERROR",
                "refresh_error_detail": detail,
                "refresh_status": refresh,
            }
'''
a = repl(a, old, new, "daily gate error context")

# Surface diagnostic detail in status payload.
old = '''            "automatic_yfinance_fallback": False,
        }
'''
# only replace the first post_close_daily_status tail after its marker
marker = a.index('    def post_close_daily_status(self)')
pos = a.index(old, marker)
a = a[:pos] + '''            "refresh_error_detail": gate.get("refresh_error_detail"),
            "refresh_status": gate.get("refresh_status"),
            "automatic_yfinance_fallback": False,
        }
''' + a[pos+len(old):]
api.write_text(a, encoding="utf-8")

js = root / "modern_ui" / "frontend" / "app.js"
t = js.read_text(encoding="utf-8")
# Add an explicit error-detail tile to the daily grid without hiding source state.
t = t.replace(
    "['Refresh',x.last_result?.refresh_status?.refresh_result?.status||x.last_result?.refresh_status?.refresh_result||'official-first']",
    "['Refresh',x.refresh_status?.refresh_result?.status||x.refresh_status?.refresh_result||x.last_result?.refresh_status?.refresh_result?.status||'official-first'],['Source detail',x.refresh_error_detail||x.refresh_status?.error||x.refresh_status?.refresh_result?.reason||'—']",
)
js.write_text(t, encoding="utf-8")

policy = root / "phase7" / "official_source_diagnostics_0127.json"
policy.write_text("""{
  "schema": "SRE_PHASE7_OFFICIAL_SOURCE_DIAGNOSTICS_0127",
  "release": "0.12.7-phase7-official-source-diagnostics-hotfix",
  "official_transport": "REQUESTS_SESSION_WITH_DIRECT_ARCHIVE_AND_NSE_REPORT_API_FALLBACK",
  "expose_exact_source_error": true,
  "preserve_latest_local_official_session_on_refresh_error": true,
  "automatic_yfinance_fallback": false,
  "production_recommendation_authority_changed": false,
  "production_rank_authority_changed": false
}
""", encoding="utf-8")

assert "OFFICIAL_DOWNLOAD_FAILED" in mod.read_text(encoding="utf-8")
assert "_bhavcopy_candidates" in mod.read_text(encoding="utf-8")
assert "refresh_error_detail" in api.read_text(encoding="utf-8")
assert "Source detail" in js.read_text(encoding="utf-8")
print("0.12.7 official source diagnostics hotfix applied")
