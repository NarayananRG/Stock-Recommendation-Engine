from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def normalize_daily(result: dict[str, Any], policy: str, exit_engine: str) -> pd.DataFrame:
    frame=result["equity"].copy().sort_values("Date").reset_index(drop=True)
    frame["Date"]=pd.to_datetime(frame["Date"]).dt.normalize()
    frame=frame.rename(columns={"Total Equity":"Equity","Open Position Value":"Invested Value","Number Open Positions":"Open Positions"})
    frame["Exposure"]=(pd.to_numeric(frame["Invested Value"])/pd.to_numeric(frame["Equity"])).fillna(0.)
    frame["Daily Return"]=pd.to_numeric(frame["Daily Return %"],errors="coerce").fillna(0.)/100.
    frame["Realized PnL"]=0.;frame["Costs"]=0.
    trades=result.get("trades",pd.DataFrame()).copy()
    if not trades.empty:
        zero=pd.Series(0.,index=trades.index)
        entry_transaction=pd.to_numeric(trades.get("Entry Transaction Cost",zero),errors="coerce").fillna(0)
        exit_transaction=pd.to_numeric(trades.get("Exit Transaction Cost",zero),errors="coerce").fillna(0)
        entry_slippage=pd.to_numeric(trades.get("Entry Slippage Cost",zero),errors="coerce").fillna(0)
        exit_slippage=pd.to_numeric(trades.get("Exit Slippage Cost",trades.get("Slippage Cost",zero)),errors="coerce").fillna(0)
        costs=pd.concat([pd.DataFrame({"Date":pd.to_datetime(trades["Entry Date"]).dt.normalize(),"Cost":entry_transaction+entry_slippage}),pd.DataFrame({"Date":pd.to_datetime(trades["Exit Date"]).dt.normalize(),"Cost":exit_transaction+exit_slippage})]).groupby("Date")["Cost"].sum()
        realized=pd.DataFrame({"Date":pd.to_datetime(trades["Exit Date"]).dt.normalize(),"PnL":pd.to_numeric(trades["Net PnL"],errors="coerce").fillna(0)}).groupby("Date")["PnL"].sum()
        frame["Costs"]=frame["Date"].map(costs).fillna(0.);frame["Realized PnL"]=frame["Date"].map(realized).fillna(0.)
    frame["Policy"]=policy;frame["Exit Engine"]=exit_engine
    return frame[["Policy","Exit Engine","Date","Equity","Daily Return %","Daily Return","Cash","Invested Value","Exposure","Open Positions","Realized PnL","Costs"]]


def enrich_trades(result: dict[str, Any], policy: str, exit_engine: str, membership: pd.DataFrame) -> pd.DataFrame:
    frame=result.get("trades",pd.DataFrame()).copy()
    if frame.empty:return frame
    frame["Signal Date"]=pd.to_datetime(frame["Signal Date"]).dt.normalize()
    if "Signal ID" not in frame:
        key=membership[["Signal ID","Ticker","Signal Date"]].copy();key["Signal Date"]=pd.to_datetime(key["Signal Date"]).dt.normalize()
        frame=frame.merge(key,on=["Ticker","Signal Date"],how="left",validate="many_to_one")
    lookup=membership.assign(**{"Signal ID":membership["Signal ID"].astype(str)}).set_index("Signal ID");ids=frame["Signal ID"].astype(str)
    if "Initial Stop" not in frame and "Stop" in frame:frame["Initial Stop"]=frame["Stop"]
    if "Original T1" not in frame:frame["Original T1"]=ids.map(lookup["Target 1"])
    if "Original T2" not in frame:frame["Original T2"]=ids.map(lookup["Target 2"])
    frame["Policy"]=policy;frame["Exit Engine"]=exit_engine
    code=policy.split("_K")[0]
    frame["Selection Rank"]=ids.map(lookup.get(f"{code} Rank",pd.Series(dtype=float))) if policy.startswith("R") else np.nan
    frame["Selection Score"]=ids.map(lookup.get(f"{code} Score",pd.Series(dtype=float))) if policy.startswith("R") else np.nan
    frame["Daily K"]=int(policy[-1]) if policy.endswith(("K1","K2")) else "ALL"
    frame["Same-Date Candidate Count"]=ids.map(lookup.get("Same-Date Candidate Count",pd.Series(dtype=float)))
    frame["Net R"]=pd.to_numeric(frame.get("R Multiple"),errors="coerce")
    frame["Holding Sessions"]=pd.to_numeric(frame.get("Bars Held"),errors="coerce")
    zero=pd.Series(0.,index=frame.index)
    frame["Costs"]=pd.to_numeric(frame.get("Slippage Cost",zero),errors="coerce").fillna(0)+pd.to_numeric(frame.get("Transaction Cost",zero),errors="coerce").fillna(0)
    return frame


