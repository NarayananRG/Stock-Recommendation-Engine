from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .hashing import canonical_json_hash, dataframe_content_hash, sha256_file


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def archive_market_frames(frames: Mapping[str, pd.DataFrame], archive_root: Path,
                          as_of_date: str, provider: str,
                          downloaded_utc: str) -> dict[str, Any]:
    """Create the immutable final-analysis OHLC archive from provider frames."""
    if archive_root.exists():
        raise FileExistsError("FINAL_MARKET_DATA_ARCHIVE_ALREADY_EXISTS_IMMUTABLE")
    archive_root.mkdir(parents=True, exist_ok=False)
    rows = []
    logical = {}
    for ticker, source in sorted(frames.items()):
        frame = source.copy().sort_index()
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        frame = frame.loc[frame.index <= pd.Timestamp(as_of_date)]
        if frame.empty:
            raise RuntimeError(f"FINAL_MARKET_DATA_EMPTY: {ticker}")
        normalized = frame.reset_index().rename(columns={frame.index.name or "index": "Date"})
        logical[ticker] = dataframe_content_hash(normalized)
        name = "INDEX_NSEI.csv.gz" if ticker == "^NSEI" else f"{ticker}.csv.gz"
        target = archive_root / name
        payload = normalized.to_csv(index=False, lineterminator="\n", date_format="%Y-%m-%d", float_format="%.17g").encode()
        with target.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                zipped.write(payload)
        rows.append({"Ticker": ticker, "File": name, "Logical Hash": logical[ticker], "SHA256": sha256_file(target), "Rows": len(frame), "Minimum Date": frame.index.min().date().isoformat(), "Maximum Date": frame.index.max().date().isoformat()})
    manifest = {"schema":"STAGE4A3_FINAL_MARKET_DATA_V1","provider":provider,"downloaded_utc":downloaded_utc,"as_of_date":as_of_date,"files":rows,"per_ticker_logical_hashes":logical,"overall_logical_hash":canonical_json_hash(logical),"immutable":True,"provider_revision_risk":"Daily provider history may be revised; archived bytes are authoritative for this analysis."}
    (archive_root.parent / "stage4a3_final_market_data_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
    return manifest


def verify_and_load_archive(archive_root: Path, manifest_path: Path) -> dict[str, pd.DataFrame]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames: dict[str, pd.DataFrame] = {}
    logical: dict[str, str] = {}
    for item in manifest["files"]:
        path = archive_root / item["File"]
        if not path.exists() or sha256_file(path) != item["SHA256"]:
            raise RuntimeError("FINAL_MARKET_DATA_ARCHIVE_TAMPERED")
        frame = pd.read_csv(path, compression="gzip")
        if dataframe_content_hash(frame) != item["Logical Hash"]:
            raise RuntimeError("FINAL_MARKET_DATA_LOGICAL_HASH_MISMATCH")
        frame["Date"] = pd.to_datetime(frame["Date"])
        frames[item["Ticker"]] = frame.set_index("Date")
        logical[item["Ticker"]] = item["Logical Hash"]
    if canonical_json_hash(logical) != manifest["overall_logical_hash"]:
        raise RuntimeError("FINAL_MARKET_DATA_OVERALL_HASH_MISMATCH")
    return frames


def acquire_and_archive(repo: Path, stage_root: Path, as_of_date: str,
                        archive_parent: Path, downloaded_utc: str) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Use frozen Stage 2.2.1 ingestion; no operator-supplied return arrays exist."""
    stage221 = _module("stage4a3_final_stage221", repo/"Stage 2.2.2 Final/stage2_2_1/Stock_Alert_Stage2_2_1_Reproducible_Benchmark.py")
    stage21 = stage221.load_stage21_module(repo/"Stage 2.2.2 Final/baseline/stage2_1/Stock_Alert_Stage2_1_Optimized_15Y.py")
    dataset_config = json.loads((repo/"Stage 3/config/stage3_dataset_config.json").read_text(encoding="utf-8"))
    tickers = pd.read_csv(stage_root/"prospective_universe.csv")["Ticker"].astype(str).tolist()
    scratch = archive_parent/"provider_download_cache"
    cfg = stage221.Stage22Config(test_start=dataset_config["test_start"],test_end=as_of_date,warmup_anchor_start=dataset_config["test_start"],cache_directory=scratch,frozen_data_directory=scratch,data_mode="REFRESH")
    engine = stage221.CandidateSignalEngine(stage21,cfg,tickers);engine.load_data()
    expected = set(tickers)|{"^NSEI"}
    if set(engine.engine.raw_data) != expected:
        raise RuntimeError("FINAL_MARKET_DATA_UNIVERSE_INCOMPLETE")
    archive = archive_parent/"final_market_data"
    manifest = archive_market_frames(engine.engine.raw_data,archive,as_of_date,"YFINANCE_REFRESH_VIA_FROZEN_STAGE2_2_1",downloaded_utc)
    return verify_and_load_archive(archive,archive_parent/"stage4a3_final_market_data_manifest.json"),manifest
