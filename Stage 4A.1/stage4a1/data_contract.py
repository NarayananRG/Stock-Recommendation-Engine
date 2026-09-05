"""Frozen Stage 4A/3.1 reference gates and input loading."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from .hashing import dataframe_content_hash, sha256_file


UPSTREAM_PREFIXES = ("Stage 2.2.2 Final/", "Stage 2B/", "Stage 2B.1/", "Stage 3/", "Stage 3.1/", "Stage 4A/")


def load_config(stage_root: Path) -> dict[str, Any]:
    return json.loads((stage_root / "config" / "stage4a1_config.json").read_text(encoding="utf-8"))


def git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def load_opportunity(repo_root: Path) -> pd.DataFrame:
    path = repo_root / "Stage 3.1" / "results" / "stage3_1_trade_opportunity_dataset.csv.gz"
    frame = pd.read_csv(path, low_memory=False)
    frame["Signal Date"] = pd.to_datetime(frame["Signal Date"], errors="raise").dt.normalize()
    for column in ["ENTRY_LABEL_AVAILABLE_DATE", "T1_LABEL_AVAILABLE_DATE", "T2_LABEL_AVAILABLE_DATE"]:
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
    return frame


def _row(category: str, check: str, passed: bool, expected: Any, actual: Any, details: str = "") -> dict[str, Any]:
    return {"Category": category, "Check": check, "Status": "PASS" if bool(passed) else "FAIL", "Expected": expected, "Actual": actual, "Details": details}


def build_reference_gate(repo_root: Path, stage_root: Path, config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, label in [("stage4a", "Stage 4A"), ("stage3_1", "Stage 3.1"), ("stage2b_1", "Stage 2B.1")]:
        expected = config[key]
        actual = git(repo_root, "rev-list", "-n", "1", expected["tag"])
        rows.append(_row("REFERENCE", f"{label} frozen tag commit", actual == expected["commit"], expected["commit"], actual))
    merge_base = git(repo_root, "merge-base", "HEAD", config["stage4a"]["tag"])
    rows.append(_row("REFERENCE", "Branch based on frozen Stage 4A tag", merge_base == config["stage4a"]["commit"], config["stage4a"]["commit"], merge_base))

    status_lines = [line for line in git(repo_root, "status", "--porcelain").splitlines() if line]
    changed_paths = [line[3:].strip('"').replace("\\", "/") for line in status_lines]
    outside = [path for path in changed_paths if not path.startswith("Stage 4A.1/")]
    rows.append(_row("ISOLATION", "Working-tree changes confined to Stage 4A.1", not outside, "Stage 4A.1/* only", outside or "Stage 4A.1/* only"))
    committed = [line for line in git(repo_root, "diff", "--name-only", config["stage4a"]["tag"], "HEAD").splitlines() if line]
    committed_outside = [path for path in committed if not path.startswith("Stage 4A.1/")]
    rows.append(_row("ISOLATION", "Tracked changes from Stage 4A tag confined to Stage 4A.1", not committed_outside, "Stage 4A.1/* only", committed_outside or "Stage 4A.1/* only"))
    for prefix in UPSTREAM_PREFIXES:
        relative = prefix.rstrip("/")
        dirty = git(repo_root, "status", "--porcelain", "--", relative)
        tree_diff = git(repo_root, "diff", "--name-only", config["stage4a"]["tag"], "--", relative)
        rows.append(_row("UPSTREAM", f"{relative} working tree unchanged", dirty == "", "no changes", dirty or "no changes"))
        rows.append(_row("UPSTREAM", f"{relative} equals frozen Stage 4A tree", tree_diff == "", "no differences", tree_diff or "no differences"))

    stage4a_identity = json.loads((repo_root / "Stage 4A" / "results" / "stage4a_experiment_identity.json").read_text(encoding="utf-8"))
    rows.append(_row("IDENTITY", "Stage 4A experiment ID", stage4a_identity.get("EXPERIMENT_ID") == config["stage4a"]["experiment_id"], config["stage4a"]["experiment_id"], stage4a_identity.get("EXPERIMENT_ID")))
    rows.append(_row("IDENTITY", "Stage 4A package hash", stage4a_identity.get("STAGE4A_CODE_PACKAGE_HASH") == config["stage4a"]["package_hash"], config["stage4a"]["package_hash"], stage4a_identity.get("STAGE4A_CODE_PACKAGE_HASH")))
    rows.append(_row("IDENTITY", "Stage 4A config hash", stage4a_identity.get("STAGE4A_CONFIG_HASH") == config["stage4a"]["config_hash"], config["stage4a"]["config_hash"], stage4a_identity.get("STAGE4A_CONFIG_HASH")))

    opportunity = pd.read_csv(repo_root / "Stage 3.1" / "results" / "stage3_1_trade_opportunity_dataset.csv.gz", low_memory=False)
    opportunity_hash = dataframe_content_hash(opportunity)
    rows.append(_row("DATASET", "Stage 3.1 trade_opportunity logical hash", opportunity_hash == config["stage3_1"]["trade_opportunity_content_hash"], config["stage3_1"]["trade_opportunity_content_hash"], opportunity_hash))
    stage31_identity = json.loads((repo_root / "Stage 3.1" / "results" / "stage3_1_experiment_identity.json").read_text(encoding="utf-8"))
    rows.append(_row("IDENTITY", "Stage 3.1 experiment ID", stage31_identity.get("EXPERIMENT_ID") == config["stage3_1"]["experiment_id"], config["stage3_1"]["experiment_id"], stage31_identity.get("EXPERIMENT_ID")))
    rows.append(_row("IDENTITY", "Stage 3.1 package hash", stage31_identity.get("STAGE3_1_CODE_PACKAGE_HASH") == config["stage3_1"]["package_hash"], config["stage3_1"]["package_hash"], stage31_identity.get("STAGE3_1_CODE_PACKAGE_HASH")))

    prediction_audit: dict[str, Any] = {}
    for name, expected_hash in [
        ("stage4a_oos_predictions.csv.gz", config["stage4a"]["oos_prediction_logical_hash"]),
        ("stage4a_joint_oos_predictions.csv.gz", config["stage4a"]["joint_prediction_logical_hash"]),
    ]:
        path = repo_root / "Stage 4A" / "results" / name
        frame = pd.read_csv(path, low_memory=False)
        logical = dataframe_content_hash(frame)
        artifact = sha256_file(path)
        prediction_audit[name] = {"logical_content_hash": logical, "artifact_sha256": artifact, "rows": len(frame)}
        rows.append(_row("PREDICTION", f"Frozen {name} logical hash", logical == expected_hash, expected_hash, logical))

    gate = pd.DataFrame(rows)
    if not gate["Status"].eq("PASS").all():
        raise RuntimeError("Frozen reference gate failed: " + "; ".join(gate.loc[gate["Status"].eq("FAIL"), "Check"]))
    return gate, {"merge_base": merge_base, "trade_opportunity_logical_hash": opportunity_hash, "stage4a_predictions": prediction_audit}
