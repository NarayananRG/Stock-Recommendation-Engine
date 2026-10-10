from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"Live Pilot"
sys.path.insert(0,str(ROOT))

from live_pilot_core import (
    LivePilotStore,
    build_decision_envelope,
    compare_reproducibility,
    evaluate_readiness,
)

RESULTS=[]
def require(v,msg="assertion failed"):
    if not v: raise AssertionError(msg)
def case(name,fn):
    try:
        fn(); status,detail="PASS",""
    except Exception as exc:
        status,detail="FAIL",f"{type(exc).__name__}: {exc}"
    RESULTS.append({"test":name,"status":status,"detail":detail})

ready=evaluate_readiness(
    expected_production_version="0.8.0-leg8",
    actual_production_version="0.8.0-leg8",
    official_price_data_ready=True,
    market_index_data_ready=True,
    sector_data_ready=True,
    data_freshness_ready=True,
    pit_integrity_ready=True,
    database_integrity_ready=True,
    backup_ready=True,
    duplicate_run_protection_ready=True,
    capital_sizing_ready=True,
    yfinance_used=False,
)
case("all hard gates ready",lambda:require(ready.live_ready))
blocked=evaluate_readiness(
    expected_production_version="0.8.0-leg8",
    actual_production_version="0.8.0-leg8",
    official_price_data_ready=True,
    market_index_data_ready=True,
    sector_data_ready=True,
    data_freshness_ready=False,
    pit_integrity_ready=True,
    database_integrity_ready=True,
    backup_ready=True,
    duplicate_run_protection_ready=True,
    capital_sizing_ready=True,
    yfinance_used=False,
)
case("stale data blocks readiness",lambda:require(not blocked.live_ready and "data_freshness_ready" in blocked.hard_failures))

decision={
    "action":"BUY","symbol":"ABC","rank":1,"quantity":2,
    "expected_return":0.04,"probability":0.61,"risk":"MODERATE",
    "reason_codes":["HISTORICAL_EDGE","AFFORDABLE"]
}
env=build_decision_envelope(
    pilot_id="LIVE_001",production_version="0.8.0-leg8",
    capital_inr=1000,holding_sessions=21,readiness=ready,
    production_decision=decision,production_ranking=[decision],
    fundamental_v2_shadow={"event_profile":"MIXED_DIRECTIONAL"}
)
case("v2 remains shadow",lambda:require(env["fundamental_v2_shadow"]["authority"]=="SHADOW_ONLY"))
case("v2 cannot alter rank",lambda:require(env["fundamental_v2_shadow"]["production_rank_changed"] is False))
case("hash present",lambda:require(len(env["decision_hash_sha256"])==64))
env2=build_decision_envelope(
    pilot_id="LIVE_001",production_version="0.8.0-leg8",
    capital_inr=1000,holding_sessions=21,readiness=ready,
    production_decision=decision,production_ranking=[decision],
)
repro=compare_reproducibility(env,env2)
case("same production output reproduces",lambda:require(repro["exact_match"] is True))

with tempfile.TemporaryDirectory() as td:
    store=LivePilotStore(Path(td)/"pilot.sqlite")
    h=store.save_snapshot(env)
    loaded=store.load_snapshot(h)
    case("snapshot immutable store roundtrip",lambda:require(loaded["decision_hash_sha256"]==h))
    case("sqlite integrity",lambda:require(store.integrity_check()=="ok"))
    store.record_execution(
        pilot_id="LIVE_001",decision_hash=h,
        execution={"manual_execution":True,"fill_price":412.5,"quantity":2}
    )
    store.record_monitoring(
        pilot_id="LIVE_001",decision_hash=h,
        monitoring={"session":1,"lifecycle_state":"HOLD"}
    )
    store.record_reproducibility(pilot_id="LIVE_001",result=repro)
    case("manual ledger writes accepted",lambda:require(True))

failed=[x for x in RESULTS if x["status"]!="PASS"]
print({"tests":len(RESULTS),"passed":len(RESULTS)-len(failed),"failed":len(failed),"failures":failed})
if failed:
    raise SystemExit(1)
