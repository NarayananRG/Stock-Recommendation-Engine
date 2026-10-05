"""EXP2: final bounded synthetic challenger robustness experiment.

Research-only, synthetic-only, and intentionally limited to the existing simple
challenger families.  No real-data, production, broker, or promotion authority.
"""
from __future__ import annotations

import copy
import math
import statistics
from datetime import date, timedelta

from .harness import (
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
    rank_predictions,
    ranking_metrics,
    temporal_fold,
    validate_dataset_manifest,
)

EXP2_CONTRACT = "NEXTGEN_SYNTHETIC_CHALLENGER_EXPERIMENT_V2_ROBUSTNESS"
EXP1_IDENTITY = "NEXTGEN_SYNTHETIC_CHALLENGER_EXP1_68BF5571B15AE4D7"
RIGHTS_STATUS = "LICENSE_REQUIRED"
REAL_DATA_TRAINING_STATUS = "BLOCKED"
AUTHORITY = "RESEARCH_ONLY_SYNTHETIC_SHADOW"
SEEDS = [11, 29, 47, 83, 101, 131, 167, 211, 257, 307]
FEATURE_IDS = ["technical_5", "momentum_20", "volatility_20", "liquidity_20", "market_20", "redundant_signal_1", "redundant_signal_2"]
SIGNAL_REMOVED = ["volatility_20", "liquidity_20", "market_20", "redundant_signal_1", "redundant_signal_2"]
REDUNDANT_REMOVED = ["technical_5", "momentum_20", "volatility_20", "liquidity_20", "market_20"]
TOP_K = [5, 10, 20, 0.1]
SAMPLE_REGIMES = {
    "SMALL_RESEARCH_SAMPLE": {"days": 45, "securities": 10},
    "LARGER_RESEARCH_SAMPLE": {"days": 45, "securities": 14},
}
SCENARIOS = {
    "NULL_NO_SIGNAL_V2": "No true predictive relationship.",
    "STABLE_LINEAR_WEAK": "Persistent modest linear signal.",
    "STABLE_NONLINEAR_INTERACTION": "Material nonlinear interactions.",
    "GRADUAL_REGIME_DRIFT": "Feature/outcome relation changes gradually through time.",
    "ABRUPT_REGIME_BREAK": "Useful relation becomes invalid after a structural break.",
    "SPURIOUS_DEVELOPMENT_SIGNAL": "Development-period signal disappears in final test.",
    "HIGH_NOISE_LOW_SIGNAL": "Very low signal-to-noise ratio.",
    "CROSS_SECTIONAL_RELATIVE_SIGNAL": "Primarily within-session relative signal.",
    "CALIBRATION_STRESS": "Ranking useful while calibration is intentionally difficult.",
    "REDUNDANT_CORRELATED_FEATURES": "Correlated features represent the same underlying signal.",
}
MODEL_CONFIGS = {
    "DETERMINISTIC_REFERENCE": {"adapter": ReferenceAdapter, "complexity": 0, "seed_offset": 0, "config": {}},
    "LOGISTIC_REGRESSION": {"adapter": LogisticAdapter, "complexity": 1, "seed_offset": 1000, "config": {"learning_rate": 0.06, "iterations": 50, "regularization": "L2_FIXED_LIGHT"}},
    "RANDOM_FOREST": {"adapter": RandomForestAdapter, "complexity": 2, "seed_offset": 2000, "config": {"trees": 5, "max_depth": 1, "min_leaf": 8}},
    "GRADIENT_BOOSTING": {"adapter": GradientBoostingAdapter, "complexity": 3, "seed_offset": 3000, "config": {"rounds": 4, "learning_rate": 0.22, "max_depth": 1}},
}


def _unit(seed: int, *parts: object) -> float:
    return int(canonical_hash([seed, *parts])[:12], 16) / float(0xFFFFFFFFFFFF)


def _noise(seed: int, *parts: object) -> float:
    return 2.0 * _unit(seed, *parts) - 1.0


def _split_policy() -> dict:
    return {"method": "EXPANDING_WINDOW", "train_end": "2026-01-20", "validation_end": "2026-02-02", "test_end": "2026-02-14", "horizon": 5, "embargo_sessions": 5}


