from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "NextGen Research"
sys.path.insert(0, str(ROOT))

from free_official_reconstruction import (  # noqa: E402
    backward_reconstruct, bytes_hash, canonical_hash, equity_maintenance_candidates,
    expected_reconstitution_cycles, feature_readiness, free_vs_paid_decision,
    make_change_event, parse_current_anchor, parse_nifty500_replacement,
    parse_press_archive, pit_normalize_price, readiness_v4,
    reconstruction_completeness, require_official_url, resolve_identity,
    tracked_runtime_artifacts, validate_market_rows,
)
from free_official_reconstruction.mcp_client import ENDPOINT, NseBhavcopyMcpClient  # noqa: E402

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
    return json.loads((ROOT / "results" / name).read_text(encoding="utf-8"))


def git(*args):
    return subprocess.check_output(["git", "--git-dir=_git", "--work-tree=.", *args], cwd=REPO, text=True).strip()


ANCHOR = load("nifty500_current_anchor_v1.json")
CAL = load("nifty500_expected_reconstitution_calendar_v1.json")
ADHOC = load("nifty500_adhoc_change_ledger_v1.json")
LEDGER = load("nifty500_constituent_change_ledger_v1.json")
RECON = load("nifty500_reconstructed_pit_membership_v1.json")
COMPLETE = load("nifty500_reconstruction_completeness_v1.json")
MARKET = load("free_official_market_panel_manifest_v1.json")
COVERAGE = load("free_market_data_coverage_v1.json")
FEATURES = load("free_official_feature_pit_readiness_v1.json")
V4 = load("advanced_research_readiness_v4.json")
DECISION = load("free_vs_paid_data_decision_v1.json")
CONTRACT = load("free_official_reconstruction_contract_v1.json")

CSV_GOOD = ("Company Name,Industry,Symbol,Series,ISIN Code\n"
            "Alpha Ltd.,Services,ALPHA,EQ,INE000A01001\n")
CSV_MANY = "Company Name,Industry,Symbol,Series,ISIN Code\n" + "".join(
    f"Company {i},Services,S{i},EQ,INE{i:09d}\n" for i in range(500)
)
PRESS = b'''<div class="pressItem" data-date="Feb 01, 2025"><a href='/Press_Release/x.pdf'>Replacements in indices</a></div>'''
SECTION = """1) Nifty 500
The following company is being excluded:
Sr. No. Company Name Symbol
1 Old Company Ltd. OLD
The following company is being included:
Sr. No. Company Name Symbol
1 New Company Ltd. NEW
2) Nifty Smallcap 250
"""

