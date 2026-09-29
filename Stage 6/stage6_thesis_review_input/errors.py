class Stage6ThesisReviewInputError(Exception):
    """Base Stage 6.6C error."""


class ThesisReviewInputIntegrityFailure(Stage6ThesisReviewInputError):
    """Raised when PIT provenance or deterministic replay fails."""


class ThesisReviewInputConflict(Stage6ThesisReviewInputError):
    """Raised when a logical review is reused with different inputs."""
