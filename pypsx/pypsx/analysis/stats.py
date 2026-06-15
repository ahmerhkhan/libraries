"""
Core Statistical Functions for PyPSX Analysis Module

This module provides essential statistical functions for analyzing stock data,
including returns calculation, volatility analysis, and correlation metrics.
All functions are designed to work with pandas DataFrames and support both
single-stock and multi-stock analysis.
"""

import pandas as pd
import numpy as np
from typing import Union, Dict, Optional


def _get_price_column(df: pd.DataFrame, column: str = None) -> str:
    """Helper function to auto-detect price column."""
    if column is not None:
        if column not in df.columns:
            raise ValueError(f"Column '{column}' not found in DataFrame. Available columns: {list(df.columns)}")
        return column
    
    # Auto-detect column - prioritize PSX column names
    psx_columns = ['LDCP', 'CURRENT', 'CLOSE', 'Close']
    standard_columns = ['CLOSE', 'Close', 'close']
    
    # First try PSX-specific column names
    for col in psx_columns:
        if col in df.columns:
            return col
    
    # Then try standard column names
    for col in standard_columns:
        if col in df.columns:
            return col
    
    # If no close price column found, raise error with helpful message
    available_cols = list(df.columns)
    raise ValueError(f"No close price column found. Available columns: {available_cols}. "
                    f"Expected one of: {psx_columns + standard_columns}")


