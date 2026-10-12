from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ENGINE = Path(os.environ["SRE_ENGINE_ROOT"])
sys.path.insert(0, str(ENGINE))

from stock_app import official_daily_refresh as mod


def make_cache(root: Path, count: int = 200) -> Path:
    cache = root / "data" / "normalized" / "nse_official" / "equity_bhavcopy" / "expanded_universe_2026_10_09"
    cache.mkdir(parents=True)
    rows = [["2026-10-09", "100", "102", "99", "101", "100000"]]
    for i in range(1, count + 1):
        symbol = f"STK{i:03d}"
        with (cache / f"{symbol}.NS.csv").open("w", newline="", encoding="utf-8") as h:
            w = csv.writer(h)
            w.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
            w.writerows(rows)
    with (cache / "INDEX_NSEI.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
        w.writerow(["2026-10-09", "25000", "25100", "24900", "25050", "0"])
    return cache


def make_bhav(count: int = 200) -> bytes:
    buf = io.StringIO(newline="")
    fields = ["TradDt", "TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"]
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    for i in range(1, count + 1):
        w.writerow({
            "TradDt": "2026-10-12",
            "TckrSymb": f"STK{i:03d}",
            "SctySrs": "EQ",
            "OpnPric": 100 + i / 100,
            "HghPric": 103 + i / 100,
            "LwPric": 99 + i / 100,
            "ClsPric": 102 + i / 100,
            "TtlTradgVol": 100000 + i,
        })
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("BhavCopy.csv", buf.getvalue())
    return raw.getvalue()


def last_date(path: Path) -> str:
    with path.open(encoding="utf-8") as h:
        return list(csv.DictReader(h))[-1]["Date"]


def run_success_case() -> None:
    with tempfile.TemporaryDirectory() as td:
        cache = make_cache(Path(td))
        original_request = mod._request
        original_index = mod._fetch_index
        try:
            mod._request = lambda url, timeout=35: make_bhav()
            mod._fetch_index = lambda session: ("25100", "25300", "25000", "25250")
            result = mod.refresh_official_session([str(cache)], "2026-10-12")
        finally:
            mod._request = original_request
            mod._fetch_index = original_index
        assert result["status"] == "REFRESHED", result
        assert result["matched"] == 200, result
        assert result["coverage"] == 1.0, result
        assert result["automatic_yfinance_fallback"] is False, result
        assert last_date(cache / "STK001.NS.csv") == "2026-10-12"
        assert last_date(cache / "STK200.NS.csv") == "2026-10-12"
        assert last_date(cache / "INDEX_NSEI.csv") == "2026-10-12"


def run_not_ready_case() -> None:
    with tempfile.TemporaryDirectory() as td:
        cache = make_cache(Path(td))
        original_request = mod._request
        try:
            def not_ready(url, timeout=35):
                raise mod.OfficialDataNotReady("OFFICIAL_REPORT_NOT_READY")
            mod._request = not_ready
            result = mod.refresh_official_session([str(cache)], "2026-10-12")
        finally:
            mod._request = original_request
        assert result["status"] == "NOT_READY", result
        assert last_date(cache / "STK001.NS.csv") == "2026-10-09"


def run_coverage_case() -> None:
    with tempfile.TemporaryDirectory() as td:
        cache = make_cache(Path(td))
        original_request = mod._request
        original_index = mod._fetch_index
        try:
            mod._request = lambda url, timeout=35: make_bhav(180)
            mod._fetch_index = lambda session: ("25100", "25300", "25000", "25250")
            result = mod.refresh_official_session([str(cache)], "2026-10-12")
        finally:
            mod._request = original_request
            mod._fetch_index = original_index
        assert result["status"] == "ERROR", result
        assert result["reason"] == "OFFICIAL_SESSION_COVERAGE_TOO_LOW", result
        assert last_date(cache / "STK001.NS.csv") == "2026-10-09"


if __name__ == "__main__":
    run_success_case()
    run_not_ready_case()
    run_coverage_case()
    print("PHASE7 OFFICIAL DAILY REFRESH TESTS PASS")
