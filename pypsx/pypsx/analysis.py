"""
Analysis module wrapper for PyPSX library.

Provides easy access to analysis functions from the analysis package.
"""

# Re-export all analysis functions for convenience
from pypsx.analysis.stats import (
    returns,
    volatility,
    correlation,
    correlation_matrix,
    beta,
    skewness,
    kurtosis,
    var,
    cvar,
    autocorrelation,
)

from pypsx.analysis.indicators import (
    moving_average,
    exponential_moving_average,
    bollinger_bands,
    rsi,
    macd,
    stochastic,
    williams_r,
    atr,
    adx,
    cci,
    obv,
    vwap,
)

from pypsx.analysis.performance import (
    sharpe_ratio,
    sortino_ratio,
    calmar_ratio,
    cumulative_returns,
    annualized_return,
    annualized_volatility,
    drawdown,
    max_drawdown,
    drawdown_duration,
    information_ratio,
    treynor_ratio,
    jensen_alpha,
    win_rate,
    profit_loss_ratio,
    recovery_factor,
    performance_summary,
)

from pypsx.analysis.insights import (
    interpret_stock,
    interpret_portfolio,
    market_sentiment_analysis,
)

from analysis import (
    quick_analysis,
    portfolio_analysis,
)

__all__ = [
    # Statistics
    "returns",
    "volatility",
    "correlation",
    "correlation_matrix",
    "beta",
    "skewness",
    "kurtosis",
    "var",
    "cvar",
    "autocorrelation",
    # Indicators
    "moving_average",
    "exponential_moving_average",
    "bollinger_bands",
    "rsi",
    "macd",
    "stochastic",
    "williams_r",
    "atr",
    "adx",
    "cci",
    "obv",
    "vwap",
    # Performance
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "cumulative_returns",
    "annualized_return",
    "annualized_volatility",
    "drawdown",
    "max_drawdown",
    "drawdown_duration",
    "information_ratio",
    "treynor_ratio",
    "jensen_alpha",
    "win_rate",
    "profit_loss_ratio",
    "recovery_factor",
    "performance_summary",
    # Insights
    "interpret_stock",
    "interpret_portfolio",
    "quick_analysis",
    "portfolio_analysis",
    "market_sentiment_analysis",
]

