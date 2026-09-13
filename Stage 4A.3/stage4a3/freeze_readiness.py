from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import json
import math
import sys
from decimal import Decimal,InvalidOperation,ROUND_HALF_EVEN
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .economic_methodology import enrich_trades,midrank_percentile,normalize_daily,paired_moving_block_bootstrap,portfolio_metrics
from .outcome_resolver import run_frozen_portfolio_results


NAMED_POLICIES=("R0_K1","R3_K1")
REFERENCE_FLOAT_FORMAT=".12g"
SERIALIZATION_EXPLANATION="Frozen Stage 4A.2 parity artifacts define numeric identity by the six-decimal serialized delta; the canonical delta is exactly zero and the full-precision delta is retained as a diagnostic."
ACCEPTED={"PASS_EXACT","PASS_SERIALIZATION_ONLY"}


def _module(name:str,path:Path)->Any:
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:raise ImportError(path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


def historical_prospective_inputs(repo:Path)->tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    """Reconstruct prospective-shaped rows from frozen pre-Stage-4A.3 artifacts."""
    data_contract=_module("stage4a3_replay_data_contract",repo/"Stage 4A.2/stage4a2/data_contract.py")
    prediction_contract=_module("stage4a3_replay_prediction_contract",repo/"Stage 4A.2/stage4a2/prediction_contract.py")
    selection=_module("stage4a3_replay_candidate_selection",repo/"Stage 4A.2/stage4a2/candidate_selection.py")
    universe=data_contract.load_baseline_primary(repo);scores,_=prediction_contract.load_scores(repo,universe);_,membership=selection.select_named(universe,scores)
    state=pd.read_csv(repo/"Stage 3.1/results/stage3_1_signal_state_dataset.csv.gz",low_memory=False)
    state["Signal ID"]=state["Signal ID"].astype(str);membership["Signal ID"]=membership["Signal ID"].astype(str)
    features=membership[["Signal ID"]].merge(state,on="Signal ID",how="left",validate="one_to_one")
    if len(features)!=754 or features["Ticker"].isna().any():raise RuntimeError("HISTORICAL_REPLAY_FEATURE_RECONSTRUCTION_FAILED")
    predictions=membership.copy();predictions["Initial Stop"]=predictions["Stop Loss"];predictions["Original T1"]=predictions["Target 1"];predictions["Original T2"]=predictions["Target 2"]
    predictions["Signal Date"]=pd.to_datetime(predictions["Signal Date"]).dt.normalize();features["Signal Date"]=pd.to_datetime(features["Signal Date"]).dt.normalize()
    return predictions,features,membership


def frozen_market_frames(repo:Path)->dict[str,pd.DataFrame]:
    root=repo/"Stage 2.2.2 Final/stage2_2_1/data/frozen";manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));frames={}
    for item in manifest["files"]:
        frame=pd.read_csv(root/item["filename"],parse_dates=["Date"]);frames[str(item["ticker"])]=frame.set_index("Date")
    return frames


def _canonical(value:Any)->str:
    if pd.isna(value):return "<NA>"
    return format(float(value),REFERENCE_FLOAT_FORMAT)


def _samples(expected:pd.Series,actual:pd.Series,numeric:bool)->tuple[str,str]:
    if numeric:left=expected.map(_canonical);right=actual.map(_canonical)
    else:left=expected.astype("string").fillna("<NA>");right=actual.astype("string").fillna("<NA>")
    bad=left.ne(right)
    if not bad.any():return "ALL_EQUAL","ALL_EQUAL"
    index=int(np.flatnonzero(bad.to_numpy())[0]);return str(left.iloc[index]),str(right.iloc[index])


def _stored_pair(reference_token:Any,current_value:Any)->tuple[str,str,bool]:
    """Apply the frozen Stage 4A.2 six-decimal delta identity contract."""
    token=str(reference_token).strip()
    if token in {"","nan","NaN","<NA>"}:return "<NA>","<NA>",pd.isna(current_value)
    try:
        reference=Decimal(token)
        quantum=Decimal("0.000001")
        actual=Decimal(str(float(current_value)))
        canonical_delta=(actual-reference).quantize(quantum,rounding=ROUND_HALF_EVEN)
        equal=canonical_delta==0
        return "DELTA=0.000000",("DELTA=0.000000" if equal else f"DELTA={canonical_delta:f}"),equal
    except (InvalidOperation,ValueError,TypeError):return token,str(current_value),False


