"""
HTTP request handler for PyPSX library.

DEPRECATED: This module is deprecated. Use core.fetchers instead.

This module is kept for backward compatibility only.
All new code should use core.fetchers.fetch_html() and core.fetchers.fetch_json().
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Literal, Any, Optional, Union
from io import StringIO
from .cache import cache_get, cache_set
from .errors import PSXHTTPError, PSXTimeoutError


_SESSION: Optional[requests.Session] = None


def _session() -> requests.Session:
    """Get or create a requests session with retry logic and browser-like headers."""
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    
    s = requests.Session()
    
    # Improved retry configuration with better backoff for PSX API
    retry = Retry(
        total=3,
        backoff_factor=1.0,  # Increased from 0.5 for more aggressive backoff
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    
    # Reduced pool size to avoid overwhelming the server
    adapter = HTTPAdapter(max_retries=retry, pool_connections=5, pool_maxsize=5)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    
    # Browser-like headers to prevent connection rejection
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://dps.psx.com.pk/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    })
    
    _SESSION = s
    return s


def get(url: str, kind: Literal["json", "text"] = "json", timeout: float = 20.0, ttl: Optional[float] = None) -> Any:
    """
    DEPRECATED: Use core.fetchers.fetch_html() or core.fetchers.fetch_json() instead.
    
    Make a GET request.
    
    Args:
        url: URL to fetch
        kind: Response type - "json" or "text"
        timeout: Request timeout in seconds
        ttl: Cache TTL in seconds (optional)
        
    Returns:
        Response content as text or JSON
    """
    from .fetchers import fetch_html, fetch_json
    
    if kind == "json":
        return fetch_json(url, timeout=timeout, ttl=ttl)
    else:
        return fetch_html(url, timeout=timeout, ttl=ttl)


def post(url: str, data: dict, kind: Literal["json", "text"] = "text", timeout: float = 20.0, ttl: Optional[float] = None) -> Any:
    """
    DEPRECATED: Use core.fetchers.fetch_post() instead.
    
    Make a POST request with data payload.
    
    Args:
        url: URL to POST to
        data: Dictionary to send as form data
        kind: Response type - "json" or "text" (default: "text")
        timeout: Request timeout in seconds
        ttl: Cache TTL in seconds (optional, use carefully with POST)
        
    Returns:
        Response content as text or JSON
    """
    from .fetchers import fetch_post
    return fetch_post(url, data, timeout=timeout, ttl=ttl, kind=kind)


def fetch_data(url: str, timeout: float = 10.0, ttl: Optional[float] = None) -> Union[dict, list, Any]:
    """
    DEPRECATED: Use core.fetchers.fetch_html() or core.fetchers.fetch_json() instead.
    
    Robust endpoint fetching that tries JSON first, then falls back to HTML parsing.
    
    Args:
        url: URL to fetch
        timeout: Request timeout in seconds
        ttl: Cache TTL in seconds (optional)
        
    Returns:
        JSON data (dict/list) if endpoint returns JSON, or list of DataFrames if HTML
    """
    from .fetchers import fetch_json, fetch_html
    import pandas as pd
    
    try:
        return fetch_json(url, timeout=timeout, ttl=ttl)
    except (ValueError, TypeError):
        # Fallback to HTML parsing
        html = fetch_html(url, timeout=timeout, ttl=ttl)
        return pd.read_html(StringIO(html))
