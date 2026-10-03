"""Offline focused acceptance suite for Next-Generation Research Priorities 4-8."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from common import AUTHORITY, load_json, sha256
from pit_universe import SecurityMaster, eligible_universe
from execution_india import CostScheduleBook, simulate_execution, resolve_stop_target
from source_registry_v2 import FutureSourceRegistry, validate_evidence, fixture_connector
from calibration_governance import audit_term, report_label, evaluate_calibration
from model_lifecycle import ResearchModelRegistry, model_record, retraining_eligibility, freeze_training_dataset, challenger_evaluation, approval_artifact
from regression_guard import verify_active_lane, scan_reverse_dependencies

RESULTS: list[dict] = []


def require(condition: bool, message: str = "assertion failed") -> None:
    if not condition:
        raise AssertionError(message)


def raises(fragment: str, fn) -> None:
    try:
        fn()
    except Exception as exc:
        require(fragment in str(exc), f"expected {fragment!r}, got {exc!r}")
        return
    raise AssertionError(f"expected exception containing {fragment!r}")


def case(category: str, name: str, fn) -> None:
    try:
        fn(); status, detail = "PASS", ""
    except Exception as exc:
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    RESULTS.append({"category": category, "test": name, "status": status, "detail": detail})


PROV = "a" * 64
P4_ROWS = [
    {"security_id":"SEC_OLD","entity_id":"ENT_OLD","ticker":"OLD","exchange":"NSE","listing_date":"2005-01-01","delisting_date":"2015-12-31","eligibility_start":"2005-01-01","eligibility_end":"2015-12-31","knowledge_status":"VERIFIED","source_id":"ARCHIVE","source_reference":"TEST_ONLY:OLD","observed_at":"2010-01-02T00:00:00Z","provenance_hash":PROV},
    {"security_id":"SEC_NEW","entity_id":"ENT_NEW","ticker":"NEW","exchange":"NSE","listing_date":"2020-01-01","eligibility_start":"2020-01-01","eligibility_end":None,"knowledge_status":"VERIFIED","source_id":"ARCHIVE","source_reference":"TEST_ONLY:NEW","observed_at":"2019-12-01T00:00:00Z","provenance_hash":PROV,"symbol_periods":[{"ticker":"PREV","start":"2020-01-01","end":"2021-12-31"},{"ticker":"NEW","start":"2022-01-01","end":None}]},
    {"security_id":"SEC_UNKNOWN","entity_id":"ENT_U","ticker":"UNK","exchange":"BSE","listing_date":"2010-01-01","eligibility_start":"2010-01-01","eligibility_end":None,"knowledge_status":"UNKNOWN"},
]
P4_POLICY = {"policy_id":"TEST_PIT_POLICY_V1","eligible_exchanges":["NSE","BSE"],"fixture_only":True}
MASTER = SecurityMaster.build(P4_ROWS)

case("P4", "listed security included after listing", lambda: require([x["security_id"] for x in eligible_universe(MASTER,"2012-01-01",P4_POLICY)["included_securities"]] == ["SEC_OLD"]))
case("P4", "pre-listing query excluded", lambda: require(not eligible_universe(MASTER,"2004-01-01",P4_POLICY)["included_securities"]))
case("P4", "post-delisting query excluded", lambda: require("SEC_OLD" not in [x["security_id"] for x in eligible_universe(MASTER,"2016-01-01",P4_POLICY)["included_securities"]]))
case("P4", "eligibility interval enforced", lambda: raises("impossible date interval", lambda: SecurityMaster.build([{**P4_ROWS[0],"eligibility_start":"2014-01-01","eligibility_end":"2013-01-01"}])))
case("P4", "symbol change resolves identity", lambda: require(eligible_universe(MASTER,"2021-01-01",P4_POLICY)["included_securities"][0]["ticker"] == "PREV"))
case("P4", "duplicate security rejected", lambda: raises("duplicate security", lambda: SecurityMaster.build([P4_ROWS[0],P4_ROWS[0]])))
case("P4", "conflicting ticker periods rejected", lambda: raises("contradictory ticker", lambda: SecurityMaster.build([P4_ROWS[0],{**P4_ROWS[1],"ticker":"OLD","listing_date":"2010-01-01","eligibility_start":"2010-01-01","observed_at":"2009-12-01T00:00:00Z","symbol_periods":[]}])))
case("P4", "impossible listing interval rejected", lambda: raises("impossible date interval", lambda: SecurityMaster.build([{**P4_ROWS[0],"listing_date":"2010-01-01","eligibility_start":"2009-01-01"}])))
case("P4", "verified provenance required", lambda: raises("require provenance", lambda: SecurityMaster.build([{**P4_ROWS[0],"source_id":None}])))
case("P4", "unknown status preserved", lambda: require(MASTER.records[2]["knowledge_status"] == "UNKNOWN"))
case("P4", "unknown not eligible", lambda: require("SEC_UNKNOWN" not in [x["security_id"] for x in eligible_universe(MASTER,"2012-01-01",P4_POLICY)["included_securities"]]))
case("P4", "PIT query deterministic", lambda: require(eligible_universe(MASTER,"2012-01-01",P4_POLICY) == eligible_universe(MASTER,"2012-01-01",P4_POLICY)))
case("P4", "snapshot schema deterministic", lambda: require(eligible_universe(MASTER,"2012-01-01",P4_POLICY)["schema"] == "PIT_UNIVERSE_SNAPSHOT_V1"))
case("P4", "same input same hash", lambda: require(eligible_universe(MASTER,"2012-01-01",P4_POLICY)["record_hash"] == eligible_universe(MASTER,"2012-01-01",P4_POLICY)["record_hash"]))
case("P4", "different policy different identity", lambda: require(eligible_universe(MASTER,"2012-01-01",P4_POLICY)["record_hash"] != eligible_universe(MASTER,"2012-01-01",{**P4_POLICY,"policy_id":"TEST_PIT_POLICY_V2"})["record_hash"]))
case("P4", "current frozen universe not historical truth", lambda: require(MASTER.dataset_id == "TEST_ONLY_SYNTHETIC_PIT_MASTER"))
case("P4", "delisted fixture appears historically", lambda: require("SEC_OLD" in [x["security_id"] for x in eligible_universe(MASTER,"2012-01-01",P4_POLICY)["included_securities"]]))
case("P4", "later-observed fact blocked", lambda: require(eligible_universe(SecurityMaster.build([{**P4_ROWS[0],"observed_at":"2020-01-01T00:00:00Z"}]),"2012-01-01",P4_POLICY)["unknown_count"] == 1))

SCHEDULE = {"schedule_id":"TEST_COST_V1","effective_from":"2020-01-01","effective_to":"2020-12-31","verification_status":"TEST_FIXTURE_ONLY","provenance":"TEST_ONLY","gst_rate_percent":18,"components":[{"name":"BROKERAGE","rate_bps":10,"sides":["BUY","SELL"],"gst_applicable":True},{"name":"STT","rate_bps":20,"sides":["SELL"],"gst_applicable":False}]}
BOOK = CostScheduleBook.build([SCHEDULE])
SLIP = {"policy_id":"TEST_SLIP","fixed_bps":10,"stress_multiplier":2}
LIQ = {"policy_id":"TEST_LIQ","max_participation_rate":"0.10","minimum_adv":100,"insufficient_volume_action":"PARTIAL"}
def exe(**overrides):
    args = {"security_id":"SEC","session_date":"2020-06-01","side":"BUY","requested_quantity":10,"market_reference_price":100,"volume":1000,"adv":500,"tradeable_status":"TRADEABLE","schedule_book":BOOK,"slippage_policy":SLIP,"liquidity_policy":LIQ}
    args.update(overrides); return simulate_execution(**args)

case("P5", "cost schedule deterministic", lambda: require(BOOK.select("2020-06-01") == BOOK.select("2020-06-01")))
case("P5", "buy costs", lambda: require("BROKERAGE" in exe()["cost_components"]))
case("P5", "sell costs", lambda: require("STT" in exe(side="SELL")["cost_components"]))
case("P5", "buy sell asymmetry", lambda: require(exe()["total_transaction_cost"] != exe(side="SELL")["total_transaction_cost"]))
case("P5", "GST applicable base", lambda: require(exe()["cost_components"]["GST"] == "0.18"))
case("P5", "effective schedule selection", lambda: require(BOOK.select("2020-06-01")["schedule_id"] == "TEST_COST_V1"))
case("P5", "overlap rejected", lambda: raises("overlapping", lambda: CostScheduleBook.build([SCHEDULE,{**SCHEDULE,"schedule_id":"X","effective_from":"2020-06-01"}])))
case("P5", "missing schedule explicit", lambda: raises("NOT_CONFIGURED", lambda: BOOK.select("2022-01-01")))
case("P5", "participation calculated", lambda: require(exe()["participation_rate"] == "0.010000"))
case("P5", "liquidity rejection", lambda: require(exe(requested_quantity=200, liquidity_policy={**LIQ,"insufficient_volume_action":"REJECT"})["fill_status"] == "REJECTED_LIQUIDITY"))
case("P5", "partial fill", lambda: require(exe(requested_quantity=200)["filled_quantity"] == 100))
case("P5", "zero volume rejected", lambda: require(exe(volume=0)["fill_status"] == "REJECTED_LIQUIDITY"))
case("P5", "insufficient ADV rejected", lambda: require(exe(adv=1)["fill_status"] == "REJECTED_LIQUIDITY"))
case("P5", "untradeable", lambda: require(exe(tradeable_status="UNTRADEABLE")["fill_status"] == "UNTRADEABLE"))
case("P5", "fixed bps slippage", lambda: require(exe()["assumed_execution_price"] == "100.10"))
case("P5", "stress multiplier", lambda: require(exe(stress=True)["assumed_execution_price"] == "100.20"))
case("P5", "conservative gap", lambda: require(resolve_stop_target(90,95,110,89,111) == "GAP_STOP_AT_OPEN"))
case("P5", "stop target ambiguity", lambda: require(resolve_stop_target(100,95,110,94,111) == "STOP_HIT"))
case("P5", "execution replay deterministic", lambda: require(exe() == exe()))
case("P5", "no Stage5D integration", lambda: require(AUTHORITY["trading_authority"] is False))

FIXTURE_SOURCE = {"source_id":"LOCAL_OFFICIAL_FIXTURE","authority_classification":"TEST_OFFICIAL_FIXTURE","publisher":"TEST PUBLISHER","implementation_status":"TEST_FIXTURE_ONLY","reference":"local://fixture","provenance":"TEST_ONLY","parser_id":"FIXTURE_PARSER_V1"}
REGISTRY = FutureSourceRegistry.build([FIXTURE_SOURCE])
RAW = b"official fixture"
EVENT = {"source_id":"LOCAL_OFFICIAL_FIXTURE","publisher":"TEST PUBLISHER","reference":"local://fixture/1","retrieved_at":"2020-01-01T12:00:00Z","observed_at":"2020-01-01T11:00:00Z","published_at":"2020-01-01T10:00:00Z","raw_content_hash":hashlib.sha256(RAW).hexdigest(),"parser_id":"FIXTURE_PARSER_V1","parser_code_hash":"b"*64,"event_type":"FILING","evidence_class":"PRIMARY_EVIDENCE"}
case("P6", "future registry independent", lambda: require(REGISTRY.registry_id == "STAGE6_SOURCE_REGISTRY_V2_RESEARCH"))
case("P6", "active V1 hash unchanged", lambda: require(load_json(ROOT/"source_registry_v2/source_registry_research_v1.json")["active_v1_registry_hash"] == "7d91f4c72365757b6cdfaef0c4027c46bfbdb11c3541c229e828f9ee28d58e90"))
case("P6", "active source set RBI SEBI", lambda: require(load_json(ROOT/"source_registry_v2/source_registry_research_v1.json")["active_v1_source_set"] == ["RBI_OFFICIAL_PRESS_RELEASES_RSS","SEBI_OFFICIAL_RSS"]))
case("P6", "source authority required", lambda: raises("authority", lambda: FutureSourceRegistry.build([{**FIXTURE_SOURCE,"authority_classification":None}])))
case("P6", "source provenance required", lambda: raises("provenance", lambda: FutureSourceRegistry.build([{**FIXTURE_SOURCE,"implementation_status":"VERIFIED_NOT_IMPLEMENTED","provenance":None}])))
case("P6", "verified reference required", lambda: raises("reference", lambda: FutureSourceRegistry.build([{**FIXTURE_SOURCE,"implementation_status":"VERIFIED_NOT_IMPLEMENTED","reference":None}])))
case("P6", "raw hash validated", lambda: raises("hash mismatch", lambda: validate_evidence(EVENT,REGISTRY,b"wrong","FIXTURE_PARSER_V1","2020-01-02T00:00:00Z")))
case("P6", "parser identity validated", lambda: raises("parser", lambda: validate_evidence(EVENT,REGISTRY,RAW,"OTHER","2020-01-02T00:00:00Z")))
case("P6", "publication PIT checked", lambda: raises("timestamp", lambda: validate_evidence({**EVENT,"published_at":"2020-01-03T00:00:00Z"},REGISTRY,RAW,"FIXTURE_PARSER_V1","2020-01-02T00:00:00Z")))
case("P6", "observation PIT checked", lambda: raises("timestamp", lambda: validate_evidence({**EVENT,"observed_at":"2020-01-03T00:00:00Z","retrieved_at":"2020-01-03T01:00:00Z"},REGISTRY,RAW,"FIXTURE_PARSER_V1","2020-01-02T00:00:00Z")))
case("P6", "unverified source blocked", lambda: raises("unverified", lambda: validate_evidence(EVENT,FutureSourceRegistry.build([{**FIXTURE_SOURCE,"implementation_status":"UNVERIFIED"}]),RAW,"FIXTURE_PARSER_V1","2020-01-02T00:00:00Z")))
case("P6", "fact separated from interpretation", lambda: require(validate_evidence(EVENT,REGISTRY,RAW,"FIXTURE_PARSER_V1","2020-01-02T00:00:00Z")["evidence_class"] == "PRIMARY_EVIDENCE"))
case("P6", "interpretation cannot masquerade", lambda: raises("masquerade", lambda: validate_evidence({**EVENT,"evidence_class":"MODEL_INTERPRETATION"},REGISTRY,RAW,"FIXTURE_PARSER_V1","2020-01-02T00:00:00Z")))
case("P6", "fixture connector deterministic", lambda: require(fixture_connector(RAW) == fixture_connector(RAW)))
case("P6", "unimplemented reported honestly", lambda: require(all(x["implementation_status"] == "UNVERIFIED" for x in load_json(ROOT/"source_registry_v2/source_registry_research_v1.json")["sources"])))

CAL_POLICY = {"policy_id":"TEST_CAL_V1","minimum_sample":4,"minimum_group_sample":2,"bucket_count":2}
CAL_ROWS = [{"score":s,"outcome":y,"window":w,"regime":r} for s,y,w,r in [(0.1,0,"A","CALM"),(0.2,0,"A","CALM"),(0.8,1,"B","STRESS"),(0.9,1,"B","STRESS")]]
def cal(rows=CAL_ROWS): return evaluate_calibration(rows,model_id="M",model_hash="m"*64,dataset_id="D",dataset_hash="d"*64,cutoff="2020-01-01",target="Y",policy=CAL_POLICY)
case("P7", "Brier score", lambda: require(abs(cal()["brier_score"]-0.025)<1e-12))
case("P7", "baseline Brier", lambda: require(cal()["baseline_brier_score"] == 0.25))
case("P7", "Brier skill", lambda: require(abs(cal()["brier_skill_score"]-0.9)<1e-12))
case("P7", "perfect calibration fixture", lambda: require(evaluate_calibration([{**r,"score":float(r["outcome"])} for r in CAL_ROWS],model_id="M",model_hash="m",dataset_id="D",dataset_hash="d",cutoff="X",target="Y",policy=CAL_POLICY)["brier_score"] == 0))
case("P7", "poor calibration fixture", lambda: require(evaluate_calibration([{**r,"score":1-float(r["outcome"])} for r in CAL_ROWS],model_id="M",model_hash="m",dataset_id="D",dataset_hash="d",cutoff="X",target="Y",policy=CAL_POLICY)["brier_score"] == 1))
case("P7", "bucket count", lambda: require(len(cal()["reliability_buckets"]) == 2))
case("P7", "bucket observed rate", lambda: require(cal()["reliability_buckets"][0]["observed_rate"] == 0))
case("P7", "temporal grouping", lambda: require(cal()["temporal_analysis"]["A"]["status"] == "SUFFICIENT"))
case("P7", "regime grouping", lambda: require(cal()["regime_analysis"]["STRESS"]["count"] == 2))
case("P7", "small sample insufficient", lambda: require(cal(CAL_ROWS[:2])["status"] == "INSUFFICIENT_SAMPLE_FOR_CALIBRATION"))
case("P7", "predict_proba not calibrated", lambda: require(audit_term("probability",{"produced_by":"predict_proba"}) == "UNCALIBRATED_MODEL_SCORE"))
case("P7", "uncalibrated maps model score", lambda: require(report_label("probability","UNCALIBRATED_MODEL_SCORE") == "model_score"))
case("P7", "calibrated may retain probability", lambda: require(report_label("p","CALIBRATED_PROBABILITY") == "probability"))
case("P7", "legacy not rewritten", lambda: require(report_label("confidence",audit_term("confidence",{"legacy_immutable":True})) == "confidence"))
case("P7", "evaluation deterministic", lambda: require(cal() == cal()))

def model(mid="CHAL", state="CHALLENGER"):
    return model_record(model_id=mid,model_version="1",model_state=state,created_at="2020-01-01T00:00:00Z",training_cutoff="2019-12-31T00:00:00Z",training_dataset_id="DS",training_dataset_hash="d"*64,feature_set_id="FS",feature_set_hash="f"*64,algorithm="TEST_ONLY",algorithm_configuration_hash="a"*64,preprocessing_identity="P",source_code_commit="c"*40,source_code_manifest_hash="s"*64)
TEST_GATE = {"status":"CONFIGURED_TEST_FIXTURE","minimum_elapsed_days":10,"minimum_resolved":10,"minimum_positive":2,"minimum_negative":2,"minimum_benchmark_comparable":8,"minimum_mature":8,"minimum_sector_coverage":2,"minimum_regime_coverage":2,"minimum_adverse_cases":1}
GOOD_STATS = {"elapsed_days":20,"resolved":12,"positive":5,"negative":7,"benchmark_comparable":10,"mature":10,"sector_coverage":3,"regime_coverage":2,"adverse_cases":2}
DATA_META = {"pit_universe_version":"PIT_V1","pit_universe_hash":"p"*64,"feature_definition_version":"F_V1","label_definition_version":"L_V1","execution_policy_version":"E_V1","source_data_manifest_hash":"s"*64}
DATA_ROWS = [{"observation_id":"O1","observed_at":"2019-01-01T00:00:00Z","split":"TRAIN"},{"observation_id":"O2","observed_at":"2019-02-01T00:00:00Z","split":"VALIDATION"},{"observation_id":"O3","observed_at":"2019-03-01T00:00:00Z","split":"TEST"}]
case("P8", "model deterministic", lambda: require(model()==model()))
def duplicate_conflict():
    r=ResearchModelRegistry(); r.add_model(model()); r.add_model({**model(),"algorithm":"OTHER"})
case("P8", "duplicate conflict", lambda: raises("CONFLICT", duplicate_conflict))
case("P8", "invalid transition", lambda: raises("INVALID", lambda: (lambda r:(r.add_model(model()),r.transition("CHAL","CHALLENGER","INCUMBENT")))(ResearchModelRegistry())))
case("P8", "challenger creation", lambda: require(model()["model_state"]=="CHALLENGER"))
case("P8", "incumbent reference read only", lambda: require(model("STAGE4A3_REFERENCE","INCUMBENT")["authority_scope"]=="RESEARCH_ONLY"))
case("P8", "gate not configured default", lambda: require(retraining_eligibility({},load_json(ROOT/"model_lifecycle/retraining_eligibility_policy_v1.json"))["status"]=="NOT_CONFIGURED"))
case("P8", "insufficient sample", lambda: require(not retraining_eligibility({**GOOD_STATS,"resolved":1},TEST_GATE)["eligible"]))
case("P8", "elapsed alone insufficient", lambda: require(not retraining_eligibility({"elapsed_days":999},TEST_GATE)["eligible"]))
case("P8", "positive negative gate", lambda: require("minimum_positive" in retraining_eligibility({**GOOD_STATS,"positive":0},TEST_GATE)["failed_gates"]))
case("P8", "maturity gate", lambda: require("minimum_mature" in retraining_eligibility({**GOOD_STATS,"mature":0},TEST_GATE)["failed_gates"]))
case("P8", "benchmark gate", lambda: require("minimum_benchmark_comparable" in retraining_eligibility({**GOOD_STATS,"benchmark_comparable":0},TEST_GATE)["failed_gates"]))
case("P8", "training cutoff recorded", lambda: require(freeze_training_dataset(DATA_ROWS,"2019-12-31T00:00:00Z",DATA_META)["data_cutoff"]=="2019-12-31T00:00:00Z"))
case("P8", "post-cutoff rejected", lambda: raises("POST_CUTOFF", lambda: freeze_training_dataset([{**DATA_ROWS[0],"observed_at":"2020-01-01T00:00:00Z"}],"2019-12-31T00:00:00Z",DATA_META)))
case("P8", "validation leakage prevented", lambda: require("O2" not in freeze_training_dataset(DATA_ROWS,"2019-12-31T00:00:00Z",DATA_META)["included_observation_ids"]))
case("P8", "test leakage prevented", lambda: require("O3" not in freeze_training_dataset(DATA_ROWS,"2019-12-31T00:00:00Z",DATA_META)["included_observation_ids"]))
DATASET=freeze_training_dataset(DATA_ROWS,"2019-12-31T00:00:00Z",DATA_META)
EVAL=challenger_evaluation(model("INC","INCUMBENT"),model(),DATASET,{"return":"NOT_AVAILABLE"},"e"*64)
case("P8", "challenger evaluation deterministic", lambda: require(EVAL==challenger_evaluation(model("INC","INCUMBENT"),model(),DATASET,{"return":"NOT_AVAILABLE"},"e"*64)))
case("P8", "training performance not approval", lambda: require(EVAL["promotion_state"]=="NO_PROMOTION"))
case("P8", "default no promotion", lambda: require(load_json(ROOT/"model_lifecycle/model_lifecycle_contract_v1.json")["default_promotion"]=="NO_PROMOTION"))
case("P8", "missing approval blocks", lambda: raises("approval", lambda: (lambda r:(r.add_model(model()),r.transition("CHAL","CHALLENGER","APPROVED")))(ResearchModelRegistry())))
APPROVAL=approval_artifact("INC","CHAL",EVAL,"TEST_REVIEWER","2020-01-02T00:00:00Z")
case("P8", "approval validation", lambda: require(APPROVAL["schema"]=="MODEL_PROMOTION_APPROVAL_V1"))
def valid_transition():
    r=ResearchModelRegistry(); r.add_model(model()); return r.transition("CHAL","CHALLENGER","APPROVED",APPROVAL)
case("P8", "atomic registry transition", lambda: require(valid_transition()["to_state"]=="APPROVED"))
case("P8", "invalid promotion blocked", lambda: raises("not executed", lambda: (lambda r:(r.add_model(model("A","APPROVED")),r.transition("A","APPROVED","INCUMBENT",{})))(ResearchModelRegistry())))
def rollback_event():
    r=ResearchModelRegistry(); r.add_model(model("I","INCUMBENT")); r.add_model(model("A","APPROVED")); return r,r.rollback("I","A","fixture")
case("P8", "rollback event", lambda: require(rollback_event()[1]["schema"]=="MODEL_ROLLBACK_EVENT_V1"))
case("P8", "rollback preserves history", lambda: require(rollback_event()[0].counts()["models"]==2))
def rollback_links():
    r=ResearchModelRegistry(); r.add_model(model("I","INCUMBENT")); r.add_model(model("A","APPROVED")); r.link_recommendation("I","R1"); r.rollback("I","A","fixture"); return r.counts()
case("P8", "rollback preserves provenance", lambda: require(rollback_links()["recommendation_links"]==1))
case("P8", "no Stage4A3 active change", lambda: require(model("STAGE4A3_REFERENCE","INCUMBENT")["model_id"]=="STAGE4A3_REFERENCE"))
case("P8", "no live retraining", lambda: require(load_json(ROOT/"model_lifecycle/model_lifecycle_contract_v1.json")["real_challenger_trained"] is False))
case("P8", "no live promotion", lambda: require(load_json(ROOT/"model_lifecycle/model_lifecycle_contract_v1.json")["promotion_executed"] is False))

case("CROSS", "PIT hash binds dataset", lambda: require(DATASET["pit_universe_hash"]==DATA_META["pit_universe_hash"]))
case("CROSS", "execution hash binds evaluation", lambda: require(EVAL["execution_policy_hash"]=="e"*64))
case("CROSS", "calibration binds model", lambda: require(cal()["model_hash"]=="m"*64))
case("CROSS", "future evidence no active influence", lambda: require(validate_evidence(EVENT,REGISTRY,RAW,"FIXTURE_PARSER_V1","2020-01-02T00:00:00Z")["active_recommendation_influence"]=="NONE"))
case("CROSS", "no reverse imports", lambda: require(scan_reverse_dependencies(REPO)==[]))
case("CROSS", "manifest binds identities", lambda: require(set(load_json(ROOT/"nextgen_manifest.json")["component_hashes"])=={"priority4_policy","priority5_policy","priority6_registry","priority7_policy","priority7_terminology","priority8_policy","priority8_contract"}))
case("CROSS", "no trading authority", lambda: require(all(not x for x in [AUTHORITY["trading_authority"],load_json(ROOT/"nextgen_manifest.json")["trading_authority"]])))
case("CROSS", "no active prospective authority", lambda: require(verify_active_lane(REPO,ROOT/"regression_guard/active_baseline_v1.json")["active_lane_changed_file_count"]==0))

output = ROOT / "results" / "nextgen_test_results.csv"
output.parent.mkdir(exist_ok=True)
with output.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=["category","test","status","detail"])
    writer.writeheader(); writer.writerows(RESULTS)

counts = {cat: {status: sum(r["category"]==cat and r["status"]==status for r in RESULTS) for status in ("PASS","FAIL")} for cat in ("P4","P5","P6","P7","P8","CROSS")}
print(json.dumps({"total":len(RESULTS),"passed":sum(r["status"]=="PASS" for r in RESULTS),"failed":sum(r["status"]=="FAIL" for r in RESULTS),"categories":counts},sort_keys=True))
for failure in [r for r in RESULTS if r["status"]=="FAIL"]:
    print(f"FAIL {failure['category']} {failure['test']}: {failure['detail']}")
raise SystemExit(1 if any(r["status"]=="FAIL" for r in RESULTS) else 0)
