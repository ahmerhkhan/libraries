class PSXError(Exception):
    pass


class PSXHTTPError(PSXError):
    pass


class PSXTimeoutError(PSXError):
    pass


class PSXNotFoundError(PSXError):
    pass


class PSXScopeError(PSXError):
    pass


