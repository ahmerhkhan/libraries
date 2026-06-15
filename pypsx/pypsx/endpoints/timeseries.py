"""
Timeseries data endpoint for PyPSX library.

Fetches intraday and historical OHLCV data from PSX timeseries endpoints.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Union
try:
    from loguru import logger
    logger.remove()
except Exception:
    class _N:
        def __getattr__(self, _):
            return lambda *a, **k: None
    logger = _N()

from pypsx.core.fetchers import fetch_json
from pypsx.core.parsers import parse_timeseries_intraday_json, parse_timeseries_eod_json
from pypsx.endpoints.constants import get_timeseries_intraday_url, get_timeseries_eod_url
from pypsx.core.utils import beautify_dataframe, format_period, validate_symbol, progress
from pypsx.format.json_utils import to_json


def get_intraday(symbol: str, format: str = 'dataframe', show_progress: bool = False) -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get intraday tick data for a symbol.
    
    Fetches intraday data from https://dps.psx.com.pk/timeseries/int/{SYMBOL}
    including timestamp, price, and volume for the last 2 days.
    Converts timestamps to datetime with proper timezone.
    
    Args:
        symbol: Stock symbol (e.g., "OGDC", "KSE100")
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with intraday data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_intraday("OGDC")
        >>> print(df.head())
        
        Output (pandas DataFrame):
        | TIMESTAMP           | PRICE | VOLUME |
        |---------------------|-------|---------|
        | 2024-01-15 09:30:00 | 106.50| 1000    |
        | 2024-01-15 09:31:00 | 106.75| 1500    |
    """
    try:
        # Validate symbol
        normalized_symbol = validate_symbol(symbol)
        
        # Build URL
        url = get_timeseries_intraday_url(normalized_symbol)
        
        # Fetch JSON data (PSX intraday endpoint needs more time, use 10s timeout)
        data = fetch_json(url, timeout=10.0, ttl=60)
        
        # Parse intraday data
        df = parse_timeseries_intraday_json(data)
        if df is None or df.empty:
            return None
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except ValueError:
        return None
    except Exception:
        return None


def get_history(symbol: str, period: str = "1y", format: str = 'dataframe', show_progress: bool = False) -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get historical EOD timeseries data for a symbol (for charting).
    
    WARNING: This returns [timestamp, close, volume, open] - NOT full OHLCV!
    This is for charting purposes only. For actual OHLCV data, use get_historical_data().
    
    Fetches EOD timeseries data from https://dps.psx.com.pk/timeseries/eod/{SYMBOL}
    Returns up to 5 years of data: [timestamp, close, volume, open]
    
    Args:
        symbol: Stock symbol (e.g., "OGDC", "KSE100")
        period: Time period ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y")
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with timestamp, close, volume, open (NOT full OHLCV) or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_history("OGDC", period="1y")
        >>> print(df.head())
        
        Output (pandas DataFrame):
        | TIMESTAMP  | CLOSE | VOLUME | OPEN |
        |------------|-------|--------|------|
        | 2024-01-15 | 106.90| 5,233,000| 105.50|
    """
    try:
        # Validate symbol
        normalized_symbol = validate_symbol(symbol)
        
        # Build URL
        url = get_timeseries_eod_url(normalized_symbol)
        
        # Fetch JSON data (PSX historical endpoint needs more time, use 10s timeout)
        data = fetch_json(url, timeout=10.0, ttl=3600)
        
        # Parse historical data
        df = parse_timeseries_eod_json(data)
        if df is None or df.empty:
            return None
        
        # Slice by requested period window (ensure only requested range)
        try:
            start_date, end_date = format_period(period)
            # Guard in case index isn't datetime yet
            if not pd.api.types.is_datetime64_any_dtype(df.index):
                if 'DATE' in df.columns:
                    df['DATE'] = pd.to_datetime(df['DATE'])
                    df = df.set_index('DATE')
            # Initial slice using current time window
            sliced = df.loc[(df.index >= start_date) & (df.index <= end_date)]
            if sliced.empty:
                # Fallback: align window to available data's max date
                duration = end_date - start_date
                data_end = df.index.max()
                adj_start = data_end - duration
                sliced = df.loc[(df.index >= adj_start) & (df.index <= data_end)]
                if sliced.empty:
                    # Final fallback: take last N rows approximating the duration (assume ~252 trading days/year)
                    approx_days = max(1, int(duration.days))
                    sliced = df.tail(min(len(df), approx_days))
            df = sliced
        except Exception:
            # If period formatting fails, continue with parsed data
            pass

        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except ValueError:
        return None
    except Exception:
        return None


def _parse_intraday_data(data: Dict[str, Any], symbol: str) -> Optional[pd.DataFrame]:
    """
    Parse intraday JSON data into DataFrame.
    
    Args:
        data: Raw JSON response data
        symbol: Stock symbol
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Extract intraday data from JSON structure
        if 'data' not in data:
            return None
        
        intraday_data = data['data']
        
        # Check if data is array format [timestamp, price, volume] or object format
        if isinstance(intraday_data, list) and len(intraday_data) > 0:
            # Array format: [timestamp, price, volume]
            if isinstance(intraday_data[0], list) and len(intraday_data[0]) >= 3:
                # Convert array format to DataFrame
                df = pd.DataFrame(intraday_data, columns=['TIMESTAMP', 'PRICE', 'VOLUME'])
                
                # Convert timestamp to timezone-aware datetime (PSX epoch assumed UTC)
                df['DATETIME'] = pd.to_datetime(df['TIMESTAMP'], unit='s', utc=True).dt.tz_convert('Asia/Karachi')
                # Use naive local time for consistency in outputs
                df['DATETIME'] = df['DATETIME'].dt.tz_localize(None)
                df = df.set_index('DATETIME')
                
                # Reorder columns
                df = df[['PRICE', 'VOLUME']]
                
            else:
                return None
        else:
            # Object format - convert to DataFrame
            df = pd.DataFrame(intraday_data)
            
            # Ensure required columns exist
            required_columns = ['TIMESTAMP', 'PRICE', 'VOLUME']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                # Create missing columns with default values
                for col in missing_columns:
                    df[col] = None
            
            # Convert timestamp to timezone-aware datetime (PSX epoch assumed UTC)
            if 'TIMESTAMP' in df.columns:
                df['DATETIME'] = pd.to_datetime(df['TIMESTAMP'], unit='s', utc=True).dt.tz_convert('Asia/Karachi')
                df['DATETIME'] = df['DATETIME'].dt.tz_localize(None)
                df = df.set_index('DATETIME')
        
        # Add symbol column
        df['SYMBOL'] = symbol
        
        # Sort by datetime
        df = df.sort_index()

        # Filter to typical PSX trading session to avoid off-hours timestamps
        try:
            df = df.between_time('09:15', '16:00')
        except Exception:
            pass
        
        return df
        
    except Exception as e:
        logger.error(f"Error parsing intraday data: {e}")
        return None