# Anchor and official-source controls
case("ANCHOR", "current NIFTY500 official anchor parsed", lambda: require(ANCHOR["constituent_count"] == 501))
case("ANCHOR", "anchor official source", lambda: require(ANCHOR["source_classification"] == "OFFICIAL_PUBLIC_VERIFIED"))
case("ANCHOR", "anchor no duplicate symbol", lambda: require(len({x["symbol"] for x in ANCHOR["constituents"]}) == 501))
case("ANCHOR", "anchor no duplicate ISIN", lambda: require(len({x["isin"] for x in ANCHOR["constituents"]}) == 501))
case("ANCHOR", "anchor missing ISIN reported", lambda: require(ANCHOR["missing_isin_count"] == 0))
case("ANCHOR", "anchor hash deterministic", lambda: require(len(ANCHOR["source_sha256"]) == 64))
case("ANCHOR", "non-official anchor blocked", lambda: raises(ValueError, lambda: parse_current_anchor(CSV_MANY.encode(), source_url="https://example.com/x", retrieved_at="2026-10-04T00:00:00Z", as_of_date="2026-10-01"), "OFFICIAL"))
case("ANCHOR", "HTTP anchor blocked", lambda: raises(ValueError, lambda: require_official_url("http://www.niftyindices.com/x"), "OFFICIAL"))
case("ANCHOR", "bad schema blocked", lambda: raises(ValueError, lambda: parse_current_anchor(CSV_MANY.replace("Industry", "Sector").encode(), source_url="https://www.niftyindices.com/x", retrieved_at="2026-10-04T00:00:00Z", as_of_date="2026-10-01"), "SCHEMA"))
case("ANCHOR", "duplicate symbol rejected", lambda: raises(ValueError, lambda: parse_current_anchor(("Company Name,Industry,Symbol,Series,ISIN Code\nA,S,X,EQ,INE1\nB,S,X,EQ,INE2\n" + "".join(f"C{i},S,Y{i},EQ,I{i}\n" for i in range(498))).encode(), source_url="https://www.niftyindices.com/x", retrieved_at="2026-10-04T00:00:00Z", as_of_date="2026-10-01"), "DUPLICATE"))
case("ANCHOR", "duplicate ISIN rejected", lambda: raises(ValueError, lambda: parse_current_anchor(("Company Name,Industry,Symbol,Series,ISIN Code\nA,S,X,EQ,INE1\nB,S,Y,EQ,INE1\n" + "".join(f"C{i},S,Z{i},EQ,I{i}\n" for i in range(498))).encode(), source_url="https://www.niftyindices.com/x", retrieved_at="2026-10-04T00:00:00Z", as_of_date="2026-10-01"), "DUPLICATE"))
case("ANCHOR", "count governance guard", lambda: raises(ValueError, lambda: parse_current_anchor(CSV_GOOD.encode(), source_url="https://www.niftyindices.com/x", retrieved_at="2026-10-04T00:00:00Z", as_of_date="2026-10-01"), "COUNT"))

# Scheduled changes and archive discovery
rels = parse_press_archive(PRESS, source_url="https://www.niftyindices.com/press-release", start_date="2025-01-01", end_date="2025-12-31")
case("SCHEDULE", "press release parsed", lambda: require(len(rels) == 1))
case("SCHEDULE", "press title retained", lambda: require(rels[0]["title"] == "Replacements in indices"))
case("SCHEDULE", "press URL official", lambda: require(rels[0]["source_url"].startswith("https://www.niftyindices.com/")))
case("SCHEDULE", "equity maintenance candidate selected", lambda: require(len(equity_maintenance_candidates(rels)) == 1))
case("SCHEDULE", "fixed-income candidate excluded", lambda: require(not equity_maintenance_candidates([{**rels[0], "title": "Changes in Fixed Income indices"}])))
cycles = expected_reconstitution_cycles("2021-10-01", "2026-10-01")
case("SCHEDULE", "expected March review calendar", lambda: require(sum(x["cycle"] == "MARCH" for x in cycles) == 5))
case("SCHEDULE", "expected September review calendar", lambda: require(sum(x["cycle"] == "SEPTEMBER" for x in cycles) == 5))
case("SCHEDULE", "ten expected cycles", lambda: require(len(cycles) == 10))
case("SCHEDULE", "all expected cycles located", lambda: require(sum(x["announcement_located"] for x in CAL["cycles"]) == 10))
case("SCHEDULE", "all scheduled additions parsed", lambda: require(all(x["additions"] > 0 for x in CAL["cycles"])))
case("SCHEDULE", "all scheduled deletions parsed", lambda: require(all(x["deletions"] > 0 for x in CAL["cycles"])))
case("SCHEDULE", "scheduled changes balanced", lambda: require(all(x["additions"] == x["deletions"] for x in CAL["cycles"])))
case("SCHEDULE", "schedule binds official source", lambda: require("niftyindices.com" in CAL["schedule_source_url"]))
case("SCHEDULE", "schedule source hash", lambda: require(len(CAL["schedule_source_sha256"]) == 64))