def returns(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
            column: str = None) -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate daily percentage returns.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames (symbol -> DataFrame)
        column: Column name to calculate returns for (auto-detects if None)
    
    Returns:
        Series of returns or dictionary of symbol -> returns Series
        
    Example:
        >>> import pypsx
        >>> ticker = pypsx.PSXTicker("OGDC")
        >>> df = ticker.history(period="1m")
        >>> rets = returns(df)
        >>> print(rets.head())
    """
    if isinstance(df, dict):
        return {symbol: returns(data, column) for symbol, data in df.items()}
    
    price_col = _get_price_column(df, column)
    # Calculate returns - fill NaN values in price column first (forward fill then backward fill)
    prices = df[price_col].ffill().bfill()
    rets = prices.pct_change()
    # Drop NaN but keep empty series if all NaN
    result = rets.dropna()
    # If result is empty, return series with NaN instead of empty
    if len(result) == 0 and len(rets) > 0:
        return rets
    return result


def volatility(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
               window: int = 30, 
               column: str = None) -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate rolling volatility (standard deviation of returns).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        window: Rolling window size in days (default: 30)
        column: Column name to calculate volatility for (default: 'Close')
    
    Returns:
        Series of rolling volatility or dictionary of symbol -> volatility Series
        
    Example:
        >>> vol = volatility(df, window=20)
        >>> print(vol.tail())
    """
    if isinstance(df, dict):
        return {symbol: volatility(data, window, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    vol = rets.rolling(window).std()
    # Replace NaN with 0 for first window-1 values, but keep valid NaN where data is truly missing
    # Only fill initial NaN from rolling window, not missing data NaN
    return vol.fillna(0)


def correlation(df1: pd.DataFrame, 
                df2: pd.DataFrame, 
                column: str = None) -> float:
    """
    Calculate correlation between two stock return series.
    
    Args:
        df1: First stock DataFrame
        df2: Second stock DataFrame
        column: Column name to calculate correlation for (default: 'Close')
    
    Returns:
        Correlation coefficient between the two stocks
        
    Example:
        >>> ogdc = pypsx.PSXTicker("OGDC").history(period="1y")
        >>> ppl = pypsx.PSXTicker("PPL").history(period="1y")
        >>> corr = correlation(ogdc, ppl)
        >>> print(f"OGDC-PPL correlation: {corr:.3f}")
    """
    rets1 = returns(df1, column)
    rets2 = returns(df2, column)
    
    # Align the series by date
    aligned_rets = pd.concat([rets1, rets2], axis=1, join='inner')
    if len(aligned_rets) < 2:
        return np.nan
    
    return aligned_rets.iloc[:, 0].corr(aligned_rets.iloc[:, 1])


def correlation_matrix(df_dict: Dict[str, pd.DataFrame], 
                      column: str = None) -> pd.DataFrame:
    """
    Calculate correlation matrix for multiple stocks.
    
    Args:
        df_dict: Dictionary of symbol -> DataFrame
        column: Column name to calculate correlations for (default: 'Close')
    
    Returns:
        Correlation matrix DataFrame
        
    Example:
        >>> stocks = {
        ...     "OGDC": pypsx.PSXTicker("OGDC").history(period="1y"),
        ...     "PPL": pypsx.PSXTicker("PPL").history(period="1y"),
        ...     "KEL": pypsx.PSXTicker("KEL").history(period="1y")
        ... }
        >>> corr_matrix = correlation_matrix(stocks)
        >>> print(corr_matrix)
    """
    if len(df_dict) < 2:
        raise ValueError("Need at least 2 stocks to calculate correlation matrix")
    
    # Calculate returns for all stocks
    returns_dict = {symbol: returns(df, column) for symbol, df in df_dict.items()}
    
    # Create DataFrame with all returns aligned by date
    returns_df = pd.DataFrame(returns_dict)
    
    return returns_df.corr()


def beta(df_stock: pd.DataFrame, 
         df_market: pd.DataFrame, 
         column: str = None) -> float:
    """
    Calculate beta (systematic risk) of a stock relative to market.
    
    Args:
        df_stock: Stock DataFrame
        df_market: Market index DataFrame (e.g., KSE100)
        column: Column name to calculate beta for (default: 'Close')
    
    Returns:
        Beta coefficient
        
    Example:
        >>> ogdc = pypsx.PSXTicker("OGDC").history(period="1y")
        >>> kse100 = pypsx.index_constituents("KSE100")
        >>> beta_val = beta(ogdc, kse100)
        >>> print(f"OGDC beta: {beta_val:.3f}")
    """
    stock_rets = returns(df_stock, column)
    market_rets = returns(df_market, column)
    
    # Align the series by date
    aligned_rets = pd.concat([stock_rets, market_rets], axis=1, join='inner')
    if len(aligned_rets) < 2:
        return np.nan
    
    stock_rets_aligned = aligned_rets.iloc[:, 0]
    market_rets_aligned = aligned_rets.iloc[:, 1]
    
    # Calculate covariance and variance
    covariance = np.cov(stock_rets_aligned, market_rets_aligned)[0, 1]
    market_variance = np.var(market_rets_aligned)
    
    if market_variance == 0:
        return np.nan
    
    return covariance / market_variance


def skewness(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
             column: str = None) -> Union[float, Dict[str, float]]:
    """
    Calculate skewness of returns (measure of asymmetry).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate skewness for (default: 'Close')
    
    Returns:
        Skewness value or dictionary of symbol -> skewness
        
    Example:
        >>> skew = skewness(df)
        >>> print(f"Returns skewness: {skew:.3f}")
    """
    if isinstance(df, dict):
        return {symbol: skewness(data, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) < 3:
        return np.nan
    
    return rets.skew()


def kurtosis(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
             column: str = None) -> Union[float, Dict[str, float]]:
    """
    Calculate kurtosis of returns (measure of tail heaviness).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        column: Column name to calculate kurtosis for (default: 'Close')
    
    Returns:
        Kurtosis value or dictionary of symbol -> kurtosis
        
    Example:
        >>> kurt = kurtosis(df)
        >>> print(f"Returns kurtosis: {kurt:.3f}")
    """
    if isinstance(df, dict):
        return {symbol: kurtosis(data, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) < 4:
        return np.nan
    
    return rets.kurtosis()


def var(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
        confidence_level: float = 0.05, 
        column: str = None) -> Union[float, Dict[str, float]]:
    """
    Calculate Value at Risk (VaR) at specified confidence level.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        confidence_level: Confidence level (default: 0.05 for 95% VaR)
        column: Column name to calculate VaR for (default: 'Close')
    
    Returns:
        VaR value or dictionary of symbol -> VaR
        
    Example:
        >>> var_95 = var(df, confidence_level=0.05)
        >>> print(f"95% VaR: {var_95:.3f}")
    """
    if isinstance(df, dict):
        return {symbol: var(data, confidence_level, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) < 10:
        return np.nan
    
    return np.percentile(rets, confidence_level * 100)


def cvar(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
         confidence_level: float = 0.05, 
         column: str = None) -> Union[float, Dict[str, float]]:
    """
    Calculate Conditional Value at Risk (CVaR) - expected loss beyond VaR.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        confidence_level: Confidence level (default: 0.05 for 95% CVaR)
        column: Column name to calculate CVaR for (default: 'Close')
    
    Returns:
        CVaR value or dictionary of symbol -> CVaR
        
    Example:
        >>> cvar_95 = cvar(df, confidence_level=0.05)
        >>> print(f"95% CVaR: {cvar_95:.3f}")
    """
    if isinstance(df, dict):
        return {symbol: cvar(data, confidence_level, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) < 10:
        return np.nan
    
    var_value = var(df, confidence_level, column)
    return rets[rets <= var_value].mean()


def autocorrelation(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                    lag: int = 1, 
                    column: str = None) -> Union[float, Dict[str, float]]:
    """
    Calculate autocorrelation of returns at specified lag.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        lag: Lag for autocorrelation calculation (default: 1)
        column: Column name to calculate autocorrelation for (default: 'Close')
    
    Returns:
        Autocorrelation value or dictionary of symbol -> autocorrelation
        
    Example:
        >>> autocorr = autocorrelation(df, lag=1)
        >>> print(f"1-day autocorrelation: {autocorr:.3f}")
    """
    if isinstance(df, dict):
        return {symbol: autocorrelation(data, lag, column) for symbol, data in df.items()}
    
    rets = returns(df, column)
    if len(rets) < lag + 1:
        return np.nan
    
    return rets.autocorr(lag=lag)
