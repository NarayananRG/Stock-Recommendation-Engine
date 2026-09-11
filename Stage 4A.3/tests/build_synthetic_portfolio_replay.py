from __future__ import annotations
import json,sys
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stage4a3.economic_methodology import midrank_percentile,paired_moving_block_bootstrap,portfolio_metrics

TARGET=ROOT/"tests/SYNTHETIC_MATURED_PROSPECTIVE_FIXTURE/tests/frozen_portfolio_replay";TARGET.mkdir(parents=True,exist_ok=True)
sessions=pd.bdate_range("2023-12-04","2026-01-30");named=[f"R{r}_K{k}" for r in range(6) for k in (1,2)]
def daily(policy,rate,engine):
    values=pd.Series(rate,index=sessions,dtype=float);equity=100000.*(1.+values).cumprod();invested=equity*(.2 if rate else 0.)
    return pd.DataFrame({"Policy":policy,"Exit Engine":engine,"Date":sessions,"Equity":equity,"Daily Return":values,"Cash":equity-invested,"Invested Value":invested,"Exposure":invested/equity,"Open Positions":1 if rate else 0})
def trades(policy,net_r,engine,count=50):
    if count==50 and net_r==.2:rs=[.3]*40+[-.2]*10
    elif count==50 and net_r==-.1:rs=[.1]*10+[-.15]*40
    elif count==50 and net_r==.05:rs=[.1]*30+[-.025]*20
    else:rs=[net_r]*count
    return pd.DataFrame({"Policy":[policy]*count,"Exit Engine":[engine]*count,"Signal ID":[f"{policy}_{i:03d}" for i in range(count)],"Ticker":["SYN.NS"]*count,"Signal Date":[sessions[min(i*5,len(sessions)-2)] for i in range(count)],"Entry Date":[sessions[min(i*5+1,len(sessions)-1)] for i in range(count)],"Exit Date":[sessions[min(i*5+2,len(sessions)-1)] for i in range(count)],"Net PnL":[value*75. for value in rs],"Net R":rs,"Costs":[1.]*count})
d1d=[];d1t=[];d0d=[];d0t=[]
for policy in named:
    rate=.00010 if policy=="R0_K1" else -.00005 if policy=="R3_K1" else .00002;d1d.append(daily(policy,rate,"D1_TRAIL_ONLY"));d1t.append(trades(policy,.2 if rate>0 else -.1,"D1_TRAIL_ONLY"))
    rate0=.00001 if policy=="R0_K1" else .000015 if policy=="R3_K1" else 0.;d0d.append(daily(policy,rate0,"D0_STATIC_COMPAT"));d0t.append(trades(policy,.05,"D0_STATIC_COMPAT"))
for seed in range(500):
    policy=f"RANDOM_K1_SEED_{seed:03d}";d1d.append(daily(policy,.00003+(seed%5)*.000001,"D1_TRAIL_ONLY"));d1t.append(trades(policy,.05,"D1_TRAIL_ONLY",1))
frames={"d1_daily.csv.gz":pd.concat(d1d,ignore_index=True),"d1_trades.csv.gz":pd.concat(d1t,ignore_index=True),"d0_daily.csv.gz":pd.concat(d0d,ignore_index=True),"d0_trades.csv.gz":pd.concat(d0t,ignore_index=True)}
for name,frame in frames.items():frame.to_csv(TARGET/name,index=False,compression={"method":"gzip","mtime":0},lineterminator="\n",float_format="%.17g")
r0=frames["d1_daily.csv.gz"].loc[frames["d1_daily.csv.gz"].Policy.eq("R0_K1")];r3=frames["d1_daily.csv.gz"].loc[frames["d1_daily.csv.gz"].Policy.eq("R3_K1")];r0t=frames["d1_trades.csv.gz"].loc[frames["d1_trades.csv.gz"].Policy.eq("R0_K1")];r3t=frames["d1_trades.csv.gz"].loc[frames["d1_trades.csv.gz"].Policy.eq("R3_K1")]
expected={"R0_K1":portfolio_metrics("R0_K1",r0,r0t),"R3_K1":portfolio_metrics("R3_K1",r3,r3t)};controls=[]
for policy,group in frames["d1_daily.csv.gz"].loc[frames["d1_daily.csv.gz"].Policy.str.startswith("RANDOM_")].groupby("Policy"):controls.append(portfolio_metrics(policy,group,frames["d1_trades.csv.gz"].loc[frames["d1_trades.csv.gz"].Policy.eq(policy)])["Total Return %"])
expected["Random Percentile"]=midrank_percentile(expected["R3_K1"]["Total Return %"],controls);boot=paired_moving_block_bootstrap(r3,r0,63,2000,42);expected["Bootstrap 63"]={"Lower 2.5%":boot["Delta Terminal Return %"].quantile(.025),"Median":boot["Delta Terminal Return %"].median(),"Upper 97.5%":boot["Delta Terminal Return %"].quantile(.975),"P(Delta > 0) %":boot["Delta Terminal Return %"].gt(0).mean()*100}
(TARGET/"expected_results.json").write_text(json.dumps(expected,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8");print(json.dumps({"sessions":len(sessions),"d1_rows":len(frames["d1_daily.csv.gz"])}))
