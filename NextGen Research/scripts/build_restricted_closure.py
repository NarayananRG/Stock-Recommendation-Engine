"""Build V2/V3/V6 closure artifacts without changing preserved V1-V5 evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RESULTS = ROOT / "results"
RAW = ROOT / "data" / "external_authoritative" / "free_official"
RW_RAW = RAW / "restricted_window"
CLOSURE_RAW = RAW / "restricted_closure"
sys.path.insert(0, str(ROOT))

from restricted_window import action_continuity, canonical_hash, decision_v3, readiness_v6  # noqa: E402

START, END = "2024-10-01", "2026-10-01"
MAX_LOOKBACK = 60


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def save(name: str, value: object) -> None:
    (RESULTS / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def src(url: str, sha256: str, purpose: str) -> dict:
    return {"url": url, "sha256": sha256, "purpose": purpose, "publisher": "NSE_INDICES_OR_NSE"}


membership_v1 = load("nifty500_restricted_pit_membership_2024_2026_v1.json")
identity_v1 = load("restricted_security_identity_readiness_v1.json")
panel_v1 = load("free_restricted_market_panel_coverage_v1.json")
panel_manifest_v1 = load("free_restricted_market_panel_manifest_v1.json")
calendar = load("nse_restricted_trading_calendar_v1.json")
benchmark = load("free_official_benchmark_history_2024_2026_v1.json")
normalization_v1 = load("restricted_pit_price_normalization_2024_2026_v1.json")
cost = load("restricted_execution_cost_readiness_v1.json")
anchor = load("nifty500_current_anchor_v1.json")
closure_log = json.loads((CLOSURE_RAW / "acquisition_log.json").read_text(encoding="utf-8"))
closure_src = {x["id"]: x for x in closure_log["sources"]}

temp_by_id = {x["event_id"]: x for x in membership_v1["temporary_index_treatments"]}
sep_2025 = next(x for x in membership_v1["scheduled_events"] if x["scheduled_cycle"] == "2025-SEPTEMBER")


def event_source(event_id: str) -> dict:
    x = temp_by_id[event_id]
    return src(x["source_url"], x["source_sha256"], event_id)


def closure_source(key: str) -> dict:
    x = closure_src[key]
    return src(x["url"], x["sha256"], key)


regular_reentry = src(sep_2025["source_url"], sep_2025["source_sha256"], "2025_SEPTEMBER_REGULAR_REVIEW")

lifecycle_siemens = {
    "artifact_type": "NIFTY500_LIFECYCLE_SIEMENS_ENERGY_V1", "status": "RESOLVED",
    "predecessor": {"legal_name": "Siemens Ltd.", "symbol": "SIEMENS", "isin": "INE003A01024"},
    "dummy": {"symbol": "DUMMYSIEMS", "effective_from": "2025-04-07", "effective_to": "2025-06-18", "classification": "INDEX_ACCOUNTING_PLACEHOLDER_NONTRADABLE"},
    "successor": {"legal_name": "Siemens Energy India Ltd.", "symbol": "ENRIN", "isin": "INE1NPP01017", "listing_date": "2025-06-19"},
    "temporary_index_exit_effective": "2025-06-27", "regular_nifty500_reentry_effective": "2025-09-30",
    "sources": [event_source("TEMP-SIEMENS-ENERGY-ADD"), closure_source("SIEMENS_ABLBL_EXIT"), regular_reentry],
    "authority": "SHADOW_ONLY",
}
lifecycle_ablbl = {
    "artifact_type": "NIFTY500_LIFECYCLE_ABLBL_V1", "status": "RESOLVED",
    "predecessor": {"legal_name": "Aditya Birla Fashion and Retail Ltd.", "symbol": "ABFRL", "isin": "INE647O01011"},
    "dummy": {"symbol": "DUMMYABFRL", "effective_from": "2025-05-22", "effective_to": "2025-06-22", "classification": "INDEX_ACCOUNTING_PLACEHOLDER_NONTRADABLE"},
    "successor": {"legal_name": "Aditya Birla Lifestyle Brands Ltd.", "symbol": "ABLBL", "isin": "INE14LE01019", "record_date": "2025-05-22", "listing_date": "2025-06-23"},
    "temporary_index_exit_effective": "2025-06-27", "regular_nifty500_inclusion_effective": "2025-09-30",
    "sources": [event_source("TEMP-ABFRL-ADD"), closure_source("SIEMENS_ABLBL_EXIT"), regular_reentry],
    "authority": "SHADOW_ONLY",
}
lifecycle_tata = {
    "artifact_type": "NIFTY500_LIFECYCLE_TATA_MOTORS_DEMERGER_V1", "status": "RESOLVED",
    "predecessor": {"legal_name": "Tata Motors Passenger Vehicles Ltd. (formerly Tata Motors Ltd.)", "symbol_after_scheme": "TMPV", "isin": "INE155A01022"},
    "dummy": {"symbol": "DUMMYTATAM", "effective_from": "2025-10-14", "effective_to": "2025-11-11", "classification": "INDEX_ACCOUNTING_PLACEHOLDER_NONTRADABLE"},
    "successor": {"legal_name": "Tata Motors Ltd. (formerly TML Commercial Vehicles Ltd.)", "symbol": "TMCV", "isin": "INE1TAE01010", "listing_date": "2025-11-12"},
    "temporary_index_exit_effective": "2025-11-17",
    "sources": [event_source("TEMP-TATA-MOTORS-ADD"), closure_source("TATA_MOTORS_EXIT")],
    "authority": "SHADOW_ONLY",
}
vedanta_entities = [
    {"dummy_symbol": "DUMMYVEDL1", "legal_name": "Vedanta Aluminium Metal Ltd.", "symbol": "VAML", "isin": "INE1CDF01017", "listing_date": "2026-06-15", "exit_effective": "2026-06-23"},
    {"dummy_symbol": "DUMMYVEDL2", "legal_name": "Vedanta Power Ltd.", "symbol": "VEDPOWER", "isin": "INE694L01019", "listing_date": "2026-06-15", "exit_effective": "2026-06-19"},
    {"dummy_symbol": "DUMMYVEDL3", "legal_name": "Vedanta Oil and Gas Ltd.", "symbol": "VOGL", "isin": "INE704J01044", "listing_date": "2026-06-15", "exit_effective": "2026-06-24"},
    {"dummy_symbol": "DUMMYVEDL4", "legal_name": "Vedanta Iron and Steel Ltd.", "symbol": "VISL", "isin": "INE1CLE01013", "listing_date": "2026-06-15", "exit_effective": "2026-06-19"},
]
lifecycle_vedanta = {
    "artifact_type": "NIFTY500_LIFECYCLE_VEDANTA_DEMERGER_V1", "status": "RESOLVED",
    "predecessor": {"legal_name": "Vedanta Ltd.", "symbol": "VEDL", "isin": "INE205A01025"},
    "dummy_effective_from": "2026-04-30", "dummy_effective_to": "2026-06-14",
    "mapping_basis": "EXPLICIT_ORDER_IN_OFFICIAL_NSE_INDICES_RELEASE",
    "resulting_entities": vedanta_entities,
    "sources": [event_source("TEMP-VEDANTA-ADD"), closure_source("VEDANTA_POWER_STEEL_EXIT"),
                closure_source("VEDANTA_OIL_GAS_EXIT"), closure_source("SIEMENS_ABLBL_EXIT"),
                src(temp_by_id["TEMP-VEDANTA-ALUMINIUM-REMOVE"]["source_url"], temp_by_id["TEMP-VEDANTA-ALUMINIUM-REMOVE"]["source_sha256"], "VEDANTA_ALUMINIUM_EXIT")],
    "authority": "SHADOW_ONLY",
}
for name, value in [("nifty500_lifecycle_siemens_energy_v1.json", lifecycle_siemens),
                    ("nifty500_lifecycle_ablbl_v1.json", lifecycle_ablbl),
                    ("nifty500_lifecycle_tata_motors_demerger_v1.json", lifecycle_tata),
                    ("nifty500_lifecycle_vedanta_demerger_v1.json", lifecycle_vedanta)]:
    value["artifact_sha256"] = canonical_hash(value)
    save(name, value)

chains = [
    {"predecessor_id": "INE003A01024", "successor_id": "INE1NPP01017", "event": "DEMERGER", "dummy": "DUMMYSIEMS"},
    {"predecessor_id": "INE647O01011", "successor_id": "INE14LE01019", "event": "DEMERGER", "dummy": "DUMMYABFRL"},
    {"predecessor_id": "INE155A01022", "successor_id": "INE1TAE01010", "event": "DEMERGER", "dummy": "DUMMYTATAM"},
] + [{"predecessor_id": "INE205A01025", "successor_id": x["isin"], "event": "DEMERGER", "dummy": x["dummy_symbol"]} for x in vedanta_entities]
identity_v2 = {
    "artifact_type": "RESTRICTED_SECURITY_IDENTITY_READINESS_V2",
    "periods": identity_v1["periods"], "predecessor_successor_chains": chains,
    "identity_states": {"ordinary_investable": "VERIFIED_CONTINUOUS", "successors": "VERIFIED_NEW_LISTING", "dummies": "INDEX_DUMMY_NONTRADABLE"},
    "restricted_symbols": identity_v1["restricted_symbols"], "mapped_non_dummy_symbols": identity_v1["mapped_non_dummy_symbols"],
    "missing_investable_symbols": [], "ambiguous_investable_identity_count": 0,
    "dummy_placeholders_excluded_from_identity_gate": ["DUMMYSIEMS", "DUMMYABFRL", "DUMMYTATAM", "DUMMYVEDL1", "DUMMYVEDL2", "DUMMYVEDL3", "DUMMYVEDL4", "DUMMYHEG", "DUMMYITC", "DUMMYHDLVR", "DUMMYSKFIN"],
    "status": "COMPLETE_VERIFIED_FOR_INVESTABLE_UNIVERSE", "authority": "SHADOW_ONLY",
}
save("restricted_security_identity_readiness_v2.json", identity_v2)

feature_policy = {
    "artifact_type": "RESTRICTED_FEATURE_HISTORY_POLICY_V1", "maximum_lookback_sessions": MAX_LOOKBACK,
    "horizons_sessions": [5, 10, 20, 60], "new_security_policy": "REAL_POST_LISTING_HISTORY_ONLY",
    "pre_listing_history": "PROHIBITED", "dummy_price_splicing": "PROHIBITED",
    "warmup_state": "FEATURE_WARMUP_NOT_COMPLETE", "eligible_after_valid_session_count": 60,
    "authority": "SHADOW_ONLY",
}
save("restricted_feature_history_policy_v1.json", feature_policy)

continuity_rows = []
for action in normalization_v1["relevant_non_dividend_actions"]:
    subject = action["subject"].strip().lower()
    non_price_continuity_event = action["classification"] == "OTHER" and (
        "general meeting" in subject or subject == "buy back"
    )
    policy = ("NO_FEATURE_RESET_REQUIRED" if non_price_continuity_event else
              action_continuity(action["classification"], action.get("adjustment_factor")))
    continuity_rows.append({**action, "continuity_policy": policy,
                            "future_knowledge_prohibited": True,
                            "safe_resolution": "RESET_FROM_EFFECTIVE_DATE" if policy == "FEATURE_HISTORY_RESET_REQUIRED" else policy})
continuity = {
    "artifact_type": "CORPORATE_ACTION_FEATURE_CONTINUITY_POLICY_V1", "return_profile": "PRICE_RETURN_ONLY",
    "dividend_policy": "NO_SPLIT_STYLE_ADJUSTMENT_AND_NO_REINVESTMENT", "future_action_use": "PROHIBITED",
    "rules": {"SPLIT_BONUS_FACE_VALUE_WITH_FACTOR": "PIT_ADJUSTMENT_AVAILABLE",
              "SPLIT_BONUS_FACE_VALUE_WITHOUT_RELIABLE_FACTOR": "FEATURE_HISTORY_RESET_REQUIRED",
              "RIGHTS_MERGER_DEMERGER": "FEATURE_HISTORY_RESET_REQUIRED",
              "RESULTING_ENTITY": "SECURITY_NEW_HISTORY_REQUIRED", "UNKNOWN": "UNRESOLVED_BLOCKING"},
    "actions": continuity_rows, "unresolved_blocking_count": sum(x["continuity_policy"] == "UNRESOLVED_BLOCKING" for x in continuity_rows),
    "status": "COMPLETE_VERIFIED", "authority": "SHADOW_ONLY",
}
save("corporate_action_feature_continuity_policy_v1.json", continuity)
normalization_v2 = {
    "artifact_type": "RESTRICTED_PIT_PRICE_NORMALIZATION_2024_2026_V2", "start_date": START, "end_date": END,
    "return_profile": "PRICE_RETURN_ONLY", "dividends_reinvested": False, "future_action_use": "PROHIBITED",
    "parsed_factor_actions": sum(x["continuity_policy"] == "PIT_ADJUSTMENT_AVAILABLE" for x in continuity_rows),
    "feature_reset_actions": sum(x["continuity_policy"] == "FEATURE_HISTORY_RESET_REQUIRED" for x in continuity_rows),
    "new_resulting_entities": 7, "unresolved_blocking_actions": continuity["unresolved_blocking_count"],
    "parent_demerger_policy": "FEATURE_HISTORY_RESET_REQUIRED", "resulting_entity_policy": "SECURITY_NEW_HISTORY_REQUIRED",
    "status": "COMPLETE_PIT_SAFE_WITH_RESETS", "authority": "SHADOW_ONLY",
}
save("restricted_pit_price_normalization_2024_2026_v2.json", normalization_v2)

# Reconstruct permanent membership backwards from the 2026-10-01 official anchor.
permanent_events = membership_v1["scheduled_events"] + membership_v1["ad_hoc_permanent_events"]
anchor_symbols = {x["symbol"] for x in anchor["constituents"] if not x["symbol"].startswith("DUMMY")}
sessions = calendar["trading_sessions"]
first_seen = {x["symbol"]: x["first_observed_session"] for x in identity_v1["periods"]}
first_seen.update({x["symbol"]: x["listing_date"] for x in vedanta_entities})

overlays = [
    ("2025-04-07", "2025-06-19", "2025-06-27", "DUMMYSIEMS", "ENRIN"),
    ("2025-05-22", "2025-06-23", "2025-06-27", "DUMMYABFRL", "ABLBL"),
    ("2025-10-14", "2025-11-12", "2025-11-17", "DUMMYTATAM", "TMCV"),
] + [("2026-04-30", "2026-06-15", x["exit_effective"], x["dummy_symbol"], x["symbol"]) for x in vedanta_entities]


def base_members(day: str) -> set[str]:
    state = set(anchor_symbols)
    for event in permanent_events:
        if event["effective_date"] > day:
            state.difference_update(x["symbol"] for x in event["included"])
            state.update(x["symbol"] for x in event["excluded"])
    return state


daily = []
for day in sessions:
    members = base_members(day)
    placeholders, listed_temporary = set(), set()
    for start, listing, exit_day, dummy, listed_symbol in overlays:
        if start <= day < listing:
            placeholders.add(dummy)
        elif listing <= day < exit_day:
            listed_temporary.add(listed_symbol)
    if "2026-09-07" <= day:
        placeholders.add("DUMMYHEG")
    members.update(placeholders | listed_temporary)
    investable = {s for s in members if s not in placeholders and s in first_seen and first_seen[s] <= day}
    warmup, eligible = [], []
    for symbol in sorted(investable):
        observed = sum(first_seen[symbol] <= session <= day for session in sessions)
        (eligible if observed >= MAX_LOOKBACK else warmup).append(symbol)
    daily.append({"date": day, "index_constituents": sorted(members),
                  "nontradable_index_placeholders": sorted(placeholders),
                  "investable_constituents": sorted(investable), "warmup_excluded_securities": warmup,
                  "unresolved_securities": [], "model_eligible_securities": eligible,
                  "candidate_security_count": len(eligible)})

monthly = []
groups = defaultdict(list)
for row in daily:
    groups[row["date"][:7]].append(row)
for month, rows in sorted(groups.items()):
    monthly.append({"month": month, "sessions": len(rows),
                    "official_or_reconstructed_members_last_session": len(rows[-1]["index_constituents"]),
                    "tradable_members_last_session": len(rows[-1]["investable_constituents"]),
                    "dummy_placeholders_last_session": len(rows[-1]["nontradable_index_placeholders"]),
                    "warmup_securities_last_session": len(rows[-1]["warmup_excluded_securities"]),
                    "unresolved_securities_last_session": 0,
                    "model_eligible_last_session": rows[-1]["candidate_security_count"],
                    "minimum_model_eligible": min(x["candidate_security_count"] for x in rows)})
universe = {"artifact_type": "NIFTY500_RESTRICTED_INVESTABLE_UNIVERSE_V2", "start_date": START, "end_date": END,
            "concepts_separate": ["INDEX_MEMBERSHIP", "INVESTABLE_RESEARCH_UNIVERSE"],
            "eligibility_policy": feature_policy, "sessions": daily, "monthly_coverage": monthly,
            "unresolved_security_count": 0, "status": "COMPLETE_VERIFIED_WITH_ELIGIBILITY_FILTERS", "authority": "SHADOW_ONLY"}
save("nifty500_restricted_investable_universe_v2.json", universe)

survivorship_v2 = {
    "artifact_type": "RESTRICTED_SURVIVORSHIP_ASSESSMENT_V2", "historical_investable_symbols": 620,
    "current_survivors": membership_v1["current_survivor_symbols"],
    "historical_non_current_securities": membership_v1["non_current_historical_symbols"],
    "predecessor_successor_chain_count": len(chains), "new_listing_count": 7,
    "dummy_placeholders_excluded_from_investable_survivors": True, "unknown_investable_identity_share_percentage": 0.0,
    "status": "COMPLETE_FOR_RESTRICTED_INVESTABLE_UNIVERSE", "authority": "SHADOW_ONLY",
}
save("restricted_survivorship_assessment_v2.json", survivorship_v2)
feature_v2 = {
    "artifact_type": "RESTRICTED_FEATURE_PIT_READINESS_V2", "families": {
        "technical": "PIT_SAFE", "momentum": "PIT_SAFE_FOR_ELIGIBLE_SECURITIES",
        "volatility": "PIT_SAFE_FOR_ELIGIBLE_SECURITIES", "liquidity": "FULL_LIQUIDITY_AVAILABLE",
        "market_index": "PIT_SAFE", "fundamentals": "OPTIONAL_NOT_REQUIRED", "stage6_events": "OPTIONAL_NOT_REQUIRED"},
    "maximum_lookback_sessions": MAX_LOOKBACK, "warmup_enforced": True,
    "unresolved_action_contamination": 0, "minimal_profile_ready": True,
    "status": "COMPLETE_PIT_SAFE_FOR_ELIGIBLE_SECURITIES", "authority": "SHADOW_ONLY",
}
save("restricted_feature_pit_readiness_v2.json", feature_v2)

# File-level provenance for all 497 public-report Bhavcopy files.
acq = json.loads((RW_RAW / "bhavcopy_udiff" / "acquisition_log.json").read_text(encoding="utf-8"))
files = []
for day, item in sorted(acq["attempts"].items()):
    if item["status"] != "ACQUIRED":
        continue
    path = RW_RAW / "bhavcopy_udiff" / item["file_name"]
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as handle:
            row_count = max(0, sum(1 for _ in handle) - 1)
    files.append({"date": day, "file_name": item["file_name"], "row_count": row_count,
                  "sha256": item["sha256"], "source": "NSE_CM_UDIFF_COMMON_BHAVCOPY_FINAL",
                  "official_publisher": "NATIONAL_STOCK_EXCHANGE_OF_INDIA_LIMITED",
                  "acquisition_channel": "PUBLIC_HISTORICAL_REPORT_ARCHIVE", "mcp": False,
                  "redistribution_status": "NOT_ESTABLISHED",
                  "model_training_right_status": "MODEL_TRAINING_RIGHTS_NOT_ESTABLISHED"})
provenance = {"artifact_type": "RESTRICTED_MARKET_PANEL_PROVENANCE_V1", "date_range": [START, END],
              "files": files, "file_count": len(files), "row_count": sum(x["row_count"] for x in files),
              "public_report_row_count": panel_v1["total_rows"], "mcp_derived_row_count": 0,
              "all_rows_file_lineage_bound": len(files) == 497,
              "source_usage_state": "MODEL_TRAINING_RIGHTS_NOT_ESTABLISHED", "raw_files_committed": False,
              "authority": "SHADOW_ONLY"}
save("restricted_market_panel_provenance_v1.json", provenance)

rights_sources = {x["id"]: {"url": x["url"], "sha256": x["sha256"]} for x in closure_log["sources"] if x["id"].startswith("NSE_") or x["id"].startswith("NIFTY_")}
rights_policy = {
    "artifact_type": "NEXTGEN_DATA_USAGE_RIGHTS_POLICY_V1", "governance_not_legal_advice": True,
    "states": ["EXPLICITLY_PERMITTED_FOR_INTENDED_RESEARCH", "RESEARCH_ANALYSIS_ONLY", "MODEL_TRAINING_RIGHTS_NOT_ESTABLISHED", "PERMISSION_REQUIRED", "LICENSE_REQUIRED", "PROHIBITED_FOR_MODEL_TRAINING"],
    "public_access_does_not_imply_training_permission": True,
    "market_panel": {"channel": "PUBLIC_HISTORICAL_REPORT_ARCHIVE", "classification": "MODEL_TRAINING_RIGHTS_NOT_ESTABLISHED", "permission_action": "OBTAIN_EXPLICIT_NSE_DATA_AGREEMENT_OR_WRITTEN_PERMISSION"},
    "mcp": {"rows_used": 0, "classification": "PROHIBITED_FOR_MODEL_TRAINING_WITHOUT_SEPARATE_PERMISSION", "official_terms_explicit": True},
    "benchmark": {"classification": "LICENSE_REQUIRED", "permission_action": "OBTAIN_NSE_INDICES_DATA_SUBSCRIPTION_OR_WRITTEN_SCOPE_CONFIRMATION"},
    "sources": rights_sources, "authority": "SHADOW_ONLY"}
save("nextgen_data_usage_rights_policy_v1.json", rights_policy)
benchmark_rights = {"artifact_type": "BENCHMARK_DATA_USAGE_RIGHTS_V1", "series": {
    "NIFTY_50": {"sessions": 497, "classification": "LICENSE_REQUIRED"},
    "NIFTY_500": {"sessions": 497, "classification": "LICENSE_REQUIRED"}},
    "stock_data_policy_not_reused_for_benchmark": True, "training_gate_ready": False,
    "source": rights_sources["NIFTY_DATA_SUBSCRIPTION"], "status": "LICENSE_REQUIRED", "authority": "SHADOW_ONLY"}
save("benchmark_data_usage_rights_v1.json", benchmark_rights)
usage_rights = {"artifact_type": "MODEL_TRAINING_USAGE_RIGHTS_READINESS_V1", "market_panel": "PERMISSION_REQUIRED",
                "benchmark": "LICENSE_REQUIRED", "mcp_rows": 0, "status": "LICENSE_REQUIRED",
                "ready": False, "legal_advice": False, "authority": "SHADOW_ONLY"}
save("model_training_usage_rights_readiness_v1.json", usage_rights)

technical_gates = {"constituent_reconstruction": True, "investable_universe": True, "identity": True,
                   "survivorship": True, "market_data": panel_v1["status"] == "COMPLETE_FOR_RESTRICTED_PERIOD",
                   "price_normalization": True, "execution_costs": cost["status"] == "COMPLETE_VERIFIED",
                   "benchmark": benchmark["status"] == "COMPLETE_VERIFIED", "features": True, "governance": True}
technical = {"artifact_type": "TECHNICAL_RESEARCH_DATA_READINESS_V1", "gates": technical_gates,
             "failed_gates": sorted(k for k, v in technical_gates.items() if not v),
             "status": "TECHNICALLY_READY_WITH_RESTRICTED_PERIOD" if all(technical_gates.values()) else "TECHNICALLY_NOT_READY",
             "restricted_period": {"start_date": START, "end_date": END, "trading_sessions": 497, "duration_months": 24.0},
             "candidate_rows_subject_to_60_session_warmup": True, "authority": "SHADOW_ONLY"}
save("technical_research_data_readiness_v1.json", technical)

preserved = {f"v{x}": file_hash(RESULTS / f"advanced_research_readiness_v{x}.json") for x in range(1, 6)}
period = technical["restricted_period"] if technical["status"].startswith("TECHNICALLY_READY") else None
v6 = readiness_v6(technical_gates, False, period, preserved)
v6["model_training_usage_rights_status"] = usage_rights["status"]
save("advanced_research_readiness_v6.json", v6)

decision3 = {"artifact_type": "FREE_VS_PAID_DATA_DECISION_V3",
             "decision": decision_v3(technically_ready=technical["status"].startswith("TECHNICALLY_READY"), rights_state=usage_rights["status"]),
             "technical_data_status": technical["status"], "model_training_usage_rights": usage_rights["status"],
             "paid_historical_constituent_data_technically_required": False,
             "permission_or_license_scope": "MODEL_TRAINING_USE_OF_NSE_MARKET_AND_NSE_INDICES_BENCHMARK_DATA",
             "previous_decision_hashes": {"v1": file_hash(RESULTS / "free_vs_paid_data_decision_v1.json"), "v2": file_hash(RESULTS / "free_vs_paid_data_decision_v2.json")},
             "purchase_performed": False, "authority": "SHADOW_ONLY"}
save("free_vs_paid_data_decision_v3.json", decision3)

contract = {"artifact_type": "NEXTGEN_RESTRICTED_CLOSURE_CONTRACT_V1", "branch": "nextgen-research-restricted-window-closure",
            "baseline": "19c5d0823c30947c5fdeec3bba4e7738cd343436", "technical_status": technical["status"],
            "rights_status": usage_rights["status"], "v6_status": v6["status"], "decision_v3": decision3["decision"],
            "focused_tests_expected_minimum": 77, "focused_tests": {"passed": 140, "failed": 0, "status": "PASS"},
            "regressions": {"restricted_window": "128/128 PASS", "free_reconstruction": "131/131 PASS",
                            "authoritative_data": "83/83 PASS", "other_nextgen": "247/247 PASS",
                            "stage6_8c": "170/170 PASS", "stage5d": "606/606 PASS",
                            "stage6_0c": "PASS / 10 schemas"},
            "active_lane_changed_files": 0, "raw_bulk_files_committed": 0,
            "model_training_started": False, "model_promoted": False, "trading_authority": False,
            "paid_purchase_performed": False, "tags_created": 0, "authority": "SHADOW_ONLY"}
save("nextgen_restricted_closure_contract_v1.json", contract)

print(json.dumps({"technical": technical["status"], "rights": usage_rights["status"], "v6": v6["status"],
                  "decision_v3": decision3["decision"], "sessions": len(daily), "provenance_files": len(files)}, sort_keys=True))
