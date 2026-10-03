"""Fail-closed identity guard for the already-active prospective cohort."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from stage6_ingestion.canonical import canonical_hash, without
from .activation import verify_activation_record
from .errors import ProspectiveIntegrityFailure
from .observation_config import COHORT_SCHEMA, AUTHORITY, load_observation_contract, load_observation_policy
from .operations_config import (
    ENTITY_REGISTRY_V2_HASH, ENTITY_REGISTRY_V2_ID, EXPECTED_CONTRACT_HASH as OPS_CONTRACT_HASH,
    EXPECTED_POLICY_HASH as OPS_POLICY_HASH, OPERATIONAL_SOURCES, SOURCE_REGISTRY_V2_HASH,
    SOURCE_REGISTRY_V2_ID, verify_operations_configuration,
)
from .policy import CONTROL_COMMIT, CONTROL_TAG, EXPECTED_CONTRACT_HASH, EXPECTED_POLICY_HASH, EXPECTED_PROTOCOL_HASH
from .protocol import verify_configuration

MODEL_BUNDLE_HASH = "4631eb8a1d0b34212252df3b1aae180f64ec98ba5e7955a84729df0a471c62da"
SOURCE_PACKAGE_HASH = "cc1b7bfc85c77e40f029a5ccff670e531445e5051932dab7e7e8abd2116bdc2f"
FEATURE_HASHES = (
    "62c26716ced06ea266e50ac79e404a2377015361b5ecd4f6228da77a8f6491b9",
    "a7712564c2b308c570374a1b1634f59971b9823a87a276fed8f995e1321bd490",
)


def _git(repo: Path, *args: str, check=True):
    git_dir = repo / ("_git" if (repo / "_git").exists() else ".git")
    return subprocess.run(["git", f"--git-dir={git_dir}", f"--work-tree={repo}", *args],
                          cwd=repo, text=True, capture_output=True, check=check)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_stage4a3(repo: Path):
    root = repo / "Stage 4A.3"
    identity = json.loads((root / "results/stage4a3_protocol_identity.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "models/frozen_2026/model_bundle_manifest.json").read_text(encoding="utf-8"))
    if identity.get("PROTOCOL_PACKAGE_HASH") != SOURCE_PACKAGE_HASH or identity.get("identity_components", {}).get("source_package_hash") != SOURCE_PACKAGE_HASH:
        raise ProspectiveIntegrityFailure("STAGE4A3_SOURCE_PACKAGE_DRIFT")
    if manifest.get("FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH") != MODEL_BUNDLE_HASH:
        raise ProspectiveIntegrityFailure("STAGE4A3_MODEL_BUNDLE_DRIFT")
    bundle_payload = {k: v for k, v in manifest.items() if k != "FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"}
    bundle_digest = hashlib.sha256((json.dumps(bundle_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str) + "\n").encode("utf-8")).hexdigest()
    if bundle_digest != MODEL_BUNDLE_HASH:
        raise ProspectiveIntegrityFailure("STAGE4A3_MODEL_BUNDLE_DRIFT")
    features = tuple(sorted({item.get("feature_hash") for item in manifest.get("models", [])}))
    if features != tuple(sorted(FEATURE_HASHES)) or len(manifest.get("models", [])) != 7:
        raise ProspectiveIntegrityFailure("STAGE4A3_FEATURE_IDENTITY_DRIFT")
    for item in manifest["models"]:
        if _sha256(root / "models/frozen_2026" / f"{item['model_name']}.joblib") != item["serialized_model_sha256"]:
            raise ProspectiveIntegrityFailure("STAGE4A3_MODEL_COMPONENT_DRIFT")
    source = json.loads((root / "results/stage4a3_source_manifest.json").read_text(encoding="utf-8"))
    if source.get("SOURCE_PACKAGE_HASH") != SOURCE_PACKAGE_HASH:
        raise ProspectiveIntegrityFailure("STAGE4A3_SOURCE_PACKAGE_DRIFT")
    for item in source.get("files", []):
        path = root / item["Path"]
        if not path.is_file() or path.stat().st_size != item["Bytes"] or _sha256(path) != item["SHA256"]:
            raise ProspectiveIntegrityFailure("STAGE4A3_SOURCE_COMPONENT_DRIFT")


def _validate_facts(facts: dict):
    expected = {
        "protocol_hash": EXPECTED_PROTOCOL_HASH, "policy_hash": EXPECTED_POLICY_HASH,
        "enrollment_contract_hash": EXPECTED_CONTRACT_HASH,
        "operations_policy_hash": OPS_POLICY_HASH, "operations_contract_hash": OPS_CONTRACT_HASH,
        "stage5d5_control_commit": CONTROL_COMMIT, "stage5d5_control_tag": CONTROL_TAG,
        "model_bundle_hash": MODEL_BUNDLE_HASH, "source_package_hash": SOURCE_PACKAGE_HASH,
        "feature_hashes": list(FEATURE_HASHES), "source_registry_id": SOURCE_REGISTRY_V2_ID,
        "source_registry_hash": SOURCE_REGISTRY_V2_HASH, "entity_registry_id": ENTITY_REGISTRY_V2_ID,
        "entity_registry_hash": ENTITY_REGISTRY_V2_HASH, "operational_source_set": list(OPERATIONAL_SOURCES),
    }
    for key, value in expected.items():
        if facts.get(key) != value:
            raise ProspectiveIntegrityFailure("ACTIVE_COHORT_IDENTITY_DRIFT:" + key)


def verify_active_cohort(repo_root, activation_record):
    repo = Path(repo_root).resolve()
    activation = verify_activation_record(activation_record)
    verify_configuration(); verify_operations_configuration(); _verify_stage4a3(repo)
    if _git(repo, "rev-list", "-n", "1", CONTROL_TAG).stdout.strip() != CONTROL_COMMIT:
        raise ProspectiveIntegrityFailure("STAGE5D_CONTROL_TAG_DRIFT")
    if _git(repo, "status", "--porcelain", "--", "Stage 5D").stdout.strip():
        raise ProspectiveIntegrityFailure("STAGE5D_DECISION_SYSTEM_DIRTY")
    if _git(repo, "diff", "--quiet", CONTROL_COMMIT, "HEAD", "--", "Stage 5D", check=False).returncode:
        raise ProspectiveIntegrityFailure("STAGE5D_DECISION_SYSTEM_DRIFT")
    policy, _, policy_hash = load_observation_policy(); contract, _, contract_hash = load_observation_contract()
    facts = {
        "activation_id": activation["activation_id"], "activation_record_hash": activation["record_hash"],
        "protocol_hash": activation["protocol_hash"], "policy_hash": activation["policy_hash"],
        "enrollment_contract_hash": activation["contract_hash"], "operations_policy_hash": OPS_POLICY_HASH,
        "operations_contract_hash": OPS_CONTRACT_HASH, "stage5d5_control_commit": CONTROL_COMMIT,
        "stage5d5_control_tag": CONTROL_TAG, "model_bundle_hash": MODEL_BUNDLE_HASH,
        "source_package_hash": SOURCE_PACKAGE_HASH, "feature_hashes": list(FEATURE_HASHES),
        "source_registry_id": SOURCE_REGISTRY_V2_ID, "source_registry_hash": SOURCE_REGISTRY_V2_HASH,
        "entity_registry_id": ENTITY_REGISTRY_V2_ID, "entity_registry_hash": ENTITY_REGISTRY_V2_HASH,
        "operational_source_set": list(OPERATIONAL_SOURCES), "observation_policy_id": policy["policy_id"],
        "observation_policy_hash": policy_hash, "observation_contract_id": contract["contract_version"],
        "observation_contract_hash": contract_hash, "stage5d_subtree_verification": "PASS",
        "stage4a3_bundle_verification": "PASS", "authority": AUTHORITY, "trading_authority": False,
    }
    _validate_facts(facts)
    record = {"schema_version": COHORT_SCHEMA, "cohort_fingerprint_id": "", **facts, "record_hash": ""}
    record["cohort_fingerprint_id"] = "S6PROSCOHORT_" + canonical_hash(without(record, "cohort_fingerprint_id", "record_hash"))[:24]
    record["record_hash"] = canonical_hash(without(record, "record_hash"))
    return record
