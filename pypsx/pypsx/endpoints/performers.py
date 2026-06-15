"""
Top performers data endpoint for PyPSX library.

Fetches top gainers, losers, and most active stocks from PSX performers endpoint.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union
from loguru import logger

from pypsx.core.fetchers import fetch_html, fetch_json
from pypsx.core.parsers import parse_performers_html, parse_performers_json
from pypsx.endpoints.constants import PERFORMERS_URL
from pypsx.core.utils import beautify_dataframe
from pypsx.format.json_utils import to_json


def get_performers(category: str = "active", format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get top performers data.
    
    Fetches top performers data from https://dps.psx.com.pk/performers
    based on category: "active", "advancers", or "decliners"
    
    Returns DataFrame with following columns:
    - SYMBOL (index)
    - PRICE: Current price
    - CHANGE: Price change (may be missing)
    - %CHANGE: Percentage change (may be missing)
    - VOLUME: Trading volume
    
    Note: CHANGE and %CHANGE may be 0 or missing for some entries.
    
    Args:
        category: Performance category - "active", "advancers", or "decliners"
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with performers data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> from pypsx.endpoints.performers import get_performers
        >>> df = get_performers("advancers")
        >>> print(df.head())
        
        Output (pandas DataFrame):
        | SYMBOL | PRICE | CHANGE | %CHANGE | VOLUME |
        |---------|-------|---------|----------|---------|
        | OGDC    | 106.90| +1.23   | +1.15%   | 5,233,000|
        | PPL     | 89.75 | +0.30   | +0.34%   | 2,156,000|
    """
    try:
        # Validate category
        valid_categories = ["active", "advancers", "decliners"]
        if category not in valid_categories:
            raise ValueError(f"Invalid category: {category}. Use one of: {valid_categories}")
        
        logger.info(f"Fetching top performers data for category: {category}")
        
        # Fetch HTML
        html = fetch_html(PERFORMERS_URL, timeout=30.0, ttl=30)
        
        # Parse HTML tables
        performers_dict = parse_performers_html(html)
        
        # Map category to parser output key
        category_map = {
            "active": "top_active",
            "advancers": "top_advancers",
            "decliners": "top_decliners"
        }
        
        key = category_map.get(category, "top_active")
        df = performers_dict.get(key, pd.DataFrame())
        
        if df is None or df.empty:
            logger.warning(f"No performers data parsed for category {category}")
            return None
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        logger.info(f"Successfully fetched performers data for {category}: {len(df)} stocks")
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except ValueError as e:
        logger.error(f"Invalid category {category}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching performers data for {category}: {e}")
        return None