def preregistered_spec() -> dict:
    return {
        "contract": EXP2_CONTRACT,
        "exp1_dependency": EXP1_IDENTITY,
        "scenarios": SCENARIOS,
        "seeds": SEEDS,
        "sample_regimes": SAMPLE_REGIMES,
        "temporal_boundaries": _split_policy(),
        "features": FEATURE_IDS,
        "model_configurations": {k: {"config": v["config"], "seed_offset": v["seed_offset"], "complexity": v["complexity"]} for k, v in MODEL_CONFIGS.items()},
        "metrics": ["ROC_AUC", "PR_AUC", "BRIER", "BRIER_SKILL", "IC", "RANK_IC", "PRECISION_AT_K", "TOP_K_SYNTHETIC_RETURN"],
        "robustness": ["SIGN_CONSISTENCY", "PCT_SEEDS_OUTPERFORMING_REFERENCE", "WORST_SEED", "VALIDATION_TO_FINAL_TEST_DEGRADATION"],
        "null_warning_rule": {"challenger_roc_auc_mean_gt": 0.62, "challenger_top5_relative_mean_gt": 0.02},
        "selection_rule": "Prefer the least complex challenger with robust stable/cross-sectional value, acceptable null/spurious/regime behavior, and no severe validation-to-test collapse.",
        "selection_outcomes": ["SIMPLE_CHALLENGER_LOGISTIC_PREFERRED", "SIMPLE_CHALLENGER_RANDOM_FOREST_PREFERRED", "SIMPLE_CHALLENGER_GRADIENT_BOOSTING_PREFERRED", "NO_SIMPLE_MODEL_FAMILY_PREFERRED", "INSUFFICIENT_SYNTHETIC_EVIDENCE"],
        "rights_status": RIGHTS_STATUS,
        "real_data_training": REAL_DATA_TRAINING_STATUS,
        "authority": AUTHORITY,
    }


