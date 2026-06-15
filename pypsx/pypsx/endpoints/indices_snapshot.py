"""
Indices snapshot data endpoint for PyPSX library.

Fetches indices overview data from PSX indices page.
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

from pypsx.core.fetchers import fetch_html
from pypsx.core.utils import beautify_dataframe, get_psx_indices_snapshot_codes
from pypsx.endpoints.constants import INDICES_OVERVIEW_URL
from pypsx.format.json_utils import to_json
from bs4 import BeautifulSoup
import re


def get_indices_snapshot(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get indices snapshot data.
    Only returns PSX indices listed LIVE in dps.psx.com.pk/indices.
    """
    try:
        logger.info("Fetching indices snapshot data")
        # Get valid codes/names from utility
        live_codes = get_psx_indices_snapshot_codes()
        valid_codes_set = set(live_codes.keys())

        html = fetch_html(INDICES_OVERVIEW_URL, timeout=30.0, ttl=300)
        soup = BeautifulSoup(html, "html.parser")
        if not soup:
            logger.error("Failed to fetch indices snapshot data")
            return None
        # Parse full frame from page
        df = _parse_indices_snapshot_html(soup)
        if df is None or df.empty:
            logger.warning("No indices snapshot data parsed")
            return None

        # Limit to only live codes present in the snapshot
        filtered = df[df.index.isin(valid_codes_set)]
        filtered = beautify_dataframe(filtered)
        logger.info(f"Successfully fetched indices snapshot data: {len(filtered)} indices")
        if format == 'json':
            return to_json(filtered)
        else:
            return filtered
    except Exception as e:
        logger.error(f"Error fetching indices snapshot data: {e}")
        return None


