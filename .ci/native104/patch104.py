from pathlib import Path
import os

root = Path(os.environ["SRE_ENGINE_ROOT"])

technical_module = r'''from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd


SCHEMA_VERSION = "SRE_TECHNICAL_INTELLIGENCE_V2"
AUTHORITY = "SHADOW_ONLY"
MIN_BARS = 220
ANALOGUE_MIN_SAMPLE = 10
ANALOGUE_K = 20


def _finite(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _last(series: pd.Series) -> float | None:
    if series is None or len(series) == 0:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    return _finite(values.iloc[-1]) if not values.empty else None


def canonical_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    data = frame.copy()
    aliases = {str(c).strip().lower(): c for c in data.columns}
    if not isinstance(data.index, pd.DatetimeIndex):
        date_col = next((aliases[k] for k in ("date", "datetime", "timestamp", "session") if k in aliases), None)
        if date_col is None:
            raise ValueError("OHLCV frame has no date column or DatetimeIndex")
        data.index = pd.to_datetime(data.pop(date_col), errors="coerce")
    else:
        data.index = pd.to_datetime(data.index, errors="coerce")
    data = data[~data.index.isna()].copy()
    rename = {}
    for target in ("Open", "High", "Low", "Close", "Volume"):
        source = aliases.get(target.lower(), target if target in data.columns else None)
        if source is not None and source in data.columns:
            rename[source] = target
    data = data.rename(columns=rename)
    missing = [c for c in ("Open", "High", "Low", "Close") if c not in data.columns]
    if missing:
        raise ValueError("OHLCV frame missing columns: " + ", ".join(missing))
    if "Volume" not in data.columns:
        data["Volume"] = 0.0
    for c in ("Open", "High", "Low", "Close", "Volume"):
        data[c] = pd.to_numeric(data[c], errors="coerce")
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    data = data[~data.index.duplicated(keep="last")].sort_index()
    return data[["Open", "High", "Low", "Close", "Volume"]]


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / float(period), adjust=False, min_periods=period).mean()


def _true_range(data: pd.DataFrame) -> pd.Series:
    prev_close = data["Close"].shift(1)
    return pd.concat(
        [
            data["High"] - data["Low"],
            (data["High"] - prev_close).abs(),
            (data["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    diff = close.diff()
    gain = diff.clip(lower=0.0)
    loss = -diff.clip(upper=0.0)
    avg_gain = _wilder(gain, period)
    avg_loss = _wilder(loss, period)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    return rsi


def _adx(data: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    high, low = data["High"], data["Low"]
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0.0), 0.0)
    minus_dm = down.where((down > up) & (down > 0.0), 0.0)
    atr = _wilder(_true_range(data), period)
    plus_di = 100.0 * _wilder(plus_dm, period) / atr.replace(0.0, np.nan)
    minus_di = 100.0 * _wilder(minus_dm, period) / atr.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = _wilder(dx, period)
    return adx, plus_di, minus_di


def _supertrend(data: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
    atr = _wilder(_true_range(data), period)
    hl2 = (data["High"] + data["Low"]) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    final_upper = upper.copy()
    final_lower = lower.copy()
    trend = pd.Series(index=data.index, dtype="float64")
    st = pd.Series(index=data.index, dtype="float64")
    close = data["Close"]
    for i in range(len(data)):
        if i == 0 or not math.isfinite(float(atr.iloc[i])) if pd.notna(atr.iloc[i]) else True:
            trend.iloc[i] = 1.0
            st.iloc[i] = np.nan
            continue
        if pd.isna(final_upper.iloc[i - 1]) or close.iloc[i - 1] > final_upper.iloc[i - 1]:
            final_upper.iloc[i] = upper.iloc[i]
        else:
            final_upper.iloc[i] = min(upper.iloc[i], final_upper.iloc[i - 1])
        if pd.isna(final_lower.iloc[i - 1]) or close.iloc[i - 1] < final_lower.iloc[i - 1]:
            final_lower.iloc[i] = lower.iloc[i]
        else:
            final_lower.iloc[i] = max(lower.iloc[i], final_lower.iloc[i - 1])
        prev = trend.iloc[i - 1]
        if prev >= 0 and close.iloc[i] < final_lower.iloc[i]:
            trend.iloc[i] = -1.0
        elif prev < 0 and close.iloc[i] > final_upper.iloc[i]:
            trend.iloc[i] = 1.0
        else:
            trend.iloc[i] = prev
        st.iloc[i] = final_lower.iloc[i] if trend.iloc[i] >= 0 else final_upper.iloc[i]
    return st, trend


def _completed_weekly_features(data: pd.DataFrame) -> pd.DataFrame:
    weekly = data.resample("W-FRI").agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).dropna(subset=["Close"])
    if weekly.empty:
        return pd.DataFrame(index=data.index)
    weekly["WeeklyEMA20"] = weekly["Close"].ewm(span=20, adjust=False, min_periods=20).mean()
    weekly["WeeklyEMA50"] = weekly["Close"].ewm(span=50, adjust=False, min_periods=50).mean()
    weekly["WeeklyRSI14"] = _rsi(weekly["Close"], 14)
    ema12 = weekly["Close"].ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = weekly["Close"].ewm(span=26, adjust=False, min_periods=26).mean()
    weekly["WeeklyMACD"] = ema12 - ema26
    weekly["WeeklyMACDSignal"] = weekly["WeeklyMACD"].ewm(span=9, adjust=False, min_periods=9).mean()
    weekly["WeeklyMACDHist"] = weekly["WeeklyMACD"] - weekly["WeeklyMACDSignal"]
    # Conservative point-in-time mapping: only a fully completed prior week is used.
    weekly = weekly[["WeeklyEMA20", "WeeklyEMA50", "WeeklyRSI14", "WeeklyMACD", "WeeklyMACDSignal", "WeeklyMACDHist"]].shift(1)
    return weekly.reindex(data.index.union(weekly.index)).sort_index().ffill().reindex(data.index)


def compute_features(frame: pd.DataFrame, benchmark: pd.DataFrame | None = None) -> pd.DataFrame:
    data = canonical_ohlcv(frame)
    out = data.copy()
    close = out["Close"]
    volume = out["Volume"].fillna(0.0)

    for p in (20, 50, 100, 200):
        out[f"SMA{p}"] = close.rolling(p, min_periods=p).mean()
        out[f"EMA{p}"] = close.ewm(span=p, adjust=False, min_periods=p).mean()
        out[f"EMA{p}Slope5Pct"] = out[f"EMA{p}"].pct_change(5) * 100.0

    tr = _true_range(out)
    out["ATR14"] = _wilder(tr, 14)
    out["ATRPct"] = out["ATR14"] / close.replace(0.0, np.nan) * 100.0
    out["RSI14"] = _rsi(close, 14)
    adx, pdi, mdi = _adx(out, 14)
    out["ADX14"] = adx
    out["PlusDI14"] = pdi
    out["MinusDI14"] = mdi

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    out["MACD"] = ema12 - ema26
    out["MACDSignal"] = out["MACD"].ewm(span=9, adjust=False, min_periods=9).mean()
    out["MACDHist"] = out["MACD"] - out["MACDSignal"]
    out["ROC10"] = close.pct_change(10) * 100.0
    out["ROC20"] = close.pct_change(20) * 100.0

    lowest14 = out["Low"].rolling(14, min_periods=14).min()
    highest14 = out["High"].rolling(14, min_periods=14).max()
    out["StochK14"] = 100.0 * (close - lowest14) / (highest14 - lowest14).replace(0.0, np.nan)
    out["StochD3"] = out["StochK14"].rolling(3, min_periods=3).mean()

    out["BBMid20"] = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std(ddof=0)
    out["BBUpper20"] = out["BBMid20"] + 2.0 * bb_std
    out["BBLower20"] = out["BBMid20"] - 2.0 * bb_std
    out["BBBandwidthPct"] = (out["BBUpper20"] - out["BBLower20"]) / out["BBMid20"].replace(0.0, np.nan) * 100.0
    out["BBPercentB"] = (close - out["BBLower20"]) / (out["BBUpper20"] - out["BBLower20"]).replace(0.0, np.nan)
    out["BBCompression"] = out["BBBandwidthPct"] <= out["BBBandwidthPct"].rolling(120, min_periods=40).quantile(0.20)

    direction = np.sign(close.diff()).fillna(0.0)
    out["OBV"] = (direction * volume).cumsum()
    out["OBVSlope10Pct"] = out["OBV"].diff(10) / volume.rolling(20, min_periods=5).mean().replace(0.0, np.nan) * 100.0
    spread = (out["High"] - out["Low"]).replace(0.0, np.nan)
    mfm = ((close - out["Low"]) - (out["High"] - close)) / spread
    mfv = mfm.fillna(0.0) * volume
    out["CMF20"] = mfv.rolling(20, min_periods=20).sum() / volume.rolling(20, min_periods=20).sum().replace(0.0, np.nan)
    out["ADLine"] = mfv.cumsum()
    out["ADLineSlope10"] = out["ADLine"].diff(10)

    st, st_dir = _supertrend(out, 10, 3.0)
    out["Supertrend10x3"] = st
    out["SupertrendDirection"] = st_dir

    for h in (1, 5, 10, 20, 60, 120):
        out[f"Return{h}Pct"] = close.pct_change(h) * 100.0
    out["RealizedVol20Pct"] = close.pct_change().rolling(20, min_periods=20).std() * math.sqrt(252.0) * 100.0

    out["Support20"] = out["Low"].shift(1).rolling(20, min_periods=10).min()
    out["Resistance20"] = out["High"].shift(1).rolling(20, min_periods=10).max()
    out["Support60"] = out["Low"].shift(1).rolling(60, min_periods=20).min()
    out["Resistance60"] = out["High"].shift(1).rolling(60, min_periods=20).max()
    out["DistanceSupport20Pct"] = (close / out["Support20"].replace(0.0, np.nan) - 1.0) * 100.0
    out["DistanceResistance20Pct"] = (out["Resistance20"] / close.replace(0.0, np.nan) - 1.0) * 100.0
    out["Breakout20"] = (close > out["Resistance20"]) & (close.shift(1) <= out["Resistance20"].shift(1))
    prior_breakout = out["Breakout20"].shift(1).rolling(10, min_periods=1).max().fillna(0.0).astype(bool)
    out["Retest20"] = prior_breakout & (out["Low"] <= out["Resistance20"] * 1.005) & (close >= out["Resistance20"] * 0.995)

    candle_range = (out["High"] - out["Low"]).replace(0.0, np.nan)
    body = (close - out["Open"]).abs()
    upper = out["High"] - pd.concat([out["Open"], close], axis=1).max(axis=1)
    lower = pd.concat([out["Open"], close], axis=1).min(axis=1) - out["Low"]
    out["BodyPctOfRange"] = body / candle_range * 100.0
    out["UpperWickPctOfRange"] = upper / candle_range * 100.0
    out["LowerWickPctOfRange"] = lower / candle_range * 100.0
    out["Doji"] = out["BodyPctOfRange"] <= 10.0
    out["Hammer"] = (lower >= body * 2.0) & (upper <= body * 0.75) & (body > 0.0)
    out["ShootingStar"] = (upper >= body * 2.0) & (lower <= body * 0.75) & (body > 0.0)
    prev_open, prev_close = out["Open"].shift(1), close.shift(1)
    out["BullishEngulfing"] = (close > out["Open"]) & (prev_close < prev_open) & (close >= prev_open) & (out["Open"] <= prev_close)
    out["BearishEngulfing"] = (close < out["Open"]) & (prev_close > prev_open) & (close <= prev_open) & (out["Open"] >= prev_close)

    weekly = _completed_weekly_features(out)
    for c in weekly.columns:
        out[c] = weekly[c]
    out["WeeklyTrendConfirmed"] = (
        (out["WeeklyEMA20"] > out["WeeklyEMA50"])
        & (out["WeeklyRSI14"] >= 50.0)
        & (out["WeeklyMACDHist"] >= 0.0)
    )

    if benchmark is not None and not benchmark.empty:
        bench = canonical_ohlcv(benchmark).reindex(out.index).ffill()
        out["NiftyReturn20Pct"] = bench["Close"].pct_change(20) * 100.0
        out["NiftyReturn60Pct"] = bench["Close"].pct_change(60) * 100.0
        out["RS20VsNifty"] = out["Return20Pct"] - out["NiftyReturn20Pct"]
        out["RS60VsNifty"] = out["Return60Pct"] - out["NiftyReturn60Pct"]
        bench_ema50 = bench["Close"].ewm(span=50, adjust=False, min_periods=50).mean()
        bench_ema200 = bench["Close"].ewm(span=200, adjust=False, min_periods=200).mean()
        bull = (bench["Close"] > bench_ema50) & (bench_ema50 > bench_ema200)
        bear = (bench["Close"] < bench_ema50) & (bench_ema50 < bench_ema200)
        out["MarketRegimeCode"] = np.select([bull, bear], [1.0, -1.0], default=0.0)
    else:
        out["NiftyReturn20Pct"] = np.nan
        out["NiftyReturn60Pct"] = np.nan
        out["RS20VsNifty"] = np.nan
        out["RS60VsNifty"] = np.nan
        out["MarketRegimeCode"] = np.nan

    return out


def _signal(value: bool | None, positive: float = 1.0, negative: float = -1.0) -> float | None:
    if value is None:
        return None
    return positive if bool(value) else negative


def score_snapshot(features: pd.DataFrame) -> dict[str, Any]:
    if features.empty:
        return {"score": None, "coverage": 0.0, "label": "UNAVAILABLE", "components": {}}
    r = features.iloc[-1]

    components: dict[str, tuple[float | None, float]] = {}

    close = _finite(r.get("Close"))
    ema20, ema50, ema200 = _finite(r.get("EMA20")), _finite(r.get("EMA50")), _finite(r.get("EMA200"))
    if close is not None and ema20 is not None and ema50 is not None and ema200 is not None:
        trend = ((1 if close > ema20 else -1) + (1 if ema20 > ema50 else -1) + (1 if ema50 > ema200 else -1)) / 3.0
    else:
        trend = None
    components["trend"] = (trend, 0.20)

    rsi, macd_hist, roc20 = _finite(r.get("RSI14")), _finite(r.get("MACDHist")), _finite(r.get("ROC20"))
    momentum_parts = []
    if rsi is not None:
        momentum_parts.append(1.0 if 50.0 <= rsi <= 75.0 else (0.2 if 40.0 <= rsi < 50.0 else -0.6 if rsi >= 80.0 or rsi < 35.0 else 0.0))
    if macd_hist is not None:
        momentum_parts.append(1.0 if macd_hist > 0.0 else -1.0)
    if roc20 is not None:
        momentum_parts.append(1.0 if roc20 > 0.0 else -1.0)
    components["momentum"] = ((sum(momentum_parts) / len(momentum_parts)) if momentum_parts else None, 0.15)

    cmf, obv_slope, ad_slope = _finite(r.get("CMF20")), _finite(r.get("OBVSlope10Pct")), _finite(r.get("ADLineSlope10"))
    flow_parts = []
    if cmf is not None:
        flow_parts.append(max(-1.0, min(1.0, cmf / 0.15)))
    if obv_slope is not None:
        flow_parts.append(1.0 if obv_slope > 0.0 else -1.0)
    if ad_slope is not None:
        flow_parts.append(1.0 if ad_slope > 0.0 else -1.0)
    components["volume_flow"] = ((sum(flow_parts) / len(flow_parts)) if flow_parts else None, 0.12)

    structure_parts = []
    if pd.notna(r.get("Breakout20")):
        structure_parts.append(1.0 if bool(r.get("Breakout20")) else 0.0)
    if pd.notna(r.get("Retest20")):
        structure_parts.append(0.8 if bool(r.get("Retest20")) else 0.0)
    dist_res = _finite(r.get("DistanceResistance20Pct"))
    if dist_res is not None:
        structure_parts.append(0.5 if 0.0 <= dist_res <= 3.0 else (-0.4 if dist_res > 12.0 else 0.0))
    components["structure"] = ((sum(structure_parts) / max(1, len(structure_parts))) if structure_parts else None, 0.13)

    candle = 0.0
    candle_known = False
    for key, value in (("BullishEngulfing", 1.0), ("Hammer", 0.7), ("BearishEngulfing", -1.0), ("ShootingStar", -0.7)):
        if pd.notna(r.get(key)):
            candle_known = True
            if bool(r.get(key)):
                candle += value
    components["candlestick"] = (max(-1.0, min(1.0, candle)) if candle_known else None, 0.06)

    rs_parts = []
    for key in ("RS20VsNifty", "RS60VsNifty"):
        v = _finite(r.get(key))
        if v is not None:
            rs_parts.append(max(-1.0, min(1.0, v / 10.0)))
    components["relative_strength"] = ((sum(rs_parts) / len(rs_parts)) if rs_parts else None, 0.12)

    weekly = None
    if pd.notna(r.get("WeeklyTrendConfirmed")):
        weekly = 1.0 if bool(r.get("WeeklyTrendConfirmed")) else -0.5
    components["weekly_confirmation"] = (weekly, 0.10)

    regime = _finite(r.get("MarketRegimeCode"))
    components["market_regime"] = (regime, 0.07)

    bb_comp = r.get("BBCompression")
    adx = _finite(r.get("ADX14"))
    vol_setup_parts = []
    if pd.notna(bb_comp):
        vol_setup_parts.append(0.5 if bool(bb_comp) else 0.0)
    if adx is not None:
        vol_setup_parts.append(max(-0.5, min(1.0, (adx - 15.0) / 20.0)))
    components["volatility_setup"] = ((sum(vol_setup_parts) / len(vol_setup_parts)) if vol_setup_parts else None, 0.05)

    used_weight = sum(weight for value, weight in components.values() if value is not None)
    weighted = sum(float(value) * weight for value, weight in components.values() if value is not None)
    if used_weight <= 0.0:
        score = None
    else:
        normalized = weighted / used_weight
        score = round(max(0.0, min(100.0, 50.0 + 50.0 * normalized)), 2)
    coverage = round(used_weight / sum(weight for _, weight in components.values()), 4)
    if score is None:
        label = "UNAVAILABLE"
    elif score >= 72:
        label = "STRONG_POSITIVE"
    elif score >= 58:
        label = "POSITIVE"
    elif score >= 42:
        label = "NEUTRAL"
    elif score >= 28:
        label = "NEGATIVE"
    else:
        label = "STRONG_NEGATIVE"
    return {
        "score": score,
        "coverage": coverage,
        "label": label,
        "components": {k: {"signal": _finite(v), "weight": w} for k, (v, w) in components.items()},
    }


def _regime_label(code: float | None) -> str:
    if code is None:
        return "UNAVAILABLE"
    if code > 0.5:
        return "BULL"
    if code < -0.5:
        return "BEAR"
    return "MIXED"


def historical_analogues(features: pd.DataFrame, horizon_sessions: int = 20, k: int = ANALOGUE_K) -> dict[str, Any]:
    if features is None or len(features) < max(MIN_BARS, horizon_sessions + 80):
        return {"status": "INSUFFICIENT_HISTORY", "sample_size": 0, "confidence": "LOW"}
    horizon_sessions = max(1, int(horizon_sessions))
    feature_names = [
        "RSI14", "ADX14", "MACDHist", "ROC20", "ATRPct", "BBBandwidthPct",
        "CMF20", "EMA20Slope5Pct", "EMA50Slope5Pct", "RS20VsNifty",
        "RS60VsNifty", "MarketRegimeCode",
    ]
    cols = [c for c in feature_names if c in features.columns]
    if len(cols) < 6:
        return {"status": "INSUFFICIENT_FEATURE_COVERAGE", "sample_size": 0, "confidence": "LOW"}

    current = features.iloc[-1]
    candidates = features.iloc[:-horizon_sessions].copy()
    candidates["ForwardReturn"] = features["Close"].shift(-horizon_sessions).iloc[:-horizon_sessions] / candidates["Close"] - 1.0
    current_regime = _finite(current.get("MarketRegimeCode"))
    if current_regime is not None and "MarketRegimeCode" in candidates.columns:
        same = candidates["MarketRegimeCode"].round(0) == round(current_regime)
        if int(same.sum()) >= ANALOGUE_MIN_SAMPLE:
            candidates = candidates.loc[same].copy()

    numeric = candidates[cols].apply(pd.to_numeric, errors="coerce")
    current_vector = pd.to_numeric(current[cols], errors="coerce")
    valid_cols = [c for c in cols if pd.notna(current_vector[c]) and numeric[c].notna().sum() >= 30]
    if len(valid_cols) < 6:
        return {"status": "INSUFFICIENT_FEATURE_COVERAGE", "sample_size": 0, "confidence": "LOW"}

    numeric = numeric[valid_cols]
    current_vector = current_vector[valid_cols]
    med = numeric.median()
    iqr = numeric.quantile(0.75) - numeric.quantile(0.25)
    scale = iqr.replace(0.0, np.nan)
    fallback = numeric.std().replace(0.0, np.nan)
    scale = scale.fillna(fallback).replace(0.0, 1.0).fillna(1.0)
    z = (numeric - med) / scale
    cz = (current_vector - med) / scale
    distances = ((z - cz) ** 2).mean(axis=1, skipna=True).pow(0.5)
    eligible = pd.DataFrame({"distance": distances, "forward_return": candidates["ForwardReturn"]}).dropna()
    if eligible.empty:
        return {"status": "NO_ELIGIBLE_ANALOGUES", "sample_size": 0, "confidence": "LOW"}
    chosen = eligible.nsmallest(min(k, len(eligible)), "distance")
    sample = len(chosen)
    returns = chosen["forward_return"]
    median_distance = float(chosen["distance"].median())
    similarity = 1.0 / (1.0 + max(0.0, median_distance))
    if sample >= 15 and similarity >= 0.55:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    return {
        "status": "READY" if sample >= ANALOGUE_MIN_SAMPLE else "LOW_SAMPLE",
        "sample_size": sample,
        "requested_k": k,
        "horizon_sessions": horizon_sessions,
        "median_forward_return": round(float(returns.median()), 6),
        "mean_forward_return": round(float(returns.mean()), 6),
        "positive_rate": round(float((returns > 0.0).mean()), 6),
        "p25_forward_return": round(float(returns.quantile(0.25)), 6),
        "p75_forward_return": round(float(returns.quantile(0.75)), 6),
        "median_distance": round(median_distance, 6),
        "similarity": round(similarity, 6),
        "confidence": confidence,
        "regime": _regime_label(current_regime),
        "point_in_time_safe": True,
    }


def _field(row: pd.Series, name: str, digits: int = 4) -> float | None:
    value = _finite(row.get(name))
    return None if value is None else round(value, digits)


def analyze(
    frame: pd.DataFrame,
    benchmark: pd.DataFrame | None = None,
    *,
    horizon_sessions: int = 20,
    india_vix: pd.DataFrame | None = None,
    sector_benchmark: pd.DataFrame | None = None,
) -> dict[str, Any]:
    features = compute_features(frame, benchmark)
    if features.empty:
        return {
            "schema": SCHEMA_VERSION,
            "authority": AUTHORITY,
            "status": "NO_DATA",
            "technical_score": None,
        }
    row = features.iloc[-1]
    score = score_snapshot(features)
    analogue = historical_analogues(features, horizon_sessions=horizon_sessions)

    sector_rs = {}
    if sector_benchmark is not None and not sector_benchmark.empty:
        sector = canonical_ohlcv(sector_benchmark).reindex(features.index).ffill()
        sector_ret20 = sector["Close"].pct_change(20) * 100.0
        sector_ret60 = sector["Close"].pct_change(60) * 100.0
        sector_rs = {
            "rs20_vs_sector": round(float(features["Return20Pct"].iloc[-1] - sector_ret20.iloc[-1]), 4) if pd.notna(sector_ret20.iloc[-1]) and pd.notna(features["Return20Pct"].iloc[-1]) else None,
            "rs60_vs_sector": round(float(features["Return60Pct"].iloc[-1] - sector_ret60.iloc[-1]), 4) if pd.notna(sector_ret60.iloc[-1]) and pd.notna(features["Return60Pct"].iloc[-1]) else None,
            "available": True,
        }
    else:
        sector_rs = {"rs20_vs_sector": None, "rs60_vs_sector": None, "available": False}

    vix = {"available": False, "close": None, "change_5d_pct": None, "regime": "UNAVAILABLE"}
    if india_vix is not None and not india_vix.empty:
        vf = canonical_ohlcv(india_vix)
        if not vf.empty:
            v = float(vf["Close"].iloc[-1])
            change5 = vf["Close"].pct_change(5).iloc[-1] * 100.0 if len(vf) > 5 else np.nan
            vix = {
                "available": True,
                "close": round(v, 4),
                "change_5d_pct": round(float(change5), 4) if pd.notna(change5) else None,
                "regime": "HIGH" if v >= 20.0 else "ELEVATED" if v >= 15.0 else "NORMAL",
            }

    positive_candle = [name for name in ("BullishEngulfing", "Hammer") if bool(row.get(name)) if pd.notna(row.get(name))]
    negative_candle = [name for name in ("BearishEngulfing", "ShootingStar") if bool(row.get(name)) if pd.notna(row.get(name))]

    challenger_expected = analogue.get("median_forward_return") if analogue.get("status") in {"READY", "LOW_SAMPLE"} else None
    return {
        "schema": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "status": "READY" if len(features) >= MIN_BARS else "LIMITED_HISTORY",
        "as_of_session": str(pd.Timestamp(features.index[-1]).date()),
        "bars": int(len(features)),
        "horizon_sessions": int(horizon_sessions),
        "technical_score": score["score"],
        "technical_label": score["label"],
        "evidence_coverage": score["coverage"],
        "score_components": score["components"],
        "trend": {
            "close": _field(row, "Close"),
            "sma20": _field(row, "SMA20"),
            "sma50": _field(row, "SMA50"),
            "sma200": _field(row, "SMA200"),
            "ema20": _field(row, "EMA20"),
            "ema50": _field(row, "EMA50"),
            "ema100": _field(row, "EMA100"),
            "ema200": _field(row, "EMA200"),
            "ema20_slope_5d_pct": _field(row, "EMA20Slope5Pct"),
            "ema50_slope_5d_pct": _field(row, "EMA50Slope5Pct"),
            "supertrend": _field(row, "Supertrend10x3"),
            "supertrend_direction": "BULL" if (_finite(row.get("SupertrendDirection")) or 0.0) >= 0 else "BEAR",
        },
        "momentum": {
            "rsi14": _field(row, "RSI14"),
            "adx14": _field(row, "ADX14"),
            "plus_di14": _field(row, "PlusDI14"),
            "minus_di14": _field(row, "MinusDI14"),
            "macd": _field(row, "MACD"),
            "macd_signal": _field(row, "MACDSignal"),
            "macd_hist": _field(row, "MACDHist"),
            "roc10_pct": _field(row, "ROC10"),
            "roc20_pct": _field(row, "ROC20"),
            "stoch_k14": _field(row, "StochK14"),
            "stoch_d3": _field(row, "StochD3"),
        },
        "volatility": {
            "atr14": _field(row, "ATR14"),
            "atr_pct": _field(row, "ATRPct"),
            "realized_vol_20d_pct": _field(row, "RealizedVol20Pct"),
            "bb_mid20": _field(row, "BBMid20"),
            "bb_upper20": _field(row, "BBUpper20"),
            "bb_lower20": _field(row, "BBLower20"),
            "bb_bandwidth_pct": _field(row, "BBBandwidthPct"),
            "bb_percent_b": _field(row, "BBPercentB"),
            "compression": bool(row.get("BBCompression")) if pd.notna(row.get("BBCompression")) else None,
        },
        "volume_flow": {
            "obv": _field(row, "OBV", 2),
            "obv_slope10_pct": _field(row, "OBVSlope10Pct"),
            "cmf20": _field(row, "CMF20"),
            "ad_line": _field(row, "ADLine", 2),
            "ad_line_slope10": _field(row, "ADLineSlope10", 2),
        },
        "structure": {
            "support20": _field(row, "Support20"),
            "resistance20": _field(row, "Resistance20"),
            "support60": _field(row, "Support60"),
            "resistance60": _field(row, "Resistance60"),
            "distance_support20_pct": _field(row, "DistanceSupport20Pct"),
            "distance_resistance20_pct": _field(row, "DistanceResistance20Pct"),
            "breakout20": bool(row.get("Breakout20")) if pd.notna(row.get("Breakout20")) else None,
            "retest20": bool(row.get("Retest20")) if pd.notna(row.get("Retest20")) else None,
        },
        "candlestick": {
            "body_pct_of_range": _field(row, "BodyPctOfRange"),
            "upper_wick_pct_of_range": _field(row, "UpperWickPctOfRange"),
            "lower_wick_pct_of_range": _field(row, "LowerWickPctOfRange"),
            "doji": bool(row.get("Doji")) if pd.notna(row.get("Doji")) else None,
            "positive_patterns": positive_candle,
            "negative_patterns": negative_candle,
        },
        "relative_strength": {
            "rs20_vs_nifty": _field(row, "RS20VsNifty"),
            "rs60_vs_nifty": _field(row, "RS60VsNifty"),
            **sector_rs,
        },
        "multi_timeframe": {
            "weekly_ema20": _field(row, "WeeklyEMA20"),
            "weekly_ema50": _field(row, "WeeklyEMA50"),
            "weekly_rsi14": _field(row, "WeeklyRSI14"),
            "weekly_macd_hist": _field(row, "WeeklyMACDHist"),
            "weekly_trend_confirmed": bool(row.get("WeeklyTrendConfirmed")) if pd.notna(row.get("WeeklyTrendConfirmed")) else None,
            "point_in_time_policy": "PRIOR_COMPLETED_WEEK_ONLY",
        },
        "market_context": {
            "nifty_regime": _regime_label(_finite(row.get("MarketRegimeCode"))),
            "india_vix": vix,
        },
        "historical_analogues": analogue,
        "shadow_challenger": {
            "authority": AUTHORITY,
            "technical_score": score["score"],
            "analogue_expected_return": challenger_expected,
            "analogue_confidence": analogue.get("confidence"),
            "promotion_allowed": False,
            "reason": "Technical Intelligence V2 remains shadow-only until walk-forward/out-of-sample validation passes.",
        },
        "point_in_time_safe": True,
    }


def point_in_time_prefix_audit(
    frame: pd.DataFrame,
    benchmark: pd.DataFrame | None = None,
    checkpoints: int = 6,
) -> dict[str, Any]:
    """Recompute prefixes and verify representative indicators do not change with future rows."""
    data = canonical_ohlcv(frame)
    if len(data) < 260:
        return {"status": "SKIP_INSUFFICIENT_HISTORY", "checks": 0, "failures": []}
    bench = canonical_ohlcv(benchmark) if benchmark is not None and not benchmark.empty else None
    full = compute_features(data, bench)
    positions = np.linspace(220, len(data) - 1, num=min(checkpoints, max(1, len(data) - 220)), dtype=int)
    fields = ["EMA20", "EMA50", "EMA100", "EMA200", "RSI14", "ADX14", "MACDHist", "ROC20", "StochK14", "BBBandwidthPct", "CMF20", "Support20", "Resistance20"]
    failures = []
    checks = 0
    for pos in sorted(set(int(x) for x in positions)):
        prefix = data.iloc[: pos + 1]
        bprefix = bench.loc[: prefix.index[-1]] if bench is not None else None
        pref = compute_features(prefix, bprefix)
        date = prefix.index[-1]
        for field in fields:
            left = _finite(full.loc[date, field])
            right = _finite(pref.loc[date, field])
            checks += 1
            if left is None and right is None:
                continue
            if left is None or right is None or abs(left - right) > 1e-8:
                failures.append({"date": str(pd.Timestamp(date).date()), "field": field, "full": left, "prefix": right})
    return {
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failure_count": len(failures),
        "failures": failures[:25],
    }
'''

