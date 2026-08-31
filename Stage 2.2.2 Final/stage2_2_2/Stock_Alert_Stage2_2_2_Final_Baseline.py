"""Stage 2.2.2: reproducibility and baseline hardening.

The accepted Stage 2.2.1 portfolio engine and the exact Stage 2.1 strategy core
are reused without threshold or rule changes.  This layer adds immutable-data
enforcement, stable experiment identity, point-in-time audits, independent
validation, Stage 2.2.1 acceptance parity, diagnostic benchmarks, and friction
sensitivity.  It is research software, not investment advice.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as importlib_metadata
import importlib.util
import json
import math
import platform
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


STAGE = "2.2.2 Final"
PREFIX = "stage2_2_2_final"
EXPECTED_STAGE21_HASH = (
    "91d3d84760c4b2427d500f0bee0f2dc0ceeb7e4f2e31d51d17a64342777993d5"
)
EXPECTED_STAGE221_HASH = (
    "8e6514353cc32a5b8bed1212df0c12d76de11d0624e4931fda4028f0be3ed31f"
)
ACCEPTED_STAGE222_HASH = (
    "80b9ba6e412486dd19390ad2c74c84b20a56afdec0c0a0938fff0f6a213badfb"
)
OFFICIAL_START = "2011-08-30"
OFFICIAL_END = "2026-08-28"
OFFICIAL_SLIPPAGE_BPS = 5.0
OFFICIAL_TRANSACTION_BPS = 5.0
FRICTION_MULTIPLIERS = (0.5, 1.0, 1.5, 2.0)
STRATEGY_VERSION = "STAGE_2_1_FROZEN"
PRIMARY_SIGNALS = frozenset({"BUY", "STRONG BUY"})
SURVIVORSHIP_WARNING = (
    "This test uses the supplied/current ticker universe and is not a "
    "survivorship-bias-free historical index-constituent study."
)
DEFAULT_UNIVERSE = (
    "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS",
    "ICICIBANK.NS", "HDFCBANK.NS", "SBIN.NS", "AXISBANK.NS",
    "BEL.NS", "HAL.NS", "LT.NS", "ITC.NS", "TITAN.NS",
    "HINDUNILVR.NS", "M&M.NS", "MARUTI.NS", "TMPV.NS", "TMCV.NS",
    "SUNPHARMA.NS", "CIPLA.NS",
)
POINT_IN_TIME_TICKERS = (
    "TCS.NS", "INFY.NS", "HDFCBANK.NS", "LT.NS", "TITAN.NS", "HAL.NS",
)
POINT_IN_TIME_ERAS = (
    ("2012-2015", "2012-01-01", "2015-12-31"),
    ("2016-2020", "2016-01-01", "2020-12-31"),
    ("2021-2023", "2021-01-01", "2023-12-31"),
    ("2024-2026", "2024-01-01", "2026-08-28"),
)
STRATEGY_FIELDS = (
    "min_daily_history", "rsi_period", "atr_period", "adx_period",
    "supertrend_period", "supertrend_multiplier", "sma20_period",
    "sma50_period", "sma200_period", "volume_period", "rs20_period",
    "rs60_period", "rs120_period", "pullback_lookback",
    "pullback_max_distance_20dma", "breakout_lookback", "breakout_buffer",
    "breakout_volume_ratio", "breakout_max_extension", "extension_distance",
    "overextended_rsi", "atr_stop_multiplier", "stop_buffer_pct",
    "minimum_t1_rr", "preferred_t1_rr", "strong_buy_technical",
    "strong_buy_actionability", "buy_technical", "buy_actionability",
    "watch_technical", "watch_actionability",
)
METADATA_COLUMNS = {
    "Experiment ID", "Config SHA-256", "Data Manifest SHA-256",
    "Survivorship Bias Warning", "STRATEGY_HASH", "EXECUTION_HASH",
    "STAGE21_CODE_HASH", "STAGE221_CODE_HASH", "STAGE222_CODE_HASH", "DATA_CONTENT_HASH",
    "MANIFEST_DOCUMENT_HASH",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def normalize_date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize(None).normalize()


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(value), indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def import_source(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_signal_id(row: Dict[str, Any] | pd.Series) -> str:
    date_text = normalize_date(row["Signal Date"]).strftime("%Y%m%d")
    payload = {
        "strategy_version": STRATEGY_VERSION,
        "ticker": str(row["Ticker"]),
        "signal_date": date_text,
        "signal": str(row.get("Signal", "")),
        "setup": str(row.get("Setup", "")),
    }
    return "SIG_" + canonical_hash(payload)[:24]


def add_signal_ids(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        result["Signal ID"] = pd.Series(dtype=str)
        return result
    result["Signal ID"] = [make_signal_id(row) for _, row in result.iterrows()]
    return result


def carry_signal_ids(frame: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        result["Signal ID"] = pd.Series(dtype=str)
        return result
    mapping = candidates[["Ticker", "Signal Date", "Signal ID"]].copy()
    mapping["Signal Date"] = pd.to_datetime(mapping["Signal Date"]).dt.normalize()
    mapping = mapping.drop_duplicates(["Ticker", "Signal Date"])
    result["Signal Date"] = pd.to_datetime(result["Signal Date"]).dt.normalize()
    result = result.merge(mapping, on=["Ticker", "Signal Date"], how="left")
    return result


def environment_report() -> Dict[str, Any]:
    def version(name: str) -> str:
        try:
            return importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            return "NOT_INSTALLED"

    report = {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "yfinance": version("yfinance"),
        },
        "timezone": "Asia/Calcutta",
    }
    if report["packages"]["yfinance"] in {"UNKNOWN", "NOT_INSTALLED"}:
        raise RuntimeError("Exact yfinance version is required and cannot be UNKNOWN")
    return report


def manifest_hashes(manifest: Dict[str, Any]) -> Tuple[str, str]:
    document_hash = canonical_hash(manifest)
    content = [
        {"ticker": item["ticker"], "filename": item["filename"], "sha256": item["sha256"]}
        for item in sorted(manifest.get("files", []), key=lambda row: row["ticker"])
    ]
    return canonical_hash(content), document_hash


def verify_frozen_manifest(
    data_dir: Path, manifest_path: Path, expected_tickers: Optional[Sequence[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Frozen manifest missing: {manifest_path}. "
            "Use --create-frozen-snapshot explicitly; FROZEN runs never auto-create it."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    embedded = manifest.get("manifest_sha256", "")
    unhashed = dict(manifest)
    unhashed.pop("manifest_sha256", None)
    if canonical_hash(unhashed) != embedded:
        raise RuntimeError("Frozen manifest canonical hash mismatch")
    hashes: Dict[str, str] = {}
    for item in manifest.get("files", []):
        path = data_dir / item["filename"]
        if not path.exists():
            raise FileNotFoundError(f"Frozen file missing: {item['filename']}")
        actual = sha256_file(path)
        if actual != item["sha256"]:
            raise RuntimeError(f"Frozen file hash mismatch: {item['filename']}")
        hashes[str(item["ticker"])] = actual
    if expected_tickers is not None:
        wanted = {"^NSEI", *expected_tickers}
        if set(hashes) != wanted:
            missing = sorted(wanted - set(hashes))
            extra = sorted(set(hashes) - wanted)
            raise RuntimeError(
                f"Frozen manifest ticker set mismatch; missing={missing}; extra={extra}"
            )
    return manifest, hashes


def create_frozen_snapshot(
    s221: Any,
    stage21: Any,
    args: argparse.Namespace,
    tickers: Sequence[str] = DEFAULT_UNIVERSE,
) -> Dict[str, Any]:
    """Create only the immutable manifest for an explicitly prepared snapshot."""
    data_dir = Path(args.frozen_data_dir)
    manifest_path = Path(args.manifest_path) if args.manifest_path else data_dir / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite immutable manifest: {manifest_path}"
        )
    config = s221.Stage22Config(
        test_start=OFFICIAL_START,
        test_end=OFFICIAL_END,
        cache_directory=data_dir,
        frozen_data_directory=data_dir,
        data_mode="FROZEN",
    )
    tickers = tuple(tickers)
    manifest = s221.build_data_manifest(data_dir, tickers, config, stage21)
    manifest["stage"] = STAGE
    yfinance_version = getattr(getattr(stage21, "yf", None), "__version__", None)
    if not yfinance_version or yfinance_version == "UNKNOWN":
        yfinance_version = environment_report()["packages"]["yfinance"]
    if not yfinance_version or yfinance_version in {"UNKNOWN", "NOT_INSTALLED"}:
        raise RuntimeError("Snapshot manifest requires an exact yfinance version")
    manifest["yfinance_version"] = str(yfinance_version)
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = canonical_hash(manifest)
    write_json(manifest_path, manifest)
    verify_frozen_manifest(data_dir, manifest_path, tickers)
    print(f"Created immutable frozen snapshot manifest: {manifest_path}")
    return manifest


def identity_payloads(
    s221: Any,
    config: Any,
    strategy_config: Any,
    manifest: Dict[str, Any],
    stage21_hash: str,
    stage221_hash: str,
    stage222_hash: str,
    tickers: Sequence[str],
) -> Dict[str, Any]:
    strategy = {name: getattr(strategy_config, name) for name in STRATEGY_FIELDS}
    execution = {
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
        "entry_timing": "SIGNAL_AT_CLOSE; ENTRY_ON_LATER_SESSION",
        "pullback_semantics": "BUY_LIMIT; EXECUTED_ENTRY_NOT_ABOVE_LIMIT",
        "breakout_semantics": "NEXT_SESSION_OPEN_WITH_GAP_LIMIT",
        "collision_semantics": "STOP_FIRST; ENTRY_BAR_TARGET_ONLY_NOT_CREDITED",
        "ranking": "SIGNAL,ACTIONABILITY,TECHNICAL,RR_T1,RS60,TICKER",
        "cash_and_leverage": "CASH_ONLY; NO_LEVERAGE; MAX_5_POSITIONS",
    }
    strategy_hash = canonical_hash(strategy)
    execution_hash = canonical_hash(execution)
    data_hash, document_hash = manifest_hashes(manifest)
    identity_basis = {
        "stage": STAGE,
        "strategy_hash": strategy_hash,
        "execution_hash": execution_hash,
        "stage21_code_hash": stage21_hash,
        "stage221_code_hash": stage221_hash,
        "stage222_code_hash": stage222_hash,
        "data_content_hash": data_hash,
        "test_start": config.test_start,
        "test_end": config.test_end,
        "tickers": list(tickers),
    }
    experiment_id = (
        f"S222_{normalize_date(config.test_start):%Y%m%d}_"
        f"{normalize_date(config.test_end):%Y%m%d}_"
        f"{canonical_hash(identity_basis)[:12]}"
    )
    return {
        "stage": STAGE,
        "experiment_id": experiment_id,
        "strategy_rules_changed": False,
        "execution_behavior_changed": False,
        "stage_2b_implemented": False,
        "strategy": strategy,
        "execution": execution,
        "STRATEGY_HASH": strategy_hash,
        "EXECUTION_HASH": execution_hash,
        "STAGE21_CODE_HASH": stage21_hash,
        "STAGE221_CODE_HASH": stage221_hash,
        "STAGE222_CODE_HASH": stage222_hash,
        "DATA_CONTENT_HASH": data_hash,
        "MANIFEST_DOCUMENT_HASH": document_hash,
        "test_start": config.test_start,
        "test_end": config.test_end,
        "tickers": list(tickers),
    }


def metadata(identity: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "Experiment ID": identity["experiment_id"],
        "STRATEGY_HASH": identity["STRATEGY_HASH"],
        "EXECUTION_HASH": identity["EXECUTION_HASH"],
        "STAGE21_CODE_HASH": identity["STAGE21_CODE_HASH"],
        "STAGE221_CODE_HASH": identity["STAGE221_CODE_HASH"],
        "STAGE222_CODE_HASH": identity["STAGE222_CODE_HASH"],
        "DATA_CONTENT_HASH": identity["DATA_CONTENT_HASH"],
        "MANIFEST_DOCUMENT_HASH": identity["MANIFEST_DOCUMENT_HASH"],
        "Survivorship Bias Warning": SURVIVORSHIP_WARNING,
    }


def with_metadata(frame: pd.DataFrame, identity: Dict[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    for name, value in reversed(list(metadata(identity).items())):
        if name in result.columns:
            result[name] = value
        else:
            result.insert(0, name, value)
    return result


def point_in_time_audit(
    stage21: Any,
    engine: Any,
    tickers: Sequence[str],
) -> Tuple[bool, pd.DataFrame, str]:
    """Deterministic multi-stock/multi-era prefix-invariance audit."""
    rows: List[Dict[str, Any]] = []
    nifty = engine.raw_data["^NSEI"]
    available_tickers = [
        ticker for ticker in POINT_IN_TIME_TICKERS
        if ticker in tickers and ticker in engine.features and ticker in engine.raw_data
    ]
    if not available_tickers:
        return False, pd.DataFrame(), "No representative stock was available for point-in-time audit"

    compare_columns = [
        ("SMA20", "SMA20"),
        ("SMA50", "SMA50"),
        ("SMA200", "SMA200"),
        ("RSI", "RSI"),
        ("ATR", "ATR"),
        ("ADX", "ADX"),
        ("VolumeAvg", "VolumeAvg"),
        ("VolumeRatio", "VolumeRatio"),
        ("SuperTrend", "ST"),
        ("SuperTrend direction", "STTrend"),
        ("Recent highs", "RecentHigh20"),
        ("Breakout highs", "BreakoutHigh20"),
        ("Weekly RSI", "WeeklyRSI"),
        ("Weekly SuperTrend", "WeeklyST"),
        ("Weekly SuperTrend direction", "WeeklySTTrend"),
        ("RS20", "RS20"),
        ("RS60", "RS60"),
        ("RS120", "RS120"),
    ]

    def append_comparison(
        ticker: str,
        cutoff: pd.Timestamp,
        era: str,
        field: str,
        prefix_value: Any,
        full_value: Any,
    ) -> None:
        if pd.isna(prefix_value) and pd.isna(full_value):
            passed, difference = True, 0.0
        elif isinstance(prefix_value, str) or isinstance(full_value, str):
            passed = str(prefix_value) == str(full_value)
            difference = ""
        else:
            difference = abs(float(prefix_value) - float(full_value))
            passed = bool(
                np.isclose(
                    prefix_value,
                    full_value,
                    atol=1e-10,
                    rtol=1e-10,
                    equal_nan=True,
                )
            )
        rows.append(
            {
                "Ticker": ticker,
                "Cutoff Date": cutoff,
                "Era": era,
                "Field": field,
                "Prefix Value": prefix_value,
                "Full Value": full_value,
                "Difference": difference,
                "Status": "PASS" if passed else "FAIL",
            }
        )

    for ticker in available_tickers:
        raw = engine.raw_data[ticker]
        full = engine.features[ticker]
        for era, start_text, end_text in POINT_IN_TIME_ERAS:
            eligible = full.index[
                (full.index >= normalize_date(start_text))
                & (full.index <= normalize_date(end_text))
                & full.index.isin(raw.index)
            ]
            if not len(eligible):
                continue
            cutoff = normalize_date(eligible[len(eligible) // 2])
            market_prefix = stage21.FeatureEngine(engine.config).market_regime_history(
                nifty.loc[nifty.index <= cutoff].copy()
            )
            strategy = stage21.FrozenStrategy(engine.config, market_prefix)
            prefix_features = strategy.prepare_stock(
                ticker, raw.loc[raw.index <= cutoff].copy()
            )
            if cutoff not in prefix_features.index or cutoff not in full.index:
                rows.append(
                    {
                        "Ticker": ticker,
                        "Cutoff Date": cutoff,
                        "Era": era,
                        "Field": "PREFIX_ROW",
                        "Prefix Value": "MISSING",
                        "Full Value": "PRESENT" if cutoff in full.index else "MISSING",
                        "Difference": "cutoff missing",
                        "Status": "FAIL",
                    }
                )
                continue
            for label, column in compare_columns:
                append_comparison(
                    ticker,
                    cutoff,
                    era,
                    label,
                    prefix_features.loc[cutoff, column],
                    full.loc[cutoff, column],
                )
            append_comparison(
                ticker,
                cutoff,
                era,
                "market regime",
                market_prefix.loc[cutoff, "MarketRegime"],
                engine.market_history.loc[cutoff, "MarketRegime"],
            )
            prefix_signal = strategy.signal_at(
                ticker, prefix_features, len(prefix_features) - 1
            )
            full_strategy = stage21.FrozenStrategy(engine.config, engine.market_history)
            full_position = int(full.index.get_loc(cutoff))
            full_signal = full_strategy.signal_at(ticker, full, full_position)
            prefix_hash = canonical_hash(prefix_signal)
            full_hash = canonical_hash(full_signal)
            append_comparison(
                ticker,
                cutoff,
                era,
                "final signal output",
                prefix_hash,
                full_hash,
            )

    audit = pd.DataFrame(rows)
    required_ticker_count = min(
        5, len([ticker for ticker in POINT_IN_TIME_TICKERS if ticker in tickers])
    )
    coverage_ok = (
        not audit.empty
        and audit.loc[audit["Ticker"] != "SOURCE", "Ticker"].nunique()
        >= required_ticker_count
        and audit.loc[audit["Ticker"] != "SOURCE", "Era"].nunique() == len(POINT_IN_TIME_ERAS)
    )
    passed = bool(coverage_ok and audit["Status"].eq("PASS").all())
    source = Path(stage21.__file__).read_text(encoding="utf-8")
    static_checks = {
        "rolling_highs_shifted": source.count(".shift(1)") >= 3,
        "resistance_prefix_slice": ":position + 1" in source,
        "weekly_friday_rule": '"W-FRI"' in source and 'side="right"' in source,
        "relative_strength_historical_pct_change": ".pct_change(" in source,
    }
    for name, ok in static_checks.items():
        audit.loc[len(audit)] = {
            "Ticker": "SOURCE",
            "Cutoff Date": pd.NaT,
            "Era": "STATIC",
            "Field": name,
            "Prefix Value": "",
            "Full Value": "",
            "Difference": "",
            "Status": "PASS" if ok else "FAIL",
        }
    passed = passed and all(static_checks.values())
    limitation = (
        "Weekly mapping is point-in-time safe for ordinary weeks: Mon-Thu uses the "
        "previous W-FRI candle and Friday uses the current completed candle after close. "
        "Stage 2.1 does not have an exchange-calendar rule to expose a holiday-short "
        "week on its final Thursday; it becomes available the following session. This "
        "is conservative (delayed), not forward-looking, and is reported without changing it."
    )
    return passed, audit, limitation


def dataframe_differences(
    category: str,
    current: pd.DataFrame,
    baseline: pd.DataFrame,
    keys: Sequence[str],
    columns: Optional[Sequence[str]] = None,
    tolerance: float = 1e-8,
) -> pd.DataFrame:
    """Return every missing row and every unequal field, keyed deterministically."""
    left = current.copy()
    right = baseline.copy()
    for frame in (left, right):
        for column in frame.columns:
            if "Date" in column:
                frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
    wanted = list(columns) if columns is not None else sorted(
        (set(left.columns) & set(right.columns)) - set(keys) - METADATA_COLUMNS
    )
    left = left[list(keys) + [column for column in wanted if column in left]].copy()
    right = right[list(keys) + [column for column in wanted if column in right]].copy()
    merged = left.merge(right, on=list(keys), how="outer", suffixes=("_Stage222", "_Stage221"), indicator=True)
    output: List[Dict[str, Any]] = []
    for row in merged.to_dict("records"):
        key_text = "|".join(str(row.get(key)) for key in keys)
        if row["_merge"] != "both":
            output.append({
                "Category": category, "Key": key_text, "Field": "<ROW>",
                "Final Value": "PRESENT" if row["_merge"] == "left_only" else "MISSING",
                "Accepted Stage 2.2.2 Value": "PRESENT" if row["_merge"] == "right_only" else "MISSING",
                "Absolute Difference": np.nan,
            })
            continue
        for column in wanted:
            left_value = row.get(f"{column}_Stage222")
            right_value = row.get(f"{column}_Stage221")
            left_number, right_number = safe_float(left_value), safe_float(right_value)
            if left_number is not None and right_number is not None:
                difference = abs(left_number - right_number)
                equal = bool(np.isclose(left_number, right_number, atol=tolerance, rtol=tolerance))
            elif (
                (pd.isna(left_value) or str(left_value).strip() == "")
                and (pd.isna(right_value) or str(right_value).strip() == "")
            ):
                difference, equal = 0.0, True
            else:
                difference = np.nan
                equal = str(left_value) == str(right_value)
            if not equal:
                output.append({
                    "Category": category, "Key": key_text, "Field": column,
                    "Final Value": left_value,
                    "Accepted Stage 2.2.2 Value": right_value,
                    "Absolute Difference": difference,
                })
    return pd.DataFrame(output)


def load_accepted_stage222_result(results_dir: Path, filename: str) -> pd.DataFrame:
    path = results_dir / filename
    if not path.exists() and path.suffix == ".csv":
        compressed = path.with_suffix(path.suffix + ".gz")
        if compressed.exists():
            path = compressed
    if not path.exists():
        raise FileNotFoundError(f"Accepted Stage 2.2.2 baseline file missing: {path}")
    return pd.read_csv(path, low_memory=False)


def stage222_acceptance_parity(
    candidates: pd.DataFrame,
    orders: pd.DataFrame,
    trades: pd.DataFrame,
    results: Sequence[Dict[str, Any]],
    summary: pd.DataFrame,
    baseline_dir: Path,
) -> Tuple[bool, pd.DataFrame, pd.DataFrame]:
    base_candidates = load_accepted_stage222_result(
        baseline_dir, "stage2_2_2_candidate_signal_log.csv"
    )
    candidate_columns = [
        "Signal", "Setup", "Trade Quality", "Technical Score", "Actionability Score",
        "Market Regime", "Market Score", "Price", "Entry Low", "Entry High",
        "Stop Loss", "Target 1", "Target 2", "R:R T1", "R:R T2", "RS 60D",
        "Signal ID",
    ]
    diffs = [dataframe_differences(
        "CANDIDATE", candidates, base_candidates, ["Ticker", "Signal Date"], candidate_columns
    )]
    base_orders = load_accepted_stage222_result(
        baseline_dir, "stage2_2_2_order_log.csv"
    )
    diffs.append(dataframe_differences("ORDER", orders, base_orders, ["Variant", "Order ID"]))
    base_trades = load_accepted_stage222_result(
        baseline_dir, "stage2_2_2_portfolio_trade_log.csv"
    )
    diffs.append(dataframe_differences(
        "TRADE", trades, base_trades,
        ["Variant", "Ticker", "Signal Date", "Entry Date", "Exit Date"],
    ))
    equity = pd.concat([item["equity"] for item in results], ignore_index=True)
    base_equity = pd.concat([
        load_accepted_stage222_result(
            baseline_dir, f"stage2_2_2_daily_equity_{item['variant']}.csv"
        )
        for item in results
    ], ignore_index=True)
    diffs.append(dataframe_differences("DAILY_EQUITY", equity, base_equity, ["Variant", "Date"]))
    base_summary = load_accepted_stage222_result(
        baseline_dir, "stage2_2_2_portfolio_summary.csv"
    )
    diffs.append(dataframe_differences("ENDING_SUMMARY", summary, base_summary, ["Variant"]))
    material = pd.concat([item for item in diffs if not item.empty], ignore_index=True) if any(not item.empty for item in diffs) else pd.DataFrame(
        columns=["Category", "Key", "Field", "Final Value", "Accepted Stage 2.2.2 Value", "Absolute Difference"]
    )
    status = pd.DataFrame([
        {
            "Acceptance Component": name,
            "Status": "PASS" if material[material["Category"] == name].empty else "FAIL",
            "Difference Count": int((material["Category"] == name).sum()),
        }
        for name in ("CANDIDATE", "ORDER", "TRADE", "DAILY_EQUITY", "ENDING_SUMMARY")
    ])
    return material.empty, material, status


def simple_metrics(
    dates: pd.Series | pd.Index,
    equity: pd.Series,
    starting_equity: float,
    annual_rf: float,
) -> Dict[str, float]:
    values = pd.Series(pd.to_numeric(equity, errors="coerce").values, dtype=float)
    date_values = pd.to_datetime(pd.Series(dates).values)
    returns = values.pct_change().fillna(0.0)
    years = max((date_values[-1] - date_values[0]).days / 365.25, 1.0 / 252.0)
    cagr = (float(values.iloc[-1]) / starting_equity) ** (1.0 / years) - 1.0
    volatility = float(returns.std(ddof=1) * math.sqrt(252.0))
    daily_rf = (1.0 + annual_rf) ** (1.0 / 252.0) - 1.0
    sharpe = float((returns - daily_rf).mean() / returns.std(ddof=1) * math.sqrt(252.0)) if returns.std(ddof=1) > 0 else np.nan
    drawdown = values / values.cummax() - 1.0
    return {
        "Ending Equity": float(values.iloc[-1]),
        "Net Return %": (float(values.iloc[-1]) / starting_equity - 1.0) * 100.0,
        "CAGR %": cagr * 100.0,
        "Annualized Volatility %": volatility * 100.0,
        "Sharpe Ratio": sharpe,
        "Maximum Drawdown %": float(drawdown.min() * 100.0),
    }


def build_exposure_matched_benchmarks(
    config: Any,
    results: Sequence[Dict[str, Any]],
    nifty_raw: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    nifty = nifty_raw.copy()
    nifty.index = pd.to_datetime(nifty.index).tz_localize(None).normalize()
    nifty_close = pd.to_numeric(nifty["Close"], errors="coerce")
    rows: List[Dict[str, Any]] = []
    daily_rows: List[pd.DataFrame] = []
    for item in results:
        equity = item["equity"].sort_values("Date").copy()
        dates = pd.DatetimeIndex(pd.to_datetime(equity["Date"]).dt.normalize())
        close = nifty_close.reindex(dates).ffill().bfill()
        nifty_return = close.pct_change().fillna(0.0)
        total = pd.to_numeric(equity["Total Equity"], errors="coerce").to_numpy(dtype=float)
        gross = pd.to_numeric(equity["Open Position Value"], errors="coerce").to_numpy(dtype=float)
        exposure = pd.Series(np.divide(gross, total, out=np.zeros_like(gross), where=total != 0), index=dates).clip(0.0, 1.0)
        prior_exposure = exposure.shift(1).fillna(0.0)
        average_exposure = float(exposure.mean())
        cash_returns = {
            "CASH_0": 0.0,
            "CASH_RF": (1.0 + config.annual_risk_free_rate) ** (1.0 / 252.0) - 1.0,
        }
        strategy_metrics = simple_metrics(dates, pd.Series(total), config.starting_equity, config.annual_risk_free_rate)
        for exposure_method, allocation, methodology_note in (
            (
                "EX_POST_CONSTANT_AVERAGE_EXPOSURE",
                pd.Series(average_exposure, index=dates),
                "Uses full-period realized average strategy exposure; diagnostic only; not deployable point-in-time.",
            ),
            (
                "PRIOR_SESSION_DYNAMIC_EXPOSURE",
                prior_exposure,
                "Uses prior-session strategy exposure for next-session NIFTY allocation; no same-day look-ahead.",
            ),
        ):
            for cash_name, cash_return in cash_returns.items():
                combined_return = allocation * nifty_return + (1.0 - allocation) * cash_return
                benchmark_equity = config.starting_equity * (1.0 + combined_return).cumprod()
                metrics = simple_metrics(dates, benchmark_equity, config.starting_equity, config.annual_risk_free_rate)
                rows.append({
                    "Variant": item["variant"],
                    "Benchmark": f"NIFTY_{exposure_method}_{cash_name}",
                    "Exposure Method": exposure_method,
                    "Cash Return Assumption": cash_name,
                    "Average Strategy Exposure %": average_exposure * 100.0,
                    **metrics,
                    "Strategy Net Return %": strategy_metrics["Net Return %"],
                    "Strategy Minus Benchmark Return %": strategy_metrics["Net Return %"] - metrics["Net Return %"],
                    "Interpretation": "Diagnostic control; does not establish causality.",
                    "Methodology Note": methodology_note,
                    "No-Lookahead Rule": (
                        methodology_note
                        if exposure_method == "PRIOR_SESSION_DYNAMIC_EXPOSURE"
                        else "NOT APPLICABLE: ex-post diagnostic uses full-period realized exposure."
                    ),
                })
                daily_rows.append(pd.DataFrame({
                    "Date": dates,
                    "Variant": item["variant"],
                    "Benchmark": f"NIFTY_{exposure_method}_{cash_name}",
                    "NIFTY Daily Return": nifty_return.to_numpy(),
                    "Applied Exposure": allocation.to_numpy(),
                    "Benchmark Equity": benchmark_equity.to_numpy(),
                }))
    return pd.DataFrame(rows), pd.concat(daily_rows, ignore_index=True)


def cost_sensitivity(
    s221: Any,
    config: Any,
    features: Dict[str, pd.DataFrame],
    candidates: pd.DataFrame,
    official_results: Sequence[Dict[str, Any]],
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for multiplier in FRICTION_MULTIPLIERS:
        if multiplier == 1.0:
            scenario_results = list(official_results)
            scenario_config = config
        else:
            scenario_config = replace(
                config,
                slippage_bps=OFFICIAL_SLIPPAGE_BPS * multiplier,
                transaction_cost_bps=OFFICIAL_TRANSACTION_BPS * multiplier,
            )
            scenario_results = s221.run_portfolios(scenario_config, features, candidates)
        analyzer = s221.PerformanceAnalyzer(scenario_config, pd.DataFrame(), scenario_results)
        summary = analyzer.portfolio_summary()
        for item in scenario_results:
            trades = item["trades"]
            row = summary[summary["Variant"] == item["variant"]].iloc[0].to_dict()
            equity = item["equity"]
            metrics = simple_metrics(
                equity["Date"], equity["Total Equity"], scenario_config.starting_equity,
                scenario_config.annual_risk_free_rate,
            )
            rows.append({
                "Friction Multiplier": multiplier,
                "Official Baseline": multiplier == 1.0,
                "Variant": item["variant"],
                "Slippage BPS Per Side": scenario_config.slippage_bps,
                "Transaction Cost BPS Per Side": scenario_config.transaction_cost_bps,
                "Ending Equity": metrics["Ending Equity"],
                "Net Return %": metrics["Net Return %"],
                "CAGR %": metrics["CAGR %"],
                "Maximum Drawdown %": metrics["Maximum Drawdown %"],
                "Total Trades": int(len(trades)),
                "Expectancy R": row.get("Expectancy R", np.nan),
                "Profit Factor": row.get("Profit Factor", np.nan),
                "Total Slippage Cost": float(pd.to_numeric(trades.get("Slippage Cost"), errors="coerce").sum()) if not trades.empty else 0.0,
                "Total Transaction Cost": float(pd.to_numeric(trades.get("Transaction Cost"), errors="coerce").sum()) if not trades.empty else 0.0,
                "Signals Regenerated": False,
                "Purpose": "Mechanical friction sensitivity; not optimization",
            })
    return pd.DataFrame(rows)


def validate_execution(
    config: Any,
    candidates: pd.DataFrame,
    results: Sequence[Dict[str, Any]],
    official_manifest_set_ok: bool,
    manifest_pre_ok: bool,
    manifest_post_ok: bool,
    stage21_before: str,
    stage21_after: str,
    stage221_before: str,
    stage221_after: str,
    stage222_before: str,
    stage222_after: str,
    point_in_time_ok: bool,
    reference_ok: bool,
    stage222_parity_ok: Optional[bool],
    cost_table: pd.DataFrame,
    signal_summary: Dict[str, Any],
    signal_severity: str,
    exposure_matched: pd.DataFrame,
) -> Tuple[bool, pd.DataFrame, str]:
    orders = pd.concat([item["orders"] for item in results], ignore_index=True)
    trades = pd.concat([item["trades"] for item in results], ignore_index=True)
    equity = pd.concat([item["equity"] for item in results], ignore_index=True)
    checks: List[Dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str = "", warn: bool = False) -> None:
        checks.append({"Check": name, "Status": "WARN" if warn else "PASS" if passed else "FAIL", "Detail": detail})

    add("Exact frozen Stage 2.1 source hash", stage21_before == EXPECTED_STAGE21_HASH, stage21_before)
    add("Stage 2.1 source unchanged during run", stage21_before == stage21_after, stage21_after)
    add("Exact accepted Stage 2.2.1 helper hash", stage221_before == EXPECTED_STAGE221_HASH, stage221_before)
    add("Stage 2.2.1 source unchanged during run", stage221_before == stage221_after, stage221_after)
    add("Stage 2.2.2 source unchanged during run", stage222_before == stage222_after, stage222_after)
    add("Frozen manifest verified before run", manifest_pre_ok)
    add("Frozen manifest verified after run", manifest_post_ok)
    add("Exact frozen manifest ticker set", official_manifest_set_ok)
    add("Reference signal log integrity", reference_ok)
    signal_detail = (
        f"severity={signal_severity}; generated={signal_summary.get('generated_rows')}; "
        f"reference={signal_summary.get('reference_rows')}; "
        f"exact={signal_summary.get('exact_matches')}; "
        f"rows_with_any_difference={signal_summary.get('rows_with_any_difference')}; "
        f"float_only={signal_summary.get('rows_with_float_only_difference')}; "
        f"signal_label_mismatches={signal_summary.get('signal_label_mismatches')}; "
        f"buy_nonbuy_membership_changes={signal_summary.get('buy_nonbuy_membership_changes')}; "
        f"missing_or_extra={signal_summary.get('missing_or_extra_rows')}"
    )
    add(
        "Fresh Stage 2.1 regeneration vs historical reference",
        signal_severity != "FAIL",
        signal_detail,
        warn=signal_severity == "WARN",
    )
    add("Point-in-time prefix invariance", point_in_time_ok)
    add("Strategy rules changed", True, "NO")
    add("Execution behavior changed", True, "NO")
    add("Stage 2B implemented", True, "NO")
    add("Weekly holiday-short limitation", True, "Conservative one-session delay; no future candle used", warn=True)
    add("Candidate Signal IDs present", not candidates.empty and candidates["Signal ID"].notna().all())
    id_stable = candidates.empty or bool((candidates["Signal ID"] == [make_signal_id(row) for _, row in candidates.iterrows()]).all())
    add("Candidate Signal IDs deterministic", id_stable)
    unique_inputs = candidates.drop_duplicates(["Ticker", "Signal Date", "Signal", "Setup"])
    add("Signal ID collision check", unique_inputs["Signal ID"].nunique() == len(unique_inputs))
    add("Order Signal IDs carried", orders.empty or orders["Signal ID"].notna().all())
    add("Trade Signal IDs carried", trades.empty or trades["Signal ID"].notna().all())
    entry_after = trades.empty or bool((pd.to_datetime(trades["Entry Date"]) > pd.to_datetime(trades["Signal Date"])).all())
    add("Entries strictly after signal close", entry_after)
    add("Primary portfolios exclude WATCH", trades.empty or bool(trades["Signal"].isin(PRIMARY_SIGNALS).all()))
    add("Positive quantities", trades.empty or bool((pd.to_numeric(trades["Quantity"]) > 0).all()))
    add("Stops below executed entry", trades.empty or bool((pd.to_numeric(trades["Stop"]) < pd.to_numeric(trades["Executed Entry"])).all()))
    add("Targets above executed entry", trades.empty or bool((pd.to_numeric(trades["Target"]) > pd.to_numeric(trades["Executed Entry"])).all()))
    actionable = candidates[candidates["Signal"].isin(PRIMARY_SIGNALS) & candidates["Setup"].isin({"PULLBACK", "BREAKOUT"})]
    add("T2 strictly above T1", actionable.empty or bool((pd.to_numeric(actionable["Target 2"]) > pd.to_numeric(actionable["Target 1"])).all()))

    if trades.empty:
        formula_checks = {name: True for name in (
            "entry", "exit", "entry_cost", "exit_cost", "gross", "slippage", "net"
        )}
    else:
        slip = config.slippage_bps / 10000.0
        tx = config.transaction_cost_bps / 10000.0
        nominal_entry = pd.to_numeric(trades["Nominal Entry"])
        nominal_exit = pd.to_numeric(trades["Nominal Exit"])
        executed_entry = pd.to_numeric(trades["Executed Entry"])
        executed_exit = pd.to_numeric(trades["Executed Exit"])
        quantity = pd.to_numeric(trades["Quantity"])
        expected_entry = nominal_entry * (1.0 + slip)
        pullback = trades["Setup"].eq("PULLBACK")
        expected_entry.loc[pullback] = np.minimum(expected_entry.loc[pullback], pd.to_numeric(trades.loc[pullback, "Buy Limit"]))
        expected_exit = nominal_exit * (1.0 - slip)
        expected_entry_cost = executed_entry * quantity * tx
        expected_exit_cost = executed_exit * quantity * tx
        expected_gross = (nominal_exit - nominal_entry) * quantity
        expected_slip = (executed_entry - nominal_entry + nominal_exit - executed_exit) * quantity
        expected_net = expected_gross - expected_slip - expected_entry_cost - expected_exit_cost
        formula_checks = {
            "entry": bool(np.allclose(executed_entry, expected_entry, atol=1e-8, rtol=1e-10)),
            "exit": bool(np.allclose(executed_exit, expected_exit, atol=1e-8, rtol=1e-10)),
            "entry_cost": bool(np.allclose(pd.to_numeric(trades["Entry Transaction Cost"]), expected_entry_cost, atol=1e-7, rtol=1e-10)),
            "exit_cost": bool(np.allclose(pd.to_numeric(trades["Exit Transaction Cost"]), expected_exit_cost, atol=1e-7, rtol=1e-10)),
            "gross": bool(np.allclose(pd.to_numeric(trades["Gross PnL"]), expected_gross, atol=1e-7, rtol=1e-10)),
            "slippage": bool(np.allclose(pd.to_numeric(trades["Slippage Cost"]), expected_slip, atol=1e-7, rtol=1e-10)),
            "net": bool(np.allclose(pd.to_numeric(trades["Net PnL"]), expected_net, atol=1e-7, rtol=1e-10)),
        }
    for name, passed in formula_checks.items():
        add(f"Independent {name.replace('_', ' ')} formula", passed)
    add("Pullback buy-limit ceiling", trades.empty or bool((pd.to_numeric(trades.loc[trades["Setup"].eq("PULLBACK"), "Executed Entry"]) <= pd.to_numeric(trades.loc[trades["Setup"].eq("PULLBACK"), "Buy Limit"]) + 1e-10).all()))
    add("Daily equity cash plus positions", equity.empty or bool(np.allclose(pd.to_numeric(equity["Cash"]) + pd.to_numeric(equity["Open Position Value"]), pd.to_numeric(equity["Total Equity"]), atol=1e-7, rtol=1e-10)))
    add("Cash never negative", equity.empty or bool((pd.to_numeric(equity["Cash"]) >= -1e-7).all()))
    add("No leverage", equity.empty or bool((pd.to_numeric(equity["Open Position Value"]) <= pd.to_numeric(equity["Total Equity"]) + 1e-7).all()))
    add("Maximum five open positions", equity.empty or bool((pd.to_numeric(equity["Number Open Positions"]) <= config.max_open_positions).all()))
    add("One daily equity row per variant/date", not equity.duplicated(["Variant", "Date"]).any())
    runtime_errors = [error for item in results for error in item["runtime_errors"]]
    add("Runtime state invariants", not runtime_errors, "; ".join(runtime_errors[:5]))
    add("Friction 1.0x uses official 5+5 BPS", bool(((cost_table["Friction Multiplier"] == 1.0) & (cost_table["Slippage BPS Per Side"] == 5.0) & (cost_table["Transaction Cost BPS Per Side"] == 5.0)).any()))
    constant_rows = exposure_matched[
        exposure_matched["Exposure Method"].eq("EX_POST_CONSTANT_AVERAGE_EXPOSURE")
    ]
    dynamic_rows = exposure_matched[
        exposure_matched["Exposure Method"].eq("PRIOR_SESSION_DYNAMIC_EXPOSURE")
    ]
    add(
        "Constant exposure benchmark labeled ex-post",
        not constant_rows.empty
        and constant_rows["Methodology Note"].str.contains(
            "not deployable point-in-time", regex=False
        ).all(),
    )
    add(
        "Dynamic exposure benchmark uses prior session",
        not dynamic_rows.empty
        and dynamic_rows["Methodology Note"].str.contains(
            "prior-session strategy exposure", regex=False
        ).all(),
    )
    if stage222_parity_ok is not None:
        add("Exact parity vs accepted Stage 2.2.2 at 1.0x", stage222_parity_ok)
    overall = not any(row["Status"] == "FAIL" for row in checks)
    label = "PASS WITH WARNINGS" if overall else "FAIL"
    counts = {
        status: sum(row["Status"] == status for row in checks)
        for status in ("PASS", "WARN", "FAIL")
    }
    report = "\n".join([
        "STAGE 2.2.2 VALIDATION", "-" * 112,
        *[f"{row['Check']:<58} {row['Status']:<5} {row['Detail']}".rstrip() for row in checks],
        "-" * 112,
        f"PASS/WARN/FAIL: {counts['PASS']}/{counts['WARN']}/{counts['FAIL']}",
        f"OVERALL VALIDATION: {label}",
        "STRATEGY RULES CHANGED: NO",
        "EXECUTION BEHAVIOR CHANGED: NO",
        "STAGE 2B IMPLEMENTED: NO",
        "",
        SURVIVORSHIP_WARNING,
    ])
    return overall, pd.DataFrame(checks), report


def run_stage222_self_tests(s221: Any, args: argparse.Namespace) -> None:
    """Run the permanent 21-check baseline gate without touching official outputs."""
    stage21_path = Path(args.stage21_source)
    stage221_path = Path(args.stage221_source)
    source_path = Path(__file__).resolve()
    manifest_path = (
        Path(args.manifest_path)
        if args.manifest_path
        else Path(args.frozen_data_dir) / "manifest.json"
    )
    stage21_hash = sha256_file(stage21_path)
    stage221_hash = sha256_file(stage221_path)
    stage222_hash = sha256_file(source_path)
    if stage21_hash != EXPECTED_STAGE21_HASH:
        raise AssertionError("Stage 2.1 hash gate failed")
    if stage221_hash != EXPECTED_STAGE221_HASH:
        raise AssertionError("Stage 2.2.1 helper hash gate failed")
    checks: List[Dict[str, str]] = []

    def record(name: str) -> None:
        checks.append({"Self-Test": name, "Status": "PASS"})

    record("Stage 2.1 exact hash")
    record("Stage 2.2.1 dependency hash")
    stage21 = s221.load_stage21_module(stage21_path)
    s221.run_self_tests()

    sample = pd.DataFrame(
        [
            {"Ticker": "TCS.NS", "Signal Date": "2025-01-02", "Signal": "BUY", "Setup": "BREAKOUT"},
            {"Ticker": "INFY.NS", "Signal Date": "2025-01-02", "Signal": "BUY", "Setup": "PULLBACK"},
        ]
    )
    once = add_signal_ids(sample)
    twice = add_signal_ids(sample)
    assert once["Signal ID"].equals(twice["Signal ID"]), "Signal IDs are not deterministic"
    record("Deterministic Signal ID")
    assert once["Signal ID"].nunique() == len(once), "Signal ID collision"
    record("No Signal ID collisions")

    official_manifest, _ = verify_frozen_manifest(
        Path(args.frozen_data_dir), manifest_path, DEFAULT_UNIVERSE
    )
    data_hash, _ = manifest_hashes(official_manifest)
    config = build_config(s221, args, DEFAULT_UNIVERSE)
    strategy_config = s221.CandidateSignalEngine(
        stage21, config, DEFAULT_UNIVERSE
    ).strategy_config
    with tempfile.TemporaryDirectory() as directory:
        temporary_root = Path(directory)
        identities: List[Dict[str, Any]] = []
        for name in ("portable_a", "portable_b"):
            copy_root = temporary_root / name / "nested" / "repository"
            copy_root.mkdir(parents=True)
            stage21_copy = copy_root / stage21_path.name
            stage221_copy = copy_root / stage221_path.name
            stage222_copy = copy_root / source_path.name
            manifest_copy = copy_root / "manifest.json"
            shutil.copy2(stage21_path, stage21_copy)
            shutil.copy2(stage221_path, stage221_copy)
            shutil.copy2(source_path, stage222_copy)
            shutil.copy2(manifest_path, manifest_copy)
            copied_manifest = json.loads(manifest_copy.read_text(encoding="utf-8"))
            identities.append(
                identity_payloads(
                    s221,
                    config,
                    strategy_config,
                    copied_manifest,
                    sha256_file(stage21_copy),
                    sha256_file(stage221_copy),
                    sha256_file(stage222_copy),
                    DEFAULT_UNIVERSE,
                )
            )
        portable_fields = (
            "STRATEGY_HASH",
            "EXECUTION_HASH",
            "STAGE21_CODE_HASH",
            "STAGE221_CODE_HASH",
            "STAGE222_CODE_HASH",
            "DATA_CONTENT_HASH",
            "experiment_id",
        )
        assert all(
            identities[0][field] == identities[1][field] for field in portable_fields
        ), "Portable identity depends on absolute path"
    repo_root = source_path.parent.parent
    hardcoded = [
        path
        for path in repo_root.rglob("*.py")
        if ".runtime_deps" not in path.parts
        and "C:\\Users\\" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not hardcoded, f"Hardcoded development paths found: {hardcoded}"
    record("Portable hashing across paths")

    with tempfile.TemporaryDirectory() as directory:
        missing_root = Path(directory)
        try:
            verify_frozen_manifest(missing_root, missing_root / "manifest.json")
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("Missing FROZEN manifest did not fail")
    record("Missing frozen manifest fails")

    with tempfile.TemporaryDirectory() as directory:
        snapshot_root = Path(directory)
        dates = pd.date_range("2025-01-01", periods=3, freq="B")
        for ticker in ("^NSEI", "TCS.NS"):
            filename = s221.CandidateSignalEngine._cache_name(ticker)
            pd.DataFrame(
                {
                    "Date": dates,
                    "Open": [100.0, 101.0, 102.0],
                    "High": [101.0, 102.0, 103.0],
                    "Low": [99.0, 100.0, 101.0],
                    "Close": [100.0, 101.0, 102.0],
                    "Volume": [1000, 1000, 1000],
                }
            ).to_csv(snapshot_root / filename, index=False)
        snapshot_args = SimpleNamespace(
            frozen_data_dir=str(snapshot_root), manifest_path=""
        )
        created = create_frozen_snapshot(
            s221, stage21, snapshot_args, tickers=("TCS.NS",)
        )
        assert created["yfinance_version"] not in {"UNKNOWN", "NOT_INSTALLED"}
        verify_frozen_manifest(
            snapshot_root, snapshot_root / "manifest.json", ("TCS.NS",)
        )
        record("Explicit snapshot creation works")
        try:
            create_frozen_snapshot(
                s221, stage21, snapshot_args, tickers=("TCS.NS",)
            )
        except FileExistsError:
            pass
        else:
            raise AssertionError("Existing immutable manifest was overwritten")
    record("Existing frozen manifest cannot be silently overwritten")

    reconstruction_module = import_source(
        "stage222_final_reconstruct_test",
        repo_root / "scripts" / "reconstruct_split_files.py",
    )
    with tempfile.TemporaryDirectory() as directory:
        split_root = Path(directory)
        target = split_root / "artifact.bin"
        payload = (b"stage-2.2.2-final-integrity-test\n" * 1000)
        (split_root / "artifact.bin.part001").write_bytes(payload[:17000])
        (split_root / "artifact.bin.part002").write_bytes(payload[17000:])
        split_manifest = split_root / "artifact_manifest.csv"
        pd.DataFrame(
            [
                {
                    "path": "artifact.bin",
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ]
        ).to_csv(split_manifest, index=False)
        reconstruction_module.reconstruct_all(split_root, split_manifest)
        assert target.read_bytes() == payload
        target.unlink()
        corrupt_part = split_root / "artifact.bin.part002"
        corrupt_part.write_bytes(corrupt_part.read_bytes() + b"corruption")
        try:
            reconstruction_module.reconstruct_all(split_root, split_manifest)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Corrupt split artifact was accepted")
    record("Split-file reconstruction integrity")

    test_config = s221.Stage22Config(
        test_start="2025-01-01",
        test_end="2025-01-10",
        holding_periods=(3,),
        starting_equity=10000.0,
        max_open_positions=1,
    )
    execution = s221.ExecutionModel(test_config)
    assert execution.executed_entry(100.0, "PULLBACK_LIMIT", 100.0) <= 100.0
    record("Pullback buy-limit ceiling")
    breakout_dates = pd.bdate_range("2025-01-01", periods=2)
    breakout_order = s221.PendingOrder(
        order_id=1,
        variant="T1_3D",
        ticker="AAA",
        signal_date=breakout_dates[0],
        signal="BUY",
        setup="BREAKOUT",
        created_date=breakout_dates[0],
        expiry_date=breakout_dates[1],
        valid_dates=(breakout_dates[1],),
        entry_low=99.0,
        entry_high=100.0,
        stop=95.0,
        target1=110.0,
        target2=115.0,
        actionability=75.0,
        technical_score=75.0,
        rr_t1=2.0,
        rs60=5.0,
        market_regime="BULL",
    )
    assert execution.assess_fill(
        breakout_order,
        pd.Series({"Open": 100.0, "Low": 99.0}),
        breakout_dates[0],
    ) is None
    assert execution.assess_fill(
        breakout_order,
        pd.Series({"Open": 100.0, "Low": 99.0}),
        breakout_dates[1],
    ) is not None
    record("Breakout next-session entry")
    collision = execution.ordinary_bar_exit(
        SimpleNamespace(stop=95.0, target=105.0),
        pd.Series({"Low": 94.0, "High": 106.0}),
    )
    assert collision == (95.0, "STOP_COLLISION")
    record("Stop-first collision")

    dates = pd.bdate_range("2025-01-01", periods=4)
    ambiguity_features = pd.DataFrame(
        {
            "Open": [101.0, 105.0, 102.0, 103.0],
            "High": [102.0, 115.0, 104.0, 105.0],
            "Low": [100.0, 99.0, 101.0, 102.0],
            "Close": [101.0, 102.0, 103.0, 104.0],
            "Volume": [1000] * 4,
        },
        index=dates,
    )
    ambiguity_signal = pd.DataFrame(
        [s221._synthetic_signal("CCC", dates[0], setup="PULLBACK")]
    )
    ambiguity = s221.PortfolioBacktester(
        test_config,
        {"CCC": ambiguity_features},
        ambiguity_signal,
        "T1_3D",
        "Target 1",
        3,
    ).run()
    assert len(ambiguity["trades"]) == 1
    ambiguity_trade = ambiguity["trades"].iloc[0]
    assert bool(ambiguity_trade["Conservative Entry-Bar Ambiguity"])
    assert pd.Timestamp(ambiguity_trade["Exit Date"]) > pd.Timestamp(
        ambiguity_trade["Entry Date"]
    )
    record("Entry-bar target ambiguity")

    assert math.isclose(execution.executed_entry(100.0), 100.05)
    assert math.isclose(execution.executed_exit(100.0), 99.95)
    record("Slippage formula")
    assert math.isclose(execution.transaction_cost(100.0, 10), 0.5)
    record("Transaction-cost formula")
    trades = ambiguity["trades"]
    assert np.allclose(
        trades["Gross PnL"] - trades["Slippage Cost"] - trades["Transaction Cost"],
        trades["Net PnL"],
    )
    record("Net-PnL reconciliation")
    assert ambiguity["max_concurrent_positions"] <= test_config.max_open_positions
    record("Max-position limit")
    equity = ambiguity["equity"]
    assert (equity["Cash"] >= -1e-7).all()
    assert (
        equity["Open Position Value"] <= equity["Total Equity"] + 1e-7
    ).all()
    record("Cash/non-leverage invariant")

    exposure_dates = pd.bdate_range("2025-01-01", periods=3)
    exposure_equity = pd.DataFrame(
        {
            "Date": exposure_dates,
            "Total Equity": [100.0, 100.0, 100.0],
            "Open Position Value": [50.0, 25.0, 0.0],
        }
    )
    nifty = pd.DataFrame(
        {"Close": [100.0, 110.0, 121.0]}, index=exposure_dates
    )
    exposure_summary, exposure_daily = build_exposure_matched_benchmarks(
        test_config,
        [{"variant": "T2_20D", "equity": exposure_equity}],
        nifty,
    )
    dynamic_daily = exposure_daily[
        exposure_daily["Benchmark"].eq(
            "NIFTY_PRIOR_SESSION_DYNAMIC_EXPOSURE_CASH_0"
        )
    ]
    assert np.allclose(dynamic_daily["Applied Exposure"], [0.0, 0.5, 0.25])
    record("Exposure benchmark math")
    constant_rows = exposure_summary[
        exposure_summary["Exposure Method"].eq(
            "EX_POST_CONSTANT_AVERAGE_EXPOSURE"
        )
    ]
    assert not constant_rows.empty
    assert constant_rows["Methodology Note"].str.contains(
        "not deployable point-in-time", regex=False
    ).all()
    record("Constant-exposure benchmark labeling")
    dynamic_rows = exposure_summary[
        exposure_summary["Exposure Method"].eq("PRIOR_SESSION_DYNAMIC_EXPOSURE")
    ]
    assert not dynamic_rows.empty
    assert dynamic_rows["Methodology Note"].str.contains(
        "prior-session strategy exposure", regex=False
    ).all()
    record("Dynamic exposure uses prior-session value")

    if len(checks) != 21:
        raise AssertionError(f"Expected 21 self-tests, recorded {len(checks)}")
    tests_dir = Path(args.tests_dir)
    tests_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(checks).to_csv(
        tests_dir / f"{PREFIX}_self_test_checks.csv", index=False
    )
    receipt = {
        "status": "PASS",
        "test_count": len(checks),
        "stage21_code_hash": stage21_hash,
        "stage221_code_hash": stage221_hash,
        "stage222_code_hash": stage222_hash,
        "data_content_hash": data_hash,
        "snapshot_creation_test": "PASS",
        "fresh_clone_reproducibility_test": "PASS",
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(tests_dir / "self_test_pass.json", receipt)
    print(f"STAGE 2.2.2 FINAL SELF-TESTS: PASS ({len(checks)}/21)")


def flatten_results(results: Sequence[Dict[str, Any]], key: str) -> pd.DataFrame:
    frames = [item[key] for item in results if not item[key].empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def output_csv(
    output_dir: Path,
    name: str,
    frame: pd.DataFrame,
    identity: Dict[str, Any],
    gzip_output: bool = False,
) -> Path:
    path = output_dir / name
    prepared = with_metadata(frame, identity)
    prepared.to_csv(path, index=False, compression="gzip" if gzip_output else None)
    return path


def delivery_report(
    identity: Dict[str, Any],
    config: Any,
    overall: bool,
    sanity: bool,
    runtime_seconds: float,
    parity_status: pd.DataFrame,
    point_limitation: str,
    environment: Dict[str, Any],
    checks: pd.DataFrame,
    signal_summary: Dict[str, Any],
    pit_audit: pd.DataFrame,
    exposure_matched: pd.DataFrame,
    cost_table: pd.DataFrame,
    self_test_receipt: Dict[str, Any],
    sanity_receipt: Dict[str, Any],
) -> str:
    warning_count = int(checks["Status"].eq("WARN").sum()) if not checks.empty else 0
    status = "PASS WITH WARNINGS" if overall and warning_count else "PASS" if overall else "FAIL"
    parity_text = "NOT APPLICABLE TO SANITY RUN" if sanity else (
        "PASS" if parity_status.empty or parity_status["Status"].eq("PASS").all() else "FAIL"
    )
    counts = {
        name: int(checks["Status"].eq(name).sum()) if not checks.empty else 0
        for name in ("PASS", "WARN", "FAIL")
    }
    pit_rows = pit_audit[pit_audit["Ticker"].ne("SOURCE")] if not pit_audit.empty else pit_audit
    pit_tickers = sorted(pit_rows["Ticker"].dropna().unique().tolist()) if not pit_rows.empty else []
    pit_eras = sorted(pit_rows["Era"].dropna().unique().tolist()) if not pit_rows.empty else []
    parity_lines = (
        "; ".join(
            f"{row['Acceptance Component']}={row['Status']} ({row['Difference Count']} differences)"
            for _, row in parity_status.iterrows()
        )
        if not parity_status.empty
        else parity_text
    )
    exposure_rows = exposure_matched[exposure_matched["Variant"].eq("T2_20D")]
    exposure_text = "; ".join(
        f"{row['Benchmark']}={float(row['Net Return %']):.6f}%"
        for _, row in exposure_rows.iterrows()
    )
    friction_rows = cost_table[cost_table["Variant"].eq("T2_20D")]
    friction_text = "; ".join(
        f"{float(row['Friction Multiplier']):.1f}x={float(row['Net Return %']):.6f}%"
        for _, row in friction_rows.iterrows()
    )
    environment_text = (
        f"Python {environment['python']}; {environment['python_implementation']}; "
        f"pandas {environment['packages']['pandas']}; NumPy {environment['packages']['numpy']}; "
        f"yfinance {environment['packages']['yfinance']}; {environment['platform']}"
    )
    return f"""# Stage 2.2.2 Final Baseline Delivery Report

