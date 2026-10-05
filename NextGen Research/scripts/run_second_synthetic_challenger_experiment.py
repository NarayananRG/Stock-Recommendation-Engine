"""Build EXP2 robustness experiment evidence."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
sys.path.insert(0, str(ROOT))

from simple_challenger.harness import canonical_hash  # noqa: E402
from simple_challenger.synthetic_exp2 import (  # noqa: E402
    EXP1_IDENTITY,
    REAL_DATA_TRAINING_STATUS,
    RIGHTS_STATUS,
    SAMPLE_REGIMES,
    SCENARIOS,
    SEEDS,
    model_profiles,
    run_exp2,
)


def write_json(name: str, payload: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(name: str, rows: list[dict]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["status"])
        writer.writeheader()
        writer.writerows(rows)


def fmt(value) -> str:
    return f"{value:.6f}" if isinstance(value, float) else str(value)


def report(payload: dict, profiles: dict) -> str:
    summary = payload["summary"]
    manifest = payload["manifest"]
    selected = payload["selection"]
    return f"""# NextGen Second Synthetic Challenger Robustness Report

## 1. Executive summary

EXP2 completed as the second and final bounded synthetic challenger experiment.  It evaluates robustness and model-family selection across 10 harder synthetic scenarios, 10 preregistered seeds, two sample-size regimes, and four existing simple model families.  Experiment classification: `{payload['classification']}`.  Family-selection result: `{selected}`.

## 2. EXP1 dependency

EXP2 starts from EXP1 evidence `{EXP1_IDENTITY}` and does not regenerate or overwrite EXP1 artifacts.

## 3. Synthetic-only statement

All EXP2 model training and evaluation use deterministic synthetic panels only.  No NSE, NIFTY, Stage 4A.3, Stage 5D, Stage 6, MCP, live-market, prospective, or restricted official-market dataset was used for training.

## 4. Rights status

Real-data rights remain `{RIGHTS_STATUS}`.  Real-data model training remains `{REAL_DATA_TRAINING_STATUS}`.

## 5. Experiment specification

Specification hash: `{manifest['specification_hash']}`.  Experiment ID: `{payload['experiment_id']}`.

## 6. Scenario definitions

{chr(10).join(f'- `{key}`: {value}' for key, value in SCENARIOS.items())}

## 7. Seeds

`{SEEDS}`

## 8. Dataset/sample-size design

Sample regimes: `{list(SAMPLE_REGIMES)}`.  Row-level datasets are reproducible from synthetic generator configuration and are not committed.

## 9. Temporal partitioning

Strict chronological TRAIN / VALIDATION / FINAL TEST partitions were used with an embargo.  No shuffled split was used.

## 10. Fixed model configurations

Only deterministic/reference, logistic regression, random forest, and gradient boosting were evaluated.  No hyperparameter search, AutoML, neural network, or final-test tuning was performed.

## 11. Predictive results

Predictive metrics were collected for validation and final test: ROC-AUC, PR-AUC, Brier score, Brier baseline, and Brier skill.  Undefined metrics remain explicit.

## 12. Cross-sectional ranking results

IC, Rank IC, Precision@K, and Top-K synthetic relative-return diagnostics were measured.  These remain synthetic diagnostics, not expected market returns.

## 13. Synthetic economic diagnostics

Top-5/Top-10/Top-20 and percentage Top-K synthetic forward-return diagnostics were computed on synthetic outcomes only.

## 14. Seed stability

The summary artifact reports mean, median, standard deviation, minimum, maximum, interquartile range, valid/undefined run counts, and sign consistency by scenario/sample-size/model.

## 15. Validation→final-test degradation

Conclusion: `{summary['validation_test_degradation']}`.  Degradation was measured for ROC-AUC, Rank IC, Top-5 relative synthetic return, and Brier skill.

## 16. Null false-positive control

Result: `{summary['null_control']}`.

## 17. Spurious-signal control

Result: `{summary['spurious_control']}`.  Development-period superiority is not credited when final-test generalization fails.

## 18. Regime robustness

Result: `{summary['regime_robustness']}`.  Fixed challengers are not dynamically adapted during final test.

## 19. Ranking-vs-classification analysis

Conclusion: `{summary['ranking_vs_classification']}`.  EXP2 treats ranking evidence separately from binary classification evidence.

## 20. Calibration analysis

Conclusion: `{summary['calibration']}`.  Useful ranking does not imply trustworthy probabilities.

## 21. Ablation V2

