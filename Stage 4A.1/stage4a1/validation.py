"""Fail-closed Stage 4A.1 engineering validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .hashing import write_csv


def check_row(category: str, name: str, passed: bool, expected: Any, actual: Any, warning: bool = False, details: str = "") -> dict[str, Any]:
    status = "PASS" if passed else ("WARN" if warning else "FAIL")
    return {"Category": category, "Check": name, "Status": status, "Expected": expected, "Actual": actual, "Details": details}


def build_checks(
    stage_root: Path, mode: str, reference_gate: pd.DataFrame, feature_sets: dict[str, list[str]],
    feature_hashes: dict[str, str], model_specs: dict[str, dict[str, Any]], model_hashes: dict[str, str],
    fold_audit: pd.DataFrame, preprocessing: pd.DataFrame, fit_audit: pd.DataFrame,
    transfer: pd.DataFrame, primary: pd.DataFrame, transfer_joint: pd.DataFrame, primary_joint: pd.DataFrame,
    bootstrap_summary: pd.DataFrame, evidence: pd.DataFrame, config: dict[str, Any], determinism: pd.DataFrame | None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    add = lambda c, n, p, e, a, w=False, d="": rows.append(check_row(c, n, bool(p), e, a, w, d))
    for _, item in reference_gate.iterrows():
        add(item["Category"], item["Check"], item["Status"] == "PASS", item["Expected"], item["Actual"])
    add("FEATURE", "Feature set sizes exactly frozen", [5, 92, 97] == [len(feature_sets[k]) for k in ["FS1_RULE_SUMMARY", "FS2_RAW_SIGNAL_STATE", "FS3_FULL_SIGNAL_STATE"]], [5, 92, 97], [len(feature_sets[k]) for k in ["FS1_RULE_SUMMARY", "FS2_RAW_SIGNAL_STATE", "FS3_FULL_SIGNAL_STATE"]])
    expected_feature_hashes = __import__("json").loads((stage_root.parent / "Stage 4A" / "results" / "stage4a_feature_set_hashes.json").read_text())
    for name, value in feature_hashes.items():
        add("FEATURE", f"{name} hash frozen", value == expected_feature_hashes[f"{name}_HASH"], expected_feature_hashes[f"{name}_HASH"], value)
    forbidden = [name for values in feature_sets.values() for name in values if "DATE" in name.upper().replace(" ", "_") or name in {"Ticker", "Signal ID"}]
    add("LEAKAGE", "No date/Ticker/Signal ID features", not forbidden, "none", sorted(set(forbidden)) or "none")
    expected_model_hashes = __import__("json").loads((stage_root.parent / "Stage 4A" / "results" / "stage4a_model_spec_hashes.json").read_text())
    for name, value in model_hashes.items():
        add("MODEL", f"{name} model hash frozen", value == expected_model_hashes[name]["MODEL_SPEC_HASH"], expected_model_hashes[name]["MODEL_SPEC_HASH"], value)
    add("MODEL", "Logistic class_weight remains None", all(spec["hyperparameters"].get("class_weight") is None for name, spec in model_specs.items() if name.startswith("LOGIT_")), None, [model_specs[n]["hyperparameters"].get("class_weight") for n in model_specs if n.startswith("LOGIT_")])
    add("MODEL", "Random forest class_weight remains None", model_specs["RF_FULL"]["hyperparameters"]["class_weight"] is None, None, model_specs["RF_FULL"]["hyperparameters"]["class_weight"])
    add("CHRONOLOGY", "All fold audits pass", fold_audit["Status"].eq("PASS").all(), "all PASS", fold_audit["Status"].value_counts().to_dict())
    add("CHRONOLOGY", "Training availability strictly precedes evaluation", fold_audit["Chronology Violations"].eq(0).all(), 0, int(fold_audit["Chronology Violations"].sum()))
    add("COHORT", "PRIMARY_ONLY training restricted to BASELINE_PRIMARY", fold_audit.loc[fold_audit["Training Mode"].eq("PRIMARY_ONLY"), "Status"].eq("PASS").all(), "BASELINE_PRIMARY only", "BASELINE_PRIMARY only")
    add("COHORT", "All scored rows are BASELINE_PRIMARY", transfer["Dataset Cohort"].eq(config["primary_cohort"]).all() and primary["Dataset Cohort"].eq(config["primary_cohort"]).all(), config["primary_cohort"], sorted(set(transfer["Dataset Cohort"]) | set(primary["Dataset Cohort"])))
    keys = ["Signal ID", "Target", "Model Variant", "Evaluation Year"]
    add("TRANSFER", "Transfer Signal IDs preserved", set(map(tuple, transfer[keys].to_numpy())) == set(map(tuple, primary[keys].to_numpy())), "identical keys", "identical" if set(map(tuple, transfer[keys].to_numpy())) == set(map(tuple, primary[keys].to_numpy())) else "different")
    add("PREDICTION", "Annual primary OOS predictions unique", not primary.duplicated(keys).any(), 0, int(primary.duplicated(keys).sum()))
    add("PREDICTION", "Probabilities bounded", transfer["Predicted Probability"].between(0, 1).all() and primary["Predicted Probability"].between(0, 1).all(), "[0,1]", "bounded")
    add("PREPROCESS", "Training-only preprocessing audited", preprocessing["No Evaluation Fit Operations"].eq(True).all(), True, preprocessing["No Evaluation Fit Operations"].value_counts().to_dict())
    add("PREPROCESS", "Unknown categories handled without refit", preprocessing["Status"].eq("PASS").all(), "all PASS", preprocessing["Status"].value_counts().to_dict())
    add("FIT", "All model fits retain both classes", (fit_audit["Training Positives"].gt(0) & fit_audit["Training Negatives"].gt(0)).all(), "both classes", "both classes")
    add("FIT", "Dummy prior equals training prevalence", np.allclose(fit_audit.loc[fit_audit["Model Variant"].eq("DUMMY_PRIOR"), "Training Prevalence"], primary.loc[primary["Model Variant"].eq("DUMMY_PRIOR")].groupby(["Target", "Evaluation Year"])["Training Prior"].first().sort_index().to_numpy()), True, True)
    for target, conditional in [("JOINT_T1", "P T1 Conditional"), ("JOINT_T2", "P T2 Conditional")]:
        for label, frame in [("TRANSFER", transfer_joint), ("PRIMARY_ONLY", primary_joint)]:
            subset = frame.loc[frame["Target"].eq(target)]
            exact = np.allclose(subset["Predicted Probability"], subset["P Fill"] * subset[conditional], rtol=0, atol=2e-12)
            add("JOINT", f"{label} {target} arithmetic exact", exact, True, exact)
    add("JOINT", "Non-filled joint actual equals zero", pd.concat([transfer_joint, primary_joint]).loc[pd.concat([transfer_joint, primary_joint])["Label Status"].eq("AVAILABLE_NON_FILL"), "Actual Label"].eq(0).all(), 0, 0)
    add("JOINT", "Censored joint labels excluded", pd.concat([transfer_joint, primary_joint]).loc[pd.concat([transfer_joint, primary_joint])["Label Status"].str.contains("CENSORED", na=False), "Actual Label"].isna().all(), True, True)
    primary_auc = bootstrap_summary.loc[bootstrap_summary["Block Length"].eq(63) & bootstrap_summary["Scope"].eq("POOLED_2016_2026") & bootstrap_summary["Metric"].eq("ROC AUC")]
    required = 1 if mode == "sanity" else config["bootstrap"]["minimum_valid_pooled_auc_replicates"]
    add("BOOTSTRAP", "Primary pooled AUC replicate sufficiency", primary_auc["Valid Replicates"].ge(required).all(), f">={required}", int(primary_auc["Valid Replicates"].min()))
    add("BOOTSTRAP", "All block lengths produced", set(bootstrap_summary["Block Length"]) == {21, 63, 126}, [21, 63, 126], sorted(bootstrap_summary["Block Length"].unique()))
    expected_scopes = {"POOLED_2016_2026", "ERA_2016_2020"} if mode == "sanity" else {"POOLED_2016_2026", "ERA_2016_2020", "ERA_2021_2023", "RECENT_2024_2026"}
    add("BOOTSTRAP", "All applicable pre-registered uncertainty scopes produced", set(bootstrap_summary["Scope"]) == expected_scopes, sorted(expected_scopes), sorted(bootstrap_summary["Scope"].unique()))
    add("EVIDENCE", "Only fixed evidence classifications used", set(evidence["Research Evidence Classification"]).issubset({"ROBUST POSITIVE HISTORICAL SIGNAL", "WEAK POSITIVE HISTORICAL SIGNAL", "MIXED / INCONCLUSIVE", "NO USEFUL HISTORICAL SIGNAL", "INSUFFICIENT SAMPLE"}), "fixed vocabulary", sorted(evidence["Research Evidence Classification"].unique()))
    source_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (stage_root / "stage4a1").glob("*.py") if path.name != "validation.py")
    for name, token in [("No random train/test split", "train_test_split("), ("No shuffled CV", "shuffle=True"), ("No SMOTE", "SMOTE("), ("No oversampling", "oversampl"), ("No undersampling", "undersampl"), ("No hyperparameter search", "GridSearchCV("), ("No feature selection", "SelectKBest("), ("No threshold optimization", "threshold_search")]:
        add("PROHIBITION", name, token.lower() not in source_text.lower(), "absent", "absent" if token.lower() not in source_text.lower() else token)
    warning_count = int(fit_audit["Warnings"].fillna("").ne("").sum())
    add("WARNING", "Sklearn explicit-penalty warning recorded", warning_count == 0, 0, warning_count, warning_count > 0, "Frozen explicit penalty='l2' retained as required")
    add("DETERMINISM", "Second complete official run exact", determinism is not None and determinism["Status"].eq("PASS").all(), "all PASS", "PENDING" if determinism is None else determinism["Status"].value_counts().to_dict())
    from .metric_audit import consistency_audits
    consistency, ties = consistency_audits(pd.concat([transfer, primary, transfer_joint, primary_joint], ignore_index=True))
    add("METRICS", "Point bootstrap identity parity", consistency["Status"].eq("PASS").all(), "all PASS", consistency["Status"].value_counts().to_dict())
    add("RANKING", "Shared canonical tie handling", ties["Status"].eq("PASS").all(), "all PASS", ties["Status"].value_counts().to_dict())
    return pd.DataFrame(rows)


def write_validation(checks: pd.DataFrame, output_dir: Path) -> str:
    write_csv(checks, output_dir / "stage4a1_validation_checks.csv")
    fail = int(checks["Status"].eq("FAIL").sum()); warn = int(checks["Status"].eq("WARN").sum()); passed = int(checks["Status"].eq("PASS").sum())
    status = "FAIL" if fail else ("PASS WITH WARNINGS" if warn else "PASS")
    lines = [f"STAGE 4A.1 ENGINEERING STATUS: {status}", f"PASS: {passed}", f"WARN: {warn}", f"FAIL: {fail}", ""]
    lines += [f"[{row.Status}] {row.Category} :: {row.Check} :: expected={row.Expected} actual={row.Actual} {row.Details}" for row in checks.itertuples(index=False)]
    (output_dir / "stage4a1_validation_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return status
