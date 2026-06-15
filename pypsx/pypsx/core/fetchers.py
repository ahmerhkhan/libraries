"""
Data fetching module for PyPSX library.

Provides clean, unified functions for fetching HTML and JSON from PSX endpoints.
Follows fetch → parse → expose pattern by returning raw data only.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Any, Optional
import time
import random
from .cache import cache_get, cache_set
from .errors import PSXHTTPError, PSXTimeoutError


_SESSION: Optional[requests.Session] = None
_LAST_REQUEST_TIME: Optional[float] = None
_MIN_REQUEST_INTERVAL = 0.5  # Minimum 500ms between requests to prevent rate limiting


def _throttle_request():
    """Throttle requests to prevent overwhelming the PSX API."""
    global _LAST_REQUEST_TIME
    if _LAST_REQUEST_TIME is not None:
        elapsed = time.time() - _LAST_REQUEST_TIME
        if elapsed < _MIN_REQUEST_INTERVAL:
            sleep_time = _MIN_REQUEST_INTERVAL - elapsed
            # Add small jitter (0-100ms) to prevent thundering herd
            sleep_time += random.uniform(0, 0.1)
            time.sleep(sleep_time)
    _LAST_REQUEST_TIME = time.time()


def _reset_session():
    """Reset the global session (useful when encountering connection errors)."""
    global _SESSION
    if _SESSION:
        try:
            _SESSION.close()
        except Exception:
            pass
    _SESSION = None


def _get_session() -> requests.Session:
    """Get or create a requests session with browser-like headers (no automatic retries)."""
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    
    s = requests.Session()
    
    # Disable automatic retries to prevent hanging requests
    # Requests will fail fast instead of retrying indefinitely
    adapter = HTTPAdapter(
        max_retries=0,
        pool_connections=10,
        pool_maxsize=10,
    )
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    
    # Browser-like headers to prevent connection rejection
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "close",  # Changed from keep-alive to close
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://dps.psx.com.pk/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    })
    
    _SESSION = s
    return s


def fetch_html(url: str, timeout: float = 5.0, ttl: Optional[float] = None) -> str:
    """
    Fetch HTML content from a URL.
    
    Args:
        url: URL to fetch
        timeout: Request timeout in seconds (default: 5.0)
        ttl: Cache TTL in seconds (optional)
        
    Returns:
        Raw HTML text as string
        
    Raises:
        PSXTimeoutError: If request times out
        PSXHTTPError: If HTTP error occurs
    """
    cache_key = f"GET::text::{url}"
    if ttl and ttl > 0:
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
    
    # Throttle requests to prevent rate limiting
    _throttle_request()
    
    try:
        resp = _get_session().get(url, timeout=timeout)
    except requests.exceptions.Timeout as e:
        raise PSXTimeoutError(str(e))
    except requests.RequestException as e:
        raise PSXHTTPError(str(e))
    
    if resp.status_code >= 400:
        raise PSXHTTPError(f"HTTP {resp.status_code} for {url}")
    
    html_text = resp.text
    
    if ttl and ttl > 0:
        cache_set(cache_key, html_text, ttl)
    
    return html_text


def fetch_json(url: str, timeout: float = 5.0, ttl: Optional[float] = None) -> Any:
    """
    Fetch JSON content from a URL.
    
    Args:
        url: URL to fetch
        timeout: Request timeout in seconds (default: 5.0)
        ttl: Cache TTL in seconds (optional)
        
    Returns:
        JSON data as dict, list, or other JSON-serializable type
        
    Raises:
        PSXTimeoutError: If request times out
        PSXHTTPError: If HTTP error occurs
        ValueError: If response is not valid JSON
    """
    cache_key = f"GET::json::{url}"
    if ttl and ttl > 0:
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
    
    # Throttle requests to prevent rate limiting
    _throttle_request()
    
    try:
        resp = _get_session().get(url, timeout=timeout)
    except requests.exceptions.Timeout as e:
        raise PSXTimeoutError(f"PSX API request timed out after {timeout} seconds: {url}")
    except requests.exceptions.ConnectionError as e:
        raise PSXHTTPError(f"PSX API connection error: {e}")
    except requests.RequestException as e:
        raise PSXHTTPError(f"PSX API request failed: {e}")
    
    if resp.status_code >= 400:
        raise PSXHTTPError(f"HTTP {resp.status_code} for {url}")
    
    try:
        json_data = resp.json()
    except ValueError as e:
        raise ValueError(f"Invalid JSON response from {url}: {e}")
    
    if ttl and ttl > 0:
        cache_set(cache_key, json_data, ttl)
    
    return json_data


def fetch_post(url: str, data: dict, timeout: float = 5.0, ttl: Optional[float] = None, kind: str = "text") -> Any:
    """
    Make a POST request with data payload.
    
    Args:
        url: URL to POST to
        data: Dictionary to send as form data
        timeout: Request timeout in seconds (default: 5.0)
        ttl: Cache TTL in seconds (optional, use carefully with POST)
        kind: Response type - "json" or "text" (default: "text")
        
    Returns:
        Response content as text (str) or JSON (dict/list)
        
    Raises:
        PSXTimeoutError: If request times out
        PSXHTTPError: If HTTP error occurs
    """
    # For POST requests, cache key should include the data payload
    cache_key = f"POST::{kind}::{url}::{str(sorted(data.items()))}"
    if ttl and ttl > 0:
        cached = cache_get(cache_key)
        if cached is not None:
            return cached
    
    # Throttle requests to prevent rate limiting
    _throttle_request()
    
    try:
        resp = _get_session().post(url, data=data, timeout=timeout)
    except requests.exceptions.Timeout as e:
        raise PSXTimeoutError(f"PSX API request timed out after {timeout} seconds: {url}")
    except requests.exceptions.ConnectionError as e:
        raise PSXHTTPError(f"PSX API connection error: {e}")
    except requests.RequestException as e:
        raise PSXHTTPError(f"PSX API request failed: {e}")
    
    if resp.status_code >= 400:
        raise PSXHTTPError(f"HTTP {resp.status_code} for {url}")
    
    if kind == "json":
        try:
            value = resp.json()
        except ValueError as e:
            raise ValueError(f"Invalid JSON response from {url}: {e}")
    else:
        value = resp.text
    
    if ttl and ttl > 0:
        cache_set(cache_key, value, ttl)
    
    return value

