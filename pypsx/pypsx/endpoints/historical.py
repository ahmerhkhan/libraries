"""
Historical OHLCV data endpoint for PyPSX library.

Fetches full historical OHLCV (Open, High, Low, Close, Volume) data from PSX historical endpoint.
Uses POST requests to fetch data month-by-month with parallel processing.
"""

import pandas as pd
from typing import Optional, List, Dict, Any, Union
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    from tqdm import tqdm
except Exception:
    # Fallback no-op tqdm
    def tqdm(x, **kwargs):
        return x
from bs4 import BeautifulSoup
from io import StringIO
try:
    from loguru import logger
    logger.remove()
except Exception:
    class _N:
        def __getattr__(self, _):
            return lambda *a, **k: None
    logger = _N()

from pypsx.core.fetchers import fetch_post
from pypsx.core.errors import PSXHTTPError, PSXNotFoundError


# Expected table headers
HEADERS = ['TIME', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME']


def _generate_date_range(start: date, end: date) -> List[date]:
    """
    Create a list of month-start dates between start and end.
    
    Args:
        start: Start date
        end: End date
        
    Returns:
        List of month-start dates
        
    Example:
        If start = Jan 15, 2025 and end = Mar 20, 2025,
        returns [Jan 1, 2025, Feb 1, 2025, Mar 1, 2025]
    """
    dates = []
    current = date(start.year, start.month, 1)
    end_month_start = date(end.year, end.month, 1)
    
    while current <= end_month_start:
        dates.append(current)
        # Move to next month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    
    return dates


def _download_data(symbol: str, date: date) -> pd.DataFrame:
    """
    Download historical data for a specific month.
    
    Args:
        symbol: Stock symbol
        date: Date representing the month to fetch
        
    Returns:
        DataFrame with OHLCV data for that month
    """
    url = "https://dps.psx.com.pk/historical"
    post_data = {
        "month": date.month,
        "year": date.year,
        "symbol": symbol
    }
    
    try:
        html = fetch_post(url, data=post_data, kind="text", timeout=30.0, ttl=None)
        soup = BeautifulSoup(html, 'html.parser')
        return _parse_html_table(soup)
    except PSXHTTPError as e:
        logger.warning(f"HTTP error fetching {symbol} for {date.month}/{date.year}: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"Error fetching {symbol} for {date.month}/{date.year}: {e}")
        return pd.DataFrame()


def _parse_html_table(soup: BeautifulSoup) -> pd.DataFrame:
    """
    Parse HTML table from historical data response.
    
    Args:
        soup: BeautifulSoup object from the HTML response
        
    Returns:
        DataFrame with TIME as index and OHLCV columns
    """
    rows = soup.select("tr")
    if not rows:
        return pd.DataFrame()
    
    data = []
    for row in rows:
        cols = row.select("td")
        if len(cols) < len(HEADERS):
            continue
        
        row_data = {}
        for i, header in enumerate(HEADERS):
            if i < len(cols):
                value = cols[i].get_text(strip=True)
                row_data[header] = value
        
        if row_data:
            data.append(row_data)
    
    if not data:
        return pd.DataFrame()
    
    df = pd.DataFrame(data)
    
    # Convert TIME to datetime index
    if 'TIME' in df.columns:
        df['TIME'] = pd.to_datetime(df['TIME'], errors='coerce')
        df = df.set_index('TIME')
        df = df.sort_index()
    
    # Convert numeric columns, removing commas
    numeric_cols = ['OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(',', '', regex=False),
                errors='coerce'
            )
    
    # Keep only expected columns
    df = df[[c for c in numeric_cols if c in df.columns]]
    
    return df


def _preprocess_data(data: List[pd.DataFrame]) -> pd.DataFrame:
    """
    Combine and clean monthly DataFrames.
    
    Args:
        data: List of monthly DataFrames
        
    Returns:
        Combined, cleaned DataFrame
    """
    if not data:
        return pd.DataFrame()
    
    # Filter out empty DataFrames
    non_empty = [df for df in data if not df.empty]
    
    if not non_empty:
        return pd.DataFrame()
    
    # Concatenate all DataFrames
    combined = pd.concat(non_empty, axis=0)
    
    # Remove duplicate dates (keep last occurrence)
    combined = combined[~combined.index.duplicated(keep='last')]
    
    # Sort by TIME
    combined = combined.sort_index()
    
    return combined


def get_historical_data(
    symbol: str,
    start_date: Optional[Union[date, str]] = None,
    end_date: Optional[Union[date, str]] = None,
    max_workers: int = 5,
    show_progress: bool = True
) -> pd.DataFrame:
    """
    Get historical OHLCV data for a symbol.
    
    Args:
        symbol: Stock symbol
        start_date: Start date (default: 1 month ago)
        end_date: End date (default: today)
        max_workers: Maximum number of parallel threads (default: 5)
        
    Returns:
        DataFrame with TIME as index and OPEN, HIGH, LOW, CLOSE, VOLUME columns
    """
    # Parse dates
    if end_date is None:
        end_date = date.today()
    elif isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    
    if start_date is None:
        start_date = end_date - timedelta(days=30)
    elif isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    
    # Generate date range
    date_range = _generate_date_range(start_date, end_date)
    
    if not date_range:
        logger.warning(f"No date range generated for {symbol}")
        return pd.DataFrame()
    
    logger.info(f"Fetching historical data for {symbol} ({len(date_range)} months)")
    
    # Fetch data in parallel
    monthly_data = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_date = {
            executor.submit(_download_data, symbol, d): d
            for d in date_range
        }
        iterator = as_completed(future_to_date)
        if show_progress:
            iterator = tqdm(iterator, total=len(future_to_date), desc=f"{symbol} months")
        for future in iterator:
            df = future.result()
            if not df.empty:
                monthly_data.append(df)
    
    # Combine and clean
    result = _preprocess_data(monthly_data)
    
    if result.empty:
        raise PSXNotFoundError(f"No historical data found for {symbol}")
    
    logger.info(f"Successfully fetched {len(result)} rows for {symbol}")
    return result


def get_multiple_symbols(
    symbols: List[str],
    start_date: Optional[Union[date, str]] = None,
    end_date: Optional[Union[date, str]] = None,
    max_workers: int = 5,
    show_progress: bool = True
) -> pd.DataFrame:
    """
    Get historical data for multiple symbols.
    
    Args:
        symbols: List of stock symbols
        start_date: Start date (default: 1 month ago)
        end_date: End date (default: today)
        max_workers: Maximum number of parallel threads per symbol (default: 5)
        show_progress: Show progress bar for symbols (default: True)
        
    Returns:
        Multi-index DataFrame with (Symbol, Date) index and OHLCV columns
    """
    results = []
    failed_symbols = []
    
    iterator = symbols
    if show_progress:
        iterator = tqdm(symbols, desc="Fetching symbols")
    
    for symbol in iterator:
        try:
            df = get_historical_data(symbol, start_date, end_date, max_workers, show_progress=False)
            if not df.empty:
                df['Symbol'] = symbol
                df = df.set_index('Symbol', append=True)
                df = df.swaplevel()
                results.append(df)
        except Exception as e:
            failed_symbols.append((symbol, str(e)))
            logger.warning(f"Error fetching data for {symbol}: {e}")
            continue
    
    if failed_symbols and show_progress:
        print(f"\n⚠️  {len(failed_symbols)} symbol(s) failed: {[s for s, _ in failed_symbols]}")
    
    if not results:
        return pd.DataFrame()
    
    combined = pd.concat(results, axis=0)
    return combined.sort_index()

