"""
Utility functions for PyPSX library.

Provides symbol validation, period formatting, and DataFrame beautification.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Union, List, Dict, Any
import re
from typing import Iterable
try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover
    def tqdm(x: Iterable = None, total: int | None = None, disable: bool = True, **kwargs):
        return x if x is not None else range(0)
from .cache import PyPSXCache
import requests
from bs4 import BeautifulSoup
from functools import lru_cache
try:
    from loguru import logger
except ImportError:
    class _Logger:
        def debug(self, *args, **kwargs): pass
        def info(self, *args, **kwargs): pass
        def warning(self, *args, **kwargs): pass
        def error(self, *args, **kwargs): pass
    logger = _Logger()


# Known PSX symbols for validation
KNOWN_SYMBOLS = {
    'OGDC', 'PPL', 'KEL', 'HBL', 'UBL', 'MCB', 'PSO', 'SHEL', 'ENGRO', 'LUCK',
    'FFC', 'EFERT', 'ATRL', 'NRL', 'POL', 'OGDCL', 'PTC', 'PTCL', 'TRG', 'NESTLE',
    'KSE100', 'KMI30', 'KSE30', 'KSEALLSHR', 'KMIALLSHR'
}


def validate_symbol(symbol: str) -> str:
    """
    Validate and normalize stock symbol.
    
    Args:
        symbol: Stock symbol to validate
        
    Returns:
        Normalized symbol
        
    Raises:
        ValueError: If symbol is invalid
    """
    if not symbol:
        raise ValueError("Symbol cannot be empty")
    
    normalized = symbol.upper().strip()
    
    # Basic validation - alphanumeric only
    if not re.match(r'^[A-Z0-9]+$', normalized):
        raise ValueError(f"Invalid symbol format: {symbol}")
    
    return normalized


def normalize_symbol(symbol: str) -> str:
    """
    Normalize symbol by stripping suffixes (XD, XR, NC) for matching.
    
    PSX symbols sometimes include suffixes like:
    - XD: Ex-Dividend
    - XR: Ex-Rights
    - NC: Non-Compliant
    
    This function strips these suffixes to get the base symbol for matching
    across different endpoints.
    
    Args:
        symbol: Stock symbol (may include suffixes like OGDCXD, HBLNC)
        
    Returns:
        Base symbol without suffixes (e.g., OGDC, HBL)
        
    Example:
        >>> normalize_symbol("OGDCXD")
        'OGDC'
        >>> normalize_symbol("HBLNC")
        'HBL'
        >>> normalize_symbol("KSE100")
        'KSE100'
    """
    if not symbol:
        return symbol
    
    normalized = symbol.upper().strip()
    # Strip XD, XR, NC suffixes
    normalized = re.sub(r'(XD|XR|NC)$', '', normalized)
    return normalized


def format_period(period: str) -> tuple[datetime, datetime]:
    """
    Convert period string to start and end dates.
    
    Args:
        period: Period string ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y")
        
    Returns:
        Tuple of (start_date, end_date)
        
    Raises:
        ValueError: If period format is invalid
    """
    end_date = datetime.now()
    
    period_map = {
        '1d': timedelta(days=1),
        '5d': timedelta(days=5),
        '1mo': timedelta(days=30),
        '3mo': timedelta(days=90),
        '6mo': timedelta(days=180),
        '1y': timedelta(days=365),
        '2y': timedelta(days=730),
        '5y': timedelta(days=1825)
    }
    
    if period not in period_map:
        raise ValueError(f"Invalid period: {period}. Use: {list(period_map.keys())}")
    
    start_date = end_date - period_map[period]
    return start_date, end_date


def round_numeric_values(value: Union[float, int, pd.Series], decimals: int = 2) -> Union[float, int, pd.Series]:
    """
    Round numeric values to specified decimal places.
    
    Args:
        value: Numeric value or Series to round
        decimals: Number of decimal places (default: 2, max: 3)
        
    Returns:
        Rounded value or Series
        
    Example:
        >>> round_numeric_values(123.456789, decimals=2)
        123.46
        >>> round_numeric_values(pd.Series([1.234, 5.678]), decimals=2)
        Series([1.23, 5.68])
    """
    decimals = min(max(0, decimals), 3)  # Clamp between 0 and 3
    
    if isinstance(value, pd.Series):
        return value.round(decimals)
    elif isinstance(value, (int, float)):
        if pd.isna(value):
            return value
        return round(float(value), decimals)
    return value


def beautify_dataframe(df: pd.DataFrame, symbol: Optional[str] = None) -> pd.DataFrame:
    """
    Beautify DataFrame with consistent formatting.
    
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
        'unchanged': 'UNCHANGED'
    }
    
    # Rename columns
    beautified.columns = [column_mapping.get(col.lower(), col.upper()) for col in beautified.columns]
    
    # Set symbol as index if provided and not already set
    if symbol and 'SYMBOL' not in beautified.index.names:
        if 'SYMBOL' in beautified.columns:
            beautified = beautified.set_index('SYMBOL')
        elif symbol:
            beautified.index.name = 'SYMBOL'
    
    # Format numeric columns carefully. Avoid coercing known string fields
    # which may contain index lists or other non-numeric data.
    protected_string_cols = {'INDICES', 'LISTED_IN', 'INDEX_MEMBERSHIPS', 'MARKET_WATCH_ALIASES',
                             'COMPLIANCE_STATUS', 'NON_COMPLIANCE', 'CLEARING_TYPE', 'NAME', 'SECTOR'}

    numeric_candidates = ['CURRENT', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME', 'CHANGE', '%CHANGE', 'PRICE', 'BID', 'ASK', 'PE_RATIO',
                          'LDCP', 'IDX WTG %', 'IDX Point', 'Freefloat (M)', 'Market Cap (M)']
    for col in numeric_candidates:
        if col in beautified.columns and col not in protected_string_cols:
            try:
                beautified[col] = pd.to_numeric(beautified[col], errors='coerce')
                # Round to 2-3 decimal places for display
                if col in ['CURRENT', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'PRICE', 'BID', 'ASK', 'LDCP']:
                    beautified[col] = round_numeric_values(beautified[col], decimals=2)
                elif col in ['CHANGE', 'IDX Point']:
                    beautified[col] = round_numeric_values(beautified[col], decimals=2)
                elif col in ['%CHANGE', 'IDX WTG %']:
                    beautified[col] = round_numeric_values(beautified[col], decimals=2)
                elif col in ['PE_RATIO']:
                    beautified[col] = round_numeric_values(beautified[col], decimals=2)
                # Volume and Market Cap can stay as-is (large numbers)
            except Exception:
                # Leave the column as-is if conversion fails
                pass

    # Format percentage columns (round floats only)
    if '%CHANGE' in beautified.columns and '%CHANGE' not in protected_string_cols:
        try:
            beautified['%CHANGE'] = pd.to_numeric(beautified['%CHANGE'], errors='coerce').fillna(0.0)
            beautified['%CHANGE'] = round_numeric_values(beautified['%CHANGE'], decimals=2)
        except Exception:
            pass

    # Format volume columns carefully using nullable integer when possible
    if 'VOLUME' in beautified.columns and 'VOLUME' not in protected_string_cols:
        try:
            beautified['VOLUME'] = pd.to_numeric(beautified['VOLUME'], errors='coerce').fillna(0).astype('Int64')
        except Exception:
            # Fallback: keep numeric coercion but leave dtype as object/float
            beautified['VOLUME'] = pd.to_numeric(beautified['VOLUME'], errors='coerce').fillna(0)
    
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


