from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd

from .hashing import canonical_json_hash
from .outcome_contract import OUTCOME_COLUMNS,OUTCOME_TYPES


def build_event(values: dict, prior_event_hash: str) -> dict:
    if values["Outcome Type"] not in OUTCOME_TYPES:
        raise ValueError("Unknown frozen outcome type")
    if pd.Timestamp(values["Label Available Date"])<pd.Timestamp(values["Signal Date"]):
        raise ValueError("LABEL_AVAILABILITY_BEFORE_SIGNAL")
    event={**values,"Prior Event Hash":prior_event_hash,"Frozen Rule Semantics Version":"STAGE3.1_STOP_FIRST_MAX63"}
    seed={key:value for key,value in event.items() if key not in {"Event ID","Event Hash"}}
    event.setdefault("Event ID","S4A3_OUTCOME_"+canonical_json_hash(seed)[:16])
    event["Event Hash"]=canonical_json_hash(event);return event


def append_events(outcome_root: Path, signal_date: str, events: list[dict]) -> Path:
    target=outcome_root/signal_date[:4]/f"{signal_date}_outcome_events.csv.gz"
    if target.exists():
        raise FileExistsError("OUTCOME_EVENT_FILE_IMMUTABLE")
    target.parent.mkdir(parents=True,exist_ok=True);frame=pd.DataFrame(events,columns=OUTCOME_COLUMNS);payload=frame.to_csv(index=False,lineterminator="\n").encode()
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as zipped:zipped.write(payload)
    return target


def verify_event_chain(events: pd.DataFrame, genesis: str) -> bool:
    prior=genesis
    for _,row in events.iterrows():
        values=row.to_dict();actual=values.pop("Event Hash");declared=values.get("Prior Event Hash")
        if declared!=prior or canonical_json_hash(values)!=actual:return False
        prior=actual
    return True
