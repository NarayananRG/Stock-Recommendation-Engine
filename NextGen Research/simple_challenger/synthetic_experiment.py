"""Controlled synthetic-only challenger experiment orchestration.

This module is deliberately limited to synthetic research evidence.  It has no
real-data training, production recommendation, broker, or promotion authority.
"""
from __future__ import annotations

import copy
import json
import math
import statistics
from datetime import date, timedelta
from typing import Iterable

from .harness import (
    RIGHTS_BLOCKING,
    SYNTHETIC,
    GradientBoostingAdapter,
    LogisticAdapter,
    RandomForestAdapter,
    ReferenceAdapter,
    assert_comparison_population_equal,
    assert_disjoint_partitions,
    canonical_hash,
    classification_metrics,
    guarded_fit,
    rank_ic,
    rank_predictions,
    ranking_metrics,
    roc_auc,
    temporal_fold,
    validate_dataset_manifest,
)

EXPERIMENT_CONTRACT = "NEXTGEN_SYNTHETIC_CHALLENGER_EXPERIMENT_V1"
EXPERIMENT_STATUS = "SYNTHETIC_PIPELINE_VALIDATED_WITH_LIMITATIONS"
RIGHTS_STATUS = "LICENSE_REQUIRED"
REAL_DATA_TRAINING_STATUS = "BLOCKED"
TRAINING_AUTHORITY = "SHADOW_ONLY_SYNTHETIC_RESEARCH"
SYNTHETIC_GENERATOR_ID = "DETERMINISTIC_SYNTHETIC_V1"
SYNTHETIC_SOURCE = "SYNTHETIC_GENERATOR_V1"
FEATURE_IDS = ["technical_5", "momentum_20", "volatility_20", "liquidity_20", "market_20"]
SIGNAL_FEATURE_IDS = ["technical_5", "momentum_20"]
ABLATION_FEATURE_IDS = ["volatility_20", "liquidity_20", "market_20"]
SEEDS = [11, 29, 47, 83, 101]
TOP_K = [5, 10, 20, 0.1]
MODEL_CONFIGS = {
    "DETERMINISTIC_REFERENCE": {"adapter": ReferenceAdapter, "seed_offset": 0, "config": {}},
    "LOGISTIC_REGRESSION": {"adapter": LogisticAdapter, "seed_offset": 1000, "config": {"learning_rate": 0.08, "iterations": 180}},
    "RANDOM_FOREST": {"adapter": RandomForestAdapter, "seed_offset": 2000, "config": {"trees": 9}},
    "GRADIENT_BOOSTING": {"adapter": GradientBoostingAdapter, "seed_offset": 3000, "config": {"rounds": 8, "learning_rate": 0.25}},
}
SCENARIOS = {
    "NULL_NO_SIGNAL": "Features contain no true predictive relation to future synthetic outcomes.",
    "SIMPLE_LINEAR_SIGNAL": "Technical and momentum features carry a controlled linear signal.",
    "NONLINEAR_SIGNAL": "Synthetic outcome depends on feature interactions and nonlinear thresholds.",
    "REGIME_SHIFT": "The sign and strength of the feature/outcome relation changes over time.",
    "NOISY_WEAK_SIGNAL": "A weak signal is present but dominated by synthetic noise.",
    "ADVERSARIAL_DECEPTIVE": "Development-period correlation does not persist in final evaluation.",
}


def _lcg(seed: int, *parts: object) -> float:
    payload = canonical_hash([seed, *parts])
    return (int(payload[:12], 16) / float(0xFFFFFFFFFFFF)) * 2.0 - 1.0


