"""Custom exceptions for PyTrader SDK."""


class PyTraderError(Exception):
    """Base exception for PyTrader SDK."""
    pass


class InsufficientBalanceError(PyTraderError):
    """Raised when account balance is insufficient for an order."""
    pass


class InvalidOrderError(PyTraderError):
    """Raised when an order is invalid."""
    pass


class OrderNotFoundError(PyTraderError):
    """Raised when an order is not found."""
    pass


class DataProviderError(PyTraderError):
    """Raised when there's an error with the data provider."""
    pass


class SymbolNotFoundError(DataProviderError):
    """Raised when a symbol is not found."""
    pass


class InvalidSymbolError(DataProviderError):
    """Raised when a symbol is invalid."""
    pass

