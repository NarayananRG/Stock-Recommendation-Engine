# ============================================================
# STOCK ALERT ENGINE - STAGE 2.1
# OPTIMIZED 15-YEAR HISTORICAL BACKTEST
# ============================================================
#
# Purpose:
#   Backtest the FROZEN Stage 1.2.3 rule-based strategy.
#
# Holding horizon:
#   Approximately 2 weeks to 3 months.
#
# IMPORTANT:
#   This is a research/backtesting system.
#   It is not a guarantee of future returns.
#
# MAJOR DIFFERENCE FROM STAGE 2:
#
#   OLD:
#       For every ticker
#           For every date
#               Recalculate indicators
#
#   NEW:
#       Download once
#           ↓
#       Calculate indicators once
#           ↓
#       Calculate market regime history once
#           ↓
#       Walk through dates using cached values
#
# This should be dramatically faster.
#
# ============================================================

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import warnings

import numpy as np
import pandas as pd
import yfinance as yf


warnings.filterwarnings("ignore")


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass
class BacktestConfig:

    # --------------------------------------------------------
    # Historical window
    # --------------------------------------------------------

    years: int = 15

    warmup_days: int = 450

    min_daily_history: int = 250

    # --------------------------------------------------------
    # Holding periods
    # --------------------------------------------------------

    holding_periods: Tuple[int, ...] = (
        10,
        20,
        30,
        45,
        63,
    )

    primary_holding_period: int = 63

    # --------------------------------------------------------
    # Indicators
    # --------------------------------------------------------

    rsi_period: int = 14

    atr_period: int = 14

    adx_period: int = 14

    supertrend_period: int = 10

    supertrend_multiplier: float = 3.0

    sma20_period: int = 20

    sma50_period: int = 50

    sma200_period: int = 200

    volume_period: int = 20

    # --------------------------------------------------------
    # Relative strength
    # --------------------------------------------------------

    rs20_period: int = 20

    rs60_period: int = 60

    rs120_period: int = 120

    # --------------------------------------------------------
    # Pullback
    # --------------------------------------------------------

    pullback_lookback: int = 20

    pullback_max_distance_20dma: float = 0.05

    pullback_entry_window: int = 5

    # --------------------------------------------------------
    # Breakout
    # --------------------------------------------------------

    breakout_lookback: int = 20

    breakout_buffer: float = 0.002

    breakout_volume_ratio: float = 1.20

    breakout_max_extension: float = 0.12

    # --------------------------------------------------------
    # Extension
    # --------------------------------------------------------

    extension_distance: float = 0.06

    overextended_rsi: float = 70.0

    # --------------------------------------------------------
    # Stops
    # --------------------------------------------------------

    atr_stop_multiplier: float = 1.50

    stop_buffer_pct: float = 0.005

    # --------------------------------------------------------
    # Risk / reward
    # --------------------------------------------------------

    minimum_t1_rr: float = 1.50

    preferred_t1_rr: float = 2.00

    # --------------------------------------------------------
    # Signal thresholds
    # --------------------------------------------------------

    strong_buy_technical: float = 80.0

    strong_buy_actionability: float = 80.0

    buy_technical: float = 70.0

    buy_actionability: float = 70.0

    watch_technical: float = 60.0

    watch_actionability: float = 40.0

    # --------------------------------------------------------
    # Costs
    # --------------------------------------------------------

    slippage_bps: float = 5.0

    transaction_cost_bps: float = 5.0

    # --------------------------------------------------------
    # Portfolio
    # --------------------------------------------------------

    starting_equity: float = 100000.0

    risk_per_trade: float = 0.0075

    # --------------------------------------------------------
    # Output
    # --------------------------------------------------------

    output_directory: str = "."


# ============================================================
# HELPERS
# ============================================================

def safe_float(value) -> Optional[float]:
    try:
        if value is None:
            return None

        value = float(value)

        if not np.isfinite(value):
            return None

        return value

    except Exception:
        return None


def unique_list(values: List[str]) -> List[str]:

    result = []
    seen = set()

    for value in values:

        if value and value not in seen:

            result.append(value)
            seen.add(value)

    return result


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:

    if isinstance(df.columns, pd.MultiIndex):

        level0 = list(
            df.columns.get_level_values(0)
        )

        required = {
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        }

        if required.issubset(set(level0)):

            df.columns = (
                df.columns
                .get_level_values(0)
            )

        else:

            df.columns = (
                df.columns
                .get_level_values(-1)
            )

    return df


def normalize_index(
    df: pd.DataFrame
) -> pd.DataFrame:

    df = df.copy()

    if hasattr(df.index, "tz"):

        if df.index.tz is not None:

            df.index = (
                df.index
                .tz_localize(None)
            )

    df = df[
        ~df.index.duplicated(
            keep="last"
        )
    ]

    df = df.sort_index()

    return df


# ============================================================
# INDICATORS
# ============================================================

class Indicators:

    @staticmethod
    def sma(
        series: pd.Series,
        period: int
    ) -> pd.Series:

        return series.rolling(
            period,
            min_periods=period
        ).mean()

    @staticmethod
    def rsi(
        series: pd.Series,
        period: int
    ) -> pd.Series:

        delta = series.diff()

        gain = delta.clip(
            lower=0
        )

        loss = -delta.clip(
            upper=0
        )

        avg_gain = gain.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period
        ).mean()

        avg_loss = loss.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period
        ).mean()

        rs = (
            avg_gain /
            avg_loss.replace(
                0,
                np.nan
            )
        )

        rsi = (
            100 -
            100 /
            (1 + rs)
        )

        rsi = rsi.where(
            ~avg_loss.eq(0),
            100
        )

        rsi = rsi.where(
            ~avg_gain.eq(0),
            0
        )

        return rsi

    @staticmethod
    def true_range(
        df: pd.DataFrame
    ) -> pd.Series:

        previous_close = (
            df["Close"].shift(1)
        )

        tr1 = (
            df["High"] -
            df["Low"]
        )

        tr2 = (
            df["High"] -
            previous_close
        ).abs()

        tr3 = (
            df["Low"] -
            previous_close
        ).abs()

        return pd.concat(
            [
                tr1,
                tr2,
                tr3,
            ],
            axis=1
        ).max(axis=1)

    @classmethod
    def atr(
        cls,
        df: pd.DataFrame,
        period: int
    ) -> pd.Series:

        tr = cls.true_range(df)

        return tr.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period
        ).mean()

    @classmethod
    def adx(
        cls,
        df: pd.DataFrame,
        period: int
    ) -> pd.Series:

        high = df["High"]

        low = df["Low"]

        up_move = high.diff()

        down_move = -low.diff()

        plus_dm = pd.Series(
            np.where(
                (up_move > down_move)
                &
                (up_move > 0),
                up_move,
                0.0
            ),
            index=df.index,
            dtype=float
        )

        minus_dm = pd.Series(
            np.where(
                (down_move > up_move)
                &
                (down_move > 0),
                down_move,
                0.0
            ),
            index=df.index,
            dtype=float
        )

        atr = cls.atr(
            df,
            period
        )

        plus_smoothed = plus_dm.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period
        ).mean()

        minus_smoothed = minus_dm.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period
        ).mean()

        plus_di = (
            100 *
            plus_smoothed /
            atr.replace(
                0,
                np.nan
            )
        )

        minus_di = (
            100 *
            minus_smoothed /
            atr.replace(
                0,
                np.nan
            )
        )

        denominator = (
            plus_di +
            minus_di
        ).replace(
            0,
            np.nan
        )

        dx = (
            100 *
            (
                plus_di -
                minus_di
            ).abs() /
            denominator
        )

        return dx.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period
        ).mean()

    @classmethod
    def supertrend(
        cls,
        df: pd.DataFrame,
        period: int,
        multiplier: float
    ) -> Tuple[
        pd.Series,
        pd.Series
    ]:

        atr = cls.atr(
            df,
            period
        )

        hl2 = (
            df["High"] +
            df["Low"]
        ) / 2.0

        basic_upper = (
            hl2 +
            multiplier * atr
        )

        basic_lower = (
            hl2 -
            multiplier * atr
        )

        final_upper = basic_upper.copy()

        final_lower = basic_lower.copy()

        trend = pd.Series(
            np.nan,
            index=df.index,
            dtype=float
        )

        valid_positions = np.where(
            atr.notna().to_numpy()
        )[0]

        if len(valid_positions) == 0:

            return (

                pd.Series(
                    np.nan,
                    index=df.index
                ),

                pd.Series(
                    np.nan,
                    index=df.index
                )

            )

        first = int(
            valid_positions[0]
        )

        trend.iloc[first] = 1.0

        for i in range(
            first + 1,
            len(df)
        ):

            prev_upper = (
                final_upper.iloc[i - 1]
            )

            prev_lower = (
                final_lower.iloc[i - 1]
            )

            prev_close = (
                df["Close"].iloc[i - 1]
            )

            close = (
                df["Close"].iloc[i]
            )

            if (
                not np.isfinite(
                    prev_upper
                )
            ):

                final_upper.iloc[i] = (
                    basic_upper.iloc[i]
                )

            elif (
                basic_upper.iloc[i] < prev_upper
                or
                prev_close > prev_upper
            ):

                final_upper.iloc[i] = (
                    basic_upper.iloc[i]
                )

            else:

                final_upper.iloc[i] = (
                    prev_upper
                )

            if (
                not np.isfinite(
                    prev_lower
                )
            ):

                final_lower.iloc[i] = (
                    basic_lower.iloc[i]
                )

            elif (
                basic_lower.iloc[i] > prev_lower
                or
                prev_close < prev_lower
            ):

                final_lower.iloc[i] = (
                    basic_lower.iloc[i]
                )

            else:

                final_lower.iloc[i] = (
                    prev_lower
                )

            previous_trend = (
                trend.iloc[i - 1]
            )

            if previous_trend == 1:

                if (
                    close <
                    final_lower.iloc[i]
                ):

                    trend.iloc[i] = -1.0

                else:

                    trend.iloc[i] = 1.0

            else:

                if (
                    close >
                    final_upper.iloc[i]
                ):

                    trend.iloc[i] = 1.0

                else:

                    trend.iloc[i] = -1.0

        line = pd.Series(
            np.where(
                trend == 1,
                final_lower,
                final_upper
            ),
            index=df.index,
            dtype=float
        )

        return (
            line,
            trend
        )


