"""Research diagnostics that do not alter Stage 2B trading behavior."""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd

from calibration import resolve
from policies import POLICIES, PolicyConfig, decide_after_close


def enrich_exit_day_ambiguity(trades: pd.DataFrame) -> pd.DataFrame:
    frame = trades.copy()
    reasons = frame.get("Exit Reason", pd.Series("", index=frame.index)).astype(str)
    unambiguous = reasons.str.startswith("GAP") | reasons.isin([
        "END_OF_DATA", "EXIT_MAX_63D", "EXIT_DAILY_TREND_DETERIORATION",
        "EXIT_WEEKLY_TREND_DETERIORATION", "EXIT_STALE_TRADE",
    ])
    frame["Exit Day Intraday Ordering Ambiguous"] = ~unambiguous
    frame["Exit Day MFE/MAE Convention"] = np.where(
        unambiguous, "FULL_EXIT_BAR_UNAMBIGUOUS", "FULL_EXIT_BAR_LEGACY_INTRADAY_AMBIGUOUS"
    )
    frame["MFE R Full Bar"] = pd.to_numeric(frame.get("MFE R"), errors="coerce")
    frame["MAE R Full Bar"] = pd.to_numeric(frame.get("MAE R"), errors="coerce")
    frame["MFE R Pre Exit Conservative"] = frame["MFE R Full Bar"].where(unambiguous)
    frame["MAE R Pre Exit Conservative"] = frame["MAE R Full Bar"].where(unambiguous)
    # Exact stable schema requested for future Stage 3 exclusion logic.
    frame["EXIT_DAY_SEQUENCE_AMBIGUOUS"] = frame["Exit Day Intraday Ordering Ambiguous"]
    frame["MFE_R_FULL_BAR_DIAGNOSTIC"] = frame["MFE R Full Bar"]
    frame["MAE_R_FULL_BAR_DIAGNOSTIC"] = frame["MAE R Full Bar"]
    frame["MFE_R_PRE_EXIT_CONSERVATIVE"] = frame["MFE R Pre Exit Conservative"]
    frame["MAE_R_PRE_EXIT_CONSERVATIVE"] = frame["MAE R Pre Exit Conservative"]
    return frame


def full_run_invariants(
    trades: pd.DataFrame,
    legs: pd.DataFrame,
    orders: pd.DataFrame,
    management: pd.DataFrame,
    results: Sequence[Dict[str, Any]],
) -> pd.DataFrame:
    checks: List[Tuple[str, str, bool, str]] = []
    add = lambda kind, name, ok, evidence: checks.append((kind, name, bool(ok), str(evidence)))
    add("FULL_RUN_INVARIANT", "all trades have Signal ID", trades["Signal ID"].astype(str).str.len().gt(0).all(), int(trades["Signal ID"].astype(str).str.len().eq(0).sum()))
    add("FULL_RUN_INVARIANT", "Trade ID unique", not trades["Trade ID"].duplicated().any(), int(trades["Trade ID"].duplicated().sum()))
    add("FULL_RUN_INVARIANT", "Exit Leg ID unique", not legs["Exit Leg ID"].duplicated().any(), int(legs["Exit Leg ID"].duplicated().sum()))
    leg_qty = legs.groupby("Trade ID")["Quantity"].sum()
    initial_qty = trades.set_index("Trade ID")["Quantity"]
    qty_ok = leg_qty.reindex(initial_qty.index).eq(initial_qty).all()
    add("FULL_RUN_INVARIANT", "exit-leg quantities reconcile", qty_ok, int((leg_qty.reindex(initial_qty.index) != initial_qty).sum()))
    leg_identity = (
        pd.to_numeric(legs["Gross PnL"]) - pd.to_numeric(legs["Slippage Cost"])
        - pd.to_numeric(legs["Transaction Cost"]) - pd.to_numeric(legs["Net PnL"])
    ).abs()
    add("FULL_RUN_INVARIANT", "leg PnL accounting identity", leg_identity.max() < 1e-8, leg_identity.max())
    leg_net = legs.groupby("Trade ID")["Net PnL"].sum()
    trade_net = trades.set_index("Trade ID")["Net PnL"]
    pnl_delta = (leg_net.reindex(trade_net.index) - trade_net).abs()
    add("FULL_RUN_INVARIANT", "trade PnL equals leg sum", pnl_delta.max() < 1e-8, pnl_delta.max())
    add("FULL_RUN_INVARIANT", "stops never decrease", (pd.to_numeric(management["New Stop"]) + 1e-12 >= pd.to_numeric(management["Previous Stop"])).all(), int((pd.to_numeric(management["New Stop"]) + 1e-12 < pd.to_numeric(management["Previous Stop"])).sum()))
    target_ok = (pd.to_numeric(management["New Target"]) <= pd.to_numeric(management["Previous Target"]) + 1e-12) & (pd.to_numeric(management["New Target"]) <= pd.to_numeric(management["Original T2"]) + 1e-12)
    add("FULL_RUN_INVARIANT", "targets never extend", target_ok.all(), int((~target_ok).sum()))
    effective = pd.to_datetime(management["Effective Date"], errors="coerce")
    decisions = pd.to_datetime(management["Date"], errors="coerce")
    add("FULL_RUN_INVARIANT", "after-close actions are D+1 only", (effective > decisions).all(), int((effective <= decisions).sum()))
    cal_end = pd.to_datetime(trades["Calibration Data End Date"], errors="coerce")
    entry = pd.to_datetime(trades["Entry Date"], errors="coerce")
    add("FULL_RUN_INVARIANT", "calibration data strictly precedes entry", (cal_end.isna() | (cal_end < entry)).all(), int((cal_end.notna() & (cal_end >= entry)).sum()))
    add("FULL_RUN_INVARIANT", "positive leg quantities", pd.to_numeric(legs["Quantity"]).gt(0).all(), int(pd.to_numeric(legs["Quantity"]).le(0).sum()))
    add("FULL_RUN_INVARIANT", "maximum five open positions", max(item["max_concurrent_positions"] for item in results) <= 5, max(item["max_concurrent_positions"] for item in results))
    for item in results:
        equity = item["equity"]
        identity = (pd.to_numeric(equity["Cash"]) + pd.to_numeric(equity["Open Position Value"]) - pd.to_numeric(equity["Total Equity"])).abs()
        add("FULL_RUN_INVARIANT", f"daily accounting identity: {item['variant']}", identity.max() < 1e-8, identity.max())
        add("FULL_RUN_INVARIANT", f"no negative cash: {item['variant']}", pd.to_numeric(equity["Cash"]).min() >= -1e-8, pd.to_numeric(equity["Cash"]).min())
    return pd.DataFrame([{"Type": kind, "Check": name, "Status": "PASS" if ok else "FAIL", "Evidence": evidence} for kind, name, ok, evidence in checks])


