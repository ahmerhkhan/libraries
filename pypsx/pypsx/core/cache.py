import time
from threading import RLock
from typing import Any, Optional


class TTLCache:
    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = RLock()

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expiry, value = item
            if expiry != 0 and now > expiry:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int | float | None) -> Any:
        expiry = 0 if not ttl_seconds or ttl_seconds <= 0 else time.time() + float(ttl_seconds)
        with self._lock:
            self._store[key] = (expiry, value)
        return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_GLOBAL_CACHE = TTLCache()


def cache_get(key: str) -> Optional[Any]:
    return _GLOBAL_CACHE.get(key)


def cache_set(key: str, value: Any, ttl_seconds: Optional[float]) -> Any:
    return _GLOBAL_CACHE.set(key, value, ttl_seconds)


def cache_delete(key: str) -> None:
    _GLOBAL_CACHE.delete(key)


def cache_clear() -> None:
    _GLOBAL_CACHE.clear()

"""
Global data cache for PyPSX library to prevent redundant API calls.

This module provides a singleton cache that stores fetched data across
all endpoints to avoid making the same API calls multiple times.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union
from loguru import logger
import threading
import time

class PyPSXCache:
    """Singleton cache for PyPSX data to prevent redundant API calls."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(PyPSXCache, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._cache = {}
            self._cache_timestamps = {}
            self._cache_duration = 300  # 5 minutes cache duration
            self._initialized = True
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached data if it exists and is not expired."""
        if key not in self._cache:
            return None
        
        # Check if cache is expired
        if time.time() - self._cache_timestamps[key] > self._cache_duration:
            logger.debug(f"Cache expired for {key}, removing")
            del self._cache[key]
            del self._cache_timestamps[key]
            return None
        
        logger.debug(f"Cache hit for {key}")
        return self._cache[key]
    
    def set(self, key: str, value: Any) -> None:
        """Set cached data with current timestamp."""
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()
        logger.debug(f"Cached data for {key}")
    
    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.info("Cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'cache_size': len(self._cache),
            'cached_keys': list(self._cache.keys()),
            'cache_duration': self._cache_duration
        }

# Global cache instance
_cache = PyPSXCache()

def get_cached_market_watch() -> Optional[pd.DataFrame]:
    """Get cached market watch data."""
    return _cache.get('market_watch')

def set_cached_market_watch(data: pd.DataFrame) -> None:
    """Cache market watch data."""
    _cache.set('market_watch', data)

def get_cached_compliant_listings() -> Optional[pd.DataFrame]:
    """Get cached compliant listings data."""
    return _cache.get('compliant_listings')

def set_cached_compliant_listings(data: pd.DataFrame) -> None:
    """Cache compliant listings data."""
    _cache.set('compliant_listings', data)

def get_cached_non_compliant_listings() -> Optional[pd.DataFrame]:
    """Get cached non-compliant listings data."""
    return _cache.get('non_compliant_listings')

def set_cached_non_compliant_listings(data: pd.DataFrame) -> None:
    """Cache non-compliant listings data."""
    _cache.set('non_compliant_listings', data)

def get_cached_combined_listings() -> Optional[pd.DataFrame]:
    """Get cached combined listings data."""
    return _cache.get('combined_listings')

def set_cached_combined_listings(data: pd.DataFrame) -> None:
    """Cache combined listings data."""
    _cache.set('combined_listings', data)

def clear_pypsx_cache() -> None:
    """Clear all PyPSX cache."""
    _cache.clear()

def get_cache_stats() -> Dict[str, Any]:
    """Get PyPSX cache statistics."""
    return _cache.get_stats()
