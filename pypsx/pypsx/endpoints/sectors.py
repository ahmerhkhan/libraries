"""
Sector data endpoint for PyPSX library.

Fetches sector summaries and constituent data from PSX sector-summary endpoint.
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
from pypsx.core.parsers import parse_sector_summary_html
from pypsx.endpoints.constants import SECTOR_SUMMARY_URL
from pypsx.core.utils import beautify_dataframe
from pypsx.format.json_utils import to_json


def get_sector_summary(sector_code: Optional[str] = None, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get sector summary data.
    
    Fetches sector-level data from https://dps.psx.com.pk/sector-summary/sectorwise
    including advances, declines, turnover, and market cap for all sectors.
    Optionally, a sector_code parameter can fetch its constituents.
    
    Args:
        sector_code: Optional sector code to get constituents
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with sector data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_sector_summary()
        >>> print(df.head())
        
        Output (pandas DataFrame):
        | SECTOR_CODE | SECTOR_NAME | ADVANCES | DECLINES | UNCHANGED | TURNOVER | MARKET_CAP |
        |-------------|-------------|----------|----------|-----------|----------|-------------|
        | O&GMCs      | Oil & Gas   | 12       | 8        | 5         | 1.2B     | 2.5T        |
        | Banks       | Banking     | 15       | 10       | 3         | 2.1B     | 3.2T        |
    """
    try:
        logger.info("Fetching sector summary data")
        
        # Fetch HTML
        html = fetch_html(SECTOR_SUMMARY_URL, timeout=30.0, ttl=300)
        
        # Parse HTML tables
        if sector_code:
            # For sector constituents, we still need the old parser for now
            # as it handles table selection logic
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            df = _parse_sector_constituents_html(soup, sector_code)
        else:
            df = parse_sector_summary_html(html)
        if df is None or df.empty:
            logger.warning("No sector data parsed")
            return None
        
        # Filter by sector code if provided
        if sector_code:
            df = df[df.index == sector_code.upper()]
            if df.empty:
                logger.warning(f"No data found for sector {sector_code}")
                return None
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        logger.info(f"Successfully fetched sector summary data: {len(df)} sectors")
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except Exception as e:
        logger.error(f"Error fetching sector summary data: {e}")
        return None


