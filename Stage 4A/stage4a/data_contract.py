"""Frozen Stage 3.1 input loading and immutable-reference gates."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from hashing import canonical_json_hash, dataframe_content_hash, sha256_file


DATASET_FILES = {
    "signal_state": "stage3_1_signal_state_dataset.csv.gz",
    "trade_opportunity": "stage3_1_trade_opportunity_dataset.csv.gz",
    "d1_position_day": "stage3_1_d1_position_day_dataset.csv.gz",
}


def load_config(stage_root: Path) -> dict[str, Any]:
    return json.loads((stage_root / "config" / "stage4a_model_config.json").read_text(encoding="utf-8"))


def repo_root_from_stage(stage_root: Path) -> Path:
    return stage_root.resolve().parent


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def load_trade_opportunity(repo_root: Path, config: dict[str, Any]) -> pd.DataFrame:
    path = repo_root / config["source_paths"]["trade_opportunity"]
    frame = pd.read_csv(path, low_memory=False)
    frame["Signal Date"] = pd.to_datetime(frame["Signal Date"], errors="raise").dt.normalize()
    for target_spec in config["targets"].values():
        column = target_spec["available_date"]
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
    return frame


def _gate(category: str, check: str, passed: bool, expected: Any, actual: Any, details: str = "") -> dict[str, Any]:
    return {
        "Category": category,
        "Check": check,
        "Status": "PASS" if bool(passed) else "FAIL",
        "Expected": expected,
        "Actual": actual,
        "Details": details,
    }


def build_reference_gate(repo_root: Path, config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Recompute every immutable input identity before model fitting."""
    paths = config["source_paths"]
    results_root = repo_root / paths["results"]
    stage31_root = repo_root / paths["stage3_1_root"]
    expected = config["stage3_1"]
    identity = json.loads((repo_root / paths["experiment_identity"]).read_text(encoding="utf-8"))
    dataset_manifest = json.loads((repo_root / paths["dataset_manifest"]).read_text(encoding="utf-8"))
    source_manifest = json.loads((repo_root / paths["source_manifest"]).read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []

    tag_commit = _git(repo_root, "rev-parse", f"{expected['tag']}^{{}}")
    rows.append(_gate("REFERENCE", "Stage 3.1 frozen tag commit", tag_commit == expected["commit"], expected["commit"], tag_commit))
    stage2_commit = _git(repo_root, "rev-parse", f"{config['stage2b_1']['tag']}^{{}}")
    rows.append(_gate("REFERENCE", "Stage 2B.1 frozen tag commit", stage2_commit == config["stage2b_1"]["commit"], config["stage2b_1"]["commit"], stage2_commit))
    stage3_commit = _git(repo_root, "rev-parse", config["stage3_reference"]["ref"])
    rows.append(_gate("REFERENCE", "Stage 3 immutable reference commit", stage3_commit == config["stage3_reference"]["commit"], config["stage3_reference"]["commit"], stage3_commit))
    merge_base = _git(repo_root, "merge-base", "HEAD", expected["tag"])
    rows.append(_gate("REFERENCE", "Branch created from frozen Stage 3.1 commit", merge_base == expected["commit"], expected["commit"], merge_base, "Verified by merge-base so the gate remains valid after Stage 4A is committed"))
    tracked_changes = [
        value for value in _git(repo_root, "diff", "--name-only", expected["tag"], "HEAD").splitlines()
        if value
    ]
    outside_stage4a = [value for value in tracked_changes if not value.startswith("Stage 4A/")]
    rows.append(_gate("UPSTREAM", "Tracked changes since frozen tag confined to Stage 4A", not outside_stage4a, "Stage 4A/* only", outside_stage4a or "Stage 4A/* only"))

    upstream_diff = _git(repo_root, "status", "--porcelain", "--", paths["stage3_1_root"])
    tagged_diff = _git(repo_root, "diff", "--name-only", expected["tag"], "--", paths["stage3_1_root"])
    rows.append(_gate("UPSTREAM", "Stage 3.1 working tree unchanged", upstream_diff == "", "no changes", upstream_diff or "no changes"))
    rows.append(_gate("UPSTREAM", "Stage 3.1 equals frozen tag tree", tagged_diff == "", "no differences", tagged_diff or "no differences"))

    rows.append(_gate("IDENTITY", "Stage 3.1 experiment ID", identity.get("EXPERIMENT_ID") == expected["experiment_id"], expected["experiment_id"], identity.get("EXPERIMENT_ID")))
    rows.append(_gate("IDENTITY", "Stage 3.1 package hash in identity", identity.get("STAGE3_1_CODE_PACKAGE_HASH") == expected["package_hash"], expected["package_hash"], identity.get("STAGE3_1_CODE_PACKAGE_HASH")))
    rows.append(_gate("IDENTITY", "Stage 3.1 schema hash in identity", identity.get("STAGE3_1_SCHEMA_HASH") == expected["schema_hash"], expected["schema_hash"], identity.get("STAGE3_1_SCHEMA_HASH")))
    rows.append(_gate("IDENTITY", "Stage 3.1 schema hash in dataset manifest", dataset_manifest.get("STAGE3_1_SCHEMA_HASH") == expected["schema_hash"], expected["schema_hash"], dataset_manifest.get("STAGE3_1_SCHEMA_HASH")))

    source_identity_rows = []
    for item in source_manifest["sources"]:
        source_path = stage31_root / item["relative_path"]
        actual_hash = sha256_file(source_path)
        source_identity_rows.append({"relative_path": item["relative_path"], "sha256": actual_hash})
        rows.append(_gate("SOURCE", f"Stage 3.1 source hash: {item['relative_path']}", actual_hash == item["sha256"], item["sha256"], actual_hash))
    actual_package_hash = canonical_json_hash(source_identity_rows)
    rows.append(_gate("SOURCE", "Stage 3.1 recomputed package hash", actual_package_hash == expected["package_hash"], expected["package_hash"], actual_package_hash))
    rows.append(_gate("SOURCE", "Stage 3.1 source-manifest package hash", source_manifest.get("package_hash") == expected["package_hash"], expected["package_hash"], source_manifest.get("package_hash")))

    manifest_by_name = {item["dataset_name"]: item for item in dataset_manifest["datasets"]}
    dataset_audit: dict[str, Any] = {}
    for name, file_name in DATASET_FILES.items():
        path = results_root / file_name
        frame = pd.read_csv(path, low_memory=False)
        actual_rows = len(frame)
        actual_content_hash = dataframe_content_hash(frame)
        manifest_item = manifest_by_name[name]
        actual_artifact_hash = sha256_file(path)
        dataset_audit[name] = {
            "rows": actual_rows,
            "content_hash": actual_content_hash,
            "artifact_hash": actual_artifact_hash,
        }
        rows.append(_gate("DATASET", f"{name} row count", actual_rows == expected["datasets"][name]["rows"], expected["datasets"][name]["rows"], actual_rows))
        rows.append(_gate("DATASET", f"{name} logical content hash", actual_content_hash == expected["datasets"][name]["content_hash"], expected["datasets"][name]["content_hash"], actual_content_hash))
        rows.append(_gate("DATASET", f"{name} manifest logical hash", manifest_item.get("content_hash") == expected["datasets"][name]["content_hash"], expected["datasets"][name]["content_hash"], manifest_item.get("content_hash")))
        rows.append(_gate("DATASET", f"{name} artifact hash", actual_artifact_hash == manifest_item.get("artifact_hash"), manifest_item.get("artifact_hash"), actual_artifact_hash))

    gate = pd.DataFrame(rows)
    if not gate["Status"].eq("PASS").all():
        failed = gate.loc[gate["Status"].eq("FAIL"), "Check"].tolist()
        raise RuntimeError("Immutable input gate failed: " + "; ".join(failed))
    return gate, {
        "stage3_1_tag_commit": tag_commit,
        "branch_merge_base": merge_base,
        "stage2b_1_tag_commit": stage2_commit,
        "stage3_reference_commit": stage3_commit,
        "stage3_1_package_hash": actual_package_hash,
        "stage3_1_schema_hash": dataset_manifest["STAGE3_1_SCHEMA_HASH"],
        "datasets": dataset_audit,
    }
