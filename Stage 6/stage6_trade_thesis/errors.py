class Stage6TradeThesisError(Exception):
    """Base error for deterministic Stage 6.6B materialization."""


class TradeThesisIntegrityFailure(Stage6TradeThesisError):
    """Raised when immutable thesis provenance or replay fails."""


class TradeThesisConflict(Stage6TradeThesisError):
    """Raised when an existing seed is mapped to different content."""
