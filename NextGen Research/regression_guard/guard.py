"""Read-only identity and dependency-direction guard for the frozen active lane."""
from __future__ import annotations

import subprocess
from pathlib import Path

from common import load_json


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "--git-dir=_git", "--work-tree=.", *args], cwd=repo, text=True).strip()


def verify_active_lane(repo: str | Path, baseline_manifest: str | Path) -> dict:
    root = Path(repo)
    manifest = load_json(baseline_manifest)
    baseline = manifest["baseline_commit"]
    if _git(root, "cat-file", "-t", baseline) != "commit":
        raise ValueError("frozen baseline missing")
    changed = _git(root, "diff", "--name-only", baseline, "--")
    names = [line for line in changed.splitlines() if line]
    prohibited = [n for n in names if not n.startswith("NextGen Research/")]
    if prohibited:
        raise ValueError(f"active-lane changes detected: {prohibited}")
    required = {
        "stage4a3_model_bundle_hash", "stage4a3_source_package_hash", "stage5d5_commit",
        "stage6_v1_source_registry_hash", "stage6_8c_policy_hash", "stage6_8c_contract_hash",
        "prospective_activation_id", "prospective_activation_hash",
    }
    if required - manifest.keys() or manifest["active_source_set"] != ["RBI_OFFICIAL_PRESS_RELEASES_RSS", "SEBI_OFFICIAL_RSS"]:
        raise ValueError("active identity manifest incomplete")
    return {"status": "PASS", "active_lane_changed_file_count": 0, "changed_files": names, "identities": manifest}


def scan_reverse_dependencies(repo: str | Path) -> list[str]:
    root = Path(repo)
    hits = []
    active_roots = [root / "Stage 4A.3", root / "Stage 5D", root / "Stage 6"]
    for base in active_roots:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "NextGen Research" in text or "pit_universe" in text or "model_lifecycle" in text:
                hits.append(path.relative_to(root).as_posix())
    return sorted(hits)

