"""Stage 5D.1 deterministic personal portfolio decision support."""

from .allocator import AllocationResult, allocate_candidates
from .horizon import HorizonPreference, HorizonStatus
from .portfolio_state import OpenPosition, PortfolioSnapshot
from .user_profile import InvestmentProfile, ProfileStore

__all__ = [
    "AllocationResult",
    "HorizonPreference",
    "HorizonStatus",
    "InvestmentProfile",
    "OpenPosition",
    "PortfolioSnapshot",
    "ProfileStore",
    "allocate_candidates",
]
