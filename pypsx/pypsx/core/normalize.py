"""
Field name normalization utilities for PyPSX library.

Normalizes PSX field names to consistent, standardized names across all endpoints.
"""

from typing import Dict, Any
import pandas as pd


# Field name mapping from PSX names to normalized names
FIELD_NAME_MAPPING = {
    # Price fields
    'LDCP': 'last_close',
    'CURRENT': 'current_price',
    'OPEN': 'open',
    'HIGH': 'high',
    'LOW': 'low',
    'CLOSE': 'close',
    
    # Change fields
    'CHANGE': 'change',
    'CHANGE %': 'change_pct',
    'CHANGE (%)': 'change_pct',
    '%CHANGE': 'change_pct',
    'Percent Change': 'change_pct',
    
    # Volume
    'VOLUME': 'volume',
    'Vol': 'volume',
    
    # Index fields
    'IDX WTG %': 'index_weight_pct',
    'IDX WTG (%)': 'index_weight_pct',
    'IDX WTG': 'index_weight_pct',
    'IDX Point': 'index_point',
    'IDX POINT': 'index_point',
    
    # Market cap
    'Market Cap (B)': 'market_cap_b',
    'Market Cap (M)': 'market_cap_m',
    'MARKET CAP (B)': 'market_cap_b',
    'MARKET CAP (M)': 'market_cap_m',
    
    # Free float
    'Freefloat (M)': 'freefloat_m',
    'FREEFLOAT (M)': 'freefloat_m',
    'Free Float': 'freefloat_m',
    
    # Sector fields
    'Sector Code': 'sector_code',
    'Sector Name': 'sector_name',
    'SECTOR': 'sector',
    'Sector': 'sector',
    
    # Trading board
    'Bid Volume': 'bid_volume',
    'Bid Price': 'bid_price',
    'Offer Volume': 'offer_volume',
    'Offer Price': 'offer_price',
    
    # Listings
    'Clearing Type': 'clearing_type',
    'CLEARING TYPE': 'clearing_type',
    'Shares': 'shares',
    'Free Float': 'free_float',
    'Listed In': 'listed_in',
    'LISTED IN': 'listed_in',
    
    # Common
    'Symbol': 'symbol',
    'SYMBOL': 'symbol',
    'Name': 'name',
    'NAME': 'name',
    'Price': 'price',
    'PRICE': 'price',
}


def normalize_field_names(df: pd.DataFrame, inplace: bool = False) -> pd.DataFrame:
    """
    Normalize field names in a DataFrame according to FIELD_NAME_MAPPING.
    
    Args:
        df: DataFrame to normalize
        inplace: If True, modify in place
        
    Returns:
        DataFrame with normalized column names
    """
    if not inplace:
        df = df.copy()
    
    rename_map = {}
    for old_name, new_name in FIELD_NAME_MAPPING.items():
        if old_name in df.columns:
            rename_map[old_name] = new_name
    
    if rename_map:
        df.rename(columns=rename_map, inplace=True)
    
    return df


def normalize_numeric_values(df: pd.DataFrame, fill_na: bool = True) -> pd.DataFrame:
    """
    Normalize numeric values: remove commas, convert percentages, fill NaN.
    
    Args:
        df: DataFrame to normalize
        fill_na: If True, fill NaN with 0 for numeric columns
        
    Returns:
        DataFrame with normalized numeric values
    """
    df = df.copy()
    
    for col in df.columns:
        if df[col].dtype == 'object':
            # Try to convert to numeric
            try:
                # Remove commas and convert
                df[col] = df[col].astype(str).str.replace(',', '', regex=False)
                # Handle percentages
                if '%' in str(df[col].iloc[0] if len(df) > 0 else ''):
                    df[col] = pd.to_numeric(df[col].str.replace('%', '', regex=False), errors='coerce') / 100
                else:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                if fill_na:
                    df[col] = df[col].fillna(0)
            except (ValueError, TypeError):
                pass
    
    return df


def ensure_no_nulls(df: pd.DataFrame, default_values: Dict[str, Any] = None) -> pd.DataFrame:
    """
    Ensure no null values where data should exist.
    
    Args:
        df: DataFrame to process
        default_values: Dictionary mapping column names to default values
        
    Returns:
        DataFrame with nulls filled
    """
    if default_values is None:
        default_values = {
            'volume': 0,
            'change': 0.0,
            'change_pct': 0.0,
            'current_price': 0.0,
            'last_close': 0.0,
            'open': 0.0,
            'high': 0.0,
            'low': 0.0,
        }
    
    df = df.copy()
    
    for col, default_val in default_values.items():
        if col in df.columns:
            df[col] = df[col].fillna(default_val)
    
    return df

