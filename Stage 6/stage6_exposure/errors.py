class Stage6ExposureError(ValueError): pass
class ExposureIntegrityFailure(Stage6ExposureError): pass
class ExposureVersionConflict(Stage6ExposureError): pass
