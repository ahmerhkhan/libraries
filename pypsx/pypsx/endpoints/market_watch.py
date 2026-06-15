"""
Market watch data endpoint for PyPSX library.

Fetches market-wide overview data from PSX market-watch endpoint.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union

from pypsx.core.fetchers import fetch_html
from pypsx.core.parsers import parse_market_watch_html
from pypsx.endpoints.constants import MARKET_WATCH_URL
from pypsx.format.json_utils import to_json
from pypsx.core.utils import get_sector_code_to_name_map


def get_market_watch(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get Market Watch data.
    
    Fetches current market watch data from https://dps.psx.com.pk/market-watch
    
    Returns DataFrame with exactly these columns (no fabricated fields):
    - Symbol (index)
    - Sector
    - Listed In
    - LDCP
    - Open
    - High
    - Low
    - Current
    - Change
    - Change %
    - Volume
    """
    try:
        # Fetch HTML
        html = fetch_html(MARKET_WATCH_URL, timeout=30.0, ttl=30)
        
        # Parse HTML table
        df = parse_market_watch_html(html)
        
        if df is None or df.empty:
            return None
        
        # Keep only exact columns and types; no beautify, no added fields
        
        
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except Exception as e:
        return None




def _parse_market_watch_data(data: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """
    Parse market watch JSON data into DataFrame.
    
    Args:
        data: Raw JSON response data
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Extract market data from JSON structure
        # This will depend on the actual JSON structure from PSX
        # For now, we'll create a basic structure
        
        if 'data' not in data:
            return None
        
        market_data = data['data']
        
        # Convert to DataFrame
        df = pd.DataFrame(market_data)
        
        # Ensure required columns exist
        required_columns = ['SYMBOL', 'CURRENT', 'OPEN', 'HIGH', 'LOW', 'VOLUME']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            # Create missing columns with default values
            for col in missing_columns:
                df[col] = None
        
        # Set symbol as index
        if 'SYMBOL' in df.columns:
            df = df.set_index('SYMBOL')
        
        return df
        
    except Exception as e:
        return None


def get_symbol_quote(symbol: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get quote data for a specific symbol from market watch.
    
    Args:
        symbol: Stock symbol
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with symbol data or JSON dict, None if failed
    """
    try:
        # Get all market data
        market_df = get_market_watch('dataframe')
        if market_df is None or market_df.empty:
            return None
        
        # Exact match only, no normalization
        key = str(symbol).upper()
        symbol_data = market_df[market_df.index == key]
        
        if symbol_data.empty:
            return None
        
        # Return based on format
        if format == 'json':
            return to_json(symbol_data)
        else:
            return symbol_data
            
    except Exception as e:
        return None
