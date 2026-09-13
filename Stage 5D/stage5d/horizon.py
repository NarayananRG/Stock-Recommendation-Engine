from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HorizonPreference(str, Enum):
    ONE_MONTH = "ONE_MONTH"
    THREE_MONTHS = "THREE_MONTHS"
    SIX_MONTHS = "SIX_MONTHS"


class HorizonStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    EXPECTED_MOVE_EXCEEDS_HORIZON = "EXPECTED_MOVE_EXCEEDS_HORIZON"
    INSUFFICIENT_HORIZON_EVIDENCE = "INSUFFICIENT_HORIZON_EVIDENCE"
    UNSUPPORTED_NOT_VALIDATED = "UNSUPPORTED_NOT_VALIDATED"


@dataclass(frozen=True)
class HorizonAssessment:
    selected_horizon: HorizonPreference
    horizon_session_limit: int | None
    estimated_or_rule_based_holding_compatibility: str
    horizon_status: HorizonStatus


def assess_horizon(candidate: dict[str, object], horizon: HorizonPreference) -> HorizonAssessment:
    if horizon is HorizonPreference.SIX_MONTHS:
        return HorizonAssessment(horizon, None, "Six-month behavior has not been validated", HorizonStatus.UNSUPPORTED_NOT_VALIDATED)
    limit = 21 if horizon is HorizonPreference.ONE_MONTH else 63
    validated = candidate.get("validated_holding_sessions")
    source = str(candidate.get("holding_evidence_source", "")).upper()
    if horizon is HorizonPreference.ONE_MONTH:
        if validated is None or source != "VALIDATED_DETERMINISTIC":
            estimate = candidate.get("estimated_holding_sessions")
            detail = "No validated candidate-level time-to-target evidence"
            if estimate is not None:
                detail += f"; heuristic estimate {estimate} sessions is informational only"
            return HorizonAssessment(horizon, limit, detail, HorizonStatus.INSUFFICIENT_HORIZON_EVIDENCE)
        if int(validated) > limit:
            return HorizonAssessment(horizon, limit, f"Validated deterministic holding evidence is {int(validated)} sessions", HorizonStatus.EXPECTED_MOVE_EXCEEDS_HORIZON)
        return HorizonAssessment(horizon, limit, f"Validated deterministic holding evidence is {int(validated)} sessions", HorizonStatus.ELIGIBLE)
    if validated is not None and int(validated) > limit:
        return HorizonAssessment(horizon, limit, f"Validated deterministic holding evidence is {int(validated)} sessions", HorizonStatus.EXPECTED_MOVE_EXCEEDS_HORIZON)
    return HorizonAssessment(horizon, limit, "Frozen deterministic strategy maximum is 63 market sessions", HorizonStatus.ELIGIBLE)
