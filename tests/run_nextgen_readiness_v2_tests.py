"""Fail-closed acceptance tests for ADVANCED_RESEARCH_READINESS_V2."""
from __future__ import annotations

import copy
import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from common import file_sha256, load_json
from historical_evidence import advanced_research_readiness_v2

RESULTS = []


def require(value, message="assertion failed"):
    if not value:
        raise AssertionError(message)


def case(category, name, fn):
    try:
        fn(); status, detail = "PASS", ""
    except Exception as exc:
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    RESULTS.append({"category": category, "test": name, "status": status, "detail": detail})


PIT = load_json(ROOT/"results/pit_universe_coverage_audit_v1.json")
COST = load_json(ROOT/"results/execution_cost_coverage_matrix_v1.json")
PROFILE = {"profile_id":"CROSS_SECTIONAL_STOCK_SELECTION", "universe_definition":"EXCHANGE_WIDE_PIT", "requires_historical_sector":False}
PERIOD = {"start_date":"2026-01-01", "end_date":"2026-10-03"}


def decide(pit=PIT, cost=COST, **overrides):
    args = {
        "research_profile": PROFILE, "proposed_period": PERIOD,
        "features_pit_safe": False, "governance_ready": True,
        "benchmark_prices_available": True, "identity_history_sufficient": False,
        "survivorship_distortion_materially_reduced": False,
        "index_membership_available": False, "historical_sector_available": False,
    }
    args.update(overrides)
    return advanced_research_readiness_v2(pit, cost, **args)


CURRENT = decide()
case("FAIL_CLOSED", "current evidence not ready", lambda: require(CURRENT["status"] == "NOT_READY"))
case("FAIL_CLOSED", "current reasons include no approved period", lambda: require("NO_APPROVED_ADVANCED_RESEARCH_PERIOD" in CURRENT["reasons"]))
case("FAIL_CLOSED", "features PIT safe alone remains blocked", lambda: require(decide(features_pit_safe=True)["status"] == "NOT_READY"))
case("FAIL_CLOSED", "governance alone remains blocked", lambda: require(decide(governance_ready=True)["status"] == "NOT_READY"))
case("FAIL_CLOSED", "complete execution alone remains blocked", lambda: require(CURRENT["gates"]["execution_cost_coverage_sufficient"] and CURRENT["status"] == "NOT_READY"))
case("FAIL_CLOSED", "partial universe with all other gates remains blocked", lambda: require(decide(features_pit_safe=True,identity_history_sufficient=True,survivorship_distortion_materially_reduced=True,index_membership_available=True,historical_sector_available=True)["status"] == "NOT_READY"))

PIT_COMPLETE = copy.deepcopy(PIT)
for row in PIT_COMPLETE["years"]:
    if row["year"] == 2026:
        row["cross_sectional_research_status"] = "SUFFICIENT_FOR_RESEARCH"
