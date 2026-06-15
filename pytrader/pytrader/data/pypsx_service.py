"""
Wrapper for the pyPSX library (installed as a package) with caching.

BACKEND-ONLY: This module is for backend internal use only.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# ==============================================================================
# Robust pypsx library path resolution
# ==============================================================================
current_file = Path(__file__).resolve()
search_paths = []
p = current_file.parent
for _ in range(6):
    candidate = p / "pypsx-library-main"
    if candidate.exists():
        search_paths.append(candidate)
    p = p.parent

# Hardcoded fallback path
search_paths.append(Path("c:/Users/intel/Downloads/pytrader/pypsx-library-main"))

for path in search_paths:
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Import pypsx library directly
try:
    import pypsx
    from pypsx import (
        get_indices as lib_get_indices,
        get_market_watch as lib_get_market_watch,
        get_company_fundamentals as lib_get_company_fundamentals,
        get_snapshot as lib_get_snapshot,
        get_business_description as lib_get_business_description,
        get_sector_constituents as lib_get_sector_constituents,
        get_historical as lib_get_historical,
        get_intraday as lib_get_intraday,
         get_symbols as lib_get_symbols,
    )
    # Check if new methods exist, otherwise we might need fallback or custom impl
    # Assuming the library has mostly what we need or we adapt.
except ImportError:
    # Allow import error during build/CI if library not present, but log warning
    logging.getLogger(__name__).warning("Could not import pypsx library. Ensure it is installed.")
    pypsx = None
    # Set all imported functions to None to prevent NameError
    lib_get_indices = None
    lib_get_market_watch = None
    lib_get_company_fundamentals = None
    lib_get_snapshot = None
    lib_get_business_description = None
    lib_get_sector_constituents = None
    lib_get_historical = None
    lib_get_intraday = None
    lib_get_symbols = None

from .cache.sqlite_cache import SQLiteCache
from ..utils.exceptions import DataProviderError, SymbolNotFoundError

logger = logging.getLogger(__name__)

# Cache TTLs
INTRADAY_TTL_SECONDS = int(os.getenv("PYTRADER_INTRADAY_TTL", "600"))
HISTORICAL_TTL_SECONDS = int(os.getenv("PYTRADER_HISTORICAL_TTL", "21600"))
METADATA_TTL_SECONDS = int(os.getenv("PYTRADER_METADATA_TTL", "86400"))
PRICES_TTL_SECONDS = int(os.getenv("PYTRADER_PRICES_TTL", "60"))
MARKET_WATCH_TTL_SECONDS = int(os.getenv("PYTRADER_MARKET_WATCH_TTL", "30"))


def _build_cache_key(kind: str, *parts: object) -> str:
    normalized = [kind]
    for part in parts:
        if part is None:
            normalized.append("none")
        else:
            normalized.append(str(part).lower())
    return "::".join(normalized)


class PyPSXService:
    """
    Service wrapper around local pyPSX library calls with caching.
    
    DEPRECATED: This service has a 15-minute data delay from PSX.
    
    For live/paper trading, use PSXTerminalService instead:
        from pytrader.data.psx_terminal_service import PSXTerminalService
        service = PSXTerminalService()
    
    PyPSXService is only recommended for:
    - Backtesting with historical data
    - Local development/testing where delay is acceptable
    - Fallback when psx-terminal API is unavailable
    """

    def __init__(self, cache: Optional[SQLiteCache] = None) -> None:
        import warnings
        warnings.warn(
            "PyPSXService has 15-minute data delay. "
            "For live/paper trading, use PSXTerminalService instead: "
            "from pytrader.data.psx_terminal_service import PSXTerminalService",
            DeprecationWarning,
            stacklevel=2
        )
        self.cache = cache or SQLiteCache()
        if not pypsx:
            logger.error("PyPSX library not available. Service will fail.")

    def _get_cached_or_call(
        self,
        cache_key: str,
        ttl_seconds: int,
        func: callable,
        *args,
        **kwargs
    ) -> Any:
        # Check cache
        cached = self.cache.get(cache_key)
        if cached and not cached.expired:
            return cached.value

        # Call library function
        try:
            result = func(*args, **kwargs)
            if result is not None:
                self.cache.set(cache_key, result, ttl_seconds)
            return result
        except Exception as exc:
            logger.error(f"Error calling {func.__name__}: {exc}")
            raise DataProviderError(f"Library call failed: {exc}") from exc

    def get_indices(self) -> List[Dict[str, Any]]:
        """Get all market indices."""
        # pypsx.get_indices() usually returns a DataFrame or list. We need to standardize.
        cache_key = _build_cache_key("indices")
        
        def fetch_indices():
            if lib_get_indices is None:
                raise DataProviderError(
                    "pypsx library is not available. Cannot fetch indices. "
                    "Please ensure pypsx-library is installed: pip install pypsx-library"
                )
            # lib_get_indices returns DataFrame usually, we need to convert to dict/list
            df = lib_get_indices()
            if hasattr(df, "to_dict"):
                # Reset index to include it as a column named 'symbol'
                df_reset = df.reset_index()
                # Rename index column to 'symbol' if it doesn't have a name
                if df_reset.columns[0] == 0 or df_reset.columns[0] == 'index':
                    df_reset = df_reset.rename(columns={df_reset.columns[0]: 'symbol'})
                return df_reset.to_dict(orient="records")
            return df
            
        # Return list directly, not double-wrapped
        return self._get_cached_or_call(cache_key, MARKET_WATCH_TTL_SECONDS, fetch_indices)

    def get_index_overview(self, index_symbol: str) -> Dict[str, Any]:
        """Get overview for a specific index."""
        # Index symbol mapping for common variations
        INDEX_ALIASES = {
            "KSE100": ["KSE100", "KSE 100", "KSE-100", "KSE100INDEX"],
            "KSE30": ["KSE30", "KSE 30", "KSE-30", "KMI30"],
            "ALLSHR": ["ALLSHR", "ALL SHARE", "KMIALLSHR", "KMI ALLSHR", "KMI ALLSHARE"],
            "OGTI": ["OGTI", "OGT", "OGTI INDEX"],
        }
        
        # Fetch all indices
        all_indices = self.get_indices()
        
        # Normalize the search symbol
        search_symbol = index_symbol.upper().strip()
        
        # Get possible aliases for this symbol
        possible_symbols = [search_symbol]
        for canonical, aliases in INDEX_ALIASES.items():
            if search_symbol in [a.upper() for a in aliases]:
                possible_symbols.extend([a.upper() for a in aliases])
                break
        
        # Search through indices
        if isinstance(all_indices, list):
            for idx in all_indices:
                # Check the 'symbol' field (from DataFrame index)
                idx_symbol = str(idx.get("symbol", "")).upper().strip()
                # Also check NAME field if it exists
                idx_name = str(idx.get("NAME", idx.get("Name", idx.get("name", "")))).upper().strip()
                
                # Match against any of the possible symbols
                for possible in possible_symbols:
                    if idx_symbol == possible or possible in idx_name or idx_symbol in possible:
                        return idx
        return {}

    def get_live_summary(self) -> Dict[str, Any]:
        """Get live market summary."""
        # Using market_watch as a summary proxy if no specific summary func exists
        cache_key = _build_cache_key("live_summary")
        def fetch_summary():
            if lib_get_market_watch is None:
                raise DataProviderError(
                    "pypsx library is not available. Cannot fetch market summary. "
                    "Please ensure pypsx-library is installed: pip install pypsx-library"
                )
            # If pypsx has a specific summary function, use it. 
            # Otherwise construct from market watch top level data
            result = lib_get_market_watch()
            if hasattr(result, "to_dict"):
                # Convert DataFrame to dict
                return result.to_dict(orient="records")
            return result
        
        data = self._get_cached_or_call(cache_key, MARKET_WATCH_TTL_SECONDS, fetch_summary)
        return {"summary": data} if isinstance(data, list) else data

    def get_company_snapshot(self, symbol: str) -> Dict[str, Any]:
        """Get company snapshot."""
        cache_key = _build_cache_key("snapshot", symbol)
        
        def fetch_snapshot():
            if lib_get_snapshot is None:
                raise DataProviderError(
                    f"pypsx library is not available. Cannot fetch snapshot for {symbol}. "
                    "Please ensure pypsx-library is installed: pip install pypsx-library"
                )
            result = lib_get_snapshot(symbol)
            if hasattr(result, "to_dict"):
                # Convert DataFrame to dict (single row)
                result_dict = result.to_dict(orient="records")
                return result_dict[0] if result_dict else {}
            return result
        
        return self._get_cached_or_call(cache_key, PRICES_TTL_SECONDS, fetch_snapshot)

    def get_all_prices(self) -> Dict[str, Any]:
        """Get all prices."""
        cache_key = _build_cache_key("all_prices")
        def fetch_prices():
            if lib_get_market_watch is None:
                raise DataProviderError(
                    "pypsx library is not available. Cannot fetch prices. "
                    "Please ensure pypsx-library is installed: pip install pypsx-library"
                )
            # market_watch returns all active symbols
            result = lib_get_market_watch()
            if hasattr(result, "to_dict"):
                # Convert DataFrame to list of dicts
                return result.to_dict(orient="records")
            return result
        
        data = self._get_cached_or_call(cache_key, PRICES_TTL_SECONDS, fetch_prices)
        return {"symbols": data}

    def get_company_fundamentals(self, symbol: str) -> Dict[str, Any]:
        """Get company fundamentals."""
        cache_key = _build_cache_key("fundamentals", symbol)
        def fetch_funds():
            if lib_get_company_fundamentals is None:
                raise DataProviderError(
                    f"pypsx library is not available. Cannot fetch fundamentals for {symbol}. "
                    "Please ensure pypsx-library is installed: pip install pypsx-library"
                )
            df = lib_get_company_fundamentals(symbol)
            if hasattr(df, "to_dict"):
                return df.to_dict()
            return df
        return self._get_cached_or_call(cache_key, METADATA_TTL_SECONDS, fetch_funds)

    def get_business_description(self, symbol: str) -> str:
        """Get business description."""
        cache_key = _build_cache_key("bus_desc", symbol)
        # lib_get_business_description returns string
        def fetch_business_desc():
            if lib_get_business_description is None:
                raise DataProviderError(
                    f"pypsx library is not available. Cannot fetch business description for {symbol}. "
                    "Please ensure pypsx-library is installed: pip install pypsx-library"
                )
            return lib_get_business_description(symbol)
        return self._get_cached_or_call(cache_key, METADATA_TTL_SECONDS, fetch_business_desc)

    def get_metadata(self, symbol: str) -> Dict[str, Any]:
        """Get symbol metadata."""
        # Combine sector info and other details
        cache_key = _build_cache_key("metadata", symbol)
        def fetch_metadata():
            # This is a bit composite. 
            # For now return what we can get from snapshot or fundamentals
            return {"symbol": symbol} 
        return self._get_cached_or_call(cache_key, METADATA_TTL_SECONDS, fetch_metadata)

    def get_symbols(self) -> List[Dict[str, Any]]:
        """Get list of symbols."""
        cache_key = _build_cache_key("symbols")
        def fetch_syms():
             if lib_get_symbols is None:
                 raise DataProviderError(
                     "pypsx library is not available. Cannot fetch symbols. "
                     "Please ensure pypsx-library is installed: pip install pypsx-library"
                 )
             # lib_get_symbols returns list of strings usually
             syms = lib_get_symbols()
             if isinstance(syms, list):
                 # If it's a list of strings, convert to dict format
                 if syms and isinstance(syms[0], str):
                     return [{"symbol": s} for s in syms]
                 # If already dicts, return as-is
                 return syms
             return []
        return self._get_cached_or_call(cache_key, METADATA_TTL_SECONDS, fetch_syms)

    def get_market_watch(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get market watch."""
        cache_key = _build_cache_key("market_watch", symbol or "all")
        # lib_get_market_watch returns list of dicts (or DataFrame)
        def fetch_mw():
            if lib_get_market_watch is None:
                raise DataProviderError(
                    "pypsx library is not available. Cannot fetch market watch. "
                    "Please ensure pypsx-library is installed: pip install pypsx-library"
                )
            try:
                res = lib_get_market_watch()
                if hasattr(res, "to_dict"):
                    res = res.to_dict(orient="records")
                if res and isinstance(res, list):
                    return res
            except Exception as e:
                logger.warning(f"PyPSX market watch failed: {e}. Attempting synthesis fallback...")

            # Fallback: if we have a specific symbol, we can try to synthesize it
            if symbol:
                try:
                    # We'll use a simplified version of synthesis here
                    # hitting the PSX Terminal REST API directly to avoid circular deps
                    import requests
                    sym_upper = symbol.upper()
                    base = os.getenv("PSX_TERMINAL_BASE_URL", "https://psxterminal.com/api")
                    
                    # Fetch fundamentals for price/change
                    f_resp = requests.get(f"{base}/fundamentals/{sym_upper}", timeout=10)
                    f_data = f_resp.json().get("data", {}) if f_resp.status_code == 200 else {}
                    
                    # Fetch 1d kline for volume
                    k_resp = requests.get(f"{base}/klines/{sym_upper}/1d?limit=1", timeout=10)
                    k_list = k_resp.json().get("data", []) if k_resp.status_code == 200 else []
                    k_data = k_list[0] if k_list else {}
                    
                    if f_data or k_data:
                        price = f_data.get("price") or k_data.get("close")
                        return [{
                            "symbol": sym_upper,
                            "current": price,
                            "price": price,
                            "change": f_data.get("change"),
                            "change_percent": f_data.get("changePercent"),
                            "volume": k_data.get("volume"),
                        }]
                except Exception as ex:
                    logger.warning(f"PyPSX synthesis fallback failed: {ex}")

            return []
        
        data = self._get_cached_or_call(cache_key, MARKET_WATCH_TTL_SECONDS, fetch_mw)
        if symbol and isinstance(data, list):
            return [d for d in data if str(d.get("symbol", "")).upper() == symbol.upper()]
        return data

    def get_market_watch_bulk(self, symbols: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get market watch data for multiple symbols efficiently.
        Returns a dictionary mapping symbol -> data dict.
        """
        # Fetch all market data (cached)
        all_data = self.get_market_watch()
        
        result = {}
        target_symbols = {s.upper() for s in symbols}
        
        if isinstance(all_data, list):
            for item in all_data:
                sym = str(item.get("symbol", "")).upper()
                if sym in target_symbols:
                    result[sym] = item
                    
        return result

    def get_market_watch_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get single quote from market watch."""
        mw = self.get_market_watch(symbol)
        return mw[0] if mw else None

    def get_intraday(self, symbol: str, lookback_days: int = 2, *, use_cache: bool = True) -> List[Dict[str, Any]]:
        """Get intraday data."""
        # lib_get_intraday(symbol) -> usually 1 day
        cache_key = _build_cache_key("intraday", symbol)
        
        def fetch_intraday():
             # Check if pypsx library is available
             if lib_get_intraday is None:
                 raise DataProviderError(
                     "pypsx library is not available. Cannot fetch intraday data. "
                     "Please ensure pypsx-library is installed: pip install pypsx-library"
                 )
             # library might return DataFrame
             df = lib_get_intraday(symbol)
             if hasattr(df, "to_dict"):
                 # reset index if datetime is index
                 return df.reset_index().to_dict(orient="records")
             return df
             
        data = self._get_cached_or_call(cache_key, INTRADAY_TTL_SECONDS, fetch_intraday)
        # Adapt data format if needed to match what frontend expects
        # (check key names: timestamp/Date, price/Close, volume/Volume)
        return data

    def get_historical(self, symbol: str, start_date: Optional[str]=None, end_date: Optional[str]=None, interval: str="1d", *, use_cache: bool=True) -> Dict[str, Any]:
         """Get historical data."""
         # Add version to cache key to invalidate old cached data with wrong column names
         cache_key = _build_cache_key("historical_v2", symbol, start_date, end_date, interval)
         
         def fetch_hist():
             # Check if pypsx library is available
             if lib_get_historical is None:
                 raise DataProviderError(
                     "pypsx library is not available. Cannot fetch historical data. "
                     "Please ensure pypsx-library is installed: pip install pypsx-library"
                 )
             
             # Parse dates to handle ISO datetime strings (e.g., "2025-01-01T00:00:00")
             # pypsx library expects just "YYYY-MM-DD" format
             parsed_start = None
             parsed_end = None
             
             if start_date:
                 # Try to parse as datetime first, then extract date
                 try:
                     parsed_start = datetime.fromisoformat(start_date.replace('Z', '+00:00')).date().isoformat()
                 except (ValueError, AttributeError):
                     # If it's already in date format or invalid, use as-is
                     parsed_start = start_date
             
             if end_date:
                 try:
                     parsed_end = datetime.fromisoformat(end_date.replace('Z', '+00:00')).date().isoformat()
                 except (ValueError, AttributeError):
                     parsed_end = end_date
            
             logger.info(f"[{symbol}] Fetching historical data: {parsed_start} to {parsed_end} (interval: {interval})")
            
             # Fetch monthly data directly. max_workers=3 stays within the session's
             # pool_maxsize=10, preventing "Connection pool is full" dropped connections
             # that silently return empty DataFrames and cause false "no data" errors.
             try:
                 from pypsx.endpoints.historical import get_historical_data
                 df = get_historical_data(
                     symbol,
                     start_date=parsed_start,
                     end_date=parsed_end,
                     max_workers=3,
                     show_progress=False,
                 )
             except (ImportError, AttributeError):
                 # Fallback to library API if direct import fails
                 df = lib_get_historical(symbol, start_date=parsed_start, end_date=parsed_end)

             if hasattr(df, "to_dict"):
                 # pypsx library returns DataFrame with:
                 # - Index: TIME (pandas DatetimeIndex)
                 # - Columns: OPEN, HIGH, LOW, CLOSE, VOLUME (uppercase)
                 df = df.reset_index()
                 
                 if df.empty:
                     logger.warning(f"[{symbol}] No historical data found for {parsed_start} to {parsed_end}")
                     return []

                 logger.info(f"[{symbol}] Loaded {len(df)} records")
                 
                 # Rename columns to lowercase for consistency with engine expectations
                 column_mapping = {
                     "TIME": "date",
                     "OPEN": "open",
                     "HIGH": "high", 
                     "LOW": "low",
                     "CLOSE": "close",
                     "VOLUME": "volume",
                 }
                 df = df.rename(columns=column_mapping)
                 
                 # Convert date column to ISO string format
                 # pypsx returns pandas Timestamp objects which need to be serialized
                 if "date" in df.columns:
                     df["date"] = df["date"].astype(str)
                 
                 return df.to_dict(orient="records")
             return df

         data = self._get_cached_or_call(cache_key, HISTORICAL_TTL_SECONDS, fetch_hist)
         return {"symbol": symbol, "data": data}


