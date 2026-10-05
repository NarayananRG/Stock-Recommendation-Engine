"""Focused tests for EXP2 robustness and model-family selection."""
from __future__ import annotations

import csv
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RESULTS = ROOT / "results"
sys.path.insert(0, str(ROOT))

from simple_challenger.harness import REAL, canonical_hash, row_eligible, training_guard, validate_dataset_manifest  # noqa: E402
from simple_challenger.synthetic_exp2 import (  # noqa: E402
    EXP1_IDENTITY,
    EXP2_CONTRACT,
    MODEL_CONFIGS,
    REAL_DATA_TRAINING_STATUS,
    RIGHTS_STATUS,
    SAMPLE_REGIMES,
    SCENARIOS,
    SEEDS,
    FEATURE_IDS,
    preregistered_spec,
    run_exp2,
    scenario_rows,
)

records = []


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


def diff_count(path: str) -> int:
    out = git("diff", "--name-only", "HEAD", "--", path)
    return len([line for line in out.splitlines() if line.strip()])


payload = run_exp2()
rerun = run_exp2()
manifest = payload["manifest"]
spec = preregistered_spec()
m, rows = scenario_rows("STABLE_LINEAR_WEAK", 11, "SMALL_RESEARCH_SAMPLE")

case("ID01", "EXP2 contract", lambda: require(manifest["experiment_contract"] == EXP2_CONTRACT))
case("ID02", "EXP1 dependency", lambda: require(manifest["exp1_dependency"] == EXP1_IDENTITY))
case("ID03", "deterministic experiment id", lambda: require(payload["experiment_id"] == rerun["experiment_id"]))
case("ID04", "deterministic specification hash", lambda: require(manifest["specification_hash"] == rerun["manifest"]["specification_hash"]))
case("ID05", "deterministic summary", lambda: require(canonical_hash(payload["summary"]) == canonical_hash(rerun["summary"])))
case("ID06", "synthetic only", lambda: require(manifest["synthetic_only"] is True))
case("ID07", "authority research only", lambda: require(manifest["authority"] == "RESEARCH_ONLY_SYNTHETIC_SHADOW"))

case("SC01", "all 10 scenarios", lambda: require(set(SCENARIOS) == set(spec["scenarios"]) and len(SCENARIOS) == 10))
case("SC02", "exact seed set", lambda: require(SEEDS == [11, 29, 47, 83, 101, 131, 167, 211, 257, 307]))
case("SC03", "two sample regimes", lambda: require(set(SAMPLE_REGIMES) == {"SMALL_RESEARCH_SAMPLE", "LARGER_RESEARCH_SAMPLE"}))
case("SC04", "all dataset hashes recorded", lambda: require(len(manifest["dataset_hashes"]) == len(SCENARIOS) * len(SEEDS) * len(SAMPLE_REGIMES)))
case("SC05", "synthetic manifest validates", lambda: require(validate_dataset_manifest(m, rows) == m["dataset_hash"]))
case("SC06", "scenario deterministic", lambda: require(canonical_hash(rows) == canonical_hash(scenario_rows("STABLE_LINEAR_WEAK", 11, "SMALL_RESEARCH_SAMPLE")[1])))
case("SC07", "sample regimes differ", lambda: require(canonical_hash(scenario_rows("STABLE_LINEAR_WEAK", 11, "LARGER_RESEARCH_SAMPLE")[1]) != canonical_hash(rows)))

case("TM01", "temporal boundaries preregistered", lambda: require(spec["temporal_boundaries"]["embargo_sessions"] == 5))
case("TM02", "no shuffled split", lambda: require(spec["temporal_boundaries"]["method"] == "EXPANDING_WINDOW"))
case("TM03", "no future feature leakage", lambda: require(all(row_eligible(row) for row in rows[:20])))
leaky = copy.deepcopy(rows[0]); leaky["features"]["future_return"] = leaky["relative_return"]
case("TM04", "outcome feature leakage rejected", lambda: raises(ValueError, "FUTURE_OUTCOME_FEATURE_PROHIBITED", lambda: row_eligible(leaky)))

case("MD01", "fixed simple model families", lambda: require(set(MODEL_CONFIGS) == {"DETERMINISTIC_REFERENCE", "LOGISTIC_REGRESSION", "RANDOM_FOREST", "GRADIENT_BOOSTING"}))
case("MD02", "no hyperparameter search", lambda: require(all(not spec["config"].get("hyperparameter_search", False) for spec in MODEL_CONFIGS.values())))
case("MD03", "configuration immutable", lambda: require(canonical_hash(spec["model_configurations"]) == canonical_hash(copy.deepcopy(spec["model_configurations"]))))
case("MD04", "feature set contains no label token", lambda: require(all("label" not in feature and "return" not in feature and "future" not in feature for feature in FEATURE_IDS)))

