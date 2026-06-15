"""
Company quote data endpoint for PyPSX library.

Fetches detailed quote data from PSX company pages.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union
try:
    from loguru import logger
    logger.remove()
except Exception:
    class _N:
        def __getattr__(self, _):
            return lambda *a, **k: None
    logger = _N()

from pypsx.core.fetch import get_html
from pypsx.core.parse import extract_stats_items, clean_text, parse_number, parse_percentage
from pypsx.core.utils import validate_symbol, beautify_dataframe
from pypsx.format.json_utils import to_json


def get_quote(symbol: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get detailed quote data for a stock symbol.
    
    Fetches comprehensive quote data from https://dps.psx.com.pk/company/{SYMBOL}
    including OHLCV, LDCP, change %, circuit breaker, day range, 52 week range,
    bid ask price, volume, PE ratio, VAT, haircut, 1yr change, YTD, VAR and other key stats.
    
    Args:
        symbol: Stock symbol (e.g., 'OGDC', 'HBL', 'PSO')
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with quote data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_quote("OGDC")
        >>> print(df)
        
        Output (pandas DataFrame):
        | SYMBOL | CURRENT | CHANGE | %CHANGE | VOLUME | BID | ASK | 52W RANGE | PE | YTD | VAR |
        |---------|----------|---------|----------|----------|-------|-------|-------------|-----|-----|-----|
        | OGDC    | 106.9    | +1.23   | +1.15%   | 5,233,000 | 106.5 | 107.0 | 82 - 114   | 4.5 | 6%  | 0.12 |
    """
    try:
        # Validate and normalize symbol
        try:
            normalized_symbol = validate_symbol(symbol)
        except ValueError:
            logger.error(f"Invalid symbol: {symbol}")
            return None
        
        logger.info(f"Fetching quote data for {normalized_symbol}")
        
        # Build URL
        url = f"https://dps.psx.com.pk/company/{normalized_symbol}"
        
        # Fetch HTML content
        soup = get_html(url)
        if not soup:
            logger.error(f"Failed to fetch HTML for {normalized_symbol}")
            return None
        
        # Extract comprehensive quote data
        quote_data = _extract_comprehensive_quote_data(soup, normalized_symbol)
        if not quote_data:
            logger.warning(f"No quote data found for {normalized_symbol}")
            return None
        
        # Create DataFrame
        df = pd.DataFrame([quote_data])
        df = df.set_index('SYMBOL')
        
        # Beautify DataFrame
        df = beautify_dataframe(df, normalized_symbol)
        
        logger.info(f"Successfully fetched quote data for {normalized_symbol}")
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except ValueError as e:
        logger.error(f"Invalid symbol {symbol}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching quote for {symbol}: {e}")
        return None


def get_quote_batch(symbols: list, format: str = 'dataframe') -> Dict[str, Optional[Union[pd.DataFrame, Dict[str, Any]]]]:
    """
    Get quote data for multiple symbols.
    
    Args:
        symbols: List of stock symbols
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        Dictionary mapping symbol -> quote data
    """
    results = {}
    
    for symbol in symbols:
        try:
            results[symbol] = get_quote(symbol, format)
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            results[symbol] = None
    
    return results


def _extract_comprehensive_quote_data(soup, symbol: str) -> Optional[Dict[str, Any]]:
    """
    Extract comprehensive quote data from company page HTML.
    
    Args:
        soup: BeautifulSoup object of the company page
        symbol: Stock symbol
        
    Returns:
        Dictionary with quote data or None if failed
    """
    try:
        quote_data = {'SYMBOL': symbol}
        
        # Extract stats items from the main stats panel
        stats = extract_stats_items(soup)
        if stats:
            quote_data.update(stats)
        
        # Try to extract bid/ask data from trading board or other sections
        bid_ask_data = _extract_bid_ask_data(soup)
        if bid_ask_data:
            quote_data.update(bid_ask_data)
        
        # Extract additional data from various sections
        additional_data = _extract_additional_quote_data(soup)
        if additional_data:
            quote_data.update(additional_data)
        
        # Ensure we have at least some basic data
        if len(quote_data) <= 1:  # Only symbol
            return None
            
        return quote_data
        
    except Exception as e:
        logger.error(f"Error extracting comprehensive quote data: {e}")
        return None


