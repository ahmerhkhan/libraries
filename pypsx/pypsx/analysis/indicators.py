"""
Technical Indicators for PyPSX Analysis Module

This module provides comprehensive technical analysis indicators commonly used
by traders and quantitative analysts. All indicators are implemented using
pandas for efficient vectorized calculations.
"""

import pandas as pd
import numpy as np
from typing import Union, Dict, Tuple, Optional
from .stats import _get_price_column


def moving_average(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                  window: int = 20, 
                  column: str = None) -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate simple moving average.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        window: Moving average window (default: 20)
        column: Column name to calculate MA for (default: 'Close')
    
    Returns:
        Series of moving average or dictionary of symbol -> MA Series
        
    Example:
        >>> ma_20 = moving_average(df, window=20)
        >>> print(ma_20.tail())
    """
    if isinstance(df, dict):
        return {symbol: moving_average(data, window, column) for symbol, data in df.items()}
    
    price_col = _get_price_column(df, column)
    return df[price_col].rolling(window).mean()


def exponential_moving_average(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                             window: int = 20, 
                             column: str = None) -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate exponential moving average.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        window: EMA window (default: 20)
        column: Column name to calculate EMA for (default: 'Close')
    
    Returns:
        Series of EMA or dictionary of symbol -> EMA Series
        
    Example:
        >>> ema_20 = exponential_moving_average(df, window=20)
        >>> print(ema_20.tail())
    """
    if isinstance(df, dict):
        return {symbol: exponential_moving_average(data, window, column) for symbol, data in df.items()}
    
    price_col = _get_price_column(df, column)
    return df[price_col].ewm(span=window).mean()


def bollinger_bands(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
                    window: int = 20, 
                    column: str = None,
                    num_std: float = 2.0) -> Union[Tuple[pd.Series, pd.Series, pd.Series], 
                                                   Dict[str, Tuple[pd.Series, pd.Series, pd.Series]]]:
    """
    Calculate Bollinger Bands (MA, Upper Band, Lower Band).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        window: Moving average window (default: 20)
        column: Column name to calculate bands for (default: 'Close')
        num_std: Number of standard deviations for bands (default: 2.0)
    
    Returns:
        Tuple of (MA, Upper Band, Lower Band) or dictionary of symbol -> tuple
        
    Example:
        >>> ma, upper, lower = bollinger_bands(df)
        >>> print(f"Upper: {upper.iloc[-1]:.2f}, Lower: {lower.iloc[-1]:.2f}")
    """
    if isinstance(df, dict):
        return {symbol: bollinger_bands(data, window, column, num_std) for symbol, data in df.items()}
    
    price_col = _get_price_column(df, column)
    
    ma = moving_average(df, window, column)
    std = df[price_col].rolling(window).std()
    upper = ma + (num_std * std)
    lower = ma - (num_std * std)
    
    return ma, upper, lower


