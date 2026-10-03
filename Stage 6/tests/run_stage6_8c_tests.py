from __future__ import annotations

import csv
import json
import sqlite3
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from stage6_ingestion.canonical import canonical_hash, canonical_json, without
from stage6_prospective_validation.activation import verify_activation_record
from stage6_prospective_validation.checkpoint_builder import (
    MARKET_CLASSIFICATION, SECTOR_UNAVAILABLE, build_checkpoint, derive_final_exit, determine_due_checkpoints,
)
from stage6_prospective_validation.cohort_guard import (
    FEATURE_HASHES, MODEL_BUNDLE_HASH, SOURCE_PACKAGE_HASH, _validate_facts, verify_active_cohort,
)
from stage6_prospective_validation.control_reader import Stage5DControlReader, payload_sha256
from stage6_prospective_validation.errors import ProspectiveConflict, ProspectiveIntegrityFailure, Stage6ProspectiveError
from stage6_prospective_validation.observation_config import *
from stage6_prospective_validation.observation_store import ProspectiveObservationStore, TABLES, validate_observation_store_path
from stage6_prospective_validation.operations_config import *
from stage6_prospective_validation.policy import *
from stage6_prospective_validation.recommendation_envelope import build_recommendation_envelope, validate_envelope
from stage6_prospective_validation import observation_config as oc
from stage6_prospective_validation import operations_config as ops
from stage6_prospective_validation import cohort_guard as cg

OUT = ROOT / "results/stage6_8c_test_results.csv"
CASES = []
CTX = {}
def case(group, name, fn): CASES.append((group, name, fn))
def require(value):
    if not value: raise AssertionError("requirement failed")
def expect(error, fn):
    try: fn()
    except error: return True
    raise AssertionError(f"expected {error.__name__}")


def make_activation(path):
    value = {"schema_version": ACTIVATION_SCHEMA, "activation_id": "", "protocol_id": PROTOCOL_ID,
             "protocol_hash": EXPECTED_PROTOCOL_HASH, "policy_id": POLICY_ID, "policy_hash": EXPECTED_POLICY_HASH,
             "contract_id": CONTRACT_VERSION, "contract_hash": EXPECTED_CONTRACT_HASH,
             "stage6_7_closure_baseline": BASELINE, "stage6_8a_activation_head": "f"*40, "branch": BRANCH,
             "stage5d5_control_tag": CONTROL_TAG, "stage5d5_control_commit": CONTROL_COMMIT,
             "stage5d_subtree_verification": "PASS", "stage6_7b_schema": SHADOW_SCHEMA,
             "stage6_7b_policy_id": SHADOW_POLICY, "stage6_7b_policy_hash": SHADOW_POLICY_HASH,
             "stage6_7b_contract_id": SHADOW_CONTRACT, "stage6_7b_contract_hash": SHADOW_CONTRACT_HASH,
             "stage6_7b_decision_engine_version": SHADOW_ENGINE, "stage6_7b_decision_code_hash": SHADOW_CODE_HASH,
             "activated_at_utc": "2026-09-30T10:00:00Z", "activation_date_ist": "2026-09-30",
             "minimum_completed_control_sessions": 20, "performance_based_early_stopping": "PROHIBITED",
             "authority": AUTHORITY, "trading_authority": False, "record_hash": ""}
    value["activation_id"] = "S6PROSACT_" + canonical_hash(without(value, "activation_id", "record_hash"))[:24]
    value["record_hash"] = canonical_hash(without(value, "record_hash"))
    path.write_text(json.dumps(value, sort_keys=True, indent=2)+"\n", encoding="utf-8")
    return value


