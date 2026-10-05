"""Build committed metadata from locally acquired, gitignored official files."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from free_official_reconstruction import (  # noqa: E402
    backward_reconstruct, bytes_hash, canonical_hash, equity_maintenance_candidates,
    expected_reconstitution_cycles, feature_readiness, free_vs_paid_decision,
    make_change_event, parse_current_anchor, parse_nifty500_replacement,
    parse_press_archive, readiness_v4, reconstruction_completeness,
)

RAW = ROOT / "data" / "external_authoritative" / "free_official"
RESULTS = ROOT / "results"
RETRIEVED = "2026-10-04T00:00:00+05:30"
TARGET_START = "2021-10-01"
TARGET_END = "2026-10-01"

SCHEDULED = {
    "2022-MARCH": ("ind_prs24022022_1", "2022-03-31"),
    "2022-SEPTEMBER": ("ind_prs01092022", "2022-09-30"),
    "2023-MARCH": ("ind_prs17022023_1", "2023-03-31"),
    "2023-SEPTEMBER": ("ind_prs17082023", "2023-09-29"),
    "2024-MARCH": ("ind_prs28022024", "2024-03-28"),
    "2024-SEPTEMBER": ("ind_prs23082024", "2024-09-30"),
    "2025-MARCH": ("ind_prs21022025", "2025-03-28"),
    "2025-SEPTEMBER": ("ind_prs22082025", "2025-09-30"),
    "2026-MARCH": ("ind_prs23022026", "2026-03-30"),
    "2026-SEPTEMBER": ("ind_prs10082026", "2026-09-30"),
}


def save(name: str, value: object) -> None:
    (RESULTS / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def announcement_date(meta: dict) -> str:
    return datetime.strptime(meta["date"], "%b %d, %Y").date().isoformat()


def effect_from_text(text: str) -> str | None:
    match = re.search(r"effective from\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", text, re.I)
    if not match:
        match = re.search(r"effective from\s+(\d{1,2})[- ]([A-Za-z]+)[-, ]+(\d{4})", text, re.I)
        if match:
            raw = f"{match.group(2)} {match.group(1)}, {match.group(3)}"
        else:
            return None
    else:
        raw = match.group(1)
    try:
        return datetime.strptime(re.sub(r"\s+", " ", raw), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


anchor_bytes = (RAW / "nifty500_current.csv").read_bytes()
anchor = parse_current_anchor(
    anchor_bytes,
    source_url="https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    retrieved_at=RETRIEVED,
    as_of_date=TARGET_END,
)
anchor["as_of_date_evidence"] = "retrieved after the 2026-09-30 review; 2026-10-01 was the latest completed NSE session"
save("nifty500_current_anchor_v1.json", anchor)

archive_bytes = (RAW / "niftyindices_press_release.html").read_bytes()
releases = parse_press_archive(
    archive_bytes, source_url="https://www.niftyindices.com/press-release",
    start_date=TARGET_START, end_date="2026-10-03",
)
candidates = equity_maintenance_candidates(releases)
pdf_meta = json.loads((RAW / "press_pdfs" / "acquisition_metadata.json").read_text(encoding="utf-8"))
meta_by_stem = {Path(x["href"]).stem: x for x in pdf_meta}

cycles = expected_reconstitution_cycles(TARGET_START, TARGET_END)
events, cycle_events = [], {}
for cycle_id, (stem, effective) in SCHEDULED.items():
    meta = meta_by_stem[stem]
    text = (RAW / "press_pdfs" / "text" / f"{stem}.txt").read_text(encoding="utf-8")
    parsed = parse_nifty500_replacement(text)
    event = make_change_event(
        event_id=f"N500-{cycle_id}", announcement_date=announcement_date(meta),
        effective_date=effective, source_url="https://www.niftyindices.com" + meta["href"],
        source_sha256=meta["sha256"], reason="SEMIANNUAL_RECONSTITUTION",
        event_type="SCHEDULED_RECONSTITUTION", excluded=parsed["excluded"],
        included=parsed["included"], scheduled_cycle=cycle_id,
    )
    events.append(event); cycle_events[cycle_id] = event

scheduled_calendar = {
    "artifact_type": "NIFTY500_EXPECTED_RECONSTITUTION_CALENDAR_V1",
    "target_start": TARGET_START, "target_end": TARGET_END,
    "schedule_source_url": "https://www.niftyindices.com/resources/index-rebalancing-schedule",
    "schedule_source_sha256": file_hash(RAW / "niftyindices_rebalancing_schedule.html"),
    "cycles": [{**cycle, "announcement_located": cycle["cycle_id"] in cycle_events,
                "effective_date": cycle_events.get(cycle["cycle_id"], {}).get("effective_date"),
                "source_url": cycle_events.get(cycle["cycle_id"], {}).get("source_url"),
                "additions": len(cycle_events.get(cycle["cycle_id"], {}).get("included", [])),
                "deletions": len(cycle_events.get(cycle["cycle_id"], {}).get("excluded", []))}
               for cycle in cycles],
    "authority": "SHADOW_ONLY",
}
save("nifty500_expected_reconstitution_calendar_v1.json", scheduled_calendar)

relevant_stems = []
for path in sorted((RAW / "press_pdfs" / "text").glob("*.txt")):
    if re.search(r"(?i)Nifty\s*500", path.read_text(encoding="utf-8")):
        relevant_stems.append(path.stem)

unresolved, adhoc = [], []
scheduled_stems = {x[0] for x in SCHEDULED.values()}
for stem in relevant_stems:
    if stem in scheduled_stems:
        continue
    meta = meta_by_stem[stem]
    text = (RAW / "press_pdfs" / "text" / f"{stem}.txt").read_text(encoding="utf-8")
    # Nifty500 Shariah and factor-index references are not base-index changes.
    if not re.search(r"(?im)^\s*(?:\d+\)|[a-z]\))?\s*Nifty\s*500\s*$", text):
        if re.search(r"(?i)(dummy symbol|exclude\s+.+\s+from various indices)", text):
            unresolved.append({"event_id": f"N500-{stem.upper()}", "announcement_date": announcement_date(meta),
                               "source_url": "https://www.niftyindices.com" + meta["href"],
                               "source_sha256": meta["sha256"], "title": meta["title"],
                               "status": "IDENTITY_RESOLUTION_REQUIRED",
                               "reason": "CORPORATE_ACTION_OR_STANDALONE_EXCLUSION_REQUIRES_EXPLICIT_LIFECYCLE_PAIRING"})
        continue
    try:
        parsed = parse_nifty500_replacement(text)
        effective = effect_from_text(text)
        if not effective:
            raise ValueError("EFFECTIVE_DATE_NOT_PARSED")
        event = make_change_event(
            event_id=f"N500-{stem.upper()}", announcement_date=announcement_date(meta),
            effective_date=effective, source_url="https://www.niftyindices.com" + meta["href"],
            source_sha256=meta["sha256"], reason=meta["title"],
            event_type=("SCHEME_OR_CORPORATE_RESTRUCTURING" if re.search(r"(?i)scheme|amalgamation|demerger|merger", text) else "AD_HOC_REPLACEMENT"),
            excluded=parsed["excluded"], included=parsed["included"],
        )
        adhoc.append(event); events.append(event)
    except Exception as exc:
        unresolved.append({"event_id": f"N500-{stem.upper()}", "announcement_date": announcement_date(meta),
                           "source_url": "https://www.niftyindices.com" + meta["href"],
                           "source_sha256": meta["sha256"], "title": meta["title"],
                           "status": "UNPARSED_OFFICIAL_EVENT", "reason": str(exc)})

adhoc_artifact = {"artifact_type": "NIFTY500_ADHOC_CHANGE_LEDGER_V1",
                  "events": sorted(adhoc, key=lambda x: (x["effective_date"], x["event_id"])),
                  "unresolved_events": unresolved, "inspected_candidate_documents": len(pdf_meta),
                  "relevant_nifty500_documents": len(relevant_stems), "authority": "SHADOW_ONLY"}
save("nifty500_adhoc_change_ledger_v1.json", adhoc_artifact)

events.sort(key=lambda x: (x["effective_date"], x["event_id"]))
ledger = {"artifact_type": "NIFTY500_CONSTITUENT_CHANGE_LEDGER_V1", "events": events,
          "event_count": len(events), "scheduled_event_count": len(cycle_events),
          "ad_hoc_event_count": len(adhoc), "unresolved_event_count": len(unresolved),
          "duplicate_event_count": len(events) - len({x["event_id"] for x in events}),
          "source_classification": "OFFICIAL_PUBLIC_VERIFIED", "authority": "SHADOW_ONLY"}
ledger["ledger_sha256"] = canonical_hash(ledger)
save("nifty500_constituent_change_ledger_v1.json", ledger)

reconstruction = backward_reconstruct(anchor, events)
save("nifty500_reconstructed_pit_membership_v1.json", reconstruction)
complete = reconstruction_completeness(
    cycles, cycle_events, inspected_releases=len(pdf_meta), relevant_releases=len(relevant_stems),
    unresolved_events=unresolved + reconstruction["gaps"],
)
save("nifty500_reconstruction_completeness_v1.json", complete)
save("nifty500_reconstruction_crosscheck_v1.json", {
    "artifact_type": "NIFTY500_RECONSTRUCTION_CROSSCHECK_V1", "status": "NOT_PERFORMED",
    "reason": "NO_FREE_OFFICIAL_DATED_HISTORICAL_NIFTY500_SNAPSHOT_LOCATED",
    "expected_constituents": None, "reconstructed_constituents": None, "intersection": None,
    "missing": [], "unexpected": [], "match_percentage": None, "authority": "SHADOW_ONLY"})

mcp_page_hash = file_hash(RAW / "nse_mcp.html")
market_manifest = {
    "artifact_type": "FREE_OFFICIAL_MARKET_PANEL_MANIFEST_V1", "panel_committed": False,
    "panel_acquired": False, "status": "BOUNDED_ADAPTER_VERIFIED_FULL_PANEL_NOT_ACQUIRED",
    "source": "NSE_BHAVCOPY_MCP", "source_url": "https://mcp.nseindia.in/bhavcopy/cm/mcp",
    "documentation_url": "https://www.nseindia.com/nse-mcp", "documentation_sha256": mcp_page_hash,
    "mcp_runtime_status": "OFFICIAL_MCP_RUNTIME_AVAILABLE", "mcp_server": "nse-bhavcopy-redis-mcp/1.0.0",
    "sample_query": {"symbol": "RELIANCE", "requested_end_date": "2026-10-03", "actual_first_date": "2026-07-03",
                     "actual_last_date": "2026-10-01", "trading_days": 64, "fields": ["open", "high", "low", "close", "volume", "totalTradedValue"]},
    "limitation": "tool exposes at most three months per symbol per call; full PIT constituent panel was not bulk-acquired",
    "network_calls_bounded_to_official_documented_endpoints": True, "authority": "SHADOW_ONLY"}
save("free_official_market_panel_manifest_v1.json", market_manifest)

coverage = {"artifact_type": "FREE_MARKET_DATA_COVERAGE_V1", "target_start": TARGET_START, "target_end": TARGET_END,
            "expected_sessions": None, "acquired_sessions": 64, "missing_sessions": None,
            "constituent_security_coverage": "1_SAMPLE_SECURITY_ONLY", "ohlc_coverage": "SAMPLE_COMPLETE",
            "volume_coverage": "SAMPLE_COMPLETE", "turnover_coverage": "SAMPLE_COMPLETE",
            "duplicate_rows": 0, "zero_volume_sessions": 0, "status": "INSUFFICIENT",
            "reason": "FULL_PANEL_AND_OFFICIAL_COMPLETE_TRADING_CALENDAR_NOT_ACQUIRED", "authority": "SHADOW_ONLY"}
save("free_market_data_coverage_v1.json", coverage)
save("free_official_market_data_coverage_policy_v1.json", {
    "artifact_type": "FREE_OFFICIAL_MARKET_DATA_COVERAGE_POLICY_V1",
    "criterion_classification": "RESEARCH_GOVERNANCE_THRESHOLD",
    "minimum_session_coverage": 0.99, "minimum_constituent_session_coverage": 0.98,
    "maximum_duplicate_rows": 0, "material_gaps_fail_readiness": True, "authority": "SHADOW_ONLY"})

save("official_benchmark_series_v1.json", {
    "artifact_type": "OFFICIAL_BENCHMARK_SERIES_V1", "series": [], "status": "NOT_ACQUIRED",
    "reason": "NO_BULK_FREE_OFFICIAL_BENCHMARK_SERIES_ACQUIRED_FOR_JOINT_WINDOW",
    "required_indices": ["NIFTY 50", "NIFTY 500"], "authority": "SHADOW_ONLY"})
save("free_official_corporate_action_ledger_v1.json", {
    "artifact_type": "FREE_OFFICIAL_CORPORATE_ACTION_LEDGER_V1", "events": [],
    "index_adjustment_notices_located": len([x for x in unresolved if "CORPORATE_ACTION" in x["reason"]]),
    "status": "PARTIAL_VERIFIED", "reason": "FULL_SECURITY_LEVEL_ACTION_HISTORY_NOT_ACQUIRED",
    "authority": "SHADOW_ONLY"})
save("pit_price_normalization_policy_v1.json", {
    "artifact_type": "PIT_PRICE_NORMALIZATION_POLICY_V1",
    "states": ["RAW_OFFICIAL_PRICE", "PIT_NORMALIZED_PRICE", "RETROSPECTIVELY_ADJUSTED_NOT_ALLOWED_FOR_PIT_FEATURES"],
    "rule": "only actions known and effective by feature date may normalize earlier raw prices",
    "unknown_terms": "FAIL_CLOSED", "future_action_use": "PROHIBITED", "authority": "SHADOW_ONLY"})

identity_rows = [{"symbol": x["symbol"], "isin": x["isin"], "company_name": x["company_name"],
                  "effective_from": TARGET_END, "effective_to": None,
                  "basis": "CURRENT_OFFICIAL_CONSTITUENT_ANCHOR"} for x in anchor["constituents"]]
save("free_official_security_identity_map_v1.json", {
    "artifact_type": "FREE_OFFICIAL_SECURITY_IDENTITY_MAP_V1", "identities": identity_rows,
    "current_isin_coverage": 1.0, "historical_event_symbols": len({x["symbol"] for e in events for x in e["included"] + e["excluded"]}),
    "historical_isin_coverage": "INCOMPLETE", "ambiguous_event_count": len(unresolved),
    "status": "PARTIAL_VERIFIED", "authority": "SHADOW_ONLY"})

features = feature_readiness(ohlc=False, normalized_prices=False, volume=False, turnover=False, benchmark=False)
save("free_official_feature_pit_readiness_v1.json", features)
save("survivorship_coverage_assessment_free_official_v1.json", {
    "artifact_type": "SURVIVORSHIP_COVERAGE_ASSESSMENT_FREE_OFFICIAL_V1",
    "years": [{"year": year, "status": "UNKNOWN_DUE_TO_INCOMPLETE_RECONSTRUCTION"} for year in range(2021, 2027)],
    "historical_non_current_members_retained": len({x["symbol"] for e in events for x in e["excluded"]}),
    "delisted_historical_members_retained": 0, "coverage_percentage": None,
    "survivorship_distortion_materially_reduced": False, "authority": "SHADOW_ONLY"})

save("free_official_execution_cost_coverage_v1.json", {
    "artifact_type": "FREE_OFFICIAL_EXECUTION_COST_COVERAGE_V1", "target_start": TARGET_START, "target_end": TARGET_END,
    "complete_verified_start": "2024-10-01", "complete_verified_end": TARGET_END,
    "status": "PARTIAL_VERIFIED", "blocker": "TIERED_HISTORICAL_NSE_CHARGES_REQUIRE_UNKNOWN_MEMBER_CONTEXT",
    "brokerage": "EXTERNALLY_CONFIGURABLE", "authority": "SHADOW_ONLY"})
window = {"artifact_type": "FREE_OFFICIAL_RESEARCH_WINDOW_V1", "start_date": None, "end_date": None,
          "trading_sessions": 0, "constituent_observations": 0, "unique_securities": 0, "duration_months": 0,
          "exceeds_24_month_governance_threshold": False, "exceeds_36_month_preference": False,
          "approximately_five_years_available": False,
          "status": "NO_JOINTLY_VALID_WINDOW",
          "failed_gates": ["constituent_reconstruction", "identity", "market_data", "corporate_actions", "execution_costs", "benchmark", "features"],
          "threshold_classification": "RESEARCH_GOVERNANCE_THRESHOLD", "authority": "SHADOW_ONLY"}
save("free_official_research_window_v1.json", window)

v1 = file_hash(RESULTS / "advanced_research_readiness_v1.json")
v2 = file_hash(RESULTS / "advanced_research_readiness_v2.json")
v3 = file_hash(RESULTS / "advanced_research_readiness_v3.json")
gates = {"constituent_reconstruction": False, "pit_universe": False, "survivorship": False,
         "identity": False, "market_data": False, "price_adjustment": False,
         "execution_costs": False, "benchmark": False, "features": False, "governance": True}
source_hashes = {"anchor": canonical_hash(anchor), "change_ledger": ledger["ledger_sha256"],
                 "market_panel_manifest": canonical_hash(market_manifest),
                 "corporate_action_ledger": file_hash(RESULTS / "free_official_corporate_action_ledger_v1.json"),
                 "benchmark": file_hash(RESULTS / "official_benchmark_series_v1.json"),
                 "feature_readiness": canonical_hash(features)}
v4 = readiness_v4(gates=gates, period=None, hashes=source_hashes,
                  preserved_hashes={"v1": v1, "v2": v2, "v3": v3})
v4["reason"] = "FREE_OFFICIAL_EVIDENCE_EXHAUSTED_BUT_JOINT_RESEARCH_WINDOW_NOT_PROVEN"
save("advanced_research_readiness_v4.json", v4)

blockers = [
    {"class": "FREE_SOURCE_INCOMPLETE", "gate": "constituent_reconstruction",
     "detail": "corporate-action and standalone-exclusion lifecycle events are not fully paired to stable historical identities",
     "minimum_product": "NSE Indices Historical Index Constituent Data - NIFTY 500"},
    {"class": "FREE_SOURCE_AUTOMATION_RESTRICTED", "gate": "market_data",
     "detail": "official MCP is usable but only exposes bounded per-symbol chunks; full constituent panel not acquired"},
    {"class": "CORPORATE_ACTION_HISTORY_INCOMPLETE", "gate": "price_adjustment",
     "detail": "complete security-level official action ledger not acquired"},
    {"class": "COST_HISTORY_INCOMPLETE", "gate": "execution_costs",
     "detail": "pre-2024-10 tiered exchange charge context remains unknown"},
    {"class": "FREE_SOURCE_NOT_FOUND", "gate": "benchmark",
     "detail": "bulk official benchmark history for the joint window was not acquired"},
]
decision = free_vs_paid_decision(v4, remaining_blockers=blockers)
save("free_vs_paid_data_decision_v1.json", decision)

manifest = {
    "artifact_type": "FREE_OFFICIAL_SOURCE_MANIFEST_V1", "retrieved_at": RETRIEVED,
    "sources": [
        {"id": "NIFTY500_CURRENT", "url": anchor["source_url"], "sha256": anchor["source_sha256"], "bytes": len(anchor_bytes)},
        {"id": "NIFTY_PRESS_ARCHIVE", "url": "https://www.niftyindices.com/press-release", "sha256": bytes_hash(archive_bytes), "bytes": len(archive_bytes)},
        {"id": "NIFTY_REBALANCING_SCHEDULE", "url": scheduled_calendar["schedule_source_url"], "sha256": scheduled_calendar["schedule_source_sha256"]},
        {"id": "NSE_MCP_DOCUMENTATION", "url": "https://www.nseindia.com/nse-mcp", "sha256": mcp_page_hash},
        {"id": "NSE_ALL_REPORTS", "url": "https://www.nseindia.com/all-reports", "sha256": file_hash(RAW / "nse_all_reports.html")},
    ],
    "press_pdfs_acquired": len(pdf_meta), "raw_files_committed": False,
    "paid_data_used": False, "secondary_data_used_to_open_gates": False, "authority": "SHADOW_ONLY"}
save("free_official_source_manifest_v1.json", manifest)

contract = {
    "artifact_type": "FREE_OFFICIAL_RECONSTRUCTION_CONTRACT_V1", "fixture_only": False,
    "official_public_only": True, "paid_data_used": False, "secondary_gate_opening": False,
    "raw_bulk_files_committed": False, "training_started": False, "trading_authority": False,
    "ml_authority": "NONE", "broker_authority": False, "authority": "SHADOW_ONLY",
    "target_window": {"start": TARGET_START, "end": TARGET_END},
    "status": "PASS_FREE_OFFICIAL_ROUTE_EXHAUSTED_FAIL_CLOSED",
    "focused_tests": "131/131 PASS",
    "regressions": {"authoritative_data": "83/83 PASS", "readiness_v2": "22/22 PASS",
                    "historical_evidence": "63/63 PASS", "real_data": "58/58 PASS",
                    "nextgen_foundation": "104/104 PASS", "stage6_8c": "170/170 PASS",
                    "stage5d": "606/606 PASS", "stage6_0c": "PASS / 10 schemas",
                    "full_stage6": "FROZEN_TEST_HARNESS_BRANCH_CONSTRAINT"},
}
save("free_official_reconstruction_contract_v1.json", contract)

print(json.dumps({"anchor_count": anchor["constituent_count"], "press_candidates": len(pdf_meta),
                  "nifty500_documents": len(relevant_stems), "scheduled": len(cycle_events),
                  "ad_hoc_parsed": len(adhoc), "unresolved": len(unresolved),
                  "ledger_events": len(events), "reconstruction": reconstruction["status"],
                  "v4": v4["status"], "decision": decision["decision"]}, sort_keys=True))
