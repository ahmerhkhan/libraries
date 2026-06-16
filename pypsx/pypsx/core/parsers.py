"""
Data parsing module for PyPSX library.

Converts raw HTML/JSON responses into clean pandas DataFrames.
Follows fetch → parse → expose pattern by providing pure parsing functions.
"""

import pandas as pd
from typing import Dict, Any
from io import StringIO
from bs4 import BeautifulSoup
import re
from pypsx.core.symbol_parser import parse_symbol_from_td


def _num(series: pd.Series) -> pd.Series:
    """Convert series to numeric, coercing errors to NaN."""
    return pd.to_numeric(series, errors='coerce')


def parse_market_watch_html(html: str) -> pd.DataFrame:
    """
    Parse market watch HTML into DataFrame.
    
    Extracts symbols without tags (XD, NC, XR) and maps sector codes to names.
    
    Args:
        html: Raw HTML text from market watch endpoint
        
    Returns:
        DataFrame with Symbol as index and market data columns (symbols without tags)
    """
    # Parse HTML with BeautifulSoup to extract clean symbols
    soup = BeautifulSoup(html, "html.parser")
    
    # Use pandas to read table structure
    tables = pd.read_html(StringIO(html))
    if not tables:
        return pd.DataFrame()
    df = tables[0].copy()
    
    # Normalize column names - handle variations
    df.columns = [str(c).strip() for c in df.columns]
    
    # Map common column name variations
    column_mapping = {
        'Symbol': ['Symbol', 'SYMBOL', 'symbol'],
        'Sector': ['Sector', 'SECTOR', 'sector'],
        'Listed In': ['Listed In', 'Listed In Indices', 'Listed In Indices ', 'LISTED IN'],
        'LDCP': ['LDCP', 'ldcp', 'Last Day Closing Price'],
        'Open': ['Open', 'OPEN', 'open'],
        'High': ['High', 'HIGH', 'high'],
        'Low': ['Low', 'LOW', 'low'],
        'Current': ['Current', 'CURRENT', 'current', 'Last', 'Price'],
        'Change': ['Change', 'CHANGE', 'change'],
        'Change %': ['Change %', 'Change%', 'CHANGE %', 'Percent Change', '% Change'],
        'Volume': ['Volume', 'VOLUME', 'volume', 'Vol'],
    }
    
    # Standardize column names
    for standard, variants in column_mapping.items():
        for variant in variants:
            if variant in df.columns and standard not in df.columns:
                df.rename(columns={variant: standard}, inplace=True)
                break
    
    # Keep expected columns (include all that exist)
    expected = [
        'Symbol', 'Sector', 'Listed In', 'LDCP', 'Open', 'High', 'Low', 'Current', 'Change', 'Change %', 'Volume'
    ]
    keep = [c for c in expected if c in df.columns]
    if keep:
        df = df[keep]
    
    # Extract clean symbols from HTML using symbol parser utility
    if 'Symbol' in df.columns:
        # Find all symbol cells in the table
        table = soup.find('table')
        if table:
            rows = table.find_all('tr')
            clean_symbols = []
            tags_list = []
            
            for row in rows[1:]:  # Skip header
                first_td = row.find('td')
                if first_td:
                    result = parse_symbol_from_td(first_td)
                    clean_symbols.append(result['symbol'])
                    tags_list.append(','.join(result['tags']) if result['tags'] else '')
            
            # If we extracted symbols, replace the Symbol column
            if clean_symbols and len(clean_symbols) == len(df):
                df['Symbol'] = clean_symbols
                if tags_list:
                    df['Tags'] = tags_list
            else:
                # Fallback: strip tags from existing symbols
                df['Symbol'] = df['Symbol'].astype(str).str.replace(r'(XD|XR|NC)$', '', regex=True, case=False).str.strip().str.upper()
    
    # Map sector codes to sector names
    if 'Sector' in df.columns:
        from pypsx.core.utils import get_sector_code_to_name_map
        sector_map = get_sector_code_to_name_map()
        
        def map_sector_code(code: Any) -> str:
            """Map sector code to sector name."""
            if pd.isna(code) or code == '':
                return ''
            code_str = str(code).strip()
            # Check if it's already a name (contains letters) or a code (just numbers)
            if code_str.isdigit() and code_str in sector_map:
                return sector_map[code_str]
            # If it's already a name or mapping failed, return as is
            return code_str
        
        df['Sector'] = df['Sector'].apply(map_sector_code)
    
    # Extract data directly from HTML cells to ensure we get all available values
    # This supplements pandas.read_html which may miss data in complex HTML structures
    table = soup.find('table')
    if table and not df.empty and 'Symbol' in df.columns:
        rows = table.find_all('tr')[1:]  # Skip header
        header_row = table.find('tr')
        if header_row:
            headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
            # Find column indices in HTML
            col_indices = {}
            for col_name in ['LDCP', 'Open', 'High', 'Low', 'Current', 'Change', 'Change %', 'Volume']:
                for idx, header in enumerate(headers):
                    if col_name.lower() in header.lower() or header.lower() in col_name.lower():
                        col_indices[col_name] = idx
                        break
        
        # Extract data from each row
        for df_idx, html_row in enumerate(rows):
            if df_idx >= len(df):
                break
            cells = html_row.find_all('td')
            
            for col_name in ['LDCP', 'Open', 'High', 'Low', 'Current', 'Change', 'Change %', 'Volume']:
                if col_name not in df.columns:
                    continue
                
                # Try to find the cell index
                cell_idx = col_indices.get(col_name)
                if cell_idx is None or cell_idx >= len(cells):
                    continue
                
                cell = cells[cell_idx]
                # Get data-order attribute first (most reliable for numeric data)
                data_order = cell.get('data-order', '')
                if data_order:
                    try:
                        clean_val = str(data_order).replace(',', '').replace('%', '').strip()
                        # Check if it's a valid number
                        if clean_val and (clean_val.replace('.', '').replace('-', '').isdigit() or 
                                         (clean_val.startswith('-') and clean_val[1:].replace('.', '').isdigit())):

                            # Use iloc since index hasn't been set to Symbol yet
                            df.iloc[df_idx, df.columns.get_loc(col_name)] = float(clean_val)
                            continue
                    except (ValueError, TypeError, IndexError, KeyError):
                        pass
                
                # Fallback: get text content
                cell_text = cell.get_text(strip=True)
                if cell_text and cell_text not in ['-', 'N/A', '', 'nan', 'NaN']:
                    try:
                        clean_val = str(cell_text).replace(',', '').replace('%', '').strip()
                        # More flexible number parsing
                        if clean_val and (clean_val.replace('.', '').replace('-', '').isdigit() or
                                         (clean_val.startswith('-') and clean_val[1:].replace('.', '').isdigit())):
                            # Use iloc since index hasn't been set to Symbol yet
                            df.iloc[df_idx, df.columns.get_loc(col_name)] = float(clean_val)
                    except (ValueError, TypeError, IndexError, KeyError):
                        pass
    
    # Coerce numerics - convert to proper types
    # Don't fill NaN with 0 - preserve NaN to indicate missing data vs 0.0 values
    for c in ['LDCP', 'Open', 'High', 'Low', 'Current', 'Change']:
        if c in df.columns:
            df[c] = _num(df[c].astype(str).str.replace(',', '', regex=False))
    
    if 'Change %' in df.columns:
        df['Change %'] = _num(df['Change %'].astype(str).str.replace('%', '', regex=False))
    
    if 'Volume' in df.columns:
        df['Volume'] = _num(df['Volume'].astype(str).str.replace(',', '', regex=False))
    
    # Ensure Listed In is always a list (never null)
    if 'Listed In' in df.columns:
        df['Listed In'] = df['Listed In'].fillna('').astype(str)
        # Convert comma-separated string to list if needed
        df['Listed In'] = df['Listed In'].apply(lambda x: [s.strip() for s in str(x).split(',') if s.strip()] if x else [])
    
    # Ensure Sector is never null
    if 'Sector' in df.columns:
        df['Sector'] = df['Sector'].fillna('')
    
    # Ensure Symbol column exists and set as index
    if 'Symbol' in df.columns:
        df['Symbol'] = df['Symbol'].astype(str).str.upper().str.strip()
        df = df.set_index('Symbol')
    
    # Drop any rows with completely empty Symbol
    if not df.empty:
        df = df[df.index.notna() & (df.index != '')]
    
    return df


