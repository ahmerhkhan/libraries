"""
PSX yfinance-style API
"""
from __future__ import annotations

__version__ = "3.0.1"
__author__ = "PyPSX Team"
__email__ = "pypsx@example.com"

from pypsx.ticker import PSXTicker, Ticker

# Backward compatibility alias
class PSXSymbol(Ticker):
    pass

from pypsx.api import (
    download,
    sectors,
    performers,
    market_watch,
    listings_nc,
    listings_dc,
    trading_board,
    index_constituents,
    get_indices,
    get_intraday_multiple,
    get_historical,
    symbols_nc,
    symbols_dc,
    get_symbols,
)

from pypsx.endpoints.company import get_quote, get_quote_batch
from pypsx.endpoints.company_fundamentals import get_company_fundamentals
from pypsx.endpoints.announcements import get_announcements as _get_announcements
from pypsx.endpoints.dividends import get_dividend_info as _get_dividend_info, get_dividend_history as _get_dividend_history
from pypsx.endpoints.sectors import get_sector_constituents as _get_sector_constituents
from pypsx.endpoints.compliant_listings import get_symbols_by_sector as _get_symbols_by_sector
from pypsx.endpoints.snapshot import get_snapshot

from pypsx.market import (
    top_performers,
    sector_summary,
    market_watch as market_watch_func,
    get_indices as get_indices_func,
    get_indices_breakdown,
    get_sector_breakdown,
    get_homepage_indices,
)

from pypsx.core.stream import PSXStream

# Models
from pypsx.models import (
    SymbolInfo,
    SectorSummary,
    SectorCompany,
    CompanyMarketWatch,
    IndexConstituent,
    IndexMeta,
    TradingBoardRow,
    TopActiveStock,
    TopAdvancer,
    TopDecliner,
    IntradayBar,
    EODBar,
    ListingEntry,
    CompanyFundamentals,
    Announcement,
    DividendInfo,
    DividendHistory,
)

# Analysis module (optional - requires analysis package)
try:
    from pypsx.analysis import (
        interpret_stock,
        sharpe_ratio,
        rsi,
        macd,
        bollinger_bands,
    )
except ImportError:
    # Analysis module not available
    pass

__all__ = [
    "__version__",
    "PSXTicker",
    "Ticker",
    "PSXSymbol",
    "PSXStream",
    "download",
    "sectors",
    "performers",
    "market_watch",
    "top_performers",
    "sector_summary",
    "get_indices",
    "get_indices_breakdown",
    "get_sector_breakdown",
    "get_homepage_indices",
    "listings_nc",
    "listings_dc",
    "trading_board",
    "index_constituents",
    "get_intraday_multiple",
    "get_historical",
    "symbols_nc",
    "symbols_dc",
    "get_symbols",
    # Convenience wrappers
    "get_market_watch",
    "get_most_active",
    "get_top_gainers",
    "get_top_losers",
    "get_orderbook",
    "get_intraday",
    "get_history",
    "get_index",
    "get_symbols_nc",
    "get_symbols_dc",
    "get_quote",
    "get_quote_batch",
    "get_company_fundamentals",
    "get_announcements",
    "get_dividend_info",
    "get_dividend_history",
    "get_business_description",
    "get_sector_constituents",
    "get_symbols_by_sector",
    "get_snapshot",
    # Models
    "SymbolInfo",
    "SectorSummary",
    "SectorCompany",
    "CompanyMarketWatch",
    "IndexConstituent",
    "IndexMeta",
    "TradingBoardRow",
    "TopActiveStock",
    "TopAdvancer",
    "TopDecliner",
    "IntradayBar",
    "EODBar",
    "ListingEntry",
    "CompanyFundamentals",
    "Announcement",
    "DividendInfo",
    "DividendHistory",
]


# Legacy compatibility wrappers used by audit script (clean outputs only)

def get_market_watch():
    return market_watch()


