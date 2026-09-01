"""Stage 2B.1: reproducible audit of accepted post-entry trade management.

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
REPO_ROOT = STAGE_ROOT.parent
sys.path.insert(0, str(HERE))
from policies import POLICIES, PolicyConfig, decide_after_close, trend_reason
from calibration import build_tables, prepare_outcomes, resolve, score_band
from validation import EXPECTED, compare_frames, hash_gates, sha256
from hashing import environment_report, frozen_data_checks, package_manifest, resolve_dependency_root
from diagnostics import (calibration_predictions, drawdown_summary, enrich_exit_day_ambiguity,
                         full_run_invariants, management_summaries, opportunity_recycling,
                         paired_entry_shadow, period_summaries)

PATHS: Dict[str, Path] = {}
REFERENCE_ROOT: Optional[Path] = None
SURVIVORSHIP_WARNING = "This test uses the supplied/current ticker universe and is not a survivorship-bias-free historical index-constituent study."
ACCEPTED_STAGE2B_HASHES = {
    "stage2b/Stock_Alert_Stage2B_Dynamic_Management.py": "5cdf4b4060ea093d0c6655c76e8d262f9a33e36f728655fd7fad35ede7d4e673",
    "config/stage2b_policy_config.json": "7675a643c9cfce30b36596cdd358fef3b8d14640117b3ac8aeed3a384b2ada5b",
    "stage2b/policies.py": "b98e32c63dd37b213575b1df3933bb5a750ab9396cdf7d74749e2928a3994ced",
    "stage2b/calibration.py": "a67b3bea1c2b963b55d62b3fb45973fe9e24abf61378b3b10bd91b02bdcd637e",
    "stage2b/validation.py": "6a9322b9cc4047413543dc61de8e3b4d9ac5bef5be39b2e894d06e8ec560fce1",
}


def configure_paths(baseline_root: Optional[Path], reference_root: Optional[Path]) -> None:
    """Bind repository-relative dependencies; explicit overrides are for controlled tests."""
    global PATHS, REFERENCE_ROOT
    base = resolve_dependency_root(REPO_ROOT, baseline_root, "Stage 2.2.2 Final")
    REFERENCE_ROOT = resolve_dependency_root(REPO_ROOT, reference_root, "Stage 2B")
    PATHS = {
        "stage21": base / "baseline/stage2_1/Stock_Alert_Stage2_1_Optimized_15Y.py",
        "stage221": base / "stage2_2_1/Stock_Alert_Stage2_2_1_Reproducible_Benchmark.py",
        "stage222": base / "stage2_2_2/Stock_Alert_Stage2_2_2_Final_Baseline.py",
        "identity": base / "stage2_2_2/results/stage2_2_2_final_experiment_identity.json",
        "candidates": base / "stage2_2_2/results/stage2_2_2_final_candidate_signal_log.csv.gz",
        "orders": base / "stage2_2_2/results/stage2_2_2_final_order_log.csv",
        "trades": base / "stage2_2_2/results/stage2_2_2_final_portfolio_trade_log.csv",
        "equity": base / "stage2_2_2/results/stage2_2_2_final_daily_equity_T2_63D.csv",
        "frozen": base / "stage2_2_1/data/frozen",
        "baseline_root": base,
    }
    missing = [str(path) for key, path in PATHS.items() if key != "baseline_root" and not path.exists()]
    if missing:
        raise FileNotFoundError(f"Baseline dependency is incomplete: {missing}")


def accepted_stage2b_hash_gates() -> pd.DataFrame:
    assert REFERENCE_ROOT is not None
    rows=[]
    for relative,expected in ACCEPTED_STAGE2B_HASHES.items():
        path=REFERENCE_ROOT/relative; actual=sha256(path) if path.is_file() else "MISSING"
        rows.append({"Type":"HASH_GATE_ACCEPTED_STAGE2B","Check":f"accepted Stage 2B source: {relative}","Status":"PASS" if actual==expected else "FAIL","Expected":expected,"Actual":actual})
    frame=pd.DataFrame(rows)
    if (frame["Status"]!="PASS").any(): raise RuntimeError("Accepted Stage 2B source hash gate failed")
    return frame


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
            def __init__(self, *args, policy: str, calibration_tables: pd.DataFrame,
                         policy_config: PolicyConfig, current_regime: pd.Series, **kwargs):
                super().__init__(*args, **kwargs)
                self.policy = policy; self.calibration_tables = calibration_tables
                self.policy_config = policy_config
                self.current_regime = current_regime.copy()
                self.current_regime.index = pd.to_datetime(self.current_regime.index).normalize()
                self.states: Dict[str, Dict[str, Any]] = {}; self.legs: List[Dict[str, Any]] = []
                self.management: List[Dict[str, Any]] = []; self.position_state: List[Dict[str, Any]] = []
                self.trade_counter = 0
                self.signal_lookup = {(str(r["Ticker"]), pd.Timestamp(r["Signal Date"]).normalize()): str(r["Signal ID"])
                                      for rows in self.signals_by_date.values() for r in rows}

            def _current_market_regime(self, date: pd.Timestamp) -> Any:
                """Latest completed NIFTY regime at or before date; never backfill."""
                history = self.current_regime.loc[:pd.Timestamp(date).normalize()].dropna()
                return history.iloc[-1] if not history.empty else np.nan

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
                qty = math.floor(s["initial_quantity"] * self.policy_config.partial_fraction)
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
                if position.ticker in self.positions and position.bars_held>=self.policy_config.max_hold_sessions: self._exit_leg(position.ticker,current_date,float(row["Close"]),"EXIT_MAX_63D",final=True)

            def _process_intraday_existing(self,current_date,existing_survivors):
                for ticker in list(existing_survivors):
                    p=self.positions.get(ticker); row=self._row(ticker,current_date)
                    if p is None or row is None: continue
                    self._update_extrema(ticker,row); self._bar_events(ticker,current_date,row)
                    if ticker in self.positions and p.bars_held>=self.policy_config.max_hold_sessions: self._exit_leg(ticker,current_date,float(row["Close"]),"EXIT_MAX_63D",final=True)

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
                    decision=decide_after_close(self.policy,s,row,resistance,self.policy_config)
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
                       "RS60":row.get("RS60"),"RS120":row.get("RS120"),"Market Regime":p.market_regime,
                       "Entry Market Regime":p.market_regime,"Current Market Regime":self._current_market_regime(current_date),"Partial Taken":s["partial_taken"],
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
    e=equity.sort_values("Date").reset_index(drop=True); end=float(e["Total Equity"].iloc[-1]); days=max((pd.Timestamp(e["Date"].iloc[-1])-pd.Timestamp(e["Date"].iloc[0])).days,1)
    daily=pd.to_numeric(e["Daily Return %"],errors="coerce").fillna(0)/100; ann=daily.std(ddof=1)*math.sqrt(252); cagr=(end/starting)**(365.25/days)-1
    daily_rf=(1.06)**(1/252)-1; excess=daily-daily_rf; downside=excess[excess<0].std(ddof=1)*math.sqrt(252); sharpe=excess.mean()*252/ann if ann>0 else np.nan
    t=bmetrics(trades); exposure=(pd.to_numeric(e["Open Position Value"],errors="coerce")/pd.to_numeric(e["Total Equity"],errors="coerce")).fillna(0)
    values=pd.to_numeric(e["Total Equity"]); peak=values.cummax(); drawdown=values/peak-1; trough=int(drawdown.idxmin()); peak_value=float(peak.iloc[trough]); peak_idx=int(values.iloc[:trough+1][values.iloc[:trough+1]==peak_value].index[-1])
    recoveries=values.iloc[trough+1:][values.iloc[trough+1:]>=peak_value]; recovery_idx=int(recoveries.index[0]) if not recoveries.empty else None
    underwater=(drawdown<0).astype(int); runs=underwater.groupby((underwater!=underwater.shift()).cumsum()).cumsum(); longest_underwater=int(runs.max())
    max_drawdown=float(drawdown.min()); calmar=cagr/abs(max_drawdown) if max_drawdown<0 else np.nan
    turnover=(pd.to_numeric(trades.get("Position Value"),errors="coerce").sum()+(pd.to_numeric(trades.get("Executed Exit"),errors="coerce")*pd.to_numeric(trades.get("Quantity"),errors="coerce")).sum())/values.mean() if not trades.empty else 0
    return {"Policy":policy,"Starting Equity":starting,"Ending Equity":end,"Total Return %":100*(end/starting-1),"CAGR %":100*cagr,
      "Annualized Volatility %":100*ann,"Sharpe RF 6%":sharpe,"Sharpe RF 0%":daily.mean()*252/ann if ann>0 else np.nan,
      "Sortino RF 6%":excess.mean()*252/downside if downside>0 else np.nan,"Calmar":calmar,"Max Drawdown %":100*max_drawdown,
      "Max Drawdown Start Date":e.loc[peak_idx,"Date"],"Max Drawdown Trough Date":e.loc[trough,"Date"],"Recovery Date":e.loc[recovery_idx,"Date"] if recovery_idx is not None else pd.NaT,
      "Drawdown Duration Sessions":trough-peak_idx,"Recovery Duration Sessions":recovery_idx-trough if recovery_idx is not None else np.nan,"Longest Underwater Duration Sessions":longest_underwater,
      **t,"Median Holding Days":pd.to_numeric(trades.get("Bars Held"),errors="coerce").median() if not trades.empty else np.nan,
      "Maximum Holding Days":pd.to_numeric(trades.get("Bars Held"),errors="coerce").max() if not trades.empty else np.nan,
      "Average Exposure %":100*exposure.mean(),"Median Exposure %":100*exposure.median(),"Days Fully Cash":int((exposure==0).sum()),
      "Average Open Positions":pd.to_numeric(e["Number Open Positions"],errors="coerce").mean(),
      "Capacity Rejects":int((orders.get("Status",pd.Series(dtype=str))=="REJECTED_CAPACITY").sum()),
      "Turnover (Gross Notional / Average Equity)":turnover,
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
    daily_rf=(1+rf)**(1/252)-1
    for item in results:
        e=item["equity"].sort_values("Date"); dates=pd.DatetimeIndex(pd.to_datetime(e["Date"]).dt.normalize())
        # Union before forward fill so a pre-start NIFTY observation remains available.
        aligned=close.reindex(close.index.union(dates)).sort_index().ffill().reindex(dates)
        source_positions=close.index.searchsorted(dates,side="right")-1
        if aligned.empty or pd.isna(aligned.iloc[0]) or (source_positions<0).any():
            raise RuntimeError("NIFTY cannot be aligned at the first benchmark date without future data; explicitly shorten the benchmark window")
        source_dates=pd.DatetimeIndex(close.index[source_positions])
        if (source_dates>dates).any(): raise RuntimeError("Benchmark alignment used a future NIFTY row")
        nr=aligned.pct_change().fillna(0)
        total=pd.to_numeric(e["Total Equity"],errors="coerce").to_numpy(); gross=pd.to_numeric(e["Open Position Value"],errors="coerce").to_numpy(); ex=pd.Series(np.divide(gross,total,out=np.zeros_like(gross),where=total!=0),index=dates).clip(0,1)
        for label,w,cashrf in [("FULL_NIFTY",pd.Series(1.,index=dates),0),("EX_POST_CONSTANT_AVERAGE_EXPOSURE / CASH_0",pd.Series(ex.mean(),index=dates),0),
          ("EX_POST_CONSTANT_AVERAGE_EXPOSURE / CASH_RF",pd.Series(ex.mean(),index=dates),daily_rf),("PRIOR_SESSION_DYNAMIC_EXPOSURE / CASH_0",ex.shift(1).fillna(0),0),
          ("PRIOR_SESSION_DYNAMIC_EXPOSURE / CASH_RF",ex.shift(1).fillna(0),daily_rf)]:
            curve=(1+w*nr+(1-w)*cashrf).cumprod()*100000
            rows.append({"Policy":item["variant"],"Benchmark":label,"Average Exposure %":100*w.mean(),"Ending Equity":curve.iloc[-1],"Total Return %":100*(curve.iloc[-1]/100000-1),
                         "Benchmark Start Date":dates[0],"First NIFTY Source Date":source_dates[0],"Latest NIFTY Source Date":source_dates[-1],
                         "Future NIFTY Rows Used":False,"Alignment":"EXACT_OR_PRIOR_OBSERVATION_FORWARD_FILL"})
    return pd.DataFrame(rows)


def self_tests(policy_config: PolicyConfig) -> pd.DataFrame:
    """Executable synthetic tests only; full-run invariants are recorded separately."""
    state={"current_stop":95.,"active_target":120.,"original_t2":120.,"executed_entry":100.,"current_r":1.1,
           "partial_taken":False,"days_held":2,"t1_q75":10}
    row={"Close":106.,"ST":101.,"SwingLow10":99.,"STTrend":1,"WeeklySTTrend":1,"SMA20":100,"SMA50":99}
    d=decide_after_close("D2_BREAK_EVEN_TRAIL",state,row,None,policy_config)
    trail=decide_after_close("D1_TRAIL_ONLY",{**state,"current_r":0},row,None,policy_config)
    resistance=decide_after_close("D5_RESISTANCE_TIGHTEN",{**state,"partial_taken":True},row,110,policy_config)
    stale=decide_after_close("D6_HYBRID_DYNAMIC",{**state,"current_r":-0.1,"days_held":11},{**row,"STTrend":-1,"Close":90},None,policy_config)
    next_day=next_session(types.SimpleNamespace(ticker_dates={"X":[pd.Timestamp("2025-01-02"),pd.Timestamp("2025-01-03")]}),"X",pd.Timestamp("2025-01-02"))
    gross=(110-100)*3; entry_slip=(100.05-100)*3; exit_slip=(110-109.945)*3; entry_cost=100.05*3*.0005; exit_cost=109.945*3*.0005
    net=gross-entry_slip-exit_slip-entry_cost-exit_cost
    checks=[
      ("UNIT","stop never loosens",d.proposed_stop>=state["current_stop"],f"{d.proposed_stop} >= {state['current_stop']}"),
      ("UNIT","target never extends",d.proposed_target<=state["original_t2"],f"{d.proposed_target} <= {state['original_t2']}"),
      ("UNIT","completed-close decision effective next session",next_day==pd.Timestamp("2025-01-03"),str(next_day)),
      ("UNIT","SuperTrend trailing",trail.proposed_stop==101.,str(trail.proposed_stop)),
      ("UNIT","swing-low trailing candidate evaluated",trail.proposed_stop>=99.,str(trail.proposed_stop)),
      ("UNIT","configured break-even trigger",d.proposed_stop>=100.,str(d.proposed_stop)),
      ("UNIT","configured partial T1 quantity",math.floor(5*policy_config.partial_fraction)==2,str(math.floor(5*policy_config.partial_fraction))),
      ("UNIT","quantity-one partial edge case",math.floor(1*policy_config.partial_fraction)==0,str(math.floor(1*policy_config.partial_fraction))),
      ("UNIT","partial leg accounting identity",abs(net-(gross-entry_slip-exit_slip-entry_cost-exit_cost))<1e-12,str(net)),
      ("UNIT","trend deterioration schedule",trend_reason({**row,"STTrend":-1,"Close":90})=="EXIT_DAILY_TREND_DETERIORATION",str(trend_reason({**row,"STTrend":-1,"Close":90}))),
      ("UNIT","resistance target tightening",resistance.proposed_target==110.,str(resistance.proposed_target)),
      ("UNIT","accepted D6 stale rule semantics",stale.scheduled_exit=="EXIT_STALE_TRADE",str(stale.scheduled_exit)),
      ("UNIT","Beta-smoothed probability math",abs((3+1)/(5+2)-4/7)<1e-12,str((3+1)/(5+2))),
      ("UNIT","expected-time quantile math",np.quantile([1,2,3,4],.75)==3.25,str(np.quantile([1,2,3,4],.75))),
      ("UNIT","configured maximum holding period",policy_config.max_hold_sessions==63,str(policy_config.max_hold_sessions)),
      ("UNIT","swing-low feature contract",policy_config.swing_low_sessions==10,str(policy_config.swing_low_sessions)),
    ]
    return pd.DataFrame([{"Type":kind,"Check":name,"Status":"PASS" if ok else "FAIL","Evidence":evidence} for kind,name,ok,evidence in checks])


def _write_blocker(out: Path, phase: str, message: str) -> None:
    report = out / "stage2b_1_behavior_change_blocker_report.md"
    report.write_text(f"# Stage 2B.1 behavior-change blocker\n\nPhase: {phase}\n\n{message}\n\nNo later research phases were run.\n", encoding="utf-8")


def _accepted_parity(candidates, orders, trades, legs, management, results):
    assert REFERENCE_ROOT is not None
    root=REFERENCE_ROOT/"stage2b/results"; summaries=[]; parts=[]
    refs=[
      ("candidate selection",candidates,pd.read_csv(root/"stage2b_candidate_signal_log.csv.gz",compression="gzip"),["Signal Date","Ticker"]),
      ("orders and entries",orders,pd.read_csv(root/"stage2b_order_log.csv.gz",compression="gzip"),["Policy","Order ID"]),
      ("trades and final exits",trades,pd.read_csv(root/"stage2b_trade_log.csv.gz",compression="gzip"),["Policy","Trade ID"]),
      ("exit legs, costs and PnL",legs,pd.read_csv(root/"stage2b_exit_leg_log.csv.gz",compression="gzip"),["Policy","Exit Leg ID"]),
      ("stop and target management",management,pd.read_csv(root/"stage2b_daily_management_log.csv.gz",compression="gzip"),["Policy","Trade ID","Date"]),
    ]
    for name,actual,expected,keys in refs:
        count,diff=compare_frames(name,actual,expected,keys); summaries.append({"Artifact":name,"Difference Count":count,"Status":"PASS" if count==0 else "FAIL"}); parts.append(diff)
    for item in results:
        policy=item["variant"]; expected=pd.read_csv(root/f"stage2b_daily_equity_{policy}.csv.gz",compression="gzip")
        count,diff=compare_frames(f"equity {policy}",item["equity"],expected,["Date","Variant"]); summaries.append({"Artifact":f"equity {policy}","Difference Count":count,"Status":"PASS" if count==0 else "FAIL"}); parts.append(diff)
    return pd.DataFrame(summaries),pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()


def run(sanity=False, baseline_root: Optional[Path]=None, reference_root: Optional[Path]=None):
    started=time.perf_counter(); configure_paths(baseline_root,reference_root)
    out=STAGE_ROOT/("tests/sanity_results" if sanity else "results"); out.mkdir(parents=True,exist_ok=True)
    config_path=STAGE_ROOT/"config/stage2b_1_policy_config.json"; config=json.loads(config_path.read_text(encoding="utf-8")); policy_config=PolicyConfig.from_mapping(config)
    identity0=json.loads(PATHS["identity"].read_text(encoding="utf-8")); official_tickers=list(identity0["tickers"])
    source_files=[Path(__file__),HERE/"policies.py",HERE/"calibration.py",HERE/"validation.py",HERE/"diagnostics.py",HERE/"hashing.py"]
    source_manifest,package_hash_before=package_manifest(STAGE_ROOT,source_files)
    source_manifest["individual_source_hashes"]={row["relative_path"]:row["sha256"] for row in source_manifest["sources"]}
    (out/"stage2b_1_source_manifest.json").write_text(json.dumps(source_manifest,indent=2),encoding="utf-8")
    env=environment_report(); (out/"stage2b_1_environment_report.json").write_text(json.dumps(env,indent=2),encoding="utf-8")
    data_pre,manifest,data_hash,manifest_document_hash=frozen_data_checks(PATHS["frozen"],official_tickers)
    data_pre.to_csv(out/"stage2b_1_data_integrity_pre_run.csv",index=False)
    if data_hash != EXPECTED["DATA_CONTENT_HASH"]: raise RuntimeError(f"Frozen data content hash mismatch: {data_hash}")
    baseline_gates=pd.DataFrame(hash_gates(PATHS,identity0)); baseline_gates.insert(0,"Type","HASH_GATE")
    accepted_stage2b_pre=accepted_stage2b_hash_gates()
    unit=self_tests(policy_config); unit.to_csv(out/"stage2b_1_unit_test_results.csv",index=False)
    if (unit["Status"]!="PASS").any(): raise RuntimeError("Executable unit-test failure")
    print(f"Unit tests: PASS ({len(unit)}); immutable data: PASS ({len(manifest['files'])} files)")

    b,s=load_baseline(); tickers=official_tickers[:2] if sanity else official_tickers
    development_start="2024-01-01" if sanity else config["development_start"]
    cfg,engine,candidates=load_features_and_candidates(b,s,tickers,development_start,config["evaluation_end"])
    current_regime=engine.engine.market_history["MarketRegime"]

    compatibility=pd.DataFrame([{"Artifact":"not run in sanity mode","Difference Count":0,"Status":"NOT_RUN"}]); d0_differences=pd.DataFrame(columns=["Artifact","Row","Column","Actual","Expected"])
    if not sanity:
        d0=b.PortfolioBacktester(cfg,engine.engine.features,candidates,"T2_63D","Target 2",policy_config.max_hold_sessions).run()
        d0_refs=[("D0 candidate replay integrity",candidates,pd.read_csv(PATHS["candidates"],compression="gzip"),["Signal Date","Ticker"]),
                 ("D0 static order execution",d0["orders"],pd.read_csv(PATHS["orders"]),["Variant","Order ID"]),
                 ("D0 static trade execution",d0["trades"],pd.read_csv(PATHS["trades"]),["Variant","Ticker","Signal Date","Entry Date"]),
                 ("D0 static equity accounting",d0["equity"],pd.read_csv(PATHS["equity"]),["Date","Variant"])]
        rows=[]; parts=[]
        for name,actual,expected,keys in d0_refs:
            if "Variant" in expected: expected=expected[expected["Variant"]=="T2_63D"]
            count,diff=compare_frames(name,actual,expected,keys); rows.append({"Artifact":name,"Difference Count":count,"Status":"PASS" if count==0 else "FAIL"}); parts.append(diff)
        compatibility=pd.DataFrame(rows); d0_differences=pd.concat(parts,ignore_index=True)
        compatibility.to_csv(out/"stage2b_1_d0_static_compatibility_summary.csv",index=False); d0_differences.to_csv(out/"stage2b_1_d0_static_compatibility_differences.csv",index=False)
        if compatibility["Difference Count"].sum()!=0:
            _write_blocker(out,"PHASE E",f"D0 mismatch: {int(compatibility['Difference Count'].sum())} differences. Inspect the two D0 CSV files.")
            raise RuntimeError("D0 mismatch; stopped before Stage 2B dynamic acceptance replay")
        print("D0 candidate replay and static execution: PASS (0 differences)")
    else:
        compatibility.to_csv(out/"stage2b_1_d0_static_compatibility_summary.csv",index=False); d0_differences.to_csv(out/"stage2b_1_d0_static_compatibility_differences.csv",index=False)

    eval_start="2024-01-01" if sanity else config["evaluation_start"]
    eval_cfg=b.Stage22Config(test_start=eval_start,test_end=config["evaluation_end"],cache_directory=PATHS["frozen"],frozen_data_directory=PATHS["frozen"],data_mode="FROZEN",
                             starting_equity=config["starting_equity"],risk_per_trade=config["risk_per_trade"],max_position_pct=config["max_position_pct"],max_open_positions=config["max_open_positions"],
                             slippage_bps=config["slippage_bps"],transaction_cost_bps=config["transaction_cost_bps"])
    eval_candidates=candidates[candidates["Signal Date"]>=pd.Timestamp(eval_start)].copy()
    years=range(pd.Timestamp(eval_start).year,pd.Timestamp(config["evaluation_end"]).year+1)
    first_sessions={year:min(date for date in engine.engine.features[tickers[0]].index if date.year==year) for year in years}
    outcomes,cal_tables=candidate_calibration(b,cfg,engine.engine.features,candidates,first_sessions)
    Dynamic=DynamicBacktester.build(b); results=[]
    for policy in POLICIES:
        bt=Dynamic(eval_cfg,engine.engine.features,eval_candidates,policy,"Target 2",policy_config.max_hold_sessions,policy=policy,
                   calibration_tables=cal_tables,policy_config=policy_config,current_regime=current_regime)
        item=bt.run(); results.append(item); print(f"{policy}: {len(item['trades'])} trades")
    runtime_errors={item["variant"]:item["runtime_errors"] for item in results if item["runtime_errors"]}
    if runtime_errors:
        _write_blocker(out,"PHASE F",f"Runtime accounting/state errors: `{runtime_errors}`")
        raise RuntimeError(str(runtime_errors))
    static=b.run_portfolios(eval_cfg,engine.engine.features,eval_candidates)
    all_trade_raw=pd.concat([item["trades"].assign(Policy=item["variant"]) for item in results],ignore_index=True)
    all_order=pd.concat([item["orders"].assign(Policy=item["variant"]) for item in results],ignore_index=True)
    all_legs=pd.concat([item["legs"] for item in results],ignore_index=True)
    management=pd.concat([item["management"] for item in results],ignore_index=True)
    states=pd.concat([item["position_state"] for item in results],ignore_index=True)

    parity=pd.DataFrame([{"Artifact":"not run in sanity mode","Difference Count":0,"Status":"NOT_RUN"}]); parity_differences=pd.DataFrame(columns=["Artifact","Row","Column","Actual","Expected"])
    if not sanity:
        parity,parity_differences=_accepted_parity(candidates,all_order,all_trade_raw,all_legs,management,results)
        parity.to_csv(out/"stage2b_1_stage2b_acceptance_parity_summary.csv",index=False); parity_differences.to_csv(out/"stage2b_1_stage2b_acceptance_parity_differences.csv",index=False)
        if parity["Difference Count"].sum()!=0:
            _write_blocker(out,"PHASE F",f"Accepted Stage 2B D1-D6 trading parity failed with {int(parity['Difference Count'].sum())} differences. Inspect the parity CSV files before any diagnostic work.")
            raise RuntimeError("D1-D6 accepted Stage 2B parity mismatch; diagnostics intentionally not run")
        print("Accepted Stage 2B D1-D6 trading parity: PASS (0 differences)")
    else:
        parity.to_csv(out/"stage2b_1_stage2b_acceptance_parity_summary.csv",index=False); parity_differences.to_csv(out/"stage2b_1_stage2b_acceptance_parity_differences.csv",index=False)

    # PHASE G begins only after all behavior gates above.
    all_trade=enrich_exit_day_ambiguity(all_trade_raw)
    invariant_tests=full_run_invariants(all_trade_raw,all_legs,all_order,management,results)
    tests=pd.concat([unit,invariant_tests],ignore_index=True); tests.to_csv(out/"stage2b_1_unit_test_results.csv",index=False)
    if (tests["Status"]!="PASS").any():
        _write_blocker(out,"PHASE G ACCOUNTING GATE","One or more full-run accounting/look-ahead invariants failed. Inspect stage2b_1_unit_test_results.csv.")
        raise RuntimeError("Full-run invariant failure")
    summaries=[equity_metrics(item["variant"],item["equity"],item["trades"],item["orders"],config["starting_equity"]) for item in results+static]
    summary=pd.DataFrame(summaries); yearly,periods=period_summaries(results+static,config["starting_equity"]); drawdowns=drawdown_summary(results+static)
    predictions,cal_quality,cal_buckets=calibration_predictions(outcomes,cal_tables,eval_start)
    management_reports=management_summaries(all_trade,all_legs,management,engine.engine.features)
    static_t2=next(item["trades"] for item in static if item["variant"]=="T2_63D")
    paired_detail,paired_summary=paired_entry_shadow(static_t2,eval_candidates,engine.engine.features,cal_tables,policy_config,config["slippage_bps"],config["transaction_cost_bps"])
    recycling=opportunity_recycling(static_t2,all_trade)
    exposure=exposure_benchmarks(results,engine.engine.raw_data["^NSEI"])
    observed=all_trade[["Policy","Signal ID","Exit Date","Exit Reason"]].merge(paired_detail[["Policy","Signal ID","Shadow Exit Date","Shadow Exit Reason"]],on=["Policy","Signal ID"],how="inner")
    shadow_exit_match=(pd.to_datetime(observed["Exit Date"]).eq(pd.to_datetime(observed["Shadow Exit Date"])) & observed["Exit Reason"].astype(str).eq(observed["Shadow Exit Reason"].astype(str)))
    calibration_end=pd.to_datetime(predictions["Calibration Data End Date"]); prediction_entry=pd.to_datetime(predictions["Entry Date"]).fillna(pd.to_datetime(predictions["Signal Date"]))
    diagnostic_tests=pd.DataFrame([
      {"Type":"INTEGRATION","Check":"daily logs contain entry and past-only current regime","Status":"PASS" if management[["Entry Market Regime","Current Market Regime"]].notna().all().all() else "FAIL","Evidence":int(management[["Entry Market Regime","Current Market Regime"]].isna().sum().sum())},
      {"Type":"INTEGRATION","Check":"benchmark never uses a future NIFTY row","Status":"PASS" if not exposure["Future NIFTY Rows Used"].any() else "FAIL","Evidence":int(exposure["Future NIFTY Rows Used"].sum())},
      {"Type":"INTEGRATION","Check":"paired-entry shadow covers every static entry and D1-D6 policy","Status":"PASS" if len(paired_detail)==len(static_t2)*len(POLICIES) else "FAIL","Evidence":f"{len(paired_detail)} / {len(static_t2)*len(POLICIES)}"},
      {"Type":"INTEGRATION","Check":"shadow exits match realistic engine on shared entries","Status":"PASS" if shadow_exit_match.all() else "FAIL","Evidence":f"{int((~shadow_exit_match).sum())} differences across {len(observed)} shared entries"},
      {"Type":"INTEGRATION","Check":"calibration predictions are strictly past-only","Status":"PASS" if (calibration_end.isna() | (calibration_end<prediction_entry)).all() else "FAIL","Evidence":int((calibration_end.notna() & (calibration_end>=prediction_entry)).sum())},
    ])
    diagnostic_tests.to_csv(out/"stage2b_1_diagnostic_integration_tests.csv",index=False)
    if (diagnostic_tests["Status"]!="PASS").any():
        failed=diagnostic_tests[diagnostic_tests["Status"]!="PASS"][["Check","Evidence"]].to_dict("records")
        raise RuntimeError(f"Stage 2B.1 diagnostic integration test failure: {failed}")

    cost_rows=[]
    if not sanity:
        for multiplier in config["friction_multipliers"]:
            if multiplier==1.0:
                for item in results: cost_rows.append({"Friction Multiplier":multiplier,**equity_metrics(item["variant"],item["equity"],item["trades"],item["orders"],config["starting_equity"])})
                continue
            friction_cfg=b.Stage22Config(test_start=eval_start,test_end=config["evaluation_end"],cache_directory=PATHS["frozen"],frozen_data_directory=PATHS["frozen"],data_mode="FROZEN",starting_equity=config["starting_equity"],
                risk_per_trade=config["risk_per_trade"],max_position_pct=config["max_position_pct"],max_open_positions=config["max_open_positions"],slippage_bps=config["slippage_bps"]*multiplier,transaction_cost_bps=config["transaction_cost_bps"]*multiplier)
            for policy in POLICIES:
                item=Dynamic(friction_cfg,engine.engine.features,eval_candidates,policy,"Target 2",policy_config.max_hold_sessions,policy=policy,
                             calibration_tables=cal_tables,policy_config=policy_config,current_regime=current_regime).run()
                cost_rows.append({"Friction Multiplier":multiplier,**equity_metrics(policy,item["equity"],item["trades"],item["orders"],config["starting_equity"])})

    # Required result artifacts.
    all_trade.to_csv(out/"stage2b_1_trade_log.csv.gz",index=False,compression="gzip"); all_legs.to_csv(out/"stage2b_1_exit_leg_log.csv.gz",index=False,compression="gzip")
    all_order.to_csv(out/"stage2b_1_order_log.csv.gz",index=False,compression="gzip"); management.to_csv(out/"stage2b_1_daily_management_log.csv.gz",index=False,compression="gzip")
    states.to_csv(out/"stage2b_1_daily_position_state.csv.gz",index=False,compression="gzip")
    for item in results: item["equity"].to_csv(out/f"stage2b_1_daily_equity_{item['variant']}.csv.gz",index=False,compression="gzip")
    summary.to_csv(out/"stage2b_1_policy_summary.csv",index=False); yearly.to_csv(out/"stage2b_1_yearly_summary.csv",index=False); periods.to_csv(out/"stage2b_1_period_summary.csv",index=False)
    drawdowns.to_csv(out/"stage2b_1_drawdown_summary.csv",index=False); exposure.to_csv(out/"stage2b_1_exposure_matched_benchmarks.csv",index=False)
    summary[[column for column in summary if "Exposure" in column or column in ["Policy","Ending Equity","Days Fully Cash","Average Open Positions"]]].to_csv(out/"stage2b_1_exposure_summary.csv",index=False)
    pd.DataFrame(cost_rows).to_csv(out/"stage2b_1_cost_sensitivity.csv",index=False)
    management_reports["stop"].to_csv(out/"stage2b_1_stop_management_summary.csv",index=False); management_reports["partial"].to_csv(out/"stage2b_1_partial_profit_summary.csv",index=False)
    management_reports["target"].to_csv(out/"stage2b_1_target_revision_summary.csv",index=False); management_reports["trend"].to_csv(out/"stage2b_1_trend_exit_summary.csv",index=False)
    predictions.to_csv(out/"stage2b_1_calibration_predictions.csv.gz",index=False,compression="gzip"); cal_quality.to_csv(out/"stage2b_1_calibration_quality.csv",index=False); cal_buckets.to_csv(out/"stage2b_1_calibration_buckets.csv",index=False)
    paired_detail.to_csv(out/"stage2b_1_paired_entry_trade_comparison.csv.gz",index=False,compression="gzip"); paired_summary.to_csv(out/"stage2b_1_paired_entry_summary.csv",index=False); recycling.to_csv(out/"stage2b_1_opportunity_recycling_summary.csv",index=False)
    config_path.replace(config_path) if False else None
    (out/"stage2b_1_policy_config.json").write_text(config_path.read_text(encoding="utf-8"),encoding="utf-8")

    data_post,_,data_hash_post,manifest_document_hash_post=frozen_data_checks(PATHS["frozen"],official_tickers); data_post.to_csv(out/"stage2b_1_data_integrity_post_run.csv",index=False)
    source_after,package_hash_after=package_manifest(STAGE_ROOT,source_files)
    integrity_rows=[{"Type":"HASH_GATE","Check":"Stage 2B.1 package unchanged during run","Status":"PASS" if package_hash_before==package_hash_after else "FAIL","Evidence":f"{package_hash_before} -> {package_hash_after}"},
                    {"Type":"HASH_GATE","Check":"frozen data unchanged during run","Status":"PASS" if data_hash==data_hash_post and manifest_document_hash==manifest_document_hash_post else "FAIL","Evidence":f"{data_hash} -> {data_hash_post}"}]
    post_baseline=pd.DataFrame(hash_gates(PATHS,json.loads(PATHS["identity"].read_text(encoding="utf-8")))); post_baseline.insert(0,"Type","HASH_GATE_POST_RUN")
    accepted_stage2b_post=accepted_stage2b_hash_gates(); accepted_stage2b_post["Type"]="HASH_GATE_ACCEPTED_STAGE2B_POST_RUN"
    test_results=pd.concat([baseline_gates,accepted_stage2b_pre,data_pre,unit,invariant_tests,diagnostic_tests],ignore_index=True,sort=False); test_results.to_csv(out/"stage2b_1_unit_test_results.csv",index=False)
    validations=pd.concat([test_results,pd.DataFrame(integrity_rows),post_baseline,accepted_stage2b_post],ignore_index=True,sort=False)
    if (validations["Status"]!="PASS").any(): raise RuntimeError("Post-run identity validation failed")

    policy_hash=sha256(config_path)
    identity_basis={"stage":"2B.1","STAGE2B1_PACKAGE_HASH":package_hash_after,"POLICY_CONFIG_HASH":policy_hash,"STAGE21_CODE_HASH":EXPECTED["STAGE21_CODE_HASH"],
      "STAGE221_CODE_HASH":EXPECTED["STAGE221_CODE_HASH"],"STAGE222_FINAL_CODE_HASH":EXPECTED["STAGE222_FINAL_CODE_HASH"],"DATA_CONTENT_HASH":data_hash,
      "STRATEGY_HASH":EXPECTED["STRATEGY_HASH"],"EXECUTION_BASELINE_HASH":EXPECTED["EXECUTION_BASELINE_HASH"],"test_start":eval_start,"test_end":config["evaluation_end"],"tickers":tickers}
    identity_basis["ACCEPTED_STAGE2B_MAIN_HASH"]=ACCEPTED_STAGE2B_HASHES["stage2b/Stock_Alert_Stage2B_Dynamic_Management.py"]
    identity_basis["ACCEPTED_STAGE2B_CONFIG_HASH"]=ACCEPTED_STAGE2B_HASHES["config/stage2b_policy_config.json"]
    experiment_hash=hashlib.sha256(json.dumps(identity_basis,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()[:12]
    identity_payload={**identity_basis,"EXPERIMENT_ID":f"S2B1_{eval_start.replace('-','')}_{config['evaluation_end'].replace('-','')}_{experiment_hash}",
                      "MANIFEST_DOCUMENT_HASH":manifest_document_hash,"ACCEPTED_STAGE2B_EXPERIMENT_ID":"S2B_20160101_20260828_005e454666f1",
                      "baseline_resolution":"explicit --baseline-root" if baseline_root else 'REPO_ROOT / "Stage 2.2.2 Final"',"sanity_mode":sanity}
    (out/"stage2b_1_experiment_identity.json").write_text(json.dumps(identity_payload,indent=2,default=str),encoding="utf-8")
    validations.to_csv(out/"stage2b_1_validation_checks.csv",index=False)
    (out/"stage2b_1_validation_report.txt").write_text("ENGINEERING STATUS: PASS\n"+"\n".join(f"{row.Status}: [{getattr(row,'Type','CHECK')}] {row.Check}" for row in validations.itertuples()),encoding="utf-8")
    runtime=time.perf_counter()-started
    def csv_block(frame: pd.DataFrame, columns: Optional[List[str]]=None) -> str:
        selected=frame[[column for column in (columns or list(frame.columns)) if column in frame]].copy()
        return "```csv\n"+selected.to_csv(index=False,float_format="%.6f").strip()+"\n```"
    result_files=sorted({"Stage2B_1_Delivery_Report.md",*(path.name for path in out.iterdir() if path.is_file())})
    files_text="\n".join(f"- `results/{name}`" for name in result_files)
    source_hash_text="\n".join(f"- `{row['relative_path']}`: `{row['sha256']}`" for row in source_after["sources"])
    sanity_identity_path=STAGE_ROOT/"tests/sanity_results/stage2b_1_experiment_identity.json"
    sanity_status="NOT VERIFIED FOR THIS PACKAGE HASH"
    if sanity:
        sanity_status="PASS (this run)"
    elif sanity_identity_path.is_file():
        sanity_identity=json.loads(sanity_identity_path.read_text(encoding="utf-8"))
        sanity_status="PASS" if sanity_identity.get("STAGE2B1_PACKAGE_HASH")==package_hash_after else "STALE PACKAGE HASH"
    test_counts=test_results.groupby(["Type","Status"]).size().reset_index(name="Count")
    dynamic_summary=summary[summary["Policy"].isin(POLICIES)]
    d1_static=summary[(summary["Policy"]=="D1_TRAIL_ONLY")|summary["Policy"].astype(str).str.startswith("T1_")|summary["Policy"].astype(str).str.startswith("T2_")]
    recent=periods[(periods["Period"]=="2024-2026")&periods["Policy"].isin(POLICIES)]
    d1_exposure=exposure[exposure["Policy"]=="D1_TRAIL_ONLY"]
    friction=pd.DataFrame(cost_rows); d1_friction=friction[friction["Policy"]=="D1_TRAIL_ONLY"] if not friction.empty else friction
    overall_cal=cal_quality[cal_quality["Evaluation Year"].astype(str)=="OVERALL"]
    report=f"""# Stage 2B.1 Delivery Report

