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

# Independently specified daily-equity fixture.  It exercises the accepted
# portfolio metric/bootstrap calculations without pretending synthetic bars are
# production market data or allowing this path outside tests.
replay=TARGET/"tests/frozen_portfolio_replay";replay.mkdir(parents=True)
sessions=pd.bdate_range("2023-12-04","2026-01-30")
named=[f"R{r}_K{k}" for r in range(6) for k in (1,2)]
def daily(policy,rate,engine):
    values=pd.Series(rate,index=sessions,dtype=float);equity=100000.*(1.+values).cumprod();invested=equity*(.2 if rate else 0.)
    return pd.DataFrame({"Policy":policy,"Exit Engine":engine,"Date":sessions,"Equity":equity,"Daily Return":values,"Cash":equity-invested,"Invested Value":invested,"Exposure":invested/equity,"Open Positions":1 if rate else 0})
def trades(policy,net_r,engine,count=50):
    if count==50 and net_r==.2:rs=[.3]*40+[-.2]*10
    elif count==50 and net_r==-.1:rs=[.1]*10+[-.15]*40
    elif count==50 and net_r==.05:rs=[.1]*30+[-.025]*20
    else:rs=[net_r]*count
    return pd.DataFrame({"Policy":[policy]*count,"Exit Engine":[engine]*count,"Signal ID":[f"{policy}_{i:03d}" for i in range(count)],"Ticker":["SYN.NS"]*count,"Signal Date":[sessions[min(i*5,len(sessions)-2)] for i in range(count)],"Entry Date":[sessions[min(i*5+1,len(sessions)-1)] for i in range(count)],"Exit Date":[sessions[min(i*5+2,len(sessions)-1)] for i in range(count)],"Net PnL":[value*75. for value in rs],"Net R":rs,"Costs":[1.]*count})
d1_daily=[];d1_trades=[];d0_daily=[];d0_trades=[]
for policy in named:
    rate=.00010 if policy=="R0_K1" else -.00005 if policy=="R3_K1" else .00002
    d1_daily.append(daily(policy,rate,"D1_TRAIL_ONLY"));d1_trades.append(trades(policy,.2 if rate>0 else -.1,"D1_TRAIL_ONLY"))
    d0rate=.00001 if policy=="R0_K1" else .000015 if policy=="R3_K1" else 0.
    d0_daily.append(daily(policy,d0rate,"D0_STATIC_COMPAT"));d0_trades.append(trades(policy,.05,"D0_STATIC_COMPAT"))
for seed in range(500):
    policy=f"RANDOM_K1_SEED_{seed:03d}";rate=.00003+(seed%5)*.000001
    d1_daily.append(daily(policy,rate,"D1_TRAIL_ONLY"));d1_trades.append(trades(policy,.05,"D1_TRAIL_ONLY",1))
frames={"d1_daily.csv.gz":pd.concat(d1_daily,ignore_index=True),"d1_trades.csv.gz":pd.concat(d1_trades,ignore_index=True),"d0_daily.csv.gz":pd.concat(d0_daily,ignore_index=True),"d0_trades.csv.gz":pd.concat(d0_trades,ignore_index=True)}
for name,frame in frames.items():frame.to_csv(replay/name,index=False,compression={"method":"gzip","mtime":0},lineterminator="\n",float_format="%.17g")
from stage4a3.economic_methodology import midrank_percentile,paired_moving_block_bootstrap,portfolio_metrics
r0=frames["d1_daily.csv.gz"].loc[frames["d1_daily.csv.gz"]["Policy"].eq("R0_K1")];r3=frames["d1_daily.csv.gz"].loc[frames["d1_daily.csv.gz"]["Policy"].eq("R3_K1")]
r0t=frames["d1_trades.csv.gz"].loc[frames["d1_trades.csv.gz"]["Policy"].eq("R0_K1")];r3t=frames["d1_trades.csv.gz"].loc[frames["d1_trades.csv.gz"]["Policy"].eq("R3_K1")]
expected={"R0_K1":portfolio_metrics("R0_K1",r0,r0t),"R3_K1":portfolio_metrics("R3_K1",r3,r3t)}
controls=[]
for policy,group in frames["d1_daily.csv.gz"].loc[frames["d1_daily.csv.gz"]["Policy"].str.startswith("RANDOM_")].groupby("Policy"):controls.append(portfolio_metrics(policy,group,frames["d1_trades.csv.gz"].loc[frames["d1_trades.csv.gz"]["Policy"].eq(policy)])["Total Return %"])
expected["Random Percentile"]=midrank_percentile(expected["R3_K1"]["Total Return %"],controls)
boot=paired_moving_block_bootstrap(r3,r0,63,2000,42);expected["Bootstrap 63"]={"Lower 2.5%":boot["Delta Terminal Return %"].quantile(.025),"Median":boot["Delta Terminal Return %"].median(),"Upper 97.5%":boot["Delta Terminal Return %"].quantile(.975),"P(Delta > 0) %":boot["Delta Terminal Return %"].gt(0).mean()*100}
(replay/"expected_results.json").write_text(json.dumps(expected,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
print(json.dumps({"fixture":"SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE","snapshots":25,"candidates":len(predictions),"events":len(events)+len(random),"portfolio_sessions":len(sessions)}))
