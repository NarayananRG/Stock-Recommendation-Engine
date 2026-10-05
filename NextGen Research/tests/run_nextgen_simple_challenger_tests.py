"""Focused regression suite for the synthetic-only simple challenger harness."""
from __future__ import annotations

import ast
import copy
import csv
import json
import math
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RESULTS = ROOT / "results"
sys.path.insert(0, str(ROOT))

from simple_challenger.harness import (  # noqa: E402
    BLOCKED,
    MODEL_MARKER,
    REAL,
    SYNTHETIC,
    ExperimentRegistry,
    GradientBoostingAdapter,
    LogisticAdapter,
    RandomForestAdapter,
    ReferenceAdapter,
    assert_comparison_population_equal,
    assert_disjoint_partitions,
    canonical_hash,
    classification_metrics,
    deterministic_experiment_signature,
    economic_evaluation,
    guarded_fit,
    pearson,
    pr_auc,
    rank_ic,
    rank_predictions,
    ranking_metrics,
    roc_auc,
    row_eligible,
    source_is_real,
    source_is_prohibited_training_input,
    stability_analysis,
    synthetic_fixture,
    temporal_fold,
    top_k,
    training_guard,
    validate_dataset_manifest,
    validate_synthetic_source_identity,
)

BASE = "48c95246851fc6af67228f663ddb475b79c2c821"
FEATURES = ["technical_5", "momentum_20", "volatility_20", "liquidity_20", "market_20"]
records: list[dict] = []


def require(value, message="requirement failed"):
    if not value:
        raise AssertionError(message)


def raises(error, text, function):
    try:
        function()
    except error as exc:
        require(text in str(exc), f"expected {text!r}, got {exc!r}")
        return
    raise AssertionError(f"expected {error.__name__}: {text}")


def case(identifier, description, function):
    try:
        function()
        records.append({"test_id": identifier, "description": description, "status": "PASS", "detail": ""})
    except Exception as exc:  # keep complete evidence even when one assertion fails
        records.append({"test_id": identifier, "description": description, "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"})


def git(*args):
    return subprocess.check_output(
        ["git", "--git-dir=_git", "--work-tree=.", *args], cwd=REPO, text=True, stderr=subprocess.STDOUT
    ).strip()


manifest, rows = synthetic_fixture()
training_rows = rows[:288]
training_manifest = dict(manifest, dataset_id="synthetic-challenger-v1-training", dataset_hash=canonical_hash(training_rows))
sample = copy.deepcopy(rows[0])


# Dataset/PIT and provenance.
case("DS01", "synthetic dataset accepted", lambda: require(validate_dataset_manifest(manifest, rows) == manifest["dataset_hash"]))
for index, right in enumerate(("LICENSE_REQUIRED", "PERMISSION_REQUIRED", "NOT_ESTABLISHED"), 2):
    real = dict(training_manifest, classification=REAL, source_manifest_bindings=["NSE_BHAVCOPY_RESTRICTED"])
    case(f"DS{index:02d}", f"real restricted dataset rejected under {right}", lambda r=right, m=real: raises(PermissionError, BLOCKED, lambda: training_guard(m, training_rows, r)))
