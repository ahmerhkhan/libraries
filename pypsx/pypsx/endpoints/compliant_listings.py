"""
Compliant listing endpoint for PyPSX library.

Fetches comprehensive listing data from PSX compliant listing page including
symbols, full company names, sectors, shares, free float, and index memberships.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union, List
import requests
from bs4 import BeautifulSoup
import re
try:
    from loguru import logger
    logger.remove()
except Exception:
    class _N:
        def __getattr__(self, _):
            return lambda *a, **k: None
    logger = _N()

from pypsx.core.utils import beautify_dataframe
from pypsx.format.json_utils import to_json
from pypsx.core.cache import get_cached_compliant_listings, set_cached_compliant_listings


def get_compliant_listings(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get comprehensive compliant listings data from PSX.
    
    Fetches all listed companies with their symbols, full names, sectors,
    shares, free float, and index memberships from the compliant listing page.
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with compliant listings data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_compliant_listings()
        >>> print(df.head())
        
        Output (pandas DataFrame):
        | SYMBOL | NAME | SECTOR | CLEARING_TYPE | SHARES | FREE_FLOAT | LISTED_IN |
        |---------|------|---------|---------------|--------|-------------|-----------|
        | 786 | 786 Investments Limited | Investment Banks | NC | 14,973,750 | 5,240,813 | ALLSHR |
        | AABS | Al-Abbas Sugar Mills Limited | Sugar and Allied Industries | NC | 17,362,300 | 1,736,230 | ALLSHRKMIALLSHR |
    """
    try:
        
        # Check cache first
        cached_data = get_cached_compliant_listings()
        if cached_data is not None:
            if format == 'json':
                return to_json(cached_data)
            else:
                return cached_data
        
        # URL of the compliant listing page
        url = "https://dps.psx.com.pk/listings-table/main/nc"
        
        # Headers to mimic browser request
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # Send GET request
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Parse HTML content
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find the table
        table = soup.find("table", class_="tbl")
        if not table:
            return None
        
        # Extract table headers
        thead = table.find("thead")
        if not thead:
            return None
            
        headers = [th.get_text(strip=True) for th in thead.find_all("th")]
        
        # Extract table rows
        tbody = table.find("tbody")
        if not tbody:
            return None
            
        rows = []
        for tr in tbody.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            row = [cell.get_text(strip=True).replace(",", "") for cell in cells]
            rows.append(row)
        
        if not rows:
            return None
        
        # Create DataFrame
        df = pd.DataFrame(rows, columns=headers)
        
        # Clean and normalize the data
        df = _clean_compliant_listings_data(df)
        
        # Set symbol as index
        df = df.set_index('SYMBOL')
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        # Cache the data
        set_cached_compliant_listings(df)
        
        
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except requests.exceptions.RequestException as e:
        return None
    except Exception as e:
        return None