# ============================================================
# DATA DOWNLOAD
# ============================================================

class HistoricalDataLoader:

    def __init__(
        self,
        config: BacktestConfig
    ):

        self.config = config

        self.test_end = pd.Timestamp(
            date.today()
        )

        self.test_start = (
            self.test_end -
            pd.DateOffset(
                years=config.years
            )
        )

        self.warmup_start = (
            self.test_start -
            pd.Timedelta(
                days=config.warmup_days
            )
        )

    def download(
        self,
        ticker: str
    ) -> pd.DataFrame:

        try:

            df = yf.download(

                ticker,

                start=self.warmup_start.strftime(
                    "%Y-%m-%d"
                ),

                end=(
                    self.test_end +
                    pd.Timedelta(days=2)
                ).strftime(
                    "%Y-%m-%d"
                ),

                interval="1d",

                auto_adjust=True,

                repair=True,

                progress=False,

                threads=False,

            )

        except Exception as exc:

            print(
                f"ERROR downloading "
                f"{ticker}: {exc}"
            )

            return pd.DataFrame()

        if df is None or df.empty:

            return pd.DataFrame()

        df = clean_columns(df)

        required = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        ]

        missing = [
            c
            for c in required
            if c not in df.columns
        ]

        if missing:

            print(
                f"SKIPPED {ticker}: "
                f"missing columns {missing}"
            )

            return pd.DataFrame()

        df = df[
            required
        ].copy()

        for col in required:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        df = df.dropna(
            subset=[
                "Open",
                "High",
                "Low",
                "Close",
            ]
        )

        df = normalize_index(df)

        return df


# ============================================================
# PRECOMPUTED FEATURE ENGINE
# ============================================================

class FeatureEngine:

    def __init__(
        self,
        config: BacktestConfig
    ):

        self.config = config

    # --------------------------------------------------------
    # Add stock indicators
    # --------------------------------------------------------

    def add_stock_features(
        self,
        df: pd.DataFrame
    ) -> pd.DataFrame:

        df = df.copy()

        df["SMA20"] = Indicators.sma(
            df["Close"],
            self.config.sma20_period
        )

        df["SMA50"] = Indicators.sma(
            df["Close"],
            self.config.sma50_period
        )

        df["SMA200"] = Indicators.sma(
            df["Close"],
            self.config.sma200_period
        )

        df["RSI"] = Indicators.rsi(
            df["Close"],
            self.config.rsi_period
        )

        df["ATR"] = Indicators.atr(
            df,
            self.config.atr_period
        )

        df["ADX"] = Indicators.adx(
            df,
            self.config.adx_period
        )

        df["VolumeAvg"] = (
            df["Volume"]
            .rolling(
                self.config.volume_period,
                min_periods=self.config.volume_period
            )
            .mean()
        )

        df["VolumeRatio"] = (
            df["Volume"] /
            df["VolumeAvg"].replace(
                0,
                np.nan
            )
        )

        (
            df["ST"],
            df["STTrend"]
        ) = Indicators.supertrend(

            df,

            self.config.supertrend_period,

            self.config.supertrend_multiplier

        )

        # ----------------------------------------------------
        # Historical swing levels
        # ----------------------------------------------------

        df["SwingLow10"] = (
            df["Low"]
            .rolling(
                10,
                min_periods=10
            )
            .min()
        )

        df["RecentHigh20"] = (
            df["High"]
            .rolling(
                self.config.pullback_lookback,
                min_periods=self.config.pullback_lookback
            )
            .max()
            .shift(1)
        )

        df["BreakoutHigh20"] = (
            df["High"]
            .rolling(
                self.config.breakout_lookback,
                min_periods=self.config.breakout_lookback
            )
            .max()
            .shift(1)
        )

        return df

    # --------------------------------------------------------
    # Weekly regime history
    # --------------------------------------------------------

    def completed_weekly_features(
        self,
        daily: pd.DataFrame
    ) -> pd.DataFrame:

        # Resample daily candles into Friday-ended weeks.
        weekly = daily.resample(
            "W-FRI"
        ).agg({

            "Open": "first",

            "High": "max",

            "Low": "min",

            "Close": "last",

            "Volume": "sum",

        })

        weekly = weekly.dropna(
            subset=[
                "Open",
                "High",
                "Low",
                "Close",
            ]
        )

        weekly["RSI"] = Indicators.rsi(
            weekly["Close"],
            self.config.rsi_period
        )

        (
            weekly["ST"],
            weekly["STTrend"]
        ) = Indicators.supertrend(

            weekly,

            self.config.supertrend_period,

            self.config.supertrend_multiplier

        )

        return weekly

    # --------------------------------------------------------
    # Build historical weekly map
    # --------------------------------------------------------

    def make_completed_weekly_map(
        self,
        daily: pd.DataFrame
    ) -> pd.DataFrame:

        weekly = self.completed_weekly_features(
            daily
        )

        result = pd.DataFrame(
            index=daily.index
        )

        result["WeeklyRSI"] = np.nan

        result["WeeklySTTrend"] = np.nan

        result["WeeklyST"] = np.nan

        # For each daily date, use the last week that has
        # actually completed at that date.
        #
        # If date is Friday, that Friday's completed candle
        # is available after market close.
        #
        # For Mon-Thu, the previous Friday is used.

        week_index = weekly.index

        daily_dates = pd.DatetimeIndex(
            daily.index
        )

        positions = (
            week_index
            .searchsorted(
                daily_dates,
                side="right"
            ) - 1
        )

        valid = positions >= 0

        if valid.any():

            valid_daily = daily_dates[
                valid
            ]

            valid_positions = positions[
                valid
            ]

            selected_week_dates = (
                week_index[
                    valid_positions
                ]
            )

            result.loc[
                valid_daily,
                "WeeklyRSI"
            ] = (
                weekly
                .loc[
                    selected_week_dates,
                    "RSI"
                ]
                .to_numpy()
            )

            result.loc[
                valid_daily,
                "WeeklySTTrend"
            ] = (
                weekly
                .loc[
                    selected_week_dates,
                    "STTrend"
                ]
                .to_numpy()
            )

            result.loc[
                valid_daily,
                "WeeklyST"
            ] = (
                weekly
                .loc[
                    selected_week_dates,
                    "ST"
                ]
                .to_numpy()
            )

        return result

    # --------------------------------------------------------
    # NIFTY market regime history
    # --------------------------------------------------------

    def market_regime_history(
        self,
        nifty: pd.DataFrame
    ) -> pd.DataFrame:

        nifty = self.add_stock_features(
            nifty
        )

        weekly_map = (
            self.make_completed_weekly_map(
                nifty
            )
        )

        nifty = nifty.join(
            weekly_map
        )

        regime = pd.DataFrame(
            index=nifty.index
        )

        regime["Price"] = (
            nifty["Close"]
        )

        regime["SMA20"] = (
            nifty["SMA20"]
        )

        regime["SMA50"] = (
            nifty["SMA50"]
        )

        regime["SMA200"] = (
            nifty["SMA200"]
        )

        regime["DailyRSI"] = (
            nifty["RSI"]
        )

        regime["ADX"] = (
            nifty["ADX"]
        )

        regime["DailyST"] = (
            nifty["STTrend"]
        )

        regime["WeeklyRSI"] = (
            nifty["WeeklyRSI"]
        )

        regime["WeeklyST"] = (
            nifty["WeeklySTTrend"]
        )

        score = np.zeros(
            len(nifty),
            dtype=float
        )

        score += np.where(
            nifty["Close"] > nifty["SMA20"],
            15,
            0
        )

        score += np.where(
            nifty["Close"] > nifty["SMA50"],
            20,
            0
        )

        score += np.where(
            nifty["Close"] > nifty["SMA200"],
            20,
            0
        )

        score += np.where(
            nifty["SMA20"] > nifty["SMA50"],
            10,
            0
        )

        score += np.where(
            nifty["SMA50"] > nifty["SMA200"],
            15,
            0
        )

        score += np.where(
            nifty["STTrend"] == 1,
            5,
            0
        )

        score += np.where(
            nifty["WeeklySTTrend"] == 1,
            5,
            0
        )

        score += np.where(
            nifty["RSI"].between(
                50,
                70
            ),
            5,
            0
        )

        score += np.where(
            nifty["ADX"] >= 20,
            5,
            0
        )

        regime["MarketScore"] = score

        regime["MarketRegime"] = np.select(

            [

                score >= 80,

                score >= 60,

                score >= 40,

                score >= 20,

            ],

            [

                "STRONG BULL",

                "BULL",

                "NEUTRAL",

                "BEAR",

            ],

            default="STRONG BEAR"

        )

        return regime


# ============================================================
# STRATEGY EVALUATOR
# ============================================================

