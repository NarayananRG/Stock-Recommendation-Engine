from __future__ import annotations

import csv
import gzip
import hashlib
import inspect
import json
import shutil
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
from stage6_prospective_validation.checkpoint_market_archive import (
    ARCHIVE_SCHEMA, CREATOR_ID, FROZEN_ADAPTER_ID, FROZEN_PROVIDER, RUNTIME_RELATIVE,
    capture_checkpoint_market_archive, validate_checkpoint_market_archive_root,
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
from stage6_prospective_validation.prospective_store import ProspectiveValidationStore
from stage6_prospective_validation import observation_config as oc
from stage6_prospective_validation import operations_config as ops
from stage6_prospective_validation import cohort_guard as cg
from stage6_prospective_validation.verified_inputs import (
    CHECKPOINT_MARKET_ARCHIVE_SCHEMA, MARKET_ARCHIVE_SCHEMA, MarketArchiveResolver, ProspectiveStoreReader,
    Stage4A3SnapshotResolver, Stage6ContextReader,
)
from stage6_prospective_validation.session_calendar import verify_ordinary_session

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


def create_prospective(path, activation_path, control):
    with ProspectiveValidationStore(path, activation_path) as store:
        store.enroll_session(control_database=control, run_id="RUN1")


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


def make_real_snapshot(root, *, snapshot_id="S4A3_1", candidate_signal="SIG1", candidate_ticker="AAA.NS",
                       feature_signal="SIG1", feature_ticker="AAA.NS", duplicate_candidate=False,
                       prediction_feature_hash="ROW_HASH", feature_row_hash="ROW_HASH",
                       candidate_input_hash="CANDIDATE", market_hash="MARKET"):
    import pandas as pd
    stage4_root=REPO/"Stage 4A.3"; prospective=Path(root)/"snapshots"
    sys.path.insert(0,str(stage4_root))
    try:
        from stage4a3.hash_chain import genesis_hash
        from stage4a3.hashing import canonical_json_hash
        from stage4a3.immutable_ledger import write_snapshot
        from stage4a3.snapshot_contract import PREDICTION_COLUMNS
        row={column:"" for column in PREDICTION_COLUMNS}
        row.update({"Protocol Version":"STAGE4A3A_V1","Protocol Commit":"3ff3c0283174589d43883ce75b1dfd87a33613ce","Protocol Tag":"stage4a3-prospective-shadow-protocol-baseline","Snapshot ID":snapshot_id,"Signal Date":"2026-10-05","Snapshot Created UTC":"2026-10-05T10:00:00Z","Snapshot Created Asia/Kolkata":"2026-10-05T15:30:00+05:30","Signal ID":candidate_signal,"Ticker":candidate_ticker,"Original Signal":"BUY","Signal":"BUY","Setup":"PULLBACK","Market Regime":"BULL","Trade Quality":"A","Actionability Score":90,"Technical Score":80,"Planned Entry":100,"Initial Stop":95,"Original T1":110,"Original T2":120,"Dataset Cohort":"PROSPECTIVE","Feature Row Hash":prediction_feature_hash,"Model Bundle Hash":MODEL_BUNDLE_HASH,"Prediction Semantics":"SHADOW_ONLY_NO_TRADING_EFFECT"})
        for code in range(6): row.update({f"R{code} Score":0.5+code/100,f"R{code} Same-Date Rank":1,f"R{code}_K1 Selected":code==3,f"R{code}_K2 Selected":False})
        prediction_rows=[row,deepcopy(row)] if duplicate_candidate else [row]
        predictions=pd.DataFrame(prediction_rows,columns=PREDICTION_COLUMNS)
        features=pd.DataFrame([{"Signal ID":feature_signal,"Ticker":feature_ticker,"Feature Row Hash":feature_row_hash,"feature_x":1}])
        candidate={"Signal Date":"2026-10-05","Full Input Logical Hash":candidate_input_hash,"Feature Contract Hash":FEATURE_HASHES[0],"Candidate Count":len(predictions)}
        market={"raw_data_logical_hash":market_hash,"provider_identifier":"FROZEN_STAGE4A3_TEST_ADAPTER","maximum_market_data_date":"2026-10-05","nifty_maximum_date":"2026-10-05"}
        metadata={"Snapshot ID":snapshot_id,"Signal Date":"2026-10-05","Snapshot Created UTC":"2026-10-05T10:00:00Z","Candidate Count":len(predictions),"Candidate Input Manifest Hash":canonical_json_hash(candidate)}
        write_snapshot(prospective,Path(root)/"audit","2026-10-05",metadata,predictions,features,market,genesis_hash("3ff3c0283174589d43883ce75b1dfd87a33613ce",MODEL_BUNDLE_HASH),"3ff3c0283174589d43883ce75b1dfd87a33613ce",MODEL_BUNDLE_HASH,candidate_input_manifest=candidate)
    finally:
        sys.path.remove(str(stage4_root))
    return prospective


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_market_archive(root, observations, *, ticker="AAA.NS", benchmark="^NSEI", target_date=None,
                        captured_at="2026-10-13T11:00:00Z", provider="FROZEN_STAGE4A3_MARKET_ADAPTER"):
    directory=Path(root); directory.mkdir(parents=True,exist_ok=True); target_date=target_date or observations[-1]["session_date"]
    stock_path=directory/"stock_ohlc.csv.gz"; nifty_path=directory/"nifty_close.csv.gz"
    with gzip.open(stock_path,"wt",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=("ticker","session_date","observed_at_utc","close","high","low"),lineterminator="\n"); writer.writeheader()
        for row in observations: writer.writerow({"ticker":ticker,"session_date":row["session_date"],"observed_at_utc":row["observed_at_utc"],"close":row["stock_close"],"high":row["stock_high"],"low":row["stock_low"]})
    with gzip.open(nifty_path,"wt",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=("ticker","session_date","observed_at_utc","close"),lineterminator="\n"); writer.writeheader()
        for row in observations: writer.writerow({"ticker":benchmark,"session_date":row["session_date"],"observed_at_utc":row["observed_at_utc"],"close":row["nifty_close"]})
    normalized=[{"session_date":r["session_date"],"observed_at_utc":r["observed_at_utc"],"stock_close":r["stock_close"],"stock_high":r["stock_high"],"stock_low":r["stock_low"],"nifty_close":r["nifty_close"]} for r in observations]
    logical=canonical_hash({"provider_identifier":provider,"ticker":ticker,"benchmark_ticker":benchmark,"observations":normalized})
    value={"archive_schema":MARKET_ARCHIVE_SCHEMA,"archive_id":"S6MD_"+logical[:24],"classification":MARKET_CLASSIFICATION,"provider_identifier":provider,"ticker":ticker,"benchmark_ticker":benchmark,"target_session_date":target_date,"captured_at_utc":captured_at,"market_data_logical_hash":logical,"files":[{"file":p.name,"sha256":_file_sha(p),"bytes":p.stat().st_size} for p in (stock_path,nifty_path)],"manifest_hash":""}
    value["manifest_hash"]=canonical_hash(without(value,"manifest_hash")); (directory/"market_archive_manifest.json").write_text(json.dumps(value,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return directory


def frozen_fixture_acquire(repo, stage4a3_root, as_of_date, archive_parent, downloaded_utc):
    """Injected test transport that exercises the frozen archive writer without network."""
    import pandas as pd
    sys.path.insert(0, str(stage4a3_root))
    try:
        from stage4a3.final_market_data import archive_market_frames, verify_and_load_archive
        dates = CTX.get("adapter_dates_override") or CTX["verified_dates"]
        stock = pd.DataFrame({"Open":[100+i for i in range(len(dates))],
                              "High":[102+i for i in range(len(dates))],
                              "Low":[98+i for i in range(len(dates))],
                              "Close":[100+i for i in range(len(dates))]}, index=pd.to_datetime(dates))
        nifty = pd.DataFrame({"Open":[20000+10*i for i in range(len(dates))],
                              "High":[20005+10*i for i in range(len(dates))],
                              "Low":[19995+10*i for i in range(len(dates))],
                              "Close":[20000+10*i for i in range(len(dates))]}, index=pd.to_datetime(dates))
        frames={"AAA.NS":stock,"^NSEI":nifty}; CTX["acquisition_calls"].append((as_of_date,downloaded_utc))
        manifest=archive_market_frames(frames,Path(archive_parent)/"final_market_data",as_of_date,
                                       "TEST_ONLY_FROZEN_STAGE4A3_ADAPTER",downloaded_utc)
        loaded=verify_and_load_archive(Path(archive_parent)/"final_market_data",Path(archive_parent)/"stage4a3_final_market_data_manifest.json")
        return loaded,manifest
    finally:
        sys.path.remove(str(stage4a3_root))


def add_control_sessions(control, prospective, activation_path, count=40):
    dates=[]; day=date(2026,10,6)
    while len(dates)<count:
        try: verify_ordinary_session(day.isoformat()); dates.append(day.isoformat())
        except Exception: pass
        day+=timedelta(days=1)
        if day.year!=2026 and len(dates)<count: raise AssertionError("fixture exceeds verified 2026 calendar")
    connection=sqlite3.connect(control)
    for index,session in enumerate(dates,2):
        run={"run_id":f"RUN{index}","market_session_date":session,"run_started_utc":session+"T08:00:00Z","run_completed_utc":session+"T11:00:00Z","data_provider":"FIXTURE","market_data_hash":f"MARKET{index}","candidate_input_hash":f"CANDIDATE{index}","candidate_count":0,"stage4a3_snapshot_id":f"S4A3_{index}","allocation_run_id":f"ALLOC{index}","management_session_run_id":f"MGMT{index}","recommendation_count":0,"news_status":"AVAILABLE"}
        text=canonical_json(run); connection.execute("INSERT INTO stage5d5_live_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(*[run[k] for k in ("run_id","market_session_date","run_started_utc","run_completed_utc","data_provider","market_data_hash","candidate_input_hash","candidate_count","stage4a3_snapshot_id","allocation_run_id","management_session_run_id","recommendation_count","news_status")],text,payload_sha256(text)))
    connection.commit(); connection.close()
    with ProspectiveValidationStore(prospective,activation_path) as store:
        for index in range(2,count+2): store.enroll_session(control_database=control,run_id=f"RUN{index}")
    return dates


def setup(temp):
    root=Path(temp.name); activation_path=root/"activation.json"; activation=make_activation(activation_path)
    cohort=verify_active_cohort(REPO,activation_path)
    control=root/"control.sqlite3"; rec=create_control(control); prospective=root/"prospective.sqlite3"; create_prospective(prospective,activation_path,control)
    env=build_recommendation_envelope(control_database=control,prospective_database=prospective,recommendation_id="REC1",cohort_fingerprint=cohort,activation_record=activation_path,stage4a3_snapshot=snapshot(),test_only_adapter=True)
    store=ProspectiveObservationStore(root/"observation.sqlite3",REPO,cohort,allow_test_runtime=True); store.persist_envelope(env)
    m5=manifest(rows(5)); cp5=build_checkpoint(envelope=env,checkpoint_type="D+5",checkpoint_cutoff_utc=m5["observations"][-1]["session_date"]+"T11:00:00Z",market_data_manifest=m5,test_only_adapter=True)
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
case("SESSION","due D+5",lambda:require([x["checkpoint_type"] for x in determine_due_checkpoints(decision_date="2026-10-05",completed_session_dates=[x["session_date"] for x in rows(5)[1:]],test_only_adapter=True)]==["D+5"]))
case("SESSION","existing checkpoint not due",lambda:require(determine_due_checkpoints(decision_date="2026-10-05",completed_session_dates=[x["session_date"] for x in rows(5)[1:]],existing_checkpoint_types=("D+5",),test_only_adapter=True)==[]))
case("SESSION","final exit due separately",lambda:require(determine_due_checkpoints(decision_date="2026-10-05",completed_session_dates=[],final_exit_completed=True,test_only_adapter=True)[0]["checkpoint_type"]=="FINAL_EXIT"))
case("SESSION","unsorted completion sequence rejected",lambda:expect(Stage6ProspectiveError,lambda:determine_due_checkpoints(decision_date="2026-10-05",completed_session_dates=["2026-10-07","2026-10-06"],test_only_adapter=True)))
case("SESSION","missing stock target fails",lambda:expect(Stage6ProspectiveError,CTX["missing_stock"]))
case("RETURN","stock formula",lambda:require(CTX["cp5"]["stock_return"]=="0.05"))
case("RETURN","nifty formula",lambda:require(CTX["cp5"]["nifty_return"]=="0.0025"))
case("RETURN","stock minus nifty",lambda:require(CTX["cp5"]["stock_minus_nifty"]=="0.0475"))
case("RETURN","sector formula",lambda:require(abs(Decimal(CTX["cp_sector"]["sector_return"])-(Decimal(30100)/Decimal(30000)-1))<Decimal("1e-27")))
case("RETURN","stock minus sector",lambda:require(abs(Decimal(CTX["cp_sector"]["stock_minus_sector"])-(Decimal("0.05")-(Decimal(30100)/Decimal(30000)-1)))<Decimal("1e-27")))
case("RETURN","sector unavailable status",lambda:require(CTX["cp5"]["sector_benchmark_status"]==SECTOR_UNAVAILABLE))
case("RETURN","sector unavailable null",lambda:require(CTX["cp5"]["sector_return"] is None and CTX["cp5"]["sector_benchmark_identifier"] is None))
case("RETURN","MFE",lambda:require(CTX["cp5"]["mfe"]=="0.07"))
case("RETURN","MAE",lambda:require(CTX["cp5"]["mae"]=="-0.01"))
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

# Independent-audit provenance and PIT corrections
case("AUDIT_STAGE4A3","fabricated self-hashed production descriptor rejected",lambda:expect(Stage6ProspectiveError,CTX["fabricated_production"]))
case("AUDIT_STAGE4A3","wrong real snapshot id rejected",lambda:expect(ProspectiveIntegrityFailure,lambda:CTX["snapshot_variant"]("wrong_id",snapshot_id="WRONG")))
case("AUDIT_STAGE4A3","wrong candidate ticker rejected",lambda:expect(ProspectiveIntegrityFailure,lambda:CTX["snapshot_variant"]("wrong_candidate",candidate_ticker="BBB.NS")))
case("AUDIT_STAGE4A3","candidate absent rejected",lambda:expect(Stage6ProspectiveError,lambda:CTX["snapshot_variant"]("candidate_absent",candidate_signal="OTHER")))
case("AUDIT_STAGE4A3","duplicate candidate rejected",lambda:expect(ProspectiveIntegrityFailure,lambda:CTX["snapshot_variant"]("candidate_duplicate",duplicate_candidate=True)))
case("AUDIT_STAGE4A3","wrong feature ticker rejected",lambda:expect(ProspectiveIntegrityFailure,lambda:CTX["snapshot_variant"]("wrong_feature",feature_ticker="BBB.NS")))
case("AUDIT_STAGE4A3","feature row hash mismatch rejected",lambda:expect(ProspectiveIntegrityFailure,lambda:CTX["snapshot_variant"]("feature_hash",prediction_feature_hash="A",feature_row_hash="B")))
case("AUDIT_STAGE4A3","candidate input hash mismatch rejected",lambda:expect(ProspectiveIntegrityFailure,lambda:CTX["snapshot_variant"]("candidate_input",candidate_input_hash="WRONG")))
case("AUDIT_STAGE4A3","market data hash mismatch rejected",lambda:expect(ProspectiveIntegrityFailure,lambda:CTX["snapshot_variant"]("market_hash",market_hash="WRONG")))
case("AUDIT_STAGE4A3","tampered snapshot file rejected",lambda:expect(ProspectiveIntegrityFailure,CTX["tampered_snapshot"]))
case("AUDIT_STAGE4A3","valid immutable snapshot accepted",lambda:require(CTX["resolved_snapshot"]["snapshot_directory_verification"]=="PASS"))
case("AUDIT_ORIGIN","enrolled post-activation origin accepted",lambda:require(CTX["real_env"]["prospective_origin_session_binding"]["record_id"]==CTX["origin_session"]["enrollment_id"]))
case("AUDIT_ORIGIN","later prospective case not required",lambda:require(CTX["real_env"]["prospective_case_status"]=="NOT_AVAILABLE_AT_RECOMMENDATION_CREATION" and CTX["real_env"]["prospective_case_binding"] is None))
case("AUDIT_ORIGIN","non-enrolled origin rejected",lambda:expect(Stage6ProspectiveError,CTX["non_enrolled_origin"]))
case("AUDIT_ORIGIN","pre-activation origin rejected",lambda:expect(Stage6ProspectiveError,CTX["preactivation_origin"]))
case("AUDIT_ORIGIN","wrong control database identity rejected",lambda:expect(ProspectiveIntegrityFailure,CTX["wrong_control_identity"]))
case("AUDIT_SESSION","caller Saturday cannot become D+N",lambda:expect(Stage6ProspectiveError,CTX["caller_dates_production"]))
case("AUDIT_SESSION","caller Sunday rejected by verified calendar",lambda:expect(Stage6ProspectiveError,lambda:verify_ordinary_session("2026-10-11")))
case("AUDIT_SESSION","official closed date rejected",lambda:expect(Stage6ProspectiveError,lambda:verify_ordinary_session("2026-10-20")))
case("AUDIT_SESSION","production due resolution uses session chain",lambda:require(next(x for x in CTX["verified_due"] if x["checkpoint_type"]=="D+5")["checkpoint_date"]==CTX["target_date"]))
case("AUDIT_SESSION","missing ordinal returns NOT_DUE",lambda:require(next(x for x in CTX["verified_due"] if x["checkpoint_type"]=="D+60")["status"]=="NOT_DUE"))
case("AUDIT_SESSION","unsupported future calendar fails closed",lambda:expect(Stage6ProspectiveError,lambda:verify_ordinary_session("2027-01-04")))
case("AUDIT_MARKET","arbitrary self-hashed market JSON rejected",lambda:expect(Stage6ProspectiveError,CTX["arbitrary_market_production"]))
case("AUDIT_MARKET","wrong ticker market archive rejected",lambda:expect(ProspectiveIntegrityFailure,lambda:CTX["market_variant"]("wrong_ticker",ticker="BBB.NS")))
case("AUDIT_MARKET","missing NIFTY row rejected",lambda:expect(ProspectiveIntegrityFailure,CTX["missing_nifty_archive"]))
case("AUDIT_MARKET","wrong target session rejected",lambda:expect(ProspectiveIntegrityFailure,lambda:CTX["market_variant"]("wrong_target",target_date="2026-12-01")))
case("AUDIT_MARKET","archive file hash tamper rejected",lambda:expect(ProspectiveIntegrityFailure,CTX["tampered_market"]))
case("AUDIT_MARKET","data after checkpoint rejected",lambda:expect(ProspectiveIntegrityFailure,lambda:MarketArchiveResolver(make_market_archive(CTX["root"]/"market_future",CTX["verified_rows"]+[dict(CTX["verified_rows"][-1],session_date="2026-12-31")],target_date=CTX["target_date"],captured_at=CTX["checkpoint_cutoff"])).resolve(ticker="AAA.NS",anchor_date="2026-10-05",target_date=CTX["target_date"],checkpoint_cutoff_utc=CTX["checkpoint_cutoff"],verified_session_dates=CTX["verified_dates"])))
case("AUDIT_MARKET","checkpoint before close blocked",lambda:expect(Stage6ProspectiveError,CTX["before_close"]))
case("AUDIT_MARKET","valid immutable archive accepted",lambda:require(CTX["verified_market"]["provenance_verification"]=="PASS" and CTX["verified_checkpoint"]["checkpoint_date"]==CTX["target_date"]))
case("AUDIT_EXCURSION","extreme D0 high excluded from MFE",lambda:require(CTX["forward_checkpoint"](d0_high="10000")["mfe"]==CTX["verified_checkpoint"]["mfe"]))
case("AUDIT_EXCURSION","extreme D0 low excluded from MAE",lambda:require(CTX["forward_checkpoint"](d0_low="1")["mae"]==CTX["verified_checkpoint"]["mae"]))
case("AUDIT_EXCURSION","D+1 high drives MFE",lambda:require(CTX["forward_checkpoint"](d1_high="150")["mfe"]=="0.5"))
case("AUDIT_EXCURSION","D+1 low drives MAE",lambda:require(CTX["forward_checkpoint"](d1_low="50")["mae"]=="-0.5"))
case("AUDIT_EXCURSION","drawdown seeds anchor close",lambda:require(CTX["verified_checkpoint"]["maximum_drawdown"]=="0"))
case("AUDIT_THESIS","arbitrary caller thesis rejected",lambda:expect(Stage6ProspectiveError,CTX["arbitrary_thesis"]))
case("AUDIT_THESIS","verified stored thesis accepted",lambda:require(CTX["verified_thesis_checkpoint"]["current_thesis_state"]=="VALID"))
case("AUDIT_THESIS","stored thesis hash mismatch rejected",lambda:expect(ProspectiveIntegrityFailure,CTX["context_wrong_hash"]))
case("AUDIT_THESIS","thesis after cutoff excluded",lambda:expect(Stage6ProspectiveError,CTX["context_after_cutoff"]))
case("AUDIT_THESIS","missing thesis explicit",lambda:require(CTX["verified_checkpoint"]["current_thesis_state"]=="NOT_AVAILABLE"))
case("AUDIT_EXIT","transaction typed canonical mismatch rejected",lambda:expect(ProspectiveIntegrityFailure,CTX["typed_tx_mismatch"]))
case("AUDIT_EXIT","void typed canonical mismatch rejected",lambda:expect(ProspectiveIntegrityFailure,CTX["void_mismatch"]))
case("AUDIT_EXIT","later void does not affect earlier cutoff",lambda:require(CTX["later_void_earlier"]()["exit_status"]=="FINAL_EXIT_COMPLETED"))
case("AUDIT_EXIT","later evaluation reflects void",lambda:expect(Stage6ProspectiveError,CTX["later_void_later"]))
case("AUDIT_EXIT","future trade date rejected",lambda:expect(Stage6ProspectiveError,CTX["future_trade"]))
case("AUDIT_EXIT","incomplete position rejected",lambda:expect(Stage6ProspectiveError,CTX["no_fill_exit"]))
case("AUDIT_STORE","checkpoint relational binding tamper fails",lambda:expect(ProspectiveIntegrityFailure,CTX["checkpoint_relationship_tamper"]))
case("AUDIT_STORE","envelope cohort binding tamper fails",lambda:expect(ProspectiveIntegrityFailure,CTX["envelope_cohort_tamper"]))

# Final operational market-archive correction
case("ARCHIVE_CAPTURE","ticker derived from envelope",lambda:require(CTX["capture_manifest"]["ticker"]==CTX["env"]["ticker"]=="AAA.NS"))
case("ARCHIVE_CAPTURE","target date derived from D+N chain",lambda:require(CTX["capture_manifest"]["target_session_date"]==CTX["target_date"]))
case("ARCHIVE_CAPTURE","caller target date is not an input",lambda:require("target_date" not in inspect.signature(capture_checkpoint_market_archive).parameters))
case("ARCHIVE_CAPTURE","caller ticker is not an input",lambda:require("ticker" not in inspect.signature(capture_checkpoint_market_archive).parameters))
case("ARCHIVE_GATE","not due checkpoint uses zero acquisition calls",lambda:require(expect(Stage6ProspectiveError,CTX["capture_not_due"]) and len(CTX["acquisition_calls"])==2))
case("ARCHIVE_GATE","before close uses zero acquisition calls",lambda:require(expect(Stage6ProspectiveError,CTX["capture_before_close"]) and len(CTX["acquisition_calls"])==2))
case("ARCHIVE_GATE","due completed checkpoint invokes adapter",lambda:require(CTX["capture_result"]["status"]=="CREATED" and len(CTX["acquisition_calls"])==2))
case("ARCHIVE_SOURCE","frozen Stage4A3 adapter identity",lambda:require(CTX["capture_manifest"]["frozen_adapter_id"]==FROZEN_ADAPTER_ID))
case("ARCHIVE_SOURCE","production provider path fixed",lambda:require(FROZEN_PROVIDER=="YFINANCE_REFRESH_VIA_FROZEN_STAGE2_2_1" and "provider" not in inspect.signature(capture_checkpoint_market_archive).parameters))
case("ARCHIVE_BOUNDARY","archive only below approved runtime root",lambda:require(RUNTIME_RELATIVE.as_posix()=="Stage 6/runtime/prospective_validation/checkpoint_market_data" and CTX["capture_dir"].is_relative_to(CTX["capture_runtime"].resolve())))
case("ARCHIVE_BOUNDARY","research results path rejected",lambda:expect(Stage6ProspectiveError,lambda:validate_checkpoint_market_archive_root(REPO/"Stage 6/results/checkpoint_market_data",REPO)))
case("ARCHIVE_BOUNDARY","fixture path rejected",lambda:expect(Stage6ProspectiveError,lambda:validate_checkpoint_market_archive_root(REPO/"Stage 6/tests/fixtures/checkpoint_market_data",REPO)))
case("ARCHIVE_HASH","stock file hash verified",lambda:require(next(x for x in CTX["capture_manifest"]["files"] if x["file"]=="stock_ohlc.csv.gz")["sha256"]==_file_sha(CTX["capture_dir"]/"stock_ohlc.csv.gz")))
case("ARCHIVE_HASH","NIFTY file hash verified",lambda:require(next(x for x in CTX["capture_manifest"]["files"] if x["file"]=="nifty_close.csv.gz")["sha256"]==_file_sha(CTX["capture_dir"]/"nifty_close.csv.gz")))
case("ARCHIVE_HASH","manifest hash verified",lambda:require(CTX["capture_manifest"]["manifest_hash"]==canonical_hash(without(CTX["capture_manifest"],"manifest_hash"))))
case("ARCHIVE_HASH","logical market hash verified",lambda:require(CTX["capture_manifest"]["market_data_logical_hash"]==CTX["captured_market"]["market_data_logical_hash"]))
case("ARCHIVE_SESSION","exact verified session sequence preserved",lambda:require(CTX["capture_manifest"]["verified_session_dates"]==CTX["verified_dates"]))
case("ARCHIVE_SESSION","target session preserved",lambda:require(CTX["captured_market"]["target_session_date"]==CTX["target_date"]))
case("ARCHIVE_IDEMPOTENCY","exact replay idempotent",lambda:require(CTX["capture_replay"]()["status"]=="IDEMPOTENT_SUCCESS" and len(CTX["acquisition_calls"])==2))
case("ARCHIVE_IDEMPOTENCY","conflicting archive rejected",lambda:expect(ProspectiveConflict,CTX["capture_conflict"]))
case("ARCHIVE_RESOLVER","creator archive consumed by resolver",lambda:require(CTX["captured_market"]["archive_schema"]==CHECKPOINT_MARKET_ARCHIVE_SCHEMA and CTX["captured_market"]["provenance_verification"]=="PASS"))
case("ARCHIVE_RESOLVER","resolved archive builds checkpoint",lambda:require(CTX["captured_checkpoint"]["checkpoint_date"]==CTX["target_date"]))
case("ARCHIVE_READ_ONLY","Stage5D unchanged",lambda:require(CTX["capture_control_before"]==CTX["capture_control_after"]))
case("ARCHIVE_READ_ONLY","prospective store unchanged",lambda:require(CTX["capture_prospective_before"]==CTX["capture_prospective_after"]))
case("ARCHIVE_READ_ONLY","recommendation envelope unchanged",lambda:require(CTX["capture_envelope_before"]==CTX["capture_envelope_after"]))
case("ARCHIVE_AUTHORITY","classification remains outcome measurement only",lambda:require(CTX["capture_manifest"]["classification"]==MARKET_CLASSIFICATION))
case("ARCHIVE_AUTHORITY","active RBI SEBI source set unchanged",lambda:require(tuple(OPERATIONAL_SOURCES)==("RBI_OFFICIAL_PRESS_RELEASES_RSS","SEBI_OFFICIAL_RSS")))
case("ARCHIVE_AUTHORITY","no broker or trading authority",lambda:require(CTX["capture_manifest"]["trading_authority"] is False))
case("ARCHIVE_AUTHORITY","no model or recommendation influence",lambda:require(CTX["capture_manifest"]["recommendation_influence"]=="NONE"))
case("ARCHIVE_FINAL_EXIT","target date derived from verified transaction lifecycle",lambda:require(CTX["final_capture_manifest"]["target_session_date"]==CTX["final_exit"]["final_exit_date"]))
case("ARCHIVE_NETWORK","zero real network and operator action exposed",lambda:require(len(CTX["acquisition_calls"])==2 and "capture-checkpoint-market-data" in (ROOT/"stage6_prospective_validation/observation_operator.py").read_text()))


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
    CTX["rebuild_env"]=build_recommendation_envelope(control_database=CTX["control"],prospective_database=CTX["prospective"],recommendation_id="REC1",cohort_fingerprint=CTX["cohort"],activation_record=CTX["activation_path"],stage4a3_snapshot=snapshot(),test_only_adapter=True)
    CTX["session_dates"]=add_control_sessions(CTX["control"],CTX["prospective"],CTX["activation_path"])
    with Stage5DControlReader(CTX["control"]) as reader:
        CTX["recommendation_row"]=reader.get_recommendation("REC1"); CTX["origin_run"]=reader.get_origin_run("ALLOC1")
    CTX["real_snapshot_root"]=make_real_snapshot(CTX["root"]/"real_stage4a3")
    CTX["real_resolver"]=Stage4A3SnapshotResolver(REPO/"Stage 4A.3",CTX["real_snapshot_root"])
    CTX["resolved_snapshot"]=CTX["real_resolver"].resolve(CTX["origin_run"],CTX["recommendation_row"])
    CTX["real_env"]=build_recommendation_envelope(control_database=CTX["control"],prospective_database=CTX["prospective"],recommendation_id="REC1",cohort_fingerprint=CTX["cohort"],activation_record=CTX["activation_path"],stage4a3_root=REPO/"Stage 4A.3",stage4a3_prospective_root=CTX["real_snapshot_root"])
    with ProspectiveStoreReader(CTX["prospective"],CTX["activation"]) as reader:
        CTX["origin_session"]=reader.origin_session(CTX["origin_run"]); CTX["verified_due"]=reader.due_checkpoints(CTX["origin_session"])
        target=next(x for x in CTX["verified_due"] if x["checkpoint_type"]=="D+5")["checkpoint_date"]
        CTX["verified_dates"]=reader.session_dates_through(CTX["origin_session"],target)
    def wrong_control_identity():
        with ProspectiveStoreReader(CTX["prospective"],CTX["activation"]) as reader:return reader.origin_session(CTX["origin_run"],"WRONG_CONTROL_DB")
    CTX["wrong_control_identity"]=wrong_control_identity
    def preactivation_origin():
        fake=deepcopy(CTX["origin_run"]);fake.update({"market_session_date":"2026-09-29","run_started_utc":"2026-09-29T08:00:00Z","run_completed_utc":"2026-09-29T11:00:00Z"});fake["payload_sha256"]="F"*64
        target=CTX["root"]/"preactivation.sqlite3";shutil.copyfile(CTX["prospective"],target);c=sqlite3.connect(target);c.execute("DROP TRIGGER protect_prospective_sessions_update");row=c.execute("SELECT canonical_json FROM prospective_sessions WHERE run_id='RUN1'").fetchone();value=json.loads(row[0]);value.update({"market_session_date":fake["market_session_date"],"run_started_utc":fake["run_started_utc"],"run_completed_utc":fake["run_completed_utc"]});value["control_run_binding"]["record_hash"]=fake["payload_sha256"];value["stage5d5_run_payload_hash"]=fake["payload_sha256"];value["record_hash"]=canonical_hash(without(value,"record_hash"));c.execute("UPDATE prospective_sessions SET market_session_date=?,record_hash=?,canonical_json=? WHERE run_id='RUN1'",(value["market_session_date"],value["record_hash"],canonical_json(value)));c.execute("CREATE TRIGGER protect_prospective_sessions_update BEFORE UPDATE ON prospective_sessions BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END");c.commit();c.close()
        with ProspectiveStoreReader(target,CTX["activation"]) as reader:return reader.origin_session(fake,"CONTROL_DB")
    CTX["preactivation_origin"]=preactivation_origin
    verified_rows=[]
    for n,session in enumerate(CTX["verified_dates"]): verified_rows.append({"session_date":session,"observed_at_utc":session+"T10:30:00Z","stock_close":str(100+n),"stock_high":str(102+n),"stock_low":str(98+n),"nifty_close":str(20000+10*n)})
    CTX["verified_rows"]=verified_rows; CTX["target_date"]=verified_rows[-1]["session_date"]; CTX["checkpoint_cutoff"]=CTX["target_date"]+"T11:00:00Z"
    CTX["archive_dir"]=make_market_archive(CTX["root"]/"market_archive",verified_rows,target_date=CTX["target_date"],captured_at=CTX["checkpoint_cutoff"])
    CTX["verified_market"]=MarketArchiveResolver(CTX["archive_dir"]).resolve(ticker="AAA.NS",anchor_date="2026-10-05",target_date=CTX["target_date"],checkpoint_cutoff_utc=CTX["checkpoint_cutoff"],verified_session_dates=CTX["verified_dates"])
    CTX["verified_checkpoint"]=build_checkpoint(envelope=CTX["real_env"],checkpoint_type="D+5",checkpoint_cutoff_utc=CTX["checkpoint_cutoff"],market_data_manifest=CTX["verified_market"])
    CTX["acquisition_calls"]=[]; CTX["capture_runtime"]=CTX["root"]/"capture_runtime"
    CTX["capture_control_before"]=Path(CTX["control"]).read_bytes(); CTX["capture_prospective_before"]=Path(CTX["prospective"]).read_bytes()
    CTX["capture_envelope_before"]=CTX["store"].connection.execute("SELECT canonical_json FROM recommendation_audit_envelopes WHERE recommendation_id='REC1'").fetchone()[0]
    CTX["capture_result"]=capture_checkpoint_market_archive(repo_root=REPO,activation_record=CTX["activation_path"],prospective_database=CTX["prospective"],control_database=CTX["control"],observation_database=CTX["store"].database,recommendation_id="REC1",checkpoint_type="D+5",current_time_utc=CTX["checkpoint_cutoff"],acquisition_adapter=frozen_fixture_acquire,runtime_root=CTX["capture_runtime"],test_only_adapter=True)
    CTX["capture_dir"]=Path(CTX["capture_result"]["archive_directory"]); CTX["capture_manifest"]=json.loads((CTX["capture_dir"]/"market_archive_manifest.json").read_text())
    CTX["captured_market"]=CTX["capture_result"]["market_manifest"]
    CTX["captured_checkpoint"]=build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=CTX["capture_manifest"]["captured_at_utc"],market_data_manifest=CTX["captured_market"])
    CTX["capture_control_after"]=Path(CTX["control"]).read_bytes(); CTX["capture_prospective_after"]=Path(CTX["prospective"]).read_bytes()
    CTX["capture_envelope_after"]=CTX["store"].connection.execute("SELECT canonical_json FROM recommendation_audit_envelopes WHERE recommendation_id='REC1'").fetchone()[0]
    def replay_capture(runtime=None, checkpoint="D+5", current=None):
        return capture_checkpoint_market_archive(repo_root=REPO,activation_record=CTX["activation_path"],prospective_database=CTX["prospective"],control_database=CTX["control"],observation_database=CTX["store"].database,recommendation_id="REC1",checkpoint_type=checkpoint,current_time_utc=current or CTX["checkpoint_cutoff"],acquisition_adapter=frozen_fixture_acquire,runtime_root=runtime or CTX["capture_runtime"],test_only_adapter=True)
    CTX["capture_replay"]=replay_capture
    CTX["capture_not_due"]=lambda:replay_capture(CTX["root"]/"not_due_runtime","D+60")
    CTX["capture_before_close"]=lambda:replay_capture(CTX["root"]/"before_close_runtime","D+5",CTX["target_date"]+"T09:00:00Z")
    def capture_conflict():
        target=CTX["root"]/"conflict_runtime"; shutil.copytree(CTX["capture_runtime"],target)
        archive=Path(next((target/"REC1").iterdir())); path=archive/"stock_ohlc.csv.gz"; path.write_bytes(path.read_bytes()+b"tamper")
        return replay_capture(target)
    CTX["capture_conflict"]=capture_conflict
    def snapshot_variant(name, **kwargs):
        root=CTX["root"]/("s4_"+name); prospective=make_real_snapshot(root,**kwargs)
        return Stage4A3SnapshotResolver(REPO/"Stage 4A.3",prospective).resolve(CTX["origin_run"],CTX["recommendation_row"])
    CTX["snapshot_variant"]=snapshot_variant
    def tampered_snapshot():
        target=CTX["root"]/"s4_tamper"; shutil.copytree(CTX["real_snapshot_root"],target); path=target/"2026"/"2026-10-05"/"candidate_predictions.csv.gz"; path.write_bytes(path.read_bytes()+b"x")
        return Stage4A3SnapshotResolver(REPO/"Stage 4A.3",target).resolve(CTX["origin_run"],CTX["recommendation_row"])
    CTX["tampered_snapshot"]=tampered_snapshot
    CTX["fabricated_production"]=lambda:build_recommendation_envelope(control_database=CTX["control"],prospective_database=CTX["prospective"],recommendation_id="REC1",cohort_fingerprint=CTX["cohort"],activation_record=CTX["activation_path"],stage4a3_snapshot=snapshot(),stage4a3_root=REPO/"Stage 4A.3",stage4a3_prospective_root=CTX["real_snapshot_root"])
    def market_variant(name, **kwargs):
        directory=make_market_archive(CTX["root"]/("market_"+name),CTX["verified_rows"],target_date=kwargs.pop("target_date",CTX["target_date"]),captured_at=kwargs.pop("captured_at",CTX["checkpoint_cutoff"]),**kwargs)
        return MarketArchiveResolver(directory).resolve(ticker="AAA.NS",anchor_date="2026-10-05",target_date=CTX["target_date"],checkpoint_cutoff_utc=CTX["checkpoint_cutoff"],verified_session_dates=CTX["verified_dates"])
    CTX["market_variant"]=market_variant
    def tampered_market():
        target=CTX["root"]/"market_tamper"; shutil.copytree(CTX["archive_dir"],target); path=target/"stock_ohlc.csv.gz"; path.write_bytes(path.read_bytes()+b"x")
        return MarketArchiveResolver(target).resolve(ticker="AAA.NS",anchor_date="2026-10-05",target_date=CTX["target_date"],checkpoint_cutoff_utc=CTX["checkpoint_cutoff"],verified_session_dates=CTX["verified_dates"])
    CTX["tampered_market"]=tampered_market
    CTX["before_close"]=lambda:MarketArchiveResolver(CTX["archive_dir"]).resolve(ticker="AAA.NS",anchor_date="2026-10-05",target_date=CTX["target_date"],checkpoint_cutoff_utc=CTX["target_date"]+"T09:00:00Z",verified_session_dates=CTX["verified_dates"])
    context_db=CTX["root"]/"context.sqlite3"; c=sqlite3.connect(context_db); c.execute("CREATE TABLE trade_thesis_records(materialization_record_id TEXT PRIMARY KEY,record_hash TEXT,canonical_json TEXT)")
    thesis={"schema_version":"TEST_VERIFIED_THESIS","materialization_record_id":"TH1","recommendation_id":"REC1","signal_id":"SIG1","ticker":"AAA.NS","recorded_at_utc":CTX["target_date"]+"T10:30:00Z","current_thesis_state":"VALID","original_thesis_validity_state":"VALID","record_hash":""}; thesis["record_hash"]=canonical_hash(without(thesis,"record_hash")); c.execute("INSERT INTO trade_thesis_records VALUES(?,?,?)",("TH1",thesis["record_hash"],canonical_json(thesis))); c.commit(); c.close()
    CTX["context_db"]=context_db; CTX["thesis"]=thesis; CTX["thesis_binding"]={"table":"trade_thesis_records","id_column":"materialization_record_id","record_type":"TEST_VERIFIED_THESIS","record_id":"TH1","record_hash":thesis["record_hash"]}
    with Stage6ContextReader(context_db) as reader: CTX["resolved_thesis"],CTX["resolved_thesis_binding"]=reader.resolve(CTX["thesis_binding"],cutoff_utc=CTX["checkpoint_cutoff"],recommendation_id="REC1",signal_id="SIG1",ticker="AAA.NS")
    CTX["verified_thesis_checkpoint"]=build_checkpoint(envelope=CTX["real_env"],checkpoint_type="D+5",checkpoint_cutoff_utc=CTX["checkpoint_cutoff"],market_data_manifest=CTX["verified_market"],thesis_records=[{"recorded_at_utc":thesis["recorded_at_utc"],"current_thesis_state":"VALID","original_thesis_validity_state":"VALID","binding":CTX["resolved_thesis_binding"]}],thesis_records_verified=True)
    other=deepcopy(CTX["env"]); other["recommendation_binding"]["record_hash"]="b"*64; other["envelope_id"]=""; other["record_hash"]=""; other["envelope_id"]="S6PROSENV_"+canonical_hash(without(other,"envelope_id","record_hash"))[:24]; other["record_hash"]=canonical_hash(without(other,"record_hash")); CTX["different_env_id"]=other["envelope_id"]
    def leaky(key): bad=deepcopy(CTX["env"]); bad["stage6_creation_context"][key]="x"; return validate_envelope(bad)
    CTX["leaky_env"]=leaky
    CTX["future_context"]=lambda:build_recommendation_envelope(control_database=CTX["control"],prospective_database=CTX["prospective"],recommendation_id="REC1",cohort_fingerprint=CTX["cohort"],activation_record=CTX["activation_path"],stage4a3_snapshot=snapshot(),creation_context={"recorded_at_utc":"2026-10-06T10:30:00Z"},test_only_adapter=True)
    def env_conflict():
        bad=deepcopy(CTX["env"]); bad["stage6_creation_context"]={"availability":"AVAILABLE","recorded_at_utc":"2026-10-05T10:00:00Z","known_risks":[],"invalidation_conditions":[]}; bad["envelope_id"]=""; bad["record_hash"]=""; bad["envelope_id"]="S6PROSENV_"+canonical_hash(without(bad,"envelope_id","record_hash"))[:24]; bad["record_hash"]=canonical_hash(without(bad,"record_hash")); return CTX["store"].persist_envelope(bad)
    CTX["envelope_conflict"]=env_conflict
    def cp(n,sector=False,thesis=()):
        m=manifest(rows(n,sector)); return build_checkpoint(envelope=CTX["env"],checkpoint_type=f"D+{n}",checkpoint_cutoff_utc=m["observations"][-1]["session_date"]+"T11:00:00Z",market_data_manifest=m,thesis_records=thesis,test_only_adapter=True)
    CTX["cp20"]=cp(20); CTX["cp60"]=cp(60); CTX["cp_sector"]=cp(5,True)
    dd=rows(5); dd[1]["stock_close"]="120"; dd[2]["stock_close"]="108"; md=manifest(dd); CTX["cp_drawdown"]=build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=dd[-1]["session_date"]+"T11:00:00Z",market_data_manifest=md,test_only_adapter=True)
    later={"recorded_at_utc":"2026-10-20T12:00:00Z","current_thesis_state":"INVALIDATED","original_thesis_validity_state":"INVALIDATED","binding":{"record_type":"THESIS","record_id":"T2","record_hash":"H2"}}
    early={"recorded_at_utc":"2026-10-10T09:00:00Z","current_thesis_state":"VALID","original_thesis_validity_state":"VALID","binding":{"record_type":"THESIS","record_id":"T1","record_hash":"H1"}}
    CTX["cp_thesis"]=cp(5,False,[later,early])
    def missing_stock(): x=rows(5); x[-1]["stock_close"]=None; m=manifest(x); return build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=x[-1]["session_date"]+"T11:00:00Z",market_data_manifest=m,test_only_adapter=True)
    CTX["missing_stock"]=missing_stock
    def future_row(): x=rows(6); m=manifest(x); return build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=x[5]["session_date"]+"T11:00:00Z",market_data_manifest=m,test_only_adapter=True)
    CTX["future_row"]=future_row
    def future_observed(): x=rows(5); cutoff=x[-1]["session_date"]+"T11:00:00Z"; x[0]["observed_at_utc"]="2026-12-01T00:00:00Z"; m=manifest(x); return build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=cutoff,market_data_manifest=m,test_only_adapter=True)
    CTX["future_observed"]=future_observed
    def missing_nifty(): x=rows(5); x[-1]["nifty_close"]=None; m=manifest(x); return build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=x[-1]["session_date"]+"T11:00:00Z",market_data_manifest=m,test_only_adapter=True)
    CTX["missing_nifty"]=missing_nifty
    def cp_conflict():
        x=rows(5); x[-1]["stock_close"]="106"; m=manifest(x); bad=build_checkpoint(envelope=CTX["env"],checkpoint_type="D+5",checkpoint_cutoff_utc=x[-1]["session_date"]+"T11:00:00Z",market_data_manifest=m,test_only_adapter=True); return CTX["store"].persist_checkpoint(bad)
    CTX["checkpoint_conflict"]=cp_conflict
    CTX["prospective_hash_before"]=Path(CTX["prospective"]).read_bytes(); CTX["prospective_hash_after"]=lambda:Path(CTX["prospective"]).read_bytes()
    c=sqlite3.connect(CTX["control"]); tx=[]
    for tid,side,qty,day,price in (("BUY1","BUY",10,"2026-10-06","101"),("SELL1","SELL",10,CTX["m5"]["observations"][-1]["session_date"],"105")):
        p={"ticker":"AAA.NS","trade_date":day,"side":side,"quantity":qty,"price_inr":price,"fees_inr":"0","recommendation_id":"REC1","signal_id":"SIG1","external_reference":None,"notes":None}; text=canonical_json(p); c.execute("INSERT INTO user_transactions(transaction_id,idempotency_key,ticker,trade_date,side,quantity,price_inr,fees_inr,recommendation_id,signal_id,external_reference,notes,canonical_payload_json,payload_sha256,recorded_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(tid,"KEY"+tid,"AAA.NS",day,side,qty,price,"0","REC1","SIG1",None,None,text,payload_sha256(text),day+"T09:00:00Z"))
    c.commit(); c.close()
    CTX["control_hash_before"]=Path(CTX["control"]).read_bytes(); CTX["control_hash_after"]=lambda:Path(CTX["control"]).read_bytes()
    with Stage5DControlReader(CTX["control"]) as reader: CTX["final_exit"]=derive_final_exit(reader,"REC1",CTX["m5"]["observations"][-1]["session_date"]+"T11:00:00Z")
    with ProspectiveStoreReader(CTX["prospective"],CTX["activation"]) as reader: CTX["adapter_dates_override"]=reader.session_dates_through(CTX["origin_session"],CTX["final_exit"]["final_exit_date"])
    CTX["final_capture"]=capture_checkpoint_market_archive(repo_root=REPO,activation_record=CTX["activation_path"],prospective_database=CTX["prospective"],control_database=CTX["control"],observation_database=CTX["store"].database,recommendation_id="REC1",checkpoint_type="FINAL_EXIT",current_time_utc=CTX["final_exit"]["final_exit_date"]+"T11:00:00Z",acquisition_adapter=frozen_fixture_acquire,runtime_root=CTX["root"]/"final_capture_runtime",test_only_adapter=True)
    CTX.pop("adapter_dates_override")
    CTX["final_capture_manifest"]=json.loads((Path(CTX["final_capture"]["archive_directory"])/"market_archive_manifest.json").read_text())
    CTX["cp_exit"]=build_checkpoint(envelope=CTX["env"],checkpoint_type="FINAL_EXIT",checkpoint_cutoff_utc=CTX["m5"]["observations"][-1]["session_date"]+"T11:00:00Z",market_data_manifest=CTX["m5"],final_exit=CTX["final_exit"],test_only_adapter=True)
    def voided_exit():
        clone=CTX["root"] / "voided.sqlite3"; clone.write_bytes(Path(CTX["control"]).read_bytes()); c=sqlite3.connect(clone); p={"transaction_id":"SELL1","reason":"fixture"}; text=canonical_json(p); c.execute("INSERT INTO transaction_voids(void_id,transaction_id,idempotency_key,reason,voided_at_utc,canonical_payload_json,payload_sha256) VALUES('V1','SELL1','VK','fixture','2026-10-13T10:00:00Z',?,?)",(text,payload_sha256(text))); c.commit(); c.close();
        with Stage5DControlReader(clone) as reader:return derive_final_exit(reader,"REC1","2026-10-13T11:00:00Z")
    CTX["voided_exit"]=voided_exit
    def no_fill_exit():
        with Stage5DControlReader(CTX["control"]) as reader:return derive_final_exit(reader,"MISSING","2026-10-13T11:00:00Z")
    CTX["no_fill_exit"]=no_fill_exit
    empty_db=CTX["root"]/"empty_prospective.sqlite3"
    with ProspectiveValidationStore(empty_db,CTX["activation_path"]): pass
    CTX["non_enrolled_origin"]=lambda:build_recommendation_envelope(control_database=CTX["control"],prospective_database=empty_db,recommendation_id="REC1",cohort_fingerprint=CTX["cohort"],activation_record=CTX["activation_path"],stage4a3_root=REPO/"Stage 4A.3",stage4a3_prospective_root=CTX["real_snapshot_root"])
    CTX["caller_dates_production"]=lambda:determine_due_checkpoints(decision_date="2026-10-05",completed_session_dates=["2026-10-10"],test_only_adapter=False)
    def arbitrary_market_production():
        return build_checkpoint(envelope=CTX["real_env"],checkpoint_type="D+5",checkpoint_cutoff_utc=CTX["checkpoint_cutoff"],market_data_manifest=manifest(CTX["verified_rows"]))
    CTX["arbitrary_market_production"]=arbitrary_market_production
    def missing_nifty_archive():
        target=CTX["root"]/"market_missing_nifty"; make_market_archive(target,CTX["verified_rows"],target_date=CTX["target_date"],captured_at=CTX["checkpoint_cutoff"])
        with gzip.open(target/"nifty_close.csv.gz","rt",encoding="utf-8",newline="") as h: values=list(csv.DictReader(h))[:-1]
        with gzip.open(target/"nifty_close.csv.gz","wt",encoding="utf-8",newline="") as h: w=csv.DictWriter(h,fieldnames=("ticker","session_date","observed_at_utc","close"),lineterminator="\n");w.writeheader();w.writerows(values)
        doc=json.loads((target/"market_archive_manifest.json").read_text());
        for item in doc["files"]:
            if item["file"]=="nifty_close.csv.gz": item["sha256"]=_file_sha(target/item["file"]);item["bytes"]=(target/item["file"]).stat().st_size
        doc["manifest_hash"]=canonical_hash(without(doc,"manifest_hash"));(target/"market_archive_manifest.json").write_text(json.dumps(doc),encoding="utf-8")
        return MarketArchiveResolver(target).resolve(ticker="AAA.NS",anchor_date="2026-10-05",target_date=CTX["target_date"],checkpoint_cutoff_utc=CTX["checkpoint_cutoff"],verified_session_dates=CTX["verified_dates"])
    CTX["missing_nifty_archive"]=missing_nifty_archive
    def forward_checkpoint(d0_high="102",d0_low="98",d1_high="103",d1_low="99"):
        items=deepcopy(CTX["verified_rows"]);items[0]["stock_high"]=d0_high;items[0]["stock_low"]=d0_low;items[1]["stock_high"]=d1_high;items[1]["stock_low"]=d1_low
        return build_checkpoint(envelope=CTX["real_env"],checkpoint_type="D+5",checkpoint_cutoff_utc=CTX["checkpoint_cutoff"],market_data_manifest=manifest(items),test_only_adapter=True)
    CTX["forward_checkpoint"]=forward_checkpoint
    CTX["arbitrary_thesis"]=lambda:build_checkpoint(envelope=CTX["real_env"],checkpoint_type="D+5",checkpoint_cutoff_utc=CTX["checkpoint_cutoff"],market_data_manifest=CTX["verified_market"],thesis_records=[{"recorded_at_utc":CTX["target_date"]+"T10:30:00Z","current_thesis_state":"VALID","original_thesis_validity_state":"VALID","binding":{"record_type":"X","record_id":"X","record_hash":"X"}}])
    def context_wrong_hash():
        bad={**CTX["thesis_binding"],"record_hash":"0"*64}
        with Stage6ContextReader(CTX["context_db"]) as reader:return reader.resolve(bad,cutoff_utc=CTX["checkpoint_cutoff"],recommendation_id="REC1",signal_id="SIG1",ticker="AAA.NS")
    CTX["context_wrong_hash"]=context_wrong_hash
    def context_after_cutoff():
        with Stage6ContextReader(CTX["context_db"]) as reader:return reader.resolve(CTX["thesis_binding"],cutoff_utc=CTX["target_date"]+"T09:00:00Z",recommendation_id="REC1",signal_id="SIG1",ticker="AAA.NS")
    CTX["context_after_cutoff"]=context_after_cutoff
    def lifecycle_clone(name, edit):
        target=CTX["root"]/(name+".sqlite3"); shutil.copyfile(CTX["control"],target); c=sqlite3.connect(target);edit(c);c.commit();c.close();return target
    def typed_tx_mismatch():
        db=lifecycle_clone("tx_mismatch",lambda c:c.execute("UPDATE user_transactions SET side='BUY' WHERE transaction_id='SELL1'"))
        with Stage5DControlReader(db) as reader:return derive_final_exit(reader,"REC1",CTX["checkpoint_cutoff"])
    CTX["typed_tx_mismatch"]=typed_tx_mismatch
    def void_db(voided_at, mismatch=False):
        def edit(c):
            p={"transaction_id":"SELL1","reason":"payload" if mismatch else "fixture"};text=canonical_json(p);c.execute("INSERT INTO transaction_voids(void_id,transaction_id,idempotency_key,reason,voided_at_utc,canonical_payload_json,payload_sha256) VALUES('V2','SELL1','VK2','fixture',?,?,?)",(voided_at,text,payload_sha256(text)))
        return lifecycle_clone("void_"+voided_at.replace(":","_"),edit)
    def later_void_earlier():
        db=void_db("2026-12-30T10:00:00Z")
        with Stage5DControlReader(db) as reader:return derive_final_exit(reader,"REC1",CTX["m5"]["observations"][-1]["session_date"]+"T11:00:00Z")
    CTX["later_void_earlier"]=later_void_earlier
    def later_void_later():
        db=void_db("2026-12-30T10:00:00Z")
        with Stage5DControlReader(db) as reader:return derive_final_exit(reader,"REC1","2026-12-31T11:00:00Z")
    CTX["later_void_later"]=later_void_later
    def void_mismatch():
        db=void_db(CTX["target_date"]+"T10:00:00Z",True)
        with Stage5DControlReader(db) as reader:return derive_final_exit(reader,"REC1",CTX["checkpoint_cutoff"])
    CTX["void_mismatch"]=void_mismatch
    def future_trade():
        def edit(c):
            row=c.execute("SELECT canonical_payload_json FROM user_transactions WHERE transaction_id='SELL1'").fetchone();p=json.loads(row[0]);p["trade_date"]="2026-12-31";text=canonical_json(p);c.execute("UPDATE user_transactions SET trade_date='2026-12-31',canonical_payload_json=?,payload_sha256=? WHERE transaction_id='SELL1'",(text,payload_sha256(text)))
        db=lifecycle_clone("future_trade",edit)
        with Stage5DControlReader(db) as reader:return derive_final_exit(reader,"REC1",CTX["checkpoint_cutoff"])
    CTX["future_trade"]=future_trade
    def checkpoint_relationship_tamper():
        target=CTX["root"]/"obs_cp_tamper.sqlite3"; destination=sqlite3.connect(target);CTX["store"].connection.backup(destination);destination.close();c=sqlite3.connect(target);c.execute("DROP TRIGGER protect_benchmark_checkpoints_update");row=c.execute("SELECT checkpoint_id,canonical_json FROM benchmark_checkpoints LIMIT 1").fetchone();value=json.loads(row[1]);value["recommendation_audit_envelope_binding"]["record_hash"]="0"*64;value["checkpoint_id"]="";value["record_hash"]="";value["checkpoint_id"]="S6PROSCHK_"+canonical_hash(without(value,"checkpoint_id","record_hash"))[:24];value["record_hash"]=canonical_hash(without(value,"record_hash"));c.execute("UPDATE benchmark_checkpoints SET checkpoint_id=?,record_hash=?,canonical_json=? WHERE checkpoint_id=?",(value["checkpoint_id"],value["record_hash"],canonical_json(value),row[0]));c.execute("CREATE TRIGGER protect_benchmark_checkpoints_update BEFORE UPDATE ON benchmark_checkpoints BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END");c.commit();c.close()
        with ProspectiveObservationStore(target,REPO,CTX["cohort"],allow_test_runtime=True) as store:return store.integrity_check()
    CTX["checkpoint_relationship_tamper"]=checkpoint_relationship_tamper
    def envelope_cohort_tamper():
        target=CTX["root"]/"obs_env_tamper.sqlite3"
        with ProspectiveObservationStore(target,REPO,CTX["cohort"],allow_test_runtime=True) as store:store.persist_envelope(CTX["real_env"])
        c=sqlite3.connect(target);c.execute("DROP TRIGGER protect_recommendation_audit_envelopes_update");row=c.execute("SELECT envelope_id,canonical_json FROM recommendation_audit_envelopes").fetchone();value=json.loads(row[1]);value["cohort_fingerprint_binding"]["record_hash"]="0"*64;value["envelope_id"]="";value["record_hash"]="";value["envelope_id"]="S6PROSENV_"+canonical_hash(without(value,"envelope_id","record_hash"))[:24];value["record_hash"]=canonical_hash(without(value,"record_hash"));c.execute("UPDATE recommendation_audit_envelopes SET envelope_id=?,record_hash=?,canonical_json=? WHERE envelope_id=?",(value["envelope_id"],value["record_hash"],canonical_json(value),row[0]));c.execute("CREATE TRIGGER protect_recommendation_audit_envelopes_update BEFORE UPDATE ON recommendation_audit_envelopes BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END");c.commit();c.close()
        with ProspectiveObservationStore(target,REPO,CTX["cohort"],allow_test_runtime=True) as store:return store.integrity_check()
    CTX["envelope_cohort_tamper"]=envelope_cohort_tamper


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
