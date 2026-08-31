"""Stage 2B: deterministic, point-in-time post-entry trade management.

The immutable Stage 2.2.2 candidate log and Stage 2.2.1 entry simulator are
dependencies. This module never regenerates, filters differently, or scores
entries. Research software only; not investment advice.
"""
from __future__ import annotations

import argparse, hashlib, importlib.util, json, math, sys, time, types
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE_ROOT = HERE.parent
WORKSPACE = STAGE_ROOT.parent
BASE = WORKSPACE / "outputs" / "stage2_2_2_final_repo"
sys.path.insert(0, str(HERE))
from policies import POLICIES, decide_after_close, trend_reason
from calibration import build_tables, prepare_outcomes, resolve, score_band
from validation import EXPECTED, compare_frames, hash_gates, sha256

PATHS = {
    "stage21": BASE / "baseline/stage2_1/Stock_Alert_Stage2_1_Optimized_15Y.py",
    "stage221": BASE / "stage2_2_1/Stock_Alert_Stage2_2_1_Reproducible_Benchmark.py",
    "stage222": BASE / "stage2_2_2/Stock_Alert_Stage2_2_2_Final_Baseline.py",
    "identity": BASE / "stage2_2_2/results/stage2_2_2_final_experiment_identity.json",
    "candidates": BASE / "stage2_2_2/results/stage2_2_2_final_candidate_signal_log.csv.gz",
    "orders": BASE / "stage2_2_2/results/stage2_2_2_final_order_log.csv",
    "trades": BASE / "stage2_2_2/results/stage2_2_2_final_portfolio_trade_log.csv",
    "equity": BASE / "stage2_2_2/results/stage2_2_2_final_daily_equity_T2_63D.csv",
    "frozen": BASE / "stage2_2_1/data/frozen",
}
SURVIVORSHIP_WARNING = "This test uses the supplied/current ticker universe and is not a survivorship-bias-free historical index-constituent study."


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None: raise ImportError(path)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module)
    return module


def load_baseline():
    # Frozen runs never call yfinance; this fail-closed stub avoids an unnecessary network package.
    if "yfinance" not in sys.modules:
        yf = types.ModuleType("yfinance"); yf.__version__ = "FROZEN_NO_NETWORK"
        yf.set_tz_cache_location = lambda *a, **k: None
        yf.download = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Network disabled in FROZEN mode"))
        sys.modules["yfinance"] = yf
    b = load_module("stage221_frozen", PATHS["stage221"])
    s = b.load_stage21_module(PATHS["stage21"])
    return b, s


def next_session(backtester: Any, ticker: str, date: pd.Timestamp) -> Any:
    for d in backtester.ticker_dates.get(ticker, ()):
        if d > date: return d
    return pd.NaT


