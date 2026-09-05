"""Stage 4A.1 executable-cohort robustness validation runner."""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn

HERE = Path(__file__).resolve().parent
STAGE_ROOT = HERE.parent
REPO_ROOT = STAGE_ROOT.parent
if str(STAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(STAGE_ROOT))

from stage4a1.bootstrap import paired_comparison, run_bootstrap, summarize_bootstrap
from stage4a1.data_contract import build_reference_gate, load_config, load_opportunity
from stage4a1.diagnostics import dataset_cohort_comparison, evidence_classification, original_signal_diagnostics
from stage4a1.folds import fold_audit, masks
from stage4a1.hashing import canonical_json_hash, dataframe_content_hash, sha256_file, source_package_manifest, write_csv, write_csv_gz, write_json
from stage4a1.metrics import calibration, metric_tables, rank_agreement, ranking_metrics, yearly_stability
from stage4a1.metric_audit import consistency_audits
from stage4a1.models import MODEL_ORDER, contracts, fit_predict, joint_predictions
from stage4a1.validation import build_checks, write_validation


BEHAVIOR_FILES = [
    "config/stage4a1_config.json", "stage4a1/__init__.py", "stage4a1/Stock_Alert_Stage4A1_Executable_Cohort.py",
    "stage4a1/data_contract.py", "stage4a1/folds.py", "stage4a1/models.py", "stage4a1/metrics.py",
    "stage4a1/bootstrap.py", "stage4a1/diagnostics.py", "stage4a1/validation.py", "stage4a1/hashing.py",
    "tests/run_stage4a1_tests.py", "tests/test_ranking_regression.py", "stage4a1/ranking.py", "stage4a1/metric_audit.py", "stage4a1/correction_review.py",
]


