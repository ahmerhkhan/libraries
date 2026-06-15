"""
Backend WebSocket Client for Real-Time Price Streaming
===========================================================

WebSocket client that connects to the PyTrader backend for real-time price updates.
The backend synthesizes prices from REST (fundamentals + klines) and broadcasts.

Features:
- Real-time tick updates (price, bid, ask, volume)
- Automatic reconnection with exponential backoff
- Subscription management (up to 20 symbols per connection)
- Heartbeat/ping-pong handling
- Thread-safe price caching
- Callback system for price updates

WebSocket Limits:
- 5 connections per IP
- 20 subscriptions per connection
- Total capacity: 100 symbols per IP

Author: PyTrader Team
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


@dataclass
class TickData:
    """Real-time tick data from WebSocket"""
    symbol: str
    price: float
    change: float
    change_percent: float
    volume: int
    trades: int
    high: float
    low: float
    bid: float
    ask: float
    bid_volume: int
    ask_volume: int
    timestamp: datetime
    market_state: str  # PRE, OPN, SUS, CLS
    
    @classmethod
    def from_websocket(cls, data: Dict[str, Any]) -> "TickData":
        """Create TickData from WebSocket tick update"""
        tick = data.get("tick", {})
        return cls(
            symbol=tick.get("s", ""),
            price=float(tick.get("c", 0)),
            change=float(tick.get("ch", 0)),
            change_percent=float(tick.get("pch", 0)) * 100,  # Convert to percentage
            volume=int(tick.get("v", 0)),
            trades=int(tick.get("tr", 0)),
            high=float(tick.get("h", 0)),
            low=float(tick.get("l", 0)),
            bid=float(tick.get("bp", 0)),
            ask=float(tick.get("ap", 0)),
            bid_volume=int(tick.get("bv", 0)),
            ask_volume=int(tick.get("av", 0)),
            timestamp=datetime.fromtimestamp(tick.get("t", time.time() * 1000) / 1000),
            market_state=tick.get("st", "UNKNOWN"),
        )


class PSXWebSocketClient:
    """
    WebSocket client for backend market data streaming.
    
    Connects to backend `/ws/market` and listens for:
      - {"type":"market_ticks","ticks":{SYMBOL:{...}}}
      - {"type":"market_prices","prices":{SYMBOL: float}}
    """
    
    def __init__(
        self,
        *,
        ws_url: Optional[str] = None,
        token: Optional[str] = None,
        market_type: str = "REG",
        auto_reconnect: bool = True,
        heartbeat_interval: float = 30.0,
    ):
        """
        Initialize WebSocket client.
        
        Args:
            ws_url: WebSocket URL
            market_type: Market type to subscribe to (REG, FUT, IDX)
            auto_reconnect: Whether to automatically reconnect on disconnect
            heartbeat_interval: Heartbeat interval in seconds
        """
        # Default to backend websocket base from config.
        if ws_url:
            self.ws_url = ws_url
        else:
            from ..config import settings
            ws_base = settings.resolve_backend_ws_base(paper=True)
            self.ws_url = f"{ws_base}/ws/market"
        self.token = token
        self.market_type = market_type
        self.auto_reconnect = auto_reconnect
        self.heartbeat_interval = heartbeat_interval
        
        # Connection state
        self.ws: Optional[WebSocketClientProtocol] = None
        self.is_connected = False
        self.is_running = False
        self.client_id: Optional[str] = None
        
        # Subscription management
        self.subscribed_symbols: Set[str] = set()
        self.subscription_keys: List[str] = []
        self._subscription_lock = Lock()
        
        # Price cache
        self.tick_cache: Dict[str, TickData] = {}
        self._cache_lock = Lock()
        
        # Callbacks
        self.tick_callbacks: List[Callable[[TickData], None]] = []
        self.connection_callbacks: List[Callable[[bool], None]] = []
        
        # Reconnection backoff
        self.reconnect_delay = 1.0
        self.max_reconnect_delay = 60.0
        
        # Tasks
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        
        logger.info("PSXWebSocketClient initialized: %s", self.ws_url)
    
    async def connect(self) -> bool:
        """
        Connect to WebSocket server.
        
        Returns:
            True if connected successfully
        """
        try:
            logger.info(f"Connecting to {self.ws_url}...")
            
            url = self.ws_url
            tok = (self.token or "").strip()
            if tok:
                joiner = "&" if "?" in url else "?"
                url = f"{url}{joiner}token={tok}"
            self.ws = await websockets.connect(
                url,
                ping_interval=None,  # We handle heartbeat manually
                ping_timeout=None,
            )
            
            self.is_connected = True
            self.reconnect_delay = 1.0  # Reset backoff
            
            logger.info("✅ WebSocket connected")
            
            # Notify connection callbacks
            for callback in self.connection_callbacks:
                try:
                    callback(True)
                except Exception as e:
                    logger.error(f"Connection callback error: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.is_connected = False
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from WebSocket server"""
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        
        self.is_connected = False
        self.client_id = None
        
        # Notify connection callbacks
        for callback in self.connection_callbacks:
            try:
                callback(False)
            except Exception as e:
                logger.error(f"Connection callback error: {e}")
        
        logger.info("WebSocket disconnected")

    def _emit_ticks_from_price_maps(self, data: Dict[str, Any]) -> None:
        """Turn backend `market_prices` / `hb` payloads into TickData (mid + synthetic or explicit bid/ask)."""
        prices = data.get("prices") or {}
        if not isinstance(prices, dict):
            return
        bids = data.get("bid") if isinstance(data.get("bid"), dict) else {}
        asks = data.get("ask") if isinstance(data.get("ask"), dict) else {}
        for sym, px in prices.items():
            symbol = str(sym or "").upper()
            if not symbol:
                continue
            try:
                price_f = float(px)
            except Exception:
                continue
            if price_f <= 0:
                continue
            bid_f = float(bids.get(sym) or bids.get(symbol) or 0.0)
            ask_f = float(asks.get(sym) or asks.get(symbol) or 0.0)
            if bid_f <= 0 or ask_f <= 0:
                from .paper_spread import synthetic_bid_ask_from_last

                bid_f, ask_f = synthetic_bid_ask_from_last(price_f)
            tick_data = TickData(
                symbol=symbol,
                price=price_f,
                change=0.0,
                change_percent=0.0,
                volume=0,
                trades=0,
                high=price_f,
                low=price_f,
                bid=bid_f,
                ask=ask_f,
                bid_volume=0,
                ask_volume=0,
                timestamp=datetime.fromtimestamp(time.time()),
                market_state="UNKNOWN",
            )
            with self._cache_lock:
                self.tick_cache[tick_data.symbol] = tick_data
            for callback in self.tick_callbacks:
                try:
                    callback(tick_data)
                except Exception as e:
                    logger.error(f"Tick callback error: {e}")
    
    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "ping":
                # Respond with pong
                await self._send_pong(data.get("timestamp"))
                
            elif msg_type == "market_ticks":
                ticks = data.get("ticks") or {}
                if isinstance(ticks, dict):
                    for sym, payload in ticks.items():
                        if not isinstance(payload, dict):
                            continue
                        symbol = str(payload.get("symbol") or sym or "").upper()
                        if not symbol:
                            continue
                        price = payload.get("last") or payload.get("price") or payload.get("current") or 0.0
                        if price is None:
                            continue
                        try:
                            price_f = float(price)
                        except Exception:
                            continue
                        if price_f <= 0:
                            continue
                        bid_f = float(payload.get("bid") or 0.0)
                        ask_f = float(payload.get("ask") or 0.0)
                        if bid_f <= 0 or ask_f <= 0:
                            from .paper_spread import synthetic_bid_ask_from_last

                            bid_f, ask_f = synthetic_bid_ask_from_last(price_f)
                        tick_data = TickData(
                            symbol=symbol,
                            price=price_f,
                            change=float(payload.get("change") or 0.0),
                            change_percent=float(payload.get("change_percent") or 0.0),
                            volume=int(payload.get("volume") or 0),
                            trades=int(payload.get("trades") or 0),
                            high=float(payload.get("high") or price_f),
                            low=float(payload.get("low") or price_f),
                            bid=bid_f,
                            ask=ask_f,
                            bid_volume=int(payload.get("bid_volume") or 0),
                            ask_volume=int(payload.get("ask_volume") or 0),
                            timestamp=datetime.fromtimestamp(time.time()),
                            market_state=str(payload.get("market_state") or payload.get("st") or "UNKNOWN"),
                        )
                        with self._cache_lock:
                            self.tick_cache[tick_data.symbol] = tick_data
                        for callback in self.tick_callbacks:
                            try:
                                callback(tick_data)
                            except Exception as e:
                                logger.error(f"Tick callback error: {e}")

            elif msg_type == "market_prices":
                self._emit_ticks_from_price_maps(data)

            elif msg_type == "hb":
                self._emit_ticks_from_price_maps(data)

            elif msg_type == "kline":
                kline_data = data.get("kline", data)
                symbol = data.get("symbol") or kline_data.get("symbol", "")
                if not symbol:
                    return
                
                # Emulate TickData from K-Line
                tick_data = TickData(
                    symbol=symbol.upper(),
                    price=float(kline_data.get("close", 0.0)),
                    change=0.0,
                    change_percent=0.0,
                    volume=int(kline_data.get("volume", 0)),
                    trades=0,
                    high=float(kline_data.get("high", 0.0)),
                    low=float(kline_data.get("low", 0.0)),
                    bid=0.0,
                    ask=0.0,
                    bid_volume=0,
                    ask_volume=0,
                    timestamp=datetime.fromtimestamp(kline_data.get("timestamp", time.time() * 1000) / 1000),
                    market_state="UNKNOWN",
                )
                
                # Update cache
                with self._cache_lock:
                    # preserve change_percent if already in cache
                    existing = self.tick_cache.get(tick_data.symbol)
                    if existing:
                        tick_data.change = existing.change
                        tick_data.change_percent = existing.change_percent
                    self.tick_cache[tick_data.symbol] = tick_data
                
                # Notify callbacks
                for callback in self.tick_callbacks:
                    try:
                        callback(tick_data)
                    except Exception as e:
                        logger.error(f"Tick callback error: {e}")
                        
            elif msg_type == "subscribeResponse":
                request_id = data.get("requestId")
                status = data.get("status")
                subscription_key = data.get("subscriptionKey")
                
                if status == "success":
                    self.subscription_keys.append(subscription_key)
                    logger.info(f"✅ Subscribed: {subscription_key}")
                else:
                    logger.error(f"❌ Subscription failed: {request_id}")
                    
            elif msg_type == "error":
                logger.error(f"WebSocket error message: {data.get('message')}")
                
            else:
                logger.debug(f"Unknown message type: {msg_type}")
                
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON message: {message[:100]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def _send_pong(self, timestamp: int) -> None:
        """Send pong response to ping"""
        if self.ws:
            pong = {"type": "pong", "timestamp": timestamp}
            await self.ws.send(json.dumps(pong))
    
    async def _subscribe_market_data(self) -> None:
        # Deprecated: backend market WS is server-push; no upstream subscriptions.
        return
    
    async def _receive_loop(self) -> None:
        """Main receive loop for WebSocket messages"""
        try:
            while self.is_running and self.ws:
                try:
                    message = await asyncio.wait_for(self.ws.recv(), timeout=60.0)
                    await self._handle_message(message)
                except asyncio.TimeoutError:
                    logger.warning("WebSocket receive timeout (60s)")
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket connection closed")
                    break
                    
        except Exception as e:
            logger.error(f"Error in receive loop: {e}")
        finally:
            await self.disconnect()
            
            # Attempt reconnection if enabled
            if self.auto_reconnect and self.is_running:
                logger.info(f"Attempting reconnection in {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)
                
                # Exponential backoff
                self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
                
                # Reconnect
                if await self.connect():
                    self._receive_task = asyncio.create_task(self._receive_loop())
    
    async def start(self, symbols: Optional[List[str]] = None) -> bool:
        """
        Start WebSocket client.
        
        Args:
            symbols: List of symbols to track (optional, subscribes to all if None)
            
        Returns:
            True if started successfully
        """
        if self.is_running:
            logger.warning("WebSocket client already running")
            return False
        
        self.is_running = True
        
        # Set symbols to track
        if symbols:
            with self._subscription_lock:
                self.subscribed_symbols = {s.upper() for s in symbols}
        
        # Connect
        if not await self.connect():
            self.is_running = False
            return False
        
        # Start receive loop
        self._receive_task = asyncio.create_task(self._receive_loop())
        
        logger.info("WebSocket client started")
        return True
    
    async def stop(self) -> None:
        """Stop WebSocket client"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Cancel tasks
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect
        await self.disconnect()
        
        logger.info("WebSocket client stopped")
    
    def add_symbol(self, symbol: str) -> None:
        """Add a symbol to track"""
        with self._subscription_lock:
            self.subscribed_symbols.add(symbol.upper())
        logger.debug(f"Added symbol: {symbol}")
    
    def remove_symbol(self, symbol: str) -> None:
        """Remove a symbol from tracking"""
        with self._subscription_lock:
            self.subscribed_symbols.discard(symbol.upper())
        
        # Clear from cache
        with self._cache_lock:
            self.tick_cache.pop(symbol.upper(), None)
        
        logger.debug(f"Removed symbol: {symbol}")
    
    def get_tick(self, symbol: str) -> Optional[TickData]:
        """Get latest tick data for a symbol, with REST fallback"""
        with self._cache_lock:
            tick = self.tick_cache.get(symbol.upper())
            if tick is not None:
                return tick

        # Fallback: Seed cache via REST synthesizer if empty
        try:
            from .psx_terminal_service import PSXTerminalService
            if getattr(self, "_rest_service", None) is None:
                self._rest_service = PSXTerminalService()

            price_data = self._rest_service.get_price(symbol.upper())
            
            # Parse timestamp safely
            try:
                ts = datetime.fromisoformat(price_data.get("last_updated"))
                # Strip timezone if present so it doesn't crash existing naive datetime usages, 
                # or keep it if existing schema is timezone-aware.
                # Actually, legacy schema uses naive local time (datetime.fromtimestamp)
                if ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
            except (ValueError, TypeError):
                ts = datetime.now()

            tick = TickData(
                symbol=price_data.get("symbol", symbol.upper()),
                price=price_data.get("price", 0.0),
                change=price_data.get("change", 0.0),
                change_percent=price_data.get("change_percent", 0.0),
                volume=price_data.get("volume", 0),
                trades=0,
                high=price_data.get("high", 0.0),
                low=price_data.get("low", 0.0),
                bid=price_data.get("bid", 0.0),
                ask=price_data.get("ask", 0.0),
                bid_volume=0,
                ask_volume=0,
                timestamp=ts,
                market_state=price_data.get("market_state", "UNKNOWN")
            )
            with self._cache_lock:
                self.tick_cache[symbol.upper()] = tick
            return tick
        except Exception as e:
            logger.error(f"Fallback get_tick failed for {symbol}: {e}")
            return None
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Get latest price for a symbol"""
        tick = self.get_tick(symbol)
        return tick.price if tick else None
    
    def register_tick_callback(self, callback: Callable[[TickData], None]) -> None:
        """Register callback for tick updates"""
        self.tick_callbacks.append(callback)
    
    def register_connection_callback(self, callback: Callable[[bool], None]) -> None:
        """Register callback for connection status changes"""
        self.connection_callbacks.append(callback)
    
    def get_cached_prices(self) -> Dict[str, float]:
        """Get all cached prices as dict"""
        with self._cache_lock:
            return {symbol: tick.price for symbol, tick in self.tick_cache.items()}


# Example usage
if __name__ == "__main__":
    async def main():
        # Create client
        client = PSXWebSocketClient()
        
        # Register callbacks
        def on_tick(tick: TickData):
            print(f"📊 {tick.symbol}: Rs. {tick.price:.2f} ({tick.change_percent:+.2f}%) "
                  f"[Bid: {tick.bid:.2f}, Ask: {tick.ask:.2f}]")
        
        def on_connection(connected: bool):
            status = "Connected" if connected else "Disconnected"
            print(f"🔌 {status}")
        
        client.register_tick_callback(on_tick)
        client.register_connection_callback(on_connection)
        
        # Start with KMI-30 symbols
        symbols = ["OGDC", "HBL", "UBL", "MCB", "PPL"]
        await client.start(symbols)
        
        # Run for 60 seconds
        await asyncio.sleep(60)
        
        # Show cached prices
        print("\n📈 Cached Prices:")
        prices = client.get_cached_prices()
        for symbol, price in prices.items():
            print(f"  {symbol}: Rs. {price:.2f}")
        
        # Stop
        await client.stop()
    
    asyncio.run(main())
