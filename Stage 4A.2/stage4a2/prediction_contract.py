from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class PredictionSpec:
    policy: str
    file_name: str
    mode: str
    target: str
    model_variant: str
    feature_set: str


SPECS = (
    PredictionSpec("R1", "stage4a1_primary_only_oos_predictions.csv.gz", "PRIMARY_ONLY", "T1_BEFORE_STOP_63", "LOGIT_FULL", "FS3_FULL_SIGNAL_STATE"),
    PredictionSpec("R2", "stage4a1_primary_only_oos_predictions.csv.gz", "PRIMARY_ONLY", "T1_BEFORE_STOP_63", "LOGIT_RAW", "FS2_RAW_SIGNAL_STATE"),
    PredictionSpec("R3", "stage4a1_transfer_baseline_primary_joint_predictions.csv.gz", "TRANSFER", "JOINT_T1", "LOGIT_FULL", "FS3_FULL_SIGNAL_STATE"),
    PredictionSpec("R4", "stage4a1_transfer_baseline_primary_joint_predictions.csv.gz", "TRANSFER", "JOINT_T1", "LOGIT_RAW", "FS2_RAW_SIGNAL_STATE"),
    PredictionSpec("R5", "stage4a1_transfer_baseline_primary_predictions.csv.gz", "TRANSFER", "ENTRY_FILLED", "RF_FULL", "FS3_FULL_SIGNAL_STATE"),
)


def load_scores(repo_root: Path, universe: pd.DataFrame) -> tuple[dict[str, pd.Series], pd.DataFrame]:
    results = repo_root / "Stage 4A.1" / "results"
    ids = universe[["Signal ID", "Signal Date"]].copy()
    scores: dict[str, pd.Series] = {}
    audits: list[dict[str, object]] = []
    for spec in SPECS:
        frame = pd.read_csv(results / spec.file_name, low_memory=False)
        frame["Signal Date"] = pd.to_datetime(frame["Signal Date"]).dt.normalize()
        frame["Training Cutoff Date"] = pd.to_datetime(frame["Training Cutoff Date"]).dt.normalize()
        chosen = frame.loc[
            frame["Mode"].eq(spec.mode)
            & frame["Target"].eq(spec.target)
            & frame["Model Variant"].eq(spec.model_variant)
            & frame["Feature Set"].eq(spec.feature_set)
        ].copy()
        merged = ids.merge(chosen, on=["Signal ID", "Signal Date"], how="left", validate="one_to_one", suffixes=("", "_prediction"))
        missing = int(merged["Predicted Probability"].isna().sum())
        year_bad = int((merged["Evaluation Year"] != merged["Signal Date"].dt.year).sum())
        cutoff_bad = int((merged["Training Cutoff Date"] > merged["Signal Date"]).sum())
        lineage_bad = int((merged["Stage 4A.1 Experiment ID"] != "S4A1_20160101_20260828_89fadf5b6425").sum())
        audits.extend([
            {"Policy": spec.policy, "Check": "one score per expected Signal ID", "Status": "PASS" if missing == 0 and len(merged) == len(ids) else "FAIL", "Failures": missing},
            {"Policy": spec.policy, "Check": "Evaluation Year equals Signal Date year", "Status": "PASS" if year_bad == 0 else "FAIL", "Failures": year_bad},
            {"Policy": spec.policy, "Check": "Training Cutoff Date <= Signal Date", "Status": "PASS" if cutoff_bad == 0 else "FAIL", "Failures": cutoff_bad},
            {"Policy": spec.policy, "Check": "frozen Stage 4A.1 lineage", "Status": "PASS" if lineage_bad == 0 else "FAIL", "Failures": lineage_bad},
        ])
        if missing or year_bad or cutoff_bad or lineage_bad:
            raise RuntimeError(f"Prediction lineage gate failed for {spec.policy}")
        scores[spec.policy] = merged.set_index("Signal ID")["Predicted Probability"].astype(float)
    return scores, pd.DataFrame(audits)
