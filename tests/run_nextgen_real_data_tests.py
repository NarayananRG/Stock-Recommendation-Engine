"""Offline acceptance suite for the verified real-data foundation."""
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

from common import file_sha256, load_json, sha256
from pit_universe import SecurityMaster, eligible_universe
from real_data_foundation import (
    apply_delistings, assess_drift, build_real_pit_snapshot, calculate_verified_costs,
    coverage_report, load_stage4a3_rows, load_verified_cost_schedule,
    parse_nse_delisting_rows, parse_nse_security_master, parse_official_announcement,
    real_calibration_audit, retraining_research_gate, select_cost_schedule,
)
from regression_guard import scan_reverse_dependencies

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


FIX = ROOT / "fixtures/nse_equity_security_master_sample.csv"
RAW = FIX.read_bytes()
MASTER_HASH = hashlib.sha256(RAW).hexdigest()
SEC = parse_nse_security_master(RAW, observed_date="2026-10-03", source_reference="official://nse/equity")
SNAP = build_real_pit_snapshot(SEC, observed_date="2026-10-03", source_dataset_id="REAL_SAMPLE")

case("UNIVERSE", "official security-master parser", lambda: require(len(SEC) == 5))
case("UNIVERSE", "immutable source hash", lambda: require(all(x["provenance_hash"] == MASTER_HASH for x in SEC)))
case("UNIVERSE", "current real snapshot creation", lambda: require(SNAP["data_status"].startswith("REAL_VERIFIED")))
case("UNIVERSE", "official listing date classified", lambda: require(SEC[0]["listing_date_status"] == "VERIFIED_LISTING_DATE"))
case("UNIVERSE", "first appearance not substituted", lambda: require("FIRST_OBSERVED" not in SEC[0]["listing_date_status"]))
case("UNIVERSE", "missing historical membership unknown", lambda: require(SEC[0]["historical_membership_status"] == "UNKNOWN"))
case("UNIVERSE", "sector history unknown", lambda: require(SEC[0]["sector_history_status"] == "UNKNOWN"))
case("UNIVERSE", "duplicate official identity fails", lambda: raises("DUPLICATE", lambda: parse_nse_security_master(RAW + RAW.splitlines(True)[1], observed_date="2026-10-03", source_reference="x")))
case("UNIVERSE", "manifest deterministic", lambda: require(load_json(ROOT/"data/manifests/real_source_archive_manifest_v1.json")["archives"][0]["sha256"] == "95f0d731f5858f71e876c45377dcefa79bc7a8db1e8161d0c92320252af4aa8f"))
DELIST = parse_nse_delisting_rows([["20MICRONS","INE144J01027","20 Microns Limited","Main Board","2026-09-02","Compulsory Delisting"]], retrieved_at="2026-10-03T00:00:00Z", source_reference="official://nse/delist", source_content_hash="d"*64)
case("UNIVERSE", "verified delisting ingestion", lambda: require(DELIST[0]["verification_state"] == "REAL_VERIFIED"))
case("UNIVERSE", "delisting affects PIT query", lambda: require("NSE:INE144J01027" not in [x["security_id"] for x in build_real_pit_snapshot(apply_delistings(SEC, DELIST), observed_date="2026-10-03", source_dataset_id="D")["included_securities"]]))

SCHEDULE_PATH = ROOT / "execution_india/india_equity_cost_schedule_v1.json"
SCHEDULE = load_verified_cost_schedule(SCHEDULE_PATH)
case("COST", "verified schedule source required", lambda: require(SCHEDULE["verification_state"] == "VERIFIED"))
case("COST", "fixture cannot masquerade verified", lambda: raises("REQUIRED", lambda: load_verified_cost_schedule(ROOT/"execution_india/execution_policy_v1.json")))
case("COST", "current verified rate selection", lambda: require(select_cost_schedule(SCHEDULE, "2026-10-03")["artifact_id"] == "INDIA_EQUITY_COST_SCHEDULE_V1"))
case("COST", "effective date boundary", lambda: require(select_cost_schedule(SCHEDULE, "2024-10-01")["effective_from"] == "2024-10-01"))
case("COST", "uncovered historical date fails", lambda: raises("NOT_VERIFIED", lambda: select_cost_schedule(SCHEDULE, "2024-09-30")))
BUY = calculate_verified_costs("100000", "BUY", SCHEDULE, "2")
SELL = calculate_verified_costs("100000", "SELL", SCHEDULE, "2")
case("COST", "buy stamp applicability", lambda: require("STAMP_DUTY_DELIVERY" in BUY["components"]))
case("COST", "sell stamp excluded", lambda: require("STAMP_DUTY_DELIVERY" not in SELL["components"]))
case("COST", "GST taxable base handling", lambda: require(BUY["gst_taxable_base"] == "23.07"))
case("COST", "brokerage separately configurable", lambda: require(BUY["broker_specific_cost"] == "20.00"))
case("COST", "schedule provenance hash deterministic", lambda: require(load_verified_cost_schedule(SCHEDULE_PATH)["canonical_hash"] == SCHEDULE["canonical_hash"]))
case("COST", "brokerage not statutory", lambda: require(SCHEDULE["brokerage"]["cost_class"] == "BROKER_SPECIFIC_COST"))