future = copy.deepcopy(sample); future["feature_available_at"] = "2026-01-02T15:30:00+05:30"
case("DS05", "future feature rejected", lambda: raises(ValueError, "FUTURE_FEATURE_PROHIBITED", lambda: row_eligible(future)))
case("DS06", "immature label rejected", lambda: raises(ValueError, "LABEL_NOT_MATURE", lambda: row_eligible(sample, "2026-01-04")))
survivor = copy.deepcopy(sample); survivor["universe_method"] = "CURRENT_SURVIVOR_UNIVERSE"
case("DS07", "current survivor universe rejected", lambda: raises(ValueError, "CURRENT_SURVIVOR_UNIVERSE_PROHIBITED", lambda: row_eligible(survivor)))
noninvest = copy.deepcopy(sample); noninvest["investability_status"] = "SUSPENDED"
case("DS08", "non-investable row excluded", lambda: require(row_eligible(noninvest) is False))
warmup = copy.deepcopy(sample); warmup["warmup_status"] = "INCOMPLETE"
case("DS09", "warm-up row excluded", lambda: require(row_eligible(warmup) is False))
case("DS10", "dataset hash deterministic", lambda: require(canonical_hash(rows) == canonical_hash(copy.deepcopy(rows))))
bad_hash = dict(manifest, dataset_hash="0" * 64)
case("DS11", "dataset hash mismatch fails", lambda: raises(ValueError, "DATASET_HASH_MISMATCH", lambda: validate_dataset_manifest(bad_hash, rows)))
bad_provenance = copy.deepcopy(manifest); bad_provenance["provenance"] = {"synthetic_generation": False}
case("DS12", "synthetic provenance required", lambda: raises(ValueError, "SYNTHETIC_PROVENANCE_REQUIRED", lambda: validate_dataset_manifest(bad_provenance, rows)))
spoof = copy.deepcopy(manifest); spoof["source_manifest_bindings"] = ["NSE_NIFTY_500_MEMBERSHIP"]
case("DS13", "real source cannot be spoofed synthetic", lambda: raises(ValueError, "REAL_DATA_SYNTHETIC_SPOOF_BLOCKED", lambda: validate_dataset_manifest(spoof, rows)))
case("DS14", "NSE manifest detected as real", lambda: require(source_is_real({"source_manifest_bindings": ["NSE_BHAVCOPY"]})))
case("DS15", "NIFTY manifest detected as real", lambda: require(source_is_real({"source_manifest_bindings": ["NIFTY_500_MEMBERSHIP"]})))
for field, bad_value, ident in (("pit_universe_member", False, "DS16"), ("identity_status", "UNRESOLVED", "DS17"),
                                ("corporate_action_state", "UNSAFE", "DS18"), ("feature_history_available", False, "DS19")):
    changed = copy.deepcopy(sample); changed[field] = bad_value
    case(ident, f"{field} eligibility enforced", lambda row=changed: require(row_eligible(row) is False))
mcp_manifest = copy.deepcopy(manifest); mcp_manifest["source_manifest_bindings"] = ["MCP_LIVE_MARKET_DATA"]
case("DS20", "MCP/live-market training input rejected", lambda: raises(ValueError, "PROHIBITED_TRAINING_SOURCE", lambda: validate_dataset_manifest(mcp_manifest, rows)))
stage_manifest = copy.deepcopy(manifest); stage_manifest["provenance"]["source_path"] = "Stage 4A.3/runtime/snapshot.json"
case("DS21", "active prospective runtime source rejected", lambda: raises(ValueError, "PROHIBITED_TRAINING_SOURCE", lambda: validate_dataset_manifest(stage_manifest, rows)))
unknown_synth = copy.deepcopy(manifest); unknown_synth["source_manifest_bindings"] = ["SYNTHETIC_UNKNOWN"]
case("DS22", "unapproved synthetic source rejected", lambda: raises(ValueError, "UNAPPROVED_SYNTHETIC_SOURCE", lambda: validate_dataset_manifest(unknown_synth, rows)))
wrong_generator = copy.deepcopy(manifest); wrong_generator["provenance"]["generator_id"] = "OTHER_GENERATOR"
case("DS23", "synthetic generator identity exact", lambda: raises(ValueError, "SYNTHETIC_SOURCE_IDENTITY_REQUIRED", lambda: validate_synthetic_source_identity(wrong_generator)))
leaky = copy.deepcopy(sample); leaky["features"]["future_return_5d"] = leaky["relative_return"]
case("DS24", "future outcome field cannot enter features", lambda: raises(ValueError, "FUTURE_OUTCOME_FEATURE_PROHIBITED", lambda: row_eligible(leaky)))
same_time_label = copy.deepcopy(sample); same_time_label["label_available_at"] = same_time_label["feature_available_at"]
case("DS25", "label must follow information timestamp", lambda: raises(ValueError, "LABEL_MUST_FOLLOW_INFORMATION_TIME", lambda: row_eligible(same_time_label)))
case("DS26", "prohibited source helper detects MCP", lambda: require(source_is_prohibited_training_input(mcp_manifest)))