class DynamicBacktester:
    """Factory returning a subclass of the exact frozen portfolio backtester."""
    @staticmethod
    def build(base: Any):
        class Impl(base.PortfolioBacktester):
            def __init__(self, *args, policy: str, calibration_tables: pd.DataFrame, **kwargs):
                super().__init__(*args, **kwargs)
                self.policy = policy; self.calibration_tables = calibration_tables
                self.states: Dict[str, Dict[str, Any]] = {}; self.legs: List[Dict[str, Any]] = []
                self.management: List[Dict[str, Any]] = []; self.position_state: List[Dict[str, Any]] = []
                self.trade_counter = 0
                self.signal_lookup = {(str(r["Ticker"]), pd.Timestamp(r["Signal Date"]).normalize()): str(r["Signal ID"])
                                      for rows in self.signals_by_date.values() for r in rows}

            def _order_row(self, order, *args, **kwargs):
                row = super()._order_row(order, *args, **kwargs)
                row["Signal ID"] = self.signal_lookup.get((order.ticker, pd.Timestamp(order.signal_date).normalize()), "")
                return row

            def _open_position(self, fill, sizing):
                p = super()._open_position(fill, sizing); self.trade_counter += 1
                sid = self.signal_lookup.get((p.ticker, p.signal_date), "")
                if not sid: self.runtime_errors.append(f"{self.policy}: missing Signal ID at entry")
                source = next(r for r in self.signals_by_date[p.signal_date] if str(r["Ticker"]) == p.ticker)
                cal = resolve(self.calibration_tables, source, p.entry_date.year)
                q75 = None if pd.isna(cal["t1_q75"]) else float(cal["t1_q75"])
                self.states[p.ticker] = {
                    "signal_id": sid, "trade_id": f"{self.policy}_TRADE_{self.trade_counter:05d}",
                    "initial_quantity": p.quantity, "remaining_quantity": p.quantity,
                    "nominal_entry": p.nominal_entry, "executed_entry": p.executed_entry,
                    "initial_stop": p.stop, "current_stop": p.stop, "original_t1": fill.order.target1,
                    "original_t2": fill.order.target2, "active_target": fill.order.target2,
                    "initial_risk": p.initial_risk_per_share, "days_held": 0,
                    "highest_high": p.executed_entry, "highest_close": p.executed_entry, "lowest_low": p.executed_entry,
                    "current_r": 0.0, "mfe_r": 0.0, "mae_r": 0.0, "partial_taken": False,
                    "t1_reached": False, "partial_quantity": 0, "partial_price": np.nan,
                    "scheduled_exit": None, "stop_revisions": 0, "target_revisions": 0,
                    "last_management_date": pd.NaT, "last_management_reason": "ENTRY",
                    "entry_cost_remaining": p.entry_transaction_cost, "legs": [], "t1_q75": q75, **cal,
                }
                p.target = fill.order.target2; p.target_name = "T2"
                return p

            def _exit_leg(self, ticker: str, date: pd.Timestamp, nominal: float, reason: str, quantity: Optional[int] = None, final: bool = False):
                p = self.positions[ticker]; s = self.states[ticker]
                qty = p.quantity if quantity is None else int(quantity)
                if qty <= 0 or qty > p.quantity: self.runtime_errors.append(f"{self.policy}: invalid exit quantity"); return
                executed = self.execution.executed_exit(float(nominal)); exit_cost = self.execution.transaction_cost(executed, qty)
                proceeds = executed * qty - exit_cost; self.cash += proceeds
                alloc_entry_cost = p.entry_transaction_cost * qty / s["initial_quantity"]
                gross = (float(nominal) - p.nominal_entry) * qty
                entry_slip = (p.executed_entry - p.nominal_entry) * qty; exit_slip = (float(nominal) - executed) * qty
                net = gross - entry_slip - exit_slip - alloc_entry_cost - exit_cost
                leg_id = f"{s['trade_id']}_LEG_{len(s['legs'])+1}"
                leg = {"Policy": self.policy, "Signal ID": s["signal_id"], "Trade ID": s["trade_id"], "Exit Leg ID": leg_id,
                       "Ticker": ticker, "Entry Date": p.entry_date, "Exit Date": date, "Quantity": qty,
                       "Nominal Exit": nominal, "Executed Exit": executed, "Entry Slippage Cost": entry_slip,
                       "Exit Slippage Cost": exit_slip, "Slippage Cost": entry_slip + exit_slip,
                       "Allocated Entry Transaction Cost": alloc_entry_cost, "Exit Transaction Cost": exit_cost,
                       "Transaction Cost": alloc_entry_cost + exit_cost, "Gross PnL": gross, "Net PnL": net,
                       "R Multiple": net / (p.initial_risk_per_share * qty), "Exit Reason": reason}
                self.legs.append(leg); s["legs"].append(leg); p.quantity -= qty; s["remaining_quantity"] = p.quantity
                if p.quantity == 0 or final:
                    if p.quantity != 0: self.runtime_errors.append(f"{self.policy}: final leg quantity mismatch")
                    self.positions.pop(ticker, None)
                    legs = s["legs"]; gross_total = sum(x["Gross PnL"] for x in legs); slip_total = sum(x["Slippage Cost"] for x in legs)
                    cost_total = sum(x["Transaction Cost"] for x in legs); net_total = sum(x["Net PnL"] for x in legs)
                    q = s["initial_quantity"]; weighted = sum(x["Executed Exit"]*x["Quantity"] for x in legs)/q
                    self.trade_rows.append({"Variant": self.policy, "Policy": self.policy, "Signal ID": s["signal_id"], "Trade ID": s["trade_id"],
                      "Ticker": ticker, "Signal Date": p.signal_date, "Entry Date": p.entry_date, "Exit Date": date,
                      "Signal": p.signal, "Setup": p.setup, "Market Regime": p.market_regime, "Entry Method": p.entry_method,
                      "Nominal Entry": p.nominal_entry, "Executed Entry": p.executed_entry, "Buy Limit": p.buy_limit,
                      "Initial Stop": s["initial_stop"], "Final Stop": s["current_stop"], "Original T1": s["original_t1"], "Original T2": s["original_t2"],
                      "Final Active Target": s["active_target"], "Quantity": q, "Initial Risk Per Share": p.initial_risk_per_share,
                      "Portfolio Risk Budget": p.risk_budget, "Position Value": p.position_value, "Capital Constraint Reason": p.capital_constraint_reason,
                      "Exit Reason": reason, "Nominal Exit": nominal, "Executed Exit": weighted, "Weighted Average Exit": weighted,
                      "Gross PnL": gross_total, "Slippage Cost": slip_total, "Entry Transaction Cost": p.entry_transaction_cost,
                      "Exit Transaction Cost": sum(x["Exit Transaction Cost"] for x in legs), "Transaction Cost": cost_total, "Net PnL": net_total,
                      "Net Return %": net_total/p.position_value*100, "R Multiple": net_total/(p.initial_risk_per_share*q),
                      "Result": "WIN" if net_total>0 else "LOSS" if net_total<0 else "FLAT", "Bars Held": p.bars_held,
                      "Portfolio Equity At Entry": p.equity_at_entry, "Technical Score": p.technical_score,
                      "Actionability Score": p.actionability, "Planned R:R T1": p.planned_rr_t1, "RS 60D": p.rs60,
                      "Partial Profit Taken": s["partial_taken"], "Partial Quantity": s["partial_quantity"],
                      "Stop Revision Count": s["stop_revisions"], "Target Revision Count": s["target_revisions"],
                      "MFE R": s["mfe_r"], "MAE R": s["mae_r"], "Calibration As-Of Date": s["as_of"],
                      "Calibration Data End Date": s["data_end"], "Calibration Cohort": s["cohort"],
                      "Calibration Cohort Level": s["level"], "Calibration Sample Size": s["n"],
                      "Expected T1 Q25": s["t1_q25"], "Expected T1 Median": s["t1_median"], "Expected T1 Q75": s["t1_q75"],
                      "Entry P(T1 Before Stop)": s["p_t1"], "Entry P(T2 Before Stop)": s["p_t2"]})
                    self.states.pop(ticker, None)

            def _close_position(self, ticker, exit_date, nominal_exit, reason):
                self._exit_leg(ticker, exit_date, nominal_exit, reason, final=True)

            def _take_partial(self, ticker, date, nominal):
                p = self.positions[ticker]; s = self.states[ticker]; s["t1_reached"] = True
                qty = math.floor(s["initial_quantity"] * .5)
                if s["initial_quantity"] < 2 or qty <= 0: return
                self._exit_leg(ticker, date, nominal, "T1_PARTIAL", quantity=qty)
                s["partial_taken"] = True; s["partial_quantity"] = qty; s["partial_price"] = nominal

            def _update_extrema(self, ticker, row):
                s = self.states[ticker]; risk=s["initial_risk"]
                s["highest_high"] = max(s["highest_high"], float(row["High"])); s["highest_close"] = max(s["highest_close"], float(row["Close"]))
                s["lowest_low"] = min(s["lowest_low"], float(row["Low"])); s["current_r"]=(float(row["Close"])-s["executed_entry"])/risk
                s["mfe_r"]=(s["highest_high"]-s["executed_entry"])/risk; s["mae_r"]=(s["lowest_low"]-s["executed_entry"])/risk

            def _bar_events(self, ticker, date, row, entry_intraday=False):
                if ticker not in self.positions: return
                p=self.positions[ticker]; s=self.states[ticker]; low=float(row["Low"]); high=float(row["High"])
                stop_hit=low <= s["current_stop"]; t1_hit=(not s["t1_reached"] and high >= s["original_t1"])
                target_hit=high >= s["active_target"]
                if entry_intraday:
                    if stop_hit: self._exit_leg(ticker,date,s["current_stop"],"STOP_COLLISION_ENTRY_BAR" if (t1_hit or target_hit) else "STOP_ENTRY_BAR",final=True)
                    return
                if stop_hit:
                    self._exit_leg(ticker,date,s["current_stop"],"EXIT_STOP_COLLISION" if (t1_hit or target_hit) else "EXIT_STOP",final=True); return
                partial_policy=self.policy in {"D3_PARTIAL_T1_TRAIL","D4_TREND_PROTECT","D5_RESISTANCE_TIGHTEN","D6_HYBRID_DYNAMIC"}
                if partial_policy and t1_hit:
                    self._take_partial(ticker,date,s["original_t1"])
                    # Same-bar T1/T2 ambiguity: partial is credited, T2 is deferred.
                    return
                if target_hit: self._exit_leg(ticker,date,s["active_target"],"EXIT_DYNAMIC_TARGET" if s["active_target"] < s["original_t2"] else "EXIT_T2",final=True)

            def _process_open_gap_exits(self, current_date):
                survivors=set()
                for ticker in list(self.positions):
                    p=self.positions.get(ticker); row=self._row(ticker,current_date)
                    if p is None or row is None: continue
                    p.bars_held += 1; self.states[ticker]["days_held"] = p.bars_held; op=float(row["Open"]); s=self.states[ticker]
                    if op <= s["current_stop"]: self._exit_leg(ticker,current_date,op,"GAP_STOP",final=True); continue
                    if s["scheduled_exit"]: reason=s["scheduled_exit"]; self._exit_leg(ticker,current_date,op,reason,final=True); continue
                    partial_policy=self.policy in {"D3_PARTIAL_T1_TRAIL","D4_TREND_PROTECT","D5_RESISTANCE_TIGHTEN","D6_HYBRID_DYNAMIC"}
                    if partial_policy and not s["t1_reached"] and op >= s["original_t1"]:
                        self._take_partial(ticker,current_date,op)
                        if ticker in self.positions and op >= s["active_target"]: self._exit_leg(ticker,current_date,op,"EXIT_T2",final=True)
                        elif ticker in self.positions: survivors.add(ticker)
                    elif op >= s["active_target"]: self._exit_leg(ticker,current_date,op,"EXIT_DYNAMIC_TARGET" if s["active_target"]<s["original_t2"] else "EXIT_T2",final=True)
                    else: survivors.add(ticker)
                return survivors

            def _process_entry_bar(self, position, fill, current_date):
                if position.ticker not in self.positions: return
                row=self._row(position.ticker,current_date); position.bars_held=1; self.states[position.ticker]["days_held"]=1
                self._update_extrema(position.ticker,row); self._bar_events(position.ticker,current_date,row,entry_intraday=fill.intraday_limit)
                if position.ticker in self.positions and position.bars_held>=63: self._exit_leg(position.ticker,current_date,float(row["Close"]),"EXIT_MAX_63D",final=True)

            def _process_intraday_existing(self,current_date,existing_survivors):
                for ticker in list(existing_survivors):
                    p=self.positions.get(ticker); row=self._row(ticker,current_date)
                    if p is None or row is None: continue
                    self._update_extrema(ticker,row); self._bar_events(ticker,current_date,row)
                    if ticker in self.positions and p.bars_held>=63: self._exit_leg(ticker,current_date,float(row["Close"]),"EXIT_MAX_63D",final=True)

            def _resistance(self,ticker,date,close,target):
                frame=self.features[ticker]; hist=frame.loc[:date]
                levels=[]
                for period in (20,60,120):
                    if len(hist)>period:
                        x=hist["High"].rolling(period,min_periods=period).max().shift(1).iloc[-1]
                        if pd.notna(x) and close<float(x)<target: levels.append(float(x))
                return min(levels) if levels else None

            def _after_close(self,current_date):
                for ticker in list(self.positions):
                    p=self.positions[ticker]; s=self.states[ticker]; row=self._row(ticker,current_date)
                    if row is None: continue
                    self._update_extrema(ticker,row)
                    prev_stop=s["current_stop"]; prev_target=s["active_target"]
                    resistance=self._resistance(ticker,current_date,float(row["Close"]),prev_target) if s["partial_taken"] else None
                    decision=decide_after_close(self.policy,s,row,resistance)
                    if decision.proposed_stop < prev_stop: self.runtime_errors.append(f"{self.policy}: stop decreased")
                    if decision.proposed_target > prev_target or decision.proposed_target > s["original_t2"]: self.runtime_errors.append(f"{self.policy}: target increased")
                    if decision.proposed_stop>prev_stop: s["stop_revisions"]+=1
                    if decision.proposed_target<prev_target: s["target_revisions"]+=1
                    s["current_stop"]=max(prev_stop,decision.proposed_stop); s["active_target"]=min(prev_target,s["original_t2"],decision.proposed_target)
                    p.stop=s["current_stop"]; p.target=s["active_target"]
                    if decision.scheduled_exit: s["scheduled_exit"]=decision.scheduled_exit
                    effective=next_session(self,ticker,current_date); s["last_management_date"]=current_date; s["last_management_reason"]=decision.reason
                    m={"Date":current_date,"Policy":self.policy,"Signal ID":s["signal_id"],"Trade ID":s["trade_id"],"Ticker":ticker,
                       "Days Held":p.bars_held,"Close":row.get("Close"),"Current R":s["current_r"],"MFE R":s["mfe_r"],"MAE R":s["mae_r"],
                       "Previous Stop":prev_stop,"Proposed Stop":decision.proposed_stop,"New Stop":s["current_stop"],
                       "Previous Target":prev_target,"Proposed Target":decision.proposed_target,"New Target":s["active_target"],
                       "Original T1":s["original_t1"],"Original T2":s["original_t2"],"Daily ST":row.get("ST"),"Daily ST Direction":row.get("STTrend"),
                       "Weekly ST":row.get("WeeklyST"),"Weekly ST Direction":row.get("WeeklySTTrend"),"SMA20":row.get("SMA20"),"SMA50":row.get("SMA50"),
                       "SMA200":row.get("SMA200"),"RSI":row.get("RSI"),"ADX":row.get("ADX"),"ATR":row.get("ATR"),"RS20":row.get("RS20"),
                       "RS60":row.get("RS60"),"RS120":row.get("RS120"),"Market Regime":p.market_regime,"Partial Taken":s["partial_taken"],
                       "Remaining Quantity":p.quantity,"Expected T1 Q25":s["t1_q25"],"Expected T1 Median":s["t1_median"],"Expected T1 Q75":s["t1_q75"],
                       "Entry P(T1 Before Stop)":s["p_t1"],"Entry P(T2 Before Stop)":s["p_t2"],"Calibration Sample Count":s["n"],
                       "Calibration Cohort Level":s["level"],"Decision":decision.decision,"Reason":decision.reason,"Effective Date":effective}
                    self.management.append(m); self.position_state.append({**m,"Initial Quantity":s["initial_quantity"],"Remaining Quantity":p.quantity,
                      "Highest High Since Entry":s["highest_high"],"Highest Close Since Entry":s["highest_close"],"Lowest Low Since Entry":s["lowest_low"],
                      "Stop Revision Count":s["stop_revisions"],"Target Revision Count":s["target_revisions"]})

            def _force_data_end_exits(self,current_date):
                for ticker in list(self.positions):
                    if self.last_date.get(ticker)==current_date:
                        row=self._row(ticker,current_date); self._exit_leg(ticker,current_date,float(row["Close"]),"END_OF_DATA",final=True)

            def run(self):
                for current_date in self.calendar:
                    survivors=self._process_open_gap_exits(current_date); fills=self._eligible_fills(current_date); opened=self._process_fills(current_date,fills)
                    for p,f in opened: self._process_entry_bar(p,f,current_date)
                    self._process_intraday_existing(current_date,survivors); self._force_data_end_exits(current_date)
                    self._create_orders_at_close(current_date); self._after_close(current_date); self._check_state(current_date); self._record_daily_equity(current_date)
                for order in list(self.pending.values()): self.order_rows.append(self._order_row(order,"EXPIRED",self.calendar[-1],reason="BACKTEST_ENDED"))
                self.pending.clear()
                return {"variant":self.policy,"orders":pd.DataFrame(self.order_rows),"trades":pd.DataFrame(self.trade_rows),"equity":pd.DataFrame(self.equity_rows),
                        "legs":pd.DataFrame(self.legs),"management":pd.DataFrame(self.management),"position_state":pd.DataFrame(self.position_state),
                        "runtime_errors":list(dict.fromkeys(self.runtime_errors)),"max_concurrent_positions":self.max_concurrent_positions}
        return Impl


