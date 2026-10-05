from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
RESULTS_DIR = ROOT / "results"
sys.path.insert(0, str(ROOT))

from restricted_window import (  # noqa: E402
    DECISION_STATES, apply_pit_adjustment, build_calendar,
    classify_corporate_action, free_vs_paid_decision_v2,
    parse_benchmark_payload, parse_effective_date, parse_udiff_csv,
    readiness_v5, split_or_bonus_factor, tracked_runtime_artifacts,
)

RESULTS = []


def require(value, message="assertion failed"):
    if not value:
        raise AssertionError(message)


def raises(error, fn, contains=None):
    try:
        fn()
    except error as exc:
        if contains:
            require(contains in str(exc), str(exc))
        return
    raise AssertionError(f"expected {error.__name__}")


def case(category, name, fn):
    try:
        fn(); status, detail = "PASS", ""
    except Exception as exc:
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    RESULTS.append({"category": category, "test": name, "status": status, "detail": detail})


def load(name):
    return json.loads((RESULTS_DIR / name).read_text(encoding="utf-8"))


def sha(name):
    return hashlib.sha256((RESULTS_DIR / name).read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "--git-dir=_git", "--work-tree=.", *args], cwd=REPO, text=True).strip()


CAL = load("nse_restricted_trading_calendar_v1.json")
PANEL = load("free_restricted_market_panel_coverage_v1.json")
PANEL_MANIFEST = load("free_restricted_market_panel_manifest_v1.json")
BENCH = load("free_official_benchmark_history_2024_2026_v1.json")
MEMBERSHIP = load("nifty500_restricted_pit_membership_2024_2026_v1.json")
COMPLETE = load("nifty500_restricted_reconstruction_completeness_v1.json")
IDENTITY = load("restricted_security_identity_readiness_v1.json")
SURV = load("restricted_survivorship_assessment_v1.json")
NORM = load("restricted_pit_price_normalization_2024_2026_v1.json")
COST = load("restricted_execution_cost_readiness_v1.json")
FEATURE = load("restricted_feature_pit_readiness_v1.json")
WINDOW = load("free_official_restricted_research_window_v2.json")
V5 = load("advanced_research_readiness_v5.json")
DECISION = load("free_vs_paid_data_decision_v2.json")
SOURCE = load("free_official_restricted_source_manifest_v1.json")

# Decision V2 semantics
case("DECISION", "all decision states supported", lambda: require(len(DECISION_STATES) == 5))
case("DECISION", "multiple free blockers do not imply paid", lambda: require(free_vs_paid_decision_v2(ready=False, blockers=[{"free_routes_exhausted": False}, {"free_routes_exhausted": False}])["decision"] == "FREE_OFFICIAL_RECONSTRUCTION_INCOMPLETE"))
case("DECISION", "one unattempted free route incomplete", lambda: require(free_vs_paid_decision_v2(ready=False, blockers=[{"free_routes_exhausted": False}])["decision"] == "FREE_OFFICIAL_RECONSTRUCTION_INCOMPLETE"))
case("DECISION", "confirmed licensed only blocker permits paid", lambda: require(free_vs_paid_decision_v2(ready=False, blockers=[{"free_routes_exhausted": True, "licensed_only_proven": True}])["decision"] == "LICENSED_DATA_REQUIRED_FOR_RESEARCH_READINESS"))
case("DECISION", "access blocked classified", lambda: require(free_vs_paid_decision_v2(ready=False, blockers=[{"free_routes_exhausted": True, "source_access_blocked": True}])["decision"] == "FREE_OFFICIAL_SOURCE_ACCESS_BLOCKED"))
case("DECISION", "restricted ready classified", lambda: require(free_vs_paid_decision_v2(ready=True, blockers=[])["decision"] == "FREE_OFFICIAL_DATA_SUFFICIENT_FOR_RESTRICTED_PERIOD"))
case("DECISION", "unrestricted ready classified", lambda: require(free_vs_paid_decision_v2(ready=True, unrestricted=True, blockers=[])["decision"] == "FREE_OFFICIAL_DATA_SUFFICIENT"))
case("DECISION", "blocker count rule explicit", lambda: require(DECISION["blocker_count_not_used_as_paid_rule"] is True))
case("DECISION", "current decision incomplete", lambda: require(DECISION["decision"] == "FREE_OFFICIAL_RECONSTRUCTION_INCOMPLETE"))
case("DECISION", "no purchase performed", lambda: require(DECISION["purchase_performed"] is False))
case("DECISION", "V1 decision preserved", lambda: require(sha("free_vs_paid_data_decision_v1.json") == DECISION["previous_v1_sha256"]))

