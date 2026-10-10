"""Read-only Fundamental Research V2 shadow adapter for Live Pilot V1."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
from typing import Any


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except ValueError:
        return None


def load_shadow_profile(
    *,
    repo_root: str | Path,
    symbol: str,
    decision_timestamp: str | None = None,
    reporting_basis_preference: str = "CONSOLIDATED",
) -> dict[str, Any]:
    """Return the latest already-generated PIT-safe V2 profile available by decision time.

    No network, no recomputation, and no production action/rank authority.
    """
    root=Path(repo_root)
    path=(
        root/"NextGen Research"/"results"/
        "fundamental_v2_phase2a7_risk_events"/"risk_event_profiles.jsonl"
    )
    base={
        "available":False,
        "symbol":symbol,
        "authority":"SHADOW_ONLY",
        "production_action_changed":False,
        "production_rank_changed":False,
        "warning_codes":[],
    }
    if not path.exists():
        return {**base,"reason":"PHASE2A7_PROFILE_FILE_NOT_FOUND"}

    cutoff=_parse_ts(decision_timestamp)
    wanted=str(symbol).strip().upper().removesuffix(".NS").removesuffix(".BO")
    candidates=[]
    with path.open("r",encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row=json.loads(line)
            row_symbol=str(row.get("symbol") or "").strip().upper().removesuffix(".NS").removesuffix(".BO")
            if row_symbol!=wanted:
                continue
            available=_parse_ts(row.get("effective_availability_ts"))
            if cutoff is not None and available is not None and available>cutoff:
                continue
            candidates.append(row)

    if not candidates:
        return {**base,"reason":"NO_PIT_SAFE_V2_PROFILE_AVAILABLE_BY_DECISION_TIME"}

    candidates.sort(
        key=lambda row:(
            row.get("reporting_basis")==reporting_basis_preference,
            str(row.get("effective_availability_ts") or ""),
        ),
        reverse=True,
    )
    selected=candidates[0]
    warnings=[]
    if selected.get("strong_deterioration_transition"):
        warnings.append("STRONG_DETERIORATION_SIGN_TRANSITION")
    if selected.get("event_profile")=="PURE_DETERIORATION":
        warnings.append("PURE_DETERIORATION_PROFILE")
    elif selected.get("event_profile")=="MIXED_DIRECTIONAL":
        warnings.append("MIXED_DIRECTIONAL_PROFILE")

    return {
        **base,
        "available":True,
        "reason":"AVAILABLE",
        "reporting_basis":selected.get("reporting_basis"),
        "quarter_end":selected.get("current_quarter_end"),
        "effective_availability_ts":selected.get("effective_availability_ts"),
        "event_profile":selected.get("event_profile"),
        "deterioration_evidence_count":selected.get("deterioration_evidence_count"),
        "improvement_evidence_count":selected.get("improvement_evidence_count"),
        "context_evidence_count":selected.get("context_evidence_count"),
        "strong_deterioration_transition":bool(selected.get("strong_deterioration_transition")),
        "strong_improvement_transition":bool(selected.get("strong_improvement_transition")),
        "warning_codes":warnings,
    }
