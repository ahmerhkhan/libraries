"""
Market-level functions for PyPSX library.

Provides general market data endpoints like top performers, sector summary,
market watch, and indices overview.
"""

from typing import Dict, List, Tuple, Any, cast
import pandas as pd
from pypsx.endpoints.market_watch import get_market_watch
from pypsx.endpoints.performers import get_performers
from pypsx.endpoints.sectors import get_sector_summary
from pypsx.endpoints.indices_snapshot import get_indices_snapshot, get_homepage_indices_snapshot
from pypsx.endpoints.index_constituents import get_index_constituents


def top_performers() -> Dict[str, pd.DataFrame]:
    """
    Get top performers data.
    
    Returns:
        Dictionary with keys:
        - 'top_gainers': DataFrame with top advancers
        - 'top_decliners': DataFrame with top decliners  
        - 'top_actives': DataFrame with most active stocks
        
    Example:
        >>> from pypsx.market import top_performers
        >>> performers = top_performers()
        >>> print(performers['top_gainers'].head())
    """
    gainers = get_performers("advancers", format='dataframe')
    decliners = get_performers("decliners", format='dataframe')
    actives = get_performers("active", format='dataframe')
    
    return {
        "top_gainers": gainers if gainers is not None else pd.DataFrame(),
        "top_decliners": decliners if decliners is not None else pd.DataFrame(),
        "top_actives": actives if actives is not None else pd.DataFrame(),
    }


def sector_summary() -> pd.DataFrame:
    """
    Get sector summary data.
    
    Returns:
        DataFrame with sector-level statistics (advances, declines, turnover, etc.)
        
    Example:
        >>> from pypsx.market import sector_summary
        >>> df = sector_summary()
        >>> print(df.head())
    """
    result = get_sector_summary(format='dataframe')
    return result if result is not None else pd.DataFrame()


def market_watch() -> pd.DataFrame:
    """
    Get full market watch data.
    
    Returns:
        DataFrame with market-wide ticker data (OHLCV, sector, indices)
        
    Example:
        >>> from pypsx.market import market_watch
        >>> df = market_watch()
        >>> print(df.head())
    """
    result = get_market_watch(format='dataframe')
    return result if result is not None else pd.DataFrame()


def get_indices() -> pd.DataFrame:
    """
    Get indices overview.
    
    Returns:
        DataFrame with index symbols and their High, Low, Current, Change, %Change
        
    Example:
        >>> from pypsx.market import get_indices
        >>> df = get_indices()
        >>> print(df.head())
    """
    result = get_indices_snapshot(format='dataframe')
    if isinstance(result, pd.DataFrame):
        return result
    return pd.DataFrame()


def get_indices_breakdown() -> Dict[str, Any]:
    """
    Get complete breakdown of all PSX indices with constituent counts and statistics.
    
    Returns:
        Dictionary with breakdown information:
            - total_indices: Total number of indices
            - indices: List of tuples (index_code, symbol_count, stats_dict)
            - total_symbols_analyzed: Total symbols across all indices (with duplicates)
            - unique_symbols: Total unique symbols across all indices
            
    Example:
        >>> from pypsx.market import get_indices_breakdown
        >>> breakdown = get_indices_breakdown()
        >>> print(f"Total indices: {breakdown['total_indices']}")
        >>> for idx, count, stats in breakdown['indices'][:3]:
        ...     print(f"{idx}: {count} symbols")
    """
    # Get all indices
    indices = get_indices_snapshot(format='dataframe')
    if indices is None or indices.empty:  # type: ignore[union-attr]
        return {'total_indices': 0, 'indices': [], 'total_symbols_analyzed': 0, 'unique_symbols': 0}
    
    indices_list = list(indices.index) if hasattr(indices, 'index') else list(indices.keys()) if isinstance(indices, dict) else []
    
    breakdown: List[Tuple[str, int, Dict[str, Any]]] = []
    all_symbols = set()
    total_symbols_across_indices = 0
    
    # Get index statistics from indices snapshot
    index_stats = {}
    for idx in indices_list:
        try:
            if hasattr(indices, 'loc') and idx in indices.index:  # type: ignore[union-attr]
                idx_info = indices.loc[idx]
                stats = {}
                for col in idx_info.index:
                    stats[col.lower()] = idx_info[col]
                index_stats[idx] = stats
        except:
            pass

    for idx in indices_list:
        try:
            constituents = get_index_constituents(idx)
            if constituents is not None and not constituents.empty:  # type: ignore[union-attr]
                symbol_count: int = len(constituents)
                symbols_in_index = set(constituents.index) if hasattr(constituents, 'index') else set()
                all_symbols.update(symbols_in_index)
                total_symbols_across_indices += symbol_count
                
                # Get index stats
                stats = index_stats.get(idx, {})
                breakdown.append((idx, symbol_count, stats))
            else:
                breakdown.append((idx, 0, {}))
        except Exception as e:
            breakdown.append((idx, 0, {}))

    # Sort by symbol count descending
    def get_symbol_count(item: Tuple[str, int, Dict[str, Any]]) -> int:
        """Extract symbol count for sorting."""
        count = item[1]
        return int(count) if isinstance(count, (int, float)) else 0
    breakdown.sort(key=get_symbol_count, reverse=True)

    return {
        'total_indices': len(indices_list),
        'indices': breakdown,
        'total_symbols_analyzed': total_symbols_across_indices,
        'unique_symbols': len(all_symbols)
    }