def create_control(path):
    c = sqlite3.connect(path)
    c.executescript("""
CREATE TABLE ledger_meta(singleton INTEGER PRIMARY KEY,schema_version TEXT,database_id TEXT,created_at_utc TEXT);
CREATE TABLE stage5d5_meta(singleton INTEGER PRIMARY KEY,schema_version TEXT);
CREATE TABLE stage5d5_live_runs(run_id TEXT PRIMARY KEY,market_session_date TEXT UNIQUE,run_started_utc TEXT,run_completed_utc TEXT,data_provider TEXT,market_data_hash TEXT,candidate_input_hash TEXT,candidate_count INTEGER,stage4a3_snapshot_id TEXT,allocation_run_id TEXT,management_session_run_id TEXT,recommendation_count INTEGER,news_status TEXT,canonical_payload_json TEXT,payload_sha256 TEXT);
CREATE TABLE allocation_runs(allocation_run_id TEXT PRIMARY KEY,decision_date TEXT,profile_version INTEGER,capital_ceiling_inr TEXT,selected_horizon TEXT,management_policy_id TEXT,horizon_session_limit INTEGER,portfolio_summary_json TEXT,portfolio_snapshot_json TEXT,recommendation_count INTEGER,actionable_recommendation_count INTEGER,canonical_payload_json TEXT,payload_sha256 TEXT,persisted_at_utc TEXT);
CREATE TABLE recommendations(recommendation_id TEXT PRIMARY KEY,allocation_run_id TEXT,signal_id TEXT,ticker TEXT,signal_date TEXT,decision_date TEXT,portfolio_action_status TEXT,recommended_quantity INTEGER,selected_horizon TEXT,persisted_at_utc TEXT,canonical_payload_json TEXT,payload_sha256 TEXT);
CREATE TABLE recommendation_events(event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE,recommendation_id TEXT,event_type TEXT,effective_date TEXT,recorded_at_utc TEXT,payload_json TEXT,payload_sha256 TEXT,idempotency_key TEXT UNIQUE);
CREATE TABLE user_transactions(transaction_sequence INTEGER PRIMARY KEY AUTOINCREMENT,transaction_id TEXT UNIQUE,idempotency_key TEXT UNIQUE,ticker TEXT,trade_date TEXT,side TEXT,quantity INTEGER,price_inr TEXT,fees_inr TEXT,recommendation_id TEXT,signal_id TEXT,external_reference TEXT,notes TEXT,canonical_payload_json TEXT,payload_sha256 TEXT,recorded_at_utc TEXT);
CREATE TABLE transaction_voids(void_sequence INTEGER PRIMARY KEY AUTOINCREMENT,void_id TEXT UNIQUE,transaction_id TEXT,idempotency_key TEXT UNIQUE,reason TEXT,voided_at_utc TEXT,canonical_payload_json TEXT,payload_sha256 TEXT);
""")
    c.execute("INSERT INTO ledger_meta VALUES(1,'STAGE5D2_SCHEMA_V1','CONTROL_DB','2026-09-30T00:00:00Z')")
    c.execute("INSERT INTO stage5d5_meta VALUES(1,?)", (CONTROL_SCHEMA,))
    rec = {"recommendation_id":"REC1","allocation_run_id":"ALLOC1","signal_id":"SIG1","profile_version":1,
           "ticker":"AAA.NS","signal_date":"2026-10-05","decision_date":"2026-10-05","deterministic_signal":"BUY",
           "entry_low":"98","entry_high":"102","sizing_entry_price":"100","stop":"95","target_1":"110","target_2":"120",
           "recommended_quantity":10,"estimated_purchase_value_inr":"1000","risk_budget_inr":"50","risk_per_share_inr":"5",
           "selected_horizon":"SWING","market_regime":"BULL","portfolio_action_status":"ACTIONABLE_BUY",
           "horizon_status":"SUPPORTED","plain_language_reason":"Frozen deterministic signal."}
    portfolio = {"cash_inr":"10000","open_positions":[],"profile_version":1}
    summary = {"decision_date":"2026-10-05","profile_version":1,"capital_ceiling_inr":"10000","selected_horizon":"SWING"}
    allocation = {"allocation_run_id":"ALLOC1","decision_date":"2026-10-05","portfolio_summary":summary,"portfolio_snapshot":portfolio,"recommendations":[rec]}
    atext = canonical_json(allocation); rtext = canonical_json(rec)
    c.execute("INSERT INTO allocation_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("ALLOC1","2026-10-05",1,"10000","SWING",None,None,canonical_json(summary),canonical_json(portfolio),1,1,atext,payload_sha256(atext),"2026-10-05T10:30:00Z"))
    c.execute("INSERT INTO recommendations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("REC1","ALLOC1","SIG1","AAA.NS","2026-10-05","2026-10-05","ACTIONABLE_BUY",10,"SWING","2026-10-05T10:30:00Z",rtext,payload_sha256(rtext)))
    run = {"run_id":"RUN1","market_session_date":"2026-10-05","run_started_utc":"2026-10-05T08:00:00Z","run_completed_utc":"2026-10-05T09:00:00Z","data_provider":"FIXTURE","market_data_hash":"MARKET","candidate_input_hash":"CANDIDATE","candidate_count":1,"stage4a3_snapshot_id":"S4A3_1","allocation_run_id":"ALLOC1","management_session_run_id":"MGMT1","recommendation_count":1,"news_status":"AVAILABLE"}
    text = canonical_json(run); c.execute("INSERT INTO stage5d5_live_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (*[run[k] for k in ("run_id","market_session_date","run_started_utc","run_completed_utc","data_provider","market_data_hash","candidate_input_hash","candidate_count","stage4a3_snapshot_id","allocation_run_id","management_session_run_id","recommendation_count","news_status")],text,payload_sha256(text)))
    event={"recommendation_id":"REC1","event_type":"PENDING_ENTRY","effective_date":"2026-10-06"}; et=canonical_json(event)
    c.execute("INSERT INTO recommendation_events(event_id,recommendation_id,event_type,effective_date,recorded_at_utc,payload_json,payload_sha256,idempotency_key) VALUES('EV1','REC1','PENDING_ENTRY','2026-10-06','2026-10-05T11:00:00Z',?,?,?)", (et,payload_sha256(et),"EVKEY"))
    c.commit(); c.close(); return rec


def create_prospective(path, rec, activation):
    c=sqlite3.connect(path); c.executescript("CREATE TABLE prospective_cases(case_id TEXT,recommendation_id TEXT,canonical_json TEXT);CREATE TABLE prospective_control_recommendations(recommendation_id TEXT,payload_sha256 TEXT,canonical_payload_json TEXT);")
    case={"schema_version":"STAGE6_PROSPECTIVE_CASE_ENROLLMENT_V1","case_id":"CASE1","recommendation_id":"REC1","record_hash":"","activation_binding":{"record_id":activation["activation_id"],"record_hash":activation["record_hash"]}}; case["record_hash"]=canonical_hash(without(case,"record_hash"))
    text=canonical_json(rec); c.execute("INSERT INTO prospective_cases VALUES(?,?,?)", ("CASE1","REC1",canonical_json(case))); c.execute("INSERT INTO prospective_control_recommendations VALUES(?,?,?)", ("REC1",payload_sha256(text),text)); c.commit(); c.close()


def snapshot():
    value={"snapshot_id":"S4A3_1","snapshot_content_hash":"","model_bundle_hash":MODEL_BUNDLE_HASH,"source_package_hash":SOURCE_PACKAGE_HASH,"protocol_version":"STAGE4A3A_V1","protocol_tag":"stage4a3-prospective-shadow-protocol-baseline","feature_set":"FS3_FULL_SIGNAL_STATE","feature_hash":FEATURE_HASHES[0],"feature_row":{"x":"1"},"feature_row_hash":canonical_hash({"x":"1"}),"candidate_input_hash":"CANDIDATE","market_data_manifest_id":"MD1","market_data_manifest_hash":"MDHASH","signal_id":"SIG1","ticker":"AAA.NS","candidate_row":{"signal_id":"SIG1","ticker":"AAA.NS"}}
    value["snapshot_content_hash"]=canonical_hash(without(value,"snapshot_content_hash")); return value


def rows(count, sector=False):
    result=[]; day=date(2026,10,5); n=0
    while len(result)<count+1:
        if day.weekday()<5 and day.isoformat()!="2026-10-09":
            price=100+n; item={"session_date":day.isoformat(),"observed_at_utc":day.isoformat()+"T10:00:00Z","stock_close":str(price),"stock_high":str(price+2),"stock_low":str(price-2),"nifty_close":str(20000+10*n)}
            if sector:item.update({"sector_benchmark_id":"NIFTY_IT","sector_close":str(30000+20*n)})
            result.append(item); n+=1
        day+=timedelta(days=1)
    return result


def manifest(items):
    value={"manifest_id":"MD_"+str(len(items)),"classification":MARKET_CLASSIFICATION,"observations":items,"manifest_hash":""}; value["manifest_hash"]=canonical_hash(without(value,"manifest_hash")); return value


def setup(temp):
    root=Path(temp.name); activation_path=root/"activation.json"; activation=make_activation(activation_path)
    cohort=verify_active_cohort(REPO,activation_path)
    control=root/"control.sqlite3"; rec=create_control(control); prospective=root/"prospective.sqlite3"; create_prospective(prospective,rec,activation)
    env=build_recommendation_envelope(control_database=control,prospective_database=prospective,recommendation_id="REC1",cohort_fingerprint=cohort,stage4a3_snapshot=snapshot())
    store=ProspectiveObservationStore(root/"observation.sqlite3",REPO,cohort,allow_test_runtime=True); store.persist_envelope(env)
    m5=manifest(rows(5)); cp5=build_checkpoint(envelope=env,checkpoint_type="D+5",checkpoint_cutoff_utc=m5["observations"][-1]["session_date"]+"T11:00:00Z",market_data_manifest=m5)
    CTX.update(locals())


# Cohort identity and drift
case("COHORT","correct frozen identities",lambda:require(CTX["cohort"]["stage5d_subtree_verification"]=="PASS"))
case("COHORT","deterministic fingerprint",lambda:require(verify_active_cohort(REPO,CTX["activation_path"])==CTX["cohort"]))
for key in ("model_bundle_hash","feature_hashes","stage5d5_control_commit","protocol_hash","operations_policy_hash","operations_contract_hash","source_registry_hash","operational_source_set"):
    case("COHORT_DRIFT",key,lambda key=key:expect(ProspectiveIntegrityFailure,lambda:_validate_facts({**{"protocol_hash":EXPECTED_PROTOCOL_HASH,"policy_hash":EXPECTED_POLICY_HASH,"enrollment_contract_hash":EXPECTED_CONTRACT_HASH,"operations_policy_hash":ops.EXPECTED_POLICY_HASH,"operations_contract_hash":ops.EXPECTED_CONTRACT_HASH,"stage5d5_control_commit":CONTROL_COMMIT,"stage5d5_control_tag":CONTROL_TAG,"model_bundle_hash":MODEL_BUNDLE_HASH,"source_package_hash":SOURCE_PACKAGE_HASH,"feature_hashes":list(FEATURE_HASHES),"source_registry_id":SOURCE_REGISTRY_V2_ID,"source_registry_hash":SOURCE_REGISTRY_V2_HASH,"entity_registry_id":ENTITY_REGISTRY_V2_ID,"entity_registry_hash":ENTITY_REGISTRY_V2_HASH,"operational_source_set":list(OPERATIONAL_SOURCES)},key:"BAD"})))
case("COHORT","activation tamper",lambda:expect(ProspectiveIntegrityFailure,CTX["tamper_activation"]))
case("COHORT","Stage5D tree drift",lambda:expect(ProspectiveIntegrityFailure,CTX["stage5d_drift"]))
case("COHORT","guard no repository mutation",lambda:require(CTX["status_before"]==CTX["status_after"]))

# Envelope
case("ENVELOPE","valid",lambda:require(validate_envelope(CTX["env"])["recommendation_id"]=="REC1"))
case("ENVELOPE","deterministic",lambda:require(CTX["rebuild_env"]==CTX["env"]))
case("ENVELOPE","different dependency different identity",lambda:require(CTX["different_env_id"]!=CTX["env"]["envelope_id"]))
case("ENVELOPE","query only",lambda:require(CTX["env"]["source_read_modes"]["stage5d"]=="READ_ONLY_QUERY_ONLY"))
case("ENVELOPE","recommendation hash",lambda:require(CTX["env"]["recommendation_binding"]["record_hash"]==payload_sha256(canonical_json(CTX["rec"]))))
case("ENVELOPE","allocation binding",lambda:require(CTX["env"]["portfolio_snapshot"]["cash_inr"]=="10000"))
case("ENVELOPE","stage4a3 model binding",lambda:require(CTX["env"]["stage4a3"]["model_bundle_hash"]==MODEL_BUNDLE_HASH))
case("ENVELOPE","stage4a3 feature binding",lambda:require(CTX["env"]["stage4a3"]["feature_hash"] in FEATURE_HASHES))
case("ENVELOPE","missing context explicit",lambda:require(CTX["env"]["stage6_creation_context"]["availability"]=="NOT_AVAILABLE_AT_RECOMMENDATION_CREATION"))
for key in ("future_return","realized_pnl","exit_price","exit_reason","mfe","mae","checkpoint_outcome","d+5_result","d+20_result","d+60_result","final_outcome","target_hit_result","realized_holding_return"):
    case("ENVELOPE_LEAK",key,lambda key=key:expect(Stage6ProspectiveError,lambda:CTX["leaky_env"](key)))
case("ENVELOPE","target fields allowed",lambda:require(CTX["env"]["recommendation"]["target_1"]=="110"))
case("ENVELOPE","future context rejected",lambda:expect(Stage6ProspectiveError,CTX["future_context"]))
case("ENVELOPE","store exact replay",lambda:require(CTX["store"].persist_envelope(CTX["env"])["status"]=="IDEMPOTENT_SUCCESS"))
case("ENVELOPE","conflicting replay",lambda:expect(ProspectiveConflict,CTX["envelope_conflict"]))
case("ENVELOPE","update blocked",lambda:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute("UPDATE recommendation_audit_envelopes SET record_hash='x'")))
case("ENVELOPE","delete blocked",lambda:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute("DELETE FROM recommendation_audit_envelopes")))

# Checkpoints and calculations
case("SESSION","weekend skipped",lambda:require(CTX["cp5"]["checkpoint_date"]=="2026-10-13"))
case("SESSION","holiday skipped",lambda:require("2026-10-09" not in [x["session_date"] for x in CTX["m5"]["observations"]]))
case("SESSION","D+5 ordinal",lambda:require(CTX["cp5"]["trading_session_ordinal"]==5))
case("SESSION","D+20 ordinal",lambda:require(CTX["cp20"]["trading_session_ordinal"]==20))
case("SESSION","D+60 ordinal",lambda:require(CTX["cp60"]["trading_session_ordinal"]==60))
case("SESSION","anchor not D+1",lambda:require(CTX["cp5"]["return_anchor_date"]=="2026-10-05" and CTX["cp5"]["checkpoint_date"]!=CTX["cp5"]["return_anchor_date"]))
case("SESSION","due D+5",lambda:require([x["checkpoint_type"] for x in determine_due_checkpoints(decision_date="2026-10-05",completed_session_dates=[x["session_date"] for x in rows(5)[1:]])]==["D+5"]))
case("SESSION","existing checkpoint not due",lambda:require(determine_due_checkpoints(decision_date="2026-10-05",completed_session_dates=[x["session_date"] for x in rows(5)[1:]],existing_checkpoint_types=("D+5",))==[]))
case("SESSION","final exit due separately",lambda:require(determine_due_checkpoints(decision_date="2026-10-05",completed_session_dates=[],final_exit_completed=True)[0]["checkpoint_type"]=="FINAL_EXIT"))
case("SESSION","unsorted completion sequence rejected",lambda:expect(Stage6ProspectiveError,lambda:determine_due_checkpoints(decision_date="2026-10-05",completed_session_dates=["2026-10-07","2026-10-06"])))
case("SESSION","missing stock target fails",lambda:expect(Stage6ProspectiveError,CTX["missing_stock"]))
case("RETURN","stock formula",lambda:require(CTX["cp5"]["stock_return"]=="0.05"))
case("RETURN","nifty formula",lambda:require(CTX["cp5"]["nifty_return"]=="0.0025"))
case("RETURN","stock minus nifty",lambda:require(CTX["cp5"]["stock_minus_nifty"]=="0.0475"))
case("RETURN","sector formula",lambda:require(abs(Decimal(CTX["cp_sector"]["sector_return"])-(Decimal(30100)/Decimal(30000)-1))<Decimal("1e-27")))
case("RETURN","stock minus sector",lambda:require(abs(Decimal(CTX["cp_sector"]["stock_minus_sector"])-(Decimal("0.05")-(Decimal(30100)/Decimal(30000)-1)))<Decimal("1e-27")))
case("RETURN","sector unavailable status",lambda:require(CTX["cp5"]["sector_benchmark_status"]==SECTOR_UNAVAILABLE))
case("RETURN","sector unavailable null",lambda:require(CTX["cp5"]["sector_return"] is None and CTX["cp5"]["sector_benchmark_identifier"] is None))
case("RETURN","MFE",lambda:require(CTX["cp5"]["mfe"]=="0.07"))
case("RETURN","MAE",lambda:require(CTX["cp5"]["mae"]=="-0.02"))
case("RETURN","drawdown",lambda:require(abs(Decimal(CTX["cp_drawdown"]["maximum_drawdown"])-(Decimal(103)/Decimal(120)-1))<Decimal("1e-27")))
case("PIT","future row rejected",lambda:expect(Stage6ProspectiveError,CTX["future_row"]))
case("PIT","future observed timestamp rejected",lambda:expect(Stage6ProspectiveError,CTX["future_observed"]))
case("PIT","NIFTY missing fails",lambda:expect(Stage6ProspectiveError,CTX["missing_nifty"]))
case("PIT","market classification",lambda:require(CTX["cp5"]["market_data_classification"]==MARKET_CLASSIFICATION))
case("PIT","recommendation influence none",lambda:require(CTX["cp5"]["recommendation_influence"]=="NONE"))

# Immutability / thesis / lifecycle / boundary
case("CHECKPOINT","create",lambda:require(CTX["store"].persist_checkpoint(CTX["cp5"])["status"]=="CREATED"))
case("CHECKPOINT","exact replay",lambda:require(CTX["store"].persist_checkpoint(CTX["cp5"])["status"]=="IDEMPOTENT_SUCCESS"))
case("CHECKPOINT","conflict",lambda:expect(ProspectiveConflict,CTX["checkpoint_conflict"]))
case("CHECKPOINT","update blocked",lambda:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute("UPDATE benchmark_checkpoints SET record_hash='x'")))
case("CHECKPOINT","delete blocked",lambda:expect(sqlite3.DatabaseError,lambda:CTX["store"].connection.execute("DELETE FROM benchmark_checkpoints")))
case("CHECKPOINT","recommendation unchanged",lambda:require(CTX["control_hash_before"]==CTX["control_hash_after"]()))
case("CHECKPOINT","envelope unchanged",lambda:require(CTX["env"]==json.loads(CTX["store"].connection.execute("SELECT canonical_json FROM recommendation_audit_envelopes").fetchone()[0])))
case("CHECKPOINT","prospective unchanged",lambda:require(CTX["prospective_hash_before"]==CTX["prospective_hash_after"]()))
case("CHECKPOINT","different horizon appends",lambda:require(CTX["store"].persist_checkpoint(CTX["cp20"])["status"]=="CREATED"))
case("THESIS","as-of cutoff",lambda:require(CTX["cp_thesis"]["current_thesis_state"]=="VALID"))
case("THESIS","later record excluded",lambda:require(CTX["cp_thesis"]["original_thesis_validity_state"]=="VALID"))
case("THESIS","missing explicit",lambda:require(CTX["cp5"]["current_thesis_state"]=="NOT_AVAILABLE"))
case("LIFECYCLE","valid final exit",lambda:require(CTX["final_exit"]["exit_status"]=="FINAL_EXIT_COMPLETED"))
case("LIFECYCLE","final checkpoint",lambda:require(CTX["cp_exit"]["checkpoint_type"]=="FINAL_EXIT"))
case("LIFECYCLE","voided exit rejected",lambda:expect(Stage6ProspectiveError,CTX["voided_exit"]))
case("LIFECYCLE","no fill rejected",lambda:expect(Stage6ProspectiveError,CTX["no_fill_exit"]))
case("STORE","integrity",lambda:require(CTX["store"].integrity_check()["result"]=="PASS"))
case("STORE","research path rejected",lambda:expect(Stage6ProspectiveError,lambda:validate_observation_store_path(REPO/"Stage 4A.3/results/x.sqlite3",REPO)))
case("STORE","fixture path rejected",lambda:expect(Stage6ProspectiveError,lambda:validate_observation_store_path(REPO/"Stage 6/tests/fixtures/x.sqlite3",REPO)))
case("STORE","approved path",lambda:require(validate_observation_store_path(REPO/"Stage 6/runtime/prospective_validation/prospective_observation.sqlite3",REPO).name=="prospective_observation.sqlite3"))
case("STORE","authority",lambda:require(CTX["store"].integrity_check()["authority"]=="SHADOW_ONLY"))
case("STORE","trading false",lambda:require(CTX["store"].integrity_check()["trading_authority"] is False))
case("CONFIG","policy hash",lambda:require(load_observation_policy()[2]==EXPECTED_POLICY_HASH_8C))
case("CONFIG","contract hash",lambda:require(load_observation_contract()[2]==EXPECTED_CONTRACT_HASH_8C))