REGISTRY = load_json(ROOT / "source_registry_v2/verified_source_evidence_v1.json")
SOURCES = {x["source_id"]: x for x in REGISTRY["sources"]}
ANN = load_json(ROOT / "fixtures/official_announcement_sample.json")
PARSED_ANN = parse_official_announcement(ANN, source_id="NSE_CORPORATE_ANNOUNCEMENTS", cutoff_utc="2026-09-11T00:00:00Z")
case("SOURCES", "NSE announcement source verified", lambda: require(SOURCES["NSE_CORPORATE_ANNOUNCEMENTS"]["implementation_status"].startswith("VERIFIED")))
case("SOURCES", "parser structure validation", lambda: require(PARSED_ANN["schema"] == "OFFICIAL_ANNOUNCEMENT_EVIDENCE_V1"))
case("SOURCES", "publication timestamps preserved", lambda: require(PARSED_ANN["broadcast_at_utc"] == ANN["broadcast_at_utc"]))
case("SOURCES", "attachment preserved", lambda: require(PARSED_ANN["attachment_reference"] == ANN["attachment_reference"]))
case("SOURCES", "corporate action not overclaimed", lambda: require(SOURCES["NSE_CORPORATE_ACTIONS"]["implementation_status"] == "VERIFIED_NOT_IMPLEMENTED"))
case("SOURCES", "BSE independently verified", lambda: require(SOURCES["BSE_CORPORATE_FILINGS"]["publisher"] == "BSE Limited"))
case("SOURCES", "unverified cannot become implemented", lambda: require(all(x["implementation_status"] != "VERIFIED_IMPLEMENTED" or x.get("parser_id") for x in REGISTRY["sources"])))
case("SOURCES", "live retrieval absent", lambda: require(PARSED_ANN["network_calls"] == 0 and REGISTRY["network_calls_in_tests"] == 0))
case("SOURCES", "primary evidence separated", lambda: require(PARSED_ANN["evidence_class"] == "PRIMARY_EVIDENCE" and PARSED_ANN["interpretation"] is None))
case("SOURCES", "PIT timestamp violation fails", lambda: raises("PIT", lambda: parse_official_announcement({**ANN,"broadcast_at_utc":"2026-09-09T00:00:00Z"}, source_id="X", cutoff_utc="2026-09-11T00:00:00Z")))

CAL_POLICY = load_json(ROOT / "calibration_governance/real_calibration_policy_v1.json")
CAL = real_calibration_audit(REPO, CAL_POLICY)
case("CALIBRATION", "actual model identity bound", lambda: require(all(len(x["model_hash"]) == 64 for x in CAL["evaluations"])))
case("CALIBRATION", "actual bundle identity bound", lambda: require(all(x["identity_binding"]["model_bundle_hash"] == CAL["model_bundle_hash"] for x in CAL["evaluations"])))
case("CALIBRATION", "actual dataset identity bound", lambda: require(all(x["dataset_id"] == "STAGE4A_OOS_2026_IMMUTABLE" for x in CAL["evaluations"])))
case("CALIBRATION", "real Brier calculated", lambda: require(any(x.get("brier_score") is not None for x in CAL["evaluations"])))
case("CALIBRATION", "real Brier skill calculated", lambda: require(any(x.get("brier_skill_score") is not None for x in CAL["evaluations"])))
case("CALIBRATION", "reliability buckets", lambda: require(any(x.get("reliability_buckets") for x in CAL["evaluations"])))
case("CALIBRATION", "temporal grouping", lambda: require(any(x.get("temporal_analysis") for x in CAL["evaluations"])))
case("CALIBRATION", "insufficient primary sample handled", lambda: require(any(x["calibration_status"] == "INSUFFICIENT_EVIDENCE" for x in CAL["evaluations"])))
case("CALIBRATION", "terminology remains score", lambda: require(all(x["terminology_classification"] == "UNCALIBRATED_MODEL_SCORE" for x in CAL["evaluations"])))
case("CALIBRATION", "no retraining", lambda: require(CAL["retraining_performed"] is False))

