from __future__ import annotations

import argparse,gzip,json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score,brier_score_loss,log_loss,roc_auc_score

from .economic_methodology import enrich_trades,midrank_percentile,normalize_daily,paired_moving_block_bootstrap,portfolio_metrics
from .final_analysis_gate import gate_audit,is_unlocked
from .final_market_data import acquire_and_archive,verify_and_load_archive
from .immutable_ledger import record_breach
from .ledger_counts import derive_final_gate_counts,prediction_rows
from .model_scoring import verify_bundle
from .outcome_resolver import load_all_events,run_frozen_portfolio_results


FINAL_OUTPUTS=["stage4a3_final_gate_audit.csv","stage4a3_prospective_sample_summary.csv","stage4a3_predictive_metrics.csv","stage4a3_predictive_calibration.csv","stage4a3_policy_summary_d1.csv","stage4a3_policy_summary_d0.csv","stage4a3_yearly_or_period_metrics.csv","stage4a3_random_control_raw.csv.gz","stage4a3_random_control_summary.csv","stage4a3_named_policy_random_percentiles.csv","stage4a3_block_bootstrap_63.csv.gz","stage4a3_block_bootstrap_21.csv.gz","stage4a3_block_bootstrap_126.csv.gz","stage4a3_bootstrap_summary.csv","stage4a3_primary_confirmatory_result.json","Stage4A3_Final_Prospective_Report.md","stage4a3_trade_ledger_d1.csv.gz","stage4a3_daily_portfolio_d1.csv.gz","stage4a3_trade_ledger_d0.csv.gz","stage4a3_daily_portfolio_d0.csv.gz"]


def write_csv(frame:pd.DataFrame,path:Path)->None:path.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(path,index=False,lineterminator="\n",float_format="%.12g")
def write_gz(frame:pd.DataFrame,path:Path)->None:
    path.parent.mkdir(parents=True,exist_ok=True);payload=frame.to_csv(index=False,lineterminator="\n",float_format="%.12g").encode()
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as zipped:zipped.write(payload)
def write_json(value:Any,path:Path)->None:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8",newline="\n")


def economic_criteria(r3:dict[str,Any],r0:dict[str,Any],evidence:dict[str,Any])->pd.DataFrame:
    checks=[("total return",r3["total_return"]>r0["total_return"]),("CAGR",r3["cagr"]>r0["cagr"]),("expectancy R",r3["expectancy_r"]>r0["expectancy_r"]),("profit factor",r3["profit_factor"]>=r0["profit_factor"]),("bootstrap lower 2.5%",evidence["bootstrap_63_delta_terminal_return_lower_2_5"]>0),("random K1 percentile",evidence["random_k1_total_return_percentile"]>=95),("max drawdown tolerance",r3["max_drawdown"]>=r0["max_drawdown"]-2),("minimum completed trades",r3["completed_trades"]>=50),("ledger integrity",bool(evidence["ledger_integrity_pass"])),("no protocol drift",bool(evidence["no_protocol_drift"]))]
    return pd.DataFrame([{"Criterion":name,"Status":"PASS" if passed else "FAIL"} for name,passed in checks])


def require_unlocked(config:dict[str,Any],activation:dict[str,Any],counts:dict[str,Any],audit_root:Path)->pd.DataFrame:
    audit=gate_audit(config,activation,counts)
    if not is_unlocked(audit):
        record_breach(audit_root,{"UTC Time":pd.Timestamp.now(tz="UTC").isoformat(),"Breach Type":"PREMATURE_EVALUATION_ATTEMPT","Details":"PROSPECTIVE_EVALUATION_LOCKED","Blocked / Allowed":"BLOCKED","Affected Signal Date":"","Protocol Hash":counts.get("protocol_hash","")})
        raise RuntimeError("PROSPECTIVE_EVALUATION_LOCKED\n"+audit.to_csv(index=False))
    return audit


def _boolean(value:Any)->bool:return str(value).strip().lower() in {"true","1","yes"}


def feature_rows(stage_root:Path)->pd.DataFrame:
    index=stage_root/"prospective/audit/prospective_snapshot_index.csv"
    if not index.exists():return pd.DataFrame()
    parts=[]
    for day in pd.read_csv(index,dtype=str).get("Signal Date",[]):
        path=stage_root/"prospective/snapshots"/str(day)[:4]/str(day)/"feature_snapshot.csv.gz"
        if path.exists():parts.append(pd.read_csv(path,low_memory=False))
    return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()


