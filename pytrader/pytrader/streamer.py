"""
Lightweight market stream: connects to the PyTrader backend `/ws/market` and fires `on_tick`
for each synthesized price pulse (same feed the web UI uses).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List, Optional

from .config import settings
from .data.websocket_client import PSXWebSocketClient, TickData

logger = logging.getLogger(__name__)


class Streamer:
    """
    Example::

        streamer = Streamer(token=os.environ[\"PYTRADER_TOKEN\"])
        streamer.on_tick(lambda t: print(t.symbol, t.price, t.bid, t.ask))

        import asyncio
        asyncio.run(streamer.run())
    """

    def __init__(
        self,
        *,
        token: Optional[str] = None,
        ws_url: Optional[str] = None,
        paper: bool = True,
    ) -> None:
        base = (ws_url or "").strip() or settings.resolve_backend_ws_base(paper=paper)
        url = base if "/ws/" in base else f"{base.rstrip('/')}/ws/market"
        self._client = PSXWebSocketClient(ws_url=url, token=token)

    def on_tick(self, callback: Callable[[TickData], None]) -> None:
        self._client.register_tick_callback(callback)

    async def run(self, symbols: Optional[List[str]] = None) -> None:
        ok = await self._client.start(symbols)
        if not ok:
            raise ConnectionError("Streamer failed to connect to backend WebSocket")
        logger.info("Streamer connected; waiting for backend pulses…")
        try:
            if self._client._receive_task:
                await self._client._receive_task
        except asyncio.CancelledError:
            pass
        finally:
            await self._client.stop()

    async def stop(self) -> None:
        await self._client.stop()
