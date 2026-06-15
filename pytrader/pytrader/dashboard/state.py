from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class DashboardState:
    """
    Thread-safe in-memory store for dashboard telemetry.

    The trading engine pushes CycleReport payloads through the in-process
    telemetry hook. The dashboard server reads snapshots from this store
    to hydrate HTTP/WebSocket responses without blocking the strategy loop.
    """

    def __init__(
        self,
        bot_id: str,
        symbols: Sequence[str],
        *,
        log_dir: Optional[Path] = None,
        load_from_disk: bool = True,
        max_points: int = 768,
        max_trades: int = 300,
    ) -> None:
        self.bot_id = bot_id
        self.symbols = [sym.upper() for sym in symbols]
        self._lock = Lock()
        self._equity_history: Deque[Dict[str, Any]] = deque(maxlen=max_points)
        self._trade_history: Deque[Dict[str, Any]] = deque(maxlen=max_trades)
        self._latest_snapshot: Dict[str, Any] = self._build_initial_snapshot()
        self.updated_at: Optional[str] = None
        
        # Load historical data from disk if enabled
        if load_from_disk and log_dir:
            self._hydrate_from_disk(log_dir)

    def ingest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply a new cycle payload and return a snapshot safe for JSON serialization.
        """
        with self._lock:
            snapshot = self._update_snapshot_locked(payload)
            self._latest_snapshot = snapshot
            self.updated_at = snapshot["updated_at"]
            return deepcopy(snapshot)

    def snapshot(self) -> Dict[str, Any]:
        """
        Return the latest dashboard snapshot.
        """
        with self._lock:
            return deepcopy(self._latest_snapshot)

    def _build_initial_snapshot(self) -> Dict[str, Any]:
        timestamp = _utcnow_iso()
        base = {
            "bot": {"id": self.bot_id, "symbols": self.symbols},
            "status": "initializing",
            "equity": 0.0,
            "cash": 0.0,
            "positions_value": 0.0,
            "positions": [],
            "prices": {},
            "metrics": {},
            "recent_trades": [],
            "last_cycle": {
                "timestamp": timestamp,
                "trades": [],
                "batches": [],
                "total_fees": 0.0,
                "avg_slippage_bps": 0.0,
            },
            "equity_history": [],
            "updated_at": timestamp,
        }
        return base

    def _update_snapshot_locked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = payload.get("timestamp") or _utcnow_iso()
        if isinstance(timestamp, datetime):
            timestamp = timestamp.isoformat()

        equity = _to_float(payload.get("equity"))
        cash = _to_float(payload.get("cash"))
        positions_value = _to_float(payload.get("positions_value"))
        status = payload.get("status", "ok")

        prices = {
            symbol: _to_float(value)
            for symbol, value in (payload.get("prices") or {}).items()
        }

        positions = self._normalise_positions(payload.get("positions") or [], prices, equity)
        new_trades = self._normalise_trades(payload.get("trades") or [])
        metrics = self._normalise_metrics(payload.get("metrics") or {})

        self._equity_history.append(
            {
                "timestamp": timestamp,
                "equity": equity,
                "cash": cash,
                "positions_value": positions_value,
            }
        )

        recent_trades = self._recent_trades()

        snapshot = {
            "bot": {"id": self.bot_id, "symbols": self.symbols},
            "status": status,
            "equity": equity,
            "cash": cash,
            "positions_value": positions_value,
            "positions": positions,
            "prices": prices,
            "metrics": metrics,
            "recent_trades": recent_trades,
            "last_cycle": {
                "timestamp": timestamp,
                "trades": new_trades,
                "batches": payload.get("batches") or [],
                "total_fees": _to_float(payload.get("total_fees")),
                "avg_slippage_bps": _to_float(payload.get("avg_slippage_bps")),
            },
            "equity_history": list(self._equity_history),
            "updated_at": timestamp,
        }
        return snapshot

    def _normalise_positions(
        self,
        positions: Iterable[Dict[str, Any]],
        prices: Dict[str, float],
        equity: float,
    ) -> List[Dict[str, Any]]:
        normalised: List[Dict[str, Any]] = []
        for position in positions:
            symbol = position.get("symbol") or position.get("ticker")
            if not symbol:
                continue
            qty = _to_int(position.get("qty") or position.get("quantity"))
            avg_cost = _to_float(position.get("avg_cost") or position.get("avg_price"))
            current_price = _to_float(
                position.get("current_price") or prices.get(symbol) or avg_cost
            )
            market_value = current_price * qty
            unrealized = _to_float(position.get("unrealized_pnl"))
            if unrealized == 0.0:
                unrealized = (current_price - avg_cost) * qty
            allocation_pct = 0.0
            if equity > 0:
                allocation_pct = (market_value / equity) * 100.0
            normalised.append(
                {
                    "symbol": symbol,
                    "qty": qty,
                    "avg_cost": avg_cost,
                    "current_price": current_price,
                    "market_value": market_value,
                    "unrealized_pnl": unrealized,
                    "allocation_pct": allocation_pct,
                }
            )
        return normalised

    def _normalise_trades(self, trades: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalised: List[Dict[str, Any]] = []
        for trade in trades:
            ts = trade.get("timestamp") or _utcnow_iso()
            if isinstance(ts, datetime):
                ts = ts.isoformat()
            record = {
                "timestamp": ts,
                "symbol": trade.get("symbol"),
                "side": (trade.get("side") or "").upper(),
                "quantity": _to_int(trade.get("quantity") or trade.get("qty")),
                "price": _to_float(trade.get("price")),
                "cost": _to_float(trade.get("cost")),
                "pnl_realized": _to_float(trade.get("pnl_realized")),
                "commission": _to_float(trade.get("commission")),
                "note": trade.get("note", ""),
            }
            normalised.append(record)
            self._trade_history.append(record)
        return normalised

    def _recent_trades(self, limit: int = 60) -> List[Dict[str, Any]]:
        if not self._trade_history:
            return []
        snapshot = list(self._trade_history)[-limit:]
        return list(reversed(snapshot))

    def _normalise_metrics(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        clean: Dict[str, Any] = {}
        for key, value in metrics.items():
            clean[key] = _to_float(value) if isinstance(value, (int, float)) else value
        return clean
    
    def _hydrate_from_disk(self, log_dir: Path) -> None:
        """
        Restore equity history and trades from disk.
        
        This enables the dashboard to show historical data even when
        the bot is not actively running.
        """
        from .state_loader import SessionStateLoader
        
        try:
            loader = SessionStateLoader(self.bot_id, log_dir)
            historical_data = loader.load_latest_session()
            
            # Restore equity history
            equity_history = historical_data.get("equity_history", [])
            for point in equity_history:
                self._equity_history.append(point)
            
            # Restore trade history
            trades = historical_data.get("trades", [])
            for trade in trades[:60]:  # Limit to recent trades
                self._trade_history.append(trade)
            
            # Restore latest snapshot if available
            snapshot = historical_data.get("snapshot", {})
            if snapshot.get("equity", 0) > 0:
                self._latest_snapshot = snapshot
                self.updated_at = snapshot.get("updated_at")
        
        except Exception as e:
            # If loading fails, just continue with empty state
            # Don't crash the dashboard
            import logging
            logging.getLogger("pytrader.dashboard").warning(
                f"Failed to load historical data: {e}"
            )


