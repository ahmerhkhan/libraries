"""
LiveFeed — clean blocking/async interface for real-time PSX market data.

Usage::

    from pytrader import LiveFeed

    feed = LiveFeed(api_key="PK_xxx", secret_key="spsx...", symbols=["OGDC", "HBL"])
    feed.on_tick(lambda tick: print(tick.symbol, tick.price))
    feed.start()          # blocks until Ctrl+C
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List, Optional

from .data.websocket_client import PSXWebSocketClient, TickData
from .config import settings

logger = logging.getLogger(__name__)


class LiveFeed:
    """
    Real-time market data feed for PSX symbols.

    Connects to `/ws/market` using your API key + secret (no token exchange step).
    Fires registered callbacks for every tick received.

    Example::

        feed = LiveFeed(api_key="PK_xxx", secret_key="spsx...", symbols=["OGDC", "HBL"])
        feed.on_tick(lambda tick: print(tick.symbol, tick.price, tick.bid, tick.ask))
        feed.start()          # blocking — Ctrl+C to stop

    Async usage::

        async def run():
            await feed.start_async()
        asyncio.run(run())
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        token: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        paper: bool = True,
        ws_url: Optional[str] = None,
    ) -> None:
        """
        Args:
            api_key: PYPSX API key (PK_... for paper, AK_... for live). Preferred auth method.
            secret_key: PYPSX secret key paired with api_key.
            token: Pre-exchanged WS token (legacy, use api_key instead).
            symbols: Initial list of symbols to subscribe. Can also call subscribe() later.
            paper: True for paper-api.pypsx.com, False for api.pypsx.com.
            ws_url: Override WebSocket base URL (for custom deployments).
        """
        ws_base = (ws_url or "").strip() or settings.resolve_backend_ws_base(paper=paper)
        url = ws_base if "/ws/" in ws_base else f"{ws_base.rstrip('/')}/ws/market"
        self._client = PSXWebSocketClient(
            ws_url=url,
            token=token,
            api_key=api_key,
            secret_key=secret_key,
            paper=paper,
        )
        self._symbols: List[str] = [s.upper() for s in (symbols or [])]

    def on_tick(self, callback: Callable[[TickData], None]) -> "LiveFeed":
        """Register a callback fired for every tick. Returns self for chaining."""
        self._client.register_tick_callback(callback)
        return self

    def subscribe(self, symbol: str) -> None:
        """Add a symbol to the live feed (works before or after start())."""
        sym = symbol.strip().upper()
        if sym not in self._symbols:
            self._symbols.append(sym)
        self._client.add_symbol(sym)

    def unsubscribe(self, symbol: str) -> None:
        """Remove a symbol from the live feed."""
        sym = symbol.strip().upper()
        self._symbols = [s for s in self._symbols if s != sym]
        self._client.remove_symbol(sym)

    def start(self) -> None:
        """
        Start streaming (blocking). Runs until Ctrl+C or stop() is called from another thread.
        """
        try:
            asyncio.run(self.start_async())
        except KeyboardInterrupt:
            pass

    async def start_async(self) -> None:
        """
        Start streaming (async coroutine). Awaitable from existing event loops.

        Example::

            feed = LiveFeed(api_key=..., secret_key=..., symbols=["OGDC"])
            feed.on_tick(lambda t: print(t.price))
            await feed.start_async()
        """
        ok = await self._client.start(self._symbols or None)
        if not ok:
            raise ConnectionError("LiveFeed: failed to connect to backend WebSocket")
        logger.info("LiveFeed connected — streaming %s", self._symbols or "all symbols")
        try:
            if self._client._receive_task:
                await self._client._receive_task
        except asyncio.CancelledError:
            pass
        finally:
            await self._client.stop()

    async def stop_async(self) -> None:
        """Stop the feed (async)."""
        await self._client.stop()

    def stop(self) -> None:
        """Stop the feed. Safe to call from a separate thread."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._client.stop())
            else:
                loop.run_until_complete(self._client.stop())
        except Exception:
            pass
