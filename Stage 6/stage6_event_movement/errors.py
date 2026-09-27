class Stage6EventMovementError(ValueError): pass
class EventMovementIntegrityFailure(Stage6EventMovementError): pass
class EventMovementConflict(Stage6EventMovementError): pass
