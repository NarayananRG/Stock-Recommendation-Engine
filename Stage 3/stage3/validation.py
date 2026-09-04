"""Fail-closed Stage 3 gates, parity checks, and leakage validation."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from hashing import canonical_json_hash, matching_text_hash, sha256_bytes, sha256_file


def _row(check_type: str, check: str, passed: bool, expected: Any, actual: Any, detail: str = "") -> dict[str, Any]:
    return {"Type": check_type, "Check": check, "Status": "PASS" if passed else "FAIL", "Expected": expected, "Actual": actual, "Detail": detail}


def baseline_gate(repo_root: Path, config: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    expected = config["expected_hashes"]
    paths = config["source_paths"]
    rows: list[dict[str, Any]] = []
    tag = subprocess.check_output(["git", "rev-list", "-n", "1", config["baseline_tag"]], cwd=repo_root, text=True).strip()
    rows.append(_row("IMMUTABLE_BASELINE", "frozen git tag resolution", tag == config["baseline_commit"], config["baseline_commit"], tag))
    frozen_dirs = ["Stage 2B.1", "Stage 2B", "Stage 2.2.2 Final"]
    diff = subprocess.run(["git", "diff", "--quiet", config["baseline_tag"], "--", *frozen_dirs], cwd=repo_root).returncode
    rows.append(_row("IMMUTABLE_BASELINE", "frozen dependency tree equals tag", diff == 0, "NO DIFFERENCE", "NO DIFFERENCE" if diff == 0 else "DIFFERENCE"))

    identity = json.loads((repo_root / paths["stage2b1_identity"]).read_text(encoding="utf-8"))
    rows.append(_row("IMMUTABLE_BASELINE", "Stage 2B.1 experiment ID", identity.get("EXPERIMENT_ID") == config["source_experiment_id"], config["source_experiment_id"], identity.get("EXPERIMENT_ID")))
    source_manifest = json.loads((repo_root / paths["stage2b1_source_manifest"]).read_text(encoding="utf-8"))
    package_rows = []
    line_endings = {}
    for item in source_manifest["sources"]:
        value, mode = matching_text_hash(repo_root / "Stage 2B.1" / item["relative_path"], item["sha256"])
        package_rows.append({"relative_path": item["relative_path"], "sha256": value})
        line_endings[item["relative_path"]] = mode
    package_hash = canonical_json_hash(package_rows)
    rows.append(_row("HASH_GATE", "Stage 2B.1 source package hash", package_hash == expected["STAGE2B1_PACKAGE_HASH"], expected["STAGE2B1_PACKAGE_HASH"], package_hash, json.dumps(line_endings, sort_keys=True)))

    source_keys = (("STAGE21_CODE_HASH", "stage21"), ("STAGE221_CODE_HASH", "stage221"), ("STAGE222_FINAL_CODE_HASH", "stage222"))
    source_modes = {}
    for key, path_key in source_keys:
        actual, mode = matching_text_hash(repo_root / paths[path_key], expected[key])
        source_modes[key] = mode
        rows.append(_row("HASH_GATE", key, actual == expected[key], expected[key], actual, f"line_endings={mode}"))

    stage222_identity_path = repo_root / "Stage 2.2.2 Final/stage2_2_2/results/stage2_2_2_final_experiment_identity.json"
    stage222_identity = json.loads(stage222_identity_path.read_text(encoding="utf-8"))
    strategy_hash = canonical_json_hash(stage222_identity["strategy"])
    execution_hash = canonical_json_hash(stage222_identity["execution"])
    rows.append(_row("HASH_GATE", "STRATEGY_HASH", strategy_hash == expected["STRATEGY_HASH"], expected["STRATEGY_HASH"], strategy_hash))
    rows.append(_row("HASH_GATE", "EXECUTION_BASELINE_HASH", execution_hash == expected["EXECUTION_BASELINE_HASH"], expected["EXECUTION_BASELINE_HASH"], execution_hash))

    frozen_dir = repo_root / paths["frozen_data"]
    manifest = json.loads((frozen_dir / "manifest.json").read_text(encoding="utf-8"))
    content = []
    for item in sorted(manifest["files"], key=lambda value: value["ticker"]):
        actual = sha256_file(frozen_dir / item["filename"])
        rows.append(_row("FROZEN_DATA", f"file hash {item['ticker']}", actual == item["sha256"], item["sha256"], actual))
        content.append({"ticker": item["ticker"], "filename": item["filename"], "sha256": item["sha256"]})
    data_hash = canonical_json_hash(content)
    rows.append(_row("HASH_GATE", "DATA_CONTENT_HASH", data_hash == expected["DATA_CONTENT_HASH"], expected["DATA_CONTENT_HASH"], data_hash))

    artifact_manifest = pd.read_csv(repo_root / "Stage 2.2.2 Final/artifact_manifest.csv")
    candidate_manifest = artifact_manifest[artifact_manifest["path"].astype(str).str.endswith("accepted_results/stage2_2_2_candidate_signal_log.csv.gz")]
    candidate_parts = sorted(repo_root.glob(paths["accepted_candidates_glob"]))
    reconstructed_hash = sha256_bytes(b"".join(part.read_bytes() for part in candidate_parts))
    expected_candidate_hash = str(candidate_manifest.iloc[0]["sha256"]) if len(candidate_manifest) == 1 else "MISSING_MANIFEST_ROW"
    rows.append(_row("SOURCE_ARTIFACT", "accepted candidate artifact reconstructed hash", reconstructed_hash == expected_candidate_hash, expected_candidate_hash, reconstructed_hash, f"parts={len(candidate_parts)}"))
    frame = pd.DataFrame(rows)
    if (frame["Status"] != "PASS").any():
        raise RuntimeError("Immutable baseline gate failed: " + "; ".join(frame.loc[frame["Status"] != "PASS", "Check"]))
    metadata = {"tag_commit": tag, "package_hash": package_hash, "strategy_hash": strategy_hash, "execution_hash": execution_hash, "data_hash": data_hash, "candidate_artifact_hash": reconstructed_hash, "line_endings": {**line_endings, **source_modes}}
    return frame, metadata


def source_parity(source: pd.DataFrame, signal_state: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = ["Signal ID"]
    material = ["Ticker", "Signal Date", "Signal", "Setup", "Technical Score", "Actionability Score", "Entry Low", "Entry High", "Stop Loss", "Target 1", "Target 2"]
    left = source[keys + material].copy(); right = signal_state[keys + material].copy()
    left["Signal Date"] = pd.to_datetime(left["Signal Date"]).dt.normalize(); right["Signal Date"] = pd.to_datetime(right["Signal Date"]).dt.normalize()
    merged = left.merge(right, on=keys, how="outer", suffixes=(" Source", " Stage3"), indicator=True)
    differences = []
    for _, row in merged.iterrows():
        if row["_merge"] != "both":
            differences.append({"Signal ID": row["Signal ID"], "Field": "ROW_MEMBERSHIP", "Source Value": row["_merge"], "Stage 3 Value": row["_merge"], "Difference Type": str(row["_merge"])})
            continue
        for column in material:
            a, b = row[f"{column} Source"], row[f"{column} Stage3"]
            if pd.isna(a) and pd.isna(b):
                continue
            if column in {"Technical Score", "Actionability Score", "Entry Low", "Entry High", "Stop Loss", "Target 1", "Target 2"}:
                equal = np.isclose(float(a), float(b), rtol=0, atol=1e-12, equal_nan=True)
            else:
                equal = a == b
            if not equal:
                differences.append({"Signal ID": row["Signal ID"], "Field": column, "Source Value": a, "Stage 3 Value": b, "Difference Type": "VALUE_MISMATCH"})
    diff = pd.DataFrame(differences, columns=["Signal ID", "Field", "Source Value", "Stage 3 Value", "Difference Type"])
    summary = pd.DataFrame([{
        "Source Rows": len(source), "Stage 3 Rows": len(signal_state), "Source Unique Signal IDs": source["Signal ID"].nunique(), "Stage 3 Unique Signal IDs": signal_state["Signal ID"].nunique(), "Difference Count": len(diff), "Status": "PASS" if diff.empty else "FAIL"
    }])
    return summary, diff


def candidate_outcome_parity(source: pd.DataFrame, opportunities: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    reference = source[source["Candidate Status"].notna()].copy()
    actual = opportunities.set_index("Signal ID")
    differences = []
    numeric = {
        "Candidate Nominal Entry": ("NOMINAL_ENTRY", 1e-10),
        "Candidate Executed Entry": ("EXECUTED_ENTRY", 1e-10),
        "Candidate R Multiple": ("BASELINE_COMPAT_T1_NET_R", 1e-9),
        "Candidate Bars Held": ("BASELINE_COMPAT_T1_BARS_HELD", 0),
    }
    string = {
        "Candidate Entry Method": "ENTRY_METHOD",
        "Candidate Exit Reason": "BASELINE_COMPAT_T1_EXIT_REASON",
    }
    dates = {"Candidate Entry Date": "ENTRY_DATE", "Candidate Exit Date": "BASELINE_COMPAT_T1_EXIT_DATE"}
    for _, row in reference.iterrows():
        signal_id = row["Signal ID"]
        if signal_id not in actual.index:
            differences.append({"Signal ID": signal_id, "Field": "OPPORTUNITY_MEMBERSHIP", "Reference": row["Candidate Status"], "Stage 3": "MISSING", "Absolute Difference": np.nan})
            continue
        current = actual.loc[signal_id]
        status = str(row["Candidate Status"])
        expected_filled = status in {"SIMULATED", "INVALID_RISK"}
        actual_fill = current["ENTRY_FILLED"]
        if pd.isna(actual_fill):
            if expected_filled:
                differences.append({"Signal ID": signal_id, "Field": "ENTRY_FILLED", "Reference": expected_filled, "Stage 3": "CENSORED", "Absolute Difference": np.nan})
        elif bool(actual_fill) != expected_filled:
            differences.append({"Signal ID": signal_id, "Field": "ENTRY_FILLED", "Reference": expected_filled, "Stage 3": actual_fill, "Absolute Difference": np.nan})
        if status == "INVALID_RISK" and bool(current["ENTRY_RISK_VALID"]):
            differences.append({"Signal ID": signal_id, "Field": "ENTRY_RISK_VALID", "Reference": False, "Stage 3": True, "Absolute Difference": np.nan})
        if status != "SIMULATED":
            continue
        for ref_col, (actual_col, tolerance) in numeric.items():
            a, b = float(row[ref_col]), float(current[actual_col])
            if abs(a - b) > tolerance:
                differences.append({"Signal ID": signal_id, "Field": ref_col, "Reference": a, "Stage 3": b, "Absolute Difference": abs(a-b)})
        for ref_col, actual_col in string.items():
            if str(row[ref_col]) != str(current[actual_col]):
                differences.append({"Signal ID": signal_id, "Field": ref_col, "Reference": row[ref_col], "Stage 3": current[actual_col], "Absolute Difference": np.nan})
        for ref_col, actual_col in dates.items():
            a, b = pd.Timestamp(row[ref_col]).normalize(), pd.Timestamp(current[actual_col]).normalize()
            if a != b:
                differences.append({"Signal ID": signal_id, "Field": ref_col, "Reference": a, "Stage 3": b, "Absolute Difference": np.nan})
    diff = pd.DataFrame(differences, columns=["Signal ID", "Field", "Reference", "Stage 3", "Absolute Difference"])
    summary = pd.DataFrame([{"Reference Rows": len(reference), "Comparable Simulated Rows": int((reference["Candidate Status"] == "SIMULATED").sum()), "Difference Count": len(diff), "Status": "PASS" if diff.empty else "FAIL"}])
    return summary, diff


def d1_shadow_parity(repo_root: Path, config: Mapping[str, Any], opportunities: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    paired = pd.read_csv(repo_root / config["source_paths"]["stage2b1_paired_d1"], compression="gzip", low_memory=False)
    paired = paired[paired["Policy"] == "D1_TRAIL_ONLY"].copy()
    paired = paired[paired["Ticker"].isin(set(opportunities["Ticker"].astype(str)))]
    trades = pd.read_csv(repo_root / config["source_paths"]["stage2b1_trade_log"], compression="gzip", low_memory=False)
    trades = trades[trades["Policy"] == "D1_TRAIL_ONLY"].drop_duplicates("Signal ID").set_index("Signal ID")
    actual = opportunities.set_index("Signal ID")
    differences = []
    for _, row in paired.iterrows():
        signal_id = row["Signal ID"]
        if signal_id not in actual.index:
            differences.append({"Signal ID": signal_id, "Field": "ROW_MEMBERSHIP", "Reference": "PAIRED_D1", "Stage 3": "MISSING", "Absolute Difference": np.nan})
            continue
        current = actual.loc[signal_id]
        comparisons = {
            "Shadow Exit Date": (pd.Timestamp(row["Shadow Exit Date"]).normalize(), pd.Timestamp(current["D1_SHADOW_EXIT_DATE"]).normalize(), None),
            "Shadow Exit Reason": (str(row["Shadow Exit Reason"]), str(current["D1_SHADOW_EXIT_REASON"]), None),
            "Shadow Bars Held": (int(row["Shadow Bars Held"]), int(current["D1_SHADOW_BARS_HELD"]), 0),
            "Shadow Executed Exit": (float(row["Shadow Executed Exit"]), float(current["D1_SHADOW_EXECUTED_EXIT"]), 1e-8),
            "Shadow R": (float(row["Shadow R"]), float(current["D1_SHADOW_NET_R"]), 1e-8),
        }
        if signal_id in trades.index:
            comparisons["Stop Revision Count"] = (int(trades.at[signal_id, "Stop Revision Count"]), int(current["D1_SHADOW_STOP_REVISION_COUNT"]), 0)
        for field, (a, b, tolerance) in comparisons.items():
            equal = (a == b) if tolerance is None else abs(float(a) - float(b)) <= tolerance
            if not equal:
                differences.append({"Signal ID": signal_id, "Field": field, "Reference": a, "Stage 3": b, "Absolute Difference": abs(float(a)-float(b)) if tolerance is not None else np.nan})
    diff = pd.DataFrame(differences, columns=["Signal ID", "Field", "Reference", "Stage 3", "Absolute Difference"])
    summary = pd.DataFrame([{"Comparable D1 Paired Rows": len(paired), "Difference Count": len(diff), "Status": "PASS" if diff.empty else "FAIL"}])
    return summary, diff


def ml_column_registry(datasets: Mapping[str, pd.DataFrame], feature_names: Iterable[str], label_names: Iterable[str]) -> pd.DataFrame:
    features, labels = set(feature_names), set(label_names)
    identifiers = {"Signal ID", "Ticker", "Signal Date", "STAGE3_ROW_ID", "Stage 3 Experiment ID", "Source Experiment ID", "Dataset Cohort", "Entry Date", "Management Date", "Feature As-Of Date"}
    rows = []
    for dataset, frame in datasets.items():
        for column in frame.columns:
            if column in identifiers or column.endswith("ROW_ID"):
                role = "IDENTIFIER"
            elif "AVAILABLE_DATE" in column or "CENSORED" in column or column.endswith("SEMANTICS") or column.endswith("AMBIGUOUS") or column.endswith("RESOLUTION_DATE"):
                role = "LABEL_METADATA"
            elif column.startswith("Current ") and ("Full Bar Diagnostic" in column or "FULL_BAR_DIAGNOSTIC" in column):
                role = "FEATURE_DIAGNOSTIC_ONLY"
            elif column in labels or column.startswith(("FWD_CLOSE_RETURN_", "MFE_R_", "MAE_R_", "MFE_PCT_", "MAE_PCT_", "TIME_TO_", "D1_REMAINING_", "NEXT_")) or column in {"ENTRY_FILLED", "ENTRY_SESSIONS_TO_FILL", "T1_BEFORE_STOP_63", "T2_BEFORE_STOP_63", "STOP_BEFORE_T1_63", "STOP_BEFORE_T2_63", "D1_EXIT_NEXT_SESSION", "D1_FINAL_EXIT_REASON", "ORIGINAL_T2_REACHED_BEFORE_D1_EXIT"}:
                role = "TARGET"
            elif column.startswith("Candidate ") or column.startswith("BASELINE_COMPAT_") or column.startswith("D1_SHADOW_"):
                role = "LEAKAGE_EXCLUDE"
            elif column in features:
                role = "FEATURE_ALLOWED"
            elif "Full Bar Diagnostic" in column or "FULL_BAR_DIAGNOSTIC" in column:
                role = "FEATURE_DIAGNOSTIC_ONLY"
            else:
                role = "LEAKAGE_EXCLUDE"
            rows.append({"Dataset": dataset, "Column": column, "Role": role})
    return pd.DataFrame(rows).drop_duplicates(["Dataset", "Column"]).sort_values(["Dataset", "Column"]).reset_index(drop=True)


def integration_checks(
    signal_state: pd.DataFrame,
    opportunities: pd.DataFrame,
    position_day: pd.DataFrame,
    feature_registry: pd.DataFrame,
    ml_registry: pd.DataFrame,
    point_in_time: pd.DataFrame,
    source_summary: pd.DataFrame,
    candidate_summary: pd.DataFrame,
    d1_summary: pd.DataFrame,
    config: Mapping[str, Any],
) -> pd.DataFrame:
    rows = []
    add = lambda check, passed, expected, actual, detail="": rows.append(_row("INTEGRATION", check, bool(passed), expected, actual, detail))
    add("Signal ID unique", signal_state["Signal ID"].is_unique, len(signal_state), signal_state["Signal ID"].nunique())
    add("Signal Stage 3 Row ID unique", signal_state["STAGE3_ROW_ID"].is_unique, len(signal_state), signal_state["STAGE3_ROW_ID"].nunique())
    add("Opportunity Stage 3 Row ID unique", opportunities["STAGE3_ROW_ID"].is_unique, len(opportunities), opportunities["STAGE3_ROW_ID"].nunique())
    add("Position-day Stage 3 Row ID unique", position_day["STAGE3_ROW_ID"].is_unique, len(position_day), position_day["STAGE3_ROW_ID"].nunique())
    add("No fake levels in eligible opportunities", opportunities[["Entry Low", "Entry High", "Stop Loss", "Target 1", "Target 2"]].notna().all().all(), "ALL PRESENT", int(opportunities[["Entry Low", "Entry High", "Stop Loss", "Target 1", "Target 2"]].isna().sum().sum()))
    excluded = set(config["explicitly_excluded_signals"])
    add("Excluded signals absent from opportunities", not opportunities["Signal"].isin(excluded).any(), "0", int(opportunities["Signal"].isin(excluded).sum()))
    add("Source parity", source_summary.iloc[0]["Status"] == "PASS", "PASS", source_summary.iloc[0]["Status"])
    add("Candidate outcome parity", candidate_summary.iloc[0]["Status"] == "PASS", "PASS", candidate_summary.iloc[0]["Status"])
    add("D1 shadow parity", d1_summary.iloc[0]["Status"] == "PASS", "PASS", d1_summary.iloc[0]["Status"])
    add("Point-in-time prefix invariance", not (point_in_time["Status"] == "FAIL").any(), "0 FAIL", int((point_in_time["Status"] == "FAIL").sum()))
    add("Signal market source is not future", (pd.to_datetime(signal_state["NIFTY Feature Source Date"]) <= pd.to_datetime(signal_state["Feature As-Of Date"])).all(), "source<=asof", int((pd.to_datetime(signal_state["NIFTY Feature Source Date"]) > pd.to_datetime(signal_state["Feature As-Of Date"])).sum()))
    add("Position market source is not future", (pd.to_datetime(position_day["Current Market Feature Source Date"]) <= pd.to_datetime(position_day["Feature As-Of Date"])).all(), "source<=asof", int((pd.to_datetime(position_day["Current Market Feature Source Date"]) > pd.to_datetime(position_day["Feature As-Of Date"])).sum()))
    target_allowed = ml_registry[(ml_registry["Role"] == "FEATURE_ALLOWED") & ml_registry["Column"].str.contains("RETURN|MFE|MAE|BEFORE_STOP|FINAL_EXIT|Candidate Exit|AVAILABLE_DATE", case=False, regex=True)]
    allowed_exceptions = target_allowed[target_allowed["Column"].isin({"Current MFE Conservative To Date", "Current MAE Conservative To Date", "Current Stock Return 5D %", "Current Stock Return 20D %", "Current NIFTY Return 5D %", "Current NIFTY Return 20D %", "NIFTY Return 5D %", "NIFTY Return 20D %", "NIFTY Return 60D %", "Stock Return 1D %", "Stock Return 5D %", "Stock Return 10D %", "Stock Return 20D %", "Stock Return 60D %"})]
    leaks = target_allowed.drop(index=allowed_exceptions.index)
    add("No target column in feature allow-list", leaks.empty, "0", len(leaks), "|".join(leaks["Column"].astype(str).head(10)))
    missing_registry = set(feature_registry["Feature Name"]) - set(ml_registry.loc[ml_registry["Role"] == "FEATURE_ALLOWED", "Column"])
    add("Feature registry consumed by ML registry", not missing_registry, "0", len(missing_registry), "|".join(sorted(missing_registry)[:10]))
    unregistered_allowed = set(ml_registry.loc[ml_registry["Role"] == "FEATURE_ALLOWED", "Column"]) - set(feature_registry["Feature Name"])
    add("No unregistered feature in ML allow-list", not unregistered_allowed, "0", len(unregistered_allowed), "|".join(sorted(unregistered_allowed)[:10]))
    # Censoring is target-specific: T1 may have resolved while T2 remains
    # unavailable near the data boundary.  Reject only a label manufactured
    # for the same target whose horizon is censored.
    t1_censored_labeled = opportunities["T1_CENSORED"].fillna(True).astype(bool) & opportunities["T1_BEFORE_STOP_63"].notna()
    t2_censored_labeled = opportunities["T2_CENSORED"].fillna(True).astype(bool) & opportunities["T2_BEFORE_STOP_63"].notna()
    censored_labeled = int(t1_censored_labeled.sum() + t2_censored_labeled.sum())
    add("Censored target rows are not manufactured failures", censored_labeled == 0, "0 target-specific labels", censored_labeled)
    add("No global imputation marker", not any("IMPUT" in str(column).upper() for column in signal_state.columns), "NO IMPUTATION", "NO IMPUTATION")
    add("Current and entry regimes retained", {"Entry Market Regime", "Current Market Regime"}.issubset(position_day.columns), "BOTH", "BOTH" if {"Entry Market Regime", "Current Market Regime"}.issubset(position_day.columns) else "MISSING")
    return pd.DataFrame(rows)


def fail_if_any(checks: pd.DataFrame, context: str) -> None:
    failed = checks[checks["Status"] != "PASS"]
    if not failed.empty:
        raise RuntimeError(f"{context} failed: " + "; ".join(failed["Check"].astype(str)))
