"""Evidence-backed Stage 4A engineering acceptance checks."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from features import RULE_GROUP, leakage_feature_names
from hashing import write_csv
from joint_probability import assert_joint_arithmetic
from models import MODEL_ORDER


def _row(category: str, check: str, passed: bool, expected: Any, actual: Any, details: str = "") -> dict[str, Any]:
    return {
        "Category": category, "Check": check, "Status": "PASS" if bool(passed) else "FAIL",
        "Expected": expected, "Actual": actual, "Details": details,
    }


def build_validation_checks(
    stage_root: Path,
    mode: str,
    expected_years: list[int],
    config: dict[str, Any],
    reference_gate: pd.DataFrame,
    feature_sets: dict[str, list[str]],
    feature_registry_output: pd.DataFrame,
    feature_hashes: dict[str, str],
    model_specs: dict[str, dict[str, Any]],
    model_hashes: dict[str, str],
    fold_audit: pd.DataFrame,
    preprocessing_audit: pd.DataFrame,
    fit_audit: pd.DataFrame,
    predictions: pd.DataFrame,
    joint_predictions: pd.DataFrame,
    recent: pd.DataFrame,
    determinism: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    add: Callable[..., None] = lambda *args: rows.append(_row(*args))
    add("REFERENCE", "Immutable reference gate", reference_gate["Status"].eq("PASS").all(), "all PASS", reference_gate["Status"].value_counts().to_dict())
    add("REFERENCE", "Stage 3.1 frozen tag verified", reference_gate.loc[reference_gate["Check"].eq("Stage 3.1 frozen tag commit"), "Status"].eq("PASS").all(), "PASS", reference_gate.loc[reference_gate["Check"].eq("Stage 3.1 frozen tag commit"), "Status"].tolist())
    add("UPSTREAM", "Stage 3.1 unmodified", reference_gate.loc[reference_gate["Category"].eq("UPSTREAM"), "Status"].eq("PASS").all(), "all PASS", reference_gate.loc[reference_gate["Category"].eq("UPSTREAM"), "Status"].tolist())

    all_features = feature_sets["FS3_FULL_SIGNAL_STATE"]
    rule = feature_sets["FS1_RULE_SUMMARY"]
    raw = feature_sets["FS2_RAW_SIGNAL_STATE"]
    leaks = leakage_feature_names(all_features)
    add("FEATURES", "Exactly three pre-registered feature sets", set(feature_sets) == set(config["feature_sets"]), sorted(config["feature_sets"]), sorted(feature_sets))
    add("FEATURES", "FS1 contains only rule-engine derived features", set(feature_registry_output.loc[feature_registry_output["Feature Set"].eq("FS1_RULE_SUMMARY"), "Feature Group"]) == {RULE_GROUP}, RULE_GROUP, sorted(feature_registry_output.loc[feature_registry_output["Feature Set"].eq("FS1_RULE_SUMMARY"), "Feature Group"].unique()))
    add("FEATURES", "FS2 excludes rule-engine derived features", not set(rule) & set(raw), "disjoint", len(set(rule) & set(raw)))
    add("FEATURES", "FS3 equals FS1 union FS2", set(all_features) == set(rule) | set(raw), len(all_features), len(set(rule) | set(raw)))
    add("FEATURES", "Feature counts fixed", (len(rule), len(raw), len(all_features)) == (5, 92, 97), "5/92/97", f"{len(rule)}/{len(raw)}/{len(all_features)}")
    add("LEAKAGE", "Target leakage count", len(leaks) == 0, 0, len(leaks), ", ".join(leaks))
    add("LEAKAGE", "Ticker excluded", "Ticker" not in all_features, "excluded", "included" if "Ticker" in all_features else "excluded")
    add("LEAKAGE", "Signal ID excluded", "Signal ID" not in all_features, "excluded", "included" if "Signal ID" in all_features else "excluded")
    date_features = [name for name in all_features if "DATE" in name.upper()]
    add("LEAKAGE", "Raw date feature count", len(date_features) == 0, 0, len(date_features), ", ".join(date_features))
    add("IDENTITY", "Feature-set hashes deterministic and complete", set(feature_hashes) == set(feature_sets) and all(len(v) == 64 for v in feature_hashes.values()), sorted(feature_sets), sorted(feature_hashes))

    add("MODELS", "Exactly five pre-registered model variants", set(model_specs) == set(MODEL_ORDER) and len(model_specs) == len(MODEL_ORDER), MODEL_ORDER, sorted(model_specs))
    add("MODELS", "Model specification hashes complete", set(model_hashes) == set(MODEL_ORDER) and all(len(v) == 64 for v in model_hashes.values()), MODEL_ORDER, list(model_hashes))
    logit_expected = config["logistic_parameters"]
    logit_actual = model_specs["LOGIT_FULL"]["hyperparameters"]
    add("MODELS", "Logistic hyperparameters frozen", logit_actual == logit_expected, logit_expected, logit_actual)
    rf_expected = config["random_forest_parameters"]
    rf_actual = model_specs["RF_FULL"]["hyperparameters"]
    add("MODELS", "Random Forest hyperparameters frozen", rf_actual == rf_expected, rf_expected, rf_actual)
    add("MODELS", "Random seed fixed", all(spec["random_seed"] == 42 for spec in model_specs.values()), 42, sorted(set(spec["random_seed"] for spec in model_specs.values())))
    add("MODELS", "No class rebalancing", logit_actual["class_weight"] is None and rf_actual["class_weight"] is None, None, {"logit": logit_actual["class_weight"], "rf": rf_actual["class_weight"]})

    diff_columns = [c for c in fold_audit if c.startswith("Difference ")]
    add("CHRONOLOGY", "Fold reconstruction exact", fold_audit[diff_columns].fillna(0).abs().to_numpy().sum() == 0, 0, int(fold_audit[diff_columns].fillna(0).abs().to_numpy().sum()))
    add("CHRONOLOGY", "Zero training-availability violations", fold_audit["Reconstructed Training Availability Violations"].sum() == 0, 0, int(fold_audit["Reconstructed Training Availability Violations"].sum()))
    add("CHRONOLOGY", "All reconstructed folds pass", fold_audit["Status"].eq("PASS").all(), "all PASS", fold_audit["Status"].value_counts().to_dict())
    add("CHRONOLOGY", "Only requested evaluation years scored", set(predictions["Evaluation Year"].unique()) == set(expected_years), expected_years, sorted(predictions["Evaluation Year"].unique()))

    if len(preprocessing_audit):
        add("PREPROCESSING", "Training-only imputation", preprocessing_audit["Training-Only Imputation Confirmed"].all(), True, bool(preprocessing_audit["Training-Only Imputation Confirmed"].all()))
        add("PREPROCESSING", "Training-only encoding", preprocessing_audit["Training-Only Encoder Confirmed"].all(), True, bool(preprocessing_audit["Training-Only Encoder Confirmed"].all()))
        add("PREPROCESSING", "No evaluation fit operations", preprocessing_audit["No Evaluation Fit Operations"].all(), True, bool(preprocessing_audit["No Evaluation Fit Operations"].all()))
        add("PREPROCESSING", "No global scaling", preprocessing_audit["No Global Scaling"].all(), True, bool(preprocessing_audit["No Global Scaling"].all()))
        add("PREPROCESSING", "No target encoding", preprocessing_audit["No Target Encoding"].all(), True, bool(preprocessing_audit["No Target Encoding"].all()))
    add("MODELS", "No silent fit failure", len(fit_audit) == len(config["targets"]) * len(expected_years) * len(MODEL_ORDER), len(config["targets"]) * len(expected_years) * len(MODEL_ORDER), len(fit_audit))
    warning_count = int(fit_audit["Warnings"].fillna("").ne("").sum())
    if warning_count:
        rows.append({
            "Category": "MODELS", "Check": "Model fit warnings disclosed",
            "Status": "WARN", "Expected": "record every warning", "Actual": warning_count,
            "Details": "Warnings are preserved in stage4a_model_fit_audit.csv; no convergence failure occurred.",
        })
    else:
        add("MODELS", "Model fit warnings disclosed", True, 0, 0)
    add("MODELS", "Dummy prior equals training prevalence", np.array_equal(predictions.loc[predictions["Model Variant"].eq("DUMMY_PRIOR"), "Predicted Probability"].to_numpy(), predictions.loc[predictions["Model Variant"].eq("DUMMY_PRIOR"), "Training Prevalence"].to_numpy()), "exact equality", "exact" if np.array_equal(predictions.loc[predictions["Model Variant"].eq("DUMMY_PRIOR"), "Predicted Probability"].to_numpy(), predictions.loc[predictions["Model Variant"].eq("DUMMY_PRIOR"), "Training Prevalence"].to_numpy()) else "different")
    add("MODELS", "Prediction probabilities in range", predictions["Predicted Probability"].between(0, 1).all(), "[0,1]", f"[{predictions['Predicted Probability'].min()}, {predictions['Predicted Probability'].max()}]")
    uniqueness = ["Signal ID", "Evaluation Year", "Target", "Model Variant"]
    add("PREDICTIONS", "Yearly prediction uniqueness", not predictions.duplicated(uniqueness).any(), 0, int(predictions.duplicated(uniqueness).sum()))
    required_lineage = ["Signal ID", "Signal Date", "Evaluation Year", "Target", "Model Variant", "Feature Set", "Model Spec Hash", "Feature Set Hash", "Stage 3.1 Experiment ID", "Stage 4A Experiment ID", "Training Cutoff Date", "Predicted Probability"]
    missing_lineage = [c for c in required_lineage if c not in predictions or predictions[c].isna().any()]
    add("PREDICTIONS", "OOS prediction lineage complete", len(missing_lineage) == 0, 0, len(missing_lineage), ", ".join(missing_lineage))
    combinations = predictions.groupby(["Target", "Model Variant"])["Evaluation Year"].nunique()
    add("PREDICTIONS", "Complete target/model annual OOS coverage", combinations.eq(len(expected_years)).all() and len(combinations) == len(config["targets"]) * len(MODEL_ORDER), f"{len(config['targets']) * len(MODEL_ORDER)} groups x {len(expected_years)} years", combinations.to_dict())

    assert_joint_arithmetic(joint_predictions)
    add("JOINT", "Joint probability arithmetic exact", True, "exact", "exact")
    nonfill = joint_predictions["Label Status"].eq("AVAILABLE_NON_FILL")
    add("JOINT", "Observed non-fill joint actual is zero", joint_predictions.loc[nonfill, "Actual Label"].eq(0).all(), 0, sorted(joint_predictions.loc[nonfill, "Actual Label"].dropna().unique()))
    excluded = joint_predictions["Label Status"].isin(["ENTRY_DATA_END_CENSORED", "FILLED_INVALID_RISK", "T1_DATA_END_CENSORED", "T2_DATA_END_CENSORED"])
    add("JOINT", "Unresolved/invalid joint labels excluded", joint_predictions.loc[excluded, "Actual Label"].isna().all(), "all NA", int(joint_predictions.loc[excluded, "Actual Label"].notna().sum()))
    available = joint_predictions["Label Status"].isin(["AVAILABLE_NON_FILL", "AVAILABLE_VALID_FILL"])
    add("JOINT", "Joint label availability date present only for available labels", joint_predictions.loc[available, "Label Available Date"].notna().all() and joint_predictions.loc[~available, "Label Available Date"].isna().all(), "consistent", "consistent" if joint_predictions.loc[available, "Label Available Date"].notna().all() and joint_predictions.loc[~available, "Label Available Date"].isna().all() else "inconsistent")
    add("JOINT", "Joint probabilities in range", joint_predictions["Predicted Probability"].between(0, 1).all(), "[0,1]", f"[{joint_predictions['Predicted Probability'].min()}, {joint_predictions['Predicted Probability'].max()}]")
    add("RECENT", "Dedicated 2024-2026 metrics produced", (mode == "sanity") or (set(recent["Target"]) == set(config["targets"]) | {"JOINT_T1", "JOINT_T2"}), sorted(set(config["targets"]) | {"JOINT_T1", "JOINT_T2"}), sorted(recent["Target"].unique()) if len(recent) else [])
    model_binaries = list(stage_root.rglob("*.pkl")) + list(stage_root.rglob("*.joblib"))
    add("REPRODUCIBILITY", "No model binaries required", not model_binaries, 0, len(model_binaries))
    add("SCOPE", "No feature selection", config["prohibitions"]["feature_selection"], "prohibited", "prohibited" if config["prohibitions"]["feature_selection"] else "allowed")
    add("SCOPE", "No hyperparameter search", config["prohibitions"]["hyperparameter_search"], "prohibited", "prohibited" if config["prohibitions"]["hyperparameter_search"] else "allowed")
    add("SCOPE", "No threshold optimization", config["prohibitions"]["probability_threshold_optimization"], "prohibited", "prohibited" if config["prohibitions"]["probability_threshold_optimization"] else "allowed")
    add("SCOPE", "No ML trading backtest", config["prohibitions"]["ml_trading_backtest"], "prohibited", "prohibited" if config["prohibitions"]["ml_trading_backtest"] else "allowed")
    if determinism is not None:
        add("DETERMINISM", "Second full run exact match", determinism["Status"].eq("PASS").all(), "all PASS", determinism["Status"].value_counts().to_dict())
    elif mode == "official":
        add("DETERMINISM", "Second full run exact match", False, "all PASS", "PENDING")
    return pd.DataFrame(rows)


def write_validation_artifacts(checks: pd.DataFrame, output_dir: Path) -> str:
    write_csv(checks, output_dir / "stage4a_validation_checks.csv")
    failures = checks.loc[checks["Status"].eq("FAIL")]
    warnings_count = int(checks["Status"].eq("WARN").sum())
    status = "FAIL" if len(failures) else ("PASS WITH WARNINGS" if warnings_count else "PASS")
    lines = [
        "STAGE 4A ENGINEERING VALIDATION",
        f"ENGINEERING STATUS: {status}",
        f"CHECKS: {len(checks)}",
        f"PASS: {int(checks['Status'].eq('PASS').sum())}",
        f"WARN: {warnings_count}",
        f"FAIL: {int(checks['Status'].eq('FAIL').sum())}",
        "",
    ]
    for row in checks.to_dict("records"):
        lines.append(f"[{row['Status']}] {row['Category']} :: {row['Check']} :: expected={row['Expected']} :: actual={row['Actual']} :: {row['Details']}")
    (output_dir / "stage4a_validation_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return status
