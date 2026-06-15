"""
Reports data endpoint for PyPSX library.

Fetches financial reports data from PSX company reports endpoint.
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


def get_reports(symbol: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get financial reports for a company.
    
    Fetches financial reports data from https://dps.psx.com.pk/company/reports/{SYMBOL}
    including report_type, period_ended, posting_date, and pdf_link.
    
    Args:
        symbol: Stock symbol (e.g., "OGDC", "HBL")
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with reports data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_reports("OGDC")
        >>> print(df.head())
        
        Output (pandas DataFrame):
        | REPORT_TYPE | PERIOD_ENDED | POSTING_DATE | PDF_LINK |
        |-------------|--------------|--------------|----------|
        | Annual      | 2023-06-30   | 2023-08-15   | /pdf/... |
        | Quarterly   | 2023-09-30   | 2023-10-15   | /pdf/... |
    """
    try:
        # Validate symbol
        if not validate_symbol(symbol):
            logger.error(f"Invalid symbol: {symbol}")
            return None
        
        logger.info(f"Fetching reports data for {symbol}")
        
        # Build URL
        url = f"https://dps.psx.com.pk/company/reports/{symbol.upper()}"
        
        # Fetch HTML data
        soup = get_html(url)
        if not soup:
            logger.error(f"Failed to fetch reports data for {symbol}")
            return None
        
        # Parse reports data
        df = _parse_reports_html(soup, symbol)
        if df is None or df.empty:
            logger.warning(f"No reports data parsed for {symbol}")
            return None
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        logger.info(f"Successfully fetched reports data for {symbol}: {len(df)} reports")
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except Exception as e:
        logger.error(f"Error fetching reports data for {symbol}: {e}")
        return None


def _parse_reports_html(soup, symbol: str) -> Optional[pd.DataFrame]:
    """
    Parse reports HTML data into DataFrame.
    
    Args:
        soup: BeautifulSoup object of the HTML page
        symbol: Stock symbol
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        # Find reports table
        rows = soup.select("table.tbl tbody tr")
        
        if not rows:
            logger.warning("No reports table found in HTML")
            return None
        
        # Extract data from rows
        data = []
        for row in rows:
            try:
                # Extract report type
                report_type_cell = row.select_one("td:nth-child(1)")
                report_type = report_type_cell.get_text(strip=True) if report_type_cell else None
                
                # Extract period ended
                period_cell = row.select_one("td:nth-child(2)")
                period_ended = period_cell.get_text(strip=True) if period_cell else None
                
                # Extract posting date
                posting_cell = row.select_one("td:nth-child(3)")
                posting_date = posting_cell.get_text(strip=True) if posting_cell else None
                
                # Extract PDF link
                link_tag = row.select_one("a")
                pdf_link = None
                if link_tag and link_tag.get("href"):
                    href = link_tag.get('href')
                    if href.startswith('http://') or href.startswith('https://'):
                        pdf_link = href
                    else:
                        try:
                            from urllib.parse import urljoin
                            pdf_link = urljoin("https://dps.psx.com.pk", href)
                        except Exception:
                            pdf_link = f"https://dps.psx.com.pk{href}"
                
                if report_type and period_ended and posting_date:
                    data.append({
                        "REPORT_TYPE": report_type,
                        "PERIOD_ENDED": period_ended,
                        "POSTING_DATE": posting_date,
                        "PDF_LINK": pdf_link
                    })
                    
            except Exception as e:
                logger.warning(f"Error parsing report row: {e}")
                continue
        
        if not data:
            logger.warning("No valid report data extracted")
            return None
        
        # Create DataFrame
        df = pd.DataFrame(data)
        
        # Add symbol column
        df['SYMBOL'] = symbol.upper()
        
        # Set index
        df = df.set_index(['SYMBOL', 'REPORT_TYPE'])
        
        logger.info(f"Successfully parsed reports HTML for {symbol}: {len(df)} reports")
        return df
        
    except Exception as e:
        logger.error(f"Error parsing reports HTML: {e}")
        return None