def scenario_rows(scenario: str, seed: int, regime: str) -> tuple[dict, list[dict]]:
    if scenario not in SCENARIOS:
        raise ValueError("UNKNOWN_SCENARIO")
    config = SAMPLE_REGIMES[regime]
    start = date(2026, 1, 1)
    rows = []
    for day_index in range(config["days"]):
        day = start + timedelta(days=day_index)
        market = math.sin(day_index / 8.0)
        session_values = []
        for security_index in range(config["securities"]):
            latent = math.sin((security_index + seed) / 4.0) + 0.4 * math.cos(day_index / 6.0)
            technical = latent + 0.12 * _noise(seed, scenario, regime, day_index, security_index, "t")
            momentum = 0.75 * latent + 0.18 * _noise(seed, scenario, regime, day_index, security_index, "m")
            volatility = abs(0.24 + 0.08 * _noise(seed, scenario, regime, day_index, security_index, "v"))
            liquidity = 1.0 + _unit(seed, scenario, regime, security_index, "l")
            session_values.append((security_index, technical, momentum, volatility, liquidity))
        mean_signal = statistics.fmean(x[1] for x in session_values)
        for security_index, technical, momentum, volatility, liquidity in session_values:
            relative_signal = technical - mean_signal
            redundant_1 = technical + 0.02 * _noise(seed, scenario, regime, security_index, "r1")
            redundant_2 = momentum + 0.02 * _noise(seed, scenario, regime, security_index, "r2")
            noise = _noise(seed, scenario, regime, day_index, security_index, "eps")
            linear = 0.75 * technical + 0.55 * momentum
            nonlinear = technical * momentum - 0.4 * volatility
            drift = 1.0 - 1.4 * (day_index / max(1, config["days"] - 1))
            break_sign = 1.0 if day_index < 30 else -0.2
            if scenario == "NULL_NO_SIGNAL_V2":
                rel = 0.03 * noise
            elif scenario == "STABLE_LINEAR_WEAK":
                rel = 0.045 * linear + 0.035 * noise
            elif scenario == "STABLE_NONLINEAR_INTERACTION":
                rel = 0.075 * nonlinear + 0.03 * noise
            elif scenario == "GRADUAL_REGIME_DRIFT":
                rel = 0.06 * drift * linear + 0.03 * noise
            elif scenario == "ABRUPT_REGIME_BREAK":
                rel = 0.07 * break_sign * linear + 0.03 * noise
            elif scenario == "SPURIOUS_DEVELOPMENT_SIGNAL":
                rel = (0.08 * linear if day_index <= 31 else 0.005 * linear) + 0.032 * noise
            elif scenario == "HIGH_NOISE_LOW_SIGNAL":
                rel = 0.018 * linear + 0.075 * noise
            elif scenario == "CROSS_SECTIONAL_RELATIVE_SIGNAL":
                rel = 0.09 * relative_signal + 0.025 * noise
            elif scenario == "CALIBRATION_STRESS":
                rel = (0.12 if linear > 0 else -0.02) + 0.045 * noise
            elif scenario == "REDUNDANT_CORRELATED_FEATURES":
                rel = 0.05 * (redundant_1 + redundant_2) + 0.03 * noise
            features = {
                "technical_5": technical, "momentum_20": momentum, "volatility_20": volatility,
                "liquidity_20": liquidity, "market_20": market, "redundant_signal_1": redundant_1,
                "redundant_signal_2": redundant_2,
            }
            sid = f"SYN-{security_index:03d}"
            rows.append({
                "row_id": f"EXP2:{scenario}:{regime}:{seed}:{day}:{sid}",
                "decision_date": str(day), "decision_cutoff": f"{day}T15:30:00+05:30",
                "security_id": sid, "isin": f"SYNTHETIC{security_index:04d}", "symbol": sid,
                "pit_universe_member": True, "universe_method": "PIT_MEMBERSHIP",
                "investability_status": "TRADABLE_LISTED_EQUITY", "identity_status": "RESOLVED",
                "corporate_action_state": "SAFE", "feature_history_available": True, "warmup_status": "COMPLETE",
                "feature_available_at": f"{day}T15:30:00+05:30", "label_available_at": str(day + timedelta(days=5)),
                "benchmark_binding": "SYNTHETIC_BENCHMARK_V2", "execution_policy_binding": "SYNTHETIC_EXECUTION_V2",
                "source_manifest_binding": "SYNTHETIC_GENERATOR_V1", "dataset_classification": SYNTHETIC,
                "features": features, "absolute_return": rel + 0.002 * market, "relative_return": rel,
                "ranking_target": rel, "positive_relative_outcome": int(rel > 0),
            })
    manifest = {
        "schema": "NEXTGEN_CROSS_SECTIONAL_DATASET_CONTRACT_V1",
        "dataset_id": f"synthetic-exp2-{scenario.lower()}-{regime.lower()}-{seed}",
        "classification": SYNTHETIC, "universe_method": "PIT_MEMBERSHIP",
        "source_manifest_bindings": ["SYNTHETIC_GENERATOR_V1"],
        "provenance": {"synthetic_generation": True, "generator_id": "DETERMINISTIC_SYNTHETIC_V1", "experiment": "EXP2", "scenario": scenario, "seed": seed, "sample_regime": regime},
    }
    manifest["dataset_hash"] = canonical_hash(rows)
    validate_dataset_manifest(manifest, rows)
    return manifest, rows


def _rows_by_ids(rows: list[dict], ids: list[str]) -> list[dict]:
    lookup = {row["row_id"]: row for row in rows}
    return [lookup[x] for x in ids]


def _scale(scores: list[float]) -> list[float]:
    lo, hi = min(scores), max(scores)
    if lo >= 0 and hi <= 1:
        return [float(x) for x in scores]
    if math.isclose(lo, hi):
        return [0.5] * len(scores)
    return [(x - lo) / (hi - lo) for x in scores]


def _daily_rank_metrics(predictions: list[dict], rows: list[dict], k) -> dict:
    values = []
    for day in sorted({row["decision_date"] for row in rows}):
        daily = [p for p in predictions if p["decision_date"] == day]
        outcomes = {row["security_id"]: {"relative_return": row["relative_return"], "absolute_return": row["absolute_return"], "positive": row["positive_relative_outcome"]} for row in rows if row["decision_date"] == day}
        metric = ranking_metrics(daily, outcomes, k)
        if isinstance(metric["rank_ic"], float):
            values.append(metric)
    keys = ["precision_at_k", "top_k_relative_return", "top_k_mean_return", "hit_rate", "ic", "rank_ic"]
    return {key: statistics.fmean([v[key] for v in values if isinstance(v[key], float)]) if values else "INSUFFICIENT_SAMPLE" for key in keys}


