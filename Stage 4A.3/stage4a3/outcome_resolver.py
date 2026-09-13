from __future__ import annotations

import gzip
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any,Mapping

import pandas as pd

from .hashing import canonical_json_hash, dataframe_content_hash, sha256_file
from .immutable_ledger import record_breach
from .outcome_contract import OUTCOME_COLUMNS,OUTCOME_TYPES
from .candidate_selection import random_key


INDEX_COLUMNS=["Sequence","Batch ID","Generated UTC","Event Count","Batch File","Batch SHA256","Previous Event Hash","Current Event Hash"]
EVENT_GENESIS="STAGE4A3_OUTCOME_EVENT_GENESIS"


def _module(name:str,path:Path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:raise ImportError(path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


def seal_event(values: Mapping[str,Any], prior_event_hash: str) -> dict[str,Any]:
    if values["Outcome Type"] not in OUTCOME_TYPES:raise ValueError("Unknown frozen outcome type")
    if values.get("Label Available Date") and pd.Timestamp(values["Label Available Date"])<pd.Timestamp(values["Signal Date"]):raise ValueError("LABEL_AVAILABILITY_BEFORE_SIGNAL")
    normalized={key:("" if value is None else "TRUE" if value is True else "FALSE" if value is False else str(value)) for key,value in values.items()}
    event={**normalized,"Prior Event Hash":prior_event_hash,"Frozen Rule Semantics Version":"STAGE3.1_STOP_FIRST_MAX63_STAGE2B.1_D1_TRAIL_ONLY"}
    seed={key:value for key,value in event.items() if key not in {"Event ID","Event Hash"}}
    event.setdefault("Event ID","S4A3_OUTCOME_"+canonical_json_hash(seed)[:16]);event["Event Hash"]=canonical_json_hash(event);return event


def verify_event_chain(events: pd.DataFrame, genesis: str=EVENT_GENESIS) -> bool:
    prior=genesis
    for _,row in events.iterrows():
        values=row.to_dict();actual=values.pop("Event Hash");declared=values.get("Prior Event Hash")
        if declared!=prior or canonical_json_hash(values)!=actual:return False
        prior=actual
    return True


def load_all_events(outcome_root: Path) -> pd.DataFrame:
    index_path=outcome_root/"outcome_event_index.csv"
    if not index_path.exists() or not index_path.stat().st_size:return pd.DataFrame(columns=OUTCOME_COLUMNS)
    index=pd.read_csv(index_path,dtype=str);parts=[]
    for relative in index["Batch File"]:parts.append(pd.read_csv(outcome_root/relative,compression="gzip",dtype=str,keep_default_na=False))
    return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=OUTCOME_COLUMNS)


def append_event_batch(outcome_root: Path, events: list[dict[str,Any]], generated_utc: str, audit_root: Path|None=None, protocol_hash: str="") -> Path:
    if not events:raise ValueError("EMPTY_OUTCOME_BATCH")
    outcome_root.mkdir(parents=True,exist_ok=True);index_path=outcome_root/"outcome_event_index.csv"
    index=pd.read_csv(index_path,dtype=str) if index_path.exists() and index_path.stat().st_size else pd.DataFrame(columns=INDEX_COLUMNS)
    existing=load_all_events(outcome_root);terminal=existing.loc[existing["Is Terminal"].astype(str).str.lower().isin(["true","1"])] if len(existing) else existing
    terminal_keys={(str(r["Signal ID"]),str(r.get("Policy","")),str(r["Outcome Type"])):str(r["Outcome Value"]) for _,r in terminal.iterrows()}
    prior=EVENT_GENESIS if index.empty else str(index.iloc[-1]["Current Event Hash"]);sealed=[]
    for value in events:
        key=(str(value["Signal ID"]),str(value.get("Policy","")),str(value["Outcome Type"]))
        if key in terminal_keys:
            if terminal_keys[key]!=str(value["Outcome Value"]):
                if audit_root is not None:record_breach(audit_root,{"UTC Time":generated_utc,"Breach Type":"CONTRADICTORY_TERMINAL_OUTCOME","Details":str(key),"Blocked / Allowed":"BLOCKED","Affected Signal Date":value["Signal Date"],"Protocol Hash":protocol_hash})
                raise RuntimeError("CONTRADICTORY_TERMINAL_OUTCOME")
            raise RuntimeError("DUPLICATE_TERMINAL_OUTCOME")
        event=seal_event(value,prior);sealed.append(event);prior=event["Event Hash"]
    frame=pd.DataFrame(sealed,columns=OUTCOME_COLUMNS);logical=dataframe_content_hash(frame);batch_id="S4A3_OUTCOME_BATCH_"+logical[:16]
    signal_date=min(str(v["Signal Date"]) for v in sealed);directory=outcome_root/signal_date[:4]/signal_date;directory.mkdir(parents=True,exist_ok=True)
    stamp=pd.Timestamp(generated_utc).strftime("%Y%m%dT%H%M%S%fZ");relative=Path(signal_date[:4])/signal_date/f"{stamp}_{logical[:12]}.csv.gz";target=outcome_root/relative
    if target.exists():raise FileExistsError("OUTCOME_EVENT_BATCH_IMMUTABLE")
    payload=frame.to_csv(index=False,lineterminator="\n",float_format="%.17g").encode()
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as zipped:zipped.write(payload)
    row={"Sequence":len(index)+1,"Batch ID":batch_id,"Generated UTC":generated_utc,"Event Count":len(frame),"Batch File":relative.as_posix(),"Batch SHA256":sha256_file(target),"Previous Event Hash":EVENT_GENESIS if index.empty else index.iloc[-1]["Current Event Hash"],"Current Event Hash":prior}
    pd.concat([index,pd.DataFrame([row])],ignore_index=True).to_csv(index_path,index=False,lineterminator="\n");return target


def verify_outcome_ledger(outcome_root: Path) -> bool:
    index_path=outcome_root/"outcome_event_index.csv"
    if not index_path.exists():return not any(outcome_root.glob("*/*/*.csv.gz"))
    index=pd.read_csv(index_path,dtype=str);prior=EVENT_GENESIS;sequence=1
    for _,row in index.iterrows():
        path=outcome_root/row["Batch File"]
        if int(row["Sequence"])!=sequence or row["Previous Event Hash"]!=prior or not path.exists() or sha256_file(path)!=row["Batch SHA256"]:return False
        events=pd.read_csv(path,compression="gzip",dtype=str,keep_default_na=False)
        if events.empty or events.iloc[0]["Prior Event Hash"]!=prior:return False
        for _,event in events.iterrows():
            values=event.to_dict();actual=values.pop("Event Hash")
            if values["Prior Event Hash"]!=prior or canonical_json_hash(values)!=actual:return False
            prior=actual
        if prior!=row["Current Event Hash"]:return False
        sequence+=1
    indexed={str(value) for value in index["Batch File"]};present={path.relative_to(outcome_root).as_posix() for path in outcome_root.glob("*/*/*.csv.gz")}
    return indexed==present


def compute_frozen_label_events(repo: Path, snapshot_dir: Path, market_frames: Mapping[str,pd.DataFrame], observation_through: str, generated_utc: str, source_market_hash: str) -> list[dict[str,Any]]:
    """Compute ENTRY/T1/T2 from immutable predictions and future bars using frozen Stage 3 functions."""
    predictions=pd.read_csv(snapshot_dir/"candidate_predictions.csv.gz");features=pd.read_csv(snapshot_dir/"feature_snapshot.csv.gz")
    if len(predictions)!=len(features):raise RuntimeError("PREDICTION_FEATURE_ROW_MISMATCH")
    stage3=str((repo/"Stage 3/stage3").resolve());sys.path.remove(stage3) if stage3 in sys.path else None;sys.path.insert(0,stage3)
    # Frozen stages use top-level helper module names. Select the Stage 3 helper
    # explicitly so an earlier Stage 2B import cannot contaminate resolution.
    sys.modules.pop("hashing",None)
    opportunity=_module("stage4a3_outcome_opportunity",repo/"Stage 3/stage3/opportunity_engine.py");labels=_module("stage4a3_outcome_labels",repo/"Stage 3/stage3/labels.py")
    stage221=_module("stage4a3_outcome_stage221",repo/"Stage 2.2.2 Final/stage2_2_1/Stock_Alert_Stage2_2_1_Reproducible_Benchmark.py");stage21=stage221.load_stage21_module(repo/"Stage 2.2.2 Final/baseline/stage2_1/Stock_Alert_Stage2_1_Optimized_15Y.py")
    config=json.loads((repo/"Stage 3/config/stage3_dataset_config.json").read_text());frozen_config=stage221.Stage22Config(test_start=config["test_start"],test_end=observation_through,pullback_entry_window=config["pullback_entry_window"],breakout_gap_limit=config["breakout_gap_limit"],slippage_bps=config["slippage_bps"],transaction_cost_bps=config["transaction_cost_bps"])
    events=[]
    for number,prediction in predictions.iterrows():
        feature=features.iloc[number].to_dict();row={**feature,**prediction.to_dict(),"Entry Low":feature["Entry Low"],"Entry High":feature["Entry High"],"Stop Loss":prediction["Initial Stop"],"Target 1":prediction["Original T1"],"Target 2":prediction["Original T2"]}
        bars=market_frames[str(row["Ticker"])].copy();bars.index=pd.to_datetime(bars.index);bars=bars.loc[bars.index<=pd.Timestamp(observation_through)]
        entry=opportunity.simulate_entry(row,bars,stage221,frozen_config,config);combined={**row,**entry};computed=labels.add_opportunity_labels(combined,bars,config)
        required_entry_sessions=1 if str(row["Setup"])=="BREAKOUT" else int(config["pullback_entry_window"])
        observed_entry_sessions=sum(pd.Timestamp(value).normalize()>pd.Timestamp(row["Signal Date"]).normalize() for value in bars.index)
        # Stage 3's historical builder always had the full entry window available.
        # A live resolver must not reinterpret a partial future window as expiry.
        entry_terminal=(entry["ENTRY_STATUS"] in {"FILLED","INVALID_RISK"} or (entry["ENTRY_STATUS"]=="EXPIRED" and observed_entry_sessions>=required_entry_sessions)) and pd.notna(entry["ENTRY_LABEL_AVAILABLE_DATE"])
        if entry_terminal:events.append({"Generated UTC":generated_utc,"Signal ID":row["Signal ID"],"Signal Date":row["Signal Date"],"Ticker":row["Ticker"],"Policy":"","Outcome Type":"ENTRY_FILLED","Outcome State":entry["ENTRY_STATUS"],"Outcome Value":bool(entry["ENTRY_FILLED"]),"Observation Through Date":observation_through,"Label Available Date":pd.Timestamp(entry["ENTRY_LABEL_AVAILABLE_DATE"]).date().isoformat(),"Source Market Data Hash":source_market_hash,"Is Terminal":True})
        if bool(entry.get("ENTRY_FILLED")):
            for short,outcome_type in (("T1","T1_BEFORE_STOP_63"),("T2","T2_BEFORE_STOP_63")):
                if not bool(computed[f"{short}_CENSORED"]):events.append({"Generated UTC":generated_utc,"Signal ID":row["Signal ID"],"Signal Date":row["Signal Date"],"Ticker":row["Ticker"],"Policy":"","Outcome Type":outcome_type,"Outcome State":computed[f"{short}_LABEL_OUTCOME"],"Outcome Value":bool(computed[f"{short}_BEFORE_STOP_63"]),"Observation Through Date":observation_through,"Label Available Date":pd.Timestamp(computed[f"{short}_LABEL_AVAILABLE_DATE"]).date().isoformat(),"Source Market Data Hash":source_market_hash,"Is Terminal":True})
    return events


def run_frozen_portfolio_results(repo:Path,predictions:pd.DataFrame,feature_rows:pd.DataFrame,raw_market_frames:Mapping[str,pd.DataFrame],observation_through:str,include_random_controls:bool=False,include_d0:bool=True,policies:list[str]|None=None,evaluation_start:str|None=None,random_seeds:range|list[int]|None=None)->dict[str,dict[str,Any]]:
    """One authoritative Stage 2B.1/Stage 2.2.2 execution path for outcomes and final economics."""
    if len(predictions)!=len(feature_rows):raise RuntimeError("PREDICTION_FEATURE_ROW_MISMATCH")
    stage2b1_path=str((repo/"Stage 2B.1/stage2b").resolve());sys.path.remove(stage2b1_path) if stage2b1_path in sys.path else None;sys.path.insert(0,stage2b1_path)
    for helper in ("hashing","validation","policies","calibration","diagnostics"):sys.modules.pop(helper,None)
    module=_module("stage4a3_exact_stage2b1",repo/"Stage 2B.1/stage2b/Stock_Alert_Stage2B_1_Dynamic_Management.py")
    baseline_root=repo/"Stage 2.2.2 Final"
    module.PATHS={"stage21":baseline_root/"baseline/stage2_1/Stock_Alert_Stage2_1_Optimized_15Y.py","stage221":baseline_root/"stage2_2_1/Stock_Alert_Stage2_2_1_Reproducible_Benchmark.py","stage222":baseline_root/"stage2_2_2/Stock_Alert_Stage2_2_2_Final_Baseline.py","frozen":baseline_root/"stage2_2_1/data/frozen","baseline_root":baseline_root}
    baseline,stage21=module.load_baseline();policy_values=json.loads((repo/"Stage 2B.1/config/stage2b_1_policy_config.json").read_text());policy_config=module.PolicyConfig.from_mapping(policy_values)
    tickers=sorted(set(predictions["Ticker"].astype(str)));start=evaluation_start or pd.to_datetime(predictions["Signal Date"]).min().date().isoformat();cfg=baseline.Stage22Config(test_start=start,test_end=observation_through,starting_equity=100000.,risk_per_trade=.0075,max_position_pct=.25,max_open_positions=5,slippage_bps=5.,transaction_cost_bps=5.)
    engine=baseline.CandidateSignalEngine(stage21,cfg,tickers);engine.engine.raw_data={name:stage21.normalize_index(frame.copy()) for name,frame in raw_market_frames.items()};engine.precompute()
    combined=pd.concat([predictions.reset_index(drop=True),feature_rows.reset_index(drop=True)],axis=1);combined=combined.loc[:,~combined.columns.duplicated()].copy()
    combined["Stop Loss"]=combined["Initial Stop"];combined["Target 1"]=combined["Original T1"];combined["Target 2"]=combined["Original T2"]
    named=[f"R{r}_K{k}" for r in range(6) for k in (1,2)]
    selected_policies=named if policies is None else policies
    truth=lambda values:values.astype(str).str.strip().str.lower().isin({"true","1","yes"})
    selections={name:set(combined.loc[truth(combined[name+" Selected"]),"Signal ID"].astype(str)) for name in named if name in selected_policies}
    if include_random_controls:
        for seed in (range(500) if random_seeds is None else random_seeds):
            ids=[]
            for _,group in combined.groupby("Signal Date"):ids.append(min(group["Signal ID"].astype(str),key=lambda value:random_key(seed,value)))
            selections[f"RANDOM_K1_SEED_{seed:03d}"]=set(ids)
    # Rebuild the exact past-only annual calibration table used by frozen
    # Stage 2B.1.  An empty/default calibration would change D1 behavior.
    candidate_parts=sorted((baseline_root/"stage2_2_2/results").glob("stage2_2_2_final_candidate_signal_log.csv.gz.part*"))
    if not candidate_parts:raise RuntimeError("FROZEN_STAGE2B1_CANDIDATES_MISSING")
    # The accepted artifact is byte-split, not a set of independent gzip files.
    historical=pd.read_csv(io.BytesIO(b"".join(path.read_bytes() for path in candidate_parts)),compression="gzip",low_memory=False)
    historical["Signal Date"]=pd.to_datetime(historical["Signal Date"]).dt.normalize()
    calibration_candidates=pd.concat([historical,combined],ignore_index=True,sort=False)
    if "Signal ID" in calibration_candidates:calibration_candidates=calibration_candidates.drop_duplicates("Signal ID",keep="last")
    available_dates=sorted({pd.Timestamp(date).normalize() for frame in engine.engine.features.values() for date in frame.index})
    years=range(pd.Timestamp(start).year,pd.Timestamp(observation_through).year+1)
    first_sessions={year:min(date for date in available_dates if date.year==year) for year in years if any(date.year==year for date in available_dates)}
    _,calibration_tables=module.candidate_calibration(baseline,cfg,engine.engine.features,calibration_candidates,first_sessions)
    dynamic=module.DynamicBacktester.build(baseline);results:dict[str,dict[str,Any]]={}
    for policy,ids in selections.items():
        candidates=combined.loc[combined["Signal ID"].astype(str).isin(ids)].copy()
        bt=dynamic(cfg,engine.engine.features,candidates,"D1_TRAIL_ONLY","Target 2",63,policy="D1_TRAIL_ONLY",calibration_tables=calibration_tables,policy_config=policy_config,current_regime=engine.engine.market_history["MarketRegime"]);result=bt.run()
        if result["runtime_errors"]:raise RuntimeError(f"FROZEN_D1_RUNTIME_ERRORS: {result['runtime_errors']}")
        results[policy]={"D1":result,"membership":candidates}
        if include_d0 and policy in {f"R{r}_K{k}" for r in range(6) for k in (1,2)}:
            results[policy]["D0"]=baseline.PortfolioBacktester(cfg,engine.engine.features,candidates,"T2_63D","Target 2",63).run()
    return results


def compute_frozen_d1_policy_events(repo:Path,predictions:pd.DataFrame,feature_rows:pd.DataFrame,raw_market_frames:Mapping[str,pd.DataFrame],observation_through:str,generated_utc:str,source_market_hash:str,include_random_controls:bool=False,include_d0:bool=True,policies:list[str]|None=None)->list[dict[str,Any]]:
    """Derive immutable terminal events from the common frozen portfolio execution."""
    results=run_frozen_portfolio_results(repo,predictions,feature_rows,raw_market_frames,observation_through,include_random_controls,include_d0,policies);events=[]
    combined=pd.concat([predictions.reset_index(drop=True),feature_rows.reset_index(drop=True)],axis=1);combined=combined.loc[:,~combined.columns.duplicated()]
    for policy,engines in results.items():
        trades=engines["D1"]["trades"]
        for _,trade in trades.loc[~trades["Exit Reason"].eq("END_OF_DATA")].iterrows():
            value={"Net R":float(trade["R Multiple"]),"Net PnL":float(trade["Net PnL"]),"Portfolio Return Fraction":float(trade["Net PnL"])/float(trade["Portfolio Equity At Entry"]),"Exit Reason":trade["Exit Reason"],"Bars Held":int(trade["Bars Held"])}
            events.append({"Generated UTC":generated_utc,"Signal ID":trade["Signal ID"],"Signal Date":pd.Timestamp(trade["Signal Date"]).date().isoformat(),"Ticker":trade["Ticker"],"Policy":policy,"Outcome Type":"D1_TRADE_COMPLETION","Outcome State":"COMPLETED","Outcome Value":json.dumps(value,sort_keys=True,separators=(",",":")),"Observation Through Date":observation_through,"Label Available Date":pd.Timestamp(trade["Exit Date"]).date().isoformat(),"Source Market Data Hash":source_market_hash,"Is Terminal":True})
        if "D0" in engines:
            static=engines["D0"]
            for _,trade in static["trades"].loc[~static["trades"]["Exit Reason"].eq("END_OF_DATA")].iterrows():
                value={"Net R":float(trade["R Multiple"]),"Net PnL":float(trade["Net PnL"]),"Portfolio Return Fraction":float(trade["Net PnL"])/float(trade.get("Portfolio Equity At Entry",100000.)),"Exit Reason":trade["Exit Reason"],"Bars Held":int(trade["Bars Held"])}
                events.append({"Generated UTC":generated_utc,"Signal ID":trade.get("Signal ID",combined.loc[(combined["Ticker"]==trade["Ticker"])&(pd.to_datetime(combined["Signal Date"])==pd.Timestamp(trade["Signal Date"])),"Signal ID"].iloc[0]),"Signal Date":pd.Timestamp(trade["Signal Date"]).date().isoformat(),"Ticker":trade["Ticker"],"Policy":policy+"_D0","Outcome Type":"D1_TRADE_COMPLETION","Outcome State":"COMPLETED","Outcome Value":json.dumps(value,sort_keys=True,separators=(",",":")),"Observation Through Date":observation_through,"Label Available Date":pd.Timestamp(trade["Exit Date"]).date().isoformat(),"Source Market Data Hash":source_market_hash,"Is Terminal":True})
    return events
