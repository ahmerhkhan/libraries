"""
Company snapshot data endpoint for PyPSX library.

Fetches comprehensive snapshot data from all tabs on PSX company pages.
This is more holistic than get_quote as it extracts data from ALL tabs.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union, List
try:
    from loguru import logger
    logger.remove()
except Exception:
    class _N:
        def __getattr__(self, _):
            return lambda *a, **k: None
    logger = _N()

from pypsx.core.fetch import get_html
from pypsx.core.utils import validate_symbol, beautify_dataframe
from pypsx.format.json_utils import to_json
from pypsx.core.parse import clean_text, parse_number, parse_percentage


def get_snapshot(symbol: str, format: str = 'dict') -> Optional[Union[Dict[str, Any], pd.DataFrame]]:
    """
    Get comprehensive snapshot data from all tabs on company page.
    
    This is a more holistic approach than get_quote() as it extracts data
    from ALL tabs (REG, Intraday, etc.) on the company page.
    
    Args:
        symbol: Stock symbol (e.g., "OGDC", "BOP", "PPL")
        format: Output format - 'dict' (default) or 'dataframe'
        
    Returns:
        Dictionary with tab names as keys and stats as values, or DataFrame
        
    Example:
        >>> import pypsx
        >>> snapshot = pypsx.get_snapshot("BOP")
        >>> print(snapshot['REG'])
        {'Open': '34.11', 'High': '35.40', 'Low': '33.25', ...}
    """
    try:
        # Validate symbol
        try:
            normalized_symbol = validate_symbol(symbol)
        except ValueError:
            logger.error(f"Invalid symbol: {symbol}")
            return None
        
        logger.info(f"Fetching snapshot data for {normalized_symbol}")
        
        # Build URL
        url = f"https://dps.psx.com.pk/company/{normalized_symbol}"
        
        # Fetch HTML content
        soup = get_html(url)
        if not soup:
            logger.error(f"Failed to fetch HTML for {normalized_symbol}")
            return None
        
        # Extract snapshot data from all tabs
        snapshot_data = _extract_snapshot_data(soup, normalized_symbol)
        if not snapshot_data:
            logger.warning(f"No snapshot data found for {normalized_symbol}")
            return None
        
        logger.info(f"Successfully fetched snapshot data for {normalized_symbol}: {len(snapshot_data)} tabs")
        
        # Return based on format
        if format == 'dataframe':
            return _snapshot_dict_to_dataframe(snapshot_data, normalized_symbol)
        else:
            return snapshot_data
            
    except Exception as e:
        logger.error(f"Error fetching snapshot for {symbol}: {e}")
        return None


def _extract_snapshot_data(soup, symbol: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """
    Extract snapshot data from all tabs on the company page.
    
    Args:
        soup: BeautifulSoup object of the company page
        symbol: Stock symbol
        
    Returns:
        Dictionary with tab names as keys and stats dictionaries as values
    """
    try:
        all_data = {}
        
        # Find all tabs
        tabs = soup.find_all("div", class_="tabs__panel")
        
        if not tabs:
            logger.warning("No tabs found on company page")
            return None
        
        for tab in tabs:
            tab_name = tab.get("data-name")
            if not tab_name:
                continue
            
            panel_data = {}
            
            # Loop over all stats blocks in this tab
            stats_blocks = tab.find_all("div", class_="stats")
            for block in stats_blocks:
                for item in block.find_all("div", class_="stats_item"):
                    label_elem = item.find("div", class_="stats_label")
                    value_elem = item.find("div", class_="stats_value")
                    
                    if label_elem and value_elem:
                        label = clean_text(label_elem.get_text())
                        value = clean_text(value_elem.get_text())
                        
                        if label and value:
                            # Convert value based on type
                            cleaned_value = _parse_snapshot_value(label, value)
                            panel_data[label] = cleaned_value
            
            if panel_data:
                all_data[tab_name] = panel_data
        
        if not all_data:
            return None
            
        return all_data
        
    except Exception as e:
        logger.error(f"Error extracting snapshot data: {e}")
        return None


def _parse_snapshot_value(label: str, value: str) -> Any:
    """
    Parse snapshot value based on label and content.
    
    Args:
        label: Stats label
        value: Raw value string
        
    Returns:
        Parsed value (number, percentage, range tuple, or string)
    """
    if not value or value.strip() == '-':
        return None
    
    # Parse percentage values
    if '%' in value or ('change' in label.lower() and '%' not in value):
        return parse_percentage(value)
    
    # Parse ranges (e.g., "30.15 — 36.85")
    if ' — ' in value or ' - ' in value:
        try:
            parts = value.replace(' — ', ' - ').split(' - ')
            if len(parts) == 2:
                low = parse_number(parts[0].strip())
                high = parse_number(parts[1].strip())
                if low is not None and high is not None:
                    return (low, high)
        except Exception:
            pass
    
    # Parse numeric values
    if any(char.isdigit() for char in value.replace(',', '').replace('.', '').replace('-', '')):
        parsed = parse_number(value)
        if parsed is not None:
            return parsed
    
    # Return as string if no parsing worked
    return value.strip()


def _snapshot_dict_to_dataframe(snapshot_data: Dict[str, Dict[str, Any]], symbol: str) -> pd.DataFrame:
    """
    Convert snapshot dictionary to DataFrame.
    
    Args:
        snapshot_data: Dictionary with tab names and stats
        symbol: Stock symbol
        
    Returns:
        DataFrame with tab, metric, and value columns
    """
    rows = []
    for tab_name, stats in snapshot_data.items():
        for metric, value in stats.items():
            rows.append({
                'SYMBOL': symbol,
                'TAB': tab_name,
                'METRIC': metric,
                'VALUE': value
            })
    
    if not rows:
        return pd.DataFrame()
    
    df = pd.DataFrame(rows)
    df = df.set_index(['SYMBOL', 'TAB', 'METRIC'])
    return beautify_dataframe(df)