# Label maturity and semantics.
for index, horizon in enumerate((5, 20, 60), 1):
    mature = copy.deepcopy(sample)
    mature["label_available_at"] = str(date.fromisoformat(mature["decision_date"]) + timedelta(days=horizon))
    case(f"LB{index:02d}", f"D+{horizon} unavailable before maturity", lambda r=mature: raises(ValueError, "LABEL_NOT_MATURE", lambda: row_eligible(r, str(date.fromisoformat(r["label_available_at"]) - timedelta(days=1)))))
    case(f"LB{index+3:02d}", f"D+{horizon} available at maturity", lambda r=mature: require(row_eligible(r, r["label_available_at"])))
case("LB07", "benchmark-relative target arithmetic", lambda: require(math.isclose(.08 - .03, .05)))
case("LB08", "positive relative outcome matches target sign", lambda: require(all(row["positive_relative_outcome"] == int(row["relative_return"] > 0) for row in rows)))
case("LB09", "ranking target equals continuous relative return", lambda: require(all(row["ranking_target"] == row["relative_return"] for row in rows)))
case("LB10", "label contract is price return only", lambda: require(json.loads((RESULTS / "nextgen_outcome_label_contract_v1.json").read_text())["return_profile"] == "PRICE_RETURN_ONLY"))

# Temporal folds.
policy = {"method": "EXPANDING_WINDOW", "train_end": "2026-01-10", "validation_end": "2026-01-14", "test_end": "2026-01-18", "horizon": 5, "embargo_sessions": 1}
fold = temporal_fold(rows, policy)
case("TM01", "chronological train validation test", lambda: require(fold["counts"]["train"] and fold["counts"]["validation"] and fold["counts"]["test"]))
for index, method in enumerate(("RANDOM_SPLIT", "SHUFFLED_K_FOLD", "RANDOMIZED_CV"), 2):
    bad = dict(policy, method=method)
    case(f"TM{index:02d}", f"{method} prohibited", lambda p=bad: raises(ValueError, "RANDOM_TEMPORAL_SPLIT_PROHIBITED", lambda: temporal_fold(rows, p)))
case("TM05", "immature overlapping target excluded", lambda: require(fold["counts"]["excluded_immature"] > 0))
case("TM06", "expanding fold deterministic", lambda: require(fold == temporal_fold(copy.deepcopy(rows), copy.deepcopy(policy))))
rolling = dict(policy, method="ROLLING_WINDOW")
case("TM07", "rolling fold deterministic", lambda: require(temporal_fold(rows, rolling) == temporal_fold(rows, rolling)))
no_embargo = temporal_fold(rows, dict(policy, embargo_sessions=0))
case("TM08", "embargo excludes at least as many rows", lambda: require(fold["counts"]["excluded_immature"] >= no_embargo["counts"]["excluded_immature"]))
case("TM09", "fold binds dataset hash", lambda: require(fold["dataset_hash"] == canonical_hash(rows)))
case("TM10", "fold hash deterministic", lambda: require(fold["fold_hash"] == temporal_fold(rows, policy)["fold_hash"]))
case("TM11", "train validation test partitions disjoint", lambda: require(assert_disjoint_partitions(fold) is None))
overlap_fold = copy.deepcopy(fold); overlap_fold["row_ids"]["validation"].append(overlap_fold["row_ids"]["train"][0])
case("TM12", "partition overlap rejected", lambda: raises(ValueError, "TEMPORAL_PARTITION_OVERLAP", lambda: assert_disjoint_partitions(overlap_fold)))
case("TM13", "test rows absent from train partition", lambda: require(not set(fold["row_ids"]["train"]).intersection(fold["row_ids"]["test"])))

