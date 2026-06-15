"""
PyPSX SDK - run strategies locally, stream telemetry to the backend, and
monitor everything from the dashboard.

Bots execute entirely on the founder's machines via the SDK. The backend acts
as an authenticated data + telemetry hub (no remote strategy execution).
"""

# Primary client - dual-endpoint REST client (doesn't trigger trader_core)
from .client import TradingClient, PyPSXClient, PyTrader

# Authentication (doesn't trigger trader_core)
from .auth import AuthenticationError, require_token, validate_token

# Export indicators (doesn't trigger trader_core)
from . import indicators

# Deprecated: Trader class for local execution (kept for backward compatibility)
# Lazy imports to avoid loading trader_core (which imports backtesting engine) 
# when backend only needs data services like PyPSXService
def __getattr__(name: str):
    """Lazy import for Trader and related classes to avoid loading trader_core on package import."""
    import sys
    
    # Get the current module
    module = sys.modules[__name__]
    
    if name == "Trader":
        from .trader import Trader
        # Store in module dict so 'from pytrader import Trader' works after first access
        setattr(module, "Trader", Trader)
        return Trader
    if name == "Strategy":
        from .strategy import Strategy
        setattr(module, "Strategy", Strategy)
        return Strategy
    if name == "load_strategy":
        from .strategy_loader import load_strategy
        setattr(module, "load_strategy", load_strategy)
        return load_strategy
    if name == "list_strategies":
        from .strategy_loader import list_strategies
        setattr(module, "list_strategies", list_strategies)
        return list_strategies
    if name == "register_strategy":
        from .strategy_loader import register_strategy
        setattr(module, "register_strategy", register_strategy)
        return register_strategy
    if name == "start_dashboard":
        from .dashboard import start_dashboard
        setattr(module, "start_dashboard", start_dashboard)
        return start_dashboard
    if name == "run_backtest":
        from .sdk import run_backtest
        setattr(module, "run_backtest", run_backtest)
        return run_backtest
    if name == "start_paper_trading":
        from .sdk import start_paper_trading
        setattr(module, "start_paper_trading", start_paper_trading)
        return start_paper_trading
    if name == "Streamer":
        from .streamer import Streamer
        setattr(module, "Streamer", Streamer)
        return Streamer
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

# BACKEND-ONLY: These components are for backend internal use only.
# SDK users should NOT import these - they are not part of the public API.
# They are kept in the package for backend to use, but not exported to SDK users.
# from .trader_core import (
#     BacktestEngine,
#     BacktestConfig,
#     TradingEngine,
#     EngineConfig,
#     TradeMetrics,
#     PortfolioService,
# )

__version__ = "2.1.0"

__all__ = [
    # Primary API - account-aware client
    "TradingClient",
    "PyPSXClient",
    "PyTrader",
    # Authentication
    "AuthenticationError",
    "require_token",
    "validate_token",
    # Deprecated - kept for backward compatibility
    "Trader",
    "Strategy",
    "run_backtest",
    "start_paper_trading",
    "start_dashboard",
    "load_strategy",
    "list_strategies",
    "register_strategy",
    "Streamer",
    # Utilities
    "indicators",
    # NOTE: Backend-only components (BacktestEngine, TradingEngine, etc.) are NOT exported
    # SDK users must use PyTrader client only. Backend components are for internal use.
]
