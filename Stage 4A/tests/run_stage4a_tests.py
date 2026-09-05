"""Deterministic acceptance tests for Stage 4A chronological ML research."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

TESTS_ROOT = Path(__file__).resolve().parent
STAGE_ROOT = TESTS_ROOT.parent
REPO_ROOT = STAGE_ROOT.parent
MODULE_ROOT = STAGE_ROOT / "stage4a"
sys.path.insert(0, str(MODULE_ROOT))

from benchmarks import rule_score_benchmarks
from data_contract import build_reference_gate, load_config, load_trade_opportunity
from diagnostics import cohort_metrics
from features import RULE_GROUP, build_feature_contract, leakage_feature_names
from folds import modeling_masks, reconstruct_fold_audit, target_masks
from hashing import canonical_json_hash, dataframe_content_hash, source_package_manifest, write_csv_gz
from joint_probability import assert_joint_arithmetic
from metrics import calibration_diagnostics, classification_metrics, pooled_metrics, top_bucket_lift
from models import MODEL_ORDER, build_model_contract, fit_predict_variant
from preprocessing import build_preprocessor, evaluation_unknown_category_count


class SkipTest(RuntimeError):
    pass


def _assert(condition: bool, message: str) -> None:
    if not bool(condition):
        raise AssertionError(message)


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr.strip())
    return result.stdout.strip()


def _run_test(number: int, name: str, function: Callable[[], None]) -> dict[str, object]:
    try:
        function()
        status, details = "PASS", ""
    except SkipTest as exc:
        status, details = "SKIP", str(exc)
    except Exception as exc:
        status, details = "FAIL", f"{type(exc).__name__}: {exc}"
    return {"Test Number": number, "Test": name, "Status": status, "Details": details}


def run_tests(results_dir: Path, mode: str) -> pd.DataFrame:
    config = load_config(STAGE_ROOT)
    source_results = REPO_ROOT / config["source_paths"]["results"]
    opportunity = load_trade_opportunity(REPO_ROOT, config)
    feature_registry = pd.read_csv(source_results / "stage3_1_feature_registry.csv", low_memory=False)
    ml_registry = pd.read_csv(source_results / "stage3_1_ml_column_registry.csv", low_memory=False)
    frozen_folds = pd.read_csv(source_results / "stage3_1_walk_forward_split_manifest.csv", low_memory=False)
    feature_sets, feature_rows, feature_hashes, type_maps = build_feature_contract(feature_registry, ml_registry, config)
    model_rows, model_hashes, model_specs = build_model_contract(config, feature_hashes)
    fold_audit = reconstruct_fold_audit(opportunity, frozen_folds, config)
    reference_gate, _ = build_reference_gate(REPO_ROOT, config)
    predictions = pd.read_csv(results_dir / "stage4a_oos_predictions.csv.gz", low_memory=False)
    joint = pd.read_csv(results_dir / "stage4a_joint_oos_predictions.csv.gz", low_memory=False)
    preprocessing_audit = pd.read_csv(results_dir / "stage4a_preprocessing_audit.csv")
    fit_audit = pd.read_csv(results_dir / "stage4a_model_fit_audit.csv")
    source_text = "\n".join(
        (MODULE_ROOT / name).read_text(encoding="utf-8")
        for name in ["models.py", "preprocessing.py", "folds.py", "metrics.py"]
    ).lower()

    ml_allowed = set(ml_registry.loc[(ml_registry["Dataset"] == "trade_opportunity") & (ml_registry["Role"] == "FEATURE_ALLOWED"), "Column"])
    registry_allowed = set(feature_registry.loc[(feature_registry["Dataset"] == "trade_opportunity") & feature_registry["ML Allowed"].astype(str).str.upper().isin(["TRUE", "1", "YES"]), "Feature Name"])
    all_features = feature_sets["FS3_FULL_SIGNAL_STATE"]
    t1 = config["targets"]["T1_BEFORE_STOP_63"]
    t2 = config["targets"]["T2_BEFORE_STOP_63"]
    entry = config["targets"]["ENTRY_FILLED"]
    year = 2016
    t1_masks = target_masks(opportunity, "T1_BEFORE_STOP_63", t1, year)
    t2_masks = target_masks(opportunity, "T2_BEFORE_STOP_63", t2, year)
    entry_masks = target_masks(opportunity, "ENTRY_FILLED", entry, year)

    train_demo = pd.DataFrame({"num": [1.0, np.nan, 3.0], "cat": ["A", "B", "A"]})
    eval_demo = pd.DataFrame({"num": [100.0, np.nan], "cat": ["C", "A"]})
    demo_preprocessor = build_preprocessor(["num"], ["cat"], True)
    demo_preprocessor.fit(train_demo)
    before_statistics = demo_preprocessor.named_transformers_["numeric"].named_steps["imputer"].statistics_.copy()
    before_categories = [x.copy() for x in demo_preprocessor.named_transformers_["categorical"].named_steps["encoder"].categories_]
    demo_preprocessor.transform(eval_demo)
    after_statistics = demo_preprocessor.named_transformers_["numeric"].named_steps["imputer"].statistics_.copy()
    after_categories = demo_preprocessor.named_transformers_["categorical"].named_steps["encoder"].categories_

    synthetic_predictions = pd.DataFrame({
        "Target": ["X"] * 10, "Model Variant": ["M"] * 10, "Feature Set": ["F"] * 10,
        "Evaluation Year": [2020] * 10, "Signal ID": [f"S{i:02d}" for i in range(10)],
        "Actual Label": [0, 1] * 5, "Predicted Probability": [0.5] * 10,
        "Training Prior": [0.4] * 10,
    })

    tests: list[tuple[int, str, Callable[[], None]]] = []
    add = lambda number, name, fn: tests.append((number, name, fn))
    add(1, "Stage 3.1 frozen tag resolves to expected commit", lambda: _assert(_git("rev-parse", f"{config['stage3_1']['tag']}^{{}}") == config["stage3_1"]["commit"], "tag mismatch"))
    add(2, "Stage 3.1 package hash matches", lambda: _assert(reference_gate.loc[reference_gate["Check"].eq("Stage 3.1 recomputed package hash"), "Status"].eq("PASS").all(), "package hash mismatch"))
    add(3, "Stage 3.1 schema hash matches", lambda: _assert(reference_gate.loc[reference_gate["Check"].str.contains("schema hash"), "Status"].eq("PASS").all(), "schema hash mismatch"))
    add(4, "Stage 3.1 trade-opportunity content hash matches", lambda: _assert(reference_gate.loc[reference_gate["Check"].eq("trade_opportunity logical content hash"), "Status"].eq("PASS").all(), "content hash mismatch"))
    add(5, "Stage 3.1 dataset row count matches", lambda: _assert(len(opportunity) == config["stage3_1"]["datasets"]["trade_opportunity"]["rows"], "row count mismatch"))
    add(6, "Stage 3.1 directory unchanged", lambda: _assert(_git("status", "--porcelain", "--", "Stage 3.1") == "" and _git("diff", "--name-only", config["stage3_1"]["tag"], "--", "Stage 3.1") == "", "Stage 3.1 changed"))
    add(7, "Stage 2B.1 tag unchanged", lambda: _assert(_git("rev-parse", f"{config['stage2b_1']['tag']}^{{}}") == config["stage2b_1"]["commit"], "Stage 2B.1 tag mismatch"))
    add(8, "Stage 3 reference unchanged", lambda: _assert(_git("rev-parse", config["stage3_reference"]["ref"]) == config["stage3_reference"]["commit"], "Stage 3 reference mismatch"))
    add(9, "FEATURE_ALLOWED registry equality", lambda: _assert(ml_allowed == registry_allowed == set(all_features), "registry sets differ"))
    add(10, "Raw date feature count is zero", lambda: _assert(not [x for x in all_features if "DATE" in x.upper()], "date feature found"))
    add(11, "Ticker excluded", lambda: _assert("Ticker" not in all_features, "Ticker present"))
    add(12, "Signal ID excluded", lambda: _assert("Signal ID" not in all_features, "Signal ID present"))
    add(13, "Target leakage count is zero", lambda: _assert(len(leakage_feature_names(all_features)) == 0, "leakage feature found"))
    add(14, "ENTRY censored rows excluded from fitting", lambda: _assert(not (entry_masks["training"] & opportunity["ENTRY_DATA_END_CENSORED"].astype(bool)).any(), "censored ENTRY in training"))
    add(15, "T1 NOT_APPLICABLE excluded", lambda: _assert(not (t1_masks["training"] & opportunity["T1_STATUS"].eq("NOT_APPLICABLE")).any(), "T1 not-applicable in training"))
    add(16, "T1 DATA_END_CENSORED excluded", lambda: _assert(not (t1_masks["training"] & opportunity["T1_STATUS"].eq("DATA_END_CENSORED")).any(), "T1 censored in training"))
    add(17, "T2 NOT_APPLICABLE excluded", lambda: _assert(not (t2_masks["training"] & opportunity["T2_STATUS"].eq("NOT_APPLICABLE")).any(), "T2 not-applicable in training"))
    add(18, "T2 DATA_END_CENSORED excluded", lambda: _assert(not (t2_masks["training"] & opportunity["T2_STATUS"].eq("DATA_END_CENSORED")).any(), "T2 censored in training"))
    add(19, "Training label availability strictly before evaluation start", lambda: _assert((t1_masks["available"].loc[t1_masks["training"]] < t1_masks["evaluation_start"]).all(), "availability violation"))
    add(20, "Fold reconstructed count equals Stage 3.1 contract", lambda: _assert(fold_audit["Unexplained Count Differences"].eq(0).all(), "fold difference"))
    add(21, "Training as-of dates strictly earlier than evaluation", lambda: _assert((opportunity.loc[t2_masks["training"], "Signal Date"] < t2_masks["evaluation_start"]).all(), "same/future as-of date"))
    add(22, "No evaluation row appears in training", lambda: _assert(not set(opportunity.index[t1_masks["training"]]) & set(opportunity.index[t1_masks["evaluation_score"]]), "row overlap"))
    add(23, "No random split", lambda: _assert("train_test_split" not in source_text and config["prohibitions"]["random_train_test_split"], "random split enabled"))
    add(24, "No shuffled CV", lambda: _assert("kfold" not in source_text and "shuffle=true" not in source_text and config["prohibitions"]["shuffled_cross_validation"], "shuffled CV enabled"))
    add(25, "No SMOTE", lambda: _assert("smote" not in source_text and config["prohibitions"]["class_rebalancing"], "SMOTE found"))
    add(26, "No oversampling", lambda: _assert("oversampl" not in source_text and config["prohibitions"]["class_rebalancing"], "oversampling found"))
    add(27, "No class-weight tuning", lambda: _assert(config["logistic_parameters"]["class_weight"] is None and config["random_forest_parameters"]["class_weight"] is None, "class weights used"))
    add(28, "No target encoding", lambda: _assert("targetencoder" not in source_text.replace(" ", "") and not config["preprocessing"]["target_encoding"], "target encoding found"))
    add(29, "Imputer fitted only on training fold", lambda: _assert(np.array_equal(before_statistics, after_statistics) and before_statistics[0] == 2.0, "imputer changed on evaluation"))
    add(30, "Scaler fitted only on training fold", lambda: _assert(demo_preprocessor.named_transformers_["numeric"].named_steps["scaler"].mean_[0] == 2.0, "scaler not training-only"))
    add(31, "Encoder fitted only on training fold", lambda: _assert(all(np.array_equal(a, b) for a, b in zip(before_categories, after_categories, strict=True)), "encoder changed"))
    add(32, "Unknown evaluation category handled without refit", lambda: _assert(evaluation_unknown_category_count(train_demo, eval_demo, ["cat"]) == 1 and "C" not in set(after_categories[0]), "unknown category leaked"))

    def test_dummy_prior() -> None:
        train = opportunity.loc[entry_masks["training"]].head(200)
        evaluation = opportunity.loc[entry_masks["evaluation_score"]].head(10)
        prob, _, _, _ = fit_predict_variant("DUMMY_PRIOR", "ENTRY_FILLED", 2016, "NONE", [], {"numeric": [], "categorical": []}, train, evaluation, train["ENTRY_FILLED"], config)
        _assert(np.array_equal(prob, np.full(len(evaluation), train["ENTRY_FILLED"].astype(int).mean())), "dummy differs from prior")

    add(33, "DUMMY prior equals training prevalence", test_dummy_prior)
    add(34, "Logistic hyperparameters exactly frozen", lambda: _assert(model_specs["LOGIT_FULL"]["hyperparameters"] == config["logistic_parameters"], "logistic spec drift"))
    add(35, "RF hyperparameters exactly frozen", lambda: _assert(model_specs["RF_FULL"]["hyperparameters"] == config["random_forest_parameters"], "RF spec drift"))
    add(36, "Model seed fixed", lambda: _assert(all(spec["random_seed"] == 42 for spec in model_specs.values()), "seed drift"))
    add(37, "Feature sets exactly preregistered", lambda: _assert(set(feature_sets) == set(config["feature_sets"]) and len(feature_sets) == 3, "feature-set drift"))
    add(38, "FS1 contains only RULE_ENGINE_DERIVED_FEATURES", lambda: _assert(set(feature_rows.loc[feature_rows["Feature Set"].eq("FS1_RULE_SUMMARY"), "Feature Group"]) == {RULE_GROUP}, "FS1 wrong group"))
    add(39, "FS2 excludes RULE_ENGINE_DERIVED_FEATURES", lambda: _assert(not set(feature_sets["FS1_RULE_SUMMARY"]) & set(feature_sets["FS2_RAW_SIGNAL_STATE"]), "FS2 contains rule features"))
    add(40, "FS3 equals complete allowed feature set", lambda: _assert(set(feature_sets["FS3_FULL_SIGNAL_STATE"]) == ml_allowed, "FS3 incomplete"))
    add(41, "No feature-set drift across folds", lambda: _assert(predictions.loc[~predictions["Feature Set"].eq("NONE")].groupby("Model Variant")["Feature Set Hash"].nunique().eq(1).all(), "feature hash varies by fold"))
    add(42, "No feature selection", lambda: _assert("selectfrommodel" not in source_text.replace("_", "") and config["prohibitions"]["feature_selection"], "feature selection found"))
    add(43, "No hyperparameter search", lambda: _assert(not any(term in source_text for term in ["gridsearchcv", "randomizedsearchcv", "optuna"]) and config["prohibitions"]["hyperparameter_search"], "search found"))
    add(44, "No probability-threshold optimization", lambda: _assert(config["fixed_probability_threshold"] == 0.5 and config["prohibitions"]["probability_threshold_optimization"], "threshold not fixed"))
    add(45, "T1 model conditional on valid filled opportunity", lambda: _assert(opportunity.loc[t1_masks["training"], "ENTRY_STATUS"].eq("FILLED").all() and opportunity.loc[t1_masks["training"], "ENTRY_RISK_VALID"].astype(bool).all(), "T1 training not conditional"))
    add(46, "T2 model conditional on valid filled opportunity", lambda: _assert(opportunity.loc[t2_masks["training"], "ENTRY_STATUS"].eq("FILLED").all() and opportunity.loc[t2_masks["training"], "ENTRY_RISK_VALID"].astype(bool).all(), "T2 training not conditional"))
    add(47, "T1 conditional model scores all evaluation opportunities", lambda: _assert(predictions.loc[(predictions["Target"] == "T1_BEFORE_STOP_63") & (predictions["Model Variant"] == "DUMMY_PRIOR")].groupby("Evaluation Year").size().min() > predictions.loc[(predictions["Target"] == "T1_BEFORE_STOP_63") & (predictions["Model Variant"] == "DUMMY_PRIOR")].dropna(subset=["Actual Label"]).groupby("Evaluation Year").size().min(), "T1 only scored labelled rows"))
    add(48, "T2 conditional model scores all evaluation opportunities", lambda: _assert(predictions.loc[(predictions["Target"] == "T2_BEFORE_STOP_63") & (predictions["Model Variant"] == "DUMMY_PRIOR")].groupby("Evaluation Year").size().min() > predictions.loc[(predictions["Target"] == "T2_BEFORE_STOP_63") & (predictions["Model Variant"] == "DUMMY_PRIOR")].dropna(subset=["Actual Label"]).groupby("Evaluation Year").size().min(), "T2 only scored labelled rows"))
    add(49, "JOINT_T1 equals product", lambda: _assert(np.allclose(joint.loc[joint["Target"].eq("JOINT_T1"), "Predicted Probability"], joint.loc[joint["Target"].eq("JOINT_T1"), "P Fill"] * joint.loc[joint["Target"].eq("JOINT_T1"), "P T1 Conditional"], rtol=0.0, atol=2e-12), "T1 product exceeds serialized precision"))
    add(50, "JOINT_T2 equals product", lambda: _assert(np.allclose(joint.loc[joint["Target"].eq("JOINT_T2"), "Predicted Probability"], joint.loc[joint["Target"].eq("JOINT_T2"), "P Fill"] * joint.loc[joint["Target"].eq("JOINT_T2"), "P T2 Conditional"], rtol=0.0, atol=2e-12), "T2 product exceeds serialized precision"))
    add(51, "Observed non-fill produces joint actual zero", lambda: _assert(joint.loc[joint["Label Status"].eq("AVAILABLE_NON_FILL"), "Actual Label"].eq(0).all(), "nonfill not zero"))
    add(52, "Incomplete entry-window row excluded from joint label", lambda: _assert(joint.loc[joint["Label Status"].eq("ENTRY_DATA_END_CENSORED"), "Actual Label"].isna().all(), "entry-censored label manufactured"))
    add(53, "Invalid-risk fill excluded from joint label", lambda: _assert(joint.loc[joint["Label Status"].eq("FILLED_INVALID_RISK"), "Actual Label"].isna().all(), "invalid-risk label manufactured"))
    add(54, "Target-censored fill excluded from joint label", lambda: _assert(joint.loc[joint["Label Status"].isin(["T1_DATA_END_CENSORED", "T2_DATA_END_CENSORED"]), "Actual Label"].isna().all(), "target-censored label manufactured"))
    add(55, "Joint label availability semantics correct", lambda: _assert(joint.loc[joint["Label Status"].isin(["AVAILABLE_NON_FILL", "AVAILABLE_VALID_FILL"]), "Label Available Date"].notna().all() and joint.loc[~joint["Label Status"].isin(["AVAILABLE_NON_FILL", "AVAILABLE_VALID_FILL"]), "Label Available Date"].isna().all(), "joint availability inconsistent"))
    add(56, "ROC AUC implementation checked", lambda: _assert(classification_metrics([0, 1], [0.1, 0.9], 0.5)["ROC AUC"] == roc_auc_score([0, 1], [0.1, 0.9]) == 1.0, "AUC mismatch"))
    add(57, "Average Precision implementation checked", lambda: _assert(classification_metrics([0, 1, 1], [0.1, 0.6, 0.9], 0.5)["Average Precision"] == average_precision_score([0, 1, 1], [0.1, 0.6, 0.9]), "AP mismatch"))
    add(58, "Brier Score implementation checked", lambda: _assert(classification_metrics([0, 1], [0.25, 0.75], 0.5)["Brier Score"] == brier_score_loss([0, 1], [0.25, 0.75]), "Brier mismatch"))
    add(59, "Brier Skill benchmark uses training prior only", lambda: _assert(classification_metrics([0, 1], [0.2, 0.8], [0.4, 0.4])["Brier Benchmark Score"] == np.mean((np.array([0, 1]) - 0.4) ** 2), "wrong benchmark"))

    def test_logloss_clipping() -> None:
        original = np.array([0.0, 1.0])
        result = classification_metrics([0, 1], original, 0.5)
        _assert(np.array_equal(original, [0.0, 1.0]) and np.isfinite(result["Log Loss"]), "metric clipping mutated probability")

    add(60, "Log Loss clipping affects metric only", test_logloss_clipping)
    add(61, "Calibration buckets deterministic", lambda: _assert(dataframe_content_hash(calibration_diagnostics(synthetic_predictions)[0]) == dataframe_content_hash(calibration_diagnostics(synthetic_predictions)[0]), "calibration nondeterministic"))
    add(62, "Top-decile ranking deterministic", lambda: _assert(dataframe_content_hash(top_bucket_lift(synthetic_predictions)) == dataframe_content_hash(top_bucket_lift(synthetic_predictions)), "ranking nondeterministic"))

    def test_tie_break() -> None:
        lift = top_bucket_lift(synthetic_predictions)
        top = lift.loc[lift["Bucket"].eq("TOP_10_PERCENT")].iloc[0]
        expected_actual = synthetic_predictions.sort_values(["Predicted Probability", "Signal ID"], ascending=[False, True], kind="mergesort").iloc[0]["Actual Label"]
        _assert(top["Success Rate"] == expected_actual, "Signal ID stable tie-break not used")

    add(63, "Stable tie-break uses metadata only", test_tie_break)
    add(64, "Yearly prediction uniqueness", lambda: _assert(not predictions.duplicated(["Signal ID", "Evaluation Year", "Target", "Model Variant"]).any(), "duplicate prediction"))
    add(65, "Pooled OOS contains only yearly OOS predictions", lambda: _assert(set(predictions["Evaluation Year"]) == (set(config["sanity_evaluation_years"]) if mode == "sanity" else set(config["evaluation_years"])), "unexpected year"))
    add(66, "2024-2026 report exists", lambda: _assert(mode == "sanity" or ((results_dir / "stage4a_recent_2024_2026_metrics.csv").exists() and set(pd.read_csv(results_dir / "stage4a_recent_2024_2026_metrics.csv")["Target"]) == set(config["targets"]) | {"JOINT_T1", "JOINT_T2"}), "recent report incomplete"))
    add(67, "Cohort diagnostics do not refit", lambda: _assert(pd.read_csv(results_dir / "stage4a_metrics_by_setup.csv")["Models Refit for Cohort"].astype(str).str.upper().isin(["FALSE", "0"]).all(), "cohort refit detected"))
    add(68, "Rule ranking benchmark uses frozen score unchanged", lambda: _assert(pd.read_csv(results_dir / "stage4a_rule_score_benchmarks.csv")["Score Modified"].astype(str).str.upper().isin(["FALSE", "0"]).all(), "rule score modified"))
    add(69, "Logistic coefficient diagnostics do not alter feature set", lambda: _assert(set(pd.read_csv(results_dir / "stage4a_logistic_coefficient_audit.csv.gz")["Model Variant"].unique()) == {"LOGIT_RULE", "LOGIT_RAW", "LOGIT_FULL"} and set(feature_sets["FS3_FULL_SIGNAL_STATE"]) == ml_allowed, "coefficient diagnostic changed features"))
    add(70, "Model binaries not required", lambda: _assert(not list(STAGE_ROOT.rglob("*.pkl")) and not list(STAGE_ROOT.rglob("*.joblib")), "model binary found"))
    add(71, "Model spec hashes deterministic", lambda: _assert(build_model_contract(config, feature_hashes)[1] == model_hashes, "model hashes drift"))
    add(72, "Feature-set hashes deterministic", lambda: _assert(build_feature_contract(feature_registry, ml_registry, config)[2] == feature_hashes, "feature hashes drift"))

    def test_package_path_independent() -> None:
        behavior = json.loads((results_dir / "stage4a_source_manifest.json").read_text(encoding="utf-8"))["stage4a"]
        copied = Path(tempfile.mkdtemp(prefix="stage4a_package_test_"))
        try:
            for item in behavior["sources"]:
                destination = copied / item["relative_path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(STAGE_ROOT / item["relative_path"], destination)
            rebuilt = source_package_manifest(copied, [item["relative_path"] for item in behavior["sources"]])
            _assert(rebuilt["package_hash"] == behavior["package_hash"], "absolute path affected package hash")
        finally:
            shutil.rmtree(copied)

    add(73, "Stage 4A package hash path independent", test_package_path_independent)

    def test_oos_hash() -> None:
        first = dataframe_content_hash(predictions)
        temp_path = Path(tempfile.gettempdir()) / "stage4a_oos_hash_test.csv.gz"
        write_csv_gz(predictions, temp_path)
        try:
            second = dataframe_content_hash(pd.read_csv(temp_path, low_memory=False))
            _assert(first == second, "OOS logical hash changed after deterministic serialization")
        finally:
            temp_path.unlink(missing_ok=True)

    add(74, "OOS prediction hash deterministic", test_oos_hash)

    def test_second_full_run() -> None:
        path = results_dir / "stage4a_determinism_check.csv"
        if mode != "official" or not path.exists():
            raise SkipTest("Requires the second complete official run")
        determinism = pd.read_csv(path)
        _assert(determinism["Status"].eq("PASS").all() and determinism["Artifact"].eq("stage4a_oos_predictions.csv.gz").any(), "official rerun mismatch")

    add(75, "Second full run prediction hash exact match", test_second_full_run)
    result = pd.DataFrame([_run_test(number, name, function) for number, name, function in tests])
    _assert(len(result) == 75 and result["Test Number"].tolist() == list(range(1, 76)), "test numbering incomplete")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=["sanity", "official"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = run_tests(args.results_dir.resolve(), args.mode)
    output = args.output.resolve() if args.output else args.results_dir.resolve() / "stage4a_unit_test_results.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(output, index=False, lineterminator="\n")
    print(results["Status"].value_counts().to_string())
    failed = results["Status"].eq("FAIL").sum()
    if failed:
        print(results.loc[results["Status"].eq("FAIL"), ["Test Number", "Test", "Details"]].to_string(index=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
