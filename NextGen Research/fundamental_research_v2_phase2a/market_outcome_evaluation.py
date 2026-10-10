"""Official-only market outcome evaluation for Fundamental Research V2 Phase 2A.8."""
from __future__ import annotations

import bisect
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Iterable

HORIZONS=(21,63,126)
SKIP_DIRS={".git","node_modules",".venv","venv","__pycache__","target","dist","build"}
SUPPORTED={".csv",".json",".jsonl",".parquet"}
OFFICIAL_TOKENS=("official","nse","bse","exchange")
REJECT_TOKENS=("yfinance","yf_fallback","fallback_yfinance")
SYMBOL_ALIASES=("symbol","ticker","stocksymbol","nsesymbol","securitysymbol","tradingsymbol")
DATE_ALIASES=("date","tradingdate","sessiondate","tradedate","timestamp","datetime")
CLOSE_ALIASES=("close","closeprice","closingprice","closevalue","lastclose")
PROVIDER_ALIASES=("provider","sourceprovider","datasource","source")


def normalize_symbol(value) -> str:
    text=str(value or "").strip().upper()
    text=re.sub(r"\.(NS|BO)$","",text)
    return text


def _norm_col(value) -> str:
    return re.sub(r"[^a-z0-9]","",str(value).lower())


def _path_score(path: Path) -> int:
    s=str(path).lower().replace("\\","/")
    score=0
    if "complete_stock_history" in s or "complete-stock-history" in s: score+=12
    if "official_v1" in s or "official-v1" in s: score+=10
    if "official" in s: score+=8
    if "nse" in s: score+=6
    if "bse" in s: score+=6
    if "history" in s: score+=3
    if "price" in s or "ohlc" in s: score+=2
    return score


def _candidate_path(path: Path) -> bool:
    s=str(path).lower().replace("\\","/")
    if path.suffix.lower() not in SUPPORTED:
        return False
    if any(token in s for token in REJECT_TOKENS):
        return False
    if "fundamental_v2_phase2a" in s and "market" not in s:
        return False
    return any(token in s for token in OFFICIAL_TOKENS)


def _find_col(columns, aliases):
    mapping={_norm_col(c):c for c in columns}
    for alias in aliases:
        if alias in mapping:
            return mapping[alias]
    return None


def _json_records(obj, inherited_symbol=None):
    records=[]
    if isinstance(obj,list):
        if obj and all(isinstance(x,dict) for x in obj):
            for row in obj:
                copy=dict(row)
                if inherited_symbol and not any(_norm_col(k) in SYMBOL_ALIASES for k in copy):
                    copy["symbol"]=inherited_symbol
                records.append(copy)
        return records
    if not isinstance(obj,dict):
        return records
    lowered={_norm_col(k):k for k in obj}
    if any(a in lowered for a in DATE_ALIASES) and any(a in lowered for a in CLOSE_ALIASES):
        row=dict(obj)
        if inherited_symbol and not any(_norm_col(k) in SYMBOL_ALIASES for k in row):
            row["symbol"]=inherited_symbol
        return [row]
    for key,value in obj.items():
        child_symbol=inherited_symbol
        normalized=normalize_symbol(key)
        if normalized and re.fullmatch(r"[A-Z0-9&_-]{2,30}",normalized) and isinstance(value,(list,dict)):
            child_symbol=normalized
        if _norm_col(key) in {"data","records","history","prices","rows","result","results"}:
            child_symbol=inherited_symbol
        records.extend(_json_records(value,child_symbol))
    return records


def _read_frame(path: Path):
    try:
        import pandas as pd
    except Exception as exc:
        raise RuntimeError("PANDAS_REQUIRED_FOR_OFFICIAL_PRICE_DISCOVERY") from exc
    suffix=path.suffix.lower()
    if suffix==".csv":
        return pd.read_csv(path,low_memory=False)
    if suffix==".parquet":
        return pd.read_parquet(path)
    if suffix==".jsonl":
        return pd.read_json(path,lines=True)
    if suffix==".json":
        obj=json.loads(path.read_text(encoding="utf-8"))
        records=_json_records(obj)
        return pd.DataFrame(records)
    raise ValueError(f"UNSUPPORTED_PRICE_FILE:{path}")


