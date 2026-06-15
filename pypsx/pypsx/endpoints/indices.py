"""
Indices data endpoint for PyPSX library.

Fetches index constituent data from PSX indices endpoint.
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

from pypsx.core.fetchers import fetch_html, fetch_json
from pypsx.core.parsers import parse_index_constituents_html
from pypsx.endpoints.constants import get_index_url
from pypsx.core.utils import beautify_dataframe, get_psx_indices_snapshot_codes
from pypsx.format.json_utils import to_json


def get_index(index_name: str = "KSE100", format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get index constituents data.
    Index must exist in current PSX snapshot; do not use hardcoded lists.
    """
    try:
        # Dynamically validated indices
        live_codes = get_psx_indices_snapshot_codes().keys()
        if index_name not in live_codes:
            logger.warning(f"Index {index_name} not in PSX indices snapshot.")
            return None
        logger.info(f"Fetching index constituents data for {index_name}")
        url = get_index_url(index_name)
        html = fetch_html(url, timeout=30.0, ttl=300)
        df = parse_index_constituents_html(html)
        if df is None or df.empty:
            logger.warning(f"No index data parsed for {index_name}")
            return None
        df = beautify_dataframe(df)
        logger.info(f"Successfully fetched index constituents data for {index_name}: {len(df)} constituents")
        if format == 'json':
            return to_json(df)
        else:
            return df
    except Exception as e:
        logger.error(f"Error fetching index constituents data for {index_name}: {e}")
        return None


def get_all_indices(format: str = 'dataframe') -> Dict[str, Optional[Union[pd.DataFrame, Dict[str, Any]]]]:
    """
    Get data for all PSX indices present in the live snapshot.
    """
    results = {}
    try:
        live_codes = get_psx_indices_snapshot_codes().keys()
        for index_name in live_codes:
            try:
                results[index_name] = get_index(index_name, format)
            except Exception as e:
                logger.error(f"Error fetching data for {index_name}: {e}")
                results[index_name] = None
    except Exception as exc:
        logger.error(f"Error fetching list of indices: {exc}")
    return results


def _parse_index_constituents_html(soup, index_name: str) -> Optional[pd.DataFrame]:
    """
    Parse index constituents HTML data into DataFrame.
    
    Args:
        soup: BeautifulSoup object of the HTML page
        index_name: Index name
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Find all tables
        tables = soup.find_all('table')
        
        if not tables:
            logger.warning("No tables found in index constituents HTML")
            return None
        
        # Use the first (and usually only) table
        main_table = tables[0]
        
        # Extract table data using pandas
        import pandas as pd
        
        # Read HTML table directly with pandas
        from io import StringIO
        dfs = pd.read_html(StringIO(str(main_table)))
        if not dfs:
            logger.warning("No data extracted from index constituents table")
            return None
        
        df = dfs[0]  # Take the first (and usually only) DataFrame
        
        if df.empty:
            logger.warning("Empty DataFrame extracted from index constituents table")
            return None
        
        # Clean column names
        df.columns = [col.strip().upper() for col in df.columns]
        
        # Map column names to standard format
        column_mapping = {
            'CHANGE (%)': '%CHANGE',
            'IDX WTG (%)': 'IDX_WTG',  # Standardize to IDX_WTG
            'IDX POINT': 'IDX_POINT',  # Standardize to IDX_POINT
            'FREEFLOAT (M)': 'FREE_FLOAT',  # Standardize to FREE_FLOAT
            'MARKET CAP (M)': 'MARKET_CAP',
            'WEIGHT (%)': 'IDX_WTG',  # Alternative format
            'CONTRIBUTION': 'IDX_POINT'  # Alternative format
        }
        
        # Rename columns
        df = df.rename(columns=column_mapping)
        
        # Extract clean symbols from HTML using href links (symbols in href don't have suffixes)
        if 'SYMBOL' in df.columns:
            from pypsx.core.symbol_parser import parse_symbol_from_td
            # Find symbol cells in HTML table and extract from href
            main_table = tables[0] if tables else None
            if main_table:
                rows = main_table.find_all('tr')
                clean_symbols = []
                
                for row in rows[1:]:  # Skip header
                    first_td = row.find('td')
                    if first_td:
                        result = parse_symbol_from_td(first_td)
                        clean_symbols.append(result['symbol'])
                    else:
                        clean_symbols.append('')
                
                # If we extracted symbols, replace the SYMBOL column
                if clean_symbols and len(clean_symbols) == len(df):
                    df['SYMBOL'] = clean_symbols
                else:
                    # Fallback: strip tags from existing symbols
                    df['SYMBOL'] = df['SYMBOL'].astype(str).str.replace(r'(XD|XR|NC|DC)$', '', regex=True, case=False).str.strip().str.upper()
            else:
                # Fallback if no table found
                df['SYMBOL'] = df['SYMBOL'].astype(str).str.replace(r'(XD|XR|NC|DC)$', '', regex=True, case=False).str.strip().str.upper()
            
            df = df.set_index('SYMBOL')
        
        # Convert numeric columns
        numeric_columns = ['LDCP', 'CURRENT', 'CHANGE', '%CHANGE', 'IDX_WTG', 'IDX_POINT', 'VOLUME', 'FREE_FLOAT', 'MARKET_CAP']
        for col in numeric_columns:
            if col in df.columns:
                # Handle comma-separated numbers
                if col in ['VOLUME', 'FREE_FLOAT', 'MARKET_CAP']:
                    df[col] = df[col].astype(str).str.replace(',', '').str.replace(' ', '')
                elif col in ['%CHANGE', 'IDX_WTG']:
                    # Handle percentage values (remove % sign)
                    df[col] = df[col].astype(str).str.replace('%', '').str.replace(' ', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Ensure all required fields exist with proper defaults
        numeric_defaults = {
            'LDCP': 0.0,
            'CURRENT': 0.0,
            'CHANGE': 0.0,
            '%CHANGE': 0.0,
            'IDX_WTG': 0.0,
            'IDX_POINT': 0.0,
            'VOLUME': 0,
            'FREE_FLOAT': 0,
            'MARKET_CAP': 0.0
        }
        
        for col, default in numeric_defaults.items():
            if col not in df.columns:
                df[col] = default
            else:
                df[col] = df[col].fillna(default)  # Replace NaN with defaults
        
        logger.info(f"Successfully parsed index constituents HTML for {index_name}: {len(df)} stocks")
        return df
        
    except Exception as e:
        logger.error(f"Error parsing index constituents HTML: {e}")
        return None


def _parse_index_constituents_data(data: Dict[str, Any], index_name: str) -> Optional[pd.DataFrame]:
    """
    Parse index constituents JSON data into DataFrame.
    
    Args:
        data: Raw JSON response data
        index_name: Index name
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Extract index data from JSON structure
        if 'data' not in data:
            logger.warning("No 'data' key found in index constituents response")
            return None
        
        index_data = data['data']
        
        # Convert to DataFrame
        df = pd.DataFrame(index_data)
        
        # Add index name
        df['INDEX_NAME'] = index_name
        
        # Ensure required columns exist
        required_columns = ['SYMBOL', 'INDEX_NAME', 'WEIGHT', 'CONTRIBUTION']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            logger.warning(f"Missing columns in index data: {missing_columns}")
            # Create missing columns with default values
            for col in missing_columns:
                df[col] = None
        
        # Set symbol as index
        if 'SYMBOL' in df.columns:
            df = df.set_index('SYMBOL')
        
        return df
        
    except Exception as e:
        logger.error(f"Error parsing index constituents data: {e}")
        return None
