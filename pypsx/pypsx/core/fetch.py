"""
Backward compatibility shim for core.fetch module.

This module provides compatibility for endpoints that haven't been migrated yet.
It redirects to the new core.fetchers module.
"""

from typing import Optional, Dict, Any
from bs4 import BeautifulSoup
from .fetchers import fetch_html as _fetch_html, fetch_json as _fetch_json


def get_html(url: str) -> Optional[BeautifulSoup]:
    """
    Fetch HTML content from URL (backward compatibility).
    
    Args:
        url: URL to fetch
        
    Returns:
        BeautifulSoup object or None if failed
        
    Note:
        This is a compatibility wrapper around core.fetchers.fetch_html()
    """
    try:
        html = _fetch_html(url)
        if html:
            return BeautifulSoup(html, "html.parser")
        return None
    except Exception:
        return None


def get_json(url: str) -> Optional[Dict[str, Any]]:
    """
    Fetch JSON content from URL (backward compatibility).
    
    Args:
        url: URL to fetch
        
    Returns:
        JSON data as dict or None if failed
        
    Note:
        This is a compatibility wrapper around core.fetchers.fetch_json()
    """
    try:
        return _fetch_json(url)
    except Exception:
        return None