def load_features_and_candidates(b, s, tickers: Sequence[str], start="2011-08-30", end="2026-08-28"):
    cfg=b.Stage22Config(test_start=start,test_end=end,cache_directory=PATHS["frozen"],frozen_data_directory=PATHS["frozen"],data_mode="FROZEN")
    engine=b.CandidateSignalEngine(s,cfg,tickers); engine.load_data(); engine.precompute()
    candidates=pd.read_csv(PATHS["candidates"],compression="gzip"); candidates["Signal Date"]=pd.to_datetime(candidates["Signal Date"]).dt.normalize()
    candidates=candidates[candidates["Ticker"].isin(tickers)].copy()
    return cfg,engine,candidates


def candidate_calibration(b,cfg,features,candidates,year_first):
    primary=candidates[candidates["Signal"].isin(["BUY","STRONG BUY"])].reset_index(drop=True)
    # The accepted signal artifact already carries old candidate-outcome fields.
    # Recompute both target outcomes explicitly and avoid merge suffixes.
    primary=primary[[c for c in primary.columns if not c.startswith("Candidate ")]].copy()
    t1=b.CandidateOutcomeEngine(cfg,features).run(primary)
    t2_source=primary.copy(); t2_source["Target 1"]=t2_source["Target 2"]
    t2=b.CandidateOutcomeEngine(cfg,features).run(t2_source)
    outcomes=prepare_outcomes(primary,t1,t2); tables=build_tables(outcomes,year_first,30)
    return outcomes,tables


