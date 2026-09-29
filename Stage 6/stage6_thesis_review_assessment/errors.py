class Stage6ThesisReviewAssessmentError(Exception):
    """Base Stage 6.6D error."""


class ThesisReviewAssessmentIntegrityFailure(Stage6ThesisReviewAssessmentError):
    """Raised when provenance, rules, or replay fail."""


class ThesisReviewAssessmentConflict(Stage6ThesisReviewAssessmentError):
    """Raised for contradictory reuse of one frozen review snapshot."""
