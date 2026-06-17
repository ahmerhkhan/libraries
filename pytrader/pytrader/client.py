"""Dual-endpoint HTTP client for pyPSX trading and telemetry."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
import warnings
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import httpx

from .auth import BotAuthSession
from .telemetry import TelemetryClient


class _AttrDict(dict):
    """Dictionary with attribute-style access for Alpaca-like ergonomics."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class TradingClient(TelemetryClient):
    """
    pyPSX convenience client for reads, telemetry, and order submission.

    Recommended usage:
        client = TradingClient(
            api_key="PKXXXXXXXXXXXXXXXXXX",
            secret_key="SKXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
            paper=True,
        )

    Legacy usage remains supported:
        client = PyTrader(bot_id="alpha", api_token="legacy-token")
    """

    def __init__(
        self,
        *,
        account_id: Optional[str] = None,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: Optional[bool] = None,
        user_id: Optional[str] = None,
        bot_id: Optional[str] = None,
        api_token: Optional[str] = None,
        backend_url: Optional[str] = None,
        base_url: Optional[str] = None,
        bot_label: Optional[str] = None,
        timeout: float = 30.0,
        use_jwt_auth: Optional[bool] = None,
        mode: str = "PAPER",
        bearer_jwt: Optional[str] = None,
    ) -> None:
        if account_id and bot_id:
            warnings.warn(
                "bot_id is ignored when account_id is provided. Prefer account_id-only initialization.",
                DeprecationWarning,
                stacklevel=2,
            )
        super().__init__(
            bot_id=bot_id,
            api_token=api_token,
            account_id=account_id,
            api_key=api_key,
            secret_key=secret_key,
            backend_url=backend_url,
            base_url=base_url,
            bot_label=bot_label,
            timeout=timeout,
            user_id=user_id,
            use_jwt_auth=use_jwt_auth,
            mode=mode,
            paper=paper,
            bearer_jwt=bearer_jwt,
        )
        self._reader = httpx.Client(timeout=timeout)
        self._commission_rate_pct: Optional[float] = None

    @classmethod
    def from_env(
        cls,
        *,
        paper: bool = True,
        account_id: Optional[str] = None,
        timeout: float = 30.0,
    ) -> "TradingClient":
        """
        Create a TradingClient from environment variables.

        Required env vars:
        - PYPSX_API_KEY_ID
        - PYPSX_API_SECRET_KEY
        """
        api_key = os.getenv("PYPSX_API_KEY_ID")
        secret_key = os.getenv("PYPSX_API_SECRET_KEY")
        if not api_key or not secret_key:
            raise ValueError(
                "Missing API credentials in environment. "
                "Set PYPSX_API_KEY_ID and PYPSX_API_SECRET_KEY."
            )
        return cls(
            account_id=account_id,
            api_key=api_key,
            secret_key=secret_key,
            paper=paper,
            timeout=timeout,
        )

    def close(self) -> None:
        super().close()
        self._reader.close()

    def _require_bot_scope(self, target_bot_id: Optional[str] = None) -> str:
        resolved = target_bot_id if target_bot_id is not None else self.bot_id
        if not resolved:
            raise ValueError(
                "This method is bot-scoped and is not available for live-brokerage. "
                "Use account-aware methods like get_portfolio_valuation(), get_orders(), or get_account_config()."
            )
        return resolved

    def get_portfolio(self, bot_id: Optional[str] = None) -> Dict[str, Any]:
        target = self._require_bot_scope(bot_id)
        return self._get(f"/portfolio/{target}")

    def get_account(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Alpaca-style convenience helper.

        Returns a dict with stable keys: account_id, mode, cash, equity, buying_power.
        """
        resolved_account_id = account_id or self.account_id
        config = self.get_account_config(resolved_account_id)
        valuation = self.get_portfolio_valuation(account_id=resolved_account_id)
        cash = float(valuation.get("cash", 0.0) or 0.0)
        equity = float(valuation.get("equity", 0.0) or 0.0)
        return _AttrDict({
            "account_id": resolved_account_id,
            "mode": config.get("mode", self.mode),
            "cash": cash,
            "equity": equity,
            "buying_power": cash,
            "can_trade": bool(config.get("can_trade", True)),
            "restricted": bool(config.get("restricted", False)),
        })

    def get_portfolio_valuation(
        self,
        *,
        account_id: Optional[str] = None,
        refresh: bool = True,
        mode: Optional[str] = None,
        bot_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "account_id": account_id or self.account_id,
            "refresh": refresh,
        }
        if mode:
            params["mode"] = mode.upper()
        if bot_id is not None:
            params["bot_id"] = bot_id
        return self._get("/portfolio/valuation", params=params)

    def get_positions(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        data = self._get("/positions", params={"account_id": account_id or self.account_id})
        return data.get("positions", [])

    def get_orders(
        self,
        *,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"account_id": account_id or self.account_id, "limit": limit}
        if status:
            params["status"] = status
        data = self._get("/orders", params=params)
        return data.get("orders", [])

    def get_account_config(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        return self._get("/account/config", params={"account_id": account_id or self.account_id})

    def get_fundamentals(self, symbol: str) -> Dict[str, Any]:
        """Return fundamentals for a PSX symbol: pe_ratio, dividend_yield, market_cap, free_float, etc."""
        sym = str(symbol).strip().upper()
        return self._get(f"/market/fundamentals/{sym}")

    def get_dividends(self, symbol: str) -> List[Dict[str, Any]]:
        """Return dividend history for a PSX symbol: year, amount, ex_date, payment_date, record_date."""
        sym = str(symbol).strip().upper()
        result = self._get(f"/market/dividends/{sym}")
        if isinstance(result, dict):
            return result.get("dividends", [])
        return result if isinstance(result, list) else []

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Return the latest live price snapshot for a PSX symbol.

        Fields: symbol, current, price, change, change_pct, volume, high, low, bid, ask.
        Data is sourced from the PSX live feed (Redis/AHL); updated every few seconds during market hours.
        """
        sym = str(symbol).strip().upper()
        return self._get(f"/market/snapshot/{sym}")

    def get_market_depth(self, symbol: str) -> Dict[str, Any]:
        """
        Return the latest L2 order book snapshot for a PSX symbol.

        Fields: symbol, bids (list of {price, qty, orders}), asks (list of {price, qty, orders}).
        Returns empty bids/asks outside market hours or if the live feed is not running.
        """
        sym = str(symbol).strip().upper()
        return self._get(f"/market/depth/{sym}")

    def get_recent_trades(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Return recent trade ticks for a PSX symbol from the live feed.

        Each tick dict contains: price, volume, timestamp, and side where available.
        Returns an empty list outside market hours or if the live feed is not running.
        """
        sym = str(symbol).strip().upper()
        result = self._get(f"/market/trades/{sym}", params={"limit": limit})
        return result.get("trades", [])

    def _get_ws_token(self) -> str:
        """
        Return an api_token suitable for WebSocket ?token= auth.

        When using api_key + secret_key, exchanges them for a ws-compatible token via
        GET /auth/sdk-token.  Result is cached for the lifetime of this client instance.
        """
        cached = getattr(self, "_ws_token_cache", None)
        if cached:
            return cached
        if self.api_token:
            self._ws_token_cache = self.api_token
            return self.api_token
        try:
            result = self._get("/auth/sdk-token")
            token = str(result.get("token") or "")
            if token:
                self._ws_token_cache = token
                return token
        except Exception:
            pass
        return ""

    def get_commission_rate(self) -> float:
        """Return the user's commission rate percentage, fetching from backend once and caching."""
        if self._commission_rate_pct is None:
            try:
                result = self._get("/user/commission_rate")
                self._commission_rate_pct = float(result.get("commission_rate", 0.15))
            except Exception:
                self._commission_rate_pct = 0.15
        return self._commission_rate_pct

    def add_funds(
        self,
        amount: float,
        *,
        account_id: Optional[str] = None,
        bot_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add paper cash via backend cash endpoints.

        This is intended for self-topup in paper-trading tests.
        Hard-blocks LIVE accounts client-side (backend also enforces).
        """
        resolved_account_id = account_id or self.account_id
        if not resolved_account_id:
            raise ValueError("account_id is required for add_funds()")

        cfg = self.get_account_config(resolved_account_id)
        if str(cfg.get("mode") or "").upper() == "LIVE":
            raise PermissionError("add_funds() is disabled for LIVE accounts.")

        resolved_bot_id = bot_id
        if not resolved_bot_id:
            if str(resolved_account_id).startswith("paper-bot:"):
                resolved_bot_id = str(resolved_account_id).split("paper-bot:", 1)[1]
            elif str(resolved_account_id) == "paper-main":
                resolved_bot_id = "manual"
            else:
                resolved_bot_id = self.bot_id or "manual"

        resolved_bot_id = str(resolved_bot_id)
        if not resolved_bot_id:
            raise ValueError("Unable to resolve bot_id for add_funds()")

        payload = {
            "amount": float(amount),
            "account_id": resolved_account_id,
        }
        return self._post_json(f"/bots/{resolved_bot_id}/cash/add", payload)

    def get_performance(self, bot_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        target = self._require_bot_scope(bot_id)
        return self._get(f"/performance/{target}", params={"limit": limit})

    def get_trades(self, bot_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        target = self._require_bot_scope(bot_id)
        return self._get(f"/trades/{target}", params={"limit": limit})

    def get_logs(self, bot_id: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
        target = self._require_bot_scope(bot_id)
        return self._get(f"/logs/{target}", params={"limit": limit})

    def get_symbols(self) -> List[Dict[str, Any]]:
        response = self._get("/symbols")
        return response.get("symbols", [])

    def get_intraday(self, symbol: str, days: int = 2) -> List[Dict[str, Any]]:
        response = self._get(f"/intraday/{symbol.upper()}", params={"days": days})
        return response.get("data", [])

    def get_historical(
        self,
        symbol: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
        interval: str = "1d",
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"interval": interval}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        response = self._get(f"/historical/{symbol.upper()}", params=params)
        return response.get("data", [])

    def list_bots(self) -> List[Dict[str, Any]]:
        data = self._get("/bots")
        return data.get("bots", [])

    def create_bot(
        self,
        *,
        bot_id: str,
        bot_label: Optional[str] = None,
        strategy_name: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        cycle_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "bot_id": bot_id,
            "bot_label": bot_label,
            "strategy_name": strategy_name,
            "symbols": symbols,
            "cycle_minutes": cycle_minutes,
        }
        return self._post_json("/bots", payload)

    def create_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        limit_price: Optional[float] = None,
        commission_rate: Optional[float] = None,
        status: Optional[str] = None,
        queued_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        warnings.warn(
            "client.create_order() is deprecated. Use place_manual_order(), which is account-aware.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price,
            limit_price=limit_price,
            commission_rate=commission_rate,
        )

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        limit_price: Optional[float] = None,
        commission_rate: Optional[float] = None,
        idempotency_key: Optional[str] = None,
        account_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submits an order with a unique `Idempotency-Key` header by default so rapid
        duplicate posts do not violate PostgreSQL ON CONFLICT constraints on the backend.
        Pass an explicit `idempotency_key` only when intentionally retrying the same logical order.
        """
        payload: Dict[str, Any] = {
            "account_id": account_id or self.account_id,
            "mode": self.mode,
            "bot_id": self.bot_id,
            "symbol": symbol.upper(),
            "side": side.upper(),
            "quantity": quantity,
            "order_type": order_type.upper(),
            "source": source or "Algo",
        }
        if price is not None:
            payload["price"] = price
        if stop_price is not None:
            payload["stop_price"] = stop_price
        if limit_price is not None:
            payload["limit_price"] = limit_price
        if commission_rate is not None:
            payload["commission_rate"] = commission_rate
            print(f"[pyPSX] {payload['side']} {payload['symbol']} — commission rate: {commission_rate}%")
        else:
            # No override — backend applies the algo global default (0.15%).
            # Do NOT fall back to the web-profile rate; algo and website tracks are separate.
            print(f"[pyPSX] {payload['side']} {payload['symbol']} — commission rate: backend default (0.15%)")
        # Always send an idempotency key by default.
        # This prevents accidental duplicate-key collisions during rapid-fire orders.
        key = (idempotency_key or "").strip() or str(uuid.uuid4())
        headers = {"Idempotency-Key": key}
        result = self._post_json("/orders", payload, headers=headers)
        if "order_id" not in result and "id" in result:
            result["order_id"] = result["id"]
        return result

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """Fetch the current state of an order by its ID."""
        return self._get(f"/orders/{order_id}")

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel a queued or open order. Returns the updated order dict."""
        result = self._post_json(f"/orders/{order_id}/cancel", {})
        return result

    def place_manual_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        limit_price: Optional[float] = None,
        commission_rate: Optional[float] = None,
        idempotency_key: Optional[str] = None,
        account_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price,
            limit_price=limit_price,
            commission_rate=commission_rate,
            idempotency_key=idempotency_key,
            account_id=account_id,
            source=source,
        )

    def get_order_executions(
        self,
        *,
        since: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"bot_id": self._require_bot_scope(), "limit": limit}
        if since:
            params["since"] = since
        data = self._get("/order_executions", params=params)
        return data.get("executions", [])

    async def stream_ticker(
        self,
        symbol: str,
        on_tick: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Connect to ``/ws/marketdata/{symbol}`` and yield real-time tick dicts.

        Each yielded dict has the compact firehose format::

            {"symbol": "HBL", "p": 281.47, "b": 281.30, "a": 281.64, "v": 1500, "t": "..."}

        Usage — async for loop::

            async for tick in api.stream_ticker("SYS"):
                print(tick["p"])  # latest price

        Usage — callback style::

            async for tick in api.stream_ticker("SYS", on_tick=lambda t: print(t)):
                pass

        Args:
            symbol: PSX ticker symbol (case-insensitive).
            on_tick: Optional synchronous callback invoked for every received tick.
        """
        try:
            import websockets  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "websockets is required for stream_ticker(). "
                "Install it with: pip install websockets"
            ) from exc

        sym = symbol.strip().upper()
        base = self.base_url.rstrip("/")
        if base.startswith("https://"):
            ws_base = base.replace("https://", "wss://", 1)
        elif base.startswith("http://"):
            ws_base = base.replace("http://", "ws://", 1)
        else:
            ws_base = base
        url = f"{ws_base}/ws/marketdata/{sym}"

        # Prefer direct API key auth (no token exchange round-trip).
        if self.api_key and self.secret_key:
            url = f"{url}?api_key={self.api_key}&secret_key={self.secret_key}"
        else:
            token = self._get_ws_token()
            if token:
                url = f"{url}?token={token}"

        reconnect_delay = 1.0
        max_delay = 60.0

        while True:
            try:
                async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
                    reconnect_delay = 1.0  # reset backoff on successful connect
                    async for raw in ws:
                        try:
                            tick: Dict[str, Any] = json.loads(raw)
                        except Exception:
                            continue
                        # Respond to server-side manual ping messages
                        if tick.get("type") == "ping":
                            try:
                                await ws.send(json.dumps({"type": "pong", "timestamp": tick.get("timestamp")}))
                            except Exception:
                                pass
                            continue
                        if on_tick is not None:
                            try:
                                on_tick(tick)
                            except Exception:
                                pass
                        yield tick
            except Exception:
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if getattr(self, "_bot_session", None):
            session: BotAuthSession = self._bot_session  # type: ignore[assignment]
            response = session.handle_401_and_retry("GET", url, params=params)
        elif getattr(self, "_static_headers", None):
            request_headers = dict(self._static_headers)
            request_headers.update(self._mode_headers())
            response = self._reader.get(url, params=params, headers=request_headers)
        else:
            request_headers = {"X-PyTrader-Token": self.api_token}
            request_headers.update(self._mode_headers())
            response = self._reader.get(url, params=params, headers=request_headers)
        response.raise_for_status()
        return response.json()

    def _post_json(
        self,
        path: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if getattr(self, "_bot_session", None):
            session: BotAuthSession = self._bot_session  # type: ignore[assignment]
            response = session.handle_401_and_retry("POST", url, json=payload, headers=headers)
        elif getattr(self, "_static_headers", None):
            request_headers = dict(self._static_headers)
            request_headers.update(self._mode_headers())
            if headers:
                request_headers.update(headers)
            response = self._reader.post(url, json=payload, headers=request_headers)
        else:
            request_headers = {"X-PyTrader-Token": self.api_token}
            request_headers.update(self._mode_headers())
            if headers:
                request_headers.update(headers)
            response = self._reader.post(url, json=payload, headers=request_headers)
        response.raise_for_status()
        return response.json()

PyPSXClient = TradingClient
PyTrader = TradingClient



