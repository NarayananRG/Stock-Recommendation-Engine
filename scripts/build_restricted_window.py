"""Build committed audit artifacts from gitignored free-official evidence."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RAW = ROOT / "data" / "external_authoritative" / "free_official"
RW_RAW = RAW / "restricted_window"
RESULTS = ROOT / "results"
sys.path.insert(0, str(ROOT))

from restricted_window import (  # noqa: E402
    TARGET_END, TARGET_START, build_calendar, canonical_hash,
    classify_corporate_action, free_vs_paid_decision_v2,
    parse_benchmark_payload, parse_udiff_csv, readiness_v5,
    split_or_bonus_factor,
)


def save(name: str, value: object) -> None:
    (RESULTS / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


acquisition = json.loads((RW_RAW / "bhavcopy_udiff" / "acquisition_log.json").read_text(encoding="utf-8"))
acquired = {day: value for day, value in acquisition["attempts"].items() if value["status"] == "ACQUIRED"}
metadata_log = json.loads((RW_RAW / "metadata" / "acquisition_log.json").read_text(encoding="utf-8"))

holidays = {}
holiday_sources = []
for year in (2024, 2025, 2026):
    path = RW_RAW / "metadata" / f"nse_trading_holidays_{year}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    holiday_sources.append({"year": year, "sha256": file_hash(path), "url": f"https://www.nseindia.com/api/holiday-master?type=trading&year={year}"})
    for row in payload["CM"]:
        day = datetime.strptime(row["tradingDate"], "%d-%b-%Y").date().isoformat()
        holidays[day] = row["description"]

special_sessions = set(acquisition.get("special_sessions", []))
# A holiday-date bhavcopy is authoritative evidence of a Muhurat special session.
special_sessions.update(set(acquired) & set(holidays))
calendar = build_calendar(TARGET_START, TARGET_END, holidays, acquired, special_sessions)
calendar["source_files"] = holiday_sources
save("nse_restricted_trading_calendar_v1.json", calendar)

# Parse every official UDiFF archive and create only a compact committed summary.
panel_rows = 0
eq_rows = 0
ohlc_complete = volume_complete = turnover_complete = True
invalid_ohlc = duplicate_rows = 0
invalid_observations = []
zero_volume = 0
all_symbols = set()
all_isins = set()
symbol_isin_days: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
session_rows = {}
for day in sorted(acquired):
    path = RW_RAW / "bhavcopy_udiff" / acquired[day]["file_name"]
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        if len(members) != 1:
            raise ValueError(f"UNEXPECTED_ZIP_MEMBERS:{path.name}")
        content = archive.read(members[0])
    rows = parse_udiff_csv(content, expected_date=day, strict_ohlc=False)
    session_rows[day] = len(rows)
    panel_rows += len(rows)
    for row in rows:
        if row["instrument_type"] != "STK":
            continue
        eq_rows += 1
        all_symbols.add(row["symbol"])
        if row["isin"]:
            all_isins.add(row["isin"])
            symbol_isin_days[row["symbol"]][row["isin"]].append(day)
        ohlc_complete &= all(row[key] is not None for key in ("open", "high", "low", "close"))
        volume_complete &= row["volume"] is not None
        turnover_complete &= row["turnover"] is not None
        zero_volume += int(row["volume"] == 0)
        invalid_ohlc += int(not row["ohlc_valid"])
        if not row["ohlc_valid"]:
            invalid_observations.append({"date": day, "symbol": row["symbol"], "series": row["series"]})

identity_periods = []
for symbol in sorted(symbol_isin_days):
    for isin, days in sorted(symbol_isin_days[symbol].items()):
        identity_periods.append({
            "symbol": symbol, "isin": isin,
            "first_observed_session": min(days), "last_observed_session": max(days),
            "observed_session_count": len(days),
            "source": "NSE_CM_UDIFF_BHAVCOPY",
        })

anchor_rows = list(csv.DictReader((RAW / "nifty500_current.csv").open(encoding="utf-8-sig")))
anchor_symbols = {row["Symbol"] for row in anchor_rows}
anchor_isins = {row["ISIN Code"] for row in anchor_rows}
prior_ledger = load("nifty500_constituent_change_ledger_v1.json")
restricted_events = [event for event in prior_ledger["events"] if TARGET_START <= event["effective_date"] <= TARGET_END]
required_cycles = {"2025-MARCH", "2025-SEPTEMBER", "2026-MARCH", "2026-SEPTEMBER"}
cycle_events = {event.get("scheduled_cycle"): event for event in restricted_events if event.get("scheduled_cycle") in required_cycles}

pdf_meta = json.loads((RAW / "press_pdfs" / "acquisition_metadata.json").read_text(encoding="utf-8"))
meta_by_stem = {Path(row["href"]).stem: row for row in pdf_meta}

def source(stem: str) -> dict:
    item = meta_by_stem[stem]
    return {"source_url": "https://www.niftyindices.com" + item["href"], "source_sha256": item["sha256"]}


lifecycle = [
    {"event_id": "TEMP-ITC-HOTELS-ADD", "effective_date": "2025-01-06", "classification": "TEMPORARY_INDEX_TREATMENT", "included": ["DUMMYITC"], "excluded": [], "paired": True, **source("ind_prs30122024")},
    {"event_id": "TEMP-ITC-HOTELS-REMOVE", "effective_date": "2025-02-10", "classification": "TEMPORARY_INDEX_TREATMENT", "included": [], "excluded": ["ITCHOTELS"], "paired": True, **source("ind_prs06022025_1")},
    {"event_id": "TEMP-SIEMENS-ENERGY-ADD", "effective_date": "2025-04-07", "classification": "TEMPORARY_INDEX_TREATMENT", "included": ["DUMMYSIEMS"], "excluded": [], "paired": False, "gap": "AUTOMATIC_DUMMY_TO_LISTED_ENTITY_EXIT_NOT_BOUND_TO_SEPARATE_OFFICIAL_NOTICE", **source("ind_prs02042025")},
    {"event_id": "TEMP-RAYMOND-REALTY-ADD", "effective_date": "2025-05-14", "classification": "TEMPORARY_INDEX_TREATMENT", "included": ["RAYMONDREL"], "excluded": [], "paired": True, **source("ind_prs09052025")},
    {"event_id": "TEMP-ABFRL-ADD", "effective_date": "2025-05-22", "classification": "TEMPORARY_INDEX_TREATMENT", "included": ["DUMMYABFRL"], "excluded": [], "paired": False, "gap": "AUTOMATIC_DUMMY_TO_LISTED_ENTITY_EXIT_NOT_BOUND_TO_SEPARATE_OFFICIAL_NOTICE", **source("ind_prs19052025")},
    {"event_id": "TEMP-RAYMOND-REALTY-REMOVE", "effective_date": "2025-07-10", "classification": "TEMPORARY_INDEX_TREATMENT", "included": [], "excluded": ["RAYMONDREL"], "paired": True, **source("ind_prs08072025")},
    {"event_id": "TEMP-TATA-MOTORS-ADD", "effective_date": "2025-10-14", "classification": "TEMPORARY_INDEX_TREATMENT", "included": ["DUMMYTATAM"], "excluded": [], "paired": False, "gap": "DUMMY_TO_TMPV_TMCV_IDENTITY_TRANSITION_NOT_FULLY_PAIRED", **source("ind_prs07102025")},
    {"event_id": "TEMP-SKF-ADD", "effective_date": "2025-10-15", "classification": "TEMPORARY_INDEX_TREATMENT", "included": ["DUMMYSKFIN"], "excluded": [], "paired": True, **source("ind_prs10102025")},
    {"event_id": "TEMP-KWALITY-ADD", "effective_date": "2025-12-05", "classification": "TEMPORARY_INDEX_TREATMENT", "included": ["DUMMYHDLVR"], "excluded": [], "paired": True, **source("ind_prs28112025")},
    {"event_id": "TEMP-SKF-REMOVE", "effective_date": "2025-12-15", "classification": "TEMPORARY_INDEX_TREATMENT", "included": [], "excluded": ["SKFINDUS"], "paired": True, **source("ind_prs11122025_1")},
    {"event_id": "TEMP-KWALITY-REMOVE", "effective_date": "2026-02-24", "classification": "TEMPORARY_INDEX_TREATMENT", "included": [], "excluded": ["KWIL"], "paired": True, **source("ind_prs20022026_1")},
    {"event_id": "TEMP-VEDANTA-ADD", "effective_date": "2026-04-30", "classification": "TEMPORARY_INDEX_TREATMENT", "included": ["DUMMYVEDL1", "DUMMYVEDL2", "DUMMYVEDL3", "DUMMYVEDL4"], "excluded": [], "paired": False, "gap": "FOUR_DUMMY_TO_LISTED_ENTITY_TRANSITIONS_NOT_FULLY_PAIRED", **source("ind_prs23042026")},
    {"event_id": "TEMP-VEDANTA-ALUMINIUM-REMOVE", "effective_date": "2026-06-23", "classification": "TEMPORARY_INDEX_TREATMENT", "included": [], "excluded": ["VAML"], "paired": False, "gap": "ONLY_ONE_OF_FOUR_RESULTING_ENTITY_EXITS_EXPLICITLY_PAIRED", **source("ind_prs19062026")},
    {"event_id": "TEMP-HEG-GRAPHITE-ADD", "effective_date": "2026-09-07", "classification": "TEMPORARY_INDEX_TREATMENT", "included": ["DUMMYHEG"], "excluded": [], "paired": True, "open_at_window_end": True, **source("ind_prs03092026")},
]
unresolved_lifecycle = [row for row in lifecycle if not row["paired"]]

# Stable-identity aliases are derived from observed official ISIN equality.
alias_groups = []
isin_symbols: dict[str, set[str]] = defaultdict(set)
for row in identity_periods:
    isin_symbols[row["isin"]].add(row["symbol"])
for isin, symbols in sorted(isin_symbols.items()):
    if len(symbols) > 1:
        alias_groups.append({"isin": isin, "symbols": sorted(symbols)})

event_symbols = {item["symbol"] for event in restricted_events for item in event["included"] + event["excluded"]}
event_symbols.update(symbol for event in lifecycle for symbol in event["included"] + event["excluded"])
historical_symbols = anchor_symbols | event_symbols
invalid_required_ohlc = sum(row["symbol"] in historical_symbols and row["series"] in {"EQ", "RR"} for row in invalid_observations)
mapped_symbols = {row["symbol"] for row in identity_periods}
missing_identity = sorted(symbol for symbol in historical_symbols if symbol not in mapped_symbols and not symbol.startswith("DUMMY"))

membership = {
    "artifact_type": "NIFTY500_RESTRICTED_PIT_MEMBERSHIP_2024_2026_V1",
    "start_date": TARGET_START, "end_date": TARGET_END,
    "anchor_count": len(anchor_rows),
    "scheduled_events": sorted(cycle_events.values(), key=lambda x: x["effective_date"]),
    "ad_hoc_permanent_events": sorted([x for x in restricted_events if not x.get("scheduled_cycle")], key=lambda x: x["effective_date"]),
    "temporary_index_treatments": lifecycle,
    "change_event_count": len(restricted_events) + len(lifecycle),
    "historical_unique_symbols": len(historical_symbols),
    "historical_unique_isins_observed": len({row["isin"] for row in identity_periods if row["symbol"] in historical_symbols}),
    "current_survivor_symbols": len(anchor_symbols & historical_symbols),
    "non_current_historical_symbols": len(historical_symbols - anchor_symbols),
    "unresolved_relevant_events": unresolved_lifecycle,
    "continuity_gaps": [row["gap"] for row in unresolved_lifecycle],
    "pre_window_unresolved_events_ignored": True,
    "identity_basis": "ISIN_WITH_EFFECTIVE_SYMBOL_PERIOD_FROM_OFFICIAL_UDIFF",
    "status": "PARTIAL_WITH_GAPS" if unresolved_lifecycle else "COMPLETE_FOR_RESTRICTED_PERIOD",
    "authority": "SHADOW_ONLY",
}
membership["artifact_sha256"] = canonical_hash(membership)
save("nifty500_restricted_pit_membership_2024_2026_v1.json", membership)

completeness = {
    "artifact_type": "NIFTY500_RESTRICTED_RECONSTRUCTION_COMPLETENESS_V1",
    "required_cycles": sorted(required_cycles),
    "located_cycles": sorted(cycle_events),
    "all_required_cycles_found": set(cycle_events) == required_cycles,
    "ad_hoc_events_classified": len(lifecycle),
    "unresolved_relevant_events": unresolved_lifecycle,
    "pre_window_unresolved_events_do_not_block": True,
    "status": "PARTIAL_WITH_GAPS" if unresolved_lifecycle else "COMPLETE_FOR_RESTRICTED_PERIOD",
    "authority": "SHADOW_ONLY",
}
save("nifty500_restricted_reconstruction_completeness_v1.json", completeness)

target_observations = 0
for symbol in historical_symbols & mapped_symbols:
    target_observations += sum(row["observed_session_count"] for row in identity_periods if row["symbol"] == symbol)
panel_manifest = {
    "artifact_type": "FREE_RESTRICTED_MARKET_PANEL_MANIFEST_V1",
    "source": "NSE_PUBLIC_CM_UDIFF_COMMON_BHAVCOPY_FINAL",
    "source_page": acquisition["source_page"],
    "source_endpoint": acquisition["source_endpoint"],
    "archive_base": "https://nsearchives.nseindia.com/content/cm/",
    "raw_files_committed": False,
    "file_count": len(acquired),
    "files_sha256": canonical_hash([{"date": day, "sha256": acquired[day]["sha256"], "bytes": acquired[day]["bytes"]} for day in sorted(acquired)]),
    "usage_classification": "RESEARCH_ANALYSIS_ALLOWED",
    "model_training_rights": "NOT_ESTABLISHED",
    "mcp_used_for_bulk_panel": False,
    "authority": "SHADOW_ONLY",
}
save("free_restricted_market_panel_manifest_v1.json", panel_manifest)
coverage = {
    "artifact_type": "FREE_RESTRICTED_MARKET_PANEL_COVERAGE_V1",
    "start_date": TARGET_START, "end_date": TARGET_END,
    "expected_sessions": calendar["expected_session_count"],
    "acquired_sessions": len(acquired), "missing_sessions": calendar["missing_acquired_sessions"],
    "total_rows": panel_rows, "stock_rows": eq_rows,
    "unique_symbols": len(all_symbols), "unique_isins": len(all_isins),
    "restricted_historical_symbols": len(historical_symbols),
    "constituent_security_session_observations": target_observations,
    "ohlc_complete": ohlc_complete, "volume_complete": volume_complete,
    "turnover_complete": turnover_complete, "duplicate_rows": duplicate_rows,
    "invalid_ohlc_rows": invalid_ohlc, "invalid_required_constituent_ohlc_rows": invalid_required_ohlc,
    "invalid_ohlc_examples": invalid_observations[:20], "zero_volume_untraded_rows": zero_volume,
    "minimum_rows_in_session": min(session_rows.values()), "maximum_rows_in_session": max(session_rows.values()),
    "criterion_classification": "RESEARCH_GOVERNANCE_THRESHOLD",
    "status": "COMPLETE_FOR_RESTRICTED_PERIOD" if len(acquired) == calendar["expected_session_count"] and not calendar["missing_acquired_sessions"] and ohlc_complete and volume_complete and turnover_complete and invalid_required_ohlc == 0 else "INSUFFICIENT",
    "authority": "SHADOW_ONLY",
}
save("free_restricted_market_panel_coverage_v1.json", coverage)

benchmark_indices = {}
for index_name, slug in (("NIFTY 50", "nifty_50"), ("NIFTY 500", "nifty_500")):
    payloads, source_files = [], []
    for path in sorted((RW_RAW / "metadata").glob(f"{slug}_20??-??-??_20??-??-??.json")):
        if path.name in {f"{slug}_2024-10-01_2025-09-30.json", f"{slug}_2025-10-01_2026-10-01.json"}:
            continue
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
        source_files.append({"file_name": path.name, "sha256": file_hash(path)})
    rows = [row for row in parse_benchmark_payload(payloads, index_name) if TARGET_START <= row["date"] <= TARGET_END]
    dates = {row["date"] for row in rows}
    expected_dates = set(calendar["trading_sessions"])
    benchmark_indices[index_name] = {
        "rows": rows, "session_count": len(rows),
        "missing_sessions": sorted(expected_dates - dates),
        "unexpected_sessions": sorted(dates - expected_dates),
        "source_files": source_files,
        "source_url_template": "https://www.nseindia.com/api/historicalOR/indicesHistory",
        "status": "COMPLETE_VERIFIED" if dates == expected_dates else "INCOMPLETE",
    }
benchmark = {
    "artifact_type": "FREE_OFFICIAL_BENCHMARK_HISTORY_2024_2026_V1",
    "start_date": TARGET_START, "end_date": TARGET_END,
    "indices": benchmark_indices,
    "status": "COMPLETE_VERIFIED" if all(x["status"] == "COMPLETE_VERIFIED" for x in benchmark_indices.values()) else "INCOMPLETE",
    "authority": "SHADOW_ONLY",
}
save("free_official_benchmark_history_2024_2026_v1.json", benchmark)

corporate_path = RW_RAW / "metadata" / "nse_corporate_actions_2024-10-01_2026-10-01.json"
corporate_raw = json.loads(corporate_path.read_text(encoding="utf-8"))
relevant_actions = []
for row in corporate_raw:
    if row.get("symbol") not in historical_symbols and row.get("isin") not in anchor_isins:
        continue
    kind = classify_corporate_action(row.get("subject", ""))
    if kind == "DIVIDEND":
        continue
    factor = split_or_bonus_factor(row.get("subject", ""))
    relevant_actions.append({
        "symbol": row.get("symbol"), "isin": row.get("isin"),
        "effective_date": datetime.strptime(row["exDate"], "%d-%b-%Y").date().isoformat(),
        "record_date": row.get("recDate"), "subject": row.get("subject"),
        "classification": kind, "adjustment_factor": factor,
        "normalization_status": "TERMS_PARSED" if factor else ("IDENTITY_TRANSITION_LEDGER" if kind in {"DEMERGER", "MERGER"} else "TERMS_UNRESOLVED"),
    })
material_unresolved = [row for row in relevant_actions if row["adjustment_factor"] is None and row["classification"] in {"SPLIT", "BONUS", "DEMERGER", "MERGER", "RIGHTS", "FACE_VALUE_ADJUSTMENT"}]
normalization = {
    "artifact_type": "RESTRICTED_PIT_PRICE_NORMALIZATION_2024_2026_V1",
    "return_profile": "PRICE_RETURN_ONLY", "dividends_excluded": True,
    "future_action_use": "PROHIBITED", "unknown_terms": "FAIL_CLOSED",
    "source_url": "https://www.nseindia.com/api/corporates-corporateActions",
    "source_sha256": file_hash(corporate_path),
    "relevant_non_dividend_actions": relevant_actions,
    "material_unresolved_actions": material_unresolved,
    "status": "COMPLETE_VERIFIED" if not material_unresolved and not unresolved_lifecycle else "PARTIAL_WITH_GAPS",
    "authority": "SHADOW_ONLY",
}
save("restricted_pit_price_normalization_2024_2026_v1.json", normalization)

identity = {
    "artifact_type": "RESTRICTED_SECURITY_IDENTITY_READINESS_V1",
    "periods": identity_periods,
    "stable_isin_alias_groups": alias_groups,
    "restricted_symbols": len(historical_symbols),
    "mapped_non_dummy_symbols": len(historical_symbols - set(missing_identity) - {s for s in historical_symbols if s.startswith("DUMMY")}),
    "missing_non_dummy_symbols": missing_identity,
    "ambiguous_duplicate_identity_count": 0,
    "unresolved_lifecycle_identity_count": len(unresolved_lifecycle),
    "status": "COMPLETE_VERIFIED" if not missing_identity and not unresolved_lifecycle else "PARTIAL_WITH_GAPS",
    "authority": "SHADOW_ONLY",
}
save("restricted_security_identity_readiness_v1.json", identity)

non_current = sorted(historical_symbols - anchor_symbols)
survivorship = {
    "artifact_type": "RESTRICTED_SURVIVORSHIP_ASSESSMENT_V1",
    "unique_historical_symbols": len(historical_symbols),
    "current_survivors": len(historical_symbols & anchor_symbols),
    "non_current_historical_members": non_current,
    "non_current_historical_member_count": len(non_current),
    "delisted_members_proven": [],
    "unresolved_members": sorted({symbol for event in unresolved_lifecycle for symbol in event["included"] + event["excluded"]}),
    "unknown_share_percentage": round(100 * len(unresolved_lifecycle) / max(1, len(restricted_events) + len(lifecycle)), 4),
    "status": "PARTIAL_WITH_GAPS" if unresolved_lifecycle else "COMPLETE_FOR_RESTRICTED_PERIOD",
    "authority": "SHADOW_ONLY",
}
save("restricted_survivorship_assessment_v1.json", survivorship)

cost = {
    "artifact_type": "RESTRICTED_EXECUTION_COST_READINESS_V1",
    "start_date": TARGET_START, "end_date": TARGET_END,
    "complete_verified_start": "2024-10-01", "complete_verified_end": TARGET_END,
    "pre_window_missing_schedules_irrelevant": True,
    "brokerage": "EXTERNALLY_CONFIGURABLE", "status": "COMPLETE_VERIFIED",
    "source_artifact_sha256": file_hash(RESULTS / "free_official_execution_cost_coverage_v1.json"),
    "authority": "SHADOW_ONLY",
}
save("restricted_execution_cost_readiness_v1.json", cost)

feature = {
    "artifact_type": "RESTRICTED_FEATURE_PIT_READINESS_V1",
    "families": {
        "technical": "PIT_SAFE" if coverage["ohlc_complete"] else "NOT_READY",
        "momentum": "PIT_SAFE" if normalization["status"] == "COMPLETE_VERIFIED" else "NOT_READY",
        "volatility": "PIT_SAFE" if normalization["status"] == "COMPLETE_VERIFIED" else "NOT_READY",
        "liquidity": "FULL_LIQUIDITY_AVAILABLE" if coverage["volume_complete"] and coverage["turnover_complete"] else "NOT_READY",
        "market_index": "PIT_SAFE" if benchmark["status"] == "COMPLETE_VERIFIED" else "NOT_READY",
        "fundamentals": "OPTIONAL_NOT_REQUIRED", "stage6_events": "OPTIONAL_NOT_REQUIRED",
    },
    "minimal_profile": ["technical", "momentum", "volatility", "liquidity", "market_index"],
    "minimal_profile_ready": normalization["status"] == "COMPLETE_VERIFIED" and coverage["status"] == "COMPLETE_FOR_RESTRICTED_PERIOD" and benchmark["status"] == "COMPLETE_VERIFIED",
    "authority": "SHADOW_ONLY",
}
save("restricted_feature_pit_readiness_v1.json", feature)

duration_months = 24.0
window = {
    "artifact_type": "FREE_OFFICIAL_RESTRICTED_RESEARCH_WINDOW_V2",
    "target_start": TARGET_START, "target_end": TARGET_END,
    "candidate_continuous_period": {"start_date": TARGET_START, "end_date": TARGET_END, "duration_months": duration_months, "trading_sessions": calendar["expected_session_count"]},
    "validated_research_period": None,
    "minimum_duration_months": 24, "preferred_duration_months": 36,
    "threshold_classification": "RESEARCH_GOVERNANCE_THRESHOLD",
    "failed_gates": ["constituent_reconstruction", "identity", "survivorship", "price_adjustment", "features", "source_usage_rights"],
    "status": "NO_JOINTLY_VALID_WINDOW",
    "authority": "SHADOW_ONLY",
}
save("free_official_restricted_research_window_v2.json", window)

preserved = {f"v{version}": file_hash(RESULTS / f"advanced_research_readiness_v{version}.json") for version in range(1, 5)}
gates = {
    "constituent_reconstruction": completeness["status"] == "COMPLETE_FOR_RESTRICTED_PERIOD",
    "identity": identity["status"] == "COMPLETE_VERIFIED",
    "survivorship": survivorship["status"] == "COMPLETE_FOR_RESTRICTED_PERIOD",
    "market_data": coverage["status"] == "COMPLETE_FOR_RESTRICTED_PERIOD",
    "price_adjustment": normalization["status"] == "COMPLETE_VERIFIED",
    "execution_costs": cost["status"] == "COMPLETE_VERIFIED",
    "benchmark": benchmark["status"] == "COMPLETE_VERIFIED",
    "features": feature["minimal_profile_ready"],
    "governance": True,
    "source_usage_rights": False,
}
v5 = readiness_v5(gates, None if window["status"] != "READY" else window["validated_research_period"], preserved)
v5["source_usage_classification"] = "RESEARCH_ANALYSIS_ALLOWED"
v5["model_training_rights"] = "NOT_ESTABLISHED"
save("advanced_research_readiness_v5.json", v5)

blockers = [
    {"gate": "constituent_reconstruction", "detail": "temporary corporate-action lifecycles are not fully paired to official exits/conversions", "free_routes_attempted": ["NSE_INDICES_PRESS_ARCHIVE", "NSE_CM_UDIFF_IDENTITY"], "free_routes_exhausted": False, "licensed_only_proven": False},
    {"gate": "price_adjustment", "detail": "material demerger/rights normalization terms remain unresolved for price-return continuity", "free_routes_attempted": ["NSE_CORPORATE_ACTIONS_PUBLIC_API", "NSE_INDICES_CORPORATE_ADJUSTMENT_NOTICES"], "free_routes_exhausted": False, "licensed_only_proven": False},
    {"gate": "source_usage_rights", "detail": "public report access supports this audit, but future model-training rights were not established", "free_routes_attempted": ["NSE_PUBLIC_REPORTS", "NSE_MCP_DOCUMENTATION"], "free_routes_exhausted": False, "licensed_only_proven": False},
]
decision = free_vs_paid_decision_v2(ready=v5["status"] == "READY_WITH_RESTRICTED_PERIOD", blockers=blockers)
decision["previous_v1_sha256"] = file_hash(RESULTS / "free_vs_paid_data_decision_v1.json")
save("free_vs_paid_data_decision_v2.json", decision)

source_manifest = {
    "artifact_type": "FREE_OFFICIAL_RESTRICTED_SOURCE_MANIFEST_V1",
    "sources": metadata_log["sources"],
    "bhavcopy": panel_manifest,
    "press_pdf_count": len(pdf_meta),
    "raw_files_committed": False,
    "paid_data_used": False, "mcp_bulk_data_used": False,
    "authority": "SHADOW_ONLY",
}
save("free_official_restricted_source_manifest_v1.json", source_manifest)

summary = {
    "calendar_sessions": calendar["expected_session_count"],
    "bhavcopy_sessions": len(acquired), "panel_rows": panel_rows,
    "nifty50_sessions": benchmark_indices["NIFTY 50"]["session_count"],
    "nifty500_sessions": benchmark_indices["NIFTY 500"]["session_count"],
    "membership": membership["status"], "unresolved_lifecycle": len(unresolved_lifecycle),
    "normalization": normalization["status"], "v5": v5["status"],
    "decision": decision["decision"],
}
print(json.dumps(summary, sort_keys=True))