def period_summaries(results: Sequence[Dict[str, Any]], starting_equity: float = 100000.0) -> Tuple[pd.DataFrame, pd.DataFrame]:
    yearly: List[Dict[str, Any]] = []; periods: List[Dict[str, Any]] = []
    definitions = [("2016-2020", 2016, 2020), ("2021-2023", 2021, 2023), ("2024-2026", 2024, 2026)]
    for item in results:
        equity = item["equity"].copy().sort_values("Date")
        equity["Date"] = pd.to_datetime(equity["Date"]); equity["Year"] = equity["Date"].dt.year
        prior_equity = starting_equity
        for year, group in equity.groupby("Year", sort=True):
            end = float(group["Total Equity"].iloc[-1])
            yearly.append({"Policy": item["variant"], "Year": int(year), "Start Equity (Prior Session)": prior_equity,
                           "End Equity": end, "Return %": 100 * (end / prior_equity - 1),
                           "First Session": group["Date"].iloc[0], "Last Session": group["Date"].iloc[-1]})
            prior_equity = end
        for label, first_year, last_year in definitions:
            group = equity[equity["Year"].between(first_year, last_year)]
            if group.empty: continue
            earlier = equity[equity["Date"] < group["Date"].iloc[0]]
            start = float(earlier["Total Equity"].iloc[-1]) if not earlier.empty else starting_equity
            end = float(group["Total Equity"].iloc[-1])
            periods.append({"Policy": item["variant"], "Period": label, "Start Equity (Prior Session)": start,
                            "End Equity": end, "Return %": 100 * (end / start - 1),
                            "First Session": group["Date"].iloc[0], "Last Session": group["Date"].iloc[-1]})
    return pd.DataFrame(yearly), pd.DataFrame(periods)


