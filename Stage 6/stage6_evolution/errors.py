"""Fail-closed Stage 6.2E evolution errors."""


class Stage6EvolutionError(ValueError):
    """An evolution directive or operation violates the frozen contract."""


class EvolutionIntegrityFailure(Stage6EvolutionError):
    """Stored evolution lineage or deterministic replay failed."""


class EvolutionConflict(Stage6EvolutionError):
    """An immutable directive or evolution identity conflicts with stored content."""