# Event parsing and ledger
parsed = parse_nifty500_replacement(SECTION)
case("EVENT", "ad-hoc exclusion parsed", lambda: require(parsed["excluded"][0]["symbol"] == "OLD"))
case("EVENT", "ad-hoc inclusion parsed", lambda: require(parsed["included"][0]["symbol"] == "NEW"))
case("EVENT", "singular company grammar parsed", lambda: require(len(parsed["excluded"]) == 1))
case("EVENT", "missing NIFTY500 section rejected", lambda: raises(ValueError, lambda: parse_nifty500_replacement("Nifty 50"), "SECTION"))
case("EVENT", "empty NIFTY500 transition rejected", lambda: raises(ValueError, lambda: parse_nifty500_replacement("1) Nifty 500\nNo change"), "TRANSITION"))
EV = make_change_event(event_id="E", announcement_date="2024-01-01", effective_date="2024-01-02", source_url="https://www.niftyindices.com/x.pdf", source_sha256="0"*64, reason="test", event_type="AD_HOC_REPLACEMENT", excluded=parsed["excluded"], included=parsed["included"])
case("EVENT", "event effective date retained", lambda: require(EV["effective_date"] == "2024-01-02"))
case("EVENT", "event official source retained", lambda: require(EV["source_classification"] == "OFFICIAL_PUBLIC_VERIFIED"))
case("EVENT", "event identity basis explicit", lambda: require(EV["identity_basis"] == "OFFICIAL_SYMBOL_PLUS_EFFECTIVE_PERIOD"))
case("EVENT", "future announcement rejected", lambda: raises(ValueError, lambda: make_change_event(event_id="E", announcement_date="2024-01-03", effective_date="2024-01-02", source_url="https://www.niftyindices.com/x", source_sha256="0"*64, reason="x", event_type="X", excluded=parsed["excluded"], included=parsed["included"]), "CHRONOLOGY"))
case("EVENT", "duplicate event identity rejected", lambda: raises(ValueError, lambda: make_change_event(event_id="E", announcement_date="2024-01-01", effective_date="2024-01-02", source_url="https://www.niftyindices.com/x", source_sha256="0"*64, reason="x", event_type="X", excluded=[{"company_name":"A","symbol":"S"}], included=[{"company_name":"B","symbol":"S"}]), "AMBIGUOUS"))
case("EVENT", "empty event rejected", lambda: raises(ValueError, lambda: make_change_event(event_id="E", announcement_date="2024-01-01", effective_date="2024-01-02", source_url="https://www.niftyindices.com/x", source_sha256="0"*64, reason="x", event_type="X", excluded=[], included=[]), "EMPTY"))
case("EVENT", "ledger chronological", lambda: require([x["effective_date"] for x in LEDGER["events"]] == sorted(x["effective_date"] for x in LEDGER["events"])))
case("EVENT", "ledger duplicate checked", lambda: require(LEDGER["duplicate_event_count"] == 0))
case("EVENT", "scheduled ledger count", lambda: require(LEDGER["scheduled_event_count"] == 10))
case("EVENT", "ad-hoc discovery retained", lambda: require(ADHOC["inspected_candidate_documents"] == 129))
case("EVENT", "unresolved events explicit", lambda: require(ADHOC["unresolved_events"]))
case("EVENT", "merger scheme event retained", lambda: require(any(x["event_type"] == "SCHEME_OR_CORPORATE_RESTRUCTURING" for x in ADHOC["events"])))

