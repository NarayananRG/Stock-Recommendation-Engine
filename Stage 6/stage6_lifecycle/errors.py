"""Stage 6.2F lifecycle failures."""


class Stage6LifecycleError(ValueError):
    pass


class LifecycleIntegrityFailure(Stage6LifecycleError):
    pass


class LifecycleConflict(Stage6LifecycleError):
    pass