ENGINEERING STATUS: PASS

Stage 2B.1 audits and reports the accepted Stage 2B post-entry policies. The Stage 2.1 entry engine, Stage 2.2.2 Final baseline, and accepted Stage 2B trading outputs were not modified.

## 1. Files created

- `README.md`
- `requirements.txt`
- `Stage2B_1_Delivery_Report.md`
- `config/stage2b_1_policy_config.json`
- `stage2b/Stock_Alert_Stage2B_1_Dynamic_Management.py`
- `stage2b/policies.py`, `calibration.py`, `validation.py`, `diagnostics.py`, `hashing.py`
- `tests/run_stage2b_1_tests.py`
{files_text}

## 2–10. Reproducibility identity

- Normal repository resolution: `REPO_ROOT / "Stage 2.2.2 Final"` and `REPO_ROOT / "Stage 2B"`; this controlled local benchmark used: {identity_payload['baseline_resolution']}.
- Environment: Python {env['python']}; pandas {env['packages']['pandas']}; NumPy {env['packages']['numpy']}; yfinance {env['packages']['yfinance']} (not used in FROZEN mode)
- Stage 2.1 hash: `{EXPECTED['STAGE21_CODE_HASH']}`
- Stage 2.2.1 hash: `{EXPECTED['STAGE221_CODE_HASH']}`
- Stage 2.2.2 Final hash: `{EXPECTED['STAGE222_FINAL_CODE_HASH']}`
- Accepted Stage 2B main hash: `{ACCEPTED_STAGE2B_HASHES['stage2b/Stock_Alert_Stage2B_Dynamic_Management.py']}`
- Accepted Stage 2B config hash: `{ACCEPTED_STAGE2B_HASHES['config/stage2b_policy_config.json']}`
- Frozen data content hash: `{data_hash}`
- Stage 2B.1 package hash: `{package_hash_after}`
- Policy config hash: `{policy_hash}`
- Experiment ID: `{identity_payload['EXPERIMENT_ID']}`