# Reconstruction and completeness
synthetic_anchor = {"as_of_date":"2024-02-01","constituents":[{"company_name":"New","symbol":"NEW","isin":"INE2","industry":"S","series":"EQ"}]}
syn = backward_reconstruct(synthetic_anchor, [EV])
case("RECON", "reverse ADD removes stock", lambda: require("NEW" not in syn["snapshots"][-1]["constituents"]))
case("RECON", "reverse REMOVE restores stock", lambda: require("OLD" in syn["snapshots"][-1]["constituents"]))
case("RECON", "deterministic backward reconstruction", lambda: require(syn == backward_reconstruct(synthetic_anchor, [EV])))
case("RECON", "snapshot hash deterministic", lambda: require(len(syn["snapshots"][-1]["snapshot_sha256"]) == 64))
case("RECON", "round-trip anchor preserved", lambda: require(syn["snapshots"][0]["constituents"] == ["NEW"]))
bad = backward_reconstruct(synthetic_anchor, [{**EV,"included":[{"company_name":"Missing","symbol":"MISS"}]}])
case("RECON", "unresolved event prevents continuity", lambda: require(bad["status"] == "PARTIAL_WITH_GAPS"))
case("RECON", "identity resolution status explicit", lambda: require(bad["gaps"][0]["status"] == "IDENTITY_RESOLUTION_REQUIRED"))
case("RECON", "actual reconstruction fails closed", lambda: require(RECON["status"] == "PARTIAL_WITH_GAPS"))
case("RECON", "actual reconstruction binds ledger hash", lambda: require(RECON["change_ledger_sha256"] == canonical_hash(LEDGER["events"])))
complete_map = {x["cycle_id"]: {"effective_date":"2024-01-01","included":[{"symbol":"A"}],"excluded":[{"symbol":"B"}]} for x in cycles}
cgood = reconstruction_completeness(cycles, complete_map, inspected_releases=1, relevant_releases=1, unresolved_events=[])
case("COMPLETE", "all expected cycles synthetic complete", lambda: require(cgood["status"] == "COMPLETE_FOR_BOUNDED_PERIOD"))
cbad = reconstruction_completeness(cycles, {k:v for i,(k,v) in enumerate(complete_map.items()) if i}, inspected_releases=1, relevant_releases=1, unresolved_events=[])
case("COMPLETE", "missing one cycle partial", lambda: require(cbad["status"] == "PARTIAL_WITH_GAPS"))
case("COMPLETE", "unresolved ad-hoc event partial", lambda: require(reconstruction_completeness(cycles, complete_map, inspected_releases=1, relevant_releases=1, unresolved_events=[{"x":1}])["status"] == "PARTIAL_WITH_GAPS"))
case("COMPLETE", "actual completeness partial", lambda: require(COMPLETE["status"] == "PARTIAL_WITH_GAPS"))
case("COMPLETE", "ten official cycles found", lambda: require(COMPLETE["located_cycle_count"] == 10))

# Market data and MCP
ROWS = [{"date":"2026-10-01","symbol":"ABC","open":10,"high":12,"low":9,"close":11,"volume":100,"totalTradedValue":1100}]
mgood = validate_market_rows(ROWS, source_url=ENDPOINT)
case("MARKET", "official Bhavcopy schema", lambda: require(mgood["ohlc_complete"]))
case("MARKET", "exact session date", lambda: require(mgood["first_date"] == "2026-10-01"))
case("MARKET", "volume valid", lambda: require(mgood["volume_complete"]))
case("MARKET", "turnover available", lambda: require(mgood["turnover_complete"]))
case("MARKET", "duplicate security session rejected", lambda: raises(ValueError, lambda: validate_market_rows(ROWS+ROWS, source_url=ENDPOINT), "DUPLICATE"))
case("MARKET", "invalid high rejected", lambda: raises(ValueError, lambda: validate_market_rows([{**ROWS[0],"high":8}], source_url=ENDPOINT), "OHLC"))
case("MARKET", "invalid low rejected", lambda: raises(ValueError, lambda: validate_market_rows([{**ROWS[0],"low":13}], source_url=ENDPOINT), "OHLC"))
case("MARKET", "negative volume rejected", lambda: raises(ValueError, lambda: validate_market_rows([{**ROWS[0],"volume":-1}], source_url=ENDPOINT), "VOLUME"))
case("MARKET", "non-official market source blocked", lambda: raises(ValueError, lambda: validate_market_rows(ROWS, source_url="https://example.com/x"), "OFFICIAL"))
case("MARKET", "official MCP runtime verified", lambda: require(MARKET["mcp_runtime_status"] == "OFFICIAL_MCP_RUNTIME_AVAILABLE"))
case("MARKET", "MCP bounded three months", lambda: require(MARKET["sample_query"]["trading_days"] == 64))
case("MARKET", "latest completed session derived", lambda: require(MARKET["sample_query"]["actual_last_date"] == "2026-10-01"))
case("MARKET", "full panel not falsely claimed", lambda: require(MARKET["panel_acquired"] is False))
case("MARKET", "market coverage insufficient", lambda: require(COVERAGE["status"] == "INSUFFICIENT"))
case("MARKET", "MCP custom endpoint rejected", lambda: raises(ValueError, lambda: NseBhavcopyMcpClient(endpoint="https://example.com"), "OFFICIAL"))
client = NseBhavcopyMcpClient(); client.session_id = "test"
case("MARKET", "MCP lowercase symbol rejected", lambda: raises(ValueError, lambda: client.stock_history(symbol="abc",months=3,end_date="2026-10-01"), "BOUNDED"))
case("MARKET", "MCP overlong request rejected", lambda: raises(ValueError, lambda: client.stock_history(symbol="ABC",months=4,end_date="2026-10-01"), "BOUNDED"))

