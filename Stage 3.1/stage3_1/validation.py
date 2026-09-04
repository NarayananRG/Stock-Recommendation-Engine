"""Immutable reference, parity, leakage, and semantic acceptance gates."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from hashing import sha256_file


def _row(check_type: str, check: str, passed: bool, expected: Any, actual: Any, detail: str = "") -> dict[str, Any]:
    return {
        "Type": check_type,
        "Check": check,
        "Status": "PASS" if passed else "FAIL",
        "Expected": expected,
        "Actual": actual,
        "Detail": detail,
    }


def stage3_reference_gate(repo_root: Path, config: Mapping[str, Any]) -> pd.DataFrame:
    paths = config["source_paths"]
    rows: list[dict[str, Any]] = []

    def resolve(ref: str) -> str:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            cwd=repo_root,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip() if completed.returncode == 0 else "MISSING"

    tag = subprocess.check_output(["git", "rev-list", "-n", "1", config["baseline_tag"]], cwd=repo_root, text=True).strip()
    rows.append(_row("IMMUTABLE_REFERENCE", "Stage 2B.1 frozen tag commit", tag == config["baseline_commit"], config["baseline_commit"], tag))
    frozen = ["Stage 2.2.2 Final", "Stage 2B", "Stage 2B.1"]
    frozen_diff = subprocess.run(["git", "diff", "--quiet", config["baseline_tag"], "--", *frozen], cwd=repo_root).returncode
    rows.append(_row("IMMUTABLE_REFERENCE", "Frozen dependency folders unchanged", frozen_diff == 0, "NO DIFFERENCE", "NO DIFFERENCE" if frozen_diff == 0 else "DIFFERENCE"))
    pre_hotfix = resolve(f"{config['stage3_1_pre_hotfix_reference_commit']}^{{commit}}")
    rows.append(_row(
        "IMMUTABLE_REFERENCE", "Stage 3.1 pre-hotfix reference commit exists",
        pre_hotfix == config["stage3_1_pre_hotfix_reference_commit"],
        config["stage3_1_pre_hotfix_reference_commit"], pre_hotfix,
    ))
    branch_ref = f"refs/remotes/origin/{config['stage3_reference_branch']}"
    branch_commit = resolve(branch_ref)
    rows.append(_row(
        "IMMUTABLE_REFERENCE", "Stage 3 reference branch commit",
        branch_commit == config["stage3_reference_commit"],
        config["stage3_reference_commit"], branch_commit, branch_ref,
    ))
    stage3_diff = subprocess.run(
        ["git", "diff", "--quiet", config["stage3_reference_commit"], "--", "Stage 3"],
        cwd=repo_root,
    ).returncode
    rows.append(_row(
        "IMMUTABLE_REFERENCE", "Stage 3 working directory equals exact reference commit",
        stage3_diff == 0, "NO DIFFERENCE", "NO DIFFERENCE" if stage3_diff == 0 else "DIFFERENCE",
        config["stage3_reference_commit"],
    ))
    reference_tree = resolve(f"{config['stage3_reference_commit']}:Stage 3")
    current_tree = resolve("HEAD:Stage 3")
    rows.append(_row(
        "IMMUTABLE_REFERENCE", "Stage 3 git tree hash at current HEAD",
        current_tree == reference_tree and reference_tree != "MISSING",
        reference_tree, current_tree,
    ))

    identity = json.loads((repo_root / paths["stage3_identity"]).read_text(encoding="utf-8"))
    rows.append(_row("STAGE3_REFERENCE", "Stage 3 experiment", identity.get("experiment_id") == config["stage3_reference_experiment"], config["stage3_reference_experiment"], identity.get("experiment_id")))
    rows.append(_row("STAGE3_REFERENCE", "Stage 3 code package hash", identity.get("STAGE3_CODE_PACKAGE_HASH") == config["stage3_reference_code_package_hash"], config["stage3_reference_code_package_hash"], identity.get("STAGE3_CODE_PACKAGE_HASH")))
    rows.append(_row("STAGE3_REFERENCE", "Stage 3 schema hash", identity.get("STAGE3_SCHEMA_HASH") == config["stage3_reference_schema_hash"], config["stage3_reference_schema_hash"], identity.get("STAGE3_SCHEMA_HASH")))
    manifest = json.loads((repo_root / paths["stage3_dataset_manifest"]).read_text(encoding="utf-8"))
    by_name = {str(item["dataset_name"]): item for item in manifest["datasets"]}
    for dataset, expected in config["stage3_reference_datasets"].items():
        actual = by_name.get(dataset, {})
        rows.append(_row("STAGE3_REFERENCE", f"{dataset} row count", int(actual.get("row_count", -1)) == int(expected["rows"]), expected["rows"], actual.get("row_count")))
        rows.append(_row("STAGE3_REFERENCE", f"{dataset} logical content hash", actual.get("content_hash") == expected["content_hash"], expected["content_hash"], actual.get("content_hash")))
        artifact = repo_root / paths["stage3_results"] / str(actual.get("artifact", ""))
        artifact_hash = sha256_file(artifact) if artifact.is_file() else "MISSING"
        rows.append(_row("STAGE3_REFERENCE", f"{dataset} artifact hash", artifact_hash == actual.get("artifact_hash"), actual.get("artifact_hash"), artifact_hash))
    frame = pd.DataFrame(rows)
    fail_if_any(frame, "Stage 3.1 reference gate")
    return frame


MATERIAL_SIGNAL_COLUMNS = [
    "Signal ID", "Ticker", "Signal Date", "Signal", "Setup", "Technical Score",
    "Actionability Score", "Entry Low", "Entry High", "Stop Loss", "Target 1", "Target 2",
]


def dataframe_parity(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    key_columns: Sequence[str],
    compare_columns: Sequence[str],
    label: str,
    tolerance: float = 1e-12,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    left = reference[list(key_columns) + list(compare_columns)].copy()
    right = current[list(key_columns) + list(compare_columns)].copy()
    merged = left.merge(right, on=list(key_columns), how="outer", suffixes=(" Reference", " Stage3.1"), indicator=True)
    differences: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        key = "|".join(str(row[column]) for column in key_columns)
        if row["_merge"] != "both":
            differences.append({"Key": key, "Field": "ROW_MEMBERSHIP", "Reference": row["_merge"], "Stage 3.1": row["_merge"], "Absolute Difference": np.nan})
            continue
        for column in compare_columns:
            a, b = row[f"{column} Reference"], row[f"{column} Stage3.1"]
            if pd.isna(a) and pd.isna(b):
                continue
            if isinstance(a, (float, int, np.number)) and isinstance(b, (float, int, np.number)):
                equal = np.isclose(float(a), float(b), rtol=0, atol=tolerance, equal_nan=True)
                absolute = abs(float(a) - float(b)) if not equal else 0.0
            else:
                equal = str(a) == str(b)
                absolute = np.nan
            if not equal:
                differences.append({"Key": key, "Field": column, "Reference": a, "Stage 3.1": b, "Absolute Difference": absolute})
    diff = pd.DataFrame(differences, columns=["Key", "Field", "Reference", "Stage 3.1", "Absolute Difference"])
    summary = pd.DataFrame([{
        "Comparison": label,
        "Reference Rows": len(reference),
        "Stage 3.1 Rows": len(current),
        "Difference Count": len(diff),
        "Status": "PASS" if diff.empty else "FAIL",
    }])
    return summary, diff


def entry_parity(
    reference: pd.DataFrame,
    current: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    stable = current["ENTRY_FILLED"].eq(True).fillna(False) | current["ENTRY_WINDOW_COMPLETE"].fillna(False)
    ids = set(current.loc[stable, "Signal ID"])
    left = reference[reference["Signal ID"].isin(ids)]
    right = current[current["Signal ID"].isin(ids)]
    fields = ["ENTRY_FILLED", "ENTRY_DATE", "ENTRY_METHOD", "NOMINAL_ENTRY", "EXECUTED_ENTRY", "ENTRY_SESSIONS_TO_FILL"]
    return dataframe_parity(left, right, ["Signal ID"], fields, "COMPLETE_WINDOW_OR_FILLED_ENTRY_PARITY", tolerance=1e-10)


def position_day_parity(reference: pd.DataFrame, current: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    fields = [
        "Days Held", "Executed Entry", "Initial Stop", "Previous Session Stop",
        "Current Stop", "Original T1", "Original T2", "Current Close", "Current R",
        "Current MFE Conservative To Date", "Current MAE Conservative To Date",
        "Stop Revision Count", "D1_EXIT_NEXT_SESSION", "D1_REMAINING_SESSIONS",
        "D1_REMAINING_NET_R", "D1_FINAL_EXIT_REASON",
    ]
    return dataframe_parity(reference, current, ["Signal ID", "Management Date"], fields, "D1_POSITION_DAY_CURRENT_STATE_PARITY", tolerance=1e-10)


def integration_checks(
    signal_state: pd.DataFrame,
    opportunities: pd.DataFrame,
    position_day: pd.DataFrame,
    feature_registry: pd.DataFrame,
    label_registry: pd.DataFrame,
    ml_registry: pd.DataFrame,
    date_audit: pd.DataFrame,
    availability_audit: pd.DataFrame,
    point_in_time: pd.DataFrame,
    parity_summaries: Sequence[pd.DataFrame],
    semantic_changes: pd.DataFrame,
    time_to_target_audit: pd.DataFrame,
    feature_metadata_audit: pd.DataFrame,
    feature_value_parity_summary: pd.DataFrame,
    config: Mapping[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    add = lambda check, passed, expected, actual, detail="": rows.append(_row("INTEGRATION", check, bool(passed), expected, actual, detail))
    add("Signal row count", len(signal_state) == config["stage3_reference_datasets"]["signal_state"]["rows"], config["stage3_reference_datasets"]["signal_state"]["rows"], len(signal_state))
    add("Opportunity row count", len(opportunities) == config["stage3_reference_datasets"]["trade_opportunity"]["rows"], config["stage3_reference_datasets"]["trade_opportunity"]["rows"], len(opportunities))
    add("D1 position-day row count", len(position_day) == config["stage3_reference_datasets"]["d1_position_day"]["rows"], config["stage3_reference_datasets"]["d1_position_day"]["rows"], len(position_day))
    add("Signal IDs unique", signal_state["Signal ID"].is_unique, len(signal_state), signal_state["Signal ID"].nunique())
    add("Opportunity IDs unique", opportunities["Signal ID"].is_unique, len(opportunities), opportunities["Signal ID"].nunique())
    add("Feature registry composite key unique", not feature_registry.duplicated(["Dataset", "Feature Name"]).any(), "0", int(feature_registry.duplicated(["Dataset", "Feature Name"]).sum()))

    allowed_ml = set(map(tuple, ml_registry.loc[ml_registry["Role"] == "FEATURE_ALLOWED", ["Dataset", "Column"]].to_numpy()))
    allowed_features = set(map(tuple, feature_registry.loc[feature_registry["ML Allowed"].fillna(False).astype(bool), ["Dataset", "Feature Name"]].to_numpy()))
    add("ML registry equals feature registry per dataset", allowed_ml == allowed_features, "0 symmetric differences", len(allowed_ml.symmetric_difference(allowed_features)))
    date_violations = date_audit["FEATURE_ALLOWED Violation"].fillna(False).astype(bool) if not date_audit.empty else pd.Series(dtype=bool)
    add("DATE_LIKE_FEATURE_ALLOWED_COUNT", not date_violations.any(), 0, int(date_violations.sum()))
    nifty = ml_registry[(ml_registry["Column"] == "NIFTY Feature Source Date") & (ml_registry["Role"] == "FEATURE_ALLOWED")]
    add("NIFTY Feature Source Date not FEATURE_ALLOWED", nifty.empty, 0, len(nifty))

    leakage_pattern = r"^(?:ENTRY_|FWD_|FWD_CLOSE_RETURN_|MFE_|MAE_|T1_|T2_|STOP_|TIME_TO_|D1_SHADOW_|D1_FINAL_|D1_REMAINING_|NEXT_)|EXIT|AVAILABLE_DATE|CENSORED|STATUS"
    leaks = ml_registry[(ml_registry["Role"] == "FEATURE_ALLOWED") & ml_registry["Column"].str.contains(leakage_pattern, case=False, regex=True)]
    allowed_to_date = leaks["Column"].isin(["Current MFE Conservative To Date", "Current MAE Conservative To Date"])
    leaks = leaks[~allowed_to_date]
    add("No target or future field FEATURE_ALLOWED", leaks.empty, 0, len(leaks), "|".join(leaks["Column"].head(10)))

    partial_nonfill = opportunities[
        opportunities["ENTRY_FILLED"].eq(False)
        & ~opportunities["ENTRY_WINDOW_COMPLETE"].fillna(False)
    ]
    add("No incomplete window labeled non-fill", partial_nonfill.empty, 0, len(partial_nonfill))
    entry_alias_diff = (
        opportunities["ENTRY_CENSORED"].fillna(False).astype(bool)
        != opportunities["ENTRY_DATA_END_CENSORED"].fillna(False).astype(bool)
    )
    add("ENTRY_CENSORED is exact data-end alias", not entry_alias_diff.any(), 0, int(entry_alias_diff.sum()))
    nonapp_censored = (
        (~opportunities["T1_APPLICABLE"].fillna(False))
        & opportunities["T1_DATA_END_CENSORED"].fillna(False)
    ) | (
        (~opportunities["T2_APPLICABLE"].fillna(False))
        & opportunities["T2_DATA_END_CENSORED"].fillna(False)
    )
    add("NOT_APPLICABLE distinct from DATA_END_CENSORED", not nonapp_censored.any(), 0, int(nonapp_censored.sum()))
    d1_nonapp_censored = (~opportunities["D1_SHADOW_APPLICABLE"].fillna(False)) & opportunities["D1_SHADOW_DATA_END_CENSORED"].fillna(False)
    add("D1 non-applicable rows are not censored", not d1_nonapp_censored.any(), 0, int(d1_nonapp_censored.sum()))
    add("Label availability checks report zero violations", not (availability_audit["Status"] == "FAIL").any(), 0, int((availability_audit["Status"] == "FAIL").sum()))
    add("Walk-forward training availability violations", int(availability_audit["Training Availability Violations"].sum()) == 0, 0, int(availability_audit["Training Availability Violations"].sum()))
    add("Point-in-time prefix audit", not (point_in_time["Status"] == "FAIL").any(), 0, int((point_in_time["Status"] == "FAIL").sum()))
    required_tickers = set(config["audit_tickers"])
    present_tickers = set(point_in_time["Ticker"].astype(str)) if "Ticker" in point_in_time else set()
    add("Required prefix-audit tickers present", required_tickers.issubset(present_tickers), "|".join(sorted(required_tickers)), "|".join(sorted(present_tickers)))
    add("Entry semantic changes only incomplete windows", semantic_changes.empty or semantic_changes["Reason"].isin(["NO_FUTURE_SESSION", "INCOMPLETE_ENTRY_WINDOW"]).all(), "ONLY INCOMPLETE WINDOW", "|".join(sorted(set(semantic_changes.get("Reason", [])))))
    time_failures = int(time_to_target_audit["Status"].ne("PASS").sum())
    add("Time-to-target applicability and partitions", time_failures == 0, 0, time_failures)
    metadata_failures = int(feature_metadata_audit["Status"].ne("PASS").sum())
    add("Feature metadata semantic audit", metadata_failures == 0, 0, metadata_failures)
    feature_value_differences = int(feature_value_parity_summary["Difference Count"].sum())
    add("Pre-hotfix feature-value parity", feature_value_differences == 0, 0, feature_value_differences)
    for summary in parity_summaries:
        if summary.empty:
            continue
        record = summary.iloc[0]
        name = str(record.get("Comparison", "PARITY"))
        add(name, record["Status"] == "PASS", "PASS", record["Status"], f"differences={record.get('Difference Count', '')}")
    return pd.DataFrame(rows)


def fail_if_any(checks: pd.DataFrame, context: str) -> None:
    failed = checks[checks["Status"] != "PASS"]
    if not failed.empty:
        raise RuntimeError(f"{context} failed: " + "; ".join(failed["Check"].astype(str)))
