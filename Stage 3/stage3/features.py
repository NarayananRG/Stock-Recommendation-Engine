"""Frozen feature-engine reuse and point-in-time Stage 3 feature enrichment."""
from __future__ import annotations

import importlib.util
import io
import math
import sys
import types
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import numpy as np
import pandas as pd

from hashing import deterministic_row_id


STOCK_FEATURE_MAP = {
    "Open": "Stock Open",
    "High": "Stock High",
    "Low": "Stock Low",
    "Close": "Stock Close",
    "Volume": "Stock Volume",
    "SMA20": "Stock SMA20",
    "SMA50": "Stock SMA50",
    "SMA200": "Stock SMA200",
    "ATR": "Stock ATR",
    "ATRPct": "Stock ATR %",
    "ST": "Stock Daily ST",
    "STTrend": "Stock Daily ST Direction",
    "WeeklyST": "Stock Weekly ST",
    "WeeklySTTrend": "Stock Weekly ST Direction",
    "VolumeAvg": "Stock Average Volume 20",
    "Return1Pct": "Stock Return 1D %",
    "Return5Pct": "Stock Return 5D %",
    "Return10Pct": "Stock Return 10D %",
    "Return20Pct": "Stock Return 20D %",
    "Return60Pct": "Stock Return 60D %",
    "RealizedVol10Pct": "Stock Realized Volatility 10D %",
    "RealizedVol20Pct": "Stock Realized Volatility 20D %",
    "RangeATR": "Stock Range / ATR",
    "GapPct": "Stock Same-Day Gap %",
    "RelativeVolume5": "Stock Relative Volume 5D",
    "RelativeVolume20": "Stock Relative Volume 20D",
    "SwingLow10": "Stock Swing Low 10",
    "RecentHigh20": "Stock Recent High 20",
    "BreakoutHigh20": "Stock Breakout High 20",
}

MARKET_FEATURE_MAP = {
    "Price": "NIFTY Close",
    "SMA20": "NIFTY SMA20",
    "SMA50": "NIFTY SMA50",
    "SMA200": "NIFTY SMA200",
    "DailyRSI": "NIFTY Daily RSI",
    "WeeklyRSI": "NIFTY Weekly RSI",
    "ADX": "NIFTY ADX",
    "DailyST": "NIFTY Daily ST Direction",
    "WeeklyST": "NIFTY Weekly ST Direction",
    "MarketRegime": "NIFTY Regime",
    "MarketScore": "NIFTY Market Score",
    "ATRPct": "NIFTY ATR %",
    "DailySTValue": "NIFTY Daily ST",
    "WeeklySTValue": "NIFTY Weekly ST",
    "DistanceSMA20Pct": "NIFTY Distance SMA20 %",
    "DistanceSMA50Pct": "NIFTY Distance SMA50 %",
    "DistanceSMA200Pct": "NIFTY Distance SMA200 %",
    "Return5Pct": "NIFTY Return 5D %",
    "Return20Pct": "NIFTY Return 20D %",
    "Return60Pct": "NIFTY Return 60D %",
    "RealizedVol20Pct": "NIFTY Rolling Volatility 20D %",
    "Drawdown252Pct": "NIFTY Drawdown From 252D High %",
}


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def install_frozen_yfinance_stub() -> None:
    if "yfinance" in sys.modules:
        return
    module = types.ModuleType("yfinance")
    module.__version__ = "FROZEN_NO_NETWORK"
    module.set_tz_cache_location = lambda *args, **kwargs: None
    module.download = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Network disabled in Stage 3 FROZEN mode"))
    sys.modules["yfinance"] = module


def read_split_gzip_csv(repo_root: Path, pattern: str) -> tuple[pd.DataFrame, list[Path]]:
    parts = sorted(repo_root.glob(pattern))
    if not parts:
        raise FileNotFoundError(f"No split artifact parts match: {pattern}")
    payload = b"".join(path.read_bytes() for path in parts)
    frame = pd.read_csv(io.BytesIO(payload), compression="gzip", low_memory=False)
    return frame, parts


