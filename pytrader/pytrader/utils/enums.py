"""Enums for PyTrader SDK."""

from enum import Enum


class OrderSide(str, Enum):
    """Order side (buy or sell)."""
    
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type."""
    
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    """Order status."""
    
    PENDING = "pending"
    QUEUED = "queued"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(str, Enum):
    """Time in force for orders."""
    
    DAY = "day"  # Order expires at end of trading day
    GTC = "gtc"  # Good Till Cancel - order remains active until filled or cancelled
    IOC = "ioc"  # Immediate Or Cancel - order must be filled immediately or cancelled
    FOK = "fok"  # Fill Or Kill - order must be filled completely or cancelled

