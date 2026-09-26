"""Fail-closed errors for Stage 6.2C candidate classification."""


class Stage6CandidateError(Exception):
    """Invalid ruleset, input, or classification request."""


class CandidateIntegrityFailure(Stage6CandidateError):
    """Stored candidate lineage or deterministic replay failed."""


class CandidateConflict(Stage6CandidateError):
    """An immutable candidate or batch identity conflicts with stored content."""