class FrozenStrategy:

    def __init__(
        self,
        config: BacktestConfig,
        market_history: pd.DataFrame
    ):

        self.config = config

        self.market = market_history

    # ========================================================
    # RELATIVE STRENGTH
    # ========================================================

    def relative_strength_series(
        self,
        stock: pd.DataFrame
    ) -> pd.DataFrame:

        result = pd.DataFrame(
            index=stock.index
        )

        for period, name in [
            (
                self.config.rs20_period,
                "RS20"
            ),
            (
                self.config.rs60_period,
                "RS60"
            ),
            (
                self.config.rs120_period,
                "RS120"
            ),
        ]:

            stock_return = (
                stock["Close"]
                .pct_change(periods=period)
            )

            nifty_return = (
                self.market["Price"]
                .pct_change(periods=period)
            )

            result[name] = (
                stock_return -
                nifty_return
            ) * 100.0

        return result

    # ========================================================
    # TREND
    # ========================================================

    @staticmethod
    def trend_structure_row(
        row
    ) -> str:

        price = row["Close"]

        sma20 = row["SMA20"]

        sma50 = row["SMA50"]

        sma200 = row["SMA200"]

        if (
            price >
            sma20 >
            sma50 >
            sma200
        ):

            return "STRONG BULLISH"

        if (
            price >
            sma50 >
            sma200
        ):

            return "BULLISH"

        if (
            price >
            sma50
            and
            sma50 <= sma200
        ):

            return "MIXED BULLISH"

        if (
            price <
            sma20 <
            sma50 <
            sma200
        ):

            return "DEEP BEARISH"

        if (
            price <
            sma50 <
            sma200
        ):

            return "BEARISH"

        return "MIXED"

    # ========================================================
    # TECHNICAL SCORE
    # ========================================================

    def technical_score(
        self,
        trend: str,
        daily_bull: bool,
        weekly_bull: bool,
        daily_rsi: float,
        weekly_rsi: float,
        adx: float,
        rs20: float,
        rs60: float,
        rs120: float,
        volume_ratio: float
    ) -> float:

        score = 0.0

        trend_points = {

            "STRONG BULLISH": 30,

            "BULLISH": 26,

            "MIXED BULLISH": 17,

            "MIXED": 10,

            "BEARISH": 4,

            "DEEP BEARISH": 0,

        }

        score += trend_points.get(
            trend,
            0
        )

        if weekly_bull:
            score += 5

        if daily_bull:
            score += 5

        if 50 <= daily_rsi <= 65:

            score += 10

        elif 45 <= daily_rsi < 50:

            score += 6

        elif 65 < daily_rsi <= 70:

            score += 5

        elif 70 < daily_rsi <= 75:

            score += 2

        if 45 <= weekly_rsi <= 65:

            score += 5

        elif 65 < weekly_rsi <= 70:

            score += 2

        if adx >= 30:

            score += 10

        elif adx >= 25:

            score += 9

        elif adx >= 20:

            score += 7

        elif adx >= 15:

            score += 3

        positive = sum([

            rs20 > 0,

            rs60 > 0,

            rs120 > 0,

        ])

        if positive == 3:

            score += 20

        elif positive == 2:

            score += 13

        elif positive == 1:

            score += 6

        if volume_ratio >= 1.5:

            score += 5

        elif volume_ratio >= 1.0:

            score += 3

        elif volume_ratio >= 0.7:

            score += 1

        return max(
            0,
            min(
                100,
                score
            )
        )

    # ========================================================
    # ACTIONABILITY SCORE
    # ========================================================

    def actionability_score(
        self,
        setup: str,
        market_regime: str,
        trend: str,
        daily_rsi: float,
        weekly_rsi: float,
        distance20: float,
        distance50: float,
        volume_ratio: float,
        rr_t1: Optional[float],
        rr_t2: Optional[float],
        resistance_distance: Optional[float],
        trade_valid: bool
    ) -> float:

        score = 0.0

        setup_points = {

            "PULLBACK": 25,

            "BREAKOUT": 25,

            "OVEREXTENDED": 0,

            "NO_CLEAR_SETUP": 0,

        }

        score += setup_points.get(
            setup,
            0
        )

        trend_points = {

            "STRONG BULLISH": 15,

            "BULLISH": 13,

            "MIXED BULLISH": 7,

            "MIXED": 4,

            "BEARISH": 1,

            "DEEP BEARISH": 0,

        }

        score += trend_points.get(
            trend,
            0
        )

        if -0.02 <= distance20 <= 0.03:
            score += 10

        elif 0.03 < distance20 <= 0.06:
            score += 5

        if -0.02 <= distance50 <= 0.05:
            score += 8

        elif 0.05 < distance50 <= 0.10:
            score += 4

        if 45 <= daily_rsi <= 65:
            score += 7

        elif 65 < daily_rsi <= 70:
            score += 3

        if weekly_rsi <= 70:
            score += 3

        if setup == "PULLBACK":

            if volume_ratio >= 1.0:
                score += 5

            elif volume_ratio >= 0.7:
                score += 3

            else:
                score += 1

        elif setup == "BREAKOUT":

            if volume_ratio >= 1.5:
                score += 10

            elif volume_ratio >= 1.2:
                score += 7

            elif volume_ratio >= 1.0:
                score += 3

        if rr_t1 is not None:

            if rr_t1 >= 2.0:
                score += 12

            elif rr_t1 >= 1.5:
                score += 8

            elif rr_t1 >= 1.0:
                score += 2

        if rr_t2 is not None:

            if rr_t2 >= 3.0:
                score += 5

            elif rr_t2 >= 2.0:
                score += 4

            elif rr_t2 >= 1.5:
                score += 2

        market_points = {

            "STRONG BULL": 5,

            "BULL": 4,

            "NEUTRAL": 2,

            "BEAR": 0,

            "STRONG BEAR": 0,

        }

        score += market_points.get(
            market_regime,
            0
        )

        if resistance_distance is not None:

            if resistance_distance >= 0.08:
                score += 5

            elif resistance_distance >= 0.05:
                score += 3

            elif resistance_distance >= 0.03:
                score += 1

        if not trade_valid:
            score -= 25

        if market_regime == "BEAR":
            score -= 10

        elif market_regime == "STRONG BEAR":
            score -= 20

        if daily_rsi > 70:
            score -= 8

        if daily_rsi > 75:
            score -= 8

        if distance20 > 0.06:
            score -= 8

        if distance20 > 0.10:
            score -= 10

        if trend in [
            "BEARISH",
            "DEEP BEARISH"
        ]:

            score -= 15

        if (
            rr_t1 is not None
            and
            rr_t1 < 1.0
        ):

            score -= 30

        elif (
            rr_t1 is not None
            and
            rr_t1 < 1.5
        ):

            score -= 15

        score = max(
            0,
            min(
                100,
                score
            )
        )

        if setup == "NO_CLEAR_SETUP":

            score = min(
                score,
                20
            )

        if setup == "OVEREXTENDED":

            score = min(
                score,
                20
            )

        if trend in [
            "BEARISH",
            "DEEP BEARISH"
        ]:

            score = min(
                score,
                40
            )

        if (
            rr_t1 is not None
            and
            rr_t1 < 1.0
        ):

            score = min(
                score,
                20
            )

        elif (
            rr_t1 is not None
            and
            rr_t1 < 1.5
        ):

            score = min(
                score,
                35
            )

        return score

    # ========================================================
    # HISTORICAL RESISTANCE
    # ========================================================

    @staticmethod
    def historical_resistance(
        daily: pd.DataFrame,
        entry: float
    ) -> Tuple[
        Optional[float],
        Optional[float]
    ]:

        levels = []

        for period in [
            20,
            60,
            120,
        ]:

            if len(daily) <= period:
                continue

            high = (
                daily["High"]
                .rolling(
                    period,
                    min_periods=period
                )
                .max()
                .shift(1)
                .iloc[-1]
            )

            if np.isfinite(high):

                high = float(high)

                if high > entry:

                    levels.append(
                        high
                    )

        levels = sorted(
            set(levels)
        )

        if not levels:

            return (
                None,
                None
            )

        r1 = levels[0]

        r2 = None

        for level in levels[1:]:

            if level > r1 * 1.01:

                r2 = level

                break

        return (
            r1,
            r2
        )

    # ========================================================
    # HISTORICAL STOCK SIGNALS
    # ========================================================

    def prepare_stock(
        self,
        ticker: str,
        raw: pd.DataFrame
    ) -> pd.DataFrame:

        stock = FeatureEngine(
            self.config
        ).add_stock_features(
            raw
        )

        weekly_map = (
            FeatureEngine(
                self.config
            )
            .make_completed_weekly_map(
                raw
            )
        )

        stock = stock.join(
            weekly_map
        )

        rs = (
            self.relative_strength_series(
                stock
            )
        )

        stock = stock.join(
            rs
        )

        # ----------------------------------------------------
        # We can precompute many fields vectorially.
        # Trade levels that depend on a specific setup are
        # calculated only when a candidate occurs.
        # ----------------------------------------------------

        stock["Distance20"] = (
            stock["Close"] /
            stock["SMA20"] -
            1.0
        )

        stock["Distance50"] = (
            stock["Close"] /
            stock["SMA50"] -
            1.0
        )

        stock["DailyBull"] = (
            stock["STTrend"] == 1
        )

        stock["WeeklyBull"] = (
            stock["WeeklySTTrend"] == 1
        )

        stock["TrendStructure"] = [
            self.trend_structure_row(
                row
            )
            for _, row in stock.iterrows()
        ]

        stock["Overextended"] = (

            (stock["RSI"] > self.config.overextended_rsi)

            |

            (stock["WeeklyRSI"] > self.config.overextended_rsi)

            |

            (stock["Distance20"] >
             self.config.extension_distance)

            |

            (stock["Distance50"] >
             self.config.extension_distance)

        )

        return stock

    # ========================================================
    # SIGNAL AT ONE DATE
    # ========================================================

    def signal_at(
        self,
        ticker: str,
        stock: pd.DataFrame,
        position: int
    ) -> Optional[Dict]:

        if position < 0:

            return None

        row = stock.iloc[position]

        signal_date = stock.index[position]

        required_fields = [

            "Close",

            "SMA20",

            "SMA50",

            "SMA200",

            "RSI",

            "ATR",

            "ADX",

            "VolumeRatio",

            "ST",

            "STTrend",

            "WeeklyRSI",

            "WeeklySTTrend",

            "RS20",

            "RS60",

            "RS120",

        ]

        if any(
            pd.isna(row[field])
            for field in required_fields
        ):

            return None

        # ----------------------------------------------------
        # Market
        # ----------------------------------------------------

        if signal_date not in self.market.index:

            return None

        market_row = (
            self.market.loc[
                signal_date
            ]
        )

        market_regime = (
            market_row["MarketRegime"]
        )

        market_score = float(
            market_row["MarketScore"]
        )

        price = float(
            row["Close"]
        )

        sma20 = float(
            row["SMA20"]
        )

        sma50 = float(
            row["SMA50"]
        )

        sma200 = float(
            row["SMA200"]
        )

        rsi = float(
            row["RSI"]
        )

        weekly_rsi = float(
            row["WeeklyRSI"]
        )

        atr = float(
            row["ATR"]
        )

        adx = float(
            row["ADX"]
        )

        volume_ratio = float(
            row["VolumeRatio"]
        )

        daily_bull = (
            row["STTrend"] == 1
        )

        weekly_bull = (
            row["WeeklySTTrend"] == 1
        )

        trend = (
            row["TrendStructure"]
        )

        rs20 = float(
            row["RS20"]
        )

        rs60 = float(
            row["RS60"]
        )

        rs120 = float(
            row["RS120"]
        )

        distance20 = float(
            row["Distance20"]
        )

        distance50 = float(
            row["Distance50"]
        )

        overextended = bool(
            row["Overextended"]
        )

        # ----------------------------------------------------
        # Setup detection
        # ----------------------------------------------------

        pullback = False

        if (
            daily_bull
            and
            weekly_bull
            and
            price > sma50 > sma200
            and
            distance20 <=
            self.config.pullback_max_distance_20dma
            and
            rsi <= 65
        ):

            recent_high = row[
                "RecentHigh20"
            ]

            if np.isfinite(recent_high):

                pullback = (
                    price <
                    float(recent_high) *
                    0.99
                )

        breakout = False

        breakout_level = np.nan

        previous_high = row[
            "BreakoutHigh20"
        ]

        if (
            daily_bull
            and
            weekly_bull
            and
            rsi >= 50
            and
            adx >= 18
            and
            volume_ratio >=
            self.config.breakout_volume_ratio
            and
            np.isfinite(previous_high)
        ):

            breakout_level = (
                float(previous_high) *
                (
                    1 +
                    self.config.breakout_buffer
                )
            )

            if price > breakout_level:

                if (
                    distance20 <=
                    self.config.breakout_max_extension
                ):

                    breakout = True

        if breakout:

            setup = "BREAKOUT"

        elif pullback:

            setup = "PULLBACK"

        elif overextended:

            setup = "OVEREXTENDED"

        else:

            setup = "NO_CLEAR_SETUP"

        # ----------------------------------------------------
        # Trade levels
        # ----------------------------------------------------

        entry_low = None

        entry_high = None

        stop = None

        target1 = None

        target2 = None

        rr1 = None

        rr2 = None

        resistance1 = None

        resistance2 = None

        trade_valid = False

        # ----------------------------------------------------
        # PULLBACK
        # ----------------------------------------------------

        if setup == "PULLBACK":

            # Nearest historical support candidates.
            swing_low = row[
                "SwingLow10"
            ]

            support_candidates = []

            if np.isfinite(swing_low):

                support_candidates.append(
                    (
                        "SWING LOW",
                        float(swing_low)
                    )
                )

            if np.isfinite(sma20):

                support_candidates.append(
                    (
                        "20 DMA",
                        sma20
                    )
                )

            if np.isfinite(sma50):

                support_candidates.append(
                    (
                        "50 DMA",
                        sma50
                    )
                )

            st = float(
                row["ST"]
            )

            if np.isfinite(st):

                support_candidates.append(
                    (
                        "SUPERTREND",
                        st
                    )
                )

            support_candidates = [

                x
                for x in support_candidates
                if x[1] < price

            ]

            if support_candidates:

                support_candidates.sort(
                    key=lambda x: x[1],
                    reverse=True
                )

                support_type, support = (
                    support_candidates[0]
                )

                support_buffer = (
                    atr * 0.40
                )

                entry_low = max(

                    support -
                    support_buffer,

                    sma50 * 0.985

                )

                entry_high = min(

                    price,

                    support +
                    support_buffer

                )

                if entry_low > entry_high:

                    entry_low = max(

                        support * 0.995,

                        entry_high -
                        atr * 0.50

                    )

                entry_reference = (
                    entry_high
                )

                stop_candidates = [

                    float(swing_low) *
                    (
                        1 -
                        self.config.stop_buffer_pct
                    )
                    if np.isfinite(swing_low)
                    else np.nan,

                    support *
                    (
                        1 -
                        self.config.stop_buffer_pct
                    ),

                    st *
                    (
                        1 -
                        self.config.stop_buffer_pct
                    )
                    if np.isfinite(st)
                    else np.nan,

                    entry_reference -
                    (
                        atr *
                        self.config.atr_stop_multiplier
                    ),

                ]

                stop_candidates = [

                    x
                    for x in stop_candidates
                    if np.isfinite(x)
                    and x < entry_reference

                ]

                if stop_candidates:

                    stop = min(
                        stop_candidates
                    )

        else:

            support_type = None

            support = None

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        if setup == "BREAKOUT":

            if np.isfinite(
                breakout_level
            ):

                entry_low = (
                    float(breakout_level)
                )

                entry_high = (
                    float(breakout_level) *
                    1.015
                )

                entry_reference = (
                    entry_high
                )

                swing_low = row[
                    "SwingLow10"
                ]

                if np.isfinite(
                    swing_low
                ):

                    retest_low = float(
                        swing_low
                    )

                else:

                    retest_low = (
                        entry_reference -
                        atr
                    )

                stop_candidates = [

                    retest_low *
                    (
                        1 -
                        self.config.stop_buffer_pct
                    ),

                    float(breakout_level) *
                    (
                        1 -
                        self.config.stop_buffer_pct
                    ),

                    entry_reference -
                    (
                        atr *
                        self.config.atr_stop_multiplier
                    ),

                ]

                stop_candidates = [

                    x
                    for x in stop_candidates
                    if np.isfinite(x)
                    and x < entry_reference

                ]

                if stop_candidates:

                    stop = min(
                        stop_candidates
                    )

            support_type = None

            support = None

        # ----------------------------------------------------
        # Resistance / targets
        # ----------------------------------------------------

        if (
            entry_high is not None
            and
            stop is not None
        ):

            historical_until_now = (
                stock.iloc[
                    :position + 1
                ]
            )

            (
                resistance1,
                resistance2
            ) = self.historical_resistance(
                historical_until_now,
                entry_high
            )

            risk = (
                entry_high -
                stop
            )

            if risk > 0:

                if (
                    resistance1 is not None
                    and
                    resistance1 > entry_high
                ):

                    target1 = resistance1

                else:

                    target1 = (
                        entry_high +
                        risk * 1.5
                    )

                if (
                    resistance2 is not None
                    and
                    resistance2 > target1
                ):

                    target2 = resistance2

                else:

                    target2 = (
                        entry_high +
                        risk * 2.5
                    )

                if target2 <= target1:

                    target2 = (
                        target1 +
                        max(
                            atr,
                            risk * 0.50
                        )
                    )

                rr1 = (
                    target1 -
                    entry_high
                ) / risk

                rr2 = (
                    target2 -
                    entry_high
                ) / risk

                trade_valid = True

        # ----------------------------------------------------
        # Scores
        # ----------------------------------------------------

        tech = self.technical_score(

            trend,

            daily_bull,

            weekly_bull,

            rsi,

            weekly_rsi,

            adx,

            rs20,

            rs60,

            rs120,

            volume_ratio

        )

        resistance_distance = None

        if (
            resistance1 is not None
            and
            entry_high is not None
        ):

            resistance_distance = (
                resistance1 /
                entry_high
            ) - 1.0

        actionability = (
            self.actionability_score(

                setup,

                market_regime,

                trend,

                rsi,

                weekly_rsi,

                distance20,

                distance50,

                volume_ratio,

                rr1,

                rr2,

                resistance_distance,

                trade_valid

            )
        )

        # ----------------------------------------------------
        # Quality
        # ----------------------------------------------------

        if setup in [
            "NO_CLEAR_SETUP",
            "OVEREXTENDED"
        ]:

            quality = "POOR"

        elif (
            rr1 is None
            or
            rr1 < 1.0
            or
            actionability < 40
        ):

            quality = "POOR"

        elif (
            rr1 >= 2.0
            and
            actionability >= 75
        ):

            quality = "GOOD"

        elif (
            rr1 >= 1.5
            and
            actionability >= 55
        ):

            quality = "FAIR"

        else:

            quality = "POOR"

        # ----------------------------------------------------
        # Final signal
        # ----------------------------------------------------

        signal = "AVOID"

        if (

            trade_valid

            and

            setup in [
                "PULLBACK",
                "BREAKOUT"
            ]

            and

            quality == "GOOD"

            and

            tech >=
            self.config.strong_buy_technical

            and

            actionability >=
            self.config.strong_buy_actionability

            and

            rr1 >=
            self.config.preferred_t1_rr

            and

            market_regime in [
                "STRONG BULL",
                "BULL"
            ]

            and

            trend in [
                "STRONG BULLISH",
                "BULLISH"
            ]

            and

            not overextended

        ):

            signal = "STRONG BUY"

        elif (

            trade_valid

            and

            setup in [
                "PULLBACK",
                "BREAKOUT"
            ]

            and

            quality in [
                "GOOD",
                "FAIR"
            ]

            and

            tech >=
            self.config.buy_technical

            and

            actionability >=
            self.config.buy_actionability

            and

            rr1 >=
            self.config.minimum_t1_rr

            and

            market_regime in [
                "STRONG BULL",
                "BULL",
                "NEUTRAL"
            ]

            and

            trend in [
                "STRONG BULLISH",
                "BULLISH"
            ]

            and

            not overextended

        ):

            signal = "BUY"

        elif (

            trade_valid

            and

            setup in [
                "PULLBACK",
                "BREAKOUT"
            ]

            and

            tech >= 70

            and

            actionability >=
            self.config.watch_actionability

            and

            rr1 >=
            self.config.minimum_t1_rr

            and

            market_regime in [
                "BEAR",
                "STRONG BEAR"
            ]

        ):

            signal = (
                "WATCH - MARKET RISK"
            )

        elif (

            setup == "OVEREXTENDED"

            and

            tech >=
            self.config.watch_technical

        ):

            signal = (
                "WATCH - EXTENDED"
            )

        elif (

            tech >=
            self.config.watch_technical

            and

            actionability >=
            self.config.watch_actionability

            and

            setup not in [
                "NO_CLEAR_SETUP",
                "OVEREXTENDED"
            ]

            and

            (
                rr1 is None
                or
                rr1 >=
                self.config.minimum_t1_rr
            )

        ):

            signal = "WATCH"

        elif (

            setup in [
                "PULLBACK",
                "BREAKOUT"
            ]

            and

            (
                tech >= 60
                or
                actionability >= 30
            )

            and

            rr1 is not None

            and

            rr1 <
            self.config.minimum_t1_rr

        ):

            signal = (
                "WAIT FOR BETTER ENTRY"
            )

        elif (

            setup == "OVEREXTENDED"

        ):

            signal = (
                "WATCH - EXTENDED"
            )

        elif (

            setup == "NO_CLEAR_SETUP"

            and

            tech >= 60

            and

            price > sma50

            and

            price > sma200

        ):

            signal = (
                "WAIT - NO SETUP"
            )

        else:

            signal = "AVOID"

        # ----------------------------------------------------
        # Only historical signals on/after the real test date
        # ----------------------------------------------------

        return {

            "Ticker": ticker,

            "Signal Date": signal_date,

            "Signal": signal,

            "Setup": setup,

            "Trade Quality": quality,

            "Technical Score": round(
                tech,
                2
            ),

            "Actionability Score": round(
                actionability,
                2
            ),

            "Market Regime": market_regime,

            "Market Score": round(
                market_score,
                2
            ),

            "Price": round(
                price,
                4
            ),

            "Entry Low": (
                round(entry_low, 4)
                if entry_low is not None
                else np.nan
            ),

            "Entry High": (
                round(entry_high, 4)
                if entry_high is not None
                else np.nan
            ),

            "Stop Loss": (
                round(stop, 4)
                if stop is not None
                else np.nan
            ),

            "Target 1": (
                round(target1, 4)
                if target1 is not None
                else np.nan
            ),

            "Target 2": (
                round(target2, 4)
                if target2 is not None
                else np.nan
            ),

            "R:R T1": (
                round(rr1, 4)
                if rr1 is not None
                else np.nan
            ),

            "R:R T2": (
                round(rr2, 4)
                if rr2 is not None
                else np.nan
            ),

            "Daily RSI": round(
                rsi,
                2
            ),

            "Weekly RSI": round(
                weekly_rsi,
                2
            ),

            "ADX": round(
                adx,
                2
            ),

            "Daily ST":
                "BULLISH"
                if daily_bull
                else "BEARISH",

            "Weekly ST":
                "BULLISH"
                if weekly_bull
                else "BEARISH",

            "20 DMA": round(
                sma20,
                4
            ),

            "50 DMA": round(
                sma50,
                4
            ),

            "200 DMA": round(
                sma200,
                4
            ),

            "Volume Ratio": round(
                volume_ratio,
                4
            ),

            "RS 20D": round(
                rs20,
                4
            ),

            "RS 60D": round(
                rs60,
                4
            ),

            "RS 120D": round(
                rs120,
                4
            ),

            "Distance 20DMA %": round(
                distance20 * 100,
                4
            ),

            "Distance 50DMA %": round(
                distance50 * 100,
                4
            ),

            "Trend Structure":
                trend,

            "Overextended":
                overextended,

            "Support Type":
                support_type
                if support_type
                else "",

            "Support":
                round(support, 4)
                if support is not None
                else np.nan,

            "Resistance 1":
                round(resistance1, 4)
                if resistance1 is not None
                else np.nan,

            "Resistance 2":
                round(resistance2, 4)
                if resistance2 is not None
                else np.nan,

        }


