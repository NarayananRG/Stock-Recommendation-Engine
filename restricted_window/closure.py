"""Deterministic restricted-window lifecycle, investability, and rights controls."""
from __future__ import annotations

import hashlib
import json
from datetime import date

AUTHORITY = "SHADOW_ONLY"
SECURITY_STATES = {"TRADABLE_LISTED_EQUITY", "INDEX_ACCOUNTING_PLACEHOLDER_NONTRADABLE",
                   "RESULTING_ENTITY_NOT_YET_LISTED", "LISTED_BUT_TEMPORARY_INDEX_TREATMENT",
                   "DELISTED_OR_EXCLUDED", "IDENTITY_UNRESOLVED"}
CONTINUITY_STATES = {"NO_FEATURE_RESET_REQUIRED", "PIT_ADJUSTMENT_AVAILABLE",
                     "FEATURE_HISTORY_RESET_REQUIRED", "SECURITY_NEW_HISTORY_REQUIRED",
                     "UNRESOLVED_BLOCKING"}
RIGHTS_STATES = {"EXPLICITLY_PERMITTED_FOR_INTENDED_RESEARCH", "RESEARCH_ANALYSIS_ONLY",
                 "MODEL_TRAINING_RIGHTS_NOT_ESTABLISHED", "PERMISSION_REQUIRED",
                 "LICENSE_REQUIRED", "PROHIBITED_FOR_MODEL_TRAINING"}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def security_state(*, placeholder=False, listed=True, temporary=False,
                   excluded=False, identity_known=True) -> str:
    if placeholder:
        return "INDEX_ACCOUNTING_PLACEHOLDER_NONTRADABLE"
    if not identity_known:
        return "IDENTITY_UNRESOLVED"
    if excluded:
        return "DELISTED_OR_EXCLUDED"
    if not listed:
        return "RESULTING_ENTITY_NOT_YET_LISTED"
    if temporary:
        return "LISTED_BUT_TEMPORARY_INDEX_TREATMENT"
    return "TRADABLE_LISTED_EQUITY"


def feature_eligibility(*, index_member: bool, listed: bool, identity_known: bool,
                        unresolved_action: bool, observed_sessions: int,
                        max_lookback: int = 60, placeholder: bool = False) -> str:
    if placeholder:
        return "INDEX_PLACEHOLDER_EXCLUDED"
    if not index_member:
        return "NOT_INDEX_MEMBER"
    if not listed:
        return "RESULTING_ENTITY_NOT_YET_LISTED"
    if not identity_known:
        return "IDENTITY_UNRESOLVED"
    if unresolved_action:
        return "CORPORATE_ACTION_UNRESOLVED"
    if observed_sessions < max_lookback:
        return "FEATURE_WARMUP_NOT_COMPLETE"
    return "MODEL_CANDIDATE_ELIGIBLE"


def action_continuity(action_type: str, adjustment_factor: float | None = None) -> str:
    action_type = action_type.upper()
    if action_type in {"DIVIDEND", "SYMBOL_CHANGE"}:
        return "NO_FEATURE_RESET_REQUIRED"
    if action_type in {"SPLIT", "BONUS", "FACE_VALUE_ADJUSTMENT"}:
        return "PIT_ADJUSTMENT_AVAILABLE" if adjustment_factor and adjustment_factor > 0 else "FEATURE_HISTORY_RESET_REQUIRED"
    if action_type in {"RIGHTS", "MERGER", "DEMERGER"}:
        return "FEATURE_HISTORY_RESET_REQUIRED"
    if action_type == "NEW_LISTING":
        return "SECURITY_NEW_HISTORY_REQUIRED"
    return "UNRESOLVED_BLOCKING"


def action_safe_for_feature(*, feature_date: str, action_effective_date: str,
                            action_known_date: str, policy: str) -> bool:
    if policy not in CONTINUITY_STATES:
        return False
    if action_effective_date > feature_date or action_known_date > feature_date:
        return True
    return policy != "UNRESOLVED_BLOCKING"


def readiness_v6(technical_gates: dict[str, bool], rights_ready: bool,
                 period: dict | None, preserved_hashes: dict[str, str]) -> dict:
    required = {"constituent_reconstruction", "investable_universe", "identity", "survivorship",
                "market_data", "price_normalization", "execution_costs", "benchmark", "features", "governance"}
    if set(technical_gates) != required:
        raise ValueError("V6_TECHNICAL_GATE_SET_INVALID")
    failed = sorted(k for k, v in technical_gates.items() if not v)
    technically_ready = not failed and period is not None
    status = ("NOT_READY" if not technically_ready else
              "TECHNICALLY_READY_RIGHTS_PENDING" if not rights_ready else
              "READY_WITH_RESTRICTED_PERIOD")
    return {"artifact_type": "ADVANCED_RESEARCH_READINESS_V6",
            "profile": "FREE_OFFICIAL_RESTRICTED_NIFTY500_PIT", "status": status,
            "technical_gates": technical_gates, "failed_technical_gates": failed,
            "model_training_usage_rights_gate": rights_ready,
            "restricted_period": period if technically_ready else None,
            "preserved_readiness_hashes": preserved_hashes, "training_started": False,
            "challenger_trained": False, "model_promoted": False,
            "trading_authority": False, "ml_authority": "NONE", "authority": AUTHORITY}


def decision_v3(*, technically_ready: bool, rights_state: str,
                technical_paid_data_required: bool = False) -> str:
    if technical_paid_data_required:
        return "LICENSED_DATA_REQUIRED_FOR_TECHNICAL_COMPLETENESS"
    if not technically_ready:
        return "FREE_DATA_STILL_TECHNICALLY_INCOMPLETE"
    if rights_state == "READY":
        return "FREE_DATA_TECHNICALLY_SUFFICIENT"
    if rights_state == "LICENSE_REQUIRED":
        return "LICENSE_REQUIRED_FOR_MODEL_TRAINING"
    if rights_state == "PERMISSION_REQUIRED":
        return "PERMISSION_REQUIRED_FOR_MODEL_TRAINING"
    return "FREE_DATA_TECHNICALLY_SUFFICIENT_RIGHTS_PENDING"


def in_period(day: str, start: str, end: str | None) -> bool:
    value = date.fromisoformat(day)
    return date.fromisoformat(start) <= value and (end is None or value <= date.fromisoformat(end))
