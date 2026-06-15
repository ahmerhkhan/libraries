from typing import List, Dict, Optional, cast
import pandas as pd
from pypsx.ticker import PSXTicker, Ticker
from pypsx.market import top_performers, sector_summary, market_watch, get_indices, get_indices_breakdown, get_sector_breakdown
from pypsx.endpoints.trading_board import get_symbols as get_symbols_from_trading_board
from pypsx.endpoints.historical import get_historical_data
from pypsx.endpoints.index_constituents import get_index_constituents


def download(symbols: List[str] | str, period: str = "1y", interval: str = "1d", to_csv: str | None = None) -> pd.DataFrame:
    """
    yfinance-like download for multiple symbols.

    Args:
        symbols: Single symbol or list of symbols
        period: Time period - "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
                 or custom format like "2024-01-01"
        interval: "1d" for daily OHLCV or "1m" for intraday trades
        to_csv: Optional CSV file path to save data

    Returns:
        DataFrame with MultiIndex columns (symbol, field) for interval='1d'
        or aligned timestamp index for interval='1m'

    Shows a progress bar while fetching symbols and handles errors gracefully.
    """
    from datetime import date, timedelta, datetime
    
    try:
        from tqdm import tqdm as _tqdm
    except Exception:
        def _tqdm(x, **kwargs):
            return x
    
    # Parse period to date range for historical data
    def _parse_period(period: str):
        """Convert period string to (start_date, end_date) tuple."""
        end_date = date.today()
        
        if period == "1mo":
            start_date = end_date - timedelta(days=30)
        elif period == "3mo":
            start_date = end_date - timedelta(days=90)
        elif period == "6mo":
            start_date = end_date - timedelta(days=180)
        elif period == "1y":
            start_date = end_date - timedelta(days=365)
        elif period == "2y":
            start_date = end_date - timedelta(days=730)
        elif period == "5y":
            start_date = end_date - timedelta(days=1825)
        elif period == "10y":
            start_date = end_date - timedelta(days=3650)
        elif period == "ytd":
            start_date = date(end_date.year, 1, 1)
        elif period == "max":
            start_date = date(2015, 1, 1)  # Approximate PSX historical limit
        else:
            # Try to parse as date
            try:
                start_date = datetime.strptime(period, "%Y-%m-%d").date()
            except ValueError:
                # Default to 1 year if parsing fails
                start_date = end_date - timedelta(days=365)
        
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

    syms = [symbols] if isinstance(symbols, str) else list(symbols)
    frames: Dict[str, pd.DataFrame] = {}
    failed_symbols = []

    if interval == "1d":
        start_date, end_date = _parse_period(period)
    
    # Show progress bar with proper description
    try:
        progress_bar = _tqdm(syms, desc="Downloading symbols", unit="symbol")
    except Exception:
        progress_bar = syms
    
    for sym in progress_bar:
        try:
            t = PSXTicker(sym)
            if interval == "1d":
                # Use full OHLCV historical with date range
                # get_historical already shows progress internally, so we skip here
                df = t.get_historical(start_date=start_date, end_date=end_date, show_progress=False)
            elif interval == "1m":
                df = t.intraday()
            else:
                raise ValueError("interval must be '1d' or '1m'")
            
            if not df.empty:
                frames[sym] = df
        except Exception as e:
            # Log failed symbol but continue with others
            failed_symbols.append((sym, str(e)))
            try:
                from loguru import logger
                logger.warning(f"Failed to download {sym}: {e}")
            except Exception:
                pass
            continue

    if failed_symbols:
        print(f"\n⚠️  Warning: {len(failed_symbols)} symbol(s) failed:")
        for sym, err in failed_symbols[:5]:  # Show first 5 failures
            print(f"  - {sym}: {err}")
        if len(failed_symbols) > 5:
            print(f"  ... and {len(failed_symbols) - 5} more")

    if not frames:
        return pd.DataFrame()

    # Align on index, join columns with a top level per symbol
    out = pd.concat(frames, axis=1)
    
    # Export to CSV if requested
    if to_csv:
        try:
            import os
            os.makedirs(os.path.dirname(to_csv) if os.path.dirname(to_csv) else ".", exist_ok=True)
            out.to_csv(to_csv)
            print(f"\n✅ Data exported to: {to_csv}")
        except Exception as e:
            print(f"\n⚠️  Warning: Failed to export to CSV: {e}")
    
    return out


