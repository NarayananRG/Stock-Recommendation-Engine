from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def normalize_daily(result: dict[str, Any], policy: str, exit_engine: str) -> pd.DataFrame:
    frame = result["equity"].copy().sort_values("Date").reset_index(drop=True)
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.normalize()
    frame = frame.rename(columns={
        "Total Equity": "Equity", "Daily Return %": "Daily Return %",
        "Open Position Value": "Invested Value", "Number Open Positions": "Open Positions",
    })
    frame["Exposure"] = (frame["Invested Value"] / frame["Equity"]).fillna(0.0)
    frame["Realized PnL"] = 0.0
    frame["Costs"] = 0.0
    trades = result.get("trades", pd.DataFrame()).copy()
    if not trades.empty:
        zero_cost = pd.Series(0.0, index=trades.index)
        entry_transaction = pd.to_numeric(trades["Entry Transaction Cost"] if "Entry Transaction Cost" in trades else zero_cost, errors="coerce").fillna(0)
        exit_transaction = pd.to_numeric(trades["Exit Transaction Cost"] if "Exit Transaction Cost" in trades else zero_cost, errors="coerce").fillna(0)
        if "Entry Slippage Cost" in trades:
            entry_slippage = pd.to_numeric(trades["Entry Slippage Cost"], errors="coerce").fillna(0)
            exit_slippage = pd.to_numeric(trades["Exit Slippage Cost"], errors="coerce").fillna(0)
        else:
            entry_slippage = zero_cost
            exit_slippage = pd.to_numeric(trades["Slippage Cost"] if "Slippage Cost" in trades else zero_cost, errors="coerce").fillna(0)
        costs = pd.concat([
            pd.DataFrame({"Date": pd.to_datetime(trades["Entry Date"]).dt.normalize(), "Cost": entry_transaction + entry_slippage}),
            pd.DataFrame({"Date": pd.to_datetime(trades["Exit Date"]).dt.normalize(), "Cost": exit_transaction + exit_slippage}),
        ]).groupby("Date")["Cost"].sum()
        frame["Costs"] = frame["Date"].map(costs).fillna(0.0)
        realized = pd.DataFrame({
            "Date": pd.to_datetime(trades["Exit Date"]).dt.normalize(),
            "Realized Net PnL": pd.to_numeric(trades["Net PnL"], errors="coerce").fillna(0.0),
        }).groupby("Date")["Realized Net PnL"].sum()
        frame["Realized PnL"] = frame["Date"].map(realized).fillna(0.0)
    frame["Policy"] = policy
    frame["Exit Engine"] = exit_engine
    return frame[["Policy", "Exit Engine", "Date", "Equity", "Daily Return %", "Cash", "Invested Value", "Exposure", "Open Positions", "Realized PnL", "Costs"]]


def enrich_trades(result: dict[str, Any], policy: str, exit_engine: str, membership: pd.DataFrame) -> pd.DataFrame:
    frame = result["trades"].copy()
    if frame.empty:
        return frame
    frame["Signal Date"] = pd.to_datetime(frame["Signal Date"]).dt.normalize()
    if "Signal ID" not in frame:
        key = membership[["Signal ID", "Ticker", "Signal Date"]].copy()
        key["Signal Date"] = pd.to_datetime(key["Signal Date"]).dt.normalize()
        frame = frame.merge(key, on=["Ticker", "Signal Date"], how="left", validate="many_to_one")
        if frame["Signal ID"].isna().any():
            raise RuntimeError("D0 trade could not be mapped back to a Signal ID")
    lookup = membership.set_index("Signal ID")
    if "Initial Stop" not in frame and "Stop" in frame:
        frame["Initial Stop"] = frame["Stop"]
    if "Original T1" not in frame:
        frame["Original T1"] = frame["Signal ID"].map(lookup["Target 1"])
    if "Original T2" not in frame:
        frame["Original T2"] = frame["Signal ID"].map(lookup["Target 2"])
    frame["Policy"] = policy
    frame["Exit Engine"] = exit_engine
    frame["Selection Rank"] = frame["Signal ID"].map(lookup.get(f"{policy.split('_K')[0]} Rank", pd.Series(dtype=float))) if policy.startswith("R") else np.nan
    frame["Selection Score"] = frame["Signal ID"].map(lookup.get(f"{policy.split('_K')[0]} Score", pd.Series(dtype=float))) if policy.startswith("R") else np.nan
    frame["Daily K"] = int(policy[-1]) if policy.endswith(("K1", "K2")) else "ALL"
    frame["Same-Date Candidate Count"] = frame["Signal ID"].map(lookup["Same-Date Candidate Count"])
    zeros = pd.Series(0.0, index=frame.index)
    frame["Costs"] = pd.to_numeric(frame["Slippage Cost"] if "Slippage Cost" in frame else zeros, errors="coerce").fillna(0) + pd.to_numeric(frame["Transaction Cost"] if "Transaction Cost" in frame else zeros, errors="coerce").fillna(0)
    risk = pd.to_numeric(frame["Initial Risk Per Share"], errors="coerce")
    entry = pd.to_numeric(frame["Executed Entry"], errors="coerce")
    t1_r = (pd.to_numeric(frame["Original T1"], errors="coerce") - entry) / risk
    t2_r = (pd.to_numeric(frame["Original T2"], errors="coerce") - entry) / risk
    mfe_column = next((name for name in ("MFE R Full Bar", "MFE R", "MFE_R_FULL_BAR_DIAGNOSTIC") if name in frame), None)
    mfe = pd.to_numeric(frame[mfe_column] if mfe_column else pd.Series(np.nan, index=frame.index), errors="coerce")
    if mfe.notna().any():
        frame["T1 Price Touched"] = mfe.ge(t1_r)
        frame["T2 Price Touched"] = mfe.ge(t2_r)
        frame["T1 Diagnostic Success"] = frame["T1 Price Touched"]
        frame["T2 Diagnostic Success"] = frame["T2 Price Touched"]
        frame["Target Diagnostic Semantics"] = "FULL_BAR_PRICE_TOUCH_NON_CONSERVATIVE_STOP_FIRST_AMBIGUITY"
    else:
        frame["T1 Reached"] = frame["Signal ID"].map(lookup["T1_BEFORE_STOP_63"]).eq(1)
        frame["T2 Reached"] = frame["Signal ID"].map(lookup["T2_BEFORE_STOP_63"]).eq(1)
        frame["T1 Diagnostic Success"] = frame["T1 Reached"]
        frame["T2 Diagnostic Success"] = frame["T2 Reached"]
        frame["Target Diagnostic Semantics"] = "AUTHORITATIVE_FROZEN_STOP_FIRST_OUTCOME"
    frame["Holding Sessions"] = pd.to_numeric(frame["Bars Held"], errors="coerce")
    frame["Net R"] = pd.to_numeric(frame["R Multiple"], errors="coerce")
    return frame