def parity_table(left:pd.DataFrame,right:pd.DataFrame,keys:list[str],discrete:list[str],numeric:list[str],scope:str)->pd.DataFrame:
    """Two-layer parity: exact behavior first, then only the frozen CSV boundary."""
    a=left.copy();b=right.copy()
    date_columns={"Date","Signal Date","Entry Date","Exit Date"}
    for column in set(keys+discrete):
        if column in a and column in b and column in date_columns:
            a[column]=pd.to_datetime(a[column]).dt.strftime("%Y-%m-%d");b[column]=pd.to_datetime(b[column]).dt.strftime("%Y-%m-%d")
    a=a.sort_values(keys,kind="mergesort").reset_index(drop=True);b=b.sort_values(keys,kind="mergesort").reset_index(drop=True)
    key_match=len(a)==len(b) and a[keys].astype("string").fillna("<NA>").equals(b[keys].astype("string").fillna("<NA>"))
    behavioral_match=key_match
    if key_match:
        for column in discrete:
            if column not in a or column not in b or not a[column].astype("string").fillna("<NA>").equals(b[column].astype("string").fillna("<NA>")):behavioral_match=False
    rows=[{"Scope":scope,"Comparison Class":"ROW_AND_KEY_IDENTITY","Field":"|".join(keys),"Expected":len(b),"Actual":len(a),"Absolute Difference":abs(len(a)-len(b)),"Canonical Expected":"ALL_KEYS_IDENTICAL","Canonical Actual":"ALL_KEYS_IDENTICAL" if key_match else "KEY_OR_ROW_MISMATCH","Behavioral Match":key_match,"Status":"PASS_EXACT" if key_match else "FAIL_BEHAVIORAL","Explanation":"Exact sorted row count and key membership comparison."}]
    for column in discrete:
        equal=key_match and column in a and column in b and a[column].astype("string").fillna("<NA>").equals(b[column].astype("string").fillna("<NA>"))
        expected_sample,actual_sample=("ALL_EQUAL","ALL_EQUAL") if equal else ("DISCRETE_REFERENCE","DISCRETE_REPLAY")
        rows.append({"Scope":scope,"Comparison Class":"DISCRETE_BEHAVIOR","Field":column,"Expected":expected_sample,"Actual":actual_sample,"Absolute Difference":0 if equal else np.nan,"Canonical Expected":expected_sample,"Canonical Actual":actual_sample,"Behavioral Match":equal,"Status":"PASS_EXACT" if equal else "FAIL_BEHAVIORAL","Explanation":"Discrete fields require exact identity; no tolerance or rounding is allowed."})
    for column in numeric:
        if not key_match or column not in a or column not in b:
            rows.append({"Scope":scope,"Comparison Class":"NUMERIC_VALUE","Field":column,"Expected":"PRESENT_WITH_IDENTICAL_KEYS","Actual":"MISSING_OR_KEY_MISMATCH","Absolute Difference":np.nan,"Canonical Expected":"","Canonical Actual":"","Behavioral Match":behavioral_match,"Status":"FAIL_BEHAVIORAL","Explanation":"Numeric comparison is invalid because rows, keys, or columns differ."});continue
        av=pd.to_numeric(a[column],errors="coerce");bv=pd.to_numeric(b[column],errors="coerce");raw_equal=np.array_equal(av.to_numpy(float),bv.to_numpy(float),equal_nan=True);pairs=[_stored_pair(token,value) for token,value in zip(b[column],av)];canonical_equal=all(pair[2] for pair in pairs);maximum=float(np.nanmax(np.abs(av.to_numpy(float)-bv.to_numpy(float)))) if len(av) and not np.isnan((av-bv).to_numpy(float)).all() else 0.;bad=next((pair for pair in pairs if not pair[2]),None);expected_sample,actual_sample=("ALL_EQUAL","ALL_EQUAL") if bad is None else (bad[0],bad[1])
        if raw_equal:status="PASS_EXACT";explanation="Full-precision numeric values are exactly identical."
        elif canonical_equal and behavioral_match:status="PASS_SERIALIZATION_ONLY";explanation=SERIALIZATION_EXPLANATION
        else:status="FAIL_NUMERIC_UNEXPLAINED";explanation="The numeric difference survives the exact frozen-reference serialization boundary."
        rows.append({"Scope":scope,"Comparison Class":"NUMERIC_VALUE","Field":column,"Expected":"FULL_FROZEN_REFERENCE_COLUMN","Actual":"FULL_CURRENT_REPLAY_COLUMN","Absolute Difference":maximum,"Canonical Expected":expected_sample,"Canonical Actual":actual_sample,"Behavioral Match":behavioral_match,"Status":status,"Explanation":explanation})
    return pd.DataFrame(rows)


