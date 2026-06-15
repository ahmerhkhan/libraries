"""
PyTrader Data Module.

Provides market data services for both live and historical trading.
"""

from .pypsx_service import PyPSXService
from .psx_terminal_service import PSXTerminalService
from .websocket_data_service import WebSocketDataService
from .data_mode import TradingMode
from .bar_aggregator import BarAggregator, AggregatedBar, TickData
from .websocket_stream_provider import WebSocketStreamProvider

__all__ = [
    "PyPSXService",
    "PSXTerminalService",
    "WebSocketDataService",  # DEPRECATED: Will be removed after migration
    "TradingMode",
    "BarAggregator",
    "AggregatedBar",
    "TickData",
    "WebSocketStreamProvider",
]