def _drawdown(equity: pd.Series) -> tuple[float, Any, Any, Any]:
    values = pd.to_numeric(equity).astype(float).reset_index(drop=True)
    dd = values / values.cummax() - 1.0
    trough = int(dd.idxmin())
    peak_value = float(values.iloc[: trough + 1].max())
    peak = int(values.iloc[: trough + 1][values.iloc[: trough + 1] == peak_value].index[-1])
    recovery = values.iloc[trough + 1 :]
    recovery = recovery[recovery >= peak_value]
    return float(dd.iloc[trough]), peak, trough, (int(recovery.index[0]) if not recovery.empty else None)


def portfolio_metrics(policy: str, daily: pd.DataFrame, trades: pd.DataFrame, orders: pd.DataFrame, candidate_count: int, selected_count: int) -> dict[str, Any]:
    e = daily.sort_values("Date").reset_index(drop=True)
    start = 100000.0
    ending = float(e["Equity"].iloc[-1])
    years = max((e["Date"].iloc[-1] - e["Date"].iloc[0]).days / 365.25, 1 / 365.25)
    returns = pd.to_numeric(e["Daily Return %"], errors="coerce").fillna(0.0) / 100.0
    vol = float(returns.std(ddof=1) * math.sqrt(252))
    rf6 = 1.06 ** (1 / 252) - 1
    dd, peak_i, trough_i, recovery_i = _drawdown(e["Equity"])
    r = pd.to_numeric(trades.get("Net R", pd.Series(dtype=float)), errors="coerce").dropna()
    pnl = pd.to_numeric(trades.get("Net PnL", pd.Series(dtype=float)), errors="coerce").dropna()
    positive = float(pnl[pnl > 0].sum())
    negative = float(-pnl[pnl < 0].sum())
    downside0 = returns[returns < 0].std(ddof=1) * math.sqrt(252)
    excess6 = returns - rf6
    downside6 = excess6[excess6 < 0].std(ddof=1) * math.sqrt(252)
    statuses = orders.get("Status", pd.Series(dtype=str)).astype(str)
    total_return = ending / start - 1
    cagr = (ending / start) ** (1 / years) - 1
    exposure = pd.to_numeric(e["Exposure"], errors="coerce").fillna(0)
    open_positions = pd.to_numeric(e["Open Positions"], errors="coerce").fillna(0)
    t1 = trades.get("T1 Diagnostic Success", pd.Series(dtype=bool)).fillna(False).astype(bool)
    t2 = trades.get("T2 Diagnostic Success", pd.Series(dtype=bool)).fillna(False).astype(bool)
    diagnostic_semantics = trades.get("Target Diagnostic Semantics", pd.Series(dtype=str)).dropna().unique().tolist()
    costs = pd.to_numeric(trades.get("Costs", pd.Series(dtype=float)), errors="coerce").fillna(0)
    avg_exposure = float(exposure.mean() * 100)
    avg_invested = float(pd.to_numeric(e["Invested Value"], errors="coerce").mean())
    return {
        "Policy": policy, "Starting Equity": start, "Ending Equity": ending, "Total Return %": total_return * 100,
        "CAGR %": cagr * 100, "Annualized Volatility %": vol * 100,
        "Sharpe Ratio RF=0": returns.mean() * 252 / vol if vol > 0 else np.nan,
        "Sharpe Ratio RF=6%": excess6.mean() * 252 / vol if vol > 0 else np.nan,
        "Sortino RF=0": returns.mean() * 252 / downside0 if downside0 and not np.isnan(downside0) else np.nan,
        "Sortino RF=6%": excess6.mean() * 252 / downside6 if downside6 and not np.isnan(downside6) else np.nan,
        "Calmar Ratio": cagr / abs(dd) if dd < 0 else np.nan, "Maximum Drawdown %": dd * 100,
        "Max Drawdown Peak Date": e.loc[peak_i, "Date"], "Max Drawdown Trough Date": e.loc[trough_i, "Date"],
        "Recovery Date": e.loc[recovery_i, "Date"] if recovery_i is not None else pd.NaT,
        "Trade Count": len(trades), "Winning Trades": int((pnl > 0).sum()), "Losing Trades": int((pnl < 0).sum()),
        "Win Rate %": float((pnl > 0).mean() * 100) if len(pnl) else np.nan,
        "Mean Net R": float(r.mean()) if len(r) else np.nan, "Median Net R": float(r.median()) if len(r) else np.nan,
        "Expectancy R": float(r.mean()) if len(r) else np.nan, "Profit Factor": positive / negative if negative > 0 else np.nan,
        "Average Holding Sessions": float(trades.get("Holding Sessions", pd.Series(dtype=float)).mean()),
        "Median Holding Sessions": float(trades.get("Holding Sessions", pd.Series(dtype=float)).median()),
        "Average Exposure %": avg_exposure, "Maximum Exposure %": float(exposure.max() * 100),
        "Return / Average Exposure": total_return * 100 / avg_exposure if avg_exposure > 0 else np.nan,
        "Net PnL / Average Invested Capital %": float(pnl.sum() / avg_invested * 100) if avg_invested > 0 else np.nan,
        "Average Open Positions": float(open_positions.mean()), "Maximum Open Positions": int(open_positions.max()),
        "Days Fully Cash": int(exposure.eq(0).sum()), "Candidate Count": candidate_count, "Selected Candidate Count": selected_count,
        "Entry Filled Count": int(statuses.eq("FILLED").sum()), "Fill Rate %": float(statuses.eq("FILLED").sum() / selected_count * 100),
        "Invalid Risk Count": int(statuses.eq("INVALID_DATA").sum()), "Expired Entry Count": int(statuses.eq("EXPIRED").sum()),
        "Capital Rejection Count": int(statuses.eq("REJECTED_CAPACITY").sum()),
        "Target Diagnostic Semantics": diagnostic_semantics[0] if len(diagnostic_semantics) == 1 else "NONE",
        "T1 Diagnostic Count": int(t1.sum()), "T1 Diagnostic Rate %": float(t1.mean() * 100) if len(t1) else np.nan,
        "T2 Diagnostic Count": int(t2.sum()), "T2 Diagnostic Rate %": float(t2.mean() * 100) if len(t2) else np.nan,
        "Total Costs": float(costs.sum()),
    }


