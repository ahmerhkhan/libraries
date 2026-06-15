from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

from zoneinfo import ZoneInfo

from .time_utils import now_tz


class InMemoryLogBuffer:
    def __init__(self, max_lines: int = 500) -> None:
        self._buffer: Deque[str] = deque(maxlen=max_lines)

    def append(self, line: str) -> None:
        self._buffer.append(line)

    def list(self, limit: int | None = None) -> List[str]:
        lines = list(self._buffer)
        return lines[-limit:] if limit else lines


log_buffer = InMemoryLogBuffer()
MARKET_TZ = now_tz().tzinfo


def _format_market_time(ts: datetime, fmt: str = "%H:%M %Z") -> str:
    target = ts
    if MARKET_TZ:
        if target.tzinfo is None:
            target = target.replace(tzinfo=MARKET_TZ)
        else:
            target = target.astimezone(MARKET_TZ)
    return target.strftime(fmt)


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("pytrader")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    return logger


logger = setup_logger()


def log_line(message: str) -> None:
    ts = now_tz().strftime("%Y-%m-%d %H:%M:%S %Z")
    logger.info(message)
    log_buffer.append(f"{ts} | {message}")


class StructuredLogBuffer:
    """In-memory buffer for structured (JSON) log events."""

    def __init__(self, max_events: int = 1000) -> None:
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=max_events)

    def append(self, event: Dict[str, Any]) -> None:
        self._buffer.append(event)

    def list(self, *, stream: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        entries = (
            list(self._buffer)
            if stream is None
            else [event for event in self._buffer if event.get("stream") == stream]
        )
        return entries[-limit:] if limit else entries


class LogStream(str, Enum):
    TRADE = "trade"
    PRICE = "price"
    PORTFOLIO = "portfolio"
    SYSTEM = "system"


BackendLogHook = Callable[[str, str, Dict[str, Any], str], None]


class PaperTradingLogger:
    """
    Structured logging helper that keeps four distinct log streams:
    trade, price, portfolio, and system.

    Each event is persisted as JSON (per spec), optionally mirrored to the backend,
    and rendered in a readable terminal format.
    """

    def __init__(
        self,
        *,
        bot_id: str,
        log_root: Path | str | None = None,
        backend_hook: Optional[BackendLogHook] = None,
        in_memory_events: int = 1000,
    ) -> None:
        base = Path(log_root or Path("logs") / "streams").expanduser()
        self.bot_id = bot_id
        self.root = (base / bot_id).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._paths = {
            LogStream.TRADE: self.root / "trade.jsonl",
            LogStream.PRICE: self.root / "price.jsonl",
            LogStream.PORTFOLIO: self.root / "portfolio.jsonl",
            LogStream.SYSTEM: self.root / "system.jsonl",
        }
        self._buffer = StructuredLogBuffer(max_events=in_memory_events)
        self._backend_hook = backend_hook

    # Public helpers -----------------------------------------------------------------
    def tail(self, *, stream: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return recent structured events for dashboards or debug tools."""
        return self._buffer.list(stream=stream, limit=limit)

    # Stream writers -----------------------------------------------------------------
    def log_trade(
        self,
        *,
        timestamp: Optional[datetime] = None,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        cost: float,
        commission: float,
        cash_before: float,
        cash_after: float,
        position_before: int,
        position_after: int,
        realized_pnl: float,
        equity_after: Optional[float] = None,
        unrealized_after: Optional[float] = None,
        slippage_value: Optional[float] = None,
    ) -> None:
        side = side.upper()
        ts = timestamp or now_tz()
        payload = {
            "symbol": symbol.upper(),
            "side": side,
            "quantity": int(quantity),
            "price": float(price),
            "notional": float(cost),
            "commission": float(commission),
            "cash_before": float(cash_before),
            "cash_after": float(cash_after),
            "position_before": int(position_before),
            "position_after": int(position_after),
            "realized_pnl": float(realized_pnl),
        }
        if equity_after is not None:
            payload["equity_after"] = float(equity_after)
        if unrealized_after is not None:
            payload["unrealized_after"] = float(unrealized_after)
        if slippage_value is not None:
            payload["slippage_value"] = float(slippage_value)

        time_label = _format_market_time(ts)
        change_label = "Cost" if side == "BUY" else "Proceeds"
        money_value = float(cost)
        first_line = f"ORDER EXECUTED: {side} {symbol.upper()}"
        details = [
            f"    Qty: {quantity}",
            f"    Price: {price:.2f}",
            f"    {change_label}: {money_value:,.0f}",
            f"    Cash Before: {cash_before:,.0f}",
            f"    Cash After: {cash_after:,.0f}",
            f"    Position Before: {position_before}",
            f"    Position After: {position_after}",
        ]
        if slippage_value is not None:
            details.append(f"    Slippage: {slippage_value:+.2f}")
        equity_line = None
        if equity_after is not None:
            unreal_str = f"{unrealized_after:+,.0f}" if unrealized_after is not None else "n/a"
            equity_line = f"New Position: {position_after} | Cash: {cash_after:,.0f} | Equity: {equity_after:,.0f} | Unrealized: {unreal_str}"

        terminal_lines = [f"{first_line} ({time_label})", *details]
        if equity_line:
            terminal_lines.append(equity_line)

        message = f"{side} {quantity} {symbol.upper()} @ {price:.2f}"
        self._write_event(
            stream=LogStream.TRADE,
            event="order_executed",
            message=message,
            payload=payload,
            level="info",
            terminal_lines=terminal_lines,
            timestamp=ts,
        )

    def log_price_update(
        self,
        *,
        timestamp: Optional[datetime] = None,
        symbol: str,
        old_price: Optional[float],
        new_price: float,
        position_qty: int,
        unrealized_pnl: float,
        equity: float,
    ) -> None:
        ts = timestamp or now_tz()
        payload = {
            "symbol": symbol.upper(),
            "old_price": float(old_price) if old_price is not None else None,
            "new_price": float(new_price),
            "position_qty": int(position_qty),
            "unrealized_pnl": float(unrealized_pnl),
            "equity": float(equity),
        }
        change = (
            float(new_price) - float(old_price)
            if old_price is not None
            else 0.0
        )
        direction = f"{change:+.2f}"
        terminal_lines = [
            f"PRICE UPDATE: {symbol.upper()} -> {new_price:.2f} ({direction})",
            f"    Unrealized P/L: {unrealized_pnl:+,.2f}",
            f"    Portfolio Equity: {equity:,.2f}",
        ]
        message = f"{symbol.upper()} price updated to {new_price:.2f}"
        self._write_event(
            stream=LogStream.PRICE,
            event="price_update",
            message=message,
            payload=payload,
            level="info",
            terminal_lines=terminal_lines,
            timestamp=ts,
        )

    def log_portfolio_snapshot(
        self,
        *,
        timestamp: Optional[datetime] = None,
        cash: float,
        positions_value: float,
        equity: float,
        realized_pnl: float,
        unrealized_pnl: float,
    ) -> None:
        ts = timestamp or now_tz()
        payload = {
            "cash": float(cash),
            "positions_value": float(positions_value),
            "equity": float(equity),
            "realized_pnl": float(realized_pnl),
            "unrealized_pnl": float(unrealized_pnl),
        }
        terminal_lines = [
            f"PORTFOLIO UPDATE ({_format_market_time(ts, '%H:%M:%S %Z')})",
            f"    Cash: {cash:,.2f}",
            f"    Positions Value: {positions_value:,.2f}",
            f"    Total Equity: {equity:,.2f}",
            f"    Unrealized P/L: {unrealized_pnl:+,.2f}",
            f"    Realized P/L: {realized_pnl:+,.2f}",
        ]
        message = f"Portfolio equity {equity:,.2f}"
        self._write_event(
            stream=LogStream.PORTFOLIO,
            event="portfolio_snapshot",
            message=message,
            payload=payload,
            level="info",
            terminal_lines=terminal_lines,
            timestamp=ts,
        )

    def log_system(
        self,
        *,
        event: str,
        message: str,
        level: str = "info",
        context: Optional[Dict[str, Any]] = None,
        timestamp=None,
        terminal_lines: Optional[List[str]] = None,
    ) -> None:
        ts = timestamp or now_tz()
        payload = {"event": event}
        if context:
            payload["context"] = context
        if terminal_lines is None and level in {"warning", "error"}:
            terminal_lines = [f"{level.upper()}: {message}"]
        self._write_event(
            stream=LogStream.SYSTEM,
            event=event,
            message=message,
            payload=payload,
            level=level,
            terminal_lines=terminal_lines,
            timestamp=ts,
        )

    # Internal -----------------------------------------------------------------------
    def _write_event(
        self,
        *,
        stream: LogStream,
        event: str,
        message: str,
        payload: Dict[str, Any],
        level: str,
        terminal_lines: Optional[List[str]],
        timestamp: Optional[datetime] = None,
    ) -> None:
        ts = timestamp or now_tz()
        record = {
            "timestamp": ts.isoformat(),
            "bot_id": self.bot_id,
            "stream": stream.value,
            "event": event,
            "level": level,
            "message": message,
            "payload": payload,
        }
        path = self._paths[stream]
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=self._json_default))
                fh.write("\n")
        except OSError as exc:
            log_line(f"[WARN] Failed to persist {stream.value} log: {exc}")

        self._buffer.append(record)

        if terminal_lines:
            for line in terminal_lines:
                log_line(line)

        if self._backend_hook:
            backend_context = dict(payload)
            backend_context["stream"] = stream.value
            backend_context["event"] = event
            try:
                self._backend_hook(level, message, backend_context, stream.value)
            except Exception as exc:
                log_line(f"[WARN] Failed to push {stream.value} log upstream: {exc}")

    @staticmethod
    def _json_default(obj: Any) -> Any:
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return obj

