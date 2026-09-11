from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .ledger_counts import prediction_rows
from .outcome_resolver import load_all_events,verify_outcome_ledger


ALLOWED_FIELDS={"activation_date","days_elapsed","eligible_sessions","captured_sessions","missed_sessions","zero_candidate_sessions","candidate_count","pending_labels","resolved_labels","completed_d1_shadow_trades","ledger_chain_valid","last_snapshot_date"}
FORBIDDEN_TERMS=("auc","average precision","brier","return","cagr","expectancy","profit factor","win rate","policy comparison","best model","rank lift","policy winner")


def operational_status(values: dict[str,Any]) -> dict[str,Any]:
    extras=sorted(set(values)-ALLOWED_FIELDS)
    if extras:raise ValueError(f"PERFORMANCE_FIELD_PROHIBITED: {extras}")
    return {name:values.get(name) for name in sorted(ALLOWED_FIELDS)}


def derive_operational_status(stage_root: Path, as_of_date: str) -> dict[str,Any]:
    activation_path=stage_root/"prospective/audit/activation_record.json";activation=json.loads(activation_path.read_text()) if activation_path.exists() else None
    index_path=stage_root/"prospective/audit/prospective_snapshot_index.csv";index=pd.read_csv(index_path) if index_path.exists() else pd.DataFrame()
    breaches_path=stage_root/"prospective/audit/protocol_breaches.csv";breaches=pd.read_csv(breaches_path) if breaches_path.exists() else pd.DataFrame()
    predictions=prediction_rows(stage_root);events=load_all_events(stage_root/"prospective/outcomes")
    terminal=events.loc[events.get("Is Terminal",pd.Series(dtype=str)).astype(str).str.lower().isin(["true","1"])] if len(events) else events
    captured=len(index);missed=int(breaches.get("Breach Type",pd.Series(dtype=str)).eq("MISSED_PROSPECTIVE_SESSION").sum())
    activation_date=activation.get("Activation Local Date") if activation else None;days=0 if not activation_date else max(0,(pd.Timestamp(as_of_date)-pd.Timestamp(activation_date)).days)
    values={"activation_date":activation_date,"days_elapsed":days,"eligible_sessions":captured+missed,"captured_sessions":captured,"missed_sessions":missed,"zero_candidate_sessions":int(pd.to_numeric(index.get("Candidate Count",pd.Series(dtype=float)),errors="coerce").eq(0).sum()),"candidate_count":len(predictions),"pending_labels":max(0,len(predictions)-terminal.loc[terminal.get("Outcome Type",pd.Series(dtype=str)).eq("ENTRY_FILLED")]["Signal ID"].nunique()) if len(terminal) else len(predictions),"resolved_labels":int(len(terminal)),"completed_d1_shadow_trades":int(terminal.get("Outcome Type",pd.Series(dtype=str)).eq("D1_TRADE_COMPLETION").sum()) if len(terminal) else 0,"ledger_chain_valid":verify_outcome_ledger(stage_root/"prospective/outcomes"),"last_snapshot_date":None if index.empty else str(index.iloc[-1]["Signal Date"])}
    return operational_status(values)