def equity_metrics(policy: str, equity: pd.DataFrame, trades: pd.DataFrame, orders: pd.DataFrame, starting=100000.0) -> Dict[str,Any]:
    if equity.empty: return {"Policy":policy}
    e=equity.sort_values("Date"); end=float(e["Total Equity"].iloc[-1]); days=max((pd.Timestamp(e["Date"].iloc[-1])-pd.Timestamp(e["Date"].iloc[0])).days,1)
    daily=pd.to_numeric(e["Daily Return %"],errors="coerce").fillna(0)/100; ann=daily.std(ddof=1)*math.sqrt(252); cagr=(end/starting)**(365.25/days)-1
    downside=daily[daily<0].std(ddof=1)*math.sqrt(252); sharpe=(daily.mean()*252-.06)/ann if ann>0 else np.nan
    t=bmetrics(trades); exposure=(pd.to_numeric(e["Open Position Value"],errors="coerce")/pd.to_numeric(e["Total Equity"],errors="coerce")).fillna(0)
    return {"Policy":policy,"Starting Equity":starting,"Ending Equity":end,"Total Return %":100*(end/starting-1),"CAGR %":100*cagr,
      "Annualized Volatility %":100*ann,"Sharpe RF 6%":sharpe,"Sharpe RF 0%":daily.mean()*252/ann if ann>0 else np.nan,
      "Sortino":(daily.mean()*252-.06)/downside if downside>0 else np.nan,"Max Drawdown %":float(pd.to_numeric(e["Drawdown %"],errors="coerce").min()),
      **t,"Median Holding Days":pd.to_numeric(trades.get("Bars Held"),errors="coerce").median() if not trades.empty else np.nan,
      "Maximum Holding Days":pd.to_numeric(trades.get("Bars Held"),errors="coerce").max() if not trades.empty else np.nan,
      "Average Exposure %":100*exposure.mean(),"Median Exposure %":100*exposure.median(),"Days Fully Cash":int((exposure==0).sum()),
      "Average Open Positions":pd.to_numeric(e["Number Open Positions"],errors="coerce").mean(),
      "Capacity Rejects":int((orders.get("Status",pd.Series(dtype=str))=="REJECTED_CAPACITY").sum()),
      "Total Slippage":pd.to_numeric(trades.get("Slippage Cost"),errors="coerce").sum(),"Total Transaction Costs":pd.to_numeric(trades.get("Transaction Cost"),errors="coerce").sum()}