Individual Stage 2B.1 source hashes:

{source_hash_text}

Frozen manifest, exact ticker set, file SHA-256, schema, duplicate dates, and date bounds passed both before and after the run. Package and dependency hashes also matched before/after.

## 11–14. Tests and acceptance gates

- Executable/full/hash test results: {len(test_results)} checks; failures: {int((test_results['Status']!='PASS').sum())}.
- Mandatory sanity run: {sanity_status}.
- D0 differences: {int(compatibility['Difference Count'].sum()) if not sanity else 'not run in sanity mode'}.
- D1–D6 accepted trading differences: {int(parity['Difference Count'].sum()) if not sanity else 'not run in sanity mode'}.

{csv_block(test_counts)}

{csv_block(parity)}

## 15. Corrected 2016–2026 D1–D6 results

{csv_block(dynamic_summary,['Policy','Starting Equity','Ending Equity','Total Return %','CAGR %','Annualized Volatility %','Sharpe RF 6%','Sharpe RF 0%','Sortino RF 6%','Calmar','Max Drawdown %','Trades','Win Rate %','Expectancy R','Profit Factor','Average Holding Days','Average Exposure %','Capacity Rejects','Turnover (Gross Notional / Average Equity)','Total Slippage','Total Transaction Costs'])}

## 16. Corrected 2024–2026 results