module_path = root / "stock_app" / "technical_v2.py"
module_path.write_text(technical_module, encoding="utf-8")

phase = root / "phase4"
phase.mkdir(parents=True, exist_ok=True)
(phase / "technical_intelligence_v2_policy.json").write_text(
    """{
  "schema": "SRE_PHASE4_TECHNICAL_INTELLIGENCE_V2_POLICY",
  "release": "0.10.0-phase4-technical-v2",
  "authority": "SHADOW_ONLY",
  "active_recommendation_authority_changed": false,
  "features": {
    "trend": ["SMA20","SMA50","SMA100","SMA200","EMA20","EMA50","EMA100","EMA200","EMA slopes","Supertrend"],
    "momentum": ["RSI14","ADX/DMI","MACD 12/26/9","ROC10/20","Stochastic 14/3"],
    "volatility": ["ATR14","realized volatility","Bollinger 20/2","compression"],
    "volume_flow": ["OBV","CMF20","Accumulation/Distribution"],
    "structure": ["support/resistance 20/60","breakout","retest"],
    "candlestick": ["body/wick geometry","doji","hammer","shooting star","bullish/bearish engulfing"],
    "relative_strength": ["vs NIFTY 20/60","vs sector when available"],
    "multi_timeframe": ["daily","prior completed weekly"],
    "market_context": ["NIFTY regime","India VIX when available"],
    "analogue_engine": "regime-conditioned historical analogues with point-in-time forward outcome closure"
  },
  "promotion_rule": "No Phase 4 shadow signal may change ranking, buy/watch status or capital allocation until walk-forward and out-of-sample validation passes.",
  "automatic_yfinance_fallback": false
}
""",
    encoding="utf-8",
)

assert "SCHEMA_VERSION = \"SRE_TECHNICAL_INTELLIGENCE_V2\"" in module_path.read_text(encoding="utf-8")
print("Phase 4 Technical Intelligence V2 core module written")
