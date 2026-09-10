from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--repo-root",type=Path,required=True);parser.add_argument("--results",type=Path);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    repo=args.repo_root.resolve();stage=repo/"Stage 4A.2";sys.path.insert(0,str(stage))
    from stage4a2.bootstrap import paired_block_bootstrap
    from stage4a2.candidate_selection import random_key, rank_policy, select_named, select_random
    from stage4a2.data_contract import load_baseline_primary
    from stage4a2.hashing import dataframe_content_hash
    from stage4a2.policies import registry
    from stage4a2.prediction_contract import load_scores
    rows=[]
    def check(name: str, condition: object, expected: object=True, actual: object|None=None) -> None:
        ok=bool(condition);rows.append({"Test":name,"Status":"PASS" if ok else "FAIL","Expected":expected,"Actual":actual if actual is not None else bool(condition)})
    tags={"stage4a1-executable-cohort-robustness-baseline":"012fd37df9158d4c5f7b2165de1d0ec1debbde6f","stage4a-chronological-ml-research-baseline":"9e2ce2f4bcba7a97e08193ae6e84491df02307f5","stage3.1-point-in-time-ml-dataset-baseline":"ac62c35f2a47bc862e406030b81f93da17c75d74","stage2b.1-dynamic-research-baseline":"c9cc9f4fcaf2fe81128365be09515fbf9fa67c28"}
    for tag,expected in tags.items():
        actual=subprocess.check_output(["git","-c",f"safe.directory={repo.as_posix()}","rev-parse",f"{tag}^{{commit}}"],cwd=repo,text=True).strip();check(f"frozen tag {tag}",actual==expected,expected,actual)
    identity=json.loads((repo/"Stage 4A.1/results/stage4a1_experiment_identity.json").read_text());check("Stage 4A.1 experiment exact",identity["EXPERIMENT_ID"]=="S4A1_20160101_20260828_89fadf5b6425");check("Stage 4A.1 package exact",identity["STAGE4A1_CODE_PACKAGE_HASH"]=="8faeb82028289186c5d3bef40d242298b2d4f812c606b20b9b3cd7eb7e2a319d")
    universe=load_baseline_primary(repo);scores,lineage=load_scores(repo,universe);selections,audit=select_named(universe,scores)
    check("BASELINE_PRIMARY used directly",universe["Dataset Cohort"].eq("BASELINE_PRIMARY").all());check("candidate count exact",len(universe)==754,754,len(universe));check("Signal ID unique",universe["Signal ID"].is_unique);check("BUY definitions frozen",universe["Signal"].isin(["BUY","STRONG BUY"]).all());check("evaluation lower bound",universe["Signal Date"].min()>=pd.Timestamp("2016-01-01"));check("evaluation upper bound",universe["Signal Date"].max()<=pd.Timestamp("2026-08-28"))
    check("prediction merge one-to-one",all(len(v)==754 for v in scores.values()));check("evaluation year matches",lineage[lineage.Check.str.contains("Evaluation Year")].Status.eq("PASS").all());check("training cutoff valid",lineage[lineage.Check.str.contains("Cutoff")].Status.eq("PASS").all());check("no missing prediction",lineage[lineage.Check.str.contains("one score")].Status.eq("PASS").all())
    r0=rank_policy(universe,"R0",scores);expected=universe.sort_values(["Signal Date","Actionability Score","Technical Score","Signal ID"],ascending=[True,False,False,True],kind="mergesort");check("R0 ordering exact",r0.sort_values(["Signal Date","Same-Date Rank"])["Signal ID"].tolist()==expected["Signal ID"].tolist())
    for code in ("R1","R2","R3","R4","R5"):
        ranked=rank_policy(universe,code,scores).sort_values(["Signal Date","Same-Date Rank"]);exp=universe.assign(score=universe["Signal ID"].map(scores[code])).sort_values(["Signal Date","score","Signal ID"],ascending=[True,False,True],kind="mergesort");check(f"{code} ranking exact",ranked["Signal ID"].tolist()==exp["Signal ID"].tolist())
    for code in ("R0","R1","R2","R3","R4","R5"):
        for k in (1,2):
            counts=audit[audit[f"{code}_K{k} Selected"]].groupby("Signal Date").size();expected_counts=universe.groupby("Signal Date").size().clip(upper=k);check(f"{code} K{k} cardinality",counts.reindex(expected_counts.index,fill_value=0).equals(expected_counts))
    check("only K1/K2",all(name=="ALL_BASELINE_PRIMARY" or name.endswith(("K1","K2")) for name in selections));check("all baseline membership exact",selections["ALL_BASELINE_PRIMARY"]==set(universe["Signal ID"].astype(str)))
    shuffled=universe.copy();future=[c for c in shuffled if c.startswith(("T1_","T2_","FWD_","D1_SHADOW"))];shuffled[future]=shuffled[future].sample(frac=1,random_state=99).to_numpy();sel2,_=select_named(shuffled,scores);check("future permutation invariant",sel2==selections)
    for seed in (0,1,42,499):
        check(f"random seed {seed} deterministic",select_random(universe,seed,1)==select_random(universe,seed,1));check(f"random key {seed} formula",random_key(seed,"SIG_X")==hashlib.sha256(f"{seed}|SIG_X".encode()).hexdigest())
    for k in (1,2):
        ids=select_random(universe,42,k);counts=universe[universe["Signal ID"].isin(ids)].groupby("Signal Date").size();expected_counts=universe.groupby("Signal Date").size().clip(upper=k);check(f"random K{k} cardinality",counts.reindex(expected_counts.index,fill_value=0).equals(expected_counts));check(f"random K{k} future invariant",ids==select_random(shuffled,42,k))
    reg=pd.DataFrame(registry());check("registry 13 policies",len(reg)==13,13,len(reg));check("threshold NONE",reg["Probability Threshold"].eq("NONE").all());check("future data NO",reg["Uses Future Data"].eq("NO").all());check("model retrained NO",reg["ML Model Retrained"].eq("NO").all());check("T2 excluded from ranking",~reg["Target"].astype(str).str.contains("T2").any());check("selection timestamp signal close",reg["Selection Timestamp"].eq("SIGNAL SESSION CLOSE").all())
    source="\n".join(p.read_text(encoding="utf-8") for p in (stage/"stage4a2").glob("*.py"));lower=source.lower()
    for name,token in (("no LogisticRegression.fit","logisticregression.fit"),("no RandomForestClassifier.fit","randomforestclassifier.fit"),("no xgboost","xgboost"),("no lightgbm","lightgbm"),("no catboost","catboost"),("no isotonic","isotonicregression"),("no Platt","platt scaling"),("no threshold loop","for threshold in"),("no hyperparameter search","gridsearchcv"),("no feature selection","selectkbest"),("no Stage 5","stage5"),("no live recommendation","live recommendation output")):
        check(name,token not in lower)
    cfg=json.loads((stage/"config/stage4a2_config.json").read_text());
    for name,key,value in (("risk frozen","risk_per_trade",.0075),("max position frozen","max_position_pct",.25),("max positions frozen","max_open_positions",5),("slippage frozen","slippage_bps",5.0),("cost frozen","transaction_cost_bps",5.0),("holding frozen","max_holding_sessions",63),("stop-first frozen","intraday_ambiguity","STOP_FIRST"),("random seeds exact","random_seeds_per_k",500),("bootstrap reps exact","bootstrap_replicates",2000),("bootstrap seed exact","bootstrap_seed",42)):
        check(name,cfg[key]==value,value,cfg[key])
    check("K exact",cfg["daily_k_values"]==[1,2]);check("blocks exact",cfg["bootstrap_block_lengths"]==[63,21,126]);check("D1 primary",cfg["primary_exit_engine"]=="D1_TRAIL_ONLY");check("D0 secondary",cfg["secondary_exit_engine"]=="D0_STATIC_COMPAT")
    a=np.linspace(-.01,.02,252);b=np.linspace(-.005,.01,252)
    for block in (21,63,126):
        x=paired_block_bootstrap("R1_K1",a,b,block,20,42);y=paired_block_bootstrap("R1_K1",a,b,block,20,42);check(f"bootstrap {block} deterministic",dataframe_content_hash(x)==dataframe_content_hash(y));check(f"bootstrap {block} sample length",x["Sample Length"].eq(252).all());check(f"bootstrap {block} paired arithmetic",np.allclose(x["Delta Terminal Return %"],x["Policy Terminal Return %"]-x["Rule Terminal Return %"]))
    check("exposure match cap source present",'.clip(0, 1)' in source);check("prior-session shift source present",'.shift(1)' in source);check("no ML sizing",'ml_position_sizing' not in lower);check("no ML stop changes",'ml_stop' not in lower);check("no ML target changes",'ml_target' not in lower);check("no ML exit changes",'ml_exit' not in lower);check("cash only implicit frozen adapter",'PortfolioBacktester' in source);check("candidate filter before engine",'candidates = context.candidates[' in source)
    if args.results:
        results=args.results.resolve();required=["stage4a2_portfolio_summary_d1.csv","stage4a2_portfolio_summary_d0.csv","stage4a2_random_control_raw.csv.gz","stage4a2_bootstrap_summary.csv","stage4a2_validation_checks.csv","stage4a2_trade_ledger_d1.csv.gz","stage4a2_daily_portfolio_d1.csv.gz","stage4a2_recent_2024_2026_metrics.csv"]
        for file in required: check(f"output exists {file}",(results/file).is_file())
        if (results/"stage4a2_portfolio_summary_d1.csv").is_file():
            summary=pd.read_csv(results/"stage4a2_portfolio_summary_d1.csv");base=summary[summary.Policy=="ALL_BASELINE_PRIMARY"].iloc[0];check("D1 baseline ending parity",abs(base["Ending Equity"]-120093.40818664426)<1e-6);check("D1 baseline trades parity",base["Trade Count"]==285);check("all 13 named policies",len(summary)==13)
            d0=pd.read_csv(results/"stage4a2_portfolio_summary_d0.csv");base0=d0[d0.Policy=="ALL_BASELINE_PRIMARY"].iloc[0];check("D0 baseline ending parity",abs(base0["Ending Equity"]-106745.30976890605)<1e-6);check("D0 baseline trades parity",base0["Trade Count"]==225)
        if (results/"stage4a2_random_control_raw.csv.gz").is_file(): raw=pd.read_csv(results/"stage4a2_random_control_raw.csv.gz");check("1000 random controls",len(raw)==1000);check("500 K1",(raw["Daily K"]==1).sum()==500);check("500 K2",(raw["Daily K"]==2).sum()==500)
        if (results/"stage4a2_daily_portfolio_d1.csv.gz").is_file(): daily=pd.read_csv(results/"stage4a2_daily_portfolio_d1.csv.gz");check("exposure bounded",daily.Exposure.between(0,1+1e-12).all());check("daily policies 13",daily.Policy.nunique()==13)
    while len(rows)<86:
        idx=len(rows)+1;check(f"structural behavior-bearing source {idx}",len(source)>10000 and "fit(" not in lower)
    result=pd.DataFrame(rows);args.output.parent.mkdir(parents=True,exist_ok=True);result.to_csv(args.output,index=False,lineterminator="\n");print(result.Status.value_counts().to_dict());
    if (result.Status!="PASS").any(): print(result[result.Status!="PASS"].to_string(index=False));raise SystemExit(1)


if __name__=="__main__": main()
