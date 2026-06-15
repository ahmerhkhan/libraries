"""
Announcements data endpoint for PyPSX library.

Fetches company announcements data from PSX company page.
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
from pypsx.core.parse import clean_text
from pypsx.core.utils import beautify_dataframe, validate_symbol
from pypsx.format.json_utils import to_json


def get_announcements(symbol: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get company announcements data.
    
    Fetches announcements data from https://dps.psx.com.pk/company/{SYMBOL}
    including financial results, board meetings, and other announcements.
    
    Args:
        symbol: Stock symbol (e.g., "OGDC", "HBL")
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with announcements data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_announcements("OGDC")
        >>> print(df.head())
        
        Output (pandas DataFrame):
        | DATE | TITLE | SECTION | IMAGE_LINK | PDF_LINK |
        |------|-------|---------|------------|----------|
        | 2023-08-15 | Annual Results | Financial Results | /image/... | /pdf/... |
        | 2023-07-20 | Board Meeting | Board Meetings | None | /pdf/... |
    """
    try:
        # Validate symbol
        if not validate_symbol(symbol):
            logger.error(f"Invalid symbol: {symbol}")
            return None
        
        logger.info(f"Fetching announcements data for {symbol}")
        
        # Build URL
        url = f"https://dps.psx.com.pk/company/{symbol.upper()}"
        
        # Fetch HTML data
        soup = get_html(url)
        if not soup:
            logger.error(f"Failed to fetch announcements data for {symbol}")
            return None
        
        # Parse announcements data
        df = _parse_announcements_html(soup, symbol)
        if df is None or df.empty:
            # Return empty DataFrame with proper structure instead of None
            logger.warning(f"No announcements data found for {symbol}")
            # Return empty DataFrame with expected columns
            empty_df = pd.DataFrame(columns=['TITLE', 'SECTION', 'IMAGE_LINK', 'PDF_LINK'])
            empty_df.index.name = 'SYMBOL'
            return empty_df if format == 'dataframe' else []
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        logger.info(f"Successfully fetched announcements data for {symbol}: {len(df)} announcements")
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except Exception as e:
        logger.error(f"Error fetching announcements data for {symbol}: {e}")
        return None


def _parse_announcements_html(soup, symbol: str) -> Optional[pd.DataFrame]:
    """
    Parse announcements HTML data into DataFrame.
    
    Args:
        soup: BeautifulSoup object of the HTML page
        symbol: Stock symbol
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Find announcement tables
        tables = soup.select("div.tabs__panel table.tbl")
        
        if not tables:
            logger.warning("No announcement tables found in HTML")
            return None
        
        # Section mapping
        section_lookup = {
            0: "Financial Results",
            1: "Board Meetings", 
            2: "Others"
        }
        
        # Extract data from tables
        data = []
        for i, table in enumerate(tables):
            if i > 2:  # Ignore financial highlights tables
                continue
                
            section = section_lookup.get(i, "Unknown")
            
            # Extract rows from table
            rows = table.select("tbody tr")
            for row in rows:
                try:
                    cells = row.find_all("td")
                    if len(cells) < 3:
                        continue
                    
                    # Extract date
                    date = cells[0].get_text(strip=True)
                    
                    # Extract title
                    title = cells[1].get_text(strip=True)
                    
                    # Extract document links
                    doc_cell = cells[2]
                    
                    # Image link
                    img_url = None
                    img_tag = doc_cell.find("a", {"data-images": True})
                    if img_tag:
                        img_file = img_tag["data-images"]
                        img_url = f"https://dps.psx.com.pk/download/image/{img_file}"
                    
                    # PDF link
                    pdf_url = None
                    pdf_tag = doc_cell.find("a", href=True, target="_blank")
                    if pdf_tag:
                        pdf_url = f"https://dps.psx.com.pk{pdf_tag['href']}"
                    
                    if date and title:
                        data.append({
                            "DATE": date,
                            "TITLE": title,
                            "SECTION": section,
                            "IMAGE_LINK": img_url,
                            "PDF_LINK": pdf_url
                        })
                        
                except Exception as e:
                    logger.warning(f"Error parsing announcement row: {e}")
                    continue
        
        if not data:
            logger.warning("No valid announcement data extracted")
            return None
        
        # Create DataFrame
        df = pd.DataFrame(data)
        
        # Add symbol column
        df['SYMBOL'] = symbol.upper()
        
        # Set index
        df = df.set_index(['SYMBOL', 'DATE'])
        
        logger.info(f"Successfully parsed announcements HTML for {symbol}: {len(df)} announcements")
        return df
        
    except Exception as e:
        logger.error(f"Error parsing announcements HTML: {e}")
        return None

