from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


@dataclass
class FrozenContext:
    module: Any
    baseline: Any
    stage21: Any
    config: Any
    engine: Any
    candidates: pd.DataFrame
    calibration_tables: pd.DataFrame
    current_regime: pd.Series
    policy_config: Any
    dynamic_class: Any


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_frozen_context(repo_root: Path, dependency_root: Path) -> FrozenContext:
    stage2b1 = repo_root / "Stage 2B.1" / "stage2b"
    if str(stage2b1) not in sys.path:
        sys.path.insert(0, str(stage2b1))
    module = _load_module("stage2b1_frozen_for_stage4a2", stage2b1 / "Stock_Alert_Stage2B_1_Dynamic_Management.py")
    module.configure_paths(dependency_root, repo_root / "Stage 2B")
    baseline, stage21 = module.load_baseline()
    identity = json.loads((repo_root / "Stage 2B.1" / "results" / "stage2b_1_experiment_identity.json").read_text(encoding="utf-8"))
    tickers = identity["tickers"]
    config, engine, candidates = module.load_features_and_candidates(baseline, stage21, tickers)
    years = range(2016, 2027)
    anchor = tickers[0]
    first_sessions = {
        year: min(date for date in engine.engine.features[anchor].index if date.year == year)
        for year in years
    }
    _, tables = module.candidate_calibration(
        baseline, config, engine.engine.features, candidates, first_sessions
    )
    policy_values = json.loads(
        (repo_root / "Stage 2B.1" / "config" / "stage2b_1_policy_config.json").read_text(encoding="utf-8")
    )
    policy_config = module.PolicyConfig.from_mapping(policy_values)
    dynamic_class = module.DynamicBacktester.build(baseline)
    return FrozenContext(
        module=module,
        baseline=baseline,
        stage21=stage21,
        config=config,
        engine=engine,
        candidates=candidates,
        calibration_tables=tables,
        current_regime=engine.engine.market_history["MarketRegime"],
        policy_config=policy_config,
        dynamic_class=dynamic_class,
    )


def evaluation_config(context: FrozenContext, start: str = "2016-01-01", end: str = "2026-08-28") -> Any:
    b = context.baseline
    c = context.policy_config
    return b.Stage22Config(
        test_start=start,
        test_end=end,
        cache_directory=context.module.PATHS["frozen"],
        frozen_data_directory=context.module.PATHS["frozen"],
        data_mode="FROZEN",
        starting_equity=100000.0,
        risk_per_trade=0.0075,
        max_position_pct=0.25,
        max_open_positions=5,
        slippage_bps=5.0,
        transaction_cost_bps=5.0,
    )


def run_d1(context: FrozenContext, selected_signal_ids: Iterable[str], policy_name: str) -> dict[str, Any]:
    ids = set(map(str, selected_signal_ids))
    candidates = context.candidates[
        (context.candidates["Signal Date"] >= pd.Timestamp("2016-01-01"))
        & context.candidates["Signal ID"].astype(str).isin(ids)
    ].copy()
    bt = context.dynamic_class(
        evaluation_config(context),
        context.engine.engine.features,
        candidates,
        "D1_TRAIL_ONLY",
        "Target 2",
        63,
        policy="D1_TRAIL_ONLY",
        calibration_tables=context.calibration_tables,
        policy_config=context.policy_config,
        current_regime=context.current_regime,
    )
    result = bt.run()
    if result["runtime_errors"]:
        raise RuntimeError(f"Frozen D1 runtime errors for {policy_name}: {result['runtime_errors']}")
    result["policy_name"] = policy_name
    return result


def run_d0(context: FrozenContext, selected_signal_ids: Iterable[str], policy_name: str) -> dict[str, Any]:
    ids = set(map(str, selected_signal_ids))
    candidates = context.candidates[
        (context.candidates["Signal Date"] >= pd.Timestamp("2016-01-01"))
        & context.candidates["Signal ID"].astype(str).isin(ids)
    ].copy()
    result = context.baseline.PortfolioBacktester(
        evaluation_config(context),
        context.engine.engine.features,
        candidates,
        "T2_63D",
        "Target 2",
        63,
    ).run()
    result["policy_name"] = policy_name
    return result