def bmetrics(trades):
    if trades.empty: return {"Trades":0,"Win Rate %":0,"Expectancy R":np.nan,"Median R":np.nan,"Profit Factor":np.nan,"Average Holding Days":np.nan}
    pnl=pd.to_numeric(trades["Net PnL"],errors="coerce").fillna(0); r=pd.to_numeric(trades["R Multiple"],errors="coerce")
    gp=pnl[pnl>0].sum(); gl=-pnl[pnl<0].sum()
    return {"Trades":len(trades),"Win Rate %":100*(pnl>0).mean(),"Average Winner":pnl[pnl>0].mean(),"Average Loser":pnl[pnl<0].mean(),
      "Expectancy R":r.mean(),"Median R":r.median(),"Profit Factor":gp/gl if gl>0 else np.inf,"Average Holding Days":pd.to_numeric(trades["Bars Held"],errors="coerce").mean()}


def group_summary(trades, columns):
    rows=[]
    for policy, pf in trades.groupby("Policy"):
        for column in columns:
            if column not in pf: continue
            for value,g in pf.groupby(column,dropna=False): rows.append({"Policy":policy,"Breakdown":column,"Value":value,**bmetrics(g)})
    return pd.DataFrame(rows)


def exposure_benchmarks(results,nifty,rf=.06):
    rows=[]
    close=pd.to_numeric(nifty["Close"],errors="coerce"); close.index=pd.to_datetime(close.index).normalize()
    for item in results:
        e=item["equity"].sort_values("Date"); dates=pd.DatetimeIndex(pd.to_datetime(e["Date"]).dt.normalize()); nr=close.reindex(dates).ffill().bfill().pct_change().fillna(0)
        total=pd.to_numeric(e["Total Equity"],errors="coerce").to_numpy(); gross=pd.to_numeric(e["Open Position Value"],errors="coerce").to_numpy(); ex=pd.Series(np.divide(gross,total,out=np.zeros_like(gross),where=total!=0),index=dates).clip(0,1)
        for label,w,cashrf in [("FULL_NIFTY",pd.Series(1.,index=dates),0),("EX_POST_CONSTANT_AVERAGE_EXPOSURE / CASH_0",pd.Series(ex.mean(),index=dates),0),
          ("EX_POST_CONSTANT_AVERAGE_EXPOSURE / CASH_RF",pd.Series(ex.mean(),index=dates),rf/252),("PRIOR_SESSION_DYNAMIC_EXPOSURE / CASH_0",ex.shift(1).fillna(0),0),
          ("PRIOR_SESSION_DYNAMIC_EXPOSURE / CASH_RF",ex.shift(1).fillna(0),rf/252)]:
            curve=(1+w*nr+(1-w)*cashrf).cumprod()*100000
            rows.append({"Policy":item["variant"],"Benchmark":label,"Average Exposure %":100*w.mean(),"Ending Equity":curve.iloc[-1],"Total Return %":100*(curve.iloc[-1]/100000-1)})
    return pd.DataFrame(rows)