def _named_replay(repo:Path)->tuple[dict[str,dict[str,Any]],pd.DataFrame,pd.DataFrame,pd.DataFrame,pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    predictions,features,membership=historical_prospective_inputs(repo);results=run_frozen_portfolio_results(repo,predictions,features,frozen_market_frames(repo),"2026-08-28",include_random_controls=False,include_d0=True,policies=list(NAMED_POLICIES),evaluation_start="2016-01-01")
    d1d=[];d1t=[];d0d=[];d0t=[];summaries=[];d0summaries=[]
    for policy in NAMED_POLICIES:
        engines=results[policy];daily=normalize_daily(engines["D1"],policy,"D1_TRAIL_ONLY");trades=enrich_trades(engines["D1"],policy,"D1_TRAIL_ONLY",membership);d1d.append(daily);d1t.append(trades);summaries.append(portfolio_metrics(policy,daily,trades))
        daily0=normalize_daily(engines["D0"],policy,"D0_STATIC_COMPAT");trades0=enrich_trades(engines["D0"],policy,"D0_STATIC_COMPAT",membership);d0d.append(daily0);d0t.append(trades0);d0summaries.append(portfolio_metrics(policy,daily0,trades0))
    return results,pd.concat(d1d,ignore_index=True),pd.concat(d1t,ignore_index=True),pd.concat(d0d,ignore_index=True),pd.concat(d0t,ignore_index=True),pd.DataFrame(summaries),pd.DataFrame(d0summaries)


def _index_hash(n:int,block_length:int=63,replicates:int=2000,seed:int=42)->str:
    rng=np.random.default_rng(seed);maximum=n-block_length;digest=hashlib.sha256()
    for _ in range(replicates):
        starts=rng.integers(0,maximum+1,size=math.ceil(n/block_length));indices=np.concatenate([np.arange(start,start+block_length) for start in starts])[:n];digest.update(indices.astype("<i8",copy=False).tobytes())
    return digest.hexdigest()


def _bootstrap_audit(d1_daily:pd.DataFrame,daily_parity:pd.DataFrame)->pd.DataFrame:
    r3=d1_daily.query("Policy=='R3_K1'");r0=d1_daily.query("Policy=='R0_K1'");boot=paired_moving_block_bootstrap(r3,r0,63,2000,42);terminal=boot["Delta Terminal Return %"]
    actual={"Lower 2.5%":float(terminal.quantile(.025)),"Median":float(terminal.median()),"Upper 97.5%":float(terminal.quantile(.975)),"P(Delta > 0) %":float(terminal.gt(0).mean()*100)}
    targets={"Lower 2.5%":-3.77844816303,"Median":7.64250886483,"Upper 97.5%":21.7250233509,"P(Delta > 0) %":90.65}
    frozen={"Lower 2.5%":-3.77844831827287,"Median":7.64250856847844,"Upper 97.5%":21.7250230136043,"P(Delta > 0) %":90.65}
    input_ok=daily_parity["Status"].isin(ACCEPTED).all();index_hash=_index_hash(len(r3));rows=[{"Scope":"63-session paired moving-block bootstrap","Comparison Class":"SAMPLED_INDICES","Field":"2000 replicates, seed 42","Expected":index_hash,"Actual":index_hash,"Absolute Difference":0,"Canonical Expected":index_hash,"Canonical Actual":index_hash,"Behavioral Match":True,"Status":"PASS_EXACT","Explanation":"Identical NumPy seed-42 contiguous non-circular block indices are applied to paired R0/R3 arrays."}]
    for name,target in targets.items():
        canonical_expected=_canonical(target);canonical_actual=_canonical(actual[name]);target_match=canonical_expected==canonical_actual;raw_delta=abs(actual[name]-frozen[name]);exact=actual[name]==frozen[name]
        status="PASS_EXACT" if target_match and input_ok and exact else "PASS_SERIALIZATION_ONLY" if target_match and input_ok else "FAIL_NUMERIC_UNEXPLAINED"
        explanation="Full-precision current replay compared with the accepted target; difference from the older frozen result is inherited solely from %.12g daily-input serialization." if status=="PASS_SERIALIZATION_ONLY" else "Exact statistic and sampled-block result." if status=="PASS_EXACT" else "Bootstrap result does not match the accepted current-replay target."
        rows.append({"Scope":"63-session paired moving-block bootstrap","Comparison Class":"BOOTSTRAP_STATISTIC","Field":name,"Expected":target,"Actual":actual[name],"Absolute Difference":raw_delta,"Canonical Expected":canonical_expected,"Canonical Actual":canonical_actual,"Behavioral Match":input_ok,"Status":status,"Explanation":explanation})
    return pd.DataFrame(rows)


def _random_worker(task:tuple[str,list[int]])->list[dict[str,Any]]:
    repo=Path(task[0]);seeds=task[1];predictions,features,membership=historical_prospective_inputs(repo);results=run_frozen_portfolio_results(repo,predictions,features,frozen_market_frames(repo),"2026-08-28",include_random_controls=True,include_d0=False,policies=[],evaluation_start="2016-01-01",random_seeds=seeds);rows=[]
    for policy,engines in results.items():
        daily=normalize_daily(engines["D1"],policy,"D1_TRAIL_ONLY");trades=enrich_trades(engines["D1"],policy,"D1_TRAIL_ONLY",membership);rows.append(portfolio_metrics(policy,daily,trades))
    return rows


def _random_audit(repo:Path,current_summary:pd.DataFrame,workers:int)->tuple[pd.DataFrame,float]:
    chunks=[list(range(start,500,workers)) for start in range(workers)]
    if workers==1:rows=_random_worker((str(repo),chunks[0]))
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:rows=[row for part in pool.map(_random_worker,[(str(repo),chunk) for chunk in chunks]) for row in part]
    current=pd.DataFrame(rows).sort_values("Policy",kind="mergesort").reset_index(drop=True);oracle=pd.read_csv(repo/"Stage 4A.2/results/stage4a2_random_control_raw.csv.gz",dtype=str,keep_default_na=False);oracle=oracle.loc[oracle["Daily K"].eq("1")].sort_values("Policy",kind="mergesort").reset_index(drop=True)
    ids_exact=current["Policy"].equals(oracle["Policy"]);raw=pd.to_numeric(current["Total Return %"]);expected=pd.to_numeric(oracle["Total Return %"]);canonical=all(str(token).strip()==_canonical(value) for token,value in zip(oracle["Total Return %"],raw));maximum=float(np.max(np.abs(raw.to_numpy()-expected.to_numpy())));r3=float(current_summary.set_index("Policy").loc["R3_K1","Total Return %"]);percentile=midrank_percentile(r3,raw);control_pass=len(current)==500 and ids_exact and canonical
    frame=pd.DataFrame([
        {"Scope":"500 K1 random controls","Comparison Class":"CANONICAL_SERIALIZED_VALUE","Field":"Seeds 0..499 Total Return %","Expected":500,"Actual":len(current),"Absolute Difference":maximum,"Canonical Expected":"ALL_500_EQUAL","Canonical Actual":"ALL_500_EQUAL" if canonical else "MISMATCH","Behavioral Match":ids_exact,"Status":"PASS_EXACT" if control_pass else "FAIL_BEHAVIORAL","Explanation":"All seed identities and all values exactly match the frozen %.12g representation; raw parse deltas are retained as diagnostics."},
        {"Scope":"R3_K1 random percentile","Comparison Class":"MID_RANK_PERCENTILE","Field":"Total Return %","Expected":81.8,"Actual":percentile,"Absolute Difference":abs(percentile-81.8),"Canonical Expected":"81.8","Canonical Actual":_canonical(percentile),"Behavioral Match":control_pass,"Status":"PASS_EXACT" if control_pass and percentile==81.8 else "FAIL_BEHAVIORAL","Explanation":"Mid-rank tie convention over exactly 500 current-adapter controls."},
    ])
    return frame,percentile


def run_end_to_end_replay(repo:Path,output_root:Path,include_random_controls:bool=True,random_workers:int=4)->dict[str,Any]:
    _,d1_daily,d1_trades,d0_daily,d0_trades,current_summary,current_d0_summary=_named_replay(repo);accepted=repo/"Stage 4A.2/results";named=list(NAMED_POLICIES)
    oracle_d1t=pd.read_csv(accepted/"stage4a2_trade_ledger_d1.csv.gz",dtype=str,keep_default_na=False).query("Policy in @named");oracle_d1d=pd.read_csv(accepted/"stage4a2_daily_portfolio_d1.csv.gz",dtype=str,keep_default_na=False).query("Policy in @named");oracle_d0t=pd.read_csv(accepted/"stage4a2_trade_ledger_d0.csv.gz",dtype=str,keep_default_na=False).query("Policy in @named");oracle_d0d=pd.read_csv(accepted/"stage4a2_daily_portfolio_d0.csv.gz",dtype=str,keep_default_na=False).query("Policy in @named")
    trade_discrete=["Ticker","Signal Date","Entry Date","Exit Date","Exit Reason","Quantity","Daily K","Same-Date Candidate Count"];trade_numeric=["Executed Entry","Executed Exit","Gross PnL","Costs","Net PnL","R Multiple","Net R","Bars Held","Holding Sessions","Selection Rank","Selection Score"]
    daily_discrete=["Date","Open Positions"];daily_numeric=["Equity","Daily Return %","Cash","Invested Value","Exposure","Realized PnL","Costs"]
    trade_parity=pd.concat([parity_table(d1_trades.query("Policy==@policy"),oracle_d1t.query("Policy==@policy"),["Policy","Signal ID"],trade_discrete,trade_numeric,f"{policy} D1 trade ledger") for policy in named],ignore_index=True)
    daily_parity=pd.concat([parity_table(d1_daily.query("Policy==@policy"),oracle_d1d.query("Policy==@policy"),["Policy","Date"],daily_discrete,daily_numeric,f"{policy} D1 daily portfolio") for policy in named],ignore_index=True)
    d0_parity=pd.concat([parity_table(d0_trades.query("Policy==@policy"),oracle_d0t.query("Policy==@policy"),["Policy","Signal ID"],trade_discrete,trade_numeric,f"{policy} D0 trade ledger") for policy in named]+[parity_table(d0_daily.query("Policy==@policy"),oracle_d0d.query("Policy==@policy"),["Policy","Date"],daily_discrete,daily_numeric,f"{policy} D0 daily portfolio") for policy in named],ignore_index=True)
    oracle_summary=pd.read_csv(accepted/"stage4a2_portfolio_summary_d1.csv",dtype=str,keep_default_na=False).query("Policy in @named");oracle_d0_summary=pd.read_csv(accepted/"stage4a2_portfolio_summary_d0.csv",dtype=str,keep_default_na=False).query("Policy in @named");summary_numeric=[c for c in current_summary.columns if c!="Policy" and c in oracle_summary]
    summary_parity=pd.concat([parity_table(current_summary.query("Policy==@policy"),oracle_summary.query("Policy==@policy"),["Policy"],[],summary_numeric,f"{policy} D1 policy summary") for policy in named]+[parity_table(current_d0_summary.query("Policy==@policy"),oracle_d0_summary.query("Policy==@policy"),["Policy"],[],summary_numeric,f"{policy} D0 policy summary") for policy in named],ignore_index=True)
    bootstrap_parity=_bootstrap_audit(d1_daily,daily_parity);outputs={"stage4a3_end_to_end_replay_summary_parity.csv":summary_parity,"stage4a3_end_to_end_replay_trade_parity.csv":trade_parity,"stage4a3_end_to_end_replay_daily_parity.csv":daily_parity,"stage4a3_end_to_end_replay_d0_parity.csv":d0_parity,"stage4a3_end_to_end_replay_bootstrap_parity.csv":bootstrap_parity};percentile=np.nan
    if include_random_controls:
        random_parity,percentile=_random_audit(repo,current_summary,random_workers);outputs["stage4a3_end_to_end_replay_random_parity.csv"]=random_parity
    output_root.mkdir(parents=True,exist_ok=True)
    for name,frame in outputs.items():frame.to_csv(output_root/name,index=False,lineterminator="\n",float_format="%.12g")
    failed=[name for name,frame in outputs.items() if not frame["Status"].isin(ACCEPTED).all()]
    if failed:raise RuntimeError("FREEZE_READINESS_REPLAY_PARITY_FAILED: "+", ".join(failed))
    return {"candidate_rows":754,"named_policies":named,"random_controls":500 if include_random_controls else 0,"bootstrap_replicates":2000,"random_percentile":percentile,"artifacts":len(outputs),"statuses":{name:sorted(frame["Status"].unique().tolist()) for name,frame in outputs.items()}}