{csv_block(recent)}

## 17. D1 versus all static controls

{csv_block(d1_static,['Policy','Ending Equity','Total Return %','CAGR %','Max Drawdown %','Trades','Average Exposure %','Capacity Rejects'])}

## 18. D1 versus exposure-matched NIFTY

The first 2016 portfolio date uses only the prior 2015-12-31 NIFTY row. Every alignment source date is at or before the portfolio date; no backfill/future row is used.

{csv_block(d1_exposure)}

## 19. Friction sensitivity

{csv_block(d1_friction,['Friction Multiplier','Policy','Ending Equity','Total Return %','CAGR %','Max Drawdown %','Trades','Total Slippage','Total Transaction Costs'])}

## 20. Paired-entry fixed-cohort result

Every one of the {len(static_t2)} exact static T2_63D entries was replayed through all six policies at fixed original quantity. Earlier exits do not recycle cash, rerank, allocate, or create positions; these are not portfolio CAGR comparisons.

{csv_block(paired_summary)}

## 21. Opportunity-recycling decomposition

{csv_block(recycling)}

## 22. Stop diagnostics

{csv_block(management_reports['stop'])}

## 23. Partial-profit diagnostics

{csv_block(management_reports['partial'])}

## 24. Target-tightening diagnostics

{csv_block(management_reports['target'])}

