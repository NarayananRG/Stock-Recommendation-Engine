"""Frozen Stage 4A model specifications and fit/predict helpers."""
from __future__ import annotations

import time
import warnings
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from hashing import canonical_json_hash
from preprocessing import assert_finite_transformed, build_preprocessor, preprocessing_audit_row


MODEL_ORDER = ["DUMMY_PRIOR", "LOGIT_RULE", "LOGIT_RAW", "LOGIT_FULL", "RF_FULL"]


def build_model_contract(
    config: dict[str, Any], feature_hashes: dict[str, str]
) -> tuple[pd.DataFrame, dict[str, str], dict[str, dict[str, Any]]]:
    rows = []
    hashes: dict[str, str] = {}
    specs: dict[str, dict[str, Any]] = {}
    for variant in MODEL_ORDER:
        declared = config["model_variants"][variant]
        family = declared["family"]
        feature_set = declared["feature_set"]
        if family == "LOGISTIC_L2":
            parameters = dict(config["logistic_parameters"])
            preprocessing = {
                **config["preprocessing"],
                "numeric_scaler": "StandardScaler",
            }
        elif family == "RANDOM_FOREST_FIXED":
            parameters = dict(config["random_forest_parameters"])
            preprocessing = {
                **config["preprocessing"],
                "numeric_scaler": "NONE",
            }
        else:
            parameters = {"strategy": "training_fold_prior"}
            preprocessing = {"features": "NONE", "fit_scope": "training_fold_only"}
        payload = {
            "model_variant": variant,
            "model_family": family,
            "feature_set": feature_set,
            "feature_set_hash": feature_hashes.get(feature_set, "NONE"),
            "hyperparameters": parameters,
            "preprocessing": preprocessing,
            "random_seed": config["random_seed"],
        }
        model_hash = canonical_json_hash(payload)
        specs[variant] = payload
        hashes[variant] = model_hash
        rows.append({
            "Model Variant": variant,
            "Model Family": family,
            "Feature Set": feature_set,
            "Feature Set Hash": feature_hashes.get(feature_set, "NONE"),
            "Hyperparameters": str(parameters),
            "Preprocessing": str(preprocessing),
            "Random Seed": config["random_seed"],
            "Model Spec Hash": model_hash,
        })
    return pd.DataFrame(rows), hashes, specs


def _model_for_variant(variant: str, config: dict[str, Any]) -> Any:
    if variant.startswith("LOGIT_"):
        return LogisticRegression(**config["logistic_parameters"])
    if variant == "RF_FULL":
        return RandomForestClassifier(**config["random_forest_parameters"])
    raise ValueError(f"No estimator for {variant}")


def fit_predict_variant(
    variant: str,
    target: str,
    year: int,
    feature_set: str,
    feature_names: list[str],
    type_map: dict[str, list[str]],
    train_frame: pd.DataFrame,
    evaluation_frame: pd.DataFrame,
    y_train: pd.Series,
    config: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    y = y_train.astype(int).to_numpy()
    if len(np.unique(y)) != 2:
        raise ValueError(f"{target} {year} {variant} training fold does not contain both classes")
    prevalence = float(np.mean(y))
    start_fit = time.perf_counter()
    coefficient_rows: list[dict[str, Any]] = []
    if variant == "DUMMY_PRIOR":
        fit_seconds = time.perf_counter() - start_fit
        start_predict = time.perf_counter()
        probabilities = np.full(len(evaluation_frame), prevalence, dtype=float)
        prediction_seconds = time.perf_counter() - start_predict
        fit_audit = {
            "Target": target,
            "Evaluation Year": int(year),
            "Model Variant": variant,
            "Feature Set": "NONE",
            "Training Rows": len(y),
            "Training Positives": int(y.sum()),
            "Training Negatives": int(len(y) - y.sum()),
            "Training Prevalence": prevalence,
            "Evaluation Scored Rows": len(evaluation_frame),
            "Raw Feature Count": 0,
            "Encoded Feature Count": 0,
            "Fit Seconds": fit_seconds,
            "Prediction Seconds": prediction_seconds,
            "Warnings": "",
            "Convergence Status": "NOT_APPLICABLE",
            "Random Seed": config["random_seed"],
        }
        return probabilities, fit_audit, None, coefficient_rows

    scale_numeric = variant.startswith("LOGIT_")
    numeric = type_map["numeric"]
    categorical = type_map["categorical"]
    preprocessor = build_preprocessor(numeric, categorical, scale_numeric)
    train_x = train_frame[feature_names]
    evaluation_x = evaluation_frame[feature_names]
    estimator = _model_for_variant(variant, config)
    caught: list[warnings.WarningMessage]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        transformed_train = preprocessor.fit_transform(train_x)
        assert_finite_transformed(transformed_train)
        estimator.fit(transformed_train, y)
    fit_seconds = time.perf_counter() - start_fit
    start_predict = time.perf_counter()
    transformed_eval = preprocessor.transform(evaluation_x)
    assert_finite_transformed(transformed_eval)
    probabilities = estimator.predict_proba(transformed_eval)[:, 1]
    prediction_seconds = time.perf_counter() - start_predict
    encoded_names = preprocessor.get_feature_names_out().tolist()
    warning_text = " | ".join(f"{item.category.__name__}: {item.message}" for item in caught)
    convergence = "WARNING" if any(issubclass(item.category, ConvergenceWarning) for item in caught) else "CONVERGED"
    fit_audit = {
        "Target": target,
        "Evaluation Year": int(year),
        "Model Variant": variant,
        "Feature Set": feature_set,
        "Training Rows": len(y),
        "Training Positives": int(y.sum()),
        "Training Negatives": int(len(y) - y.sum()),
        "Training Prevalence": prevalence,
        "Evaluation Scored Rows": len(evaluation_frame),
        "Raw Feature Count": len(feature_names),
        "Encoded Feature Count": len(encoded_names),
        "Fit Seconds": fit_seconds,
        "Prediction Seconds": prediction_seconds,
        "Warnings": warning_text,
        "Convergence Status": convergence,
        "Random Seed": config["random_seed"],
    }
    preprocess_audit = preprocessing_audit_row(
        target, year, variant, feature_set, train_x, evaluation_x,
        numeric, categorical, scale_numeric, len(encoded_names),
    )
    if variant.startswith("LOGIT_"):
        coefficient_rows = [
            {
                "Target": target,
                "Evaluation Year": int(year),
                "Model Variant": variant,
                "Encoded Feature": name,
                "Coefficient": float(coefficient),
            }
            for name, coefficient in zip(encoded_names, estimator.coef_[0], strict=True)
        ]
    return probabilities, fit_audit, preprocess_audit, coefficient_rows
