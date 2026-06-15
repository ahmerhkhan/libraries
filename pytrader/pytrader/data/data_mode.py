"""
Trading Mode Enum for PyTrader SDK.

Enforces strict separation between live streaming, backtesting, and warm-start modes.
"""

from enum import Enum


class TradingMode(Enum):
    """
    Trading mode determines which data source is used for market data.
    
    Modes:
        LIVE: Real-time WebSocket streaming from psx-terminal (zero delay, fail-fast)
        BACKTEST: Historical data from pypsx library (15-min delay acceptable for backtesting)
        WARM_START: Start with pypsx replay (market open → now), then switch to WebSocket
    """
    LIVE = "live"
    BACKTEST = "backtest"
    WARM_START = "warm_start"
    
    def __str__(self) -> str:
        return self.value
    
    @property
    def requires_websocket(self) -> bool:
        """Check if mode requires WebSocket connection."""
        return self in (TradingMode.LIVE, TradingMode.WARM_START)
    
    @property
    def allows_historical(self) -> bool:
        """Check if mode allows historical/delayed data."""
        return self in (TradingMode.BACKTEST, TradingMode.WARM_START)
    
    @property
    def allows_rest_fallback(self) -> bool:
        """Check if mode allows REST API fallback (for non-price data only)."""
        # In LIVE mode, NO fallback to REST for price data
        # Only metadata/company info can use REST
        return self != TradingMode.LIVE


__all__ = ["TradingMode"]
