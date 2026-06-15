"""
CSV metrics writer for PyTrader live paper trading.

Automatically creates and appends to CSV files for detailed metrics storage.
Works seamlessly with pip-installed PyTrader without requiring codebase access.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional



class MetricsCSVWriter:
    """
    Writes trading metrics to CSV files automatically.
    
    Creates append-only CSV files with headers, suitable for Excel/Colab analysis.
    """
    
    def __init__(self, metrics_path: Optional[Path] = None, trades_path: Optional[Path] = None):
        """
        Initialize CSV writer.
        
        Args:
            metrics_path: Path to metrics CSV (default: pytrader_metrics.csv in cwd)
            trades_path: Path to trades CSV (default: pytrader_trades.csv in cwd)
        """
        self.metrics_path = metrics_path or Path("pytrader_metrics.csv")
        self.trades_path = trades_path or Path("pytrader_trades.csv")
        
        # Ensure paths are absolute
        if not self.metrics_path.is_absolute():
            self.metrics_path = Path.cwd() / self.metrics_path
        if not self.trades_path.is_absolute():
            self.trades_path = Path.cwd() / self.trades_path
        
        # Initialize CSV files if they don't exist
        self._init_metrics_csv()
        self._init_trades_csv()
    
    def _init_metrics_csv(self) -> None:
        """Initialize metrics CSV with headers if it doesn't exist."""
        if not self.metrics_path.exists():
            headers = [
                "timestamp",
                "equity",
                "cash",
                "positions_value",
                "total_return_pct",
                "daily_return_pct",
                "session_return_pct",
                "cumulative_return_pct",
                "unrealized_pnl",
                "realized_pnl",
                "sharpe_ratio",
                "session_sharpe_ratio",
                "sortino_ratio",
                "max_drawdown_pct",
                "drawdown",  # Alias for max_drawdown_pct (spec requirement)
                "volatility_pct",
                "win_loss_ratio",
                "exposure_pct",
                "turnover_pct",
                "total_fees",
                "avg_slippage_bps",
                "positions_snapshot",  # Optional JSON snapshot (spec requirement)
            ]
            with open(self.metrics_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
    
    def _init_trades_csv(self) -> None:
        """Initialize trades CSV with headers if it doesn't exist."""
        if not self.trades_path.exists():
            headers = [
                "timestamp",
                "symbol",
                "side",
                "quantity",
                "price",
                "realized_pnl",
                "cash_after",
                "equity_after",
                "slippage_value",
            ]
            with open(self.trades_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
    
    def write_metrics(
        self,
        timestamp: datetime,
        equity: float,
        cash: float,
        positions_value: float,
        metrics: Dict[str, Any],
        total_fees: float = 0.0,
        avg_slippage_bps: float = 0.0,
            positions_snapshot: Optional[List[Dict[str, Any]]] = None,
        ) -> None:
        """
        Write cycle metrics to CSV.
        
        Args:
            timestamp: Cycle timestamp
            equity: Total portfolio equity
            cash: Available cash
            positions_value: Total positions value
            metrics: TradeMetrics dict
            total_fees: Total fees for cycle
            avg_slippage_bps: Average slippage in basis points
            positions_snapshot: Optional list of position dicts for JSON snapshot
        """
        # Format positions snapshot as JSON string (optional)
        positions_json = ""
        if positions_snapshot:
            try:
                positions_json = json.dumps(positions_snapshot)
            except:
                positions_json = ""
        
        drawdown = metrics.get("max_drawdown_pct", 0.0)  # drawdown is same as max_drawdown_pct
        session_return = metrics.get("session_return_pct", metrics.get("daily_return_pct", 0.0))
        cumulative_return = metrics.get("cumulative_return_pct", metrics.get("total_return_pct", 0.0))
        session_sharpe = metrics.get("session_sharpe_ratio", "")
        lifetime_sharpe = metrics.get("sharpe_ratio")
        
        row = [
            timestamp.isoformat(),
            equity,
            cash,
            positions_value,
            metrics.get("total_return_pct", 0.0),
            metrics.get("daily_return_pct", 0.0),
            session_return,
            cumulative_return,
            metrics.get("unrealized_pnl", 0.0),
            metrics.get("realized_pnl", 0.0),
            lifetime_sharpe if lifetime_sharpe is not None else "",
            session_sharpe if session_sharpe not in {"", None} else "",
            metrics.get("sortino_ratio") or "",
            metrics.get("max_drawdown_pct", 0.0),
            drawdown,  # drawdown column (spec requirement)
            metrics.get("volatility_pct") or "",
            metrics.get("win_loss_ratio") or "",
            metrics.get("exposure_pct", 0.0),
            metrics.get("turnover_pct", 0.0),
            total_fees,
            avg_slippage_bps,
            positions_json,  # Optional JSON snapshot (spec requirement)
        ]
        
        with open(self.metrics_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(row)
    
    def write_trade(
        self,
        timestamp: datetime,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        realized_pnl: float = 0.0,
        cash_after: float = 0.0,
        equity_after: float = 0.0,
        slippage_value: Optional[float] = None,
    ) -> None:
        """
        Write trade to CSV.
        
        Args:
            timestamp: Trade timestamp
            symbol: Stock symbol
            side: BUY or SELL
            quantity: Number of shares
            price: Execution price
            realized_pnl: Realized PnL from this trade
            cash_after: Cash balance after this trade
            equity_after: Equity value after this trade
        """
        row = [
            timestamp.isoformat(),
            symbol,
            side,
            quantity,
            price,
            realized_pnl,
            cash_after,
            equity_after,
            slippage_value if slippage_value is not None else "",
        ]
        
        with open(self.trades_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(row)
    
    def write_positions(
        self,
        timestamp: datetime,
        positions: List[Dict[str, Any]],
        prices: Dict[str, float],
    ) -> None:
        """
        Write positions snapshot to CSV.
        
        Creates/updates a positions CSV file with per-position details.
        """
        positions_path = self.metrics_path.parent / f"{self.metrics_path.stem}_positions.csv"
        
        # Initialize positions CSV if it doesn't exist
        if not positions_path.exists():
            headers = [
                "timestamp",
                "symbol",
                "qty",
                "avg_price",
                "market_price",
                "unrealized_pnl",
                "market_value",
            ]
            with open(positions_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
        
        # Write position data
        for pos in positions:
            symbol = pos.get('symbol', '')
            qty = pos.get('qty', 0)
            avg_cost = pos.get('avg_cost', 0.0)
            current_price = prices.get(symbol, avg_cost)
            unrealized_pnl = (current_price - avg_cost) * qty
            market_value = current_price * qty
            
            row = [
                timestamp.isoformat(),
                symbol,
                qty,
                avg_cost,
                current_price,
                unrealized_pnl,
                market_value,
            ]
            
            with open(positions_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(row)


__all__ = ["MetricsCSVWriter"]

