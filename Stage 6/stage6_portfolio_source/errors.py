class Stage6PortfolioSourceError(Exception):
    """Base fail-closed Stage 6.5A error."""


class PortfolioSourceIntegrityFailure(Stage6PortfolioSourceError):
    """Persisted or supplied portfolio-source evidence failed integrity checks."""


class PortfolioSourceConflict(Stage6PortfolioSourceError):
    """An immutable logical source export was supplied with different content."""
