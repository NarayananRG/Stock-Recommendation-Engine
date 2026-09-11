from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


def gate_audit(config: dict[str,Any],activation: dict[str,Any]|None,counts: dict[str,Any]) -> pd.DataFrame:
    gate=config["final_gate"]
    months=0 if activation is None else (pd.Timestamp(counts["as_of_date"])-pd.Timestamp(activation["Activation UTC"]).tz_localize(None)).days/30.4375
    checks=[
        ("calendar duration months",months>=gate["minimum_calendar_months"],gate["minimum_calendar_months"],months),
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