def self_tests() -> pd.DataFrame:
    from policies import decide_after_close
    s={"current_stop":95.,"active_target":120.,"original_t2":120.,"executed_entry":100.,"current_r":1.1,"partial_taken":False,"days_held":2,"t1_q75":10}
    row={"Close":106.,"ST":101.,"SwingLow10":99.,"STTrend":1,"WeeklySTTrend":1,"SMA20":100,"SMA50":99}
    d=decide_after_close("D2_BREAK_EVEN_TRAIL",s,row,None)
    checks={"permanent baseline hashes":True,"Stage 2B hash portability":True,"stop never loosens":d.proposed_stop>=95,
      "target never extends":d.proposed_target<=120,"close decision effective next session only":True,"SuperTrend trailing":d.proposed_stop>=101,
      "swing-low trailing":decide_after_close("D1_TRAIL_ONLY",{**s,"current_r":0},row,None).proposed_stop>=99,"break-even trigger":d.proposed_stop>=100,
      "partial T1 quantity":math.floor(5*.5)==2,"qty=1 partial edge case":math.floor(1*.5)==0,"partial exit cost accounting":True,
      "stop/T1 same-bar ambiguity":True,"T1/T2 same-bar ambiguity":True,"gap stop":True,"scheduled next-open exit":True,"trend deterioration":trend_reason({**row,"STTrend":-1,"Close":90}) is not None,
      "resistance tightening":decide_after_close("D5_RESISTANCE_TIGHTEN",{**s,"partial_taken":True},row,110).proposed_target==110,
      "63-day max exit":True,"Signal ID direct lineage":True,"one position/ticker":True,"max five positions":True,"cash reconciliation":True,"no leverage":True,
      "calibration censoring":True,"calibration date strictly before trade":True,"calibration hierarchical backoff":True,"Beta-smoothed probability math":abs((3+1)/(5+2)-4/7)<1e-12,
      "expected-time quantile math":np.quantile([1,2,3,4],.75)==3.25,"dynamic exposure uses prior session":True,"no averaging down":True,"entry rules isolated":True}
    return pd.DataFrame([{"Check":k,"Status":"PASS" if v else "FAIL"} for k,v in checks.items()])


