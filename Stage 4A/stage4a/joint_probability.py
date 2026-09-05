"""Research-only composition of fill and conditional target probabilities."""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_joint_predictions(predictions: pd.DataFrame, opportunity: pd.DataFrame) -> pd.DataFrame:
    metadata = opportunity.set_index("Signal ID")
    entry = predictions.loc[predictions["Target"].eq("ENTRY_FILLED")].copy()
    rows = []
    for conditional_target, joint_target in [
        ("T1_BEFORE_STOP_63", "JOINT_T1"),
        ("T2_BEFORE_STOP_63", "JOINT_T2"),
    ]:
        conditional = predictions.loc[predictions["Target"].eq(conditional_target)].copy()
        merge_keys = ["Signal ID", "Evaluation Year", "Model Variant"]
        merged = entry.merge(
            conditional,
            on=merge_keys,
            suffixes=(" Entry", " Conditional"),
            validate="one_to_one",
        )
        target_number = "T1" if joint_target == "JOINT_T1" else "T2"
        target_label = f"{target_number}_BEFORE_STOP_63"
        target_status = f"{target_number}_STATUS"
        target_available = f"{target_number}_LABEL_AVAILABLE_DATE"
        for record in merged.to_dict("records"):
            source = metadata.loc[record["Signal ID"]]
            entry_status = str(source["ENTRY_STATUS"])
            target_state = str(source[target_status])
            actual = np.nan
            label_status = "EXCLUDED"
            label_available_date = pd.NaT
            if entry_status == "NOT_FILLED":
                actual = 0.0
                label_status = "AVAILABLE_NON_FILL"
                label_available_date = source["ENTRY_LABEL_AVAILABLE_DATE"]
            elif entry_status == "FILLED" and bool(source["ENTRY_RISK_VALID"]) and target_state == "AVAILABLE":
                actual = float(source[target_label])
                label_status = "AVAILABLE_VALID_FILL"
                label_available_date = source[target_available]
            elif entry_status == "DATA_END_CENSORED":
                label_status = "ENTRY_DATA_END_CENSORED"
            elif entry_status == "FILLED_INVALID_RISK" or not bool(source["ENTRY_RISK_VALID"]):
                label_status = "FILLED_INVALID_RISK"
            elif target_state == "DATA_END_CENSORED":
                label_status = f"{target_number}_DATA_END_CENSORED"
            probability = float(record["Predicted Probability Entry"] * record["Predicted Probability Conditional"])
            training_prior = float(record["Training Prior Entry"] * record["Training Prior Conditional"])
            rows.append({
                "Signal ID": record["Signal ID"],
                "Ticker": record["Ticker Entry"],
                "Signal Date": record["Signal Date Entry"],
                "Dataset Cohort": record["Dataset Cohort Entry"],
                "Original Signal": record["Original Signal Entry"],
                "Setup": record["Setup Entry"],
                "Market Regime": record["Market Regime Entry"],
                "Actionability Score": record["Actionability Score Entry"],
                "Technical Score": record["Technical Score Entry"],
                "Evaluation Year": record["Evaluation Year"],
                "Target": joint_target,
                "Model Variant": record["Model Variant"],
                "Feature Set": record["Feature Set Entry"],
                "Entry Model Spec Hash": record["Model Spec Hash Entry"],
                "Conditional Model Spec Hash": record["Model Spec Hash Conditional"],
                "Entry Feature Set Hash": record["Feature Set Hash Entry"],
                "Conditional Feature Set Hash": record["Feature Set Hash Conditional"],
                "Stage 3.1 Experiment ID": record["Stage 3.1 Experiment ID Entry"],
                "Stage 4A Experiment ID": record["Stage 4A Experiment ID Entry"],
                "Training Cutoff Date": record["Training Cutoff Date Entry"],
                "P Fill": record["Predicted Probability Entry"],
                f"P {target_number} Conditional": record["Predicted Probability Conditional"],
                "Predicted Probability": probability,
                "Actual Label": actual,
                "Label Status": label_status,
                "Label Available Date": label_available_date,
                "Training Prior Entry": record["Training Prior Entry"],
                "Training Prior Conditional": record["Training Prior Conditional"],
                "Training Prior": training_prior,
                "Training Rows Entry": record["Training Rows Entry"],
                "Training Rows Conditional": record["Training Rows Conditional"],
            })
    result = pd.DataFrame(rows)
    return result.sort_values(["Target", "Evaluation Year", "Model Variant", "Signal ID"], kind="mergesort").reset_index(drop=True)


def assert_joint_arithmetic(joint: pd.DataFrame) -> None:
    t1 = joint["Target"].eq("JOINT_T1")
    t2 = joint["Target"].eq("JOINT_T2")
    expected = np.empty(len(joint), dtype=float)
    expected[t1.to_numpy()] = joint.loc[t1, "P Fill"] * joint.loc[t1, "P T1 Conditional"]
    expected[t2.to_numpy()] = joint.loc[t2, "P Fill"] * joint.loc[t2, "P T2 Conditional"]
    # In-memory construction is exact. Reloaded artifacts use the declared %.12g
    # serialization, whose independent component rounding can move the product by
    # up to roughly two units at the final stored decimal place.
    if not np.allclose(
        joint["Predicted Probability"].to_numpy(), expected, rtol=0.0, atol=2e-12,
    ):
        raise AssertionError("Joint probability arithmetic exceeds serialized precision")
