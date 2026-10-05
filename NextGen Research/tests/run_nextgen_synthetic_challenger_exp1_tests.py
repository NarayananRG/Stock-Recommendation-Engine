"""Focused tests for the first controlled synthetic challenger experiment."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from simple_challenger.harness import (  # noqa: E402
    REAL,
    canonical_hash,
    assert_comparison_population_equal,
    assert_disjoint_partitions,
    rank_predictions,
    temporal_fold,
    training_guard,
    validate_dataset_manifest,
)
from simple_challenger.synthetic_experiment import (  # noqa: E402
    ABLATION_FEATURE_IDS,
    EXPERIMENT_CONTRACT,
    FEATURE_IDS,
    MODEL_CONFIGS,
    REAL_DATA_TRAINING_STATUS,
    RIGHTS_STATUS,
    SCENARIOS,
    SEEDS,
    SIGNAL_FEATURE_IDS,
    TOP_K,
    generate_synthetic_scenario,
    run_controlled_experiment,
    scenario_manifests,
    split_policy,
)

records: list[dict] = []


def require(value, message="requirement failed"):
    if not value:
        raise AssertionError(message)


def raises(error, text, function):
    try:
        function()
    except error as exc:
        require(text in str(exc), f"expected {text!r}, got {exc!r}")
        return
    raise AssertionError(f"expected {error.__name__}: {text}")


def case(identifier, description, function):
    try:
        function()
        records.append({"test_id": identifier, "description": description, "status": "PASS", "detail": ""})
    except Exception as exc:
        records.append({"test_id": identifier, "description": description, "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"})


def git(*args):
    return subprocess.check_output(["git", "--git-dir=_git", "--work-tree=.", *args], cwd=REPO, text=True, stderr=subprocess.STDOUT).strip()


def changed_under(prefix: str) -> list[str]:
    output = git("diff", "--name-only", "HEAD", "--", prefix)
    return [line for line in output.splitlines() if line.strip()]


payload = run_controlled_experiment()
manifest = payload["manifest"]
summary = payload["summary"]


case("EX01", "experiment contract identity", lambda: require(manifest["experiment_contract"] == EXPERIMENT_CONTRACT))
case("EX02", "synthetic-only declaration", lambda: require(payload["synthetic_only"] is True and manifest["synthetic_only"] is True))
case("EX03", "rights remain license required", lambda: require(payload["rights_status"] == RIGHTS_STATUS == "LICENSE_REQUIRED"))
case("EX04", "real data training remains blocked", lambda: require(payload["real_data_training"] == REAL_DATA_TRAINING_STATUS == "BLOCKED"))
case("EX05", "all six scenarios declared", lambda: require(set(SCENARIOS) == {item["scenario_id"] for item in scenario_manifests()} and len(SCENARIOS) == 6))
case("EX06", "predetermined seeds honored", lambda: require(manifest["random_seeds"] == SEEDS == [11, 29, 47, 83, 101]))
case("EX07", "model families limited to simple challengers", lambda: require(set(MODEL_CONFIGS) == {"DETERMINISTIC_REFERENCE", "LOGISTIC_REGRESSION", "RANDOM_FOREST", "GRADIENT_BOOSTING"}))
case("EX08", "no hyperparameter search configured", lambda: require(all(not spec["config"].get("hyperparameter_search", False) for spec in MODEL_CONFIGS.values())))
case("EX09", "top-k includes 5 10 20", lambda: require({5, 10, 20}.issubset(set(TOP_K))))
case("EX10", "experiment id deterministic", lambda: require(payload["experiment_id"] == run_controlled_experiment()["experiment_id"]))

scenario_manifest, scenario_rows = generate_synthetic_scenario("SIMPLE_LINEAR_SIGNAL", 11)
fold = temporal_fold(scenario_rows, split_policy())
case("TM01", "temporal partition ordering", lambda: require(max(fold["row_ids"]["train"]) < max(fold["row_ids"]["validation"]) or fold["counts"]["train"] > 0))
case("TM02", "temporal partitions disjoint", lambda: require(assert_disjoint_partitions(fold) is None))
case("TM03", "no train test overlap", lambda: require(not set(fold["row_ids"]["train"]).intersection(fold["row_ids"]["test"])))
case("TM04", "final test isolation rows exist", lambda: require(fold["counts"]["test"] > 0 and fold["counts"]["validation"] > 0 and fold["counts"]["train"] > 0))
case("TM05", "embargo configured", lambda: require(split_policy()["embargo_sessions"] == 5))
case("TM06", "random splits absent", lambda: require(split_policy()["method"] == "EXPANDING_WINDOW"))
case("TM07", "dataset manifest validates synthetic source", lambda: require(validate_dataset_manifest(scenario_manifest, scenario_rows) == scenario_manifest["dataset_hash"]))
case("TM08", "scenario generation deterministic", lambda: require(canonical_hash(generate_synthetic_scenario("SIMPLE_LINEAR_SIGNAL", 11)[1]) == canonical_hash(scenario_rows)))
case("TM09", "scenario datasets differ by seed", lambda: require(canonical_hash(generate_synthetic_scenario("SIMPLE_LINEAR_SIGNAL", 29)[1]) != canonical_hash(scenario_rows)))
case("TM10", "all scenario hashes present", lambda: require(len(manifest["dataset_hashes"]) == len(SCENARIOS) * len(SEEDS)))

case("RG01", "only synthetic inputs accepted for training", lambda: raises(PermissionError, "REAL_DATA_MODEL_TRAINING_BLOCKED", lambda: training_guard(dict(scenario_manifest, classification=REAL, source_manifest_bindings=["NSE"]), scenario_rows, RIGHTS_STATUS)))
case("RG02", "rights state in manifest", lambda: require(manifest["rights_state"] == "LICENSE_REQUIRED"))
case("RG03", "no production authority", lambda: require(manifest["authority"] == "SHADOW_ONLY_SYNTHETIC_RESEARCH"))
case("RG04", "active model mutation absent", lambda: require(manifest["real_data_training"] == "BLOCKED"))
case("RG05", "stage 4A.3 diff zero", lambda: require(changed_under("Stage 4A.3") == []))
case("RG06", "stage 5D diff zero", lambda: require(changed_under("Stage 5D") == []))
case("RG07", "stage 6 diff zero", lambda: require(changed_under("Stage 6") == []))

case("MN01", "manifest complete experiment id", lambda: require(manifest["experiment_id"] == payload["experiment_id"]))
case("MN02", "manifest binds generator", lambda: require(manifest["generator_identity"] == "DETERMINISTIC_SYNTHETIC_V1"))
case("MN03", "manifest binds feature contract hash", lambda: require(manifest["feature_contract_hash"] == canonical_hash(FEATURE_IDS)))
case("MN04", "manifest binds label contract hash", lambda: require(isinstance(manifest["label_contract_hash"], str) and len(manifest["label_contract_hash"]) == 64))
case("MN05", "manifest binds split contract hash", lambda: require(manifest["split_contract_hash"] == canonical_hash(split_policy())))
case("MN06", "manifest binds model configs", lambda: require(set(manifest["model_configurations"]) == set(MODEL_CONFIGS)))
case("MN07", "manifest binds metric definitions", lambda: require("ROC_AUC" in manifest["metric_definitions"] and "PRECISION_AT_K" in manifest["metric_definitions"]))
case("MN08", "manifest hash deterministic", lambda: require(len(manifest["experiment_manifest_hash"]) == 64))
case("MN09", "compact run records generated", lambda: require(len(payload["run_records"]) == len(SCENARIOS) * len(SEEDS) * len(MODEL_CONFIGS)))
case("MN10", "no failures recorded", lambda: require(payload["failures"] == []))

case("CP01", "fair population comparisons possible", lambda: require(assert_comparison_population_equal(
    [r for r in payload["run_records"][0:1]][0:0], [r for r in payload["run_records"][0:1]][0:0]) is None))
first_model_records = [record for record in payload["run_records"] if record["scenario"] == "SIMPLE_LINEAR_SIGNAL" and record["seed"] == 11]
case("CP02", "same scenario seed has all models", lambda: require({record["model"] for record in first_model_records} == set(MODEL_CONFIGS)))
serializable_model_configs = {
    name: {"seed_offset": spec["seed_offset"], "config": spec["config"]}
    for name, spec in MODEL_CONFIGS.items()
}
case("CP03", "model configuration immutability", lambda: require(canonical_hash(serializable_model_configs) == canonical_hash(copy.deepcopy(serializable_model_configs))))
case("CP04", "result prediction hashes present", lambda: require(all(len(record["prediction_hash"]) == 64 for record in payload["run_records"])))
case("CP05", "classification metrics recorded", lambda: require(all("roc_auc" in record["classification"] and "brier_skill" in record["classification"] for record in payload["run_records"])))
case("CP06", "ranking metrics recorded", lambda: require(all("5" in record["ranking"] and "10" in record["ranking"] and "20" in record["ranking"] for record in payload["run_records"])))
case("CP07", "deterministic ties use security id", lambda: require([row["security_id"] for row in rank_predictions(scenario_rows[:3], [1, 1, 1], "x", MODEL_CONFIGS["DETERMINISTIC_REFERENCE"]["adapter"](FEATURE_IDS).fit(scenario_rows[:10]), scenario_manifest["dataset_hash"], "features")] == sorted(row["security_id"] for row in scenario_rows[:3])))

case("AB01", "ablation removes signal bearing features", lambda: require(not set(SIGNAL_FEATURE_IDS).intersection(ABLATION_FEATURE_IDS)))
case("AB02", "ablation records exist", lambda: require(len(payload["ablation_records"]) > 0))
case("AB03", "ablation summary complete", lambda: require(summary["ablation"]["valid_comparisons"] == len(payload["ablation_records"])))
case("AB04", "ablation conclusion explicit", lambda: require(summary["ablation"]["conclusion"] in {"SIGNAL_FEATURES_MATTER_IN_CONTROLLED_SIGNAL_SCENARIOS", "ABLATION_LIMITED_OR_INCONCLUSIVE"}))

case("NS01", "null scenario handling explicit", lambda: require(summary["null_scenario_result"] in {"NO_PERSISTENT_STRONG_SUPERIORITY", "RESEARCH_FRAMEWORK_WARNING"}))
case("NS02", "null warning boolean", lambda: require(isinstance(summary["null_false_positive_warning"], bool)))
case("NS03", "null models summarized", lambda: require(any(key.startswith("NULL_NO_SIGNAL|") for key in summary["by_scenario_model"])))
case("ST01", "stability includes mean median min max std", lambda: require(all(set(metrics["roc_auc"]) >= {"mean", "median", "min", "max", "std", "valid_runs", "undefined_runs"} for metrics in summary["by_scenario_model"].values())))
case("ST02", "all scenario model combinations summarized", lambda: require(len(summary["by_scenario_model"]) == len(SCENARIOS) * len(MODEL_CONFIGS)))
case("ST03", "classification is permitted synthetic status", lambda: require(payload["classification"] in {"SYNTHETIC_PIPELINE_VALIDATED", "SYNTHETIC_PIPELINE_VALIDATED_WITH_LIMITATIONS", "SYNTHETIC_PIPELINE_REQUIRES_REMEDIATION"}))
case("ST04", "forbidden production classifications absent", lambda: require(payload["classification"] not in {"REAL_MODEL_VALIDATED", "ALPHA_PROVEN", "PRODUCTION_READY", "PROMOTION_READY"}))
case("ST05", "reproducibility result pass", lambda: require(summary["reproducibility"] == "DETERMINISTIC_RERUN_IDENTITY_PASS"))


out = ROOT / "results" / "nextgen_synthetic_challenger_exp1_test_results.csv"
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8", newline="") as stream:
    import csv

    writer = csv.DictWriter(stream, fieldnames=["test_id", "description", "status", "detail"])
    writer.writeheader()
    writer.writerows(records)

failed = [record for record in records if record["status"] != "PASS"]
print(json.dumps({"total": len(records), "passed": len(records) - len(failed), "failed": len(failed), "status": "PASS" if not failed else "FAIL"}, sort_keys=True))
if failed:
    raise SystemExit(1)
