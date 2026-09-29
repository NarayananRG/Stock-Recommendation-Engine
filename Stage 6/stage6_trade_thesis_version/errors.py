class Stage6TradeThesisVersionError(Exception):
    pass


class TradeThesisVersionIntegrityFailure(Stage6TradeThesisVersionError):
    pass


class TradeThesisVersionConflict(Stage6TradeThesisVersionError):
    pass
