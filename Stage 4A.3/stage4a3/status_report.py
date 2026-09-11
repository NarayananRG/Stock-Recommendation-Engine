from __future__ import annotations

from typing import Any


ALLOWED_FIELDS = {
    "activation_date","days_elapsed","eligible_sessions","captured_sessions","missed_sessions",
    "zero_candidate_sessions","candidate_count","pending_labels","resolved_labels",
    "completed_d1_shadow_trades","ledger_chain_valid","last_snapshot_date",
}


def operational_status(values: dict[str, Any]) -> dict[str, Any]:
    extras = sorted(set(values) - ALLOWED_FIELDS)
    if extras:
        raise ValueError(f"PERFORMANCE_FIELD_PROHIBITED: {extras}")
    return {name: values.get(name) for name in sorted(ALLOWED_FIELDS)}
