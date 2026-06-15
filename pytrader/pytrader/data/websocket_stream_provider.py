"""
WebSocket Stream Provider - Pure WebSocket streaming for LIVE mode only.

Connects to our backend WebSocket (/ws/market), receives synthesized ticks/prices,
aggregates ticks to bars, and emits bar close events for strategy execution.

NOTE: The legacy upstream psx-terminal websocket protocol is no longer used.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

import websockets
from websockets.client import WebSocketClientProtocol

from .bar_aggregator import AggregatedBar, BarAggregator, TickData
from .data_mode import TradingMode
from ..config import settings

logger = logging.getLogger(__name__)


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _tick_from_backend_tick(symbol: str, payload: Dict[str, Any], *, ts: Optional[datetime] = None) -> TickData:
    """
    Convert backend tick payload to SDK TickData (for bar aggregation).
    `price` / `last` map to mid; `bid` / `ask` carry the synthetic book when present.
    """
    sym = _normalize_symbol(symbol)
    price = payload.get("last") or payload.get("price") or payload.get("current") or 0.0
    volume = payload.get("volume") or 0
    if ts is None:
        ts = datetime.now(timezone.utc)
    high = payload.get("high")
    low = payload.get("low")
    bid_v = payload.get("bid")
    ask_v = payload.get("ask")
    bid_f = float(bid_v) if bid_v is not None and bid_v != "" else None
    ask_f = float(ask_v) if ask_v is not None and ask_v != "" else None
    return TickData(
        symbol=sym,
        price=float(price or 0.0),
        volume=int(volume or 0),
        timestamp=ts,
        high=float(high) if high is not None else None,
        low=float(low) if low is not None else None,
        bid=bid_f,
        ask=ask_f,
    )


class _WebSocketShard:
    """
    Internal class representing a single WebSocket connection shard.
    Handles a subset of symbols to respect the 20-subscription limit.
    """
    
    def __init__(
        self, 
        shard_id: int, 
        symbols: List[str], 
        websocket_url: str,
        message_handler: Callable[[Dict[str, Any]], Any],
        *,
        token: Optional[str] = None,
        enable_virtual_ticks: bool = False,
    ):
        self.shard_id = shard_id
        self.symbols = symbols
        self.websocket_url = websocket_url
        self.message_handler = message_handler
        self.token = token
        self.enable_virtual_ticks = enable_virtual_ticks
        
        self.ws: Optional[WebSocketClientProtocol] = None
        self.client_id: Optional[str] = None
        self.running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.subscriptions: Set[str] = set()
        self._last_price: Dict[str, float] = {}
        self._last_ts: Dict[str, datetime] = {}
    
    async def start(self) -> None:
        """Start this shard's connection."""
        try:
            logger.info(f"Shard {self.shard_id}: Connecting to {self.websocket_url}")
            url = self.websocket_url
            tok = (self.token or "").strip()
            if tok:
                joiner = "&" if "?" in url else "?"
                url = f"{url}{joiner}token={tok}"
            self.ws = await websockets.connect(url, ping_interval=30)
            self.running = True
            logger.info(f"Shard {self.shard_id}: ✅ Connected (backend market WS)")
            
            # Start receive loop
            self.task = asyncio.create_task(self._receive_loop())
            
        except Exception as e:
            self.running = False
            logger.error(f"Shard {self.shard_id}: Connection failed: {e}")
            raise e

    async def stop(self) -> None:
        """Stop this shard."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        if self.ws:
            await self.ws.close()
            self.ws = None
            logger.info(f"Shard {self.shard_id}: Disconnected")

    async def _emit_virtual_ticks(self, symbol: str, new_price: float, new_ts: datetime) -> None:
        """
        Optional interpolator: synthesize micro-ticks between backend pulses.
        """
        if not self.enable_virtual_ticks:
            return
        sym = _normalize_symbol(symbol)
        prev_price = self._last_price.get(sym)
        prev_ts = self._last_ts.get(sym)
        if prev_price is None or prev_ts is None:
            return
        dt = (new_ts - prev_ts).total_seconds()
        if dt < 1.5:
            return
        # ~1 virtual step per second between backend pulses (cap 10) for smoother algos.
        steps = max(0, min(10, int(dt) - 1))
        if steps <= 0:
            return
        for i in range(1, steps + 1):
            p = prev_price + (new_price - prev_price) * (i / (steps + 1))
            ts = prev_ts + (new_ts - prev_ts) * (i / (steps + 1))
            await self.message_handler(
                {
                    "type": "market_ticks",
                    "ticks": {sym: {"symbol": sym, "price": p, "last": p, "timestamp_ms": int(ts.timestamp() * 1000), "source": "virtual"}},
                }
            )

    async def _receive_loop(self) -> None:
        """Receive loop for this shard."""
        try:
            async for message in self.ws:  # type: ignore[union-attr]
                try:
                    data = json.loads(message)
                    
                    # Handle heartbeats locally
                    if data.get("type") == "ping":
                        await self.ws.send(json.dumps({
                            "type": "pong", 
                            "timestamp": data.get("timestamp")
                        }))
                        continue

                    # Interpolate if backend only sent prices (including unified `hb` pulse).
                    if data.get("type") == "hb":
                        data = {
                            "type": "market_prices",
                            "prices": data.get("prices") or {},
                            "bid": data.get("bid") or {},
                            "ask": data.get("ask") or {},
                        }

                    if data.get("type") == "market_prices":
                        prices = data.get("prices") or {}
                        if isinstance(prices, dict):
                            now_ts = datetime.now(timezone.utc)
                            for sym, px in prices.items():
                                try:
                                    await self._emit_virtual_ticks(str(sym), float(px), now_ts)
                                except Exception:
                                    continue
                            for sym, px in prices.items():
                                try:
                                    su = _normalize_symbol(str(sym))
                                    self._last_price[su] = float(px)
                                    self._last_ts[su] = now_ts
                                except Exception:
                                    continue

                    # Forward other messages to main provider
                    await self.message_handler(data)
                    
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    logger.error(f"Shard {self.shard_id}: Message error: {e}", exc_info=True)
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Shard {self.shard_id}: Loop error: {e}")
            self.running = False
            # We could trigger a reconnect here or notify parent


class WebSocketStreamProvider:
    """
    Pure WebSocket streaming provider for LIVE paper trading mode.
    
    ARCHITECTURE: This is the ONLY data source for live prices in LIVE mode.
    - Real-time ticks from psx-terminal WebSocket → aggregated bars
    - NO REST endpoints for live prices
    - NO historical data fetching (user must provide via seed_historical_bars())
    
    Features:
    - Connection sharding (multiple WS connections to bypass 20-sub limit)
    - Tick aggregation to OHLCV bars
    - Bar close events for strategy execution
    - Fail-fast reliability
    
    Data Source Separation:
    - get_bar_history(): Returns bars accumulated from WebSocket ticks since connection start
      - Starts with 0 bars when connection begins
      - Builds history over time as bars close
      - Includes bars seeded via seed_historical_bars() (from pypsx library)
    - seed_historical_bars(): For user-provided historical data from pypsx library
      - pypsx library must be installed separately: pip install pypsx
      - Used ONLY for indicator initialization (e.g., RSI needs 14 bars)
      - NOT for live prices - live prices come ONLY from WebSocket
    
    IMPORTANT: Do NOT use pypsx library for live prices!
    - pypsx has 15-minute delay - NOT suitable for live trading
    - Live prices MUST come from psx-terminal WebSocket (this provider)
    - pypsx is ONLY for historical data, research, backtesting
    
    Example with pypsx library (separate installation):
        # User installs pypsx separately (NOT integrated into SDK)
        # pip install pypsx
        
        from pypsx import get_intraday  # User's separate installation
        from pytrader.data import WebSocketStreamProvider
        
        provider = WebSocketStreamProvider(symbols=['OGDC'], interval_minutes=15)
        
        # User loads historical data from their separate pypsx installation
        historical_data = get_intraday('OGDC', lookback_days=2)
        
        # Seed the aggregator with historical bars (for indicator initialization)
        provider.seed_historical_bars('OGDC', historical_data)
        
        # Now strategy can calculate indicators immediately
        # Live prices will come from WebSocket, not pypsx
    """
    
    # API Limit: Max 20 subscriptions per connection
    MAX_SUBS_PER_SHARD = 20
    # API Limit: Max 5 connections per IP
    MAX_SHARDS = 5
    
    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        interval_minutes: int = 15,
        max_bar_history: int = 500,
        websocket_url: Optional[str] = None,
        token: Optional[str] = None,
        mode: TradingMode = TradingMode.LIVE,
    ):
        if mode not in (TradingMode.LIVE, TradingMode.WARM_START):
            raise ValueError(f"WebSocketStreamProvider only supports LIVE and WARM_START modes, got {mode}")
        
        self.user_symbols: Set[str] = set(s.upper() for s in (symbols or []))
        self.interval_minutes = interval_minutes
        self.token = token
        # Default to backend market websocket.
        if websocket_url:
            self.websocket_url = websocket_url
        else:
            ws_base = settings.resolve_backend_ws_base(paper=True)
            self.websocket_url = f"{ws_base}/ws/market"
        self.mode = mode

        self.enable_virtual_ticks = str(os.getenv("PYTRADER_VIRTUAL_TICKS", "1")).strip().lower() in {"1", "true", "yes", "on"}
        
        # Sharding management
        self._shards: List[_WebSocketShard] = []
        self._running: bool = False
        
        # Aggregation and state
        self._aggregator = BarAggregator(interval_minutes=interval_minutes, max_history=max_bar_history)
        self._bar_close_callbacks: List[Callable[[AggregatedBar], None]] = []
        self._error_callbacks: List[Callable[[Exception], None]] = []
        self._latest_prices: Dict[str, float] = {}
        self._mtm_marks: Dict[str, float] = {}
        self._raw_tick_callbacks: List[Callable[[TickData], None]] = []
        
        # Verify limits
        if len(self.user_symbols) > self.MAX_SHARDS * self.MAX_SUBS_PER_SHARD:
            logger.warning(
                f"Symbol count ({len(self.user_symbols)}) exceeds max capacity "
                f"({self.MAX_SHARDS * self.MAX_SUBS_PER_SHARD}). Some symbols may not be subscribed."
            )
        
        logger.info(f"WebSocketStreamProvider initialized: mode={mode}, symbols={len(self.user_symbols)}")
    
    def on_bar_close(self, callback: Callable[[AggregatedBar], None]) -> None:
        self._bar_close_callbacks.append(callback)

    def on_raw_tick(self, callback: Callable[[TickData], None]) -> None:
        """Fires on every backend or virtual tick (mid in `tick.price`, optional `bid`/`ask`)."""
        self._raw_tick_callbacks.append(callback)
    
    def on_error(self, callback: Callable[[Exception], None]) -> None:
        self._error_callbacks.append(callback)

    def get_mtm_prices(self) -> Dict[str, float]:
        """Bid-side marks for long equity MTM (aligned with backend paper valuation)."""
        return dict(self._mtm_marks)

    def add_symbols(self, symbols: List[str]) -> None:
        # TODO: Implement dynamic add with re-sharding if needed
        # For now, simplistic implementation
        new_symbols = set(s.upper() for s in symbols) - self.user_symbols
        if new_symbols:
            logger.warning("Dynamic symbol addition not fully supported in sharded mode yet. Restart recommended.")
            self.user_symbols.update(new_symbols)

    async def start(self) -> None:
        """Initialize shards and start streaming."""
        if self._running:
            return
            
        self._running = True
        all_symbols = list(self.user_symbols)
        
        # Backend WS has no upstream sub limits; use a single shard.
        num_shards = 1
        logger.info(f"Starting backend market WebSocket for {len(all_symbols)} symbols")
        
        try:
            for i in range(num_shards):
                shard_symbols = all_symbols
                shard = _WebSocketShard(
                    shard_id=i,
                    symbols=shard_symbols,
                    websocket_url=self.websocket_url,
                    message_handler=self._handle_shard_message,
                    token=self.token,
                    enable_virtual_ticks=self.enable_virtual_ticks,
                )
                self._shards.append(shard)
                
                # Stagger connections slightly to avoid rate limits
                await shard.start()
                await asyncio.sleep(0.1)
                
        except Exception as e:
            await self.stop()
            raise ConnectionError(f"Failed to start WebSocket shards: {e}") from e

    async def stop(self) -> None:
        """Stop all shards."""
        self._running = False
        stop_tasks = [shard.stop() for shard in self._shards]
        if stop_tasks:
            await asyncio.gather(*stop_tasks)
        self._shards.clear()
        logger.info("All WebSocket shards stopped")

    async def _handle_shard_message(self, data: Dict[str, Any]) -> None:
        """Central message handler for all shards."""
        msg_type = data.get("type")
        
        if msg_type == "market_ticks":
            await self._handle_backend_ticks(data)
        elif msg_type == "market_prices":
            await self._handle_backend_prices(data)
        elif msg_type == "error":
            error_msg = data.get("message", "Unknown error")
            logger.error(f"WebSocket error from shard: {error_msg}")
            # If critical, could notify error callbacks

    async def _push_tick(self, tick: TickData) -> None:
        if not tick.symbol or tick.price is None:
            return
        self._latest_prices[tick.symbol] = float(tick.price)
        if tick.bid is not None and float(tick.bid) > 0:
            self._mtm_marks[tick.symbol] = float(tick.bid)
        elif float(tick.price) > 0:
            from .paper_spread import synthetic_bid_ask_from_last

            b, _ = synthetic_bid_ask_from_last(float(tick.price))
            self._mtm_marks[tick.symbol] = b
        completed_bar = self._aggregator.add_tick(tick)
        if completed_bar:
            logger.info(f"📊 Bar closed: {completed_bar.symbol} @ {completed_bar.timestamp}")
            for callback in self._bar_close_callbacks:
                try:
                    callback(completed_bar)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
        for callback in self._raw_tick_callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.error(f"Raw tick callback error: {e}")

    async def _handle_backend_ticks(self, data: Dict[str, Any]) -> None:
        ticks = data.get("ticks") or {}
        if not isinstance(ticks, dict):
            return
        for symbol, payload in ticks.items():
            if not isinstance(payload, dict):
                continue
            ts_ms = payload.get("timestamp_ms")
            ts = None
            if ts_ms is not None:
                try:
                    ts = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
                except Exception:
                    ts = None
            tick = _tick_from_backend_tick(str(symbol), payload, ts=ts)
            if tick.price <= 0:
                continue
            await self._push_tick(tick)

    async def _handle_backend_prices(self, data: Dict[str, Any]) -> None:
        prices = data.get("prices") or {}
        if not isinstance(prices, dict):
            return
        bids = data.get("bid") if isinstance(data.get("bid"), dict) else {}
        asks = data.get("ask") if isinstance(data.get("ask"), dict) else {}
        now_ts = datetime.now(timezone.utc)
        for symbol, px in prices.items():
            try:
                price = float(px)
            except Exception:
                continue
            if price <= 0:
                continue
            sym_u = _normalize_symbol(str(symbol))
            bid_f = float(bids.get(symbol) or bids.get(sym_u) or 0.0)
            ask_f = float(asks.get(symbol) or asks.get(sym_u) or 0.0)
            if bid_f <= 0 or ask_f <= 0:
                from .paper_spread import synthetic_bid_ask_from_last

                bid_f, ask_f = synthetic_bid_ask_from_last(price)
            tick = TickData(
                symbol=sym_u,
                price=price,
                volume=0,
                timestamp=now_ts,
                high=price,
                low=price,
                bid=bid_f,
                ask=ask_f,
            )
            await self._push_tick(tick)

    def get_latest_prices(self, symbols: Optional[List[str]] = None) -> Dict[str, float]:
        if symbols:
            return {s: self._latest_prices.get(s.upper()) for s in symbols if s.upper() in self._latest_prices}
        return self._latest_prices.copy()
    
    def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Get latest price for a single symbol.
        
        Convenience method for single symbol lookups.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Latest price or None if not available
        """
        return self._latest_prices.get(symbol.upper())
    
    def get_bar_history(self, symbol: str, bars: Optional[int] = None) -> Any:
        """
        Get bar history from WebSocket aggregator.
        
        ARCHITECTURE: Returns bars from WebSocket ticks + any seeded historical bars.
        - Starts with 0 bars when connection begins (unless seeded)
        - Builds history over time as bars close from WebSocket
        - Includes bars seeded via seed_historical_bars() (from pypsx library)
        
        IMPORTANT: This does NOT fetch historical data automatically.
        - Historical data must be provided by user via seed_historical_bars()
        - User must install pypsx library separately: pip install pypsx
        - pypsx is NOT integrated into SDK - it's a separate, optional dependency
        
        Args:
            symbol: Symbol to get history for
            bars: Number of bars to return (default: all available)
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
            Empty DataFrame if no bars accumulated yet (and none seeded)
        """
        return self._aggregator.get_history(symbol, bars)
    
    def seed_historical_bars(
        self, 
        symbol: str, 
        historical_data: List[Dict[str, Any]],
        interval_minutes: Optional[int] = None
    ) -> None:
        """
        Seed aggregator with historical bars from pypsx library (separate installation).
        
        ARCHITECTURE: This is for indicator initialization ONLY, NOT for live prices.
        - Historical data comes from user's separate pypsx installation
        - pypsx library is NOT integrated into SDK - user must install separately
        - Used ONLY for indicator calculations (e.g., RSI needs 14 bars)
        - Live prices come ONLY from WebSocket (this provider)
        
        This allows strategies to calculate indicators immediately without waiting
        for bars to accumulate from WebSocket (e.g., RSI needs 14 bars = 3.5 hours
        with 15-min bars).
        
        IMPORTANT: 
        - pypsx library must be installed separately: pip install pypsx
        - This method does NOT fetch data - it only seeds what you provide
        - Do NOT use pypsx for live prices (it has 15-min delay)
        - Live prices MUST come from WebSocket (this provider)
        
        Args:
            symbol: Symbol to seed bars for
            historical_data: List of dicts from pypsx.get_intraday() with keys:
                          - timestamp/Date: datetime or timestamp
                          - open/Open: float
                          - high/High: float  
                          - low/Low: float
                          - close/Close/price: float
                          - volume/Volume: int
            interval_minutes: Bar interval (default: uses provider's interval)
            
        Example:
            # User installs pypsx separately (NOT part of SDK)
            # pip install pypsx
            
            from pypsx import get_intraday  # User's separate installation
            
            # Load historical data from pypsx
            data = get_intraday('OGDC', lookback_days=2)
            
            # Seed aggregator (for indicator initialization)
            provider.seed_historical_bars('OGDC', data)
            
            # Now strategy can calculate indicators immediately
            # Live prices will come from WebSocket, not pypsx
        """
        if interval_minutes is None:
            interval_minutes = self.interval_minutes
        
        # Convert historical data to AggregatedBar objects
        bars = []
        for record in historical_data:
            # Handle different column name formats from pypsx
            ts = record.get('timestamp') or record.get('Date') or record.get('ts')
            if isinstance(ts, str):
                from dateutil import parser
                ts = parser.parse(ts)
            
            open_price = record.get('open') or record.get('Open')
            high = record.get('high') or record.get('High')
            low = record.get('low') or record.get('Low')
            close = record.get('close') or record.get('Close') or record.get('price')
            volume = record.get('volume') or record.get('Volume') or 0
            
            if not all([ts, open_price, high, low, close]):
                continue
            
            bar = AggregatedBar(
                symbol=symbol.upper(),
                timestamp=ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts)),
                open=float(open_price),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=int(volume),
                trades=0
            )
            bars.append(bar)
        
        # Seed the aggregator
        self._aggregator.seed_history(symbol.upper(), bars)
        logger.info(
            f"✅ Seeded {len(bars)} historical bars for {symbol} from pypsx library "
            f"(separate installation). Strategy can now evaluate immediately."
        )
    
    @property
    def is_connected(self) -> bool:
        return self._running and any(s.running for s in self._shards)


__all__ = ["WebSocketStreamProvider"]
