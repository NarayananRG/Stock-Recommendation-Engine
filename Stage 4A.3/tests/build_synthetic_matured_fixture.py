from __future__ import annotations
import json,sys
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parent;sys.path.insert(0,str(ROOT))
from stage4a3.candidate_selection import rank_and_select
from stage4a3.hash_chain import genesis_hash
from stage4a3.immutable_ledger import write_snapshot
from stage4a3.outcome_resolver import append_event_batch
from stage4a3.snapshot_contract import PREDICTION_COLUMNS

TARGET=ROOT/"tests/SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE"
if TARGET.exists():raise RuntimeError("Synthetic fixture already exists; use a fresh test workspace")
(TARGET/"config").mkdir(parents=True);(TARGET/"config/stage4a3_protocol.json").write_bytes((ROOT/"config/stage4a3_protocol.json").read_bytes())
audit=TARGET/"prospective/audit";snapshots=TARGET/"prospective/snapshots";outcomes=TARGET/"prospective/outcomes";audit.mkdir(parents=True);outcomes.mkdir(parents=True)
protocol="SYNTHETIC_PROTOCOL_COMMIT";bundle="SYNTHETIC_MODEL_BUNDLE";genesis=genesis_hash(protocol,bundle);activation={"Protocol Tag":"SYNTHETIC_TEST_FIXTURE","Protocol Commit":protocol,"Model Bundle Hash":bundle,"Activation UTC":"2023-12-01T10:00:00+00:00","Activation Asia/Kolkata":"2023-12-01T15:30:00+05:30","Activation Local Date":"2023-12-01","Earliest Eligible Signal Date":"2023-12-02","Frozen Universe Hash":"SYNTHETIC_UNIVERSE","Genesis Chain Hash":genesis,"Protocol Identity":"SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE"}
(audit/"activation_record.json").write_text(json.dumps(activation,indent=2,sort_keys=True)+"\n",encoding="utf-8")
previous=genesis;all_predictions=[]
dates=pd.date_range("2024-01-01",periods=25,freq="MS")+pd.Timedelta(days=4)
for day_index,date in enumerate(dates):
    signal_date=date.date().isoformat();base=pd.DataFrame({"Signal Date":[signal_date]*6,"Signal ID":[f"SYN_{day_index:02d}_{i}" for i in range(6)],"Ticker":[f"SYN{i}.NS" for i in range(6)],"Actionability Score":[90,80,70,60,50,40],"Technical Score":[80,75,70,65,60,55],**{f"R{i} Score":[.9-j*.1+i*.001 for j in range(6)] for i in range(1,6)}});ranked=rank_and_select(base)
    pred=pd.DataFrame(index=ranked.index)
    defaults={"Protocol Version":"SYNTHETIC_TEST_FIXTURE","Protocol Commit":protocol,"Protocol Tag":"SYNTHETIC_TEST_FIXTURE","Snapshot ID":f"SYNTHETIC_{day_index:02d}","Signal Date":signal_date,"Snapshot Created UTC":f"{signal_date}T11:00:00+00:00","Snapshot Created Asia/Kolkata":f"{signal_date}T16:30:00+05:30","Original Signal":"BUY","Signal":"BUY","Setup":"PULLBACK","Market Regime":"BULL","Trade Quality":"SYNTHETIC","Planned Entry":100.,"Initial Stop":95.,"Original T1":105.,"Original T2":110.,"Dataset Cohort":"BASELINE_PRIMARY","Feature Row Hash":"SYNTHETIC_FEATURE_HASH","Model Bundle Hash":bundle,"Prediction Semantics":"SHADOW_ONLY_NO_TRADING_EFFECT"}
    for col in PREDICTION_COLUMNS:pred[col]=ranked[col] if col in ranked else defaults.get(col,ranked["Signal ID"] if col=="Signal ID" else ranked["Ticker"] if col=="Ticker" else "")
    features=pd.DataFrame({"Signal ID":ranked["Signal ID"],"Ticker":ranked["Ticker"],"Feature Row Hash":["SYNTHETIC_FEATURE_HASH"]*6});market={"fixture_semantics":"SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE","raw_data_logical_hash":"SYNTHETIC_RAW","maximum_market_data_date":signal_date,"nifty_maximum_date":signal_date};candidate={"Fixture Semantics":"SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE","Signal Date":signal_date,"Candidate Count":6}
    row=write_snapshot(snapshots,audit,signal_date,{"Snapshot ID":f"SYNTHETIC_{day_index:02d}","Snapshot Created UTC":f"{signal_date}T11:00:00+00:00","Fixture Semantics":"SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE"},pred,features,market,previous,protocol,bundle,candidate_input_manifest=candidate);previous=row["Current Chain Hash"];all_predictions.append(pred)
predictions=pd.concat(all_predictions,ignore_index=True);events=[]
def event(signal_id,signal_date,ticker,policy,target,value,label):return {"Generated UTC":"2026-02-01T00:00:00+00:00","Signal ID":signal_id,"Signal Date":signal_date,"Ticker":ticker,"Policy":policy,"Outcome Type":target,"Outcome State":"RESOLVED","Outcome Value":value,"Observation Through Date":"2026-02-01","Label Available Date":label,"Source Market Data Hash":"SYNTHETIC_MARKET","Is Terminal":True}
for i,row in predictions.iterrows():
    label=(pd.Timestamp(row["Signal Date"])+pd.Timedelta(days=30)).date().isoformat();events.append(event(row["Signal ID"],row["Signal Date"],row["Ticker"],"","ENTRY_FILLED",i%4!=0,label))
    if i%4!=0:events.append(event(row["Signal ID"],row["Signal Date"],row["Ticker"],"","T1_BEFORE_STOP_63",i%2==0,label));events.append(event(row["Signal ID"],row["Signal Date"],row["Ticker"],"","T2_BEFORE_STOP_63",i%3==0,label))
named=[f"R{r}_K{k}" for r in range(6) for k in (1,2)]
for policy in named:
    for i,row in predictions.iloc[:50].iterrows():
        net=.35 if policy=="R0_K1" else -.15 if policy=="R3_K1" else .05;fraction=net*.0075;value=json.dumps({"Net R":net,"Portfolio Return Fraction":fraction,"Net PnL":fraction*100000},sort_keys=True,separators=(",",":"));label=(pd.Timestamp(row["Signal Date"])+pd.Timedelta(days=45)).date().isoformat();events.append(event(row["Signal ID"],row["Signal Date"],row["Ticker"],policy,"D1_TRADE_COMPLETION",value,label))
        if policy in {"R0_K1","R3_K1"}:events.append(event(row["Signal ID"],row["Signal Date"],row["Ticker"],policy+"_D0","D1_TRADE_COMPLETION",value,label))
append_event_batch(outcomes,events,"2026-02-01T00:00:00+00:00",audit,"SYNTHETIC")
random=[]
for seed in range(500):
    row=predictions.iloc[seed%len(predictions)];value=json.dumps({"Net R":.1,"Portfolio Return Fraction":.00075,"Net PnL":75.},sort_keys=True,separators=(",",":"));random.append(event(row["Signal ID"],row["Signal Date"],row["Ticker"],f"RANDOM_K1_SEED_{seed:03d}","D1_TRADE_COMPLETION",value,"2026-02-01"))
append_event_batch(outcomes,random,"2026-02-01T00:00:01+00:00",audit,"SYNTHETIC")
print(json.dumps({"fixture":"SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE","snapshots":25,"candidates":len(predictions),"events":len(events)+len(random)}))
