from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Callable

from .strategy_loader import BUILTIN_STRATEGIES
from .trader import Trader

DateRange = Tuple[str, Optional[str]]


def _normalise_symbols(symbols: Iterable[str]) -> List[str]:
    normalised = [symbol.upper().strip() for symbol in symbols if symbol and symbol.strip()]
    if not normalised:
        raise ValueError("At least one symbol must be provided.")
    return normalised


def _resolve_strategy(strategy_name: str, config: Optional[Dict[str, Any]]) -> Any:
    key = strategy_name.lower().strip()
    strategy_cls = BUILTIN_STRATEGIES.get(key)
    if not strategy_cls:
        raise ValueError(
            f"Strategy '{strategy_name}' is not registered. "
            f"Available templates: {', '.join(sorted(BUILTIN_STRATEGIES.keys()))}"
        )
    try:
        return strategy_cls(**(config or {}))
    except TypeError as exc:
        raise ValueError(f"Invalid configuration for '{strategy_name}': {exc}") from exc


def _resolve_date_range(
    date_range: Optional[DateRange],
    start: Optional[str],
    end: Optional[str],
) -> DateRange:
    if date_range:
        return date_range[0], date_range[1]
    if not start:
        raise ValueError("Start date is required when date_range is not provided.")
    return start, end


