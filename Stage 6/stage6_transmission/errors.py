class Stage6TransmissionError(ValueError): pass
class TransmissionIntegrityFailure(Stage6TransmissionError): pass
class TransmissionConflict(Stage6TransmissionError): pass
