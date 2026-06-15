"""
Technical indicators for PyTrader SDK.

Common indicators that can be used in custom strategies.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def SMA(data: pd.Series, period: int) -> pd.Series:
    """
    Simple Moving Average.
    
    Args:
        data: Price series (typically 'close')
        period: Number of periods for moving average
    
    Returns:
        Series with SMA values
    """
    return data.rolling(window=period, min_periods=period).mean()


def EMA(data: pd.Series, period: int, alpha: Optional[float] = None) -> pd.Series:
    """
    Exponential Moving Average.
    
    Args:
        data: Price series (typically 'close')
        period: Number of periods for moving average
        alpha: Smoothing factor (if None, uses 2/(period+1))
    
    Returns:
        Series with EMA values
    """
    if alpha is None:
        alpha = 2.0 / (period + 1.0)
    return data.ewm(alpha=alpha, adjust=False).mean()


def VWAP(df: pd.DataFrame, price_col: str = 'price', volume_col: str = 'volume') -> pd.Series:
    """
    Volume Weighted Average Price.
    
    Args:
        df: DataFrame with price and volume columns
        price_col: Name of price column
        volume_col: Name of volume column
    
    Returns:
        Series with VWAP values
    """
    if price_col not in df.columns or volume_col not in df.columns:
        raise ValueError(f"DataFrame must have '{price_col}' and '{volume_col}' columns")
    
    typical_price = df[price_col]
    volume = df[volume_col]
    
    cumulative_tpv = (typical_price * volume).cumsum()
    cumulative_volume = volume.cumsum()
    
    return cumulative_tpv / cumulative_volume


def RSI(data: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index.
    
    Args:
        data: Price series (typically 'close')
        period: Number of periods (default: 14)
    
    Returns:
        Series with RSI values (0-100)
    """
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def MACD(
    data: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Moving Average Convergence Divergence.
    
    Args:
        data: Price series (typically 'close')
        fast_period: Fast EMA period (default: 12)
        slow_period: Slow EMA period (default: 26)
        signal_period: Signal line EMA period (default: 9)
    
    Returns:
        Tuple of (MACD line, Signal line, Histogram)
    """
    ema_fast = EMA(data, fast_period)
    ema_slow = EMA(data, slow_period)
    macd_line = ema_fast - ema_slow
    signal_line = EMA(macd_line, signal_period)
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def BollingerBands(
    data: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.
    
    Args:
        data: Price series (typically 'close')
        period: Moving average period (default: 20)
        std_dev: Standard deviation multiplier (default: 2.0)
    
    Returns:
        Tuple of (Upper band, Middle band (SMA), Lower band)
    """
    middle = SMA(data, period)
    std = data.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    
    return upper, middle, lower


__all__ = [
    "SMA",
    "EMA",
    "VWAP",
    "RSI",
    "MACD",
    "BollingerBands",
]

