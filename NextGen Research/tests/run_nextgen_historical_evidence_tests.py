"""Offline acceptance suite for historical evidence completion (2016-2026)."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from common import load_json
from historical_evidence import *

RESULTS = []


def require(value, message="assertion failed"):
    if not value:
        raise AssertionError(message)


def raises(fragment, fn):
    try:
        fn()
    except Exception as exc:
        require(fragment in str(exc), f"expected {fragment}, got {exc}")
        return
    raise AssertionError(f"expected {fragment}")


def case(category, name, fn):
    try:
        fn(); status, detail = "PASS", ""
    except Exception as exc:
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    RESULTS.append({"category": category, "test": name, "status": status, "detail": detail})


SEC_BYTES = (ROOT / "fixtures/nse_equity_security_master_sample.csv").read_bytes()
SEC_HASH = hashlib.sha256(SEC_BYTES).hexdigest()
SNAP = parse_dated_security_snapshot(SEC_BYTES, report_date="2026-10-03", source_reference="official://nse", source_hash=SEC_HASH)
case("UNIVERSE", "dated snapshot parser", lambda: require(len(SNAP) == 5))
case("UNIVERSE", "snapshot source hash verification", lambda: require(all(x["source_file_sha256"] == SEC_HASH for x in SNAP)))
case("UNIVERSE", "bad snapshot hash rejected", lambda: raises("SOURCE_HASH", lambda: parse_dated_security_snapshot(SEC_BYTES, report_date="2026-10-03", source_reference="x", source_hash="0"*64)))
case("UNIVERSE", "snapshot date mandatory valid", lambda: raises("REPORT_DATE", lambda: parse_dated_security_snapshot(SEC_BYTES, report_date="", source_reference="x")))
S = {"security_id":"NSE:X","isin":"X","listing_date":"2020-01-01"}
case("UNIVERSE", "listing-before-date exclusion", lambda: require(classify_historical_eligibility(S,"2019-12-31") == "VERIFIED_NOT_YET_LISTED"))
case("UNIVERSE", "post-delisting exclusion", lambda: require(classify_historical_eligibility({**S,"delisting_date":"2022-01-01"},"2022-01-01") == "VERIFIED_DELISTED"))
case("UNIVERSE", "unknown remains unknown", lambda: require(classify_historical_eligibility(S,"2021-01-01") == "UNKNOWN_HISTORICAL_ELIGIBILITY"))
case("UNIVERSE", "exact snapshot permits eligibility", lambda: require(classify_historical_eligibility(S,"2021-01-01",{"NSE:X"}) == "VERIFIED_ELIGIBLE"))
case("UNIVERSE", "current snapshot cannot masquerade as history", lambda: require(classify_historical_eligibility(SNAP[0],"2020-01-01") != "VERIFIED_ELIGIBLE"))
case("UNIVERSE", "dated security gap explicit", lambda: require(load_json(ROOT/"data/manifests/historical_evidence_source_manifest_v1.json")["dated_security_master_status"] == "DATED_SECURITY_MASTER_DATA_GAP"))

PROV = "a"*64
IDENTITY = [
    {"isin":"INE1","symbol":"OLD","effective_from":"2018-01-01","effective_to":"2020-12-31","source_reference":"official://1","source_file_sha256":PROV},
    {"isin":"INE1","symbol":"NEW","effective_from":"2021-01-01","effective_to":None,"source_reference":"official://2","source_file_sha256":PROV},
]
case("IDENTITY", "ticker change keeps stable identity", lambda: require({x["isin"] for x in build_identity_history(IDENTITY)} == {"INE1"}))
case("IDENTITY", "non-overlapping ticker periods accepted", lambda: require(len(build_identity_history(IDENTITY)) == 2))
case("IDENTITY", "conflicting identity rejected", lambda: raises("CONFLICTING_SYMBOL", lambda: build_identity_history([IDENTITY[0],{**IDENTITY[0],"isin":"INE2"}])))
case("IDENTITY", "overlapping symbols on ISIN rejected", lambda: raises("CONFLICTING_ISIN", lambda: build_identity_history([IDENTITY[0],{**IDENTITY[1],"effective_from":"2020-01-01"}])))
case("IDENTITY", "identity provenance required", lambda: raises("INCOMPLETE", lambda: build_identity_history([{**IDENTITY[0],"source_file_sha256":""}])))

INDEX_BYTES = (ROOT/"fixtures/nifty50_change_events_2020.csv").read_bytes()
INDEX = parse_index_change_events(INDEX_BYTES, source_reference="official://nifty")
case("INDEX", "official change events parsed", lambda: require(len(INDEX) == 6))
case("INDEX", "effective-date membership event", lambda: require(index_membership_status(INDEX,index_id="NIFTY_50",isin="INE528G01035",query_date="2020-03-27") == "VERIFIED_CHANGE_EVENT"))
case("INDEX", "snapshot-only membership classified", lambda: require(index_membership_status(INDEX,index_id="NIFTY_50",isin="INE1",query_date="2020-01-01",snapshot_members={"INE1"},snapshot_date="2020-01-01") == "VERIFIED_AT_SNAPSHOT_DATE"))
case("INDEX", "snapshot nonmember classified only that date", lambda: require(index_membership_status(INDEX,index_id="NIFTY_50",isin="INE2",query_date="2020-01-01",snapshot_members={"INE1"},snapshot_date="2020-01-01") == "VERIFIED_NOT_MEMBER_AT_SNAPSHOT_DATE"))
case("INDEX", "missing period remains unknown", lambda: require(index_membership_status(INDEX,index_id="NIFTY_50",isin="INE1",query_date="2019-01-01") == "UNKNOWN"))
case("INDEX", "no current membership backfill", lambda: require(index_membership_status(INDEX,index_id="NIFTY_50",isin="INE1",query_date="2018-01-01",snapshot_members={"INE1"},snapshot_date="2026-10-03") == "UNKNOWN"))
case("INDEX", "official document hashes retained", lambda: require(all(len(x["source_file_sha256"]) == 64 for x in INDEX)))

SECTOR_BYTES = (ROOT/"fixtures/sector_snapshot_structure_sample.csv").read_bytes()
SECTORS = parse_sector_evidence(SECTOR_BYTES,snapshot_date="2024-01-01",source_reference="structure://fixture")
case("SECTOR", "dated sector evidence", lambda: require(sector_status(SECTORS,"INE000A00000","2024-01-01")["status"] == "SNAPSHOT_ONLY"))
case("SECTOR", "current sector backfill prohibited", lambda: require(sector_status(SECTORS,"INE000A00000","2020-01-01")["status"] == "UNKNOWN"))

ACTION_BYTES = (ROOT/"fixtures/corporate_action_structure_sample.csv").read_bytes()
ACTIONS = parse_corporate_actions(ACTION_BYTES,source_reference="official://structure",retrieved_at="2026-10-04T00:00:00Z")
case("ACTIONS", "official action parser structure", lambda: require(len(ACTIONS) == 1))
case("ACTIONS", "action effective date", lambda: require(ACTIONS[0]["effective_date"] == "2024-01-12"))
case("ACTIONS", "action stable identity", lambda: require(ACTIONS[0]["security_id"] == "NSE:INE000A00000"))
case("ACTIONS", "terms not inferred", lambda: require(ACTIONS[0]["structured_terms"] is None))
case("ACTIONS", "malformed action rejected", lambda: raises("STRUCTURE", lambda: parse_corporate_actions(b"a,b\n1,2\n",source_reference="x",retrieved_at="2026-10-04T00:00:00Z")))
case("ACTIONS", "fixture scope not overclaimed", lambda: require(ACTIONS[0]["evidence_scope"] == "STRUCTURE_VERIFIED_FIXTURE_ONLY"))

BOOK = load_historical_cost_book(ROOT/"execution_india/india_equity_cost_schedule_history_v2.json")
case("COST", "multiple effective schedules", lambda: require(len(BOOK["periods"]) == 6))
case("COST", "boundary date old schedule", lambda: require(select_historical_cost_period(BOOK,"2024-09-30")["period_id"] == "NSE_TIERED_20240401_20240930"))
case("COST", "boundary date new schedule", lambda: require(select_historical_cost_period(BOOK,"2024-10-01")["period_id"] == "UNIFORM_20241001_20260228"))
case("COST", "2026 schedule boundary", lambda: require(select_historical_cost_period(BOOK,"2026-03-01")["period_id"] == "UNIFORM_20260301_20261003"))
case("COST", "uncovered period rejected", lambda: raises("NOT_VERIFIED", lambda: select_historical_cost_period(BOOK,"2018-01-01")))
P2026 = select_historical_cost_period(BOOK,"2026-10-03")
case("COST", "buy stamp applicability", lambda: require(component_applicability(P2026,"STAMP_DUTY_DELIVERY","BUY")["applies"]))
case("COST", "sell stamp non-applicability", lambda: require(not component_applicability(P2026,"STAMP_DUTY_DELIVERY","SELL")["applies"]))
case("COST", "historical schedule cannot use future circular", lambda: require(select_historical_cost_period(BOOK,"2021-01-01")["components"][0]["source_id"] == "NSE_FA46730"))
case("COST", "unverified component fails closed", lambda: raises("COMPONENT_NOT_VERIFIED", lambda: component_applicability(select_historical_cost_period(BOOK,"2021-01-01"),"STT_DELIVERY","BUY")))
case("COST", "canonical cost book verified", lambda: require(len(BOOK["canonical_hash"]) == 64))

MATRIX = load_json(ROOT/"results/execution_cost_coverage_matrix_v1.json")
AUDIT = load_json(ROOT/"results/pit_universe_coverage_audit_v1.json")
READY = load_json(ROOT/"results/advanced_research_readiness_v1.json")
case("COVERAGE", "yearly execution matrix deterministic", lambda: require(build_execution_coverage_matrix(BOOK) == build_execution_coverage_matrix(BOOK)))
case("COVERAGE", "execution years complete", lambda: require([x["year"] for x in MATRIX["years"]] == list(range(2016,2027))))
case("COVERAGE", "2016 unverified", lambda: require(MATRIX["years"][0]["status"] == "UNVERIFIED"))
case("COVERAGE", "2025 complete verified", lambda: require(next(x for x in MATRIX["years"] if x["year"]==2025)["status"] == "COMPLETE_VERIFIED"))
case("COVERAGE", "yearly PIT coverage report", lambda: require(len(AUDIT["years"]) == 11))
case("COVERAGE", "insufficient year classified", lambda: require(next(x for x in AUDIT["years"] if x["year"]==2016)["cross_sectional_research_status"] == "INSUFFICIENT"))
case("COVERAGE", "current year remains cautious", lambda: require(next(x for x in AUDIT["years"] if x["year"]==2026)["cross_sectional_research_status"] == "PARTIAL_USE_WITH_CAUTION"))
case("COVERAGE", "survivorship not solved", lambda: require(AUDIT["survivorship_bias_fully_solved"] is False))
case("COVERAGE", "advanced readiness blocked", lambda: require(READY["status"] == "NOT_READY"))
case("COVERAGE", "no restricted period fabricated", lambda: require(READY["recommended_safe_research_period"] is None))
case("COVERAGE", "full readiness requires gates", lambda: require(not all(READY["gates"].values())))
case("COVERAGE", "no model training", lambda: require(READY["training_started"] is False and READY["challenger_trained"] is False))

def diff_paths(path):
    return subprocess.check_output(["git","--git-dir=_git","--work-tree=.","diff","--name-only","354eb36e3383e5de303b1189e01313c7336657f0","--",path],cwd=REPO,text=True).splitlines()

case("ISOLATION", "active Stage4A3 unchanged", lambda: require(diff_paths("Stage 4A.3") == []))
case("ISOLATION", "Stage5D unchanged", lambda: require(diff_paths("Stage 5D") == []))
case("ISOLATION", "active Stage6 unchanged", lambda: require(diff_paths("Stage 6") == []))
BASELINE = load_json(ROOT/"regression_guard/active_baseline_v1.json")
case("ISOLATION", "activation unchanged", lambda: require(BASELINE["prospective_activation_id"] == "S6PROSACT_7a2195d6a80d73508727c088"))
case("ISOLATION", "active sources unchanged", lambda: require(BASELINE["stage6_v1_source_registry_hash"] == "7d91f4c72365757b6cdfaef0c4027c46bfbdb11c3541c229e828f9ee28d58e90"))
case("ISOLATION", "raw archives ignored", lambda: require(subprocess.run(["git","--git-dir=_git","--work-tree=.","check-ignore","NextGen Research/data/raw/historical/nse_fa64232.pdf"],cwd=REPO,stdout=subprocess.DEVNULL).returncode == 0))
case("ISOLATION", "no runtime artifacts committed", lambda: require(not any(p.endswith((".db",".sqlite",".pyc")) or "__pycache__" in p for p in subprocess.check_output(["git","--git-dir=_git","--work-tree=.","ls-files","NextGen Research"],cwd=REPO,text=True).splitlines())))
case("ISOLATION", "manifest research only", lambda: require(load_json(ROOT/"historical_evidence_manifest_v1.json")["authority_scope"] == "RESEARCH_ONLY"))
case("ISOLATION", "zero live connector", lambda: require(load_json(ROOT/"historical_evidence_manifest_v1.json")["live_connectors"] == 0))
case("ISOLATION", "zero test network", lambda: require(load_json(ROOT/"historical_evidence_manifest_v1.json")["network_calls_in_tests"] == 0))
case("ISOLATION", "no trading or ML authority", lambda: require(load_json(ROOT/"historical_evidence_manifest_v1.json")["trading_authority"] is False and load_json(ROOT/"historical_evidence_manifest_v1.json")["ml_authority"] == "NONE"))

out = ROOT/"results/nextgen_historical_evidence_test_results.csv"
with out.open("w",newline="",encoding="utf-8") as stream:
    writer=csv.DictWriter(stream,fieldnames=["category","test","status","detail"]); writer.writeheader(); writer.writerows(RESULTS)
summary={"total":len(RESULTS),"passed":sum(x["status"]=="PASS" for x in RESULTS),"failed":sum(x["status"]=="FAIL" for x in RESULTS)}
print(json.dumps(summary,sort_keys=True))
for row in RESULTS:
    if row["status"]=="FAIL": print(f"FAIL {row['category']} {row['test']}: {row['detail']}")
raise SystemExit(1 if summary["failed"] else 0)
