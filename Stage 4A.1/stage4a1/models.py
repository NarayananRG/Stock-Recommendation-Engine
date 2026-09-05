"""Read-only adapters to the frozen Stage 4A feature and model implementations."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pandas as pd


MODEL_ORDER = ["DUMMY_PRIOR", "LOGIT_RULE", "LOGIT_RAW", "LOGIT_FULL", "RF_FULL"]


def frozen_modules(repo_root: Path):
    frozen_path = str(repo_root / "Stage 4A" / "stage4a")
    if frozen_path not in sys.path:
        sys.path.insert(0, frozen_path)
    return importlib.import_module("features"), importlib.import_module("models"), importlib.import_module("joint_probability")


def contracts(repo_root: Path, config: dict[str, Any]):
    features_module, models_module, _ = frozen_modules(repo_root)
    results = repo_root / "Stage 3.1" / "results"
    feature_registry = pd.read_csv(results / "stage3_1_feature_registry.csv", low_memory=False)
    ml_registry = pd.read_csv(results / "stage3_1_ml_column_registry.csv", low_memory=False)
    feature_sets, registry, feature_hashes, type_maps = features_module.build_feature_contract(feature_registry, ml_registry, config)
    model_registry, model_hashes, model_specs = models_module.build_model_contract(config, feature_hashes)
    return feature_sets, registry, feature_hashes, type_maps, model_registry, model_hashes, model_specs


def fit_predict(repo_root: Path, *args, **kwargs):
    _, models_module, _ = frozen_modules(repo_root)
    return models_module.fit_predict_variant(*args, **kwargs)


def joint_predictions(repo_root: Path, predictions: pd.DataFrame, opportunity: pd.DataFrame) -> pd.DataFrame:
    _, _, joint_module = frozen_modules(repo_root)
    return joint_module.build_joint_predictions(predictions, opportunity)
