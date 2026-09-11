from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .final_analysis_gate import gate_audit, is_unlocked
from .immutable_ledger import record_breach


FINAL_OUTPUTS = [
    "stage4a3_final_gate_audit.csv","stage4a3_prospective_sample_summary.csv","stage4a3_predictive_metrics.csv",
    "stage4a3_predictive_calibration.csv","stage4a3_policy_summary_d1.csv","stage4a3_policy_summary_d0.csv",
    "stage4a3_yearly_or_period_metrics.csv","stage4a3_random_control_raw.csv.gz","stage4a3_random_control_summary.csv",
    "stage4a3_named_policy_random_percentiles.csv","stage4a3_block_bootstrap_63.csv.gz",
    "stage4a3_block_bootstrap_21.csv.gz","stage4a3_block_bootstrap_126.csv.gz","stage4a3_bootstrap_summary.csv",
    "stage4a3_primary_confirmatory_result.json","Stage4A3_Final_Prospective_Report.md",
]


def economic_criteria(r3: dict[str, Any], r0: dict[str, Any], evidence: dict[str, Any]) -> pd.DataFrame:
    checks = [
        ("total return", r3["total_return"] > r0["total_return"]),
        ("CAGR", r3["cagr"] > r0["cagr"]),
        ("expectancy R", r3["expectancy_r"] > r0["expectancy_r"]),
        ("profit factor", r3["profit_factor"] >= r0["profit_factor"]),
        ("bootstrap lower 2.5%", evidence["bootstrap_63_delta_terminal_return_lower_2_5"] > 0),
        ("random K1 percentile", evidence["random_k1_total_return_percentile"] >= 95),
        ("max drawdown tolerance", r3["max_drawdown"] >= r0["max_drawdown"] - 0.02),
        ("minimum completed trades", r3["completed_trades"] >= 50),
        ("ledger integrity", bool(evidence["ledger_integrity_pass"])),
        ("no protocol drift", bool(evidence["no_protocol_drift"])),
    ]
    return pd.DataFrame([{"Criterion": name, "Status": "PASS" if passed else "FAIL"} for name, passed in checks])


def require_unlocked(config: dict[str, Any], activation: dict[str, Any] | None, counts: dict[str, Any], audit_root: Path) -> pd.DataFrame:
    audit = gate_audit(config, activation, counts)
    if not is_unlocked(audit):
        record_breach(audit_root,{"UTC Time":pd.Timestamp.utcnow().isoformat(),"Breach Type":"PREMATURE_EVALUATION_ATTEMPT","Details":"PROSPECTIVE_EVALUATION_LOCKED","Blocked / Allowed":"BLOCKED","Affected Signal Date":"","Protocol Hash":counts.get("protocol_hash","")})
        raise RuntimeError("PROSPECTIVE_EVALUATION_LOCKED\n" + audit.to_csv(index=False))
    return audit


def parser() -> argparse.ArgumentParser:
    value=argparse.ArgumentParser(description="Locked Stage 4A.3 final confirmatory evaluation")
    value.add_argument("--stage-root",type=Path,required=True)
    value.add_argument("--counts-json",type=Path,required=True)
    return value


def main() -> None:
    args=parser().parse_args();root=args.stage_root.resolve()
    config=json.loads((root/"config/stage4a3_protocol.json").read_text(encoding="utf-8"))
    activation_path=root/"prospective/audit/activation_record.json"
    activation=json.loads(activation_path.read_text(encoding="utf-8")) if activation_path.exists() else None
    counts=json.loads(args.counts_json.read_text(encoding="utf-8"))
    require_unlocked(config,activation,counts,root/"prospective/audit")
    raise NotImplementedError("Evaluation adapters require matured prospective outcomes; gate passed but no analysis was run")


if __name__=="__main__": main()
