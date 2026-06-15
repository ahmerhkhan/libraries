"""
Trading board data endpoint for PyPSX library.

Fetches order book and bid/ask data from PSX trading-board endpoint.
"""

import pandas as pd
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, Union
try:
    from loguru import logger
    logger.remove()
except Exception:
    class _N:
        def __getattr__(self, _):
            return lambda *a, **k: None
    logger = _N()

from pypsx.core.fetchers import fetch_html
from pypsx.core.parsers import parse_trading_board_html
from pypsx.endpoints.constants import TRADING_BOARD_URL
from pypsx.core.utils import beautify_dataframe
from pypsx.format.json_utils import to_json


def get_orderbook(symbol: Optional[str] = None, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get trading board (order book) data.
    
    Fetches bid/ask data from https://dps.psx.com.pk/trading-board/REG/main
    including bid/ask prices and volumes for all compliant companies.
    Return only selected symbol data if symbol is provided.
    
    Args:
        symbol: Optional stock symbol to filter data
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with order book data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_orderbook("KEL")
        >>> print(df)
        
        Output (pandas DataFrame):
        | SYMBOL | BID_PRICE | BID_VOLUME | ASK_PRICE | ASK_VOLUME | SPREAD |
        |---------|-----------|------------|-----------|------------|---------|
        | KEL     | 45.50     | 1000       | 45.75     | 500        | 0.25    |
    """
    try:
        logger.info("Fetching trading board data")
        
        # Fetch HTML
        html = fetch_html(TRADING_BOARD_URL, timeout=30.0, ttl=30)
        
        # Parse HTML table
        df = parse_trading_board_html(html)
        if df is None or df.empty:
            logger.warning("No trading board data parsed")
            return None
        
        # Filter by symbol if provided using exact matching (no normalization)
        if symbol:
            try:
                key = symbol.upper()
                symbol_data = df[df.index == key]
                if symbol_data.empty:
                    logger.warning(f"No order book data found for symbol {symbol}")
                    return None
                df = symbol_data
            except ValueError as e:
                logger.error(f"Invalid symbol {symbol}: {e}")
                return None
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        logger.info(f"Successfully fetched trading board data: {len(df)} entries")
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except Exception as e:
        logger.error(f"Error fetching trading board data: {e}")
        return None




def get_symbol_orderbook(symbol: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get order book data for a specific symbol.
    
    Args:
        symbol: Stock symbol
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with symbol order book data or JSON dict, None if failed
    """
    return get_orderbook(symbol, format)


def get_symbols() -> pd.DataFrame:
    """
    Get all symbols from trading board, filtering out tags.
    
    This is the primary get_symbols function for the library. It scrapes
    the trading board to extract clean symbols, names, and tags.
    
    Returns:
        DataFrame with columns: Symbol, Name, Tag
        Rows with empty symbols are filtered out.
        
    Example:
        >>> from pypsx.endpoints.trading_board import get_symbols
        >>> df = get_symbols()
        >>> print(df.head())
    """
    try:
        html = fetch_html(TRADING_BOARD_URL, timeout=30.0, ttl=300)
        soup = BeautifulSoup(html, "html.parser")
        
        table = soup.find("table")
        if not table:
            logger.warning("No table found in trading board HTML")
            return pd.DataFrame(columns=["Symbol", "Name", "Tag"])
        
        rows = table.find_all("tr")
        data = []
        
        for row in rows[1:]:  # skip header
            cols = row.find_all("td")
            if not cols:
                continue
            
            # SYMBOL & TAG handling - use symbol parser to extract from href (clean, no suffixes)
            symbol_td = cols[0]
            from pypsx.core.symbol_parser import parse_symbol_from_td
            symbol_result = parse_symbol_from_td(symbol_td)
            symbol = symbol_result['symbol']
            tag = ','.join(symbol_result['tags']) if symbol_result['tags'] else ""
            
            # NAME handling
            # Sometimes the full company name is in the 'data-title' attribute of the link
            symbol_link = symbol_td.find("a") if symbol_td else None
            name = symbol_link.get("data-title", "").strip() if symbol_link else ""
            # Fallback: try to get name from the next column if available
            if not name and len(cols) > 1:
                name = cols[1].get_text(strip=True) if cols[1] else ""
            
            data.append({
                "Symbol": symbol,
                "Name": name,
                "Tag": tag
            })
        
        # Convert to DataFrame
        df = pd.DataFrame(data)
        
        # Clean duplicates or blank rows
        df = df[df["Symbol"].str.strip() != ""]
        
        logger.info(f"Successfully extracted {len(df)} symbols from trading board")
        return df
        
    except Exception as e:
        logger.error(f"Error fetching symbols from trading board: {e}")
        return pd.DataFrame(columns=["Symbol", "Name", "Tag"])
