"""Build deterministic committed evidence from local archives and frozen Stage 4 outputs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from common import canonical_bytes, file_sha256, load_json, record, sha256
from real_data_foundation import build_real_pit_snapshot, parse_nse_security_master, real_calibration_audit


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


fixture = ROOT / "fixtures/nse_equity_security_master_sample.csv"
fixture_bytes = fixture.read_bytes()
securities = parse_nse_security_master(
    fixture_bytes, observed_date="2026-10-03",
    source_reference="https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
)
snapshot = build_real_pit_snapshot(securities, observed_date="2026-10-03",
                                   source_dataset_id="NSE_CURRENT_SECURITY_MASTER_REAL_DEMONSTRATION_20261003")
snapshot["demonstration_scope"] = "FIVE_RECORD_SANITIZED_REAL_STRUCTURE_SUBSET"
snapshot["full_archive_record_count"] = 2593
snapshot["full_archive_sha256"] = "95f0d731f5858f71e876c45377dcefa79bc7a8db1e8161d0c92320252af4aa8f"
write(ROOT / "results/real_pit_universe_demonstration_v1.json", snapshot)

cal_policy = load_json(ROOT / "calibration_governance/real_calibration_policy_v1.json")
calibration = real_calibration_audit(REPO, cal_policy)
write(ROOT / "results/real_calibration_audit_v1.json", calibration)

terminology = record("MODEL_OUTPUT_TERMINOLOGY_AUDIT_V1", {
    "source_artifacts": [
        "Stage 4A/results/stage4a_oos_predictions.csv.gz",
        "Stage 4A/results/stage4a_joint_oos_predictions.csv.gz",
    ],
    "fields": [
        {"field":"Predicted Probability","classification":"UNCALIBRATED_MODEL_SCORE","compatibility_label":"model_score"},
        {"field":"P Fill","classification":"UNCALIBRATED_MODEL_SCORE","compatibility_label":"model_score"},
        {"field":"P T1 Conditional","classification":"UNCALIBRATED_MODEL_SCORE","compatibility_label":"model_score"},
        {"field":"P T2 Conditional","classification":"UNCALIBRATED_MODEL_SCORE","compatibility_label":"model_score"},
        {"field":"Actionability Score","classification":"RULE_SCORE","compatibility_label":"signal_score"},
        {"field":"Technical Score","classification":"RULE_SCORE","compatibility_label":"signal_score"},
    ],
    "legacy_artifacts_mutated": False,
})
write(ROOT / "results/real_terminology_audit_v1.json", terminology)

components = {
    "source_archive_manifest": file_sha256(ROOT / "data/manifests/real_source_archive_manifest_v1.json"),
    "verified_source_registry": file_sha256(ROOT / "source_registry_v2/verified_source_evidence_v1.json"),
    "cost_schedule": file_sha256(ROOT / "execution_india/india_equity_cost_schedule_v1.json"),
    "drift_policy": file_sha256(ROOT / "model_lifecycle/drift_policy_v1.json"),
    "coverage_report": file_sha256(ROOT / "results/nextgen_data_coverage_report_v1.json"),
    "pit_demonstration": file_sha256(ROOT / "results/real_pit_universe_demonstration_v1.json"),
    "calibration_audit": file_sha256(ROOT / "results/real_calibration_audit_v1.json"),
    "terminology_audit": file_sha256(ROOT / "results/real_terminology_audit_v1.json"),
}
manifest = record("NEXTGEN_REAL_DATA_FOUNDATION_MANIFEST_V1", {
    "parent_foundation_commit": "c6e03f9e1ee3cab6600e441ebc7390819716fdb2",
    "parent_manifest_hash": file_sha256(ROOT / "nextgen_manifest.json"),
    "component_file_sha256": components,
    "fixture_only_tests": True, "network_calls_in_tests": 0, "live_connectors": 0,
    "active_lane_changed_files": 0, "authority_scope": "RESEARCH_ONLY",
    "trading_authority": False, "ml_authority": "NONE", "promotion_authority": "NONE",
})
write(ROOT / "real_data_foundation_manifest_v1.json", manifest)
print(json.dumps({"manifest_id": manifest["record_id"], "component_count": len(components), "models": len(calibration["evaluations"])}, sort_keys=True))