def get_top_gainers(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get top gainers (advancers) data.
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with top gainers or JSON dict, None if failed
    """
    return get_performers("advancers", format)


def get_top_losers(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get top losers (decliners) data.
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with top losers or JSON dict, None if failed
    """
    return get_performers("decliners", format)


def get_most_active(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get most active stocks data.
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with most active stocks or JSON dict, None if failed
    """
    return get_performers("active", format)


def _parse_performers_html(soup, category: str) -> Optional[pd.DataFrame]:
    """
    Parse performers HTML data into DataFrame.
    
    Args:
        soup: BeautifulSoup object of the HTML page
        category: Performance category - "active", "advancers", or "decliners"
        
    Returns:
        Parsed DataFrame or None if failed
        
    Note: The performers table has CHANGE in combined format like "-0.46 (-7.57%)"
    We need to parse this into separate CHANGE and %CHANGE columns.
    """
    try:
        # Find all tables
        tables = soup.find_all('table')
        
        if not tables:
            logger.warning("No tables found in performers HTML")
            return None
        
        # Map category to table index as they appear on the page:
        # 0: Top Active Stocks, 1: Top Advancers, 2: Top Decliners
        table_mapping = {
            "active": 0,
            "advancers": 1,
            "decliners": 2,
        }
        
        table_index = table_mapping.get(category, 1)
        
        if table_index >= len(tables):
            logger.warning(f"Table index {table_index} not found for category {category}")
            return None
        
        main_table = tables[table_index]
        
        # Extract table data using pandas
        import pandas as pd
        
        # Read HTML table directly with pandas
        from io import StringIO
        dfs = pd.read_html(StringIO(str(main_table)))
        if not dfs:
            logger.warning("No data extracted from performers table")
            return None
        
        df = dfs[0]  # Take the first (and usually only) DataFrame
        
        if df.empty:
            logger.warning("Empty DataFrame extracted from performers table")
            return None
        
        # Clean column names
        df.columns = [col.strip().upper() for col in df.columns]

        # Extract CHANGE and %CHANGE from combined CHANGE column
        if 'CHANGE' in df.columns:
            # Keep original for reference
            df['CHANGE_ORIG'] = df['CHANGE'].astype(str)
            
            # Initialize empty columns
            df['CHANGE'] = 0.0
            df['%CHANGE'] = 0.0
            
            # Regex patterns for extracting values
            change_pattern = r'^([+-]?\d+\.?\d*)'
            percent_pattern = r'\(([+-]?\d+\.?\d*)%\)'
            
            # Process each row individually to avoid NaN creation
            for idx, value in df['CHANGE_ORIG'].items():
                try:
                    value = str(value).strip()
                    if not value or value.lower() in ('nan', 'none', 'n/a'):
                        continue
                        
                    # Extract absolute change
                    import re
                    change_match = re.search(change_pattern, value)
                    if change_match:
                        change_val = float(change_match.group(1))
                        df.at[idx, 'CHANGE'] = change_val
                    
                    # Extract percentage
                    percent_match = re.search(percent_pattern, value)
                    if percent_match:
                        percent_val = float(percent_match.group(1))
                        df.at[idx, '%CHANGE'] = percent_val
                except Exception as e:
                    logger.warning(f"Error parsing change value '{value}': {e}")
                    continue
                    
            # Drop the original column
            df = df.drop('CHANGE_ORIG', axis=1)
            
        # Ensure required numeric columns exist with proper defaults
        required_cols = {
            'PRICE': 0.0,
            'CHANGE': 0.0,
            '%CHANGE': 0.0,
            'VOLUME': 0
        }
        
        # Normalize CHANGE and %CHANGE
        import re
        if 'CHANGE' in df.columns and '%CHANGE' not in df.columns:
            change_series = df['CHANGE'].astype(str)
            ch_vals = []
            pct_vals = []
            for s in change_series:
                if s is None or s == '' or s.lower() == 'nan':
                    ch_vals.append(None)
                    pct_vals.append(None)
                    continue
                s_clean = s.replace(' ', '')
                # Extract percent if present
                m_pct = re.search(r'([+-]?\d+\.?\d*)%\)?$', s_clean)
                pct_val = float(m_pct.group(1)) if m_pct else None
                # Extract first signed float as change
                m_ch = re.search(r'^[\+\-]?\d+\.?\d*', s_clean)
                ch_val = float(m_ch.group(0)) if m_ch else None
                ch_vals.append(ch_val)
                pct_vals.append(pct_val)
            df['CHANGE'] = ch_vals
            df['%CHANGE'] = pct_vals
        
        # If %CHANGE column exists already (variant), clean it to numeric
        if '%CHANGE' in df.columns:
            df['%CHANGE'] = (
                df['%CHANGE']
                .astype(str)
                .str.replace('%', '', regex=False)
                .str.strip()
            )
            df['%CHANGE'] = pd.to_numeric(df['%CHANGE'], errors='coerce')
        
        # Set symbol as index
        if 'SYMBOL' in df.columns:
            df = df.set_index('SYMBOL')
        
        # Drop placeholder/noise rows that appear in PSX tables (e.g., 'XD', 'NC')
        # and any rows without a valid PRICE
        try:
            bad_symbols = {"XD", "EX", "XR", "XRD", "EXD", "NC"}
            idx_series = df.index.astype(str).str.strip().str.upper()
            drop_mask = idx_series.isin(bad_symbols) | df.get('PRICE', pd.Series(index=df.index)).isna()
            if drop_mask.any():
                df = df[~drop_mask]
        except Exception:
            pass
        
        # Convert numeric columns
        for col, default in required_cols.items():
            # Ensure column exists
            if col not in df.columns:
                df[col] = default
            else:
                # Clean and convert data
                if col == 'VOLUME':
                    df[col] = (
                        df[col]
                        .astype(str)
                        .str.replace(',', '')
                        .str.replace(' ', '')
                        .pipe(pd.to_numeric, errors='coerce')
                        .fillna(default)
                    )
                else:
                    df[col] = (
                        pd.to_numeric(df[col], errors='coerce')
                        .fillna(default)
                    )

        # Avoid NaN in %CHANGE if missing: default to 0 when CHANGE present but percent not found
        if '%CHANGE' in df.columns and 'CHANGE' in df.columns:
            mask = df['%CHANGE'].isna() & df['CHANGE'].notna()
            if mask.any():
                df.loc[mask, '%CHANGE'] = 0.0

        # Final safety: if CHANGE/%CHANGE still NaN, set to 0 (page sometimes omits it)
        if 'CHANGE' in df.columns:
            df['CHANGE'] = df['CHANGE'].fillna(0.0)
        if '%CHANGE' in df.columns:
            df['%CHANGE'] = df['%CHANGE'].fillna(0.0)
        
        logger.info(f"Successfully parsed performers HTML for {category}: {len(df)} stocks")
        return df
        
    except Exception as e:
        logger.error(f"Error parsing performers HTML: {e}")
        return None


def _parse_performers_data(data: Dict[str, Any], category: str) -> Optional[pd.DataFrame]:
    """
    Parse performers JSON data into DataFrame.
    
    Args:
        data: Raw JSON response data
        category: Performance category
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Extract performers data from JSON structure
        if 'data' not in data:
            logger.warning("No 'data' key found in performers response")
            return None
        
        performers_data = data['data']
        
        # Filter by category if the data structure supports it
        if isinstance(performers_data, dict) and category in performers_data:
            category_data = performers_data[category]
        else:
            category_data = performers_data
        
        # Convert to DataFrame
        df = pd.DataFrame(category_data)
        
        # Ensure required columns exist
        required_columns = ['SYMBOL', 'PRICE', 'CHANGE', 'VOLUME']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            logger.warning(f"Missing columns in performers data: {missing_columns}")
            # Create missing columns with default values
            for col in missing_columns:
                df[col] = None
        
        # Add category column
        df['CATEGORY'] = category
        
        # Set symbol as index
        if 'SYMBOL' in df.columns:
            df = df.set_index('SYMBOL')
        
        return df
        
    except Exception as e:
        logger.error(f"Error parsing performers data: {e}")
        return None