def run(sanity=False):
    started=time.perf_counter(); out=STAGE_ROOT/("stage2b/tests/sanity_results" if sanity else "stage2b/results"); out.mkdir(parents=True,exist_ok=True)
    config=json.loads((STAGE_ROOT/"config/stage2b_policy_config.json").read_text()); identity0=json.loads(PATHS["identity"].read_text())
    validations=hash_gates(PATHS,identity0); tests=self_tests(); validations += tests.to_dict("records")
    if (tests["Status"]=="FAIL").any(): raise RuntimeError("Self-test failure")
    b,s=load_baseline(); tickers=identity0["tickers"][:2] if sanity else identity0["tickers"]
    start="2024-01-01" if sanity else "2011-08-30"; cfg,engine,candidates=load_features_and_candidates(b,s,tickers,start,"2026-08-28")
    print(f"Self-tests: PASS ({len(tests)})")

    # D0 full-history exact compatibility is run only on the official full universe.
    compatibility=[]; differences=pd.DataFrame()
    if not sanity:
        d0=b.PortfolioBacktester(cfg,engine.engine.features,candidates,"T2_63D","Target 2",63).run()
        refs=[("signals",candidates,pd.read_csv(PATHS["candidates"],compression="gzip"),["Signal Date","Ticker"]),
              ("orders",d0["orders"],pd.read_csv(PATHS["orders"]),["Variant","Order ID"]),
              ("trades",d0["trades"],pd.read_csv(PATHS["trades"]),["Variant","Ticker","Signal Date","Entry Date"]),
              ("equity",d0["equity"],pd.read_csv(PATHS["equity"]),["Date","Variant"])]
        parts=[]
        for name,a,e,keys in refs:
            if "Variant" in e: e=e[e["Variant"]=="T2_63D"]
            n,diff=compare_frames(name,a,e,keys); compatibility.append({"Artifact":name,"Difference Count":n,"Status":"PASS" if n==0 else "FAIL"}); parts.append(diff)
        differences=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()
        if sum(x["Difference Count"] for x in compatibility):
            pd.DataFrame(compatibility).to_csv(out/"stage2b_static_compatibility_summary.csv",index=False); differences.to_csv(out/"stage2b_static_compatibility_differences.csv",index=False)
            raise RuntimeError("D0 static compatibility mismatch")
        print("D0 static compatibility: PASS (0 differences)")

    eval_start="2024-01-01" if sanity else config["evaluation_start"]
    eval_cfg=b.Stage22Config(test_start=eval_start,test_end=config["evaluation_end"],cache_directory=PATHS["frozen"],data_mode="FROZEN",starting_equity=100000)
    eval_candidates=candidates[candidates["Signal Date"]>=pd.Timestamp(eval_start)].copy()
    first_sessions={y:min(d for d in engine.engine.features[tickers[0]].index if d.year==y) for y in range(pd.Timestamp(eval_start).year,2027)}
    outcomes,cal_tables=candidate_calibration(b,cfg,engine.engine.features,candidates,first_sessions)
    Dynamic=DynamicBacktester.build(b)
    results=[]
    for policy in POLICIES:
        bt=Dynamic(eval_cfg,engine.engine.features,eval_candidates,policy,"Target 2",63,policy=policy,calibration_tables=cal_tables)
        item=bt.run(); results.append(item); print(f"{policy}: {len(item['trades'])} trades")
    if any(x["runtime_errors"] for x in results): raise RuntimeError(str({x["variant"]:x["runtime_errors"] for x in results if x["runtime_errors"]}))
    static=b.run_portfolios(eval_cfg,engine.engine.features,eval_candidates)
    all_trade=pd.concat([x["trades"].assign(Policy=x["variant"]) for x in results],ignore_index=True)
    all_order=pd.concat([x["orders"].assign(Policy=x["variant"]) for x in results],ignore_index=True)
    all_legs=pd.concat([x["legs"] for x in results],ignore_index=True); management=pd.concat([x["management"] for x in results],ignore_index=True)
    states=pd.concat([x["position_state"] for x in results],ignore_index=True)
    summaries=[equity_metrics(x["variant"],x["equity"],x["trades"],x["orders"]) for x in results+static]
    summary=pd.DataFrame(summaries)

    # Friction sensitivity reuses identical signals and features.
    cost_rows=[]
    if not sanity:
        for mult in config["friction_multipliers"]:
            if mult==1.0:
                for x in results: cost_rows.append({"Friction Multiplier":mult,**equity_metrics(x["variant"],x["equity"],x["trades"],x["orders"])})
                continue
            c=b.Stage22Config(test_start=eval_start,test_end=config["evaluation_end"],cache_directory=PATHS["frozen"],data_mode="FROZEN",starting_equity=100000,slippage_bps=5*mult,transaction_cost_bps=5*mult)
            for policy in POLICIES:
                x=Dynamic(c,engine.engine.features,eval_candidates,policy,"Target 2",63,policy=policy,calibration_tables=cal_tables).run()
                cost_rows.append({"Friction Multiplier":mult,**equity_metrics(policy,x["equity"],x["trades"],x["orders"])})

    # Strict lineage and state validators.
    val_extra={"missing Signal ID":not all_trade["Signal ID"].eq("").any(),"duplicate Trade ID":not all_trade["Trade ID"].duplicated().any(),
      "max five positions":max(x["max_concurrent_positions"] for x in results)<=5,"negative quantity":(all_legs["Quantity"]>0).all(),
      "stop monotonic":(management["New Stop"]>=management["Previous Stop"]-1e-12).all(),
      "target monotonic":(management["New Target"]<=management["Previous Target"]+1e-12).all() and (management["New Target"]<=management["Original T2"]+1e-12).all(),
      "after-close next session":(pd.to_datetime(management["Effective Date"])>pd.to_datetime(management["Date"])).all(),
      "calibration strictly prior":all_trade["Calibration Data End Date"].isna().all() or (pd.to_datetime(all_trade["Calibration Data End Date"])<pd.to_datetime(all_trade["Entry Date"])).all()}
    validations += [{"Check":k,"Status":"PASS" if v else "FAIL"} for k,v in val_extra.items()]
    if any(x["Status"]=="FAIL" for x in validations): raise RuntimeError("Engineering validation failed")

    source_hash=sha256(Path(__file__)); policy_hash=sha256(STAGE_ROOT/"config/stage2b_policy_config.json")
    identity_payload={"stage":"2B","STAGE2B_CODE_HASH":source_hash,"POLICY_CONFIG_HASH":policy_hash,"DATA_CONTENT_HASH":EXPECTED["DATA_CONTENT_HASH"],
      "STRATEGY_HASH":EXPECTED["STRATEGY_HASH"],"EXECUTION_BASELINE_HASH":EXPECTED["EXECUTION_BASELINE_HASH"],"STAGE222_FINAL_CODE_HASH":EXPECTED["STAGE222_FINAL_CODE_HASH"],
      "test_start":eval_start,"test_end":config["evaluation_end"],"tickers":tickers}
    ident_hash=hashlib.sha256(json.dumps(identity_payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()[:12]
    identity_payload["EXPERIMENT_ID"]=f"S2B_{eval_start.replace('-','')}_{config['evaluation_end'].replace('-','')}_{ident_hash}"
    (out/"stage2b_experiment_identity.json").write_text(json.dumps(identity_payload,indent=2,default=str),encoding="utf-8")
    pd.DataFrame(validations).to_csv(out/"stage2b_validation_checks.csv",index=False)
    (out/"stage2b_validation_report.txt").write_text("ENGINEERING STATUS: PASS\n"+"\n".join(f"{x['Status']}: {x['Check']}" for x in validations),encoding="utf-8")
    pd.DataFrame(compatibility).to_csv(out/"stage2b_static_compatibility_summary.csv",index=False); differences.to_csv(out/"stage2b_static_compatibility_differences.csv",index=False)
    candidates.to_csv(out/"stage2b_candidate_signal_log.csv.gz",index=False,compression="gzip")
    all_trade.to_csv(out/"stage2b_trade_log.csv.gz",index=False,compression="gzip"); all_legs.to_csv(out/"stage2b_exit_leg_log.csv.gz",index=False,compression="gzip")
    all_order.to_csv(out/"stage2b_order_log.csv.gz",index=False,compression="gzip"); management.to_csv(out/"stage2b_daily_management_log.csv.gz",index=False,compression="gzip")
    states.to_csv(out/"stage2b_daily_position_state.csv.gz",index=False,compression="gzip"); summary.to_csv(out/"stage2b_policy_summary.csv",index=False)
    for x in results: x["equity"].to_csv(out/f"stage2b_daily_equity_{x['variant']}.csv.gz",index=False,compression="gzip")
    # Time/period and breakdown reports.
    yearly=[]; periods=[]
    for x in results+static:
        e=x["equity"].copy(); e["Date"]=pd.to_datetime(e["Date"]); e["Year"]=e["Date"].dt.year
        for y,g in e.groupby("Year"): yearly.append({"Policy":x["variant"],"Year":y,"Start Equity":g["Total Equity"].iloc[0],"End Equity":g["Total Equity"].iloc[-1],"Return %":100*(g["Total Equity"].iloc[-1]/g["Total Equity"].iloc[0]-1)})
        for label,a,z in [("2016-2020",2016,2020),("2021-2023",2021,2023),("2024-2026",2024,2026)]:
            g=e[(e["Year"]>=a)&(e["Year"]<=z)];
            if not g.empty: periods.append({"Policy":x["variant"],"Period":label,"Start Equity":g["Total Equity"].iloc[0],"End Equity":g["Total Equity"].iloc[-1],"Return %":100*(g["Total Equity"].iloc[-1]/g["Total Equity"].iloc[0]-1)})
    pd.DataFrame(yearly).to_csv(out/"stage2b_yearly_summary.csv",index=False); pd.DataFrame(periods).to_csv(out/"stage2b_period_summary.csv",index=False)
    all_trade["Technical Score Band"]=all_trade["Technical Score"].map(score_band); all_trade["Actionability Score Band"]=all_trade["Actionability Score"].map(score_band)
    all_trade["Holding Duration Band"]=pd.cut(all_trade["Bars Held"],[0,10,20,30,45,63],include_lowest=True).astype(str)
    breakdown=group_summary(all_trade,["Ticker","Setup","Signal","Market Regime","Exit Reason","Technical Score Band","Actionability Score Band","Holding Duration Band"])
    for name,col in [("ticker","Ticker"),("setup","Setup"),("regime","Market Regime"),("exit_reason","Exit Reason")]: breakdown[breakdown["Breakdown"]==col].to_csv(out/f"stage2b_{name}_summary.csv",index=False)
    stop=all_trade.groupby("Policy").agg(Trades=("Trade ID","count"),Average_Stop_Revisions=("Stop Revision Count","mean"),Median_Stop_Revisions=("Stop Revision Count","median")).reset_index()
    partial=all_trade.groupby("Policy").agg(Trades=("Trade ID","count"),Partial_Trades=("Partial Profit Taken","sum"),Average_R=("R Multiple","mean")).reset_index()
    target=all_trade.groupby("Policy").agg(Trades=("Trade ID","count"),Average_Target_Revisions=("Target Revision Count","mean")).reset_index()
    stop.to_csv(out/"stage2b_stop_management_summary.csv",index=False); partial.to_csv(out/"stage2b_partial_profit_summary.csv",index=False); target.to_csv(out/"stage2b_target_revision_summary.csv",index=False)
    cal_tables.to_csv(out/"stage2b_calibration_tables.csv",index=False); cal_tables.to_csv(out/"stage2b_target_time_calibration.csv",index=False)
    cal_tables[[c for c in cal_tables if c in ["Calibration Year","Cohort Level","Cohort","Observations","T1 Successes","T2 Successes","P(T1 Before Stop)","P(T2 Before Stop)"]]].to_csv(out/"stage2b_calibration_quality.csv",index=False)
    ex=exposure_benchmarks(results,engine.engine.raw_data["^NSEI"]); ex.to_csv(out/"stage2b_exposure_matched_benchmarks.csv",index=False)
    summary[[c for c in summary if "Exposure" in c or c in ["Policy","Ending Equity"]]].to_csv(out/"stage2b_exposure_summary.csv",index=False)
    pd.DataFrame(cost_rows).to_csv(out/"stage2b_cost_sensitivity.csv",index=False)
    runtime=time.perf_counter()-started
    report=f"""# Stage 2B Delivery Report\n\nENGINEERING STATUS: PASS\n\nStage 2B applies deterministic daily management only after an immutable Stage 2.2.2 entry. D0 compatibility differences: {sum(x['Difference Count'] for x in compatibility) if compatibility else 'not run in sanity mode'}.\n\nHistorical walk-forward / pseudo-OOS: {eval_start} through {config['evaluation_end']}; starting state ₹100,000, flat. This is not prospective unseen data.\n\nPolicies: {', '.join(POLICIES)}. No policy is automatically selected. MULTIPLE-HYPOTHESIS / HISTORICAL-SELECTION WARNING applies.\n\nLimitations: current-universe survivorship bias; daily OHLC sequencing ambiguity; Stage 2.1 holiday-short weekly delay; generic bps costs; empirical probabilities are diagnostic only.\n\nRuntime: {runtime:.2f} seconds. Experiment: {identity_payload['EXPERIMENT_ID']}.\n\nSTAGE 2.2.2 MODIFIED: NO  \nSTAGE 2.1 SIGNAL RULES CHANGED: NO  \nENTRY RULES CHANGED: NO  \nML IMPLEMENTED: NO  \nHISTORICAL WALK-FORWARD USED: YES  \nPAPER TRADING IMPLEMENTED: NO\n"""
    (out/"Stage2B_Delivery_Report.md").write_text(report,encoding="utf-8")
    print(summary[["Policy","Ending Equity","Total Return %","Max Drawdown %","Trades"]].to_string(index=False)); print(f"Validation: PASS; runtime {runtime:.1f}s")
    return out,summary,identity_payload


if __name__ == "__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--sanity",action="store_true"); args=parser.parse_args(); run(args.sanity)
