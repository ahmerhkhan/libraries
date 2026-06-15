"""
Market hours service - wraps backend API with caching and fallback.
This is the recommended way to check market hours in SDK code.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional, Dict, Any

from .market_hours import PSXMarketHours
from ..config import settings


class MarketHoursResponse:
    """Response from market hours service."""
    
    def __init__(self, data: Dict[str, Any]):
        self.is_open: bool = data.get("is_open", False)
        self.status: str = data.get("status", "CLS")
        self.status_text: str = data.get("status_text", "Market Closed")
        self.timestamp: str = data.get("timestamp", "")
        self.is_weekend: bool = data.get("is_weekend", False)
        self.can_trade: bool = data.get("can_trade", False)
        self.can_paper_trade: bool = data.get("can_paper_trade", False)
        self.is_pre_market: bool = data.get("is_pre_market", False)
        self.is_post_market: bool = data.get("is_post_market", False)
        self.next_market_open: Optional[datetime] = self._parse_datetime(data.get("next_market_open"))
        self.session_start: Optional[datetime] = self._parse_datetime(data.get("session_start"))
        self.session_end: Optional[datetime] = self._parse_datetime(data.get("session_end"))
    
    @staticmethod
    def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str)
        except Exception:
            return None


class MarketHoursService:
    """
    Service for checking market hours via backend API.
    
    Features:
    - Backend-first approach (PSX Terminal real-time data)
    - 5-minute cache to reduce API calls
    - Fallback to local PSXMarketHours if backend unavailable
    """
    
    def __init__(
        self,
        backend_url: Optional[str] = None,
        api_token: Optional[str] = None,
        cache_ttl_seconds: int = 300,  # 5 minutes
    ):
        """
        Initialize market hours service.
        
        Args:
            backend_url: Backend API URL (default: from settings)
            api_token: API token for backend auth (default: from settings)
            cache_ttl_seconds: Cache TTL in seconds (default: 300 = 5 minutes)
        """
        self.backend_url = backend_url or getattr(settings, "backend_url", None)
        self.api_token = api_token or getattr(settings, "api_token", None)
        self.cache_ttl = cache_ttl_seconds
        
        # Cache
        self._cache: Optional[MarketHoursResponse] = None
        self._cache_time: float = 0.0
        
        # Fallback flag
        self._using_fallback = False
    
    def get_status(self, force_refresh: bool = False) -> MarketHoursResponse:
        """
        Get current market status.
        
        Args:
            force_refresh: Skip cache and fetch fresh data
        
        Returns:
            Market hours response with comprehensive status
        """
        now = time.time()
        
        # Check cache
        if not force_refresh and self._cache and (now - self._cache_time) < self.cache_ttl:
            return self._cache
        
        # Try backend first
        if self.backend_url and self.api_token:
            try:
                import httpx
                
                response = httpx.get(
                    f"{self.backend_url}/market/status",
                    headers={"X-PyTrader-Token": self.api_token},
                    timeout=5.0
                )
                response.raise_for_status()
                data = response.json()
                
                result = MarketHoursResponse(data)
                self._cache = result
                self._cache_time = now
                self._using_fallback = False
                return result
            except Exception:
                # Fall through to local fallback
                pass
        
        # Fallback to local calculation
        try:
            from zoneinfo import ZoneInfo
            current_time = datetime.now(ZoneInfo("Asia/Karachi"))
        except Exception:
            current_time = datetime.now()
        
        data = {
            "is_open": PSXMarketHours.is_market_open(current_time),
            "status": PSXMarketHours.get_trading_status(current_time),
            "status_text": "Local Calculation",
            "timestamp": current_time.isoformat(),
            "is_weekend": PSXMarketHours.is_weekend(current_time),
            "can_trade": PSXMarketHours.can_start_trading(current_time),
            "can_paper_trade": PSXMarketHours.can_paper_trade(current_time),
            "is_pre_market": PSXMarketHours.is_pre_market(current_time),
            "is_post_market": PSXMarketHours.is_post_market(current_time),
            "next_market_open": PSXMarketHours.get_next_market_open(current_time).isoformat(),
        }
        
        result = MarketHoursResponse(data)
        self._cache = result
        self._cache_time = now
        self._using_fallback = True
        return result
    
    def is_market_open(self) -> bool:
        """Check if market is currently open."""
        return self.get_status().is_open
    
    def can_trade_now(self) -> bool:
        """Check if trading is allowed now (accounting for data delays)."""
        return self.get_status().can_trade
    
    def can_paper_trade_now(self) -> bool:
        """Check if paper trading is allowed now."""
        return self.get_status().can_paper_trade
    
    def is_using_fallback(self) -> bool:
        """Check if service is using local fallback (backend unavailable)."""
        return self._using_fallback


# Global singleton instance
_global_service: Optional[MarketHoursService] = None


def get_market_hours_service() -> MarketHoursService:
    """Get or create global market hours service instance."""
    global _global_service
    if _global_service is None:
        _global_service = MarketHoursService()
    return _global_service
