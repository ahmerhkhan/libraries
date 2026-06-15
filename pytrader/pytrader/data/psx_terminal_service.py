"""
PSX Terminal Service - Real-time market data integration for live trading.

This service connects to psx-terminal API for low-latency market data.
Recommended for paper trading and live trading. Provides near real-time data
without the 15-minute delay of pypsx-library.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests

from .cache.sqlite_cache import SQLiteCache
from ..utils.exceptions import DataProviderError, SymbolNotFoundError

logger = logging.getLogger(__name__)

# Cache TTLs - shorter for real-time data
PRICE_TTL_SECONDS = int(os.getenv("PSX_TERMINAL_PRICE_TTL", "30"))  # 30s for live prices
INTRADAY_TTL_SECONDS = int(os.getenv("PSX_TERMINAL_INTRADAY_TTL", "60"))  # 1min for intraday
HISTORICAL_TTL_SECONDS = int(os.getenv("PSX_TERMINAL_HISTORICAL_TTL", "3600"))  # 1hr for historical
METADATA_TTL_SECONDS = int(os.getenv("PSX_TERMINAL_METADATA_TTL", "86400"))  # 24hr for metadata


def _psx_ticks_market(symbol: str) -> str:
    """
    PSX Terminal market segment for /api/ticks/{market}/{symbol}.
    Bills/bonds (GIS/GDS-style codes) use BNB, not REG. See PSX_API_REFERENCE.md.
    """
    s = str(symbol or "").strip().upper()
    if len(s) >= 2 and s[0] == "P" and s[1].isdigit():
        return "BNB"
    return "REG"


# Path timeframe tokens; same strings are invalid as ?start=?end= range (API: 13-digit ms only).
_PSX_KLINE_TF_TOKENS = frozenset({"1m", "5m", "15m", "1h", "4h", "1d"})


def _to_psx_kline_query_ts(value: Any) -> Optional[str]:
    """
    PSX Terminal GET /api/klines accepts optional start/end as 13-digit Unix milliseconds (strings).
    Relative tokens like \"1d\" belong in the path only, not as query range parameters.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return str(int(dt.timestamp() * 1000))
    if isinstance(value, (int, float)):
        n = int(value)
        if n <= 0:
            return None
        if n < 10**12:
            n *= 1000
        return str(n)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        low = s.lower()
        if low in _PSX_KLINE_TF_TOKENS:
            return None
        if s.isdigit():
            n = int(s)
            if n < 10**12:
                n *= 1000
            return str(n)
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return str(int(dt.timestamp() * 1000))
        except Exception:
            return None
    return None


def _normalize_psx_kline_interval(interval: str) -> str:
    iv = str(interval or "1d").strip().lower()
    return iv if iv in _PSX_KLINE_TF_TOKENS else "1d"


def _psx_kline_omit_start_use_latest_only(interval: str) -> bool:
    """
    PSX Terminal rejects ?start= more than ~30 days in the past for coarser frames.
    For 1h and above, omit start/end and use only limit= — API returns the most recent candles.
    """
    tf = _normalize_psx_kline_interval(interval)
    return tf in frozenset({"1h", "4h", "1d"})


def default_psx_kline_start_ms(interval: str) -> str:
    """
    Default ?start= as 13-digit Unix ms for intervals where PSX allows a lookback (below 1h).
    Not used for 1h / 4h / 1d — those requests must omit start entirely.
    """
    tf = _normalize_psx_kline_interval(interval)
    lookback_sec = {
        "1m": 5 * 24 * 3600,
        "5m": 20 * 24 * 3600,
        "15m": 60 * 24 * 3600,
        "1h": 150 * 24 * 3600,
        "4h": 540 * 24 * 3600,
        "1d": 100 * 24 * 3600,
    }.get(tf, 100 * 24 * 3600)
    return str(int((time.time() - lookback_sec) * 1000))


