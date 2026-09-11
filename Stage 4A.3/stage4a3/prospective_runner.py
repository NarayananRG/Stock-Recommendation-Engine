from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import pandas as pd

from .candidate_selection import rank_and_select
from .candidate_input_builder import build_signal_close_input, verify_candidate_input
from .activation import signal_is_after_activation
from .feature_snapshot import add_feature_hashes, validate_feature_contract
from .hash_chain import genesis_hash
from .immutable_ledger import record_breach, write_snapshot
from .market_data_adapter import validate_capture_window
from .model_scoring import score_candidates, verify_bundle
from .protocol_integrity import verify_runtime_protocol_integrity
from .snapshot_contract import PREDICTION_COLUMNS
from .hashing import canonical_json_hash, dataframe_content_hash


def parser() -> argparse.ArgumentParser:
    value=argparse.ArgumentParser(description="Frozen Stage 4A.3 shadow snapshot runner")
    value.add_argument("--repo-root",type=Path,required=True)
    value.add_argument("--input",type=Path,help="historical candidate/feature input; dry-run only")
    value.add_argument("--market-manifest",type=Path,help="historical market manifest; dry-run only")
    value.add_argument("--dry-run",action="store_true")
    value.add_argument("--as-of",help="historical date; accepted only with --dry-run")
    value.add_argument("--dry-run-root",type=Path,help="test-only output root below Stage 4A.3/tests")
    return value


def _git(repo: Path,*args: str) -> str:
    return subprocess.check_output(["git","-c",f"safe.directory={repo.as_posix()}",*args],cwd=repo,text=True).strip()


def _previous_chain(audit_root: Path, genesis: str) -> str:
    index=audit_root/"prospective_snapshot_index.csv"
    if not index.exists() or not index.stat().st_size:
        return genesis
    frame=pd.read_csv(index,dtype=str)
    return genesis if frame.empty else str(frame.iloc[-1]["Current Chain Hash"])


def _breach(root: Path,kind: str,details: str,signal_date: str,protocol_hash: str) -> None:
    record_breach(root/"prospective/audit",{"UTC Time":pd.Timestamp.now(tz="UTC").isoformat(),"Breach Type":kind,"Details":details,"Blocked / Allowed":"BLOCKED","Affected Signal Date":signal_date,"Protocol Hash":protocol_hash})


