"""
Public Trader interface for PyTrader SDK.

High-level wrapper around TradingEngine for easy usage.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, Callable
from pathlib import Path

# Import trader_core components from local modules
from .trader_core import BacktestConfig, BacktestEngine, EngineConfig, TradingEngine
from .trader_core.strategies.base import BaseStrategy

from .strategy import Strategy
from .strategy_adapter import StrategyAdapter
from .strategy_loader import load_strategy
from .strategy_loader import load_strategy
from .config import settings
from .auth import resolve_account_context
from .data.psx_terminal_service import PSXTerminalService
from .data.data_mode import TradingMode
from .data.websocket_stream_provider import WebSocketStreamProvider

if TYPE_CHECKING:
    from .dashboard import DashboardHandle


class Trader:
    """
    High-level trading interface for PyTrader SDK.
    
    This class provides a simple interface for running backtests and paper trading
    with custom strategies.
    
    Example:
        from pytrader import Trader, Strategy
        
        class MyStrategy(Strategy):
            def on_data(self, data):
                # Your trading logic
                self.buy('OGDC', 100)
        
        trader = Trader(
            strategy=MyStrategy,
            symbols=['OGDC', 'HBL'],
            cycle_minutes=15
        )
        
        # Run backtest
        trader.run_backtest(start='2024-01-01', end='2024-12-31')
        
        # Or start paper trading
        trader.start_paper_trading(token='your-token')
    """
    
    def __init__(
        self,
        strategy: Union[str, Strategy, BaseStrategy, type[Strategy]],
        symbols: List[str],
        *,
        cycle_minutes: int = 15,
        initial_cash: Optional[float] = None,
        position_notional: float = 100_000.0,
        bot_id: str = "default",
        **kwargs: Any,
    ):
        """
        Initialize Trader.
        
        Args:
            strategy: Strategy class/instance, strategy name string, or file path
            symbols: List of symbols to trade
            cycle_minutes: Cycle duration in minutes (default: 15)
            initial_cash: Starting cash (default: 1,000,000)
            position_notional: Position size per trade (default: 100,000)
            bot_id: Bot identifier
            **kwargs: Additional engine config options
        """
        self.symbols = [s.upper() for s in symbols]
        self.bot_id = bot_id
        self._strategy_instance: Optional[Any] = None
        self._engine: Optional[TradingEngine] = None
        self._backtest_engine: Optional[BacktestEngine] = None
        self._dashboard_handle: Optional["DashboardHandle"] = None
        self._validate_cycle_minutes(cycle_minutes)
        
        # Load strategy
        strategy_obj = self._load_strategy(strategy)
        
        # Store strategy instance if it's a user Strategy
        if isinstance(strategy_obj, Strategy):
            self._strategy_instance = strategy_obj
            # Call on_start if available
            if hasattr(strategy_obj, 'on_start'):
                try:
                    strategy_obj.on_start()
                except Exception:
                    pass
        
        # Create adapter if needed
        if isinstance(strategy_obj, Strategy):
            adapter = StrategyAdapter(strategy_obj)
            # Portfolio service will be set when engine is created
            self._adapter = adapter
            strategy_obj = adapter
        else:
            self._adapter = None
        
        # Store strategy for engine
        self._strategy = strategy_obj
        
        # Store config
        self._config = {
            'cycle_minutes': cycle_minutes,
            'initial_cash': initial_cash,
            'position_notional': position_notional,
            **kwargs,
        }

    # ------------------------------------------------------------------
    # High-level connection helper for live trading
    # ------------------------------------------------------------------

    @classmethod
    def connect(
        cls,
        *,
        user_id: str,
        bot_id: str,
        bot_api_key: str,
        symbols: List[str],
        backend_url: Optional[str] = None,
        cycle_minutes: int = 15,
        initial_cash: Optional[float] = None,
        position_notional: float = 100_000.0,
    ) -> "LiveTraderHandle":
        """
        High-level helper that prepares a live trading connection.

        Example:
            from pytrader import Trader

            trader = Trader.connect(
                user_id="dev",
                bot_id="my-live-bot",
                bot_api_key="px_live_...",
                symbols=["OGDC", "HBL"],
            )

            trader.run_live(MyStrategy)
        """

        class LiveTraderHandle:
            def __init__(self) -> None:
                self._user_id = user_id
                self._bot_id = bot_id
                self._bot_api_key = bot_api_key
                self._symbols = [s.upper() for s in symbols]
                self._backend_url = backend_url
                self._cycle_minutes = cycle_minutes
                self._initial_cash = initial_cash
                self._position_notional = position_notional

            def run_live(
                self,
                strategy: Union[str, Strategy, BaseStrategy, type[Strategy]],
                **kwargs: Any,
            ) -> None:
                """
                Run the given strategy in LIVE mode using JWT-based bot authentication.

                This wraps Trader(...) + run_paper_trading(...) and wires in:
                - user_id / bot_id / bot_api_key
                - use_jwt_auth=True so the SDK performs /auth/bot/login and /auth/bot/refresh
                """
                trader = cls(
                    strategy=strategy,
                    symbols=self._symbols,
                    cycle_minutes=self._cycle_minutes,
                    initial_cash=self._initial_cash,
                    position_notional=self._position_notional,
                    bot_id=self._bot_id,
                    **kwargs,
                )
                # Pass bot_api_key straight through as api_token; TelemetryClient/PyTrader
                # will interpret it as bot_api_key when use_jwt_auth=True.
                trader.run_paper_trading(
                    api_token=self._bot_api_key,
                    backend_url=self._backend_url or settings.backend_url,
                    warm_start=True,
                    mode=TradingMode.LIVE,
                    revaluation_interval=30,
                )

        return LiveTraderHandle()
    
    def _load_strategy(
        self,
        strategy: Union[str, Strategy, BaseStrategy, type[Strategy]],
    ) -> Union[Strategy, BaseStrategy]:
        """Load strategy from various formats."""
        # If it's already an instance
        if isinstance(strategy, (Strategy, BaseStrategy)):
            return strategy
        
        # If it's a class, instantiate it
        if isinstance(strategy, type) and issubclass(strategy, Strategy):
            return strategy(symbols=self.symbols)
        
        # If it's a string (name or path), use loader
        if isinstance(strategy, str):
            return load_strategy(strategy, symbols=self.symbols)
        
        raise ValueError(f"Invalid strategy type: {type(strategy)}")
    
    def run_backtest(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        api_token: Optional[str] = None,
        backend_url: Optional[str] = None,
        base_url: Optional[str] = None,
        csv_path: Optional[Union[str, Path]] = None,
        csv_column_mapping: Optional[Dict[str, str]] = None,
        csv_delimiter: str = ",",
        csv_encoding: str = "utf-8",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Run backtest on historical data.

        Args:
            start: Start date (YYYY-MM-DD). Optional if using CSV.
            end: End date (YYYY-MM-DD), defaults to start (single day). Optional if using CSV.
            api_token: API token (used for authentication). Not required if using CSV.
            backend_url: Backend URL for token validation / telemetry. Not required if using CSV.
            csv_path: Path to CSV file. If provided, uses CSV instead of API for data.
            csv_column_mapping: Column mapping dict. Keys: timestamp, price, open, high, low, close, volume, symbol.
                                Example: {"timestamp": "ts", "price": "close", "volume": "vol"}
            csv_delimiter: CSV delimiter (default: comma)
            csv_encoding: CSV file encoding (default: utf-8)
            **kwargs: Additional backtest config options
        
        Returns:
            Dictionary with backtest results
        
        Examples:
            # Using API (default)
            result = trader.run_backtest(start="2024-01-01", end="2024-12-31", api_token="...")
            
            # Using CSV with auto-detection
            result = trader.run_backtest(csv_path="data.csv")
            
            # Using CSV with custom column mapping
            result = trader.run_backtest(
                csv_path="data.csv",
                csv_column_mapping={
                    "timestamp": "ts",
                    "price": "close",
                    "volume": "vol"
                }
            )
        """
        from pathlib import Path
        
        # If CSV is provided, don't require token
        if csv_path:
            csv_path = Path(csv_path)
            if not csv_path.exists():
                raise ValueError(f"CSV file not found: {csv_path}")
        else:
            from .auth import require_token

            be = (base_url or backend_url or "").strip() or settings.backend_url.rstrip("/")
            require_token(api_token=api_token, backend_url=be)
        
        config_kwargs = {
            'position_notional': self._config.get('position_notional', 100_000.0),
            **kwargs,
        }
        if self._config.get('initial_cash'):
            config_kwargs['initial_cash'] = self._config['initial_cash']
        
        # Add CSV config if provided
        if csv_path:
            config_kwargs['csv_path'] = csv_path
            if csv_column_mapping:
                config_kwargs['csv_column_mapping'] = csv_column_mapping
            config_kwargs['csv_delimiter'] = csv_delimiter
            config_kwargs['csv_encoding'] = csv_encoding
        
        config = BacktestConfig(**config_kwargs)
        
        self._backtest_engine = BacktestEngine(
            symbols=self.symbols,
            strategy=self._strategy,
            config=config,
            bot_id=self.bot_id,
        )
        
        # Set portfolio service on adapter if available
        if self._adapter and hasattr(self._backtest_engine, 'portfolio'):
            self._adapter.set_portfolio_service(self._backtest_engine.portfolio)
            # Set engine reference for buy_now/sell_now methods
            if hasattr(self._backtest_engine, 'execute_immediate'):
                self._adapter.set_engine(self._backtest_engine)
        
        # Start and end dates are optional for CSV
        result = self._backtest_engine.run(start=start, end=end or start if start else None, progress_callback=progress_callback)
        
        # Call on_end if available
        if self._strategy_instance and hasattr(self._strategy_instance, 'on_end'):
            try:
                self._strategy_instance.on_end()
            except Exception:
                pass
        
        return result
    
    def run_paper_trading(
        self,
        api_token: Optional[str] = None,
        api_key: Optional[str] = None,
        account_id: Optional[str] = None,
        user_id: Optional[str] = None,
        backend_url: Optional[str] = None,
        base_url: Optional[str] = None,
        warm_start: bool = False,
        max_cycles: Optional[int] = None,
        log_dir: Optional[Union[str, Path]] = None,
        dashboard: bool = False,
        dashboard_host: str = "127.0.0.1",
        dashboard_port: int = 8787,
        dashboard_auto_open: bool = True,
        dashboard_log_level: str = "warning",
        mode: TradingMode = TradingMode.LIVE,
        revaluation_interval: int = 30,
        **kwargs: Any,
    ) -> None:
        """
        Start live paper trading (synchronous wrapper for notebooks/CLI).

        Args:
            api_token: API token for authentication.
            backend_url: PyTrader backend URL (Render) for token validation & telemetry.
            base_url: Alias of backend_url.
            warm_start: ARCHITECTURE: Sync portfolio from backend (cash, positions), NOT historical data loading.
                       Historical data seeding is separate and user-controlled via seed_historical_bars().
            max_cycles: Optional safety stop (None = run indefinitely).
            log_dir: Optional directory for local metrics/trade logs.
            dashboard: When True, launch the embedded web dashboard automatically.
            dashboard_host: Host/interface to bind the dashboard server.
            dashboard_port: Port for the dashboard server.
            dashboard_auto_open: Automatically open the browser once the dashboard starts.
            dashboard_log_level: Log level passed to uvicorn (default "warning").
            mode: Trading mode (LIVE, BACKTEST, WARM_START). Default is LIVE.
            **kwargs: Additional EngineConfig overrides.
        """
        try:
            asyncio.get_running_loop()
            try:
                import nest_asyncio

                nest_asyncio.apply()
                asyncio.run(
                    self.start_paper_trading(
                        api_token=api_token,
                        api_key=api_key,
                        account_id=account_id,
                        user_id=user_id,
                        backend_url=backend_url,
                        base_url=base_url,
                        warm_start=warm_start,
                        max_cycles=max_cycles,
                        log_dir=log_dir,
                        dashboard=dashboard,
                        dashboard_host=dashboard_host,
                        dashboard_port=dashboard_port,
                        dashboard_auto_open=dashboard_auto_open,
                        dashboard_log_level=dashboard_log_level,
                        mode=mode,
                        revaluation_interval=revaluation_interval,
                        **kwargs,
                    )
                )
            except ImportError:
                raise RuntimeError(
                    "Cannot run paper trading inside an existing event loop.\n"
                    "Install 'nest-asyncio' or call 'await trader.start_paper_trading(...)'."
                )
        except RuntimeError:
            asyncio.run(
                self.start_paper_trading(
                    api_token=api_token,
                    api_key=api_key,
                    account_id=account_id,
                    user_id=user_id,
                    backend_url=backend_url,
                    base_url=base_url,
                    warm_start=warm_start,
                    max_cycles=max_cycles,
                    log_dir=log_dir,
                dashboard=dashboard,
                dashboard_host=dashboard_host,
                dashboard_port=dashboard_port,
                dashboard_auto_open=dashboard_auto_open,
                dashboard_log_level=dashboard_log_level,
                mode=mode,
                revaluation_interval=revaluation_interval,
                **kwargs,
                )
            )
    
    async def start_paper_trading(
        self,
        api_token: Optional[str] = None,
        api_key: Optional[str] = None,
        account_id: Optional[str] = None,
        user_id: Optional[str] = None,
        backend_url: Optional[str] = None,
        base_url: Optional[str] = None,
        warm_start: bool = False,
        max_cycles: Optional[int] = None,
        log_dir: Optional[Union[str, Path]] = None,
        dashboard: bool = False,
        dashboard_host: str = "127.0.0.1",
        dashboard_port: int = 8787,
        dashboard_auto_open: bool = True,
        dashboard_log_level: str = "warning",
        mode: TradingMode = TradingMode.LIVE,
        revaluation_interval: int = 30,
        **kwargs: Any,
    ) -> None:
        """
        Start live paper trading (async method).

        Args:
            api_token: API token (optional in local mode).
            backend_url: PyTrader backend URL (e.g. Render). Set to None for fully local operation.
            base_url: Alias of backend_url.
            warm_start: ARCHITECTURE: Sync portfolio from backend (cash, positions), NOT historical data loading.
                       Historical data seeding is separate and user-controlled via seed_historical_bars().
            max_cycles: Optional stop after N cycles.
            log_dir: Directory for local telemetry.
            dashboard: Launch the embedded dashboard automatically.
            dashboard_host: Host/interface for dashboard binding.
            dashboard_port: Port for the dashboard server.
            dashboard_auto_open: Whether to open the browser automatically.
            dashboard_log_level: Log level for the embedded server.
            mode: Trading mode (LIVE, BACKTEST, WARM_START). Default is LIVE.
            **kwargs: EngineConfig overrides.
        
        ARCHITECTURE - Data Sources:
            - LIVE mode: WebSocket-only (psx-terminal) for live prices
            - Historical data: pypsx library (separate install, optional, for indicators only)
            - warm_start: Backend portfolio sync only, NOT historical data loading
        
        Local Mode (backend_url=None):
            - No backend communication
            - All data stored in logs/{bot_id}/
            - Dashboard at localhost:{dashboard_port}
            - Session tracking automatic
            - Ideal for offline development/testing
            - Positions revalued with live prices from psx-terminal WebSocket
        
        Backend mode (default when api_token / api_key is set):
            - Uses PYTRADER_BACKEND_URL if set, else https://api.pypsx.com (hosted API).
            - Optional overrides: backend_url= or base_url= on this call.
            - Telemetry to backend; portfolio sync when warm_start=True.
        """
        from .auth import require_token

        credential = api_key or api_token
        effective_backend_url = (base_url or backend_url or "").strip() or None
        # Plug-and-play: with API credentials but no explicit URL, use hosted backend from settings / PYTRADER_BACKEND_URL.
        if effective_backend_url is None and credential:
            effective_backend_url = settings.backend_url.rstrip("/")

        resolved_account = resolve_account_context(account_id=account_id, bot_id=self.bot_id, mode="PAPER")
        if account_id and resolved_account.mode == "LIVE":
            raise ValueError(
                "Trader.start_paper_trading() supports paper accounts only. "
                "Use PyPSXClient(account_id='live-brokerage', ...) for live brokerage reads and orders."
            )
        use_jwt_auth = bool(account_id and resolved_account.is_paper)
        self.bot_id = resolved_account.bot_id
        validated_token = None
        if effective_backend_url:
            if use_jwt_auth:
                if not credential:
                    raise ValueError("api_key is required for account-scoped paper trading.")
                if not user_id:
                    raise ValueError("user_id is required for account-scoped paper trading.")
                validated_token = credential
            else:
                validated_token = require_token(api_token=credential, backend_url=effective_backend_url)
        # else: local-only (no credentials or explicit local mode via empty PYTRADER_BACKEND_URL + no credential)
        
        # Determine log_dir early
        resolved_log_dir = Path(log_dir) if log_dir else Path("logs")
        
        dashboard_handle, dashboard_owned = self._activate_dashboard(
            enable=dashboard,
            host=dashboard_host,
            port=dashboard_port,
            auto_open=dashboard_auto_open,
            log_level=dashboard_log_level,
            log_dir=resolved_log_dir,
        )
        
        local_mode = effective_backend_url is None
        
        # Extract data_service from kwargs before passing to EngineConfig
        # (EngineConfig doesn't accept data_service - it's passed to TradingEngine)
        data_service = kwargs.pop('data_service', None)
        
        config_kwargs = {
            'cycle_minutes': self._config.get('cycle_minutes', 15),
            'position_notional': self._config.get('position_notional', 100_000.0),
            'require_token': bool(validated_token and effective_backend_url),  # Only require if backend is used
            'api_token': validated_token,
            'account_id': resolved_account.account_id if effective_backend_url else None,
            'use_jwt_auth': bool(use_jwt_auth and effective_backend_url),
            'backend_url': effective_backend_url,  # Don't auto-default for local mode
            'warm_start': warm_start,
            'user_id': user_id or (self._compute_user_id(validated_token) if validated_token else "local-user"),
            'local_mode': local_mode,  # NEW: Enable local-first mode when no backend
            'revaluation_interval': revaluation_interval,  # NEW: Real-time revaluation interval
            **kwargs,
        }
        if log_dir is not None:
            config_kwargs['log_dir'] = Path(log_dir)
        if self._config.get('initial_cash'):
            config_kwargs['initial_cash'] = self._config['initial_cash']
        
        config = EngineConfig(**config_kwargs)
        
        # Select data service based on trading mode
        # Priority: explicit data_service from kwargs > mode-based selection
        
        # Fix 6: Add Mode Validation in Trader
        if mode == TradingMode.LIVE:
            if data_service is None:
                # LIVE mode: Use WebSocket streaming (fail-fast if unavailable)
                data_service = WebSocketStreamProvider(
                    symbols=self.symbols,
                    interval_minutes=config_kwargs['cycle_minutes'],
                    token=validated_token,
                    mode=mode
                )
            elif not isinstance(data_service, WebSocketStreamProvider):
                raise ValueError(
                    f"LIVE mode requires WebSocketStreamProvider, "
                    f"but got {type(data_service).__name__}. "
                    f"Ensure data_service is a WebSocketStreamProvider instance."
                )
        elif data_service is None:
            # No explicit data_service provided, create based on mode
            if mode == TradingMode.BACKTEST:
                # BACKTEST mode: Use pypsx (handled by engine default)
                data_service = None  # Engine will default to PyPSXService
            elif mode == TradingMode.WARM_START:
                # Fix 4: WARM_START mode logic
                # - Replay phase (market open → now): Uses pypsx for historical data (OK, it's historical)
                # - Live phase (now → future): Uses WebSocket only (no REST)
                # The WebSocketStreamProvider handles the live phase, while warm_start config
                # triggers replay using pypsx before switching to WebSocket
                data_service = WebSocketStreamProvider(
                    symbols=self.symbols,
                    interval_minutes=config_kwargs['cycle_minutes'],
                    token=validated_token,
                    mode=mode
                )
            # If mode not recognized, data_service remains None (engine will use default)

        self._engine = TradingEngine(
            symbols=self.symbols,
            strategy=self._strategy,
            config=config,
            bot_id=self.bot_id,
            data_service=data_service,
            in_process_push=dashboard_handle.publish if dashboard_handle else None,
            trading_mode=mode,  # Pass mode to engine for validation
        )
        
        # Set portfolio service and engine reference on adapter if available
        if self._adapter and hasattr(self._engine, 'portfolio'):
            self._adapter.set_portfolio_service(self._engine.portfolio)
            # Set engine reference for buy_now/sell_now methods
            self._adapter.set_engine(self._engine)
        
        try:
            await self._engine.run_forever(max_cycles=max_cycles)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            if self._engine:
                self._engine.stop()
            
            # Call on_end if available
            if self._strategy_instance and hasattr(self._strategy_instance, 'on_end'):
                try:
                    self._strategy_instance.on_end()
                except Exception:
                    pass
            if dashboard_handle and dashboard_owned:
                dashboard_handle.close()
    
    def stop(self) -> None:
        """Stop paper trading."""
        if self._engine:
            self._engine.stop()
    
    def get_metrics(self) -> Optional[Dict[str, Any]]:
        """Get latest metrics from engine."""
        if self._engine and self._engine.metrics_history:
            return self._engine.metrics_history[-1]
        return None

    def _compute_user_id(self, token: str) -> str:
        """
        Generate a stable per-user identifier so paper accounts/logs are isolated
        per API token + bot combo.
        """
        salt = os.getenv("PYTRADER_ACCOUNT_SALT", "")
        raw = f"{self.bot_id}:{token}:{salt}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        return digest[:16]

    def _validate_cycle_minutes(self, cycle_minutes: int) -> None:
        """
        Enforce realistic PSX cycle spacing unless an explicit override is provided.
        """
        min_cycle = max(1, getattr(settings, "alignment_minutes", 15))
        allow_fast = os.getenv("PYTRADER_ALLOW_FAST_CYCLE", "0").lower() in {"1", "true", "yes"}
        if cycle_minutes < min_cycle and not allow_fast:
            raise ValueError(
                f"cycle_minutes={cycle_minutes} is shorter than the PSX bar interval ({min_cycle}m). "
                "Set PYTRADER_ALLOW_FAST_CYCLE=1 if you really need sub-interval testing."
            )

    def _activate_dashboard(
        self,
        *,
        enable: bool,
        host: str,
        port: int,
        auto_open: bool,
        log_level: str,
        log_dir: Path,
    ) -> tuple[Optional["DashboardHandle"], bool]:
        """
        Ensure the embedded dashboard server is up and return (handle, owned_by_trader).
        """
        handle = self._dashboard_handle
        owned = False

        if enable and handle is None:
            from .dashboard.runtime import DashboardHandle

            handle = DashboardHandle(
                bot_id=self.bot_id,
                symbols=self.symbols,
                host=host,
                port=port,
                log_level=log_level,
                log_dir=log_dir,  # Pass log_dir for session persistence
            )
            self._dashboard_handle = handle

        if handle:
            if enable:
                handle.mark_owned(True)
                handle.start(auto_open=auto_open)
                owned = True
            else:
                handle.mark_owned(False)
                handle.start(auto_open=False)

        return handle, owned


__all__ = ["Trader"]