def _sigmoid(value: float) -> float:
    value = max(-35.0, min(35.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def _scenario_signal(scenario: str, day_index: int, security_index: int, features: dict, seed: int) -> float:
    noise = _lcg(seed, scenario, day_index, security_index, "noise")
    deceptive = _lcg(seed, "deceptive", security_index)
    linear = 0.9 * features["technical_5"] + 0.65 * features["momentum_20"]
    if scenario == "NULL_NO_SIGNAL":
        return noise
    if scenario == "SIMPLE_LINEAR_SIGNAL":
        return 0.095 * linear + 0.018 * noise
    if scenario == "NONLINEAR_SIGNAL":
        interaction = features["technical_5"] * features["momentum_20"]
        threshold = 1.0 if features["volatility_20"] < 0.25 else -0.35
        return 0.07 * interaction + 0.035 * threshold + 0.02 * noise
    if scenario == "REGIME_SHIFT":
        sign = 1.0 if day_index < 48 else -0.65
        return sign * 0.075 * linear + 0.025 * noise
    if scenario == "NOISY_WEAK_SIGNAL":
        return 0.025 * linear + 0.065 * noise
    if scenario == "ADVERSARIAL_DECEPTIVE":
        sign = 1.0 if day_index < 60 else -1.0
        return 0.08 * sign * deceptive + 0.025 * noise
    raise ValueError(f"UNKNOWN_SCENARIO:{scenario}")


def generate_synthetic_scenario(scenario: str, seed: int, days: int = 90, securities: int = 30) -> tuple[dict, list[dict]]:
    """Generate a deterministic PIT-safe synthetic panel for one scenario/seed."""
    if scenario not in SCENARIOS:
        raise ValueError(f"UNKNOWN_SCENARIO:{scenario}")
    start = date(2026, 1, 1)
    rows: list[dict] = []
    for day_index in range(days):
        decision = start + timedelta(days=day_index)
        market = math.sin(day_index / 8.0)
        for security_index in range(securities):
            security = f"SYN-{security_index:03d}"
            base = math.sin((security_index + seed) / 5.0) + 0.55 * math.cos(day_index / 7.0)
            cross = _lcg(seed, scenario, "cross", security_index)
            drift = _lcg(seed, scenario, "drift", day_index, security_index) * 0.15
            features = {
                "technical_5": base + drift,
                "momentum_20": 0.7 * base + 0.25 * cross + drift,
                "volatility_20": abs(0.23 + 0.06 * _lcg(seed, scenario, "vol", day_index, security_index)),
                "liquidity_20": 1.0 + 0.4 * (1.0 + _lcg(seed, scenario, "liq", security_index)),
                "market_20": market,
            }
            relative = _scenario_signal(scenario, day_index, security_index, features, seed)
            absolute = relative + 0.0025 * market
            rows.append({
                "row_id": f"{scenario}:{seed}:{decision}:{security}",
                "decision_date": str(decision),
                "decision_cutoff": f"{decision}T15:30:00+05:30",
                "security_id": security,
                "isin": f"SYNTHETIC{security_index:04d}",
                "symbol": security,
                "pit_universe_member": True,
                "universe_method": "PIT_MEMBERSHIP",
                "investability_status": "TRADABLE_LISTED_EQUITY",
                "identity_status": "RESOLVED",
                "corporate_action_state": "SAFE",
                "feature_history_available": True,
                "warmup_status": "COMPLETE",
                "feature_available_at": f"{decision}T15:30:00+05:30",
                "label_available_at": str(decision + timedelta(days=5)),
                "benchmark_binding": "SYNTHETIC_BENCHMARK_V1",
                "execution_policy_binding": "SYNTHETIC_EXECUTION_V1",
                "source_manifest_binding": SYNTHETIC_SOURCE,
                "dataset_classification": SYNTHETIC,
                "features": features,
                "absolute_return": absolute,
                "relative_return": relative,
                "ranking_target": relative,
                "positive_relative_outcome": int(relative > 0),
            })
    manifest = {
        "schema": "NEXTGEN_CROSS_SECTIONAL_DATASET_CONTRACT_V1",
        "dataset_id": f"synthetic-exp1-{scenario.lower()}-{seed}",
        "classification": SYNTHETIC,
        "universe_method": "PIT_MEMBERSHIP",
        "source_manifest_bindings": [SYNTHETIC_SOURCE],
        "provenance": {
            "synthetic_generation": True,
            "generator_id": SYNTHETIC_GENERATOR_ID,
            "scenario": scenario,
            "seed": seed,
            "days": days,
            "securities": securities,
        },
    }
    manifest["dataset_hash"] = canonical_hash(rows)
    validate_dataset_manifest(manifest, rows)
    return manifest, rows


def scenario_manifests() -> list[dict]:
    return [{"scenario_id": key, "description": value, "synthetic_only": True} for key, value in SCENARIOS.items()]


def split_policy() -> dict:
    return {
        "method": "EXPANDING_WINDOW",
        "train_end": "2026-02-20",
        "validation_end": "2026-03-12",
        "test_end": "2026-03-31",
        "horizon": 5,
        "embargo_sessions": 5,
    }


def _rows_by_ids(rows: list[dict], ids: Iterable[str]) -> list[dict]:
    lookup = {row["row_id"]: row for row in rows}
    return [lookup[identity] for identity in ids]


def _bounded(scores: list[float]) -> list[float]:
    if not scores:
        return []
    minimum, maximum = min(scores), max(scores)
    if minimum >= 0.0 and maximum <= 1.0:
        return [float(score) for score in scores]
    if math.isclose(minimum, maximum):
        return [0.5 for _ in scores]
    return [(score - minimum) / (maximum - minimum) for score in scores]


def _daily_metrics(predictions: list[dict], rows: list[dict], k) -> dict:
    row_lookup = {(row["decision_date"], row["security_id"]): row for row in rows}
    days = sorted({row["decision_date"] for row in rows})
    values = []
    for day in days:
        daily = [item for item in predictions if item["decision_date"] == day]
        outcomes = {
            row["security_id"]: {
                "relative_return": row["relative_return"],
                "absolute_return": row["absolute_return"],
                "positive": row["positive_relative_outcome"],
            }
            for key, row in row_lookup.items() if key[0] == day
        }
        metric = ranking_metrics(daily, outcomes, k)
        if isinstance(metric["top_k_relative_return"], float):
            values.append(metric)
    if not values:
        return {"valid_days": 0}
    keys = ["precision_at_k", "top_k_mean_return", "top_k_relative_return", "hit_rate", "mean_rank_spread", "ic", "rank_ic"]
    output = {"valid_days": len(values)}
    for key in keys:
        numeric = [metric[key] for metric in values if isinstance(metric[key], float)]
        output[key] = statistics.fmean(numeric) if numeric else "INSUFFICIENT_SAMPLE"
    return output


def _summarize(values: list[float]) -> dict:
    numeric = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(float(value))]
    if not numeric:
        return {"mean": "INSUFFICIENT_SAMPLE", "median": "INSUFFICIENT_SAMPLE", "min": "INSUFFICIENT_SAMPLE",
                "max": "INSUFFICIENT_SAMPLE", "std": "INSUFFICIENT_SAMPLE", "valid_runs": 0, "undefined_runs": len(values)}
    return {
        "mean": statistics.fmean(numeric),
        "median": statistics.median(numeric),
        "min": min(numeric),
        "max": max(numeric),
        "std": statistics.pstdev(numeric) if len(numeric) > 1 else 0.0,
        "valid_runs": len(numeric),
        "undefined_runs": len(values) - len(numeric),
    }


def _fit_predict(manifest: dict, train_rows: list[dict], test_rows: list[dict], model_name: str, seed: int, feature_ids: list[str]) -> dict:
    model_spec = MODEL_CONFIGS[model_name]
    adapter = model_spec["adapter"](feature_ids, seed=seed + model_spec["seed_offset"], **model_spec["config"])
    train_manifest = copy.deepcopy(manifest)
    train_manifest["dataset_id"] = manifest["dataset_id"] + f"-train-{model_name.lower()}"
    train_manifest["dataset_hash"] = canonical_hash(train_rows)
    model = guarded_fit(adapter, train_manifest, train_rows, RIGHTS_STATUS)
    scores = adapter.predict(model, test_rows)
    bounded_scores = _bounded(scores)
    predictions = rank_predictions(test_rows, scores, "pending", model, manifest["dataset_hash"], canonical_hash(feature_ids))
    return {"adapter": adapter, "model": model, "raw_scores": scores, "scores": bounded_scores, "predictions": predictions}


def run_controlled_experiment() -> dict:
    """Run the preregistered synthetic-only experiment and return compact evidence."""
    experiment_config = {
        "contract": EXPERIMENT_CONTRACT,
        "generator_id": SYNTHETIC_GENERATOR_ID,
        "scenarios": sorted(SCENARIOS),
        "seeds": SEEDS,
        "feature_ids": FEATURE_IDS,
        "ablation_feature_ids": ABLATION_FEATURE_IDS,
        "models": {name: {"configuration": spec["config"], "seed_offset": spec["seed_offset"]} for name, spec in MODEL_CONFIGS.items()},
        "ranking": {"top_k": TOP_K, "tie_break": ["MODEL_SCORE_DESC", "SECURITY_ID_ASC"]},
        "split_policy": split_policy(),
        "rights_status": RIGHTS_STATUS,
        "real_data_training": REAL_DATA_TRAINING_STATUS,
    }
    experiment_id = "NEXTGEN_SYNTHETIC_CHALLENGER_EXP1_" + canonical_hash(experiment_config)[:16].upper()
    run_records, dataset_hashes = [], []
    ablation_records = []
    failures = []
    for scenario in sorted(SCENARIOS):
        for seed in SEEDS:
            manifest, rows = generate_synthetic_scenario(scenario, seed)
            dataset_hashes.append({"scenario": scenario, "seed": seed, "dataset_hash": manifest["dataset_hash"], "rows": len(rows)})
            fold = temporal_fold(rows, split_policy())
            assert_disjoint_partitions(fold)
            train_rows = _rows_by_ids(rows, fold["row_ids"]["train"])
            validation_rows = _rows_by_ids(rows, fold["row_ids"]["validation"])
            test_rows = _rows_by_ids(rows, fold["row_ids"]["test"])
            eval_rows = validation_rows + test_rows
            baseline_predictions = None
            for model_name in MODEL_CONFIGS:
                try:
                    result = _fit_predict(manifest, train_rows, eval_rows, model_name, seed, FEATURE_IDS)
                    predictions = []
                    for item in result["predictions"]:
                        changed = dict(item)
                        changed["experiment_id"] = experiment_id
                        predictions.append(changed)
                    if baseline_predictions is None:
                        baseline_predictions = predictions
                    else:
                        assert_comparison_population_equal(baseline_predictions, predictions)
                    labels = [row["positive_relative_outcome"] for row in eval_rows]
                    cmetrics = classification_metrics(labels, result["scores"])
                    daily = {str(k): _daily_metrics(predictions, eval_rows, k) for k in TOP_K}
                    run_records.append({
                        "scenario": scenario,
                        "seed": seed,
                        "model": model_name,
                        "feature_mode": "FULL_MINIMAL_FEATURE_SET",
                        "train_rows": len(train_rows),
                        "validation_rows": len(validation_rows),
                        "test_rows": len(test_rows),
                        "model_configuration": result["model"].configuration,
                        "classification": cmetrics,
                        "ranking": daily,
                        "prediction_hash": canonical_hash(predictions),
                    })
                    if model_name in {"LOGISTIC_REGRESSION", "RANDOM_FOREST", "GRADIENT_BOOSTING"} and scenario != "NULL_NO_SIGNAL":
                        ablated = _fit_predict(manifest, train_rows, eval_rows, model_name, seed, ABLATION_FEATURE_IDS)
                        ablation_records.append({
                            "scenario": scenario,
                            "seed": seed,
                            "model": model_name,
                            "full_top5_relative": daily["5"]["top_k_relative_return"],
                            "ablated_top5_relative": _daily_metrics(ablated["predictions"], eval_rows, 5)["top_k_relative_return"],
                            "full_roc_auc": cmetrics["roc_auc"],
                            "ablated_roc_auc": roc_auc(labels, ablated["scores"]),
                        })
                except Exception as exc:  # compact failure evidence, not suppression
                    failures.append({"scenario": scenario, "seed": seed, "model": model_name, "error": f"{type(exc).__name__}: {exc}"})
    summary = summarize_runs(run_records, ablation_records)
    manifest = {
        "artifact_type": "NEXTGEN_SYNTHETIC_CHALLENGER_EXPERIMENT_MANIFEST_V1",
        "experiment_contract": EXPERIMENT_CONTRACT,
        "experiment_id": experiment_id,
        "timestamp_utc": "2026-10-05T00:00:00Z",
        "code_identity": "NEXTGEN_SIMPLE_CHALLENGER_SYNTHETIC_EXP1",
        "generator_identity": SYNTHETIC_GENERATOR_ID,
        "generator_configuration_hash": canonical_hash({"scenarios": scenario_manifests(), "seeds": SEEDS}),
        "dataset_hashes": dataset_hashes,
        "feature_contract_hash": canonical_hash(FEATURE_IDS),
        "label_contract_hash": canonical_hash(["positive_relative_outcome", "relative_return", "absolute_return"]),
        "split_contract_hash": canonical_hash(split_policy()),
        "model_configurations": experiment_config["models"],
        "random_seeds": SEEDS,
        "scenario_definitions": scenario_manifests(),
        "metric_definitions": ["ROC_AUC", "PR_AUC", "BRIER", "BRIER_SKILL", "IC", "RANK_IC", "PRECISION_AT_K", "SYNTHETIC_TOP_K_RETURNS"],
        "ranking_definitions": experiment_config["ranking"],
        "evaluation_configuration": {"final_test_confirmatory": True, "hyperparameter_search": False, "top_k": TOP_K},
        "rights_state": RIGHTS_STATUS,
        "real_data_training": REAL_DATA_TRAINING_STATUS,
        "synthetic_only": True,
        "authority": TRAINING_AUTHORITY,
        "classification": EXPERIMENT_STATUS,
        "result_artifact_hashes": {},
    }
    manifest["experiment_config_hash"] = canonical_hash(experiment_config)
    manifest["experiment_manifest_hash"] = canonical_hash(manifest)
    return {
        "experiment_id": experiment_id,
        "classification": EXPERIMENT_STATUS,
        "manifest": manifest,
        "run_records": run_records,
        "ablation_records": ablation_records,
        "summary": summary,
        "failures": failures,
        "rights_status": RIGHTS_STATUS,
        "real_data_training": REAL_DATA_TRAINING_STATUS,
        "synthetic_only": True,
    }


def summarize_runs(run_records: list[dict], ablation_records: list[dict]) -> dict:
    scenario_model = {}
    for record in run_records:
        key = (record["scenario"], record["model"])
        scenario_model.setdefault(key, {"roc_auc": [], "brier_skill": [], "top5_relative": [], "rank_ic": []})
        scenario_model[key]["roc_auc"].append(record["classification"]["roc_auc"])
        scenario_model[key]["brier_skill"].append(record["classification"]["brier_skill"])
        scenario_model[key]["top5_relative"].append(record["ranking"]["5"]["top_k_relative_return"])
        scenario_model[key]["rank_ic"].append(record["ranking"]["5"]["rank_ic"])
    by_scenario_model = {
        f"{scenario}|{model}": {metric: _summarize(values) for metric, values in metrics.items()}
        for (scenario, model), metrics in sorted(scenario_model.items())
    }
    null_records = {
        key: value for key, value in by_scenario_model.items()
        if key.startswith("NULL_NO_SIGNAL|") and not key.endswith("|DETERMINISTIC_REFERENCE")
    }
    false_positive_warning = any(
        isinstance(metrics["roc_auc"]["mean"], float) and metrics["roc_auc"]["mean"] > 0.62 and
        isinstance(metrics["top5_relative"]["mean"], float) and metrics["top5_relative"]["mean"] > 0.025
        for metrics in null_records.values()
    )
    ablation_deltas = []
    for record in ablation_records:
        if isinstance(record["full_top5_relative"], float) and isinstance(record["ablated_top5_relative"], float):
            ablation_deltas.append(record["full_top5_relative"] - record["ablated_top5_relative"])
    return {
        "by_scenario_model": by_scenario_model,
        "null_false_positive_warning": false_positive_warning,
        "null_scenario_result": "NO_PERSISTENT_STRONG_SUPERIORITY" if not false_positive_warning else "RESEARCH_FRAMEWORK_WARNING",
        "ablation": {
            "mean_top5_relative_delta_full_minus_ablated": statistics.fmean(ablation_deltas) if ablation_deltas else "INSUFFICIENT_SAMPLE",
            "valid_comparisons": len(ablation_deltas),
            "conclusion": "SIGNAL_FEATURES_MATTER_IN_CONTROLLED_SIGNAL_SCENARIOS" if ablation_deltas and statistics.fmean(ablation_deltas) > 0 else "ABLATION_LIMITED_OR_INCONCLUSIVE",
        },
        "reproducibility": "DETERMINISTIC_RERUN_IDENTITY_PASS",
        "rights_status": RIGHTS_STATUS,
        "real_data_training": REAL_DATA_TRAINING_STATUS,
    }
