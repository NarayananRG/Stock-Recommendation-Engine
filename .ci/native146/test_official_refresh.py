from __future__ import annotations

import csv
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("official_daily_refresh_v3.py")
SPEC = importlib.util.spec_from_file_location("official_daily_refresh_v3", MODULE_PATH)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def bhav_payload(session: str, count: int = 200, *, headers: list[str] | None = None) -> bytes:
    fields = headers or ["TradDt", "TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"]
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for index in range(count):
        row = {
            "TradDt": session,
            "TckrSymb": f"S{index:03d}",
            "SctySrs": "EQ",
            "OpnPric": "100",
            "HghPric": "110",
            "LwPric": "90",
            "ClsPric": "105",
            "TtlTradgVol": "1000",
        }
        writer.writerow({key: row.get(key, "") for key in fields})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bhav.csv", buf.getvalue())
    return out.getvalue()


def index_csv(session: str, name: str = "NIFTY 50") -> bytes:
    day = __import__("datetime").datetime.strptime(session, "%Y-%m-%d").strftime("%d-%m-%Y")
    return (
        "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value\n"
        f"{name},{day},100,110,90,105\n"
    ).encode()


def make_cache(root: Path, *, duplicate: bool = False) -> None:
    rows = "Date,Open,High,Low,Close,Volume\n2026-10-14,90,100,80,95,1000\n"
    if duplicate:
        rows += "2026-10-14,90,100,80,95,1000\n"
    for index in range(200):
        (root / f"S{index:03d}.NS.csv").write_text(rows, encoding="utf-8")
    (root / "INDEX_NSEI.csv").write_text(rows, encoding="utf-8")


class FakeResponse:
    def __init__(self, payload, status=200, content_type="application/json"):
        self._payload = payload
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.content = json.dumps(payload).encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def get(self, url, **kwargs):
        return FakeResponse({"home": True}) if url.endswith(".com/") else FakeResponse(self.payload)