def drawdown_summary(results: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    rows=[]
    for item in results:
        equity=item["equity"].copy().sort_values("Date").reset_index(drop=True); equity["Date"]=pd.to_datetime(equity["Date"])
        values=pd.to_numeric(equity["Total Equity"]); peak=values.cummax(); dd=values/peak-1; trough=int(dd.idxmin())
        peak_value=float(peak.loc[trough]); peak_candidates=equity.index[(values==peak_value)&(equity.index<=trough)]
        peak_idx=int(peak_candidates[-1]); recovery_candidates=equity.index[(equity.index>trough)&(values>=peak_value)]
        recovery_idx=int(recovery_candidates[0]) if len(recovery_candidates) else None
        underwater=(dd<0).astype(int); runs=underwater.groupby((underwater!=underwater.shift()).cumsum()).cumsum()
        rows.append({"Policy":item["variant"],"Maximum Drawdown %":100*float(dd.min()),"Peak Date":equity.loc[peak_idx,"Date"],
                     "Trough Date":equity.loc[trough,"Date"],"Recovery Date":equity.loc[recovery_idx,"Date"] if recovery_idx is not None else pd.NaT,
                     "Peak-to-Trough Sessions":int(equity.index.get_loc(trough)-equity.index.get_loc(peak_idx)),
                     "Recovery Sessions":int(equity.index.get_loc(recovery_idx)-equity.index.get_loc(trough)) if recovery_idx is not None else np.nan,
                     "Longest Underwater Duration Sessions":int(runs.max())})
    return pd.DataFrame(rows)


def calibration_predictions(outcomes: pd.DataFrame, tables: pd.DataFrame, evaluation_start: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    source=outcomes[pd.to_datetime(outcomes["Signal Date"])>=pd.Timestamp(evaluation_start)].copy()
    rows=[]
    for _, row in source.iterrows():
        year=pd.Timestamp(row["Signal Date"]).year; prediction=resolve(tables,row.to_dict(),year)
        rows.append({"Signal ID":row.get("Signal ID"),"Ticker":row["Ticker"],"Signal Date":row["Signal Date"],"Entry Date":row.get("Entry Date"),"Calibration Year":year,
                     "Calibration As-Of Date":prediction["as_of"],"Calibration Data End Date":prediction["data_end"],
                     "Cohort":prediction["cohort"],"Cohort Level":prediction["level"],"Sample Size":prediction["n"],
                     "Predicted P(T1 Before Stop)":prediction["p_t1"],"Actual T1 Success":bool(row["T1 Success"]),
                     "Predicted P(T2 Before Stop)":prediction["p_t2"],"Actual T2 Success":bool(row["T2 Success"])})
    predictions=pd.DataFrame(rows)
    quality=[]; buckets=[]
    for target in ("T1","T2"):
        p=pd.to_numeric(predictions[f"Predicted P({target} Before Stop)"],errors="coerce"); y=predictions[f"Actual {target} Success"].astype(float); valid=p.notna()
        groups=[("OVERALL",predictions.index)]
        groups += [(str(int(year)), index) for year,index in predictions.groupby("Calibration Year").groups.items()]
        for label,index in groups:
            pg=p.loc[index]; yg=y.loc[index]; vg=pg.notna()
            quality.append({"Evaluation Year":label,"Target":target,"Predictions":int(vg.sum()),"Brier Score":float(((pg[vg]-yg[vg])**2).mean()) if vg.any() else np.nan,
                            "Mean Predicted Probability":float(pg[vg].mean()) if vg.any() else np.nan,"Observed Success Rate":float(yg[vg].mean()) if vg.any() else np.nan})
        temp=pd.DataFrame({"p":p[valid],"y":y[valid]}); temp["Probability Bucket"]=pd.cut(temp["p"],np.linspace(0,1,11),include_lowest=True)
        for bucket,group in temp.groupby("Probability Bucket",observed=False):
            mean_prediction=group["p"].mean(); actual=group["y"].mean()
            buckets.append({"Target":target,"Probability Bucket":str(bucket),"Count":len(group),"Mean Prediction":mean_prediction,"Observed Success Rate":actual,
                            "Calibration Error":actual-mean_prediction if len(group) else np.nan})
    return predictions,pd.DataFrame(quality),pd.DataFrame(buckets)


def _future_window(trade: pd.Series, features: Dict[str,pd.DataFrame], sessions: int | None = None) -> pd.DataFrame:
    frame=features[str(trade["Ticker"])]; exit_date=pd.Timestamp(trade["Exit Date"]).normalize()
    remaining=max(int(trade.get("Original Maximum Horizon",63))-int(trade["Bars Held"]),0)
    count=remaining if sessions is None else min(remaining,sessions)
    return frame.loc[frame.index>exit_date].iloc[:count]


def management_summaries(trades: pd.DataFrame, legs: pd.DataFrame, management: pd.DataFrame, features: Dict[str,pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    stop_rows=[]
    revisions=management[pd.to_numeric(management["New Stop"])>pd.to_numeric(management["Previous Stop"])+1e-12].copy().sort_values(["Trade ID","Date"])
    first=revisions.groupby("Trade ID",as_index=False).first() if not revisions.empty else pd.DataFrame()
    for policy,group in trades.groupby("Policy"):
        policy_revisions=revisions[revisions["Policy"]==policy]; first_policy=first[first["Policy"]==policy] if not first.empty else first
        raised_stop=group[(pd.to_numeric(group["Final Stop"])>pd.to_numeric(group["Initial Stop"])+1e-12)&group["Exit Reason"].astype(str).str.contains("STOP")]
        later_t2=0; later_loss=0
        for _,trade in raised_stop.iterrows():
            future=_future_window(trade,features); later_t2+=int(not future.empty and (pd.to_numeric(future["High"])>=float(trade["Original T2"])).any())
            later_loss+=int(not future.empty and (pd.to_numeric(future["Low"])<=float(trade["Initial Stop"])).any())
        stop_rows.append({"Policy":policy,"Total Trades":len(group),"Average Stop Revisions":group["Stop Revision Count"].mean(),"Median Stop Revisions":group["Stop Revision Count"].median(),
                          "% With No Stop Revision":100*(group["Stop Revision Count"]==0).mean(),"% With At Least One Stop Revision":100*(group["Stop Revision Count"]>0).mean(),
                          "Break-Even Trigger Count":int((policy_revisions["Reason"]=="BREAK_EVEN_TRIGGERED").sum()),"Break-Even Trigger %":100*(policy_revisions["Reason"]=="BREAK_EVEN_TRIGGERED").sum()/max(len(group),1),
                          "First Stop Revision Average DaysHeld":first_policy["Days Held"].mean() if not first_policy.empty else np.nan,
                          "First Stop Revision Median DaysHeld":first_policy["Days Held"].median() if not first_policy.empty else np.nan,
                          "First Stop Revision Average CurrentR":first_policy["Current R"].mean() if not first_policy.empty else np.nan,
                          "SuperTrend Stop-Revision Count":int((policy_revisions["Reason"]=="TRAIL_SUPERTREND").sum()),"SwingLow Stop-Revision Count":int((policy_revisions["Reason"]=="TRAIL_SWING_LOW").sum()),
                          "BreakEven Stop-Revision Count":int((policy_revisions["Reason"]=="BREAK_EVEN_TRIGGERED").sum()),"Raised-Stop Exits":len(raised_stop),
                          "Possible Later-Winner Cut-Off Rate %":100*later_t2/max(len(raised_stop),1),"Protected-From-Later-Loss Rate %":100*later_loss/max(len(raised_stop),1),
                          "Counterfactual Label":"POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY"})

    partial_rows=[]
    for policy in ("D3_PARTIAL_T1_TRAIL","D4_TREND_PROTECT","D5_RESISTANCE_TIGHTEN","D6_HYBRID_DYNAMIC"):
        group=trades[trades["Policy"]==policy]; partial_ids=set(group.loc[group["Partial Profit Taken"],"Trade ID"]); records=[]
        for trade_id in partial_ids:
            trade=group[group["Trade ID"]==trade_id].iloc[0]; trade_legs=legs[legs["Trade ID"]==trade_id].sort_values("Exit Date"); first_leg=trade_legs[trade_legs["Exit Reason"]=="T1_PARTIAL"].iloc[0]; remainder=trade_legs.iloc[-1]
            dates=features[str(trade["Ticker"])].index; post_partial=int(((dates>pd.Timestamp(first_leg["Exit Date"]))&(dates<=pd.Timestamp(trade["Exit Date"]))).sum())
            records.append({"Partial Quantity %":100*float(first_leg["Quantity"])/float(trade["Quantity"]),"First Leg R":first_leg["R Multiple"],"Remainder R":remainder["R Multiple"],
                            "Total R":trade["R Multiple"],"Incremental Exit Transaction Cost":first_leg["Exit Transaction Cost"],"Incremental Exit Slippage":first_leg["Exit Slippage Cost"],
                            "Sessions After Partial":post_partial,"Remainder Reached T2":str(remainder["Exit Reason"])=="EXIT_T2","Remainder Later Stopped":"STOP" in str(remainder["Exit Reason"])})
        record=pd.DataFrame(records)
        partial_rows.append({"Policy":policy,"Trades":len(group),"Trades With T1 Partial":len(record),"Partial Rate %":100*len(record)/max(len(group),1),
                             "Average Partial Quantity %":record["Partial Quantity %"].mean() if not record.empty else np.nan,"Average First-Leg Realized R":record["First Leg R"].mean() if not record.empty else np.nan,
                             "Median First-Leg R":record["First Leg R"].median() if not record.empty else np.nan,"Average Remainder Realized R":record["Remainder R"].mean() if not record.empty else np.nan,
                             "Median Remainder R":record["Remainder R"].median() if not record.empty else np.nan,"Average Total Trade R":record["Total R"].mean() if not record.empty else np.nan,
                             "Total Extra Transaction Cost From Partial Legs":record["Incremental Exit Transaction Cost"].sum() if not record.empty else 0,
                             "Total Extra Slippage From Partial Legs":record["Incremental Exit Slippage"].sum() if not record.empty else 0,
                             "Average Holding Sessions After Partial":record["Sessions After Partial"].mean() if not record.empty else np.nan,
                             "% Remainder Reaching T2":100*record["Remainder Reached T2"].mean() if not record.empty else np.nan,
                             "% Remainder Later Stopped":100*record["Remainder Later Stopped"].mean() if not record.empty else np.nan})

    target_rows=[]
    target_revisions=management[pd.to_numeric(management["New Target"])<pd.to_numeric(management["Previous Target"])-1e-12].copy()
    for policy in ("D5_RESISTANCE_TIGHTEN","D6_HYBRID_DYNAMIC"):
        group=trades[trades["Policy"]==policy]; revisions_policy=target_revisions[target_revisions["Policy"]==policy]
        revised=group[group["Target Revision Count"]>0].copy(); reduction=100*(pd.to_numeric(revised["Original T2"])-pd.to_numeric(revised["Final Active Target"]))/pd.to_numeric(revised["Original T2"])
        reduction_r=(pd.to_numeric(revised["Original T2"])-pd.to_numeric(revised["Final Active Target"]))/pd.to_numeric(revised["Initial Risk Per Share"])
        exits=group[group["Exit Reason"]=="EXIT_DYNAMIC_TARGET"]; later_t2=0
        for _,trade in exits.iterrows():
            future=_future_window(trade,features); later_t2+=int(not future.empty and (pd.to_numeric(future["High"])>=float(trade["Original T2"])).any())
        target_rows.append({"Policy":policy,"Trades With Target Revision":len(revised),"Total Target Revisions":len(revisions_policy),"Average Revisions Per Trade":len(revisions_policy)/max(len(group),1),
                            "Average Target Reduction %":reduction.mean(),"Median Target Reduction %":reduction.median(),"Average Target Reduction R":reduction_r.mean(),
                            "Final Dynamic-Target Exits":len(exits),"Average R Dynamic-Target Exits":exits["R Multiple"].mean(),
                            "Original T2 Later Reached Count":later_t2,"Original T2 Later Reached %":100*later_t2/max(len(exits),1),
                            "Counterfactual Label":"POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY"})

    trend_rows=[]; trend_reasons={"EXIT_DAILY_TREND_DETERIORATION","EXIT_WEEKLY_TREND_DETERIORATION","EXIT_STALE_TRADE"}
    for policy in ("D4_TREND_PROTECT","D6_HYBRID_DYNAMIC"):
        group=trades[(trades["Policy"]==policy)&trades["Exit Reason"].isin(trend_reasons)]; record={"Policy":policy,"Daily Trend-Exit Count":int((group["Exit Reason"]=="EXIT_DAILY_TREND_DETERIORATION").sum()),
          "Weekly Trend-Exit Count":int((group["Exit Reason"]=="EXIT_WEEKLY_TREND_DETERIORATION").sum()),"Stale-Exit Count":int((group["Exit Reason"]=="EXIT_STALE_TRADE").sum()),
          "Average R At Exit":group["R Multiple"].mean(),"Median R At Exit":group["R Multiple"].median(),"Win Rate %":100*(group["Net PnL"]>0).mean() if len(group) else np.nan,
          "Average Holding Period":group["Bars Held"].mean(),"Counterfactual Label":"POST_EXIT_COUNTERFACTUAL_DIAGNOSTIC_ONLY"}
        for horizon in (5,10,20):
            returns=[]; mfes=[]; maes=[]; later_t1=[]; later_t2=[]
            for _,trade in group.iterrows():
                future=_future_window(trade,features,horizon)
                if future.empty: continue
                exit_price=float(trade["Executed Exit"]); returns.append(float(future["Close"].iloc[-1])/exit_price-1); mfes.append(float(future["High"].max())/exit_price-1); maes.append(float(future["Low"].min())/exit_price-1)
                later_t1.append((pd.to_numeric(future["High"])>=float(trade["Original T1"])).any()); later_t2.append((pd.to_numeric(future["High"])>=float(trade["Original T2"])).any())
            record.update({f"{horizon}S Average Raw Return %":100*np.mean(returns) if returns else np.nan,f"{horizon}S Average MFE %":100*np.mean(mfes) if mfes else np.nan,
                           f"{horizon}S Average MAE %":100*np.mean(maes) if maes else np.nan,f"{horizon}S Later T1 Hit %":100*np.mean(later_t1) if later_t1 else np.nan,
                           f"{horizon}S Later T2 Hit %":100*np.mean(later_t2) if later_t2 else np.nan})
        trend_rows.append(record)
    return {"stop":pd.DataFrame(stop_rows),"partial":pd.DataFrame(partial_rows),"target":pd.DataFrame(target_rows),"trend":pd.DataFrame(trend_rows)}


def opportunity_recycling(static_trades: pd.DataFrame, dynamic_trades: pd.DataFrame) -> pd.DataFrame:
    keys=["Signal ID"] if "Signal ID" in static_trades and static_trades["Signal ID"].notna().all() else ["Ticker","Signal Date"]
    static_keys=set(map(tuple,static_trades[keys].astype(str).to_numpy()))
    rows=[]
    for policy,group in dynamic_trades.groupby("Policy"):
        dyn_keys=set(map(tuple,group[keys].astype(str).to_numpy()))
        shared=group[[tuple(row) in static_keys for row in group[keys].astype(str).to_numpy()]]; additional=group[[tuple(row) not in static_keys for row in group[keys].astype(str).to_numpy()]]
        determinable=0
        shared_columns=list(dict.fromkeys([*keys,"Ticker","Exit Date"]))
        shared_static=static_trades.merge(shared[shared_columns].drop_duplicates(keys),on=keys,how="inner",suffixes=(" Static"," Dynamic"))
        for _,trade in additional.iterrows():
            ticker_column="Ticker Static" if "Ticker Static" in shared_static else "Ticker"
            earlier=shared_static[(shared_static[ticker_column]==trade["Ticker"]) & (pd.to_datetime(shared_static["Exit Date Dynamic"])<pd.Timestamp(trade["Entry Date"])) &
                                  (pd.to_datetime(shared_static["Exit Date Static"])>=pd.Timestamp(trade["Entry Date"]))]
            determinable+=int(not earlier.empty)
        rows.append({"Policy":policy,"Static Portfolio Entries":len(static_keys),"Dynamic Portfolio Entries":len(dyn_keys),
                     "Shared Entries":len(static_keys&dyn_keys),"Additional Dynamic Entries":len(dyn_keys-static_keys),
                     "Static Entries Not Taken":len(static_keys-dyn_keys),"Shared Dynamic Entry Net PnL":pd.to_numeric(shared.get("Net PnL"),errors="coerce").sum(),
                     "Dynamic-Only Entry Net PnL":pd.to_numeric(additional.get("Net PnL"),errors="coerce").sum(),
                     "Dynamic-Only Entries From Earlier Same-Ticker Exit (Determinable)":determinable,
                     "Interpretation":"DESCRIPTIVE OPPORTUNITY-RECYCLING DECOMPOSITION; ENTRY RULES UNCHANGED"})
    return pd.DataFrame(rows)


def _resistance(features: pd.DataFrame, date: pd.Timestamp, close: float, target: float) -> float | None:
    history=features.loc[:date]; levels=[]
    for period in (20,60,120):
        if len(history)>period:
            value=history["High"].rolling(period,min_periods=period).max().shift(1).iloc[-1]
            if pd.notna(value) and close<float(value)<target: levels.append(float(value))
    return min(levels) if levels else None


def _shadow_one(
    trade: pd.Series,
    signal: pd.Series,
    features: pd.DataFrame,
    tables: pd.DataFrame,
    policy: str,
    config: PolicyConfig,
    slippage_bps: float,
    transaction_cost_bps: float,
) -> Dict[str, Any]:
    entry_date=pd.Timestamp(trade["Entry Date"]).normalize(); bars=features.loc[features.index>=entry_date].iloc[:config.max_hold_sessions]
    if bars.empty or bars.index[0]!=entry_date: raise RuntimeError(f"Missing fixed entry bar for {trade['Ticker']} {entry_date}")
    initial_qty=int(trade["Quantity"]); remaining=initial_qty; nominal_entry=float(trade["Nominal Entry"]); executed_entry=float(trade["Executed Entry"])
    initial_stop=float(trade["Stop"]); original_t1=float(signal["Target 1"]); original_t2=float(signal["Target 2"]); risk=float(trade["Initial Risk Per Share"])
    calibration=resolve(tables,signal.to_dict(),entry_date.year); q75=None if pd.isna(calibration["t1_q75"]) else float(calibration["t1_q75"])
    state={"current_stop":initial_stop,"active_target":original_t2,"original_t2":original_t2,"executed_entry":executed_entry,"current_r":0.0,
           "partial_taken":False,"t1_reached":False,"days_held":0,"t1_q75":q75}
    scheduled=None; legs=[]; highest=executed_entry; lowest=executed_entry

    def add_leg(date: pd.Timestamp, nominal: float, reason: str, quantity: int) -> None:
        nonlocal remaining
        executed=float(nominal)*(1-slippage_bps/10000); exit_cost=executed*quantity*transaction_cost_bps/10000
        allocated_entry_cost=float(trade["Entry Transaction Cost"])*quantity/initial_qty
        gross=(float(nominal)-nominal_entry)*quantity; entry_slip=(executed_entry-nominal_entry)*quantity; exit_slip=(float(nominal)-executed)*quantity
        net=gross-entry_slip-exit_slip-allocated_entry_cost-exit_cost
        legs.append({"date":date,"nominal":float(nominal),"executed":executed,"reason":reason,"quantity":quantity,"net":net,
                     "gross":gross,"slippage":entry_slip+exit_slip,"transaction_cost":allocated_entry_cost+exit_cost})
        remaining-=quantity

    def partial(date: pd.Timestamp, nominal: float) -> None:
        state["t1_reached"]=True; quantity=math.floor(initial_qty*config.partial_fraction)
        if initial_qty<2 or quantity<=0: return
        add_leg(date,nominal,"T1_PARTIAL",quantity); state["partial_taken"]=True

    for bar_number,(date,row) in enumerate(bars.iterrows(),start=1):
        state["days_held"]=bar_number; open_price=float(row["Open"]); low=float(row["Low"]); high=float(row["High"]); close=float(row["Close"])
        entry_bar=bar_number==1; entry_intraday=entry_bar and str(trade["Entry Method"])=="PULLBACK_LIMIT"
        if not entry_bar:
            if open_price<=state["current_stop"]: add_leg(date,open_price,"GAP_STOP",remaining)
            elif scheduled: add_leg(date,open_price,scheduled,remaining)
            elif policy in {"D3_PARTIAL_T1_TRAIL","D4_TREND_PROTECT","D5_RESISTANCE_TIGHTEN","D6_HYBRID_DYNAMIC"} and not state["t1_reached"] and open_price>=original_t1:
                partial(date,open_price)
                if remaining and open_price>=state["active_target"]: add_leg(date,open_price,"EXIT_T2",remaining)
            elif open_price>=state["active_target"]: add_leg(date,open_price,"EXIT_DYNAMIC_TARGET" if state["active_target"]<original_t2 else "EXIT_T2",remaining)
        if remaining:
            highest=max(highest,high); lowest=min(lowest,low); state["current_r"]=(close-executed_entry)/risk
            stop_hit=low<=state["current_stop"]; t1_hit=not state["t1_reached"] and high>=original_t1; target_hit=high>=state["active_target"]
            if entry_intraday:
                if stop_hit: add_leg(date,state["current_stop"],"STOP_COLLISION_ENTRY_BAR" if (t1_hit or target_hit) else "STOP_ENTRY_BAR",remaining)
            elif stop_hit: add_leg(date,state["current_stop"],"EXIT_STOP_COLLISION" if (t1_hit or target_hit) else "EXIT_STOP",remaining)
            elif policy in {"D3_PARTIAL_T1_TRAIL","D4_TREND_PROTECT","D5_RESISTANCE_TIGHTEN","D6_HYBRID_DYNAMIC"} and t1_hit:
                partial(date,original_t1)
            elif target_hit: add_leg(date,state["active_target"],"EXIT_DYNAMIC_TARGET" if state["active_target"]<original_t2 else "EXIT_T2",remaining)
        if remaining and bar_number>=config.max_hold_sessions: add_leg(date,close,"EXIT_MAX_63D",remaining)
        if remaining and date==features.index[-1]: add_leg(date,close,"END_OF_DATA",remaining)
        if remaining:
            resistance=_resistance(features,date,close,state["active_target"]) if state["partial_taken"] else None
            decision=decide_after_close(policy,state,row,resistance,config)
            state["current_stop"]=max(state["current_stop"],decision.proposed_stop)
            state["active_target"]=min(state["active_target"],original_t2,decision.proposed_target)
            if decision.scheduled_exit: scheduled=decision.scheduled_exit
        else: break
    if remaining: raise RuntimeError(f"Shadow trade did not resolve inside fixed horizon: {trade['Ticker']} {entry_date}")
    net=sum(leg["net"] for leg in legs); final=legs[-1]
    return {"Shadow Exit Date":final["date"],"Shadow Nominal Exit":final["nominal"],"Shadow Executed Exit":sum(leg["executed"]*leg["quantity"] for leg in legs)/initial_qty,
            "Shadow Exit Reason":final["reason"],"Shadow Bars Held":state["days_held"],"Shadow Net PnL":net,"Shadow R":net/(risk*initial_qty),
            "Shadow Exit Legs":len(legs),"Shadow Partial Taken":any(leg["reason"]=="T1_PARTIAL" for leg in legs),
            "Shadow Gross PnL":sum(leg["gross"] for leg in legs),"Shadow Slippage Cost":sum(leg["slippage"] for leg in legs),
            "Shadow Transaction Cost":sum(leg["transaction_cost"] for leg in legs)}


def paired_entry_shadow(
    static_trades: pd.DataFrame,
    candidates: pd.DataFrame,
    features: Dict[str,pd.DataFrame],
    tables: pd.DataFrame,
    config: PolicyConfig,
    slippage_bps: float,
    transaction_cost_bps: float,
) -> Tuple[pd.DataFrame,pd.DataFrame]:
    """Independent fixed-entry replay; released cash never creates another entry."""
    candidate_lookup=candidates.copy(); candidate_lookup["Signal Date"]=pd.to_datetime(candidate_lookup["Signal Date"]).dt.normalize()
    candidate_lookup=candidate_lookup.drop_duplicates(["Ticker","Signal Date"]).set_index(["Ticker","Signal Date"]); rows=[]
    for _,trade in static_trades.iterrows():
        signal=candidate_lookup.loc[(str(trade["Ticker"]),pd.Timestamp(trade["Signal Date"]).normalize())]
        signal_id=str(signal["Signal ID"])
        for policy in POLICIES:
            shadow=_shadow_one(trade,signal,features[str(trade["Ticker"])],tables,policy,config,slippage_bps,transaction_cost_bps)
            delta_r=shadow["Shadow R"]-float(trade["R Multiple"]); delta_pnl=shadow["Shadow Net PnL"]-float(trade["Net PnL"])
            baseline_win=float(trade["Net PnL"])>0; shadow_win=shadow["Shadow Net PnL"]>0
            rows.append({"Policy":policy,"Signal ID":signal_id,"Ticker":trade["Ticker"],"Signal Date":trade["Signal Date"],"Entry Date":trade["Entry Date"],
                         "Nominal Entry":trade["Nominal Entry"],"Executed Entry":trade["Executed Entry"],"Fixed Quantity":trade["Quantity"],"Initial Stop":trade["Stop"],
                         "Original T1":signal["Target 1"],"Original T2":signal["Target 2"],"Original Maximum Horizon":config.max_hold_sessions,
                         "Baseline Exit Date":trade["Exit Date"],"Baseline Nominal Exit":trade["Nominal Exit"],"Baseline Executed Exit":trade["Executed Exit"],
                         "Baseline Exit Reason":trade["Exit Reason"],"Baseline Bars Held":trade["Bars Held"],"Baseline Net PnL":trade["Net PnL"],"Baseline R":trade["R Multiple"],
                         **shadow,"Delta R":delta_r,"Delta Net PnL":delta_pnl,"Holding-Time Delta":shadow["Shadow Bars Held"]-int(trade["Bars Held"]),
                         "Win/Loss Flip":"WIN_TO_LOSS" if baseline_win and not shadow_win else "LOSS_TO_WIN" if shadow_win and not baseline_win else "NO_FLIP",
                         "Analysis Label":"FIXED_ENTRY_FIXED_QUANTITY_SHADOW; CASH_RECYCLING_DISABLED; NOT_PORTFOLIO_CAGR"})
    detail=pd.DataFrame(rows); summaries=[]
    for policy,group in detail.groupby("Policy"):
        delta=group["Delta R"]
        summaries.append({"Policy":policy,"Fixed Cohort Count":len(group),"Average Baseline R":group["Baseline R"].mean(),"Average Dynamic R":group["Shadow R"].mean(),
                          "Mean Delta R":delta.mean(),"Median Delta R":delta.median(),"% Improved":100*(delta>1e-12).mean(),"% Worsened":100*(delta<-1e-12).mean(),
                          "% Unchanged":100*(delta.abs()<=1e-12).mean(),"Total Fixed-Quantity PnL Delta":group["Delta Net PnL"].sum(),
                          "Average Holding-Time Delta":group["Holding-Time Delta"].mean(),"Interpretation":"FIXED ENTRY/QUANTITY SHADOW; NO CASH RECYCLING; NOT PORTFOLIO CAGR"})
    return detail,pd.DataFrame(summaries)