def predictive_outputs(predictions:pd.DataFrame,features:pd.DataFrame,events:pd.DataFrame,model_dir:Path,synthetic:bool=False)->tuple[pd.DataFrame,pd.DataFrame]:
    verify_bundle(model_dir);t1_bundle=joblib.load(model_dir/"TRANSFER_T1_LOGIT_FULL.joblib")
    missing=set(t1_bundle["feature_names"])-set(features)
    if missing and not synthetic:raise RuntimeError("FROZEN_T1_COMPONENT_FEATURES_MISSING")
    # The legacy synthetic gate fixture predates full feature persistence.  Its
    # diagnostic scores are test-only and never feed selection or economics.
    if missing:t1_score=np.full(len(predictions),.5)
    else:
        transformed=t1_bundle["preprocessor"].transform(features[t1_bundle["feature_names"]]);t1_score=t1_bundle["estimator"].predict_proba(transformed)[:,1]
    score_table=predictions[["Signal ID","R5 Score","R3 Score"]].copy();score_table["TRANSFER T1 LOGIT_FULL Score"]=t1_score
    specs=[("ENTRY_FILLED","R5 Score"),("T1_BEFORE_STOP_63","TRANSFER T1 LOGIT_FULL Score"),("JOINT_T1","R3 Score")];rows=[];cal=[]
    for target,score in specs:
        event_target="T1_BEFORE_STOP_63" if target=="JOINT_T1" else target
        outcome=events.loc[(events["Outcome Type"]==event_target)&events["Policy"].fillna("").eq("")].copy();outcome["Observed"]=outcome["Outcome Value"].map(_boolean)
        merged=score_table[["Signal ID",score]].merge(outcome[["Signal ID","Observed"]],on="Signal ID");y=merged["Observed"].astype(int).to_numpy();p=merged[score].astype(float).to_numpy();valid=len(np.unique(y))==2
        rows.append({"Target":target,"Score":score,"Rows":len(y),"ROC AUC":roc_auc_score(y,p) if valid else np.nan,"Average Precision":average_precision_score(y,p) if len(y) else np.nan,"Brier":brier_score_loss(y,p) if len(y) else np.nan,"Brier Skill":1-brier_score_loss(y,p)/(np.mean(y)*(1-np.mean(y))) if valid else np.nan,"Log Loss":log_loss(y,np.clip(p,1e-15,1-1e-15),labels=[0,1]) if len(y) else np.nan})
        if len(merged):
            bins=pd.cut(merged[score],np.linspace(0,1,11),include_lowest=True)
            for band,g in merged.groupby(bins,observed=False):cal.append({"Target":target,"Score":score,"Bucket":str(band),"Rows":len(g),"Mean Score":g[score].mean(),"Observed Rate":g["Observed"].mean()})
    t2=events.loc[(events["Outcome Type"]=="T2_BEFORE_STOP_63")&events["Policy"].fillna("").eq("")]
    observed=t2["Outcome Value"].map(_boolean) if len(t2) else pd.Series(dtype=bool)
    rows.append({"Target":"T2_BEFORE_STOP_63","Score":"NOT AVAILABLE — NO T2 MODEL IN FROZEN PROSPECTIVE BUNDLE","Rows":len(t2),"Positive Count":int(observed.sum()),"Observed Prevalence":float(observed.mean()) if len(observed) else np.nan,"ROC AUC":np.nan,"Average Precision":np.nan,"Brier":np.nan,"Brier Skill":np.nan,"Log Loss":np.nan})
    return pd.DataFrame(rows),pd.DataFrame(cal)


def _test_replays(stage_root:Path)->tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    root=stage_root/"tests/frozen_portfolio_replay"
    if "tests" not in {part.lower() for part in stage_root.parts} or not root.exists():raise RuntimeError("TEST_REPLAY_PROHIBITED_OUTSIDE_SYNTHETIC_FIXTURE")
    return tuple(pd.read_csv(root/name,compression="gzip",parse_dates=["Date"] if "daily" in name else None) for name in ("d1_daily.csv.gz","d1_trades.csv.gz","d0_daily.csv.gz","d0_trades.csv.gz"))