def _clean_compliant_listings_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and normalize compliant listings data.
    
    Args:
        df: Raw DataFrame from HTML parsing
        
    Returns:
        Cleaned DataFrame
    """
    try:
        # Rename columns to standard format
        column_mapping = {
            'Symbol': 'SYMBOL',
            'Name': 'NAME',
            'Sector': 'SECTOR',
            'ClearingType': 'CLEARING_TYPE',
            'Shares': 'SHARES',
            'Free Float': 'FREE_FLOAT',
            'Listed In': 'LISTED_IN'
        }
        
        df = df.rename(columns=column_mapping)
        
        # Normalize sector names
        df['SECTOR'] = df['SECTOR'].apply(_normalize_sector_name)
        
        # Convert numeric columns
        numeric_columns = ['SHARES', 'FREE_FLOAT']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Clean company names
        df['NAME'] = df['NAME'].str.strip()
        
        # Parse index memberships
        df['INDEX_MEMBERSHIPS'] = df['LISTED_IN'].apply(_parse_index_memberships)
        
        # Add additional calculated fields
        df['FREE_FLOAT_PERCENTAGE'] = (df['FREE_FLOAT'] / df['SHARES'] * 100).round(2)
        
        # Add market cap category based on shares
        df['MARKET_CAP_CATEGORY'] = df['SHARES'].apply(_categorize_market_cap)
        
        return df
        
    except Exception as e:
        return df


def _normalize_sector_name(sector: str) -> str:
    """
    Normalize sector names to proper case.
    
    Args:
        sector: Raw sector name
        
    Returns:
        Normalized sector name
    """
    if not sector or pd.isna(sector):
        return "Unknown"
    
    # Sector name mappings for proper formatting
    sector_mappings = {
        'INV. BANKS / INV. COS. / SECURITIES COS.': 'Investment Banks and Securities',
        'SUGAR & ALLIED INDUSTRIES': 'Sugar and Allied Industries',
        'TEXTILE SPINNING': 'Textile Spinning',
        'COMMERCIAL BANKS': 'Commercial Banks',
        'PHARMACEUTICALS': 'Pharmaceuticals',
        'CEMENT': 'Cement',
        'OIL & GAS EXPLORATION': 'Oil and Gas Exploration',
        'OIL & GAS MARKETING': 'Oil and Gas Marketing',
        'OIL & GAS REFINERIES': 'Oil and Gas Refineries',
        'TEXTILE COMPOSITE': 'Textile Composite',
        'TEXTILE WEAVING': 'Textile Weaving',
        'TEXTILE FINISHING': 'Textile Finishing',
        'ENGINEERING': 'Engineering',
        'CHEMICAL': 'Chemical',
        'FERTILIZER': 'Fertilizer',
        'POWER GENERATION & DISTRIBUTION': 'Power Generation and Distribution',
        'TELECOMMUNICATIONS': 'Telecommunications',
        'AUTOMOBILE ASSEMBLER': 'Automobile Assembler',
        'AUTOMOBILE PARTS & ACCESSORIES': 'Automobile Parts and Accessories',
        'FOOD & PERSONAL CARE PRODUCTS': 'Food and Personal Care Products',
        'INSURANCE': 'Insurance',
        'REAL ESTATE INVESTMENT TRUST': 'Real Estate Investment Trust',
        'REAL ESTATE DEVELOPMENT': 'Real Estate Development',
        'LEATHER & TANNERIES': 'Leather and Tanneries',
        'PAPER & BOARD': 'Paper and Board',
        'GLASS & CERAMICS': 'Glass and Ceramics',
        'SYNTHETIC & RAYON': 'Synthetic and Rayon',
        'VANASPATI & ALLIED INDUSTRIES': 'Vanaspati and Allied Industries',
        'JUTE': 'Jute',
        'WOOLLEN': 'Woollen',
        'MODARABA': 'Modaraba',
        'CLOSE-END MUTUAL FUND': 'Close-End Mutual Fund',
        'OPEN-END MUTUAL FUND': 'Open-End Mutual Fund',
        'EXCHANGE TRADED FUNDS': 'Exchange Traded Funds',
        'ISLAMIC BONDS': 'Islamic Bonds',
        'TERM FINANCE CERTIFICATES': 'Term Finance Certificates',
        'SUKUK': 'Sukuk',
        'PREFERENCE SHARES': 'Preference Shares',
        'WARRANTS': 'Warrants',
        'RIGHTS': 'Rights'
    }
    
    # Check if we have a direct mapping
    if sector in sector_mappings:
        return sector_mappings[sector]
    
    # Apply general normalization for unmapped sectors
    normalized = sector.title()
    
    # Fix common patterns
    normalized = re.sub(r'\s+&\s+', ' and ', normalized)
    normalized = re.sub(r'\s+/\s+', ' / ', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    
    return normalized


def _parse_index_memberships(listed_in: str) -> List[str]:
    """
    Parse index memberships from Listed In field.
    
    Args:
        listed_in: Raw Listed In field
        
    Returns:
        List of index memberships
    """
    if not listed_in or pd.isna(listed_in):
        return []
    
    # Common PSX indices
    indices = []
    
    if 'ALLSHR' in listed_in:
        indices.append('ALLSHR')
    if 'KSE100' in listed_in:
        indices.append('KSE100')
    if 'KSE100PR' in listed_in:
        indices.append('KSE100PR')
    if 'KMIALLSHR' in listed_in:
        indices.append('KMIALLSHR')
    if 'MII30' in listed_in:
        indices.append('MII30')
    if 'KSE30' in listed_in:
        indices.append('KSE30')
    if 'KMI30' in listed_in:
        indices.append('KMI30')
    
    return indices


def _categorize_market_cap(shares: int) -> str:
    """
    Categorize market cap based on shares outstanding.
    
    Args:
        shares: Number of shares outstanding
        
    Returns:
        Market cap category
    """
    if pd.isna(shares):
        return "Unknown"
    
    if shares >= 1000000000:  # 1B+ shares
        return "Large Cap"
    elif shares >= 100000000:  # 100M+ shares
        return "Mid Cap"
    elif shares >= 10000000:  # 10M+ shares
        return "Small Cap"
    else:
        return "Micro Cap"


def get_symbols_by_sector(sector: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get all symbols in a specific sector.
    
    Args:
        sector: Sector name (normalized or partial match)
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with symbols in the sector or JSON dict, None if failed
    """
    try:
        # Get all listings
        listings = get_compliant_listings('dataframe')
        if listings is None or listings.empty:
            return None
        
        # Normalize sector name and build robust match (exact and partial)
        try:
            normalized_input = _normalize_sector_name(sector.upper())
        except Exception:
            normalized_input = sector
        s = listings['SECTOR'].astype(str).str.strip()
        mask = (
            s.str.casefold() == normalized_input.strip().casefold()
        ) | (
            s.str.contains(normalized_input, case=False, na=False)
        ) | (
            s.str.contains(sector, case=False, na=False)
        )
        sector_symbols = listings[mask]
        
        if sector_symbols.empty:
            return None
        
        # Return based on format
        if format == 'json':
            return to_json(sector_symbols)
        else:
            return sector_symbols
            
    except Exception:
        return None