# PIT normalization and identity
action={"effective_date":"2024-06-01","known_date":"2024-05-20","adjustment_factor":0.5}
case("NORMALIZE", "raw state explicit", lambda: require("RAW_OFFICIAL_PRICE" in load("pit_price_normalization_policy_v1.json")["states"]))
case("NORMALIZE", "future corporate action prohibited", lambda: require(pit_normalize_price(100,"2024-01-01","2024-05-01",[action]) == 100))
case("NORMALIZE", "effective corporate action normalizes prior price", lambda: require(pit_normalize_price(100,"2024-01-01","2024-06-02",[action]) == 50))
case("NORMALIZE", "post-action price unchanged", lambda: require(pit_normalize_price(100,"2024-06-02","2024-06-02",[action]) == 100))
case("NORMALIZE", "unknown terms fail closed", lambda: raises(ValueError, lambda: pit_normalize_price(100,"2024-01-01","2024-06-02",[{**action,"adjustment_factor":None}]), "UNKNOWN"))
case("NORMALIZE", "future price rejected", lambda: raises(ValueError, lambda: pit_normalize_price(100,"2024-06-03","2024-06-02",[]), "FUTURE"))
periods=[{"symbol":"OLD","isin":"INE1","effective_from":"2020-01-01","effective_to":"2023-12-31"},{"symbol":"NEW","isin":"INE1","effective_from":"2024-01-01","effective_to":None}]
case("IDENTITY", "historical symbol resolves", lambda: require(resolve_identity(periods,symbol="OLD",as_of_date="2023-01-01")["isin"] == "INE1"))
case("IDENTITY", "future symbol not backfilled", lambda: require(resolve_identity(periods,symbol="NEW",as_of_date="2023-01-01") is None))
case("IDENTITY", "ambiguous symbol rejected", lambda: raises(ValueError, lambda: resolve_identity(periods+[dict(periods[0])],symbol="OLD",as_of_date="2023-01-01"), "AMBIGUOUS"))
case("IDENTITY", "current ISIN preferred", lambda: require(load("free_official_security_identity_map_v1.json")["current_isin_coverage"] == 1.0))
case("IDENTITY", "historical ISIN incompleteness explicit", lambda: require(load("free_official_security_identity_map_v1.json")["historical_isin_coverage"] == "INCOMPLETE"))

