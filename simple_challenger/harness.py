"""Deterministic, standard-library-only, synthetic challenger research harness.

The module deliberately has no production, recommendation, broker, or real-data
training authority.  Every fit path is guarded by manifest provenance.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

SYNTHETIC = "SYNTHETIC_TEST_FIXTURE"
REAL = "REAL_RESTRICTED_RESEARCH_DATASET"
MODEL_MARKER = "SYNTHETIC_TEST_MODEL_ONLY"
BLOCKED = "REAL_DATA_MODEL_TRAINING_BLOCKED_RIGHTS_NOT_READY"
RIGHTS_BLOCKING = {"LICENSE_REQUIRED", "PERMISSION_REQUIRED", "NOT_ESTABLISHED"}
REAL_SOURCE_TOKENS = ("NSE", "NIFTY", "BHAVCOPY", "RESTRICTED_MARKET_PANEL", "NSE_INDICES")
REQUIRED_FAMILIES = ("technical", "momentum", "volatility", "liquidity", "market")


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def iso_day(value: str) -> date:
    return date.fromisoformat(value[:10])


def source_is_real(manifest: dict) -> bool:
    bindings = canonical_json(manifest.get("source_manifest_bindings", [])).upper()
    return manifest.get("classification") == REAL or any(token in bindings for token in REAL_SOURCE_TOKENS)


def validate_dataset_manifest(manifest: dict, rows: list[dict]) -> str:
    if manifest.get("universe_method") == "CURRENT_SURVIVOR_UNIVERSE":
        raise ValueError("CURRENT_SURVIVOR_UNIVERSE_PROHIBITED")
    expected = canonical_hash(rows)
    if manifest.get("dataset_hash") != expected:
        raise ValueError("DATASET_HASH_MISMATCH")
    if source_is_real(manifest) and manifest.get("classification") == SYNTHETIC:
        raise ValueError("REAL_DATA_SYNTHETIC_SPOOF_BLOCKED")
    if manifest.get("classification") == SYNTHETIC:
        provenance = manifest.get("provenance", {})
        if provenance.get("synthetic_generation") is not True or not provenance.get("generator_id"):
            raise ValueError("SYNTHETIC_PROVENANCE_REQUIRED")
    return expected


def row_eligible(row: dict, training_cutoff: str | None = None) -> bool:
    if row.get("universe_method") == "CURRENT_SURVIVOR_UNIVERSE":
        raise ValueError("CURRENT_SURVIVOR_UNIVERSE_PROHIBITED")
    if row["feature_available_at"] > row["decision_cutoff"]:
        raise ValueError("FUTURE_FEATURE_PROHIBITED")
    if training_cutoff and row["label_available_at"] > training_cutoff:
        raise ValueError("LABEL_NOT_MATURE")
    return all((
        row.get("pit_universe_member") is True,
        row.get("investability_status") == "TRADABLE_LISTED_EQUITY",
        row.get("identity_status") == "RESOLVED",
        row.get("corporate_action_state") == "SAFE",
        row.get("feature_history_available") is True,
        row.get("warmup_status") == "COMPLETE",
    ))


def training_guard(manifest: dict, rows: list[dict], rights_state: str) -> None:
    validate_dataset_manifest(manifest, rows)
    if source_is_real(manifest) or manifest.get("classification") != SYNTHETIC:
        if rights_state != "READY":
            raise PermissionError(BLOCKED)
        raise PermissionError("REAL_DATA_TRAINING_OUT_OF_SCOPE_FOR_SYNTHETIC_HARNESS")


def append_invocation(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(record) + "\n")


def guarded_fit(adapter, manifest: dict, rows: list[dict], rights_state: str, audit_path: Path | None = None):
    allowed = False
    reason = "ALLOWED_SYNTHETIC_TEST_FIXTURE"
    try:
        training_guard(manifest, rows, rights_state)
        allowed = True
        model = adapter.fit(rows)
        return model
    except Exception as exc:
        reason = str(exc)
        raise
    finally:
        if audit_path:
            append_invocation(audit_path, {
                "schema": "NEXTGEN_TRAINING_INVOCATION_V1",
                "dataset_id": manifest.get("dataset_id"),
                "dataset_classification": manifest.get("classification"),
                "model_family": adapter.family,
                "rights_gate_state": rights_state,
                "allowed": allowed,
                "reason": reason,
                "timestamp": "2026-10-05T00:00:00Z",
                "code_version": "NEXTGEN_SIMPLE_CHALLENGER_V1",
            })


def feature_vector(row: dict, feature_ids: list[str]) -> list[float]:
    return [float(row["features"][name]) for name in feature_ids]


def _sigmoid(value: float) -> float:
    value = max(-35.0, min(35.0, value))
    return 1.0 / (1.0 + math.exp(-value))


@dataclass
class ModelArtifact:
    model_id: str
    family: str
    feature_ids: list[str]
    target: str
    seed: int
    configuration: dict
    state: dict
    marker: str = MODEL_MARKER
    authority: str = "RESEARCH_ONLY"
    promotion_authority: str = "NONE"
    trading_authority: bool = False

    def describe(self) -> dict:
        value = self.__dict__.copy()
        value["artifact_hash"] = canonical_hash(value)
        return value


class BaseAdapter:
    family = "BASE"

    def __init__(self, feature_ids: list[str], target="positive_relative_outcome", seed=1729, **config):
        if seed is None:
            raise ValueError("EXPLICIT_SEED_REQUIRED")
        self.feature_ids, self.target, self.seed, self.config = feature_ids, target, int(seed), config

    def describe(self):
        return {"interface": "NEXTGEN_MODEL_ADAPTER_V1", "family": self.family,
                "configuration": self.config, "features": self.feature_ids, "target": self.target,
                "seed": self.seed, "authority": "RESEARCH_ONLY"}


class ReferenceAdapter(BaseAdapter):
    family = "DETERMINISTIC_REFERENCE"

    def fit(self, rows):
        weights = {name: 1.0 / (index + 1) for index, name in enumerate(self.feature_ids)}
        return ModelArtifact("reference-v1", self.family, self.feature_ids, self.target, self.seed,
                             {"fixed_weights": weights}, {"weights": weights})

    @staticmethod
    def predict(model, rows):
        return [sum(row["features"][key] * value for key, value in model.state["weights"].items()) for row in rows]


class LogisticAdapter(BaseAdapter):
    family = "LOGISTIC_REGRESSION"

    def fit(self, rows):
        rate = float(self.config.get("learning_rate", 0.08))
        iterations = int(self.config.get("iterations", 180))
        weights = [0.0] * (len(self.feature_ids) + 1)
        for _ in range(iterations):
            gradient = [0.0] * len(weights)
            for row in rows:
                x = [1.0] + feature_vector(row, self.feature_ids)
                error = _sigmoid(sum(a * b for a, b in zip(weights, x))) - float(row[self.target])
                for index, value in enumerate(x):
                    gradient[index] += error * value
            scale = rate / max(1, len(rows))
            weights = [value - scale * gradient[index] for index, value in enumerate(weights)]
        config = {"learning_rate": rate, "iterations": iterations, "hyperparameter_search": False,
                  "score_semantics": "UNCALIBRATED_MODEL_SCORE"}
        return ModelArtifact("logistic-v1", self.family, self.feature_ids, self.target, self.seed,
                             config, {"weights": weights})

    @staticmethod
    def predict(model, rows):
        return [_sigmoid(model.state["weights"][0] + sum(
            weight * value for weight, value in zip(model.state["weights"][1:], feature_vector(row, model.feature_ids)))) for row in rows]


def _best_stump(rows, feature_ids, target, candidates=None):
    candidates = candidates or feature_ids
    best = None
    for feature in candidates:
        values = sorted(float(row["features"][feature]) for row in rows)
        threshold = values[len(values) // 2]
        left = [float(row[target]) for row in rows if row["features"][feature] <= threshold]
        right = [float(row[target]) for row in rows if row["features"][feature] > threshold]
        lmean = sum(left) / len(left) if left else 0.0
        rmean = sum(right) / len(right) if right else 0.0
        error = sum((float(row[target]) - (lmean if row["features"][feature] <= threshold else rmean)) ** 2 for row in rows)
        candidate = (error, feature, threshold, lmean, rmean)
        if best is None or candidate < best:
            best = candidate
    return {"feature": best[1], "threshold": best[2], "left": best[3], "right": best[4]}


def _stump_value(stump, row):
    return stump["left"] if row["features"][stump["feature"]] <= stump["threshold"] else stump["right"]


class RandomForestAdapter(BaseAdapter):
    family = "RANDOM_FOREST"

    def fit(self, rows):
        trees = int(self.config.get("trees", 17))
        rng, stumps = random.Random(self.seed), []
        for _ in range(trees):
            sample = [rows[rng.randrange(len(rows))] for _ in rows]
            candidates = sorted(rng.sample(self.feature_ids, max(1, int(math.sqrt(len(self.feature_ids))))))
            stumps.append(_best_stump(sample, self.feature_ids, self.target, candidates))
        return ModelArtifact("rf-v1", self.family, self.feature_ids, self.target, self.seed,
                             {"trees": trees, "max_depth": 1, "hyperparameter_search": False,
                              "score_semantics": "UNCALIBRATED_MODEL_SCORE"}, {"stumps": stumps})

    @staticmethod
    def predict(model, rows):
        return [sum(_stump_value(tree, row) for tree in model.state["stumps"]) / len(model.state["stumps"]) for row in rows]


class GradientBoostingAdapter(BaseAdapter):
    family = "GRADIENT_BOOSTING"

    def fit(self, rows):
        rounds, rate = int(self.config.get("rounds", 12)), float(self.config.get("learning_rate", 0.1))
        base = sum(float(row[self.target]) for row in rows) / len(rows)
        predictions, stumps = [base] * len(rows), []
        working = [dict(row) for row in rows]
        for _ in range(rounds):
            for index, row in enumerate(working):
                row["_residual"] = float(rows[index][self.target]) - predictions[index]
            stump = _best_stump(working, self.feature_ids, "_residual")
            stumps.append(stump)
            predictions = [value + rate * _stump_value(stump, row) for value, stump, row in zip(predictions, [stump] * len(rows), rows)]
        return ModelArtifact("gb-v1", self.family, self.feature_ids, self.target, self.seed,
                             {"rounds": rounds, "learning_rate": rate, "max_depth": 1,
                              "hyperparameter_search": False, "score_semantics": "UNCALIBRATED_MODEL_SCORE"},
                             {"base": base, "stumps": stumps, "learning_rate": rate})

    @staticmethod
    def predict(model, rows):
        return [model.state["base"] + model.state["learning_rate"] * sum(
            _stump_value(stump, row) for stump in model.state["stumps"]) for row in rows]


def temporal_fold(rows: list[dict], policy: dict) -> dict:
    if policy["method"] in {"RANDOM_SPLIT", "SHUFFLED_K_FOLD", "RANDOMIZED_CV"}:
        raise ValueError("RANDOM_TEMPORAL_SPLIT_PROHIBITED")
    embargo = int(policy.get("embargo_sessions", 0))
    train_end = iso_day(policy["train_end"])
    train_cutoff = train_end - timedelta(days=embargo)
    partitions = {"train": [], "validation": [], "test": [], "excluded_immature": []}
    for row in sorted(rows, key=lambda value: (value["decision_date"], value["security_id"])):
        day = iso_day(row["decision_date"])
        if day <= train_end:
            if iso_day(row["label_available_at"]) <= train_cutoff:
                partitions["train"].append(row)
            else:
                partitions["excluded_immature"].append(row)
        elif day <= iso_day(policy["validation_end"]):
            partitions["validation"].append(row)
        elif day <= iso_day(policy["test_end"]):
            partitions["test"].append(row)
    return {"schema": "NEXTGEN_TEMPORAL_FOLD_V1", "policy": policy,
            "counts": {key: len(value) for key, value in partitions.items()},
            "row_ids": {key: [row["row_id"] for row in value] for key, value in partitions.items()},
            "dataset_hash": canonical_hash(rows), "fold_hash": canonical_hash(partitions)}


def rank_predictions(rows: list[dict], scores: list[float], experiment_id: str, model: ModelArtifact,
                     dataset_hash: str, feature_set_hash: str) -> list[dict]:
    output = []
    dates = sorted({row["decision_date"] for row in rows})
    for day in dates:
        indexed = [(row, float(score)) for row, score in zip(rows, scores) if row["decision_date"] == day]
        indexed.sort(key=lambda item: (-item[1], item[0]["security_id"]))
        size = len(indexed)
        for rank, (row, score) in enumerate(indexed, 1):
            output.append({"schema": "NEXTGEN_CROSS_SECTIONAL_PREDICTION_V1", "experiment_id": experiment_id,
                           "model_id": model.model_id, "decision_date": day, "security_id": row["security_id"],
                           "model_score": score, "rank": rank, "percentile_rank": (size - rank + 1) / size,
                           "eligible_universe_size": size, "target": model.target,
                           "feature_set_hash": feature_set_hash, "dataset_hash": dataset_hash})
    return output


def top_k(predictions: list[dict], k) -> list[dict]:
    size = predictions[0]["eligible_universe_size"] if predictions else 0
    count = max(1, math.ceil(size * k)) if isinstance(k, float) else int(k)
    return sorted(predictions, key=lambda row: row["rank"])[:min(count, size)]


def _mean(values):
    return sum(values) / len(values) if values else None


def pearson(xs, ys):
    if len(xs) < 2 or len(xs) != len(ys): return "INSUFFICIENT_SAMPLE"
    mx, my = _mean(xs), _mean(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return numerator / denominator if denominator else "INSUFFICIENT_SAMPLE"


def _ranks(values):
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]: end += 1
        rank = (start + 1 + end) / 2
        for index in order[start:end]: ranks[index] = rank
        start = end
    return ranks


def rank_ic(xs, ys):
    return pearson(_ranks(xs), _ranks(ys)) if len(xs) >= 2 else "INSUFFICIENT_SAMPLE"


def ranking_metrics(predictions, outcomes, k=5):
    joined = [(row, outcomes[row["security_id"]]) for row in predictions if row["security_id"] in outcomes]
    if len(joined) < 2:
        return {key: "INSUFFICIENT_SAMPLE" for key in ("ic", "rank_ic", "precision_at_k", "top_k_mean_return", "top_k_relative_return", "hit_rate", "mean_rank_spread")}
    scores = [row["model_score"] for row, _ in joined]
    relative = [outcome["relative_return"] for _, outcome in joined]
    selected = top_k([row for row, _ in joined], k)
    chosen = [outcomes[row["security_id"]] for row in selected]
    bottom = sorted(joined, key=lambda pair: pair[0]["rank"], reverse=True)[:len(chosen)]
    return {"ic": pearson(scores, relative), "rank_ic": rank_ic(scores, relative),
            "precision_at_k": _mean([float(item["positive"]) for item in chosen]),
            "top_k_mean_return": _mean([item["absolute_return"] for item in chosen]),
            "top_k_relative_return": _mean([item["relative_return"] for item in chosen]),
            "hit_rate": _mean([float(item["relative_return"] > 0) for item in chosen]),
            "mean_rank_spread": _mean([item["relative_return"] for item in chosen]) - _mean([item[1]["relative_return"] for item in bottom])}


def roc_auc(labels, scores):
    positives, negatives = [i for i, y in enumerate(labels) if y], [i for i, y in enumerate(labels) if not y]
    if not positives or not negatives: return "INSUFFICIENT_SAMPLE"
    wins = sum(1 if scores[p] > scores[n] else .5 if scores[p] == scores[n] else 0 for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def pr_auc(labels, scores):
    if not any(labels): return "INSUFFICIENT_SAMPLE"
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    tp, area, recall0, total = 0, 0.0, 0.0, sum(labels)
    for rank, index in enumerate(order, 1):
        if labels[index]:
            tp += 1
            recall = tp / total
            area += (recall - recall0) * (tp / rank)
            recall0 = recall
    return area


def classification_metrics(labels, scores):
    brier = _mean([(float(y) - score) ** 2 for y, score in zip(labels, scores)])
    base = _mean(labels)
    baseline = _mean([(float(y) - base) ** 2 for y in labels])
    return {"roc_auc": roc_auc(labels, scores), "pr_auc": pr_auc(labels, scores), "brier": brier,
            "baseline_brier": baseline, "brier_skill": (1 - brier / baseline) if baseline else "INSUFFICIENT_SAMPLE",
            "calibration_state": "UNCALIBRATED_MODEL_SCORE"}


def economic_evaluation(returns, costs, benchmark_returns, positions, rejected, turnovers):
    gross = sum(returns)
    total_cost = sum(costs)
    net_series = [ret - cost for ret, cost in zip(returns, costs)]
    cumulative, peak, max_drawdown = 0.0, 0.0, 0.0
    for value in net_series:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    wins, losses = [x for x in net_series if x > 0], [x for x in net_series if x < 0]
    return {"schema": "NEXTGEN_ECONOMIC_EVALUATION_V1", "gross_return": gross,
            "transaction_costs": total_cost, "net_return": sum(net_series),
            "benchmark_relative_return": sum(net_series) - sum(benchmark_returns),
            "number_of_positions": sum(positions), "rejected_untradeable_selections": sum(rejected),
            "turnover": sum(turnovers), "maximum_drawdown": max_drawdown,
            "win_rate": len(wins) / len(net_series) if net_series else "INSUFFICIENT_SAMPLE",
            "expectancy": _mean(net_series) if net_series else "INSUFFICIENT_SAMPLE",
            "profit_factor": sum(wins) / abs(sum(losses)) if losses else ("INSUFFICIENT_SAMPLE" if not wins else "INFINITE")}


class ExperimentRegistry:
    def __init__(self): self.records = {}
    def register(self, manifest):
        identity, payload_hash = manifest["experiment_id"], canonical_hash(manifest)
        if identity in self.records and self.records[identity] != payload_hash:
            raise ValueError("EXPERIMENT_IDENTITY_CONFLICT")
        state = "IDEMPOTENT_SUCCESS" if identity in self.records else "CREATED"
        self.records[identity] = payload_hash
        return state


def synthetic_fixture(days=18, securities=24, seed=1729):
    rng, rows = random.Random(seed), []
    start = date(2026, 1, 1)
    for day_index in range(days):
        decision = start + timedelta(days=day_index)
        for security_index in range(securities):
            security = f"SYN-{security_index:03d}"
            signal = math.sin((security_index + day_index) / 4) + rng.uniform(-.15, .15)
            features = {"technical_5": signal, "momentum_20": signal * .7 + rng.uniform(-.1, .1),
                        "volatility_20": abs(rng.gauss(.25, .08)), "liquidity_20": 1 + rng.random(),
                        "market_20": math.sin(day_index / 5)}
            relative = .018 * signal - .006 * features["volatility_20"] + rng.uniform(-.01, .01)
            absolute = relative + .002 * features["market_20"]
            rows.append({"row_id": f"{decision}:{security}", "decision_date": str(decision),
                         "decision_cutoff": f"{decision}T15:30:00+05:30", "security_id": security,
                         "isin": f"SYNTHETIC{security_index:04d}", "symbol": security,
                         "pit_universe_member": True, "universe_method": "PIT_MEMBERSHIP",
                         "investability_status": "TRADABLE_LISTED_EQUITY", "identity_status": "RESOLVED",
                         "corporate_action_state": "SAFE", "feature_history_available": True,
                         "warmup_status": "COMPLETE", "feature_available_at": f"{decision}T15:30:00+05:30",
                         "label_available_at": str(decision + timedelta(days=5)),
                         "benchmark_binding": "SYNTHETIC_BENCHMARK_V1", "execution_policy_binding": "SYNTHETIC_EXECUTION_V1",
                         "source_manifest_binding": "SYNTHETIC_GENERATOR_V1", "dataset_classification": SYNTHETIC,
                         "features": features, "absolute_return": absolute, "relative_return": relative,
                         "ranking_target": relative, "positive_relative_outcome": int(relative > 0)})
    manifest = {"schema": "NEXTGEN_CROSS_SECTIONAL_DATASET_CONTRACT_V1", "dataset_id": "synthetic-challenger-v1",
                "classification": SYNTHETIC, "universe_method": "PIT_MEMBERSHIP",
                "source_manifest_bindings": ["SYNTHETIC_GENERATOR_V1"],
                "provenance": {"synthetic_generation": True, "generator_id": "DETERMINISTIC_SYNTHETIC_V1", "seed": seed}}
    manifest["dataset_hash"] = canonical_hash(rows)
    return manifest, rows


def stability_analysis(rows, predictions):
    score = {item["security_id"] + item["decision_date"]: item["model_score"] for item in predictions}
    groups = {"temporal_segment": {}, "market_direction": {}, "volatility_regime": {}}
    for row in rows:
        segment = "EARLY" if iso_day(row["decision_date"]).day <= 9 else "LATE"
        market = "UP" if row["features"]["market_20"] >= 0 else "DOWN"
        volatility = "HIGH" if row["features"]["volatility_20"] >= .25 else "LOW"
        key = row["security_id"] + row["decision_date"]
        for group, label in (("temporal_segment", segment), ("market_direction", market), ("volatility_regime", volatility)):
            groups[group].setdefault(label, []).append((score[key], row["relative_return"]))
    return {"schema": "NEXTGEN_MODEL_STABILITY_ANALYSIS_V1", "groups": {
        group: {label: {"count": len(values), "ic": pearson([x for x, _ in values], [y for _, y in values])}
                for label, values in labels.items()} for group, labels in groups.items()}, "automatic_acceptance": False}