# Effective dates and membership
for label, text, expected in [
    ("w.e.f dots", "w.e.f. December 30, 2022", "2022-12-30"),
    ("w.e.f no terminal dot", "w.e.f December 30 2022", "2022-12-30"),
    ("effective from", "effective from June 30, 2025", "2025-06-30"),
    ("ordinal", "effective from 7th September 2026", "2026-09-07"),
    ("day first", "w.e.f. 10 February, 2025", "2025-02-10"),
    ("numeric dash", "effective from 30-09-2026", "2026-09-30"),
    ("numeric slash", "effective from 30/03/2026", "2026-03-30"),
]:
    case("DATE", label, lambda t=text, e=expected: require(parse_effective_date(t) == e))
case("DATE", "missing date returns none", lambda: require(parse_effective_date("no effective date") is None))
case("MEMBERSHIP", "October 2024 boundary", lambda: require(MEMBERSHIP["start_date"] == "2024-10-01"))
case("MEMBERSHIP", "October 2026 boundary", lambda: require(MEMBERSHIP["end_date"] == "2026-10-01"))
case("MEMBERSHIP", "four required cycles found", lambda: require(COMPLETE["all_required_cycles_found"]))
for cycle in ("2025-MARCH", "2025-SEPTEMBER", "2026-MARCH", "2026-SEPTEMBER"):
    case("MEMBERSHIP", f"{cycle} found", lambda c=cycle: require(c in COMPLETE["located_cycles"]))
case("MEMBERSHIP", "ad hoc treatments classified", lambda: require(COMPLETE["ad_hoc_events_classified"] >= 14))
case("MEMBERSHIP", "pre-window gaps ignored", lambda: require(COMPLETE["pre_window_unresolved_events_do_not_block"]))
case("MEMBERSHIP", "in-window gap blocks continuity", lambda: require(COMPLETE["status"] == "PARTIAL_WITH_GAPS"))
case("MEMBERSHIP", "temporary events explicit", lambda: require(all(x["classification"] == "TEMPORARY_INDEX_TREATMENT" for x in MEMBERSHIP["temporary_index_treatments"])))
case("MEMBERSHIP", "ITC lifecycle paired", lambda: require(sum(x["paired"] for x in MEMBERSHIP["temporary_index_treatments"] if "ITC-HOTELS" in x["event_id"]) == 2))
case("MEMBERSHIP", "Raymond lifecycle paired", lambda: require(sum(x["paired"] for x in MEMBERSHIP["temporary_index_treatments"] if "RAYMOND" in x["event_id"]) == 2))
case("MEMBERSHIP", "HEG open treatment retained", lambda: require(any(x.get("open_at_window_end") for x in MEMBERSHIP["temporary_index_treatments"])))
case("MEMBERSHIP", "current anchor count reported", lambda: require(MEMBERSHIP["anchor_count"] == 501))