def period_metrics(daily: pd.DataFrame, trades: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    e = daily[daily["Date"].between(start, end)].copy()
    t = trades[pd.to_datetime(trades.get("Exit Date", pd.Series(dtype=str))).between(start, end)].copy() if not trades.empty else trades
    if e.empty:
        return {}
    start_equity = float(e["Equity"].iloc[0] / (1 + e["Daily Return %"].iloc[0] / 100.0))
    end_equity = float(e["Equity"].iloc[-1])
    r = pd.to_numeric(t.get("Net R", pd.Series(dtype=float)), errors="coerce").dropna()
    pnl = pd.to_numeric(t.get("Net PnL", pd.Series(dtype=float)), errors="coerce").dropna()
    dd, *_ = _drawdown(e["Equity"])
    years = max((e["Date"].iloc[-1] - e["Date"].iloc[0]).days / 365.25, 1 / 365.25)
    return {"Start Equity": start_equity, "End Equity": end_equity, "Return %": (end_equity / start_equity - 1) * 100,
            "CAGR %": ((end_equity / start_equity) ** (1 / years) - 1) * 100, "Trades": len(t),
            "Win Rate %": float((pnl > 0).mean() * 100) if len(pnl) else np.nan, "Expectancy R": float(r.mean()) if len(r) else np.nan,
            "Profit Factor": float(pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()) if (pnl < 0).any() else np.nan,
            "Average Exposure %": float(e["Exposure"].mean() * 100), "Max Drawdown %": dd * 100}
