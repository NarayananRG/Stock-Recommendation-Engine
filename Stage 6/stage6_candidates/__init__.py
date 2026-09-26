"""Stage 6.2C deterministic event-candidate classification."""

from .candidate_builder import CANDIDATE_SCHEMA_VERSION, candidate_identity
from .candidate_store import AUTHORITY, CandidateStore
from .classifier import classify_extraction
from .errors import CandidateConflict, CandidateIntegrityFailure, Stage6CandidateError
from .ruleset import (CLASSIFICATION_METHOD, CLASSIFIER_VERSION, RULESET_ID,
                      RULESET_VERSION, load_ruleset, normalize_text, validate_ruleset)

__all__ = [
    "AUTHORITY", "CANDIDATE_SCHEMA_VERSION", "CLASSIFICATION_METHOD", "CLASSIFIER_VERSION",
    "RULESET_ID", "RULESET_VERSION", "CandidateConflict", "CandidateIntegrityFailure",
    "Stage6CandidateError", "CandidateStore", "candidate_identity", "classify_extraction", "load_ruleset",
    "normalize_text", "validate_ruleset",
]