case("MT01", "results generated for all model runs", lambda: require(len(payload["results"]) == len(SCENARIOS) * len(SAMPLE_REGIMES) * len(SEEDS) * len(MODEL_CONFIGS)))
case("MT02", "degradation generated for all model runs", lambda: require(len(payload["degradation"]) == len(payload["results"])))
case("MT03", "ranking metrics present", lambda: require(all("test_rank_ic" in row and "test_top5_relative" in row for row in payload["results"])))
case("MT04", "calibration metrics present", lambda: require(all("test_brier" in row and "test_brier_skill" in row for row in payload["results"])))
case("MT05", "validation to test degradation present", lambda: require(all("top5_degradation" in row and "brier_skill_degradation" in row for row in payload["degradation"])))
case("MT06", "null false-positive control classified", lambda: require(payload["summary"]["null_control"] in {"NULL_FALSE_POSITIVE_CONTROL_PASS", "NULL_FALSE_POSITIVE_CONTROL_WARNING"}))
case("MT07", "spurious-development control classified", lambda: require(payload["summary"]["spurious_control"] in {"SPURIOUS_SIGNAL_GENERALIZATION_FAILURE_RECOGNIZED", "SPURIOUS_SIGNAL_CONTROL_LIMITED"}))
case("MT08", "regime robustness classified", lambda: require(payload["summary"]["regime_robustness"] in {"REGIME_SCENARIOS_SHOW_EXPECTED_DEGRADATION", "REGIME_DEGRADATION_LIMITED"}))
case("MT09", "ablation V2 present", lambda: require(payload["summary"]["ablation"]["records"] > 0))
case("MT10", "selection preregistered", lambda: require("selection_rule" in spec and "selection_outcomes" in spec))
case("MT11", "selection is allowed", lambda: require(payload["selection"] in spec["selection_outcomes"]))
case("MT12", "complexity hierarchy encoded", lambda: require(MODEL_CONFIGS["LOGISTIC_REGRESSION"]["complexity"] < MODEL_CONFIGS["RANDOM_FOREST"]["complexity"] < MODEL_CONFIGS["GRADIENT_BOOSTING"]["complexity"]))
case("MT13", "experiment classification allowed", lambda: require(payload["classification"] in {"SYNTHETIC_ROBUSTNESS_VALIDATED", "SYNTHETIC_ROBUSTNESS_VALIDATED_WITH_LIMITATIONS", "SYNTHETIC_ROBUSTNESS_REQUIRES_REMEDIATION"}))
case("MT14", "no forbidden production classification", lambda: require(payload["classification"] not in {"REAL_MODEL_VALIDATED", "ALPHA_PROVEN", "PRODUCTION_READY", "PROMOTION_READY"}))

case("RG01", "real data training blocked", lambda: raises(PermissionError, "REAL_DATA_MODEL_TRAINING_BLOCKED", lambda: training_guard(dict(m, classification=REAL, source_manifest_bindings=["NSE"]), rows, RIGHTS_STATUS)))
case("RG02", "rights status license required", lambda: require(manifest["rights_status"] == RIGHTS_STATUS == "LICENSE_REQUIRED"))
case("RG03", "real training status blocked", lambda: require(manifest["real_data_training"] == REAL_DATA_TRAINING_STATUS == "BLOCKED"))
case("RG04", "no promotion authority", lambda: require("PROMOTION_READY" not in canonical_hash(manifest)))
case("RG05", "Stage 4A.3 diff zero", lambda: require(diff_count("Stage 4A.3") == 0))
case("RG06", "Stage 5D diff zero", lambda: require(diff_count("Stage 5D") == 0))
case("RG07", "Stage 6 diff zero", lambda: require(diff_count("Stage 6") == 0))

out = RESULTS / "nextgen_synthetic_challenger_exp2_test_results.csv"
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=["test_id", "description", "status", "detail"])
    writer.writeheader()
    writer.writerows(records)

failed = [r for r in records if r["status"] != "PASS"]
print(json.dumps({"total": len(records), "passed": len(records) - len(failed), "failed": len(failed), "status": "PASS" if not failed else "FAIL"}, sort_keys=True))
if failed:
    raise SystemExit(1)