def parse_performers_html(html: str) -> Dict[str, pd.DataFrame]:
    """
    Parse performers HTML into dictionary of DataFrames.
    
    Extracts clean symbols without tags (XD, NC, XR) and adds Tag column.
    
    Args:
        html: Raw HTML text from performers endpoint
        
    Returns:
        Dictionary with keys: 'top_active', 'top_advancers', 'top_decliners'
        Each value is a DataFrame with Symbol as index and Tag column
    """
    # Parse HTML with BeautifulSoup to extract symbols and tags
    soup = BeautifulSoup(html, "html.parser")
    
    dfs = pd.read_html(StringIO(html))
    out: Dict[str, pd.DataFrame] = {}
    names = ["top_active", "top_advancers", "top_decliners"]
    for i, t in enumerate(dfs[:3]):
        d = t.copy()
        # Normalize headers to consistent title case and Symbol capitalization
        d.columns = [
            (str(c).strip().title() if str(c).strip().upper() != 'SYMBOL' else 'Symbol')
            for c in d.columns
        ]
        # Keep only fields that actually exist
        base_keep = ['Symbol', 'Price', 'Change', 'Volume']
        present = [c for c in base_keep if c in d.columns]
        d = d[present]
        
        # Extract clean symbols and tags from HTML using symbol parser
        if 'Symbol' in d.columns:
            # Find symbol cells in HTML table
            tables = soup.find_all('table')
            if i < len(tables):
                table = tables[i]
                rows = table.find_all('tr')
                clean_symbols = []
                tags = []
                
                for row in rows[1:]:  # Skip header
                    first_td = row.find('td')
                    if first_td:
                        result = parse_symbol_from_td(first_td)
                        clean_symbols.append(result['symbol'])
                        tag_str = ','.join(result['tags']) if result['tags'] else '-'
                        tags.append(tag_str)
                
                # If we extracted symbols, replace the Symbol column
                if clean_symbols and len(clean_symbols) == len(d):
                    d['Symbol'] = clean_symbols
                    d['Tag'] = tags
                else:
                    # Fallback: strip tags from existing symbols
                    d['Symbol'] = d['Symbol'].astype(str).str.replace(r'(XD|XR|NC)$', '', regex=True, case=False).str.strip().str.upper()
                    d['Tag'] = "-"
            
            d['Symbol'] = d['Symbol'].astype(str).str.upper().str.strip()
            d = d.set_index('Symbol')
        # Coerce Price/Volume numerics
        if 'Price' in d.columns:
            d['Price'] = _num(d['Price'].astype(str).str.replace(',', '', regex=False))
        if 'Volume' in d.columns:
            d['Volume'] = _num(d['Volume'].astype(str).str.replace(',', '', regex=False))
        # Split Change into Change and %Change when possible
        if 'Change' in d.columns:
            raw = d['Change'].astype(str)
            # Remove icons like <i ...> if any residual markup
            raw = raw.str.replace(r"<[^>]+>", "", regex=True).str.strip()
            # Extract price change
            price_series = raw.str.extract(r"([+-]?[0-9]*\.?[0-9]+)")[0]
            # Extract percentage inside parentheses
            pct_series = raw.str.extract(r"\(([+-]?[0-9]*\.?[0-9]+)%\)")[0]
            # Coerce to numeric
            price_num = pd.to_numeric(price_series, errors='coerce')
            pct_num = pd.to_numeric(pct_series, errors='coerce')
            # Assign numeric columns
            d['Change'] = price_num
            if 'Change %' in d.columns:
                d = d.drop(columns=['Change %'])
            d['Change %'] = pct_num
        out[names[i]] = d
    return out