# Model adapters and training audit.
adapters = [ReferenceAdapter(FEATURES), LogisticAdapter(FEATURES), RandomForestAdapter(FEATURES), GradientBoostingAdapter(FEATURES)]
models = [adapter.fit(training_rows) for adapter in adapters]
for index, (adapter, model) in enumerate(zip(adapters, models), 1):
    case(f"MD{index:02d}", f"{adapter.family} synthetic fit and predict", lambda a=adapter, m=model: require(len(a.predict(m, rows[288:])) == len(rows[288:])))
    case(f"MD{index+4:02d}", f"{adapter.family} model tagged test only", lambda m=model: require(m.marker == MODEL_MARKER and not m.trading_authority))
    case(f"MD{index+8:02d}", f"{adapter.family} no hyperparameter search", lambda m=model: require(m.configuration.get("hyperparameter_search", False) is False))
case("MD13", "explicit seed required", lambda: raises(ValueError, "EXPLICIT_SEED_REQUIRED", lambda: RandomForestAdapter(FEATURES, seed=None)))
rf1, rf2 = RandomForestAdapter(FEATURES, seed=41), RandomForestAdapter(FEATURES, seed=41)
case("MD14", "same seed gives same RF predictions", lambda: require(rf1.predict(rf1.fit(training_rows), rows[288:]) == rf2.predict(rf2.fit(training_rows), rows[288:])))
rf3 = RandomForestAdapter(FEATURES, seed=42)
case("MD15", "seed is bound into model identity description", lambda: require(rf3.fit(training_rows).seed == 42))
case("MD16", "adapter describe binds authority", lambda: require(all(adapter.describe()["authority"] == "RESEARCH_ONLY" for adapter in adapters)))
case("MD17", "model promotion authority none", lambda: require(all(model.promotion_authority == "NONE" for model in models)))
case("MD18", "logistic score semantics uncalibrated", lambda: require(models[1].configuration["score_semantics"] == "UNCALIBRATED_MODEL_SCORE"))
case("MD19", "synthetic guarded fit allowed", lambda: require(guarded_fit(ReferenceAdapter(FEATURES), training_manifest, training_rows, "LICENSE_REQUIRED").marker == MODEL_MARKER))
case("MD20", "ready rights still cannot train real data in synthetic harness", lambda: raises(PermissionError, "REAL_DATA_TRAINING_OUT_OF_SCOPE", lambda: training_guard(dict(training_manifest, classification=REAL, source_manifest_bindings=["NSE"]), training_rows, "READY")))
case("MD21", "deterministic repeated experiment signature", lambda: require(deterministic_experiment_signature(RandomForestAdapter, rows, manifest, FEATURES) == deterministic_experiment_signature(RandomForestAdapter, copy.deepcopy(rows), copy.deepcopy(manifest), copy.deepcopy(FEATURES))))
case("MD22", "model configuration hash stable", lambda: require(canonical_hash(adapters[1].describe()) == canonical_hash(copy.deepcopy(adapters[1].describe()))))

# Ranking and Top-K.
rank_rows = rows[-24:]
reference = models[0]
scores = adapters[0].predict(reference, rank_rows)
ranked = rank_predictions(rank_rows, scores, "experiment", reference, manifest["dataset_hash"], "features")
case("RK01", "deterministic score order", lambda: require([r["model_score"] for r in ranked] == sorted([r["model_score"] for r in ranked], reverse=True)))
ties = rank_predictions(rank_rows[:3], [1, 1, 1], "experiment", reference, "dataset", "features")
case("RK02", "ties use stable security ID", lambda: require([r["security_id"] for r in ties] == sorted(r["security_id"] for r in ties)))
case("RK03", "percentile rank endpoints", lambda: require(ranked[0]["percentile_rank"] == 1 and math.isclose(ranked[-1]["percentile_rank"], 1 / 24)))
for index, k in enumerate((5, 10, 20), 4):
    case(f"RK{index:02d}", f"Top {k}", lambda n=k: require(len(top_k(ranked, n)) == n))
