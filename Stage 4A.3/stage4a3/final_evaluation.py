from __future__ import annotations

import argparse,gzip,json,math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score,brier_score_loss,log_loss,roc_auc_score

from .candidate_selection import random_key
from .final_analysis_gate import gate_audit,is_unlocked
from .immutable_ledger import record_breach
from .ledger_counts import derive_final_gate_counts,prediction_rows
from .outcome_resolver import load_all_events


FINAL_OUTPUTS=["stage4a3_final_gate_audit.csv","stage4a3_prospective_sample_summary.csv","stage4a3_predictive_metrics.csv","stage4a3_predictive_calibration.csv","stage4a3_policy_summary_d1.csv","stage4a3_policy_summary_d0.csv","stage4a3_yearly_or_period_metrics.csv","stage4a3_random_control_raw.csv.gz","stage4a3_random_control_summary.csv","stage4a3_named_policy_random_percentiles.csv","stage4a3_block_bootstrap_63.csv.gz","stage4a3_block_bootstrap_21.csv.gz","stage4a3_block_bootstrap_126.csv.gz","stage4a3_bootstrap_summary.csv","stage4a3_primary_confirmatory_result.json","Stage4A3_Final_Prospective_Report.md"]


def write_csv(frame:pd.DataFrame,path:Path)->None:path.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(path,index=False,lineterminator="\n",float_format="%.12g")
def write_gz(frame:pd.DataFrame,path:Path)->None:
    path.parent.mkdir(parents=True,exist_ok=True);payload=frame.to_csv(index=False,lineterminator="\n",float_format="%.12g").encode()
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as zipped:zipped.write(payload)
def write_json(value:Any,path:Path)->None:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8",newline="\n")


def economic_criteria(r3:dict[str,Any],r0:dict[str,Any],evidence:dict[str,Any])->pd.DataFrame:
    checks=[("total return",r3["total_return"]>r0["total_return"]),("CAGR",r3["cagr"]>r0["cagr"]),("expectancy R",r3["expectancy_r"]>r0["expectancy_r"]),("profit factor",r3["profit_factor"]>=r0["profit_factor"]),("bootstrap lower 2.5%",evidence["bootstrap_63_delta_terminal_return_lower_2_5"]>0),("random K1 percentile",evidence["random_k1_total_return_percentile"]>=95),("max drawdown tolerance",r3["max_drawdown"]>=r0["max_drawdown"]-0.02),("minimum completed trades",r3["completed_trades"]>=50),("ledger integrity",bool(evidence["ledger_integrity_pass"])),("no protocol drift",bool(evidence["no_protocol_drift"]))]
    return pd.DataFrame([{"Criterion":name,"Status":"PASS" if passed else "FAIL"} for name,passed in checks])


def require_unlocked(config:dict[str,Any],activation:dict[str,Any],counts:dict[str,Any],audit_root:Path)->pd.DataFrame:
    audit=gate_audit(config,activation,counts)
    if not is_unlocked(audit):
        record_breach(audit_root,{"UTC Time":pd.Timestamp.now(tz="UTC").isoformat(),"Breach Type":"PREMATURE_EVALUATION_ATTEMPT","Details":"PROSPECTIVE_EVALUATION_LOCKED","Blocked / Allowed":"BLOCKED","Affected Signal Date":"","Protocol Hash":counts.get("protocol_hash","")})
        raise RuntimeError("PROSPECTIVE_EVALUATION_LOCKED\n"+audit.to_csv(index=False))
    return audit


def _boolean(value:Any)->bool:return str(value).strip().lower() in {"true","1","yes"}
def _economic_value(value:Any)->dict[str,float]:
    try:
        item=json.loads(value) if isinstance(value,str) and value.strip().startswith("{") else {"Net R":float(value)}
    except Exception:item={"Net R":float("nan")}
    net_r=float(item.get("Net R",item.get("net_r",float("nan"))));fraction=float(item.get("Portfolio Return Fraction",item.get("portfolio_return_fraction",net_r*0.0075)))
    return {"net_r":net_r,"return_fraction":fraction}


