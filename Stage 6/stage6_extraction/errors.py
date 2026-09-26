"""Fail-closed Stage 6.2B extraction errors."""


class Stage6ExtractionError(Exception):
    """Invalid extraction request or structurally unsafe feed."""


class ExtractionIntegrityFailure(Stage6ExtractionError):
    """Stored extraction or immutable parent provenance failed verification."""


class ExtractionConflict(Stage6ExtractionError):
    """An immutable extraction identity conflicts with stored content."""
