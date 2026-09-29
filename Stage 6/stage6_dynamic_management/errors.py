class Stage6DynamicManagementError(ValueError):
    pass


class DynamicManagementConflict(Stage6DynamicManagementError):
    pass


class DynamicManagementIntegrityFailure(Stage6DynamicManagementError):
    pass