def is_valid_symbol(symbol: str) -> bool:
    """
    Check if symbol is valid (basic check).
    
    Args:
        symbol: Symbol to check
        
    Returns:
        True if valid, False otherwise
    """
    try:
        validate_symbol(symbol)
        return True
    except ValueError:
        return False


def get_symbol_info(symbol: str) -> Dict[str, Any]:
    """
    Get basic information about a symbol.
    
    Args:
        symbol: Stock symbol
        
    Returns:
        Dictionary with symbol information
    """
    normalized = validate_symbol(symbol)
    
    return {
        'symbol': normalized,
        'is_index': normalized.startswith('KSE') or normalized.startswith('KMI'),
        'is_known': normalized in KNOWN_SYMBOLS,
        'category': _categorize_symbol(normalized)
    }


def _categorize_symbol(symbol: str) -> str:
    """
    Categorize symbol by type.
    
    Args:
        symbol: Normalized symbol
        
    Returns:
        Category string
    """
    if symbol.startswith('KSE') or symbol.startswith('KMI'):
        return 'index'
    elif symbol in ['OGDC', 'PPL', 'ATRL', 'NRL', 'POL']:
        return 'energy'
    elif symbol in ['HBL', 'UBL', 'MCB']:
        return 'banking'
    elif symbol in ['ENGRO', 'FFC', 'EFERT']:
        return 'chemicals'
    else:
        return 'other'