# ============================================================
# TRADE SIMULATOR
# ============================================================

class TradeSimulator:

    def __init__(
        self,
        config: BacktestConfig
    ):

        self.config = config

    # --------------------------------------------------------
    # Cost
    # --------------------------------------------------------

    def total_round_trip_cost(
        self
    ) -> float:

        bps = (

            self.config.slippage_bps * 2

            +

            self.config.transaction_cost_bps * 2

        )

        return bps / 10000.0

    # --------------------------------------------------------
    # Find entry
    # --------------------------------------------------------

    def find_entry(
        self,
        stock: pd.DataFrame,
        signal_position: int,
        setup: str,
        entry_low: float,
        entry_high: float
    ) -> Optional[Dict]:

        # Signal is generated after the signal day's close.
        # Therefore we can only enter from the NEXT trading day.

        future = stock.iloc[
            signal_position + 1:
        ]

        if future.empty:

            return None

        if setup == "BREAKOUT":

            row = future.iloc[0]

            entry_date = future.index[0]

            open_price = float(
                row["Open"]
            )

            # Avoid chasing extreme gaps.
            max_entry = (
                entry_high *
                1.005
            )

            if open_price <= max_entry:

                return {

                    "Entry Date":
                        entry_date,

                    "Entry Price":
                        open_price,

                    "Entry Method":
                        "NEXT_OPEN",

                }

            return None

        if setup == "PULLBACK":

            search = future.head(
                self.config.pullback_entry_window
            )

            for entry_date, row in search.iterrows():

                open_price = float(
                    row["Open"]
                )

                low_price = float(
                    row["Low"]
                )

                # Better price through a gap down.
                if open_price <= entry_high:

                    entry_price = (
                        open_price
                    )

                    # Must still be inside/near the
                    # intended support zone.
                    if entry_price >= (
                        entry_low * 0.98
                    ):

                        return {

                            "Entry Date":
                                entry_date,

                            "Entry Price":
                                entry_price,

                            "Entry Method":
                                "PULLBACK_LIMIT",

                        }

                # Intraday touch of limit
                if low_price <= entry_high:

                    return {

                        "Entry Date":
                            entry_date,

                        "Entry Price":
                            entry_high,

                        "Entry Method":
                            "PULLBACK_LIMIT",

                    }

        return None

    # --------------------------------------------------------
    # Exit simulation
    # --------------------------------------------------------

    def simulate(
        self,
        stock: pd.DataFrame,
        entry_date,
        entry_price: float,
        stop: float,
        target: float,
        holding_period: int
    ) -> Dict:

        future = stock.loc[
            stock.index >= entry_date
        ]

        if future.empty:

            return {

                "Exit Date":
                    np.nan,

                "Exit Price":
                    np.nan,

                "Exit Reason":
                    "NO_FUTURE_DATA",

                "Bars Held":
                    0,

                "Gross Return %":
                    np.nan,

                "Net Return %":
                    np.nan,

                "R Multiple":
                    np.nan,

                "Result":
                    "INVALID",

            }

        cost = (
            self.total_round_trip_cost()
        )

        exit_slippage = (
            self.config.slippage_bps /
            10000.0
        )

        risk = (
            entry_price -
            stop
        )

        if risk <= 0:

            return {

                "Exit Date":
                    np.nan,

                "Exit Price":
                    np.nan,

                "Exit Reason":
                    "INVALID_STOP",

                "Bars Held":
                    0,

                "Gross Return %":
                    np.nan,

                "Net Return %":
                    np.nan,

                "R Multiple":
                    np.nan,

                "Result":
                    "INVALID",

            }

        bars = 0

        for idx, row in future.iterrows():

            bars += 1

            open_price = float(
                row["Open"]
            )

            high = float(
                row["High"]
            )

            low = float(
                row["Low"]
            )

            close = float(
                row["Close"]
            )

            # ------------------------------------------------
            # Gap through stop
            # ------------------------------------------------

            if open_price <= stop:

                exit_price = (
                    open_price *
                    (1 - exit_slippage)
                )

                reason = "STOP_GAP"

                return self._result(

                    idx,

                    exit_price,

                    reason,

                    bars,

                    entry_price,

                    risk,

                    cost

                )

            # ------------------------------------------------
            # Gap through target
            # ------------------------------------------------

            if open_price >= target:

                exit_price = (
                    open_price *
                    (1 - exit_slippage)
                )

                reason = "TARGET_GAP"

                return self._result(

                    idx,

                    exit_price,

                    reason,

                    bars,

                    entry_price,

                    risk,

                    cost

                )

            stop_hit = (
                low <= stop
            )

            target_hit = (
                high >= target
            )

            # ------------------------------------------------
            # Conservative collision rule:
            # stop first if both are touched.
            # ------------------------------------------------

            if (
                stop_hit
                and
                target_hit
            ):

                exit_price = (
                    stop *
                    (1 - exit_slippage)
                )

                reason = (
                    "STOP_COLLISION"
                )

                return self._result(

                    idx,

                    exit_price,

                    reason,

                    bars,

                    entry_price,

                    risk,

                    cost

                )

            # ------------------------------------------------
            # Stop
            # ------------------------------------------------

            if stop_hit:

                exit_price = (
                    stop *
                    (1 - exit_slippage)
                )

                reason = "STOP"

                return self._result(

                    idx,

                    exit_price,

                    reason,

                    bars,

                    entry_price,

                    risk,

                    cost

                )

            # ------------------------------------------------
            # Target
            # ------------------------------------------------

            if target_hit:

                exit_price = (
                    target *
                    (1 - exit_slippage)
                )

                reason = "TARGET"

                return self._result(

                    idx,

                    exit_price,

                    reason,

                    bars,

                    entry_price,

                    risk,

                    cost

                )

            # ------------------------------------------------
            # Time exit
            #
            # Exit after the specified number of trading
            # sessions. Because entry occurs at the open of
            # bar 1, bar "holding_period" is the final bar.
            # ------------------------------------------------

            if bars >= holding_period:

                exit_price = (
                    close *
                    (1 - exit_slippage)
                )

                reason = (
                    f"TIME_{holding_period}D"
                )

                return self._result(

                    idx,

                    exit_price,

                    reason,

                    bars,

                    entry_price,

                    risk,

                    cost

                )

        # ----------------------------------------------------
        # Data ended before holding period.
        # ----------------------------------------------------

        last_idx = future.index[-1]

        last_close = float(
            future["Close"].iloc[-1]
        )

        exit_price = (
            last_close *
            (1 - exit_slippage)
        )

        return self._result(

            last_idx,

            exit_price,

            "DATA_END",

            bars,

            entry_price,

            risk,

            cost

        )

    # --------------------------------------------------------
    # Result helper
    # --------------------------------------------------------

    @staticmethod
    def _result(
        exit_date,
        exit_price,
        reason,
        bars,
        entry_price,
        risk,
        cost
    ) -> Dict:

        gross_return = (
            exit_price /
            entry_price -
            1.0
        )

        net_return = (
            gross_return -
            cost
        )

        risk_fraction = (
            risk /
            entry_price
        )

        r_multiple = (
            net_return /
            risk_fraction
            if risk_fraction > 0
            else np.nan
        )

        if net_return > 0:

            result = "WIN"

        elif net_return < 0:

            result = "LOSS"

        else:

            result = "FLAT"

        return {

            "Exit Date":
                exit_date,

            "Exit Price":
                exit_price,

            "Exit Reason":
                reason,

            "Bars Held":
                bars,

            "Gross Return %":
                gross_return * 100.0,

            "Net Return %":
                net_return * 100.0,

            "R Multiple":
                r_multiple,

            "Result":
                result,

        }


