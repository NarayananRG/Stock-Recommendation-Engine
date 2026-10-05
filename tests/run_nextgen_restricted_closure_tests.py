from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
RESULTS_DIR = ROOT / "results"
sys.path.insert(0, str(ROOT))

from restricted_window import (  # noqa: E402
    CONTINUITY_STATES, RIGHTS_STATES, SECURITY_STATES, action_continuity,
    action_safe_for_feature, decision_v3, feature_eligibility, readiness_v6,
    security_state,
)

ROWS = []


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
    ROWS.append({"category": category, "test": name, "status": status, "detail": detail})


def load(name):
    return json.loads((RESULTS_DIR / name).read_text(encoding="utf-8"))


def sha(name):
    return hashlib.sha256((RESULTS_DIR / name).read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "--git-dir=_git", "--work-tree=.", *args], cwd=REPO, text=True).strip()


SIEMENS = load("nifty500_lifecycle_siemens_energy_v1.json")
ABLBL = load("nifty500_lifecycle_ablbl_v1.json")
TATA = load("nifty500_lifecycle_tata_motors_demerger_v1.json")
VEDANTA = load("nifty500_lifecycle_vedanta_demerger_v1.json")
IDENTITY = load("restricted_security_identity_readiness_v2.json")
POLICY = load("restricted_feature_history_policy_v1.json")
CONTINUITY = load("corporate_action_feature_continuity_policy_v1.json")
NORM = load("restricted_pit_price_normalization_2024_2026_v2.json")
UNIVERSE = load("nifty500_restricted_investable_universe_v2.json")
SURV = load("restricted_survivorship_assessment_v2.json")
FEATURE = load("restricted_feature_pit_readiness_v2.json")
PROVENANCE = load("restricted_market_panel_provenance_v1.json")
BENCH_RIGHTS = load("benchmark_data_usage_rights_v1.json")
RIGHTS_POLICY = load("nextgen_data_usage_rights_policy_v1.json")
RIGHTS = load("model_training_usage_rights_readiness_v1.json")
TECHNICAL = load("technical_research_data_readiness_v1.json")
V6 = load("advanced_research_readiness_v6.json")
DECISION3 = load("free_vs_paid_data_decision_v3.json")
CONTRACT = load("nextgen_restricted_closure_contract_v1.json")

# Lifecycle closure
case("LIFECYCLE", "Siemens resolved", lambda: require(SIEMENS["status"] == "RESOLVED"))
case("LIFECYCLE", "Siemens dummy nontradable", lambda: require(SIEMENS["dummy"]["classification"] == "INDEX_ACCOUNTING_PLACEHOLDER_NONTRADABLE"))
case("LIFECYCLE", "Siemens successor", lambda: require(SIEMENS["successor"]["symbol"] == "ENRIN"))
case("LIFECYCLE", "Siemens ISIN", lambda: require(SIEMENS["successor"]["isin"] == "INE1NPP01017"))
case("LIFECYCLE", "Siemens listing", lambda: require(SIEMENS["successor"]["listing_date"] == "2025-06-19"))
case("LIFECYCLE", "Siemens exit", lambda: require(SIEMENS["temporary_index_exit_effective"] == "2025-06-27"))
case("LIFECYCLE", "Siemens regular reentry", lambda: require(SIEMENS["regular_nifty500_reentry_effective"] == "2025-09-30"))
case("LIFECYCLE", "ABLBL resolved", lambda: require(ABLBL["status"] == "RESOLVED"))
case("LIFECYCLE", "ABLBL dummy nontradable", lambda: require(ABLBL["dummy"]["classification"] == "INDEX_ACCOUNTING_PLACEHOLDER_NONTRADABLE"))
case("LIFECYCLE", "ABLBL parent", lambda: require(ABLBL["predecessor"]["symbol"] == "ABFRL"))
case("LIFECYCLE", "ABLBL successor", lambda: require(ABLBL["successor"]["symbol"] == "ABLBL"))
case("LIFECYCLE", "ABLBL ISIN", lambda: require(ABLBL["successor"]["isin"] == "INE14LE01019"))
case("LIFECYCLE", "ABLBL listing", lambda: require(ABLBL["successor"]["listing_date"] == "2025-06-23"))
case("LIFECYCLE", "ABLBL temporary exit", lambda: require(ABLBL["temporary_index_exit_effective"] == "2025-06-27"))
case("LIFECYCLE", "ABLBL regular inclusion", lambda: require(ABLBL["regular_nifty500_inclusion_effective"] == "2025-09-30"))
case("LIFECYCLE", "Tata resolved", lambda: require(TATA["status"] == "RESOLVED"))
case("LIFECYCLE", "Tata dummy nontradable", lambda: require(TATA["dummy"]["classification"] == "INDEX_ACCOUNTING_PLACEHOLDER_NONTRADABLE"))
case("LIFECYCLE", "Tata successor", lambda: require(TATA["successor"]["symbol"] == "TMCV"))
case("LIFECYCLE", "Tata successor ISIN", lambda: require(TATA["successor"]["isin"] == "INE1TAE01010"))
case("LIFECYCLE", "Tata listing", lambda: require(TATA["successor"]["listing_date"] == "2025-11-12"))
case("LIFECYCLE", "Tata exit", lambda: require(TATA["temporary_index_exit_effective"] == "2025-11-17"))
case("LIFECYCLE", "Vedanta resolved", lambda: require(VEDANTA["status"] == "RESOLVED"))
case("LIFECYCLE", "Vedanta four successors", lambda: require(len(VEDANTA["resulting_entities"]) == 4))
for dummy, symbol, isin, exit_day in [
    ("DUMMYVEDL1", "VAML", "INE1CDF01017", "2026-06-23"),
    ("DUMMYVEDL2", "VEDPOWER", "INE694L01019", "2026-06-19"),
    ("DUMMYVEDL3", "VOGL", "INE704J01044", "2026-06-24"),
    ("DUMMYVEDL4", "VISL", "INE1CLE01013", "2026-06-19"),
]:
    case("LIFECYCLE", f"{dummy} evidence mapping", lambda d=dummy, s=symbol, i=isin: require(any(x["dummy_symbol"] == d and x["symbol"] == s and x["isin"] == i for x in VEDANTA["resulting_entities"])))
    case("LIFECYCLE", f"{symbol} listing", lambda s=symbol: require(next(x for x in VEDANTA["resulting_entities"] if x["symbol"] == s)["listing_date"] == "2026-06-15"))
    case("LIFECYCLE", f"{symbol} exit", lambda s=symbol, e=exit_day: require(next(x for x in VEDANTA["resulting_entities"] if x["symbol"] == s)["exit_effective"] == e))