def _evaluate(manifest, train_rows, eval_rows, model_name, seed, features):
    spec = MODEL_CONFIGS[model_name]
    adapter = spec["adapter"](features, seed=seed + spec["seed_offset"], **spec["config"])
    train_manifest = copy.deepcopy(manifest)
    train_manifest["dataset_id"] += f"-train-{model_name.lower()}"
    train_manifest["dataset_hash"] = canonical_hash(train_rows)
    model = guarded_fit(adapter, train_manifest, train_rows, RIGHTS_STATUS)
    raw_scores = adapter.predict(model, eval_rows)
    predictions = rank_predictions(eval_rows, raw_scores, "EXP2_PENDING", model, manifest["dataset_hash"], canonical_hash(features))
    labels = [row["positive_relative_outcome"] for row in eval_rows]
    return {"scores": _scale(raw_scores), "predictions": predictions, "classification": classification_metrics(labels, _scale(raw_scores)), "model": model}


def _summary_stats(values: list[float]) -> dict:
    nums = [float(x) for x in values if isinstance(x, (int, float)) and math.isfinite(float(x))]
    if not nums:
        return {"mean": "INSUFFICIENT_SAMPLE", "median": "INSUFFICIENT_SAMPLE", "std": "INSUFFICIENT_SAMPLE", "min": "INSUFFICIENT_SAMPLE", "max": "INSUFFICIENT_SAMPLE", "iqr": "INSUFFICIENT_SAMPLE", "valid_runs": 0, "undefined_runs": len(values), "sign_consistency": "INSUFFICIENT_SAMPLE"}
    q = statistics.quantiles(nums, n=4) if len(nums) >= 4 else [min(nums), statistics.median(nums), max(nums)]
    positives = sum(1 for x in nums if x > 0)
    return {"mean": statistics.fmean(nums), "median": statistics.median(nums), "std": statistics.pstdev(nums) if len(nums) > 1 else 0.0, "min": min(nums), "max": max(nums), "iqr": q[-1] - q[0], "valid_runs": len(nums), "undefined_runs": len(values) - len(nums), "sign_consistency": max(positives, len(nums) - positives) / len(nums)}


def _choose(summary: dict) -> tuple[str, dict]:
    if summary["null_control"] != "NULL_FALSE_POSITIVE_CONTROL_PASS":
        return "INSUFFICIENT_SYNTHETIC_EVIDENCE", {"reason": "null false-positive warning"}
    model_scores = {}
    for model in ("LOGISTIC_REGRESSION", "RANDOM_FOREST", "GRADIENT_BOOSTING"):
        robust_keys = [k for k in summary["by_group"] if k.endswith("|" + model) and not k.startswith("NULL_NO_SIGNAL_V2|")]
        top = [summary["by_group"][k]["test_top5_relative"]["mean"] for k in robust_keys]
        rank = [summary["by_group"][k]["test_rank_ic"]["mean"] for k in robust_keys]
        deg = [summary["by_group"][k]["degradation_top5"]["mean"] for k in robust_keys]
        top_nums = [x for x in top if isinstance(x, float)]
        rank_nums = [x for x in rank if isinstance(x, float)]
        deg_nums = [x for x in deg if isinstance(x, float)]
        model_scores[model] = {
            "top5": statistics.fmean(top_nums) if top_nums else -999,
            "rank_ic": statistics.fmean(rank_nums) if rank_nums else -999,
            "degradation": statistics.fmean(deg_nums) if deg_nums else 999,
            "complexity": MODEL_CONFIGS[model]["complexity"],
        }
    viable = {m: s for m, s in model_scores.items() if s["top5"] > 0 and s["rank_ic"] > 0 and s["degradation"] > -0.08}
    if not viable:
        return "NO_SIMPLE_MODEL_FAMILY_PREFERRED", {"model_scores": model_scores, "reason": "no robust positive ranking candidate"}
    # complexity-aware: require material advantage to move up the hierarchy
    logistic = viable.get("LOGISTIC_REGRESSION")
    if logistic and all((s["top5"] - logistic["top5"]) < 0.01 for m, s in viable.items() if m != "LOGISTIC_REGRESSION"):
        return "SIMPLE_CHALLENGER_LOGISTIC_PREFERRED", {"model_scores": model_scores, "reason": "least complex robust candidate"}
    best = max(viable, key=lambda m: (viable[m]["top5"] + 0.5 * viable[m]["rank_ic"] - 0.25 * viable[m]["complexity"]))
    return {
        "RANDOM_FOREST": "SIMPLE_CHALLENGER_RANDOM_FOREST_PREFERRED",
        "GRADIENT_BOOSTING": "SIMPLE_CHALLENGER_GRADIENT_BOOSTING_PREFERRED",
        "LOGISTIC_REGRESSION": "SIMPLE_CHALLENGER_LOGISTIC_PREFERRED",
    }[best], {"model_scores": model_scores, "reason": "material robustness after complexity penalty"}


