"""Deterministic Stage 6.1A failure types."""


class Stage6IngestionError(RuntimeError):
    pass


class IntegrityFailure(Stage6IngestionError):
    pass


class IdempotencyConflict(Stage6IngestionError):
    pass


class ResolutionError(Stage6IngestionError):
    pass
