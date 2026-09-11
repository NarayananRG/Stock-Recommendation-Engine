from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


def gate_audit(config: dict[str,Any],activation: dict[str,Any]|None,counts: dict[str,Any]) -> pd.DataFrame:
    gate=config["final_gate"]
    as_of=pd.Timestamp(counts["as_of_date"]).normalize();activated=None if activation is None else pd.Timestamp(activation["Activation Local Date"] if activation.get("Activation Local Date") else activation["Activation UTC"]).tz_localize(None).normalize()
    months=0 if activated is None or as_of<activated else (as_of.year-activated.year)*12+as_of.month-activated.month-(1 if as_of.day<activated.day else 0)
    duration_pass=activated is not None and as_of>=activated+pd.DateOffset(months=gate["minimum_calendar_months"])
    checks=[
        ("calendar duration months",duration_pass,gate["minimum_calendar_months"],months),
        ("BASELINE_PRIMARY candidates",counts["candidate_count"]>=gate["minimum_baseline_primary_candidates"],gate["minimum_baseline_primary_candidates"],counts["candidate_count"]),
        ("R0_K1 completed D1 trades",counts["r0_k1_completed_d1"]>=gate["minimum_r0_k1_completed_d1_trades"],gate["minimum_r0_k1_completed_d1_trades"],counts["r0_k1_completed_d1"]),
        ("R3_K1 completed D1 trades",counts["r3_k1_completed_d1"]>=gate["minimum_r3_k1_completed_d1_trades"],gate["minimum_r3_k1_completed_d1_trades"],counts["r3_k1_completed_d1"]),
        ("resolved ENTRY_FILLED labels",counts["resolved_entry_labels"]>=gate["minimum_resolved_entry_labels"],gate["minimum_resolved_entry_labels"],counts["resolved_entry_labels"]),
        ("resolved filled T1 outcomes",counts["resolved_t1_filled"]>=gate["minimum_resolved_t1_filled_outcomes"],gate["minimum_resolved_t1_filled_outcomes"],counts["resolved_t1_filled"]),
        ("ledger chain",bool(counts["ledger_chain_pass"]),True,counts["ledger_chain_pass"]),
        ("protocol integrity",bool(counts["protocol_integrity_pass"]),True,counts["protocol_integrity_pass"]),
    ]
    return pd.DataFrame([{"Gate":name,"Status":"PASS" if passed else "LOCKED","Required":expected,"Actual":actual} for name,passed,expected,actual in checks])


def is_unlocked(audit: pd.DataFrame) -> bool:
    return bool(len(audit)==8 and audit["Status"].eq("PASS").all())
