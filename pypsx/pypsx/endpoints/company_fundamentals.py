"""
Company fundamentals data endpoint for PyPSX library.

Fetches comprehensive company fundamentals data from PSX company page.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union
from loguru import logger

from pypsx.core.fetch import get_html
from pypsx.core.parse import clean_text
from pypsx.core.utils import beautify_dataframe, validate_symbol
from pypsx.format.json_utils import to_json


def get_company_fundamentals(symbol: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get comprehensive company fundamentals data.
    
    Fetches company fundamentals from https://dps.psx.com.pk/company/{SYMBOL}
    including business description, key people, financials, ratios, and equity profile.
    
    Args:
        symbol: Stock symbol (e.g., "OGDC", "HBL")
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with fundamentals data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_company_fundamentals("OGDC")
        >>> print(df.head())
        
        Output (pandas DataFrame):
        | CATEGORY | METRIC | VALUE |
        |----------|--------|-------|
        | Profile | Business Description | Oil & Gas... |
        | Governance | CEO | John Doe |
        | Financials | Revenue 2023 | 1000M |
    """
    try:
        # Validate symbol
        if not validate_symbol(symbol):
            logger.error(f"Invalid symbol: {symbol}")
            return None
        
        logger.info(f"Fetching company fundamentals data for {symbol}")
        
        # Build URL
        url = f"https://dps.psx.com.pk/company/{symbol.upper()}"
        
        # Fetch HTML data
        soup = get_html(url)
        if not soup:
            logger.error(f"Failed to fetch company fundamentals data for {symbol}")
            return None
        
        # Parse fundamentals data
        df = _parse_fundamentals_html(soup, symbol)
        if df is None or df.empty:
            logger.warning(f"No fundamentals data parsed for {symbol}")
            return None
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        logger.info(f"Successfully fetched company fundamentals data for {symbol}: {len(df)} data points")
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except Exception as e:
        logger.error(f"Error fetching company fundamentals data for {symbol}: {e}")
        return None


def _parse_fundamentals_html(soup, symbol: str) -> Optional[pd.DataFrame]:
    """
    Parse company fundamentals HTML data into DataFrame.
    
    Args:
        soup: BeautifulSoup object of the HTML page
        symbol: Stock symbol
        
    Returns:
        Parsed DataFrame or None if failed
    """
    try:
        data = []
        
        # COMPANY DESCRIPTION
        desc_section = soup.select_one("#profile .profile__item--decription p")
        if desc_section:
            data.append({
                "CATEGORY": "Profile",
                "METRIC": "Business Description",
                "VALUE": desc_section.get_text(strip=True)
            })
        
        # KEY PEOPLE
        people_section = soup.select("#profile .profile__item--people table.tbl tbody tr")
        for row in people_section:
            try:
                name_elem = row.select_one("td strong")
                title_elem = row.select_one("td:nth-child(2)")
                if name_elem and title_elem:
                    data.append({
                        "CATEGORY": "Governance",
                        "METRIC": name_elem.get_text(strip=True),
                        "VALUE": title_elem.get_text(strip=True)
                    })
            except Exception as e:
                logger.warning(f"Error parsing key people row: {e}")
                continue
        
        # ADDRESS
        address = soup.select_one("#profile .profile__items .profile__item p")
        if address:
            data.append({
                "CATEGORY": "Profile",
                "METRIC": "Address",
                "VALUE": address.get_text(strip=True)
            })
        
        # WEBSITE - Try multiple selectors
        website_selectors = [
            "#profile .profile__items .profile__item a",
            "#profile a[href^='http']",
            ".profile__item a",
            "a[href*='www']",
            "a[href*='http']",
            ".profile__items a",
            "#profile a"
        ]
        
        website_found = False
        for selector in website_selectors:
            website_els = soup.select(selector)
            for website_el in website_els:
                href = website_el.get("href", "")
                if href and ("http" in href or "www" in href):
                    data.append({
                        "CATEGORY": "Profile",
                        "METRIC": "Website",
                        "VALUE": href
                    })
                    website_found = True
                    break
            if website_found:
                break
        
        # If no website found, try to extract from text content
        if not website_found:
            for item in soup.select("#profile .profile__item"):
                text = item.get_text(strip=True)
                if "www." in text or "http" in text:
                    # Extract URL from text
                    import re
                    url_match = re.search(r'(https?://[^\s]+|www\.[^\s]+)', text)
                    if url_match:
                        data.append({
                            "CATEGORY": "Profile",
                            "METRIC": "Website",
                            "VALUE": url_match.group(1)
                        })
                        break
        
        # EQUITY PROFILE
        for item in soup.select("#equity .stats_item"):
            try:
                label_elem = item.select_one(".stats_label")
                value_elem = item.select_one(".stats_value")
                if label_elem and value_elem:
                    data.append({
                        "CATEGORY": "Equity Profile",
                        "METRIC": label_elem.get_text(strip=True),
                        "VALUE": value_elem.get_text(strip=True)
                    })
            except Exception as e:
                logger.warning(f"Error parsing equity profile item: {e}")
                continue
        
        # FINANCIALS - ANNUAL
        annual_rows = soup.select("#financials .tabs__panel[data-name='Annual'] table.tbl tbody tr")
        for row in annual_rows:
            try:
                cols = row.select("td")
                if len(cols) >= 2:
                    metric = cols[0].get_text(strip=True)
                    values = [c.get_text(strip=True) for c in cols[1:]]
                    data.append({
                        "CATEGORY": "Financials Annual",
                        "METRIC": metric,
                        "VALUE": " | ".join(values)
                    })
            except Exception as e:
                logger.warning(f"Error parsing annual financials row: {e}")
                continue
        
        # FINANCIALS - QUARTERLY
        quarterly_rows = soup.select("#financials .tabs__panel[data-name='Quarterly'] table.tbl tbody tr")
        for row in quarterly_rows:
            try:
                cols = row.select("td")
                if len(cols) >= 2:
                    metric = cols[0].get_text(strip=True)
                    values = [c.get_text(strip=True) for c in cols[1:]]
                    data.append({
                        "CATEGORY": "Financials Quarterly",
                        "METRIC": metric,
                        "VALUE": " | ".join(values)
                    })
            except Exception as e:
                logger.warning(f"Error parsing quarterly financials row: {e}")
                continue
        
        # RATIOS
        ratios_rows = soup.select(".company__ratios table.tbl tbody tr")
        for row in ratios_rows:
            try:
                cols = row.select("td")
                if len(cols) >= 2:
                    metric = cols[0].get_text(strip=True)
                    values = [c.get_text(strip=True) for c in cols[1:]]
                    data.append({
                        "CATEGORY": "Ratios",
                        "METRIC": metric,
                        "VALUE": " | ".join(values)
                    })
            except Exception as e:
                logger.warning(f"Error parsing ratios row: {e}")
                continue
        
        if not data:
            logger.warning("No valid fundamentals data extracted")
            return None
        
        # Create DataFrame
        df = pd.DataFrame(data)
        
        # Add symbol column
        df['SYMBOL'] = symbol.upper()
        
        # Set index
        df = df.set_index(['SYMBOL', 'CATEGORY', 'METRIC'])
        
        logger.info(f"Successfully parsed company fundamentals HTML for {symbol}: {len(df)} data points")
        return df
        
    except Exception as e:
        logger.error(f"Error parsing company fundamentals HTML: {e}")
        return None

