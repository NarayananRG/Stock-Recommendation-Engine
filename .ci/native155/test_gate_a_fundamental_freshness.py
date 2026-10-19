from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ENGINE_ROOT = Path(os.environ["SRE_ENGINE_ROOT"]).resolve()
sys.path.insert(0, str(ENGINE_ROOT))

from stock_app.fundamentals import FundamentalSnapshot, FundamentalSnapshotService  # noqa: E402
from stock_app.lifecycle import HOLD  # noqa: E402
from stock_app.monitoring import AdvancedMonitoringService  # noqa: E402
from stock_app.storage import AppDatabase  # noqa: E402


PANEL_RELATIVE = Path("NextGen Research/results/fundamental_v2_phase2a4_feature_panel/canonical_feature_panel.csv")
PANEL_FIELDS = [
    "symbol", "quarter_end", "reporting_basis", "submission_type", "event_id",
    "availability_ts", "provider_seq_id", "archive_gap", "domain",
    "source_document_kind", "retrieval_representation", "source_content_sha256",
]
for feature in ["REVENUE", "PAT", "PBT", "TAX", "FINANCE_COST", "DEPRECIATION",
                "OPERATING_CASH_FLOW", "CASH_AND_EQUIVALENTS", "TOTAL_ASSETS",
                "DEBT_EQUITY_RATIO", "EPS"]:
    PANEL_FIELDS.extend([f"{feature}__status", f"{feature}__concept", f"{feature}__value"])


def panel_row(symbol: str, availability: str, quarter: str = "2026-06-30", basis: str = "CONSOLIDATED") -> dict[str, str]:
    row = {field: "" for field in PANEL_FIELDS}
    row.update({
        "symbol": symbol,
        "quarter_end": quarter,
        "reporting_basis": basis,
        "submission_type": "ORIGINAL",
        "event_id": hashlib.sha256(f"{symbol}:{quarter}:{basis}".encode()).hexdigest(),
        "availability_ts": availability,
        "archive_gap": "false",
        "domain": "www.nseindia.com",
        "source_document_kind": "XBRL",
        "REVENUE__status": "SELECTED",
        "REVENUE__value": "1000000000",
        "PAT__status": "SELECTED_EQUIVALENT_DUPLICATES",
        "PAT__value": "100000000",
        "EPS__status": "SELECTED",
        "EPS__value": "10.5",
    })
    return row


def temporary_directory() -> tempfile.TemporaryDirectory[str]:
    parent = os.environ.get("SRE_TEST_TEMP_ROOT")
    if parent:
        Path(parent).mkdir(parents=True, exist_ok=True)
    # The reconstructed AppDatabase uses sqlite context managers that commit but do
    # not close immediately on Windows. Ignore delayed-handle cleanup in this
    # disposable test root; no production database is opened.
    return tempfile.TemporaryDirectory(dir=parent, ignore_cleanup_errors=True)


