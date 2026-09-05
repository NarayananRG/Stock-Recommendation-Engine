"""Stage 4A fixed chronological ML classification experiment runner."""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from benchmarks import rule_score_benchmarks
from data_contract import build_reference_gate, load_config, load_trade_opportunity, repo_root_from_stage
from diagnostics import cohort_metrics, dataset_cohort_metrics, model_comparison, research_evidence_classification
from features import build_feature_contract
from folds import modeling_masks, reconstruct_fold_audit
from hashing import (
    canonical_json_hash, dataframe_content_hash, directory_manifest, sha256_file,
    source_package_manifest, write_csv, write_csv_gz, write_json,
)
from joint_probability import build_joint_predictions
from metrics import (
    calibration_diagnostics, metrics_by_era, metrics_by_year, pooled_metrics,
    recent_metrics, top_bucket_lift, yearly_stability,
)
from models import MODEL_ORDER, build_model_contract, fit_predict_variant
from validation import build_validation_checks, write_validation_artifacts


STAGE_ROOT = HERE.parent
REPO_ROOT = repo_root_from_stage(STAGE_ROOT)
BEHAVIOR_FILES = [
    "config/stage4a_model_config.json",
    "stage4a/Stock_Alert_Stage4A_ML_Baselines.py",
    "stage4a/__init__.py",
    "stage4a/data_contract.py",
    "stage4a/features.py",
    "stage4a/folds.py",
    "stage4a/preprocessing.py",
    "stage4a/models.py",
    "stage4a/metrics.py",
    "stage4a/joint_probability.py",
    "stage4a/benchmarks.py",
    "stage4a/validation.py",
    "stage4a/hashing.py",
    "stage4a/diagnostics.py",
    "tests/run_stage4a_tests.py",
]


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    selected = frame.loc[:, columns].copy()
    for column in selected:
        if pd.api.types.is_float_dtype(selected[column]):
            selected[column] = selected[column].map(lambda v: "" if pd.isna(v) else f"{v:.6f}")
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in selected.itertuples(index=False, name=None)]
    return "\n".join([header, separator, *body])


def _experiment_identity(
    config: dict[str, Any], package_hash: str, config_hash: str,
    feature_hashes: dict[str, str], model_hashes: dict[str, str], mode: str,
) -> dict[str, Any]:
    seed = {
        "stage3_1_frozen_tag_commit": config["stage3_1"]["commit"],
        "stage3_1_package_hash": config["stage3_1"]["package_hash"],
        "stage3_1_trade_opportunity_content_hash": config["stage3_1"]["datasets"]["trade_opportunity"]["content_hash"],
        "stage4a_code_package_hash": package_hash,
        "stage4a_config_hash": config_hash,
        "feature_set_hashes": feature_hashes,
        "model_spec_hashes": model_hashes,
        "evaluation_start": config["experiment_start"],
        "evaluation_end": config["experiment_end"],
    }
    digest = canonical_json_hash(seed)
    experiment_id = f"S4A_20160101_20260828_{digest[:12]}"
    return {
        "EXPERIMENT_ID": experiment_id,
        "STAGE4A_CODE_PACKAGE_HASH": package_hash,
        "STAGE4A_CONFIG_HASH": config_hash,
        "STAGE3_1_FROZEN_TAG_COMMIT": config["stage3_1"]["commit"],
        "STAGE3_1_EXPERIMENT_ID": config["stage3_1"]["experiment_id"],
        "STAGE3_1_PACKAGE_HASH": config["stage3_1"]["package_hash"],
        "STAGE3_1_TRADE_OPPORTUNITY_CONTENT_HASH": config["stage3_1"]["datasets"]["trade_opportunity"]["content_hash"],
        "FEATURE_SET_HASHES": feature_hashes,
        "MODEL_SPEC_HASHES": model_hashes,
        "EVALUATION_START": config["experiment_start"],
        "EVALUATION_END": config["experiment_end"],
        "RUN_MODE": mode,
        "ML_MODEL_TRAINED": True,
        "HYPERPARAMETER_SEARCH_PERFORMED": False,
        "FEATURE_SELECTION_PERFORMED": False,
        "PROBABILITY_THRESHOLD_OPTIMIZED": False,
        "CLASS_REBALANCING_PERFORMED": False,
        "ML_TRADING_BACKTEST_RUN": False,
    }