def load_frozen_context(repo_root: Path, config: Mapping[str, Any], tickers: Sequence[str]) -> Dict[str, Any]:
    install_frozen_yfinance_stub()
    paths = config["source_paths"]
    stage221 = _load_module("stage3_stage221_frozen", repo_root / paths["stage221"])
    stage21 = stage221.load_stage21_module(repo_root / paths["stage21"])
    frozen_config = stage221.Stage22Config(
        test_start=config["test_start"],
        test_end=config["test_end"],
        holding_periods=tuple(config["forward_horizons"]),
        slippage_bps=float(config["slippage_bps"]),
        transaction_cost_bps=float(config["transaction_cost_bps"]),
        pullback_entry_window=int(config["pullback_entry_window"]),
        breakout_gap_limit=float(config["breakout_gap_limit"]),
        cache_directory=repo_root / paths["frozen_data"],
        frozen_data_directory=repo_root / paths["frozen_data"],
        data_mode="FROZEN",
    )
    engine = stage221.CandidateSignalEngine(stage21, frozen_config, tickers)
    engine.load_data()
    engine.precompute()
    missing = sorted(set(tickers) - set(engine.engine.features))
    if missing:
        raise RuntimeError(f"Frozen feature engine omitted requested tickers: {missing}")
    stock_features = {ticker: enrich_stock_frame(frame) for ticker, frame in engine.engine.features.items()}
    market_features = enrich_market_frame(
        engine.engine.market_history,
        engine.engine.raw_data["^NSEI"],
        engine.engine.feature_engine,
    )
    return {
        "stage21": stage21,
        "stage221": stage221,
        "frozen_config": frozen_config,
        "candidate_engine": engine,
        "features": stock_features,
        "base_features": engine.engine.features,
        "raw_data": engine.engine.raw_data,
        "market": market_features,
        "market_history": engine.engine.market_history,
        "stage1_config": engine.engine.config,
    }


def enrich_stock_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    close = pd.to_numeric(result["Close"], errors="coerce")
    returns = close.pct_change()
    for horizon in (1, 5, 10, 20, 60):
        result[f"Return{horizon}Pct"] = close.pct_change(horizon) * 100.0
    for horizon in (10, 20):
        result[f"RealizedVol{horizon}Pct"] = returns.rolling(horizon, min_periods=horizon).std() * math.sqrt(252.0) * 100.0
    result["ATRPct"] = pd.to_numeric(result["ATR"], errors="coerce") / close.replace(0, np.nan) * 100.0
    result["RangeATR"] = (pd.to_numeric(result["High"], errors="coerce") - pd.to_numeric(result["Low"], errors="coerce")) / pd.to_numeric(result["ATR"], errors="coerce").replace(0, np.nan)
    result["GapPct"] = (pd.to_numeric(result["Open"], errors="coerce") / close.shift(1).replace(0, np.nan) - 1.0) * 100.0
    result["RelativeVolume5"] = pd.to_numeric(result["Volume"], errors="coerce") / pd.to_numeric(result["Volume"], errors="coerce").rolling(5, min_periods=5).mean().replace(0, np.nan)
    result["RelativeVolume20"] = pd.to_numeric(result["VolumeRatio"], errors="coerce")
    return result


def enrich_market_frame(market_history: pd.DataFrame, raw_nifty: pd.DataFrame, feature_engine: Any) -> pd.DataFrame:
    result = market_history.copy()
    technical = feature_engine.add_stock_features(raw_nifty.copy()).join(feature_engine.make_completed_weekly_map(raw_nifty.copy()))
    result["ATRPct"] = technical["ATR"] / technical["Close"].replace(0, np.nan) * 100.0
    result["DailySTValue"] = technical["ST"]
    result["WeeklySTValue"] = technical["WeeklyST"]
    for period in (20, 50, 200):
        result[f"DistanceSMA{period}Pct"] = (result["Price"] / result[f"SMA{period}"].replace(0, np.nan) - 1.0) * 100.0
    for horizon in (5, 20, 60):
        result[f"Return{horizon}Pct"] = result["Price"].pct_change(horizon) * 100.0
    result["RealizedVol20Pct"] = result["Price"].pct_change().rolling(20, min_periods=20).std() * math.sqrt(252.0) * 100.0
    rolling_high = result["Price"].rolling(252, min_periods=20).max()
    result["Drawdown252Pct"] = (result["Price"] / rolling_high - 1.0) * 100.0
    return result


