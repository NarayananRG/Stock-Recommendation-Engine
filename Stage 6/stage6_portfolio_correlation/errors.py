class Stage6PortfolioCorrelationError(Exception):
    pass


class PortfolioCorrelationIntegrityFailure(Stage6PortfolioCorrelationError):
    pass


class PortfolioCorrelationConflict(Stage6PortfolioCorrelationError):
    pass