case("LIFECYCLE", "no lifecycle unresolved", lambda: require(all(x["status"] == "RESOLVED" for x in (SIEMENS, ABLBL, TATA, VEDANTA))))

# Investability and security states
case("INVESTABILITY", "security states complete", lambda: require(len(SECURITY_STATES) == 6))
case("INVESTABILITY", "dummy state", lambda: require(security_state(placeholder=True) == "INDEX_ACCOUNTING_PLACEHOLDER_NONTRADABLE"))
case("INVESTABILITY", "not listed state", lambda: require(security_state(listed=False) == "RESULTING_ENTITY_NOT_YET_LISTED"))
case("INVESTABILITY", "temporary listed state", lambda: require(security_state(temporary=True) == "LISTED_BUT_TEMPORARY_INDEX_TREATMENT"))
case("INVESTABILITY", "excluded state", lambda: require(security_state(excluded=True) == "DELISTED_OR_EXCLUDED"))
case("INVESTABILITY", "unknown identity state", lambda: require(security_state(identity_known=False) == "IDENTITY_UNRESOLVED"))
case("INVESTABILITY", "ordinary listed state", lambda: require(security_state() == "TRADABLE_LISTED_EQUITY"))
case("INVESTABILITY", "dummy never eligible", lambda: require(feature_eligibility(index_member=True, listed=True, identity_known=True, unresolved_action=False, observed_sessions=100, placeholder=True) == "INDEX_PLACEHOLDER_EXCLUDED"))
case("INVESTABILITY", "not listed never eligible", lambda: require(feature_eligibility(index_member=True, listed=False, identity_known=True, unresolved_action=False, observed_sessions=100) == "RESULTING_ENTITY_NOT_YET_LISTED"))
case("INVESTABILITY", "59 session warmup", lambda: require(feature_eligibility(index_member=True, listed=True, identity_known=True, unresolved_action=False, observed_sessions=59) == "FEATURE_WARMUP_NOT_COMPLETE"))
case("INVESTABILITY", "60 session eligible", lambda: require(feature_eligibility(index_member=True, listed=True, identity_known=True, unresolved_action=False, observed_sessions=60) == "MODEL_CANDIDATE_ELIGIBLE"))
case("INVESTABILITY", "unresolved action blocks", lambda: require(feature_eligibility(index_member=True, listed=True, identity_known=True, unresolved_action=True, observed_sessions=100) == "CORPORATE_ACTION_UNRESOLVED"))
case("INVESTABILITY", "index nonmember blocked", lambda: require(feature_eligibility(index_member=False, listed=True, identity_known=True, unresolved_action=False, observed_sessions=100) == "NOT_INDEX_MEMBER"))
case("INVESTABILITY", "497 universe sessions", lambda: require(len(UNIVERSE["sessions"]) == 497))
case("INVESTABILITY", "index and research concepts separate", lambda: require(len(UNIVERSE["concepts_separate"]) == 2))
case("INVESTABILITY", "no unresolved security", lambda: require(UNIVERSE["unresolved_security_count"] == 0))
case("INVESTABILITY", "dummy present in index accounting", lambda: require(any(x["nontradable_index_placeholders"] for x in UNIVERSE["sessions"])))
case("INVESTABILITY", "dummy absent from candidates", lambda: require(all(not any(s.startswith("DUMMY") for s in x["model_eligible_securities"]) for x in UNIVERSE["sessions"])))
case("INVESTABILITY", "monthly coverage complete", lambda: require(len(UNIVERSE["monthly_coverage"]) == 25))