def _execute(repo:Path,stage_root:Path,as_of_date:str,output_root:Path,predictions:pd.DataFrame,features:pd.DataFrame,synthetic:bool,activation_local_date:str)->tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    if synthetic:return _test_replays(stage_root)
    frames,_=acquire_and_archive(repo,stage_root,as_of_date,output_root,pd.Timestamp.now(tz="UTC").isoformat())
    sessions=pd.DatetimeIndex(pd.to_datetime(frames["^NSEI"].index)).normalize();eligible=sessions[(sessions>pd.Timestamp(activation_local_date))&(sessions<=pd.Timestamp(as_of_date))]
    if eligible.empty:raise RuntimeError("NO_VALID_FINAL_PORTFOLIO_SESSIONS")
    results=run_frozen_portfolio_results(repo,predictions,features,frames,as_of_date,include_random_controls=True,include_d0=True,evaluation_start=eligible.min().date().isoformat())
    d1d=[];d1t=[];d0d=[];d0t=[]
    for policy,engines in results.items():
        membership=engines["membership"]
        d1d.append(normalize_daily(engines["D1"],policy,"D1_TRAIL_ONLY"));d1t.append(enrich_trades(engines["D1"],policy,"D1_TRAIL_ONLY",membership))
        if "D0" in engines:d0d.append(normalize_daily(engines["D0"],policy,"D0_STATIC_COMPAT"));d0t.append(enrich_trades(engines["D0"],policy,"D0_STATIC_COMPAT",membership))
    return pd.concat(d1d,ignore_index=True),pd.concat(d1t,ignore_index=True),pd.concat(d0d,ignore_index=True),pd.concat(d0t,ignore_index=True)