def run(repo: Path,input_path: Path|None,market_manifest_path: Path|None,dry_run: bool,as_of: str|None,now: datetime|None=None,dry_run_root: Path|None=None) -> dict:
    root=repo/"Stage 4A.3";config=json.loads((root/"config/stage4a3_protocol.json").read_text(encoding="utf-8"))
    if as_of and not dry_run:
        raise RuntimeError("PAST_DATE_PRODUCTION_MODE_PROHIBITED")
    if not dry_run and (input_path is not None or market_manifest_path is not None):
        raise RuntimeError("PRODUCTION_ARBITRARY_INPUT_PROHIBITED")
    if dry_run and (input_path is None or market_manifest_path is None or not as_of):
        raise RuntimeError("DRY_RUN_REQUIRES_INPUT_MARKET_MANIFEST_AND_AS_OF")
    if dry_run_root is not None and (not dry_run or not dry_run_root.resolve().is_relative_to((root/"tests").resolve())):
        raise RuntimeError("DRY_RUN_OUTPUT_MUST_STAY_UNDER_TESTS")
    activation_path=root/"prospective/audit/activation_record.json"
    if not dry_run and not activation_path.exists():
        raise RuntimeError("PROSPECTIVE_COLLECTION_NOT_ACTIVATED")
    current=now or (pd.Timestamp(f"{as_of} 16:00:00",tz="Asia/Kolkata").to_pydatetime() if dry_run and as_of else datetime.now(timezone.utc))
    activation=None
    if not dry_run:
        activation=json.loads(activation_path.read_text(encoding="utf-8"))
        try: verify_runtime_protocol_integrity(repo,root,activation)
        except Exception as exc:
            _breach(root,"PROTOCOL_DRIFT_ATTEMPT",str(exc),"",activation.get("Protocol Identity",""));raise
        scratch=root/"prospective/input_cache"/current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        frame,candidate_input_manifest,market_manifest=build_signal_close_input(repo,None,scratch,"REFRESH")
        signal_date=candidate_input_manifest["Signal Date"]
        if not signal_is_after_activation(activation,current.astimezone(timezone.utc).isoformat(),signal_date):
            _breach(root,"SIGNAL_DATE_NOT_PROSPECTIVE_AFTER_ACTIVATION","signal_date <= Activation Local Date",signal_date,activation["Protocol Identity"])
            raise RuntimeError("SIGNAL_DATE_NOT_PROSPECTIVE_AFTER_ACTIVATION")
        verify_candidate_input(frame,candidate_input_manifest,activation["Frozen Universe Hash"])
    else:
        signal_date=str(as_of);frame=pd.read_csv(input_path,low_memory=False);market_manifest=json.loads(market_manifest_path.read_text(encoding="utf-8"))
        universe=json.loads((root/"results/stage4a3_frozen_universe_hash.json").read_text(encoding="utf-8"))["FROZEN_UNIVERSE_HASH"]
        ids=frame[["Signal ID"]].sort_values("Signal ID").reset_index(drop=True) if len(frame) else pd.DataFrame(columns=["Signal ID"])
        candidate_input_manifest={"Signal Date":signal_date,"Frozen Universe Hash":universe,"Raw Market Data Hash":market_manifest["raw_data_logical_hash"],"NIFTY Data Hash":"HISTORICAL_TEST_FIXTURE","Frozen Strategy/Feature Builder Identity":"HISTORICAL_TEST_FIXTURE","Feature Contract Hash":"FROZEN_CONTRACT_TEST","Candidate Count":len(frame),"Candidate Signal-ID Logical Hash":dataframe_content_hash(ids),"Full Input Logical Hash":dataframe_content_hash(frame),"Fixture Semantics":"HISTORICAL_TEST_FIXTURE"}
    validate_capture_window(current,signal_date,market_manifest)
    frame=frame.loc[frame["Dataset Cohort"].eq("BASELINE_PRIMARY") & pd.to_datetime(frame["Signal Date"]).dt.strftime("%Y-%m-%d").eq(signal_date)].copy()
    manifests=verify_bundle(root/"models/frozen_2026")
    bundles={item["model_name"]:joblib.load(root/"models/frozen_2026"/f"{item['model_name']}.joblib") for item in manifests["models"]}
    feature_sets={"FS2_RAW_SIGNAL_STATE":bundles["PRIMARY_ONLY_T1_LOGIT_RAW"]["feature_names"],"FS3_FULL_SIGNAL_STATE":bundles["PRIMARY_ONLY_T1_LOGIT_FULL"]["feature_names"]}
    validate_feature_contract(feature_sets)
    feature_names=feature_sets["FS3_FULL_SIGNAL_STATE"]
    features=add_feature_hashes(frame[feature_names],feature_names) if len(frame) else pd.DataFrame(columns=feature_names+["Feature Row Hash"])
    features.insert(0,"Ticker",frame["Ticker"].reset_index(drop=True) if len(frame) else pd.Series(dtype="object"));features.insert(0,"Signal ID",frame["Signal ID"].reset_index(drop=True) if len(frame) else pd.Series(dtype="object"))
    if len(frame):
        scores,bundle_hash=score_candidates(frame,root/"models/frozen_2026")
        base=frame.reset_index(drop=True);scores=scores.reset_index(drop=True)
        ranked=rank_and_select(pd.concat([base,scores],axis=1))
    else:
        bundle_hash=manifests["FROZEN_PROSPECTIVE_MODEL_BUNDLE_HASH"]
        ranked=pd.DataFrame(columns=list(frame.columns)+[f"R{i} Score" for i in range(6)])
        for i in range(6):
            ranked[f"R{i} Same-Date Rank"]=pd.Series(dtype="int64");ranked[f"R{i}_K1 Selected"]=pd.Series(dtype="bool");ranked[f"R{i}_K2 Selected"]=pd.Series(dtype="bool")
    protocol_commit=_git(repo,"rev-parse","HEAD") if dry_run else json.loads((root/"prospective/audit/activation_record.json").read_text(encoding="utf-8"))["Protocol Commit"]
    created_utc=current.astimezone(timezone.utc).isoformat();created_ist=current.astimezone(ZoneInfo("Asia/Kolkata")).isoformat()
    common={"Protocol Version":config["protocol_version"],"Protocol Commit":protocol_commit,"Protocol Tag":config["protocol_tag"],"Signal Date":signal_date,"Snapshot Created UTC":created_utc,"Snapshot Created Asia/Kolkata":created_ist,"Model Bundle Hash":bundle_hash,"Prediction Semantics":"SHADOW_ONLY_NO_TRADING_EFFECT"}
    predictions=pd.DataFrame(index=ranked.index)
    mapping={"Signal ID":"Signal ID","Ticker":"Ticker","Original Signal":"Original Signal","Signal":"Signal","Setup":"Setup","Market Regime":"Market Regime","Trade Quality":"Trade Quality","Actionability Score":"Actionability Score","Technical Score":"Technical Score","Planned Entry":"Entry Low","Initial Stop":"Stop Loss","Original T1":"Target 1","Original T2":"Target 2","Dataset Cohort":"Dataset Cohort"}
    for target,source in mapping.items(): predictions[target]=ranked[source] if source in ranked else pd.Series(dtype="object")
    for i in range(6):
        for suffix in ("Score","Same-Date Rank","K1 Selected","K2 Selected"):
            name=f"R{i}_{suffix}" if suffix.startswith("K") else f"R{i} {suffix}"
            predictions[name]=ranked[name] if name in ranked else pd.Series(dtype="object")
    predictions["Feature Row Hash"]=features["Feature Row Hash"].reset_index(drop=True)
    for key,value in common.items(): predictions[key]=value
    provisional={"Signal Date":signal_date,"Created UTC":created_utc,"Candidate Count":len(predictions),"Fixture Semantics":"HISTORICAL_TEST_FIXTURE" if dry_run else "PROSPECTIVE","Candidate Input Manifest Hash":canonical_json_hash(candidate_input_manifest)}
    from .snapshot_contract import snapshot_content_hash
    content=snapshot_content_hash(provisional,predictions.reindex(columns=PREDICTION_COLUMNS),features,market_manifest,candidate_input_manifest)
    snapshot_id=f"S4A3_{signal_date.replace('-','')}_{content[:12]}";predictions["Snapshot ID"]=snapshot_id
    metadata={**provisional,"Snapshot ID":snapshot_id,"Snapshot Created UTC":created_utc}
    output=(dry_run_root.resolve() if dry_run_root else root/"tests/dry_run") if dry_run else root/"prospective"
    snapshots=output/"snapshots";audit=output/"audit"
    tag_commit=protocol_commit if dry_run else json.loads((root/"prospective/audit/activation_record.json").read_text(encoding="utf-8"))["Protocol Commit"]
    previous=_previous_chain(audit,genesis_hash(tag_commit,bundle_hash))
    row=write_snapshot(snapshots,audit,signal_date,metadata,predictions.reindex(columns=PREDICTION_COLUMNS),features,market_manifest,previous,protocol_commit,bundle_hash,candidate_input_manifest=candidate_input_manifest)
    return {**row,"Output Root":str(output),"Dry Run":dry_run}


def main() -> None:
    args=parser().parse_args();print(json.dumps(run(args.repo_root.resolve(),args.input.resolve() if args.input else None,args.market_manifest.resolve() if args.market_manifest else None,args.dry_run,args.as_of,dry_run_root=args.dry_run_root),indent=2,default=str))


if __name__=="__main__": main()