def policy_summary(events:pd.DataFrame,engine:str="D1")->pd.DataFrame:
    rows=[]
    for policy,group in events.groupby("Policy"):
        values=[_economic_value(value) for value in group["Outcome Value"]];r=np.array([x["net_r"] for x in values],float);returns=np.array([x["return_fraction"] for x in values],float);equity=np.cumprod(1+np.nan_to_num(returns,nan=0));total=float(equity[-1]-1) if len(equity) else 0.;years=max((pd.to_datetime(group["Label Available Date"]).max()-pd.to_datetime(group["Signal Date"]).min()).days/365.25,1/365.25);peaks=np.maximum.accumulate(np.r_[1.,equity]);curve=np.r_[1.,equity]
        positive=float(r[r>0].sum());negative=float(-r[r<0].sum())
        rows.append({"Policy":policy,"Exit Engine":engine,"Completed Trades":len(group),"Total Return":total,"CAGR":float((1+total)**(1/years)-1) if total>-1 else -1.,"Expectancy R":float(np.nanmean(r)) if len(r) else np.nan,"Profit Factor":positive/negative if negative else np.inf,"Maximum Drawdown":float(np.min(curve/peaks-1)),"Ending Equity":float(100000*(1+total))})
    return pd.DataFrame(rows)


def predictive_outputs(predictions:pd.DataFrame,events:pd.DataFrame)->tuple[pd.DataFrame,pd.DataFrame]:
    specs=[("ENTRY_FILLED","R5 Score"),("T1_BEFORE_STOP_63","R3 Score"),("T2_BEFORE_STOP_63","R3 Score")];rows=[];cal=[]
    for target,score in specs:
        outcome=events.loc[(events["Outcome Type"]==target)&events["Policy"].fillna("").eq("")].copy();outcome["Observed"]=outcome["Outcome Value"].map(_boolean);merged=predictions[["Signal ID",score]].merge(outcome[["Signal ID","Observed"]],on="Signal ID")
        y=merged["Observed"].astype(int).to_numpy();p=merged[score].astype(float).to_numpy();valid=len(np.unique(y))==2
        rows.append({"Target":target,"Score":score,"Rows":len(y),"ROC AUC":roc_auc_score(y,p) if valid else np.nan,"Average Precision":average_precision_score(y,p) if len(y) else np.nan,"Brier":brier_score_loss(y,p) if len(y) else np.nan,"Brier Skill":1-brier_score_loss(y,p)/(np.mean(y)*(1-np.mean(y))) if valid else np.nan,"Log Loss":log_loss(y,np.clip(p,1e-15,1-1e-15),labels=[0,1]) if len(y) else np.nan})
        if len(merged):
            bins=pd.cut(merged[score],np.linspace(0,1,11),include_lowest=True)
            for band,g in merged.groupby(bins,observed=False):cal.append({"Target":target,"Score":score,"Bucket":str(band),"Rows":len(g),"Mean Score":g[score].mean(),"Observed Rate":g["Observed"].mean()})
    return pd.DataFrame(rows),pd.DataFrame(cal)


def random_controls(exact_random_events:pd.DataFrame)->pd.DataFrame:
    expected={f"RANDOM_K1_SEED_{seed:03d}" for seed in range(500)};actual=set(exact_random_events["Policy"].astype(str))
    if actual!=expected:raise RuntimeError("EXACT_RANDOM_K1_CONTROL_SET_INCOMPLETE")
    summary=policy_summary(exact_random_events);summary["Seed"]=summary["Policy"].str[-3:].astype(int);summary["Daily K"]=1
    return summary.rename(columns={"Completed Trades":"Trade Count"})