1. Files changed: new final source, README/requirements, reconstruction and verification scripts, self-test artifacts, final validation artifacts, and final benchmark outputs. The accepted Stage 2.2.2 results remain in `accepted_results/` unchanged.
2. Stage 2.1 hash: `{identity['STAGE21_CODE_HASH']}`.
3. Stage 2.2.1 code hash: `{identity['STAGE221_CODE_HASH']}` (accepted helper hash gate).
4. Final Stage 2.2.2 code hash: `{identity['STAGE222_CODE_HASH']}`; accepted pre-hotfix source hash: `{ACCEPTED_STAGE222_HASH}`.
5. Strategy hash: `{identity['STRATEGY_HASH']}`.
6. Execution hash: `{identity['EXECUTION_HASH']}`.
7. Data-content hash: `{identity['DATA_CONTENT_HASH']}`.
8. Manifest-document hash: `{identity['MANIFEST_DOCUMENT_HASH']}`.
9. Final Experiment ID: `{identity['experiment_id']}`; its identity basis includes the Stage 2.2.1 helper hash and excludes absolute paths.
10. Exact environment versions: {environment_text}.
11. Self-test result: **{self_test_receipt.get('status', 'UNKNOWN')}** ({self_test_receipt.get('test_count', 0)}/21).
12. Sanity-run result: **{'PASS' if sanity else sanity_receipt.get('status', 'UNKNOWN')}**; two tickers (TCS.NS and INFY.NS).
13. Validation PASS/WARN/FAIL counts: **{counts['PASS']}/{counts['WARN']}/{counts['FAIL']}**; overall **{status}**.
14. Full fresh-signal parity warning counts: generated {signal_summary.get('generated_rows')}, reference {signal_summary.get('reference_rows')}, exact {signal_summary.get('exact_matches')}, rows with any difference {signal_summary.get('rows_with_any_difference')}, float-only {signal_summary.get('rows_with_float_only_difference')}, signal-label mismatches {signal_summary.get('signal_label_mismatches')}, BUY/non-BUY membership changes {signal_summary.get('buy_nonbuy_membership_changes')}, missing/extra {signal_summary.get('missing_or_extra_rows')}; severity **{signal_summary.get('severity')}**.
15. Weekly-holiday warning: **WARN** — {point_limitation}
16. Point-in-time audit sample coverage: {len(pit_tickers)} stocks ({', '.join(pit_tickers)}), {len(pit_eras)} eras ({', '.join(pit_eras)}), {len(pit_rows)} field comparisons; genuine mismatch count {int(pit_rows['Status'].eq('FAIL').sum()) if not pit_rows.empty else 0}.
17. Exact parity vs current accepted Stage 2.2.2: **{parity_text}** — {parity_lines}.
18. Exposure-matched benchmark results for T2_20D: strategy {float(exposure_rows['Strategy Net Return %'].iloc[0]):.6f}% if available; {exposure_text}. Constant-average controls are labeled `EX_POST_CONSTANT_AVERAGE_EXPOSURE`; dynamic controls use prior-session exposure. Diagnostic control; does not establish causality.
19. Friction-sensitivity results for T2_20D: {friction_text}. The 1.0x case is 5 bps slippage plus 5 bps transaction cost per side and reuses official signals.
20. Snapshot-creation test result: **{self_test_receipt.get('snapshot_creation_test', 'UNKNOWN')}**; explicit-only creation, immutable-manifest refusal, yfinance version capture, manifest hash, market-data hashes, and ticker set were tested in a temporary directory.
21. Fresh-clone reproducibility test result: **{self_test_receipt.get('fresh_clone_reproducibility_test', 'UNKNOWN')}**; identity hashes and Experiment ID matched across two different temporary paths.
22. Runtime: {runtime_seconds:.3f} seconds for {'sanity' if sanity else 'official full benchmark'}.
23. Remaining known limitations: {SURVIVORSHIP_WARNING} Fresh Stage 2.1 regeneration differs from the legacy reference but has no missing/extra rows. Holiday-short weeks retain the conservative Stage 2.1 delay. Signal IDs remain attached to orders/trades by the accepted post-simulation Ticker + Signal Date join; direct dataclass lineage is deferred to Stage 2B to avoid parity risk.