def cache_data(key: str, value: Any = None) -> Any:
    """
    Basic cache accessor to reduce fetch latency.
    
    - If value is provided, stores it under the key and returns the value.
    - If value is None, returns cached value or None.
    """
    try:
        cache = PyPSXCache()
        if value is None:
            return cache.get(key)
        cache.set(key, value)
        return value
    except Exception:
        return None


def handle_api_error(error: Exception, context: str = "") -> Dict[str, Any]:
    """
    Centralized graceful API error handler with comprehensive error categorization.
    
    Args:
        error: Exception that occurred
        context: Additional context about where the error occurred
        
    Returns:
        Dictionary with structured error information
    """
    error_type = type(error).__name__
    error_message = str(error)
    
    # Categorize common errors
    if "timeout" in error_message.lower():
        error_category = "timeout"
        user_message = "Request timed out. Please try again later."
    elif "connection" in error_message.lower():
        error_category = "connection"
        user_message = "Connection error. Please check your internet connection."
    elif "not found" in error_message.lower() or "404" in error_message:
        error_category = "not_found"
        user_message = "Data not found. The requested symbol or data may not exist."
    elif "invalid" in error_message.lower():
        error_category = "invalid_input"
        user_message = "Invalid input provided. Please check your parameters."
    elif "empty" in error_message.lower() or "no data" in error_message.lower():
        error_category = "no_data"
        user_message = "No data available for the requested parameters."
    else:
        error_category = "unknown"
        user_message = "An unexpected error occurred. Please try again."
    
    return {
        "error": True,
        "error_type": error_type,
        "error_category": error_category,
        "error_message": error_message,
        "user_message": user_message,
        "context": context
    }


def safe_execute(func, *args, **kwargs):
    """
    Safely execute a function with comprehensive error handling.
    
    Args:
        func: Function to execute
        *args: Function arguments
        **kwargs: Function keyword arguments
        
    Returns:
        Tuple of (result, error_message)
    """
    try:
        result = func(*args, **kwargs)
        return result, None
    except ValueError as e:
        return None, f"Invalid input: {str(e)}"
    except KeyError as e:
        return None, f"Missing required data: {str(e)}"
    except IndexError as e:
        return None, f"Data index error: {str(e)}"
    except AttributeError as e:
        return None, f"Data structure error: {str(e)}"
    except Exception as e:
        return None, f"Unexpected error: {str(e)}"