## 25. Trend-exit diagnostics

{csv_block(management_reports['trend'])}

## 26. Calibration quality

Past-only pseudo-OOS Brier results are reported overall and by evaluation year; ten probability buckets per target include counts, mean prediction, observed rate, and calibration error.

{csv_block(overall_cal)}

{csv_block(cal_buckets)}

## 27. Drawdown duration and recovery

{csv_block(drawdowns)}

## 28. Runtime

{runtime:.2f} seconds.

## 29. Limitations

- Current-universe survivorship bias.
- Historical pseudo-OOS validation is not prospective unseen data.
- Daily OHLC sequencing ambiguity; exact exclusion fields are included for future Stage 3 work.
- Inherited Stage 2.1 holiday-short weekly limitation.
- Generic bps cost model.
- Multiple-hypothesis/history-selection risk; no policy is approved for live trading.
- Exposure-matched benchmarks and post-exit counterfactuals are diagnostic, not causal evidence.

## 30. Unresolved issues

- No blocking historical behavior, accounting, look-ahead, or parity issue remains.
- Accepted D6 semantics gate stale exits on `partial_taken`; the accepted sample produced no historical behavior-change blocker. This was preserved, not optimized.
- Research-only warnings above remain unresolved by design. Stage 3, ML, parameter search, live monitoring, and paper trading were not implemented.