def parse_performers_json(payload: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """
    Parse performers JSON into dictionary of DataFrames.
    
    Args:
        payload: JSON dict from performers endpoint
        
    Returns:
        Dictionary with keys: 'top_active', 'top_advancers', 'top_decliners'
    """
    out: Dict[str, pd.DataFrame] = {}
    mapping = {
        'top_active': ['top_active', 'active', 'most_active'],
        'top_advancers': ['top_advancers', 'advancers', 'gainers'],
        'top_decliners': ['top_decliners', 'decliners', 'losers'],
    }
    for target, keys in mapping.items():
        block = None
        for k in keys:
            if k in payload and isinstance(payload[k], (list, tuple)):
                block = payload[k]
                break
        if block is None:
            continue
        rows: list[dict] = []
        for item in block:
            if isinstance(item, dict):
                rows.append(item)
        if not rows:
            out[target] = pd.DataFrame()
            continue
        df = pd.DataFrame(rows)
        # Normalize column names
        rename_map: dict[str, str] = {}
        for c in df.columns:
            lc = str(c).strip().lower()
            if lc in ('symbol', 'sym'):
                rename_map[c] = 'Symbol'
            elif lc in ('price',):
                rename_map[c] = 'Price'
            elif lc in ('change', 'chg'):
                rename_map[c] = 'Change'
            elif lc in ('change_%', 'change_pct', 'percent_change', 'pct_change'):
                rename_map[c] = 'Change %'
            elif lc in ('volume', 'vol'):
                rename_map[c] = 'Volume'
        if rename_map:
            df = df.rename(columns=rename_map)
        keep = [c for c in ['Symbol', 'Price', 'Change', 'Change %', 'Volume'] if c in df.columns]
        df = df[keep]
        if 'Price' in df.columns:
            df['Price'] = pd.to_numeric(df['Price'], errors='coerce')
        if 'Volume' in df.columns:
            df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
        if 'Symbol' in df.columns:
            df['Symbol'] = df['Symbol'].astype(str).str.upper()
            df = df.set_index('Symbol')
        out[target] = df
    return out


def parse_sector_summary_html(html: str) -> pd.DataFrame:
    """
    Parse sector summary HTML into DataFrame.
    
    Args:
        html: Raw HTML text from sector summary endpoint
        
    Returns:
        DataFrame with Sector Code as index
    """
    tables = pd.read_html(StringIO(html))
    if not tables:
        return pd.DataFrame()
    df = tables[0].copy()
    
    # Normalize column names
    df.columns = [str(c).strip() for c in df.columns]
    
    column_mapping = {
        'Sector Code': ['Sector Code', 'SECTOR CODE', 'sector code', 'Code'],
        'Sector Name': ['Sector Name', 'SECTOR NAME', 'sector name', 'Name', 'Sector'],
        'Advance': ['Advance', 'ADVANCE', 'advance', 'Advances'],
        'Decline': ['Decline', 'DECLINE', 'decline', 'Declines'],
        'Unchange': ['Unchange', 'UNCHANGE', 'unchange', 'Unchanged'],
        'Turnover': ['Turnover', 'TURNOVER', 'turnover'],
        'Market Cap (B)': ['Market Cap (B)', 'Market Cap', 'MARKET CAP (B)', 'Market Cap (Billion)'],
    }
    
    for standard, variants in column_mapping.items():
        for variant in variants:
            if variant in df.columns and standard not in df.columns:
                df.rename(columns={variant: standard}, inplace=True)
                break
    
    expected = ['Sector Code', 'Sector Name', 'Advance', 'Decline', 'Unchange', 'Turnover', 'Market Cap (B)']
    keep = [c for c in expected if c in df.columns]
    if keep:
        df = df[keep]
    
    # Ensure no nulls for sector summary fields
    for c in ['Advance', 'Decline', 'Unchange']:
        if c in df.columns:
            df[c] = _num(df[c]).fillna(0)
    
    for c in ['Turnover', 'Market Cap (B)']:
        if c in df.columns:
            df[c] = _num(df[c].astype(str).str.replace(',', '', regex=False)).fillna(0.0)
    
    # Ensure sector name is never null
    if 'Sector Name' in df.columns:
        df['Sector Name'] = df['Sector Name'].fillna('')
    
    if 'Sector Code' in df.columns:
        df['Sector Code'] = df['Sector Code'].astype(str).str.strip()
        df = df.set_index('Sector Code')
    elif 'Sector Name' in df.columns and len(df) > 0:
        df.index.name = 'Sector Code'
    
    if not df.empty:
        df = df[df.index.notna() & (df.index != '')]
    
    return df


def parse_index_constituents_html(html: str) -> pd.DataFrame:
    """
    Parse index constituents HTML into DataFrame.
    
    Args:
        html: Raw HTML text from index endpoint
        
    Returns:
        DataFrame with Symbol as index
    """
    # Parse HTML with BeautifulSoup to extract symbols from href links
    soup = BeautifulSoup(html, "html.parser")
    
    # First, try to get data using pandas for easier column handling
    tables = pd.read_html(StringIO(html))
    if not tables:
        return pd.DataFrame()
    df = tables[0].copy()
    df.columns = [str(c).strip() for c in df.columns]
    
    # Try to match column names more flexibly
    column_mapping = {
        'Symbol': ['Symbol', 'SYMBOL', 'symbol'],
        'Name': ['Name', 'NAME', 'name', 'Company Name', 'COMPANY NAME'],
        'LDCP': ['LDCP', 'Last Day Closing Price', 'LAST DAY CLOSING PRICE'],
        'Current': ['Current', 'CURRENT', 'current', 'Current Price', 'CURRENT PRICE'],
        'Change': ['Change', 'CHANGE', 'change'],
        'Change %': ['Change %', 'CHANGE %', 'change %', '%Change', '%CHANGE', 'Change (%)', 'CHANGE (%)'],
        'IDX WTG %': ['IDX WTG %', 'IDX WTG (%)', 'IDX WTG', 'Index Weight %', 'IDX_WTG'],
        'IDX Point': ['IDX Point', 'IDX POINT', 'IDX Point Contribution', 'IDX_POINT'],
        'Volume': ['Volume', 'VOLUME', 'volume'],
        'Freefloat (M)': ['Freefloat (M)', 'Freefloat', 'FREEFLOAT (M)', 'FREEFLOAT', 'Free Float'],
        'Market Cap (M)': ['Market Cap (M)', 'Market Cap', 'MARKET CAP (M)', 'MARKET CAP', 'Market Capitalization']
    }
    
    # Create mapping from actual column names to standardized names
    rename_map = {}
    for standard_name, variants in column_mapping.items():
        for variant in variants:
            if variant in df.columns and standard_name not in rename_map.values():
                rename_map[variant] = standard_name
                break
    
    # Rename columns
    df = df.rename(columns=rename_map)
    
    # Keep all available columns from our mapping
    keep = ['Symbol', 'Name', 'LDCP', 'Current', 'Change', 'Change %', 'IDX WTG %', 'IDX Point', 'Volume', 'Freefloat (M)', 'Market Cap (M)']
    available_cols = [c for c in keep if c in df.columns]
    if available_cols:
        df = df[available_cols].copy()
    # If no standard columns found, keep all original columns
    if df.empty and len(tables[0]) > 0:
        df = tables[0].copy()
    
    # Extract clean symbols from HTML using href links (symbols in href don't have suffixes)
    if 'Symbol' in df.columns:
        # Find symbol cells in HTML table and extract from href
        table = soup.find('table')
        if table:
            rows = table.find_all('tr')
            clean_symbols = []
            
            for row in rows[1:]:  # Skip header
                first_td = row.find('td')
                if first_td:
                    result = parse_symbol_from_td(first_td)
                    clean_symbols.append(result['symbol'])
                else:
                    clean_symbols.append('')
            
            # If we extracted symbols, replace the Symbol column
            if clean_symbols and len(clean_symbols) == len(df):
                df['Symbol'] = clean_symbols
            else:
                # Fallback: strip tags from existing symbols
                df['Symbol'] = df['Symbol'].astype(str).str.replace(r'(XD|XR|NC|DC)$', '', regex=True, case=False).str.strip().str.upper()
        else:
            # Fallback if no table found
            df['Symbol'] = df['Symbol'].astype(str).str.replace(r'(XD|XR|NC|DC)$', '', regex=True, case=False).str.strip().str.upper()
        
        df = df.set_index('Symbol')
    # Ensure no nulls for index constituent fields
    for c in ['LDCP', 'Current', 'Change', 'IDX WTG %', 'IDX Point', 'Volume', 'Freefloat (M)', 'Market Cap (M)']:
        if c in df.columns:
            df[c] = _num(df[c].astype(str).str.replace(',', '', regex=False).str.replace('%', '', regex=False)).fillna(0.0)
    if 'Change %' in df.columns:
        df['Change %'] = _num(df['Change %'].astype(str).str.replace('%', '', regex=False)).fillna(0.0)
    
    # Ensure Name is never null
    if 'Name' in df.columns:
        df['Name'] = df['Name'].fillna('')
    return df


def parse_timeseries_intraday_json(payload: Dict[str, Any]) -> pd.DataFrame:
    """
    Parse intraday timeseries JSON into DataFrame.
    
    Args:
        payload: JSON dict from intraday timeseries endpoint
        
    Returns:
        DataFrame with Timestamp as index
    """
    data = payload.get('data') or []
    if not data:
        return pd.DataFrame()
    if isinstance(data[0], list) and len(data[0]) >= 3:
        df = pd.DataFrame(data, columns=['Timestamp', 'Price', 'Volume'])
    else:
        df = pd.DataFrame(data)
        df = df.rename(columns={'timestamp': 'Timestamp', 'price': 'Price', 'volume': 'Volume'})
    df = df[[c for c in ['Timestamp', 'Price', 'Volume'] if c in df.columns]]
    
    if 'Timestamp' in df.columns:
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='s', errors='coerce')
        df = df.set_index('Timestamp')
    
    for c in ['Price', 'Volume']:
        if c in df.columns:
            df[c] = _num(df[c])
    return df