# Feature history and normalization
case("LOOKBACK", "max lookback 60", lambda: require(POLICY["maximum_lookback_sessions"] == 60))
case("LOOKBACK", "all four horizons", lambda: require(POLICY["horizons_sessions"] == [5, 10, 20, 60]))
case("LOOKBACK", "prelisting prohibited", lambda: require(POLICY["pre_listing_history"] == "PROHIBITED"))
case("LOOKBACK", "dummy splicing prohibited", lambda: require(POLICY["dummy_price_splicing"] == "PROHIBITED"))
case("NORMALIZATION", "continuity states complete", lambda: require(len(CONTINUITY_STATES) == 5))
case("NORMALIZATION", "split factor adjust", lambda: require(action_continuity("SPLIT", .5) == "PIT_ADJUSTMENT_AVAILABLE"))
case("NORMALIZATION", "bonus factor adjust", lambda: require(action_continuity("BONUS", .5) == "PIT_ADJUSTMENT_AVAILABLE"))
case("NORMALIZATION", "unparsed split reset", lambda: require(action_continuity("SPLIT") == "FEATURE_HISTORY_RESET_REQUIRED"))
case("NORMALIZATION", "rights reset", lambda: require(action_continuity("RIGHTS") == "FEATURE_HISTORY_RESET_REQUIRED"))
case("NORMALIZATION", "demerger reset", lambda: require(action_continuity("DEMERGER") == "FEATURE_HISTORY_RESET_REQUIRED"))
case("NORMALIZATION", "new listing new history", lambda: require(action_continuity("NEW_LISTING") == "SECURITY_NEW_HISTORY_REQUIRED"))
case("NORMALIZATION", "dividend no split adjustment", lambda: require(action_continuity("DIVIDEND") == "NO_FEATURE_RESET_REQUIRED"))
case("NORMALIZATION", "unknown action blocks", lambda: require(action_continuity("UNKNOWN") == "UNRESOLVED_BLOCKING"))
case("NORMALIZATION", "future action does not alter feature", lambda: require(action_safe_for_feature(feature_date="2025-01-01", action_effective_date="2025-02-01", action_known_date="2025-01-20", policy="UNRESOLVED_BLOCKING")))
case("NORMALIZATION", "known unresolved action unsafe", lambda: require(not action_safe_for_feature(feature_date="2025-02-01", action_effective_date="2025-02-01", action_known_date="2025-01-20", policy="UNRESOLVED_BLOCKING")))
case("NORMALIZATION", "no blocking actions", lambda: require(NORM["unresolved_blocking_actions"] == 0))
case("NORMALIZATION", "price return only", lambda: require(NORM["return_profile"] == "PRICE_RETURN_ONLY"))
case("NORMALIZATION", "future use prohibited", lambda: require(NORM["future_action_use"] == "PROHIBITED"))
case("NORMALIZATION", "V2 PIT safe", lambda: require(NORM["status"] == "COMPLETE_PIT_SAFE_WITH_RESETS"))