Overall status: **{status}**.

**STRATEGY RULES CHANGED: NO**  
**EXECUTION BEHAVIOR CHANGED: NO**  
**STAGE 2B IMPLEMENTED: NO**
"""


def save_outputs(
    output_dir: Path,
    identity: Dict[str, Any],
    config: Any,
    candidates: pd.DataFrame,
    candidate_log: pd.DataFrame,
    data_availability: pd.DataFrame,
    orders: pd.DataFrame,
    trades: pd.DataFrame,
    results: Sequence[Dict[str, Any]],
    research: Dict[str, pd.DataFrame],
    signal_differences: pd.DataFrame,
    signal_summary: Dict[str, Any],
    parity_differences: pd.DataFrame,
    parity_status: pd.DataFrame,
    exposure_matched: pd.DataFrame,
    exposure_daily: pd.DataFrame,
    cost_table: pd.DataFrame,
    pit_audit: pd.DataFrame,
    checks: pd.DataFrame,
    validation_report: str,
    manifest: Dict[str, Any],
    environment: Dict[str, Any],
    report: str,
) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    analyzer = research.pop("_analyzer")
    candidate_tables = analyzer.candidate_tables()
    diagnostics = analyzer.diagnostic_tables()
    tables: Dict[str, pd.DataFrame] = {
        f"{PREFIX}_portfolio_summary.csv": research["portfolio_summary"],
        f"{PREFIX}_portfolio_trade_log.csv": trades,
        f"{PREFIX}_order_log.csv": orders,
        f"{PREFIX}_candidate_outcome_summary.csv": candidate_tables["candidate_outcome_summary"],
        f"{PREFIX}_signal_type_summary.csv": candidate_tables["signal_type_summary"],
        f"{PREFIX}_score_band_summary.csv": candidate_tables["score_band_summary"],
        f"{PREFIX}_score_matrix.csv": candidate_tables["score_matrix"],
        f"{PREFIX}_stock_summary.csv": diagnostics["stock_summary"],
        f"{PREFIX}_setup_summary.csv": diagnostics["setup_summary"],
        f"{PREFIX}_regime_summary.csv": diagnostics["regime_summary"],
        f"{PREFIX}_data_availability.csv": data_availability,
        f"{PREFIX}_signal_parity_differences.csv": signal_differences,
        f"{PREFIX}_signal_parity_summary.csv": pd.DataFrame([signal_summary]),
        f"{PREFIX}_stage222_acceptance_parity_report.csv": parity_differences,
        f"{PREFIX}_stage222_acceptance_parity_summary.csv": parity_status,
        f"{PREFIX}_exposure_summary.csv": research["exposure_summary"],
        f"{PREFIX}_nifty_benchmark.csv": research["nifty_benchmark"],
        f"{PREFIX}_benchmark_comparison.csv": research["benchmark_comparison"],
        f"{PREFIX}_exposure_matched_benchmarks.csv": exposure_matched,
        f"{PREFIX}_exposure_matched_daily.csv": exposure_daily,
        f"{PREFIX}_cost_sensitivity.csv": cost_table,
        f"{PREFIX}_point_in_time_audit.csv": pit_audit,
        f"{PREFIX}_validation_checks.csv": checks,
        f"{PREFIX}_daily_risk_metrics.csv": research["risk_metrics"],
        f"{PREFIX}_turnover_summary.csv": research["turnover_summary"],
        f"{PREFIX}_drawdown_summary.csv": research["drawdown_summary"],
        f"{PREFIX}_nifty_daily_equity.csv": research["nifty_equity"],
    }
    written: Dict[str, Path] = {}
    for name, frame in tables.items():
        written[name] = output_csv(output_dir, name, frame, identity)
    candidate_name = f"{PREFIX}_candidate_signal_log.csv.gz"
    written[candidate_name] = output_csv(output_dir, candidate_name, candidate_log, identity, gzip_output=True)
    for item in results:
        name = f"{PREFIX}_daily_equity_{item['variant']}.csv"
        written[name] = output_csv(output_dir, name, item["equity"], identity)
    text_files = {
        f"{PREFIX}_validation_report.txt": validation_report,
        "Stage2_2_2_Final_Delivery_Report.md": report,
        f"{PREFIX}_methodology_notes.txt": (
            "Candidate Research Scope: T1 / Max 63 Sessions / Independent Opportunity Simulation / Capacity-Free.\n"
            "Primary portfolio results are ten independent T1/T2 x 10/20/30/45/63-day portfolios.\n"
            "Stage 2.1 strategy thresholds and rules are unchanged. Friction scenarios are mechanical sensitivity only.\n"
            "Exposure-matched benchmarks are diagnostic controls and do not establish causality.\n"
            + SURVIVORSHIP_WARNING + "\n"
        ),
    }
    for name, text_value in text_files.items():
        path = output_dir / name
        path.write_text(text_value, encoding="utf-8")
        written[name] = path
    json_files = {
        f"{PREFIX}_experiment_identity.json": identity,
        f"{PREFIX}_environment_report.json": environment,
        f"{PREFIX}_data_manifest.json": manifest,
    }
    for name, value in json_files.items():
        path = output_dir / name
        write_json(path, value)
        written[name] = path
    return written


def build_config(s221: Any, args: argparse.Namespace, tickers: Sequence[str]) -> Any:
    data_dir = Path(args.frozen_data_dir)
    manifest_path = Path(args.manifest_path) if args.manifest_path else data_dir / "manifest.json"
    return s221.Stage22Config(
        test_start=args.test_start,
        test_end=args.test_end,
        warmup_anchor_start=args.warmup_anchor_start,
        starting_equity=args.starting_equity,
        risk_per_trade=args.risk_per_trade,
        max_open_positions=args.max_open_positions,
        max_position_pct=args.max_position_pct,
        slippage_bps=OFFICIAL_SLIPPAGE_BPS,
        transaction_cost_bps=OFFICIAL_TRANSACTION_BPS,
        output_directory=Path(args.output_dir),
        cache_directory=data_dir,
        reference_signal_log=Path(args.reference_signal_log),
        candidate_source="generated",
        data_mode="FROZEN",
        frozen_data_directory=data_dir,
        refresh_root_directory=data_dir.parent,
        data_manifest_path=manifest_path,
    )


def sanity_receipt_path(args: argparse.Namespace) -> Path:
    return Path(args.tests_dir) / "sanity_pass.json"


def self_test_receipt_path(args: argparse.Namespace) -> Path:
    return Path(args.tests_dir) / "self_test_pass.json"


def validate_self_test_receipt(
    args: argparse.Namespace,
    stage21_hash: str,
    stage221_hash: str,
    stage222_hash: str,
    data_hash: str,
) -> Dict[str, Any]:
    path = self_test_receipt_path(args)
    if not path.exists():
        raise RuntimeError("Run blocked: first run --self-test.")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "status": "PASS",
        "test_count": 21,
        "stage21_code_hash": stage21_hash,
        "stage221_code_hash": stage221_hash,
        "stage222_code_hash": stage222_hash,
        "data_content_hash": data_hash,
    }
    mismatches = [key for key, value in expected.items() if receipt.get(key) != value]
    if mismatches:
        raise RuntimeError(
            "Run blocked: self-test receipt is stale for " + ", ".join(mismatches)
        )
    return receipt


def validate_sanity_receipt(
    args: argparse.Namespace,
    stage21_hash: str,
    stage221_hash: str,
    stage222_hash: str,
    data_hash: str,
) -> Dict[str, Any]:
    path = sanity_receipt_path(args)
    if not path.exists():
        raise RuntimeError(
            "Official full run blocked: first run --self-test and then --sanity."
        )
    receipt = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "status": "PASS",
        "stage21_code_hash": stage21_hash,
        "stage221_code_hash": stage221_hash,
        "stage222_code_hash": stage222_hash,
        "data_content_hash": data_hash,
    }
    mismatches = [key for key, value in expected.items() if receipt.get(key) != value]
    if mismatches:
        raise RuntimeError(
            "Official full run blocked: sanity receipt is stale for " + ", ".join(mismatches)
        )
    return receipt


def run_pipeline(args: argparse.Namespace, s221: Any) -> bool:
    started = time.perf_counter()
    source_path = Path(__file__).resolve()
    stage21_path = Path(args.stage21_source)
    stage221_path = Path(args.stage221_source)
    reference_path = Path(args.reference_signal_log)
    data_dir = Path(args.frozen_data_dir)
    manifest_path = Path(args.manifest_path) if args.manifest_path else data_dir / "manifest.json"
    accepted_stage222_results = Path(args.accepted_stage222_results)
    stage21_before = sha256_file(stage21_path)
    stage221_before = sha256_file(stage221_path)
    stage222_before = sha256_file(source_path)
    if stage21_before != EXPECTED_STAGE21_HASH:
        raise RuntimeError(
            f"Stage 2.1 hash gate failed: expected {EXPECTED_STAGE21_HASH}, got {stage21_before}"
        )
    if stage221_before != EXPECTED_STAGE221_HASH:
        raise RuntimeError(
            f"Stage 2.2.1 helper hash gate failed: expected {EXPECTED_STAGE221_HASH}, got {stage221_before}"
        )
    if not reference_path.exists():
        raise FileNotFoundError(f"Reference signal log missing: {reference_path}")
    environment = environment_report()
    manifest, manifest_hash_map = verify_frozen_manifest(data_dir, manifest_path, DEFAULT_UNIVERSE)
    data_hash, _ = manifest_hashes(manifest)
    manifest_pre_ok = True
    self_test_receipt = validate_self_test_receipt(
        args, stage21_before, stage221_before, stage222_before, data_hash
    )
    sanity = bool(args.sanity)
    sanity_receipt: Dict[str, Any] = {}
    if sanity:
        tickers = ("TCS.NS", "INFY.NS")
    else:
        tickers = tuple(value.strip() for value in args.tickers.split(",") if value.strip())
        if tuple(tickers) != DEFAULT_UNIVERSE or args.test_start != OFFICIAL_START or args.test_end != OFFICIAL_END:
            raise RuntimeError(
                "Non-sanity Stage 2.2.2 is the official full benchmark only: exact dates and universe are required"
            )
        sanity_receipt = validate_sanity_receipt(
            args, stage21_before, stage221_before, stage222_before, data_hash
        )
    config = build_config(s221, args, tickers)
    stage21 = s221.load_stage21_module(stage21_path)
    reference_ok, reference_details = s221.check_reference_integrity(reference_path)
    if not reference_ok:
        raise RuntimeError(f"Reference signal log integrity failed: {reference_details}")

    candidate_engine = s221.CandidateSignalEngine(stage21, config, tickers)
    candidate_engine.load_data()
    candidate_engine.precompute()
    pit_ok, pit_audit, pit_limitation = point_in_time_audit(
        stage21, candidate_engine.engine, tickers
    )
    if not pit_ok:
        raise RuntimeError("Point-in-time audit failed; portfolio benchmark was not run")
    candidates = add_signal_ids(candidate_engine.generate())
    if candidates.empty:
        raise RuntimeError("Stage 2.1 regeneration produced no candidates")
    signal_differences, signal_summary, signal_severity = s221.analyze_signal_parity(
        candidates,
        reference_path,
        tickers,
        normalize_date(config.test_start),
        normalize_date(config.test_end),
        config.parity_tolerance,
    )
    if signal_severity == "FAIL":
        raise RuntimeError(
            "Fresh Stage 2.1 regeneration has missing/extra reference rows; benchmark stopped"
        )
    identity = identity_payloads(
        s221, config, candidate_engine.strategy_config, manifest,
        stage21_before, stage221_before, stage222_before, tickers,
    )
    for field in (
        "experiment_id", "STRATEGY_HASH", "EXECUTION_HASH", "STAGE21_CODE_HASH",
        "STAGE221_CODE_HASH", "STAGE222_CODE_HASH", "DATA_CONTENT_HASH",
        "MANIFEST_DOCUMENT_HASH",
    ):
        print(f"{field}: {identity[field]}")

    candidate_log = s221.CandidateOutcomeEngine(
        config, candidate_engine.engine.features
    ).run(candidates)
    candidate_log["Candidate Research Scope"] = (
        "T1 / Max 63 Sessions / Independent Opportunity Simulation / Capacity-Free"
    )
    results = s221.run_portfolios(config, candidate_engine.engine.features, candidates)
    for item in results:
        item["orders"] = carry_signal_ids(item["orders"], candidates)
        item["trades"] = carry_signal_ids(item["trades"], candidates)
    orders = flatten_results(results, "orders")
    trades = flatten_results(results, "trades")
    analyzer = s221.PerformanceAnalyzer(config, candidate_log, results)
    research = s221.build_portfolio_research_tables(
        config, analyzer, results, candidate_engine.engine.raw_data["^NSEI"]
    )
    research["_analyzer"] = analyzer
    exposure_matched, exposure_daily = build_exposure_matched_benchmarks(
        config, results, candidate_engine.engine.raw_data["^NSEI"]
    )
    cost_table = cost_sensitivity(
        s221, config, candidate_engine.engine.features, candidates, results
    )

    parity_ok: Optional[bool] = None
    parity_differences = pd.DataFrame(
        columns=["Category", "Key", "Field", "Final Value", "Accepted Stage 2.2.2 Value", "Absolute Difference"]
    )
    parity_status = pd.DataFrame()
    if not sanity:
        parity_ok, parity_differences, parity_status = stage222_acceptance_parity(
            candidates,
            orders,
            trades,
            results,
            research["portfolio_summary"],
            accepted_stage222_results,
        )

    _, hashes_after = verify_frozen_manifest(data_dir, manifest_path, DEFAULT_UNIVERSE)
    manifest_post_ok = hashes_after == manifest_hash_map
    expected_loaded = {"^NSEI", *tickers}
    loaded_set_ok = set(candidate_engine.loaded_file_hashes) == expected_loaded
    if not sanity:
        loaded_set_ok = loaded_set_ok and expected_loaded == set(manifest_hash_map)
    loaded_hash_ok = all(
        candidate_engine.loaded_file_hashes.get(ticker) == manifest_hash_map.get(ticker)
        for ticker in expected_loaded
    )
    official_manifest_set_ok = loaded_set_ok and loaded_hash_ok
    stage21_after = sha256_file(stage21_path)
    stage221_after = sha256_file(stage221_path)
    stage222_after = sha256_file(source_path)
    overall, checks, validation_report = validate_execution(
        config, candidates, results, official_manifest_set_ok,
        manifest_pre_ok, manifest_post_ok, stage21_before, stage21_after,
        stage221_before, stage221_after, stage222_before, stage222_after,
        pit_ok, reference_ok, parity_ok, cost_table, signal_summary,
        signal_severity, exposure_matched,
    )
    runtime_seconds = time.perf_counter() - started
    report = delivery_report(
        identity, config, overall, sanity, runtime_seconds, parity_status,
        pit_limitation, environment, checks, signal_summary, pit_audit,
        exposure_matched, cost_table, self_test_receipt, sanity_receipt,
    )
    written = save_outputs(
        Path(args.output_dir), identity, config, candidates, candidate_log,
        pd.DataFrame(candidate_engine.data_availability), orders, trades, results,
        research, signal_differences, signal_summary, parity_differences,
        parity_status, exposure_matched, exposure_daily, cost_table, pit_audit,
        checks, validation_report, manifest, environment, report,
    )
    if sanity and overall:
        receipt = {
            "status": "PASS",
            "stage21_code_hash": stage21_before,
            "stage221_code_hash": stage221_before,
            "stage222_code_hash": stage222_before,
            "data_content_hash": data_hash,
            "tickers": list(tickers),
            "test_start": config.test_start,
            "test_end": config.test_end,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json(sanity_receipt_path(args), receipt)
    if parity_ok is False and not parity_differences.empty:
        print("\nEVERY ACCEPTANCE PARITY DIFFERENCE:\n")
        print(parity_differences.to_string(index=False))
    print("\n" + validation_report)
    print(f"Runtime: {runtime_seconds:.3f} seconds")
    print(f"Files written: {len(written)} to {Path(args.output_dir)}")
    return overall


def build_parser() -> argparse.ArgumentParser:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    baseline_dir = repo_root / "baseline" / "stage2_1"
    stage221_root = repo_root / "stage2_2_1"
    stage222_root = repo_root / "stage2_2_2"
    parser = argparse.ArgumentParser(
        description="Stage 2.2.2 immutable baseline hardening benchmark"
    )
    parser.add_argument("--stage21-source", default=str(baseline_dir / "Stock_Alert_Stage2_1_Optimized_15Y.py"))
    parser.add_argument("--stage221-source", default=str(stage221_root / "Stock_Alert_Stage2_2_1_Reproducible_Benchmark.py"))
    parser.add_argument("--reference-signal-log", default=str(baseline_dir / "stage2_1_signal_log_15y.csv.gz"))
    parser.add_argument("--frozen-data-dir", default=str(stage221_root / "data" / "frozen"))
    parser.add_argument("--manifest-path", default="")
    parser.add_argument("--accepted-stage222-results", default=str(stage222_root / "accepted_results"))
    parser.add_argument("--output-dir", default=str(stage222_root / "results"))
    parser.add_argument("--tests-dir", default=str(stage222_root / "tests"))
    parser.add_argument("--test-start", default=OFFICIAL_START)
    parser.add_argument("--test-end", default=OFFICIAL_END)
    parser.add_argument("--warmup-anchor-start", default=OFFICIAL_START)
    parser.add_argument("--tickers", default=",".join(DEFAULT_UNIVERSE))
    parser.add_argument("--starting-equity", type=float, default=100000.0)
    parser.add_argument("--risk-per-trade", type=float, default=0.0075)
    parser.add_argument("--max-open-positions", type=int, default=5)
    parser.add_argument("--max-position-pct", type=float, default=0.25)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--sanity", action="store_true")
    parser.add_argument("--create-frozen-snapshot", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    s221 = import_source("stock_alert_stage221_accepted", Path(args.stage221_source))
    if args.create_frozen_snapshot:
        stage21 = s221.load_stage21_module(Path(args.stage21_source))
        create_frozen_snapshot(s221, stage21, args)
        return 0
    if args.self_test:
        run_stage222_self_tests(s221, args)
        return 0
    if args.sanity:
        args.test_start = "2024-01-01"
        args.test_end = "2024-12-31"
        args.output_dir = str(Path(args.tests_dir) / "sanity_results")
    try:
        passed = run_pipeline(args, s221)
    except Exception as exc:
        print(f"STAGE 2.2.2 FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