# ============================================================
# BACKTEST ENGINE
# ============================================================

class OptimizedBacktest:

    def __init__(
        self,
        config: BacktestConfig,
        tickers: List[str]
    ):

        self.config = config

        self.tickers = tickers

        self.loader = (
            HistoricalDataLoader(
                config
            )
        )

        self.feature_engine = (
            FeatureEngine(
                config
            )
        )

        self.simulator = (
            TradeSimulator(
                config
            )
        )

        self.raw_data: Dict[
            str,
            pd.DataFrame
        ] = {}

        self.features: Dict[
            str,
            pd.DataFrame
        ] = {}

        self.market_history = (
            pd.DataFrame()
        )

        self.signal_records = []

        self.trade_records = []

        self.test_start = (
            self.loader.test_start
        )

        self.test_end = (
            self.loader.test_end
        )

    # ========================================================
    # LOAD ALL DATA
    # ========================================================

    def load_data(self):

        print()
        print("=" * 110)
        print(
            "STAGE 2.1 - OPTIMIZED 15-YEAR BACKTEST"
        )
        print("=" * 110)

        print(
            f"Test start   : "
            f"{self.test_start.date()}"
        )

        print(
            f"Test end     : "
            f"{self.test_end.date()}"
        )

        print(
            f"Warmup start : "
            f"{self.loader.warmup_start.date()}"
        )

        print("=" * 110)

        universe = [
            "^NSEI"
        ] + self.tickers

        for ticker in universe:

            print(
                f"Downloading {ticker}..."
            )

            df = self.loader.download(
                ticker
            )

            if df.empty:

                print(
                    f"  -> FAILED"
                )

                continue

            print(
                f"  -> {len(df):,} candles"
            )

            self.raw_data[
                ticker
            ] = df

        if "^NSEI" not in self.raw_data:

            raise RuntimeError(
                "NIFTY data is required."
            )

    # ========================================================
    # PRECOMPUTE
    # ========================================================

    def precompute(self):

        print()
        print("=" * 110)
        print(
            "PRECOMPUTING INDICATORS"
        )
        print("=" * 110)

        # ----------------------------------------------------
        # Market
        # ----------------------------------------------------

        print(
            "Calculating NIFTY market history..."
        )

        nifty = (
            self.raw_data[
                "^NSEI"
            ].copy()
        )

        self.market_history = (
            self.feature_engine
            .market_regime_history(
                nifty
            )
        )

        print(
            "NIFTY market history ready."
        )

        # ----------------------------------------------------
        # Stocks
        # ----------------------------------------------------

        for ticker in self.tickers:

            if ticker not in self.raw_data:

                continue

            raw = self.raw_data[
                ticker
            ]

            # Need enough total history for indicators.
            if len(raw) < (
                self.config.min_daily_history
            ):

                print(
                    f"SKIPPED {ticker}: "
                    f"only {len(raw)} candles."
                )

                continue

            print(
                f"Precomputing {ticker}..."
            )

            try:

                features = (
                    FrozenStrategy(
                        self.config,
                        self.market_history
                    )
                    .prepare_stock(
                        ticker,
                        raw
                    )
                )

                self.features[
                    ticker
                ] = features

            except Exception as exc:

                print(
                    f"ERROR preparing "
                    f"{ticker}: {exc}"
                )

    # ========================================================
    # SIGNAL SCAN
    # ========================================================

    def generate_signals_and_trades(self):

        strategy = (
            FrozenStrategy(
                self.config,
                self.market_history
            )
        )

        print()
        print("=" * 110)
        print(
            "GENERATING HISTORICAL SIGNALS"
        )
        print("=" * 110)

        for ticker in self.tickers:

            if ticker not in self.features:

                continue

            stock = self.features[
                ticker
            ]

            test_mask = (
            (stock.index >= self.test_start)
            &
            (stock.index <= self.test_end)
            )

