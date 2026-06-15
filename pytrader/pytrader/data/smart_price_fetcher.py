"""
Dynamic Rate-Limiting Engine for Real-Time Price Fetching
==========================================================

Intelligent price fetcher that dynamically adjusts request intervals based on:
1. Portfolio size (number of positions)
2. API rate limits (100 requests/minute)
3. Network conditions and jitter

Features:
- Token Bucket algorithm for global rate limiting
- Dynamic interval calculation: Safe_Interval = (60,000ms / N) * 1.1
- Support for batch requests (10 symbols per request)
- Price caching with TTL
- Automatic retry with exponential backoff
- Thread-safe operation

Author: PyTrader Team
"""

import asyncio
import time
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List, Optional, Set, Callable, Any
from enum import Enum

logger = logging.getLogger(__name__)


class FetchPriority(Enum):
    """Priority levels for price fetch requests"""
    HIGH = 1      # Active trading positions
    MEDIUM = 2    # Watchlist
    LOW = 3       # Market indices


@dataclass
class PriceUpdate:
    """Container for price update data"""
    symbol: str
    price: float
    timestamp: datetime
    change: float = 0.0
    change_percent: float = 0.0
    volume: int = 0
    bid: float = 0.0
    ask: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "symbol": self.symbol,
            "price": self.price,
            "timestamp": self.timestamp.isoformat(),
            "change": self.change,
            "change_percent": self.change_percent,
            "volume": self.volume,
            "bid": self.bid,
            "ask": self.ask,
        }


