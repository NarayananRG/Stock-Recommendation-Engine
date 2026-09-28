class Stage6HistoricalAnalogueError(ValueError):
    pass


class HistoricalAnalogueIntegrityFailure(Stage6HistoricalAnalogueError):
    pass


class HistoricalAnalogueConflict(Stage6HistoricalAnalogueError):
    pass
