"""Fail-closed errors for the Stage 6.2A event foundation."""


class Stage6EventError(Exception):
    """Invalid event request or prohibited Stage 6.2A operation."""


class EventIntegrityFailure(Stage6EventError):
    """Stored event, dependency, or upstream evidence failed verification."""


class EventVersionConflict(Stage6EventError):
    """An immutable event version conflicts with an existing version."""