def sectors() -> pd.DataFrame:
    """Get sector summary data."""
    return sector_summary()


def performers() -> Dict[str, pd.DataFrame]:
    """Get top performers data."""
    return top_performers()


# market_watch() is already imported from pypsx.market


def get_symbols() -> List[str]:
    """
    Get all symbols from trading board.
    
    Returns:
        List of stock symbols (strings)
    """
    df = get_symbols_from_trading_board()
    if df.empty:
        return []
    symbols_list = cast(List[str], df["Symbol"].astype(str).str.upper().tolist())
    return symbols_list


def listings_nc() -> List[str]:
    """Get normal counter listings (deprecated - use get_symbols())."""
    df = get_symbols_from_trading_board()
    if df.empty:
        return []
    # Filter for normal counter symbols (no tag or specific tag logic)
    filtered = df[~df["Tag"].str.contains("DC", na=False)]["Symbol"]
    symbols_list = cast(List[str], filtered.astype(str).str.upper().tolist())
    return symbols_list


def listings_dc() -> List[str]:
    """Get defaulters counter listings (deprecated - use get_symbols())."""
    df = get_symbols_from_trading_board()
    if df.empty:
        return []
    # Filter for defaulters counter symbols
    filtered = df[df["Tag"].str.contains("DC", na=False)]["Symbol"]
    symbols_list = cast(List[str], filtered.astype(str).str.upper().tolist())
    return symbols_list


def symbols_nc() -> List[str]:
    """Alias for listings_nc() (deprecated)."""
    return listings_nc()


def symbols_dc() -> List[str]:
    """Alias for listings_dc() (deprecated)."""
    return listings_dc()


def tickers() -> List[str]:
    """Alias for get_symbols() (deprecated)."""
    return get_symbols()


def trading_board() -> pd.DataFrame:
    """Get trading board data."""
    from pypsx.endpoints.trading_board import get_orderbook
    result = get_orderbook(format='dataframe')
    return result if result is not None else pd.DataFrame()


def index_constituents(index_code: str, force_refresh: bool = False) -> pd.DataFrame:
    """Get constituents of a specific index (e.g., KSE100, KMI30)."""
    result = get_index_constituents(index_code, format='dataframe', force_refresh=force_refresh)
    return result if result is not None else pd.DataFrame()


def get_historical(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_workers: int = 5
) -> pd.DataFrame:
    """
    Get full OHLCV historical data for a symbol.
    
    This function fetches complete Open, High, Low, Close, Volume data by making
    POST requests to https://dps.psx.com.pk/historical for each month.
    
    Args:
        symbol: Stock symbol
        start_date: Start date in "YYYY-MM-DD" format (default: 1 month ago)
        end_date: End date in "YYYY-MM-DD" format (default: today)
        max_workers: Maximum number of parallel threads for fetching months (default: 5)
        
    Returns:
        DataFrame with TIME as index and OPEN, HIGH, LOW, CLOSE, VOLUME columns
        
    Example:
        >>> df = pypsx.get_historical("OGDC", "2024-01-01", "2024-12-31")
        >>> print(df.head())
    """
    from pypsx.endpoints.historical import get_historical_data
    return get_historical_data(symbol, start_date, end_date, max_workers)


# get_indices() is already imported from pypsx.market


def get_intraday_multiple(symbols: List[str]) -> pd.DataFrame:
    """
    Get intraday (1m) data for multiple symbols, aligned on timestamp.

    This is a convenience wrapper around download() that fetches
    last-2-day intraday trades for each symbol and concatenates
    them into a single DataFrame with a top-level column per symbol.

    Args:
        symbols: List of stock symbols

    Returns:
        DataFrame with DatetimeIndex and MultiIndex columns (symbol, field)
    """
    return download(symbols, period="1d", interval="1m")