def environment_report() -> dict[str, Any]:
    import joblib, scipy, threadpoolctl
    return {"python": sys.version.split()[0], "python_implementation": platform.python_implementation(), "platform": platform.platform(),
        "packages": {"numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__, "scikit-learn": sklearn.__version__, "joblib": joblib.__version__, "threadpoolctl": threadpoolctl.__version__},
        "network_data_downloaded": False, "random_seed": 42, "model_training_packages_used": ["scikit-learn"]}


def experiment_identity(config: dict[str, Any], package_hash: str, config_hash: str, feature_hashes: dict[str, str], model_hashes: dict[str, str], source_audit: dict[str, Any], mode: str) -> dict[str, Any]:
    bootstrap_spec = config["bootstrap"]
    seed = {"stage4a_frozen_commit": config["stage4a"]["commit"], "stage4a_experiment_id": config["stage4a"]["experiment_id"],
        "stage4a_oos_prediction_hash": config["stage4a"]["oos_prediction_logical_hash"], "stage4a_joint_prediction_hash": config["stage4a"]["joint_prediction_logical_hash"],
        "stage3_1_commit": config["stage3_1"]["commit"], "stage3_1_trade_opportunity_hash": config["stage3_1"]["trade_opportunity_content_hash"],
        "stage4a1_package_hash": package_hash, "stage4a1_config_hash": config_hash, "feature_set_hashes": feature_hashes,
        "model_spec_hashes": model_hashes, "bootstrap_specification": bootstrap_spec, "evaluation_start": config["experiment_start"], "evaluation_end": config["experiment_end"]}
    digest = canonical_json_hash(seed)
    return {"EXPERIMENT_ID": f"S4A1_20160101_20260828_{digest[:12]}", "STAGE4A1_CODE_PACKAGE_HASH": package_hash,
        "STAGE4A1_CONFIG_HASH": config_hash, "STAGE4A_FROZEN_TAG_COMMIT": config["stage4a"]["commit"], "STAGE4A_EXPERIMENT_ID": config["stage4a"]["experiment_id"],
        "STAGE4A_CODE_PACKAGE_HASH": config["stage4a"]["package_hash"], "STAGE4A_OOS_PREDICTION_LOGICAL_HASH": config["stage4a"]["oos_prediction_logical_hash"],
        "STAGE4A_JOINT_PREDICTION_LOGICAL_HASH": config["stage4a"]["joint_prediction_logical_hash"], "STAGE3_1_FROZEN_TAG_COMMIT": config["stage3_1"]["commit"],
        "STAGE3_1_EXPERIMENT_ID": config["stage3_1"]["experiment_id"], "STAGE3_1_PACKAGE_HASH": config["stage3_1"]["package_hash"],
        "STAGE3_1_TRADE_OPPORTUNITY_LOGICAL_HASH": source_audit["trade_opportunity_logical_hash"], "FEATURE_SET_HASHES": feature_hashes,
        "MODEL_SPEC_HASHES": model_hashes, "BOOTSTRAP_SPECIFICATION": bootstrap_spec, "EVALUATION_START": config["experiment_start"],
        "EVALUATION_END": config["experiment_end"], "RUN_MODE": mode, "TRANSFER_MODELS_RETRAINED": False, "PRIMARY_ONLY_MODELS_TRAINED": True,
        "ML_TRADING_BACKTEST_RUN": False, "FEATURE_SELECTION_PERFORMED": False, "HYPERPARAMETER_SEARCH_PERFORMED": False,
        "PROBABILITY_THRESHOLD_OPTIMIZED": False, "CLASS_REBALANCING_PERFORMED": False}


def load_transfer(config: dict[str, Any], years: list[int], tickers: list[str] | None, identity: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    direct_all = pd.read_csv(REPO_ROOT / "Stage 4A" / "results" / "stage4a_oos_predictions.csv.gz", low_memory=False)
    joint_all = pd.read_csv(REPO_ROOT / "Stage 4A" / "results" / "stage4a_joint_oos_predictions.csv.gz", low_memory=False)
    for frame in [direct_all, joint_all]:
        frame["Signal Date"] = pd.to_datetime(frame["Signal Date"]).dt.normalize()
    selection = direct_all["Dataset Cohort"].eq(config["primary_cohort"]) & direct_all["Evaluation Year"].isin(years)
    joint_selection = joint_all["Dataset Cohort"].eq(config["primary_cohort"]) & joint_all["Evaluation Year"].isin(years)
    if tickers:
        selection &= direct_all["Ticker"].isin(tickers); joint_selection &= joint_all["Ticker"].isin(tickers)
    direct = direct_all.loc[selection].copy(); joint = joint_all.loc[joint_selection].copy()
    for frame in [direct, joint]:
        frame.insert(0, "Mode", "TRANSFER"); frame["Stage 4A.1 Experiment ID"] = identity["EXPERIMENT_ID"]
    return direct.reset_index(drop=True), joint.reset_index(drop=True), direct_all, joint_all


def primary_predictions(opportunity: pd.DataFrame, config: dict[str, Any], years: list[int], tickers: list[str] | None,
        feature_sets: dict[str, list[str]], type_maps: dict[str, dict[str, list[str]]], feature_hashes: dict[str, str], model_hashes: dict[str, str], identity: dict[str, Any]):
    rows, fits, preprocessors = [], [], []
    metadata = ["Signal ID", "Ticker", "Signal Date", "Dataset Cohort", "Original Signal", "Setup", "Market Regime", "Actionability Score", "Technical Score"]
    for target, spec in config["targets"].items():
        for year in years:
            item = masks(opportunity, target, spec, year, config["primary_cohort"])
            train_mask, eval_mask, label_mask = item["training"].copy(), item["evaluation_score"].copy(), item["evaluation_label"].copy()
            if tickers:
                ticker_mask = opportunity["Ticker"].isin(tickers); train_mask &= ticker_mask; eval_mask &= ticker_mask; label_mask &= ticker_mask
            train = opportunity.loc[train_mask].copy(); evaluation = opportunity.loc[eval_mask].copy(); labels = label_mask.loc[evaluation.index]
            if train.empty or evaluation.empty or train[target].nunique() != 2:
                raise RuntimeError(f"Insufficient PRIMARY_ONLY sanity fold {target} {year}: train={len(train)} eval={len(evaluation)} classes={train[target].nunique()}")
            y_train = train[target].astype(int); prevalence = float(y_train.mean())
            for variant in MODEL_ORDER:
                feature_set = config["model_variants"][variant]["feature_set"]
                names = [] if feature_set == "NONE" else feature_sets[feature_set]
                type_map = {"numeric": [], "categorical": []} if feature_set == "NONE" else type_maps[feature_set]
                probability, fit_row, preprocessing_row, _ = fit_predict(REPO_ROOT, variant, target, year, feature_set, names, type_map, train, evaluation, y_train, config)
                fit_row["Training Mode"] = "PRIMARY_ONLY"; fits.append(fit_row)
                if preprocessing_row is not None:
                    preprocessing_row["Training Mode"] = "PRIMARY_ONLY"; preprocessors.append(preprocessing_row)
                output = evaluation[metadata].copy(); output.insert(0, "Mode", "PRIMARY_ONLY")
                output["Evaluation Year"] = year; output["Target"] = target; output["Model Variant"] = variant; output["Feature Set"] = feature_set
                output["Model Spec Hash"] = model_hashes[variant]; output["Feature Set Hash"] = feature_hashes.get(feature_set, "NONE")
                output["Stage 3.1 Experiment ID"] = config["stage3_1"]["experiment_id"]; output["Stage 4A Experiment ID"] = config["stage4a"]["experiment_id"]
                output["Stage 4A.1 Experiment ID"] = identity["EXPERIMENT_ID"]; output["Training Cutoff Date"] = item["evaluation_start"]
                output["Predicted Probability"] = probability; output["Actual Label"] = np.where(labels.to_numpy(), evaluation[target].astype(float), np.nan)
                output["Label Status"] = evaluation[spec["status"]].astype("string").to_numpy(); output["Label Available Date"] = evaluation[spec["available_date"]].to_numpy()
                output["Training Rows"] = len(train); output["Training Positive Count"] = int(y_train.sum()); output["Training Prevalence"] = prevalence; output["Training Prior"] = prevalence
                rows.append(output)
    prediction = pd.concat(rows, ignore_index=True).sort_values(["Target", "Evaluation Year", "Model Variant", "Signal ID"], kind="mergesort").reset_index(drop=True)
    return prediction, pd.DataFrame(fits), pd.DataFrame(preprocessors)


def build_primary_joint(primary: pd.DataFrame, opportunity: pd.DataFrame, identity: dict[str, Any]) -> pd.DataFrame:
    core = primary.drop(columns=["Mode", "Stage 4A.1 Experiment ID"])
    joint = joint_predictions(REPO_ROOT, core, opportunity)
    joint.insert(0, "Mode", "PRIMARY_ONLY"); joint["Stage 4A.1 Experiment ID"] = identity["EXPERIMENT_ID"]
    return joint


def sample_size_audit(folds: pd.DataFrame) -> pd.DataFrame:
    result = folds[["Training Mode", "Target", "Evaluation Year", "Training Rows", "Training Positive Rows", "Training Negative Rows", "Evaluation Candidate Rows", "Evaluation Label-Available Rows"]].copy()
    result["Evaluation Period Label"] = np.where(result["Evaluation Year"].eq(2026), "2026 PARTIAL THROUGH 2026-08-28", result["Evaluation Year"].astype(str))
    result["Sample-Size Warning"] = result["Evaluation Label-Available Rows"].lt(30)
    return result


def output_manifest(output_dir: Path) -> dict[str, Any]:
    artifacts = []
    for path in sorted(p for p in output_dir.iterdir() if p.is_file() and p.name != "stage4a1_output_manifest.json"):
        row = {"artifact": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        if path.suffix == ".csv" or path.name.endswith(".csv.gz"):
            try:
                frame = pd.read_csv(path, low_memory=False); row |= {"row_count": len(frame), "column_count": len(frame.columns), "logical_content_hash": dataframe_content_hash(frame)}
            except pd.errors.EmptyDataError:
                row |= {"row_count": 0, "column_count": 0, "logical_content_hash": canonical_json_hash([])}
        artifacts.append(row)
    return {"canonical_serialization": {"floats": "%.12g", "line_ending": "LF", "gzip_mtime": 0}, "artifacts": artifacts}


def _table(frame: pd.DataFrame, columns: list[str]) -> str:
    selected = frame.loc[:, columns].copy()
    for column in selected:
        if pd.api.types.is_float_dtype(selected[column]): selected[column] = selected[column].map(lambda x: "" if pd.isna(x) else f"{x:.6f}")
    return "| " + " | ".join(columns) + " |\n| " + " | ".join(["---"] * len(columns)) + " |\n" + "\n".join("| " + " | ".join(map(str, row)) + " |" for row in selected.itertuples(index=False, name=None))


def delivery_report(output_dir: Path, status: str) -> None:
    identity = json.loads((output_dir / "stage4a1_experiment_identity.json").read_text())
    metrics = pd.read_csv(output_dir / "stage4a1_metrics_pooled.csv")
    paired = pd.read_csv(output_dir / "stage4a1_transfer_vs_primary_only_paired.csv")
    evidence = pd.read_csv(output_dir / "stage4a1_research_evidence_classification.csv")
    sample = pd.read_csv(output_dir / "stage4a1_sample_size_audit.csv")
    recent = pd.read_csv(output_dir / "stage4a1_recent_2024_2026_metrics.csv")
    key_targets = metrics["Target"].isin(["T1_BEFORE_STOP_63", "T2_BEFORE_STOP_63"])
    key_models = metrics["Model Variant"].isin(["LOGIT_RULE", "LOGIT_RAW", "LOGIT_FULL", "RF_FULL"])
    metric_view = metrics.loc[key_targets & key_models]
    paired_view = paired.loc[paired["Scope"].eq("POOLED_2016_2026") & paired["Target"].isin(["T1_BEFORE_STOP_63", "T2_BEFORE_STOP_63"])]
    robust_count = int(evidence["Research Evidence Classification"].eq("ROBUST POSITIVE HISTORICAL SIGNAL").sum())
    declarations = """STAGE 2.2.2 FINAL MODIFIED: NO
STAGE 2B MODIFIED: NO
STAGE 2B.1 MODIFIED: NO
STAGE 3 MODIFIED: NO
STAGE 3.1 MODIFIED: NO
STAGE 4A MODIFIED: NO
STAGE 4A FROZEN TAG VERIFIED: YES
STAGE 1 SIGNAL RULES CHANGED: NO
ENTRY RULES CHANGED: NO
D1 MANAGEMENT RULES CHANGED: NO

BASELINE_PRIMARY DEFINITION CHANGED: NO

NEW FEATURES ADDED: NO
FEATURE SELECTION PERFORMED: NO
HYPERPARAMETER SEARCH PERFORMED: NO
PROBABILITY THRESHOLD OPTIMIZED: NO
CLASS REBALANCING PERFORMED: NO

TRANSFER MODELS RETRAINED: NO
PRIMARY_ONLY MODELS TRAINED: YES
CHRONOLOGICAL WALK_FORWARD USED: YES
LABEL_AVAILABILITY GATING USED: YES
RANDOM TRAIN_TEST SPLIT USED: NO

OVERLAP_AWARE_BLOCK_BOOTSTRAP USED: YES
PRIMARY_BOOTSTRAP_BLOCK_LENGTH: 63
BOOTSTRAP_REPLICATES: 2000
BOOTSTRAP_SEED: 42

ML TRADING BACKTEST RUN: NO
MODEL USED FOR LIVE TRADING: NO
PRODUCTION MODEL SELECTED: NO
STAGE 4B IMPLEMENTED: NO
STAGE 5 IMPLEMENTED: NO"""
    ready = status in {"PASS", "PASS WITH WARNINGS"} and (output_dir / "stage4a1_determinism_check.csv").exists()
    text = f"""# Stage 4A.1 Delivery Report

## A. Engineering status

**{status}**. READY FOR INDEPENDENT STAGE 4A.1 AUDIT: **{'YES' if ready else 'NO'}**.

## B. Experiment identity and hashes

- Experiment ID: `{identity['EXPERIMENT_ID']}`
- Stage 4A.1 package hash: `{identity['STAGE4A1_CODE_PACKAGE_HASH']}`
- Frozen Stage 4A commit: `{identity['STAGE4A_FROZEN_TAG_COMMIT']}`
- Frozen Stage 4A prediction hashes: `{identity['STAGE4A_OOS_PREDICTION_LOGICAL_HASH']}`, `{identity['STAGE4A_JOINT_PREDICTION_LOGICAL_HASH']}`
- Frozen Stage 3.1 trade-opportunity hash: `{identity['STAGE3_1_TRADE_OPPORTUNITY_LOGICAL_HASH']}`

## C. BASELINE_PRIMARY sample sizes

The frozen cohort contains 1,088 opportunities. Official labeled OOS row counts by target are retained in the sample-size audit. 2026 is partial through 2026-08-28, and small yearly samples are explicitly flagged.

{_table(sample.groupby(['Training Mode','Target'], as_index=False).agg(**{'Training Rows':('Training Rows','max'), 'Evaluation Label-Available Rows':('Evaluation Label-Available Rows','sum')}), ['Training Mode','Target','Training Rows','Evaluation Label-Available Rows'])}

## D–E. Frozen TRANSFER and PRIMARY_ONLY performance

{_table(metric_view, ['Mode','Target','Model Variant','Rows','ROC AUC','Average Precision','Brier Skill Score vs Training Prior'])}

## F. Paired TRANSFER versus PRIMARY_ONLY deltas

Positive AUC/Brier-skill/top-20-lift deltas favor PRIMARY_ONLY; negative Brier-score deltas favor PRIMARY_ONLY. No delta was used for automated model selection.

{_table(paired_view, ['Target','Model Variant','Delta ROC AUC','Delta ROC AUC 2.5%','Delta ROC AUC 97.5%','Delta Brier Skill Score vs Training Prior','Delta Top 20% Lift'])}

## G–H. Date-block bootstrap uncertainty

The primary analysis used 2,000 paired replicates of contiguous 63-unique-Signal-Date blocks with seed 42. All same-date rows remained grouped and both modes used identical samples. Fixed 21-date and 126-date sensitivity analyses were also retained; no block length was selected after viewing results. Invalid single-class AUC replicates are excluded and counted. Conclusions use the 63-date analysis.

## I–J. Annual and recent stability

All years 2016–2026 are reported without suppression; 2026 is partial through 2026-08-28. Recent 2024–2026 results are descriptive and were not used for tuning.

{_table(recent.loc[recent['Target'].isin(['T1_BEFORE_STOP_63','T2_BEFORE_STOP_63']) & recent['Model Variant'].isin(['LOGIT_FULL','LOGIT_RAW','LOGIT_RULE','RF_FULL'])], ['Mode','Target','Model Variant','Rows','ROC AUC','Brier Skill Score vs Training Prior'])}

## K. BASELINE_PRIMARY versus RESEARCH_EXTENDED

The cohort comparison uses only frozen Stage 4A TRANSFER predictions and does not refit retrospective subgroup models. It makes visible whether broader-population separation explains the original pooled result.

## L–M. Ranking lift and calibration

Fixed top-10%, top-20%, and bottom-20% diagnostics use probability descending then Signal ID ascending. Calibration uses fixed 0.1-wide buckets without recalibration. Probabilities are research outputs and are not validated for user-facing confidence.

## N. Evidence classification

{_table(evidence, ['Mode','Target','Model Variant','Pooled ROC AUC','Pooled AUC 63-Date Lower 95%','Pooled Brier Skill','Recent 2024-2026 ROC AUC','Years AUC > 0.50','Research Evidence Classification'])}

Models meeting the pre-registered robust-positive definition: **{robust_count}**. This count is descriptive; no production model has been selected.

## O–R. Research limitations and prohibitions

This experiment is historical pseudo-OOS research.
Stage 4A results were already known before Stage 4A.1 was designed.
Therefore Stage 4A.1 is a robustness investigation, not a new untouched holdout.

No production ML model has been selected.

No ML trading backtest was performed.

Probabilities are not validated as user-facing confidence.

## Required declarations

```text
{declarations}

READY FOR INDEPENDENT STAGE 4A.1 AUDIT: {'YES' if ready else 'NO'}
```
"""
    runtime_path = output_dir / "stage4a1_runtime_determinism_audit.json"
    if runtime_path.exists():
        runtime = json.loads(runtime_path.read_text())
        text += "\n## Runtime and behavioral determinism\n\n"
        text += f"RAW RUNTIME FIELD DIFFERENCES: {runtime['RAW RUNTIME FIELD DIFFERENCES']}\n\nBEHAVIORAL LOGICAL DIFFERENCES: {runtime['BEHAVIORAL LOGICAL DIFFERENCES']}\n\n"
        text += "Only Fit Seconds and Prediction Seconds in the model-fit audit are excluded. All other fields, including warnings, are compared.\n"
    text += "\n## Metric correctness contract\n\nLog Loss uses sklearn.metrics.log_loss(actual, np.clip(probability, 1e-15, 1.0 - 1e-15), labels=[0, 1]) through one shared fixed_log_loss helper. Clipping is metric-local; saved probabilities and labels are unchanged. Identity Log Loss and ranking comparisons are exact; other vectorized metrics allow only 1e-14 absolute machine-precision error.\n"
    for filename in ["stage4a1_point_bootstrap_metric_consistency_audit.csv", "stage4a1_ranking_tie_handling_audit.csv", "stage4a1_unit_test_results.csv"]:
        if (output_dir / filename).exists():
            audit = pd.read_csv(output_dir / filename)
            text += f"\n{filename}: {audit['Status'].value_counts().to_dict()}\n"
    comparison_path = output_dir / "stage4a1_correctness_fix_comparison.csv"
    if comparison_path.exists():
        comparison = pd.read_csv(comparison_path)
        text += "\n## Pre-fix provisional comparison\n\nThe following table includes every changed column. Unlisted shared columns are unchanged; the experiment ID is deliberately different. Predictions are compared excluding only Stage 4A.1 Experiment ID. Bottom-bucket changes are attributable to corrected canonical-tail tie handling; Log Loss changes are attributable to the shared frozen clipping implementation. Neither fix alters model fitting, predictions, labels, AUC, Brier, or evidence criteria.\n\n"
        text += _table(comparison.loc[comparison['Changed Cells'].gt(0)], ['Artifact','Column','Changed Cells','Maximum Absolute Difference']) + "\n"
    extra_tables = [
        ("Bootstrap AUC intervals and fixed sensitivities", "stage4a1_bootstrap_summary.csv", ['Block Length','Mode','Target','Model Variant','Scope','Metric','Valid Replicates','2.5%','97.5%']),
        ("Yearly stability", "stage4a1_yearly_stability.csv", None),
        ("Frozen cohort comparison", "stage4a1_dataset_cohort_comparison.csv", None),
        ("Ranking diagnostics", "stage4a1_ranking_lift.csv", None),
        ("Calibration summary", "stage4a1_calibration_summary.csv", None),
    ]
    for title, filename, columns in extra_tables:
        table = pd.read_csv(output_dir / filename)
        if filename == "stage4a1_bootstrap_summary.csv":
            table = table.loc[table['Metric'].eq('ROC AUC') & table['Scope'].eq('POOLED_2016_2026')]
        elif filename == "stage4a1_ranking_lift.csv":
            table = table.loc[table['Scope'].eq('POOLED_2016_2026')]
        text += "\n## " + title + "\n\n" + _table(table, columns or list(table.columns)) + "\n"
    # Keep the requested declarations at the very end, after audit supplements.
    declaration_start = text.index("## Required declarations")
    declaration_end = text.index("```", text.index("```text", declaration_start) + 7) + 3
    text = text[:declaration_start] + text[declaration_end:] + "\n" + text[declaration_start:declaration_end] + "\n"
    (STAGE_ROOT / "Stage4A1_Delivery_Report.md").write_text(text, encoding="utf-8", newline="\n")


def run(mode: str, output_dir: Path) -> None:
    config = load_config(STAGE_ROOT); years = config["sanity_evaluation_years"] if mode == "sanity" else config["evaluation_years"]
    tickers = config["sanity_tickers"] if mode == "sanity" else None; replicates = config["bootstrap"]["sanity_replicates"] if mode == "sanity" else config["bootstrap"]["replicates"]
    output_dir.mkdir(parents=True, exist_ok=True)
    reference, source_audit = build_reference_gate(REPO_ROOT, STAGE_ROOT, config)
    opportunity = load_opportunity(REPO_ROOT)
    feature_sets, feature_registry, feature_hashes, type_maps, model_registry, model_hashes, model_specs = contracts(REPO_ROOT, config)
    package = source_package_manifest(STAGE_ROOT, BEHAVIOR_FILES); config_hash = sha256_file(STAGE_ROOT / "config" / "stage4a1_config.json")
    identity = experiment_identity(config, package["package_hash"], config_hash, feature_hashes, model_hashes, source_audit, mode)
    transfer, transfer_joint, direct_all, joint_all = load_transfer(config, years, tickers, identity)
    primary, fit_audit, preprocessing = primary_predictions(opportunity, config, years, tickers, feature_sets, type_maps, feature_hashes, model_hashes, identity)
    primary_joint = build_primary_joint(primary, opportunity, identity)
    folds = fold_audit(opportunity, config, years)
    all_predictions = pd.concat([transfer, primary, transfer_joint, primary_joint], ignore_index=True, sort=False)
    consistency, tie_audit = consistency_audits(all_predictions)
    write_csv(consistency, output_dir / "stage4a1_point_bootstrap_metric_consistency_audit.csv")
    write_csv(tie_audit, output_dir / "stage4a1_ranking_tie_handling_audit.csv")
    if not consistency["Status"].eq("PASS").all() or not tie_audit["Status"].eq("PASS").all():
        raise RuntimeError("Behavioral blocker: point/bootstrap metric parity failed")
    pooled, yearly, era, recent = metric_tables(all_predictions); stability = yearly_stability(yearly); ranking = ranking_metrics(all_predictions); buckets, calibration_summary = calibration(all_predictions)
    point_all = pd.concat([pooled, era], ignore_index=True)
    raw_by_block = {}
    for block in [63, 21, 126]:
        print(f"BOOTSTRAP_START mode={mode} block={block} replicates={replicates}", flush=True)
        raw_by_block[block] = run_bootstrap(all_predictions, block, replicates, config["bootstrap"]["random_seed"])
        print(f"BOOTSTRAP_COMPLETE mode={mode} block={block}", flush=True)
    bootstrap_summary = pd.concat([summarize_bootstrap(raw_by_block[block]) for block in [63, 21, 126]], ignore_index=True)
    paired = paired_comparison(raw_by_block[63], point_all, ranking)
    agreement = rank_agreement(all_predictions)
    frozen_all = pd.concat([direct_all, joint_all], ignore_index=True, sort=False)
    cohort_comparison = dataset_cohort_comparison(frozen_all)
    original_signal = original_signal_diagnostics(transfer)
    evidence = evidence_classification(point_all, yearly, bootstrap_summary, config["bootstrap"]["sanity_replicates"] if mode == "sanity" else config["bootstrap"]["minimum_valid_pooled_auc_replicates"])

    write_json(identity, output_dir / "stage4a1_experiment_identity.json"); write_json({"stage4a1": package, "frozen_inputs": source_audit}, output_dir / "stage4a1_source_manifest.json")
    write_json(environment_report(), output_dir / "stage4a1_environment_report.json"); write_csv(reference, output_dir / "stage4a1_reference_gate.csv")
    write_csv(sample_size_audit(folds), output_dir / "stage4a1_sample_size_audit.csv"); write_csv(folds, output_dir / "stage4a1_fold_reconstruction_audit.csv")
    write_csv(preprocessing, output_dir / "stage4a1_primary_only_preprocessing_audit.csv"); write_csv(fit_audit, output_dir / "stage4a1_primary_only_model_fit_audit.csv")
    write_csv_gz(primary, output_dir / "stage4a1_primary_only_oos_predictions.csv.gz"); write_csv_gz(primary_joint, output_dir / "stage4a1_primary_only_joint_oos_predictions.csv.gz")
    write_csv_gz(transfer, output_dir / "stage4a1_transfer_baseline_primary_predictions.csv.gz"); write_csv_gz(transfer_joint, output_dir / "stage4a1_transfer_baseline_primary_joint_predictions.csv.gz")
    write_csv(pooled, output_dir / "stage4a1_metrics_pooled.csv"); write_csv(yearly, output_dir / "stage4a1_metrics_by_year.csv"); write_csv(era, output_dir / "stage4a1_metrics_by_era.csv")
    write_csv(recent, output_dir / "stage4a1_recent_2024_2026_metrics.csv"); write_csv(stability, output_dir / "stage4a1_yearly_stability.csv"); write_csv(ranking, output_dir / "stage4a1_ranking_lift.csv")
    write_csv(buckets, output_dir / "stage4a1_calibration_buckets.csv"); write_csv(calibration_summary, output_dir / "stage4a1_calibration_summary.csv")
    write_csv(paired, output_dir / "stage4a1_transfer_vs_primary_only_paired.csv"); write_csv(agreement, output_dir / "stage4a1_rank_agreement.csv")
    write_csv_gz(raw_by_block[63], output_dir / "stage4a1_block_bootstrap_63.csv.gz"); write_csv_gz(raw_by_block[21], output_dir / "stage4a1_block_bootstrap_21_sensitivity.csv.gz"); write_csv_gz(raw_by_block[126], output_dir / "stage4a1_block_bootstrap_126_sensitivity.csv.gz")
    write_csv(bootstrap_summary, output_dir / "stage4a1_bootstrap_summary.csv"); write_csv(cohort_comparison, output_dir / "stage4a1_dataset_cohort_comparison.csv")
    write_csv(original_signal, output_dir / "stage4a1_original_signal_diagnostics.csv"); write_csv(evidence, output_dir / "stage4a1_research_evidence_classification.csv")
    checks = build_checks(STAGE_ROOT, mode, reference, feature_sets, feature_hashes, model_specs, model_hashes, folds, preprocessing, fit_audit, transfer, primary, transfer_joint, primary_joint, bootstrap_summary, evidence, config, None)
    status = write_validation(checks, output_dir); write_json(output_manifest(output_dir), output_dir / "stage4a1_output_manifest.json")
    failed = checks["Status"].eq("FAIL")
    allowed_pending = checks["Check"].eq("Second complete official run exact")
    if (failed & ~allowed_pending).any(): raise RuntimeError(f"Stage 4A.1 {mode} validation failed")
    print(f"STAGE4A1_RUN_COMPLETE mode={mode} experiment={identity['EXPERIMENT_ID']} direct_rows={len(primary)} joint_rows={len(primary_joint)} bootstrap_rows={sum(map(len,raw_by_block.values()))} status={status}", flush=True)


def compare_runs(reference_dir: Path, candidate_dir: Path) -> None:
    names = ["stage4a1_experiment_identity.json", "stage4a1_reference_gate.csv", "stage4a1_sample_size_audit.csv", "stage4a1_fold_reconstruction_audit.csv", "stage4a1_primary_only_preprocessing_audit.csv", "stage4a1_primary_only_model_fit_audit.csv", "stage4a1_primary_only_oos_predictions.csv.gz", "stage4a1_primary_only_joint_oos_predictions.csv.gz", "stage4a1_transfer_baseline_primary_predictions.csv.gz", "stage4a1_transfer_baseline_primary_joint_predictions.csv.gz", "stage4a1_metrics_pooled.csv", "stage4a1_metrics_by_year.csv", "stage4a1_metrics_by_era.csv", "stage4a1_recent_2024_2026_metrics.csv", "stage4a1_yearly_stability.csv", "stage4a1_ranking_lift.csv", "stage4a1_calibration_buckets.csv", "stage4a1_calibration_summary.csv", "stage4a1_transfer_vs_primary_only_paired.csv", "stage4a1_rank_agreement.csv", "stage4a1_block_bootstrap_63.csv.gz", "stage4a1_block_bootstrap_21_sensitivity.csv.gz", "stage4a1_block_bootstrap_126_sensitivity.csv.gz", "stage4a1_bootstrap_summary.csv", "stage4a1_dataset_cohort_comparison.csv", "stage4a1_original_signal_diagnostics.csv", "stage4a1_research_evidence_classification.csv"]
    names += ["stage4a1_point_bootstrap_metric_consistency_audit.csv", "stage4a1_ranking_tie_handling_audit.csv", "stage4a1_source_manifest.json", "stage4a1_environment_report.json"]
    rows = []
    runtime_differences = 0
    for name in names:
        if name.endswith(".json"):
            left = canonical_json_hash(json.loads((reference_dir / name).read_text())); right = canonical_json_hash(json.loads((candidate_dir / name).read_text())); kind = "canonical JSON"
        else:
            left_frame = pd.read_csv(reference_dir / name, low_memory=False)
            right_frame = pd.read_csv(candidate_dir / name, low_memory=False)
            if name == "stage4a1_primary_only_model_fit_audit.csv":
                runtime_fields = ["Fit Seconds", "Prediction Seconds"]
                for field in runtime_fields:
                    runtime_differences += int((~(left_frame[field].eq(right_frame[field]) | (left_frame[field].isna() & right_frame[field].isna()))).sum())
                left_frame = left_frame.drop(columns=runtime_fields)
                right_frame = right_frame.drop(columns=runtime_fields)
            left = dataframe_content_hash(left_frame); right = dataframe_content_hash(right_frame); kind = "logical content"
        rows.append({"Artifact": name, "Comparison": kind, "First Run Hash": left, "Second Run Hash": right, "Status": "PASS" if left == right else "FAIL"})
    determinism = pd.DataFrame(rows); write_csv(determinism, reference_dir / "stage4a1_determinism_check.csv")
    write_json({"Excluded Runtime Fields": {"stage4a1_primary_only_model_fit_audit.csv": ["Fit Seconds", "Prediction Seconds"]},
        "RAW RUNTIME FIELD DIFFERENCES": runtime_differences,
        "BEHAVIORAL LOGICAL DIFFERENCES": int(determinism["Status"].eq("FAIL").sum()),
        "Raw differences limited to timing": bool(determinism["Status"].eq("PASS").all())}, reference_dir / "stage4a1_runtime_determinism_audit.json")
    if not determinism["Status"].eq("PASS").all(): raise RuntimeError("Stage 4A.1 determinism failed")
    config = load_config(STAGE_ROOT); reference = pd.read_csv(reference_dir / "stage4a1_reference_gate.csv"); feature_sets, _, feature_hashes, _, _, model_hashes, model_specs = contracts(REPO_ROOT, config)
    checks = build_checks(STAGE_ROOT, "official", reference, feature_sets, feature_hashes, model_specs, model_hashes,
        pd.read_csv(reference_dir / "stage4a1_fold_reconstruction_audit.csv"), pd.read_csv(reference_dir / "stage4a1_primary_only_preprocessing_audit.csv"), pd.read_csv(reference_dir / "stage4a1_primary_only_model_fit_audit.csv"),
        pd.read_csv(reference_dir / "stage4a1_transfer_baseline_primary_predictions.csv.gz", low_memory=False), pd.read_csv(reference_dir / "stage4a1_primary_only_oos_predictions.csv.gz", low_memory=False),
        pd.read_csv(reference_dir / "stage4a1_transfer_baseline_primary_joint_predictions.csv.gz", low_memory=False), pd.read_csv(reference_dir / "stage4a1_primary_only_joint_oos_predictions.csv.gz", low_memory=False),
        pd.read_csv(reference_dir / "stage4a1_bootstrap_summary.csv"), pd.read_csv(reference_dir / "stage4a1_research_evidence_classification.csv"), config, determinism)
    status = write_validation(checks, reference_dir); delivery_report(reference_dir, status); write_json(output_manifest(reference_dir), reference_dir / "stage4a1_output_manifest.json")
    if status == "FAIL": raise RuntimeError("Final Stage 4A.1 validation failed")
    print(f"STAGE4A1_DETERMINISM_COMPLETE status={status} checks={len(determinism)}", flush=True)


def finalize(output_dir: Path) -> None:
    write_json(output_manifest(output_dir), output_dir / "stage4a1_output_manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--mode", choices=["sanity", "official"]); parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--compare-reference", type=Path); parser.add_argument("--compare-candidate", type=Path); parser.add_argument("--finalize-output", type=Path); args = parser.parse_args()
    if args.compare_reference and args.compare_candidate: compare_runs(args.compare_reference.resolve(), args.compare_candidate.resolve())
    elif args.finalize_output: finalize(args.finalize_output.resolve())
    elif args.mode and args.output_dir: run(args.mode, args.output_dir.resolve())
    else: raise SystemExit("Provide run, compare, or finalize arguments")


if __name__ == "__main__":
    main()