def _extract_bid_ask_data(soup) -> Optional[Dict[str, Any]]:
    """
    Extract bid/ask data from various possible locations in the HTML.
    
    Args:
        soup: BeautifulSoup object
        
    Returns:
        Dictionary with bid/ask data or None if not found
    """
    try:
        bid_ask_data = {}
        
        # Look for bid/ask in stats items
        for item in soup.select('.stats_item'):
            label_elem = item.select_one('.stats_label')
            value_elem = item.select_one('.stats_value')
            
            if label_elem and value_elem:
                label = clean_text(label_elem.get_text())
                value = clean_text(value_elem.get_text())
                
                if label and value:
                    # Map common bid/ask labels
                    if 'bid' in label.lower() and 'price' in label.lower():
                        bid_ask_data['BID_PRICE'] = parse_number(value)
                    elif 'ask' in label.lower() and 'price' in label.lower():
                        bid_ask_data['ASK_PRICE'] = parse_number(value)
                    elif 'bid' in label.lower() and 'volume' in label.lower():
                        bid_ask_data['BID_VOLUME'] = parse_number(value)
                    elif 'ask' in label.lower() and 'volume' in label.lower():
                        bid_ask_data['ASK_VOLUME'] = parse_number(value)
        
        # Look for bid/ask in tables
        for table in soup.select('table'):
            rows = table.select('tr')
            for row in rows:
                cells = row.select('td, th')
                if len(cells) >= 2:
                    label = clean_text(cells[0].get_text())
                    value = clean_text(cells[1].get_text())
                    
                    if label and value:
                        if 'bid' in label.lower() and 'price' in label.lower():
                            bid_ask_data['BID_PRICE'] = parse_number(value)
                        elif 'ask' in label.lower() and 'price' in label.lower():
                            bid_ask_data['ASK_PRICE'] = parse_number(value)
                        elif 'bid' in label.lower() and 'volume' in label.lower():
                            bid_ask_data['BID_VOLUME'] = parse_number(value)
                        elif 'ask' in label.lower() and 'volume' in label.lower():
                            bid_ask_data['ASK_VOLUME'] = parse_number(value)
        
        # If no bid/ask data found, set to None to indicate market might be closed
        if not bid_ask_data:
            bid_ask_data = {
                'BID_PRICE': None,
                'ASK_PRICE': None,
                'BID_VOLUME': None,
                'ASK_VOLUME': None
            }
        
        return bid_ask_data
        
    except Exception as e:
        logger.error(f"Error extracting bid/ask data: {e}")
        return None


def _extract_additional_quote_data(soup) -> Optional[Dict[str, Any]]:
    """
    Extract additional quote data from various sections.
    
    Args:
        soup: BeautifulSoup object
        
    Returns:
        Dictionary with additional data or None if not found
    """
    try:
        additional_data = {}
        
        # Look for any additional metrics in various sections
        for section in soup.select('.quote-section, .market-data, .trading-info'):
            for item in section.select('.metric, .data-item, .stat'):
                label_elem = item.select_one('.label, .metric-label, .stat-label')
                value_elem = item.select_one('.value, .metric-value, .stat-value')
                
                if label_elem and value_elem:
                    label = clean_text(label_elem.get_text())
                    value = clean_text(value_elem.get_text())
                    
                    if label and value:
                        # Clean and convert value based on content
                        if '%' in value:
                            additional_data[label] = parse_percentage(value)
                        elif any(char.isdigit() for char in value):
                            additional_data[label] = parse_number(value)
                        else:
                            additional_data[label] = value
        
        return additional_data if additional_data else None
        
    except Exception as e:
        logger.error(f"Error extracting additional quote data: {e}")
        return None
