"""
DataFrame beautification utilities for PyPSX library.

Provides functions to format DataFrames for consistent, readable output.
"""

import pandas as pd
from typing import Optional, Union, Dict, Any
from loguru import logger


def beautify_dataframe(df: pd.DataFrame, symbol: Optional[str] = None) -> pd.DataFrame:
    """
    Beautify DataFrame with consistent formatting like yfinance.
    
    Args:
        df: DataFrame to beautify
        symbol: Optional symbol for index naming
        
    Returns:
        Beautified DataFrame
    """
    if df.empty:
        return df
    
    # Create a copy to avoid modifying original
    beautified = df.copy()
    
    # Standardize column names to uppercase
    column_mapping = {
        'symbol': 'SYMBOL',
        'current': 'CURRENT',
        'open': 'OPEN',
        'high': 'HIGH',
        'low': 'LOW',
        'close': 'CLOSE',
        'volume': 'VOLUME',
        'change': 'CHANGE',
        'percent_change': '%CHANGE',
        'sector': 'SECTOR',
        'price': 'PRICE',
        'bid': 'BID',
        'ask': 'ASK',
        'pe_ratio': 'PE_RATIO',
        'market_cap': 'MARKET_CAP',
        'turnover': 'TURNOVER',
        'advances': 'ADVANCES',
        'declines': 'DECLINES',
        'unchanged': 'UNCHANGED',
        'weight': 'WEIGHT',
        'contribution': 'CONTRIBUTION',
        'timestamp': 'TIMESTAMP',
        'date': 'DATE'
    }
    
    # Rename columns
    beautified.columns = [column_mapping.get(col.lower(), col.upper()) for col in beautified.columns]
    
    # Set symbol as index if provided and not already set
    if symbol and 'SYMBOL' not in beautified.index.names:
        if 'SYMBOL' in beautified.columns:
            beautified = beautified.set_index('SYMBOL')
        elif symbol:
            beautified.index.name = 'SYMBOL'
    
    # Format numeric columns
    numeric_columns = ['CURRENT', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME', 'CHANGE', '%CHANGE', 'PRICE', 'BID', 'ASK', 'PE_RATIO', 'WEIGHT', 'CONTRIBUTION']
    for col in numeric_columns:
        if col in beautified.columns:
            beautified[col] = pd.to_numeric(beautified[col], errors='coerce')
    
    # Format percentage columns
    percentage_columns = ['%CHANGE', 'WEIGHT', 'CONTRIBUTION']
    for col in percentage_columns:
        if col in beautified.columns:
            beautified[col] = beautified[col].round(2)
    
    # Format volume columns
    volume_columns = ['VOLUME']
    for col in volume_columns:
        if col in beautified.columns:
            beautified[col] = beautified[col].astype('Int64')
    
    return beautified


def format_currency(value: Union[float, int, str]) -> str:
    """
    Format currency value with commas.
    
    Args:
        value: Numeric value to format
        
    Returns:
        Formatted currency string
    """
    try:
        num_value = float(value)
        return f"{num_value:,.2f}"
    except (ValueError, TypeError):
        return str(value)


def format_percentage(value: Union[float, int, str]) -> str:
    """
    Format percentage value.
    
    Args:
        value: Numeric value to format as percentage
        
    Returns:
        Formatted percentage string
    """
    try:
        num_value = float(value)
        return f"{num_value:.2f}%"
    except (ValueError, TypeError):
        return str(value)


def format_volume(value: Union[float, int, str]) -> str:
    """
    Format volume with appropriate units (K, M, B).
    
    Args:
        value: Volume value to format
        
    Returns:
        Formatted volume string
    """
    try:
        num_value = int(float(value))
        
        if num_value >= 1_000_000_000:
            return f"{num_value / 1_000_000_000:.1f}B"
        elif num_value >= 1_000_000:
            return f"{num_value / 1_000_000:.1f}M"
        elif num_value >= 1_000:
            return f"{num_value / 1_000:.1f}K"
        else:
            return str(num_value)
    except (ValueError, TypeError):
        return str(value)


def format_dataframe_display(df: pd.DataFrame) -> pd.DataFrame:
    """
    Format DataFrame for display with proper formatting.
    
    Args:
        df: DataFrame to format
        
    Returns:
        Formatted DataFrame for display
    """
    if df.empty:
        return df
    
    display_df = df.copy()
    
    # Format currency columns
    currency_columns = ['CURRENT', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'PRICE', 'BID', 'ASK']
    for col in currency_columns:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(format_currency)
    
    # Format percentage columns
    percentage_columns = ['%CHANGE', 'WEIGHT', 'CONTRIBUTION']
    for col in percentage_columns:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(format_percentage)
    
    # Format volume columns
    volume_columns = ['VOLUME']
    for col in volume_columns:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(format_volume)
    
    return display_df