def _environment_report() -> dict[str, Any]:
    import scipy
    import joblib
    import threadpoolctl
    return {
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": {
            "numpy": np.__version__, "pandas": pd.__version__, "scikit-learn": sklearn.__version__,
            "scipy": scipy.__version__, "joblib": joblib.__version__, "threadpoolctl": threadpoolctl.__version__,
        },
        "network_data_downloaded": False,
        "model_training_packages_used": ["scikit-learn"],
        "random_seed": 42,
    }


def _prediction_rows(
    opportunity: pd.DataFrame,
    config: dict[str, Any],
    years: list[int],
    feature_sets: dict[str, list[str]],
    type_maps: dict[str, dict[str, list[str]]],
    feature_hashes: dict[str, str],
    model_hashes: dict[str, str],
    experiment_id: str,
    sanity_tickers: list[str] | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    predictions, fit_rows, preprocessing_rows, coefficient_rows = [], [], [], []
    metadata_columns = [
        "Signal ID", "Ticker", "Signal Date", "Dataset Cohort", "Original Signal",
        "Setup", "Market Regime", "Actionability Score", "Technical Score",
    ]
    for target, target_spec in config["targets"].items():
        for year in years:
            masks = modeling_masks(opportunity, target, target_spec, year, sanity_tickers)
            train = opportunity.loc[masks["training"]].copy()
            evaluation = opportunity.loc[masks["evaluation_score"]].copy()
            label_mask = masks["evaluation_label"].loc[evaluation.index]
            if train.empty or evaluation.empty:
                raise RuntimeError(f"Empty modeling fold for {target} {year}")
            y_train = train[target].astype(int)
            training_positive = int(y_train.sum())
            training_prevalence = float(y_train.mean())
            for variant in MODEL_ORDER:
                feature_set = config["model_variants"][variant]["feature_set"]
                names = [] if feature_set == "NONE" else feature_sets[feature_set]
                type_map = {"numeric": [], "categorical": []} if feature_set == "NONE" else type_maps[feature_set]
                probability, fit_audit, preprocessing_audit, coefficients = fit_predict_variant(
                    variant, target, year, feature_set, names, type_map,
                    train, evaluation, y_train, config,
                )
                fit_rows.append(fit_audit)
                if preprocessing_audit is not None:
                    preprocessing_rows.append(preprocessing_audit)
                coefficient_rows.extend(coefficients)
                output = evaluation[metadata_columns].copy()
                output["Evaluation Year"] = int(year)
                output["Target"] = target
                output["Model Variant"] = variant
                output["Feature Set"] = feature_set
                output["Model Spec Hash"] = model_hashes[variant]
                output["Feature Set Hash"] = feature_hashes.get(feature_set, "NONE")
                output["Stage 3.1 Experiment ID"] = config["stage3_1"]["experiment_id"]
                output["Stage 4A Experiment ID"] = experiment_id
                output["Training Cutoff Date"] = masks["evaluation_start"]
                output["Predicted Probability"] = probability
                output["Actual Label"] = np.where(label_mask.to_numpy(), evaluation[target].astype(float), np.nan)
                output["Label Status"] = evaluation[target_spec["status"]].astype("string").to_numpy()
                output["Label Available Date"] = evaluation[target_spec["available_date"]].to_numpy()
                output["Training Rows"] = len(train)
                output["Training Positive Count"] = training_positive
                output["Training Prevalence"] = training_prevalence
                output["Training Prior"] = training_prevalence
                predictions.append(output)
    result = pd.concat(predictions, ignore_index=True)
    result = result.sort_values(["Target", "Evaluation Year", "Model Variant", "Signal ID"], kind="mergesort").reset_index(drop=True)
    return result, pd.DataFrame(fit_rows), pd.DataFrame(preprocessing_rows), pd.DataFrame(coefficient_rows)


def _joint_metric_table(yearly: pd.DataFrame, pooled: pd.DataFrame, eras: pd.DataFrame) -> pd.DataFrame:
    parts = []
    one = yearly.copy(); one.insert(3, "Scope Type", "EVALUATION_YEAR"); one.insert(4, "Scope", one.pop("Evaluation Year"))
    # Normalize pooled and era frames without changing metric values.
    two = pooled.drop(columns=["Scope"], errors="ignore").copy(); two.insert(3, "Scope Type", "POOLED_OOS"); two.insert(4, "Scope", "POOLED_OOS")
    three = eras.copy(); three.insert(3, "Scope Type", "ERA"); three.insert(4, "Scope", three.pop("Era"))
    columns = list(one.columns)
    for part in [one, two, three]:
        parts.append(part.reindex(columns=columns))
    return pd.concat(parts, ignore_index=True)


def _output_manifest(output_dir: Path) -> dict[str, Any]:
    artifacts = []
    for path in sorted(p for p in output_dir.iterdir() if p.is_file() and p.name != "stage4a_output_manifest.json"):
        record = {"artifact": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        if path.suffix == ".csv" or path.name.endswith(".csv.gz"):
            try:
                frame = pd.read_csv(path, low_memory=False)
                record["row_count"] = len(frame)
                record["column_count"] = len(frame.columns)
                record["logical_content_hash"] = dataframe_content_hash(frame)
            except pd.errors.EmptyDataError:
                record["row_count"] = 0
                record["column_count"] = 0
                record["logical_content_hash"] = canonical_json_hash([])
        artifacts.append(record)
    return {"canonical_serialization": {"floats": "%.12g", "line_ending": "LF", "gzip_mtime": 0}, "artifacts": artifacts}


def _write_delivery_report(output_dir: Path, engineering_status: str) -> None:
    comparison = pd.read_csv(output_dir / "stage4a_model_comparison.csv")
    evidence = pd.read_csv(output_dir / "stage4a_research_evidence_classification.csv")
    recent = pd.read_csv(output_dir / "stage4a_recent_2024_2026_metrics.csv")
    determinism_path = output_dir / "stage4a_determinism_check.csv"
    deterministic = determinism_path.exists() and pd.read_csv(determinism_path)["Status"].eq("PASS").all()
    columns = ["Target", "Model Variant", "ROC AUC Pooled", "Brier Skill Score vs Training Prior Pooled", "Median Yearly ROC AUC", "ROC AUC Recent", "Brier Skill Score vs Training Prior Recent", "Pooled Top-Decile Lift", "Total Yearly Positive Count"]
    evidence_columns = ["Target", "Model Variant", "Research Evidence Classification"]
    recent_columns = ["Target", "Model Variant", "Rows", "Positive Count", "ROC AUC", "Average Precision", "Brier Score", "Brier Skill Score vs Training Prior"]
    declarations = [
        "STAGE 2.2.2 FINAL MODIFIED: NO", "STAGE 2B MODIFIED: NO", "STAGE 2B.1 MODIFIED: NO",
        "STAGE 3 MODIFIED: NO", "STAGE 3.1 MODIFIED: NO", "STAGE 3.1 FROZEN TAG VERIFIED: YES",
        "STAGE 1 SIGNAL RULES CHANGED: NO", "ENTRY RULES CHANGED: NO", "D1 MANAGEMENT RULES CHANGED: NO",
        "FEATURE SET SELECTED FROM OOS RESULTS: NO", "FEATURE SELECTION PERFORMED: NO",
        "HYPERPARAMETER SEARCH PERFORMED: NO", "PROBABILITY THRESHOLD OPTIMIZED: NO",
        "CLASS REBALANCING PERFORMED: NO", "ML MODEL TRAINED: YES",
        "CHRONOLOGICAL WALK_FORWARD USED: YES", "RANDOM TRAIN_TEST SPLIT USED: NO",
        "MODEL USED FOR LIVE TRADING: NO", "ML TRADING BACKTEST RUN: NO",
        "STAGE 5 IMPLEMENTED: NO", "STAGE 4B IMPLEMENTED: NO",
        f"READY FOR INDEPENDENT STAGE 4A AUDIT: {'YES' if engineering_status in ['PASS', 'PASS WITH WARNINGS'] and deterministic else 'NO'}",
    ]
    text = f"""# Stage 4A Delivery Report

## Outcome

Engineering status: **{engineering_status}**. This is historical walk-forward / pseudo-OOS research evidence, not true unseen prospective validation and not a live-trading model. No production model is selected.

## Primary comparisons

{_markdown_table(comparison, columns)}

These fixed descriptive comparisons answer the pre-registered questions: LOGIT_RAW versus LOGIT_FULL measures incremental rule-summary information; LOGIT_RULE versus LOGIT_FULL measures incremental richer raw-state information; LOGIT_FULL versus RF_FULL compares fixed linear and nonlinear baselines. Losing models were not tuned or altered.

## Research evidence classification

{_markdown_table(evidence, evidence_columns)}

## RECENT 2024-2026

{_markdown_table(recent, recent_columns)}

Recent evidence is shown explicitly and was not used for tuning, filtering, feature selection, or model selection.

## Reproducibility and scope

The complete official experiment covers 2016 through 2026-08-28, uses expanding target-specific availability folds, and was executed twice. Exact determinism status: **{'PASS' if deterministic else 'PENDING/FAIL'}**. OOS probabilities, composed probabilities, metrics, fold audits, preprocessor audits, fit audits, hashes, and tests are retained; model binaries are intentionally unnecessary.

## Known limitations

- Current-universe survivorship bias.
- Historical pseudo-OOS is not prospective unseen data.
- Daily OHLC intraday-order, entry-day, and exit-day ambiguity.
- Holiday-short weekly delay and generic historical execution-cost modeling.
- Sector/index membership is not historical point-in-time.
- Earlier D1 and recent deterministic evidence were weak; Stage 2B.1 empirical confidence was overconfident.
- Stage 4A probabilities are not calibrated for live display.
- No prospective validation and no ML trading strategy validation.

## Required declarations

```text
{os.linesep.join(declarations)}
```
"""
    (STAGE_ROOT / "Stage4A_Delivery_Report.md").write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")


def run_experiment(mode: str, output_dir: Path) -> None:
    config = load_config(STAGE_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_gate, source_audit = build_reference_gate(REPO_ROOT, config)
    opportunity = load_trade_opportunity(REPO_ROOT, config)
    results_root = REPO_ROOT / config["source_paths"]["results"]
    feature_registry = pd.read_csv(results_root / "stage3_1_feature_registry.csv", low_memory=False)
    ml_registry = pd.read_csv(results_root / "stage3_1_ml_column_registry.csv", low_memory=False)
    frozen_folds = pd.read_csv(results_root / "stage3_1_walk_forward_split_manifest.csv", low_memory=False)
    feature_sets, feature_registry_output, feature_hashes, type_maps = build_feature_contract(feature_registry, ml_registry, config)
    model_registry, model_hashes, model_specs = build_model_contract(config, feature_hashes)
    package_manifest = source_package_manifest(STAGE_ROOT, BEHAVIOR_FILES)
    config_hash = sha256_file(STAGE_ROOT / "config" / "stage4a_model_config.json")
    identity = _experiment_identity(config, package_manifest["package_hash"], config_hash, feature_hashes, model_hashes, mode)
    years = config["sanity_evaluation_years"] if mode == "sanity" else config["evaluation_years"]
    sanity_tickers = config["sanity_tickers"] if mode == "sanity" else None
    fold_audit = reconstruct_fold_audit(opportunity, frozen_folds, config)
    predictions, fit_audit, preprocessing_audit, coefficients = _prediction_rows(
        opportunity, config, years, feature_sets, type_maps, feature_hashes,
        model_hashes, identity["EXPERIMENT_ID"], sanity_tickers,
    )
    joint = build_joint_predictions(predictions, opportunity)

    direct_yearly = metrics_by_year(predictions)
    direct_pooled = pooled_metrics(predictions)
    direct_eras = metrics_by_era(predictions)
    joint_yearly = metrics_by_year(joint)
    joint_pooled = pooled_metrics(joint)
    joint_eras = metrics_by_era(joint)
    all_predictions = pd.concat([predictions, joint], ignore_index=True, sort=False)
    all_yearly = pd.concat([direct_yearly, joint_yearly], ignore_index=True)
    all_pooled = pd.concat([direct_pooled, joint_pooled], ignore_index=True)
    all_recent = recent_metrics(all_predictions)
    all_stability = yearly_stability(all_yearly)
    direct_calibration, direct_calibration_summary = calibration_diagnostics(predictions)
    joint_calibration, _ = calibration_diagnostics(joint)
    direct_lift = top_bucket_lift(predictions)
    joint_lift = top_bucket_lift(joint)
    all_lift = pd.concat([direct_lift, joint_lift], ignore_index=True)
    comparison = model_comparison(all_pooled, all_recent, all_stability, all_lift)
    evidence = research_evidence_classification(all_pooled, all_recent, all_stability)

    write_json(identity, output_dir / "stage4a_experiment_identity.json")
    write_json({"stage4a": package_manifest, "frozen_inputs": source_audit}, output_dir / "stage4a_source_manifest.json")
    write_json(_environment_report(), output_dir / "stage4a_environment_report.json")
    write_csv(reference_gate, output_dir / "stage4a_reference_gate.csv")
    write_csv(feature_registry_output, output_dir / "stage4a_feature_set_registry.csv")
    write_json({f"{key}_HASH": value for key, value in feature_hashes.items()}, output_dir / "stage4a_feature_set_hashes.json")
    write_csv(model_registry, output_dir / "stage4a_model_spec_registry.csv")
    write_json({variant: {"MODEL_SPEC_HASH": model_hashes[variant], "specification": model_specs[variant]} for variant in MODEL_ORDER}, output_dir / "stage4a_model_spec_hashes.json")
    write_csv(fold_audit, output_dir / "stage4a_fold_reconstruction_audit.csv")
    write_csv(preprocessing_audit, output_dir / "stage4a_preprocessing_audit.csv")
    write_csv(fit_audit, output_dir / "stage4a_model_fit_audit.csv")
    write_csv_gz(predictions, output_dir / "stage4a_oos_predictions.csv.gz")
    write_csv_gz(joint, output_dir / "stage4a_joint_oos_predictions.csv.gz")
    write_csv(direct_yearly, output_dir / "stage4a_metrics_by_year.csv")
    write_csv(direct_pooled, output_dir / "stage4a_metrics_pooled_oos.csv")
    write_csv(direct_eras, output_dir / "stage4a_metrics_by_era.csv")
    write_csv(all_recent, output_dir / "stage4a_recent_2024_2026_metrics.csv")
    write_csv(all_stability, output_dir / "stage4a_yearly_stability.csv")
    write_csv(direct_calibration, output_dir / "stage4a_calibration_buckets.csv")
    write_csv(direct_calibration_summary, output_dir / "stage4a_calibration_summary.csv")
    write_csv(rule_score_benchmarks(predictions, joint), output_dir / "stage4a_rule_score_benchmarks.csv")
    write_csv(direct_lift, output_dir / "stage4a_top_bucket_lift.csv")
    write_csv(_joint_metric_table(joint_yearly, joint_pooled, joint_eras), output_dir / "stage4a_joint_metrics.csv")
    write_csv(joint_calibration, output_dir / "stage4a_joint_calibration_buckets.csv")
    write_csv(joint_lift, output_dir / "stage4a_joint_top_bucket_lift.csv")
    write_csv(dataset_cohort_metrics(all_predictions), output_dir / "stage4a_metrics_by_dataset_cohort.csv")
    write_csv(cohort_metrics(all_predictions, "Setup"), output_dir / "stage4a_metrics_by_setup.csv")
    write_csv(cohort_metrics(all_predictions, "Market Regime"), output_dir / "stage4a_metrics_by_regime.csv")
    write_csv(cohort_metrics(all_predictions, "Original Signal"), output_dir / "stage4a_metrics_by_original_signal.csv")
    write_csv(comparison, output_dir / "stage4a_model_comparison.csv")
    write_csv(evidence, output_dir / "stage4a_research_evidence_classification.csv")
    write_csv_gz(coefficients, output_dir / "stage4a_logistic_coefficient_audit.csv.gz")
    checks = build_validation_checks(
        STAGE_ROOT, mode, years, config, reference_gate, feature_sets,
        feature_registry_output, feature_hashes, model_specs, model_hashes,
        fold_audit, preprocessing_audit, fit_audit, predictions, joint,
        all_recent, None,
    )
    status = write_validation_artifacts(checks, output_dir)
    write_json(_output_manifest(output_dir), output_dir / "stage4a_output_manifest.json")
    if mode == "official":
        _write_delivery_report(output_dir, status)
    failed = checks["Status"].eq("FAIL").sum()
    if failed and not (mode == "official" and failed == 1 and checks.loc[checks["Status"].eq("FAIL"), "Check"].eq("Second full run exact match").all()):
        raise RuntimeError(f"Stage 4A {mode} validation failed ({failed} checks)")
    print(f"STAGE4A_RUN_COMPLETE mode={mode} experiment={identity['EXPERIMENT_ID']} rows={len(predictions)} joint_rows={len(joint)} validation={status}", flush=True)


def compare_runs(reference_dir: Path, candidate_dir: Path) -> None:
    identity_names = ["stage4a_experiment_identity.json", "stage4a_feature_set_hashes.json", "stage4a_model_spec_hashes.json"]
    data_names = [
        "stage4a_feature_set_registry.csv", "stage4a_model_spec_registry.csv",
        "stage4a_fold_reconstruction_audit.csv", "stage4a_preprocessing_audit.csv",
        "stage4a_oos_predictions.csv.gz", "stage4a_joint_oos_predictions.csv.gz",
        "stage4a_metrics_by_year.csv", "stage4a_metrics_pooled_oos.csv", "stage4a_metrics_by_era.csv",
        "stage4a_recent_2024_2026_metrics.csv", "stage4a_yearly_stability.csv",
        "stage4a_calibration_buckets.csv", "stage4a_calibration_summary.csv",
        "stage4a_rule_score_benchmarks.csv",
        "stage4a_top_bucket_lift.csv", "stage4a_joint_metrics.csv",
        "stage4a_joint_calibration_buckets.csv", "stage4a_joint_top_bucket_lift.csv",
        "stage4a_metrics_by_dataset_cohort.csv", "stage4a_metrics_by_setup.csv",
        "stage4a_metrics_by_regime.csv", "stage4a_metrics_by_original_signal.csv",
        "stage4a_model_comparison.csv", "stage4a_research_evidence_classification.csv",
        "stage4a_logistic_coefficient_audit.csv.gz",
    ]
    rows = []
    for name in identity_names:
        left = json.loads((reference_dir / name).read_text(encoding="utf-8"))
        right = json.loads((candidate_dir / name).read_text(encoding="utf-8"))
        left_hash, right_hash = canonical_json_hash(left), canonical_json_hash(right)
        rows.append({"Artifact": name, "Comparison": "canonical JSON", "First Run Hash": left_hash, "Second Run Hash": right_hash, "Status": "PASS" if left_hash == right_hash else "FAIL"})
    for name in data_names:
        left_frame = pd.read_csv(reference_dir / name, low_memory=False)
        right_frame = pd.read_csv(candidate_dir / name, low_memory=False)
        left_hash, right_hash = dataframe_content_hash(left_frame), dataframe_content_hash(right_frame)
        rows.append({"Artifact": name, "Comparison": "logical content", "First Run Hash": left_hash, "Second Run Hash": right_hash, "Status": "PASS" if left_hash == right_hash else "FAIL"})
    determinism = pd.DataFrame(rows)
    write_csv(determinism, reference_dir / "stage4a_determinism_check.csv")
    if not determinism["Status"].eq("PASS").all():
        raise RuntimeError("Second complete official run was not exactly deterministic")
    config = load_config(STAGE_ROOT)
    reference_gate = pd.read_csv(reference_dir / "stage4a_reference_gate.csv")
    feature_registry_output = pd.read_csv(reference_dir / "stage4a_feature_set_registry.csv")
    feature_hash_json = json.loads((reference_dir / "stage4a_feature_set_hashes.json").read_text(encoding="utf-8"))
    feature_hashes = {key.removesuffix("_HASH"): value for key, value in feature_hash_json.items()}
    feature_sets = {name: sorted(group["Feature Name"].tolist()) for name, group in feature_registry_output.groupby("Feature Set")}
    model_hash_json = json.loads((reference_dir / "stage4a_model_spec_hashes.json").read_text(encoding="utf-8"))
    model_hashes = {key: value["MODEL_SPEC_HASH"] for key, value in model_hash_json.items()}
    model_specs = {key: value["specification"] for key, value in model_hash_json.items()}
    fold_audit = pd.read_csv(reference_dir / "stage4a_fold_reconstruction_audit.csv")
    preprocessing_audit = pd.read_csv(reference_dir / "stage4a_preprocessing_audit.csv")
    fit_audit = pd.read_csv(reference_dir / "stage4a_model_fit_audit.csv")
    predictions = pd.read_csv(reference_dir / "stage4a_oos_predictions.csv.gz", low_memory=False)
    joint = pd.read_csv(reference_dir / "stage4a_joint_oos_predictions.csv.gz", low_memory=False)
    recent = pd.read_csv(reference_dir / "stage4a_recent_2024_2026_metrics.csv")
    checks = build_validation_checks(
        STAGE_ROOT, "official", config["evaluation_years"], config, reference_gate,
        feature_sets, feature_registry_output, feature_hashes, model_specs, model_hashes,
        fold_audit, preprocessing_audit, fit_audit, predictions, joint, recent, determinism,
    )
    status = write_validation_artifacts(checks, reference_dir)
    _write_delivery_report(reference_dir, status)
    write_json(_output_manifest(reference_dir), reference_dir / "stage4a_output_manifest.json")
    if status == "FAIL":
        raise RuntimeError("Final validation failed after deterministic rerun")
    print(f"STAGE4A_DETERMINISM_COMPLETE status={status} checks={len(determinism)}", flush=True)


def finalize_output(output_dir: Path) -> None:
    write_json(_output_manifest(output_dir), output_dir / "stage4a_output_manifest.json")
    print(f"STAGE4A_OUTPUT_MANIFEST_FINALIZED artifacts={len(_output_manifest(output_dir)['artifacts'])}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["sanity", "official"])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--compare-reference", type=Path)
    parser.add_argument("--compare-candidate", type=Path)
    parser.add_argument("--finalize-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.compare_reference and args.compare_candidate:
        compare_runs(args.compare_reference.resolve(), args.compare_candidate.resolve())
    elif args.finalize_output:
        finalize_output(args.finalize_output.resolve())
    elif args.mode and args.output_dir:
        run_experiment(args.mode, args.output_dir.resolve())
    else:
        raise SystemExit("Provide --mode and --output-dir, --compare-reference/--compare-candidate, or --finalize-output")


if __name__ == "__main__":
    main()