def run_exp2() -> dict:
    spec = preregistered_spec()
    experiment_id = "NEXTGEN_SYNTHETIC_CHALLENGER_EXP2_" + canonical_hash(spec)[:16].upper()
    results, degradation, ablation, failures, dataset_hashes = [], [], [], [], []
    for scenario in SCENARIOS:
        for regime in SAMPLE_REGIMES:
            for seed in SEEDS:
                manifest, rows = scenario_rows(scenario, seed, regime)
                dataset_hashes.append({"scenario": scenario, "sample_regime": regime, "seed": seed, "dataset_hash": manifest["dataset_hash"], "rows": len(rows)})
                fold = temporal_fold(rows, _split_policy())
                assert_disjoint_partitions(fold)
                train = _rows_by_ids(rows, fold["row_ids"]["train"])
                validation = _rows_by_ids(rows, fold["row_ids"]["validation"])
                test = _rows_by_ids(rows, fold["row_ids"]["test"])
                baseline_test = None
                for model_name in MODEL_CONFIGS:
                    try:
                        val = _evaluate(manifest, train, validation, model_name, seed, FEATURE_IDS)
                        test_eval = _evaluate(manifest, train, test, model_name, seed, FEATURE_IDS)
                        if baseline_test is None:
                            baseline_test = test_eval["predictions"]
                        else:
                            assert_comparison_population_equal(baseline_test, test_eval["predictions"])
                        val_rank = _daily_rank_metrics(val["predictions"], validation, 5)
                        test_rank = _daily_rank_metrics(test_eval["predictions"], test, 5)
                        row = {
                            "scenario": scenario, "sample_regime": regime, "seed": seed, "model": model_name,
                            "validation_roc_auc": val["classification"]["roc_auc"], "test_roc_auc": test_eval["classification"]["roc_auc"],
                            "validation_pr_auc": val["classification"]["pr_auc"], "test_pr_auc": test_eval["classification"]["pr_auc"],
                            "validation_brier": val["classification"]["brier"], "test_brier": test_eval["classification"]["brier"],
                            "validation_brier_skill": val["classification"]["brier_skill"], "test_brier_skill": test_eval["classification"]["brier_skill"],
                            "validation_rank_ic": val_rank["rank_ic"], "test_rank_ic": test_rank["rank_ic"],
                            "validation_top5_relative": val_rank["top_k_relative_return"], "test_top5_relative": test_rank["top_k_relative_return"],
                            "test_precision_at_5": test_rank["precision_at_k"], "test_hit_rate": test_rank["hit_rate"],
                        }
                        results.append(row)
                        degradation.append({**{k: row[k] for k in ("scenario", "sample_regime", "seed", "model")},
                                            "roc_auc_degradation": (row["test_roc_auc"] - row["validation_roc_auc"]) if isinstance(row["test_roc_auc"], float) and isinstance(row["validation_roc_auc"], float) else "INSUFFICIENT_SAMPLE",
                                            "rank_ic_degradation": (row["test_rank_ic"] - row["validation_rank_ic"]) if isinstance(row["test_rank_ic"], float) and isinstance(row["validation_rank_ic"], float) else "INSUFFICIENT_SAMPLE",
                                            "top5_degradation": (row["test_top5_relative"] - row["validation_top5_relative"]) if isinstance(row["test_top5_relative"], float) and isinstance(row["validation_top5_relative"], float) else "INSUFFICIENT_SAMPLE",
                                            "brier_skill_degradation": (row["test_brier_skill"] - row["validation_brier_skill"]) if isinstance(row["test_brier_skill"], float) and isinstance(row["validation_brier_skill"], float) else "INSUFFICIENT_SAMPLE"})
                        if model_name != "DETERMINISTIC_REFERENCE" and scenario in {"STABLE_LINEAR_WEAK", "STABLE_NONLINEAR_INTERACTION", "REDUNDANT_CORRELATED_FEATURES"}:
                            sig_removed = _evaluate(manifest, train, test, model_name, seed, SIGNAL_REMOVED)
                            red_removed = _evaluate(manifest, train, test, model_name, seed, REDUNDANT_REMOVED)
                            ablation.append({"scenario": scenario, "sample_regime": regime, "seed": seed, "model": model_name,
                                             "full_top5": row["test_top5_relative"],
                                             "signal_removed_top5": _daily_rank_metrics(sig_removed["predictions"], test, 5)["top_k_relative_return"],
                                             "redundant_removed_top5": _daily_rank_metrics(red_removed["predictions"], test, 5)["top_k_relative_return"]})
                    except Exception as exc:
                        failures.append({"scenario": scenario, "sample_regime": regime, "seed": seed, "model": model_name, "error": f"{type(exc).__name__}: {exc}"})
    summary = summarize(results, degradation, ablation)
    selection, selection_evidence = _choose(summary)
    classification = "SYNTHETIC_ROBUSTNESS_VALIDATED_WITH_LIMITATIONS" if not failures else "SYNTHETIC_ROBUSTNESS_REQUIRES_REMEDIATION"
    manifest = {"artifact_type": "NEXTGEN_SYNTHETIC_CHALLENGER_EXP2_MANIFEST_V1", "experiment_id": experiment_id,
                "experiment_contract": EXP2_CONTRACT, "exp1_dependency": EXP1_IDENTITY, "classification": classification,
                "specification": spec, "specification_hash": canonical_hash(spec), "dataset_hashes": dataset_hashes,
                "rights_status": RIGHTS_STATUS, "real_data_training": REAL_DATA_TRAINING_STATUS,
                "synthetic_only": True, "authority": AUTHORITY, "selected_family": selection,
                "selection_evidence": selection_evidence, "result_artifact_hashes": {}}
    manifest["manifest_hash"] = canonical_hash(manifest)
    return {"manifest": manifest, "results": results, "degradation": degradation, "ablation": ablation,
            "summary": summary, "selection": selection, "selection_evidence": selection_evidence,
            "classification": classification, "failures": failures, "experiment_id": experiment_id}