def get_most_active():
    return performers().get("top_actives")


def get_top_gainers():
    return performers().get("top_gainers")


def get_top_losers():
    return performers().get("top_decliners")


def get_orderbook(symbol: str | None = None):
    if symbol:
        return Ticker(symbol).orderbook()
    return trading_board()


def get_intraday(symbol: str):
    return Ticker(symbol).history(period="1d", interval="1m")


def get_history(symbol: str, period: str = "1y"):
    """Get historical data for a symbol (convenience function)."""
    return PSXTicker(symbol).history(period=period, interval="1d")


def get_index(index_name: str, format: str = 'dataframe'):
    """Get index constituents data (convenience function)."""
    return index_constituents(index_name)




def get_symbols_nc():
    import pandas as _pd
    return _pd.DataFrame({"Symbol": symbols_nc()})


def get_symbols_dc():
    import pandas as _pd
    return _pd.DataFrame({"Symbol": symbols_dc()})


def get_announcements(symbol: str, format: str = 'dataframe'):
    """Get company announcements (convenience function)."""
    return _get_announcements(symbol, format)


def get_dividend_info(symbol: str, format: str = 'dataframe'):
    """Get dividend information (convenience function)."""
    return _get_dividend_info(symbol, format)


def get_dividend_history(symbol: str, format: str = 'dataframe'):
    """Get dividend history (convenience function)."""
    return _get_dividend_history(symbol, format)


def get_sector_constituents(sector_code: str, format: str = 'dataframe'):
    """
    Get all companies in a specific sector.
    
    Args:
        sector_code: Sector code (e.g., '0801' for AUTOMOBILE ASSEMBLER) or sector name
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with sector constituents or JSON dict
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_sector_constituents('0801')  # Automobile Assembler
        >>> print(df.head())
    """
    return _get_sector_constituents(sector_code, format)


def get_symbols_by_sector(sector_name: str, format: str = 'dataframe'):
    """
    Get all symbols in a specific sector by sector name (supports partial matching).
    
    Args:
        sector_name: Sector name (e.g., 'automobile', 'AUTOMOBILE ASSEMBLER', 'Automobile Assembler')
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with symbols in the sector or JSON dict
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_symbols_by_sector('automobile')
        >>> print(df.head())
    """
    return _get_symbols_by_sector(sector_name, format)


def get_business_description(symbol: str) -> str:
    """
    Get business description for a company.
    
    Args:
        symbol: Stock symbol
        
    Returns:
        Business description string, or empty string if not found
    """
    import pandas as pd
    try:
        df = get_company_fundamentals(symbol, format='dataframe')
        if df is None or df.empty:  # type: ignore[union-attr]
            return ""
        
        # Look for Business Description in the fundamentals DataFrame
        if isinstance(df, pd.DataFrame):
            # Try resetting index first (handles both regular and MultiIndex)
            df_reset = df.reset_index()
            
            # Check if we have METRIC and VALUE columns
            if 'METRIC' in df_reset.columns and 'VALUE' in df_reset.columns:
                desc_row = df_reset[df_reset['METRIC'] == 'Business Description']
                if not desc_row.empty:
                    value = desc_row['VALUE'].iloc[0]
                    # Return clean string, not DataFrame representation
                    if pd.notna(value):
                        return str(value).strip()
            
            # Alternative: check if it's indexed by METRIC (MultiIndex) - try direct access
            if hasattr(df.index, 'get_level_values') and isinstance(df.index, pd.MultiIndex):
                if 'Business Description' in df.index.get_level_values('METRIC').tolist():
                    try:
                        # Sort index first to avoid PerformanceWarning
                        df_sorted = df.sort_index()
                        value = df_sorted.loc[(symbol.upper(), 'Profile', 'Business Description'), 'VALUE']
                        if pd.notna(value):
                            return str(value).strip()
                    except (KeyError, IndexError):
                        pass
        
        return ""
    except Exception:
        return ""


 

