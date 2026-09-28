class Stage6PortfolioArithmeticError(Exception):
    """Base fail-closed Stage 6.5B error."""


class PortfolioArithmeticIntegrityFailure(Stage6PortfolioArithmeticError):
    """Persisted or upstream arithmetic integrity failed."""


class PortfolioArithmeticConflict(Stage6PortfolioArithmeticError):
    """An immutable source snapshot produced conflicting arithmetic."""