def get_symbols_by_index(index_name: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get all symbols in a specific index.
    
    Args:
        index_name: Index name (e.g., 'KSE100', 'KMI30')
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with symbols in the index or JSON dict, None if failed
    """
    try:
        # Get all listings
        listings = get_compliant_listings('dataframe')
        if listings is None or listings.empty:
            return None
        
        target = (index_name or "").strip().upper()
        def _has_index(members):
            if isinstance(members, list):
                for m in members:
                    try:
                        if str(m).strip().upper() == target:
                            return True
                    except Exception:
                        continue
            return False
        
        index_mask = listings['INDEX_MEMBERSHIPS'].apply(_has_index)
        index_symbols = listings[index_mask]
        
        # Fallback: use live index constituents if listings did not include memberships
        if index_symbols.empty:
            try:
                from pypsx.endpoints.indices import get_index as _get_index_live
                live = _get_index_live(target, 'dataframe')
                if live is not None and not live.empty:
                    return to_json(live) if format == 'json' else live
            except Exception:
                pass
            return None
        
        # Return based on format
        if format == 'json':
            return to_json(index_symbols)
        else:
            return index_symbols
            
    except Exception:
        return None


def get_large_cap_stocks(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get all large cap stocks (1B+ shares).
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with large cap stocks or JSON dict, None if failed
    """
    try:
        
        # Get all listings
        listings = get_compliant_listings('dataframe')
        if listings is None or listings.empty:
            return None
        
        # Filter large cap stocks
        large_cap = listings[listings['MARKET_CAP_CATEGORY'] == 'Large Cap']
        
        if large_cap.empty:
            return None
        
        # Return based on format
        if format == 'json':
            return to_json(large_cap)
        else:
            return large_cap
            
    except Exception as e:
        return None


def get_sector_summary_from_listings(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get sector summary from compliant listings data.
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with sector summary or JSON dict, None if failed
    """
    try:
        
        # Get all listings
        listings = get_compliant_listings('dataframe')
        if listings is None or listings.empty:
            return None
        
        # Group by sector and calculate summary statistics
        sector_summary = listings.groupby('SECTOR').agg({
            'NAME': 'count',  # Number of companies
            'SHARES': ['sum', 'mean'],  # Total and average shares
            'FREE_FLOAT': ['sum', 'mean'],  # Total and average free float
            'FREE_FLOAT_PERCENTAGE': 'mean',  # Average free float percentage
            'MARKET_CAP_CATEGORY': lambda x: x.value_counts().to_dict()  # Market cap distribution
        }).round(2)
        
        # Flatten column names
        sector_summary.columns = [
            'COMPANIES_COUNT',
            'TOTAL_SHARES',
            'AVG_SHARES',
            'TOTAL_FREE_FLOAT',
            'AVG_FREE_FLOAT',
            'AVG_FREE_FLOAT_PCT',
            'MARKET_CAP_DISTRIBUTION'
        ]
        
        # Sort by number of companies
        sector_summary = sector_summary.sort_values('COMPANIES_COUNT', ascending=False)
        
        # Return based on format
        if format == 'json':
            return to_json(sector_summary)
        else:
            return sector_summary
            
    except Exception as e:
        return None
