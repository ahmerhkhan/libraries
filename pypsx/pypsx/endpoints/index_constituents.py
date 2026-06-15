"""
Index constituents endpoint for PyPSX library.

Fetches detailed constituent data for indices from PSX.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union
from io import StringIO
from loguru import logger

from pypsx.core.fetchers import fetch_html
from pypsx.core.cache import cache_delete
from pypsx.core.parsers import parse_index_constituents_html
from pypsx.endpoints.constants import get_index_url
from pypsx.core.utils import beautify_dataframe
from pypsx.format.json_utils import to_json
from bs4 import BeautifulSoup


INDEX_CONSTITUENTS_TTL = 60  # seconds


def get_index_constituents(
    index_code: str,
    format: str = 'dataframe',
    force_refresh: bool = False
) -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get constituent data for an index.
    
    Args:
        index_code: Index code (e.g., 'KMI30', 'KSE100')
        format: Output format - 'dataframe' or 'json'
        force_refresh: When True, bypass in-process cache to fetch live HTML
        
    Returns DataFrame with columns:
    - SYMBOL (index)
    - NAME: Company name
    - LDCP: Last day closing price
    - CURRENT: Current price
    - CHANGE: Price change
    - %CHANGE: Percentage change
    - IDX_WTG: Index weight percentage
    - IDX_POINT: Index points contribution
    - VOLUME: Trading volume
    - FREE_FLOAT: Free float shares in millions
    - MARKET_CAP: Market cap in millions
    """
    try:
        url = get_index_url(index_code)
        cache_key = f"GET::text::{url}"

        # Allow opt-in cache bypass to guarantee a fresh scrape
        fetch_ttl: Optional[int] = INDEX_CONSTITUENTS_TTL
        if force_refresh:
            cache_delete(cache_key)
            fetch_ttl = None
        
        # Fetch HTML
        html = fetch_html(url, timeout=30.0, ttl=fetch_ttl)
        
        # Parse HTML using parser
        df = parse_index_constituents_html(html)
        if df is None or df.empty:
            logger.error(f"Failed to parse constituents for {index_code}")
            return None
        
        # Beautify output
        df = beautify_dataframe(df)
        
        return df if format == 'dataframe' else to_json(df)
        
    except Exception as e:
        logger.error(f"Error getting constituents for {index_code}: {e}")
        return None