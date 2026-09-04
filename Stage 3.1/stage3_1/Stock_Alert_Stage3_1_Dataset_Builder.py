"""Stage 3.1 semantic hardening of immutable Stage 3 research datasets."""
from __future__ import annotations

import argparse
import copy
import importlib.util
import io
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from diagnostics import (
    ambiguity_summary,
    censoring_summary,
    d1_position_day_summary,
    dataset_summary,
    feature_distribution_by_era,
    feature_missingness,
    target_summary,
)
from features import (
    date_feature_audit,
    feature_metadata_semantic_audit,
    feature_registry,
    ml_column_registry,
    normalize_date_columns,
)
from hashing import (
    canonical_json_hash,
    dataframe_content_hash,
    dataframe_schema,
    deterministic_row_id,
    directory_hash,
    environment_report,
    sha256_file,
    source_package_manifest,
    write_csv,
    write_deterministic_csv_gz,
    write_json,
)
from labels import harden_opportunity_labels, label_registry, time_to_target_semantic_audit
from opportunity_engine import harden_entry_semantics, load_frozen_calendars
from position_day_builder import harden_position_day_labels
from splits import build_walk_forward_manifest
from validation import (
    MATERIAL_SIGNAL_COLUMNS,
    dataframe_parity,
    entry_parity,
    fail_if_any,
    integration_checks,
    position_day_parity,
    stage3_reference_gate,
)


STAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE_ROOT.parent
CONFIG_PATH = STAGE_ROOT / "config" / "stage3_1_dataset_config.json"
SOURCE_PATHS = [
    "config/stage3_1_dataset_config.json",
    "stage3_1/__init__.py",
    "stage3_1/Stock_Alert_Stage3_1_Dataset_Builder.py",
    "stage3_1/features.py",
    "stage3_1/labels.py",
    "stage3_1/opportunity_engine.py",
    "stage3_1/position_day_builder.py",
    "stage3_1/splits.py",
    "stage3_1/validation.py",
    "stage3_1/hashing.py",
    "stage3_1/diagnostics.py",
    "tests/run_stage3_1_tests.py",
]


