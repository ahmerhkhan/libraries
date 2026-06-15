"""
Non-compliant listings endpoint for PyPSX library.

Fetches non-compliant listings data from PSX including companies that don't comply
with PSX regulations. This complements the compliant listings for complete coverage.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union, List
import requests
from bs4 import BeautifulSoup
import re

from pypsx.core.utils import beautify_dataframe
from pypsx.format.json_utils import to_json
from pypsx.core.cache import get_cached_non_compliant_listings, set_cached_non_compliant_listings, get_cached_combined_listings, set_cached_combined_listings
import logging

logger = logging.getLogger(__name__)


def get_non_compliant_listings(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get non-compliant listings data from PSX.
    
    Fetches companies that don't comply with PSX regulations from the
    non-compliant listings page.
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with non-compliant listings data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_non_compliant_listings()
        >>> print(df.head())
        
        Output (pandas DataFrame):
        | SYMBOL | NAME | SECTOR | NON_COMPLIANCE | CLEARING_TYPE | SHARES | FREE_FLOAT | LISTED_IN |
        |---------|------|---------|----------------|---------------|--------|-------------|-----------|
        | AAL | Agro Allianz Limited | Textile Spinning | 5.11.1.(a,b,c),5.11.2(a) | NC | 1,183,200 | 0 | ALLSHR |
    """
    try:
        
        # Check cache first
        cached_data = get_cached_non_compliant_listings()
        if cached_data is not None:
            if format == 'json':
                return to_json(cached_data)
            else:
                return cached_data
        
        # URL of the non-compliant listing page
        url = "https://dps.psx.com.pk/listings-table/main/dc"
        
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
        df = _clean_non_compliant_listings_data(df)
        
        # Set symbol as index
        df = df.set_index('SYMBOL')
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        # Cache the data
        set_cached_non_compliant_listings(df)
        
        
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except requests.exceptions.RequestException as e:
        return None
    except Exception as e:
        return None


def _clean_non_compliant_listings_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and normalize non-compliant listings data.
    
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
            'Non-Compliance of PSX Regulations': 'NON_COMPLIANCE',
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
        
        # Add compliance status
        df['COMPLIANCE_STATUS'] = 'Non-Compliant'
        
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
        'TEXTILE SPINNING': 'Textile Spinning',
        'SYNTHETIC & RAYON': 'Synthetic and Rayon',
        'PAPER, BOARD & PACKAGING': 'Paper Board and Packaging',
        'INV. BANKS / INV. COS. / SECURITIES COS.': 'Investment Banks and Securities',
        'AUTOMOBILE PARTS & ACCESSORIES': 'Automobile Parts and Accessories',
        'INSURANCE': 'Insurance',
        'JUTE': 'Jute',
        'TEXTILE COMPOSITE': 'Textile Composite',
        'CEMENT': 'Cement',
        'MISCELLANEOUS': 'Miscellaneous',
        'TEXTILE WEAVING': 'Textile Weaving',
        'ENGINEERING': 'Engineering',
        'CHEMICAL': 'Chemical',
        'SUGAR & ALLIED INDUSTRIES': 'Sugar and Allied Industries',
        'CLOSE - END MUTUAL FUND': 'Close-End Mutual Fund',
        'GLASS & CERAMICS': 'Glass and Ceramics',
        'VANASPATI & ALLIED INDUSTRIES': 'Vanaspati and Allied Industries',
        'LEASING COMPANIES': 'Leasing Companies'
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