def rsi(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
        window: int = 14, 
        period: int = None,
        column: str = None) -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate Relative Strength Index (RSI).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        window: RSI window (default: 14) - DEPRECATED: use period instead
        period: RSI period (default: 14) - preferred parameter name
        column: Column name to calculate RSI for (default: 'Close')
    
    Returns:
        Series of RSI values or dictionary of symbol -> RSI Series
        
    Example:
        >>> rsi_14 = rsi(df, period=14)
        >>> print(f"Current RSI: {rsi_14.iloc[-1]:.2f}")
    """
    # Support both 'period' and 'window' for backward compatibility
    if period is not None:
        window = period
    
    if isinstance(df, dict):
        return {symbol: rsi(data, window=window, period=None, column=column) for symbol, data in df.items()}
    
    price_col = _get_price_column(df, column)
    
    delta = df[price_col].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    
    rs = avg_gain / avg_loss
    rsi_values = 100 - (100 / (1 + rs))
    
    return rsi_values


def macd(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
         fast: int = 12, 
         slow: int = 26, 
         signal: int = 9, 
         column: str = None) -> Union[Tuple[pd.Series, pd.Series, pd.Series], 
                                        Dict[str, Tuple[pd.Series, pd.Series, pd.Series]]]:
    """
    Calculate MACD (Moving Average Convergence Divergence).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        fast: Fast EMA window (default: 12)
        slow: Slow EMA window (default: 26)
        signal: Signal line EMA window (default: 9)
        column: Column name to calculate MACD for (default: 'Close')
    
    Returns:
        Tuple of (MACD Line, Signal Line, Histogram) or dictionary of symbol -> tuple
        
    Example:
        >>> macd_line, signal_line, histogram = macd(df)
        >>> print(f"MACD: {macd_line.iloc[-1]:.3f}")
    """
    if isinstance(df, dict):
        return {symbol: macd(data, fast, slow, signal, column) for symbol, data in df.items()}
    
    price_col = _get_price_column(df, column)
    
    ema_fast = exponential_moving_average(df, fast, column)
    ema_slow = exponential_moving_average(df, slow, column)
    
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def stochastic(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
               k_window: int = 14, 
               d_window: int = 3,
               high_col: str = 'High',
               low_col: str = 'Low',
               close_col: str = 'Close') -> Union[Tuple[pd.Series, pd.Series], 
                                                  Dict[str, Tuple[pd.Series, pd.Series]]]:
    """
    Calculate Stochastic Oscillator (%K and %D).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        k_window: %K window (default: 14)
        d_window: %D window (default: 3)
        high_col: High price column (default: 'High')
        low_col: Low price column (default: 'Low')
        close_col: Close price column (default: 'Close')
    
    Returns:
        Tuple of (%K, %D) or dictionary of symbol -> tuple
        
    Example:
        >>> k_percent, d_percent = stochastic(df)
        >>> print(f"%K: {k_percent.iloc[-1]:.2f}, %D: {d_percent.iloc[-1]:.2f}")
    """
    if isinstance(df, dict):
        return {symbol: stochastic(data, k_window, d_window, high_col, low_col, close_col) 
                for symbol, data in df.items()}
    
    required_cols = [high_col, low_col, close_col]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Columns {missing_cols} not found in DataFrame. Available columns: {list(df.columns)}")
    
    lowest_low = df[low_col].rolling(k_window).min()
    highest_high = df[high_col].rolling(k_window).max()
    
    k_percent = 100 * ((df[close_col] - lowest_low) / (highest_high - lowest_low))
    d_percent = k_percent.rolling(d_window).mean()
    
    return k_percent, d_percent


def williams_r(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
               window: int = 14,
               high_col: str = 'High',
               low_col: str = 'Low',
               close_col: str = 'Close') -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate Williams %R.
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        window: Williams %R window (default: 14)
        high_col: High price column (default: 'High')
        low_col: Low price column (default: 'Low')
        close_col: Close price column (default: 'Close')
    
    Returns:
        Series of Williams %R values or dictionary of symbol -> Williams %R Series
        
    Example:
        >>> williams_r = williams_r(df)
        >>> print(f"Williams %R: {williams_r.iloc[-1]:.2f}")
    """
    if isinstance(df, dict):
        return {symbol: williams_r(data, window, high_col, low_col, close_col) 
                for symbol, data in df.items()}
    
    required_cols = [high_col, low_col, close_col]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Columns {missing_cols} not found in DataFrame. Available columns: {list(df.columns)}")
    
    highest_high = df[high_col].rolling(window).max()
    lowest_low = df[low_col].rolling(window).min()
    
    williams_r_values = -100 * ((highest_high - df[close_col]) / (highest_high - lowest_low))
    
    return williams_r_values


def atr(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
        window: int = 14,
        high_col: str = 'High',
        low_col: str = 'Low',
        close_col: str = 'Close') -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate Average True Range (ATR).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        window: ATR window (default: 14)
        high_col: High price column (default: 'High')
        low_col: Low price column (default: 'Low')
        close_col: Close price column (default: 'Close')
    
    Returns:
        Series of ATR values or dictionary of symbol -> ATR Series
        
    Example:
        >>> atr_14 = atr(df)
        >>> print(f"ATR: {atr_14.iloc[-1]:.2f}")
    """
    if isinstance(df, dict):
        return {symbol: atr(data, window, high_col, low_col, close_col) 
                for symbol, data in df.items()}
    
    required_cols = [high_col, low_col, close_col]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Columns {missing_cols} not found in DataFrame. Available columns: {list(df.columns)}")
    
    high_low = df[high_col] - df[low_col]
    high_close_prev = np.abs(df[high_col] - df[close_col].shift(1))
    low_close_prev = np.abs(df[low_col] - df[close_col].shift(1))
    
    true_range = np.maximum(high_low, np.maximum(high_close_prev, low_close_prev))
    atr_values = true_range.rolling(window).mean()
    
    return atr_values


def adx(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
        window: int = 14,
        high_col: str = 'High',
        low_col: str = 'Low',
        close_col: str = 'Close') -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate Average Directional Index (ADX).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        window: ADX window (default: 14)
        high_col: High price column (default: 'High')
        low_col: Low price column (default: 'Low')
        close_col: Close price column (default: 'Close')
    
    Returns:
        Series of ADX values or dictionary of symbol -> ADX Series
        
    Example:
        >>> adx_14 = adx(df)
        >>> print(f"ADX: {adx_14.iloc[-1]:.2f}")
    """
    if isinstance(df, dict):
        return {symbol: adx(data, window, high_col, low_col, close_col) 
                for symbol, data in df.items()}
    
    required_cols = [high_col, low_col, close_col]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Columns {missing_cols} not found in DataFrame. Available columns: {list(df.columns)}")
    
    # Calculate True Range
    tr = atr(df, 1, high_col, low_col, close_col)
    
    # Calculate Directional Movement
    high_diff = df[high_col].diff()
    low_diff = -df[low_col].diff()
    
    plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
    minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
    
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    
    # Calculate smoothed values
    plus_di = 100 * (plus_dm.rolling(window).mean() / tr.rolling(window).mean())
    minus_di = 100 * (minus_dm.rolling(window).mean() / tr.rolling(window).mean())
    
    # Calculate ADX
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx_values = dx.rolling(window).mean()
    
    return adx_values


