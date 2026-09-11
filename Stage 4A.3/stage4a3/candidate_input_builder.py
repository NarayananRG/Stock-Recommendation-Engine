from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pandas as pd

from .hashing import canonical_json_hash, dataframe_content_hash, sha256_file


BUILDER_FILES=(
    "Stage 2.2.2 Final/baseline/stage2_1/Stock_Alert_Stage2_1_Optimized_15Y.py",
    "Stage 2.2.2 Final/stage2_2_1/Stock_Alert_Stage2_2_1_Reproducible_Benchmark.py",
    "Stage 2.2.2 Final/stage2_2_2/Stock_Alert_Stage2_2_2_Final_Baseline.py",
    "Stage 3/stage3/features.py",
    "Stage 3/stage3/opportunity_engine.py",
    "Stage 3/config/stage3_dataset_config.json",
)


def _module(name: str,path: Path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise ImportError(path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


def builder_identity(repo: Path) -> str:
    return canonical_json_hash([{"path":name,"sha256":sha256_file(repo/name)} for name in BUILDER_FILES])


def _raw_hashes(raw: dict[str,pd.DataFrame]) -> tuple[str,str,dict[str,str]]:
    hashes={ticker:dataframe_content_hash(frame.reset_index()) for ticker,frame in sorted(raw.items())}
    return canonical_json_hash(hashes),hashes.get("^NSEI","MISSING"),hashes


def build_signal_close_input(repo: Path, requested_date: str | None, scratch_root: Path, data_mode: str="REFRESH") -> tuple[pd.DataFrame,dict[str,Any],dict[str,Any]]:
    """Run the exact frozen strategy and Stage 3 signal-time feature functions; never compute future labels."""
    config=json.loads((repo/"Stage 3/config/stage3_dataset_config.json").read_text(encoding="utf-8"))
    if data_mode=="FROZEN" and "yfinance" not in sys.modules:
        stub=types.ModuleType("yfinance");stub.__version__="FROZEN_NO_NETWORK";stub.set_tz_cache_location=lambda *a,**k:None;stub.download=lambda *a,**k:(_ for _ in ()).throw(RuntimeError("Network disabled in frozen parity mode"));sys.modules["yfinance"]=stub
    universe=pd.read_csv(repo/"Stage 4A.3/prospective_universe.csv");tickers=universe["Ticker"].astype(str).tolist()
    stage221=_module("stage4a3_frozen_stage221",repo/BUILDER_FILES[1]);stage21=stage221.load_stage21_module(repo/BUILDER_FILES[0])
    end=requested_date or pd.Timestamp.now(tz="Asia/Kolkata").date().isoformat()
    data_root=repo/config["source_paths"]["frozen_data"] if data_mode=="FROZEN" else scratch_root/"raw_market_data"
    engine_config=stage221.Stage22Config(test_start=end,test_end=end,warmup_anchor_start=config["test_start"],holding_periods=tuple(config["forward_horizons"]),slippage_bps=float(config["slippage_bps"]),transaction_cost_bps=float(config["transaction_cost_bps"]),pullback_entry_window=int(config["pullback_entry_window"]),breakout_gap_limit=float(config["breakout_gap_limit"]),cache_directory=data_root,frozen_data_directory=data_root,data_mode=data_mode)
    engine=stage221.CandidateSignalEngine(stage21,engine_config,tickers);engine.load_data();engine.precompute()
    raw_maxima={ticker:pd.Timestamp(frame.index.max()).date().isoformat() for ticker,frame in engine.engine.raw_data.items() if not frame.empty}
    if "^NSEI" not in raw_maxima: raise RuntimeError("DATA_NOT_READY: NIFTY_MISSING")
    stock_dates={value for key,value in raw_maxima.items() if key!="^NSEI"}
    if len(stock_dates)!=1 or raw_maxima["^NSEI"] not in stock_dates: raise RuntimeError("DATA_NOT_READY: MARKET_DATES_NOT_ALIGNED")
    signal_date=raw_maxima["^NSEI"]
    if requested_date and signal_date!=requested_date: raise RuntimeError("DATA_NOT_READY: REQUESTED_SIGNAL_DATE_NOT_LATEST_BAR")
    signals=engine.generate();stage222=_module("stage4a3_frozen_stage222",repo/BUILDER_FILES[2]);signals=stage222.add_signal_ids(signals)
    signals=signals.loc[pd.to_datetime(signals["Signal Date"]).dt.strftime("%Y-%m-%d").eq(signal_date)].copy() if not signals.empty else signals
    stage3_path=str((repo/"Stage 3/stage3").resolve())
    if stage3_path not in sys.path:sys.path.insert(0,stage3_path)
    features_module=_module("stage4a3_frozen_stage3_features",repo/BUILDER_FILES[3]);opportunity_module=_module("stage4a3_frozen_stage3_opportunity",repo/BUILDER_FILES[4])
    stock_features={ticker:features_module.enrich_stock_frame(frame) for ticker,frame in engine.engine.features.items()}
    market_features=features_module.enrich_market_frame(engine.engine.market_history,engine.engine.raw_data["^NSEI"],engine.engine.feature_engine)
    if signals.empty:
        enriched=pd.DataFrame(columns=["Signal ID","Ticker","Signal Date","Dataset Cohort"])
    else:
        enriched=features_module.build_signal_state_dataset(signals,stock_features,market_features,config,"STAGE4A3_PROSPECTIVE_INPUT")
        cohort=[]
        for row in enriched.to_dict("records"):
            eligible,name,_=opportunity_module.opportunity_eligibility(row,config);cohort.append(name if eligible else "NOT_ELIGIBLE")
        enriched["Dataset Cohort"]=cohort;enriched=enriched.loc[enriched["Dataset Cohort"].eq("BASELINE_PRIMARY")].reset_index(drop=True)
    raw_hash,nifty_hash,per_ticker=_raw_hashes(engine.engine.raw_data)
    feature_contract=json.loads((repo/"Stage 4A.3/models/frozen_2026/model_bundle_manifest.json").read_text())
    contract_hash=canonical_json_hash({m["feature_set"]:m["feature_hash"] for m in feature_contract["models"]})
    signal_ids=enriched[["Signal ID"]].sort_values("Signal ID").reset_index(drop=True) if len(enriched) else pd.DataFrame(columns=["Signal ID"])
    manifest={"Signal Date":signal_date,"Frozen Universe Hash":dataframe_content_hash(universe),"Raw Market Data Hash":raw_hash,"NIFTY Data Hash":nifty_hash,"Frozen Strategy/Feature Builder Identity":builder_identity(repo),"Feature Contract Hash":contract_hash,"Candidate Count":len(enriched),"Candidate Signal-ID Logical Hash":dataframe_content_hash(signal_ids),"Full Input Logical Hash":dataframe_content_hash(enriched),"Data Mode":data_mode,"Per-Ticker Raw Hashes":per_ticker}
    received={key for key in engine.engine.raw_data if key!="^NSEI"}
    market_manifest={"provider_identifier":"FROZEN_YFINANCE_INGESTION" if data_mode=="FROZEN" else "YFINANCE_REFRESH_VIA_FROZEN_STAGE2_2_1","download_timestamp_utc":pd.Timestamp.now(tz="UTC").isoformat() if data_mode=="REFRESH" else "HISTORICAL_TEST_FIXTURE","maximum_market_data_date":signal_date,"nifty_maximum_date":signal_date,"ticker_count_requested":len(tickers),"ticker_count_received":len(received),"missing_tickers":sorted(set(tickers)-received),"raw_data_logical_hash":raw_hash}
    return enriched,manifest,market_manifest


def verify_candidate_input(frame: pd.DataFrame, manifest: dict[str,Any], frozen_universe_hash: str) -> None:
    if manifest["Frozen Universe Hash"]!=frozen_universe_hash or manifest["Candidate Count"]!=len(frame):raise RuntimeError("CANDIDATE_INPUT_PROVENANCE_MISMATCH")
    ids=frame[["Signal ID"]].sort_values("Signal ID").reset_index(drop=True) if len(frame) else pd.DataFrame(columns=["Signal ID"])
    if manifest["Candidate Signal-ID Logical Hash"]!=dataframe_content_hash(ids) or manifest["Full Input Logical Hash"]!=dataframe_content_hash(frame):raise RuntimeError("CANDIDATE_INPUT_PROVENANCE_MISMATCH")
