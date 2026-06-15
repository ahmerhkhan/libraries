"""
Shim to expose portfolio subpackage via ``pytrader.trader_core.portfolio``.
"""

from .service import PortfolioService
from .metrics import TradeMetrics, compute_portfolio_metrics