def get_sector_constituents(sector_code: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get constituents for a specific sector.
    
    Args:
        sector_code: Sector code (e.g., 'O&GMCs', 'Banks')
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with sector constituents or JSON dict, None if failed
    """
    try:
        logger.info(f"Fetching constituents for sector {sector_code}")
        
        # Fetch HTML
        html = fetch_html(SECTOR_SUMMARY_URL, timeout=30.0, ttl=300)
        
        # Parse HTML tables for sector constituents
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        df = _parse_sector_constituents_html(soup, sector_code)
        if df is None or df.empty:
            logger.warning(f"No constituents data parsed for sector {sector_code}")
            return None
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        logger.info(f"Successfully fetched constituents for sector {sector_code}: {len(df)} companies")
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except Exception as e:
        logger.error(f"Error fetching constituents for sector {sector_code}: {e}")
        return None


def _parse_sector_summary_html(soup) -> Optional[pd.DataFrame]:
    """
    Parse sector summary HTML data into DataFrame.
    
    Args:
        soup: BeautifulSoup object of the HTML page
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Find all tables
        tables = soup.find_all('table')
        
        if not tables:
            logger.warning("No tables found in sector summary HTML")
            return None
        
        # Use the first table (sector summary)
        main_table = tables[0]
        
        # Extract table data using pandas
        import pandas as pd
        
        # Read HTML table directly with pandas
        from io import StringIO
        dfs = pd.read_html(StringIO(str(main_table)))
        if not dfs:
            logger.warning("No data extracted from sector summary table")
            return None
        
        df = dfs[0]  # Take the first (and usually only) DataFrame
        
        if df.empty:
            logger.warning("Empty DataFrame extracted from sector summary table")
            return None
        
        # Clean column names
        df.columns = [col.strip().upper() for col in df.columns]
        
        # Map column names to standard format
        column_mapping = {
            'SECTOR CODE': 'SECTOR_CODE',
            'SECTOR NAME': 'SECTOR_NAME',
            'ADVANCE': 'ADVANCES',
            'DECLINE': 'DECLINES',
            'UNCHANGE': 'UNCHANGED',
            'TURNOVER': 'TURNOVER',
            'MARKET CAP. (B)': 'MARKET_CAP'
        }
        
        # Rename columns
        df = df.rename(columns=column_mapping)
        
        # Set sector code as index
        if 'SECTOR_CODE' in df.columns:
            df = df.set_index('SECTOR_CODE')
        
        # Convert numeric columns
        numeric_columns = ['ADVANCES', 'DECLINES', 'UNCHANGED', 'TURNOVER', 'MARKET_CAP']
        for col in numeric_columns:
            if col in df.columns:
                # Handle comma-separated numbers
                if col in ['TURNOVER', 'MARKET_CAP']:
                    df[col] = df[col].astype(str).str.replace(',', '').str.replace(' ', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        logger.info(f"Successfully parsed sector summary HTML: {len(df)} sectors")
        return df
        
    except Exception as e:
        logger.error(f"Error parsing sector summary HTML: {e}")
        return None


def _parse_sector_constituents_html(soup, sector_code: str) -> Optional[pd.DataFrame]:
    """
    Parse sector constituents HTML data into DataFrame.
    
    Args:
        soup: BeautifulSoup object of the HTML page
        sector_code: Sector code to find constituents for
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Find all tables
        tables = soup.find_all('table')
        
        if not tables:
            logger.warning("No tables found in sector constituents HTML")
            return None
        
        # Find the table for the specific sector
        # Tables 2+ contain sector constituents
        sector_table = None
        
        # Map sector codes to table indices based on debug output
        sector_table_mapping = {
            "0801": 1,   # AUTOMOBILE ASSEMBLER
            "0802": 2,   # AUTOMOBILE PARTS & ACCESSORIES  
            "0803": 3,   # CABLE & ELECTRICAL GOODS
            "0804": 4,   # CEMENT
            "0805": 5,   # CHEMICAL
            "0820": 20,  # Oil & Gas (O&GMCs)
            "O&GMCs": 20,  # Alternative format for Oil & Gas
            "OIL & GAS": 20,  # Another alternative format
            # Add more mappings as needed
        }
        
        table_index = sector_table_mapping.get(sector_code)
        
        if table_index and table_index < len(tables):
            sector_table = tables[table_index]
        else:
            # Fallback: search through tables
            for i, table in enumerate(tables[1:], 1):  # Skip first table (summary)
                # Check if this table contains the sector code
                table_text = table.get_text()
                if sector_code in table_text:
                    sector_table = table
                    break
        
        if not sector_table:
            logger.warning(f"No table found for sector code {sector_code}")
            # Try to find by searching through table content
            for i, table in enumerate(tables[1:], 1):  # Skip first table (summary)
                table_text = table.get_text().upper()
                if sector_code.upper() in table_text or "OIL" in table_text and "GAS" in table_text:
                    sector_table = table
                    logger.info(f"Found sector table at index {i} by content search")
                    break
            
            if not sector_table:
                logger.warning(f"Could not find table for sector {sector_code} even after content search")
                return None
        
        # Parse table row by row to extract clean symbols and tags
        import pandas as pd
        from pypsx.core.symbol_parser import parse_symbol_from_td
        
        # Find header row to identify columns
        header_row = sector_table.find('tr')
        if not header_row:
            logger.warning("No header row found in sector constituents table")
            return None
        
        # Extract column names from header
        header_cells = header_row.find_all(['th', 'td'])
        column_names = []
        for cell in header_cells:
            col_name = cell.get_text(strip=True).upper()
            # Map common column name variations
            if 'CHANGE' in col_name and '%' in col_name:
                col_name = '%CHANGE'
            elif col_name == 'NAME':
                col_name = 'COMPANY_NAME'
            column_names.append(col_name)
        
        # If no column names found, use default
        if not column_names:
            column_names = ['SYMBOL', 'NAME', 'LDCP', 'OPEN', 'HIGH', 'LOW', 'CURRENT', 'CHANGE', '%CHANGE', 'VOLUME']
        
        # Parse data rows
        rows = sector_table.find_all('tr')[1:]  # Skip header row
        if not rows:
            logger.warning("No data rows found in sector constituents table")
            return None
        
        data_rows = []
        clean_symbols = []
        tags_list = []
        
        for row in rows:
            cells = row.find_all('td')
            if not cells:
                continue
            
            # Parse symbol from first cell using proper HTML parsing
            symbol_result = parse_symbol_from_td(cells[0])
            clean_symbol = symbol_result['symbol']
            tags = symbol_result['tags']
            
            if not clean_symbol:
                # Skip rows without valid symbols
                continue
            
            clean_symbols.append(clean_symbol)
            tags_list.append(','.join(tags) if tags else None)
            
            # Extract data from remaining cells
            row_data = {}
            for i, cell in enumerate(cells[1:], 1):  # Start from second cell
                if i < len(column_names):
                    col_name = column_names[i]
                    cell_text = cell.get_text(strip=True)
                    row_data[col_name] = cell_text
            
            # Also extract name if available (usually second column)
            if len(cells) > 1:
                name_cell = cells[1]
                name_text = name_cell.get_text(strip=True)
                if name_text:
                    row_data['COMPANY_NAME'] = name_text
            
            data_rows.append(row_data)
        
        if not data_rows:
            logger.warning("No valid data rows extracted from sector constituents table")
            return None
        
        # Create DataFrame
        df = pd.DataFrame(data_rows)
        
        # Add clean symbols and tags
        df.insert(0, 'SYMBOL', clean_symbols)
        if any(tag for tag in tags_list if tag):
            df['TAG'] = tags_list
        
        # Ensure we have standard columns
        if 'COMPANY_NAME' not in df.columns and 'NAME' in df.columns:
            df['COMPANY_NAME'] = df['NAME']
        
        # Map column names to standard format
        column_mapping = {
            'CHANGE (%)': '%CHANGE',
            'NAME': 'COMPANY_NAME'
        }
        df = df.rename(columns=column_mapping)
        
        # Set symbol as index
        if 'SYMBOL' in df.columns:
            df = df.set_index('SYMBOL')
        
        # Convert numeric columns
        numeric_columns = ['LDCP', 'OPEN', 'HIGH', 'LOW', 'CURRENT', 'CHANGE', '%CHANGE', 'VOLUME']
        for col in numeric_columns:
            if col in df.columns:
                # Handle comma-separated numbers and percentage values
                if col == 'VOLUME':
                    df[col] = df[col].astype(str).str.replace(',', '').str.replace(' ', '')
                elif col == '%CHANGE':
                    # Handle percentage values (remove % sign)
                    df[col] = df[col].astype(str).str.replace('%', '').str.replace(' ', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        logger.info(f"Successfully parsed sector constituents HTML for {sector_code}: {len(df)} stocks")
        return df
        
    except Exception as e:
        logger.error(f"Error parsing sector constituents HTML: {e}")
        return None


def _parse_sector_summary_data(data: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """
    Parse sector summary JSON data into DataFrame.
    
    Args:
        data: Raw JSON response data
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Extract sector data from JSON structure
        if 'data' not in data:
            logger.warning("No 'data' key found in sector summary response")
            return None
        
        sector_data = data['data']
        
        # Convert to DataFrame
        df = pd.DataFrame(sector_data)
        
        # Ensure required columns exist
        required_columns = ['SECTOR_CODE', 'SECTOR_NAME', 'ADVANCES', 'DECLINES', 'TURNOVER']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            logger.warning(f"Missing columns in sector data: {missing_columns}")
            # Create missing columns with default values
            for col in missing_columns:
                df[col] = None
        
        # Set sector code as index
        if 'SECTOR_CODE' in df.columns:
            df = df.set_index('SECTOR_CODE')
        
        return df
        
    except Exception as e:
        logger.error(f"Error parsing sector summary data: {e}")
        return None


def _parse_sector_constituents_data(data: Dict[str, Any], sector_code: str) -> Optional[pd.DataFrame]:
    """
    Parse sector constituents JSON data into DataFrame.
    
    Args:
        data: Raw JSON response data
        sector_code: Sector code
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Extract constituents data from JSON structure
        if 'data' not in data:
            logger.warning("No 'data' key found in sector constituents response")
            return None
        
        constituents_data = data['data']
        
        # Convert to DataFrame
        df = pd.DataFrame(constituents_data)
        
        # Add sector code
        df['SECTOR_CODE'] = sector_code
        
        # Ensure required columns exist
        required_columns = ['SYMBOL', 'SECTOR_CODE', 'CURRENT', 'VOLUME']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            logger.warning(f"Missing columns in constituents data: {missing_columns}")
            # Create missing columns with default values
            for col in missing_columns:
                df[col] = None
        
        # Set symbol as index
        if 'SYMBOL' in df.columns:
            df = df.set_index('SYMBOL')
        
        return df
        
    except Exception as e:
        logger.error(f"Error parsing sector constituents data: {e}")
        return None
