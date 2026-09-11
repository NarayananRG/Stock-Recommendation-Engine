from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from .hashing import dataframe_content_hash
from .model_scoring import verify_bundle


PROTECTED_PATHS = (
    "Stage 4A.3/stage4a3",
    "Stage 4A.3/config",
    "Stage 4A.3/scripts",
    "Stage 4A.3/requirements-lock.txt",
    "Stage 4A.3/Stage4A3_Protocol.md",
    "Stage 4A.3/prospective_universe.csv",
    "Stage 4A.3/models/frozen_2026",
    "Stage 4A.3/results/stage4a3_protocol_identity.json",
    "Stage 4A.3/results/stage4a3_model_bundle_manifest.json",
)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo.as_posix()}", *args],
        cwd=repo, text=True, capture_output=True, check=check,
    )


def _load(stage_root: Path, relative: str) -> dict[str, Any]:
    return json.loads((stage_root/relative).read_text(encoding="utf-8"))


def verify_protocol_material(repo: Path, stage_root: Path, tag: str, expected_commit: str | None = None, require_head: bool = False) -> dict[str, Any]:
    resolved=git(repo,"rev-parse",f"{tag}^{{commit}}").stdout.strip()
    if expected_commit is not None and resolved != expected_commit:
        raise RuntimeError("ACTIVATION_BLOCKED_PROTOCOL_DRIFT: TAG_COMMIT_MISMATCH")
    if require_head and git(repo,"rev-parse","HEAD").stdout.strip() != resolved:
        raise RuntimeError("ACTIVATION_BLOCKED_PROTOCOL_DRIFT: ACTIVATE_FROM_ACCEPTED_TAG_COMMIT")
    dirty=git(repo,"status","--porcelain","--",*PROTECTED_PATHS).stdout.strip()
    drift=git(repo,"diff","--quiet",tag,"--",*PROTECTED_PATHS,check=False).returncode
    if dirty or drift:
        raise RuntimeError("ACTIVATION_BLOCKED_PROTOCOL_DRIFT: PROTECTED_FILE_MISMATCH")
    config=_load(stage_root,"config/stage4a3_protocol.json")
    identity=_load(stage_root,"results/stage4a3_protocol_identity.json")
    result_manifest=_load(stage_root,"results/stage4a3_model_bundle_manifest.json")
    bundle=verify_bundle(stage_root/"models/frozen_2026")
    actual_hash=bundle["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]
    expected_hashes={config["expected_model_bundle_hash"],identity["identity_components"]["model_bundle_hash"],result_manifest["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]}
    if expected_hashes != {actual_hash}:
        raise RuntimeError("ACTIVATION_BLOCKED_PROTOCOL_DRIFT: MODEL_BUNDLE_IDENTITY_MISMATCH")
    universe=pd.read_csv(stage_root/"prospective_universe.csv")
    universe_hash=dataframe_content_hash(universe)
    stored=_load(stage_root,"results/stage4a3_frozen_universe_hash.json")["FROZEN_UNIVERSE_HASH"]
    if universe_hash != stored or universe_hash != identity["identity_components"]["universe_hash"]:
        raise RuntimeError("ACTIVATION_BLOCKED_PROTOCOL_DRIFT: FROZEN_UNIVERSE_MISMATCH")
    return {"protocol_commit":resolved,"protocol_identity":identity["PROTOCOL_ID"],"model_bundle_hash":actual_hash,"frozen_universe_hash":universe_hash}


def verify_runtime_protocol_integrity(repo: Path, stage_root: Path, activation: dict[str, Any]) -> dict[str, Any]:
    config=_load(stage_root,"config/stage4a3_protocol.json")
    try:
        verified=verify_protocol_material(repo,stage_root,config["protocol_tag"],expected_commit=activation["Protocol Commit"],require_head=False)
    except Exception as exc:
        raise RuntimeError("PROTOCOL_DRIFT_ATTEMPT") from exc
    if verified["model_bundle_hash"] != activation["Model Bundle Hash"] or verified["frozen_universe_hash"] != activation["Frozen Universe Hash"] or verified["protocol_identity"] != activation["Protocol Identity"]:
        raise RuntimeError("PROTOCOL_DRIFT_ATTEMPT")
    return verified
