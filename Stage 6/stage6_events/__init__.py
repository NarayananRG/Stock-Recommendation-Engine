"""Stage 6.2A immutable event-intelligence foundation (fixture-only)."""

from .errors import EventIntegrityFailure, EventVersionConflict, Stage6EventError
from .event_builder import build_event, deterministic_event_id
from .event_store import AUTHORITY, EventStore
from .event_validation import validate_event

__all__ = [
    "AUTHORITY", "EventIntegrityFailure", "EventStore", "EventVersionConflict",
    "Stage6EventError", "build_event", "deterministic_event_id", "validate_event",
]