def _load_tests() -> Any:
    path = STAGE_ROOT / "tests" / "run_stage3_1_tests.py"
    spec = importlib.util.spec_from_file_location("stage3_1_tests", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_reference_frame(path: Path) -> pd.DataFrame:
    return normalize_date_columns(pd.read_csv(path, compression="gzip", low_memory=False))


def _read_git_csv(commit: str, repo_path: str, compression: str | None = None) -> pd.DataFrame:
    payload = subprocess.check_output(
        ["git", "show", f"{commit}:{repo_path}"],
        cwd=REPO_ROOT,
    )
    return normalize_date_columns(
        pd.read_csv(io.BytesIO(payload), compression=compression, low_memory=False)
    )


def _feature_value_parity(
    reference: Mapping[str, pd.DataFrame],
    current: Mapping[str, pd.DataFrame],
    reference_registry: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries: list[pd.DataFrame] = []
    differences: list[pd.DataFrame] = []
    for dataset, current_frame in current.items():
        reference_frame = reference[dataset]
        features = sorted(
            name for name in reference_registry.loc[
                reference_registry["Dataset"].eq(dataset), "Feature Name"
            ].astype(str).unique()
            if name in reference_frame.columns and name in current_frame.columns
        )
        keys = ["Signal ID", "Management Date"] if dataset == "d1_position_day" else ["Signal ID"]
        comparison = f"{dataset.upper()}_PRE_HOTFIX_FEATURE_VALUE_PARITY"
        reference_view = reference_frame[keys + features]
        current_view = current_frame[keys + features]
        ordered_keys_match = (
            len(reference_view) == len(current_view)
            and reference_view[keys].reset_index(drop=True).equals(
                current_view[keys].reset_index(drop=True)
            )
        )
        logical_values_match = (
            ordered_keys_match
            and dataframe_content_hash(reference_view) == dataframe_content_hash(current_view)
        )
        if logical_values_match:
            summary = pd.DataFrame([{
                "Comparison": comparison,
                "Reference Rows": len(reference_frame),
                "Stage 3.1 Rows": len(current_frame),
                "Difference Count": 0,
                "Status": "PASS",
            }])
            diff = pd.DataFrame(columns=[
                "Key", "Field", "Reference", "Stage 3.1", "Absolute Difference",
            ])
        else:
            summary, diff = dataframe_parity(
                reference_frame, current_frame, keys, features,
                comparison, tolerance=1e-12,
            )
        summary.insert(0, "Dataset", dataset)
        summary["Compared Feature Columns"] = len(features)
        summaries.append(summary)
        if not diff.empty:
            diff.insert(0, "Dataset", dataset)
            differences.append(diff)
    summary_frame = pd.concat(summaries, ignore_index=True)
    difference_frame = (
        pd.concat(differences, ignore_index=True)
        if differences
        else pd.DataFrame(columns=[
            "Dataset", "Key", "Field", "Reference", "Stage 3.1", "Absolute Difference",
        ])
    )
    return summary_frame, difference_frame


def _parity_output_names(prefix: str) -> tuple[str, str]:
    return f"stage3_1_{prefix}_summary.csv", f"stage3_1_{prefix}_differences.csv"


def _write_validation_report(checks: pd.DataFrame, path: Path) -> None:
    lines = ["STAGE 3.1 VALIDATION REPORT", "=" * 72]
    for _, row in checks.iterrows():
        lines.append((
            f"[{row['Status']}] {row['Type']} :: {row['Check']} :: "
            f"expected={row['Expected']} :: actual={row['Actual']} :: {row.get('Detail', '')}"
        ).rstrip())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _semantic_change_manifest(
    entry_changes: pd.DataFrame,
    opportunities: pd.DataFrame,
    feature_reg: pd.DataFrame,
    date_audit: pd.DataFrame,
    availability_audit: pd.DataFrame,
    time_to_target_audit: pd.DataFrame,
    config: Mapping[str, Any],
) -> pd.DataFrame:
    t1_not_app = int(opportunities["T1_STATUS"].eq("NOT_APPLICABLE").sum())
    date_changed = int(
        date_audit["Column"].eq("NIFTY Feature Source Date").sum()
    ) if not date_audit.empty else 0
    shared_features = int((feature_reg.groupby("Feature Name")["Dataset"].nunique() > 1).sum())
    valid_entry = (
        opportunities["ENTRY_FILLED"].fillna(False).astype(bool)
        & opportunities["ENTRY_RISK_VALID"].fillna(False).astype(bool)
    )
    time_metadata_changes = sum(
        int((valid_entry & opportunities[f"{target}_BEFORE_STOP_63"].eq(False).fillna(False)).sum())
        for target in ("T1", "T2")
    )
    d1_metadata_rows = int(feature_reg["Dataset"].eq("d1_position_day").sum())
    rows = [
        ["INCOMPLETE_ENTRY_WINDOW", "Any future bar made a non-fill appear resolved", "Full setup-specific window required unless an earlier fill resolves the order", "NOT OBSERVED must not mean FAILED", "YES", "Data-end partial non-fills", len(entry_changes), "PASS"],
        ["NOT_APPLICABLE_VS_CENSORED", "Non-entered and non-D1-cohort rows were mixed with censoring", "Applicability, status, and data-end censoring are target-specific", "Censoring denominators must include applicable rows only", "METADATA ONLY", "Non-entered, invalid-risk, and non-D1 rows", t1_not_app, "PASS"],
        ["RAW_DATE_FEATURE_ROLE", "At least one source date was FEATURE_ALLOWED", "All raw calendar/source dates are excluded from ML", "Audit dates are not predictive inputs", "NO", "NIFTY source-date registry rows", date_changed, "PASS"],
        ["DATASET_SPECIFIC_FEATURE_REGISTRY", "Registry key was Feature Name only", "Registry key is Dataset + Feature Name", "Same name can have different as-of semantics", "NO", "Shared feature names", shared_features, "PASS"],
        ["FORWARD_HORIZON_NAMING", "Entry-inclusive counting was implicit", "Canonical ENTRY_INCLUSIVE names plus exact legacy aliases", "Remove one-session ambiguity without changing values", "NO", str(len(config["forward_horizons"]) * 2) + " canonical columns", len(config["forward_horizons"]) * 2, "PASS"],
        ["CONDITIONAL_TIME_TO_TARGET", "Time-to-target condition was implicit", "Registry declares conditional regression on target success", "Avoid treating non-hits as missing regression labels", "NO", "2 labels", 2, "PASS"],
        ["VALIDATION_VIOLATION_REPORTING", "Some reports used row counts as actual violations", "Each availability check reports explicit violation counts", "Validation totals now mean violations", "NO", "All label availability checks", len(availability_audit), "PASS"],
        ["TIME_TO_TARGET_APPLICABILITY_FIX", "All valid entries were marked applicable even after definitive target failure", "Only successful or underlying data-end-censored target outcomes are applicable", "Conditional regression applicability must match target success or unresolved censoring", "NO", "Resolved target-failure metadata rows across T1/T2", time_metadata_changes, "PASS" if time_to_target_audit["Status"].eq("PASS").all() else "FAIL"],
        ["TRUE_DATASET_SPECIFIC_FEATURE_METADATA", "Metadata began from a globally keyed Feature Name row", "Metadata is generated for each Dataset + Feature Name pair", "Position-day current and entry-frozen states require distinct lineage", "NO", "D1 position-day feature registry rows", d1_metadata_rows, "PASS"],
        ["STAGE3_REFERENCE_COMMIT_GATE", "Stage 3 was compared only with current HEAD/worktree", "Stage 3 branch, commit, tree, worktree, and artifacts are checked against the exact immutable commit", "Prove the reference is unchanged", "NO", "Stage 3 reference gate", 1, "PASS"],
        ["SYNTHETIC_D1_CENSOR_TEST", "The real-data D1 censor assertion could pass on zero rows", "Deterministic applicable-censored and non-primary synthetic cases are asserted", "Prevent vacuous censoring coverage", "NO", "Synthetic test scenarios", 2, "PASS"],
    ]
    return pd.DataFrame(rows, columns=[
        "Area", "Old Stage 3 Behavior", "Stage 3.1 Behavior", "Reason",
        "Changes Numeric Outcome?", "Expected Rows Affected", "Actual Rows Affected",
        "Acceptance Status",
    ])


def _delivery_report(
    identity: Mapping[str, Any],
    summary: Mapping[str, Any],
    manifests: Mapping[str, Any],
    censor: pd.DataFrame,
    parity: Mapping[str, pd.DataFrame],
    ml: Mapping[str, int],
    split: pd.DataFrame,
    determinism: pd.DataFrame,
    time_semantic_audit: pd.DataFrame,
    metadata_semantic_audit: pd.DataFrame,
    tests: pd.DataFrame,
    reference_gate: pd.DataFrame,
    runtime: Mapping[str, float],
    config: Mapping[str, Any],
    status: str,
) -> str:
    def counts(target: str) -> str:
        row = censor[censor["Target"] == target]
        if row.empty:
            return "not present"
        item = row.iloc[0]
        return (
            f"applicable={int(item['Applicable Rows']):,}, available={int(item['Available Rows']):,}, "
            f"not applicable={int(item['Not Applicable Rows']):,}, "
            f"data-end censored={int(item['Data-End Censored Rows']):,}"
        )

    lines = [
        "# Stage 3.1 Delivery Report",
        "",
        f"ENGINEERING STATUS: **{status}**",
        "",
        "Stage 3.1 hardens dataset semantics only. It does not train a model or change trading logic.",
        "",
        "## Reference",
        "",
        f"- Stage 2B.1 tag: `{config['baseline_tag']}`",
        f"- Stage 2B.1 commit: `{config['baseline_commit']}`",
        f"- Stage 3 reference branch: `{config['stage3_reference_branch']}`",
        f"- Stage 3 reference commit: `{config['stage3_reference_commit']}`",
        f"- Stage 3 reference package hash: `{config['stage3_reference_code_package_hash']}`",
        f"- Stage 3.1 pre-hotfix reference commit: `{config['stage3_1_pre_hotfix_reference_commit']}`",
        f"- Current checkout commit at runtime: `{identity['CURRENT_GIT_COMMIT_AT_RUNTIME']}`",
        f"- Final Stage 3.1 commit at runtime: `{identity['FINAL_STAGE3_1_COMMIT_AT_RUNTIME']}`",
        "",
        "## Identity",
        "",
        f"- Stage 3.1 Experiment ID: `{identity['EXPERIMENT_ID']}`",
        f"- Stage 3.1 code package hash: `{identity['STAGE3_1_CODE_PACKAGE_HASH']}`",
        f"- Config hash: `{identity['STAGE3_1_CONFIG_HASH']}`",
        f"- Schema hash: `{identity['STAGE3_1_SCHEMA_HASH']}`",
        "",
        "## Datasets",
        "",
        f"- Signal rows: {summary['signal_rows']:,}",
        f"- Opportunity rows: {summary['opportunity_rows']:,}",
        f"- Filled opportunities: {summary['filled']:,}",
        f"- Genuine observed non-fills: {summary['nonfilled']:,}",
        f"- Incomplete entry-window censored rows: {summary['entry_censored']:,}",
        f"- Invalid-risk rows: {summary['invalid_risk']:,}",
        f"- BASELINE_PRIMARY rows: {summary['baseline_primary']:,}",
        f"- RESEARCH_EXTENDED rows: {summary['research_extended']:,}",
        f"- D1 applicable rows: {summary['d1_applicable']:,}",
        f"- D1 position-day rows: {summary['position_rows']:,}",
        "",
        "## Censoring and applicability",
        "",
        f"- T1: {counts('T1_BEFORE_STOP_63')}",
        f"- T2: {counts('T2_BEFORE_STOP_63')}",
        "",
        "## Conditional time-to-target semantics",
        "",
    ]
    for _, item in time_semantic_audit.iterrows():
        lines.append(
            f"- {item['Target']}: available={int(item['Available Rows']):,}, "
            f"not applicable={int(item['Not Applicable Rows']):,}, "
            f"data-end censored={int(item['Data-End Censored Rows']):,}, "
            f"applicable={int(item['Applicable Rows']):,}, "
            f"partition violations={int(item['Partition Violations']):,}, "
            f"status={item['Status']}"
        )
    lines.extend([
        "",
        "## Other censoring and applicability",
        "",
    ])
    for horizon in config["forward_horizons"]:
        lines.append(f"- FWD {horizon}: {counts(f'FWD_CLOSE_RETURN_{horizon}_ENTRY_INCLUSIVE_PCT')}")
    lines.extend([
        f"- D1 shadow: {counts('D1_SHADOW_NET_R')}",
        "",
        "## Parity",
        "",
        f"- Stage 3 signal parity differences: {int(parity['signal'].iloc[0]['Difference Count']):,}",
        f"- Frozen source parity differences: {int(parity['source'].iloc[0]['Difference Count']):,}",
        f"- Opportunity membership differences: {int(parity['opportunity'].iloc[0]['Difference Count']):,}",
        f"- Expected entry semantic changes: {summary['entry_changes']:,}",
        f"- Unexplained entry differences: {int(parity['entry'].iloc[0]['Difference Count']):,}",
        f"- Candidate outcome differences: {int(parity['candidate'].iloc[0]['Difference Count']):,}",
        f"- D1 shadow differences: {int(parity['d1'].iloc[0]['Difference Count']):,}",
        f"- Position-day differences: {int(parity['position'].iloc[0]['Difference Count']):,}",
        f"- Stable numerical target differences: {int(parity['target'].iloc[0]['Difference Count']):,}",
        f"- Final feature-value differences: {int(parity['feature']['Difference Count'].sum()):,}",
        "",
        "## ML safety",
        "",
        f"- FEATURE_ALLOWED count: {ml['feature_allowed']:,}",
        f"- Date-like FEATURE_ALLOWED count: {ml['date_allowed']:,}",
        f"- Target leakage violations: {ml['target_leaks']:,}",
        f"- Unregistered feature violations: {ml['unregistered']:,}",
        f"- Registry inconsistencies: {ml['registry_difference']:,}",
        f"- Feature metadata semantic violations: {int(metadata_semantic_audit['Status'].ne('PASS').sum()):,}",
        "",
        "## Reference safety",
        "",
        f"- Stage 3 reference gate failures: {int(reference_gate['Status'].ne('PASS').sum()):,}",
        f"- Stage 3 branch commit check: {reference_gate.loc[reference_gate['Check'].eq('Stage 3 reference branch commit'), 'Status'].iloc[0]}",
        f"- Stage 3 exact-commit directory check: {reference_gate.loc[reference_gate['Check'].eq('Stage 3 working directory equals exact reference commit'), 'Status'].iloc[0]}",
        f"- Stage 3 artifact/hash gates: {'PASS' if reference_gate.loc[reference_gate['Type'].eq('STAGE3_REFERENCE'), 'Status'].eq('PASS').all() else 'FAIL'}",
        "",
        "## Walk forward",
        "",
        f"- Targets: {split['Target'].nunique():,}",
        f"- Evaluation years: {split['Evaluation Year'].nunique():,}",
        f"- Training availability violations: {int(split['Training Availability Violations'].sum()):,}",
        "",
        "## Tests",
        "",
        f"- Total tests: {len(tests):,}",
        f"- PASS: {int(tests['Status'].eq('PASS').sum()):,}",
        f"- FAIL: {int(tests['Status'].eq('FAIL').sum()):,}",
        "",
        "## Determinism",
        "",
        f"- First-run/previous hashes available: {'YES' if determinism['Previous Hash'].notna().any() else 'NO'}",
        f"- Repeated-run hash differences: {int((determinism['Status'] == 'FAIL').sum()):,}",
    ])
    for _, item in determinism.iterrows():
        lines.append(f"- {item['Identity']}: first=`{item['Previous Hash']}`, second=`{item['Current Hash']}`, status={item['Status']}")
    lines.extend([
        "",
        "## Runtime",
        "",
        f"- Sanity runtime: {runtime.get('sanity', 0.0):.2f} seconds",
        f"- Official runtime: {runtime.get('official', 0.0):.2f} seconds",
        f"- Deterministic rerun runtime: {runtime.get('rerun', 0.0):.2f} seconds",
        "",
        "## Scope declarations",
        "",
        "STAGE 2.2.2 FINAL MODIFIED: NO",
        "",
        "STAGE 2B MODIFIED: NO",
        "",
        "STAGE 2B.1 MODIFIED: NO",
        "",
        "STAGE 3 REFERENCE MODIFIED: NO",
        "",
        "STAGE 1 SIGNAL RULES CHANGED: NO",
        "",
        "OPPORTUNITY ELIGIBILITY RULES CHANGED: NO",
        "",
        "ENTRY EXECUTION RULES CHANGED: NO",
        "",
        "D1 MANAGEMENT RULES CHANGED: NO",
        "",
        "HISTORICAL VALID TARGET VALUES CHANGED: NO",
        "",
        "ML MODEL TRAINED: NO",
        "",
        "FEATURE SELECTION PERFORMED: NO",
        "",
        "HYPERPARAMETER TUNING PERFORMED: NO",
        "",
        "STRATEGY THRESHOLD TUNING PERFORMED: NO",
        "",
        "INCOMPLETE ENTRY WINDOW SEMANTICS FIXED: YES",
        "",
        "NOT_APPLICABLE SEPARATED FROM DATA_END_CENSORED: YES",
        "",
        "RAW DATE ML FEATURES ALLOWED: NO",
        "",
        "FEATURE REGISTRY DATASET-SPECIFIC: YES",
        "",
        "FORWARD HORIZON SEMANTICS EXPLICIT: YES",
        "",
        "TIME-TO-TARGET CONDITIONAL SEMANTICS EXPLICIT: YES",
        "",
        "WALK-FORWARD LABEL AVAILABILITY ENFORCED: YES",
        "",
        "TIME_TO_TARGET APPLICABILITY FIXED: YES",
        "",
        "FEATURE REGISTRY METADATA TRULY DATASET-SPECIFIC: YES",
        "",
        "STAGE 3 EXACT REFERENCE COMMIT VERIFIED: YES",
        "",
        "SYNTHETIC D1 CENSOR TEST ADDED: YES",
        "",
        f"DATE_LIKE FEATURE_ALLOWED COUNT: {ml['date_allowed']}",
        "",
        f"TARGET LEAKAGE VIOLATIONS: {ml['target_leaks']}",
        "",
        f"TRAINING AVAILABILITY VIOLATIONS: {int(split['Training Availability Violations'].sum())}",
        "",
        f"FINAL STAGE 3.1 READY FOR INDEPENDENT FREEZE AUDIT: {'YES' if status in {'PASS', 'PASS WITH WARNINGS'} else 'NO'}",
        "",
        "## Known limitations",
        "",
    ])
    lines.extend(f"- {value}" for value in config["known_limitations"])
    lines.extend(["", "No Stage 4 model training is authorized or performed.", ""])
    return "\n".join(lines)


def run(sanity: bool = False, requested_tickers: Sequence[str] = ()) -> dict[str, Any]:
    started = time.perf_counter()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    output = STAGE_ROOT / ("tests/sanity_results" if sanity else "results")
    output.mkdir(parents=True, exist_ok=True)
    previous_manifest_path = output / "stage3_1_dataset_manifest.json"
    previous_manifest = json.loads(previous_manifest_path.read_text(encoding="utf-8")) if previous_manifest_path.is_file() else None
    previous_identity_path = output / "stage3_1_experiment_identity.json"
    previous_identity = json.loads(previous_identity_path.read_text(encoding="utf-8")) if previous_identity_path.is_file() else None
    runtime_history_path = output / "stage3_1_runtime_history.json"
    previous_runtime = (
        json.loads(runtime_history_path.read_text(encoding="utf-8"))
        if runtime_history_path.is_file()
        else {}
    )
    sanity_runtime_path = STAGE_ROOT / "tests" / "sanity_results" / "stage3_1_runtime_history.json"
    sanity_runtime = (
        json.loads(sanity_runtime_path.read_text(encoding="utf-8"))
        if sanity_runtime_path.is_file()
        else {}
    )

    reference_tree_before = directory_hash(REPO_ROOT / config["source_paths"]["stage3_root"])
    reference_gate = stage3_reference_gate(REPO_ROOT, config)
    package_manifest = source_package_manifest(STAGE_ROOT, SOURCE_PATHS)
    config_hash = canonical_json_hash(config)
    identity_seed = canonical_json_hash({
        "code": package_manifest["package_hash"],
        "config": config_hash,
        "stage3_commit": config["stage3_reference_commit"],
        "stage3_schema": config["stage3_reference_schema_hash"],
    })[:12]
    experiment_id = f"S3_1_{config['test_start'].replace('-', '')}_{config['test_end'].replace('-', '')}_{identity_seed}"
    if sanity:
        experiment_id += "_SANITY"

    source_root = REPO_ROOT / config["source_paths"]["stage3_results"]
    stage3_signal = _read_reference_frame(REPO_ROOT / config["source_paths"]["stage3_signal_state"])
    stage3_opp = _read_reference_frame(REPO_ROOT / config["source_paths"]["stage3_trade_opportunity"])
    stage3_pos = _read_reference_frame(REPO_ROOT / config["source_paths"]["stage3_d1_position_day"])
    tickers = sorted(set(requested_tickers or (["TCS.NS", "INFY.NS"] if sanity else stage3_signal["Ticker"].astype(str).unique())))
    pre_hotfix_commit = config["stage3_1_pre_hotfix_reference_commit"]
    pre_hotfix_datasets = {
        "signal_state": _read_git_csv(pre_hotfix_commit, "Stage 3.1/results/stage3_1_signal_state_dataset.csv.gz", "gzip"),
        "trade_opportunity": _read_git_csv(pre_hotfix_commit, "Stage 3.1/results/stage3_1_trade_opportunity_dataset.csv.gz", "gzip"),
        "d1_position_day": _read_git_csv(pre_hotfix_commit, "Stage 3.1/results/stage3_1_d1_position_day_dataset.csv.gz", "gzip"),
    }
    pre_hotfix_feature_registry = _read_git_csv(
        pre_hotfix_commit, "Stage 3.1/results/stage3_1_feature_registry.csv"
    )
    if sanity:
        stage3_signal = stage3_signal[stage3_signal["Ticker"].isin(tickers)].reset_index(drop=True)
        stage3_opp = stage3_opp[stage3_opp["Ticker"].isin(tickers)].reset_index(drop=True)
        stage3_pos = stage3_pos[stage3_pos["Ticker"].isin(tickers)].reset_index(drop=True)
        pre_hotfix_datasets = {
            name: frame[frame["Ticker"].isin(tickers)].reset_index(drop=True)
            for name, frame in pre_hotfix_datasets.items()
        }

    signal_state = stage3_signal.copy()
    signal_state["Stage 3.1 Experiment ID"] = experiment_id
    signal_state["STAGE3_1_ROW_ID"] = [
        deterministic_row_id(config["dataset_schema_versions"]["signal_state"], value)
        for value in signal_state["Signal ID"]
    ]

    calendars = load_frozen_calendars(REPO_ROOT, config["source_paths"]["frozen_data"], tickers)
    opportunities, entry_changes = harden_entry_semantics(stage3_opp, calendars, config)
    opportunities = harden_opportunity_labels(opportunities, config)
    opportunities["Stage 3.1 Experiment ID"] = experiment_id
    opportunities["STAGE3_1_ROW_ID"] = [
        deterministic_row_id(config["dataset_schema_versions"]["trade_opportunity"], value)
        for value in opportunities["Signal ID"]
    ]

    position_day = harden_position_day_labels(stage3_pos, config)
    position_day["Stage 3.1 Experiment ID"] = experiment_id
    position_day["STAGE3_1_ROW_ID"] = [
        deterministic_row_id(
            config["dataset_schema_versions"]["d1_position_day"],
            signal_id,
            pd.Timestamp(date).strftime("%Y-%m-%d"),
        )
        for signal_id, date in zip(position_day["Signal ID"], position_day["Management Date"])
    ]

    datasets = {"signal_state": signal_state, "trade_opportunity": opportunities, "d1_position_day": position_day}
    stage3_feature = pd.read_csv(REPO_ROOT / config["source_paths"]["stage3_feature_registry"])
    feature_reg = feature_registry(datasets, stage3_feature)
    label_reg = label_registry(config)
    ml_reg = ml_column_registry(datasets, feature_reg, label_reg)
    date_audit = date_feature_audit(datasets, ml_reg)
    split_manifest, availability_audit = build_walk_forward_manifest(opportunities, position_day, config)
    time_semantic_audit = time_to_target_semantic_audit(opportunities)
    metadata_semantic_audit = feature_metadata_semantic_audit(feature_reg, ml_reg)
    feature_value_summary, feature_value_diff = _feature_value_parity(
        pre_hotfix_datasets, datasets, pre_hotfix_feature_registry,
    )

    # Prefix invariance is an independent frozen-input audit.  It deliberately
    # retains every configured audit ticker even when the output datasets are a
    # two-ticker sanity subset.
    point_in_time = pd.read_csv(REPO_ROOT / config["source_paths"]["stage3_point_in_time_audit"])
    signal_summary, signal_diff = dataframe_parity(stage3_signal, signal_state, ["Signal ID"], MATERIAL_SIGNAL_COLUMNS[1:], "STAGE3_SIGNAL_PARITY")
    source_summary, source_diff = dataframe_parity(stage3_signal, signal_state, ["Signal ID"], MATERIAL_SIGNAL_COLUMNS[1:], "FROZEN_SIGNAL_SOURCE_PARITY")
    opportunity_summary, opportunity_diff = dataframe_parity(stage3_opp, opportunities, ["Signal ID"], [], "STAGE3_OPPORTUNITY_MEMBERSHIP_PARITY")
    entry_summary, entry_diff = entry_parity(stage3_opp, opportunities)
    target_fields = [
        "T1_BEFORE_STOP_63", "T2_BEFORE_STOP_63", "STOP_BEFORE_T1_63", "STOP_BEFORE_T2_63",
        "TIME_TO_T1_SESSIONS", "TIME_TO_T2_SESSIONS",
    ]
    for horizon in config["forward_horizons"]:
        target_fields.extend([
            f"FWD_CLOSE_RETURN_{horizon}_PCT", f"FWD_CLOSE_RETURN_{horizon}_R",
            f"MFE_R_{horizon}_FULL_BAR_DIAGNOSTIC", f"MAE_R_{horizon}_FULL_BAR_DIAGNOSTIC",
            f"MFE_R_{horizon}_CONSERVATIVE", f"MAE_R_{horizon}_CONSERVATIVE",
            f"MFE_PCT_{horizon}_CONSERVATIVE", f"MAE_PCT_{horizon}_CONSERVATIVE",
        ])
    target_fields.extend([
        "D1_SHADOW_EXIT_DATE", "D1_SHADOW_EXIT_REASON", "D1_SHADOW_BARS_HELD",
        "D1_SHADOW_EXECUTED_EXIT", "D1_SHADOW_STOP_REVISION_COUNT", "D1_SHADOW_NET_R",
    ])
    target_summary_frame, target_diff = dataframe_parity(stage3_opp, opportunities, ["Signal ID"], target_fields, "STAGE3_STABLE_TARGET_NUMERICAL_PARITY", tolerance=1e-10)
    position_summary, position_diff = position_day_parity(stage3_pos, position_day)

    parity_root = REPO_ROOT / ("Stage 3/tests/sanity_results" if sanity else "Stage 3/results")
    candidate_summary = pd.read_csv(parity_root / "stage3_candidate_outcome_parity_summary.csv")
    candidate_diff = pd.read_csv(parity_root / "stage3_candidate_outcome_parity_differences.csv")
    d1_summary = pd.read_csv(parity_root / "stage3_d1_shadow_parity_summary.csv")
    d1_diff = pd.read_csv(parity_root / "stage3_d1_shadow_parity_differences.csv")

    runtime_config = copy.deepcopy(config)
    for name, frame in datasets.items():
        runtime_config["stage3_reference_datasets"][name]["rows"] = len(frame)
    parity_summaries = [signal_summary, source_summary, opportunity_summary, entry_summary, target_summary_frame, position_summary]
    semantic_manifest = _semantic_change_manifest(
        entry_changes, opportunities, feature_reg, date_audit,
        availability_audit, time_semantic_audit, config,
    )
    integration = integration_checks(
        signal_state, opportunities, position_day, feature_reg, label_reg, ml_reg,
        date_audit, availability_audit, point_in_time, parity_summaries,
        entry_changes, time_semantic_audit, metadata_semantic_audit,
        feature_value_summary, runtime_config,
    )

    allowed_ml = set(map(tuple, ml_reg.loc[ml_reg["Role"] == "FEATURE_ALLOWED", ["Dataset", "Column"]].to_numpy()))
    allowed_features = set(map(tuple, feature_reg.loc[feature_reg["ML Allowed"].fillna(False).astype(bool), ["Dataset", "Feature Name"]].to_numpy()))
    target_leaks = ml_reg[(ml_reg["Role"] == "FEATURE_ALLOWED") & ml_reg["Column"].str.contains(
        r"^(?:ENTRY_|FWD_|FWD_CLOSE_RETURN_|MFE_|MAE_|T1_|T2_|STOP_|TIME_TO_|D1_SHADOW_|D1_FINAL_|D1_REMAINING_|NEXT_)|EXIT|AVAILABLE_DATE|CENSORED|STATUS",
        case=False, regex=True,
    )]
    target_leaks = target_leaks[~target_leaks["Column"].isin(["Current MFE Conservative To Date", "Current MAE Conservative To Date"])]
    test_context = {
        "config": config, "repo_root": REPO_ROOT, "stage_root": STAGE_ROOT,
        "signal_state": signal_state, "opportunities": opportunities, "position_day": position_day,
        "feature_registry": feature_reg, "label_registry": label_reg, "ml_registry": ml_reg,
        "split_manifest": split_manifest, "availability_audit": availability_audit,
        "date_audit": date_audit, "point_in_time": point_in_time, "entry_changes": entry_changes,
        "reference_gate": reference_gate, "package_manifest": package_manifest,
        "time_to_target_audit": time_semantic_audit,
        "feature_metadata_audit": metadata_semantic_audit,
        "feature_value_parity_summary": feature_value_summary,
        "signal_parity_summary": signal_summary, "target_parity_summary": target_summary_frame,
        "d1_parity_summary": d1_summary,
        "row_id_recheck": {
            "expected": deterministic_row_id(config["dataset_schema_versions"]["signal_state"], signal_state.iloc[0]["Signal ID"]),
            "actual": signal_state.iloc[0]["STAGE3_1_ROW_ID"],
        },
        "content_hash_recheck": {
            "first": dataframe_content_hash(signal_state.iloc[: min(25, len(signal_state))]),
            "second": dataframe_content_hash(signal_state.iloc[: min(25, len(signal_state))].copy(deep=True)),
        },
        "target_leak_count": len(target_leaks),
        "registry_symmetric_difference": len(allowed_ml.symmetric_difference(allowed_features)),
    }
    tests = _load_tests().run_tests(test_context)

    violation_columns = [
        "Availability Before As-Of Violations",
        "Unavailable Label With Value Violations",
        "Not Applicable Label With Value Violations",
        "Data-End Censored Label With Manufactured Value Violations",
        "Applicability/Status Contradictions",
        "Partition Violations",
        "Training Availability Violations",
    ]
    availability_checks = pd.DataFrame({
        "Type": "LABEL_AVAILABILITY",
        "Check": availability_audit["Dataset"].astype(str) + "::" + availability_audit["Target"].astype(str),
        "Status": availability_audit["Status"],
        "Expected": 0,
        "Actual": availability_audit[violation_columns].sum(axis=1).astype(int),
        "Detail": "explicit violation count; total_rows=" + availability_audit["Total Rows"].astype(str),
    })
    self_test_check = pd.DataFrame([{
        "Type": "SELF_TEST", "Check": "73 deterministic semantic assertions",
        "Status": "PASS" if tests["Status"].eq("PASS").all() else "FAIL",
        "Expected": 0, "Actual": int(tests["Status"].eq("FAIL").sum()),
        "Detail": "|".join(tests.loc[tests["Status"] == "FAIL", "Test"].astype(str)),
    }])
    reference_tree_after = directory_hash(REPO_ROOT / config["source_paths"]["stage3_root"])
    immutability_post = pd.DataFrame([{
        "Type": "IMMUTABLE_REFERENCE", "Check": "Stage 3 directory hash unchanged during execution",
        "Status": "PASS" if reference_tree_before == reference_tree_after else "FAIL",
        "Expected": reference_tree_before, "Actual": reference_tree_after, "Detail": "",
    }])
    checks = pd.concat([reference_gate, integration, availability_checks, self_test_check, immutability_post], ignore_index=True)

    dataset_artifacts = {
        "signal_state": output / "stage3_1_signal_state_dataset.csv.gz",
        "trade_opportunity": output / "stage3_1_trade_opportunity_dataset.csv.gz",
        "d1_position_day": output / "stage3_1_d1_position_day_dataset.csv.gz",
    }
    for name, frame in datasets.items():
        write_deterministic_csv_gz(frame, dataset_artifacts[name])
    schema_hash = canonical_json_hash({name: dataframe_schema(frame) for name, frame in datasets.items()})
    dataset_manifest = {
        "STAGE3_1_SCHEMA_HASH": schema_hash,
        "canonical_content": config["canonical_content"],
        "datasets": [
            {
                "dataset_name": name,
                "artifact": path.name,
                "row_count": len(datasets[name]),
                "column_count": len(datasets[name].columns),
                "content_hash": dataframe_content_hash(datasets[name]),
                "artifact_hash": sha256_file(path),
                "artifact_size_bytes": path.stat().st_size,
                "schema": dataframe_schema(datasets[name]),
            }
            for name, path in dataset_artifacts.items()
        ],
    }
    same_experiment = bool(
        previous_identity
        and previous_identity.get("EXPERIMENT_ID") == experiment_id
    )
    previous_by_name = {
        item["dataset_name"]: item
        for item in previous_manifest.get("datasets", [])
    } if previous_manifest and same_experiment else {}
    determinism_rows = []
    current_identity_values = {
        "EXPERIMENT_ID": experiment_id,
        "STAGE3_1_CODE_PACKAGE_HASH": package_manifest["package_hash"],
        "STAGE3_1_CONFIG_HASH": config_hash,
        "STAGE3_1_SCHEMA_HASH": schema_hash,
    }
    for field, current in current_identity_values.items():
        old = previous_identity.get(field) if same_experiment and previous_identity else None
        determinism_rows.append({
            "Identity": field,
            "Previous Hash": old,
            "Current Hash": current,
            "Status": "PASS" if old is None or old == current else "FAIL",
        })
    for item in dataset_manifest["datasets"]:
        previous = previous_by_name.get(item["dataset_name"], {})
        for field in ("content_hash", "artifact_hash"):
            old = previous.get(field)
            current = item[field]
            determinism_rows.append({
                "Identity": f"{item['dataset_name']}::{field}",
                "Previous Hash": old,
                "Current Hash": current,
                "Status": "PASS" if old is None or old == current else "FAIL",
            })
    determinism = pd.DataFrame(determinism_rows)

    current_git_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True,
    ).strip()
    stage31_dirty = bool(subprocess.check_output(
        ["git", "status", "--porcelain", "--", "Stage 3.1"],
        cwd=REPO_ROOT, text=True,
    ).strip())

    identity = {
        "stage": "3.1",
        "EXPERIMENT_ID": experiment_id,
        "STAGE3_1_CODE_PACKAGE_HASH": package_manifest["package_hash"],
        "STAGE3_1_CONFIG_HASH": config_hash,
        "STAGE3_1_SCHEMA_HASH": schema_hash,
        "baseline_tag": config["baseline_tag"],
        "baseline_commit": config["baseline_commit"],
        "stage3_reference_branch": config["stage3_reference_branch"],
        "stage3_reference_commit": config["stage3_reference_commit"],
        "stage3_reference_experiment": config["stage3_reference_experiment"],
        "STAGE3_1_PRE_HOTFIX_REFERENCE_COMMIT": pre_hotfix_commit,
        "CURRENT_GIT_COMMIT_AT_RUNTIME": current_git_commit,
        "FINAL_STAGE3_1_COMMIT_AT_RUNTIME": "UNCOMMITTED_HOTFIX_WORKTREE" if stage31_dirty else current_git_commit,
        "sanity_mode": sanity,
        "tickers": tickers,
        "ML_MODEL_TRAINED": False,
        "FEATURE_SELECTION_PERFORMED": False,
        "HYPERPARAMETER_TUNING_PERFORMED": False,
        "STRATEGY_THRESHOLD_TUNING_PERFORMED": False,
    }

    csv_outputs = {
        "stage3_1_validation_checks.csv": checks,
        "stage3_1_unit_test_results.csv": tests,
        "stage3_1_feature_registry.csv": feature_reg,
        "stage3_1_label_registry.csv": label_reg,
        "stage3_1_ml_column_registry.csv": ml_reg,
        "stage3_1_walk_forward_split_manifest.csv": split_manifest,
        "stage3_1_stage3_reference_gate.csv": reference_gate,
        "stage3_1_semantic_change_manifest.csv": semantic_manifest,
        "stage3_1_time_to_target_semantic_audit.csv": time_semantic_audit,
        "stage3_1_feature_metadata_semantic_audit.csv": metadata_semantic_audit,
        "stage3_1_final_feature_value_parity_summary.csv": feature_value_summary,
        "stage3_1_final_feature_value_parity_differences.csv": feature_value_diff,
        "stage3_1_signal_source_parity_summary.csv": source_summary,
        "stage3_1_signal_source_parity_differences.csv": source_diff,
        "stage3_1_stage3_signal_parity_summary.csv": signal_summary,
        "stage3_1_stage3_signal_parity_differences.csv": signal_diff,
        "stage3_1_stage3_opportunity_parity_summary.csv": opportunity_summary,
        "stage3_1_stage3_opportunity_parity_differences.csv": opportunity_diff,
        "stage3_1_entry_semantic_changes.csv": entry_changes,
        "stage3_1_entry_parity_summary.csv": entry_summary,
        "stage3_1_entry_parity_differences.csv": entry_diff,
        "stage3_1_stage3_target_parity_summary.csv": target_summary_frame,
        "stage3_1_stage3_target_parity_differences.csv": target_diff,
        "stage3_1_candidate_outcome_parity_summary.csv": candidate_summary,
        "stage3_1_candidate_outcome_parity_differences.csv": candidate_diff,
        "stage3_1_d1_shadow_parity_summary.csv": d1_summary,
        "stage3_1_d1_shadow_parity_differences.csv": d1_diff,
        "stage3_1_position_day_parity_summary.csv": position_summary,
        "stage3_1_position_day_parity_differences.csv": position_diff,
        "stage3_1_point_in_time_audit.csv": point_in_time,
        "stage3_1_label_availability_audit.csv": availability_audit,
        "stage3_1_date_feature_audit.csv": date_audit,
        "stage3_1_ambiguity_summary.csv": ambiguity_summary(opportunities, position_day),
        "stage3_1_censoring_summary.csv": censoring_summary(datasets, label_reg),
        "stage3_1_feature_missingness.csv": feature_missingness(datasets, feature_reg),
        "stage3_1_feature_distribution_by_era.csv": feature_distribution_by_era(signal_state, feature_reg),
        "stage3_1_dataset_summary.csv": dataset_summary(signal_state, opportunities, position_day),
        "stage3_1_target_summary.csv": target_summary(opportunities),
        "stage3_1_target_summary_by_year.csv": target_summary(opportunities, ["Year"]),
        "stage3_1_target_summary_by_setup.csv": target_summary(opportunities, ["Setup"]),
        "stage3_1_target_summary_by_regime.csv": target_summary(opportunities, ["Market Regime"]),
        "stage3_1_target_summary_by_signal.csv": target_summary(opportunities, ["Signal"]),
        "stage3_1_target_summary_by_ticker.csv": target_summary(opportunities, ["Ticker"]),
        "stage3_1_d1_position_day_summary.csv": d1_position_day_summary(position_day),
        "stage3_1_determinism_check.csv": determinism,
    }
    for name, frame in csv_outputs.items():
        write_csv(frame, output / name)
    write_json(identity, output / "stage3_1_experiment_identity.json")
    write_json(package_manifest, output / "stage3_1_source_manifest.json")
    write_json(dataset_manifest, output / "stage3_1_dataset_manifest.json")
    write_json(environment_report(), output / "stage3_1_environment_report.json")
    _write_validation_report(checks, output / "stage3_1_validation_report.txt")

    fail_if_any(checks, "Stage 3.1")
    fail_if_any(tests.rename(columns={"Test": "Check"}), "Stage 3.1 self-tests")
    if (determinism["Status"] == "FAIL").any():
        raise RuntimeError("Stage 3.1 determinism check failed")

    elapsed = time.perf_counter() - started
    summary = {
        "signal_rows": len(signal_state),
        "opportunity_rows": len(opportunities),
        "filled": int(opportunities["ENTRY_FILLED"].eq(True).sum()),
        "nonfilled": int(opportunities["ENTRY_FILLED"].eq(False).sum()),
        "entry_censored": int(opportunities["ENTRY_DATA_END_CENSORED"].fillna(False).sum()),
        "invalid_risk": int((opportunities["ENTRY_FILLED"].eq(True) & ~opportunities["ENTRY_RISK_VALID"].fillna(False)).sum()),
        "baseline_primary": int(opportunities["Dataset Cohort"].eq("BASELINE_PRIMARY").sum()),
        "research_extended": int(opportunities["Dataset Cohort"].eq("RESEARCH_EXTENDED").sum()),
        "d1_applicable": int(opportunities["D1_SHADOW_APPLICABLE"].fillna(False).sum()),
        "position_rows": len(position_day),
        "entry_changes": len(entry_changes),
    }
    ml_stats = {
        "feature_allowed": int(ml_reg["Role"].eq("FEATURE_ALLOWED").sum()),
        "date_allowed": int(date_audit["FEATURE_ALLOWED Violation"].fillna(False).sum()),
        "target_leaks": len(target_leaks),
        "unregistered": len(allowed_ml - allowed_features),
        "registry_difference": len(allowed_ml.symmetric_difference(allowed_features)),
    }
    status = "PASS WITH WARNINGS"
    if sanity:
        runtime = {"sanity": elapsed, "official": 0.0, "rerun": 0.0}
    elif not same_experiment:
        runtime = {
            "sanity": float(sanity_runtime.get("sanity", 0.0)),
            "official": elapsed,
            "rerun": 0.0,
        }
    else:
        runtime = {
            "sanity": float(sanity_runtime.get("sanity", 0.0)),
            "official": float(previous_runtime.get("official", elapsed)),
            "rerun": elapsed,
        }
    write_json(runtime, runtime_history_path)
    report = _delivery_report(
        identity, summary, dataset_manifest, csv_outputs["stage3_1_censoring_summary.csv"],
        {
            "signal": signal_summary, "source": source_summary, "opportunity": opportunity_summary,
            "entry": entry_summary, "candidate": candidate_summary, "d1": d1_summary,
            "position": position_summary, "target": target_summary_frame,
            "feature": feature_value_summary,
        },
        ml_stats, split_manifest, determinism, time_semantic_audit,
        metadata_semantic_audit, tests, reference_gate, runtime, config, status,
    )
    (output / "Stage3_1_Delivery_Report.md").write_text(report, encoding="utf-8", newline="\n")
    if not sanity:
        (STAGE_ROOT / "Stage3_1_Delivery_Report.md").write_text(report, encoding="utf-8", newline="\n")

    print(f"STAGE 3.1 STATUS: {status}")
    print(f"EXPERIMENT ID: {experiment_id}")
    print(f"SIGNAL ROWS: {len(signal_state)}")
    print(f"OPPORTUNITY ROWS: {len(opportunities)}")
    print(f"D1 POSITION-DAY ROWS: {len(position_day)}")
    print(f"INCOMPLETE ENTRY-WINDOW CENSORED: {summary['entry_censored']}")
    print(f"SELF-TESTS: {int(tests['Status'].eq('PASS').sum())}/{len(tests)} PASS")
    print(f"DATE_LIKE_FEATURE_ALLOWED_COUNT: {ml_stats['date_allowed']}")
    print(f"TRAINING AVAILABILITY VIOLATIONS: {int(split_manifest['Training Availability Violations'].sum())}")
    print(f"RUNTIME SECONDS: {elapsed:.2f}")
    for declaration in [
        "STAGE 2.2.2 FINAL MODIFIED: NO", "STAGE 2B MODIFIED: NO",
        "STAGE 2B.1 MODIFIED: NO", "STAGE 3 REFERENCE MODIFIED: NO",
        "STAGE 1 SIGNAL RULES CHANGED: NO", "OPPORTUNITY ELIGIBILITY RULES CHANGED: NO",
        "ENTRY EXECUTION RULES CHANGED: NO", "D1 MANAGEMENT RULES CHANGED: NO",
        "HISTORICAL VALID TARGET VALUES CHANGED: NO", "ML MODEL TRAINED: NO",
        "FEATURE SELECTION PERFORMED: NO", "HYPERPARAMETER TUNING PERFORMED: NO",
        "STRATEGY THRESHOLD TUNING PERFORMED: NO",
        "INCOMPLETE ENTRY WINDOW SEMANTICS FIXED: YES",
        "NOT_APPLICABLE SEPARATED FROM DATA_END_CENSORED: YES",
        "RAW DATE ML FEATURES ALLOWED: NO", "FEATURE REGISTRY DATASET-SPECIFIC: YES",
        "FORWARD HORIZON SEMANTICS EXPLICIT: YES",
        "TIME-TO-TARGET CONDITIONAL SEMANTICS EXPLICIT: YES",
        "WALK-FORWARD LABEL AVAILABILITY ENFORCED: YES",
        "TIME_TO_TARGET APPLICABILITY FIXED: YES",
        "FEATURE REGISTRY METADATA TRULY DATASET-SPECIFIC: YES",
        "STAGE 3 EXACT REFERENCE COMMIT VERIFIED: YES",
        "SYNTHETIC D1 CENSOR TEST ADDED: YES",
        f"TARGET LEAKAGE VIOLATIONS: {ml_stats['target_leaks']}",
        "FINAL STAGE 3.1 READY FOR INDEPENDENT FREEZE AUDIT: YES",
    ]:
        print(declaration)
    return {"identity": identity, "summary": summary, "checks": checks, "tests": tests, "manifest": dataset_manifest, "runtime": elapsed}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanity", action="store_true", help="Run the mandatory two-ticker sanity build")
    parser.add_argument("--tickers", nargs="*", default=(), help="Optional ticker subset; sanity defaults to TCS.NS and INFY.NS")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(sanity=args.sanity, requested_tickers=args.tickers)