REF = [{"feature_value":1.0,"score":0.5,"outcome_rate":0.4,"volatility":1.0,"liquidity":100,"benchmark_relative_return":0,"regime":"CALM","sector":"BANK"} for _ in range(20)]
CUR = [dict(x) for x in REF]
DRIFT_POLICY = {**load_json(ROOT/"model_lifecycle/drift_policy_v1.json"), "configuration_status":"CONFIGURED_TEST_FIXTURE"}
case("DRIFT", "identical distributions stable", lambda: require(assess_drift(REF,CUR,DRIFT_POLICY)["drift_status"] == "STABLE"))
SHIFT = [{**x,"feature_value":4.0,"score":0.9,"regime":"STRESS","sector":"IT"} for x in CUR]
case("DRIFT", "shifted distribution signal", lambda: require(assess_drift(REF,SHIFT,DRIFT_POLICY)["drift_status"] in {"POSSIBLE_DRIFT","MATERIAL_DRIFT"}))
case("DRIFT", "insufficient sample", lambda: require(assess_drift(REF[:2],CUR[:2],DRIFT_POLICY)["drift_status"] == "INSUFFICIENT_DATA"))
ONE = [{**x,"score":0.9} for x in CUR]
case("DRIFT", "single metric cannot retrain", lambda: require(assess_drift(REF,ONE,DRIFT_POLICY)["retraining_permitted"] is False))
case("DRIFT", "research-only authority", lambda: require(assess_drift(REF,CUR,DRIFT_POLICY)["authority_scope"] == "RESEARCH_ONLY"))
case("DRIFT", "automatic action none", lambda: require(assess_drift(REF,SHIFT,DRIFT_POLICY)["automatic_action"] == "NONE"))
case("DRIFT", "eligibility includes drift", lambda: require("drift_evidence_present" in retraining_research_gate({"sample_sufficient":True,"outcomes_mature":True,"benchmark_comparable":True}, assess_drift(REF,SHIFT,DRIFT_POLICY))["gates"]))
case("DRIFT", "no automatic promotion", lambda: require(retraining_research_gate({}, assess_drift(REF,CUR,DRIFT_POLICY))["automatic_promotion"] is False))

def git_diff_paths(*paths):
    cmd = ["git", "--git-dir=_git", "--work-tree=.", "diff", "--name-only", "c6e03f9e1ee3cab6600e441ebc7390819716fdb2", "--", *paths]
    return subprocess.check_output(cmd, cwd=REPO, text=True).splitlines()

case("ISOLATION", "active Stage4A3 unchanged", lambda: require(git_diff_paths("Stage 4A.3") == []))
case("ISOLATION", "active Stage5D unchanged", lambda: require(git_diff_paths("Stage 5D") == []))
case("ISOLATION", "active Stage6 unchanged", lambda: require(git_diff_paths("Stage 6") == []))
case("ISOLATION", "no reverse dependency", lambda: require(scan_reverse_dependencies(REPO) == []))
case("ISOLATION", "raw archives ignored", lambda: require(subprocess.run(["git","--git-dir=_git","--work-tree=.","check-ignore","NextGen Research/data/raw/nse/EQUITY_L.csv"],cwd=REPO).returncode == 0))
case("ISOLATION", "no live connector", lambda: require(REGISTRY["activated_into_stage6_v1"] is False and all(not x["connector_implemented"] for x in REGISTRY["sources"])))
case("ISOLATION", "coverage gaps explicit", lambda: require(load_json(ROOT/"results/nextgen_data_coverage_report_v1.json")["survivorship_bias_fully_solved"] is False))
case("ISOLATION", "real manifest research only", lambda: require(load_json(ROOT/"real_data_foundation_manifest_v1.json")["authority_scope"] == "RESEARCH_ONLY"))

out = ROOT / "results/nextgen_real_data_test_results.csv"
with out.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=["category","test","status","detail"])
    writer.writeheader(); writer.writerows(RESULTS)
summary = {"total":len(RESULTS),"passed":sum(x["status"]=="PASS" for x in RESULTS),"failed":sum(x["status"]=="FAIL" for x in RESULTS)}
print(json.dumps(summary, sort_keys=True))
for row in RESULTS:
    if row["status"] == "FAIL": print(f"FAIL {row['category']} {row['test']}: {row['detail']}")
raise SystemExit(1 if summary["failed"] else 0)
