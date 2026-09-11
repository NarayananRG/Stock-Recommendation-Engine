from __future__ import annotations

import hashlib
from typing import Iterable

import pandas as pd


def genesis_hash(protocol_tag_commit: str, model_bundle_hash: str) -> str:
    return hashlib.sha256((protocol_tag_commit+model_bundle_hash+"STAGE4A3_GENESIS").encode("utf-8")).hexdigest()


def current_chain_hash(previous_chain_hash: str, signal_date: str, snapshot_content_hash: str, protocol_commit: str, model_bundle_hash: str) -> str:
    return hashlib.sha256((previous_chain_hash+signal_date+snapshot_content_hash+protocol_commit+model_bundle_hash).encode("utf-8")).hexdigest()


def verify_index(index: pd.DataFrame, protocol_commit: str, model_bundle_hash: str, genesis: str) -> bool:
    if index.empty:
        return True
    ordered=index.sort_values("Sequence",kind="mergesort").reset_index(drop=True)
    if pd.to_numeric(ordered["Sequence"],errors="coerce").tolist()!=list(range(1,len(ordered)+1)) or ordered["Signal Date"].duplicated().any() or not pd.to_datetime(ordered["Signal Date"]).is_monotonic_increasing:
        return False
    previous=genesis
    for _,row in ordered.iterrows():
        if row["Previous Chain Hash"]!=previous:
            return False
        expected=current_chain_hash(previous,str(row["Signal Date"]),row["Snapshot Content Hash"],protocol_commit,model_bundle_hash)
        if row["Current Chain Hash"]!=expected:
            return False
        previous=expected
    return True