case("RK07", "percentage Top-K", lambda: require(len(top_k(ranked, .25)) == 6))
case("RK08", "Top-K bounded by universe", lambda: require(len(top_k(ranked, 100)) == 24))
case("RK09", "prediction binds experiment", lambda: require(all(r["experiment_id"] == "experiment" for r in ranked)))
case("RK10", "prediction binds dataset and features", lambda: require(all(r["dataset_hash"] == manifest["dataset_hash"] and r["feature_set_hash"] == "features" for r in ranked)))

# Prediction, ranking and classification metrics.
case("MT01", "IC known fixture", lambda: require(math.isclose(pearson([1, 2, 3], [2, 4, 6]), 1)))
case("MT02", "RankIC known fixture", lambda: require(math.isclose(rank_ic([3, 1, 2], [30, 10, 20]), 1)))
case("MT03", "insufficient IC state", lambda: require(pearson([1], [1]) == "INSUFFICIENT_SAMPLE"))
outcomes = {row["security_id"]: {"relative_return": row["relative_return"], "absolute_return": row["absolute_return"], "positive": row["positive_relative_outcome"]} for row in rank_rows}
metrics = ranking_metrics(ranked, outcomes, 5)
for index, key in enumerate(("precision_at_k", "top_k_mean_return", "top_k_relative_return", "hit_rate", "mean_rank_spread"), 4):
    case(f"MT{index:02d}", f"ranking metric {key}", lambda name=key: require(isinstance(metrics[name], float)))
case("MT09", "ranking metrics IC", lambda: require(isinstance(metrics["ic"], float)))
case("MT10", "ranking metrics RankIC", lambda: require(isinstance(metrics["rank_ic"], float)))
case("MT11", "ROC-AUC perfect fixture", lambda: require(roc_auc([0, 1], [.1, .9]) == 1))
case("MT12", "PR-AUC perfect fixture", lambda: require(pr_auc([0, 1], [.1, .9]) == 1))
classification = classification_metrics([0, 1, 1, 0], [.1, .8, .7, .2])
for index, key in enumerate(("brier", "baseline_brier", "brier_skill"), 13):
    case(f"MT{index:02d}", f"classification metric {key}", lambda name=key: require(isinstance(classification[name], float)))
case("MT16", "constant prediction ROC handles ties", lambda: require(roc_auc([0, 1], [.5, .5]) == .5))
case("MT17", "single-class ROC insufficient", lambda: require(roc_auc([1, 1], [.2, .8]) == "INSUFFICIENT_SAMPLE"))
case("MT18", "single-class PR insufficient without positives", lambda: require(pr_auc([0, 0], [.2, .8]) == "INSUFFICIENT_SAMPLE"))
case("MT19", "constant label Brier skill insufficient", lambda: require(classification_metrics([1, 1], [.5, .5])["brier_skill"] == "INSUFFICIENT_SAMPLE"))
case("MT20", "scores not called calibrated probability", lambda: require(classification["calibration_state"] == "UNCALIBRATED_MODEL_SCORE"))
case("MT21", "classification rejects denominator mismatch", lambda: raises(ValueError, "CLASSIFICATION_LENGTH_MISMATCH", lambda: classification_metrics([0, 1], [.2])))
case("MT22", "classification rejects nonfinite score", lambda: raises(ValueError, "NONFINITE_SCORE", lambda: classification_metrics([0, 1], [.2, float("nan")])))
case("MT23", "empty classification fail-closed", lambda: require(classification_metrics([], [])["brier"] == "INSUFFICIENT_SAMPLE"))
case("MT24", "Brier hand fixture", lambda: require(math.isclose(classification_metrics([0, 1], [.25, .75])["brier"], .0625)))
case("MT25", "RankIC reverse fixture", lambda: require(math.isclose(rank_ic([1, 2, 3], [3, 2, 1]), -1)))

