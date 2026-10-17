import csv,json,hashlib
from pathlib import Path

root=Path(".")
audit=json.loads((root/"NextGen Research/results/real_calibration_audit_v1.json").read_text())
policy=json.loads((root/"NextGen Research/calibration_governance/real_calibration_policy_v1.json").read_text())
evaluations=audit["evaluations"]
lineage=list(csv.DictReader((root/"Stage 4A.2/results/stage4a2_prediction_lineage_audit.csv").open()))
calibration=list(csv.DictReader((root/"Stage 4A/results/stage4a_calibration_summary.csv").open()))
assert policy["promotion_authority"]=="NONE"
assert audit["active_recommendation_influence"]=="NONE"
assert all(r["Status"]=="PASS" and r["Failures"]=="0" for r in lineage)
assert evaluations and all(x["trading_authority"] is False for x in evaluations)
sample_counts=sorted(set(x["sample_count"] for x in evaluations))
status_counts={}
for x in evaluations: status_counts[x["calibration_status"]]=status_counts.get(x["calibration_status"],0)+1
report={
 "audit":"SRE_FORECAST_LINEAGE_REAL_EVIDENCE",
 "production_changes":False,
 "stage4_oos_calibration_rows":len(calibration),
 "stage4_oos_summary_sample_targets":[{"target":x["Target"],"model":x["Model Variant"],"rows":int(x["Rows"]),"ece":float(x["Expected Calibration Error"])} for x in calibration],
 "stage4a2_lineage_checks":len(lineage),
 "stage4a2_lineage_status":"PASS",
 "real_calibration_evaluation_count":len(evaluations),
 "real_calibration_sample_counts":sample_counts,
 "real_calibration_status_counts":status_counts,
 "real_calibration_policy_minimum_sample":policy["minimum_sample"],
 "real_calibration_authority":audit["active_recommendation_influence"],
 "actual_oct16_run_available":False,
 "forecast_horizon_vs_recovery_horizon":"NOT_VERIFIED",
 "expected_return_is_validated_for_buy_decision":False,
 "risk":"HISTORICAL_OOS_CALIBRATION_SUMMARY_IS_NOT_EVIDENCE_OF_2026_10_16_LEGACY_EXPECTED_RETURN_CALIBRATION",
 "next_evidence_needed":"2026-10-16 run JSON for GODREJCP and HINDZINC including run_id, market_session, horizon_sessions, expected_return provenance and source close",
 "decision":"NO_PRODUCTION_GATE_CHANGE_AND_NO_INSTALLER_REBUILD"
}
Path("forecast-lineage-evidence-report.json").write_text(json.dumps(report,indent=2)+"\n")
print("REAL_EVIDENCE_LINEAGE PASS")
print("REAL CALIBRATION COUNTS:",json.dumps(status_counts))
print("FORECAST BUY AUTHORITY: NOT ESTABLISHED")
print("REPORT: forecast-lineage-evidence-report.json")
