class Stage6RecursiveThesisError(Exception):
    pass


class RecursiveThesisIntegrityFailure(Stage6RecursiveThesisError):
    pass


class RecursiveThesisConflict(Stage6RecursiveThesisError):
    pass