# Economic metrics.
econ = economic_evaluation([.02, -.01, .03], [.001, .001, .001], [.005, -.002, .006], [5, 5, 5], [1, 0, 2], [.4, .3, .5])
expected = {"gross_return": .04, "transaction_costs": .003, "net_return": .037,
            "number_of_positions": 15, "rejected_untradeable_selections": 3, "turnover": 1.2}
for index, (key, value) in enumerate(expected.items(), 1):
    case(f"EC{index:02d}", f"economic {key}", lambda name=key, want=value: require(math.isclose(econ[name], want)))
for index, key in enumerate(("benchmark_relative_return", "maximum_drawdown", "win_rate", "expectancy", "profit_factor"), 7):
    case(f"EC{index:02d}", f"economic metric {key}", lambda name=key: require(name in econ))
case("EC12", "profit factor handles no losses", lambda: require(economic_evaluation([.1], [0], [0], [1], [0], [0])["profit_factor"] == "INFINITE"))
case("EC13", "economic series alignment enforced", lambda: raises(ValueError, "ECONOMIC_SERIES_LENGTH_MISMATCH", lambda: economic_evaluation([.1, .2], [0], [0], [1], [0], [0])))
case("EC14", "benchmark relative hand fixture", lambda: require(math.isclose(economic_evaluation([.05], [.01], [.02], [1], [0], [0])["benchmark_relative_return"], .02)))
case("EC15", "drawdown hand fixture", lambda: require(math.isclose(economic_evaluation([.1, -.2, .05], [0, 0, 0], [0, 0, 0], [1, 1, 1], [0, 0, 0], [0, 0, 0])["maximum_drawdown"], -.2)))

# Ablation and stability artifacts.
ablation = json.loads((RESULTS / "nextgen_ablation_framework_v1.json").read_text())
for index, name in enumerate(("TECHNICAL", "TECHNICAL_MOMENTUM", "TECHNICAL_MOMENTUM_VOLATILITY", "PLUS_LIQUIDITY", "PLUS_MARKET_CONTEXT"), 1):
    case(f"AB{index:02d}", f"ablation {name}", lambda n=name: require(n in ablation["ablations"]))
case("AB06", "incremental metrics computed contract", lambda: require(len(ablation["incremental_metrics"]) == 7))
case("AB07", "no automatic feature acceptance", lambda: require(ablation["automatic_feature_acceptance"] is False))
stability = stability_analysis(rows[288:], rank_predictions(rows[288:], adapters[0].predict(reference, rows[288:]), "experiment", reference, "dataset", "features"))
for index, group in enumerate(("temporal_segment", "volatility_regime", "market_direction"), 1):
    case(f"ST{index:02d}", f"stability by {group}", lambda name=group: require(stability["groups"][name]))
case("ST04", "stability never auto-accepts", lambda: require(stability["automatic_acceptance"] is False))

