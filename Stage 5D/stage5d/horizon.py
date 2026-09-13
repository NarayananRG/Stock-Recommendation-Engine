from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HorizonPreference(str, Enum):
    ONE_MONTH = "ONE_MONTH"
    THREE_MONTHS = "THREE_MONTHS"
    SIX_MONTHS = "SIX_MONTHS"


class HorizonStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    UNSUPPORTED_NOT_VALIDATED = "UNSUPPORTED_NOT_VALIDATED"


@dataclass(frozen=True)
class HorizonAssessment:
    selected_horizon: HorizonPreference
    horizon_session_limit: int | None
    horizon_status: HorizonStatus
    management_policy_id: str | None
    management_policy_source: str | None
    management_policy_max_sessions: int | None
    management_policy_validation_semantics: str | None
    estimated_or_rule_based_holding_compatibility: str


POLICY_BY_HORIZON: dict[HorizonPreference, HorizonAssessment] = {
    HorizonPreference.ONE_MONTH: HorizonAssessment(
        selected_horizon=HorizonPreference.ONE_MONTH,
        horizon_session_limit=20,
        horizon_status=HorizonStatus.ELIGIBLE,
        management_policy_id="STATIC_T2_20D",
        management_policy_source="FROZEN_STAGE2_2_2_STATIC_BASELINE",
        management_policy_max_sessions=20,
        management_policy_validation_semantics="HISTORICALLY_TESTED_DETERMINISTIC_NOT_PROSPECTIVE",
        estimated_or_rule_based_holding_compatibility=(
            "Approximately one month; later daily monitoring must apply STATIC_T2_20D. "
            "Historical deterministic testing does not guarantee profit."
        ),
    ),
    HorizonPreference.THREE_MONTHS: HorizonAssessment(
        selected_horizon=HorizonPreference.THREE_MONTHS,
        horizon_session_limit=63,
        horizon_status=HorizonStatus.ELIGIBLE,
        management_policy_id="D1_TRAIL_ONLY_63D",
        management_policy_source="FROZEN_STAGE2B_1_DYNAMIC_BASELINE",
        management_policy_max_sessions=63,
        management_policy_validation_semantics="HISTORICALLY_TESTED_DETERMINISTIC_NOT_PROSPECTIVE",
        estimated_or_rule_based_holding_compatibility=(
            "Up to 63 sessions; later daily monitoring must apply D1_TRAIL_ONLY_63D. "
            "Historical deterministic testing does not guarantee profit."
        ),
    ),
    HorizonPreference.SIX_MONTHS: HorizonAssessment(
        selected_horizon=HorizonPreference.SIX_MONTHS,
        horizon_session_limit=None,
        horizon_status=HorizonStatus.UNSUPPORTED_NOT_VALIDATED,
        management_policy_id=None,
        management_policy_source=None,
        management_policy_max_sessions=None,
        management_policy_validation_semantics=None,
        estimated_or_rule_based_holding_compatibility="Six-month management has not been validated",
    ),
}


def assess_horizon(candidate: dict[str, object], horizon: HorizonPreference) -> HorizonAssessment:
    """Return the fixed policy contract; candidate assertions are intentionally ignored."""
    del candidate
    return POLICY_BY_HORIZON[horizon]
