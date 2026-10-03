"""Deterministic score terminology and calibration evaluation."""
from __future__ import annotations

import math
from collections import defaultdict

from common import record, sha256


def audit_term(field_name: str, metadata: dict) -> str:
    if metadata.get("legacy_immutable"):
        return "LEGACY_IMMUTABLE_FIELD"
    if metadata.get("rule_based"):
        return "RULE_SCORE"
    if metadata.get("ranking_only"):
        return "RANKING_SCORE"
    if metadata.get("calibration_artifact_status") == "SUFFICIENT_EVIDENCE":
        return "CALIBRATED_PROBABILITY"
    if metadata.get("model_output") or metadata.get("produced_by") == "predict_proba":
        return "UNCALIBRATED_MODEL_SCORE"
    return "UNKNOWN_SEMANTICS"


def report_label(field_name: str, semantics: str) -> str:
    if semantics == "LEGACY_IMMUTABLE_FIELD":
        return field_name
    if semantics == "CALIBRATED_PROBABILITY":
        return "probability"
    if semantics == "RANKING_SCORE":
        return "ranking_score"
    if semantics in {"UNCALIBRATED_MODEL_SCORE", "UNKNOWN_SEMANTICS"}:
        return "model_score"
    return "signal_score"


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float | None, float | None]:
    if len(set(xs)) < 2:
        return None, None
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        return None, None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / variance
    return mean_y - slope * mean_x, slope


def evaluate_calibration(rows: list[dict], *, model_id: str, model_hash: str, dataset_id: str,
                         dataset_hash: str, cutoff: str, target: str, policy: dict) -> dict:
    n = len(rows)
    minimum = int(policy["minimum_sample"])
    if n < minimum:
        return record("CALIBRATION_EVALUATION_V1", {
            "model_id": model_id, "model_hash": model_hash, "dataset_id": dataset_id,
            "dataset_hash": dataset_hash, "evaluation_cutoff": cutoff, "target": target,
            "sample_count": n, "status": "INSUFFICIENT_SAMPLE_FOR_CALIBRATION",
            "policy_id": policy["policy_id"], "policy_hash": sha256(policy),
        })
    probabilities = [float(r["score"]) for r in rows]
    outcomes = [int(r["outcome"]) for r in rows]
    if any(p < 0 or p > 1 for p in probabilities) or any(y not in {0, 1} for y in outcomes):
        raise ValueError("invalid calibration data")
    prevalence = sum(outcomes) / n
    brier = sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / n
    baseline = sum((prevalence - y) ** 2 for y in outcomes) / n
    skill = None if baseline == 0 else 1 - brier / baseline
    bucket_count = int(policy["bucket_count"])
    buckets = []
    for index in range(bucket_count):
        selected = [(p, y) for p, y in zip(probabilities, outcomes) if min(int(p * bucket_count), bucket_count - 1) == index]
        if selected:
            buckets.append({"bucket": index, "count": len(selected), "predicted_mean": sum(p for p, _ in selected) / len(selected), "observed_rate": sum(y for _, y in selected) / len(selected)})
    intercept, slope = _linear_fit(probabilities, outcomes)
    def groups(field: str) -> dict:
        grouped = defaultdict(list)
        for row in rows:
            grouped[row.get(field, "NOT_AVAILABLE")].append(row)
        return {k: ({"status": "SUFFICIENT", "count": len(v), "brier": sum((float(x["score"]) - int(x["outcome"])) ** 2 for x in v) / len(v)} if len(v) >= int(policy["minimum_group_sample"]) else {"status": "INSUFFICIENT_SAMPLE", "count": len(v)}) for k, v in sorted(grouped.items())}
    return record("CALIBRATION_EVALUATION_V1", {
        "model_id": model_id, "model_hash": model_hash, "dataset_id": dataset_id,
        "dataset_hash": dataset_hash, "evaluation_cutoff": cutoff, "target": target,
        "sample_count": n, "positive_count": sum(outcomes), "negative_count": n - sum(outcomes),
        "score_semantics": "UNCALIBRATED_MODEL_SCORE", "brier_score": brier,
        "baseline_brier_score": baseline, "brier_skill_score": skill,
        "reliability_buckets": buckets, "calibration_intercept": intercept,
        "calibration_slope": slope, "temporal_analysis": groups("window"),
        "regime_analysis": groups("regime"), "status": "EVALUATED_NOT_OPERATIONAL",
        "policy_id": policy["policy_id"], "policy_hash": sha256(policy),
    })