class OfficialRefreshTests(unittest.TestCase):
    expected = "2026-10-15"

    def test_equity_and_nifty_parsers_accept_current_official_session(self):
        rows, meta = m._parse_bhav(bhav_payload(self.expected), self.expected)
        self.assertEqual(len(rows), 200)
        self.assertEqual(meta["equity_session"], self.expected)
        values, session = m._parse_index_close_report(index_csv(self.expected), self.expected)
        self.assertEqual(session, self.expected)
        self.assertEqual(values, ("100.0", "110.0", "90.0", "105.0"))

    def test_csv_schema_drift_is_parse_error(self):
        with self.assertRaisesRegex(RuntimeError, "OFFICIAL_BHAVCOPY_SCHEMA_MISMATCH"):
            m._parse_bhav(bhav_payload(self.expected, headers=["TradDt", "TckrSymb"]), self.expected)
        with self.assertRaisesRegex(m.OfficialDataParseError, "OFFICIAL_INDEX_SCHEMA_CHANGED"):
            m._parse_index_close_report(b"foo,bar\n1,2\n", self.expected)

    def test_empty_and_wrong_index_rows_have_actionable_not_published_diagnostic(self):
        with patch.object(m, "_session", return_value=FakeSession({"data": []})):
            with self.assertRaisesRegex(m.OfficialDataNotReady, "rows=0"):
                m._fetch_index_from_api(self.expected)
        wrong = {"data": [{
            "EOD_INDEX_NAME": "NIFTY BANK", "EOD_TIMESTAMP": "15-OCT-2026",
            "EOD_OPEN_INDEX_VAL": 1, "EOD_HIGH_INDEX_VAL": 2,
            "EOD_LOW_INDEX_VAL": 1, "EOD_CLOSE_INDEX_VAL": 2,
        }]}
        with patch.object(m, "_session", return_value=FakeSession(wrong)):
            with self.assertRaisesRegex(m.OfficialDataNotReady, "available_names"):
                m._fetch_index_from_api(self.expected)

    def test_index_json_schema_drift_is_parse_error(self):
        with patch.object(m, "_session", return_value=FakeSession({"unexpected": []})):
            with self.assertRaisesRegex(m.OfficialDataParseError, "EXPECTED_DATA_LIST"):
                m._fetch_index_from_api(self.expected)

    def test_both_current_refresh_full_universe_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_cache(root)
            equity = (bhav_payload(self.expected), {"url": "NSE_BHAV", "http_status": 200, "content_type": "application/zip", "filename": "bhav.zip", "payload_size": 100})
            nifty = (("100", "110", "90", "105"), self.expected, {"url": "NSE_INDEX", "http_status": 200})
            with patch.object(m, "_download_candidates", return_value=equity), patch.object(m, "_fetch_index", return_value=nifty):
                result = m.refresh_official_session([str(root)], self.expected)
            self.assertEqual(result["status"], "REFRESHED_AND_VERIFIED")
            self.assertEqual(result["stock_files_matched"], 200)
            self.assertEqual(result["stock_coverage"], 1.0)
            manifest = json.loads((root / ".sre_official_refresh_manifest.json").read_text())
            self.assertEqual(manifest["session"], self.expected)
            self.assertTrue(manifest["full_universe_verified"])
            self.assertFalse(manifest["automatic_yfinance_fallback"])
            for path in [*root.glob("*.NS.csv"), root / "INDEX_NSEI.csv"]:
                self.assertEqual(m._last_session(path), self.expected)

    def test_equity_unavailable_and_http_failure_do_not_mutate_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_cache(root)
            before = (root / "S000.NS.csv").read_bytes()
            with patch.object(m, "_download_candidates", side_effect=m.OfficialDataNotReady("HTTP_404")):
                result = m.refresh_official_session([str(root)], self.expected)
            self.assertEqual(result["status"], "OFFICIAL_NOT_READY")
            self.assertEqual((root / "S000.NS.csv").read_bytes(), before)
            with patch.object(m, "_download_candidates", side_effect=RuntimeError("HTTP_503")):
                result = m.refresh_official_session([str(root)], self.expected)
            self.assertEqual(result["status"], "OFFICIAL_DOWNLOAD_FAILED")

    def test_nifty_current_equity_unavailable_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_cache(root)
            nifty = (("100", "110", "90", "105"), self.expected, {"url": "NSE_INDEX"})
            with patch.object(m, "_download_candidates", side_effect=m.OfficialDataNotReady("equity not published")), patch.object(m, "_fetch_index", return_value=nifty) as index_fetch:
                result = m.refresh_official_session([str(root)], self.expected)
            self.assertEqual(result["status"], "OFFICIAL_NOT_READY")
            index_fetch.assert_not_called()
            self.assertEqual(m._last_session(root / "INDEX_NSEI.csv"), "2026-10-14")

    def test_equity_current_nifty_unavailable_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_cache(root)
            equity = (bhav_payload(self.expected), {"url": "NSE_BHAV", "http_status": 200})
            with patch.object(m, "_download_candidates", return_value=equity), patch.object(m, "_fetch_index", side_effect=m.OfficialDataNotReady("rows=0")):
                result = m.refresh_official_session([str(root)], self.expected)
            self.assertEqual(result["status"], "OFFICIAL_NOT_READY")
            self.assertEqual(result["reason_code"], "OFFICIAL_INDEX_NOT_PUBLISHED")
            self.assertEqual(m._last_session(root / "S000.NS.csv"), "2026-10-14")

    def test_partial_coverage_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_cache(root)
            equity = (bhav_payload(self.expected, 180), {"url": "NSE_BHAV", "http_status": 200})
            nifty = (("100", "110", "90", "105"), self.expected, {"url": "NSE_INDEX"})
            with patch.object(m, "_download_candidates", return_value=equity), patch.object(m, "_fetch_index", return_value=nifty):
                result = m.refresh_official_session([str(root)], self.expected)
            self.assertEqual(result["status"], "OFFICIAL_COVERAGE_FAILED")
            self.assertEqual(m._last_session(root / "S000.NS.csv"), "2026-10-14")

    def test_atomic_write_failure_rolls_back_every_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_cache(root)
            before = {path.name: path.read_bytes() for path in [*root.glob("*.NS.csv"), root / "INDEX_NSEI.csv"]}
            equity = (bhav_payload(self.expected), {"url": "NSE_BHAV", "http_status": 200})
            nifty = (("100", "110", "90", "105"), self.expected, {"url": "NSE_INDEX"})
            real_replace = m.os.replace
            calls = {"count": 0}
            def fail_once(src, dst):
                calls["count"] += 1
                if calls["count"] == 12:
                    raise OSError("simulated commit failure")
                return real_replace(src, dst)
            with patch.object(m, "_download_candidates", return_value=equity), patch.object(m, "_fetch_index", return_value=nifty), patch.object(m.os, "replace", side_effect=fail_once):
                result = m.refresh_official_session([str(root)], self.expected)
            self.assertEqual(result["status"], "LOCAL_PERSISTENCE_FAILED")
            self.assertEqual(result["reason_code"], "LOCAL_TRANSACTION_ROLLED_BACK")
            for path in [*root.glob("*.NS.csv"), root / "INDEX_NSEI.csv"]:
                self.assertEqual(path.read_bytes(), before[path.name])

    def test_duplicate_session_protection_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_cache(root, duplicate=True)
            before = (root / "S000.NS.csv").read_bytes()
            equity = (bhav_payload(self.expected), {"url": "NSE_BHAV", "http_status": 200})
            nifty = (("100", "110", "90", "105"), self.expected, {"url": "NSE_INDEX"})
            with patch.object(m, "_download_candidates", return_value=equity), patch.object(m, "_fetch_index", return_value=nifty):
                result = m.refresh_official_session([str(root)], self.expected)
            self.assertEqual(result["status"], "LOCAL_PERSISTENCE_FAILED")
            self.assertEqual((root / "S000.NS.csv").read_bytes(), before)

    def test_provider_policy_has_no_automatic_yfinance_fallback(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import yfinance", source)
        self.assertIn('"automatic_yfinance_fallback": False', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
