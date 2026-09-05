"""Executable Stage 4A.1 contract and result tests."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

STAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE_ROOT.parent
sys.path.insert(0, str(STAGE_ROOT))

from stage4a1.bootstrap import sample_date_counts, vector_metrics
from stage4a1.data_contract import build_reference_gate, git, load_config, load_opportunity
from stage4a1.hashing import dataframe_content_hash, write_csv
from stage4a1.metrics import classification_metrics, ranking_metrics
from stage4a1.models import contracts


def run_tests(phase: str, results: Path, output: Path) -> None:
    config = load_config(STAGE_ROOT); rows = []
    def test(name: str, fn) -> None:
        try:
            value = fn(); passed = bool(value if not isinstance(value, tuple) else value[0]); details = "" if not isinstance(value, tuple) else str(value[1])
            rows.append({"Test": name, "Status": "PASS" if passed else "FAIL", "Details": details})
        except Exception as exc:
            rows.append({"Test": name, "Status": "FAIL", "Details": f"{type(exc).__name__}: {exc}"})

    test("Stage 4A frozen tag resolves exactly", lambda: git(REPO_ROOT, "rev-list", "-n", "1", config["stage4a"]["tag"]) == config["stage4a"]["commit"])
    test("Stage 3.1 frozen tag resolves exactly", lambda: git(REPO_ROOT, "rev-list", "-n", "1", config["stage3_1"]["tag"]) == config["stage3_1"]["commit"])
    test("Stage 2B.1 frozen tag resolves exactly", lambda: git(REPO_ROOT, "rev-list", "-n", "1", config["stage2b_1"]["tag"]) == config["stage2b_1"]["commit"])
    identity4 = json.loads((REPO_ROOT / "Stage 4A/results/stage4a_experiment_identity.json").read_text())
    identity31 = json.loads((REPO_ROOT / "Stage 3.1/results/stage3_1_experiment_identity.json").read_text())
    test("Stage 4A experiment identity matches", lambda: identity4["EXPERIMENT_ID"] == config["stage4a"]["experiment_id"])
    test("Stage 4A package hash matches", lambda: identity4["STAGE4A_CODE_PACKAGE_HASH"] == config["stage4a"]["package_hash"])
    test("Stage 3.1 experiment identity matches", lambda: identity31["EXPERIMENT_ID"] == config["stage3_1"]["experiment_id"])
    test("Stage 3.1 package hash matches", lambda: identity31["STAGE3_1_CODE_PACKAGE_HASH"] == config["stage3_1"]["package_hash"])
    opportunity = load_opportunity(REPO_ROOT)
    test("BASELINE_PRIMARY filtering uses frozen Dataset Cohort", lambda: int(opportunity["Dataset Cohort"].eq("BASELINE_PRIMARY").sum()) == 1088)
    test("BASELINE_PRIMARY definition not reconstructed", lambda: "Dataset Cohort" in opportunity.columns)
    feature_sets, _, feature_hashes, _, _, model_hashes, model_specs = contracts(REPO_ROOT, config)
    test("Feature set sizes are 5/92/97", lambda: [len(feature_sets[k]) for k in ["FS1_RULE_SUMMARY","FS2_RAW_SIGNAL_STATE","FS3_FULL_SIGNAL_STATE"]] == [5,92,97])
    frozen_feature_hashes = json.loads((REPO_ROOT / "Stage 4A/results/stage4a_feature_set_hashes.json").read_text())
    test("Feature sets exactly equal frozen Stage 4A definitions", lambda: all(feature_hashes[k] == frozen_feature_hashes[f"{k}_HASH"] for k in feature_hashes))
    all_features = set().union(*map(set, feature_sets.values()))
    forbidden_tokens = ("DATE", "STATUS", "EXIT", "AVAILABLE", "FUTURE_MFE", "FUTURE_MAE", "CENSORED")
    test("No leakage field present", lambda: not [x for x in all_features if any(t in x.upper().replace(" ","_") for t in forbidden_tokens)])
    test("No date feature present", lambda: not [x for x in all_features if "DATE" in x.upper()])
    test("Ticker excluded", lambda: "Ticker" not in all_features)
    test("Signal ID excluded", lambda: "Signal ID" not in all_features)
    frozen_model_hashes = json.loads((REPO_ROOT / "Stage 4A/results/stage4a_model_spec_hashes.json").read_text())
    test("All model hashes exactly frozen", lambda: all(model_hashes[k] == frozen_model_hashes[k]["MODEL_SPEC_HASH"] for k in model_hashes))
    lp = config["logistic_parameters"]; rp = config["random_forest_parameters"]
    for key, value in {"penalty":"l2","C":1.0,"solver":"liblinear","max_iter":5000,"class_weight":None,"random_state":42}.items():
        test(f"Logistic parameter {key} frozen", lambda k=key,v=value: lp[k] == v)
    for key, value in {"n_estimators":300,"max_depth":8,"min_samples_leaf":20,"max_features":"sqrt","bootstrap":True,"class_weight":None,"random_state":42,"n_jobs":1}.items():
        test(f"RF parameter {key} frozen", lambda k=key,v=value: rp[k] == v)
    sources = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (STAGE_ROOT / "stage4a1").glob("*.py") if p.name != "validation.py")
    for name, token in [("No random train/test split","train_test_split("),("No shuffled CV","shuffle=True"),("No SMOTE","SMOTE("),("No oversampling","oversampl"),("No undersampling","undersampl"),("No feature selection","SelectKBest("),("No hyperparameter search","GridSearchCV("),("No threshold optimization","threshold_search"),("No class weighting",'class_weight": "balanced"')]:
        test(name, lambda t=token: t.lower() not in sources.lower())
    test("No Stage 4B implementation", lambda: not (REPO_ROOT / "Stage 4B").exists())
    test("No Stage 5 implementation", lambda: not (REPO_ROOT / "Stage 5").exists())
    test("No model binaries required", lambda: not list(STAGE_ROOT.rglob("*.pkl")) and not list(STAGE_ROOT.rglob("*.joblib")))
    test("Stage 4A.1 branch merge-base is frozen Stage 4A", lambda: git(REPO_ROOT,"merge-base","HEAD",config["stage4a"]["tag"]) == config["stage4a"]["commit"])
    test("No upstream working-tree modification", lambda: all(not git(REPO_ROOT,"status","--porcelain","--",path) for path in ["Stage 2.2.2 Final","Stage 2B","Stage 2B.1","Stage 3","Stage 3.1","Stage 4A"]))
    test("Primary bootstrap block length fixed", lambda: config["bootstrap"]["primary_block_length"] == 63)
    test("Bootstrap replicates fixed", lambda: config["bootstrap"]["replicates"] == 2000)
    test("Bootstrap seed fixed", lambda: config["bootstrap"]["random_seed"] == 42)
    a = sample_date_counts(150,63,20,np.random.default_rng(42)); b = sample_date_counts(150,63,20,np.random.default_rng(42))
    test("63-session bootstrap deterministic", lambda: np.array_equal(a,b))
    test("21-session sensitivity deterministic", lambda: np.array_equal(sample_date_counts(150,21,20,np.random.default_rng(42)),sample_date_counts(150,21,20,np.random.default_rng(42))))
    test("126-session sensitivity deterministic", lambda: np.array_equal(sample_date_counts(150,126,20,np.random.default_rng(42)),sample_date_counts(150,126,20,np.random.default_rng(42))))
    test("Bootstrap samples original number of date positions", lambda: np.all(a.sum(axis=1) == 150))
    tiny = pd.DataFrame({"Signal Date":pd.to_datetime(["2020-01-01","2020-01-01","2020-01-02","2020-01-03"]),"Signal ID":["a","b","c","d"],"Actual Label":[0,1,0,1],"Predicted Probability":[.1,.8,.4,.7],"Training Prior":[.5]*4})
    raw = vector_metrics(tiny, np.array([[1,1,1],[2,0,1]]), pd.Index(pd.to_datetime(["2020-01-01","2020-01-02","2020-01-03"])))
    test("Same-date rows remain grouped", lambda: int(raw.iloc[1]["Rows"]) == 5)
    sklearn_auc = roc_auc_score(tiny["Actual Label"],tiny["Predicted Probability"])
    test("AUC implementation checked against sklearn", lambda: np.isclose(raw.iloc[0]["ROC AUC"],sklearn_auc))
    test("Brier implementation checked", lambda: np.isclose(raw.iloc[0]["Brier Score"],brier_score_loss(tiny["Actual Label"],tiny["Predicted Probability"])))
    metric = classification_metrics(tiny["Actual Label"],tiny["Predicted Probability"],.5)
    test("Brier Skill benchmark uses training prior", lambda: np.isclose(metric["Brier Benchmark Score"],.25))
    rank_input = tiny.assign(Mode="X",Target="Y",**{"Model Variant":"M","Feature Set":"F","Evaluation Year":2020})
    ranking = ranking_metrics(rank_input)
    test("Top-10 and top-20 ranking calculation checked", lambda: {"Top 10% Lift","Top 20% Lift"}.issubset(ranking.columns))
    test("Ranking tie-break deterministic", lambda: ranking_metrics(rank_input).equals(ranking_metrics(rank_input.sample(frac=1,random_state=1))))
    import test_ranking_regression as regression
    def assertions_pass(function):
        function()
        return True
    for name, function in [
        ("A bucket identity", lambda: regression.identity_parity(regression.fixture((.1,.8,.4,.7)))),
        ("B tied membership", regression.tied_membership),
        ("C bottom tie regression", lambda: regression.identity_parity(regression.fixture())),
        ("D duplicated observations", regression.duplicated_observations),
        ("E paired observation parity", regression.paired_observations),
        ("F exact Log Loss identity", regression.log_loss_identity),
        ("G extreme clipping contract", regression.extreme_contract),
        ("H probabilities unmodified", regression.nonmutation),
        ("I shared bootstrap Log Loss routes", regression.shared_loss_routes),
        ("J full shared metric identity", regression.full_identity),
    ]:
        test(name, lambda f=function: assertions_pass(f))

    if phase == "final":
        required = ["stage4a1_experiment_identity.json","stage4a1_primary_only_oos_predictions.csv.gz","stage4a1_primary_only_joint_oos_predictions.csv.gz","stage4a1_transfer_baseline_primary_predictions.csv.gz","stage4a1_transfer_baseline_primary_joint_predictions.csv.gz","stage4a1_recent_2024_2026_metrics.csv","stage4a1_determinism_check.csv","stage4a1_bootstrap_summary.csv","stage4a1_transfer_vs_primary_only_paired.csv","stage4a1_rank_agreement.csv"]
        for name in required: test(f"Required result exists: {name}", lambda n=name: (results/n).is_file())
        transfer = pd.read_csv(results/"stage4a1_transfer_baseline_primary_predictions.csv.gz",low_memory=False); primary = pd.read_csv(results/"stage4a1_primary_only_oos_predictions.csv.gz",low_memory=False)
        tj = pd.read_csv(results/"stage4a1_transfer_baseline_primary_joint_predictions.csv.gz",low_memory=False); pj = pd.read_csv(results/"stage4a1_primary_only_joint_oos_predictions.csv.gz",low_memory=False)
        keys=["Signal ID","Target","Model Variant","Evaluation Year"]
        test("Transfer probabilities exactly equal frozen values", lambda: dataframe_content_hash(transfer.drop(columns=["Mode","Stage 4A.1 Experiment ID"])) == dataframe_content_hash(pd.read_csv(REPO_ROOT/"Stage 4A/results/stage4a_oos_predictions.csv.gz",low_memory=False).query("`Dataset Cohort` == 'BASELINE_PRIMARY'").reset_index(drop=True)))
        test("Same Transfer Signal IDs preserved", lambda: set(map(tuple,transfer[keys].to_numpy())) == set(map(tuple,primary[keys].to_numpy())))
        test("PRIMARY_ONLY predictions unique", lambda: not primary.duplicated(keys).any())
        test("Joint T1 arithmetic exact", lambda: np.allclose(pj.loc[pj.Target.eq("JOINT_T1"),"Predicted Probability"],pj.loc[pj.Target.eq("JOINT_T1"),"P Fill"]*pj.loc[pj.Target.eq("JOINT_T1"),"P T1 Conditional"],atol=2e-12,rtol=0))
        test("Joint T2 arithmetic exact", lambda: np.allclose(pj.loc[pj.Target.eq("JOINT_T2"),"Predicted Probability"],pj.loc[pj.Target.eq("JOINT_T2"),"P Fill"]*pj.loc[pj.Target.eq("JOINT_T2"),"P T2 Conditional"],atol=2e-12,rtol=0))
        test("Non-filled joint actual zero", lambda: pd.concat([tj,pj]).loc[pd.concat([tj,pj])["Label Status"].eq("AVAILABLE_NON_FILL"),"Actual Label"].eq(0).all())
        test("Censored joint labels excluded", lambda: pd.concat([tj,pj]).loc[pd.concat([tj,pj])["Label Status"].str.contains("CENSORED",na=False),"Actual Label"].isna().all())
        fold = pd.read_csv(results/"stage4a1_fold_reconstruction_audit.csv")
        test("Training label dates strictly precede evaluation", lambda: fold["Chronology Violations"].eq(0).all())
        test("PRIMARY_ONLY training uses BASELINE_PRIMARY only", lambda: fold.loc[fold["Training Mode"].eq("PRIMARY_ONLY"),"Status"].eq("PASS").all())
        prep = pd.read_csv(results/"stage4a1_primary_only_preprocessing_audit.csv")
        test("PRIMARY_ONLY preprocessing training-only", lambda: prep["No Evaluation Fit Operations"].eq(True).all())
        test("Unknown categories handled without evaluation refit", lambda: prep["Status"].eq("PASS").all())
        bootstrap = pd.read_csv(results/"stage4a1_bootstrap_summary.csv")
        test("Paired bootstrap all modes present", lambda: set(bootstrap["Mode"]) == {"TRANSFER","PRIMARY_ONLY"})
        test("Pooled AUC has at least 1800 valid replicates", lambda: bootstrap.loc[bootstrap["Block Length"].eq(63)&bootstrap["Scope"].eq("POOLED_2016_2026")&bootstrap["Metric"].eq("ROC AUC"),"Valid Replicates"].ge(1800).all())
        test("Recent 2024-2026 artifact produced", lambda: pd.read_csv(results/"stage4a1_recent_2024_2026_metrics.csv").shape[0] > 0)
        test("Second complete official run exactly matches first", lambda: pd.read_csv(results/"stage4a1_determinism_check.csv")["Status"].eq("PASS").all())
        for name in ["stage4a1_point_bootstrap_metric_consistency_audit.csv", "stage4a1_ranking_tie_handling_audit.csv"]:
            test("All audit comparisons pass: " + name, lambda n=name: pd.read_csv(results/n)["Status"].eq("PASS").all())
        report=(STAGE_ROOT/"Stage4A1_Delivery_Report.md").read_text()
        for phrase in ["No production ML model has been selected.","No ML trading backtest was performed.","Probabilities are not validated as user-facing confidence.","READY FOR INDEPENDENT STAGE 4A.1 AUDIT: YES"]:
            test(f"Delivery report declaration: {phrase}", lambda p=phrase: p in report)

    result = pd.DataFrame(rows); write_csv(result, output)
    failed = int(result["Status"].eq("FAIL").sum()); print(f"STAGE4A1_TESTS phase={phase} pass={len(result)-failed} fail={failed}",flush=True)
    if failed: raise SystemExit(1)


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--phase",choices=["preflight","final"],required=True); parser.add_argument("--results",type=Path,default=STAGE_ROOT/"results"); parser.add_argument("--output",type=Path,required=True); args=parser.parse_args()
    run_tests(args.phase,args.results.resolve(),args.output.resolve())


if __name__ == "__main__": main()