def moving_block_bootstrap(events:pd.DataFrame,block:int,replicates:int=2000,seed:int=42)->pd.DataFrame:
    daily={}
    for policy in ("R0_K1","R3_K1"):
        group=events.loc[events["Policy"].eq(policy)].copy();group["Return"]=[_economic_value(v)["return_fraction"] for v in group["Outcome Value"]];daily[policy]=group.groupby("Signal Date")["Return"].sum()
    aligned=pd.concat(daily,axis=1).fillna(0).sort_index();n=len(aligned);rng=np.random.default_rng(seed);rows=[]
    if not n:return pd.DataFrame(columns=["Replicate","Block Length","R0_K1 Terminal Return","R3_K1 Terminal Return","Delta Terminal Return"])
    for replicate in range(replicates):
        indexes=[]
        while len(indexes)<n:
            start=int(rng.integers(0,n));indexes.extend((start+i)%n for i in range(block))
        sample=aligned.iloc[indexes[:n]];r0=float(np.prod(1+sample["R0_K1"])-1);r3=float(np.prod(1+sample["R3_K1"])-1);rows.append({"Replicate":replicate,"Block Length":block,"R0_K1 Terminal Return":r0,"R3_K1 Terminal Return":r3,"Delta Terminal Return":r3-r0})
    return pd.DataFrame(rows)