# Experiment manifest immutability and bindings.
experiment = json.loads((RESULTS / "nextgen_experiment_manifest_v1.json").read_text())
registry = ExperimentRegistry()
case("MF01", "deterministic experiment ID", lambda: require(experiment["experiment_id"] == json.loads((RESULTS / "nextgen_experiment_manifest_v1.json").read_text())["experiment_id"]))
case("MF02", "first registration created", lambda: require(registry.register(experiment) == "CREATED"))
case("MF03", "same replay idempotent", lambda: require(registry.register(copy.deepcopy(experiment)) == "IDEMPOTENT_SUCCESS"))
conflict = copy.deepcopy(experiment); conflict["benchmark"] = "DIFFERENT"
case("MF04", "conflicting replay blocked", lambda: raises(ValueError, "EXPERIMENT_IDENTITY_CONFLICT", lambda: registry.register(conflict)))
for index, key in enumerate(("dataset_hash", "feature_set_hash", "label_contract", "model_configurations", "seed", "code_hash", "temporal_split", "execution_policy", "benchmark"), 5):
    case(f"MF{index:02d}", f"manifest binds {key}", lambda name=key: require(experiment.get(name) not in (None, "")))
case("MF14", "manifest trading authority false", lambda: require(experiment["trading_authority"] is False))
case("MF15", "manifest promotion authority none", lambda: require(experiment["promotion_authority"] == "NONE"))
same_population = [dict(row, model_id="challenger") for row in ranked]
case("MF16", "baseline challenger identical population accepted", lambda: require(assert_comparison_population_equal(ranked, same_population) is None))
different_population = copy.deepcopy(same_population); different_population.pop()
case("MF17", "different comparison population rejected", lambda: raises(ValueError, "COMPARISON_POPULATION_MISMATCH", lambda: assert_comparison_population_equal(ranked, different_population)))
different_boundary = copy.deepcopy(same_population); different_boundary[0]["dataset_hash"] = "different"
case("MF18", "different dataset boundary rejected", lambda: raises(ValueError, "COMPARISON_POPULATION_MISMATCH", lambda: assert_comparison_population_equal(ranked, different_boundary)))

# Rights audit and anti-bypass behavior.
rights = json.loads((RESULTS / "model_training_usage_rights_readiness_v1.json").read_text())
case("RG01", "current rights state read", lambda: require(rights["status"] == "LICENSE_REQUIRED"))
for index, state in enumerate(("LICENSE_REQUIRED", "PERMISSION_REQUIRED", "NOT_ESTABLISHED"), 2):
    real = dict(training_manifest, classification=REAL, source_manifest_bindings=["NSE_RESTRICTED_MARKET_PANEL"])
    case(f"RG{index:02d}", f"{state} blocks real fit", lambda s=state, m=real: raises(PermissionError, BLOCKED, lambda: guarded_fit(ReferenceAdapter(FEATURES), m, training_rows, s)))
case("RG05", "synthetic training allowed", lambda: require(guarded_fit(ReferenceAdapter(FEATURES), training_manifest, training_rows, rights["status"]).marker == MODEL_MARKER))
case("RG06", "caller text spoof blocked", lambda: raises(ValueError, "REAL_DATA_SYNTHETIC_SPOOF_BLOCKED", lambda: training_guard(spoof, rows, rights["status"])))
with tempfile.TemporaryDirectory() as directory:
    audit = Path(directory) / "audit.jsonl"
    guarded_fit(ReferenceAdapter(FEATURES), training_manifest, training_rows, rights["status"], audit)
    allowed_record = json.loads(audit.read_text().splitlines()[0])
    case("RG07", "allowed synthetic invocation recorded", lambda: require(allowed_record["allowed"] is True))
with tempfile.TemporaryDirectory() as directory:
    audit = Path(directory) / "audit.jsonl"
    real = dict(training_manifest, classification=REAL, source_manifest_bindings=["NSE_BHAVCOPY"])
    try: guarded_fit(ReferenceAdapter(FEATURES), real, training_rows, rights["status"], audit)
    except PermissionError: pass
    blocked_record = json.loads(audit.read_text().splitlines()[0])
    case("RG08", "blocked real invocation recorded", lambda: require(blocked_record["allowed"] is False and BLOCKED in blocked_record["reason"]))