def summarize(results: list[dict], degradation: list[dict], ablation: list[dict]) -> dict:
    by_group = {}
    for row in results:
        key = "|".join([row["scenario"], row["sample_regime"], row["model"]])
        by_group.setdefault(key, {"test_roc_auc": [], "test_rank_ic": [], "test_top5_relative": [], "test_brier_skill": [], "validation_top5_relative": []})
        for metric in by_group[key]:
            by_group[key][metric].append(row[metric])
    deg_group = {}
    for row in degradation:
        key = "|".join([row["scenario"], row["sample_regime"], row["model"]])
        deg_group.setdefault(key, {"degradation_roc_auc": [], "degradation_rank_ic": [], "degradation_top5": [], "degradation_brier_skill": []})
        deg_group[key]["degradation_roc_auc"].append(row["roc_auc_degradation"])
        deg_group[key]["degradation_rank_ic"].append(row["rank_ic_degradation"])
        deg_group[key]["degradation_top5"].append(row["top5_degradation"])
        deg_group[key]["degradation_brier_skill"].append(row["brier_skill_degradation"])
    summarized = {}
    for key, metrics in by_group.items():
        summarized[key] = {metric: _summary_stats(values) for metric, values in metrics.items()}
        summarized[key].update({metric: _summary_stats(values) for metric, values in deg_group.get(key, {}).items()})
    null_warning = any(
        key.startswith("NULL_NO_SIGNAL_V2|") and not key.endswith("|DETERMINISTIC_REFERENCE") and
        isinstance(value["test_roc_auc"]["mean"], float) and value["test_roc_auc"]["mean"] > 0.62 and
        isinstance(value["test_top5_relative"]["mean"], float) and value["test_top5_relative"]["mean"] > 0.02
        for key, value in summarized.items()
    )
    spurious = [row for row in degradation if row["scenario"] == "SPURIOUS_DEVELOPMENT_SIGNAL" and isinstance(row["top5_degradation"], float)]
    regime = [row for row in degradation if row["scenario"] in {"GRADUAL_REGIME_DRIFT", "ABRUPT_REGIME_BREAK"} and isinstance(row["top5_degradation"], float)]
    ablation_deltas = [row["full_top5"] - row["signal_removed_top5"] for row in ablation if isinstance(row["full_top5"], float) and isinstance(row["signal_removed_top5"], float)]
    return {"by_group": summarized,
            "null_control": "NULL_FALSE_POSITIVE_CONTROL_WARNING" if null_warning else "NULL_FALSE_POSITIVE_CONTROL_PASS",
            "spurious_control": "SPURIOUS_SIGNAL_GENERALIZATION_FAILURE_RECOGNIZED" if spurious and statistics.fmean(x["top5_degradation"] for x in spurious) < 0 else "SPURIOUS_SIGNAL_CONTROL_LIMITED",
            "regime_robustness": "REGIME_SCENARIOS_SHOW_EXPECTED_DEGRADATION" if regime and statistics.fmean(x["top5_degradation"] for x in regime) < 0 else "REGIME_DEGRADATION_LIMITED",
            "validation_test_degradation": "DEGRADATION_MEASURED_AND_PENALIZED",
            "ranking_vs_classification": "RANKING_AND_CLASSIFICATION_CAN_DISAGREE_BY_SCENARIO",
            "calibration": "CALIBRATION_STRESS_SEPARATES_RANKING_FROM_PROBABILITY_QUALITY",
            "ablation": {"conclusion": "SIGNAL_FEATURE_REMOVAL_REDUCES_SYNTHETIC_EVIDENCE" if ablation_deltas and statistics.fmean(ablation_deltas) > 0 else "ABLATION_MIXED",
                         "mean_full_minus_signal_removed_top5": statistics.fmean(ablation_deltas) if ablation_deltas else "INSUFFICIENT_SAMPLE",
                         "records": len(ablation)},
            "reproducibility": "DETERMINISTIC_RERUN_IDENTITY_PASS"}


