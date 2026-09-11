from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .immutable_ledger import verify_ledger
from .outcome_resolver import load_all_events, verify_outcome_ledger
from .protocol_integrity import verify_runtime_protocol_integrity
from .session_coverage import verify_coverage


def prediction_rows(stage_root: Path) -> pd.DataFrame:
    index_path=stage_root/"prospective/audit/prospective_snapshot_index.csv"
    if not index_path.exists() or not index_path.stat().st_size:return pd.DataFrame()
    index=pd.read_csv(index_path,dtype=str);parts=[]
    for date in index.get("Signal Date",[]):
        path=stage_root/"prospective/snapshots"/str(date)[:4]/str(date)/"candidate_predictions.csv.gz"
        if path.exists():parts.append(pd.read_csv(path,low_memory=False))
    return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()


def derive_final_gate_counts(repo: Path, stage_root: Path, as_of_date: str, *, synthetic_integrity: bool=False) -> dict[str,Any]:
    activation=json.loads((stage_root/"prospective/audit/activation_record.json").read_text(encoding="utf-8"))
    predictions=prediction_rows(stage_root);events=load_all_events(stage_root/"prospective/outcomes");as_of=pd.Timestamp(as_of_date)
    if len(predictions):predictions=predictions.loc[pd.to_datetime(predictions["Signal Date"])<=as_of].copy()
    if len(events):events=events.loc[pd.to_datetime(events["Label Available Date"],errors="coerce")<=as_of].copy()
    ledger=verify_ledger(stage_root/"prospective/snapshots",stage_root/"prospective/audit",activation["Protocol Commit"],activation["Model Bundle Hash"],activation["Genesis Chain Hash"])
    outcomes=verify_outcome_ledger(stage_root/"prospective/outcomes")
    coverage_path=stage_root/"prospective/audit/session_coverage_index.csv";coverage=verify_coverage(coverage_path) if coverage_path.exists() else True
    if synthetic_integrity:
        if "tests" not in {part.lower() for part in stage_root.parts}:raise RuntimeError("SYNTHETIC_INTEGRITY_ONLY_UNDER_TESTS")
        protocol=True
    else:
        try:verify_runtime_protocol_integrity(repo,stage_root,activation);protocol=True
        except Exception:protocol=False
    terminal=events.loc[events.get("Is Terminal",pd.Series(dtype=str)).astype(str).str.lower().isin(["true","1"])] if len(events) else events
    d1=terminal.loc[terminal.get("Outcome Type",pd.Series(dtype=str)).eq("D1_TRADE_COMPLETION")] if len(terminal) else terminal
    entry=terminal.loc[terminal.get("Outcome Type",pd.Series(dtype=str)).eq("ENTRY_FILLED")] if len(terminal) else terminal
    t1=terminal.loc[terminal.get("Outcome Type",pd.Series(dtype=str)).eq("T1_BEFORE_STOP_63")] if len(terminal) else terminal
    return {"as_of_date":as_of_date,"candidate_count":int(len(predictions.loc[predictions["Dataset Cohort"].eq("BASELINE_PRIMARY")])) if len(predictions) else 0,"r0_k1_completed_d1":int(d1.loc[d1["Policy"].eq("R0_K1")]["Signal ID"].nunique()) if len(d1) else 0,"r3_k1_completed_d1":int(d1.loc[d1["Policy"].eq("R3_K1")]["Signal ID"].nunique()) if len(d1) else 0,"resolved_entry_labels":int(entry["Signal ID"].nunique()) if len(entry) else 0,"resolved_t1_filled":int(t1["Signal ID"].nunique()) if len(t1) else 0,"ledger_chain_pass":bool(ledger and outcomes and coverage),"protocol_integrity_pass":bool(protocol),"protocol_hash":activation["Protocol Identity"]}
