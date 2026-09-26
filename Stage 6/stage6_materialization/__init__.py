"""Stage 6.2D deterministic candidate-to-event materialization."""

from .errors import MaterializationConflict, MaterializationIntegrityFailure, Stage6MaterializationError
from .event_mapper import MATERIALIZATION_SCHEMA_VERSION, materialization_identity
from .materialization_store import AUTHORITY, STORE_SCHEMA_VERSION, MaterializationStore
from .materialization_validation import validate_materialization
from .policy import (MATERIALIZER_VERSION, POLICY_ID, POLICY_VERSION, load_policy,
                     validate_policy)

__all__ = [
    "AUTHORITY", "MATERIALIZATION_SCHEMA_VERSION", "MATERIALIZER_VERSION", "POLICY_ID",
    "POLICY_VERSION", "STORE_SCHEMA_VERSION", "MaterializationConflict",
    "MaterializationIntegrityFailure", "MaterializationStore", "Stage6MaterializationError",
    "load_policy", "materialization_identity", "validate_materialization", "validate_policy",
]
