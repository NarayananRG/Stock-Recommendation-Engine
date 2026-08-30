"""
Stock Alert Engine - Stage 2.2.1 reproducibility and research audit.

Stage 2.2.1 deliberately imports and reuses the frozen Stage 2.1 feature engine
and FrozenStrategy.  It changes portfolio selection, order handling, execution,
cash accounting, reporting, and validation; it does not change strategy rules.

This is research software, not investment advice.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import platform
import sys
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


SURVIVORSHIP_WARNING = (
    "This test uses the supplied/current ticker universe and is not a "
    "survivorship-bias-free historical index-constituent study."
)

OFFICIAL_TEST_START = "2011-08-30"
OFFICIAL_TEST_END = "2026-08-28"
STAGE221_PREFIX = "stage2_2_1"

DEFAULT_UNIVERSE = (
    "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS",
    "ICICIBANK.NS", "HDFCBANK.NS", "SBIN.NS", "AXISBANK.NS",
    "BEL.NS", "HAL.NS", "LT.NS",
    "ITC.NS", "TITAN.NS", "HINDUNILVR.NS",
    "M&M.NS", "MARUTI.NS", "TMPV.NS", "TMCV.NS",
    "SUNPHARMA.NS", "CIPLA.NS",
)

PRIMARY_SIGNALS = frozenset({"STRONG BUY", "BUY"})
RESEARCH_SIGNALS = frozenset(
    {"STRONG BUY", "BUY", "WATCH", "WATCH - MARKET RISK"}
)
VALID_SETUPS = frozenset({"PULLBACK", "BREAKOUT"})


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def normalize_date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_stage21_module(source: Path):
    """Load the frozen Stage 2.1 implementation without editing it."""
    source = source.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(
            f"Stage 2.1 source not found: {source}. "
            "Place both scripts together or pass --stage21-source."
        )
    spec = importlib.util.spec_from_file_location("stock_alert_stage21_frozen", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load Stage 2.1 source: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class Stage22Config:
    test_start: str = OFFICIAL_TEST_START
    test_end: str = OFFICIAL_TEST_END
    warmup_anchor_start: str = "2011-08-30"
    warmup_days: int = 450
    holding_periods: Tuple[int, ...] = (10, 20, 30, 45, 63)
    starting_equity: float = 100000.0
    risk_per_trade: float = 0.0075
    max_open_positions: int = 5
    max_position_pct: float = 0.25
    slippage_bps: float = 5.0
    transaction_cost_bps: float = 5.0
    annual_risk_free_rate: float = 0.06
    pullback_entry_window: int = 5
    breakout_gap_limit: float = 0.005
    parity_tolerance: float = 1e-4
    output_directory: Path = Path(".")
    cache_directory: Path = Path("stage2_2_data_cache")
    reference_signal_log: Optional[Path] = None
    candidate_source: str = "generated"
    data_mode: str = "FROZEN"
    frozen_data_directory: Path = Path("data/frozen")
    refresh_root_directory: Path = Path("data")
    data_manifest_path: Optional[Path] = None
    experiment_id: str = "PENDING"
    config_hash: str = ""
    data_manifest_hash: str = ""

    def __post_init__(self) -> None:
        self.output_directory = Path(self.output_directory)
        self.cache_directory = Path(self.cache_directory)
        if self.reference_signal_log is not None:
            self.reference_signal_log = Path(self.reference_signal_log)
        self.frozen_data_directory = Path(self.frozen_data_directory)
        self.refresh_root_directory = Path(self.refresh_root_directory)
        if self.data_manifest_path is not None:
            self.data_manifest_path = Path(self.data_manifest_path)
        if self.candidate_source not in {"generated", "reference"}:
            raise ValueError("candidate_source must be 'generated' or 'reference'")
        self.data_mode = self.data_mode.upper()
        if self.data_mode not in {"FROZEN", "REFRESH"}:
            raise ValueError("data_mode must be FROZEN or REFRESH")
        if normalize_date(self.test_end) < normalize_date(self.test_start):
            raise ValueError("test_end must be on or after test_start")
        if self.starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        if not 0 < self.risk_per_trade <= 1:
            raise ValueError("risk_per_trade must be in (0, 1]")
        if self.max_open_positions <= 0:
            raise ValueError("max_open_positions must be positive")
        if not 0 < self.max_position_pct <= 1:
            raise ValueError("max_position_pct must be in (0, 1]")


@dataclass
class PendingOrder:
    order_id: int
    variant: str
    ticker: str
    signal_date: pd.Timestamp
    signal: str
    setup: str
    created_date: pd.Timestamp
    expiry_date: pd.Timestamp
    valid_dates: Tuple[pd.Timestamp, ...]
    entry_low: float
    entry_high: float
    stop: float
    target1: float
    target2: float
    actionability: float
    technical_score: float
    rr_t1: float
    rs60: float
    market_regime: str
    trade_quality: str = ""
    rank: Optional[int] = None


@dataclass
class FillCandidate:
    order: PendingOrder
    fill_date: pd.Timestamp
    nominal_entry: float
    entry_method: str
    intraday_limit: bool
    gap_below_zone: bool = False


@dataclass
class Position:
    variant: str
    ticker: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    signal: str
    setup: str
    market_regime: str
    entry_method: str
    nominal_entry: float
    executed_entry: float
    stop: float
    target: float
    target_name: str
    quantity: int
    initial_risk_per_share: float
    risk_budget: float
    position_value: float
    entry_transaction_cost: float
    equity_at_entry: float
    technical_score: float
    actionability: float
    planned_rr_t1: float
    rs60: float
    buy_limit: Optional[float] = None
    bars_held: int = 0
    ambiguity_invoked: bool = False
    capital_constraint_reason: str = "NONE"


class ExecutionModel:
    """One consistent slippage and transaction-cost model."""

    def __init__(self, config: Stage22Config):
        self.config = config

    @property
    def slippage_fraction(self) -> float:
        return self.config.slippage_bps / 10000.0

    @property
    def transaction_fraction(self) -> float:
        return self.config.transaction_cost_bps / 10000.0

    def executed_entry(
        self,
        nominal_entry: float,
        entry_method: str = "NEXT_OPEN",
        buy_limit: Optional[float] = None,
    ) -> float:
        worsened = nominal_entry * (1.0 + self.slippage_fraction)
        if entry_method.startswith("PULLBACK"):
            if buy_limit is None:
                raise ValueError("Pullback limit execution requires buy_limit")
            # A buy-limit order cannot execute above its limit.  A gap/open fill
            # may be conservatively degraded only up to that ceiling; an
            # intraday touch at the limit therefore executes exactly at limit.
            return min(worsened, buy_limit)
        return worsened

    def executed_exit(self, nominal_exit: float) -> float:
        return nominal_exit * (1.0 - self.slippage_fraction)

    def transaction_cost(self, executed_price: float, quantity: int) -> float:
        return executed_price * quantity * self.transaction_fraction

    def assess_fill(
        self,
        order: PendingOrder,
        row: pd.Series,
        current_date: pd.Timestamp,
    ) -> Optional[FillCandidate]:
        if current_date not in order.valid_dates:
            return None

        open_price = float(row["Open"])
        low_price = float(row["Low"])

        if order.setup == "BREAKOUT":
            if current_date != order.valid_dates[0]:
                return None
            max_entry = order.entry_high * (1.0 + self.config.breakout_gap_limit)
            if open_price <= max_entry:
                return FillCandidate(
                    order=order,
                    fill_date=current_date,
                    nominal_entry=open_price,
                    entry_method="NEXT_OPEN",
                    intraday_limit=False,
                )
            return None

        if order.setup == "PULLBACK":
            if open_price <= order.entry_high:
                return FillCandidate(
                    order=order,
                    fill_date=current_date,
                    nominal_entry=open_price,
                    entry_method=(
                        "PULLBACK_GAP_OPEN"
                        if open_price < order.entry_low * 0.98
                        else "PULLBACK_OPEN"
                    ),
                    intraday_limit=False,
                    gap_below_zone=open_price < order.entry_low * 0.98,
                )
            if low_price <= order.entry_high:
                return FillCandidate(
                    order=order,
                    fill_date=current_date,
                    nominal_entry=order.entry_high,
                    entry_method="PULLBACK_LIMIT",
                    intraday_limit=True,
                )
        return None

    @staticmethod
    def open_gap_exit(
        position: Position,
        row: pd.Series,
    ) -> Optional[Tuple[float, str]]:
        open_price = float(row["Open"])
        if open_price <= position.stop:
            return open_price, "STOP_GAP"
        if open_price >= position.target:
            return open_price, "TARGET_GAP"
        return None

    @staticmethod
    def ordinary_bar_exit(
        position: Position,
        row: pd.Series,
    ) -> Optional[Tuple[float, str]]:
        low_price = float(row["Low"])
        high_price = float(row["High"])
        stop_hit = low_price <= position.stop
        target_hit = high_price >= position.target
        if stop_hit and target_hit:
            return position.stop, "STOP_COLLISION"
        if stop_hit:
            return position.stop, "STOP"
        if target_hit:
            return position.target, "TARGET"
        return None


class CandidateSignalEngine:
    """Generate signals through the unmodified Stage 2.1 strategy core."""

    def __init__(
        self,
        stage21: Any,
        config: Stage22Config,
        tickers: Sequence[str],
    ) -> None:
        self.stage21 = stage21
        self.config = config
        self.tickers = list(tickers)
        strategy_config = stage21.BacktestConfig(
            years=15,
            warmup_days=config.warmup_days,
            holding_periods=config.holding_periods,
            primary_holding_period=max(config.holding_periods),
            slippage_bps=config.slippage_bps,
            transaction_cost_bps=config.transaction_cost_bps,
            starting_equity=config.starting_equity,
            risk_per_trade=config.risk_per_trade,
            output_directory=str(config.output_directory),
        )
        self.strategy_config = strategy_config
        self.engine = stage21.OptimizedBacktest(strategy_config, self.tickers)
        self.engine.test_start = normalize_date(config.test_start)
        self.engine.test_end = normalize_date(config.test_end)
        self.engine.loader.test_start = self.engine.test_start
        self.engine.loader.test_end = self.engine.test_end
        warmup_anchor = min(
            self.engine.test_start,
            normalize_date(config.warmup_anchor_start),
        )
        self.engine.loader.warmup_start = (
            warmup_anchor - pd.Timedelta(days=config.warmup_days)
        )
        self.data_availability: List[Dict[str, Any]] = []
        self.loaded_file_hashes: Dict[str, str] = {}

    @staticmethod
    def _cache_name(ticker: str) -> str:
        return ticker.replace("^", "INDEX_").replace("&", "AND") + ".csv"

    def _read_cache(self, ticker: str) -> pd.DataFrame:
        path = self.config.cache_directory / self._cache_name(ticker)
        if not path.exists():
            if self.config.data_mode == "FROZEN":
                raise FileNotFoundError(
                    f"FROZEN DATA MISSING: {ticker} requires {path}"
                )
            return pd.DataFrame()
        frame = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
        frame = self.stage21.normalize_index(frame)
        if frame.empty:
            return pd.DataFrame()
        self.loaded_file_hashes[ticker] = sha256_file(path)
        return frame

    def _write_cache(self, ticker: str, frame: pd.DataFrame) -> None:
        if self.config.data_mode == "FROZEN":
            raise RuntimeError("FROZEN mode cannot write or overwrite market data")
        self.config.cache_directory.mkdir(parents=True, exist_ok=True)
        path = self.config.cache_directory / self._cache_name(ticker)
        cached = frame.copy()
        cached.index.name = "Date"
        cached.to_csv(path)

    def load_data(self) -> None:
        if self.config.data_mode == "REFRESH":
            # yfinance caches are isolated with the refresh snapshot.
            yfinance_cache = self.config.cache_directory / "yfinance_internal"
            yfinance_cache.mkdir(parents=True, exist_ok=True)
            if hasattr(self.stage21.yf, "set_tz_cache_location"):
                self.stage21.yf.set_tz_cache_location(str(yfinance_cache))
        print("\n" + "=" * 110)
        print("STAGE 2.2.1 - REPRODUCIBLE HISTORICAL WINDOW")
        print("=" * 110)
        print(f"Data mode    : {self.config.data_mode}")
        print(f"Data path    : {self.config.cache_directory.resolve()}")
        print(f"Test start   : {self.engine.test_start.date()}")
        print(f"Test end     : {self.engine.test_end.date()}")
        print(f"Warmup start : {self.engine.loader.warmup_start.date()}")
        print(SURVIVORSHIP_WARNING)
        print("=" * 110)

        for ticker in ["^NSEI", *self.tickers]:
            source = self.config.data_mode
            frame = self._read_cache(ticker)
            if frame.empty and self.config.data_mode == "REFRESH":
                source = "YFINANCE_REFRESH"
                print(f"Downloading {ticker}...")
                frame = self.engine.loader.download(ticker)
                if not frame.empty:
                    self._write_cache(ticker, frame)
            if frame.empty:
                if self.config.data_mode == "FROZEN":
                    raise RuntimeError(f"Frozen file for {ticker} is empty")
                self.data_availability.append(
                    {
                        "Ticker": ticker,
                        "Status": "SKIPPED",
                        "Reason": "NO_DATA_OR_DOWNLOAD_FAILED",
                        "Rows": 0,
                        "First Date": pd.NaT,
                        "Last Date": pd.NaT,
                        "Source": source,
                    }
                )
                continue
            frame = frame.loc[
                (frame.index >= self.engine.loader.warmup_start)
                & (frame.index <= self.engine.test_end)
            ].copy()
            self.engine.raw_data[ticker] = frame
            self.data_availability.append(
                {
                    "Ticker": ticker,
                    "Status": "LOADED",
                    "Reason": "",
                    "Rows": len(frame),
                    "First Date": frame.index.min(),
                    "Last Date": frame.index.max(),
                    "Source": source,
                }
            )
            print(f"  {ticker}: {len(frame):,} candles ({source})")

        if "^NSEI" not in self.engine.raw_data:
            raise RuntimeError("NIFTY data is required for historical regimes")

    def precompute(self) -> None:
        self.engine.precompute()
        prepared = set(self.engine.features)
        for row in self.data_availability:
            ticker = row["Ticker"]
            if ticker == "^NSEI" or row["Status"] != "LOADED":
                continue
            if ticker not in prepared:
                row["Status"] = "SKIPPED"
                row["Reason"] = "INSUFFICIENT_HISTORY_OR_FEATURE_ERROR"

    def generate(self) -> pd.DataFrame:
        strategy = self.stage21.FrozenStrategy(
            self.engine.config,
            self.engine.market_history,
        )
        records: List[Dict[str, Any]] = []
        print("\n" + "=" * 110)
        print("GENERATING FROZEN CANDIDATE SIGNALS")
        print("=" * 110)
        for ticker in self.tickers:
            stock = self.engine.features.get(ticker)
            if stock is None or stock.empty:
                continue
            mask = (
                (stock.index >= self.engine.test_start)
                & (stock.index <= self.engine.test_end)
            )
            positions = np.flatnonzero(mask)
            before = len(records)
            for position in positions:
                signal = strategy.signal_at(ticker, stock, int(position))
                if signal is not None:
                    records.append(signal)
            print(f"  {ticker}: {len(records) - before:,} signals")
        result = pd.DataFrame(records)
        if not result.empty:
            result["Signal Date"] = pd.to_datetime(result["Signal Date"]).dt.normalize()
            result = result.sort_values(["Signal Date", "Ticker"]).reset_index(drop=True)
        return result


def compare_signal_parity(
    generated: pd.DataFrame,
    reference_path: Optional[Path],
    tickers: Sequence[str],
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    tolerance: float,
) -> Tuple[bool, pd.DataFrame, Dict[str, Any]]:
    if reference_path is None or not Path(reference_path).exists():
        details = {
            "Status": "FAIL",
            "Reason": "REFERENCE_SIGNAL_LOG_MISSING",
            "Generated Rows": len(generated),
            "Reference Rows": 0,
            "Mismatched Rows": len(generated),
        }
        return False, pd.DataFrame(), details

    reference = pd.read_csv(reference_path)
    reference["Signal Date"] = pd.to_datetime(reference["Signal Date"]).dt.normalize()
    reference = reference[
        reference["Ticker"].isin(tickers)
        & (reference["Signal Date"] >= test_start)
        & (reference["Signal Date"] <= test_end)
    ].copy()

    keys = ["Ticker", "Signal Date"]
    string_columns = ["Signal", "Setup", "Market Regime"]
    numeric_columns = [
        "Technical Score", "Actionability Score", "Entry Low", "Entry High",
        "Stop Loss", "Target 1", "Target 2", "R:R T1",
    ]
    wanted = keys + string_columns + numeric_columns
    left = generated[[c for c in wanted if c in generated.columns]].copy()
    right = reference[[c for c in wanted if c in reference.columns]].copy()
    merged = left.merge(right, on=keys, how="outer", suffixes=("_New", "_Ref"), indicator=True)
    mismatch_reasons: List[str] = []
    mismatch_mask = merged["_merge"] != "both"

    for column in string_columns:
        new_col, ref_col = f"{column}_New", f"{column}_Ref"
        unequal = (
            merged[new_col].fillna("<NA>").astype(str)
            != merged[ref_col].fillna("<NA>").astype(str)
        )
        mismatch_mask |= unequal

    for column in numeric_columns:
        new_col, ref_col = f"{column}_New", f"{column}_Ref"
        new_values = pd.to_numeric(merged[new_col], errors="coerce")
        ref_values = pd.to_numeric(merged[ref_col], errors="coerce")
        both_nan = new_values.isna() & ref_values.isna()
        unequal = (~both_nan) & (~np.isclose(new_values, ref_values, atol=tolerance, rtol=0, equal_nan=True))
        mismatch_mask |= unequal

    differences = merged.loc[mismatch_mask].copy()
    passed = differences.empty and len(left) == len(right)
    details = {
        "Status": "PASS" if passed else "FAIL",
        "Reason": "" if passed else "CANDIDATE_SIGNAL_DIFFERENCE",
        "Generated Rows": len(left),
        "Reference Rows": len(right),
        "Mismatched Rows": len(differences),
    }
    return passed, differences, details


def load_reference_candidates(
    reference_path: Path,
    tickers: Sequence[str],
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
) -> pd.DataFrame:
    reference = pd.read_csv(reference_path)
    reference["Signal Date"] = pd.to_datetime(reference["Signal Date"]).dt.normalize()
    reference = reference[
        reference["Ticker"].isin(tickers)
        & (reference["Signal Date"] >= test_start)
        & (reference["Signal Date"] <= test_end)
    ].copy()
    return reference.sort_values(["Signal Date", "Ticker"]).reset_index(drop=True)


def json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value.resolve())
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(value), indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def build_data_manifest(
    data_directory: Path,
    tickers: Sequence[str],
    config: Stage22Config,
    stage21: Any,
) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    for ticker in ["^NSEI", *tickers]:
        filename = CandidateSignalEngine._cache_name(ticker)
        path = data_directory / filename
        if not path.exists():
            raise FileNotFoundError(f"Cannot freeze missing file: {path}")
        frame = pd.read_csv(path)
        if "Date" not in frame.columns:
            raise ValueError(f"Frozen file lacks Date column: {path}")
        dates = pd.to_datetime(frame["Date"], errors="coerce")
        files.append(
            {
                "ticker": ticker,
                "filename": filename,
                "rows": int(len(frame)),
                "first_date": dates.min().date().isoformat() if dates.notna().any() else None,
                "last_date": dates.max().date().isoformat() if dates.notna().any() else None,
                "sha256": sha256_file(path),
                "columns": list(frame.columns),
                "missing_value_counts": {
                    column: int(value) for column, value in frame.isna().sum().items()
                },
                "duplicate_date_count": int(dates.duplicated(keep=False).sum()),
                "source_name": "Yahoo Finance frozen from completed Stage 2.2 cache",
                "auto_adjust": True,
                "repair": True,
            }
        )
    manifest: Dict[str, Any] = {
        "schema_version": "1.0",
        "stage": "2.2.1",
        "data_mode": "FROZEN",
        "test_start": OFFICIAL_TEST_START,
        "test_end": OFFICIAL_TEST_END,
        "warmup_start": (
            normalize_date(OFFICIAL_TEST_START) - pd.Timedelta(days=config.warmup_days)
        ).date().isoformat(),
        "generated_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "pandas_version": pd.__version__,
        "numpy_version": np.__version__,
        "yfinance_version": getattr(stage21.yf, "__version__", "UNKNOWN"),
        "files": files,
    }
    manifest["manifest_sha256"] = canonical_json_hash(manifest)
    return manifest


def verify_data_manifest(
    data_directory: Path,
    manifest: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    expected_manifest_hash = manifest.get("manifest_sha256", "")
    unhashed = dict(manifest)
    unhashed.pop("manifest_sha256", None)
    actual_manifest_hash = canonical_json_hash(unhashed)
    if actual_manifest_hash != expected_manifest_hash:
        errors.append("Manifest canonical hash mismatch")
    for item in manifest.get("files", []):
        path = data_directory / item["filename"]
        if not path.exists():
            errors.append(f"Missing frozen file: {item['filename']}")
            continue
        actual_hash = sha256_file(path)
        if actual_hash != item.get("sha256"):
            errors.append(f"SHA-256 mismatch: {item['filename']}")
    return not errors, errors


def check_reference_integrity(
    reference_path: Path,
) -> Tuple[bool, Dict[str, Any]]:
    required = {
        "Ticker", "Signal Date", "Signal", "Setup", "Technical Score",
        "Actionability Score", "Market Regime", "Entry Low", "Entry High",
        "Stop Loss", "Target 1", "Target 2", "R:R T1", "R:R T2",
    }
    before_hash = sha256_file(reference_path)
    frame = pd.read_csv(reference_path)
    after_hash = sha256_file(reference_path)
    missing = sorted(required.difference(frame.columns))
    duplicate_keys = int(frame.duplicated(["Ticker", "Signal Date"], keep=False).sum())
    passed = (
        before_hash == after_hash
        and not missing
        and not frame.empty
        and duplicate_keys == 0
    )
    return passed, {
        "file_sha256": before_hash,
        "rows": int(len(frame)),
        "missing_required_columns": missing,
        "duplicate_ticker_date_rows": duplicate_keys,
        "file_unchanged_during_load": before_hash == after_hash,
    }


def analyze_signal_parity(
    generated: pd.DataFrame,
    reference_path: Path,
    tickers: Sequence[str],
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    tolerance: float,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    reference = load_reference_candidates(
        reference_path, tickers, test_start, test_end
    )
    keys = ["Ticker", "Signal Date"]
    string_columns = ["Signal", "Setup", "Market Regime"]
    numeric_columns = [
        "Technical Score", "Actionability Score", "Entry Low", "Entry High",
        "Stop Loss", "Target 1", "Target 2", "R:R T1", "R:R T2",
    ]
    left = generated[keys + string_columns + numeric_columns].copy()
    right = reference[keys + string_columns + numeric_columns].copy()
    left["Signal Date"] = pd.to_datetime(left["Signal Date"]).dt.normalize()
    right["Signal Date"] = pd.to_datetime(right["Signal Date"]).dt.normalize()
    merged = left.merge(
        right, on=keys, how="outer", suffixes=("_Generated", "_Reference"), indicator=True
    )

    report_rows: List[Dict[str, Any]] = []
    exact_matches = 0
    float_only_rows = 0
    signal_label_mismatches = 0
    buy_membership_changes = 0
    max_numeric_differences = {column: 0.0 for column in numeric_columns}
    buy_states = {"BUY", "STRONG BUY"}

    for row in merged.to_dict("records"):
        classifications: List[str] = []
        exact = row["_merge"] == "both"
        significant_numeric = False
        any_numeric_difference = False
        if row["_merge"] != "both":
            classifications.append("MISSING_ROW")

        if row["_merge"] == "both":
            generated_signal = str(row["Signal_Generated"])
            reference_signal = str(row["Signal_Reference"])
            if generated_signal != reference_signal:
                classifications.append("SIGNAL_LABEL_DIFFERENCE")
                signal_label_mismatches += 1
                exact = False
            if (generated_signal in buy_states) != (reference_signal in buy_states):
                classifications.append("BUY_MEMBERSHIP_DIFFERENCE")
                buy_membership_changes += 1
            if str(row["Setup_Generated"]) != str(row["Setup_Reference"]):
                classifications.append("SETUP_DIFFERENCE")
                exact = False
            if str(row["Market Regime_Generated"]) != str(row["Market Regime_Reference"]):
                classifications.append("MARKET_REGIME_DIFFERENCE")
                exact = False

            for column in numeric_columns:
                new_value = safe_float(row.get(f"{column}_Generated"))
                ref_value = safe_float(row.get(f"{column}_Reference"))
                if new_value is None and ref_value is None:
                    difference = 0.0
                elif new_value is None or ref_value is None:
                    difference = np.inf
                else:
                    difference = abs(new_value - ref_value)
                if np.isfinite(difference):
                    max_numeric_differences[column] = max(
                        max_numeric_differences[column], difference
                    )
                if difference > 0:
                    any_numeric_difference = True
                    exact = False
                if difference > tolerance:
                    significant_numeric = True
                    if column in {"Technical Score", "Actionability Score"}:
                        classifications.append("SCORE_DIFFERENCE")
                    elif column in {"Entry Low", "Entry High"}:
                        classifications.append("ENTRY_DIFFERENCE")
                    elif column == "Stop Loss":
                        classifications.append("STOP_DIFFERENCE")
                    elif column in {"Target 1", "Target 2", "R:R T1", "R:R T2"}:
                        classifications.append("TARGET_DIFFERENCE")

        if exact:
            exact_matches += 1
            continue
        if (
            row["_merge"] == "both"
            and any_numeric_difference
            and not significant_numeric
            and not classifications
        ):
            classifications.append("FLOAT_ONLY")
            float_only_rows += 1
        classifications = list(dict.fromkeys(classifications))
        output = {
            "Ticker": row.get("Ticker"),
            "Signal Date": row.get("Signal Date"),
            "Classification": "|".join(classifications) or "UNCLASSIFIED_DIFFERENCE",
            "Material To Portfolio Membership": "BUY_MEMBERSHIP_DIFFERENCE" in classifications,
            "Generated Signal": row.get("Signal_Generated"),
            "Reference Signal": row.get("Signal_Reference"),
            "Generated Setup": row.get("Setup_Generated"),
            "Reference Setup": row.get("Setup_Reference"),
            "Generated Market Regime": row.get("Market Regime_Generated"),
            "Reference Market Regime": row.get("Market Regime_Reference"),
        }
        for column in numeric_columns:
            new_value = row.get(f"{column}_Generated")
            ref_value = row.get(f"{column}_Reference")
            output[f"Generated {column}"] = new_value
            output[f"Reference {column}"] = ref_value
            new_number = safe_float(new_value)
            ref_number = safe_float(ref_value)
            output[f"Abs Diff {column}"] = (
                abs(new_number - ref_number)
                if new_number is not None and ref_number is not None
                else np.nan
            )
        report_rows.append(output)

    missing_rows = int((merged["_merge"] != "both").sum())
    severity = "FAIL" if missing_rows else "WARN" if report_rows else "PASS"
    summary = {
        "severity": severity,
        "generated_rows": int(len(left)),
        "reference_rows": int(len(right)),
        "rows_compared": int((merged["_merge"] == "both").sum()),
        "exact_matches": int(exact_matches),
        "rows_with_any_difference": int(len(report_rows)),
        "rows_with_float_only_difference": int(float_only_rows),
        "signal_label_mismatches": int(signal_label_mismatches),
        "buy_nonbuy_membership_changes": int(buy_membership_changes),
        "missing_or_extra_rows": missing_rows,
        "maximum_numeric_difference": max_numeric_differences,
        "tolerance": tolerance,
    }
    return pd.DataFrame(report_rows), summary, severity


class PortfolioBacktester:
    """Chronological FLAT -> PENDING_ORDER -> OPEN_POSITION simulator."""

    def __init__(
        self,
        config: Stage22Config,
        features: Dict[str, pd.DataFrame],
        candidate_signals: pd.DataFrame,
        variant: str,
        target_column: str,
        holding_period: int,
    ) -> None:
        self.config = config
        self.features = features
        self.variant = variant
        self.target_column = target_column
        self.target_name = "T1" if target_column == "Target 1" else "T2"
        self.holding_period = holding_period
        self.execution = ExecutionModel(config)
        self.cash = float(config.starting_equity)
        self.pending: Dict[str, PendingOrder] = {}
        self.positions: Dict[str, Position] = {}
        self.last_close: Dict[str, float] = {}
        self.order_rows: List[Dict[str, Any]] = []
        self.trade_rows: List[Dict[str, Any]] = []
        self.equity_rows: List[Dict[str, Any]] = []
        self.runtime_errors: List[str] = []
        self.order_counter = 0
        self.max_concurrent_positions = 0

        signals = candidate_signals.copy()
        if not signals.empty:
            signals["Signal Date"] = pd.to_datetime(signals["Signal Date"]).dt.normalize()
            signals = signals[signals["Signal"].isin(PRIMARY_SIGNALS)].copy()
        self.signals_by_date: Dict[pd.Timestamp, List[Dict[str, Any]]] = {
            date: group.to_dict("records")
            for date, group in signals.groupby("Signal Date", sort=True)
        }

        all_dates: set[pd.Timestamp] = set()
        self.ticker_dates: Dict[str, Tuple[pd.Timestamp, ...]] = {}
        self.last_date: Dict[str, pd.Timestamp] = {}
        test_start = normalize_date(config.test_start)
        test_end = normalize_date(config.test_end)
        for ticker, frame in features.items():
            dates = tuple(
                pd.Timestamp(value).normalize()
                for value in frame.index[(frame.index >= test_start) & (frame.index <= test_end)]
            )
            if dates:
                self.ticker_dates[ticker] = dates
                self.last_date[ticker] = dates[-1]
                all_dates.update(dates)
        self.calendar = tuple(sorted(all_dates))

    def _row(self, ticker: str, current_date: pd.Timestamp) -> Optional[pd.Series]:
        frame = self.features.get(ticker)
        if frame is None or current_date not in frame.index:
            return None
        row = frame.loc[current_date]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        return row

    def _equity_at(self, current_date: pd.Timestamp, price_field: str) -> float:
        market_value = 0.0
        for ticker, position in self.positions.items():
            row = self._row(ticker, current_date)
            if row is not None:
                price = safe_float(row.get(price_field))
            else:
                price = self.last_close.get(ticker)
            if price is None:
                price = position.nominal_entry
            market_value += position.quantity * price
        return self.cash + market_value

    @staticmethod
    def _ranking_key(candidate: FillCandidate) -> Tuple[Any, ...]:
        order = candidate.order
        return (
            0 if order.signal == "STRONG BUY" else 1,
            -order.actionability,
            -order.technical_score,
            -order.rr_t1,
            -order.rs60,
            order.ticker,
        )

    @staticmethod
    def _signal_values(signal: Dict[str, Any]) -> Optional[Dict[str, float]]:
        mapping = {
            "entry_low": safe_float(signal.get("Entry Low")),
            "entry_high": safe_float(signal.get("Entry High")),
            "stop": safe_float(signal.get("Stop Loss")),
            "target1": safe_float(signal.get("Target 1")),
            "target2": safe_float(signal.get("Target 2")),
            "actionability": safe_float(signal.get("Actionability Score")),
            "technical": safe_float(signal.get("Technical Score")),
            "rr_t1": safe_float(signal.get("R:R T1")),
            "rs60": safe_float(signal.get("RS 60D")),
        }
        if any(value is None for value in mapping.values()):
            return None
        return {key: float(value) for key, value in mapping.items() if value is not None}

    def _future_valid_dates(
        self,
        ticker: str,
        signal_date: pd.Timestamp,
        setup: str,
    ) -> Tuple[pd.Timestamp, ...]:
        future = tuple(date for date in self.ticker_dates.get(ticker, ()) if date > signal_date)
        count = 1 if setup == "BREAKOUT" else self.config.pullback_entry_window
        return future[:count]

    def _order_row(
        self,
        order: PendingOrder,
        status: str,
        status_date: pd.Timestamp,
        reason: str = "",
        fill: Optional[FillCandidate] = None,
        rank: Optional[int] = None,
    ) -> Dict[str, Any]:
        return {
            "Variant": self.variant,
            "Order ID": order.order_id,
            "Ticker": order.ticker,
            "Signal Date": order.signal_date,
            "Signal": order.signal,
            "Setup": order.setup,
            "Market Regime": order.market_regime,
            "Order Created Date": order.created_date,
            "Order Expiry Date": order.expiry_date,
            "Planned Entry Low": order.entry_low,
            "Planned Entry High": order.entry_high,
            "Planned Stop": order.stop,
            "T1": order.target1,
            "T2": order.target2,
            "Actionability": order.actionability,
            "Technical Score": order.technical_score,
            "R:R": order.rr_t1,
            "RS 60D": order.rs60,
            "Rank": rank,
            "Status": status,
            "Status Date": status_date,
            "Reason": reason,
            "Eligible Fill Date": fill.fill_date if fill else pd.NaT,
            "Nominal Fill": fill.nominal_entry if fill else np.nan,
            "Entry Method": fill.entry_method if fill else "",
            "Trading Sessions to Fill": (
                order.valid_dates.index(fill.fill_date) + 1
                if fill is not None and fill.fill_date in order.valid_dates
                else np.nan
            ),
            "Gap Below Pullback Zone": bool(fill.gap_below_zone) if fill else False,
        }

    def _ignored_order_row(
        self,
        signal: Dict[str, Any],
        current_date: pd.Timestamp,
        status: str,
        reason: str,
    ) -> Dict[str, Any]:
        self.order_counter += 1
        values = self._signal_values(signal) or {}
        dummy = PendingOrder(
            order_id=self.order_counter,
            variant=self.variant,
            ticker=str(signal.get("Ticker", "")),
            signal_date=current_date,
            signal=str(signal.get("Signal", "")),
            setup=str(signal.get("Setup", "")),
            created_date=current_date,
            expiry_date=pd.NaT,
            valid_dates=(),
            entry_low=values.get("entry_low", np.nan),
            entry_high=values.get("entry_high", np.nan),
            stop=values.get("stop", np.nan),
            target1=values.get("target1", np.nan),
            target2=values.get("target2", np.nan),
            actionability=values.get("actionability", np.nan),
            technical_score=values.get("technical", np.nan),
            rr_t1=values.get("rr_t1", np.nan),
            rs60=values.get("rs60", np.nan),
            market_regime=str(signal.get("Market Regime", "")),
            trade_quality=str(signal.get("Trade Quality", "")),
        )
        return self._order_row(dummy, status, current_date, reason=reason)

    def _create_orders_at_close(self, current_date: pd.Timestamp) -> None:
        for signal in self.signals_by_date.get(current_date, []):
            ticker = str(signal["Ticker"])
            if ticker in self.positions:
                self.order_rows.append(
                    self._ignored_order_row(
                        signal, current_date, "IGNORED_ALREADY_OPEN", "TICKER_ALREADY_OPEN"
                    )
                )
                continue
            if ticker in self.pending:
                self.order_rows.append(
                    self._ignored_order_row(
                        signal, current_date, "IGNORED_ALREADY_PENDING", "TICKER_ALREADY_PENDING"
                    )
                )
                continue

            setup = str(signal.get("Setup", ""))
            values = self._signal_values(signal)
            valid_dates = self._future_valid_dates(ticker, current_date, setup)
            invalid_reason = ""
            if setup not in VALID_SETUPS:
                invalid_reason = "INVALID_SETUP"
            elif values is None:
                invalid_reason = "MISSING_TRADE_LEVEL_OR_SCORE"
            elif not valid_dates:
                invalid_reason = "NO_FUTURE_SESSION"
            elif not (
                values["stop"] < values["entry_high"]
                and values["target1"] > values["entry_low"]
                and values["target2"] > values["target1"]
            ):
                invalid_reason = "INVALID_PRICE_LEVELS"

            if invalid_reason:
                self.order_rows.append(
                    self._ignored_order_row(
                        signal, current_date, "INVALID_DATA", invalid_reason
                    )
                )
                continue

            assert values is not None
            self.order_counter += 1
            order = PendingOrder(
                order_id=self.order_counter,
                variant=self.variant,
                ticker=ticker,
                signal_date=current_date,
                signal=str(signal["Signal"]),
                setup=setup,
                created_date=current_date,
                expiry_date=valid_dates[-1],
                valid_dates=valid_dates,
                entry_low=values["entry_low"],
                entry_high=values["entry_high"],
                stop=values["stop"],
                target1=values["target1"],
                target2=values["target2"],
                actionability=values["actionability"],
                technical_score=values["technical"],
                rr_t1=values["rr_t1"],
                rs60=values["rs60"],
                market_regime=str(signal.get("Market Regime", "")),
                trade_quality=str(signal.get("Trade Quality", "")),
            )
            self.pending[ticker] = order

    def _position_size(
        self,
        fill: FillCandidate,
        stop: float,
        current_date: pd.Timestamp,
    ) -> Dict[str, Any]:
        executed_entry = self.execution.executed_entry(
            fill.nominal_entry,
            fill.entry_method,
            fill.order.entry_high if fill.order.setup == "PULLBACK" else None,
        )
        risk_per_share = executed_entry - stop
        equity = self._equity_at(current_date, "Open")
        risk_budget = equity * self.config.risk_per_trade
        if risk_per_share <= 0:
            return {
                "quantity": 0,
                "status": "INVALID_RISK",
                "reason": "STOP_NOT_BELOW_EXECUTED_ENTRY",
                "executed_entry": executed_entry,
                "risk_per_share": risk_per_share,
                "risk_budget": risk_budget,
                "equity": equity,
            }

        risk_quantity = math.floor(risk_budget / risk_per_share)
        position_quantity = math.floor(
            (equity * self.config.max_position_pct) / executed_entry
        )
        all_in_unit_cost = executed_entry * (1.0 + self.execution.transaction_fraction)
        cash_quantity = math.floor(max(self.cash, 0.0) / all_in_unit_cost)
        quantity = min(risk_quantity, position_quantity, cash_quantity)

        binding: List[str] = []
        if position_quantity < risk_quantity:
            binding.append("MAX_POSITION_PCT")
        if cash_quantity < min(risk_quantity, position_quantity):
            binding.append("AVAILABLE_CASH")
        if quantity <= 0:
            if cash_quantity <= 0:
                status, reason = "REJECTED_CASH", "INSUFFICIENT_CASH_FOR_ONE_SHARE"
            elif position_quantity <= 0:
                status, reason = (
                    "REJECTED_POSITION_LIMIT",
                    "MAX_POSITION_PCT_TOO_SMALL_FOR_ONE_SHARE",
                )
            else:
                status, reason = "INVALID_RISK", "RISK_BUDGET_TOO_SMALL_FOR_ONE_SHARE"
        else:
            status, reason = "FILLED", "+".join(binding) if binding else "NONE"
        return {
            "quantity": int(quantity),
            "status": status,
            "reason": reason,
            "executed_entry": executed_entry,
            "risk_per_share": risk_per_share,
            "risk_budget": risk_budget,
            "equity": equity,
        }

    def _open_position(
        self,
        fill: FillCandidate,
        sizing: Dict[str, Any],
    ) -> Position:
        order = fill.order
        quantity = int(sizing["quantity"])
        executed_entry = float(sizing["executed_entry"])
        position_value = executed_entry * quantity
        entry_cost = self.execution.transaction_cost(executed_entry, quantity)
        total_debit = position_value + entry_cost
        self.cash -= total_debit
        if self.cash < -1e-7:
            self.runtime_errors.append(
                f"{self.variant}: cash negative after {order.ticker} entry on {fill.fill_date}"
            )
        target = order.target1 if self.target_name == "T1" else order.target2
        position = Position(
            variant=self.variant,
            ticker=order.ticker,
            signal_date=order.signal_date,
            entry_date=fill.fill_date,
            signal=order.signal,
            setup=order.setup,
            market_regime=order.market_regime,
            entry_method=fill.entry_method,
            nominal_entry=fill.nominal_entry,
            executed_entry=executed_entry,
            stop=order.stop,
            target=target,
            target_name=self.target_name,
            quantity=quantity,
            initial_risk_per_share=float(sizing["risk_per_share"]),
            risk_budget=float(sizing["risk_budget"]),
            position_value=position_value,
            entry_transaction_cost=entry_cost,
            equity_at_entry=float(sizing["equity"]),
            technical_score=order.technical_score,
            actionability=order.actionability,
            planned_rr_t1=order.rr_t1,
            rs60=order.rs60,
            buy_limit=order.entry_high if order.setup == "PULLBACK" else None,
            capital_constraint_reason=str(sizing["reason"]),
        )
        self.positions[position.ticker] = position
        return position

    def _close_position(
        self,
        ticker: str,
        exit_date: pd.Timestamp,
        nominal_exit: float,
        reason: str,
    ) -> None:
        position = self.positions.pop(ticker)
        executed_exit = self.execution.executed_exit(nominal_exit)
        exit_cost = self.execution.transaction_cost(executed_exit, position.quantity)
        proceeds = executed_exit * position.quantity - exit_cost
        self.cash += proceeds

        gross_pnl = (nominal_exit - position.nominal_entry) * position.quantity
        entry_slippage = (
            position.executed_entry - position.nominal_entry
        ) * position.quantity
        exit_slippage = (
            nominal_exit - executed_exit
        ) * position.quantity
        slippage_cost = entry_slippage + exit_slippage
        transaction_cost = position.entry_transaction_cost + exit_cost
        net_pnl = gross_pnl - slippage_cost - transaction_cost
        cash_net_pnl = proceeds - (
            position.executed_entry * position.quantity
            + position.entry_transaction_cost
        )
        if not math.isclose(net_pnl, cash_net_pnl, abs_tol=1e-6, rel_tol=1e-10):
            self.runtime_errors.append(
                f"{self.variant}: PnL reconciliation failed for {ticker} on {exit_date}"
            )
        actual_initial_risk = position.initial_risk_per_share * position.quantity
        r_multiple = net_pnl / actual_initial_risk if actual_initial_risk > 0 else np.nan
        net_return = (
            net_pnl / position.position_value * 100.0
            if position.position_value > 0
            else np.nan
        )
        result = "WIN" if net_pnl > 0 else "LOSS" if net_pnl < 0 else "FLAT"
        self.trade_rows.append(
            {
                "Variant": self.variant,
                "Ticker": ticker,
                "Signal Date": position.signal_date,
                "Entry Date": position.entry_date,
                "Exit Date": exit_date,
                "Signal": position.signal,
                "Setup": position.setup,
                "Market Regime": position.market_regime,
                "Entry Method": position.entry_method,
                "Nominal Entry": position.nominal_entry,
                "Executed Entry": position.executed_entry,
                "Buy Limit": position.buy_limit,
                "Stop": position.stop,
                "Target": position.target,
                "Target Name": position.target_name,
                "Quantity": position.quantity,
                "Initial Risk Per Share": position.initial_risk_per_share,
                "Portfolio Risk Budget": position.risk_budget,
                "Position Value": position.position_value,
                "Capital Constraint Reason": position.capital_constraint_reason,
                "Exit Reason": reason,
                "Nominal Exit": nominal_exit,
                "Executed Exit": executed_exit,
                "Gross PnL": gross_pnl,
                "Entry Slippage Cost": entry_slippage,
                "Exit Slippage Cost": exit_slippage,
                "Slippage Cost": slippage_cost,
                "Entry Transaction Cost": position.entry_transaction_cost,
                "Exit Transaction Cost": exit_cost,
                "Transaction Cost": transaction_cost,
                "Net PnL": net_pnl,
                "Net Return %": net_return,
                "R Multiple": r_multiple,
                "Result": result,
                "Bars Held": position.bars_held,
                "Portfolio Equity At Entry": position.equity_at_entry,
                "Technical Score": position.technical_score,
                "Actionability Score": position.actionability,
                "Planned R:R T1": position.planned_rr_t1,
                "RS 60D": position.rs60,
                "Conservative Entry-Bar Ambiguity": position.ambiguity_invoked,
                "ENTRY_BAR_AMBIGUITY": position.ambiguity_invoked,
            }
        )

    def _process_open_gap_exits(self, current_date: pd.Timestamp) -> set[str]:
        survivors: set[str] = set()
        for ticker in list(self.positions):
            position = self.positions.get(ticker)
            row = self._row(ticker, current_date)
            if position is None or row is None:
                continue
            position.bars_held += 1
            exit_event = self.execution.open_gap_exit(position, row)
            if exit_event is not None:
                self._close_position(ticker, current_date, *exit_event)
            else:
                survivors.add(ticker)
        return survivors

    def _eligible_fills(self, current_date: pd.Timestamp) -> List[FillCandidate]:
        candidates: List[FillCandidate] = []
        for ticker, order in list(self.pending.items()):
            row = self._row(ticker, current_date)
            fill = (
                self.execution.assess_fill(order, row, current_date)
                if row is not None
                else None
            )
            if fill is not None:
                candidates.append(fill)
            elif current_date >= order.expiry_date:
                self.order_rows.append(
                    self._order_row(order, "EXPIRED", current_date, reason="ENTRY_NOT_TRIGGERED")
                )
                self.pending.pop(ticker, None)
        return sorted(candidates, key=self._ranking_key)

    def _process_fills(
        self,
        current_date: pd.Timestamp,
        fill_candidates: Sequence[FillCandidate],
    ) -> List[Tuple[Position, FillCandidate]]:
        opened: List[Tuple[Position, FillCandidate]] = []
        for rank, fill in enumerate(fill_candidates, start=1):
            order = fill.order
            order.rank = rank
            if order.ticker not in self.pending:
                continue
            if len(self.positions) >= self.config.max_open_positions:
                self.order_rows.append(
                    self._order_row(
                        order,
                        "REJECTED_CAPACITY",
                        current_date,
                        reason="MAX_OPEN_POSITIONS_REACHED",
                        fill=fill,
                        rank=rank,
                    )
                )
                self.pending.pop(order.ticker, None)
                continue
            prospective_entry = self.execution.executed_entry(
                fill.nominal_entry,
                fill.entry_method,
                order.entry_high if order.setup == "PULLBACK" else None,
            )
            chosen_target = order.target1 if self.target_name == "T1" else order.target2
            if (
                order.stop >= prospective_entry
                or order.target1 <= prospective_entry
                or order.target2 <= order.target1
                or chosen_target <= prospective_entry
            ):
                self.order_rows.append(
                    self._order_row(
                        order,
                        "INVALID_DATA",
                        current_date,
                        reason="EXECUTED_ENTRY_BREAKS_STOP_OR_TARGET_ORDERING",
                        fill=fill,
                        rank=rank,
                    )
                )
                self.pending.pop(order.ticker, None)
                continue
            sizing = self._position_size(fill, order.stop, current_date)
            if sizing["status"] != "FILLED":
                self.order_rows.append(
                    self._order_row(
                        order,
                        str(sizing["status"]),
                        current_date,
                        reason=str(sizing["reason"]),
                        fill=fill,
                        rank=rank,
                    )
                )
                self.pending.pop(order.ticker, None)
                continue
            position = self._open_position(fill, sizing)
            self.order_rows.append(
                self._order_row(
                    order,
                    "FILLED",
                    current_date,
                    reason=str(sizing["reason"]),
                    fill=fill,
                    rank=rank,
                )
            )
            self.pending.pop(order.ticker, None)
            opened.append((position, fill))
        return opened

    def _process_entry_bar(
        self,
        position: Position,
        fill: FillCandidate,
        current_date: pd.Timestamp,
    ) -> None:
        if position.ticker not in self.positions:
            return
        row = self._row(position.ticker, current_date)
        if row is None:
            return
        position.bars_held = 1
        low_price = float(row["Low"])
        high_price = float(row["High"])
        if fill.intraday_limit:
            stop_hit = low_price <= position.stop
            target_theoretically_hit = high_price >= position.target
            if target_theoretically_hit:
                position.ambiguity_invoked = True
            if stop_hit:
                reason = (
                    "STOP_COLLISION_ENTRY_BAR"
                    if target_theoretically_hit
                    else "STOP_ENTRY_BAR"
                )
                self._close_position(position.ticker, current_date, position.stop, reason)
                return
            # A target-only touch on an intraday limit entry bar is deliberately ignored.
        else:
            event = self.execution.ordinary_bar_exit(position, row)
            if event is not None:
                self._close_position(position.ticker, current_date, *event)
                return
        if (
            position.ticker in self.positions
            and position.bars_held >= self.holding_period
        ):
            self._close_position(
                position.ticker,
                current_date,
                float(row["Close"]),
                f"TIME_{self.holding_period}D",
            )

    def _process_intraday_existing(
        self,
        current_date: pd.Timestamp,
        existing_survivors: Iterable[str],
    ) -> None:
        for ticker in list(existing_survivors):
            position = self.positions.get(ticker)
            row = self._row(ticker, current_date)
            if position is None or row is None:
                continue
            event = self.execution.ordinary_bar_exit(position, row)
            if event is not None:
                self._close_position(ticker, current_date, *event)
                continue
            if position.bars_held >= self.holding_period:
                self._close_position(
                    ticker,
                    current_date,
                    float(row["Close"]),
                    f"TIME_{self.holding_period}D",
                )

    def _force_data_end_exits(self, current_date: pd.Timestamp) -> None:
        for ticker in list(self.positions):
            if self.last_date.get(ticker) != current_date:
                continue
            row = self._row(ticker, current_date)
            if row is not None:
                self._close_position(
                    ticker, current_date, float(row["Close"]), "DATA_END"
                )

    def _record_daily_equity(self, current_date: pd.Timestamp) -> None:
        market_value = 0.0
        for ticker, position in self.positions.items():
            row = self._row(ticker, current_date)
            price = safe_float(row.get("Close")) if row is not None else self.last_close.get(ticker)
            if price is None:
                price = position.nominal_entry
            market_value += position.quantity * price
        equity = self.cash + market_value
        previous_equity = (
            self.equity_rows[-1]["Total Equity"]
            if self.equity_rows
            else self.config.starting_equity
        )
        previous_peak = (
            self.equity_rows[-1]["Peak Equity"]
            if self.equity_rows
            else self.config.starting_equity
        )
        peak = max(previous_peak, equity)
        drawdown = (equity / peak - 1.0) * 100.0 if peak > 0 else np.nan
        daily_return = (
            (equity / previous_equity - 1.0) * 100.0
            if previous_equity != 0
            else np.nan
        )
        self.equity_rows.append(
            {
                "Date": current_date,
                "Variant": self.variant,
                "Cash": self.cash,
                "Open Position Value": market_value,
                "Total Equity": equity,
                "Peak Equity": peak,
                "Drawdown %": drawdown,
                "Number Open Positions": len(self.positions),
                "Daily Return %": daily_return,
            }
        )
        for ticker in self.features:
            row = self._row(ticker, current_date)
            if row is not None:
                close = safe_float(row.get("Close"))
                if close is not None:
                    self.last_close[ticker] = close

    def _check_state(self, current_date: pd.Timestamp) -> None:
        overlap = set(self.pending).intersection(self.positions)
        if overlap:
            self.runtime_errors.append(
                f"{self.variant}: pending/open overlap {sorted(overlap)} on {current_date}"
            )
        if len(self.positions) > self.config.max_open_positions:
            self.runtime_errors.append(
                f"{self.variant}: {len(self.positions)} positions on {current_date}"
            )
        if self.cash < -1e-7:
            self.runtime_errors.append(
                f"{self.variant}: materially negative cash {self.cash} on {current_date}"
            )
        self.max_concurrent_positions = max(
            self.max_concurrent_positions, len(self.positions)
        )

    def run(self) -> Dict[str, Any]:
        for current_date in self.calendar:
            existing_survivors = self._process_open_gap_exits(current_date)
            fill_candidates = self._eligible_fills(current_date)
            opened = self._process_fills(current_date, fill_candidates)
            for position, fill in opened:
                self._process_entry_bar(position, fill, current_date)
            self._process_intraday_existing(current_date, existing_survivors)
            self._force_data_end_exits(current_date)
            self._create_orders_at_close(current_date)
            self._check_state(current_date)
            self._record_daily_equity(current_date)

        for order in list(self.pending.values()):
            status_date = self.calendar[-1] if self.calendar else order.signal_date
            self.order_rows.append(
                self._order_row(order, "EXPIRED", status_date, reason="BACKTEST_ENDED")
            )
        self.pending.clear()

        return {
            "variant": self.variant,
            "orders": pd.DataFrame(self.order_rows),
            "trades": pd.DataFrame(self.trade_rows),
            "equity": pd.DataFrame(self.equity_rows),
            "runtime_errors": list(dict.fromkeys(self.runtime_errors)),
            "max_concurrent_positions": self.max_concurrent_positions,
        }


class CandidateOutcomeEngine:
    """Independent research outcomes; never used to construct portfolio returns."""

    def __init__(
        self,
        config: Stage22Config,
        features: Dict[str, pd.DataFrame],
    ) -> None:
        self.config = config
        self.features = features
        self.execution = ExecutionModel(config)
        self.holding_period = max(config.holding_periods)

    def _valid_dates(
        self, ticker: str, signal_date: pd.Timestamp, setup: str
    ) -> Tuple[pd.Timestamp, ...]:
        frame = self.features.get(ticker)
        if frame is None:
            return ()
        future = tuple(pd.Timestamp(value).normalize() for value in frame.index if value > signal_date)
        count = 1 if setup == "BREAKOUT" else self.config.pullback_entry_window
        return future[:count]

    def _simulate_one(self, signal: Dict[str, Any], row_id: int) -> Dict[str, Any]:
        empty = {
            "_Candidate Row": row_id,
            "Candidate Status": "NO_RESEARCH_OUTCOME",
            "Candidate Entry Date": pd.NaT,
            "Candidate Exit Date": pd.NaT,
            "Candidate Entry Method": "",
            "Candidate Exit Reason": "",
            "Candidate Nominal Entry": np.nan,
            "Candidate Executed Entry": np.nan,
            "Candidate Nominal Exit": np.nan,
            "Candidate Executed Exit": np.nan,
            "Candidate Net PnL": np.nan,
            "Candidate Net Return %": np.nan,
            "Candidate R Multiple": np.nan,
            "Candidate Result": "",
            "Candidate Bars Held": np.nan,
            "Candidate Entry-Bar Ambiguity": False,
        }
        if signal.get("Signal") not in RESEARCH_SIGNALS:
            return empty
        ticker = str(signal.get("Ticker", ""))
        setup = str(signal.get("Setup", ""))
        if setup not in VALID_SETUPS or ticker not in self.features:
            return empty
        values = PortfolioBacktester._signal_values(signal)
        if values is None:
            return empty
        signal_date = normalize_date(signal["Signal Date"])
        valid_dates = self._valid_dates(ticker, signal_date, setup)
        if not valid_dates:
            return empty
        order = PendingOrder(
            order_id=row_id,
            variant="CANDIDATE_T1_63D",
            ticker=ticker,
            signal_date=signal_date,
            signal=str(signal["Signal"]),
            setup=setup,
            created_date=signal_date,
            expiry_date=valid_dates[-1],
            valid_dates=valid_dates,
            entry_low=values["entry_low"],
            entry_high=values["entry_high"],
            stop=values["stop"],
            target1=values["target1"],
            target2=values["target2"],
            actionability=values["actionability"],
            technical_score=values["technical"],
            rr_t1=values["rr_t1"],
            rs60=values["rs60"],
            market_regime=str(signal.get("Market Regime", "")),
        )
        frame = self.features[ticker]
        fill: Optional[FillCandidate] = None
        for current_date in valid_dates:
            if current_date not in frame.index:
                continue
            candidate = self.execution.assess_fill(
                order, frame.loc[current_date], current_date
            )
            if candidate is not None:
                fill = candidate
                break
        if fill is None:
            empty["Candidate Status"] = "EXPIRED"
            return empty

        executed_entry = self.execution.executed_entry(
            fill.nominal_entry,
            fill.entry_method,
            order.entry_high if order.setup == "PULLBACK" else None,
        )
        risk_per_share = executed_entry - order.stop
        if risk_per_share <= 0 or order.target1 <= executed_entry:
            empty["Candidate Status"] = "INVALID_RISK"
            empty["Candidate Entry Date"] = fill.fill_date
            return empty

        future = frame.loc[frame.index >= fill.fill_date]
        nominal_exit = float(future["Close"].iloc[-1])
        exit_date = normalize_date(future.index[-1])
        exit_reason = "DATA_END"
        bars = 0
        ambiguity = False
        for date_value, bar in future.iterrows():
            current_date = normalize_date(date_value)
            bars += 1
            if current_date == fill.fill_date:
                if fill.intraday_limit:
                    stop_hit = float(bar["Low"]) <= order.stop
                    target_theoretical = float(bar["High"]) >= order.target1
                    ambiguity = target_theoretical
                    if stop_hit:
                        nominal_exit = order.stop
                        exit_date = current_date
                        exit_reason = (
                            "STOP_COLLISION_ENTRY_BAR"
                            if target_theoretical
                            else "STOP_ENTRY_BAR"
                        )
                        break
                else:
                    temporary = Position(
                        variant="CANDIDATE",
                        ticker=ticker,
                        signal_date=signal_date,
                        entry_date=fill.fill_date,
                        signal=order.signal,
                        setup=setup,
                        market_regime=order.market_regime,
                        entry_method=fill.entry_method,
                        nominal_entry=fill.nominal_entry,
                        executed_entry=executed_entry,
                        stop=order.stop,
                        target=order.target1,
                        target_name="T1",
                        quantity=1,
                        initial_risk_per_share=risk_per_share,
                        risk_budget=risk_per_share,
                        position_value=executed_entry,
                        entry_transaction_cost=0.0,
                        equity_at_entry=executed_entry,
                        technical_score=order.technical_score,
                        actionability=order.actionability,
                        planned_rr_t1=order.rr_t1,
                        rs60=order.rs60,
                    )
                    event = self.execution.ordinary_bar_exit(temporary, bar)
                    if event is not None:
                        nominal_exit, exit_reason = event
                        exit_date = current_date
                        break
            else:
                temporary = Position(
                    variant="CANDIDATE",
                    ticker=ticker,
                    signal_date=signal_date,
                    entry_date=fill.fill_date,
                    signal=order.signal,
                    setup=setup,
                    market_regime=order.market_regime,
                    entry_method=fill.entry_method,
                    nominal_entry=fill.nominal_entry,
                    executed_entry=executed_entry,
                    stop=order.stop,
                    target=order.target1,
                    target_name="T1",
                    quantity=1,
                    initial_risk_per_share=risk_per_share,
                    risk_budget=risk_per_share,
                    position_value=executed_entry,
                    entry_transaction_cost=0.0,
                    equity_at_entry=executed_entry,
                    technical_score=order.technical_score,
                    actionability=order.actionability,
                    planned_rr_t1=order.rr_t1,
                    rs60=order.rs60,
                )
                gap = self.execution.open_gap_exit(temporary, bar)
                event = gap or self.execution.ordinary_bar_exit(temporary, bar)
                if event is not None:
                    nominal_exit, exit_reason = event
                    exit_date = current_date
                    break
            if bars >= self.holding_period:
                nominal_exit = float(bar["Close"])
                exit_date = current_date
                exit_reason = f"TIME_{self.holding_period}D"
                break

        executed_exit = self.execution.executed_exit(nominal_exit)
        entry_cost = self.execution.transaction_cost(executed_entry, 1)
        exit_cost = self.execution.transaction_cost(executed_exit, 1)
        gross_pnl = nominal_exit - fill.nominal_entry
        slippage_cost = (executed_entry - fill.nominal_entry) + (nominal_exit - executed_exit)
        net_pnl = gross_pnl - slippage_cost - entry_cost - exit_cost
        net_return = net_pnl / executed_entry * 100.0
        r_multiple = net_pnl / risk_per_share
        return {
            "_Candidate Row": row_id,
            "Candidate Status": "SIMULATED",
            "Candidate Entry Date": fill.fill_date,
            "Candidate Exit Date": exit_date,
            "Candidate Entry Method": fill.entry_method,
            "Candidate Exit Reason": exit_reason,
            "Candidate Nominal Entry": fill.nominal_entry,
            "Candidate Executed Entry": executed_entry,
            "Candidate Nominal Exit": nominal_exit,
            "Candidate Executed Exit": executed_exit,
            "Candidate Net PnL": net_pnl,
            "Candidate Net Return %": net_return,
            "Candidate R Multiple": r_multiple,
            "Candidate Result": "WIN" if net_pnl > 0 else "LOSS" if net_pnl < 0 else "FLAT",
            "Candidate Bars Held": bars,
            "Candidate Entry-Bar Ambiguity": ambiguity,
        }

    def run(self, candidate_signals: pd.DataFrame) -> pd.DataFrame:
        if candidate_signals.empty:
            return candidate_signals.copy()
        source = candidate_signals.reset_index(drop=True).copy()
        source["_Candidate Row"] = np.arange(len(source))
        research = source[source["Signal"].isin(RESEARCH_SIGNALS)]
        outcomes = [
            self._simulate_one(row, int(row["_Candidate Row"]))
            for row in research.to_dict("records")
        ]
        outcome_frame = pd.DataFrame(outcomes)
        result = source.merge(outcome_frame, on="_Candidate Row", how="left")
        result = result.drop(columns=["_Candidate Row"])
        return result


def max_consecutive_losses(values: Iterable[float]) -> int:
    maximum = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def performance_metrics(
    frame: pd.DataFrame,
    pnl_column: str = "Net PnL",
    return_column: str = "Net Return %",
    r_column: str = "R Multiple",
    bars_column: str = "Bars Held",
    profit_factor_column: Optional[str] = None,
) -> Dict[str, Any]:
    if frame.empty:
        return {
            "Trades": 0,
            "Wins": 0,
            "Losses": 0,
            "Win Rate %": 0.0,
            "Average Return %": np.nan,
            "Median Return %": np.nan,
            "Average R": np.nan,
            "Median R": np.nan,
            "Profit Factor": np.nan,
            "Expectancy R": np.nan,
            "Average Holding Days": np.nan,
            "Max Consecutive Losses": 0,
            "Total Net PnL": 0.0,
        }
    data = frame.copy()
    pnl = pd.to_numeric(data[pnl_column], errors="coerce").fillna(0.0)
    factor_values = pd.to_numeric(
        data[profit_factor_column or pnl_column], errors="coerce"
    ).fillna(0.0)
    returns = pd.to_numeric(data[return_column], errors="coerce")
    r_values = pd.to_numeric(data[r_column], errors="coerce")
    bars = pd.to_numeric(data[bars_column], errors="coerce")
    wins = int((pnl > 0).sum())
    losses = int((pnl < 0).sum())
    gross_profit = float(factor_values[factor_values > 0].sum())
    gross_loss = abs(float(factor_values[factor_values < 0].sum()))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf if gross_profit > 0 else np.nan
    return {
        "Trades": len(data),
        "Wins": wins,
        "Losses": losses,
        "Win Rate %": wins / len(data) * 100.0,
        "Average Return %": float(returns.mean()),
        "Median Return %": float(returns.median()),
        "Average R": float(r_values.mean()),
        "Median R": float(r_values.median()),
        "Profit Factor": profit_factor,
        "Expectancy R": float(r_values.mean()),
        "Average Holding Days": float(bars.mean()),
        "Max Consecutive Losses": max_consecutive_losses(pnl.tolist()),
        "Total Net PnL": float(pnl.sum()),
    }


def technical_score_band(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "MISSING"
    if number < 50:
        return "< 50"
    if number < 60:
        return "50-59"
    if number < 70:
        return "60-69"
    if number < 80:
        return "70-79"
    if number < 90:
        return "80-89"
    return "90-100"


def actionability_score_band(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "MISSING"
    if number < 40:
        return "< 40"
    if number < 50:
        return "40-49"
    if number < 60:
        return "50-59"
    if number < 70:
        return "60-69"
    if number < 80:
        return "70-79"
    if number < 90:
        return "80-89"
    return "90-100"


def rr_band(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "MISSING"
    if number < 1.5:
        return "< 1.5"
    if number < 2.0:
        return "1.5-1.99"
    if number < 2.5:
        return "2.0-2.49"
    if number < 3.0:
        return "2.5-2.99"
    return "3.0+"


class PerformanceAnalyzer:
    def __init__(
        self,
        config: Stage22Config,
        candidate_log: pd.DataFrame,
        portfolio_results: Sequence[Dict[str, Any]],
    ) -> None:
        self.config = config
        self.candidate_log = candidate_log.copy()
        self.results = list(portfolio_results)
        self.orders = pd.concat(
            [result["orders"] for result in self.results if not result["orders"].empty],
            ignore_index=True,
        ) if any(not result["orders"].empty for result in self.results) else pd.DataFrame()
        self.trades = pd.concat(
            [result["trades"] for result in self.results if not result["trades"].empty],
            ignore_index=True,
        ) if any(not result["trades"].empty for result in self.results) else pd.DataFrame()

    @staticmethod
    def _group_summary(
        frame: pd.DataFrame,
        group_columns: Sequence[str],
        candidate: bool = False,
    ) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        if frame.empty:
            return pd.DataFrame()
        columns: Any = group_columns[0] if len(group_columns) == 1 else list(group_columns)
        for key, group in frame.groupby(columns, dropna=False, sort=True):
            key_tuple = key if isinstance(key, tuple) else (key,)
            if candidate:
                metrics = performance_metrics(
                    group,
                    pnl_column="Candidate Net PnL",
                    return_column="Candidate Net Return %",
                    r_column="Candidate R Multiple",
                    bars_column="Candidate Bars Held",
                    profit_factor_column="Candidate R Multiple",
                )
                metrics["One-Share Net PnL (Diagnostic Only)"] = metrics.pop(
                    "Total Net PnL"
                )
            else:
                metrics = performance_metrics(group)
            row = {column: value for column, value in zip(group_columns, key_tuple)}
            row.update(metrics)
            rows.append(row)
        return pd.DataFrame(rows)

    def candidate_tables(self) -> Dict[str, pd.DataFrame]:
        log = self.candidate_log.copy()
        if log.empty:
            return {
                "candidate_outcome_summary": pd.DataFrame(),
                "signal_type_summary": pd.DataFrame(),
                "score_band_summary": pd.DataFrame(),
                "score_matrix": pd.DataFrame(),
            }
        log["Technical Score Band"] = log["Technical Score"].map(technical_score_band)
        log["Actionability Score Band"] = log["Actionability Score"].map(actionability_score_band)
        log["R:R Band"] = log["R:R T1"].map(rr_band)
        simulated = log[log["Candidate Status"] == "SIMULATED"].copy()

        dimension_frames: List[pd.DataFrame] = []
        for dimension, column in [
            ("Signal", "Signal"),
            ("Setup", "Setup"),
            ("Market Regime", "Market Regime"),
            ("Ticker", "Ticker"),
            ("Technical Score Band", "Technical Score Band"),
            ("Actionability Score Band", "Actionability Score Band"),
            ("R:R Band", "R:R Band"),
        ]:
            table = self._group_summary(simulated, [column], candidate=True)
            if table.empty:
                continue
            table.insert(0, "Dimension", dimension)
            table = table.rename(columns={column: "Group"})
            dimension_frames.append(table)
        candidate_outcome_summary = (
            pd.concat(dimension_frames, ignore_index=True)
            if dimension_frames
            else pd.DataFrame()
        )
        signal_summary = self._group_summary(simulated, ["Signal"], candidate=True)

        score_frames: List[pd.DataFrame] = []
        for score_type, column in [
            ("Technical Score", "Technical Score Band"),
            ("Actionability Score", "Actionability Score Band"),
        ]:
            table = self._group_summary(simulated, [column], candidate=True)
            if table.empty:
                continue
            table.insert(0, "Score Type", score_type)
            table = table.rename(columns={column: "Score Band"})
            score_frames.append(table)
        score_band_summary = (
            pd.concat(score_frames, ignore_index=True) if score_frames else pd.DataFrame()
        )
        score_matrix = self._group_summary(
            simulated,
            ["Technical Score Band", "Actionability Score Band"],
            candidate=True,
        )
        return {
            "candidate_outcome_summary": candidate_outcome_summary,
            "signal_type_summary": signal_summary,
            "score_band_summary": score_band_summary,
            "score_matrix": score_matrix,
        }

    @staticmethod
    def _slice_drawdown(equity: pd.DataFrame, start_equity: float) -> float:
        if equity.empty:
            return 0.0
        values = pd.to_numeric(equity["Total Equity"], errors="coerce")
        running_peak = pd.concat(
            [pd.Series([start_equity]), values.reset_index(drop=True)],
            ignore_index=True,
        ).cummax().iloc[1:]
        drawdown = values.reset_index(drop=True) / running_peak.reset_index(drop=True) - 1.0
        return float(drawdown.min() * 100.0)

    def portfolio_summary(self) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        start_date = normalize_date(self.config.test_start)
        end_date = normalize_date(self.config.test_end)
        elapsed_years = max((end_date - start_date).days / 365.25, 0.0)
        for result in self.results:
            trades = result["trades"]
            equity = result["equity"]
            metrics = performance_metrics(trades) if not trades.empty else performance_metrics(pd.DataFrame())
            ending_equity = (
                float(equity["Total Equity"].iloc[-1])
                if not equity.empty
                else self.config.starting_equity
            )
            cagr = (
                (ending_equity / self.config.starting_equity) ** (1.0 / elapsed_years) - 1.0
                if elapsed_years > 0 and ending_equity > 0
                else np.nan
            )
            orders = result["orders"]
            row = {
                "Variant": result["variant"],
                "Starting Equity": self.config.starting_equity,
                "Ending Equity": ending_equity,
                "Net Return %": (ending_equity / self.config.starting_equity - 1.0) * 100.0,
                "CAGR %": cagr * 100.0 if np.isfinite(cagr) else np.nan,
                "Total Trades": metrics["Trades"],
                "Wins": metrics["Wins"],
                "Losses": metrics["Losses"],
                "Win Rate %": metrics["Win Rate %"],
                "Average Winner": (
                    float(trades.loc[trades["Net PnL"] > 0, "Net PnL"].mean())
                    if not trades.empty and (trades["Net PnL"] > 0).any()
                    else np.nan
                ),
                "Average Loser": (
                    float(trades.loc[trades["Net PnL"] < 0, "Net PnL"].mean())
                    if not trades.empty and (trades["Net PnL"] < 0).any()
                    else np.nan
                ),
                "Average R": metrics["Average R"],
                "Median R": metrics["Median R"],
                "Expectancy R": metrics["Expectancy R"],
                "Profit Factor": metrics["Profit Factor"],
                "Maximum Drawdown %": (
                    float(equity["Drawdown %"].min()) if not equity.empty else 0.0
                ),
                "Maximum Consecutive Losses": metrics["Max Consecutive Losses"],
                "Average Holding Days": metrics["Average Holding Days"],
                "Maximum Concurrent Positions": result["max_concurrent_positions"],
                "Capacity Rejections": (
                    int((orders["Status"] == "REJECTED_CAPACITY").sum())
                    if not orders.empty else 0
                ),
                "Expired Orders": (
                    int((orders["Status"] == "EXPIRED").sum())
                    if not orders.empty else 0
                ),
                "Survivorship Bias Warning": SURVIVORSHIP_WARNING,
            }
            rows.append(row)
        return pd.DataFrame(rows)

    def yearly_summary(self) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        for result in self.results:
            equity = result["equity"].copy()
            trades = result["trades"].copy()
            if equity.empty:
                continue
            equity["Date"] = pd.to_datetime(equity["Date"])
            equity["Year"] = equity["Date"].dt.year
            if not trades.empty:
                trades["Exit Date"] = pd.to_datetime(trades["Exit Date"])
                trades["Year"] = trades["Exit Date"].dt.year
            previous_ending = self.config.starting_equity
            for year, year_equity in equity.groupby("Year", sort=True):
                year_trades = (
                    trades[trades["Year"] == year] if not trades.empty else pd.DataFrame()
                )
                metrics = performance_metrics(year_trades) if not year_trades.empty else performance_metrics(pd.DataFrame())
                ending = float(year_equity["Total Equity"].iloc[-1])
                gross_pnl = float(year_trades["Gross PnL"].sum()) if not year_trades.empty else 0.0
                rows.append(
                    {
                        "Variant": result["variant"],
                        "Year": int(year),
                        "Trades": metrics["Trades"],
                        "Wins": metrics["Wins"],
                        "Losses": metrics["Losses"],
                        "Win Rate %": metrics["Win Rate %"],
                        "Gross Return %": gross_pnl / previous_ending * 100.0 if previous_ending else np.nan,
                        "Net Return %": (ending / previous_ending - 1.0) * 100.0 if previous_ending else np.nan,
                        "Average R": metrics["Average R"],
                        "Expectancy R": metrics["Expectancy R"],
                        "Profit Factor": metrics["Profit Factor"],
                        "Max Drawdown %": self._slice_drawdown(year_equity, previous_ending),
                        "Ending Equity": ending,
                        "Survivorship Bias Warning": SURVIVORSHIP_WARNING,
                    }
                )
                previous_ending = ending
        return pd.DataFrame(rows)

    def period_summary(self) -> pd.DataFrame:
        periods = [
            ("2011-2015", 2011, 2015),
            ("2016-2020", 2016, 2020),
            ("2021-2023", 2021, 2023),
            ("2024-2026", 2024, 2026),
        ]
        rows: List[Dict[str, Any]] = []
        for result in self.results:
            equity = result["equity"].copy()
            trades = result["trades"].copy()
            if equity.empty:
                continue
            equity["Date"] = pd.to_datetime(equity["Date"])
            if not trades.empty:
                trades["Exit Date"] = pd.to_datetime(trades["Exit Date"])
            for label, first_year, last_year in periods:
                period_equity = equity[
                    equity["Date"].dt.year.between(first_year, last_year)
                ]
                if period_equity.empty:
                    continue
                before = equity[equity["Date"] < period_equity["Date"].iloc[0]]
                starting = (
                    float(before["Total Equity"].iloc[-1])
                    if not before.empty else self.config.starting_equity
                )
                ending = float(period_equity["Total Equity"].iloc[-1])
                period_trades = (
                    trades[trades["Exit Date"].dt.year.between(first_year, last_year)]
                    if not trades.empty else pd.DataFrame()
                )
                metrics = performance_metrics(period_trades) if not period_trades.empty else performance_metrics(pd.DataFrame())
                rows.append(
                    {
                        "Variant": result["variant"],
                        "Period": label,
                        "Trades": metrics["Trades"],
                        "Wins": metrics["Wins"],
                        "Losses": metrics["Losses"],
                        "Win Rate %": metrics["Win Rate %"],
                        "Net Return %": (ending / starting - 1.0) * 100.0 if starting else np.nan,
                        "Average R": metrics["Average R"],
                        "Expectancy R": metrics["Expectancy R"],
                        "Profit Factor": metrics["Profit Factor"],
                        "Max Drawdown %": self._slice_drawdown(period_equity, starting),
                        "Ending Equity": ending,
                        "Survivorship Bias Warning": SURVIVORSHIP_WARNING,
                    }
                )
        return pd.DataFrame(rows)

    def diagnostic_tables(self) -> Dict[str, pd.DataFrame]:
        return {
            "stock_summary": self._group_summary(self.trades, ["Variant", "Ticker"]),
            "setup_summary": self._group_summary(self.trades, ["Variant", "Setup"]),
            "regime_summary": self._group_summary(self.trades, ["Variant", "Market Regime"]),
        }


class Validator:
    def __init__(
        self,
        config: Stage22Config,
        candidate_signals: pd.DataFrame,
        parity_passed: bool,
        parity_details: Dict[str, Any],
        portfolio_results: Sequence[Dict[str, Any]],
    ) -> None:
        self.config = config
        self.candidates = candidate_signals
        self.parity_passed = parity_passed
        self.parity_details = parity_details
        self.results = list(portfolio_results)
        self.checks: List[Dict[str, str]] = []

    def _add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(
            {"Check": name, "Status": "PASS" if passed else "FAIL", "Detail": detail}
        )

    def run(self) -> Tuple[bool, pd.DataFrame, str]:
        start = normalize_date(self.config.test_start)
        end = normalize_date(self.config.test_end)
        signal_dates = (
            pd.to_datetime(self.candidates["Signal Date"])
            if not self.candidates.empty else pd.Series([], dtype="datetime64[ns]")
        )
        point_in_time = (
            not signal_dates.empty
            and signal_dates.min() >= start
            and signal_dates.max() <= end
            and self.parity_passed
        )
        self._add("Point-in-time signal checks", point_in_time, "Frozen core + date window + parity")
        self._add(
            "Stage 2.1 signal parity",
            self.parity_passed,
            f"generated={self.parity_details.get('Generated Rows', 0)}, "
            f"reference={self.parity_details.get('Reference Rows', 0)}, "
            f"mismatches={self.parity_details.get('Mismatched Rows', 0)}",
        )

        all_orders = []
        all_trades = []
        all_equity = []
        runtime_errors: List[str] = []
        for result in self.results:
            if not result["orders"].empty:
                all_orders.append(result["orders"])
            if not result["trades"].empty:
                all_trades.append(result["trades"])
            if not result["equity"].empty:
                all_equity.append(result["equity"])
            runtime_errors.extend(result["runtime_errors"])
        orders = pd.concat(all_orders, ignore_index=True) if all_orders else pd.DataFrame()
        trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
        equity = pd.concat(all_equity, ignore_index=True) if all_equity else pd.DataFrame()

        entry_after_signal = True if trades.empty else (
            pd.to_datetime(trades["Entry Date"]) > pd.to_datetime(trades["Signal Date"])
        ).all()
        self._add("Entry strictly after signal", bool(entry_after_signal))

        overlap_errors: List[str] = []
        if not trades.empty:
            for (variant, ticker), group in trades.groupby(["Variant", "Ticker"]):
                ordered = group.sort_values("Entry Date")
                previous_exit: Optional[pd.Timestamp] = None
                for _, row in ordered.iterrows():
                    entry = normalize_date(row["Entry Date"])
                    if previous_exit is not None and entry <= previous_exit:
                        overlap_errors.append(f"{variant}:{ticker}:{entry.date()}")
                    previous_exit = normalize_date(row["Exit Date"])
        self._add(
            "No duplicate same-ticker positions",
            not overlap_errors,
            "; ".join(overlap_errors[:5]),
        )
        pending_errors = [error for error in runtime_errors if "pending/open overlap" in error]
        self._add(
            "No duplicate same-ticker orders",
            not pending_errors,
            "; ".join(pending_errors[:5]),
        )

        max_positions_ok = True if equity.empty else (
            pd.to_numeric(equity["Number Open Positions"], errors="coerce")
            <= self.config.max_open_positions
        ).all()
        self._add("Maximum positions respected", bool(max_positions_ok))
        no_watch = True if trades.empty else trades["Signal"].isin(PRIMARY_SIGNALS).all()
        self._add("No WATCH trades in primary portfolio", bool(no_watch))
        positive_quantity = True if trades.empty else (
            pd.to_numeric(trades["Quantity"], errors="coerce") > 0
        ).all()
        self._add("No negative quantity", bool(positive_quantity))
        cash_ok = True if equity.empty else (
            pd.to_numeric(equity["Cash"], errors="coerce") >= -1e-7
        ).all()
        self._add("Cash constraint respected", bool(cash_ok))

        stop_ok = True if trades.empty else (
            pd.to_numeric(trades["Stop"], errors="coerce")
            < pd.to_numeric(trades["Executed Entry"], errors="coerce")
        ).all()
        t1_ok = True if trades.empty else (
            trades.apply(
                lambda row: (
                    safe_float(row["Target"]) is not None
                    and safe_float(row["Executed Entry"]) is not None
                    and (
                        row["Target Name"] != "T1"
                        or float(row["Target"]) > float(row["Executed Entry"])
                    )
                ),
                axis=1,
            ).all()
        )
        candidate_levels = self.candidates[
            self.candidates["Signal"].isin(PRIMARY_SIGNALS)
            & self.candidates["Setup"].isin(VALID_SETUPS)
        ] if not self.candidates.empty else pd.DataFrame()
        t2_ok = True if candidate_levels.empty else (
            pd.to_numeric(candidate_levels["Target 2"], errors="coerce")
            > pd.to_numeric(candidate_levels["Target 1"], errors="coerce")
        ).all()
        self._add("Stop below entry", bool(stop_ok))
        self._add("T1 above entry", bool(t1_ok))
        self._add("T2 above T1", bool(t2_ok))

        equity_reconciled = True
        if not equity.empty:
            expected = pd.to_numeric(equity["Cash"], errors="coerce") + pd.to_numeric(
                equity["Open Position Value"], errors="coerce"
            )
            actual = pd.to_numeric(equity["Total Equity"], errors="coerce")
            equity_reconciled = np.allclose(expected, actual, atol=1e-6, rtol=1e-10)
        self._add("Daily equity reconciliation", bool(equity_reconciled))

        slippage_ok = True
        costs_ok = True
        if not trades.empty:
            slippage_ok = np.allclose(
                pd.to_numeric(trades["Slippage Cost"], errors="coerce"),
                pd.to_numeric(trades["Entry Slippage Cost"], errors="coerce")
                + pd.to_numeric(trades["Exit Slippage Cost"], errors="coerce"),
                atol=1e-6,
                rtol=1e-10,
            )
            costs_ok = np.allclose(
                pd.to_numeric(trades["Transaction Cost"], errors="coerce"),
                pd.to_numeric(trades["Entry Transaction Cost"], errors="coerce")
                + pd.to_numeric(trades["Exit Transaction Cost"], errors="coerce"),
                atol=1e-6,
                rtol=1e-10,
            )
            expected_net = (
                pd.to_numeric(trades["Gross PnL"], errors="coerce")
                - pd.to_numeric(trades["Slippage Cost"], errors="coerce")
                - pd.to_numeric(trades["Transaction Cost"], errors="coerce")
            )
            costs_ok = costs_ok and np.allclose(
                expected_net,
                pd.to_numeric(trades["Net PnL"], errors="coerce"),
                atol=1e-6,
                rtol=1e-10,
            )
        self._add("Slippage charged once", bool(slippage_ok))
        self._add("Transaction costs reconciled", bool(costs_ok))
        self._add("Runtime state invariants", not runtime_errors, "; ".join(runtime_errors[:5]))

        overall = all(row["Status"] == "PASS" for row in self.checks)
        report_lines = [
            "STAGE 2.2 VALIDATION",
            "-" * 88,
            *[
                f"{row['Check']:<44} {row['Status']:<5} {row['Detail']}".rstrip()
                for row in self.checks
            ],
            "-" * 88,
            f"OVERALL VALIDATION: {'PASS' if overall else 'FAIL'}",
            "",
            SURVIVORSHIP_WARNING,
        ]
        return overall, pd.DataFrame(self.checks), "\n".join(report_lines)


def _add_warning(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["Survivorship Bias Warning"] = SURVIVORSHIP_WARNING
    return result


def save_outputs(
    config: Stage22Config,
    candidate_log: pd.DataFrame,
    data_availability: pd.DataFrame,
    parity_differences: pd.DataFrame,
    analyzer: PerformanceAnalyzer,
    portfolio_results: Sequence[Dict[str, Any]],
    validation_checks: pd.DataFrame,
    validation_report: str,
    runtime_seconds: float,
) -> Dict[str, Path]:
    output = config.output_directory
    output.mkdir(parents=True, exist_ok=True)
    candidate_tables = analyzer.candidate_tables()
    diagnostics = analyzer.diagnostic_tables()
    files: Dict[str, pd.DataFrame] = {
        "stage2_2_candidate_signal_log.csv": candidate_log,
        "stage2_2_candidate_outcome_summary.csv": candidate_tables["candidate_outcome_summary"],
        "stage2_2_signal_type_summary.csv": candidate_tables["signal_type_summary"],
        "stage2_2_score_band_summary.csv": candidate_tables["score_band_summary"],
        "stage2_2_score_matrix.csv": candidate_tables["score_matrix"],
        "stage2_2_order_log.csv": analyzer.orders,
        "stage2_2_portfolio_summary.csv": analyzer.portfolio_summary(),
        "stage2_2_portfolio_trade_log.csv": analyzer.trades,
        "stage2_2_yearly_summary.csv": analyzer.yearly_summary(),
        "stage2_2_period_summary.csv": analyzer.period_summary(),
        "stage2_2_stock_summary.csv": diagnostics["stock_summary"],
        "stage2_2_setup_summary.csv": diagnostics["setup_summary"],
        "stage2_2_regime_summary.csv": diagnostics["regime_summary"],
        "stage2_2_data_availability.csv": data_availability,
        "stage2_2_signal_parity_differences.csv": parity_differences,
        "stage2_2_validation_checks.csv": validation_checks,
    }
    for result in portfolio_results:
        files[f"stage2_2_daily_equity_{result['variant']}.csv"] = result["equity"]

    written: Dict[str, Path] = {}
    for filename, frame in files.items():
        path = output / filename
        prepared = frame.copy()
        prepared["Candidate Source"] = config.candidate_source.upper()
        _add_warning(prepared).to_csv(path, index=False)
        written[filename] = path

    report_path = output / "stage2_2_validation_report.txt"
    report_path.write_text(
        validation_report
        + f"\n\nRuntime seconds: {runtime_seconds:.3f}\n"
        + f"Test window: {config.test_start} through {config.test_end}\n",
        encoding="utf-8",
    )
    written[report_path.name] = report_path

    methodology_path = output / "stage2_2_methodology_notes.txt"
    methodology_path.write_text(
        "STAGE 2.2 METHODOLOGY NOTES\n"
        "=" * 72
        + "\n"
        + SURVIVORSHIP_WARNING
        + "\n\n"
        + "Frozen signal core: imported unchanged from Stage 2.1.\n"
        + f"Portfolio candidate source: {config.candidate_source.upper()}.\n"
        + "Primary entries: BUY and STRONG BUY only.\n"
        + "Research candidate horizon: T1 with a 63-session maximum.\n"
        + "R:R research bands: <1.5, 1.5-1.99, 2.0-2.49, 2.5-2.99, 3.0+.\n"
        + "Intraday pullback entry-bar target-only touches are not credited.\n"
        + "Gap-down pullback limit orders execute at the better opening price; "
        + "orders whose executed entry invalidates the stop/target ordering are rejected.\n"
        + "Capacity is freed by opening-gap exits, but not reused after an unknown-time "
        + "intraday exit on the same session.\n"
        + "Daily open-position valuation uses unadjusted close mark-to-market; "
        + "slippage and transaction cost are realized only at execution.\n",
        encoding="utf-8",
    )
    written[methodology_path.name] = methodology_path
    return written


def make_variants(config: Stage22Config) -> List[Tuple[str, str, int]]:
    variants: List[Tuple[str, str, int]] = []
    for target_name, target_column in [("T1", "Target 1"), ("T2", "Target 2")]:
        for holding_period in config.holding_periods:
            variants.append(
                (f"{target_name}_{holding_period}D", target_column, holding_period)
            )
    return variants


def run_portfolios(
    config: Stage22Config,
    features: Dict[str, pd.DataFrame],
    candidates: pd.DataFrame,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for variant, target_column, holding_period in make_variants(config):
        started = time.perf_counter()
        backtester = PortfolioBacktester(
            config,
            features,
            candidates,
            variant,
            target_column,
            holding_period,
        )
        result = backtester.run()
        results.append(result)
        elapsed = time.perf_counter() - started
        print(
            f"  {variant}: {len(result['trades']):,} trades, "
            f"{result['max_concurrent_positions']} max positions, {elapsed:.2f}s"
        )
    return results


def _synthetic_signal(
    ticker: str,
    signal_date: pd.Timestamp,
    signal: str = "BUY",
    setup: str = "BREAKOUT",
    technical: float = 75.0,
    actionability: float = 75.0,
    entry_low: float = 99.0,
    entry_high: float = 100.0,
    stop: float = 95.0,
    target1: float = 110.0,
    target2: float = 115.0,
) -> Dict[str, Any]:
    return {
        "Ticker": ticker,
        "Signal Date": signal_date,
        "Signal": signal,
        "Setup": setup,
        "Trade Quality": "GOOD",
        "Technical Score": technical,
        "Actionability Score": actionability,
        "Market Regime": "BULL",
        "Entry Low": entry_low,
        "Entry High": entry_high,
        "Stop Loss": stop,
        "Target 1": target1,
        "Target 2": target2,
        "R:R T1": (target1 - entry_high) / (entry_high - stop),
        "R:R T2": (target2 - entry_high) / (entry_high - stop),
        "RS 60D": 5.0,
    }


def run_self_tests() -> None:
    dates = pd.bdate_range("2020-01-01", periods=7)
    base = pd.DataFrame(
        {
            "Open": [100, 100, 101, 102, 103, 104, 105],
            "High": [101, 102, 103, 104, 105, 106, 107],
            "Low": [99, 99, 100, 101, 102, 103, 104],
            "Close": [100, 101, 102, 103, 104, 105, 106],
            "Volume": [1000] * 7,
        },
        index=dates,
    )
    features = {"AAA": base.copy(), "BBB": base.copy()}
    candidates = pd.DataFrame(
        [
            _synthetic_signal("AAA", dates[0], signal="STRONG BUY", technical=80, actionability=80),
            _synthetic_signal("BBB", dates[0], signal="BUY", technical=95, actionability=95),
            _synthetic_signal("AAA", dates[1], signal="BUY"),
            _synthetic_signal("BBB", dates[1], signal="WATCH"),
        ]
    )
    config = Stage22Config(
        test_start=str(dates[0].date()),
        test_end=str(dates[-1].date()),
        holding_periods=(3,),
        starting_equity=10000.0,
        max_open_positions=1,
        output_directory=Path("."),
    )
    result = PortfolioBacktester(
        config, features, candidates, "T1_3D", "Target 1", 3
    ).run()
    filled = result["orders"][result["orders"]["Status"] == "FILLED"]
    assert not filled.empty and filled.iloc[0]["Ticker"] == "AAA", "STRONG BUY ranking failed"
    assert (result["orders"]["Status"] == "REJECTED_CAPACITY").any(), "capacity rejection missing"
    assert (result["orders"]["Status"] == "IGNORED_ALREADY_OPEN").any(), "open-state duplicate not ignored"
    assert result["max_concurrent_positions"] <= 1, "position capacity exceeded"
    assert (result["trades"]["Quantity"] > 0).all(), "non-positive executed quantity"
    assert np.allclose(
        result["trades"]["Gross PnL"]
        - result["trades"]["Slippage Cost"]
        - result["trades"]["Transaction Cost"],
        result["trades"]["Net PnL"],
    ), "cost reconciliation failed"

    pullback = pd.DataFrame(
        {
            "Open": [101, 105, 102, 103],
            "High": [102, 115, 104, 105],
            "Low": [100, 99, 101, 102],
            "Close": [101, 102, 103, 104],
            "Volume": [1000] * 4,
        },
        index=dates[:4],
    )
    ambiguity_signal = pd.DataFrame(
        [_synthetic_signal("CCC", dates[0], setup="PULLBACK")]
    )
    ambiguity_config = Stage22Config(
        test_start=str(dates[0].date()),
        test_end=str(dates[3].date()),
        holding_periods=(2,),
        starting_equity=10000.0,
    )
    ambiguity = PortfolioBacktester(
        ambiguity_config,
        {"CCC": pullback},
        ambiguity_signal,
        "T1_2D",
        "Target 1",
        2,
    ).run()
    assert len(ambiguity["trades"]) == 1, "ambiguity test trade missing"
    trade = ambiguity["trades"].iloc[0]
    assert bool(trade["Conservative Entry-Bar Ambiguity"]), "ambiguity flag missing"
    assert float(trade["Executed Entry"]) <= float(trade["Buy Limit"]), (
        "pullback buy-limit execution exceeded its ceiling"
    )
    assert math.isclose(float(trade["Executed Entry"]), 100.0), (
        "intraday pullback touch should execute at the buy limit, not above it"
    )
    assert normalize_date(trade["Exit Date"]) > normalize_date(trade["Entry Date"]), (
        "intraday limit target was incorrectly credited on entry bar"
    )
    assert not ambiguity["runtime_errors"], ambiguity["runtime_errors"]
    print("SELF-TESTS: PASS")


def build_strategy_config_payload(
    config: Stage22Config,
    strategy_config: Any,
    stage21_source: Path,
    manifest: Dict[str, Any],
    tickers: Sequence[str],
) -> Dict[str, Any]:
    frozen_strategy = (
        asdict(strategy_config)
        if is_dataclass(strategy_config)
        else dict(vars(strategy_config))
    )
    payload: Dict[str, Any] = {
        "stage": "2.2.1",
        "strategy_threshold_policy": "UNCHANGED_STAGE_2_1",
        "stage21_source": str(stage21_source.resolve()),
        "stage21_source_sha256": sha256_file(stage21_source),
        "frozen_strategy_config": json_safe(frozen_strategy),
        "portfolio_and_execution_config": {
            "test_start": config.test_start,
            "test_end": config.test_end,
            "warmup_anchor_start": config.warmup_anchor_start,
            "warmup_days": config.warmup_days,
            "holding_periods": list(config.holding_periods),
            "starting_equity": config.starting_equity,
            "risk_per_trade": config.risk_per_trade,
            "max_open_positions": config.max_open_positions,
            "max_position_pct": config.max_position_pct,
            "slippage_bps": config.slippage_bps,
            "transaction_cost_bps": config.transaction_cost_bps,
            "annual_risk_free_rate": config.annual_risk_free_rate,
            "pullback_entry_window": config.pullback_entry_window,
            "breakout_gap_limit": config.breakout_gap_limit,
            "parity_tolerance": config.parity_tolerance,
            "data_mode": config.data_mode,
            "candidate_source": "FRESHLY_REGENERATED_ONLY",
            "pullback_limit_semantics": "EXECUTED_ENTRY_NOT_ABOVE_BUY_LIMIT",
            "entry_bar_ambiguity": "TARGET_ONLY_TOUCH_NOT_CREDITED",
        },
        "tickers": list(tickers),
        "data_manifest_sha256": manifest["manifest_sha256"],
    }
    payload["config_sha256"] = canonical_json_hash(payload)
    identity = {
        "config_sha256": payload["config_sha256"],
        "data_manifest_sha256": manifest["manifest_sha256"],
        "test_start": config.test_start,
        "test_end": config.test_end,
    }
    payload["experiment_id"] = (
        f"S221_{normalize_date(config.test_start):%Y%m%d}_"
        f"{normalize_date(config.test_end):%Y%m%d}_"
        f"{canonical_json_hash(identity)[:12]}"
    )
    return payload


def _daily_risk_metrics(
    equity: pd.DataFrame,
    config: Stage22Config,
) -> Dict[str, Any]:
    if equity.empty:
        return {}
    frame = equity.sort_values("Date").copy()
    frame["Date"] = pd.to_datetime(frame["Date"])
    values = pd.to_numeric(frame["Total Equity"], errors="coerce").astype(float)
    returns = pd.to_numeric(frame["Daily Return %"], errors="coerce").fillna(0.0) / 100.0
    elapsed_years = max(
        (frame["Date"].iloc[-1] - frame["Date"].iloc[0]).days / 365.25,
        1.0 / 252.0,
    )
    ending = float(values.iloc[-1])
    cagr = (ending / config.starting_equity) ** (1.0 / elapsed_years) - 1.0
    annual_return = float(returns.mean() * 252.0)
    annual_volatility = float(returns.std(ddof=1) * math.sqrt(252.0))
    daily_rf = (1.0 + config.annual_risk_free_rate) ** (1.0 / 252.0) - 1.0
    excess = returns - daily_rf
    sharpe = (
        float(excess.mean() / returns.std(ddof=1) * math.sqrt(252.0))
        if returns.std(ddof=1) > 0 else np.nan
    )
    sharpe_zero = (
        float(returns.mean() / returns.std(ddof=1) * math.sqrt(252.0))
        if returns.std(ddof=1) > 0 else np.nan
    )
    downside = np.minimum(excess, 0.0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))) * math.sqrt(252.0))
    sortino = (
        float(excess.mean() * 252.0 / downside_deviation)
        if downside_deviation > 0 else np.nan
    )
    running_peak = pd.concat(
        [pd.Series([config.starting_equity]), values.reset_index(drop=True)],
        ignore_index=True,
    ).cummax().iloc[1:].reset_index(drop=True)
    drawdown = values.reset_index(drop=True) / running_peak - 1.0
    bottom_index = int(drawdown.idxmin())
    max_drawdown = float(drawdown.iloc[bottom_index])
    peak_index = int(values.reset_index(drop=True).iloc[: bottom_index + 1].idxmax())
    recovery_index: Optional[int] = None
    peak_value = float(running_peak.iloc[bottom_index])
    recovered = np.flatnonzero(values.reset_index(drop=True).iloc[bottom_index + 1 :].to_numpy() >= peak_value)
    if recovered.size:
        recovery_index = bottom_index + 1 + int(recovered[0])
    longest = 0
    current = 0
    for underwater in (drawdown < -1e-12):
        current = current + 1 if underwater else 0
        longest = max(longest, current)
    max_drawdown_abs = abs(max_drawdown)
    return {
        "Annualized Return %": annual_return * 100.0,
        "CAGR %": cagr * 100.0,
        "Annualized Volatility %": annual_volatility * 100.0,
        "Sharpe Ratio (RF 6%)": sharpe,
        "Sharpe Ratio (RF 0%)": sharpe_zero,
        "Sortino Ratio (RF 6%)": sortino,
        "Maximum Drawdown %": max_drawdown * 100.0,
        "Calmar Ratio": cagr / max_drawdown_abs if max_drawdown_abs > 0 else np.nan,
        "Return / Max Drawdown": (ending / config.starting_equity - 1.0) / max_drawdown_abs if max_drawdown_abs > 0 else np.nan,
        "Drawdown Peak Date": frame["Date"].iloc[peak_index],
        "Drawdown Bottom Date": frame["Date"].iloc[bottom_index],
        "Drawdown Recovery Date": frame["Date"].iloc[recovery_index] if recovery_index is not None else pd.NaT,
        "Recovery Trading Days": recovery_index - bottom_index if recovery_index is not None else np.nan,
        "Longest Below-Peak Trading Days": longest,
        "Best Daily Return %": float(returns.max() * 100.0),
        "Worst Daily Return %": float(returns.min() * 100.0),
        "Positive Trading Days %": float((returns > 0).mean() * 100.0),
        "Negative Trading Days %": float((returns < 0).mean() * 100.0),
    }


def build_portfolio_research_tables(
    config: Stage22Config,
    analyzer: PerformanceAnalyzer,
    portfolio_results: Sequence[Dict[str, Any]],
    nifty_raw: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    risk_rows: List[Dict[str, Any]] = []
    exposure_rows: List[Dict[str, Any]] = []
    turnover_rows: List[Dict[str, Any]] = []
    drawdown_rows: List[Dict[str, Any]] = []
    for result in portfolio_results:
        variant = result["variant"]
        equity = result["equity"].copy()
        trades = result["trades"].copy()
        orders = result["orders"].copy()
        risk = _daily_risk_metrics(equity, config)
        risk_rows.append({"Variant": variant, **risk})
        drawdown_rows.append(
            {"Variant": variant, **{key: value for key, value in risk.items() if "Drawdown" in key or "Below-Peak" in key or "Recovery" in key}}
        )
        positions = pd.to_numeric(equity.get("Number Open Positions"), errors="coerce").fillna(0)
        total_equity = pd.to_numeric(equity.get("Total Equity"), errors="coerce")
        gross = pd.to_numeric(equity.get("Open Position Value"), errors="coerce") / total_equity
        cash_pct = pd.to_numeric(equity.get("Cash"), errors="coerce") / total_equity
        exposure_rows.append(
            {
                "Variant": variant,
                "% Days Any Exposure": float((positions > 0).mean() * 100.0),
                "% Days Fully Cash": float((positions == 0).mean() * 100.0),
                "Average Open Positions": float(positions.mean()),
                "Median Open Positions": float(positions.median()),
                "Maximum Open Positions": int(positions.max()) if len(positions) else 0,
                "% Days At Five Positions": float((positions == config.max_open_positions).mean() * 100.0),
                "Average Gross Exposure %": float(gross.mean() * 100.0),
                "Median Gross Exposure %": float(gross.median() * 100.0),
                "Maximum Gross Exposure %": float(gross.max() * 100.0),
                "Average Cash %": float(cash_pct.mean() * 100.0),
                "Median Cash %": float(cash_pct.median() * 100.0),
                "Capacity Rejections": int((orders.get("Status") == "REJECTED_CAPACITY").sum()) if not orders.empty else 0,
                "Cash Rejections": int((orders.get("Status") == "REJECTED_CASH").sum()) if not orders.empty else 0,
                "Expired Orders": int((orders.get("Status") == "EXPIRED").sum()) if not orders.empty else 0,
            }
        )
        if trades.empty:
            buy_value = sell_value = 0.0
            average_position = average_trade_pct = average_risk_pct = average_actual_risk_pct = np.nan
        else:
            quantity = pd.to_numeric(trades["Quantity"], errors="coerce")
            buy_value = float((pd.to_numeric(trades["Executed Entry"], errors="coerce") * quantity).sum())
            sell_value = float((pd.to_numeric(trades["Executed Exit"], errors="coerce") * quantity).sum())
            position_value = pd.to_numeric(trades["Position Value"], errors="coerce")
            entry_equity = pd.to_numeric(trades["Portfolio Equity At Entry"], errors="coerce")
            actual_risk = pd.to_numeric(trades["Initial Risk Per Share"], errors="coerce") * quantity
            average_position = float(position_value.mean())
            average_trade_pct = float((position_value / entry_equity).mean() * 100.0)
            average_risk_pct = float((pd.to_numeric(trades["Portfolio Risk Budget"], errors="coerce") / entry_equity).mean() * 100.0)
            average_actual_risk_pct = float((actual_risk / entry_equity).mean() * 100.0)
        average_equity = float(total_equity.mean()) if len(total_equity) else config.starting_equity
        years = max((normalize_date(config.test_end) - normalize_date(config.test_start)).days / 365.25, 1.0 / 252.0)
        two_way = buy_value + sell_value
        turnover_rows.append(
            {
                "Variant": variant,
                "Total Buy Value": buy_value,
                "Total Sell Value": sell_value,
                "Two-Way Turnover Value": two_way,
                "Two-Way Turnover / Average Equity": two_way / average_equity if average_equity else np.nan,
                "Annualized Two-Way Turnover": two_way / average_equity / years if average_equity else np.nan,
                "Average Position Value": average_position,
                "Average Trade Capital %": average_trade_pct,
                "Average Configured Risk Budget %": average_risk_pct,
                "Average Actual Initial Risk Used %": average_actual_risk_pct,
            }
        )

    nifty = nifty_raw.copy()
    nifty.index = pd.to_datetime(nifty.index).tz_localize(None).normalize()
    nifty = nifty.loc[(nifty.index >= normalize_date(config.test_start)) & (nifty.index <= normalize_date(config.test_end))]
    close = pd.to_numeric(nifty["Close"], errors="coerce").dropna()
    nifty_equity = pd.DataFrame()
    if not close.empty:
        benchmark_values = config.starting_equity * close / float(close.iloc[0])
        benchmark_returns = benchmark_values.pct_change().fillna(0.0) * 100.0
        benchmark_peak = benchmark_values.cummax()
        nifty_equity = pd.DataFrame(
            {
                "Date": close.index,
                "Total Equity": benchmark_values.values,
                "Daily Return %": benchmark_returns.values,
                "Drawdown %": (benchmark_values / benchmark_peak - 1.0).values * 100.0,
            }
        )
    benchmark_metrics = _daily_risk_metrics(nifty_equity, config) if not nifty_equity.empty else {}
    benchmark_row = {
        "Benchmark": "NIFTY 50 PRICE INDEX (^NSEI)",
        "Start Close": float(close.iloc[0]) if not close.empty else np.nan,
        "End Close": float(close.iloc[-1]) if not close.empty else np.nan,
        "Net Return %": (float(close.iloc[-1] / close.iloc[0] - 1.0) * 100.0) if not close.empty else np.nan,
        **benchmark_metrics,
        "Dividend Treatment": "Price-index comparison; dividends excluded",
    }
    portfolio_summary = analyzer.portfolio_summary().drop(columns=["CAGR %", "Maximum Drawdown %"], errors="ignore")
    risk_frame = pd.DataFrame(risk_rows)
    portfolio_summary = portfolio_summary.merge(risk_frame, on="Variant", how="left")
    comparison = portfolio_summary[["Variant", "Net Return %", "CAGR %", "Maximum Drawdown %", "Sharpe Ratio (RF 6%)", "Sortino Ratio (RF 6%)", "Calmar Ratio"]].copy()
    for key in ["Net Return %", "CAGR %", "Maximum Drawdown %", "Sharpe Ratio (RF 6%)", "Sortino Ratio (RF 6%)", "Calmar Ratio"]:
        comparison[f"NIFTY {key}"] = benchmark_row.get(key, np.nan)
    comparison["Excess Net Return vs NIFTY %"] = comparison["Net Return %"] - comparison["NIFTY Net Return %"]
    comparison["Benchmark Note"] = benchmark_row["Dividend Treatment"]
    return {
        "portfolio_summary": portfolio_summary,
        "risk_metrics": risk_frame,
        "exposure_summary": pd.DataFrame(exposure_rows),
        "turnover_summary": pd.DataFrame(turnover_rows),
        "drawdown_summary": pd.DataFrame(drawdown_rows),
        "nifty_benchmark": pd.DataFrame([benchmark_row]),
        "benchmark_comparison": comparison,
        "nifty_equity": nifty_equity,
    }


def build_fill_summary(orders: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame()
    rows: List[Dict[str, Any]] = []
    for dimension, column in [
        ("Signal", "Signal"), ("Setup", "Setup"),
        ("Market Regime", "Market Regime"), ("Ticker", "Ticker"),
    ]:
        for (variant, group_value), group in orders.groupby(["Variant", column], dropna=False, sort=True):
            status = group["Status"].astype(str)
            created = ~(status.str.startswith("IGNORED") | status.eq("INVALID_DATA"))
            sessions = pd.to_numeric(group.loc[status.eq("FILLED"), "Trading Sessions to Fill"], errors="coerce")
            created_count = int(created.sum())
            filled_count = int(status.eq("FILLED").sum())
            rows.append(
                {
                    "Variant": variant,
                    "Dimension": dimension,
                    "Group": group_value,
                    "Signals": int(len(group)),
                    "Orders Created": created_count,
                    "Filled": filled_count,
                    "Expired": int(status.eq("EXPIRED").sum()),
                    "Capacity Rejections": int(status.eq("REJECTED_CAPACITY").sum()),
                    "Cash Rejections": int(status.eq("REJECTED_CASH").sum()),
                    "Already Open Ignored": int(status.eq("IGNORED_ALREADY_OPEN").sum()),
                    "Already Pending Ignored": int(status.eq("IGNORED_ALREADY_PENDING").sum()),
                    "Fill Rate %": filled_count / created_count * 100.0 if created_count else np.nan,
                    "Average Trading Sessions to Fill": float(sessions.mean()) if not sessions.empty else np.nan,
                    "Median Trading Sessions to Fill": float(sessions.median()) if not sessions.empty else np.nan,
                }
            )
    return pd.DataFrame(rows)


def add_period_flags(frame: pd.DataFrame, pnl_frame: pd.DataFrame, period_column: str) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        return result
    if not pnl_frame.empty:
        result = result.merge(pnl_frame, on=["Variant", period_column], how="left")
    result["Negative Expectancy Flag"] = pd.to_numeric(result["Expectancy R"], errors="coerce") < 0
    result["Profit Factor Below One Flag"] = pd.to_numeric(result["Profit Factor"], errors="coerce") < 1
    result["Negative Return Flag"] = pd.to_numeric(result["Net Return %"], errors="coerce") < 0
    return result


class Stage221Validator:
    def __init__(
        self,
        config: Stage22Config,
        candidates: pd.DataFrame,
        portfolio_results: Sequence[Dict[str, Any]],
        manifest_ok: bool,
        manifest_errors: Sequence[str],
        manifest: Dict[str, Any],
        loaded_hashes: Dict[str, str],
        reference_ok: bool,
        reference_details: Dict[str, Any],
        parity_summary: Dict[str, Any],
        stage21_hash_before: str,
        stage21_hash_after: str,
    ) -> None:
        self.config = config
        self.candidates = candidates
        self.results = list(portfolio_results)
        self.manifest_ok = manifest_ok
        self.manifest_errors = list(manifest_errors)
        self.manifest = manifest
        self.loaded_hashes = loaded_hashes
        self.reference_ok = reference_ok
        self.reference_details = reference_details
        self.parity_summary = parity_summary
        self.stage21_hash_before = stage21_hash_before
        self.stage21_hash_after = stage21_hash_after
        self.checks: List[Dict[str, str]] = []

    def _add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append({"Check": name, "Status": status, "Detail": detail})

    def run(self, runtime_seconds: float) -> Tuple[bool, pd.DataFrame, str]:
        expected_hashes = {item["ticker"]: item["sha256"] for item in self.manifest.get("files", [])}
        loaded_match = all(expected_hashes.get(ticker) == digest for ticker, digest in self.loaded_hashes.items())
        self._add("Frozen manifest and file hashes", "PASS" if self.manifest_ok else "FAIL", "; ".join(self.manifest_errors[:5]))
        self._add("Strategy and execution use same frozen dataset", "PASS" if loaded_match and self.config.data_mode == "FROZEN" else "FAIL", f"loaded_files={len(self.loaded_hashes)}")
        self._add("Stage 2.1 source unchanged during run", "PASS" if self.stage21_hash_before == self.stage21_hash_after else "FAIL", self.stage21_hash_after)
        self._add("Reference log integrity", "PASS" if self.reference_ok else "FAIL", json.dumps(self.reference_details, default=str))
        parity_differences = int(self.parity_summary.get("rows_with_any_difference", 0))
        parity_status = "PASS" if parity_differences == 0 else "WARN"
        self._add("Fresh regeneration vs saved reference", parity_status, f"differences={parity_differences}; reference is diagnostic only")

        orders = pd.concat([r["orders"] for r in self.results if not r["orders"].empty], ignore_index=True) if any(not r["orders"].empty for r in self.results) else pd.DataFrame()
        trades = pd.concat([r["trades"] for r in self.results if not r["trades"].empty], ignore_index=True) if any(not r["trades"].empty for r in self.results) else pd.DataFrame()
        equity = pd.concat([r["equity"] for r in self.results if not r["equity"].empty], ignore_index=True) if any(not r["equity"].empty for r in self.results) else pd.DataFrame()
        runtime_errors = list(dict.fromkeys(error for r in self.results for error in r["runtime_errors"]))
        dates = pd.to_datetime(self.candidates["Signal Date"]) if not self.candidates.empty else pd.Series([], dtype="datetime64[ns]")
        point_in_time = not dates.empty and dates.min() >= normalize_date(self.config.test_start) and dates.max() <= normalize_date(self.config.test_end)
        self._add("Point-in-time signal date window", "PASS" if point_in_time else "FAIL")
        entry_after = trades.empty or bool((pd.to_datetime(trades["Entry Date"]) > pd.to_datetime(trades["Signal Date"])).all())
        self._add("Entries strictly after signal dates", "PASS" if entry_after else "FAIL")
        no_watch = trades.empty or bool(trades["Signal"].isin(PRIMARY_SIGNALS).all())
        self._add("No WATCH trades in primary portfolios", "PASS" if no_watch else "FAIL")
        positive_quantity = trades.empty or bool((pd.to_numeric(trades["Quantity"], errors="coerce") > 0).all())
        self._add("Positive executed quantities", "PASS" if positive_quantity else "FAIL")
        max_positions = equity.empty or bool((pd.to_numeric(equity["Number Open Positions"], errors="coerce") <= self.config.max_open_positions).all())
        self._add("Maximum concurrent positions", "PASS" if max_positions else "FAIL")
        cash_ok = equity.empty or bool((pd.to_numeric(equity["Cash"], errors="coerce") >= -1e-7).all())
        self._add("Cash never materially negative", "PASS" if cash_ok else "FAIL")
        equity_ok = equity.empty or bool(np.allclose(pd.to_numeric(equity["Cash"]) + pd.to_numeric(equity["Open Position Value"]), pd.to_numeric(equity["Total Equity"]), atol=1e-6, rtol=1e-10))
        self._add("Daily full-equity reconciliation", "PASS" if equity_ok else "FAIL")
        duplicate_equity = equity.duplicated(["Variant", "Date"]).any() if not equity.empty else False
        self._add("One equity row per variant/session", "PASS" if not duplicate_equity else "FAIL")

        overlap_errors: List[str] = []
        if not trades.empty:
            for (variant, ticker), group in trades.groupby(["Variant", "Ticker"]):
                prior_exit: Optional[pd.Timestamp] = None
                for _, row in group.sort_values("Entry Date").iterrows():
                    entry_date = normalize_date(row["Entry Date"])
                    if prior_exit is not None and entry_date <= prior_exit:
                        overlap_errors.append(f"{variant}:{ticker}:{entry_date.date()}")
                    prior_exit = normalize_date(row["Exit Date"])
        self._add("No overlapping same-ticker positions", "PASS" if not overlap_errors else "FAIL", "; ".join(overlap_errors[:5]))
        pending_overlap = [e for e in runtime_errors if "pending/open overlap" in e]
        self._add("No pending/open same-ticker overlap", "PASS" if not pending_overlap else "FAIL", "; ".join(pending_overlap[:5]))

        if trades.empty:
            stop_ok = targets_ok = slippage_ok = cost_ok = limit_ok = True
        else:
            stop_ok = bool((pd.to_numeric(trades["Stop"]) < pd.to_numeric(trades["Executed Entry"])).all())
            targets_ok = bool((pd.to_numeric(trades["Target"]) > pd.to_numeric(trades["Executed Entry"])).all())
            slippage_ok = bool(np.allclose(pd.to_numeric(trades["Slippage Cost"]), pd.to_numeric(trades["Entry Slippage Cost"]) + pd.to_numeric(trades["Exit Slippage Cost"]), atol=1e-6, rtol=1e-10))
            expected_net = pd.to_numeric(trades["Gross PnL"]) - pd.to_numeric(trades["Slippage Cost"]) - pd.to_numeric(trades["Transaction Cost"])
            cost_ok = bool(np.allclose(expected_net, pd.to_numeric(trades["Net PnL"]), atol=1e-6, rtol=1e-10))
            pullbacks = trades[trades["Setup"] == "PULLBACK"]
            limit_ok = pullbacks.empty or bool((pd.to_numeric(pullbacks["Executed Entry"]) <= pd.to_numeric(pullbacks["Buy Limit"]) + 1e-10).all())
        self._add("Stops below executed entry", "PASS" if stop_ok else "FAIL")
        self._add("Targets above executed entry", "PASS" if targets_ok else "FAIL")
        t2 = self.candidates[self.candidates["Signal"].isin(PRIMARY_SIGNALS) & self.candidates["Setup"].isin(VALID_SETUPS)] if not self.candidates.empty else pd.DataFrame()
        t2_ok = t2.empty or bool((pd.to_numeric(t2["Target 2"], errors="coerce") > pd.to_numeric(t2["Target 1"], errors="coerce")).all())
        self._add("T2 strictly above T1", "PASS" if t2_ok else "FAIL")
        self._add("Pullback fills do not exceed buy limit", "PASS" if limit_ok else "FAIL")
        self._add("Slippage charged once", "PASS" if slippage_ok else "FAIL")
        self._add("Transaction costs and net PnL reconcile", "PASS" if cost_ok else "FAIL")
        self._add("Runtime state invariants", "PASS" if not runtime_errors else "FAIL", "; ".join(runtime_errors[:5]))
        self._add("Benchmark runtime completed", "PASS", f"{runtime_seconds:.3f} seconds")
        overall = not any(row["Status"] == "FAIL" for row in self.checks)
        label = "PASS" if overall and not any(row["Status"] == "WARN" for row in self.checks) else "PASS WITH WARNINGS" if overall else "FAIL"
        report = "\n".join([
            "STAGE 2.2.1 VALIDATION", "-" * 96,
            *[f"{row['Check']:<48} {row['Status']:<5} {row['Detail']}".rstrip() for row in self.checks],
            "-" * 96, f"OVERALL VALIDATION: {label}", "", SURVIVORSHIP_WARNING,
        ])
        return overall, pd.DataFrame(self.checks), report


def save_stage221_outputs(
    config: Stage22Config,
    candidate_log: pd.DataFrame,
    data_availability: pd.DataFrame,
    parity_differences: pd.DataFrame,
    parity_summary: Dict[str, Any],
    analyzer: PerformanceAnalyzer,
    portfolio_results: Sequence[Dict[str, Any]],
    research_tables: Dict[str, pd.DataFrame],
    validation_checks: pd.DataFrame,
    validation_report: str,
    runtime_seconds: float,
    manifest: Dict[str, Any],
    strategy_config_payload: Dict[str, Any],
) -> Dict[str, Path]:
    output = config.output_directory
    output.mkdir(parents=True, exist_ok=True)
    candidate_tables = analyzer.candidate_tables()
    diagnostics = analyzer.diagnostic_tables()
    yearly = analyzer.yearly_summary()
    period = analyzer.period_summary()
    all_trades = analyzer.trades.copy()
    if not all_trades.empty:
        all_trades["Exit Date"] = pd.to_datetime(all_trades["Exit Date"])
        yearly_pnl = all_trades.assign(Year=all_trades["Exit Date"].dt.year).groupby(["Variant", "Year"], as_index=False)["Net PnL"].sum()
        yearly_pnl = yearly_pnl.rename(columns={"Net PnL": "Net PnL"})
        period_map = []
        for label, first, last in [("2011-2015", 2011, 2015), ("2016-2020", 2016, 2020), ("2021-2023", 2021, 2023), ("2024-2026", 2024, 2026)]:
            subset = all_trades[all_trades["Exit Date"].dt.year.between(first, last)]
            if not subset.empty:
                grouped = subset.groupby("Variant", as_index=False)["Net PnL"].sum()
                grouped["Period"] = label
                period_map.append(grouped)
        period_pnl = pd.concat(period_map, ignore_index=True) if period_map else pd.DataFrame(columns=["Variant", "Period", "Net PnL"])
    else:
        yearly_pnl = pd.DataFrame(columns=["Variant", "Year", "Net PnL"])
        period_pnl = pd.DataFrame(columns=["Variant", "Period", "Net PnL"])
    yearly = add_period_flags(yearly, yearly_pnl, "Year")
    period = add_period_flags(period, period_pnl, "Period")
    files: Dict[str, pd.DataFrame] = {
        f"{STAGE221_PREFIX}_candidate_signal_log.csv": candidate_log,
        f"{STAGE221_PREFIX}_candidate_outcome_summary.csv": candidate_tables["candidate_outcome_summary"],
        f"{STAGE221_PREFIX}_signal_type_summary.csv": candidate_tables["signal_type_summary"],
        f"{STAGE221_PREFIX}_score_band_summary.csv": candidate_tables["score_band_summary"],
        f"{STAGE221_PREFIX}_score_matrix.csv": candidate_tables["score_matrix"],
        f"{STAGE221_PREFIX}_order_log.csv": analyzer.orders,
        f"{STAGE221_PREFIX}_portfolio_trade_log.csv": analyzer.trades,
        f"{STAGE221_PREFIX}_portfolio_summary.csv": research_tables["portfolio_summary"],
        f"{STAGE221_PREFIX}_daily_risk_metrics.csv": research_tables["risk_metrics"],
        f"{STAGE221_PREFIX}_benchmark_comparison.csv": research_tables["benchmark_comparison"],
        f"{STAGE221_PREFIX}_nifty_benchmark.csv": research_tables["nifty_benchmark"],
        f"{STAGE221_PREFIX}_nifty_daily_equity.csv": research_tables["nifty_equity"],
        f"{STAGE221_PREFIX}_exposure_summary.csv": research_tables["exposure_summary"],
        f"{STAGE221_PREFIX}_turnover_summary.csv": research_tables["turnover_summary"],
        f"{STAGE221_PREFIX}_drawdown_summary.csv": research_tables["drawdown_summary"],
        f"{STAGE221_PREFIX}_fill_summary.csv": build_fill_summary(analyzer.orders),
        f"{STAGE221_PREFIX}_yearly_summary.csv": yearly,
        f"{STAGE221_PREFIX}_period_summary.csv": period,
        f"{STAGE221_PREFIX}_stock_summary.csv": diagnostics["stock_summary"],
        f"{STAGE221_PREFIX}_setup_summary.csv": diagnostics["setup_summary"],
        f"{STAGE221_PREFIX}_regime_summary.csv": diagnostics["regime_summary"],
        f"{STAGE221_PREFIX}_data_availability.csv": data_availability,
        f"{STAGE221_PREFIX}_signal_parity_differences.csv": parity_differences,
        f"{STAGE221_PREFIX}_signal_parity_summary.csv": pd.DataFrame([parity_summary]),
        f"{STAGE221_PREFIX}_validation_checks.csv": validation_checks,
    }
    for result in portfolio_results:
        files[f"{STAGE221_PREFIX}_daily_equity_{result['variant']}.csv"] = result["equity"]
    written: Dict[str, Path] = {}
    for filename, frame in files.items():
        path = output / filename
        prepared = frame.copy()
        prepared.insert(0, "Experiment ID", config.experiment_id)
        prepared["Config SHA-256"] = config.config_hash
        prepared["Data Manifest SHA-256"] = config.data_manifest_hash
        prepared["Survivorship Bias Warning"] = SURVIVORSHIP_WARNING
        prepared.to_csv(path, index=False)
        written[filename] = path
    report_path = output / f"{STAGE221_PREFIX}_validation_report.txt"
    report_path.write_text(validation_report + f"\n\nExperiment ID: {config.experiment_id}\nRuntime seconds: {runtime_seconds:.3f}\nTest window: {config.test_start} through {config.test_end}\n", encoding="utf-8")
    written[report_path.name] = report_path
    methodology_path = output / f"{STAGE221_PREFIX}_methodology_notes.txt"
    methodology_path.write_text(
        "STAGE 2.2.1 METHODOLOGY NOTES\n" + "=" * 72 + "\n" + SURVIVORSHIP_WARNING + "\n\n"
        "All strategy and execution inputs are read from the same SHA-256-verified frozen OHLC snapshot.\n"
        "Candidate signals are freshly regenerated through the unchanged Stage 2.1 FrozenStrategy.\n"
        "The saved Stage 2.1 signal log is read-only and used only for integrity and parity diagnostics.\n"
        "Primary entries are BUY and STRONG BUY only. Ten independent portfolios test T1/T2 over 10/20/30/45/63 sessions.\n"
        "Pullback fills are buy-limit orders and never execute above the planned Entry High.\n"
        "An intraday pullback entry-bar target-only touch is not credited; stop collisions are conservative.\n"
        "Daily risk measures use total portfolio equity including cash and open positions. Sharpe/Sortino use a 6% annual risk-free rate; an RF=0 Sharpe is also reported.\n"
        "The NIFTY comparison uses the frozen ^NSEI price index and excludes dividends.\n",
        encoding="utf-8",
    )
    written[methodology_path.name] = methodology_path
    manifest_copy = output / f"{STAGE221_PREFIX}_data_manifest.json"
    config_copy = output / f"{STAGE221_PREFIX}_strategy_config.json"
    write_json(manifest_copy, manifest)
    write_json(config_copy, strategy_config_payload)
    written[manifest_copy.name] = manifest_copy
    written[config_copy.name] = config_copy
    return written


def run_pipeline(args: argparse.Namespace) -> bool:
    started = time.perf_counter()
    stage21_source = Path(args.stage21_source)
    reference_signal_log = Path(args.reference_signal_log)
    output_directory = Path(args.output_dir)
    tickers = tuple(
        value.strip() for value in args.tickers.split(",") if value.strip()
    ) if args.tickers else DEFAULT_UNIVERSE
    data_mode = args.data_mode.upper()
    frozen_data_directory = Path(args.frozen_data_dir)
    refresh_root_directory = Path(args.refresh_root_dir)
    if data_mode == "FROZEN":
        active_data_directory = frozen_data_directory
        manifest_path = Path(args.manifest_path) if args.manifest_path else active_data_directory / "manifest.json"
    else:
        timestamp = datetime.now(timezone.utc).strftime("refresh_%Y%m%dT%H%M%SZ")
        active_data_directory = refresh_root_directory / timestamp
        active_data_directory.mkdir(parents=True, exist_ok=False)
        manifest_path = active_data_directory / "manifest.json"
    config = Stage22Config(
        test_start=args.test_start,
        test_end=args.test_end,
        warmup_anchor_start=args.warmup_anchor_start,
        starting_equity=args.starting_equity,
        risk_per_trade=args.risk_per_trade,
        max_open_positions=args.max_open_positions,
        max_position_pct=args.max_position_pct,
        output_directory=output_directory,
        cache_directory=active_data_directory,
        reference_signal_log=reference_signal_log,
        candidate_source="generated",
        data_mode=data_mode,
        frozen_data_directory=frozen_data_directory,
        refresh_root_directory=refresh_root_directory,
        data_manifest_path=manifest_path,
    )

    if not reference_signal_log.exists():
        raise FileNotFoundError(f"Reference signal log not found: {reference_signal_log}")
    reference_ok, reference_details = check_reference_integrity(reference_signal_log)
    stage21_hash_before = sha256_file(stage21_source)
    stage21 = load_stage21_module(stage21_source)

    manifest: Dict[str, Any]
    manifest_ok = False
    manifest_errors: List[str] = []
    if data_mode == "FROZEN":
        if not manifest_path.exists():
            # The official manifest always covers the complete universe, even for
            # a one/two-ticker sanity run.
            manifest = build_data_manifest(
                active_data_directory, DEFAULT_UNIVERSE, config, stage21
            )
            write_json(manifest_path, manifest)
            print(f"Created immutable data manifest: {manifest_path.resolve()}")
        else:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_ok, manifest_errors = verify_data_manifest(active_data_directory, manifest)
        if not manifest_ok:
            raise RuntimeError("Frozen data verification failed: " + "; ".join(manifest_errors))

    candidate_engine = CandidateSignalEngine(stage21, config, tickers)
    candidate_engine.load_data()
    if data_mode == "REFRESH":
        manifest = build_data_manifest(active_data_directory, tickers, config, stage21)
        manifest["data_mode"] = "REFRESH_SNAPSHOT"
        unhashed = dict(manifest)
        unhashed.pop("manifest_sha256", None)
        manifest["manifest_sha256"] = canonical_json_hash(unhashed)
        write_json(manifest_path, manifest)
        manifest_ok, manifest_errors = verify_data_manifest(active_data_directory, manifest)
        if not manifest_ok:
            raise RuntimeError("Refresh snapshot verification failed: " + "; ".join(manifest_errors))
    candidate_engine.precompute()
    generated_candidates = candidate_engine.generate()
    if generated_candidates.empty:
        raise RuntimeError("Fresh Stage 2.1 regeneration produced no candidate signals")
    parity_differences, parity_summary, parity_severity = analyze_signal_parity(
        generated_candidates,
        reference_signal_log,
        tickers,
        normalize_date(config.test_start),
        normalize_date(config.test_end),
        config.parity_tolerance,
    )
    print(
        "Fresh regeneration vs saved reference: "
        + parity_severity
        + f" ({parity_summary['rows_with_any_difference']} differing rows)"
    )
    candidates = generated_candidates

    strategy_config_payload = build_strategy_config_payload(
        config, candidate_engine.strategy_config, stage21_source, manifest, tickers
    )
    config.config_hash = strategy_config_payload["config_sha256"]
    config.experiment_id = strategy_config_payload["experiment_id"]
    config.data_manifest_hash = manifest["manifest_sha256"]
    print(f"Experiment ID : {config.experiment_id}")
    print(f"Config hash   : {config.config_hash}")
    print(f"Dataset hash  : {config.data_manifest_hash}")

    print("\nGenerating independent candidate research outcomes...")
    candidate_log = CandidateOutcomeEngine(
        config, candidate_engine.engine.features
    ).run(candidates)

    print("\nRunning independent chronological portfolio variants...")
    portfolio_results = run_portfolios(
        config, candidate_engine.engine.features, candidates
    )
    analyzer = PerformanceAnalyzer(config, candidate_log, portfolio_results)
    research_tables = build_portfolio_research_tables(
        config, analyzer, portfolio_results, candidate_engine.engine.raw_data["^NSEI"]
    )
    runtime_seconds = time.perf_counter() - started
    manifest_ok_after, manifest_errors_after = verify_data_manifest(active_data_directory, manifest)
    manifest_ok = manifest_ok and manifest_ok_after
    manifest_errors = list(dict.fromkeys([*manifest_errors, *manifest_errors_after]))
    validator = Stage221Validator(
        config=config,
        candidates=candidates,
        portfolio_results=portfolio_results,
        manifest_ok=manifest_ok,
        manifest_errors=manifest_errors,
        manifest=manifest,
        loaded_hashes=candidate_engine.loaded_file_hashes,
        reference_ok=reference_ok,
        reference_details=reference_details,
        parity_summary=parity_summary,
        stage21_hash_before=stage21_hash_before,
        stage21_hash_after=sha256_file(stage21_source),
    )
    overall, validation_checks, validation_report = validator.run(runtime_seconds)
    written = save_stage221_outputs(
        config,
        candidate_log,
        pd.DataFrame(candidate_engine.data_availability),
        parity_differences,
        parity_summary,
        analyzer,
        portfolio_results,
        research_tables,
        validation_checks,
        validation_report,
        runtime_seconds,
        manifest,
        strategy_config_payload,
    )

    print("\n" + validation_report)
    summary = research_tables["portfolio_summary"]
    if not summary.empty:
        columns = [
            "Variant", "Ending Equity", "Net Return %", "Total Trades",
            "Win Rate %", "Expectancy R", "Profit Factor", "Maximum Drawdown %",
        ]
        print("\nPORTFOLIO SUMMARY")
        print("-" * 110)
        print(summary[columns].to_string(index=False))
    print(f"\nRuntime: {runtime_seconds:.2f} seconds")
    print(f"Outputs: {config.output_directory.resolve()}")
    print(f"Files written: {len(written)}")
    return overall


def build_parser() -> argparse.ArgumentParser:
    script_dir = Path(__file__).resolve().parent
    stage221_root = script_dir / "stage2_2_1"
    project_stage2 = Path.home() / "Documents" / "Stock Alert App" / "Stage 2"
    stage21_default = script_dir / "Stock_Alert_Stage2_1_Optimized_15Y.py"
    reference_default = script_dir / "stage2_1_signal_log_15y.csv"
    if not stage21_default.exists():
        stage21_default = project_stage2 / "Stock_Alert_Stage2_1_Optimized_15Y.py"
    if not reference_default.exists():
        reference_default = project_stage2 / "stage2_1_signal_log_15y.csv"
    parser = argparse.ArgumentParser(
        description="Stage 2.2.1 reproducible stock-alert portfolio benchmark"
    )
    parser.add_argument(
        "--stage21-source",
        default=str(stage21_default),
    )
    parser.add_argument(
        "--reference-signal-log",
        default=str(reference_default),
    )
    parser.add_argument("--output-dir", default=str(stage221_root / "results"))
    parser.add_argument("--data-mode", choices=("FROZEN", "REFRESH"), default="FROZEN")
    parser.add_argument("--frozen-data-dir", default=str(stage221_root / "data" / "frozen"))
    parser.add_argument("--refresh-root-dir", default=str(stage221_root / "data"))
    parser.add_argument("--manifest-path", default="")
    parser.add_argument("--test-start", default=OFFICIAL_TEST_START)
    parser.add_argument("--test-end", default=OFFICIAL_TEST_END)
    parser.add_argument("--warmup-anchor-start", default="2011-08-30")
    parser.add_argument("--tickers", default=", ".join(DEFAULT_UNIVERSE))
    parser.add_argument("--starting-equity", type=float, default=100000.0)
    parser.add_argument("--risk-per-trade", type=float, default=0.0075)
    parser.add_argument("--max-open-positions", type=int, default=5)
    parser.add_argument("--max-position-pct", type=float, default=0.25)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        run_self_tests()
        return 0
    try:
        passed = run_pipeline(args)
    except Exception as exc:
        print(f"STAGE 2.2.1 FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
