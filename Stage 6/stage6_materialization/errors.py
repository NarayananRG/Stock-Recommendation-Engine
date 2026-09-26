"""Fail-closed Stage 6.2D materialization errors."""


class Stage6MaterializationError(ValueError):
    """Materialization input or policy violates the frozen contract."""


class MaterializationIntegrityFailure(Stage6MaterializationError):
    """Persistent materialization lineage or deterministic replay failed."""


class MaterializationConflict(Stage6MaterializationError):
    """An immutable materialization identity conflicts with stored content."""
