class Stage6PortfolioContextError(Exception):
    pass


class PortfolioContextIntegrityFailure(Stage6PortfolioContextError):
    pass


class PortfolioContextConflict(Stage6PortfolioContextError):
    pass