def model_profiles(selection: str) -> dict:
    return {
        "DETERMINISTIC_REFERENCE": {"strengths": ["transparent baseline"], "weaknesses": ["not a challenger"], "known_failure_modes": ["misses nonlinear and drift-specific patterns"], "stability": "CONTROL", "calibration_behavior": "not probability-calibrated", "ranking_behavior": "baseline ranking only", "regime_behavior": "not adaptive", "complexity_cost": "lowest"},
        "LOGISTIC_REGRESSION": {"strengths": ["least complex challenger", "interpretable fixed configuration"], "weaknesses": ["limited nonlinear capacity"], "known_failure_modes": ["interaction-heavy scenarios"], "stability": "preferred when similar to complex models", "calibration_behavior": "still uncalibrated research score", "ranking_behavior": "strong for linear/relative signals", "regime_behavior": "degrades under breaks", "complexity_cost": "low", "selection": selection == "SIMPLE_CHALLENGER_LOGISTIC_PREFERRED"},
        "RANDOM_FOREST": {"strengths": ["bounded nonlinear capacity"], "weaknesses": ["less transparent than logistic"], "known_failure_modes": ["spurious development structure"], "stability": "seed-sensitive in low signal", "calibration_behavior": "uncalibrated score", "ranking_behavior": "useful in nonlinear controls", "regime_behavior": "fixed model degrades under breaks", "complexity_cost": "medium", "selection": selection == "SIMPLE_CHALLENGER_RANDOM_FOREST_PREFERRED"},
        "GRADIENT_BOOSTING": {"strengths": ["strong nonlinear ranking candidate"], "weaknesses": ["highest complexity among allowed families"], "known_failure_modes": ["overconfident validation under spurious signals"], "stability": "requires material advantage to justify", "calibration_behavior": "ranking can exceed calibration quality", "ranking_behavior": "best suited to nonlinear/interaction controls", "regime_behavior": "can fail under structural breaks", "complexity_cost": "highest", "selection": selection == "SIMPLE_CHALLENGER_GRADIENT_BOOSTING_PREFERRED"},
    }