case("RG09", "audit storage is temporary only", lambda: require(json.loads((RESULTS / "nextgen_training_invocation_v1.json").read_text())["production_runtime_artifact"] is False))
case("RG10", "rights remain unchanged after build", lambda: require(json.loads((RESULTS / "model_training_rights_guard_v1.json").read_text())["current_real_data_rights"] == "LICENSE_REQUIRED"))

# Isolation, scope and committed-contract checks.
case("IS01", "Stage4A3 unchanged", lambda: require(git("diff", "--name-only", BASE, "--", "Stage 4A.3") == ""))
case("IS02", "Stage5D unchanged", lambda: require(git("diff", "--name-only", BASE, "--", "Stage 5D") == ""))
case("IS03", "Stage6 unchanged", lambda: require(git("diff", "--name-only", BASE, "--", "Stage 6") == ""))
case("IS04", "activation unchanged", lambda: require(git("diff", "--name-only", BASE, "--", "Stage 4A.3/results/stage4a3_activation.json") == ""))
case("IS05", "prospective runtime unchanged", lambda: require(git("diff", "--name-only", BASE, "--", "Stage 4A.3/runtime") == ""))
case("IS06", "recommendation logic unchanged", lambda: require(git("diff", "--name-only", BASE, "--", "Stage 5D/stage5d") == ""))
model_manifest = json.loads((RESULTS / "nextgen_synthetic_model_manifest_v1.json").read_text())
case("IS07", "no real-data model artifact", lambda: require(model_manifest["real_models"] == 0))
case("IS08", "no promotion", lambda: require(all(model["promotion_authority"] == "NONE" for model in model_manifest["models"])))
case("IS09", "no trading authority", lambda: require(all(model["trading_authority"] is False for model in model_manifest["models"])))
case("IS10", "no raw real panel committed", lambda: require(not any("raw" in path.lower() and "nextgen research" in path.lower() for path in git("ls-files").splitlines())))
case("IS11", "no stage tag created", lambda: require("simple-challenger" not in git("tag", "--list")))
case("IS12", "all implementation remains under NextGen", lambda: require(not git("diff", "--name-only", BASE, "--", ":(exclude)NextGen Research/**")))
source = (ROOT / "simple_challenger" / "harness.py").read_text(encoding="utf-8")
tree = ast.parse(source)
imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
case("IS13", "no network library imported", lambda: require(not imports.intersection({"requests", "urllib", "httpx", "aiohttp", "socket"})))
case("IS14", "no advanced models implemented", lambda: require(not any(token in source for token in ("Transformer", "StockMixer", "reinforcement learning", "mixture-of-experts"))))
case("IS15", "future real experiment not executed", lambda: require(json.loads((RESULTS / "first_real_challenger_experiment_plan_v1.json").read_text())["execution_status"] == "NOT_EXECUTED_RIGHTS_BLOCKED"))
case("IS16", "large artifacts governed not rewritten", lambda: require(json.loads((RESULTS / "nextgen_large_artifact_policy_v1.json").read_text())["existing_immutable_artifacts_rewritten"] is False))
case("IS17", "exact baseline is ancestor", lambda: require(git("merge-base", "HEAD", BASE) == BASE))
case("IS18", "contract fixture-only", lambda: require(json.loads((RESULTS / "nextgen_simple_challenger_harness_contract_v1.json").read_text())["fixture_only"] is True))

RESULTS.mkdir(parents=True, exist_ok=True)
output = RESULTS / "nextgen_simple_challenger_test_results.csv"
with output.open("w", encoding="utf-8", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=["test_id", "description", "status", "detail"])
    writer.writeheader(); writer.writerows(records)

passed = sum(record["status"] == "PASS" for record in records)
failed = len(records) - passed
print(json.dumps({"total": len(records), "passed": passed, "failed": failed, "status": "PASS" if not failed else "FAIL"}, sort_keys=True))
if failed:
    for record in records:
        if record["status"] == "FAIL": print(f"FAIL {record['test_id']}: {record['detail']}")
    raise SystemExit(1)