# UDiFF parsing
HEADER = "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
ROW = "2024-10-01,2024-10-01,CM,NSE,STK,1,INE000A01001,ABC,EQ,,,,,ABC LTD,10,12,9,11,11,10,,11,,,100,1100,5,F1,1,,,,,\n"
parsed = parse_udiff_csv((HEADER + ROW).encode(), expected_date="2024-10-01")
case("MARKET", "UDiFF parser row", lambda: require(len(parsed) == 1))
case("MARKET", "UDiFF ISIN parsed", lambda: require(parsed[0]["isin"] == "INE000A01001"))
case("MARKET", "UDiFF turnover parsed", lambda: require(parsed[0]["turnover"] == 1100))
case("MARKET", "UDiFF trades parsed", lambda: require(parsed[0]["trades"] == 5))
case("MARKET", "UDiFF date mismatch rejected", lambda: raises(ValueError, lambda: parse_udiff_csv((HEADER + ROW).encode(), expected_date="2024-10-02"), "DATE"))
case("MARKET", "UDiFF bad schema rejected", lambda: raises(ValueError, lambda: parse_udiff_csv(b"a,b\n1,2\n"), "SCHEMA"))
case("MARKET", "UDiFF duplicate rejected", lambda: raises(ValueError, lambda: parse_udiff_csv((HEADER + ROW + ROW).encode()), "DUPLICATE"))
bad_high = ROW.replace(",10,12,9,11,", ",10,8,9,11,")
case("MARKET", "invalid OHLC rejected", lambda: raises(ValueError, lambda: parse_udiff_csv((HEADER + bad_high).encode()), "OHLC"))
case("MARKET", "invalid OHLC observable non-strict", lambda: require(parse_udiff_csv((HEADER + bad_high).encode(), strict_ohlc=False)[0]["ohlc_valid"] is False))
case("MARKET", "497 bulk sessions acquired", lambda: require(PANEL["acquired_sessions"] == 497))
case("MARKET", "no missing sessions", lambda: require(PANEL["missing_sessions"] == []))
case("MARKET", "panel complete", lambda: require(PANEL["status"] == "COMPLETE_FOR_RESTRICTED_PERIOD"))
case("MARKET", "OHLC complete", lambda: require(PANEL["ohlc_complete"]))
case("MARKET", "volume complete", lambda: require(PANEL["volume_complete"]))
case("MARKET", "turnover complete", lambda: require(PANEL["turnover_complete"]))
case("MARKET", "no required invalid OHLC", lambda: require(PANEL["invalid_required_constituent_ohlc_rows"] == 0))
case("MARKET", "bulk panel not MCP", lambda: require(PANEL_MANIFEST["mcp_used_for_bulk_panel"] is False))
case("MARKET", "full-session hashes bound", lambda: require(len(PANEL_MANIFEST["files_sha256"]) == 64))
case("MARKET", "raw files not committed claim", lambda: require(PANEL_MANIFEST["raw_files_committed"] is False))

# Calendar and benchmark
cal = build_calendar("2025-01-01", "2025-01-05", {"2025-01-01": "Holiday"}, {"2025-01-02", "2025-01-03"}, [])
case("CALENDAR", "weekends excluded", lambda: require(cal["weekend_exclusion_count"] == 2))
case("CALENDAR", "holidays excluded", lambda: require(len(cal["official_holidays"]) == 1))
case("CALENDAR", "expected count deterministic", lambda: require(cal["expected_session_count"] == 2))
special = build_calendar("2025-02-01", "2025-02-02", {}, {"2025-02-01"}, {"2025-02-01"})
case("CALENDAR", "special Saturday supported", lambda: require(special["trading_sessions"] == ["2025-02-01"]))
case("CALENDAR", "official calendar complete", lambda: require(CAL["status"] == "COMPLETE_VERIFIED"))
case("CALENDAR", "two budget sessions retained", lambda: require({"2025-02-01", "2026-02-01"}.issubset(set(CAL["special_trading_sessions"]))))
case("CALENDAR", "Muhurat session retained", lambda: require("2025-10-21" in CAL["special_trading_sessions"]))
case("CALENDAR", "exact 497 sessions", lambda: require(CAL["expected_session_count"] == 497))
sample_benchmark = {"data": [{"EOD_INDEX_NAME": "NIFTY 50", "EOD_OPEN_INDEX_VAL": 10, "EOD_HIGH_INDEX_VAL": 12, "EOD_LOW_INDEX_VAL": 9, "EOD_CLOSE_INDEX_VAL": 11, "EOD_TIMESTAMP": "01-OCT-2024"}]}
case("BENCHMARK", "NIFTY50 parser", lambda: require(parse_benchmark_payload([sample_benchmark], "NIFTY 50")[0]["date"] == "2024-10-01"))
case("BENCHMARK", "wrong benchmark rejected", lambda: raises(ValueError, lambda: parse_benchmark_payload([sample_benchmark], "NIFTY 500"), "IDENTITY"))
case("BENCHMARK", "NIFTY50 complete", lambda: require(BENCH["indices"]["NIFTY 50"]["status"] == "COMPLETE_VERIFIED"))
case("BENCHMARK", "NIFTY500 complete", lambda: require(BENCH["indices"]["NIFTY 500"]["status"] == "COMPLETE_VERIFIED"))
case("BENCHMARK", "NIFTY50 exact sessions", lambda: require(BENCH["indices"]["NIFTY 50"]["session_count"] == 497))
case("BENCHMARK", "NIFTY500 exact sessions", lambda: require(BENCH["indices"]["NIFTY 500"]["session_count"] == 497))
case("BENCHMARK", "no NIFTY50 gap", lambda: require(not BENCH["indices"]["NIFTY 50"]["missing_sessions"]))
case("BENCHMARK", "overall benchmark complete", lambda: require(BENCH["status"] == "COMPLETE_VERIFIED"))