def run_backtest(
    strategy_name: str,
    *,
    symbols: Sequence[str],
    config: Optional[Dict[str, Any]] = None,
    date_range: Optional[DateRange] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    api_token: Optional[str] = None,
    backend_url: Optional[str] = None,
    base_url: Optional[str] = None,
    initial_cash: Optional[float] = None,
    position_notional: float = 100_000.0,
    interval: str = "1d",
    min_lot: int = 1,
    slippage_bps: float = 0.0,
    commission_per_share: float = 0.0,
    commission_pct_notional: float = 0.0,
    allow_short: bool = False,
    capital_allocation_pct: Optional[float] = None,
    max_leverage: Optional[float] = None,
    max_position_pct: Optional[float] = None,
    max_positions: Optional[int] = None,
    risk_per_trade_pct: Optional[float] = None,
    min_volume_threshold: Optional[float] = None,
    skip_illiquid_days: bool = False,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    """
    Run a local backtest for a predefined strategy template.

    Args:
        strategy_name: Registered strategy template name (e.g., 'sma_momentum').
        symbols: Iterable of PSX tickers.
        config: Strategy configuration parameters.
        date_range: Tuple of (start, end) ISO dates.
        start: Optional start date (YYYY-MM-DD) when date_range is omitted.
        end: Optional end date (YYYY-MM-DD) when date_range is omitted.
        api_token: API token for authentication.
        backend_url: PyTrader backend URL used for token validation.
        base_url: Alias of backend_url.
        initial_cash: Optional starting cash override.
        position_notional: Target notional per trade.
        interval: Historical data interval (default '1d').
        min_lot: Minimum tradable lot size.
        slippage_bps: Slippage in basis points applied to fills.
        commission_per_share: Fixed commission per share.
        commission_pct_notional: Percentage commission on notional value.
        capital_allocation_pct: Optional percent of equity to allocate per trade.
        max_leverage: Optional gross leverage cap (e.g., 2.0).
        max_position_pct: Optional percent of equity allowed per symbol.
        max_positions: Optional cap on concurrent open positions.
        risk_per_trade_pct: Optional percent of equity risked per trade.
        min_volume_threshold: Minimum volume required to trade.
        skip_illiquid_days: Skip trading when volume is below threshold.

    Returns:
        Dictionary containing metrics, equity_curve, trades, hourly_summary, and summary fields.
    """
    symbols_list = _normalise_symbols(symbols)
    strategy = _resolve_strategy(strategy_name, config)
    start_date, end_date = _resolve_date_range(date_range, start, end)

    trader = Trader(
        strategy=strategy,
        symbols=symbols_list,
        initial_cash=initial_cash,
        position_notional=position_notional,
        bot_id=f"backtest-{strategy_name}",
    )

    capital_allocation = None
    if capital_allocation_pct is not None:
        capital_allocation = max(0.0, capital_allocation_pct / 100.0)

    result = trader.run_backtest(
        start=start_date,
        end=end_date or start_date,
        api_token=api_token,
        backend_url=backend_url,
        base_url=base_url,
        interval=interval,
        min_lot=min_lot,
        slippage_bps=slippage_bps,
        commission_per_share=commission_per_share,
        commission_pct_notional=commission_pct_notional,
        allow_short=allow_short,
        capital_allocation=capital_allocation,
        max_leverage=max_leverage,
        max_position_pct=max_position_pct,
        max_positions=max_positions,
        risk_per_trade_pct=risk_per_trade_pct,
        min_volume_threshold=min_volume_threshold,
        skip_illiquid_days=skip_illiquid_days,
        progress_callback=progress_callback,
    )
    return result


def start_paper_trading(
    strategy_name: str,
    *,
    symbols: Sequence[str],
    config: Optional[Dict[str, Any]] = None,
    api_token: Optional[str] = None,
    api_key: Optional[str] = None,
    account_id: Optional[str] = None,
    user_id: Optional[str] = None,
    backend_url: Optional[str] = None,
    base_url: Optional[str] = None,
    capital: float = 1_000_000.0,
    position_notional: float = 100_000.0,
    cycle_minutes: int = 15,
    warm_start: bool = True,
    max_cycles: Optional[int] = None,
    log_dir: Optional[Path] = None,
    metrics_path: Optional[Path] = None,
    trades_path: Optional[Path] = None,
    detailed_logs: bool = False,
    dashboard: bool = False,
    dashboard_host: str = "127.0.0.1",
    dashboard_port: int = 8787,
    dashboard_auto_open: bool = True,
    dashboard_log_level: str = "warning",
) -> None:
    """
    Start terminal-only paper trading for a registered strategy template.

    Args:
        strategy_name: Registered strategy template name.
        symbols: Iterable of PSX tickers.
        config: Strategy configuration parameters.
        api_token: API token for live data (required).
        backend_url: PyTrader backend URL for telemetry + authentication.
        base_url: Alias of backend_url.
        capital: Initial virtual cash.
        position_notional: Target notional per trade.
        cycle_minutes: Engine polling cadence.
        warm_start: Whether to replay today's session before live ticks.
        max_cycles: Optional number of cycles to run (None = run indefinitely).
        log_dir: Directory for metrics/trade logs.
        metrics_path: CSV path for metrics history.
        trades_path: CSV path for trade history.
        detailed_logs: Toggle verbose console output.
        dashboard: Launch the embedded dashboard automatically.
        dashboard_host: Host/interface for the dashboard server.
        dashboard_port: Port used by the dashboard web server.
        dashboard_auto_open: Automatically open the browser when the dashboard starts.
        dashboard_log_level: Log level for the embedded dashboard server.
    """
    symbols_list = _normalise_symbols(symbols)
    strategy = _resolve_strategy(strategy_name, config)

    trader = Trader(
        strategy=strategy,
        symbols=symbols_list,
        cycle_minutes=cycle_minutes,
        initial_cash=capital,
        position_notional=position_notional,
        bot_id=f"paper-{strategy_name}",
    )

    trader.run_paper_trading(
        api_token=api_token,
        api_key=api_key,
        account_id=account_id,
        user_id=user_id,
        backend_url=backend_url,
        base_url=base_url,
        warm_start=warm_start,
        max_cycles=max_cycles,
        log_dir=log_dir or Path("logs"),
        metrics_path=metrics_path,
        trades_path=trades_path,
        detailed_logs=detailed_logs,
        dashboard=dashboard,
        dashboard_host=dashboard_host,
        dashboard_port=dashboard_port,
        dashboard_auto_open=dashboard_auto_open,
        dashboard_log_level=dashboard_log_level,
    )