# test_mask may already be a NumPy ndarray.
# flatnonzero works for both NumPy arrays and
# boolean-like array results without needing .to_numpy().
            test_positions = np.flatnonzero(test_mask)

            print(
                f"Processing {ticker}: "
                f"{len(test_positions):,} dates"
            )

            signals_count = 0

            eligible_count = 0

            for position in test_positions:

                try:

                    signal = (
                        strategy.signal_at(

                            ticker,

                            stock,

                            int(position)

                        )
                    )

                    if signal is None:

                        continue

                    self.signal_records.append(
                        signal
                    )

                    signals_count += 1

                    # ----------------------------------------
                    # Only actual actionable entries
                    # are sent to trade simulator.
                    # ----------------------------------------

                    if signal["Signal"] not in [

                        "STRONG BUY",

                        "BUY",

                        "WATCH",

                        "WATCH - MARKET RISK",

                    ]:

                        continue

                    if signal["Setup"] not in [

                        "PULLBACK",

                        "BREAKOUT",

                    ]:

                        continue

                    rr1 = safe_float(
                        signal["R:R T1"]
                    )

                    if (
                        rr1 is None
                        or
                        rr1 <
                        self.config.minimum_t1_rr
                    ):

                        continue

                    entry_low = safe_float(
                        signal["Entry Low"]
                    )

                    entry_high = safe_float(
                        signal["Entry High"]
                    )

                    stop = safe_float(
                        signal["Stop Loss"]
                    )

                    target1 = safe_float(
                        signal["Target 1"]
                    )

                    target2 = safe_float(
                        signal["Target 2"]
                    )

                    if any(

                        x is None
                        for x in [
                            entry_low,
                            entry_high,
                            stop,
                            target1,
                            target2,
                        ]

                    ):

                        continue

                    entry = (
                        self.simulator
                        .find_entry(

                            stock,

                            int(position),

                            signal["Setup"],

                            entry_low,

                            entry_high

                        )
                    )

                    if entry is None:

                        continue

                    if entry[
                        "Entry Price"
                    ] <= stop:

                        continue

                    eligible_count += 1

                    base = {

                        "Ticker":
                            ticker,

                        "Signal Date":
                            signal["Signal Date"],

                        "Entry Date":
                            entry["Entry Date"],

                        "Entry Method":
                            entry["Entry Method"],

                        "Entry Price":
                            entry["Entry Price"],

                        "Signal":
                            signal["Signal"],

                        "Setup":
                            signal["Setup"],

                        "Trade Quality":
                            signal["Trade Quality"],

                        "Technical Score":
                            signal["Technical Score"],

                        "Actionability Score":
                            signal[
                                "Actionability Score"
                            ],

                        "Market Regime":
                            signal[
                                "Market Regime"
                            ],

                        "Market Score":
                            signal[
                                "Market Score"
                            ],

                        "Planned Entry Low":
                            entry_low,

                        "Planned Entry High":
                            entry_high,

                        "Stop Loss":
                            stop,

                        "Target 1":
                            target1,

                        "Target 2":
                            target2,

                        "Planned R:R T1":
                            rr1,

                        "Planned R:R T2":
                            signal[
                                "R:R T2"
                            ],

                        "Daily RSI":
                            signal[
                                "Daily RSI"
                            ],

                        "Weekly RSI":
                            signal[
                                "Weekly RSI"
                            ],

                        "ADX":
                            signal[
                                "ADX"
                            ],

                        "Daily ST":
                            signal[
                                "Daily ST"
                            ],

                        "Weekly ST":
                            signal[
                                "Weekly ST"
                            ],

                        "20 DMA":
                            signal[
                                "20 DMA"
                            ],

                        "50 DMA":
                            signal[
                                "50 DMA"
                            ],

                        "200 DMA":
                            signal[
                                "200 DMA"
                            ],

                        "Volume Ratio":
                            signal[
                                "Volume Ratio"
                            ],

                        "RS 20D":
                            signal[
                                "RS 20D"
                            ],

                        "RS 60D":
                            signal[
                                "RS 60D"
                            ],

                        "RS 120D":
                            signal[
                                "RS 120D"
                            ],

                    }

                    # ----------------------------------------
                    # Simulate each horizon
                    # ----------------------------------------

                    for holding_period in (
                        self.config.holding_periods
                    ):

                        t1 = (
                            self.simulator
                            .simulate(

                                stock,

                                entry[
                                    "Entry Date"
                                ],

                                entry[
                                    "Entry Price"
                                ],

                                stop,

                                target1,

                                holding_period

                            )
                        )

                        t2 = (
                            self.simulator
                            .simulate(

                                stock,

                                entry[
                                    "Entry Date"
                                ],

                                entry[
                                    "Entry Price"
                                ],

                                stop,

                                target2,

                                holding_period

                            )
                        )

                        for prefix, result in [
                            (
                                f"T1_{holding_period}D",
                                t1
                            ),
                            (
                                f"T2_{holding_period}D",
                                t2
                            ),
                        ]:

                            base[
                                f"{prefix}_ExitDate"
                            ] = result[
                                "Exit Date"
                            ]

                            base[
                                f"{prefix}_ExitPrice"
                            ] = result[
                                "Exit Price"
                            ]

                            base[
                                f"{prefix}_Reason"
                            ] = result[
                                "Exit Reason"
                            ]

                            base[
                                f"{prefix}_Bars"
                            ] = result[
                                "Bars Held"
                            ]

                            base[
                                f"{prefix}_ReturnPct"
                            ] = result[
                                "Net Return %"
                            ]

                            base[
                                f"{prefix}_R"
                            ] = result[
                                "R Multiple"
                            ]

                            base[
                                f"{prefix}_Result"
                            ] = result[
                                "Result"
                            ]

                    self.trade_records.append(
                        base
                    )

                except Exception as exc:

                    print(
                        f"  ERROR "
                        f"{ticker} "
                        f"{stock.index[position]}: "
                        f"{exc}"
                    )

            print(
                f"  -> Signals: "
                f"{signals_count:,} | "
                f"Eligible trades: "
                f"{eligible_count:,}"
            )

    # ========================================================
    # DATAFRAMES
    # ========================================================

    def signals_dataframe(
        self
    ) -> pd.DataFrame:

        if not self.signal_records:

            return pd.DataFrame()

        return pd.DataFrame(
            self.signal_records
        )

    def trades_dataframe(
        self
    ) -> pd.DataFrame:

        if not self.trade_records:

            return pd.DataFrame()

        return pd.DataFrame(
            self.trade_records
        )

    # ========================================================
    # METRICS
    # ========================================================

    @staticmethod
    def metrics(
        df: pd.DataFrame,
        r_col: str,
        return_col: str,
        result_col: str,
        bars_col: str
    ) -> Dict:

        if df.empty:

            return {

                "Trades": 0,

                "Wins": 0,

                "Losses": 0,

                "Win Rate %": 0.0,

                "Average Return %": 0.0,

                "Median Return %": 0.0,

                "Average R": 0.0,

                "Median R": 0.0,

                "Profit Factor": 0.0,

                "Expectancy R": 0.0,

                "Average Holding Days": 0.0,

                "Max Consecutive Losses": 0,

            }

        r = pd.to_numeric(
            df[r_col],
            errors="coerce"
        ).dropna()

        returns = pd.to_numeric(
            df[return_col],
            errors="coerce"
        ).dropna()

        results = (
            df[result_col]
            .fillna("")
            .astype(str)
        )

        bars = pd.to_numeric(
            df[bars_col],
            errors="coerce"
        ).dropna()

        wins = int(
            (results == "WIN").sum()
        )

        losses = int(
            (results == "LOSS").sum()
        )

        total = len(
            df
        )

        win_rate = (
            wins /
            total *
            100
            if total
            else 0
        )

        positive_r = r[
            r > 0
        ].sum()

        negative_r = abs(
            r[
                r < 0
            ].sum()
        )

        if negative_r > 0:

            profit_factor = (
                positive_r /
                negative_r
            )

        elif positive_r > 0:

            profit_factor = np.inf

        else:

            profit_factor = 0.0

        max_losses = 0

        current_losses = 0

        for result in results:

            if result == "LOSS":

                current_losses += 1

                max_losses = max(
                    max_losses,
                    current_losses
                )

            else:

                current_losses = 0

        return {

            "Trades":
                total,

            "Wins":
                wins,

            "Losses":
                losses,

            "Win Rate %":
                round(
                    win_rate,
                    2
                ),

            "Average Return %":
                round(
                    returns.mean(),
                    4
                ),

            "Median Return %":
                round(
                    returns.median(),
                    4
                ),

            "Average R":
                round(
                    r.mean(),
                    4
                ),

            "Median R":
                round(
                    r.median(),
                    4
                ),

            "Profit Factor":
                round(
                    profit_factor,
                    4
                )
                if np.isfinite(
                    profit_factor
                )
                else np.inf,

            "Expectancy R":
                round(
                    r.mean(),
                    4
                ),

            "Average Holding Days":
                round(
                    bars.mean(),
                    2
                )
                if len(bars)
                else 0.0,

            "Max Consecutive Losses":
                max_losses,

        }

    # ========================================================
    # HOLDING SUMMARY
    # ========================================================

    def holding_summary(
        self
    ) -> pd.DataFrame:

        trades = (
            self.trades_dataframe()
        )

        rows = []

        if trades.empty:

            return pd.DataFrame()

        for holding_period in (
            self.config.holding_periods
        ):

            for target_name in [
                "T1",
                "T2"
            ]:

                r_col = (
                    f"{target_name}_"
                    f"{holding_period}D_R"
                )

                return_col = (
                    f"{target_name}_"
                    f"{holding_period}D_ReturnPct"
                )

                result_col = (
                    f"{target_name}_"
                    f"{holding_period}D_Result"
                )

                bars_col = (
                    f"{target_name}_"
                    f"{holding_period}D_Bars"
                )

                if r_col not in trades:

                    continue

                test = trades[
                    [
                        r_col,
                        return_col,
                        result_col,
                        bars_col,
                    ]
                ].dropna(
                    subset=[
                        r_col,
                        return_col,
                    ]
                )

                m = self.metrics(

                    test,

                    r_col,

                    return_col,

                    result_col,

                    bars_col

                )

                m[
                    "Target"
                ] = target_name

                m[
                    "Holding Period"
                ] = holding_period

                rows.append(
                    m
                )

        return pd.DataFrame(
            rows
        )

    # ========================================================
    # STOCK SUMMARY
    # ========================================================

    def stock_summary(
        self
    ) -> pd.DataFrame:

        trades = (
            self.trades_dataframe()
        )

        if trades.empty:

            return pd.DataFrame()

        holding = (
            self.config.primary_holding_period
        )

        r_col = (
            f"T1_{holding}D_R"
        )

        return_col = (
            f"T1_{holding}D_ReturnPct"
        )

        result_col = (
            f"T1_{holding}D_Result"
        )

        bars_col = (
            f"T1_{holding}D_Bars"
        )

        rows = []

        for ticker, group in (
            trades.groupby(
                "Ticker"
            )
        ):

            m = self.metrics(

                group,

                r_col,

                return_col,

                result_col,

                bars_col

            )

            m["Ticker"] = ticker

            rows.append(
                m
            )

        return (
            pd.DataFrame(rows)
            .sort_values(
                [
                    "Expectancy R",
                    "Profit Factor"
                ],
                ascending=False
            )
        )

    # ========================================================
    # SETUP SUMMARY
    # ========================================================

    def setup_summary(
        self
    ) -> pd.DataFrame:

        trades = (
            self.trades_dataframe()
        )

        if trades.empty:

            return pd.DataFrame()

        holding = (
            self.config.primary_holding_period
        )

        r_col = (
            f"T1_{holding}D_R"
        )

        return_col = (
            f"T1_{holding}D_ReturnPct"
        )

        result_col = (
            f"T1_{holding}D_Result"
        )

        bars_col = (
            f"T1_{holding}D_Bars"
        )

        rows = []

        for setup, group in (
            trades.groupby(
                "Setup"
            )
        ):

            m = self.metrics(

                group,

                r_col,

                return_col,

                result_col,

                bars_col

            )

            m["Setup"] = setup

            rows.append(
                m
            )

        return pd.DataFrame(
            rows
        )

    # ========================================================
    # REGIME SUMMARY
    # ========================================================

    def regime_summary(
        self
    ) -> pd.DataFrame:

        trades = (
            self.trades_dataframe()
        )

        if trades.empty:

            return pd.DataFrame()

        holding = (
            self.config.primary_holding_period
        )

        r_col = (
            f"T1_{holding}D_R"
        )

        return_col = (
            f"T1_{holding}D_ReturnPct"
        )

        result_col = (
            f"T1_{holding}D_Result"
        )

        bars_col = (
            f"T1_{holding}D_Bars"
        )

        rows = []

        for regime, group in (
            trades.groupby(
                "Market Regime"
            )
        ):

            m = self.metrics(

                group,

                r_col,

                return_col,

                result_col,

                bars_col

            )

            m[
                "Market Regime"
            ] = regime

            rows.append(
                m
            )

        return pd.DataFrame(
            rows
        )

    # ========================================================
    # SIGNAL SUMMARY
    # ========================================================

    def signal_summary(
        self
    ) -> pd.DataFrame:

        signals = (
            self.signals_dataframe()
        )

        if signals.empty:

            return pd.DataFrame()

        return (

            signals[
                "Signal"
            ]
            .value_counts()
            .rename_axis(
                "Signal"
            )
            .reset_index(
                name="Count"
            )

        )

    # ========================================================
    # EQUITY CURVE
    # ========================================================

    def equity_curve(
        self
    ) -> pd.DataFrame:

        trades = (
            self.trades_dataframe()
        )

        if trades.empty:

            return pd.DataFrame()

        holding = (
            self.config.primary_holding_period
        )

        r_col = (
            f"T1_{holding}D_R"
        )

        result_col = (
            f"T1_{holding}D_Result"
        )

        exit_col = (
            f"T1_{holding}D_ExitDate"
        )

        data = trades[
            [
                "Ticker",
                "Entry Date",
                exit_col,
                r_col,
                result_col,
            ]
        ].copy()

        data = data.dropna(
            subset=[
                "Entry Date",
                exit_col,
                r_col,
            ]
        )

        data = data.sort_values(
            [
                exit_col,
                "Entry Date"
            ]
        )

        equity = (
            self.config.starting_equity
        )

        rows = []

        for _, row in data.iterrows():

            r_multiple = float(
                row[r_col]
            )

            pnl = (

                equity *

                self.config.risk_per_trade *

                r_multiple

            )

            equity += pnl

            rows.append({

                "Exit Date":
                    row[exit_col],

                "Ticker":
                    row["Ticker"],

                "Entry Date":
                    row["Entry Date"],

                "R Multiple":
                    r_multiple,

                "Result":
                    row[result_col],

                "PnL":
                    pnl,

                "Equity":
                    equity,

            })

        curve = pd.DataFrame(
            rows
        )

        if curve.empty:

            return curve

        curve["Peak"] = (
            curve["Equity"]
            .cummax()
        )

        curve["Drawdown %"] = (

            curve["Equity"] /
            curve["Peak"] -
            1.0

        ) * 100.0

        return curve

    # ========================================================
    # MAIN SUMMARY
    # ========================================================

    def print_summary(
        self
    ):

        signals = (
            self.signals_dataframe()
        )

        trades = (
            self.trades_dataframe()
        )

        print()
        print("=" * 110)
        print(
            "STAGE 2.1 - 15 YEAR BACKTEST RESULT"
        )
        print("=" * 110)

        print(
            f"Historical signals : "
            f"{len(signals):,}"
        )

        print(
            f"Eligible trades    : "
            f"{len(trades):,}"
        )

        if trades.empty:

            print(
                "No eligible trades were generated."
            )

            return

        holding = (
            self.config.primary_holding_period
        )

        r_col = (
            f"T1_{holding}D_R"
        )

        return_col = (
            f"T1_{holding}D_ReturnPct"
        )

        result_col = (
            f"T1_{holding}D_Result"
        )

        bars_col = (
            f"T1_{holding}D_Bars"
        )

        test = trades[
            [
                r_col,
                return_col,
                result_col,
                bars_col,
            ]
        ].dropna()

        m = self.metrics(

            test,

            r_col,

            return_col,

            result_col,

            bars_col

        )

        print()
        print(
            f"PRIMARY TEST: "
            f"T1 / {holding} trading days"
        )

        print(
            f"Trades                 : "
            f"{m['Trades']:,}"
        )

        print(
            f"Win Rate               : "
            f"{m['Win Rate %']:.2f}%"
        )

        print(
            f"Average Return         : "
            f"{m['Average Return %']:.4f}%"
        )

        print(
            f"Median Return          : "
            f"{m['Median Return %']:.4f}%"
        )

        print(
            f"Average R              : "
            f"{m['Average R']:.4f}"
        )

        print(
            f"Profit Factor          : "
            f"{m['Profit Factor']}"
        )

        print(
            f"Expectancy             : "
            f"{m['Expectancy R']:.4f} R"
        )

        print(
            f"Average Holding Days   : "
            f"{m['Average Holding Days']:.2f}"
        )

        print(
            f"Max Consecutive Losses : "
            f"{m['Max Consecutive Losses']}"
        )

        curve = self.equity_curve()

        if not curve.empty:

            print(
                f"Starting Equity        : "
                f"₹{self.config.starting_equity:,.2f}"
            )

            print(
                f"Sequential Equity      : "
                f"₹{curve['Equity'].iloc[-1]:,.2f}"
            )

            print(
                f"Maximum Drawdown       : "
                f"{curve['Drawdown %'].min():.2f}%"
            )

        print("=" * 110)

    # ========================================================
    # SAVE
    # ========================================================

    def save_outputs(
        self
    ):

        output = Path(
            self.config.output_directory
        )

        output.mkdir(
            parents=True,
            exist_ok=True
        )

        files = {

            "stage2_1_signal_log_15y.csv":
                self.signals_dataframe(),

            "stage2_1_trade_log_15y.csv":
                self.trades_dataframe(),

            "stage2_1_holding_summary_15y.csv":
                self.holding_summary(),

            "stage2_1_stock_summary_15y.csv":
                self.stock_summary(),

            "stage2_1_setup_summary_15y.csv":
                self.setup_summary(),

            "stage2_1_regime_summary_15y.csv":
                self.regime_summary(),

            "stage2_1_signal_summary_15y.csv":
                self.signal_summary(),

            "stage2_1_equity_curve_15y.csv":
                self.equity_curve(),

        }

        print()
        print("=" * 110)
        print(
            "SAVING OUTPUTS"
        )
        print("=" * 110)

        for filename, df in files.items():

            path = (
                output /
                filename
            )

            df.to_csv(
                path,
                index=False
            )

            print(
                f"Saved: {path}"
            )