# Corporate actions and PIT normalization
for subject, expected in [("Stock Split From Rs 10 To Rs 2", "SPLIT"), ("Bonus 1:1", "BONUS"), ("Demerger", "DEMERGER"), ("Scheme of Amalgamation", "MERGER"), ("Rights 1:2", "RIGHTS"), ("Dividend Rs 5", "DIVIDEND")]:
    case("ACTION", f"classify {expected}", lambda s=subject, e=expected: require(classify_corporate_action(s) == e))
case("ACTION", "bonus factor", lambda: require(split_or_bonus_factor("Bonus 1:1") == 0.5))
case("ACTION", "split factor", lambda: require(split_or_bonus_factor("Stock Split From Rs 10 To Rs 2") == 0.2))
case("ACTION", "unknown factor none", lambda: require(split_or_bonus_factor("Demerger") is None))
action = {"known_date": "2025-01-01", "effective_date": "2025-01-10", "adjustment_factor": 0.5}
case("NORMALIZE", "known effective action applied", lambda: require(apply_pit_adjustment(100, "2025-01-01", "2025-01-10", [action]) == 50))
case("NORMALIZE", "future known date prohibited", lambda: require(apply_pit_adjustment(100, "2024-12-01", "2024-12-31", [action]) == 100))
case("NORMALIZE", "post action price unchanged", lambda: require(apply_pit_adjustment(100, "2025-01-11", "2025-01-11", [action]) == 100))
case("NORMALIZE", "future price rejected", lambda: raises(ValueError, lambda: apply_pit_adjustment(100, "2025-01-11", "2025-01-10", []), "FUTURE"))
case("NORMALIZE", "unknown material terms fail", lambda: raises(ValueError, lambda: apply_pit_adjustment(100, "2025-01-01", "2025-01-10", [{**action, "adjustment_factor": None}]), "UNRESOLVED"))
case("NORMALIZE", "price return profile explicit", lambda: require(NORM["return_profile"] == "PRICE_RETURN_ONLY"))
case("NORMALIZE", "future action use prohibited", lambda: require(NORM["future_action_use"] == "PROHIBITED"))
case("NORMALIZE", "material gaps fail closed", lambda: require(NORM["status"] == "PARTIAL_WITH_GAPS"))

# Costs, features, identity, survivorship, readiness
case("COST", "October 1 2024 included", lambda: require(COST["complete_verified_start"] == "2024-10-01"))
case("COST", "restricted costs complete", lambda: require(COST["status"] == "COMPLETE_VERIFIED"))
case("COST", "pre-window schedules irrelevant", lambda: require(COST["pre_window_missing_schedules_irrelevant"]))
case("FEATURE", "technical ready", lambda: require(FEATURE["families"]["technical"] == "PIT_SAFE"))
case("FEATURE", "full liquidity ready", lambda: require(FEATURE["families"]["liquidity"] == "FULL_LIQUIDITY_AVAILABLE"))
case("FEATURE", "benchmark feature ready", lambda: require(FEATURE["families"]["market_index"] == "PIT_SAFE"))
case("FEATURE", "momentum fails without normalization", lambda: require(FEATURE["families"]["momentum"] == "NOT_READY"))
case("FEATURE", "volatility fails without normalization", lambda: require(FEATURE["families"]["volatility"] == "NOT_READY"))
case("FEATURE", "fundamentals optional", lambda: require(FEATURE["families"]["fundamentals"] == "OPTIONAL_NOT_REQUIRED"))
case("IDENTITY", "no missing non-dummy symbols", lambda: require(IDENTITY["missing_non_dummy_symbols"] == []))
case("IDENTITY", "stable aliases retained", lambda: require(IDENTITY["stable_isin_alias_groups"]))
case("IDENTITY", "unresolved lifecycle fails identity", lambda: require(IDENTITY["status"] == "PARTIAL_WITH_GAPS"))
case("SURVIVORSHIP", "removed historical members retained", lambda: require(SURV["non_current_historical_member_count"] > 0))
case("SURVIVORSHIP", "unknown share reported", lambda: require(SURV["unknown_share_percentage"] > 0))
case("SURVIVORSHIP", "survivorship partial", lambda: require(SURV["status"] == "PARTIAL_WITH_GAPS"))
case("WINDOW", "24 month candidate reported", lambda: require(WINDOW["candidate_continuous_period"]["duration_months"] == 24.0))
case("WINDOW", "497 candidate sessions", lambda: require(WINDOW["candidate_continuous_period"]["trading_sessions"] == 497))
case("WINDOW", "no false jointly valid window", lambda: require(WINDOW["status"] == "NO_JOINTLY_VALID_WINDOW"))
case("V5", "V1 preserved", lambda: require(sha("advanced_research_readiness_v1.json") == V5["preserved_readiness_hashes"]["v1"]))
case("V5", "V2 preserved", lambda: require(sha("advanced_research_readiness_v2.json") == V5["preserved_readiness_hashes"]["v2"]))
case("V5", "V3 preserved", lambda: require(sha("advanced_research_readiness_v3.json") == V5["preserved_readiness_hashes"]["v3"]))
case("V5", "V4 preserved", lambda: require(sha("advanced_research_readiness_v4.json") == V5["preserved_readiness_hashes"]["v4"]))
case("V5", "incomplete reconstruction not ready", lambda: require(V5["status"] == "NOT_READY"))
case("V5", "market gate passes", lambda: require(V5["gates"]["market_data"]))
case("V5", "benchmark gate passes", lambda: require(V5["gates"]["benchmark"]))
case("V5", "cost gate passes", lambda: require(V5["gates"]["execution_costs"]))
case("V5", "training false", lambda: require(V5["training_started"] is False))
case("V5", "synthetic all gates ready", lambda: require(readiness_v5({k: True for k in V5["gates"]}, {"start_date": "2024-10-01", "end_date": "2026-10-01"}, {})["status"] == "READY_WITH_RESTRICTED_PERIOD"))