def enrich():
    # aliases avoid the intentionally overlapping 6.8A/6.8B imported names
    global EXPECTED_POLICY_HASH_8C, EXPECTED_CONTRACT_HASH_8C
    EXPECTED_POLICY_HASH_8C=oc.EXPECTED_POLICY_HASH; EXPECTED_CONTRACT_HASH_8C=oc.EXPECTED_CONTRACT_HASH
    activation=CTX["activation"]
    bad=deepcopy(activation); bad["activation_date_ist"]="2026-09-29"; Path(CTX["root"] / "bad_activation.json").write_text(json.dumps(bad),encoding="utf-8")
    CTX["tamper_activation"]=lambda:verify_activation_record(CTX["root"] / "bad_activation.json")
    class GitResult:
        def __init__(self,stdout="",returncode=0): self.stdout=stdout; self.returncode=returncode
    def fake_git(repo,*args,check=True):
        if args[:3]==("rev-list","-n","1"): return GitResult(CONTROL_COMMIT+"\n")
        if args and args[0]=="status": return GitResult("")
        if args and args[0]=="diff": return GitResult("",1)
        return GitResult("")
    def stage5d_drift():
        with patch.object(cg,"_verify_stage4a3",lambda repo:None),patch.object(cg,"_git",fake_git): return verify_active_cohort(REPO,CTX["activation_path"])
    CTX["stage5d_drift"]=stage5d_drift
    git=["git",f"--git-dir={REPO/'_git'}",f"--work-tree={REPO}"]; CTX["status_before"]=subprocess.check_output([*git,"status","--porcelain"],text=True); verify_active_cohort(REPO,CTX["activation_path"]); CTX["status_after"]=subprocess.check_output([*git,"status","--porcelain"],text=True)
    CTX["rebuild_env"]=build_recommendation_envelope(control_database=CTX["control"],prospective_database=CTX["prospective"],recommendation_id="REC1",cohort_fingerprint=CTX["cohort"],stage4a3_snapshot=snapshot())
    other=deepcopy(CTX["env"]); other["recommendation_binding"]["record_hash"]="b"*64; other["envelope_id"]=""; other["record_hash"]=""; other["envelope_id"]="S6PROSENV_"+canonical_hash(without(other,"envelope_id","record_hash"))[:24]; other["record_hash"]=canonical_hash(without(other,"record_hash")); CTX["different_env_id"]=other["envelope_id"]
    def leaky(key): bad=deepcopy(CTX["env"]); bad["stage6_creation_context"][key]="x"; return validate_envelope(bad)
    CTX["leaky_env"]=leaky
    CTX["future_context"]=lambda:build_recommendation_envelope(control_database=CTX["control"],prospective_database=CTX["prospective"],recommendation_id="REC1",cohort_fingerprint=CTX["cohort"],stage4a3_snapshot=snapshot(),creation_context={"recorded_at_utc":"2026-10-06T10:30:00Z"})
    def env_conflict():
        bad=deepcopy(CTX["env"]); bad["stage6_creation_context"]={"availability":"AVAILABLE","recorded_at_utc":"2026-10-05T10:00:00Z","known_risks":[],"invalidation_conditions":[]}; bad["envelope_id"]=""; bad["record_hash"]=""; bad["envelope_id"]="S6PROSENV_"+canonical_hash(without(bad,"envelope_id","record_hash"))[:24]; bad["record_hash"]=canonical_hash(without(bad,"record_hash")); return CTX["store"].persist_envelope(bad)
    CTX["envelope_conflict"]=env_conflict
    def cp(n,sector=False,thesis=()):
        m=manifest(rows(n,sector)); return build_checkpoint(envelope=CTX["env"],checkpoint_type=f"D+{n}",checkpoint_cutoff_utc=m["observations"][-1]["session_date"]+"T11:00:00Z",market_data_manifest=m,thesis_records=thesis)
    CTX["cp20"]=cp(20); CTX["cp60"]=cp(60); CTX["cp_sector"]=cp(5,True)
    dd=rows(5); dd[1]["stock_close"]="120"; dd[2]["stock_close"]="108"; md=manifest(dd); CTX["cp_drawdown"]=build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=dd[-1]["session_date"]+"T11:00:00Z",market_data_manifest=md)
    later={"recorded_at_utc":"2026-10-20T12:00:00Z","current_thesis_state":"INVALIDATED","original_thesis_validity_state":"INVALIDATED","binding":{"record_type":"THESIS","record_id":"T2","record_hash":"H2"}}
    early={"recorded_at_utc":"2026-10-10T09:00:00Z","current_thesis_state":"VALID","original_thesis_validity_state":"VALID","binding":{"record_type":"THESIS","record_id":"T1","record_hash":"H1"}}
    CTX["cp_thesis"]=cp(5,False,[later,early])
    def missing_stock(): x=rows(5); x[-1]["stock_close"]=None; m=manifest(x); return build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=x[-1]["session_date"]+"T11:00:00Z",market_data_manifest=m)
    CTX["missing_stock"]=missing_stock
    def future_row(): x=rows(6); m=manifest(x); return build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=x[5]["session_date"]+"T11:00:00Z",market_data_manifest=m)
    CTX["future_row"]=future_row
    def future_observed(): x=rows(5); cutoff=x[-1]["session_date"]+"T11:00:00Z"; x[0]["observed_at_utc"]="2026-12-01T00:00:00Z"; m=manifest(x); return build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=cutoff,market_data_manifest=m)
    CTX["future_observed"]=future_observed
    def missing_nifty(): x=rows(5); x[-1]["nifty_close"]=None; m=manifest(x); return build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=x[-1]["session_date"]+"T11:00:00Z",market_data_manifest=m)
    CTX["missing_nifty"]=missing_nifty
    def cp_conflict():
        x=rows(5); x[-1]["stock_close"]="106"; m=manifest(x); bad=build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=x[-1]["session_date"]+"T11:00:00Z",market_data_manifest=m); return CTX["store"].persist_checkpoint(bad)
    CTX["checkpoint_conflict"]=cp_conflict
    CTX["prospective_hash_before"]=Path(CTX["prospective"]).read_bytes(); CTX["prospective_hash_after"]=lambda:Path(CTX["prospective"]).read_bytes()
    c=sqlite3.connect(CTX["control"]); tx=[]
    for tid,side,qty,day,price in (("BUY1","BUY",10,"2026-10-06","101"),("SELL1","SELL",10,CTX["m5"]["observations"][-1]["session_date"],"105")):
        p={"ticker":"AAA.NS","trade_date":day,"side":side,"quantity":qty,"price_inr":price,"fees_inr":"0","recommendation_id":"REC1","signal_id":"SIG1","external_reference":None,"notes":None}; text=canonical_json(p); c.execute("INSERT INTO user_transactions(transaction_id,idempotency_key,ticker,trade_date,side,quantity,price_inr,fees_inr,recommendation_id,signal_id,external_reference,notes,canonical_payload_json,payload_sha256,recorded_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(tid,"KEY"+tid,"AAA.NS",day,side,qty,price,"0","REC1","SIG1",None,None,text,payload_sha256(text),day+"T09:00:00Z"))
    c.commit(); c.close()
    CTX["control_hash_before"]=Path(CTX["control"]).read_bytes(); CTX["control_hash_after"]=lambda:Path(CTX["control"]).read_bytes()
    with Stage5DControlReader(CTX["control"]) as reader: CTX["final_exit"]=derive_final_exit(reader,"REC1",CTX["m5"]["observations"][-1]["session_date"]+"T11:00:00Z")
    CTX["cp_exit"]=build_checkpoint(envelope=CTX["env"],checkpoint_type="FINAL_EXIT",checkpoint_cutoff_utc=CTX["m5"]["observations"][-1]["session_date"]+"T11:00:00Z",market_data_manifest=CTX["m5"],final_exit=CTX["final_exit"])
    def voided_exit():
        clone=CTX["root"] / "voided.sqlite3"; clone.write_bytes(Path(CTX["control"]).read_bytes()); c=sqlite3.connect(clone); p={"transaction_id":"SELL1","reason":"fixture"}; text=canonical_json(p); c.execute("INSERT INTO transaction_voids(void_id,transaction_id,idempotency_key,reason,voided_at_utc,canonical_payload_json,payload_sha256) VALUES('V1','SELL1','VK','fixture','2026-10-13T10:00:00Z',?,?)",(text,payload_sha256(text))); c.commit(); c.close();
        with Stage5DControlReader(clone) as reader:return derive_final_exit(reader,"REC1","2026-10-13T11:00:00Z")
    CTX["voided_exit"]=voided_exit
    def no_fill_exit():
        with Stage5DControlReader(CTX["control"]) as reader:return derive_final_exit(reader,"MISSING","2026-10-13T11:00:00Z")
    CTX["no_fill_exit"]=no_fill_exit


def main():
    temp=tempfile.TemporaryDirectory(); rows_out=[]; failed=0
    try:
        setup(temp); enrich()
        for i,(group,name,fn) in enumerate(CASES,1):
            try: fn(); result,detail="PASS",""
            except Exception as exc: result,detail="FAIL",f"{type(exc).__name__}: {exc}"; failed+=1
            rows_out.append({"test_id":f"S6_8C_{i:03d}","test_group":group,"test_name":name,"result":result,"detail":detail})
        OUT.parent.mkdir(parents=True,exist_ok=True)
        with OUT.open("w",newline="",encoding="utf-8") as handle:
            writer=csv.DictWriter(handle,fieldnames=("test_id","test_group","test_name","result","detail"),lineterminator="\n"); writer.writeheader(); writer.writerows(rows_out)
        print(f"Stage 6.8C: {len(rows_out)-failed}/{len(rows_out)} PASS"+(f", {failed} FAIL" if failed else ""))
        for row in rows_out:
            if row["result"]=="FAIL": print(row)
        return 1 if failed else 0
    finally:
        try: CTX["store"].close()
        except Exception: pass
        temp.cleanup()

if __name__=="__main__": raise SystemExit(main())
