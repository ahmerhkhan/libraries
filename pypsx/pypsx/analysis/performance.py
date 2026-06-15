"""
Financial Performance Metrics for PyPSX Analysis Module

This module provides comprehensive financial performance metrics including
risk-adjusted returns, drawdown analysis, and comparative performance analytics.
All functions are designed for quantitative analysis and portfolio management.
"""

import pandas as pd
import numpy as np
from typing import Union, Dict, Optional, Tuple
from .stats import returns, _get_price_column


def sharpe_ratio(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                 risk_free_rate: float = 0.08, 
                 column: str = None,
                 periods_per_year: int = 252) -> Union[float, Dict[str, float]]:
    """
    Calculate Sharpe ratio (risk-adjusted return).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        risk_free_rate: Annual risk-free rate (default: 0.08 for 8%)
        column: Column name to calculate Sharpe ratio for (auto-detects if None)
        periods_per_year: Trading periods per year (default: 252)
    
    Returns:
        Sharpe ratio value or dictionary of symbol -> Sharpe ratio
        
    Example:
        >>> sharpe = sharpe_ratio(df, risk_free_rate=0.08)
        >>> print(f"Sharpe ratio: {sharpe:.3f}")
    """
    if isinstance(df, dict):
        return {symbol: sharpe_ratio(data, risk_free_rate, column, periods_per_year) 
                for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) < 2:
        return np.nan
    
    excess_returns = rets - (risk_free_rate / periods_per_year)
    
    if excess_returns.std() == 0:
        return np.nan
    
    return (excess_returns.mean() / excess_returns.std()) * (periods_per_year ** 0.5)


def sortino_ratio(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                  risk_free_rate: float = 0.08, 
                  column: str = None,
                  periods_per_year: int = 252) -> Union[float, Dict[str, float]]:
    """
    Calculate Sortino ratio (downside risk-adjusted return).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        risk_free_rate: Annual risk-free rate (default: 0.08 for 8%)
        column: Column name to calculate Sortino ratio for (default: 'Close')
        periods_per_year: Trading periods per year (default: 252)
    
    Returns:
        Sortino ratio value or dictionary of symbol -> Sortino ratio
        
    Example:
        >>> sortino = sortino_ratio(df, risk_free_rate=0.08)
        >>> print(f"Sortino ratio: {sortino:.3f}")
    """
    if isinstance(df, dict):
        return {symbol: sortino_ratio(data, risk_free_rate, column, periods_per_year) 
                for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) < 2:
        return np.nan
    
    excess_returns = rets - (risk_free_rate / periods_per_year)
    downside_returns = excess_returns[excess_returns < 0]
    
    if len(downside_returns) == 0 or downside_returns.std() == 0:
        return np.nan
    
    downside_deviation = downside_returns.std()
    return (excess_returns.mean() / downside_deviation) * (periods_per_year ** 0.5)