# Isolation and authority
case("ISOLATION", "Stage4A3 unchanged", lambda: require(not git("diff", "--name-only", "f0a45b2da54a687353a9aeab5f4956d15176b70b", "--", "Stage 4A.3")))
case("ISOLATION", "Stage5D unchanged", lambda: require(not git("diff", "--name-only", "f0a45b2da54a687353a9aeab5f4956d15176b70b", "--", "Stage 5D")))
case("ISOLATION", "Stage6 unchanged", lambda: require(not git("diff", "--name-only", "f0a45b2da54a687353a9aeab5f4956d15176b70b", "--", "Stage 6")))
case("ISOLATION", "no raw bulk tracked", lambda: require(not git("ls-files", "NextGen Research/data/external_authoritative/free_official/restricted_window")))
case("ISOLATION", "no paid data", lambda: require(SOURCE["paid_data_used"] is False))
case("ISOLATION", "no MCP bulk data", lambda: require(SOURCE["mcp_bulk_data_used"] is False))
case("ISOLATION", "research analysis classification", lambda: require(PANEL_MANIFEST["usage_classification"] == "RESEARCH_ANALYSIS_ALLOWED"))
case("ISOLATION", "training rights not fabricated", lambda: require(PANEL_MANIFEST["model_training_rights"] == "NOT_ESTABLISHED"))
case("ISOLATION", "no model trained", lambda: require(V5["challenger_trained"] is False))
case("ISOLATION", "no model promoted", lambda: require(V5["model_promoted"] is False))
case("ISOLATION", "no trading authority", lambda: require(V5["trading_authority"] is False))
case("ISOLATION", "shadow only", lambda: require(V5["authority"] == "SHADOW_ONLY"))
case("ISOLATION", "runtime detector catches raw", lambda: require(tracked_runtime_artifacts(["x/raw/a.csv"])))
case("ISOLATION", "runtime detector catches ZIP", lambda: require(tracked_runtime_artifacts(["x/a.zip"])))

out = RESULTS_DIR / "nextgen_restricted_window_test_results.csv"
with out.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["category", "test", "status", "detail"])
    writer.writeheader(); writer.writerows(RESULTS)

passed = sum(row["status"] == "PASS" for row in RESULTS)
failed = len(RESULTS) - passed
print(json.dumps({"total": len(RESULTS), "passed": passed, "failed": failed, "result": "PASS" if not failed else "FAIL"}))
if failed:
    for row in RESULTS:
        if row["status"] == "FAIL":
            print(f"FAIL {row['category']} :: {row['test']} :: {row['detail']}")
    raise SystemExit(1)
