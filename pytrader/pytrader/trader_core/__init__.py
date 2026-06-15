"""
Shim package to expose the public trader_core API under the historical
``pytrader.trader_core`` namespace.

This allows imports like:
    from pytrader.trader_core import TradingEngine, BacktestEngine
"""

# Import from local trader_core modules
from .backtesting.engine import BacktestConfig, BacktestEngine
from .execution.live_engine import EngineConfig, TradingEngine
from .portfolio.service import PortfolioService
from .portfolio.metrics import TradeMetrics
from .strategies.base import BaseStrategy
from .strategies import (
    BollingerMeanReversionStrategy,
    DualSMAMomentumStrategy,
    SMAMomentumStrategy,
    VWAPReversionStrategy,
)

__all__ = [
    "PortfolioService",
    "TradingEngine",
    "EngineConfig",
    "BacktestEngine",
    "BacktestConfig",
    "TradeMetrics",
    "BaseStrategy",
    "SMAMomentumStrategy",
    "DualSMAMomentumStrategy",
    "BollingerMeanReversionStrategy",
    "VWAPReversionStrategy",
]