def parse_timeseries_eod_json(payload: Dict[str, Any]) -> pd.DataFrame:
    """
    Parse end-of-day timeseries JSON into DataFrame.
    
    IMPORTANT: EOD timeseries returns [timestamp, close, volume, open] - NOT OHLCV!
    This is for charting purposes only. For actual OHLCV data, use historical endpoint.
    
    Args:
        payload: JSON dict from EOD timeseries endpoint
        
    Returns:
        DataFrame with Timestamp as index and columns: Close, Volume, Open
    """
    data = payload.get('data') or []
    if not data:
        return pd.DataFrame()
    
    if isinstance(data[0], list):
        # EOD format: [timestamp, close, volume, open]
        # According to changes.md, this is NOT OHLCV - it's timestamp, close, volume, open
        if len(data[0]) >= 4:
            # We have: timestamp, close, volume, open
            df = pd.DataFrame(data, columns=['Timestamp', 'Close', 'Volume', 'Open'])
        elif len(data[0]) >= 3:
            # Fallback: timestamp, close, volume (no open)
            df = pd.DataFrame(data, columns=['Timestamp', 'Close', 'Volume'])
            df['Open'] = df['Close']  # Use close as open if not provided
        else:
            return pd.DataFrame()
    else:
        df = pd.DataFrame(data)
        df = df.rename(columns={
            'timestamp': 'Timestamp', 
            'close': 'Close', 
            'volume': 'Volume', 
            'open': 'Open'
        })
    
    # Keep only the columns we actually have from EOD endpoint
    valid_cols = ['Timestamp', 'Close', 'Volume', 'Open']
    df = df[[c for c in valid_cols if c in df.columns]]
    
    if 'Timestamp' in df.columns:
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='s', errors='coerce')
        df = df.set_index('Timestamp')
    
    # Ensure we have Open column - if not, set it from Close
    if 'Open' not in df.columns and 'Close' in df.columns:
        df['Open'] = df['Close']
    
    # Convert to numeric
    for c in ['Close', 'Volume', 'Open']:
        if c in df.columns:
            df[c] = _num(df[c])
    
    return df