def get_sector_breakdown() -> Dict[str, Any]:
    """
    Get complete breakdown of all PSX sectors with company counts and computed statistics.
    
    Returns:
        Dictionary with breakdown information:
            - total_sectors: Total number of sectors
            - sectors: List of dictionaries with sector info, company count, and averages
            - total_companies: Total number of companies across all sectors
            
    Example:
        >>> from pypsx.market import get_sector_breakdown
        >>> breakdown = get_sector_breakdown()
        >>> print(f"Total sectors: {breakdown['total_sectors']}")
        >>> for sector in breakdown['sectors'][:3]:
        ...     print(f"{sector['name']}: {sector['company_count']} companies")
    """
    # Get sector summary
    sector_summary = get_sector_summary(format='dataframe')
    
    # Get market watch for detailed company data
    market_watch = get_market_watch(format='dataframe')
    
    if sector_summary is None or sector_summary.empty:  # type: ignore[union-attr]
        return {'total_sectors': 0, 'sectors': [], 'total_companies': 0}
    
    sectors_breakdown: List[Dict[str, Any]] = []
    
    # Process each sector
    for sector_code, sector_info in sector_summary.iterrows():  # type: ignore[union-attr]
        sector_name = sector_info.get('SECTOR NAME', '') if 'SECTOR NAME' in sector_info.index else str(sector_code)
        
        # Get companies in this sector from market watch
        sector_companies = market_watch[market_watch['Sector'] == sector_name] if 'Sector' in market_watch.columns else pd.DataFrame()  # type: ignore[union-attr,index]
        
        company_count: int = len(sector_companies) if not sector_companies.empty else 0
        
        # Compute averages from market watch data
        from pypsx.core.utils import round_numeric_values
        averages = {}
        if not sector_companies.empty:
            numeric_cols = ['LDCP', 'Open', 'High', 'Low', 'Current', 'Change', 'Change %', 'Volume']
            for col in numeric_cols:
                if col in sector_companies.columns:
                    values = pd.to_numeric(sector_companies[col], errors='coerce')
                    avg_val = values.mean()
                    if pd.notna(avg_val):
                        # Round to 2-3 decimal places
                        rounded_val = round_numeric_values(avg_val, decimals=2)
                        averages[col.lower().replace(' ', '_')] = float(rounded_val)
        
        # Get sector summary stats
        sector_stats = {
            'code': str(sector_code),
            'name': sector_name,
            'advances': float(sector_info.get('ADVANCE', 0)) if 'ADVANCE' in sector_info.index else 0,
            'declines': float(sector_info.get('DECLINE', 0)) if 'DECLINE' in sector_info.index else 0,
            'unchanged': float(sector_info.get('UNCHANGE', 0)) if 'UNCHANGE' in sector_info.index else 0,
            'turnover': sector_info.get('TURNOVER', 0) if 'TURNOVER' in sector_info.index else 0,
        }
        
        sector_data: Dict[str, Any] = {
            **sector_stats,
            'company_count': company_count,
            'averages': averages
        }
        sectors_breakdown.append(sector_data)
    
    # Sort by company count descending
    def get_company_count(item: Dict[str, Any]) -> int:
        """Extract company count for sorting."""
        val = item.get('company_count', 0)
        return int(val) if isinstance(val, (int, float)) else 0
    sectors_breakdown.sort(key=get_company_count, reverse=True)
    
    def get_count(s: Dict[str, Any]) -> int:
        """Extract company count for sum."""
        val = s.get('company_count', 0)
        return int(val) if isinstance(val, (int, float)) else 0
    total_companies = sum(get_count(s) for s in sectors_breakdown)
    
    return {
        'total_sectors': len(sectors_breakdown),
        'sectors': sectors_breakdown,
        'total_companies': total_companies
    }


def get_homepage_indices() -> pd.DataFrame:
    """
    Get indices snapshot from PSX homepage.
    
    Fetches the top indices displayed on the PSX homepage including
    KSE100, KSE30, ALLSHR, KMI30, etc. with their current values,
    changes, and percentage changes.
    
    Returns:
        DataFrame with index data (NAME as index, VALUE, CHANGE, PERCENT_CHANGE)
        
    Example:
        >>> from pypsx.market import get_homepage_indices
        >>> df = get_homepage_indices()
        >>> print(df.head())
    """
    result = get_homepage_indices_snapshot(format='dataframe')
    return result if result is not None else pd.DataFrame()