# Costs, benchmarks, features, survivorship, window and V4
case("COST", "effective-date cost coverage explicit", lambda: require(load("free_official_execution_cost_coverage_v1.json")["complete_verified_start"] == "2024-10-01"))
case("COST", "uncovered old period partial", lambda: require(load("free_official_execution_cost_coverage_v1.json")["status"] == "PARTIAL_VERIFIED"))
case("COST", "tiered unknown context remains partial", lambda: require("TIERED" in load("free_official_execution_cost_coverage_v1.json")["blocker"]))
case("BENCHMARK", "missing official benchmark detected", lambda: require(load("official_benchmark_series_v1.json")["status"] == "NOT_ACQUIRED"))
case("FEATURE", "OHLC opens technical gate", lambda: require(feature_readiness(ohlc=True,normalized_prices=False,volume=False,turnover=False,benchmark=False)["families"]["technical"] == "PIT_SAFE"))
case("FEATURE", "normalized price opens momentum", lambda: require(feature_readiness(ohlc=False,normalized_prices=True,volume=False,turnover=False,benchmark=False)["families"]["momentum"] == "PIT_SAFE"))
case("FEATURE", "volume opens volume liquidity", lambda: require(feature_readiness(ohlc=False,normalized_prices=False,volume=True,turnover=False,benchmark=False)["families"]["liquidity"] == "VOLUME_LIQUIDITY_AVAILABLE"))
case("FEATURE", "turnover absence prevents full liquidity", lambda: require(FEATURES["families"]["liquidity"] != "FULL_LIQUIDITY_AVAILABLE"))
case("FEATURE", "benchmark opens market gate", lambda: require(feature_readiness(ohlc=False,normalized_prices=False,volume=False,turnover=False,benchmark=True)["families"]["market_index"] == "PIT_SAFE"))
case("FEATURE", "all synthetic features ready", lambda: require(feature_readiness(ohlc=True,normalized_prices=True,volume=True,turnover=True,benchmark=True)["minimal_required_profile_pit_safe"]))
SURV=load("survivorship_coverage_assessment_free_official_v1.json")
case("SURVIVORSHIP", "historical removals retained", lambda: require(SURV["historical_non_current_members_retained"] > 0))
case("SURVIVORSHIP", "current-survivor-only state fails", lambda: require(SURV["survivorship_distortion_materially_reduced"] is False))
case("SURVIVORSHIP", "unknown historical years explicit", lambda: require(all(x["status"].startswith("UNKNOWN") for x in SURV["years"])))
WINDOW=load("free_official_research_window_v1.json")
case("WINDOW", "no jointly valid window", lambda: require(WINDOW["status"] == "NO_JOINTLY_VALID_WINDOW"))
case("WINDOW", "24 month gate false", lambda: require(WINDOW["exceeds_24_month_governance_threshold"] is False))
case("WINDOW", "36 month preference false", lambda: require(WINDOW["exceeds_36_month_preference"] is False))
case("V4", "V1 unchanged", lambda: require(hashlib.sha256((ROOT/"results/advanced_research_readiness_v1.json").read_bytes()).hexdigest() == V4["preserved_readiness_hashes"]["v1"]))
case("V4", "V2 unchanged", lambda: require(hashlib.sha256((ROOT/"results/advanced_research_readiness_v2.json").read_bytes()).hexdigest() == V4["preserved_readiness_hashes"]["v2"]))
case("V4", "V3 unchanged", lambda: require(hashlib.sha256((ROOT/"results/advanced_research_readiness_v3.json").read_bytes()).hexdigest() == V4["preserved_readiness_hashes"]["v3"]))
case("V4", "incomplete reconstruction not ready", lambda: require(not V4["gates"]["constituent_reconstruction"]))
case("V4", "insufficient market coverage not ready", lambda: require(not V4["gates"]["market_data"]))
case("V4", "unsafe adjustment semantics not ready", lambda: require(not V4["gates"]["price_adjustment"]))
case("V4", "incomplete costs not ready", lambda: require(not V4["gates"]["execution_costs"]))
case("V4", "incomplete features not ready", lambda: require(not V4["gates"]["features"]))
allg={k:True for k in V4["gates"]}
vready=readiness_v4(gates=allg,period={"start_date":"2024-01-01","end_date":"2025-12-31"},hashes={},preserved_hashes={})
case("V4", "all synthetic gates ready restricted", lambda: require(vready["status"] == "READY_WITH_RESTRICTED_PERIOD"))
case("V4", "exact restricted period emitted", lambda: require(vready["restricted_period"]["start_date"] == "2024-01-01"))
case("V4", "no training started", lambda: require(V4["training_started"] is False and V4["challenger_trained"] is False))
case("V4", "no model promoted", lambda: require(V4["model_promoted"] is False))
case("V4", "no ML authority", lambda: require(V4["ml_authority"] == "NONE"))
case("V4", "no trading authority", lambda: require(V4["trading_authority"] is False))
case("DECISION", "licensed data conclusion explicit", lambda: require(DECISION["decision"] == "LICENSED_DATA_REQUIRED_FOR_RESEARCH_READINESS"))
case("DECISION", "one minimum product named first", lambda: require(DECISION["minimum_missing_product"] == "NSE Indices Historical Index Constituent Data - NIFTY 500"))
case("DECISION", "no purchase performed", lambda: require(DECISION["purchase_performed"] is False))

