from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    code: str
    ranking_source: str
    mode: str
    target: str
    model_variant: str
    feature_set: str
    primary: str


POLICIES = (
    Policy("R0", "Actionability DESC; Technical DESC", "NONE", "NONE", "NONE", "NONE", "CONTROL"),
    Policy("R1", "Frozen predicted probability DESC", "PRIMARY_ONLY", "T1_BEFORE_STOP_63", "LOGIT_FULL", "FS3_FULL_SIGNAL_STATE", "PRIMARY"),
    Policy("R2", "Frozen predicted probability DESC", "PRIMARY_ONLY", "T1_BEFORE_STOP_63", "LOGIT_RAW", "FS2_RAW_SIGNAL_STATE", "PRIMARY"),
    Policy("R3", "Frozen predicted probability DESC", "TRANSFER", "JOINT_T1", "LOGIT_FULL", "FS3_FULL_SIGNAL_STATE", "PRIMARY"),
    Policy("R4", "Frozen predicted probability DESC", "TRANSFER", "JOINT_T1", "LOGIT_RAW", "FS2_RAW_SIGNAL_STATE", "PRIMARY"),
    Policy("R5", "Frozen predicted probability DESC", "TRANSFER", "ENTRY_FILLED", "RF_FULL", "FS3_FULL_SIGNAL_STATE", "DIAGNOSTIC"),
)


def registry() -> list[dict[str, object]]:
    rows = [{
        "Policy": "ALL_BASELINE_PRIMARY", "Ranking Source": "NONE", "Prediction Mode": "NONE",
        "Target": "NONE", "Model Variant": "NONE", "Feature Set": "NONE", "Daily K": "ALL",
        "Primary/Diagnostic": "SYSTEM_REFERENCE", "Exit Engine": "D1 and D0", "Selection Timestamp": "SIGNAL SESSION CLOSE",
        "Tie Rule": "Signal ID ASC", "Probability Threshold": "NONE", "Uses Future Data": "NO", "ML Model Retrained": "NO",
    }]
    for policy in POLICIES:
        for k in (1, 2):
            rows.append({
                "Policy": f"{policy.code}_K{k}", "Ranking Source": policy.ranking_source,
                "Prediction Mode": policy.mode, "Target": policy.target, "Model Variant": policy.model_variant,
                "Feature Set": policy.feature_set, "Daily K": k, "Primary/Diagnostic": policy.primary,
                "Exit Engine": "D1 and D0", "Selection Timestamp": "SIGNAL SESSION CLOSE",
                "Tie Rule": "Signal ID ASC", "Probability Threshold": "NONE", "Uses Future Data": "NO", "ML Model Retrained": "NO",
            })
    return rows