def parse_trading_board_html(html: str) -> pd.DataFrame:
    """
    Parse trading board HTML into DataFrame.
    
    Extracts clean symbols without tags (XD, NC, XR) and adds Tag column.
    
    Args:
        html: Raw HTML text from trading board endpoint
        
    Returns:
        DataFrame with Symbol as index and Tag column
    """
    # Parse HTML with BeautifulSoup to extract symbols and tags
    soup = BeautifulSoup(html, "html.parser")
    
    tables = pd.read_html(StringIO(html))
    if not tables:
        return pd.DataFrame()
    df = tables[0].copy()
    
    # Normalize column names
    df.columns = [str(c).strip() for c in df.columns]
    
    column_mapping = {
        'Symbol': ['Symbol', 'SYMBOL', 'symbol'],
        'Name': ['Name', 'NAME', 'name', 'Company Name'],
        'Bid Volume': ['Bid Volume', 'BID VOLUME', 'bid volume', 'Bid Vol'],
        'Bid Price': ['Bid Price', 'BID PRICE', 'bid price', 'Bid'],
        'Offer Volume': ['Offer Volume', 'OFFER VOLUME', 'offer volume', 'Offer Vol'],
        'Offer Price': ['Offer Price', 'OFFER PRICE', 'offer price', 'Offer', 'Ask Price'],
        'LDCP': ['LDCP', 'ldcp', 'Last Day Closing Price'],
        'Change': ['Change', 'CHANGE', 'change'],
        'Volume': ['Volume', 'VOLUME', 'volume', 'Vol'],
    }
    
    for standard, variants in column_mapping.items():
        for variant in variants:
            if variant in df.columns and standard not in df.columns:
                df.rename(columns={variant: standard}, inplace=True)
                break
    
    expected = ['Symbol', 'Name', 'Bid Volume', 'Bid Price', 'Offer Volume', 'Offer Price', 'LDCP', 'Change', 'Volume']
    keep = [c for c in expected if c in df.columns]
    if keep:
        df = df[keep]
    
    # Extract clean symbols and tags from HTML using symbol parser
    if 'Symbol' in df.columns:
        table = soup.find("table")
        if table:
            rows = table.find_all("tr")
            clean_symbols = []
            tags = []
            
            for row in rows[1:]:  # skip header
                first_td = row.find("td")
                if first_td:
                    result = parse_symbol_from_td(first_td)
                    clean_symbols.append(result['symbol'])
                    tag_str = ','.join(result['tags']) if result['tags'] else '-'
                    tags.append(tag_str)
            
            # If we extracted symbols, replace the Symbol column
            if clean_symbols and len(clean_symbols) == len(df):
                df['Symbol'] = clean_symbols
                df['Tag'] = tags
            else:
                # Fallback: strip tags from existing symbols
                df['Symbol'] = df['Symbol'].astype(str).str.replace(r'(XD|XR|NC)$', '', regex=True, case=False).str.strip().str.upper()
                df['Tag'] = "-"
        
        df['Symbol'] = df['Symbol'].astype(str).str.upper().str.strip()
        df = df.set_index('Symbol')
    
    # Ensure no nulls for trading board fields
    numeric_cols = ['Bid Volume', 'Bid Price', 'Offer Volume', 'Offer Price', 'LDCP', 'Change', 'Volume']
    for c in numeric_cols:
        if c in df.columns:
            df[c] = _num(df[c].astype(str).str.replace(',', '', regex=False)).fillna(0.0)
    
    # Ensure Name is never null
    if 'Name' in df.columns:
        df['Name'] = df['Name'].fillna('')
    
    if not df.empty:
        df = df[df.index.notna() & (df.index != '')]
    
    return df