def cci(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
        window: int = 20,
        high_col: str = 'High',
        low_col: str = 'Low',
        close_col: str = 'Close') -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate Commodity Channel Index (CCI).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        window: CCI window (default: 20)
        high_col: High price column (default: 'High')
        low_col: Low price column (default: 'Low')
        close_col: Close price column (default: 'Close')
    
    Returns:
        Series of CCI values or dictionary of symbol -> CCI Series
        
    Example:
        >>> cci_20 = cci(df)
        >>> print(f"CCI: {cci_20.iloc[-1]:.2f}")
    """
    if isinstance(df, dict):
        return {symbol: cci(data, window, high_col, low_col, close_col) 
                for symbol, data in df.items()}
    
    required_cols = [high_col, low_col, close_col]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Columns {missing_cols} not found in DataFrame. Available columns: {list(df.columns)}")
    
    typical_price = (df[high_col] + df[low_col] + df[close_col]) / 3
    sma_tp = typical_price.rolling(window).mean()
    mad = typical_price.rolling(window).apply(lambda x: np.mean(np.abs(x - x.mean())))
    
    cci_values = (typical_price - sma_tp) / (0.015 * mad)
    
    return cci_values


def obv(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
        close_col: str = 'Close',
        volume_col: str = 'Volume') -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate On-Balance Volume (OBV).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        close_col: Close price column (default: 'Close')
        volume_col: Volume column (default: 'Volume')
    
    Returns:
        Series of OBV values or dictionary of symbol -> OBV Series
        
    Example:
        >>> obv_values = obv(df)
        >>> print(f"OBV: {obv_values.iloc[-1]:,.0f}")
    """
    if isinstance(df, dict):
        return {symbol: obv(data, close_col, volume_col) for symbol, data in df.items()}
    
    required_cols = [close_col, volume_col]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Columns {missing_cols} not found in DataFrame. Available columns: {list(df.columns)}")
    
    price_change = df[close_col].diff()
    obv_values = np.where(price_change > 0, df[volume_col],
                          np.where(price_change < 0, -df[volume_col], 0))
    
    obv_values = pd.Series(obv_values, index=df.index).cumsum()
    
    return obv_values


def vwap(df: Union[pd.DataFrame, Dict[str, pd.DataFrame]], 
         high_col: str = 'High',
         low_col: str = 'Low',
         close_col: str = 'Close',
         volume_col: str = 'Volume') -> Union[pd.Series, Dict[str, pd.Series]]:
    """
    Calculate Volume Weighted Average Price (VWAP).
    
    Args:
        df: Single DataFrame or dictionary of DataFrames
        high_col: High price column (default: 'High')
        low_col: Low price column (default: 'Low')
        close_col: Close price column (default: 'Close')
        volume_col: Volume column (default: 'Volume')
    
    Returns:
        Series of VWAP values or dictionary of symbol -> VWAP Series
        
    Example:
        >>> vwap_values = vwap(df)
        >>> print(f"VWAP: {vwap_values.iloc[-1]:.2f}")
    """
    if isinstance(df, dict):
        return {symbol: vwap(data, high_col, low_col, close_col, volume_col) 
                for symbol, data in df.items()}
    
    required_cols = [high_col, low_col, close_col, volume_col]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Columns {missing_cols} not found in DataFrame. Available columns: {list(df.columns)}")
    
    typical_price = (df[high_col] + df[low_col] + df[close_col]) / 3
    volume_price = typical_price * df[volume_col]
    
    cumulative_volume_price = volume_price.cumsum()
    cumulative_volume = df[volume_col].cumsum()
    
    vwap_values = cumulative_volume_price / cumulative_volume
    
    return vwap_values