def get_all_listings_combined(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get combined listings data from both compliant and non-compliant sources.
    
    This provides complete coverage of all PSX listed companies.
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with all listings data or JSON dict, None if failed
    """
    try:
        logger.info("Fetching combined listings data (Compliant + Non-Compliant)")
        
        # Check cache first
        cached_data = get_cached_combined_listings()
        if cached_data is not None:
            logger.info("Using cached combined listings data")
            if format == 'json':
                return to_json(cached_data)
            else:
                return cached_data
        
        # Get compliant listings
        from pypsx.endpoints.compliant_listings import get_compliant_listings
        compliant_df = get_compliant_listings('dataframe')
        if compliant_df is None or compliant_df.empty:
            logger.error("Failed to get compliant listings data")
            return None
        
        # Get non-compliant listings
        non_compliant_df = get_non_compliant_listings('dataframe')
        if non_compliant_df is None or non_compliant_df.empty:
            logger.error("Failed to get non-compliant listings data")
            return None
        
        # Add compliance status to compliant listings
        compliant_df['COMPLIANCE_STATUS'] = 'Compliant'
        compliant_df['NON_COMPLIANCE'] = None
        
        # Ensure both DataFrames have the same columns
        all_columns = set(compliant_df.columns) | set(non_compliant_df.columns)
        
        for col in all_columns:
            if col not in compliant_df.columns:
                compliant_df[col] = None
            if col not in non_compliant_df.columns:
                non_compliant_df[col] = None
        
        # Combine the DataFrames
        combined_df = pd.concat([compliant_df, non_compliant_df], ignore_index=False)
        
        # Sort by symbol
        combined_df = combined_df.sort_index()
        
        # Beautify DataFrame
        combined_df = beautify_dataframe(combined_df)
        
        # Cache the data
        set_cached_combined_listings(combined_df)
        
        logger.info(f"Successfully created combined listings: {len(combined_df)} companies")
        logger.info(f"  Compliant: {len(compliant_df)} companies")
        logger.info(f"  Non-Compliant: {len(non_compliant_df)} companies")
        
        # Return based on format
        if format == 'json':
            return to_json(combined_df)
        else:
            return combined_df
            
    except Exception as e:
        return None


def get_compliance_summary(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get compliance summary statistics.
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with compliance summary or JSON dict, None if failed
    """
    try:
        logger.info("Creating compliance summary")
        
        # Get combined listings
        combined_df = get_all_listings_combined('dataframe')
        if combined_df is None or combined_df.empty:
            logger.error("Failed to get combined listings data")
            return None
        
        # Create compliance summary
        compliance_summary = combined_df.groupby('COMPLIANCE_STATUS').agg({
            'NAME': 'count',  # Number of companies
            'SHARES': ['sum', 'mean'],  # Total and average shares
            'FREE_FLOAT': ['sum', 'mean'],  # Total and average free float
            'FREE_FLOAT_PERCENTAGE': 'mean',  # Average free float percentage
            'MARKET_CAP_CATEGORY': lambda x: x.value_counts().to_dict()  # Market cap distribution
        }).round(2)
        
        # Flatten column names
        compliance_summary.columns = [
            'COMPANIES_COUNT',
            'TOTAL_SHARES',
            'AVG_SHARES',
            'TOTAL_FREE_FLOAT',
            'AVG_FREE_FLOAT',
            'AVG_FREE_FLOAT_PCT',
            'MARKET_CAP_DISTRIBUTION'
        ]
        
        logger.info(f"Created compliance summary for {len(compliance_summary)} compliance statuses")
        
        # Return based on format
        if format == 'json':
            return to_json(compliance_summary)
        else:
            return compliance_summary
            
    except Exception as e:
        return None


def get_non_compliant_by_reason(reason: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get non-compliant companies by specific compliance reason.
    
    Args:
        reason: Compliance reason to filter by (e.g., "5.11.1.(a)")
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with filtered non-compliant companies or JSON dict, None if failed
    """
    try:
        logger.info(f"Getting non-compliant companies by reason: {reason}")
        
        # Get non-compliant listings
        non_compliant_df = get_non_compliant_listings('dataframe')
        if non_compliant_df is None or non_compliant_df.empty:
            logger.error("Failed to get non-compliant listings data")
            return None
        
        # Filter by compliance reason
        filtered_df = non_compliant_df[
            non_compliant_df['NON_COMPLIANCE'].str.contains(reason, case=False, na=False)
        ]
        
        if filtered_df.empty:
            return None
        
        logger.info(f"Found {len(filtered_df)} non-compliant companies for reason: {reason}")
        
        # Return based on format
        if format == 'json':
            return to_json(filtered_df)
        else:
            return filtered_df
            
    except Exception as e:
        return None

        if non_compliant_df is None or non_compliant_df.empty:
            logger.error("Failed to get non-compliant listings data")
            return None
        
        # Filter by compliance reason
        filtered_df = non_compliant_df[
            non_compliant_df['NON_COMPLIANCE'].str.contains(reason, case=False, na=False)
        ]
        
        if filtered_df.empty:
            logger.warning(f"No non-compliant companies found for reason: {reason}")
            return None
        
        logger.info(f"Found {len(filtered_df)} non-compliant companies for reason: {reason}")
        
        # Return based on format
        if format == 'json':
            return to_json(filtered_df)
        else:
            return filtered_df
            
    except Exception as e:
        logger.error(f"Error filtering non-compliant companies by reason {reason}: {e}")
        return None