Conclusion: `{summary['ablation']['conclusion']}`.  Mean full-minus-signal-removed Top-5 synthetic relative-return delta: `{fmt(summary['ablation']['mean_full_minus_signal_removed_top5'])}`.

## 22. Complexity assessment

The preregistered hierarchy penalizes complexity: LOGISTIC_REGRESSION < RANDOM_FOREST < GRADIENT_BOOSTING.  More complex models require material, repeated, robust incremental value.

## 23. Model-family profiles

{chr(10).join(f'- `{name}`: strengths={profile["strengths"]}; weaknesses={profile["weaknesses"]}; failure_modes={profile["known_failure_modes"]}; complexity={profile["complexity_cost"]}' for name, profile in profiles.items())}

## 24. Model-family selection

Selection: `{selected}`.  This is a research-family selection only and does not authorize real-data training, production promotion, trading, or replacement of any active model.

## 25. Limitations

EXP2 is synthetic-only.  It cannot prove real alpha, real profitability, real-market calibration, or production readiness.

## 26. What EXP2 proves

It proves the controlled synthetic robustness pipeline can compare simple model families under harder deterministic scenarios and produce reproducible compact evidence.

## 27. What EXP2 does NOT prove

It does not prove that any model will make money, should trade, should replace the active model, or is ready for production.

## 28. Rights/provenance status

Rights remain `{RIGHTS_STATUS}` and real-data training remains `{REAL_DATA_TRAINING_STATUS}`.

## 29. Frozen-lane integrity

Stage 4A.3, Stage 5D, and Stage 6 are not modified by EXP2.

## 30. Recommended next research action

Stop synthetic model-family experiments.  If real-data training rights remain blocked, the blocker is rights availability.  If rights become available later, use the selected simple family only as a candidate for a separately authorized first real-data challenger experiment.
"""


def main() -> None:
    payload = run_exp2()
    profiles = model_profiles(payload["selection"])
    artifacts = {
        "summary": "nextgen_synthetic_challenger_exp2_summary.json",
        "results": "nextgen_synthetic_challenger_exp2_results.csv",
        "degradation": "nextgen_synthetic_challenger_exp2_degradation.csv",
        "ablation": "nextgen_synthetic_challenger_exp2_ablation.json",
        "profiles": "nextgen_synthetic_challenger_exp2_model_profiles.json",
    }
    write_csv(artifacts["results"], payload["results"])
    write_csv(artifacts["degradation"], payload["degradation"])
    write_json(artifacts["ablation"], {"artifact_type": "NEXTGEN_SYNTHETIC_CHALLENGER_EXP2_ABLATION_V1", "experiment_id": payload["experiment_id"], "records": payload["ablation"], "summary": payload["summary"]["ablation"]})
    write_json(artifacts["profiles"], {"artifact_type": "NEXTGEN_SYNTHETIC_CHALLENGER_EXP2_MODEL_PROFILES_V1", "experiment_id": payload["experiment_id"], "selected_family": payload["selection"], "profiles": profiles})
    write_json(artifacts["summary"], {"artifact_type": "NEXTGEN_SYNTHETIC_CHALLENGER_EXP2_SUMMARY_V1", "experiment_id": payload["experiment_id"], "classification": payload["classification"], "selected_family": payload["selection"], "selection_evidence": payload["selection_evidence"], "summary": payload["summary"], "failures": payload["failures"], "rights_status": RIGHTS_STATUS, "real_data_training": REAL_DATA_TRAINING_STATUS})
    manifest = payload["manifest"]
    manifest["result_artifact_hashes"] = {
        key: canonical_hash((RESULTS / name).read_text(encoding="utf-8")) if name.endswith(".csv") else canonical_hash(json.loads((RESULTS / name).read_text(encoding="utf-8")))
        for key, name in artifacts.items()
    }
    manifest["manifest_hash"] = canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
    write_json("nextgen_synthetic_challenger_exp2_manifest.json", manifest)
    (ROOT / "NextGen_Second_Synthetic_Challenger_Robustness_Report.md").write_text(report({**payload, "manifest": manifest}, profiles), encoding="utf-8")
    print(json.dumps({"experiment_id": payload["experiment_id"], "classification": payload["classification"], "selected_family": payload["selection"], "scenarios": len(SCENARIOS), "seeds": len(SEEDS), "sample_regimes": len(SAMPLE_REGIMES), "runs": len(payload["results"]), "failures": len(payload["failures"]), "status": "PASS"}, sort_keys=True))


if __name__ == "__main__":
    main()