def validate_dataframe(df: pd.DataFrame, required_columns: List[str] = None, min_rows: int = 1) -> tuple:
    """
    Validate DataFrame structure and content.
    
    Args:
        df: DataFrame to validate
        required_columns: List of required column names
        min_rows: Minimum number of rows required
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if df is None:
        return False, "DataFrame is None"
    
    if df.empty:
        return False, "DataFrame is empty"
    
    if len(df) < min_rows:
        return False, f"DataFrame has insufficient rows: {len(df)} < {min_rows}"
    
    if required_columns:
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return False, f"Missing required columns: {missing_columns}"
    
    return True, None


def progress(iterable: Iterable | None = None, total: int | None = None, show_progress: bool = True, description: str = ""):
    """
    Lightweight progress helper using tqdm; suppressed when show_progress is False.
    """
    return tqdm(iterable, total=total, disable=not show_progress, desc=description)


@lru_cache(maxsize=1)
def get_sector_code_to_name_map() -> Dict[str, str]:
    """Fetch Sector Code -> Sector Name mapping from sector summary page and cache it."""
    try:
        import pandas as _pd
        import requests as _req
        from io import StringIO
        url = "https://dps.psx.com.pk/sector-summary/sectorwise"
        resp = _req.get(url, timeout=10)
        resp.raise_for_status()
        tables = _pd.read_html(StringIO(resp.text))
        if not tables:
            return {}
        df = tables[0]
        cols = [str(c).strip() for c in df.columns]
        df.columns = cols
        code_col = next((c for c in cols if c.lower().startswith('sector') and 'code' in c.lower()), None)
        name_col = next((c for c in cols if c.lower().startswith('sector') and 'name' in c.lower()), None)
        if not code_col or not name_col:
            return {}
        return {str(row[code_col]).strip(): str(row[name_col]).strip() for _, row in df.iterrows()}
    except Exception:
        return {}


def get_psx_indices_snapshot_codes() -> Dict[str, Dict[str, str]]:
    """
    Scrape the current indices snapshot table from PSX and return {code: {name, ...}} for each row.
    Returns:
        Dict of index codes (e.g., 'KSE100', 'ALLSHR') to {name/values} dict.
        Handles indices with date suffixes by extracting the base code.
    """
    try:
        url = "https://dps.psx.com.pk/indices"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="tbl")
        results = {}

        # Handle no table case gracefully
        if not table:
            logger.warning("No indices table found in HTML response")
            return results
            
        # Ensure table has expected structure
        thead = table.find("thead")
        tbody = table.find("tbody")
        if not thead or not tbody:
            logger.warning("Invalid table structure in indices response")
            return results
        
        # Validate header structure
        header_cells = [th.get_text(strip=True) for th in thead.find_all("th")]
        if not header_cells or len(header_cells) < 4:  # Minimum required columns
            logger.warning("Invalid header structure in indices table")
            return results

        header_cells = [th.get_text(strip=True) for th in table.find("thead").find_all("th")]
        for row in table.find("tbody").find_all("tr"):
            try:
                cols = [col.get_text(strip=True).replace("\xa0", " ") for col in row.find_all("td")]
                if len(cols) < 1 or cols[0] in (None, '', 'N/A'):
                    continue
                    
                index_code = cols[0].strip()
                if '(' in index_code:  # Handle dated indices like HBLTTI(28-10-2025 18:30:00)
                    index_code = index_code.split('(')[0].strip()
                    
                if not index_code:  # Skip if no valid code after cleanup
                    continue
                    
                # Only add if we have current price (valid index)
                if len(cols) >= 4 and cols[3] != 'N/A':
                    results[index_code] = {
                        'Index': index_code,
                        'High': cols[1] if len(cols) > 1 else 'N/A',
                        'Low': cols[2] if len(cols) > 2 else 'N/A',
                        'Current': cols[3] if len(cols) > 3 else 'N/A',
                        'Change': cols[4] if len(cols) > 4 else 'N/A',
                        '% Change': cols[5] if len(cols) > 5 else 'N/A'
                    }
                    
            except Exception:
                continue  # Skip problematic rows

        return results
        
    except Exception:
        return {}