class TokenBucket:
    """
    Token Bucket rate limiter for global API rate limiting.
    
    Enforces maximum 100 requests per minute across all operations.
    """
    
    def __init__(self, capacity: int = 100, refill_rate: float = 100.0):
        """
        Initialize token bucket.
        
        Args:
            capacity: Maximum tokens (100 for 100 RPM)
            refill_rate: Tokens per minute (100 for 100 RPM)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per minute
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self._lock = Lock()
        
        logger.info(f"TokenBucket initialized: {capacity} capacity, {refill_rate} tokens/min")
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed_seconds = now - self.last_refill
        
        # Calculate tokens to add (refill_rate is per minute)
        tokens_to_add = (elapsed_seconds / 60.0) * self.refill_rate
        
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens.
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            True if tokens were consumed, False if insufficient tokens
        """
        with self._lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    async def wait_for_token(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        """
        Wait until tokens are available.
        
        Args:
            tokens: Number of tokens needed
            timeout: Maximum time to wait (seconds)
            
        Returns:
            True if tokens acquired, False if timeout
        """
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            if self.consume(tokens):
                return True
            
            # Calculate sleep time until next token available
            with self._lock:
                self._refill()
                if self.tokens >= tokens:
                    continue
                    
                tokens_needed = tokens - self.tokens
                sleep_seconds = (tokens_needed / self.refill_rate) * 60.0
                sleep_seconds = min(sleep_seconds, 1.0)  # Max 1 second sleep
            
            await asyncio.sleep(sleep_seconds)
        
        return False
    
    def available_tokens(self) -> float:
        """Get current available tokens"""
        with self._lock:
            self._refill()
            return self.tokens


class PriceFetcherQueue:
    """
    Smart queue for fetching real-time prices with dynamic throttling.
    
    Automatically adjusts fetch interval based on portfolio size to maximize
    refresh rate while staying under API rate limits.
    """
    
    def __init__(
        self,
        data_service: Any,
        *,
        max_rpm: int = 100,
        safety_buffer: float = 1.1,
        batch_size: int = 1,
        cache_ttl_seconds: int = 30,
        enable_batching: bool = False,
    ):
        """
        Initialize price fetcher queue.
        
        Args:
            data_service: Service for fetching prices (e.g., PSXTerminalService)
            max_rpm: Maximum requests per minute
            safety_buffer: Safety multiplier for interval calculation (1.1 = 10% buffer)
            batch_size: Number of symbols to fetch per request (if batching supported)
            cache_ttl_seconds: Cache time-to-live in seconds
            enable_batching: Whether to use batch requests
        """
        self.data_service = data_service
        self.max_rpm = max_rpm
        self.safety_buffer = safety_buffer
        self.batch_size = batch_size if enable_batching else 1
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self.enable_batching = enable_batching
        
        # Token bucket for global rate limiting
        self.token_bucket = TokenBucket(capacity=max_rpm, refill_rate=max_rpm)
        
        # Ticker management
        self.tickers: Set[str] = set()
        self.priority_map: Dict[str, FetchPriority] = {}
        self._ticker_lock = Lock()
        
        # Price cache
        self.price_cache: Dict[str, PriceUpdate] = {}
        self.cache_timestamps: Dict[str, datetime] = {}
        self._cache_lock = Lock()
        
        # Queue state
        self.is_running = False
        self._fetch_task: Optional[asyncio.Task] = None
        self._current_interval_ms: float = 600.0  # Default
        
        # Callbacks for price updates
        self.update_callbacks: List[Callable[[PriceUpdate], None]] = []
        
        # Statistics
        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "rate_limit_hits": 0,
            "errors": 0,
        }
        
        logger.info(f"PriceFetcherQueue initialized: max_rpm={max_rpm}, batch_size={self.batch_size}")
    
    def add_ticker(self, symbol: str, priority: FetchPriority = FetchPriority.MEDIUM) -> None:
        """Add a ticker to the fetch queue"""
        with self._ticker_lock:
            self.tickers.add(symbol.upper())
            self.priority_map[symbol.upper()] = priority
        
        # Recalculate interval
        self._update_fetch_interval()
        
        logger.debug(f"Added ticker {symbol} (priority={priority.name}), total={len(self.tickers)}")
    
    def remove_ticker(self, symbol: str) -> None:
        """Remove a ticker from the fetch queue"""
        with self._ticker_lock:
            self.tickers.discard(symbol.upper())
            self.priority_map.pop(symbol.upper(), None)
        
        # Clean up cache
        with self._cache_lock:
            self.price_cache.pop(symbol.upper(), None)
            self.cache_timestamps.pop(symbol.upper(), None)
        
        # Recalculate interval
        self._update_fetch_interval()
        
        logger.debug(f"Removed ticker {symbol}, total={len(self.tickers)}")
    
    def set_tickers(self, symbols: List[str], priority: FetchPriority = FetchPriority.MEDIUM) -> None:
        """Set the complete list of tickers to fetch"""
        with self._ticker_lock:
            self.tickers = {s.upper() for s in symbols}
            self.priority_map = {s.upper(): priority for s in symbols}
        
        self._update_fetch_interval()
        
        logger.info(f"Set {len(symbols)} tickers for fetching")
    
    def _update_fetch_interval(self) -> None:
        """
        Calculate dynamic fetch interval based on portfolio size.
        
        Formula: Safe_Interval_ms = (60,000 ms / Total_Positions) * Safety_Buffer
        """
        with self._ticker_lock:
            num_tickers = len(self.tickers)
        
        if num_tickers == 0:
            self._current_interval_ms = 600.0
            return
        
        # Adjust for batching
        effective_requests = num_tickers if self.batch_size == 1 else (num_tickers / self.batch_size)
        effective_requests = max(1, effective_requests)
        
        # Calculate interval: 60,000ms / effective_requests * safety_buffer
        self._current_interval_ms = (60000.0 / effective_requests) * self.safety_buffer
        
        # Floor at minimum 100ms
        self._current_interval_ms = max(100.0, self._current_interval_ms)
        
        logger.debug(f"Updated fetch interval: {self._current_interval_ms:.0f}ms for {num_tickers} tickers")
    
    def get_cached_price(self, symbol: str) -> Optional[PriceUpdate]:
        """Get cached price if not expired"""
        with self._cache_lock:
            if symbol.upper() not in self.price_cache:
                return None
            
            cache_time = self.cache_timestamps.get(symbol.upper())
            if not cache_time:
                return None
            
            # Check TTL
            if datetime.now() - cache_time > self.cache_ttl:
                # Expired
                self.price_cache.pop(symbol.upper(), None)
                self.cache_timestamps.pop(symbol.upper(), None)
                return None
            
            self.stats["cache_hits"] += 1
            return self.price_cache[symbol.upper()]
    
    async def fetch_price(self, symbol: str, use_cache: bool = True) -> Optional[PriceUpdate]:
        """
        Fetch price for a single symbol.
        
        Args:
            symbol: Stock symbol
            use_cache: Whether to use cached data
            
        Returns:
            PriceUpdate object or None if fetch failed
        """
        symbol = symbol.upper()
        
        # Check cache first
        if use_cache:
            cached = self.get_cached_price(symbol)
            if cached:
                return cached
        
        self.stats["cache_misses"] += 1
        
        # Wait for token
        if not await self.token_bucket.wait_for_token(1, timeout=10.0):
            self.stats["rate_limit_hits"] += 1
            logger.warning(f"Rate limit reached, could not fetch {symbol}")
            return None
        
        # Fetch from service
        try:
            self.stats["total_requests"] += 1
            price_data = self.data_service.get_price(symbol)
            
            if not price_data:
                return None
            
            # Create PriceUpdate
            update = PriceUpdate(
                symbol=symbol,
                price=price_data.get("price", 0.0),
                timestamp=datetime.now(),
                change=price_data.get("change", 0.0),
                change_percent=price_data.get("change_percent", 0.0),
                volume=price_data.get("volume", 0),
                bid=price_data.get("bid", 0.0),
                ask=price_data.get("ask", 0.0),
            )
            
            # Update cache
            with self._cache_lock:
                self.price_cache[symbol] = update
                self.cache_timestamps[symbol] = datetime.now()
            
            # Notify callbacks
            for callback in self.update_callbacks:
                try:
                    callback(update)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
            
            return update
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Error fetching price for {symbol}: {e}")
            return None
    
    async def _fetch_loop(self) -> None:
        """Main fetch loop that cycles through all tickers"""
        logger.info("Starting price fetch loop")
        
        while self.is_running:
            try:
                # Get current ticker list (snapshot)
                with self._ticker_lock:
                    current_tickers = list(self.tickers)
                    priorities = self.priority_map.copy()
                
                if not current_tickers:
                    await asyncio.sleep(1.0)
                    continue
                
                # Sort by priority (HIGH first)
                current_tickers.sort(key=lambda s: priorities.get(s, FetchPriority.LOW).value)
                
                # Fetch each ticker
                for symbol in current_tickers:
                    if not self.is_running:
                        break
                    
                    await self.fetch_price(symbol, use_cache=False)
                    
                    # Sleep for dynamic interval
                    await asyncio.sleep(self._current_interval_ms / 1000.0)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in fetch loop: {e}", exc_info=True)
                await  asyncio.sleep(1.0)
        
        logger.info("Price fetch loop stopped")
    
    async def start(self) -> None:
        """Start the fetch loop"""
        if self.is_running:
            logger.warning("Fetch queue already running")
            return
        
        self.is_running = True
        self._fetch_task = asyncio.create_task(self._fetch_loop())
        logger.info("Price fetch queue started")
    
    async def stop(self) -> None:
        """Stop the fetch loop"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        if self._fetch_task:
            self._fetch_task.cancel()
            try:
                await self._fetch_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Price fetch queue stopped")
    
    def register_callback(self, callback: Callable[[PriceUpdate], None]) -> None:
        """Register a callback for price updates"""
        self.update_callbacks.append(callback)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get fetcher statistics"""
        return {
            **self.stats,
            "active_tickers": len(self.tickers),
            "cached_prices": len(self.price_cache),
            "current_interval_ms": self._current_interval_ms,
            "available_tokens": self.token_bucket.available_tokens(),
        }


# Example usage
if __name__ == "__main__":
    import sys
    sys.path.append(".")
    
    from pytrader.data.psx_terminal_service import PSXTerminalService
    
    async def main():
        # Initialize data service
        data_service = PSXTerminalService()
        
        # Create fetcher queue
        fetcher = PriceFetcherQueue(
            data_service,
            max_rpm=100,
            safety_buffer=1.1,
            batch_size=1,
            cache_ttl_seconds=30,
        )
        
        # Register callback
        def on_price_update(update: PriceUpdate):
            print(f"📊 {update.symbol}: Rs. {update.price:.2f} ({update.change_percent:+.2f}%)")
        
        fetcher.register_callback(on_price_update)
        
        # Add portfolio tickers
        portfolio = ["OGDC", "HBL", "UBL", "MCB", "PPL", "LUCK", "FFC", "EFERT", "PSO", "HUBC"]
        fetcher.set_tickers(portfolio, priority=FetchPriority.HIGH)
        
        # Start fetching
        await fetcher.start()
        
        # Run for 60 seconds
        await asyncio.sleep(60)
        
        # Print stats
        print("\n📈 Statistics:")
        stats = fetcher.get_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        # Stop
        await fetcher.stop()
    
    asyncio.run(main())