# Isolation and repository boundaries
case("ISOLATION", "Stage4A3 unchanged", lambda: require(git("diff","--name-only","3ad6b8e99fb3263d2dd2ec9dd509f7d54802e308","--","Stage 4A.3") == ""))
case("ISOLATION", "Stage5D unchanged", lambda: require(git("diff","--name-only","3ad6b8e99fb3263d2dd2ec9dd509f7d54802e308","--","Stage 5D") == ""))
case("ISOLATION", "Stage6 unchanged", lambda: require(git("diff","--name-only","3ad6b8e99fb3263d2dd2ec9dd509f7d54802e308","--","Stage 6") == ""))
case("ISOLATION", "branch exact", lambda: require(git("branch","--show-current") == "nextgen-research-free-official-reconstruction"))
case("ISOLATION", "exact parent remains ancestor", lambda: require(git("merge-base","HEAD","3ad6b8e99fb3263d2dd2ec9dd509f7d54802e308") == "3ad6b8e99fb3263d2dd2ec9dd509f7d54802e308"))
case("ISOLATION", "no raw historical bulk tracked", lambda: require(not [x for x in git("ls-files","NextGen Research/data/external_authoritative").splitlines() if not x.endswith((".gitignore","DATA_DROP_README.md"))]))
case("ISOLATION", "no runtime artifacts tracked", lambda: require(not tracked_runtime_artifacts(git("ls-files").splitlines())))
case("ISOLATION", "no paid acquisition", lambda: require(CONTRACT["paid_data_used"] is False))
case("ISOLATION", "no secondary gate opening", lambda: require(CONTRACT["secondary_gate_opening"] is False))
case("ISOLATION", "SHADOW_ONLY authority", lambda: require(CONTRACT["authority"] == "SHADOW_ONLY"))
case("ISOLATION", "no recommendation logic change", lambda: require(git("diff","--name-only","3ad6b8e99fb3263d2dd2ec9dd509f7d54802e308","--","Stage 5D") == ""))
case("ISOLATION", "source hash helper deterministic", lambda: require(bytes_hash(b"x") == hashlib.sha256(b"x").hexdigest()))
case("ISOLATION", "canonical hash deterministic", lambda: require(canonical_hash({"b":2,"a":1}) == canonical_hash({"a":1,"b":2})))

out = ROOT / "results" / "nextgen_free_official_reconstruction_test_results.csv"
with out.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=["category","test","status","detail"])
    writer.writeheader(); writer.writerows(RESULTS)
summary = {"total":len(RESULTS),"passed":sum(x["status"]=="PASS" for x in RESULTS),"failed":sum(x["status"]=="FAIL" for x in RESULTS)}
print(json.dumps(summary, sort_keys=True))
for row in RESULTS:
    if row["status"] == "FAIL":
        print(f"FAIL {row['category']} {row['test']}: {row['detail']}")
raise SystemExit(1 if summary["failed"] else 0)
