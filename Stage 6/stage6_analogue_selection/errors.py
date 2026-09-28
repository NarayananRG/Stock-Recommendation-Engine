class Stage6AnalogueSelectionError(ValueError):
    pass


class AnalogueSelectionIntegrityFailure(Stage6AnalogueSelectionError):
    pass


class AnalogueSelectionConflict(Stage6AnalogueSelectionError):
    pass