def discover_official_price_history(repo_root: Path, target_symbols: set[str]):
    target={normalize_symbol(x) for x in target_symbols if normalize_symbol(x)}
    candidates=[]
    for root,dirs,files in os.walk(repo_root):
        dirs[:]=[d for d in dirs if d not in SKIP_DIRS]
        root_path=Path(root)
        for name in files:
            path=root_path/name
            if _candidate_path(path):
                candidates.append(path)
    candidates.sort(key=lambda p:(-_path_score(p),str(p).lower()))

    selected={}
    accepted=[]
    rejected=[]
    conflicts=[]
    for path in candidates:
        try:
            frame=_read_frame(path)
        except Exception as exc:
            rejected.append({"path":str(path),"reason":f"READ_FAILED:{type(exc).__name__}"})
            continue
        if frame is None or frame.empty:
            rejected.append({"path":str(path),"reason":"EMPTY"})
            continue

        columns=list(frame.columns)
        symbol_col=_find_col(columns,SYMBOL_ALIASES)
        date_col=_find_col(columns,DATE_ALIASES)
        close_col=_find_col(columns,CLOSE_ALIASES)
        provider_col=_find_col(columns,PROVIDER_ALIASES)
        inferred_symbol=None
        if symbol_col is None:
            stem=normalize_symbol(path.stem)
            if stem in target:
                inferred_symbol=stem
            else:
                rejected.append({"path":str(path),"reason":"NO_SYMBOL_COLUMN_OR_TARGET_FILENAME"})
                continue
        if date_col is None or close_col is None:
            rejected.append({"path":str(path),"reason":"DATE_OR_CLOSE_COLUMN_MISSING"})
            continue

        if provider_col is not None:
            sample=[str(x).lower() for x in frame[provider_col].dropna().head(100).tolist()]
            if any("yfinance" in x for x in sample):
                rejected.append({"path":str(path),"reason":"YFINANCE_PROVIDER_METADATA"})
                continue

        score=_path_score(path)
        row_count=0
        symbol_count=set()
        for _,row in frame.iterrows():
            symbol=inferred_symbol or normalize_symbol(row.get(symbol_col))
            if target and symbol not in target:
                continue
            try:
                raw_date=row.get(date_col)
                parsed=datetime.fromisoformat(str(raw_date).replace("Z","+00:00")).date()
            except Exception:
                try:
                    import pandas as pd
                    parsed=pd.to_datetime(row.get(date_col),errors="raise").date()
                except Exception:
                    continue
            try:
                close=float(row.get(close_col))
            except Exception:
                continue
            if not math.isfinite(close) or close<=0:
                continue
            row_count+=1
            symbol_count.add(symbol)
            key=(symbol,parsed)
            prior=selected.get(key)
            current={"close":close,"score":score,"path":str(path)}
            if prior is None or score>prior["score"]:
                selected[key]=current
            elif score==prior["score"] and abs(prior["close"]-close)>1e-9:
                conflicts.append({
                    "symbol":symbol,"date":parsed.isoformat(),
                    "kept_path":min(prior["path"],str(path)),
                    "other_path":max(prior["path"],str(path)),
                    "close_a":prior["close"],"close_b":close,
                })
                if str(path)<prior["path"]:
                    selected[key]=current
        if row_count:
            accepted.append({
                "path":str(path),"score":score,"usable_rows":row_count,
                "target_symbols":len(symbol_count)
            })
        else:
            rejected.append({"path":str(path),"reason":"NO_TARGET_PRICE_ROWS"})

    by_symbol=defaultdict(list)
    for (symbol,session_date),record in selected.items():
        by_symbol[symbol].append((session_date,record["close"]))
    for symbol in by_symbol:
        by_symbol[symbol].sort()

    report={
        "artifact_type":"FUNDAMENTAL_RESEARCH_V2_OFFICIAL_PRICE_DISCOVERY_V1",
        "candidate_file_count":len(candidates),
        "accepted_file_count":len(accepted),
        "rejected_file_count":len(rejected),
        "accepted_files":accepted,
        "rejected_files":rejected[:500],
        "equal_priority_conflict_count":len(conflicts),
        "conflicts":conflicts[:200],
        "loaded_symbol_count":len(by_symbol),
        "loaded_price_row_count":sum(len(v) for v in by_symbol.values()),
        "yfinance_used":False,
        "network_used":False,
    }
    return dict(by_symbol),report


def compute_forward_outcomes(profiles: Iterable[dict], prices: dict[str,list[tuple[date,float]]]):
    outcomes=[]
    matched_events=set()
    for profile in profiles:
        symbol=normalize_symbol(profile.get("symbol"))
        series=prices.get(symbol)
        availability=profile.get("effective_availability_ts")
        if not series or not availability:
            continue
        filing_date=datetime.fromisoformat(str(availability)).date()
        dates=[x[0] for x in series]
        entry_index=bisect.bisect_right(dates,filing_date)
        if entry_index>=len(series):
            continue
        entry_date,entry_close=series[entry_index]
        matched_events.add((profile.get("reporting_basis"),profile.get("current_event_id")))
        for horizon in HORIZONS:
            exit_index=entry_index+horizon
            mature=exit_index<len(series)
            row={
                "symbol":symbol,
                "reporting_basis":profile.get("reporting_basis"),
                "current_event_id":profile.get("current_event_id"),
                "current_quarter_end":profile.get("current_quarter_end"),
                "effective_availability_ts":availability,
                "event_profile":profile.get("event_profile"),
                "strong_deterioration_transition":profile.get("strong_deterioration_transition"),
                "strong_improvement_transition":profile.get("strong_improvement_transition"),
                "horizon_sessions":horizon,
                "entry_date":entry_date.isoformat(),
                "entry_close":entry_close,
                "mature":mature,
                "exit_date":None,
                "exit_close":None,
                "forward_return":None,
            }
            if mature:
                exit_date,exit_close=series[exit_index]
                row["exit_date"]=exit_date.isoformat()
                row["exit_close"]=exit_close
                row["forward_return"]=exit_close/entry_close-1.0
            outcomes.append(row)
    return outcomes,len(matched_events)


def _stats(values):
    clean=[float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not clean:
        return {"count":0,"mean":None,"median":None,"positive_rate":None}
    return {
        "count":len(clean),
        "mean":mean(clean),
        "median":median(clean),
        "positive_rate":sum(x>0 for x in clean)/len(clean),
    }


def summarize_outcomes(outcomes: Iterable[dict]):
    rows=list(outcomes)
    groups=defaultdict(list)
    for row in rows:
        if row.get("mature"):
            groups[(row.get("event_profile"),int(row.get("horizon_sessions")))].append(row.get("forward_return"))
    return [
        {"event_profile":profile,"horizon_sessions":horizon,**_stats(values)}
        for (profile,horizon),values in sorted(groups.items())
    ]