# Identity, survivorship, feature readiness
case("IDENTITY", "identity complete", lambda: require(IDENTITY["status"] == "COMPLETE_VERIFIED_FOR_INVESTABLE_UNIVERSE"))
case("IDENTITY", "seven successor chains", lambda: require(len(IDENTITY["predecessor_successor_chains"]) == 7))
case("IDENTITY", "no missing investable identity", lambda: require(IDENTITY["missing_investable_symbols"] == []))
case("IDENTITY", "no ambiguous investable identity", lambda: require(IDENTITY["ambiguous_investable_identity_count"] == 0))
case("IDENTITY", "dummies separately classified", lambda: require(IDENTITY["identity_states"]["dummies"] == "INDEX_DUMMY_NONTRADABLE"))
case("SURVIVORSHIP", "survivorship complete", lambda: require(SURV["status"] == "COMPLETE_FOR_RESTRICTED_INVESTABLE_UNIVERSE"))
case("SURVIVORSHIP", "historical members retained", lambda: require(SURV["historical_non_current_securities"] > 0))
case("SURVIVORSHIP", "dummy excluded from survivor count", lambda: require(SURV["dummy_placeholders_excluded_from_investable_survivors"]))
case("SURVIVORSHIP", "zero unknown investable share", lambda: require(SURV["unknown_investable_identity_share_percentage"] == 0.0))
for family, expected in [("technical", "PIT_SAFE"), ("momentum", "PIT_SAFE_FOR_ELIGIBLE_SECURITIES"), ("volatility", "PIT_SAFE_FOR_ELIGIBLE_SECURITIES"), ("liquidity", "FULL_LIQUIDITY_AVAILABLE"), ("market_index", "PIT_SAFE")]:
    case("FEATURE", f"{family} ready", lambda f=family, e=expected: require(FEATURE["families"][f] == e))
case("FEATURE", "fundamentals optional", lambda: require(FEATURE["families"]["fundamentals"] == "OPTIONAL_NOT_REQUIRED"))
case("FEATURE", "minimal profile ready", lambda: require(FEATURE["minimal_profile_ready"]))

# Provenance and rights
case("PROVENANCE", "497 source files", lambda: require(PROVENANCE["file_count"] == 497))
case("PROVENANCE", "all files have channel", lambda: require(all(x["acquisition_channel"] for x in PROVENANCE["files"])))
case("PROVENANCE", "all files hash bound", lambda: require(all(len(x["sha256"]) == 64 for x in PROVENANCE["files"])))
case("PROVENANCE", "all file rows counted", lambda: require(all(x["row_count"] > 0 for x in PROVENANCE["files"])))
case("PROVENANCE", "public report rows exact", lambda: require(PROVENANCE["public_report_row_count"] == 1579133))
case("PROVENANCE", "MCP rows zero", lambda: require(PROVENANCE["mcp_derived_row_count"] == 0))
case("PROVENANCE", "raw not committed claim", lambda: require(PROVENANCE["raw_files_committed"] is False))
case("RIGHTS", "rights states complete", lambda: require(len(RIGHTS_STATES) == 6))
case("RIGHTS", "public access not permission", lambda: require(RIGHTS_POLICY["public_access_does_not_imply_training_permission"]))
case("RIGHTS", "MCP training permission not inferred", lambda: require(RIGHTS_POLICY["mcp"]["classification"] == "PROHIBITED_FOR_MODEL_TRAINING_WITHOUT_SEPARATE_PERMISSION"))
case("RIGHTS", "public report classified separately", lambda: require(RIGHTS_POLICY["market_panel"]["channel"] == "PUBLIC_HISTORICAL_REPORT_ARCHIVE"))
case("RIGHTS", "market rights not established", lambda: require(RIGHTS_POLICY["market_panel"]["classification"] == "MODEL_TRAINING_RIGHTS_NOT_ESTABLISHED"))
case("RIGHTS", "benchmark separate", lambda: require(BENCH_RIGHTS["stock_data_policy_not_reused_for_benchmark"]))
case("RIGHTS", "benchmark license required", lambda: require(BENCH_RIGHTS["status"] == "LICENSE_REQUIRED"))
case("RIGHTS", "training rights fail closed", lambda: require(RIGHTS["ready"] is False))
case("RIGHTS", "training rights license state", lambda: require(RIGHTS["status"] == "LICENSE_REQUIRED"))

# V6 and decision V3
case("TECHNICAL", "technically ready", lambda: require(TECHNICAL["status"] == "TECHNICALLY_READY_WITH_RESTRICTED_PERIOD"))
case("TECHNICAL", "all technical gates pass", lambda: require(all(TECHNICAL["gates"].values())))
case("TECHNICAL", "exact restricted start", lambda: require(TECHNICAL["restricted_period"]["start_date"] == "2024-10-01"))
case("TECHNICAL", "exact restricted end", lambda: require(TECHNICAL["restricted_period"]["end_date"] == "2026-10-01"))
case("TECHNICAL", "497 sessions", lambda: require(TECHNICAL["restricted_period"]["trading_sessions"] == 497))
for version in range(1, 6):
    case("V6", f"V{version} preserved", lambda v=version: require(sha(f"advanced_research_readiness_v{v}.json") == V6["preserved_readiness_hashes"][f"v{v}"]))