def resolve_psx_kline_start_ms(start: Any, interval: str) -> str:
    """Valid 13-digit ms for ?start=, or a default lookback if start is missing/invalid (sub-1h only)."""
    parsed = _to_psx_kline_query_ts(start)
    return parsed if parsed else default_psx_kline_start_ms(interval)


def _build_cache_key(kind: str, *parts: object) -> str:
    normalized = [kind]
    for part in parts:
        if part is None:
            normalized.append("none")
        else:
            normalized.append(str(part).lower())
    return "::".join(normalized)


class PSXTerminalService:
    """
    Service wrapper for PSX Terminal API with caching.
    
    Provides low-latency market data for paper trading and live trading.
    No 15-minute delay unlike pypsx-library.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 30,
        cache: Optional[SQLiteCache] = None
    ) -> None:
        """
        Initialize PSX Terminal Service.
        
        Args:
            base_url: Base URL for psx-terminal API (default: https://psxterminal.com/api)
            timeout: Request timeout in seconds
            cache: Optional cache instance (creates new SQLiteCache if None)
        """
        self.base_url = base_url or os.getenv(
            "PSX_TERMINAL_BASE_URL",
            os.getenv("PSX_TERMINAL_BASE", "https://psxterminal.com/api")
        )
        self.timeout = timeout
        self.cache = cache or SQLiteCache()
        
        # Global request throttle to prevent API overload
        self._request_lock = threading.Lock()
        self._last_request_time = 0
        self._min_request_interval = 0.6  # 600ms between requests (max ~1.67 req/sec, API limit: 100/min)
        
        # Create session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        
        # 1-second fast memory cache for ticks
        self._mem_tick_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._mem_tick_lock = threading.Lock()
        
        logger.info(f"PSXTerminalService initialized with base_url: {self.base_url}")

    def _get_cached_or_call(
        self,
        cache_key: str,
        ttl_seconds: int,
        func: callable,
        *args,
        **kwargs
    ) -> Any:
        """Get from cache or call function and cache result."""
        # Check cache
        cached = self.cache.get(cache_key)
        if cached and not cached.expired:
            logger.debug(f"Cache HIT: {cache_key}")
            return cached.value

        # Call function
        try:
            logger.debug(f"Cache MISS: {cache_key}, calling function...")
            result = func(*args, **kwargs)
            if result is not None:
                self.cache.set(cache_key, result, ttl_seconds)
            return result
        except Exception as exc:
            logger.error(f"Error calling {func.__name__}: {exc}")
            raise DataProviderError(f"PSX Terminal API call failed: {exc}") from exc

    def _make_request(self, endpoint: str, params: Optional[Dict] = None, max_retries: int = 5) -> Dict[str, Any]:
        """
        Make HTTP request to psx-terminal API with retry logic and global rate limiting.
        
        API Rate Limits (per documentation):
        - 100 requests/minute per IP
        - 503 errors indicate server overload/rate limiting
        - 404 errors indicate missing data for that symbol
        """
        url = f"{self.base_url}{endpoint}"
        
        # Global rate limiting: enforce minimum delay between all requests
        with self._request_lock:
            now = time.time()
            time_since_last = now - self._last_request_time
            if time_since_last < self._min_request_interval:
                sleep_time = self._min_request_interval - time_since_last
                time.sleep(sleep_time)
            self._last_request_time = time.time()
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                
                if not data.get("success"):
                    raise DataProviderError(f"API returned success=false for {endpoint}")
                
                return data.get("data", {})
                
            except requests.exceptions.HTTPError as exc:
                # Handle specific HTTP errors
                if exc.response.status_code == 404:
                    # 404 means data not available for this symbol - don't retry
                    logger.warning(f"Data not found for {endpoint} (404)")
                    raise DataProviderError(f"Data not found: {endpoint}") from exc
                    
                elif exc.response.status_code == 503:
                    # 503 means service unavailable/rate limited - retry with longer backoff
                    if attempt < max_retries - 1:
                        backoff_time = (2 ** attempt) * 1.0  # 1s, 2s, 4s, 8s, 16s
                        logger.warning(f"Service unavailable (503) for {endpoint}, retrying in {backoff_time}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(backoff_time)
                        continue
                    else:
                        logger.error(f"Max retries exceeded for {endpoint} after {max_retries} attempts")
                        raise DataProviderError(f"Service unavailable (503) for {endpoint} after {max_retries} retries") from exc
                        
                elif exc.response.status_code == 429:
                    # 429 means too many requests - longer backoff
                    if attempt < max_retries - 1:
                        backoff_time = (2 ** attempt) * 3  # 3s, 6s, 12s, 24s, 48s
                        logger.warning(f"Rate limit exceeded (429) for {endpoint}, waiting {backoff_time}s")
                        time.sleep(backoff_time)
                        continue
                    else:
                        raise DataProviderError(f"Rate limit exceeded (429) for {endpoint}") from exc
                else:
                    raise DataProviderError(f"Request failed for {endpoint}: {exc}") from exc
                    
            except requests.exceptions.Timeout as exc:
                if attempt < max_retries - 1:
                    logger.warning(f"Timeout for {endpoint}, retrying (attempt {attempt + 1}/{max_retries})")
                    time.sleep(1.0)
                    continue
                raise DataProviderError(f"Request timeout for {endpoint}") from exc
                
            except requests.exceptions.RequestException as exc:
                raise DataProviderError(f"Request failed for {endpoint}: {exc}") from exc
                
            except ValueError as exc:
                raise DataProviderError(f"Invalid JSON response from {endpoint}") from exc
        
        # Should never reach here, but just in case
        raise DataProviderError(f"Failed to fetch {endpoint} after {max_retries} attempts")

    def get_price(self, symbol: str, *, use_cache: bool = True) -> Dict[str, Any]:
        """
        Get current price for a symbol by synthesizing fundamentals and klines.
        
        Args:
            symbol: Stock symbol (e.g., OGDC, PPL)
            
        Returns:
            Dict with keys: symbol, price, change, change_percent, volume, etc.
        """
        import concurrent.futures
        
        sym_upper = symbol.upper()
        
        # 1-second fast memory cache
        if use_cache:
            with self._mem_tick_lock:
                cached = self._mem_tick_cache.get(sym_upper)
                if cached and time.time() - cached[0] < 1.0:
                    return cached[1]
        
        def fetch_price():
            market = _psx_ticks_market(sym_upper)
            # Short-circuit for bills/bonds which might not have fundamentals
            if market == "BNB":
                data = self._make_request(f"/ticks/{market}/{sym_upper}")
                if not data:
                    raise SymbolNotFoundError(f"Symbol {symbol} not found")
                change_pct = data.get("changePercent", 0) * 100
                px = float(data.get("price") or 0.0)
                bid = float(data.get("bid") or 0.0)
                ask = float(data.get("ask") or 0.0)
                if px > 0 and (bid <= 0 or ask <= 0):
                    from .paper_spread import synthetic_bid_ask_from_last

                    bid, ask = synthetic_bid_ask_from_last(px)
                return {
                    "symbol": data.get("symbol"),
                    "price": data.get("price"),
                    "change": data.get("change"),
                    "change_percent": change_pct,
                    "volume": data.get("volume"),
                    "high": data.get("high"),
                    "low": data.get("low"),
                    "bid": bid,
                    "ask": ask,
                    "market_state": data.get("st"),
                    "st": data.get("st"),
                    "timestamp": data.get("timestamp"),
                    "last_updated": datetime.fromtimestamp(data.get("timestamp", time.time()), tz=timezone.utc).isoformat(),
                }
            
            # Synthesize from fundamentals and klines
            fund_data = {}
            kline_data = {}
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                # Use a small internal helper to avoid throwing on 404 immediately during concurrent fetch
                def safe_fetch(endpoint, params=None):
                    try:
                        return self._make_request(endpoint, params)
                    except Exception as e:
                        logger.warning(f"Fallback synthesis fetch failed for {endpoint}: {e}")
                        return None

                f_future = executor.submit(safe_fetch, f"/fundamentals/{sym_upper}")
                k_future = executor.submit(safe_fetch, f"/klines/{sym_upper}/1d", {"limit": 1})
                
                fund_data = f_future.result() or {}
                kline_res = k_future.result()
                if kline_res and isinstance(kline_res, list) and len(kline_res) > 0:
                    kline_data = kline_res[0]
                    
            if not fund_data and not kline_data:
                raise SymbolNotFoundError(f"Symbol {symbol} not found (synthesis failed)")

            # Fundamentals changePercent is already a percentage (e.g. 1.928 for 1.928%)
            price = fund_data.get("price") or kline_data.get("close") or 0.0
            change = fund_data.get("change") or 0.0
            change_pct = round(fund_data.get("changePercent") or 0.0, 2)
            
            # Daily volume from 1d kline
            volume = kline_data.get("volume") or 0
            
            timestamp_ms = kline_data.get("timestamp") or (time.time() * 1000)
            timestamp_sec = timestamp_ms / 1000

            from .paper_spread import synthetic_bid_ask_from_last

            last_px = float(price or 0.0)
            syn_bid, syn_ask = synthetic_bid_ask_from_last(last_px) if last_px > 0 else (0.0, 0.0)
            result = {
                "symbol": sym_upper,
                "price": price,
                "change": change,
                "change_percent": change_pct,
                "volume": int(volume),
                "high": kline_data.get("high") or price,
                "low": kline_data.get("low") or price,
                "bid": syn_bid,
                "ask": syn_ask,
                "market_state": "UNKNOWN",
                "st": "UNKNOWN",
                "timestamp": timestamp_sec,
                "last_updated": datetime.fromtimestamp(timestamp_sec, tz=timezone.utc).isoformat(),
            }
            return result

        if not use_cache:
            result = fetch_price()
            with self._mem_tick_lock:
                self._mem_tick_cache[sym_upper] = (time.time(), result)
            return result

        cache_key = _build_cache_key("price", symbol)
        result = self._get_cached_or_call(cache_key, PRICE_TTL_SECONDS, fetch_price)
        
        with self._mem_tick_lock:
            self._mem_tick_cache[sym_upper] = (time.time(), result)
            
        return result

    def get_latest_prices(self, symbols: List[str], *, use_cache: bool = True) -> Dict[str, float]:
        """
        Convenience batch fetch for latest prices.

        The upstream PSX Terminal API is still per-symbol for ticks, but exposing this
        method lets callers use a single interface and choose whether to bypass cache.
        """
        prices: Dict[str, float] = {}
        for symbol in symbols:
            try:
                quote = self.get_price(str(symbol).upper(), use_cache=use_cache)
                price = quote.get("price")
                if price is None:
                    continue
                prices[str(symbol).upper()] = float(price)
            except Exception:
                continue
        return prices

    def get_market_watch_bulk(self, symbols: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get market watch data for multiple symbols.
        Returns a dictionary mapping symbol -> data dict.
        """
        result = {}
        for symbol in symbols:
            try:
                sym_upper = str(symbol).upper()
                quote = self.get_price(sym_upper)
                if quote:
                    # Map to the format expected by portfolio recompute
                    result[sym_upper] = {
                        "symbol": sym_upper,
                        "current_price": quote.get("price"),
                        "current": quote.get("price"),
                        "change": quote.get("change"),
                        "change_percent": quote.get("change_percent"),
                        "volume": quote.get("volume"),
                        "bid": quote.get("bid"),
                        "ask": quote.get("ask"),
                    }
            except Exception:
                continue
        return result

    def get_symbols(self) -> List[str]:
        """Get list of all available symbols."""
        cache_key = _build_cache_key("symbols")
        
        def fetch_symbols():
            data = self._make_request("/symbols")
            # API returns list of symbol strings
            if isinstance(data, list):
                # Filter out non-string items just in case
                return [s for s in data if isinstance(s, str)]
            return []
        
        return self._get_cached_or_call(cache_key, METADATA_TTL_SECONDS, fetch_symbols)

    def get_intraday(self, symbol: str, lookback_days: int = 2, *, use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        Get intraday 1-minute candlestick data.
        
        Args:
            symbol: Stock symbol
            lookback_days: Number of days to look back (not used, API returns latest)
            use_cache: Whether to use cached data
            
        Returns:
            List of dicts with keys: timestamp, price, volume, open, high, low
        """
        cache_key = _build_cache_key("intraday", symbol)
        
        def fetch_intraday():
            # Fetch 1-minute klines (limit 100 = ~1.5 hours of data)
            data = self._make_request(
                f"/klines/{symbol.upper()}/1m",
                params={"limit": 100, "start": default_psx_kline_start_ms("1m")},
            )
            
            if not isinstance(data, list):
                return []
            
            ticks = []
            for kline in data:
                ticks.append({
                    "timestamp": kline.get("timestamp"),  # Milliseconds
                    "price": kline.get("close"),
                    "volume": kline.get("volume"),
                    "open": kline.get("open"),
                    "high": kline.get("high"),
                    "low": kline.get("low"),
                })
            
            return ticks
        
        if not use_cache:
            return fetch_intraday()
        
        return self._get_cached_or_call(cache_key, INTRADAY_TTL_SECONDS, fetch_intraday)

    def get_historical(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        interval: str = "1d",
        *,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Get historical candlestick data.
        
        Args:
            symbol: Stock symbol
            start_date: Start date (13-digit Unix timestamp in milliseconds or ISO string)
            end_date: End date (13-digit Unix timestamp in milliseconds or ISO string)
            interval: Timeframe (1m, 5m, 15m, 1h, 4h, 1d)
            use_cache: Whether to use cached data
            
        Returns:
            Dict with keys: symbol, interval, data (list of OHLCV dicts)
        """
        cache_key = _build_cache_key(
            "historical", symbol, start_date, end_date, _normalize_psx_kline_interval(interval)
        )
        
        def fetch_historical():
            tf = _normalize_psx_kline_interval(interval)
            params: Dict[str, Any] = {"limit": 100}
            if not _psx_kline_omit_start_use_latest_only(tf):
                end_q = _to_psx_kline_query_ts(end_date)
                params["start"] = resolve_psx_kline_start_ms(start_date, tf)
                if end_q:
                    params["end"] = end_q

            data = self._make_request(f"/klines/{symbol.upper()}/{tf}", params=params)
            
            if not isinstance(data, list):
                return {"symbol": symbol, "interval": tf, "data": []}
            
            # Convert to expected format with Date field
            klines = []
            for kline in data:
                # Robustly convert various timestamp formats to milliseconds
                raw_ts = kline.get("timestamp", 0)
                ts_ms = 0
                try:
                    if raw_ts is None:
                        ts_ms = 0
                    elif isinstance(raw_ts, (int, float)):
                        ts_ms = int(raw_ts)
                    elif isinstance(raw_ts, str):
                        s = raw_ts.strip()
                        # Numeric string (milliseconds or seconds)
                        if s.isdigit():
                            ts_ms = int(s)
                        else:
                            # Try float-like numeric string
                            try:
                                ts_ms = int(float(s))
                            except Exception:
                                # Try ISO datetime string
                                try:
                                    dt = datetime.fromisoformat(s)
                                    ts_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
                                except Exception:
                                    ts_ms = 0
                    else:
                        ts_ms = int(raw_ts)
                except Exception:
                    ts_ms = 0

                ts_seconds = ts_ms / 1000

                klines.append({
                    "Date": datetime.fromtimestamp(ts_seconds, tz=timezone.utc).isoformat(),
                    "Open": kline.get("open"),
                    "High": kline.get("high"),
                    "Low": kline.get("low"),
                    "Close": kline.get("close"),
                    "Volume": kline.get("volume"),
                    "timestamp": raw_ts,
                })
            
            return {"symbol": symbol, "interval": tf, "data": klines}
        
        if not use_cache:
            return fetch_historical()
        
        return self._get_cached_or_call(cache_key, HISTORICAL_TTL_SECONDS, fetch_historical)

    def get_company_snapshot(self, symbol: str) -> Dict[str, Any]:
        """Get company snapshot with current price and metadata."""
        cache_key = _build_cache_key("snapshot", symbol)
        
        def fetch_snapshot():
            market = _psx_ticks_market(symbol)
            tick_data = self._make_request(f"/ticks/{market}/{symbol.upper()}")
            
            if not tick_data:
                raise SymbolNotFoundError(f"Symbol {symbol} not found")
            
            company_data: Dict[str, Any] = {}
            if market != "BNB":
                try:
                    company_data = self._make_request(f"/companies/{symbol.upper()}")
                except Exception:
                    company_data = {}
            
            stats = company_data.get("financialStats", {})
            
            return {
                "symbol": tick_data.get("symbol"),
                "current": tick_data.get("price"),
                "change": tick_data.get("change"),
                "change_pct": tick_data.get("changePercent", 0) * 100,
                "volume": tick_data.get("volume"),
                "value": tick_data.get("value"),
                "high": tick_data.get("high"),
                "low": tick_data.get("low"),
                "bid_price": tick_data.get("bid"),
                "bid_volume": tick_data.get("bidVol"),
                "ask_price": tick_data.get("ask"),
                "ask_volume": tick_data.get("askVol"),
                "market_cap": stats.get("marketCap", {}).get("numeric") if isinstance(stats.get("marketCap"), dict) else None,
                "shares": stats.get("shares", {}).get("numeric") if isinstance(stats.get("shares"), dict) else None,
                "free_float": stats.get("freeFloat", {}).get("numeric") if isinstance(stats.get("freeFloat"), dict) else None,
                "free_float_pct": stats.get("freeFloatPercent", {}).get("numeric") if isinstance(stats.get("freeFloatPercent"), dict) else None,
                "business_description": company_data.get("businessDescription"),
                "key_people": company_data.get("keyPeople", []),
            }
        
        return self._get_cached_or_call(cache_key, PRICE_TTL_SECONDS, fetch_snapshot)

    def get_company_fundamentals(self, symbol: str) -> Dict[str, Any]:
        """Get company fundamentals."""
        if _psx_ticks_market(symbol) == "BNB":
            return {}

        cache_key = _build_cache_key("fundamentals", symbol)
        
        def fetch_fundamentals():
            data = self._make_request(f"/fundamentals/{symbol.upper()}")
            return data if data else {}
        
        return self._get_cached_or_call(cache_key, METADATA_TTL_SECONDS, fetch_fundamentals)

    def get_company_information(self, symbol: str) -> Dict[str, Any]:
        """
        GET /companies/{symbol} — business description, financialStats, keyPeople.
        Does not call /ticks; use when tick snapshots fail but profile text is still needed.
        """
        sym = str(symbol or "").strip().upper()
        if not sym or _psx_ticks_market(sym) == "BNB":
            return {}
        cache_key = _build_cache_key("company_info", sym)

        def fetch_info():
            try:
                data = self._make_request(f"/companies/{sym}")
                return data if isinstance(data, dict) else {}
            except DataProviderError as exc:
                logger.warning("get_company_information failed for %s: %s", sym, exc)
                return {}

        return self._get_cached_or_call(cache_key, METADATA_TTL_SECONDS, fetch_info)

    def get_market_stats(self, market_type: str = "REG") -> Dict[str, Any]:
        """Get market statistics (breadth, gainers, losers, etc.)."""
        cache_key = _build_cache_key("stats", market_type)
        
        def fetch_stats():
            data = self._make_request(f"/stats/{market_type.upper()}")
            return data if data else {}
        
        return self._get_cached_or_call(cache_key, PRICE_TTL_SECONDS, fetch_stats)

    def get_indices(self) -> List[Dict[str, Any]]:
        """Get all market indices."""
        cache_key = _build_cache_key("indices")
        
        def fetch_indices():
            indices = ['KSE100', 'KSE30', 'ALLSHR', 'KMI30', 'KMIALLSHR']
            results = []
            
            for idx in indices:
                try:
                    data = self._make_request(f"/ticks/IDX/{idx}")
                    if data:
                        results.append({
                            "symbol": data.get("symbol"),
                            "name": data.get("symbol"),
                            "value": data.get("price"),
                            "change": data.get("change"),
                            "change_pct": data.get("changePercent", 0) * 100,
                            "high": data.get("high"),
                            "low": data.get("low"),
                        })
                except Exception as exc:
                    logger.warning(f"Failed to fetch index {idx}: {exc}")
                    continue
            
            return results
        
        return self._get_cached_or_call(cache_key, PRICE_TTL_SECONDS, fetch_indices)

    def get_sectors(self) -> List[Dict[str, Any]]:
        """
        Get sector performance data.
        
        Returns:
            List of dicts with sector performance metrics.
        """
        # API Doc: GET /api/stats/sectors
        cache_key = _build_cache_key("stats", "sectors")
        
        def fetch_sectors():
            try:
                # Correct endpoint: /stats/sectors (not /stats/SECTORS)
                data = self._make_request("/stats/sectors")
                
                if not data:
                    return []
                
                # API returns dict mapping sector names to performance data
                # Convert to list format for frontend
                sectors_list = []
                for sector_name, sector_data in data.items():
                    if isinstance(sector_data, dict):
                        sectors_list.append({
                            "name": sector_name,
                            "totalVolume": sector_data.get("totalVolume"),
                            "totalValue": sector_data.get("totalValue"),
                            "totalTrades": sector_data.get("totalTrades"),
                            "gainers": sector_data.get("gainers"),
                            "losers": sector_data.get("losers"),
                            "unchanged": sector_data.get("unchanged"),
                            "avgChange": sector_data.get("avgChange"),
                            "avgChangePercent": sector_data.get("avgChangePercent"),
                            "symbols": sector_data.get("symbols", [])
                        })
                
                return sectors_list
                
            except DataProviderError as e:
                logger.warning(f"Sectors endpoint error: {e}")
                return []
            except Exception as e:
                logger.error(f"Error fetching sectors: {e}")
                return []
            
        return self._get_cached_or_call(cache_key, PRICE_TTL_SECONDS, fetch_sectors)

    def get_index_overview(self, symbol: str) -> Dict[str, Any]:
        """
        Get overview for a specific index.
        """
        # Efficiently get just the one index if possible, or filter from list
        # API allows /ticks/IDX/{symbol}
        cache_key = _build_cache_key("index", symbol)
        
        def fetch_index():
            # Try specific endpoint
            try:
                data = self._make_request(f"/ticks/IDX/{symbol.upper()}")
                if data:
                    # Enrich with change_pct if needed
                    if "changePercent" in data and "change_pct" not in data:
                        data["change_pct"] = data["changePercent"] * 100
                    return data
            except:
                pass
            
            # Fallback to list search
            indices = self.get_indices()
            for idx in indices:
                if idx.get("symbol") == symbol.upper():
                    return idx
            return {}

        return self._get_cached_or_call(cache_key, PRICE_TTL_SECONDS, fetch_index)

    def get_live_summary(self) -> Dict[str, Any]:
        """Get live market summary matching PyPSXService interface."""
        # Need KSE100 + stats
        cache_key = _build_cache_key("live_summary")
        
        def fetch_summary():
            stats = self._make_request("/stats/REG")
            if not stats:
                stats = {}
                
            # Get KSE100
            try:
                kse100 = self.get_index_overview("KSE100")
            except:
                kse100 = {}
                
            # Helper to transform list items
            def transform_list(items):
                result = []
                for item in items:
                    # Ensure symbol is valid string for frontend .toLowerCase()
                    sym = item.get("symbol")
                    if not isinstance(sym, str):
                        continue
                        
                    result.append({
                        "symbol": sym,
                        "current": item.get("price"),
                        "price": item.get("price"),
                        "change": item.get("change"),
                        "change_percent": item.get("changePercent", 0) * 100,
                        "volume": item.get("volume"),
                        "value": item.get("value"),
                    })
                return result

            top_gainers = transform_list(stats.get("topGainers", []))
            top_losers = transform_list(stats.get("topLosers", []))
            
            # transform topVolume slightly differently if needed, but structure is same usually
            top_volume = transform_list(stats.get("topVolume", []))
            
            summary = {
                "kse100_value": kse100.get("current") or kse100.get("price"),
                "kse100_change": kse100.get("change"),
                "kse100_change_pct": kse100.get("change_pct") or (kse100.get("changePercent", 0) * 100),
                "total_volume": stats.get("totalVolume"),
                "total_value": stats.get("totalValue"),
                "total_trades": stats.get("totalTrades"),
                "gainers": stats.get("gainers"),
                "losers": stats.get("losers"),
                "unchanged": stats.get("unchanged"),
                "advancers": stats.get("gainers"), # Alias
                "decliners": stats.get("losers"),  # Alias
                "top_gainers": top_gainers,
                "top_losers": top_losers,
                "top_decliners": top_losers, # Alias
                "top_volume": top_volume,
            }
            return summary
            
        return self._get_cached_or_call(cache_key, PRICE_TTL_SECONDS, fetch_summary)

    def get_all_prices(self) -> Dict[str, Any]:
        """
        Get all prices. CAUTION: PSX API doesn't support bulk price fetch efficiently.
        Returns prices for top active symbols (from stats) to avoid 500+ requests.
        """
        cache_key = _build_cache_key("all_prices")
        
        def fetch_all():
            stats = self._make_request("/stats/REG")
            if not stats: 
                return {"symbols": []}
                
            # Collecting symbols from top lists
            # This is a partial list but prevents throttling/503s
            all_symbols = {}
            
            for lst in ["topGainers", "topLosers", "topVolume"]:
                for item in stats.get(lst, []):
                    sym = item.get("symbol")
                    if sym and sym not in all_symbols:
                        all_symbols[sym] = {
                            "symbol": sym,
                            "price": item.get("price"),
                            "change": item.get("change"),
                            "change_pct": item.get("changePercent", 0) * 100,
                            "volume": item.get("volume"),
                        }
            
            return {"symbols": list(all_symbols.values())}
            
        return self._get_cached_or_call(cache_key, PRICE_TTL_SECONDS, fetch_all)

    def get_business_description(self, symbol: str) -> str:
        """Get business description."""
        # Wrap get_company_snapshot
        snap = self.get_company_snapshot(symbol)
        return snap.get("business_description")

    def get_market_watch(self, symbol: str) -> Dict[str, Any]:
        """Get market watch data (alias for snapshot)."""
        return self.get_company_snapshot(symbol)

    def get_metadata(self, symbol: str) -> Dict[str, Any]:
        """Get metadata (alias for snapshot/fundamentals)."""
        try:
            snap = self.get_company_snapshot(symbol)
            funds = self.get_company_fundamentals(symbol)
            # Merge both
            return {**snap, **funds}
        except:
             return {"symbol": symbol}

    def get_dividends(self, symbol: str) -> List[Dict[str, Any]]:
        """Get dividend history for a specific symbol."""
        cache_key = _build_cache_key("dividends", symbol)
        
        def fetch_dividends():
            res = self._make_request(f"/dividends/{symbol.upper()}")
            if isinstance(res, list):
                return res
            if isinstance(res, dict) and "data" in res:
                return res.get("data", [])
            return []
            
        return self._get_cached_or_call(cache_key, PRICE_TTL_SECONDS, fetch_dividends)

    def __del__(self):
        """Cleanup: close session on deletion."""
        if hasattr(self, "session"):
            self.session.close()


# Convenience alias for backward compatibility
AsyncPSXTerminalService = PSXTerminalService  # Same implementation, just alias for now