def _parse_historical_data(data: Dict[str, Any], symbol: str, period: str) -> Optional[pd.DataFrame]:
    """
    Parse historical JSON data into DataFrame.
    
    Args:
        data: Raw JSON response data
        symbol: Stock symbol
        period: Data period
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Extract historical data from JSON structure
        if 'data' not in data:
            return None
        
        historical_data = data['data']
        
        # Check if data is array format [timestamp, close, volume, high] or object format
        if isinstance(historical_data, list) and len(historical_data) > 0:
            # Array format: [timestamp, close, volume, high]
            if isinstance(historical_data[0], list) and len(historical_data[0]) >= 3:
                # Convert array format to DataFrame
                df = pd.DataFrame(historical_data, columns=['TIMESTAMP', 'CLOSE', 'VOLUME', 'HIGH'])
                
                # Convert timestamp to datetime (auto-detect seconds vs milliseconds)
                try:
                    ts_sample = df['TIMESTAMP'].iloc[0]
                    unit = 'ms' if float(ts_sample) > 10**12 else 's'
                except Exception:
                    unit = 's'
                df['DATE'] = pd.to_datetime(df['TIMESTAMP'], unit=unit)
                df = df.set_index('DATE')
                
                # For historical data, we typically only have close prices
                # Set OPEN, HIGH, LOW to CLOSE for consistency
                df['OPEN'] = df['CLOSE']
                df['LOW'] = df['CLOSE']
                
                # Reorder columns
                df = df[['OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME']]
                
            else:
                return None
        else:
            # Object format - convert to DataFrame
            df = pd.DataFrame(historical_data)
            
            # Ensure required columns exist
            required_columns = ['DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                # Create missing columns with default values
                for col in missing_columns:
                    df[col] = None
            
            # Convert date to datetime
            if 'DATE' in df.columns:
                df['DATE'] = pd.to_datetime(df['DATE'])
                df = df.set_index('DATE')
        
        # Add symbol column
        df['SYMBOL'] = symbol
        
        # Sort by date
        df = df.sort_index()
        
        return df
        
    except Exception:
        return None
