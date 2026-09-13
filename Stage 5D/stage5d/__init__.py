"""Stage 5D.1 deterministic personal portfolio decision support."""

from .allocator import AllocationResult, allocate_candidates
from .horizon import HorizonPreference, HorizonStatus
from .portfolio_state import OpenPosition, PendingEntryReservation, PortfolioSnapshot
from .source_contract import derive_signal_id, frozen_priority_key, normalize_source_candidate
from .user_profile import InvestmentProfile, ProfileStore

__all__ = [
    "AllocationResult",
    "HorizonPreference",
    "HorizonStatus",
    "InvestmentProfile",
    "OpenPosition",
    "PendingEntryReservation",
    "PortfolioSnapshot",
    "ProfileStore",
    "allocate_candidates",
    "derive_signal_id",
    "frozen_priority_key",
    "normalize_source_candidate",
]
