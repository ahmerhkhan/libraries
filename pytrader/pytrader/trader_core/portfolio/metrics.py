"""
Reusable portfolio metrics helpers shared by execution and backtesting engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..utils.risk import (
    calculate_returns,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_volatility,
)
from .service import PortfolioService


@dataclass
class TradeMetrics:
    total_return_pct: float
    daily_return_pct: float
    session_return_pct: float
    cumulative_return_pct: float
    sharpe_ratio: float
    session_sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    volatility_pct: float
    win_loss_ratio: float
    exposure_pct: float
    turnover_pct: float
    cumulative_pnl: float
    sharpe_ratio_available: bool = False
    session_sharpe_ratio_available: bool = False
    sortino_ratio_available: bool = False
    volatility_available: bool = False
    win_loss_ratio_available: bool = False


def compute_portfolio_metrics(
    portfolio: PortfolioService,
    *,
    timestamp: datetime,
    latest_prices: Dict[str, float],
    trades_snapshot: Optional[List[Dict[str, Any]]] = None,
    initial_capital: Optional[float] = None,  # NEW: Original starting capital for accurate total return
) -> Dict[str, Any]:
    if timestamp.tzinfo is None:
        ts_utc = timestamp.replace(tzinfo=timezone.utc)
    else:
        ts_utc = timestamp.astimezone(timezone.utc)

    raw_curve = portfolio.get_equity_curve(limit=500)
    filtered_curve: List[Dict[str, Any]] = []
    for point in raw_curve:
        ts_val = point.get("ts")
        if not ts_val:
            continue
        try:
            point_ts = datetime.fromisoformat(ts_val)
        except ValueError:
            continue
        if point_ts.tzinfo is None:
            point_ts = point_ts.replace(tzinfo=timezone.utc)
        else:
            point_ts = point_ts.astimezone(timezone.utc)
        if point_ts <= ts_utc:
            filtered_curve.append((point_ts, point))

    filtered_curve.sort(key=lambda item: item[0])
    equity_curve = [point for _, point in filtered_curve]

    equities = [point["equity"] for point in equity_curve if point.get("equity") is not None]
    session_equities = [
        point["equity"]
        for point_ts, point in filtered_curve
        if point.get("equity") is not None and point_ts.date() == ts_utc.date()
    ]
    returns = calculate_returns(equities)
    session_returns = calculate_returns(session_equities)
    sharpe = calculate_sharpe_ratio(returns) if returns else None
    sortino = calculate_sortino_ratio(returns) if returns else None
    volatility = calculate_volatility(returns) if returns else None
    sharpe_ratio_value = sharpe if sharpe is not None else 0.0
    sortino_ratio_value = sortino if sortino is not None else 0.0
    volatility_pct_value = round(volatility * 100, 2) if volatility is not None else 0.0

    total_return_pct = 0.0
    if equities:
        # Use initial_capital if provided, otherwise fall back to first equity in curve
        baseline_capital = initial_capital if initial_capital is not None else equities[0]
        if baseline_capital > 0:
            total_return_pct = ((equities[-1] - baseline_capital) / baseline_capital) * 100

    if session_returns:
        daily_return_pct = session_returns[-1] * 100
    else:
        daily_return_pct = returns[-1] * 100 if returns else 0.0

    drawdown_series = session_equities if len(session_equities) >= 2 else equities
    max_drawdown_pct = _max_drawdown_pct(drawdown_series)
    session_return_pct = 0.0
    if len(session_equities) >= 1:
        first_session_equity = session_equities[0]
        last_session_equity = session_equities[-1]
        if first_session_equity > 0:
            session_return_pct = ((last_session_equity - first_session_equity) / first_session_equity) * 100
    session_sharpe = calculate_sharpe_ratio(session_returns) if session_returns else None
    session_sharpe_value = session_sharpe if session_sharpe is not None else 0.0

    trades = trades_snapshot or portfolio.get_trades(limit=500)
    wins = sum(1 for t in trades if t["pnl_realized"] > 0)
    losses = sum(1 for t in trades if t["pnl_realized"] < 0)
    win_loss_ratio: Optional[float] = None
    if wins + losses > 0:
        win_loss_ratio = wins / max(losses, 1)

    summary = portfolio.get_summary()
    positions_summary = _build_positions_summary(summary.positions, latest_prices)
    positions_value = sum(p["market_value"] for p in positions_summary)
    unrealized_total = sum(p["unrealized_pnl"] for p in positions_summary)
    effective_equity = float(summary.cash) + positions_value
    exposure_pct = (positions_value / effective_equity * 100) if effective_equity else 0.0
    # Clamp exposure at 100% max to avoid display overflows from rounding artifacts
    exposure_pct = min(exposure_pct, 100.0)

    turnover_pct = _turnover_pct(trades, effective_equity)
    cumulative_pnl = summary.realized_pnl + unrealized_total
    win_loss_ratio_value = round(win_loss_ratio, 2) if win_loss_ratio is not None else 0.0

    return {
        "timestamp": ts_utc.isoformat(),
        "equity": effective_equity,
        "cash": summary.cash,
        "positions_value": positions_value,
        "realized_pnl": summary.realized_pnl,
        "unrealized_pnl": unrealized_total,
        "session_return_pct": round(session_return_pct, 2),
        "cumulative_return_pct": round(total_return_pct, 2),
        "metrics": TradeMetrics(
            total_return_pct=round(total_return_pct, 2),
            daily_return_pct=round(daily_return_pct, 2),
            session_return_pct=round(session_return_pct, 2),
            cumulative_return_pct=round(total_return_pct, 2),
            sharpe_ratio=sharpe_ratio_value,
            session_sharpe_ratio=session_sharpe_value,
            sortino_ratio=sortino_ratio_value,
            max_drawdown_pct=round(max_drawdown_pct, 2),
            volatility_pct=volatility_pct_value,
            win_loss_ratio=win_loss_ratio_value,
            exposure_pct=round(exposure_pct, 2),
            turnover_pct=round(turnover_pct, 2),
            cumulative_pnl=round(cumulative_pnl, 2),
            sharpe_ratio_available=sharpe is not None,
            session_sharpe_ratio_available=session_sharpe is not None,
            sortino_ratio_available=sortino is not None,
            volatility_available=volatility is not None,
            win_loss_ratio_available=win_loss_ratio is not None,
        ),
        "positions": positions_summary,
        "equity_curve": equity_curve,
    }


def _build_positions_summary(
    positions: List[Dict[str, Any]],
    latest_prices: Dict[str, float],
) -> List[Dict[str, Any]]:
    summary: List[Dict[str, Any]] = []
    for pos in positions:
        qty = pos.get("qty", 0)
        if qty == 0:
            continue
        symbol = pos["symbol"]
        price = latest_prices.get(symbol, pos.get("avg_cost", 0.0))
        market_value = price * qty
        avg_cost = pos.get("avg_cost", 0.0)
        unrealized_pnl = (price - avg_cost) * qty
        summary.append(
            {
                "symbol": symbol,
                "qty": qty,
                "avg_cost": avg_cost,
                "current_price": price,
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl,
            }
        )
    return summary


def _turnover_pct(trades: List[Dict[str, Any]], equity_value: float) -> float:
    if equity_value <= 0 or not trades:
        return 0.0
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    turnover_cash = 0.0
    for trade in trades:
        try:
            ts = datetime.fromisoformat(trade["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
        except ValueError:
            continue
        if ts < cutoff:
            continue
        turnover_cash += abs(trade.get("cost", 0.0))
    return (turnover_cash / equity_value) * 100 if equity_value else 0.0


def _max_drawdown_pct(equities: List[float]) -> float:
    if len(equities) < 2:
        return 0.0
    peak = equities[0]
    max_drawdown = 0.0
    for value in equities:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown * 100