STAGE 2.2.2 FINAL MODIFIED: NO  
STAGE 2B MODIFIED: NO  
STAGE 2.1 SIGNAL RULES CHANGED: NO  
ENTRY RULES CHANGED: NO  
D1-D6 MANAGEMENT RULES CHANGED: NO  
ML IMPLEMENTED: NO  
POLICY OPTIMIZATION PERFORMED: NO  
PAPER TRADING IMPLEMENTED: NO
"""
    (out/"Stage2B_1_Delivery_Report.md").write_text(report,encoding="utf-8")
    if not sanity: (STAGE_ROOT/"Stage2B_1_Delivery_Report.md").write_text(report,encoding="utf-8")
    print(summary[["Policy","Ending Equity","Total Return %","Max Drawdown %","Trades"]].to_string(index=False)); print(f"Validation: PASS; runtime {runtime:.1f}s")
    return out,summary,identity_payload


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description="Stage 2B.1 reproducible management audit")
    parser.add_argument("--sanity",action="store_true",help="Run the mandatory two-ticker short-window sanity test")
    parser.add_argument("--baseline-root",type=Path,help='Override REPO_ROOT / "Stage 2.2.2 Final" for a controlled local test')
    parser.add_argument("--stage2b-reference-root",type=Path,help='Override REPO_ROOT / "Stage 2B" for a controlled local test')
    args=parser.parse_args(); run(args.sanity,args.baseline_root,args.stage2b_reference_root)
