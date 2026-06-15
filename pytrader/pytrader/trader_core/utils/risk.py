"""Risk metric helpers exposed under the trader_core namespace."""

from __future__ import annotations

import statistics
from typing import List, Optional


def calculate_sharpe_ratio(
    returns: List[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> Optional[float]:
    if len(returns) < 2:
        return None

    avg_return = statistics.mean(returns)
    std_return = statistics.stdev(returns)
    if std_return == 0:
        return None

    annual_return = avg_return * periods_per_year
    annual_std = std_return * (periods_per_year ** 0.5)
    if annual_std <= 0:
        return None

    sharpe = (annual_return - risk_free_rate) / annual_std
    return round(sharpe, 4)


def calculate_sortino_ratio(
    returns: List[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> Optional[float]:
    if len(returns) < 2:
        return None

    downside_returns = [r for r in returns if r < 0]
    if len(downside_returns) < 2:
        return None

    avg_return = statistics.mean(returns)
    downside_std = statistics.stdev(downside_returns)
    if downside_std == 0:
        return None

    annual_return = avg_return * periods_per_year
    annual_downside_std = downside_std * (periods_per_year ** 0.5)
    if annual_downside_std <= 0:
        return None

    sortino = (annual_return - risk_free_rate) / annual_downside_std
    return round(sortino, 4)


def calculate_max_drawdown(portfolio_values: List[float]) -> dict:
    if len(portfolio_values) < 2:
        value = portfolio_values[0] if portfolio_values else 0.0
        return {
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "peak_value": value,
            "trough_value": value,
            "peak_index": 0,
            "trough_index": 0,
        }

    peak_value = portfolio_values[0]
    peak_index = 0
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    trough_value = portfolio_values[0]
    trough_index = 0

    for i, value in enumerate(portfolio_values):
        if value > peak_value:
            peak_value = value
            peak_index = i
        drawdown = peak_value - value
        drawdown_pct = (drawdown / peak_value) * 100 if peak_value > 0 else 0.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_drawdown_pct = drawdown_pct
            trough_value = value
            trough_index = i

    return {
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "peak_value": peak_value,
        "trough_value": trough_value,
        "peak_index": peak_index,
        "trough_index": trough_index,
    }


def calculate_volatility(returns: List[float], periods_per_year: int = 252) -> Optional[float]:
    if len(returns) < 2:
        return None
    std_return = statistics.stdev(returns)
    return round(std_return * (periods_per_year ** 0.5), 4)


def calculate_returns(portfolio_values: List[float]) -> List[float]:
    if len(portfolio_values) < 2:
        return []
    returns: List[float] = []
    for i in range(1, len(portfolio_values)):
        prev = portfolio_values[i - 1]
        if prev > 0:
            returns.append((portfolio_values[i] - prev) / prev)
    return returns


__all__ = [
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_max_drawdown",
    "calculate_volatility",
    "calculate_returns",
]