def portfolio_metrics(policy: str, daily: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
    equity=daily.sort_values("Date").reset_index(drop=True)
    if equity.empty:raise RuntimeError("EMPTY_DAILY_PORTFOLIO")
    start=100000.;ending=float(equity["Equity"].iloc[-1]);years=max((equity["Date"].iloc[-1]-equity["Date"].iloc[0]).days/365.25,1/365.25)
    curve=pd.to_numeric(equity["Equity"],errors="raise").astype(float);dd=curve/curve.cummax()-1
    returns=pd.to_numeric(equity["Daily Return"],errors="raise").astype(float)
    pnl=pd.to_numeric(trades.get("Net PnL",pd.Series(dtype=float)),errors="coerce").dropna();r=pd.to_numeric(trades.get("Net R",pd.Series(dtype=float)),errors="coerce").dropna()
    loss=float(-pnl[pnl<0].sum());gain=float(pnl[pnl>0].sum())
    return {"Policy":policy,"Starting Equity":start,"Ending Equity":ending,"Total Return %":(ending/start-1)*100,"CAGR %":((ending/start)**(1/years)-1)*100,"Maximum Drawdown %":float(dd.min()*100),"Mean Daily Return %":float(returns.mean()*100),"Annualized Volatility %":float(returns.std(ddof=1)*math.sqrt(252)*100),"Average Exposure %":float(pd.to_numeric(equity["Exposure"]).mean()*100),"Trade Count":len(trades),"Expectancy R":float(r.mean()) if len(r) else np.nan,"Profit Factor":gain/loss if loss else np.nan,"Total Costs":float(pd.to_numeric(trades.get("Costs",pd.Series(dtype=float)),errors="coerce").fillna(0).sum())}


def paired_moving_block_bootstrap(r3_daily: pd.DataFrame, r0_daily: pd.DataFrame, block_length: int,
                                  replicates: int=2000, seed: int=42) -> pd.DataFrame:
    columns=["Date","Daily Return","Exposure"]
    left=r3_daily[columns].rename(columns={"Daily Return":"R3 Return","Exposure":"R3 Exposure"})
    right=r0_daily[columns].rename(columns={"Daily Return":"R0 Return","Exposure":"R0 Exposure"})
    aligned=right.merge(left,on="Date",how="inner",validate="one_to_one").sort_values("Date")
    if len(aligned)!=len(left) or len(aligned)!=len(right):raise RuntimeError("PAIRED_DAILY_CALENDAR_MISMATCH")
    n=len(aligned)
    if block_length>n:raise ValueError("BLOCK_LENGTH_EXCEEDS_DAILY_CALENDAR")
    rng=np.random.default_rng(seed);rows=[];max_start=n-block_length
    def metrics(values:np.ndarray,exposure:np.ndarray)->dict[str,float]:
        wealth=np.cumprod(1+values);total=float(wealth[-1]-1);dd=wealth/np.maximum.accumulate(wealth)-1;years=n/252
        return {"Terminal Return %":total*100,"CAGR %":((1+total)**(1/years)-1)*100,"Mean Daily Return %":float(values.mean()*100),"Annualized Volatility %":float(values.std(ddof=1)*math.sqrt(252)*100),"Maximum Drawdown %":float(dd.min()*100),"Average Exposure %":float(exposure.mean()*100)}
    for replicate in range(replicates):
        starts=rng.integers(0,max_start+1,size=math.ceil(n/block_length));indices=np.concatenate([np.arange(start,start+block_length) for start in starts])[:n]
        r0=metrics(aligned["R0 Return"].to_numpy(float)[indices],aligned["R0 Exposure"].to_numpy(float)[indices]);r3=metrics(aligned["R3 Return"].to_numpy(float)[indices],aligned["R3 Exposure"].to_numpy(float)[indices])
        row={"Replicate":replicate,"Block Length":block_length,"Sample Length":n}
        for name in r3:row[f"R0_K1 {name}"]=r0[name];row[f"R3_K1 {name}"]=r3[name];row[f"Delta {name}"]=r3[name]-r0[name]
        rows.append(row)
    return pd.DataFrame(rows)


def midrank_percentile(value: float, controls: np.ndarray | pd.Series) -> float:
    values=np.asarray(controls,dtype=float)
    return float((np.sum(values<value)+.5*np.sum(values==value))/len(values)*100) if len(values) else np.nan
