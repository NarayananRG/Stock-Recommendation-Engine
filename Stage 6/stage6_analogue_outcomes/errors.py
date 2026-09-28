class Stage6AnalogueOutcomeError(ValueError):
    pass


class AnalogueOutcomeIntegrityFailure(Stage6AnalogueOutcomeError):
    pass


class AnalogueOutcomeConflict(Stage6AnalogueOutcomeError):
    pass