def evaluate(repo:Path,stage_root:Path,as_of_date:str,output_root:Path)->dict[str,Any]:
    config=json.loads((stage_root/"config/stage4a3_protocol.json").read_text());activation=json.loads((stage_root/"prospective/audit/activation_record.json").read_text());synthetic="tests" in {p.lower() for p in stage_root.parts}
    counts=derive_final_gate_counts(repo,stage_root,as_of_date,synthetic_integrity=synthetic);audit=require_unlocked(config,activation,counts,stage_root/"prospective/audit")
    predictions=prediction_rows(stage_root);events=load_all_events(stage_root/"prospective/outcomes");terminal=events.loc[events["Is Terminal"].map(_boolean)]
    d1=terminal.loc[terminal["Outcome Type"].eq("D1_TRADE_COMPLETION")];d1_named=d1.loc[~d1["Policy"].eq("OPPORTUNITY_D1") & ~d1["Policy"].str.startswith("RANDOM_K1_SEED_",na=False)];d0=d1.loc[d1["Policy"].str.endswith("_D0",na=False)]
    d1_summary=policy_summary(d1_named.loc[~d1_named["Policy"].str.endswith("_D0",na=False)]);d0_summary=policy_summary(d0,"D0_STATIC_COMPAT") if len(d0) else pd.DataFrame(columns=d1_summary.columns)
    predictive,calibration=predictive_outputs(predictions,terminal);random=random_controls(d1.loc[d1["Policy"].str.startswith("RANDOM_K1_SEED_",na=False)])
    boot={block:moving_block_bootstrap(d1,block,2000,42) for block in (63,21,126)};boot_summary=pd.DataFrame([{"Block Length":block,"Replicates":len(frame),"Seed":42,"Delta Terminal Return Lower 2.5%":frame["Delta Terminal Return"].quantile(.025),"Median":frame["Delta Terminal Return"].median(),"Upper 97.5%":frame["Delta Terminal Return"].quantile(.975)} for block,frame in boot.items()])
    lookup=d1_summary.set_index("Policy");r0row=lookup.loc["R0_K1"];r3row=lookup.loc["R3_K1"];r0={"total_return":r0row["Total Return"],"cagr":r0row["CAGR"],"expectancy_r":r0row["Expectancy R"],"profit_factor":r0row["Profit Factor"],"max_drawdown":r0row["Maximum Drawdown"],"completed_trades":r0row["Completed Trades"]};r3={"total_return":r3row["Total Return"],"cagr":r3row["CAGR"],"expectancy_r":r3row["Expectancy R"],"profit_factor":r3row["Profit Factor"],"max_drawdown":r3row["Maximum Drawdown"],"completed_trades":r3row["Completed Trades"]}
    percentile=float((random["Total Return"]<=r3["total_return"]).mean()*100);evidence={"bootstrap_63_delta_terminal_return_lower_2_5":float(boot_summary.set_index("Block Length").loc[63,"Delta Terminal Return Lower 2.5%"]),"random_k1_total_return_percentile":percentile,"ledger_integrity_pass":counts["ledger_chain_pass"],"no_protocol_drift":counts["protocol_integrity_pass"]};criteria=economic_criteria(r3,r0,evidence);confirmed=criteria["Status"].eq("PASS").all()
    sample=pd.DataFrame([counts]);yearly=d1_named.assign(Period=pd.to_datetime(d1_named["Label Available Date"]).dt.year).groupby(["Policy","Period"]).size().rename("Completed Trades").reset_index();random_summary=random[["Total Return","Expectancy R"]].agg(["min","median","max"]).reset_index(names="Statistic");percentiles=pd.DataFrame([{"Policy":"R3_K1","Random K1 Total Return Percentile":percentile}]);result={"Primary Policy":"R3_K1","Comparator":"R0_K1","All Ten Criteria Pass":bool(confirmed),"Conclusion":"PROSPECTIVELY CONFIRMED POSITIVE ECONOMIC UTILITY" if confirmed else "NOT PROSPECTIVELY CONFIRMED","Stage 5":"MAY BE CONSIDERED" if confirmed else "REMAINS BLOCKED","Secondary Substitution Allowed":False,"Criteria":criteria.to_dict("records")}
    write_csv(audit,output_root/FINAL_OUTPUTS[0]);write_csv(sample,output_root/FINAL_OUTPUTS[1]);write_csv(predictive,output_root/FINAL_OUTPUTS[2]);write_csv(calibration,output_root/FINAL_OUTPUTS[3]);write_csv(d1_summary,output_root/FINAL_OUTPUTS[4]);write_csv(d0_summary,output_root/FINAL_OUTPUTS[5]);write_csv(yearly,output_root/FINAL_OUTPUTS[6]);write_gz(random,output_root/FINAL_OUTPUTS[7]);write_csv(random_summary,output_root/FINAL_OUTPUTS[8]);write_csv(percentiles,output_root/FINAL_OUTPUTS[9]);write_gz(boot[63],output_root/FINAL_OUTPUTS[10]);write_gz(boot[21],output_root/FINAL_OUTPUTS[11]);write_gz(boot[126],output_root/FINAL_OUTPUTS[12]);write_csv(boot_summary,output_root/FINAL_OUTPUTS[13]);write_json(result,output_root/FINAL_OUTPUTS[14]);(output_root/FINAL_OUTPUTS[15]).write_text(f"# Stage 4A.3 Final Prospective Report\n\nPrimary: R3_K1\n\nComparator: R0_K1\n\nConclusion: {result['Conclusion']}\n\nStage 5: {result['Stage 5']}\n\nNo secondary substitution is allowed.\n",encoding="utf-8",newline="\n")
    return result


def parser()->argparse.ArgumentParser:
    value=argparse.ArgumentParser(description="Locked Stage 4A.3 final confirmatory evaluation");value.add_argument("--repo-root",type=Path,required=True);value.add_argument("--stage-root",type=Path,required=True);value.add_argument("--as-of",required=True);value.add_argument("--output-root",type=Path);return value
def main()->None:
    args=parser().parse_args();stage=args.stage_root.resolve();output=(args.output_root or stage/"results").resolve()
    if output!= (stage/"results").resolve() and not output.is_relative_to((stage/"tests").resolve()) and "tests" not in {p.lower() for p in stage.parts}:raise RuntimeError("TEST_EVALUATION_OUTPUT_MUST_STAY_UNDER_TESTS")
    print(json.dumps(evaluate(args.repo_root.resolve(),stage,args.as_of,output),indent=2))
if __name__=="__main__":main()