def calmar_ratio(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                 column: str = None) -> Union[float, Dict[str, float]]:
    """
    Calculate Calmar ratio (annual return / maximum drawdown).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate Calmar ratio for (default: 'Close')
    
    Returns:
        Calmar ratio value or dictionary of symbol -> Calmar ratio
        
    Example:
        >>> calmar = calmar_ratio(df)
        >>> print(f"Calmar ratio: {calmar:.3f}")
    """
    if isinstance(df, dict):
        return {symbol: calmar_ratio(data, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) < 2:
        return np.nan
    
    annual_return = (1 + rets).prod() ** (252 / len(rets)) - 1
    max_drawdown = abs(drawdown(df, column).min())
    
    if max_drawdown == 0:
        return np.nan
    
    return annual_return / max_drawdown


def cumulative_returns(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                      column: str = None) -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate cumulative returns.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate cumulative returns for (auto-detects if None)
    
    Returns:
        Series of cumulative returns or dictionary of symbol -> cumulative returns Series
        
    Example:
        >>> cum_rets = cumulative_returns(df)
        >>> print(f"Total return: {cum_rets.iloc[-1]:.2%}")
    """
    if isinstance(df, dict):
        return {symbol: cumulative_returns(data, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    return (1 + rets).cumprod() - 1


def annualized_return(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                     column: str = None,
                     periods_per_year: int = 252) -> Union[float, Dict[str, float]]:
    """
    Calculate annualized return.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate annualized return for (default: 'Close')
        periods_per_year: Trading periods per year (default: 252)
    
    Returns:
        Annualized return value or dictionary of symbol -> annualized return
        
    Example:
        >>> ann_ret = annualized_return(df)
        >>> print(f"Annualized return: {ann_ret:.2%}")
    """
    if isinstance(df, dict):
        return {symbol: annualized_return(data, column, periods_per_year) 
                for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) < 2:
        return np.nan
    
    return (1 + rets).prod() ** (periods_per_year / len(rets)) - 1


def annualized_volatility(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                         column: str = None,
                         periods_per_year: int = 252) -> Union[float, Dict[str, float]]:
    """
    Calculate annualized volatility.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate annualized volatility for (default: 'Close')
        periods_per_year: Trading periods per year (default: 252)
    
    Returns:
        Annualized volatility value or dictionary of symbol -> annualized volatility
        
    Example:
        >>> ann_vol = annualized_volatility(df)
        >>> print(f"Annualized volatility: {ann_vol:.2%}")
    """
    if isinstance(df, dict):
        return {symbol: annualized_volatility(data, column, periods_per_year) 
                for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) < 2:
        return np.nan
    
    return rets.std() * (periods_per_year ** 0.5)


def drawdown(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
             column: str = None) -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate drawdown series.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate drawdown for (default: 'Close')
    
    Returns:
        Series of drawdown values or dictionary of symbol -> drawdown Series
        
    Example:
        >>> dd = drawdown(df)
        >>> print(f"Maximum drawdown: {dd.min():.2%}")
    """
    if isinstance(df, dict):
        return {symbol: drawdown(data, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    cumulative = (1 + rets).cumprod()
    running_max = cumulative.cummax()
    return (cumulative - running_max) / running_max


def max_drawdown(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                 column: str = None) -> Union[float, Dict[str, float]]:
    """
    Calculate maximum drawdown.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate max drawdown for (default: 'Close')
    
    Returns:
        Maximum drawdown value or dictionary of symbol -> max drawdown
        
    Example:
        >>> max_dd = max_drawdown(df)
        >>> print(f"Maximum drawdown: {max_dd:.2%}")
    """
    if isinstance(df, dict):
        return {symbol: max_drawdown(data, column) for symbol, data in df.items()}
    
    dd = drawdown(df, column)
    return dd.min()


def drawdown_duration(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                     column: str = None) -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate drawdown duration (days in drawdown).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate drawdown duration for (default: 'Close')
    
    Returns:
        Series of drawdown duration or dictionary of symbol -> drawdown duration Series
        
    Example:
        >>> dd_duration = drawdown_duration(df)
        >>> print(f"Max drawdown duration: {dd_duration.max()} days")
    """
    if isinstance(df, dict):
        return {symbol: drawdown_duration(data, column) for symbol, data in df.items()}
    
    dd = drawdown(df, column)
    in_drawdown = dd < 0
    
    # Calculate consecutive days in drawdown
    duration = pd.Series(index=dd.index, dtype=float)
    current_duration = 0
    
    for i, is_dd in enumerate(in_drawdown):
        if is_dd:
            current_duration += 1
        else:
            current_duration = 0
        duration.iloc[i] = current_duration
    
    return duration


def information_ratio(df_stock: pd.DataFrame, 
                     df_benchmark: pd.DataFrame, 
                     column: str = None) -> float:
    """
    Calculate information ratio (active return / tracking error).
    
    Args:
        df_stock: Stock DataFrame
        df_benchmark: Benchmark DataFrame
        column: Column name to calculate information ratio for (default: 'Close')
    
    Returns:
        Information ratio value
        
    Example:
        >>> ogdc = pypsx.PSXTicker("OGDC").history(period="1y")
        >>> kse100 = pypsx.index_constituents("KSE100")
        >>> ir = information_ratio(ogdc, kse100)
        >>> print(f"Information ratio: {ir:.3f}")
    """
    stock_rets = returns(df_stock, column)
    benchmark_rets = returns(df_benchmark, column)
    
    # Align the series by date
    aligned_rets = pd.concat([stock_rets, benchmark_rets], axis=1, join='inner')
    if len(aligned_rets) < 2:
        return np.nan
    
    stock_rets_aligned = aligned_rets.iloc[:, 0]
    benchmark_rets_aligned = aligned_rets.iloc[:, 1]
    
    active_returns = stock_rets_aligned - benchmark_rets_aligned
    tracking_error = active_returns.std()
    
    if tracking_error == 0:
        return np.nan
    
    return active_returns.mean() / tracking_error


def treynor_ratio(df_stock: pd.DataFrame, 
                  df_market: pd.DataFrame, 
                  risk_free_rate: float = 0.08,
                  column: str = None,
                  periods_per_year: int = 252) -> float:
    """
    Calculate Treynor ratio (excess return / beta).
    
    Args:
        df_stock: Stock DataFrame
        df_market: Market DataFrame
        risk_free_rate: Annual risk-free rate (default: 0.08 for 8%)
        column: Column name to calculate Treynor ratio for (default: 'Close')
        periods_per_year: Trading periods per year (default: 252)
    
    Returns:
        Treynor ratio value
        
    Example:
        >>> ogdc = pypsx.PSXTicker("OGDC").history(period="1y")
        >>> kse100 = pypsx.index_constituents("KSE100")
        >>> treynor = treynor_ratio(ogdc, kse100)
        >>> print(f"Treynor ratio: {treynor:.3f}")
    """
    from .stats import beta
    
    stock_rets = returns(df_stock, column)
    market_rets = returns(df_market, column)
    
    # Align the series by date
    aligned_rets = pd.concat([stock_rets, market_rets], axis=1, join='inner')
    if len(aligned_rets) < 2:
        return np.nan
    
    stock_rets_aligned = aligned_rets.iloc[:, 0]
    market_rets_aligned = aligned_rets.iloc[:, 1]
    
    excess_return = stock_rets_aligned.mean() - (risk_free_rate / periods_per_year)
    stock_beta = beta(df_stock, df_market, column)
    
    if stock_beta == 0 or np.isnan(stock_beta):
        return np.nan
    
    return excess_return / stock_beta


def jensen_alpha(df_stock: pd.DataFrame, 
                 df_market: pd.DataFrame, 
                 risk_free_rate: float = 0.08,
                 column: str = None,
                 periods_per_year: int = 252) -> float:
    """
    Calculate Jensen's alpha (CAPM alpha).
    
    Args:
        df_stock: Stock DataFrame
        df_market: Market DataFrame
        risk_free_rate: Annual risk-free rate (default: 0.08 for 8%)
        column: Column name to calculate Jensen's alpha for (default: 'Close')
        periods_per_year: Trading periods per year (default: 252)
    
    Returns:
        Jensen's alpha value
        
    Example:
        >>> ogdc = pypsx.PSXTicker("OGDC").history(period="1y")
        >>> kse100 = pypsx.index_constituents("KSE100")
        >>> alpha = jensen_alpha(ogdc, kse100)
        >>> print(f"Jensen's alpha: {alpha:.3f}")
    """
    from .stats import beta
    
    stock_rets = returns(df_stock, column)
    market_rets = returns(df_market, column)
    
    # Align the series by date
    aligned_rets = pd.concat([stock_rets, market_rets], axis=1, join='inner')
    if len(aligned_rets) < 2:
        return np.nan
    
    stock_rets_aligned = aligned_rets.iloc[:, 0]
    market_rets_aligned = aligned_rets.iloc[:, 1]
    
    risk_free_daily = risk_free_rate / periods_per_year
    stock_beta = beta(df_stock, df_market, column)
    
    if np.isnan(stock_beta):
        return np.nan
    
    expected_return = risk_free_daily + stock_beta * (market_rets_aligned.mean() - risk_free_daily)
    alpha = stock_rets_aligned.mean() - expected_return
    
    return alpha


def win_rate(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
             column: str = None) -> Union[float, Dict[str, float]]:
    """
    Calculate win rate (percentage of positive return days).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate win rate for (default: 'Close')
    
    Returns:
        Win rate value or dictionary of symbol -> win rate
        
    Example:
        >>> wr = win_rate(df)
        >>> print(f"Win rate: {wr:.2%}")
    """
    if isinstance(df, dict):
        return {symbol: win_rate(data, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) == 0:
        return np.nan
    
    return (rets > 0).mean()


def profit_loss_ratio(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                      column: str = None) -> Union[float, Dict[str, float]]:
    """
    Calculate profit/loss ratio (average gain / average loss).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate P/L ratio for (default: 'Close')
    
    Returns:
        P/L ratio value or dictionary of symbol -> P/L ratio
        
    Example:
        >>> pl_ratio = profit_loss_ratio(df)
        >>> print(f"P/L ratio: {pl_ratio:.2f}")
    """
    if isinstance(df, dict):
        return {symbol: profit_loss_ratio(data, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) == 0:
        return np.nan
    
    gains = rets[rets > 0]
    losses = rets[rets < 0]
    
    if len(gains) == 0 or len(losses) == 0:
        return np.nan
    
    avg_gain = gains.mean()
    avg_loss = abs(losses.mean())
    
    if avg_loss == 0:
        return np.nan
    
    return avg_gain / avg_loss


def recovery_factor(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                    column: str = None) -> Union[float, Dict[str, float]]:
    """
    Calculate recovery factor (total return / maximum drawdown).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate recovery factor for (default: 'Close')
    
    Returns:
        Recovery factor value or dictionary of symbol -> recovery factor
        
    Example:
        >>> rf = recovery_factor(df)
        >>> print(f"Recovery factor: {rf:.2f}")
    """
    if isinstance(df, dict):
        return {symbol: recovery_factor(data, column) for symbol, data in df.items()}
    
    total_return = cumulative_returns(df, column).iloc[-1]
    max_dd = abs(max_drawdown(df, column))
    
    if max_dd == 0:
        return np.nan
    
    return total_return / max_dd


def performance_summary(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                       risk_free_rate: float = 0.08,
                       column: str = None) -> Union[Dict, Dict[str, Dict]]:
    """
    Calculate comprehensive performance summary.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        risk_free_rate: Annual risk-free rate (default: 0.08 for 8%)
        column: Column name to calculate performance metrics for (default: 'Close')
    
    Returns:
        Dictionary of performance metrics or dictionary of symbol -> metrics
        
    Example:
        >>> summary = performance_summary(df)
        >>> print(f"Sharpe: {summary['sharpe_ratio']:.3f}")
        >>> print(f"Max DD: {summary['max_drawdown']:.2%}")
    """
    if isinstance(df, dict):
        return {symbol: performance_summary(data, risk_free_rate, column) 
                for symbol, data in df.items()}
    
    return {
        'total_return': cumulative_returns(df, column).iloc[-1],
        'annualized_return': annualized_return(df, column),
        'annualized_volatility': annualized_volatility(df, column),
        'sharpe_ratio': sharpe_ratio(df, risk_free_rate, column),
        'sortino_ratio': sortino_ratio(df, risk_free_rate, column),
        'calmar_ratio': calmar_ratio(df, column),
        'max_drawdown': max_drawdown(df, column),
        'win_rate': win_rate(df, column),
        'profit_loss_ratio': profit_loss_ratio(df, column),
        'recovery_factor': recovery_factor(df, column)
    }