def evaluate(repo:Path,stage_root:Path,as_of_date:str,output_root:Path)->dict[str,Any]:
    config=json.loads((stage_root/"config/stage4a3_protocol.json").read_text());activation=json.loads((stage_root/"prospective/audit/activation_record.json").read_text());synthetic="tests" in {p.lower() for p in stage_root.parts}
    counts=derive_final_gate_counts(repo,stage_root,as_of_date,synthetic_integrity=synthetic);audit=require_unlocked(config,activation,counts,stage_root/"prospective/audit")
    predictions=prediction_rows(stage_root);features=feature_rows(stage_root);events=load_all_events(stage_root/"prospective/outcomes");terminal=events.loc[events["Is Terminal"].map(_boolean)]
    d1_daily,d1_trades,d0_daily,d0_trades=_execute(repo,stage_root,as_of_date,output_root,predictions,features,synthetic,activation["Activation Local Date"])
    d1_summary=pd.DataFrame([portfolio_metrics(policy,daily,d1_trades.loc[d1_trades["Policy"].eq(policy)]) for policy,daily in d1_daily.groupby("Policy")]);d0_summary=pd.DataFrame([portfolio_metrics(policy,daily,d0_trades.loc[d0_trades["Policy"].eq(policy)]) for policy,daily in d0_daily.groupby("Policy")])
    predictive,calibration=predictive_outputs(predictions,features,terminal,repo/"Stage 4A.3/models/frozen_2026",synthetic)
    random=d1_summary.loc[d1_summary["Policy"].str.startswith("RANDOM_K1_SEED_")].copy()
    if set(random["Policy"])!={f"RANDOM_K1_SEED_{seed:03d}" for seed in range(500)}:raise RuntimeError("EXACT_RANDOM_K1_CONTROL_SET_INCOMPLETE")
    named=d1_summary.loc[~d1_summary["Policy"].str.startswith("RANDOM_K1_SEED_")].copy();lookup=named.set_index("Policy");r0row=lookup.loc["R0_K1"];r3row=lookup.loc["R3_K1"]
    boot={block:paired_moving_block_bootstrap(d1_daily.loc[d1_daily["Policy"].eq("R3_K1")],d1_daily.loc[d1_daily["Policy"].eq("R0_K1")],block,2000,42) for block in (63,21,126)}
    boot_summary=pd.DataFrame([{"Block Length":block,"Replicates":len(frame),"Seed":42,"Delta Terminal Return Lower 2.5%":frame["Delta Terminal Return %"].quantile(.025),"Median":frame["Delta Terminal Return %"].median(),"Upper 97.5%":frame["Delta Terminal Return %"].quantile(.975),"P(Delta > 0) %":frame["Delta Terminal Return %"].gt(0).mean()*100} for block,frame in boot.items()])
    percentile=midrank_percentile(float(r3row["Total Return %"]),random["Total Return %"])
    r0={"total_return":r0row["Total Return %"],"cagr":r0row["CAGR %"],"expectancy_r":r0row["Expectancy R"],"profit_factor":r0row["Profit Factor"],"max_drawdown":r0row["Maximum Drawdown %"],"completed_trades":r0row["Trade Count"]};r3={"total_return":r3row["Total Return %"],"cagr":r3row["CAGR %"],"expectancy_r":r3row["Expectancy R"],"profit_factor":r3row["Profit Factor"],"max_drawdown":r3row["Maximum Drawdown %"],"completed_trades":r3row["Trade Count"]}
    evidence={"bootstrap_63_delta_terminal_return_lower_2_5":float(boot_summary.set_index("Block Length").loc[63,"Delta Terminal Return Lower 2.5%"]),"random_k1_total_return_percentile":percentile,"ledger_integrity_pass":counts["ledger_chain_pass"],"no_protocol_drift":counts["protocol_integrity_pass"]};criteria=economic_criteria(r3,r0,evidence);confirmed=criteria["Status"].eq("PASS").all()
    years=[]
    for (policy,year),group in d1_daily.groupby(["Policy",d1_daily["Date"].dt.year]):
        years.append({"Policy":policy,"Period":year,"Starting Equity":float(group.iloc[0]["Equity"]/(1+group.iloc[0]["Daily Return"])),"Ending Equity":float(group.iloc[-1]["Equity"]),"Sessions":len(group)})
    random_summary=random[["Total Return %","Expectancy R"]].agg(["min","median","max"]).reset_index(names="Statistic");percentiles=pd.DataFrame([{"Policy":"R3_K1","Metric":"Total Return %","Random K1 Total Return Percentile":percentile,"Tie Rule":"MID_RANK"}]);result={"Primary Policy":"R3_K1","Comparator":"R0_K1","All Ten Criteria Pass":bool(confirmed),"Conclusion":"PROSPECTIVELY CONFIRMED POSITIVE ECONOMIC UTILITY" if confirmed else "NOT PROSPECTIVELY CONFIRMED","Stage 5":"MAY BE CONSIDERED" if confirmed else "REMAINS BLOCKED","Secondary Substitution Allowed":False,"Criteria":criteria.to_dict("records")}
    write_csv(audit,output_root/FINAL_OUTPUTS[0]);write_csv(pd.DataFrame([counts]),output_root/FINAL_OUTPUTS[1]);write_csv(predictive,output_root/FINAL_OUTPUTS[2]);write_csv(calibration,output_root/FINAL_OUTPUTS[3]);write_csv(named,output_root/FINAL_OUTPUTS[4]);write_csv(d0_summary,output_root/FINAL_OUTPUTS[5]);write_csv(pd.DataFrame(years),output_root/FINAL_OUTPUTS[6]);write_gz(random,output_root/FINAL_OUTPUTS[7]);write_csv(random_summary,output_root/FINAL_OUTPUTS[8]);write_csv(percentiles,output_root/FINAL_OUTPUTS[9]);write_gz(boot[63],output_root/FINAL_OUTPUTS[10]);write_gz(boot[21],output_root/FINAL_OUTPUTS[11]);write_gz(boot[126],output_root/FINAL_OUTPUTS[12]);write_csv(boot_summary,output_root/FINAL_OUTPUTS[13]);write_json(result,output_root/FINAL_OUTPUTS[14]);(output_root/FINAL_OUTPUTS[15]).write_text(f"# Stage 4A.3 Final Prospective Report\n\nPrimary: R3_K1\n\nComparator: R0_K1\n\nConclusion: {result['Conclusion']}\n\nStage 5: {result['Stage 5']}\n\nT2 score-based prospective metric: NOT AVAILABLE — NO T2 MODEL IN FROZEN PROSPECTIVE BUNDLE.\n\nNo secondary substitution is allowed.\n",encoding="utf-8",newline="\n");write_gz(d1_trades,output_root/FINAL_OUTPUTS[16]);write_gz(d1_daily,output_root/FINAL_OUTPUTS[17]);write_gz(d0_trades,output_root/FINAL_OUTPUTS[18]);write_gz(d0_daily,output_root/FINAL_OUTPUTS[19])
    return result


def parser()->argparse.ArgumentParser:
    value=argparse.ArgumentParser(description="Locked Stage 4A.3 final confirmatory evaluation");value.add_argument("--repo-root",type=Path,required=True);value.add_argument("--stage-root",type=Path,required=True);value.add_argument("--as-of",required=True);value.add_argument("--output-root",type=Path);return value
def main()->None:
    args=parser().parse_args();stage=args.stage_root.resolve();output=(args.output_root or stage/"results").resolve()
    if output!=(stage/"results").resolve() and not output.is_relative_to((stage/"tests").resolve()) and "tests" not in {p.lower() for p in stage.parts}:raise RuntimeError("TEST_EVALUATION_OUTPUT_MUST_STAY_UNDER_TESTS")
    print(json.dumps(evaluate(args.repo_root.resolve(),stage,args.as_of,output),indent=2))
if __name__=="__main__":main()
