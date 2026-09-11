from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .hash_chain import current_chain_hash, verify_index
from .hashing import sha256_file
from .snapshot_contract import snapshot_content_hash, validate_candidate_predictions


INDEX_COLUMNS=["Sequence","Signal Date","Snapshot ID","Created UTC","Candidate Count","Snapshot Content Hash","Previous Chain Hash","Current Chain Hash","Git Commit if available","Status"]
BREACH_COLUMNS=["UTC Time","Breach Type","Details","Blocked / Allowed","Affected Signal Date","Protocol Hash"]


def _json(value: Any, path: Path) -> None:
    path.write_text(json.dumps(value,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8",newline="\n")


def _csv_gz(frame: pd.DataFrame, path: Path) -> None:
    payload=frame.to_csv(index=False,lineterminator="\n",date_format="%Y-%m-%d",float_format="%.17g").encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as zipped:
            zipped.write(payload)


def record_breach(audit_root: Path, event: dict[str, Any]) -> None:
    path=audit_root/"protocol_breaches.csv";existing=pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame(columns=BREACH_COLUMNS)
    pd.concat([existing,pd.DataFrame([event],columns=BREACH_COLUMNS)],ignore_index=True).to_csv(path,index=False,lineterminator="\n")


def write_snapshot(snapshot_root: Path, audit_root: Path, signal_date: str, metadata: dict[str,Any], predictions: pd.DataFrame, features: pd.DataFrame, market_manifest: dict[str,Any], previous_chain_hash: str, protocol_commit: str, model_bundle_hash: str, git_commit: str="") -> dict[str,Any]:
    validate_candidate_predictions(predictions)
    target=snapshot_root/signal_date[:4]/signal_date
    if target.exists():
        raise FileExistsError("SNAPSHOT_ALREADY_EXISTS_IMMUTABLE")
    index_path=audit_root/"prospective_snapshot_index.csv"
    index=pd.read_csv(index_path,dtype=str) if index_path.exists() and index_path.stat().st_size else pd.DataFrame(columns=INDEX_COLUMNS)
    if signal_date in set(index.get("Signal Date",pd.Series(dtype=str)).astype(str)):
        raise RuntimeError("DUPLICATE_SIGNAL_DATE")
    if not index.empty and signal_date<=str(index.iloc[-1]["Signal Date"]):
        raise RuntimeError("OUT_OF_ORDER_SNAPSHOT")
    content_hash=snapshot_content_hash(metadata,predictions,features,market_manifest)
    chain=current_chain_hash(previous_chain_hash,signal_date,content_hash,protocol_commit,model_bundle_hash)
    target.mkdir(parents=True,exist_ok=False)
    _json(metadata,target/"snapshot_metadata.json");_csv_gz(predictions,target/"candidate_predictions.csv.gz");_csv_gz(features,target/"feature_snapshot.csv.gz");_json(market_manifest,target/"market_data_manifest.json")
    files=["snapshot_metadata.json","candidate_predictions.csv.gz","feature_snapshot.csv.gz","market_data_manifest.json"]
    manifest={"Snapshot Content Hash":content_hash,"files":[{"file":name,"sha256":sha256_file(target/name),"bytes":(target/name).stat().st_size} for name in files]};_json(manifest,target/"snapshot_manifest.json")
    chain_record={"Previous Chain Hash":previous_chain_hash,"Current Chain Hash":chain,"Signal Date":signal_date,"Snapshot Content Hash":content_hash,"Protocol Commit":protocol_commit,"Model Bundle Hash":model_bundle_hash};_json(chain_record,target/"hash_chain.json")
    row={"Sequence":len(index)+1,"Signal Date":signal_date,"Snapshot ID":metadata["Snapshot ID"],"Created UTC":metadata["Snapshot Created UTC"],"Candidate Count":len(predictions),"Snapshot Content Hash":content_hash,"Previous Chain Hash":previous_chain_hash,"Current Chain Hash":chain,"Git Commit if available":git_commit,"Status":"CAPTURED"}
    audit_root.mkdir(parents=True,exist_ok=True);pd.concat([index,pd.DataFrame([row])],ignore_index=True).to_csv(index_path,index=False,lineterminator="\n")
    return row


def verify_snapshot_files(snapshot_dir: Path) -> bool:
    manifest=json.loads((snapshot_dir/"snapshot_manifest.json").read_text(encoding="utf-8"))
    return all((snapshot_dir/item["file"]).is_file() and sha256_file(snapshot_dir/item["file"])==item["sha256"] for item in manifest["files"])


def verify_ledger(snapshot_root: Path, audit_root: Path, protocol_commit: str, model_bundle_hash: str, genesis: str) -> bool:
    index_path=audit_root/"prospective_snapshot_index.csv"
    if not index_path.exists():
        return not any(snapshot_root.glob("*/*/snapshot_manifest.json"))
    index=pd.read_csv(index_path,dtype=str)
    if not verify_index(index,protocol_commit,model_bundle_hash,genesis):
        return False
    indexed=set(index["Signal Date"].astype(str))
    present={path.parent.name for path in snapshot_root.glob("*/*/snapshot_manifest.json")}
    if indexed!=present:
        return False
    for _,row in index.iterrows():
        directory=snapshot_root/str(row["Signal Date"])[:4]/str(row["Signal Date"])
        if not verify_snapshot_files(directory):
            return False
        manifest=json.loads((directory/"snapshot_manifest.json").read_text(encoding="utf-8"))
        if manifest["Snapshot Content Hash"]!=row["Snapshot Content Hash"]:
            return False
    return True
