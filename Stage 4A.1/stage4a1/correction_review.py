"""Read-only comparison to preserved provisional outputs; writes local audit."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from .hashing import write_csv


def review(old: Path, new: Path):
    rows = []
    names = ["metrics_pooled.csv", "metrics_by_year.csv", "metrics_by_era.csv", "ranking_lift.csv",
             "bootstrap_summary.csv", "transfer_vs_primary_only_paired.csv", "research_evidence_classification.csv",
             "block_bootstrap_63.csv.gz", "block_bootstrap_21_sensitivity.csv.gz", "block_bootstrap_126_sensitivity.csv.gz",
             "primary_only_oos_predictions.csv.gz", "primary_only_joint_oos_predictions.csv.gz",
             "transfer_baseline_primary_predictions.csv.gz", "transfer_baseline_primary_joint_predictions.csv.gz"]
    for suffix in names:
        name = "stage4a1_" + suffix
        a, b = (pd.read_csv(directory / name, low_memory=False) for directory in [old, new])
        if len(a) != len(b):
            raise RuntimeError("Behavioral blocker: row counts changed: " + name)
        for column in a.columns.intersection(b.columns):
            if column == "Stage 4A.1 Experiment ID":
                continue
            equal = a[column].eq(b[column]) | (a[column].isna() & b[column].isna())
            difference = (a[column] - b[column]).abs().max() if pd.api.types.is_numeric_dtype(a[column]) else np.nan
            rows.append({"Artifact": name, "Column": column, "Changed Cells": int((~equal).sum()), "Maximum Absolute Difference": difference})
    result = pd.DataFrame(rows)
    write_csv(result, new / "stage4a1_correctness_fix_comparison.csv")
    prediction_change = result.loc[result.Artifact.str.contains("predictions"), "Changed Cells"].sum()
    if prediction_change:
        raise RuntimeError("Behavioral blocker: prediction artifact fields changed beyond experiment ID")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    args = parser.parse_args()
    print(review(args.old, args.new).query("`Changed Cells` > 0").to_string(index=False))