case("V6", "rights pending state", lambda: require(V6["status"] == "TECHNICALLY_READY_RIGHTS_PENDING"))
case("V6", "no failed technical gates", lambda: require(V6["failed_technical_gates"] == []))
case("V6", "training false", lambda: require(V6["training_started"] is False))
case("V6", "synthetic technical failure", lambda: require(readiness_v6({**TECHNICAL["gates"], "features": False}, False, TECHNICAL["restricted_period"], {})["status"] == "NOT_READY"))
case("V6", "synthetic rights pending", lambda: require(readiness_v6(TECHNICAL["gates"], False, TECHNICAL["restricted_period"], {})["status"] == "TECHNICALLY_READY_RIGHTS_PENDING"))
case("V6", "synthetic fully ready", lambda: require(readiness_v6(TECHNICAL["gates"], True, TECHNICAL["restricted_period"], {})["status"] == "READY_WITH_RESTRICTED_PERIOD"))
case("DECISION3", "technical and rights distinguished", lambda: require(DECISION3["technical_data_status"] == "TECHNICALLY_READY_WITH_RESTRICTED_PERIOD" and DECISION3["model_training_usage_rights"] == "LICENSE_REQUIRED"))
case("DECISION3", "license is for training", lambda: require(DECISION3["decision"] == "LICENSE_REQUIRED_FOR_MODEL_TRAINING"))
case("DECISION3", "constituent paid data not needed", lambda: require(DECISION3["paid_historical_constituent_data_technically_required"] is False))
case("DECISION3", "permission pending synthetic", lambda: require(decision_v3(technically_ready=True, rights_state="PERMISSION_REQUIRED") == "PERMISSION_REQUIRED_FOR_MODEL_TRAINING"))
case("DECISION3", "technical paid need separate", lambda: require(decision_v3(technically_ready=False, rights_state="NOT_ESTABLISHED", technical_paid_data_required=True) == "LICENSED_DATA_REQUIRED_FOR_TECHNICAL_COMPLETENESS"))
case("DECISION3", "V1 decision preserved", lambda: require(sha("free_vs_paid_data_decision_v1.json") == DECISION3["previous_decision_hashes"]["v1"]))
case("DECISION3", "V2 decision preserved", lambda: require(sha("free_vs_paid_data_decision_v2.json") == DECISION3["previous_decision_hashes"]["v2"]))

# Isolation and authority
for path in ("Stage 4A.3", "Stage 5D", "Stage 6"):
    case("ISOLATION", f"{path} unchanged", lambda p=path: require(not git("diff", "--name-only", "19c5d0823c30947c5fdeec3bba4e7738cd343436", "--", p)))
case("ISOLATION", "no raw tracked", lambda: require(not git("ls-files", "NextGen Research/data/external_authoritative/free_official/restricted_closure")))
case("ISOLATION", "no training", lambda: require(V6["challenger_trained"] is False))
case("ISOLATION", "no promotion", lambda: require(V6["model_promoted"] is False))
case("ISOLATION", "no trading authority", lambda: require(V6["trading_authority"] is False))
case("ISOLATION", "shadow only", lambda: require(V6["authority"] == "SHADOW_ONLY"))
case("ISOLATION", "no paid purchase", lambda: require(DECISION3["purchase_performed"] is False))
case("ISOLATION", "contract baseline exact", lambda: require(CONTRACT["baseline"] == "19c5d0823c30947c5fdeec3bba4e7738cd343436"))
case("ISOLATION", "no tag expected", lambda: require(CONTRACT["tags_created"] == 0))

out = RESULTS_DIR / "nextgen_restricted_closure_test_results.csv"
with out.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["category", "test", "status", "detail"])
    writer.writeheader(); writer.writerows(ROWS)
passed = sum(x["status"] == "PASS" for x in ROWS)
failed = len(ROWS) - passed
print(json.dumps({"total": len(ROWS), "passed": passed, "failed": failed, "result": "PASS" if not failed else "FAIL"}))
if failed:
    for row in ROWS:
        if row["status"] == "FAIL":
            print(f"FAIL {row['category']} :: {row['test']} :: {row['detail']}")
    raise SystemExit(1)
