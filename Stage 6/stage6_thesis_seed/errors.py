class Stage6ThesisSeedError(Exception):
    """Fail-closed Stage 6.6A input or operation error."""


class ThesisSeedIntegrityFailure(Stage6ThesisSeedError):
    """Persistent or cryptographic integrity failure."""


class ThesisSeedConflict(Stage6ThesisSeedError):
    """Immutable export identity was reused with different content."""
