"""Build committed, bounded historical-evidence summaries from ignored official archives."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from common import file_sha256, load_json, record
from real_data_foundation import parse_nse_security_master, parse_nse_delistings_xlsx
from historical_evidence import (
    advanced_research_readiness, build_execution_coverage_matrix,
    build_pit_coverage_audit, load_historical_cost_book, parse_index_change_events,
)


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


master_path = ROOT / "data/raw/nse/EQUITY_L.csv"
delisting_path = ROOT / "data/raw/nse/delisted_companies.xlsx"
if not master_path.is_file() or not delisting_path.is_file():
    raise SystemExit("OFFICIAL_GITIGNORED_ARCHIVES_REQUIRED")

master_bytes = master_path.read_bytes()
securities = parse_nse_security_master(
    master_bytes, observed_date="2026-10-03",
    source_reference="https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    source_hash="95f0d731f5858f71e876c45377dcefa79bc7a8db1e8161d0c92320252af4aa8f",
)
delistings = parse_nse_delistings_xlsx(
    delisting_path.read_bytes(), retrieved_at="2026-10-03T00:00:00Z",
    source_reference="https://nsearchives.nseindia.com/web/mediaattachment/2026-09/Copy_of_List_of_delisted_Companies_20260612152719_9_20260901172525_1_20260910122051.xlsx",
    source_hash="fcc27d5850f381fa0193003ddbd4d2f7724c770e9082d7fbbad6b97dd87f1664",
)

index_fixture = ROOT / "fixtures/nifty50_change_events_2020.csv"
index_events = parse_index_change_events(
    index_fixture.read_bytes(), source_reference="NSE_INDICES_OFFICIAL_CHANGE_NOTICES_2020"
)
book_path = ROOT / "execution_india/india_equity_cost_schedule_history_v2.json"
book = load_historical_cost_book(book_path)
matrix = build_execution_coverage_matrix(book)
audit = build_pit_coverage_audit(
    securities, delistings,
    exact_snapshots={2026: {row["security_id"] for row in securities}},
    source_ids=["NSE_EQUITY_SECURITY_MASTER_20261003", "NSE_DELISTED_COMPANIES_20260910"],
)
readiness = advanced_research_readiness(
    audit, matrix, leakage_safe=False, governance_ready=True, benchmark_prices_available=True
)

write(ROOT / "results/execution_cost_coverage_matrix_v1.json", matrix)
write(ROOT / "results/pit_universe_coverage_audit_v1.json", audit)
write(ROOT / "results/advanced_research_readiness_v1.json", readiness)

manifest = record("NEXTGEN_HISTORICAL_EVIDENCE_MANIFEST_V1", {
    "parent_commit": "354eb36e3383e5de303b1189e01313c7336657f0",
    "branch": "nextgen-research-historical-evidence",
    "research_period": "2016-01-01..2026-10-03",
    "security_master_records": len(securities), "delisting_records": len(delistings),
    "index_change_events": len(index_events), "dated_security_master_status": "DATED_SECURITY_MASTER_DATA_GAP",
    "component_file_sha256": {
        "source_manifest": file_sha256(ROOT / "data/manifests/historical_evidence_source_manifest_v1.json"),
        "historical_cost_book": file_sha256(book_path),
        "execution_coverage": file_sha256(ROOT / "results/execution_cost_coverage_matrix_v1.json"),
        "pit_coverage": file_sha256(ROOT / "results/pit_universe_coverage_audit_v1.json"),
        "readiness": file_sha256(ROOT / "results/advanced_research_readiness_v1.json"),
    },
    "fixture_only_tests": True, "network_calls_in_tests": 0, "live_connectors": 0,
    "active_lane_changed_files": 0, "authority_scope": "RESEARCH_ONLY",
    "model_training": False, "trading_authority": False, "ml_authority": "NONE",
})
write(ROOT / "historical_evidence_manifest_v1.json", manifest)
print(json.dumps({"securities": len(securities), "delistings": len(delistings), "index_events": len(index_events), "readiness": readiness["status"]}, sort_keys=True))