def _cross_sectional_rs(features: Mapping[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    parts = []
    for ticker, frame in features.items():
        part = frame[["RS20", "RS60", "RS120"]].copy()
        part["Ticker"] = ticker
        part["Date"] = part.index
        parts.append(part.reset_index(drop=True))
    combined = pd.concat(parts, ignore_index=True)
    for column in ("RS20", "RS60", "RS120"):
        combined[f"{column}_Percentile"] = combined.groupby("Date")[column].rank(pct=True, method="average") * 100.0
    return {ticker: group.set_index("Date").sort_index() for ticker, group in combined.groupby("Ticker")}


def build_signal_state_dataset(
    source: pd.DataFrame,
    features: Mapping[str, pd.DataFrame],
    market: pd.DataFrame,
    config: Mapping[str, Any],
    experiment_id: str,
) -> pd.DataFrame:
    result = source.copy()
    result["Signal Date"] = pd.to_datetime(result["Signal Date"], errors="raise").dt.normalize()
    result["Original Signal"] = result["Signal"].astype(str)
    result["Feature As-Of Date"] = result["Signal Date"]
    result["Earliest Trading Action Date Rule"] = "NEXT_VALID_SESSION"
    result["Dataset Cohort"] = "SIGNAL_STATE"
    result["Source Experiment ID"] = config["source_experiment_id"]
    result["Stage 3 Experiment ID"] = experiment_id
    schema = config["dataset_schema_versions"]["signal_state"]
    result["STAGE3_ROW_ID"] = [deterministic_row_id(schema, signal_id) for signal_id in result["Signal ID"]]
    cross = _cross_sectional_rs(features)
    chunks = []
    for ticker, group in result.groupby("Ticker", sort=False):
        stock = features[str(ticker)]
        dates = pd.DatetimeIndex(group["Signal Date"])
        selected = stock.reindex(dates)
        if selected.index.has_duplicates:
            selected = selected.groupby(level=0).last().reindex(dates)
        enriched = group.copy().reset_index(drop=False).rename(columns={"index": "_source_order"})
        for source_name, target_name in STOCK_FEATURE_MAP.items():
            enriched[target_name] = selected[source_name].to_numpy()
        cross_selected = cross[str(ticker)].reindex(dates)
        enriched["RS20 Cross-Sectional Percentile"] = cross_selected["RS20_Percentile"].to_numpy()
        enriched["RS60 Cross-Sectional Percentile"] = cross_selected["RS60_Percentile"].to_numpy()
        enriched["RS120 Cross-Sectional Percentile"] = cross_selected["RS120_Percentile"].to_numpy()
        chunks.append(enriched)
    result = pd.concat(chunks, ignore_index=True).sort_values("_source_order").drop(columns="_source_order").reset_index(drop=True)
    signal_dates = pd.DatetimeIndex(result["Signal Date"])
    positions = market.index.searchsorted(signal_dates, side="right") - 1
    if (positions < 0).any():
        raise RuntimeError("A signal predates all frozen NIFTY feature history")
    source_dates = market.index[positions]
    market_selected = market.iloc[positions].copy()
    result["NIFTY Feature Source Date"] = pd.DatetimeIndex(source_dates).to_numpy()
    for source_name, target_name in MARKET_FEATURE_MAP.items():
        result[target_name] = market_selected[source_name].to_numpy()
    result["Distance To Support %"] = (pd.to_numeric(result["Price"]) / pd.to_numeric(result["Support"]).replace(0, np.nan) - 1.0) * 100.0
    result["Distance To T1 %"] = (pd.to_numeric(result["Target 1"]) / pd.to_numeric(result["Price"]).replace(0, np.nan) - 1.0) * 100.0
    result["Distance To T2 %"] = (pd.to_numeric(result["Target 2"]) / pd.to_numeric(result["Price"]).replace(0, np.nan) - 1.0) * 100.0
    result["Initial Risk %"] = (pd.to_numeric(result["Entry High"]) - pd.to_numeric(result["Stop Loss"])) / pd.to_numeric(result["Entry High"]).replace(0, np.nan) * 100.0
    atr = pd.to_numeric(result["Stock ATR"], errors="coerce").replace(0, np.nan)
    result["Stop Distance ATR"] = (pd.to_numeric(result["Entry High"]) - pd.to_numeric(result["Stop Loss"])) / atr
    result["T1 Distance ATR"] = (pd.to_numeric(result["Target 1"]) - pd.to_numeric(result["Entry High"])) / atr
    result["T2 Distance ATR"] = (pd.to_numeric(result["Target 2"]) - pd.to_numeric(result["Entry High"])) / atr
    return result


def feature_registry(signal_state: pd.DataFrame, position_day: pd.DataFrame | None = None) -> pd.DataFrame:
    rows = []
    identifier = {"Ticker", "Signal Date", "Signal ID", "STAGE3_ROW_ID", "Feature As-Of Date", "Source Experiment ID", "Stage 3 Experiment ID", "Experiment ID"}
    future_markers = ("Candidate ", "ENTRY_", "FWD_", "MFE_", "MAE_", "T1_", "T2_", "STOP_", "D1_")
    source_groups = {
        "Market Regime": "MARKET_CONTEXT", "Market Score": "MARKET_CONTEXT",
        "Price": "STOCK_TREND", "20 DMA": "STOCK_TREND", "50 DMA": "STOCK_TREND", "200 DMA": "STOCK_TREND",
        "Daily RSI": "MOMENTUM", "Weekly RSI": "MOMENTUM", "ADX": "MOMENTUM",
        "Daily ST": "STOCK_TREND", "Weekly ST": "STOCK_TREND", "Volume Ratio": "VOLUME",
        "RS 20D": "RELATIVE_STRENGTH", "RS 60D": "RELATIVE_STRENGTH", "RS 120D": "RELATIVE_STRENGTH",
        "Setup": "SETUP_STRUCTURE", "Support": "SETUP_STRUCTURE", "Resistance 1": "SETUP_STRUCTURE", "Resistance 2": "SETUP_STRUCTURE",
        "Entry Low": "RISK_REWARD", "Entry High": "RISK_REWARD", "Stop Loss": "RISK_REWARD", "Target 1": "RISK_REWARD", "Target 2": "RISK_REWARD", "R:R T1": "RISK_REWARD", "R:R T2": "RISK_REWARD",
        "Signal": "RULE_ENGINE_DERIVED_FEATURES", "Original Signal": "RULE_ENGINE_DERIVED_FEATURES", "Trade Quality": "RULE_ENGINE_DERIVED_FEATURES", "Technical Score": "RULE_ENGINE_DERIVED_FEATURES", "Actionability Score": "RULE_ENGINE_DERIVED_FEATURES",
    }
    for column in signal_state.columns:
        if column in identifier or column.startswith(("STAGE", "DATA_", "STRATEGY_", "EXECUTION_", "MANIFEST_")) or column in {"Survivorship Bias Warning", "Dataset Cohort", "Earliest Trading Action Date Rule"}:
            continue
        if column.startswith(future_markers):
            continue
        group = source_groups.get(column)
        if group is None:
            if column.startswith("NIFTY"):
                group = "MARKET_CONTEXT"
            elif column.startswith("Stock Return"):
                group = "MOMENTUM"
            elif "Volatility" in column or "ATR" in column or "Range" in column or "Gap" in column:
                group = "VOLATILITY"
            elif "Volume" in column:
                group = "VOLUME"
            elif column.startswith("RS"):
                group = "RELATIVE_STRENGTH"
            elif any(token in column for token in ("Support", "Resistance", "Breakout", "Swing", "Overextended", "Trend Structure")):
                group = "SETUP_STRUCTURE"
            elif any(token in column for token in ("Entry", "Stop", "T1", "T2", "Risk", "R:R")):
                group = "RISK_REWARD"
            else:
                group = "STOCK_TREND"
        rows.append({
            "Feature Name": column,
            "Feature Group": group,
            "Data Type": str(signal_state[column].dtype),
            "Source": "Frozen Stage 2.2.2 candidate" if column in source_groups else "Frozen OHLC / exact Stage 2.1 engine",
            "Formula / Description": "Point-in-time value known at the completed signal-session close",
            "As-Of Semantics": "SIGNAL SESSION CLOSE",
            "Point-In-Time Safe": True,
            "ML Allowed": True,
            "Reason if ML Disallowed": "",
            "Missing Value Meaning": "Insufficient prior history or no legitimate frozen trade level",
            "Known Ambiguity": "Daily OHLC only" if column == "Stock Same-Day Gap %" else "",
            "Stage Source": "Stage 2.1 / Stage 2.2.2 Final / Stage 3 deterministic rolling enrichment",
        })
    # Position-day inputs are registered explicitly.  This prevents a current
    # state variable from becoming an ML input merely because it happens to be
    # present in the wide research artifact.
    position_groups = {
        "Days Held": "TRADE_STATE",
        "Executed Entry": "RISK_REWARD",
        "Initial Stop": "RISK_REWARD",
        "Previous Session Stop": "RISK_REWARD",
        "Current Stop": "RISK_REWARD",
        "Original T1": "RISK_REWARD",
        "Original T2": "RISK_REWARD",
        "Current Close": "STOCK_TREND",
        "Current R": "TRADE_STATE",
        "Current MFE Conservative To Date": "TRADE_STATE",
        "Current MAE Conservative To Date": "TRADE_STATE",
        "Stop Distance R": "RISK_REWARD",
        "T1 Distance R": "RISK_REWARD",
        "T2 Distance R": "RISK_REWARD",
        "Stop Revision Count": "TRADE_STATE",
        "SMA20": "STOCK_TREND",
        "SMA50": "STOCK_TREND",
        "SMA200": "STOCK_TREND",
        "Daily ST": "STOCK_TREND",
        "Daily ST Direction": "STOCK_TREND",
        "Weekly ST": "STOCK_TREND",
        "Weekly ST Direction": "STOCK_TREND",
        "RSI": "MOMENTUM",
        "Weekly RSI": "MOMENTUM",
        "ADX": "MOMENTUM",
        "ATR": "VOLATILITY",
        "RS20": "RELATIVE_STRENGTH",
        "RS60": "RELATIVE_STRENGTH",
        "RS120": "RELATIVE_STRENGTH",
        "Current Stock Return 5D %": "MOMENTUM",
        "Current Stock Return 20D %": "MOMENTUM",
        "Current Stock Realized Volatility 20D %": "VOLATILITY",
        "Current Volume Ratio": "VOLUME",
        "Entry Market Regime": "MARKET_CONTEXT",
        "Current Market Regime": "MARKET_CONTEXT",
        "Entry Technical Score": "RULE_ENGINE_DERIVED_FEATURES",
        "Entry Actionability Score": "RULE_ENGINE_DERIVED_FEATURES",
        "Current NIFTY Close": "MARKET_CONTEXT",
        "Current NIFTY Daily RSI": "MARKET_CONTEXT",
        "Current NIFTY Weekly RSI": "MARKET_CONTEXT",
        "Current NIFTY ADX": "MARKET_CONTEXT",
        "Current NIFTY ATR %": "MARKET_CONTEXT",
        "Current NIFTY Daily ST Direction": "MARKET_CONTEXT",
        "Current NIFTY Weekly ST Direction": "MARKET_CONTEXT",
        "Current NIFTY Return 5D %": "MARKET_CONTEXT",
        "Current NIFTY Return 20D %": "MARKET_CONTEXT",
        "Current NIFTY Volatility 20D %": "MARKET_CONTEXT",
        "Current NIFTY Drawdown 252D %": "MARKET_CONTEXT",
    }
    if position_day is not None:
        for column, group in position_groups.items():
            if column not in position_day.columns:
                continue
            rows.append({
                "Feature Name": column,
                "Feature Group": group,
                "Data Type": str(position_day[column].dtype),
                "Source": "Independent frozen D1 shadow state",
                "Formula / Description": "State known at the completed management-session close",
                "As-Of Semantics": "COMPLETED MANAGEMENT SESSION CLOSE",
                "Point-In-Time Safe": True,
                "ML Allowed": True,
                "Reason if ML Disallowed": "",
                "Missing Value Meaning": "Insufficient prior history",
                "Known Ambiguity": "Entry-bar OHLC excluded" if "Conservative To Date" in column else "",
                "Stage Source": "Stage 2B.1 D1_TRAIL_ONLY / frozen Stage 2.1 features / Stage 3 state calculation",
            })
    return pd.DataFrame(rows).drop_duplicates("Feature Name").sort_values("Feature Name").reset_index(drop=True)


def point_in_time_audit(context: Mapping[str, Any], config: Mapping[str, Any]) -> pd.DataFrame:
    stage21 = context["stage21"]
    raw_data = context["raw_data"]
    full_features = context["features"]
    full_market = context["market"]
    stage1_config = context["stage1_config"]
    eras = (("2012-2015", "2015-12-31"), ("2016-2020", "2020-12-31"), ("2021-2023", "2023-12-31"), ("2024-2026", config["test_end"]))
    representative = [
        "SMA20", "SMA50", "SMA200", "RSI", "ATR", "ADX", "ST", "STTrend",
        "WeeklyRSI", "WeeklySTTrend", "RS20", "RS60", "RS120", "ATRPct",
        "Return1Pct", "Return5Pct", "Return10Pct", "Return20Pct", "Return60Pct",
        "RealizedVol10Pct", "RealizedVol20Pct", "RangeATR", "GapPct",
        "RelativeVolume5", "RelativeVolume20",
    ]
    rows = []
    for ticker in config["audit_tickers"]:
        if ticker not in raw_data or ticker not in full_features:
            continue
        for era, cutoff_text in eras:
            available = raw_data[ticker].loc[:pd.Timestamp(cutoff_text)]
            if available.empty or available.index.max() < pd.Timestamp(era[:4] + "-01-01"):
                rows.append({"Ticker": ticker, "Era": era, "Cutoff": pd.NaT, "Feature": "ALL", "Full Value": np.nan, "Prefix Value": np.nan, "Absolute Difference": np.nan, "Status": "SKIP_NOT_AVAILABLE", "Source Max Date": pd.NaT})
                continue
            cutoff = pd.Timestamp(available.index.max()).normalize()
            nifty_prefix = raw_data["^NSEI"].loc[:cutoff].copy()
            stock_prefix = raw_data[ticker].loc[:cutoff].copy()
            engine = stage21.FeatureEngine(stage1_config)
            market_prefix = engine.market_regime_history(nifty_prefix)
            prepared = stage21.FrozenStrategy(stage1_config, market_prefix).prepare_stock(ticker, stock_prefix)
            prefix = enrich_stock_frame(prepared)
            full = full_features[ticker]
            for feature in representative:
                left, right = full.at[cutoff, feature], prefix.at[cutoff, feature]
                if pd.isna(left) and pd.isna(right):
                    difference, status = 0.0, "PASS"
                elif isinstance(left, str) or isinstance(right, str):
                    difference, status = (0.0, "PASS") if str(left) == str(right) else (np.nan, "FAIL")
                else:
                    difference = abs(float(left) - float(right))
                    status = "PASS" if difference <= 1e-10 else "FAIL"
                rows.append({"Ticker": ticker, "Era": era, "Cutoff": cutoff, "Feature": feature, "Full Value": left, "Prefix Value": right, "Absolute Difference": difference, "Status": status, "Source Max Date": stock_prefix.index.max()})
            market_full_row, market_prefix_frame = full_market.loc[cutoff], enrich_market_frame(market_prefix, nifty_prefix, engine)
            for feature in ("Return5Pct", "Return20Pct", "Return60Pct", "RealizedVol20Pct", "Drawdown252Pct"):
                left, right = market_full_row[feature], market_prefix_frame.at[cutoff, feature]
                difference = 0.0 if pd.isna(left) and pd.isna(right) else abs(float(left) - float(right))
                rows.append({"Ticker": ticker, "Era": era, "Cutoff": cutoff, "Feature": "NIFTY " + feature, "Full Value": left, "Prefix Value": right, "Absolute Difference": difference, "Status": "PASS" if difference <= 1e-10 else "FAIL", "Source Max Date": nifty_prefix.index.max()})
    return pd.DataFrame(rows)