# ============================================================
# VALIDATION
# ============================================================

def validate(
    engine: OptimizedBacktest
) -> List[str]:

    errors = []

    signals = (
        engine.signals_dataframe()
    )

    trades = (
        engine.trades_dataframe()
    )

    # --------------------------------------------------------
    # Signal date window
    # --------------------------------------------------------

    if not signals.empty:

        dates = pd.to_datetime(
            signals["Signal Date"]
        )

        if dates.min() < engine.test_start:

            errors.append(
                "Signal exists before test start."
            )

        if dates.max() > engine.test_end:

            errors.append(
                "Signal exists after test end."
            )

    # --------------------------------------------------------
    # Trade checks
    # --------------------------------------------------------

    if not trades.empty:

        signal_dates = pd.to_datetime(
            trades["Signal Date"]
        )

        entry_dates = pd.to_datetime(
            trades["Entry Date"]
        )

        if (
            entry_dates <= signal_dates
        ).any():

            errors.append(
                "At least one trade entered "
                "on/before signal close."
            )

        entry = pd.to_numeric(
            trades["Entry Price"],
            errors="coerce"
        )

        stop = pd.to_numeric(
            trades["Stop Loss"],
            errors="coerce"
        )

        t1 = pd.to_numeric(
            trades["Target 1"],
            errors="coerce"
        )

        t2 = pd.to_numeric(
            trades["Target 2"],
            errors="coerce"
        )

        if (
            stop >= entry
        ).any():

            errors.append(
                "At least one trade has "
                "Stop >= actual Entry."
            )

        if (
            t1 <= entry
        ).any():

            errors.append(
                "At least one trade has "
                "Target 1 <= Entry."
            )

        if (
            t2 <= t1
        ).any():

            errors.append(
                "At least one trade has "
                "Target 2 <= Target 1."
            )

        rr1 = pd.to_numeric(
            trades["Planned R:R T1"],
            errors="coerce"
        )

        if (
            rr1 < engine.config.minimum_t1_rr
        ).any():

            errors.append(
                "Eligible trade has T1 R:R "
                "below minimum."
            )

        # ----------------------------------------------------
        # Check entry method
        # ----------------------------------------------------

        if (
            entry_dates <= signal_dates
        ).any():

            errors.append(
                "Look-ahead: entry date "
                "not strictly after signal date."
            )

    # --------------------------------------------------------
    # Trade count consistency
    # --------------------------------------------------------

    if not signals.empty:

        invalid = signals[
            (
                signals["Signal"]
                .isin(
                    [
                        "BUY",
                        "STRONG BUY",
                        "WATCH",
                        "WATCH - MARKET RISK",
                    ]
                )
                &
                (
                    signals["Setup"]
                    .isin(
                        [
                            "PULLBACK",
                            "BREAKOUT",
                        ]
                    )
                )
                &
                (
                    pd.to_numeric(
                        signals["R:R T1"],
                        errors="coerce"
                    )
                    >=
                    engine.config.minimum_t1_rr
                )
            )
        ]

        if len(trades) > len(invalid):

            errors.append(
                "More trades than potentially "
                "eligible signals."
            )

    return unique_list(
        errors
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    config = BacktestConfig(

        years=15,

        warmup_days=450,

        holding_periods=(
            10,
            20,
            30,
            45,
            63,
        ),

        primary_holding_period=63,

    )

    # ========================================================
    # UNIVERSE
    # ========================================================

    universe = [

        # IT
        "TCS.NS",
        "INFY.NS",
        "HCLTECH.NS",
        "WIPRO.NS",

        # Banking
        "ICICIBANK.NS",
        "HDFCBANK.NS",
        "SBIN.NS",
        "AXISBANK.NS",

        # Industrial / Defence
        "BEL.NS",
        "HAL.NS",
        "LT.NS",

        # Consumer
        "ITC.NS",
        "TITAN.NS",
        "HINDUNILVR.NS",

        # Auto
        "M&M.NS",
        "MARUTI.NS",

        # Current Tata symbols
        #
        # TMCV is expected to have insufficient history.
        # The engine will skip it cleanly.
        "TMPV.NS",
        "TMCV.NS",

        # Pharma
        "SUNPHARMA.NS",
        "CIPLA.NS",

    ]

    print()
    print("=" * 110)
    print(
        "STOCK ALERT ENGINE"
    )
    print(
        "STAGE 2.1 - OPTIMIZED 15-YEAR BACKTEST"
    )
    print("=" * 110)

    engine = OptimizedBacktest(
        config,
        universe
    )

    # --------------------------------------------------------
    # 1. Download
    # --------------------------------------------------------

    engine.load_data()

    # --------------------------------------------------------
    # 2. Calculate indicators ONCE
    # --------------------------------------------------------

    engine.precompute()

    # --------------------------------------------------------
    # 3. Generate point-in-time signals and trades
    # --------------------------------------------------------

    engine.generate_signals_and_trades()

    # --------------------------------------------------------
    # 4. Main summary
    # --------------------------------------------------------

    engine.print_summary()

    # --------------------------------------------------------
    # 5. Holding period
    # --------------------------------------------------------

    print()
    print("=" * 130)
    print(
        "PERFORMANCE BY HOLDING PERIOD"
    )
    print("=" * 130)

    holding = (
        engine.holding_summary()
    )

    if not holding.empty:

        print(
            holding[
                [
                    "Target",
                    "Holding Period",
                    "Trades",
                    "Win Rate %",
                    "Average Return %",
                    "Average R",
                    "Profit Factor",
                    "Expectancy R",
                    "Average Holding Days",
                    "Max Consecutive Losses",
                ]
            ]
            .to_string(
                index=False
            )
        )

    else:

        print(
            "No holding-period results."
        )

    # --------------------------------------------------------
    # 6. Stock summary
    # --------------------------------------------------------

    print()
    print("=" * 130)
    print(
        "PERFORMANCE BY STOCK"
    )
    print("=" * 130)

    stock = (
        engine.stock_summary()
    )

    if not stock.empty:

        print(
            stock[
                [
                    "Ticker",
                    "Trades",
                    "Win Rate %",
                    "Average Return %",
                    "Average R",
                    "Profit Factor",
                    "Expectancy R",
                    "Average Holding Days",
                    "Max Consecutive Losses",
                ]
            ]
            .to_string(
                index=False
            )
        )

    else:

        print(
            "No stock results."
        )

    # --------------------------------------------------------
    # 7. Setup summary
    # --------------------------------------------------------

    print()
    print("=" * 130)
    print(
        "PERFORMANCE BY SETUP"
    )
    print("=" * 130)

    setup = (
        engine.setup_summary()
    )

    if not setup.empty:

        print(
            setup[
                [
                    "Setup",
                    "Trades",
                    "Win Rate %",
                    "Average Return %",
                    "Average R",
                    "Profit Factor",
                    "Expectancy R",
                    "Average Holding Days",
                ]
            ]
            .to_string(
                index=False
            )
        )

    else:

        print(
            "No setup results."
        )

    # --------------------------------------------------------
    # 8. Market regime
    # --------------------------------------------------------

    print()
    print("=" * 130)
    print(
        "PERFORMANCE BY MARKET REGIME"
    )
    print("=" * 130)

    regime = (
        engine.regime_summary()
    )

    if not regime.empty:

        print(
            regime[
                [
                    "Market Regime",
                    "Trades",
                    "Win Rate %",
                    "Average Return %",
                    "Average R",
                    "Profit Factor",
                    "Expectancy R",
                    "Average Holding Days",
                ]
            ]
            .to_string(
                index=False
            )
        )

    else:

        print(
            "No regime results."
        )

    # --------------------------------------------------------
    # 9. Signal distribution
    # --------------------------------------------------------

    print()
    print("=" * 130)
    print(
        "SIGNAL DISTRIBUTION"
    )
    print("=" * 130)

    signal_summary = (
        engine.signal_summary()
    )

    if not signal_summary.empty:

        print(
            signal_summary.to_string(
                index=False
            )
        )

    else:

        print(
            "No signals."
        )

    # --------------------------------------------------------
    # 10. Validation
    # --------------------------------------------------------

    print()
    print("=" * 110)
    print(
        "VALIDATION"
    )
    print("=" * 110)

    validation_errors = (
        validate(
            engine
        )
    )

    if validation_errors:

        print(
            "VALIDATION FAILED"
        )

        for error in validation_errors:

            print(
                f"  ! {error}"
            )

    else:

        print(
            "All validation checks passed."
        )

    print("=" * 110)

    # --------------------------------------------------------
    # 11. Save
    # --------------------------------------------------------

    engine.save_outputs()

    print()
    print("=" * 110)
    print(
        "STAGE 2.1 COMPLETE"
    )
    print("=" * 110)