def get_index_overview(index_name: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get overview data for a specific index.
    
    Args:
        index_name: Index name (e.g., "KSE100", "KMI30")
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with index overview or JSON dict, None if failed
    """
    try:
        # Get all indices snapshot
        snapshot_df = get_indices_snapshot(format='dataframe')
        if snapshot_df is None or snapshot_df.empty:
            return None
        
        # Filter for specific index
        if index_name.upper() in snapshot_df.index:
            index_data = snapshot_df.loc[index_name.upper()]
            
            if format == 'json':
                return to_json(index_data.to_frame().T)
            else:
                return index_data.to_frame().T
        else:
            logger.warning(f"Index {index_name} not found in snapshot")
            return None
            
    except Exception as e:
        logger.error(f"Error fetching index overview for {index_name}: {e}")
        return None


def _parse_indices_snapshot_html(soup) -> Optional[pd.DataFrame]:
    """
    Parse indices snapshot HTML data into DataFrame.
    
    Args:
        soup: BeautifulSoup object of the HTML page
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Find indices table
        table_rows = soup.select("table.tbl tbody tr")
        
        if not table_rows:
            logger.warning("No indices table found in HTML")
            return None
        
        # Extract data from rows
        data = []
        for row in table_rows:
            try:
                cols = row.select("td")
                if len(cols) < 6:
                    continue
                
                # Extract index name
                index_name_elem = cols[0].select_one("b")
                index_name = index_name_elem.get_text(strip=True) if index_name_elem else None
                
                if not index_name:
                    continue
                
                # Helper function to extract numeric values
                def get_numeric_value(cell):
                    raw = cell.get("data-order")
                    if raw and raw.replace(".", "").replace("-", "").isdigit():
                        return float(raw)
                    return None
                
                # Extract values
                high = get_numeric_value(cols[1])
                low = get_numeric_value(cols[2])
                current = get_numeric_value(cols[3])
                change = get_numeric_value(cols[4])
                percentage_change = get_numeric_value(cols[5])
                
                data.append({
                    "INDEX": index_name,
                    "HIGH": high,
                    "LOW": low,
                    "CURRENT": current,
                    "CHANGE": change,
                    "PERCENTAGE_CHANGE": percentage_change
                })
                
            except Exception as e:
                logger.warning(f"Error parsing indices row: {e}")
                continue
        
        if not data:
            logger.warning("No valid indices data extracted")
            return None
        
        # Create DataFrame
        df = pd.DataFrame(data)
        
        # Set index
        df = df.set_index('INDEX')
        
        logger.info(f"Successfully parsed indices snapshot HTML: {len(df)} indices")
        return df
        
    except Exception as e:
        logger.error(f"Error parsing indices snapshot HTML: {e}")
        return None


def get_homepage_indices_snapshot(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get indices snapshot from PSX homepage.
    
    Fetches the top indices displayed on the PSX homepage (https://dps.psx.com.pk/)
    including KSE100, KSE30, ALLSHR, KMI30, etc. with their current values,
    changes, and percentage changes.
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with index data or JSON dict, None if failed
        
    Example:
        >>> from pypsx.endpoints.indices_snapshot import get_homepage_indices_snapshot
        >>> df = get_homepage_indices_snapshot()
        >>> print(df.head())
        
        Output (pandas DataFrame):
        | NAME | VALUE | CHANGE | PERCENT_CHANGE |
        |------|-------|--------|----------------|
        | KSE100 | 161281.76 | -1521.39 | -0.93 |
        | KSE100PR | 50788.50 | -487.24 | -0.95 |
    """
    try:
        logger.info("Fetching homepage indices snapshot")
        homepage_url = "https://dps.psx.com.pk/"
        
        # Fetch HTML with proper headers
        html = fetch_html(homepage_url, timeout=30.0, ttl=60)
        soup = BeautifulSoup(html, "html.parser")
        
        if not soup:
            logger.error("Failed to fetch homepage")
            return None
        
        # Find all index blocks using the exact scraping logic
        data = []
        indices_items = soup.find_all('div', class_='topIndices__item')
        
        for item in indices_items:
            try:
                # Extract data using find (matching user's scraping logic)
                name_tag = item.find('div', class_='topIndices__item__name')
                value_tag = item.find('div', class_='topIndices__item__val')
                change_tag = item.find('div', class_='topIndices__item__change')
                changep_tag = item.find('div', class_='topIndices__item__changep')
                date_tag = item.find('div', class_='topIndices__item__date')  # optional
                
                name = name_tag.text.strip() if name_tag else None
                value_str = value_tag.text.strip() if value_tag else None
                change_str = change_tag.text.strip() if change_tag else None
                changep_str = changep_tag.text.strip() if changep_tag else None
                date = date_tag.text.strip() if date_tag else None
                
                if not name:
                    continue
                
                # Parse numeric values for convenience (keep raw strings too)
                # Value: remove commas and convert to float
                value = None
                if value_str:
                    try:
                        value = float(value_str.replace(",", ""))
                    except (ValueError, AttributeError):
                        pass
                
                # Change: extract numeric value
                change = None
                if change_str:
                    try:
                        # Remove any non-numeric characters except minus sign and decimal
                        change_str_clean = re.sub(r'[^\d.-]', '', change_str)
                        change = float(change_str_clean) if change_str_clean else None
                    except (ValueError, AttributeError):
                        pass
                
                # Percent change: extract numeric value from parentheses
                change_percent = None
                if changep_str:
                    try:
                        # Extract number from format like "(-0.93%)" or "(0.03%)"
                        match = re.search(r'\(([+-]?\d+\.?\d*)%\)', changep_str)
                        if match:
                            change_percent = float(match.group(1))
                    except (ValueError, AttributeError):
                        pass
                
                data.append({
                    "NAME": name,
                    "VALUE": value,
                    "VALUE_RAW": value_str,  # Keep raw string value
                    "CHANGE": change,
                    "CHANGE_RAW": change_str,  # Keep raw string change
                    "CHANGE_PERCENT": change_percent,
                    "CHANGE_PERCENT_RAW": changep_str,  # Keep raw string percent change
                    "DATE": date
                })
                
            except Exception as e:
                logger.warning(f"Error parsing index item: {e}")
                continue
        
        if not data:
            logger.warning("No homepage indices data extracted")
            return None
        
        # Create DataFrame
        df = pd.DataFrame(data)
        
        # Set name as index
        df = df.set_index('NAME')
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        logger.info(f"Successfully fetched homepage indices snapshot: {len(df)} indices")
        
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except Exception as e:
        logger.error(f"Error fetching homepage indices snapshot: {e}")
        return None