def make_fixture(rows: list[dict[str, str]]) -> tuple[tempfile.TemporaryDirectory[str], Path, AppDatabase]:
    temp = temporary_directory()
    root = Path(temp.name)
    panel = root / PANEL_RELATIVE
    panel.parent.mkdir(parents=True)
    with panel.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PANEL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    identity = root / "data/fundamentals/company_identity_map_v1.csv"
    identity.parent.mkdir(parents=True)
    symbols = sorted({row["symbol"] for row in rows} | {"IDENTITYONLY", "HDFCBANK", "INFY", "TCS"})
    with identity.open("w", encoding="utf-8", newline="") as handle:
        fields = ["company_id", "symbol", "nse_symbol", "bse_code", "company_name", "isin", "sector", "historical_symbols"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for symbol in symbols:
            writer.writerow({"company_id": symbol, "symbol": symbol, "nse_symbol": symbol,
                             "company_name": symbol, "sector": "METALS"})
    db = AppDatabase(root / "test.sqlite3")
    db.initialize()
    return temp, root, db


class GateAFundamentalTests(unittest.TestCase):
    def test_fresh_stale_very_stale_unavailable_future_and_restart(self) -> None:
        rows = [
            panel_row("FRESHCO", "2026-07-24T17:34:31+05:30"),
            panel_row("STALECO", "2026-04-01T17:34:31+05:30"),
            panel_row("OLDCO", "2025-01-01T17:34:31+05:30"),
            panel_row("FUTURECO", "2026-11-01T17:34:31+05:30"),
        ]
        temp, root, db = make_fixture(rows)
        self.addCleanup(temp.cleanup)
        service = FundamentalSnapshotService(root, db)
        self.assertEqual(service.get_snapshot("FRESHCO", "2026-10-19").data_freshness, "FRESH")
        self.assertEqual(service.get_snapshot("STALECO", "2026-10-19").data_freshness, "STALE")
        self.assertEqual(service.get_snapshot("OLDCO", "2026-10-19").data_freshness, "VERY_STALE")
        self.assertEqual(service.get_snapshot("FUTURECO", "2026-10-19").data_freshness, "UNAVAILABLE")
        missing = service.get_snapshot("IDENTITYONLY", "2026-10-19")
        self.assertEqual(missing.data_quality["reason"], "no verified official observation available")
        unmapped = service.get_snapshot("NOTMAPPED", "2026-10-19")
        self.assertEqual(unmapped.data_quality["reason"], "missing company mapping")

        restarted = FundamentalSnapshotService(root, db)
        again = restarted.get_snapshot("FRESHCO", "2026-10-19")
        self.assertEqual(again.publication_timestamp, "2026-07-24T17:34:31+05:30")
        self.assertEqual(again.source, "OFFICIAL_PHASE5_CANONICAL_PANEL")

    def test_empty_and_parser_failure_fail_closed(self) -> None:
        temp, root, db = make_fixture([])
        self.addCleanup(temp.cleanup)
        service = FundamentalSnapshotService(root, db)
        self.assertEqual(service.get_snapshot("IDENTITYONLY", "2026-10-19").data_freshness, "UNAVAILABLE")
        (root / PANEL_RELATIVE).write_bytes(b"\xff\xfe\x00broken")
        service = FundamentalSnapshotService(root, db)
        self.assertEqual(service.get_snapshot("IDENTITYONLY", "2026-10-19").data_freshness, "UNAVAILABLE")

    def test_monitoring_diagnostics_distinguish_unavailable_and_count_very_stale(self) -> None:
        monitor = object.__new__(AdvancedMonitoringService)
        monitor.latest_actions = lambda: [
            {"action": "HOLD", "thesis_health": "HEALTHY", "data_freshness": {"market": "CURRENT", "fundamental": "VERY_STALE"}, "alternative_symbol": None}
        ]
        self.assertEqual(monitor.summary()["stale_count"], 1)

        monitor.allocator = SimpleNamespace(sectors={})
        monitor._previous_monitoring = lambda *_: None
        monitor._current_sector_fraction = lambda *_: 0.0
        monitor._replacement_candidate = lambda **_: (None, {})
        monitor._alternative_streak = lambda *_: 0
        position = {"id": 1, "symbol": "TEST"}
        assessment = {"state": HOLD, "market_session": "2026-10-19", "metrics_json": "{}", "explanation": "", "current_close": 1.0}

        def decision_for(freshness: str):
            monitor.fundamentals = SimpleNamespace(get_fundamentals_as_of=lambda *_: FundamentalSnapshot(
                symbol="TEST", as_of_date="2026-10-19", assessment="UNAVAILABLE" if freshness == "UNAVAILABLE" else "NEUTRAL",
                latest_period=None, publication_timestamp=None, days_since_publication=None,
                data_freshness=freshness, sector="UNKNOWN", source="UNAVAILABLE", values={}, features={},
                data_quality={}, unavailable_fields=[], conflicts=[]))
            return monitor._evaluate(position, assessment, None, {})

        unavailable = decision_for("UNAVAILABLE")
        self.assertIn("FUNDAMENTAL_DATA_UNAVAILABLE", unavailable.reason_codes)
        self.assertNotIn("FUNDAMENTAL_DATA_STALE", unavailable.reason_codes)
        old = decision_for("VERY_STALE")
        self.assertIn("FUNDAMENTAL_DATA_STALE", old.reason_codes)

    def test_installed_official_panel_hindzinc_and_nifty200_impact(self) -> None:
        panel = ENGINE_ROOT / PANEL_RELATIVE
        universe_files = sorted((ENGINE_ROOT / "data/official/nifty200").glob("ind_nifty200list_*.csv"))
        if not panel.exists() or not universe_files:
            self.skipTest("official Phase 5 panel or NIFTY 200 universe is not present")
        with temporary_directory() as temp_dir:
            db = AppDatabase(Path(temp_dir) / "gate-a.sqlite3")
            db.initialize()
            service = FundamentalSnapshotService(ENGINE_ROOT, db)
            hindzinc = service.get_snapshot("HINDZINC", "2026-10-19")
            self.assertEqual(hindzinc.latest_period, "2026-06-30")
            self.assertEqual(hindzinc.publication_timestamp, "2026-07-24T17:34:31+05:30")
            self.assertEqual(hindzinc.days_since_publication, 87)
            self.assertEqual(hindzinc.data_freshness, "FRESH")
            self.assertEqual(hindzinc.source, "OFFICIAL_PHASE5_CANONICAL_PANEL")

            with universe_files[-1].open(encoding="utf-8-sig", newline="") as handle:
                symbols = [str(row["Symbol"]).strip().upper().replace(".NS", "") for row in csv.DictReader(handle)]
            states: dict[str, list[str]] = {key: [] for key in ["FRESH", "STALE", "VERY_STALE", "UNAVAILABLE"]}
            for symbol in symbols:
                states[service.get_snapshot(symbol, "2026-10-19").data_freshness].append(symbol)
            self.assertEqual(len(symbols), 200)
            self.assertGreaterEqual(len(states["FRESH"]), 150)
            audit = {
                "as_of_date": "2026-10-19",
                "universe_path": str(universe_files[-1]),
                "panel_path": str(panel),
                "counts": {key: len(value) for key, value in states.items()},
                "symbols": states,
                "hindzinc": {
                    "latest_period": hindzinc.latest_period,
                    "publication_timestamp": hindzinc.publication_timestamp,
                    "days_since_publication": hindzinc.days_since_publication,
                    "freshness": hindzinc.data_freshness,
                    "source": hindzinc.source,
                },
            }
            output = Path(os.environ.get("SRE_GATE_A_AUDIT_OUT", Path(temp_dir) / "gate-a-audit.json"))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
            print(json.dumps(audit["counts"], sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
