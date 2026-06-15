"""
WebSocket-Enhanced Data Service for PyTrader
=============================================

Provides real-time price data using WebSocket streaming with REST API fallback.
This service can be used as a drop-in replacement for PyPSXService to enable
WebSocket-based price fetching in trading strategies.

Features:
- Real-time WebSocket price streaming from PSX Terminal
- Automatic fallback to REST API if WebSocket unavailable
- Compatible with existing PyPSXService interface
- Sub-second latency for trading decisions
- Zero rate limits (WebSocket-first architecture)

Usage:
    from pytrader.data.websocket_data_service import WebSocketDataService
    
    data_service = WebSocketDataService()
    trader = Trader(
        strategy=MyStrategy(),
        symbols=['OGDC', 'PPL', 'HBL'],
        data_service=data_service  # Use WebSocket-enabled service
    )
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

from .websocket_client import PSXWebSocketClient, TickData
from .pypsx_service import PyPSXService

logger = logging.getLogger(__name__)


class WebSocketDataService(PyPSXService):
    """
    WebSocket-enhanced data service that prioritizes real-time WebSocket prices
    over REST API calls.
    
    Maintains PyPSXService interface but uses WebSocket for current/latest prices,
    falling back to REST only when necessary.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize WebSocket data service with REST fallback."""
        super().__init__(*args, **kwargs)
        
        self.ws_client: Optional[PSXWebSocketClient] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_started = False
        self._subscribed_symbols: set = set()
        
        logger.info("WebSocketDataService initialized (WebSocket-first with REST fallback)")
    
    def ensure_websocket(self, symbols: List[str]) -> None:
        """
        Ensure WebSocket client is running for given symbols.
        
        Args:
            symbols: List of symbols to subscribe to
        """
        if self._ws_started:
            # Add new symbols if needed
            new_symbols = set(s.upper() for s in symbols) - self._subscribed_symbols
            if new_symbols:
                for symbol in new_symbols:
                    if self.ws_client:
                        self.ws_client.add_symbol(symbol)
                self._subscribed_symbols.update(new_symbols)
            return
        
        try:
            # Create WebSocket client
            self.ws_client = PSXWebSocketClient()
            
            # Start WebSocket in background
            self._ws_loop = asyncio.new_event_loop()
            
            def run_ws():
                asyncio.set_event_loop(self._ws_loop)
                self._ws_loop.run_until_complete(
                    self.ws_client.start(symbols=[s.upper() for s in symbols])
                )
                self._ws_loop.run_forever()
            
            import threading
            ws_thread = threading.Thread(target=run_ws, daemon=True)
            ws_thread.start()
            
            self._ws_started = True
            self._subscribed_symbols = set(s.upper() for s in symbols)
            
            logger.info(f"✅ WebSocket client started for {len(symbols)} symbols")
            
        except Exception as e:
            logger.warning(f"Failed to start WebSocket client: {e}. Will use REST API fallback.")
            self.ws_client = None
            self._ws_started = False
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current price with WebSocket priority.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Current price or None if unavailable
        """
        # Try WebSocket first
        if self.ws_client:
            price = self.ws_client.get_price(symbol.upper())
            if price is not None:
                return price
        
        
        # Fallback to REST API (get_market_watch_quote)
        try:
            quote = self.get_market_watch_quote(symbol)
            if quote:
                # Try common keys for current price
                for key in ['current', 'price', 'close', 'last']:
                    val = quote.get(key) or quote.get(key.upper())
                    if val is not None:
                        try:
                            # Handle string price with commas
                            if isinstance(val, str):
                                val = val.replace(',', '')
                            return float(val)
                        except (ValueError, TypeError):
                            continue
            return None
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None
    
    def get_intraday(
        self,
        symbol: str,
        interval: str = "1m",
        limit: Optional[int] = None,
        **kwargs
    ) -> List[Dict]:
        """
        Get intraday data with WebSocket-enhanced latest price.
        """
        # Get historical data from REST API (returns List[Dict])
        # Note: PyPSXService ignores 'interval' and 'limit' but we accept them for compatibility
        data = super().get_intraday(symbol, **kwargs)
        
        # Update latest price with WebSocket if available
        if self.ws_client and data and isinstance(data, list):
            latest_price = self.ws_client.get_price(symbol.upper())
            if latest_price:
                # Update the last candle
                last_candle = data[-1]
                
                # Check key names (could be 'Close' or 'close')
                price_key = 'close' if 'close' in last_candle else 'Close'
                time_key = 'ts' if 'ts' in last_candle else ('time' if 'time' in last_candle else 'Date')
                
                # Update price
                if price_key in last_candle:
                    last_candle[price_key] = latest_price
                    
                # Update timestamp to now
                if time_key in last_candle:
                    last_candle[time_key] = datetime.now()
                
                logger.debug(f"Updated {symbol} latest price with WebSocket: {latest_price}")
        
        return data
            
    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        """
        Get latest prices for multiple symbols with WebSocket priority.
        
        Args:
            symbols: List of symbols
            
        Returns:
            Dictionary mapping symbol to price
        """
        prices = {}
        
        # Ensure WebSocket is running for these symbols
        self.ensure_websocket(symbols)
        
        # Get prices from WebSocket cache
        if self.ws_client:
            ws_prices = self.ws_client.get_cached_prices()
            for symbol in symbols:
                sym_upper = symbol.upper()
                if sym_upper in ws_prices:
                    prices[symbol] = ws_prices[sym_upper]
        
        # Fill missing prices with REST API
        missing_symbols = [s for s in symbols if s not in prices]
        if missing_symbols:
            for symbol in missing_symbols:
                rest_price = self.get_current_price(symbol)
                if rest_price:
                    prices[symbol] = rest_price
        
        return prices
    
    def stop(self) -> None:
        """Stop WebSocket client and cleanup resources."""
        if self.ws_client:
            try:
                if self._ws_loop and self.ws_client.is_running:
                    # Stop WebSocket client
                    asyncio.run_coroutine_threadsafe(
                        self.ws_client.stop(),
                        self._ws_loop
                    ).result(timeout=5)
                logger.info("WebSocket client stopped")
            except Exception as e:
                logger.warning(f"Error stopping WebSocket client: {e}")
            finally:
                self.ws_client = None
                self._ws_started = False


__all__ = ['WebSocketDataService']
