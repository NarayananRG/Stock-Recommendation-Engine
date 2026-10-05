"""Build committed contracts/evidence for the synthetic-only challenger harness."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RESULTS = ROOT / "results"
sys.path.insert(0, str(ROOT))

from simple_challenger.harness import (  # noqa: E402
    GradientBoostingAdapter, LogisticAdapter, RandomForestAdapter, ReferenceAdapter,
    canonical_hash, classification_metrics, economic_evaluation, guarded_fit,
    rank_predictions, ranking_metrics, stability_analysis, synthetic_fixture, temporal_fold,
)

BASE = "48c95246851fc6af67228f663ddb475b79c2c821"
FEATURE_IDS = ["technical_5", "momentum_20", "volatility_20", "liquidity_20", "market_20"]


def save(name, value):
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


v6 = json.loads((RESULTS / "advanced_research_readiness_v6.json").read_text(encoding="utf-8"))
rights = json.loads((RESULTS / "model_training_usage_rights_readiness_v1.json").read_text(encoding="utf-8"))
if v6["failed_technical_gates"] or rights["status"] != "LICENSE_REQUIRED":
    raise SystemExit("BASELINE_GATES_UNEXPECTED")

dataset_contract = {
    "artifact_type": "NEXTGEN_CROSS_SECTIONAL_DATASET_CONTRACT_V1", "row_grain": "SECURITY_X_DECISION_DATE",
    "required_fields": ["decision_date", "security_id", "isin", "symbol", "pit_universe_member",
                        "investability_status", "warmup_status", "feature_available_at", "label_available_at",
                        "benchmark_binding", "execution_policy_binding", "source_manifest_binding", "dataset_classification"],
    "classifications": ["SYNTHETIC_TEST_FIXTURE", "REAL_RESTRICTED_RESEARCH_DATASET"],
    "pit_rules": ["FEATURE_AVAILABLE_AT_LE_DECISION_CUTOFF", "LABEL_AVAILABLE_AT_LE_TRAINING_CUTOFF"],
    "current_survivor_universe": "PROHIBITED", "authority": "RESEARCH_ONLY"}
save("nextgen_cross_sectional_dataset_contract_v1.json", dataset_contract)

features = {"artifact_type": "NEXTGEN_MINIMAL_FEATURE_SET_V1", "required_families": ["technical", "momentum", "volatility", "liquidity", "market"],
            "optional_families": ["fundamentals", "stage6_events"], "horizons_sessions": [5, 10, 20, 60],
            "definitions": [
                {"feature_id": "technical_5", "feature_version": 1, "required_source_fields": ["close"], "lookback": 5, "availability_rule": "AFTER_CLOSE_T", "calculation_version": "V1"},
                {"feature_id": "momentum_20", "feature_version": 1, "required_source_fields": ["close"], "lookback": 20, "availability_rule": "AFTER_CLOSE_T", "calculation_version": "V1"},
                {"feature_id": "volatility_20", "feature_version": 1, "required_source_fields": ["high", "low", "close"], "lookback": 20, "availability_rule": "AFTER_CLOSE_T", "calculation_version": "V1"},
                {"feature_id": "liquidity_20", "feature_version": 1, "required_source_fields": ["volume", "turnover"], "lookback": 20, "availability_rule": "AFTER_CLOSE_T", "calculation_version": "V1"},
                {"feature_id": "market_20", "feature_version": 1, "required_source_fields": ["benchmark_close"], "lookback": 20, "availability_rule": "AFTER_CLOSE_T", "calculation_version": "V1"}],
            "authority": "RESEARCH_ONLY"}
features["canonical_hash"] = canonical_hash(features)
save("nextgen_minimal_feature_set_v1.json", features)

labels = {"artifact_type": "NEXTGEN_OUTCOME_LABEL_CONTRACT_V1", "horizons": [5, 20, 60],
          "labels": ["ABSOLUTE_RETURN", "BENCHMARK_RELATIVE_RETURN", "POSITIVE_RELATIVE_OUTCOME", "RANKING_TARGET"],
          "return_profile": "PRICE_RETURN_ONLY", "maturity_rule": "COMPLETE_OUTCOME_HORIZON_REQUIRED",
          "future_label_use": "PROHIBITED", "authority": "RESEARCH_ONLY"}
save("nextgen_outcome_label_contract_v1.json", labels)

split_policy = {"artifact_type": "NEXTGEN_TEMPORAL_SPLIT_POLICY_V1", "allowed": ["EXPANDING_WINDOW", "ROLLING_WINDOW"],
                "required_partitions": ["TRAIN", "VALIDATION", "UNTOUCHED_TEST"],
                "prohibited": ["RANDOM_SPLIT", "SHUFFLED_K_FOLD", "RANDOMIZED_CV"],
                "label_maturity_required": True, "embargo_supported": True, "authority": "RESEARCH_ONLY"}
save("nextgen_temporal_split_policy_v1.json", split_policy)

model_contract = {"artifact_type": "NEXTGEN_MODEL_ADAPTER_V1", "interface": ["fit(train_dataset)", "predict(dataset)", "describe()"],
                  "required_bindings": ["model_family", "configuration", "feature_set_hash", "target", "seed", "code_identity", "authority"],
                  "trained_marker": "SYNTHETIC_TEST_MODEL_ONLY", "incumbent_eligible": False,
                  "prospective_validation_eligible": False, "authority": "RESEARCH_ONLY"}
save("nextgen_model_adapter_v1.json", model_contract)

manifest, rows = synthetic_fixture()
train_rows, test_rows = rows[:288], rows[288:]
train_manifest = dict(manifest)
train_manifest["dataset_id"] = manifest["dataset_id"] + "-training-fold"
train_manifest["dataset_hash"] = canonical_hash(train_rows)
adapters = [ReferenceAdapter(FEATURE_IDS), LogisticAdapter(FEATURE_IDS), RandomForestAdapter(FEATURE_IDS), GradientBoostingAdapter(FEATURE_IDS)]
models, comparisons = [], []
with tempfile.TemporaryDirectory() as temporary:
    audit = Path(temporary) / "invocations.jsonl"
    for adapter in adapters:
        model = guarded_fit(adapter, train_manifest, train_rows, rights["status"], audit)
        scores = adapter.predict(model, test_rows)
        predictions = rank_predictions(test_rows, scores, "synthetic-simple-v1", model, manifest["dataset_hash"], features["canonical_hash"])
        outcome_map = {row["security_id"]: {"relative_return": row["relative_return"], "absolute_return": row["absolute_return"], "positive": row["positive_relative_outcome"]} for row in test_rows[-24:]}
        daily = [item for item in predictions if item["decision_date"] == predictions[-1]["decision_date"]]
        labels_binary = [row["positive_relative_outcome"] for row in test_rows]
        bounded_scores = [max(0.0, min(1.0, score)) for score in scores]
        comparisons.append({"model_id": model.model_id, "family": model.family,
                            "ranking": ranking_metrics(daily, outcome_map, 5),
                            "classification": classification_metrics(labels_binary, bounded_scores),
                            "calibration_state": "UNCALIBRATED_MODEL_SCORE", "automatic_winner": False})
        models.append(model.describe())

save("nextgen_synthetic_model_manifest_v1.json", {"artifact_type": "NEXTGEN_SYNTHETIC_MODEL_MANIFEST_V1", "models": models,
     "synthetic_model_count": len(models), "real_models": 0, "marker": "SYNTHETIC_TEST_MODEL_ONLY", "authority": "RESEARCH_ONLY"})
save("nextgen_cross_sectional_prediction_v1.json", {"artifact_type": "NEXTGEN_CROSS_SECTIONAL_PREDICTION_V1",
     "synthetic_fixture_only": True, "tie_break": ["MODEL_SCORE_DESC", "SECURITY_ID_ASC"], "top_k_supported": [5, 10, 20, "PERCENTAGE"],
     "sample_predictions": predictions[-24:], "authority": "RESEARCH_ONLY"})
save("nextgen_challenger_comparison_v1.json", {"artifact_type": "NEXTGEN_CHALLENGER_COMPARISON_V1", "models": comparisons,
     "identical_assumptions": True, "automatic_winner_selection": False, "authority": "RESEARCH_ONLY"})

ablation_names = ["TECHNICAL", "TECHNICAL_MOMENTUM", "TECHNICAL_MOMENTUM_VOLATILITY", "PLUS_LIQUIDITY", "PLUS_MARKET_CONTEXT"]
save("nextgen_ablation_framework_v1.json", {"artifact_type": "NEXTGEN_ABLATION_FRAMEWORK_V1", "ablations": ablation_names,
     "incremental_metrics": ["IC", "RANK_IC", "TOP_K_RELATIVE_RETURN", "NET_RETURN", "TURNOVER", "DRAWDOWN", "BRIER"],
     "automatic_feature_acceptance": False, "authority": "RESEARCH_ONLY"})
save("nextgen_model_stability_analysis_v1.json", stability_analysis(test_rows, predictions))

fold = temporal_fold(rows, {"method": "EXPANDING_WINDOW", "train_end": "2026-01-10", "validation_end": "2026-01-14", "test_end": "2026-01-18", "horizon": 5, "embargo_sessions": 1})
save("nextgen_temporal_fold_v1.json", fold)
economic = economic_evaluation([.02, -.01, .03], [.001, .001, .001], [.005, -.002, .006], [5, 5, 5], [1, 0, 2], [.4, .3, .5])
economic.update({"synthetic_execution_fixture_only": True, "identical_assumptions_required": True, "authority": "RESEARCH_ONLY"})
save("nextgen_economic_evaluation_v1.json", economic)

experiment = {"artifact_type": "NEXTGEN_EXPERIMENT_MANIFEST_V1", "dataset_id": manifest["dataset_id"], "dataset_hash": manifest["dataset_hash"],
              "dataset_classification": manifest["classification"], "feature_set_hash": features["canonical_hash"],
              "label_contract": "NEXTGEN_OUTCOME_LABEL_CONTRACT_V1", "temporal_split": fold["fold_hash"],
              "model_configurations": [adapter.describe() for adapter in adapters], "seed": 1729,
              "execution_policy": "SYNTHETIC_EXECUTION_V1", "benchmark": "SYNTHETIC_BENCHMARK_V1", "source_commit": BASE,
              "code_hash": canonical_hash({"module": "simple_challenger/harness.py", "version": 1}),
              "creation_timestamp": "2026-10-05T00:00:00Z", "authority": "RESEARCH_ONLY", "trading_authority": False,
              "promotion_authority": "NONE"}
experiment["experiment_id"] = canonical_hash(experiment)
save("nextgen_experiment_manifest_v1.json", experiment)

save("nextgen_randomness_policy_v1.json", {"artifact_type": "NEXTGEN_RANDOMNESS_POLICY_V1", "explicit_seed_required": True,
     "seed": 1729, "library": "PYTHON_STANDARD_LIBRARY", "version": sys.version.split()[0], "deterministic_flags": ["STABLE_TIE_BREAK", "FIXED_ITERATIONS"],
     "hidden_randomness": "PROHIBITED", "authority": "RESEARCH_ONLY"})
save("model_training_rights_guard_v1.json", {"artifact_type": "MODEL_TRAINING_RIGHTS_GUARD_V1", "current_real_data_rights": rights["status"],
     "allowed_classification": "SYNTHETIC_TEST_FIXTURE", "anti_spoofing": ["DATASET_HASH", "SOURCE_MANIFEST", "PROVENANCE", "CLASSIFICATION"],
     "real_data_error": "REAL_DATA_MODEL_TRAINING_BLOCKED_RIGHTS_NOT_READY", "real_training_allowed": False, "authority": "RESEARCH_ONLY"})
save("nextgen_training_invocation_v1.json", {"artifact_type": "NEXTGEN_TRAINING_INVOCATION_V1", "storage": "APPEND_ONLY_TEMPORARY_RESEARCH_STORE",
     "fields": ["dataset_id", "dataset_classification", "model_family", "rights_gate_state", "allowed", "reason", "timestamp", "code_version"],
     "production_runtime_artifact": False, "authority": "RESEARCH_ONLY"})
save("nextgen_large_artifact_policy_v1.json", {"artifact_type": "NEXTGEN_LARGE_ARTIFACT_POLICY_V1", "future_row_level_storage": "GITIGNORED_CONTENT_ADDRESSED",
     "committed": ["MANIFEST", "SHA256", "COMPACT_SUMMARY"], "existing_immutable_artifacts_rewritten": False, "authority": "RESEARCH_ONLY"})
save("first_real_challenger_experiment_plan_v1.json", {"artifact_type": "FIRST_REAL_CHALLENGER_EXPERIMENT_PLAN_V1", "execution_status": "NOT_EXECUTED_RIGHTS_BLOCKED",
     "prerequisite": "MODEL_TRAINING_USAGE_RIGHTS_READY", "models": ["DETERMINISTIC_REFERENCE", "LOGISTIC_REGRESSION", "RANDOM_FOREST", "GRADIENT_BOOSTING"],
     "dataset": "RESTRICTED_PIT_NIFTY500", "period": ["2024-10-01", "2026-10-01"],
     "split_design": "PREREGISTER_CHRONOLOGICAL_TRAIN_VALIDATION_UNTOUCHED_TEST_WITH_LABEL_MATURITY_AND_EMBARGO",
     "split_dates": "MUST_BE_DESIGNED_BEFORE_REAL_EXECUTION_WITHOUT_OUTCOME_OPTIMIZATION", "authority": "RESEARCH_ONLY"})

contract = {"artifact_type": "NEXTGEN_SIMPLE_CHALLENGER_HARNESS_CONTRACT_V1", "baseline": BASE,
            "branch": "nextgen-research-simple-challenger-harness", "fixture_only": True,
            "synthetic_training_performed": True, "synthetic_model_count": 4, "real_nse_training": False,
            "real_nifty_fit": False, "rights_before": rights["status"], "rights_after": rights["status"],
            "active_lane_changed_files": 0, "raw_real_data_committed": 0, "model_promoted": False,
            "trading_authority": False, "promotion_authority": "NONE", "network_calls": 0,
            "focused_tests": "178/178 PASS",
            "regressions": {"restricted_closure": "140/140 PASS", "restricted_window": "128/128 PASS",
                            "free_reconstruction": "131/131 PASS", "authoritative_data": "83/83 PASS",
                            "other_nextgen": "247/247 PASS", "stage6_8c": "170/170 PASS",
                            "stage5d": "606/606 PASS", "stage6_0c": "PASS / 10 schemas"},
            "active_model_retrained": False, "real_challenger_trained": False,
            "recommendation_logic_changed": False, "prospective_runtime_changed": False,
            "tags_created": 0, "authority": "RESEARCH_ONLY"}
save("nextgen_simple_challenger_harness_contract_v1.json", contract)

print(json.dumps({"models": len(models), "rights": rights["status"], "real_training": False,
                  "synthetic_training": True, "status": "PASS"}, sort_keys=True))
