from __future__ import annotations

import argparse
import json
from datetime import datetime,timezone
from pathlib import Path

import pandas as pd

from .hashing import canonical_json_hash,dataframe_content_hash
from .ledger_counts import prediction_rows
from .outcome_resolver import append_event_batch,compute_frozen_d1_policy_events,compute_frozen_label_events,load_all_events
from .protocol_integrity import verify_runtime_protocol_integrity


def _load_market_frames(root:Path,manifest_path:Path,observation_through:str)->tuple[dict[str,pd.DataFrame],str]:
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"));frames={};actual={}
    for path in sorted(root.glob("*.csv")):
        frame=pd.read_csv(path);date_column="Date" if "Date" in frame else frame.columns[0]
        frame[date_column]=pd.to_datetime(frame[date_column]);frame=frame.set_index(date_column).sort_index();frame.index.name="Date"
        frame=frame.loc[frame.index<=pd.Timestamp(observation_through)].copy();ticker="^NSEI" if path.stem=="INDEX_NSEI" else path.stem;frames[ticker]=frame;actual[ticker]=dataframe_content_hash(frame.reset_index())
    if not frames or "^NSEI" not in frames:raise RuntimeError("OUTCOME_MARKET_DATA_INCOMPLETE")
    expected=manifest.get("Per-Ticker Raw Hashes Through Observation")
    if expected!=actual:raise RuntimeError("OUTCOME_MARKET_DATA_HASH_MISMATCH")
    logical=canonical_json_hash(actual)
    if manifest.get("Raw Market Data Hash Through Observation")!=logical or manifest.get("Observation Through Date")!=observation_through:raise RuntimeError("OUTCOME_MARKET_MANIFEST_MISMATCH")
    return frames,logical


def _snapshot_parts(stage_root:Path,observation_through:str)->list[tuple[pd.DataFrame,pd.DataFrame,Path]]:
    index=pd.read_csv(stage_root/"prospective/audit/prospective_snapshot_index.csv",dtype=str);parts=[]
    for date in index.loc[pd.to_datetime(index["Signal Date"])<=pd.Timestamp(observation_through),"Signal Date"]:
        directory=stage_root/"prospective/snapshots"/date[:4]/date
        parts.append((pd.read_csv(directory/"candidate_predictions.csv.gz",low_memory=False),pd.read_csv(directory/"feature_snapshot.csv.gz",low_memory=False),directory))
    return parts


def run(repo:Path,observation_through:str,market_root:Path,market_manifest:Path,include_random_controls:bool=False)->dict:
    stage_root=repo/"Stage 4A.3";activation=json.loads((stage_root/"prospective/audit/activation_record.json").read_text(encoding="utf-8"));verify_runtime_protocol_integrity(repo,stage_root,activation)
    frames,source_hash=_load_market_frames(market_root,market_manifest,observation_through);generated=datetime.now(timezone.utc).isoformat();events=[];parts=_snapshot_parts(stage_root,observation_through)
    for _,_,directory in parts:events.extend(compute_frozen_label_events(repo,directory,frames,observation_through,generated,source_hash))
    if parts:
        predictions=pd.concat([item[0] for item in parts],ignore_index=True);features=pd.concat([item[1] for item in parts],ignore_index=True)
        events.extend(compute_frozen_d1_policy_events(repo,predictions,features,frames,observation_through,generated,source_hash,include_random_controls=include_random_controls,include_d0=True))
    existing=load_all_events(stage_root/"prospective/outcomes");keys={(str(r["Signal ID"]),str(r.get("Policy","")),str(r["Outcome Type"])) for _,r in existing.iterrows()}
    new=[event for event in events if (str(event["Signal ID"]),str(event.get("Policy","")),str(event["Outcome Type"])) not in keys]
    if not new:return {"Outcome Events Appended":0,"Observation Through Date":observation_through,"Status":"NO_NEW_TERMINAL_OUTCOMES"}
    path=append_event_batch(stage_root/"prospective/outcomes",new,generated,stage_root/"prospective/audit",activation["Protocol Identity"])
    return {"Outcome Events Appended":len(new),"Observation Through Date":observation_through,"Batch":path.relative_to(stage_root).as_posix(),"Status":"APPENDED"}


def main()->None:
    parser=argparse.ArgumentParser(description="Compute frozen Stage 3.1 and Stage 2B.1 outcomes from immutable snapshots and hashed future EOD bars")
    parser.add_argument("--repo-root",type=Path,required=True);parser.add_argument("--observation-through",required=True);parser.add_argument("--market-root",type=Path,required=True);parser.add_argument("--market-manifest",type=Path,required=True);parser.add_argument("--include-random-controls",action="store_true")
    args=parser.parse_args();print(json.dumps(run(args.repo_root.resolve(),args.observation_through,args.market_root.resolve(),args.market_manifest.resolve(),args.include_random_controls),indent=2))


if __name__=="__main__":main()