PIT_COMPLETE["survivorship_bias_fully_solved"] = True
ALL_TRUE = {
    "features_pit_safe":True, "governance_ready":True,
    "benchmark_prices_available":True, "identity_history_sufficient":True,
    "survivorship_distortion_materially_reduced":True,
    "index_membership_available":True, "historical_sector_available":True,
}
case("FAIL_CLOSED", "survivorship false blocks complete fixture", lambda: require(decide(PIT_COMPLETE,**{**ALL_TRUE,"survivorship_distortion_materially_reduced":False})["status"] == "NOT_READY"))
case("FAIL_CLOSED", "identity false blocks complete fixture", lambda: require(decide(PIT_COMPLETE,**{**ALL_TRUE,"identity_history_sufficient":False})["status"] == "NOT_READY"))
INDEX_PROFILE = {"profile_id":"CROSS_SECTIONAL_STOCK_SELECTION","universe_definition":"INDEX_CONSTITUENT_PIT","requires_historical_sector":False}
case("PROFILE", "index profile requires historical membership", lambda: require(decide(PIT_COMPLETE,**{**ALL_TRUE,"research_profile":INDEX_PROFILE,"index_membership_available":False})["status"] == "NOT_READY"))
SECTOR_PROFILE = {"profile_id":"CROSS_SECTIONAL_STOCK_SELECTION","universe_definition":"EXCHANGE_WIDE_PIT","requires_historical_sector":True}
case("PROFILE", "sector-neutral profile requires historical sectors", lambda: require(decide(PIT_COMPLETE,**{**ALL_TRUE,"research_profile":SECTOR_PROFILE,"historical_sector_available":False})["status"] == "NOT_READY"))
READY = decide(PIT_COMPLETE,**ALL_TRUE)
case("PROFILE", "all required gates permit restricted synthetic fixture", lambda: require(READY["status"] == "READY_WITH_RESTRICTED_PERIOD"))
case("PROFILE", "restricted period represented explicitly", lambda: require(READY["recommended_safe_research_period"] == PERIOD and READY["proposed_research_period"]["years"] == [2026]))
case("PROFILE", "partial year never fully eligible", lambda: require(CURRENT["partial_snapshot_years"] == [2026] and CURRENT["fully_research_eligible_years"] == []))
case("ARTIFACT", "V1 artifact preserved byte-for-byte", lambda: require(file_sha256(ROOT/"results/advanced_research_readiness_v1.json") == "70b603aecd427e9947d4fbf4a68b9eb6f32ff2c1151a930049300d343c5ba6b4"))
case("ARTIFACT", "V2 deterministic", lambda: require(decide() == decide()))
case("ARTIFACT", "required gate changes V2 record hash", lambda: require(decide(PIT_COMPLETE,**ALL_TRUE)["record_hash"] != decide(PIT_COMPLETE,**{**ALL_TRUE,"identity_history_sufficient":False})["record_hash"]))
case("ARTIFACT", "current V2 committed result matches", lambda: require(load_json(ROOT/"results/advanced_research_readiness_v2.json") == CURRENT))
case("AUTHORITY", "no training started", lambda: require(CURRENT["training_started"] is False and CURRENT["challenger_trained"] is False))
case("AUTHORITY", "no model promoted", lambda: require(CURRENT["model_promoted"] is False and CURRENT["ml_authority"] == "NONE"))


def active_diff():
    return subprocess.check_output([
        "git","--git-dir=_git","--work-tree=.","diff","--name-only",
        "c00853e15e6d3496f06bb7151808c6da48d0cbd6","--","Stage 4A.3","Stage 5D","Stage 6"
    ],cwd=REPO,text=True).splitlines()


case("ISOLATION", "active lane unchanged", lambda: require(active_diff() == []))
CLASSIFICATION = load_json(ROOT/"results/stage6_regression_classification_v1.json")
case("ISOLATION", "Stage6 branch constraint classified separately", lambda: require(CLASSIFICATION["failure_classification"] == "FROZEN_TEST_HARNESS_BRANCH_CONSTRAINT" and CLASSIFICATION["code_regression"] is False))
case("ISOLATION", "frozen Stage6 test not modified", lambda: require(CLASSIFICATION["frozen_test_modified"] is False and CLASSIFICATION["stage6_file_diff_count"] == 0))

out = ROOT/"results/nextgen_readiness_v2_test_results.csv"
with out.open("w",newline="",encoding="utf-8") as stream:
    writer=csv.DictWriter(stream,fieldnames=["category","test","status","detail"]); writer.writeheader(); writer.writerows(RESULTS)
summary={"total":len(RESULTS),"passed":sum(x["status"]=="PASS" for x in RESULTS),"failed":sum(x["status"]=="FAIL" for x in RESULTS)}
print(json.dumps(summary,sort_keys=True))
for row in RESULTS:
    if row["status"]=="FAIL": print(f"FAIL {row['category']} {row['test']}: {row['detail']}")
raise SystemExit(1 if summary["failed"] else 0)
