"""
Live paper trading engine with 15-minute cycles and integrated metrics.

BACKEND-ONLY: This engine is for backend internal use only.
SDK client code should use PyTrader client instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import httpx
import requests
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

import pandas as pd

from ...data.pypsx_service import PyPSXService
from ...data.websocket_stream_provider import WebSocketStreamProvider
from ...data.bar_aggregator import AggregatedBar
from ...data.data_mode import TradingMode
from ...telemetry import TelemetryClient
from .telemetry import (
    CallbackTelemetry,
    CompositeTelemetry,
    CycleReport,
    FileTelemetry,
    HttpTelemetry,
    NullTelemetry,
    BackendRelayTelemetry,
    SessionTelemetry,
)
from .session_manager import SessionManager
from ...utils.logger import PaperTradingLogger
from ..utils import is_market_open, log_line, now_tz
import sys
import os
from ..utils.metrics_csv import MetricsCSVWriter
from ...config import settings
from zoneinfo import ZoneInfo
from ..portfolio.metrics import (
    TradeMetrics,
    compute_portfolio_metrics,
)
from ..portfolio.service import PortfolioService, PortfolioSummary
from ...utils.exceptions import DataProviderError
from ...utils.time_utils import next_market_open, today_session_window
from ...utils.market_hours import PSXMarketHours
from .paper_account import PaperAccountManager
from .signal_queue import SignalQueue

logger = logging.getLogger(__name__)


def _empty_intraday_frame() -> pd.DataFrame:
    """Return a typed empty DataFrame for intraday data flows."""
    return pd.DataFrame(
        {
            "ts": pd.Series(dtype="datetime64[ns]"),
            "price": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
        }
    )


def _as_series(value: Any) -> pd.Series:
    """Helper to appease static type checkers for pandas column access."""
    return cast(pd.Series, value)


@dataclass
class EngineConfig:
    cycle_minutes: int = 15
    lookback_days: int = 2
    position_notional: float = 100_000.0
    capital_allocation: Optional[float] = None  # Percentage of equity per trade (e.g., 0.2 = 20%)
    min_lot: int = 1
    initial_cash: Optional[float] = None
    log_dir: Path = Path("logs")
    backend_url: Optional[str] = None
    backend_endpoint: str = "/live/metrics"
    api_token: Optional[str] = None
    account_id: Optional[str] = None
    use_jwt_auth: bool = False
    require_token: bool = False
    bias_threshold_pct: float = 0.1
    use_cache: bool = False
    verbose_warm_start: bool = False
    record_warm_start_trades: bool = True
    fast_sleep_seconds: Optional[float] = None  # Internal: for development/testing only (not for production use)
    slippage_bps: float = 0.0
    commission_per_share: float = 0.0
    commission_pct_notional: float = 0.0015  # Default: 0.15% per share (percentage-based)
    warm_start: bool = False  # ARCHITECTURE: Sync portfolio from backend, NOT historical data loading
                               # - warm_start=True: Sync portfolio state from backend (cash, positions)
                               # - Historical data seeding is separate and user-controlled (via seed_historical_bars())
                               # - warm_start does NOT load historical data via REST (that's deprecated)
    reset_account: bool = False  # Reset account to initial cash
    user_id: str = "default"  # User ID for account persistence
    allow_short: bool = False  # Allow short selling (selling without existing position)
    detailed_logs: bool = False  # Print verbose stats every cycle (default: concise)
    verbose: bool = False  # Same as detailed_logs for backward compatibility
    metrics_path: Optional[Path] = None  # Path to metrics CSV (default: pytrader_metrics.csv)
    trades_path: Optional[Path] = None  # Path to trades CSV (default: pytrader_trades.csv)
    price_log_threshold_pct: float = 0.25  # Minimum % move before price logs emit
    unrealized_log_threshold: float = 250.0  # Minimum PKR change in unrealized P/L before logging
    reset_session_metrics_on_warm_start: bool = True  # Forward-only metrics when joining mid-session
    local_mode: bool = False  # NEW: Enable fully local operation (no backend dependencies)
    revaluation_interval: int = 30  # NEW: Seconds between portfolio revaluations for real-time updates (0 = disabled)
    allow_immediate_execution: bool = True  # NEW: Allow strategies to execute orders immediately without waiting for bar close
                                             # - True: strategy.buy()/sell() executes immediately with current prices
                                             # - False: orders wait for bar close (traditional behavior)



@dataclass
class SignalSnapshot:
    symbol: str
    side: Optional[str]
    strategy_signal: str
    bias: str
    generated_at: datetime
    signal_price: float
    vwap: float
    target_qty: int
    note: str = ""
    delta_pct: float = 0.0
    executed_at: Optional[datetime] = None
    batch_label: Optional[str] = None


class TradingEngine:
    """
    Paper trading loop that simulates live trading using 15-minute data batches.
    
    BACKEND-ONLY: This engine is for backend internal use only.
    SDK client code should use PyTrader client instead.
    """

    def __init__(
        self,
        symbols: List[str],
        strategy: Any,
        *,
        portfolio: Optional[PortfolioService] = None,
        data_service: Optional[PyPSXService] = None,
        config: Optional[EngineConfig] = None,
        bot_id: str = "default",
        telemetry: Optional[CompositeTelemetry] = None,
        in_process_push: Optional[Any] = None,
        trading_mode: Optional[TradingMode] = None,
    ) -> None:
        # Store trading mode for validation
        self._trading_mode = trading_mode
        
        # Enforce data_service requirement - no default fallback
        if data_service is None:
            raise ValueError(
                "data_service is required. "
                "For LIVE mode, use WebSocketStreamProvider. "
                "For BACKTEST, use PyPSXService."
            )
        
        self.symbols = [s.upper().strip() for s in symbols]
        self.strategy = strategy
        self._strategy_name = self._determine_strategy_name(strategy)
        self.config = config or EngineConfig()
        self.service = data_service
        self.bot_id = bot_id
        
        # Detect if using WebSocket stream provider for LIVE mode
        self._using_websocket = isinstance(self.service, WebSocketStreamProvider)
        
        # ARCHITECTURE: Enforce WebSocket-Only in LIVE Mode
        if self._trading_mode == TradingMode.LIVE:
            if not self._using_websocket:
                raise RuntimeError(
                    "ARCHITECTURE VIOLATION: LIVE mode requires WebSocketStreamProvider. "
                    "LIVE mode must use WebSocket-only data source (psx-terminal). "
                    "Ensure mode=TradingMode.LIVE and WebSocketStreamProvider is provided."
                )
            log_line("="*70)
            log_line("🔌 LIVE MODE: WebSocket-Only Data Source")
            log_line("="*70)
            log_line("📡 Live prices: psx-terminal WebSocket (real-time, no delay)")
            log_line("📚 Historical data: pypsx library (separate install, optional, for indicators only)")
            log_line("🚫 REST endpoints: DISABLED for live prices")
            log_line("="*70)
        elif self._using_websocket:
            log_line("🔌 Using WebSocket streaming for real-time data")
        
        # Initialize market hours service for backend-integrated checks
        from ...utils.market_hours_service import MarketHoursService
        self._market_hours_service = MarketHoursService(
            backend_url=self.config.backend_url,
            api_token=self.config.api_token
        )

        # Initialize account manager for persistent state
        default_cash = self.config.initial_cash or 1_000_000.0
        self.account_manager = PaperAccountManager(
            user_id=self.config.user_id,
            bot_id=self.bot_id,
            default_cash=default_cash,
        )
        
        account_state = None
        initial_cash = default_cash

        # Default behavior: Always restore from local files if they exist
        # If user wants a fresh start, they should change the bot_id
        if self.account_manager.account_file.exists():
            try:
                account_state = self.account_manager.load_account()
                if account_state and account_state.cash is not None:
                    initial_cash = account_state.cash
                    log_line(
                        f"📂 Restored account state from {self.account_manager.account_file}\n"
                        f"   Cash: {account_state.cash:,.0f} | Positions: {len(account_state.positions)}"
                    )
                else:
                    log_line(f"[INFO] Reset paper account for {self.config.user_id}/{self.bot_id}: cash={default_cash:,.0f}")
            except Exception as exc:
                log_line(f"[WARN] Failed to load account state, starting fresh: {exc}")
                account_state = None
                initial_cash = default_cash
        else:
            log_line(f"[INFO] Reset paper account for {self.config.user_id}/{self.bot_id}: cash={default_cash:,.0f}")

        # ARCHITECTURE: Warm start = backend portfolio sync, NOT historical data loading
        if self.config.warm_start:
            log_line(
                f"Warm start enabled: Portfolio will be synced from backend "
                f"(user_id={self.config.user_id}, bot_id={self.bot_id})."
            )
            log_line(
                "NOTE: warm_start syncs portfolio state (cash, positions) from backend. "
                "Historical data seeding is separate and user-controlled."
            )
            # Backend is the authoritative source - we'll sync in start()
            # But we still use local account state as baseline if available
        
        # Portfolio is now PERSISTENT (disk-based SQLite)
        # It will be stored locally and survive restarts
        # Local files are the single source of truth for portfolio state
        # Create persistent database in user_data/portfolios directory
        portfolio_db_dir = Path("user_data") / "portfolios"
        portfolio_db_dir.mkdir(parents=True, exist_ok=True)
        portfolio_db_path = portfolio_db_dir / f"{self.bot_id}.db"
        
        portfolio_kwargs = {
            "initial_cash": initial_cash,
            "allow_short": self.config.allow_short,
            "db_url": f"sqlite:///{portfolio_db_path}",  # Persistent disk storage
        }
        # Add backend sync params if warm start enabled
        if self.config.warm_start and self.config.api_token and self.config.backend_url:
            # Create minimal API client for PortfolioService
            try:
                # Use requests session as simple API client
                api_session = requests.Session()
                api_session.headers.update({
                    "X-PyTrader-Token": self.config.api_token,
                    "x-trading-mode": "live",
                })
                # Add base_url attribute for convenience
                api_session.get = lambda path, **kwargs: requests.Session.get(
                    api_session, 
                    f"{self.config.backend_url}{path}", 
                    headers={
                        "X-PyTrader-Token": self.config.api_token,
                        "x-trading-mode": "live",
                    },
                    **kwargs
                )
                portfolio_kwargs["api_client"] = api_session
                portfolio_kwargs["bot_id"] = self.bot_id
            except Exception as exc:
                log_line(f"Warning: Could not create API client for portfolio sync: {exc}")
        
        self.portfolio = portfolio or PortfolioService(**portfolio_kwargs)
        
        # Only set initial_cash if NOT restoring from account state
        # If account_state exists, we'll use the restored cash value instead
        restore_has_positions = account_state and account_state.positions
        
        if portfolio is None and initial_cash is not None and not restore_has_positions:
            summary_snapshot = self.portfolio.get_summary()
            delta = float(initial_cash) - float(summary_snapshot.cash)
            if abs(delta) > 1e-6:
                self.portfolio.apply_cash_adjustment(delta)
        
        #  Restore positions from local account state if available
        if restore_has_positions:
            self._restore_positions_from_account(account_state.positions)
        
        # Store initial_capital from account state for accurate total return calculation
        self._initial_capital: Optional[float] = None
        if account_state and account_state.initial_capital:
            self._initial_capital = float(account_state.initial_capital)
        
        base_summary = self.portfolio.get_summary()
        self._initial_equity: Optional[float] = float(base_summary.equity)
        self._session_start_equity: Optional[float] = self._initial_equity
        self._trade_count_baseline: int = 0
        self._joined_mid_session: bool = False
        self._metrics_baseline = {
            "equity": float(base_summary.equity),
            "cash": float(base_summary.cash),
            "unrealized_pnl": float(base_summary.unrealized_pnl),
            "realized_pnl": float(base_summary.realized_pnl),
        }

        self.is_running: bool = False
        self._cycle_delta = timedelta(minutes=self.config.cycle_minutes)
        self._sleep_seconds = self.config.fast_sleep_seconds
        self._intraday_cache: Dict[str, pd.DataFrame] = {}
        self._session_data: Dict[str, pd.DataFrame] = {}
        self.metrics_history: List[Dict[str, Any]] = []
        self._last_seen_ts: Dict[str, pd.Timestamp] = {}
        self._last_vwap: Dict[str, float] = {}
        self._session_start: Optional[datetime] = None
        self._warm_start_complete: bool = False
        self._warm_start_cycles: int = 0
        self._supports_color: bool = self._check_color_support()
        self._session_end: Optional[datetime] = None
        self._last_cycle_close: Optional[datetime] = None
        self._local_tz: Optional[ZoneInfo] = None

        # Market day filtering: Track today's first trade and first price per symbol
        self._symbol_first_trade_time: Dict[str, datetime] = {}  # symbol -> first trade timestamp today
        self._symbol_open_price_today: Dict[str, float] = {}  # symbol -> first price today
        self._today_date: Optional[date] = None  # Current market day date (PKT)
        self._off_hours_scan_done: bool = False  # Track if off-hours scan has run

        if self.config.require_token and not self.config.api_token:
            raise RuntimeError(
                "PyTrader Live Trading requires an API token. "
                "Set PYTRADER_TOKEN or provide EngineConfig.api_token."
            )

        self._backend_client: Optional[TelemetryClient] = None
        self._telemetry, self._backend_client = self._build_telemetry(telemetry, in_process_push)
        self._backend_log_hook = self._build_backend_log_hook()
        log_root = self.config.log_dir
        if not isinstance(log_root, Path):
            log_root = Path(log_root)
        self._paper_logger = PaperTradingLogger(
            bot_id=self.bot_id,
            log_root=log_root / "streams",
            backend_hook=self._backend_log_hook,
        )
        self._price_log_threshold_pct = max(0.0, float(self.config.price_log_threshold_pct))
        self._unrealized_log_threshold = max(0.0, float(self.config.unrealized_log_threshold))
        self._last_seen_price: Dict[str, float] = {}
        self._last_logged_price: Dict[str, float] = {}
        self._last_logged_unrealized: Dict[str, float] = {}
        self._last_logged_qty: Dict[str, int] = {}
        self._active_signals: Dict[str, SignalSnapshot] = {}
        # Queue for orders generated after market close (in-memory only, cleared on restart)
        self._queued_signals: List[SignalSnapshot] = []
        
        # Real-time revaluation task for dashboard updates
        self._revaluation_task: Optional[asyncio.Task] = None
        self._revaluation_stop_event: Optional[asyncio.Event] = None

        # Real-time cash sync (ACCOUNT_UPDATE signal from backend).
        # Keeps the bot active and ensures millisecond-level cash awareness.
        self._account_update_task: Optional[asyncio.Task] = None
        self._account_update_stop_event: Optional[asyncio.Event] = None
        
        # Signal queue persistence REMOVED - backend orders are the authoritative queue
        # self.signal_queue = SignalQueue(...)  # ← REMOVED
        # self._load_queued_signals_from_storage()  # ← REMOVED
        
        # Initialize CSV writer for metrics storage
        scoped_metrics_path = self.config.metrics_path
        scoped_trades_path = self.config.trades_path
        if scoped_metrics_path is None:
            scoped_metrics_path = log_root / f"{self.account_manager.user_id}-{self.bot_id}-metrics.csv"
        if scoped_trades_path is None:
            scoped_trades_path = log_root / f"{self.account_manager.user_id}-{self.bot_id}-trades.csv"

        self.csv_writer = MetricsCSVWriter(
            metrics_path=Path(scoped_metrics_path),
            trades_path=Path(scoped_trades_path),
        )
        
        # Handle verbose flag (backward compatibility with detailed_logs)
        if self.config.verbose and not self.config.detailed_logs:
            self.config.detailed_logs = self.config.verbose
    
    def _check_color_support(self) -> bool:
        """Check if terminal supports ANSI color codes."""
        if os.getenv("NO_COLOR") or os.getenv("TERM") == "dumb":
            return False
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def _build_positions_snapshot(
        self,
        summary_positions: List[Dict[str, Any]],
        prices: Optional[Dict[str, float]] = None,
    ) -> Tuple[List[Dict[str, Any]], float, float]:
        """
        Build a per-position snapshot enriched with live prices, market value, and unrealized PnL.
        """
        price_map = prices or {}
        snapshot: List[Dict[str, Any]] = []
        total_value = 0.0
        total_unrealized = 0.0
        for pos in summary_positions:
            qty = pos.get("qty", 0)
            if qty <= 0:
                continue
            symbol = pos["symbol"]
            avg_cost = float(pos.get("avg_cost", 0.0))
            current_price = float(price_map.get(symbol, avg_cost))
            market_value = current_price * qty
            unrealized = (current_price - avg_cost) * qty
            snapshot.append(
                {
                    "symbol": symbol,
                    "qty": qty,
                    "avg_cost": avg_cost,
                    "current_price": current_price,
                    "market_value": market_value,
                    "unrealized_pnl": unrealized,
                }
            )
            total_value += market_value
            total_unrealized += unrealized
        return snapshot, total_value, total_unrealized

    def _refresh_session_baseline(self) -> None:
        summary = self.portfolio.get_summary()
        self._session_start_equity = float(summary.equity)
        if self.config.reset_session_metrics_on_warm_start:
            self._reset_metrics_snapshot(summary)
            self._log_system_event(
                event="session_metrics_reset",
                message="Session metrics reset at warm start",
                level="info",
            )

    def _reset_metrics_snapshot(self, summary: PortfolioSummary) -> None:
        self._metrics_baseline = {
            "equity": float(summary.equity),
            "cash": float(summary.cash),
            "unrealized_pnl": float(summary.unrealized_pnl),
            "realized_pnl": float(summary.realized_pnl),
        }
    
    def _sync_portfolio_from_backend(self) -> None:
        """
        Sync portfolio state from backend.
        
        CRITICAL: This is the ONLY way to initialize portfolio state in warm start.
        Backend state is the single source of truth.
        
        Invariant: Portfolio state = backend /bots/{bot_id}/state
        """
        # Skip backend sync in local mode
        if self.config.local_mode:
            log_line("📁 Local mode: Skipping backend sync (using local files only)")
            return
        
        if not self.config.backend_url or not self.config.api_token:
            log_line("⚠️ Warning: No backend configured, skipping portfolio sync")
            return
        
        try:
            log_line("🔄 Syncing portfolio from backend state...")
            
            import httpx
            with httpx.Client(timeout=30.0) as client:
                headers = {
                    "X-PyTrader-Token": self.config.api_token,
                    "x-trading-mode": "live",
                }
                base = self.config.backend_url.rstrip("/")
                
                # Fetch full portfolio state (with revaluation)
                url = f"{base}/bots/{self.bot_id}/state"
                
                try:
                    resp = client.get(url, headers=headers)
                    resp.raise_for_status()
                    state = resp.json()
                except Exception as exc:
                    log_line(f"⚠️ Warning: Could not fetch state from backend: {exc}")
                    log_line("Continuing with local initial cash")
                    return
            
            # Extract backend state
            backend_cash = float(state.get('cash', self.portfolio.initial_cash))
            backend_equity = float(state.get('equity', backend_cash))
            backend_positions = state.get('positions', [])
            
            # Adjust local cash to match backend
            summary = self.portfolio.get_summary()
            cash_delta = backend_cash - summary.cash
            if abs(cash_delta) > 0.01:
                self.portfolio.apply_cash_adjustment(cash_delta)
                log_line(f"💰 Adjusted cash by {cash_delta:+,.0f} to match backend")
            
            # Log what we found (positions are already in backend from executions)
            log_line(
                f"✅ Synced from backend: "
                f"Equity=Rs.{backend_equity:,.0f}, "
                f"Cash=Rs.{backend_cash:,.0f}, "
                f"{len(backend_positions)} position(s)"
            )
            
            # Update initial equity after sync
            self._initial_equity = backend_equity
            self._session_start_equity = backend_equity
            
        except Exception as exc:
            log_line(f"⚠️ Warning: Failed to sync from backend: {exc}")
            log_line("Continuing with local state")
    
    def _colorize(self, text: str, color: str) -> str:
        """Add ANSI color codes if terminal supports it."""
        if not self._supports_color:
            return text
        colors = {
            "green": "\033[32m",
            "red": "\033[31m",
            "yellow": "\033[33m",
            "blue": "\033[34m",
            "cyan": "\033[36m",
            "reset": "\033[0m",
            "bold": "\033[1m",
        }
        return f"{colors.get(color, '')}{text}{colors['reset']}"

    def _validate_data_source(self) -> None:
        """
        Runtime validation to ensure data source architecture is correct.
        
        ARCHITECTURE: In WebSocket LIVE mode, REST calls are strictly forbidden.
        This method validates that the data source configuration is correct.
        """
        if self._using_websocket and self._trading_mode == TradingMode.LIVE:
            # Validate that we're using WebSocketStreamProvider
            if not isinstance(self.service, WebSocketStreamProvider):
                raise RuntimeError(
                    f"ARCHITECTURE VIOLATION: LIVE mode requires WebSocketStreamProvider, "
                    f"but got {type(self.service).__name__}. "
                    f"LIVE mode must use WebSocket-only data source."
                )
            
            # Validate that service is configured for LIVE mode
            if hasattr(self.service, 'mode') and self.service.mode != TradingMode.LIVE:
                logger.warning(
                    f"WebSocketStreamProvider mode is {self.service.mode}, but engine is in LIVE mode. "
                    f"This may cause issues."
                )
            
            log_line("✅ Data source validation passed: WebSocket-only mode confirmed")
        elif self._trading_mode == TradingMode.LIVE and not self._using_websocket:
            raise RuntimeError(
                "ARCHITECTURE VIOLATION: LIVE mode requires WebSocket data source, "
                "but WebSocketStreamProvider is not being used. "
                "LIVE mode cannot use REST-based data sources."
            )
    
    def start(self) -> None:
        if self.is_running:
            return
        
        # ARCHITECTURE: Validate data source before starting
        self._validate_data_source()
        
        now = now_tz()
        self._session_start, session_market_close = today_session_window(now)
        # Extend session end by 15 minutes to allow processing final batch
        self._session_end = session_market_close + timedelta(minutes=15)
        # Local timezone for display/alignment
        self._local_tz = ZoneInfo(getattr(settings, "timezone", "Asia/Karachi"))
        
        # Set today's date for strict filtering
        self._today_date = now.date()
        
        # Reset first trade tracking for new day
        self._symbol_first_trade_time.clear()
        self._symbol_open_price_today.clear()
        
        # LIVE MODE: WebSocket-first - skip traditional data loading
        if self._using_websocket:
            log_line("🚀 LIVE MODE: Initializing WebSocket streaming...")
            log_line(f"   📡 Symbols: {', '.join(self.symbols)}")
            log_line(f"   ⏱️  Bar interval: {self.config.cycle_minutes} minutes")
            log_line(f"   🔔 Strategy executes on bar close events")
            
            # No traditional data loading - WebSocket handles everything
            self._last_cycle_close = now
            self._last_seen_ts.clear()
            self._last_vwap.clear()
            self.is_running = True
            
            # Sync initial portfolio state
            if self.config.warm_start:
                log_line("⏳ Warm start: Restoring account state...")
                self._initialize_history(now)
                summary = self.portfolio.get_summary()
                log_line(f"✅ Warm start complete | Cash: {summary.cash:,.0f} PKR | Equity: {summary.equity:,.0f} PKR")
                self._warm_start_complete = True
                self._sync_initial_portfolio()
            else:
                summary = self.portfolio.get_summary()
                log_line(f"💰 Starting fresh | Cash: {summary.cash:,.0f} PKR")
                self._sync_initial_portfolio()
            
            log_line("✅ WebSocket LIVE mode initialized. Waiting for bar close events...")
            return  # Skip traditional initialization
        
        # TRADITIONAL MODE: Continue with existing data loading logic
        # Detect first available timestamp from today's data to avoid hard-coded start
        # Also detect if we're starting BEFORE first trade of the day
        earliest_ts: Optional[pd.Timestamp] = None
        has_today_trades = False
        probe_symbols = list(self.symbols)
        
        for sym in probe_symbols:
            try:
                # Load today's data with strict filtering
                df_today = self._load_symbol_history(
                    sym,
                    up_to=now,
                    use_cache=self.config.use_cache,
                    publish=False,
                )
                if not df_today.empty:
                    has_today_trades = True
                    cur_earliest_raw = df_today["ts"].min()
                    if pd.notna(cur_earliest_raw):
                        cur_earliest = pd.Timestamp(cur_earliest_raw)
                    if earliest_ts is None or cur_earliest < earliest_ts:
                        earliest_ts = cur_earliest
            except Exception:
                continue
        
        # Handle case: Starting BEFORE first trade of the day
        if not has_today_trades or earliest_ts is None:
            # Check if market is closed - if so, allow off-hours scan to run
            can_paper_trade = PSXMarketHours.can_paper_trade(now)
            if not can_paper_trade:
                # Market is closed - allow bot to run so off-hours scan can execute
                log_line("Market is closed. Bot will run off-hours scan to generate queued signals.")
                self._last_cycle_close = now
                self._last_seen_ts.clear()
                self._last_vwap.clear()
                self.is_running = True
                return  # Allow cycle_once to run off-hours scan
            else:
                # Market should be open but no trades yet - wait for first trade
                print("\n" + "-" * 70)
                print("⏳ WAITING FOR FIRST MARKET TRADE")
                print("-" * 70)
                print("No trades available for today yet.")
                print("Portfolio loaded. Waiting for first price update...")
                print("-" * 70 + "\n")
                # Set session start to current time, will update when first trade arrives
                self._last_cycle_close = now
                self._last_seen_ts.clear()
                self._last_vwap.clear()
                # Mark as running so cycle_once can check for first trade
                self.is_running = True
                return  # Don't proceed with full initialization until first trade
        
        # We have today's trades - align to cycle grid
        if earliest_ts is not None:
            # Align to our cycle grid and clamp not before declared session start
            aligned = earliest_ts.floor(f"{self.config.cycle_minutes}min")
            if aligned > self._session_start:
                self._session_start = aligned
        self._last_cycle_close = self._session_start
        self._last_seen_ts.clear()
        self._last_vwap.clear()
        
        # Log initialization (clean format for users)
        symbols_text = ", ".join(self.symbols)
        print("\n" + "-" * 70)
        if self.config.warm_start:
            print(f"MODE: LIVE-WARM | Symbols: {symbols_text} | Interval: {self.config.cycle_minutes}m")
            print("-" * 70)
            current_str = self._format_local_time(now)
            print(f"\nWarm starting from current time: {current_str}")
            print("ARCHITECTURE: warm_start syncs portfolio from backend (cash, positions)")
            print("Historical data seeding is separate and user-controlled.\n")
            print("Restoring account state and revaluing with current market prices...\n")
            self._initialize_history(now)
            summary = self.portfolio.get_summary()
            print("\n" + "-" * 70)
            print("✅ Warm Start Completed (Portfolio synced from backend)")
            print(f"Cash: {summary.cash:,.0f} PKR | Equity: {summary.equity:,.0f} PKR")
            if summary.positions:
                print(f"Positions: {len(summary.positions)} open")
            print("Now entering LIVE PAPER TRADING...")
            print("-" * 70 + "\n")
            self._warm_start_complete = True
            self._joined_mid_session = has_today_trades
            
            # Sync portfolio after warm start (intraday_cache should be populated now)
            self._sync_initial_portfolio()
        else:
            print(f"MODE: LIVE | Symbols: {symbols_text} | Interval: {self.config.cycle_minutes}m")
            print("-" * 70)
            summary = self.portfolio.get_summary()
            print("\nStarting fresh from current time")
            print(f"Cash: {summary.cash:,.0f} PKR | Equity: {summary.equity:,.0f} PKR\n")
            self._warm_start_complete = True  # No warm-start, so we're immediately in live mode
        
        self._trade_count_baseline = self._current_trade_count()
        
        # Initialize backend client for order management if configured
        self._backend_client: Optional[Any] = None
        if self.config.backend_url and self.config.api_token:
            try:
                from ...client import PyTrader
                self._backend_client = PyTrader(
                    bot_id=self.bot_id,
                    api_token=self.config.api_token,
                    account_id=self.config.account_id,
                    user_id=self.config.user_id,
                    backend_url=self.config.backend_url,
                    timeout=5.0,
                    use_jwt_auth=self.config.use_jwt_auth,
                )
                log_line(f"Backend client initialized for {self.bot_id}")
                
                # NOTE: Portfolio sync now handled automatically in PortfolioService.__init__
                # No need for manual _sync_portfolio_from_backend() call here
                
            except Exception as exc:
                log_line(f"Failed to initialize backend client: {exc}")
                if self.config.warm_start:
                    raise RuntimeError(
                        f"Warm start requires backend connection but initialization failed: {exc}"
                    )

        self.is_running = True
        self._log_system_event(
            event="bot_started",
            message="Paper trading engine started",
            symbols=self.symbols,
            cycle_minutes=self.config.cycle_minutes,
            warm_start=self.config.warm_start,
            joined_mid_session=self._joined_mid_session,
        )

    def stop(self) -> None:
        """Stop the trading engine, persist state, and close telemetry."""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Stop real-time revaluation task
        if self._revaluation_task and not self._revaluation_task.done():
            if self._revaluation_stop_event:
                self._revaluation_stop_event.set()
            self._revaluation_task.cancel()
            log_line("⏹️ Stopped real-time revaluation")

        # Stop account update websocket listener
        if self._account_update_task and not self._account_update_task.done():
            if self._account_update_stop_event:
                self._account_update_stop_event.set()
            self._account_update_task.cancel()
            log_line("⏹️ Stopped ACCOUNT_UPDATE listener")
        
        # Print session summary before stopping
        if self.metrics_history:
            self._print_session_summary()
        
        log_line("Trading session stopped")
        self._log_system_event(event="bot_stopped", message="Paper trading engine stopped")
        
        # End session if session manager exists
        if hasattr(self, "session_manager") and self.session_manager:
            try:
                self.session_manager.end_session()
                log_line(f"Session ended: {self.session_manager.current_session.session_id}")
            except Exception as exc:
                log_line(f"Warning: Could not end session: {exc}")
        
        # Save final account state before stopping (with full position details)
        try:
            summary = self.portfolio.get_summary()
            # Save positions with both quantity and avg_cost
            positions_dict = {
                pos["symbol"]: {"qty": pos["qty"], "avg_cost": pos["avg_cost"]}
                for pos in summary.positions
            }
            self.account_manager.save_account(
                cash=float(summary.cash),
                positions=positions_dict,
                equity=float(summary.equity),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            log_line(f"Failed to save account state on stop: {exc}")
        
        if hasattr(self, "_telemetry") and self._telemetry is not None:
            try:
                self._telemetry.close()
            except Exception:
                pass

    def execute_immediate(
        self,
        symbol: str,
        side: str,
        quantity: int,
        *,
        reason: str = "",
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute an order immediately without waiting for bar close.
        
        This method enables local-first, immediate execution based on pre-computed signals.
        No need to wait for the next bar close event - orders execute instantly with
        current market prices.
        
        Args:
            symbol: Stock symbol (e.g., "HBL", "OGDC")
            side: "BUY" or "SELL"
            quantity: Number of shares to trade
            reason: Optional reason/note for this order (for logging)
            price: Optional price override (if None, fetches current market price)
        
        Returns:
            Trade execution dict with keys: symbol, side, quantity, price, timestamp, etc.
            Returns None if execution fails.
        
        Example:
            # Execute buy order immediately based on pre-computed signal
            result = engine.execute_immediate("HBL", "BUY", 100, reason="MA crossover detected")
            if result['success']:
                print(f"Bought {result['quantity']} @ {result['execution_price']:.2f}")
            
            # Execute sell order with specific price
            result = engine.execute_immediate("OGDC", "SELL", 50, price=95.50, reason="Take profit")
        
        ARCHITECTURE:
            - Bypasses bar-based execution queue
            - Executes immediately with current prices from WebSocket or REST
            - Local-first: No backend dependency for execution
            - Telemetry sent asynchronously (non-blocking)
        """
        if not self.config.allow_immediate_execution:
            log_line(
                f"⚠️ Immediate execution disabled (allow_immediate_execution=False). "
                f"Order for {symbol} will wait for next bar close."
            )
            return {
                'success': False,
                'error': 'Immediate execution disabled',
                'trade': None,
                'execution_price': 0.0,
                'quantity': 0,
                'commission': 0.0,
                'slippage_bps': 0.0,
            }
        
        symbol = symbol.upper().strip()
        side = side.upper().strip()
        
        if side not in ("BUY", "SELL"):
            log_line(f"❌ Invalid side '{side}'. Must be 'BUY' or 'SELL'.")
            return {
                'success': False,
                'error': f"Invalid side '{side}'",
                'trade': None,
                'execution_price': 0.0,
                'quantity': 0,
                'commission': 0.0,
                'slippage_bps': 0.0,
            }
        
        if quantity <= 0:
            log_line(f"❌ Invalid quantity {quantity}. Must be > 0.")
            return {
                'success': False,
                'error': f"Invalid quantity {quantity}",
                'trade': None,
                'execution_price': 0.0,
                'quantity': 0,
                'commission': 0.0,
                'slippage_bps': 0.0,
            }
        
        # Get executable price if not provided (ask for BUY, bid for SELL).
        if price is None:
            try:
                from ...data.paper_spread import mark_execution_price, synthetic_bid_ask_from_last

                price_data: Dict[str, Any] = {}
                try:
                    if hasattr(self.service, "get_price"):
                        raw = self.service.get_price(symbol)
                        price_data = raw if isinstance(raw, dict) else {"price": float(raw or 0)}
                except Exception:
                    price_data = {}

                mid = float(price_data.get("price") or 0.0)
                if mid <= 0 and self._using_websocket:
                    mid = float(self._last_seen_price.get(symbol) or 0)
                if mid > 0 and not price_data.get("price"):
                    price_data["price"] = mid

                price = mark_execution_price(price_data, side) if mid > 0 else 0.0
                if price <= 0 and mid > 0:
                    bid, ask = synthetic_bid_ask_from_last(mid)
                    price = ask if side == "BUY" else bid

                if price is None or price <= 0:
                    log_line(f"⚠️ No usable price for {symbol}. Skipping execution.")
                    return {
                        'success': False,
                        'error': f"No price available for {symbol}",
                        'trade': None,
                        'execution_price': 0.0,
                        'quantity': 0,
                        'commission': 0.0,
                        'slippage_bps': 0.0,
                    }
            except Exception as exc:
                log_line(f"❌ Failed to fetch price for {symbol}: {exc}")
                return {
                    'success': False,
                    'error': f"Failed to fetch price: {exc}",
                    'trade': None,
                    'execution_price': 0.0,
                    'quantity': 0,
                    'commission': 0.0,
                    'slippage_bps': 0.0,
                }
        
        # Execute the trade
        try:
            now_utc = now_tz()
            
            # Apply slippage if configured (on top of bid/ask edge).
            effective_price = float(price)
            slippage_bps = self.config.slippage_bps
            if slippage_bps > 0:
                slippage_factor = 1.0 + (slippage_bps / 10_000.0 if side == "BUY" else -slippage_bps / 10_000.0)
                effective_price = float(price) * slippage_factor
            
            # Calculate commission
            notional = effective_price * quantity
            commission = 0.0
            if self.config.commission_per_share > 0:
                commission += self.config.commission_per_share * quantity
            if self.config.commission_pct_notional > 0:
                commission += notional * self.config.commission_pct_notional
            
            # Execute through portfolio service
            if side == "BUY":
                result = self.portfolio.buy(
                    symbol=symbol,
                    qty=quantity,
                    price=effective_price,
                    timestamp=now_utc,
                    commission=commission,
                )
            else:  # SELL
                result = self.portfolio.sell(
                    symbol=symbol,
                    qty=quantity,
                    price=effective_price,
                    timestamp=now_utc,
                    commission=commission,
                )
            
            if not result or result.get("error"):
                error_msg = result.get("error", "Unknown error") if result else "Execution failed"
                log_line(f"❌ Trade execution failed for {symbol}: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'trade': None,
                    'execution_price': effective_price,
                    'quantity': quantity,
                    'commission': commission,
                    'slippage_bps': slippage_bps,
                }
            
            # Build trade record
            trade = {
                "timestamp": now_utc,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": effective_price,
                "notional": notional,
                "commission": commission,
                "slippage_bps": slippage_bps if slippage_bps > 0 else 0,
                "reason": reason or "immediate_execution",
                "source": "execute_immediate",
            }
            
            # Log to console
            log_line(
                f"✅ Immediate execution: {side} {quantity} {symbol} @ {effective_price:.2f} "
                f"(notional: {notional:,.0f}, fees: {commission:.2f})"
            )
            if reason:
                log_line(f"   Reason: {reason}")
            
            # Log to CSV
            try:
                self.csv_writer.write_trade(trade)
            except Exception as exc:
                log_line(f"⚠️ Failed to log trade to CSV: {exc}")
            
            # Send telemetry (non-blocking)
            try:
                if self._backend_client and not self.config.local_mode:
                    self._backend_client.log_trades([trade])
                    
                    # Send portfolio update
                    summary = self.portfolio.get_summary()
                    self._backend_client.update_portfolio(
                        equity=float(summary.equity),
                        cash=float(summary.cash),
                        positions=summary.positions,
                        positions_value=float(summary.positions_value),
                        timestamp=now_utc,
                        status="online",
                    )
            except Exception as exc:
                log_line(f"⚠️ Telemetry failed (non-blocking): {exc}")
            
            # Save account state
            try:
                summary = self.portfolio.get_summary()
                positions_dict = {
                    pos["symbol"]: {"qty": pos["qty"], "avg_cost": pos["avg_cost"]}
                    for pos in summary.positions
                }
                self.account_manager.save_account(
                    cash=float(summary.cash),
                    positions=positions_dict,
                    equity=float(summary.equity),
                )
            except Exception as exc:
                log_line(f"⚠️ Failed to save account state: {exc}")
            
            # Return success with trade details
            return {
                'success': True,
                'error': None,
                'trade': trade,
                'execution_price': effective_price,
                'quantity': quantity,
                'commission': commission,
                'slippage_bps': slippage_bps,
            }
            
        except Exception as exc:
            log_line(f"❌ Unexpected error during execution for {symbol}: {exc}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': f"Unexpected error: {exc}",
                'trade': None,
                'execution_price': 0.0,
                'quantity': 0,
                'commission': 0.0,
                'slippage_bps': 0.0,
            }


    async def run_forever(self, max_cycles: Optional[int] = None) -> None:
        """
        Continuous loop that runs until `stop()` is called or max_cycles is reached.
        Handles market hours, errors, and continues running across sessions.
        """
        self.start()
        
        # Sync initial portfolio state to backend (if positions were restored)
        self._sync_initial_portfolio()

        # Start real-time cash sync listener (backend -> bot).
        # This must run concurrently with the price websocket so cash changes are instant.
        if (
            self.config.backend_url
            and self.config.api_token
            and self.config.account_id
            and not self.config.local_mode
        ):
            self._account_update_stop_event = asyncio.Event()
            self._account_update_task = asyncio.create_task(
                self._account_update_listener_loop(),
                name=f"pytrader-account-update-{self.bot_id}",
            )
        
        # Check for queued signals on startup and execute if market is open
        now = now_tz()
        market_status = self._market_hours_service.get_status()
        can_trade = market_status.can_trade
        if can_trade and self._queued_signals:
            log_line("Market is open on startup. Processing queued signals...")
            self._process_queued_signals(now)
        
        # LIVE MODE: WebSocket event-driven execution
        if self._using_websocket:
            try:
                log_line("🔌 Starting WebSocket connection...")
                log_line("📡 DATA SOURCE: PyTrader backend /ws/market (synthesized REST heartbeat)")
                
                # Start WebSocket stream provider
                await self.service.start()
                
                # Fix 3: Log WebSocket connection success
                log_line("✅ WebSocket connection established successfully")
                log_line(f"📊 Subscribed to {len(self.symbols)} symbol(s): {', '.join(self.symbols)}")
                
                # Register bar close callback for event-driven strategy execution
                self.service.on_bar_close(self._on_websocket_bar_close)
                if hasattr(self.service, "on_raw_tick"):
                    self.service.on_raw_tick(self._on_backend_heartbeat_tick)
                
                # ARCHITECTURE: Initial strategy evaluation with seeded historical data
                # This allows strategies to evaluate immediately if historical data was seeded
                # (e.g., for indicator initialization) without waiting for next bar close
                self._evaluate_strategy_with_seeded_data()
                
                # Start real-time revaluation using WebSocket prices
                if self.config.revaluation_interval > 0 and not self._backend_is_source_of_truth():
                    self._revaluation_stop_event = asyncio.Event()
                    self._revaluation_task = asyncio.create_task(
                        self._websocket_revaluation_loop()
                    )
                    log_line(f"⚡ Started real-time portfolio revaluation (interval: {self.config.revaluation_interval}s)")
                
                log_line("✅ WebSocket connected. Streaming market data...")
                log_line("📊 Strategy will execute on bar close events")
                log_line("🚫 Live prices come from backend WS only (no direct PSX Terminal socket)\n")
                log_line("💡 Waiting for ticks and bar close events...")
                log_line("   - Bars close every 15 minutes (at :00, :15, :30, :45)")
                log_line("   - Strategy needs at least 14 bars of history for RSI calculation")
                log_line("   - If market is closed, no ticks will be received\n")
                
                # Periodic status updates to show we're still running
                last_status_time = now_tz()
                tick_count = 0
                
                # Keep running until stop signal
                while self.is_running:
                    await asyncio.sleep(1)  # Minimal sleep, work is event-driven
                    
                    # Show status every 30 seconds
                    now = now_tz()
                    if (now - last_status_time).total_seconds() >= 30:
                        # Check if we're receiving ticks
                        if hasattr(self.service, '_latest_prices') and self.service._latest_prices:
                            prices_count = len(self.service._latest_prices)
                            log_line(f"💓 WebSocket active | {prices_count} symbol(s) with price data | Waiting for bar close...")
                        else:
                            log_line("💓 WebSocket active | Waiting for ticks... (market may be closed)")
                        last_status_time = now
                
            except ConnectionError as e:
                log_line(f"❌ WebSocket connection failed: {e}")
                log_line("LIVE mode requires WebSocket connection. Stopping.")
                raise
            except asyncio.CancelledError:
                log_line("Gracefully stopping WebSocket engine...")
            finally:
                if hasattr(self.service, 'stop'):
                    await self.service.stop()
                log_line("WebSocket connection closed")
            return
        
        # TRADITIONAL MODE: Time-based cycling
        # Start real-time revaluation task for dashboard updates
        if self.config.revaluation_interval > 0 and not self._backend_is_source_of_truth():
            self._revaluation_stop_event = asyncio.Event()
            self._revaluation_task = asyncio.create_task(
                self._continuous_revaluation_loop()
            )
            log_line(f"⚡ Started real-time portfolio revaluation (interval: {self.config.revaluation_interval}s)")
        
        cycles = 0
        consecutive_errors = 0
        max_consecutive_errors = 10
        last_hourly_summary: Optional[datetime] = None
        try:
            while self.is_running:
                try:
                    await self.cycle_once()
                    consecutive_errors = 0  # Reset error counter on success
                    cycles += 1
                    
                    # Print hourly summary only if at least 1 hour has passed
                    now = now_tz()
                    if last_hourly_summary is None:
                        # First cycle - set initial time but don't print summary yet
                        last_hourly_summary = now
                    elif (now - last_hourly_summary).total_seconds() >= 3600:
                        # At least 1 hour has passed - print summary
                        self._print_hourly_summary(now)
                        last_hourly_summary = now
                    
                    if max_cycles is not None and cycles >= max_cycles:
                        log_line(f"Reached max_cycles ({max_cycles}). Stopping.")
                        break
                except asyncio.CancelledError:
                    log_line("Gracefully stopping live engine...")
                    break
                except KeyboardInterrupt:
                    log_line("Manual stop detected.")
                    break
                except Exception as exc:
                    consecutive_errors += 1
                    message = f"Cycle {cycles + 1} failed: {exc}"
                    log_line(message)
                    self._log_system_event(
                        event="cycle_error",
                        message=message,
                        level="error",
                        cycle=cycles + 1,
                    )
                    if consecutive_errors >= max_consecutive_errors:
                        warn_msg = f"Too many consecutive errors ({consecutive_errors}). Stopping."
                        log_line(warn_msg)
                        self._log_system_event(
                            event="cycle_error_limit",
                            message=warn_msg,
                            level="error",
                            consecutive_errors=consecutive_errors,
                        )
                        break
                    await asyncio.sleep(5.0)  # Brief pause before retrying
                    continue
                
                await self._sleep_until_next_cycle()
        except (KeyboardInterrupt, asyncio.CancelledError):
            log_line("Shutdown signal received. Stopping gracefully...")
        finally:
            self.stop()
            log_line(f"Session ended. Total cycles: {cycles}")

    def _initialize_history(self, now: datetime) -> None:
        """
        Warm start: Restore account state and revalue with current prices.
        
        ARCHITECTURE: This method is for warm start (backend portfolio sync), NOT historical data loading.
        - warm_start: Syncs portfolio state (cash, positions) from backend
        - Historical data seeding: Separate, user-controlled via seed_historical_bars()
        - In WebSocket mode: History comes from aggregator (seeded + WebSocket bars), not REST
        
        Historical replay is handled separately to ensure we process every
        completed cycle before switching to live mode.
        """
        # ARCHITECTURE: Guard against REST calls in WebSocket LIVE mode
        if self._using_websocket:
            # For WebSocket mode, history comes from aggregator
            # Prices will be available from WebSocket stream
            log_line("WebSocket mode: Skipping REST-based history initialization. "
                    "History will come from WebSocket aggregator.")
            return
        
        # Load current market prices for all symbols (today's data only)
        current_prices: Dict[str, float] = {}
        
        # Get latest prices from market feed (today's trades only)
        for symbol in self.symbols:
            try:
                # Load intraday data with strict today filtering
                df_full = self._load_symbol_history(
                    symbol,
                    up_to=now,
                    use_cache=self.config.use_cache,
                    publish=False,
                )
                self._intraday_cache[symbol] = df_full
                self._session_data[symbol] = df_full
                if not df_full.empty:
                    # Get the most recent price from today
                    latest_price = float(df_full["price"].iloc[-1])
                    current_prices[symbol] = latest_price
                    ts_series = cast(pd.Series, df_full["ts"])
                    last_ts = pd.Timestamp(ts_series.max())
                    if pd.notna(last_ts):
                        self._last_seen_ts[symbol] = last_ts
                elif symbol in self._symbol_open_price_today:
                    # No trades yet today, but we have first price cached
                    current_prices[symbol] = self._symbol_open_price_today[symbol]
                    log_line(f"[{symbol}] Using today's first price: {current_prices[symbol]:.2f}")
            except Exception as exc:
                log_line(f"Could not load price for {symbol} during warm start: {exc}")
                # Try to get price from portfolio if position exists
                summary = self.portfolio.get_summary()
                for pos in summary.positions:
                    if pos["symbol"] == symbol and pos.get("avg_cost", 0.0) > 0:
                        current_prices[symbol] = pos["avg_cost"]
                        break
        
        # Revalue portfolio with current prices (this updates unrealized PnL and equity)
        if current_prices:
            self.portfolio.revalue_and_snapshot(now, current_prices)
            log_line(f"Revalued portfolio with current market prices for {len(current_prices)} symbols")
        else:
            log_line("Warning: No prices available for warm start. Portfolio not revalued.")
        
        self._log_daily_first_trades()
        
        # Get final summary after revaluation
        summary = self.portfolio.get_summary()
        
        # Log warm start completion
        if summary.positions:
            pos_count = len(summary.positions)
            log_line(f"Warm start: Restored {pos_count} positions, cash: {summary.cash:,.0f} PKR, equity: {summary.equity:,.0f} PKR")
        else:
            log_line(f"Warm start: No previous positions, cash: {summary.cash:,.0f} PKR, equity: {summary.equity:,.0f} PKR")
        self._session_start_equity = float(summary.equity)

        # Prime signal snapshots without executing trades
        for symbol, df_full in self._session_data.items():
            if df_full is None or df_full.empty:
                continue
            snapshot, _ = self._build_signal_snapshot(symbol, df_full, now)
            if snapshot:
                self._active_signals[symbol] = snapshot
        log_line("Warm start: Signals primed from cumulative intraday data (no trades executed).")

    def _on_backend_heartbeat_tick(self, tick: Any) -> None:
        """
        Each backend price pulse updates local shadow-ledger MTM (bid marks for longs).
        Keeps portfolio.equity / unrealized in sync between bar closes.
        """
        try:
            if self._backend_is_source_of_truth():
                return
            if not hasattr(self.service, "get_mtm_prices"):
                return
            marks = self.service.get_mtm_prices()
            if not marks:
                return
            self.portfolio.revalue_and_snapshot(now_tz(), marks)
        except Exception as exc:
            logger.debug("Heartbeat revalue skipped: %s", exc)

    def _on_websocket_bar_close(self, bar: AggregatedBar) -> None:
        """
        Callback handler for WebSocket bar close events.
        
        ARCHITECTURE: This is the ONLY way strategy execution happens in WebSocket LIVE mode.
        Called by WebSocketStreamProvider when a bar period completes.
        
        The bar history includes:
        - Seeded historical bars (from pypsx library, if provided)
        - Bars accumulated from WebSocket ticks since connection start
        
        Args:
            bar: Completed aggregated bar from WebSocket ticks
        """
        try:
            symbol = bar.symbol
            
            # Get full history from aggregator for indicators
            # This includes seeded historical bars + WebSocket bars
            history_df = self.service.get_bar_history(symbol)
            
            # Log bar close with timestamp and confirm data source
            bar_time_str = bar.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')
            bar_count = len(history_df) if history_df is not None and not history_df.empty else 0
            log_line(f"📊 Bar closed: {symbol} @ {bar_time_str} | "
                    f"OHLC: {bar.open:.2f}/{bar.high:.2f}/{bar.low:.2f}/{bar.close:.2f} | V:{bar.volume:,} | "
                    f"Total bars: {bar_count} | Source: WebSocket (aggregated from ticks)")
            
            # Execute strategy with bar data (includes historical + new bar)
            if history_df is not None and not history_df.empty:
                self._execute_strategy_for_symbol(symbol, history_df, bar.timestamp)
            else:
                log_line(f"⚠️  {symbol}: No bar history available yet (first bar)")
            
        except Exception as e:
            log_line(f"❌ Error handling bar close for {bar.symbol}: {e}", exc_info=True)
    
    async def _websocket_revaluation_loop(self) -> None:
        """
        Continuous revaluation loop using WebSocket prices.
        
        Fetches latest prices from WebSocket stream provider and revalues portfolio
        for real-time dashboard updates.
        """
        try:
            while not self._revaluation_stop_event.is_set():
                try:
                    # Get latest prices from WebSocket
                    current_prices = self.service.get_latest_prices()
                    
                    if current_prices:
                        now = now_tz()
                        await asyncio.to_thread(
                            self._publish_revaluation_update,
                            now,
                            current_prices
                        )
                    
                    # Sleep until next revaluation
                    await asyncio.sleep(self.config.revaluation_interval)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log_line(f"Revaluation error: {e}")
                    await asyncio.sleep(self.config.revaluation_interval)
                    
        except asyncio.CancelledError:
            log_line("Revaluation loop stopped")
        finally:
            log_line("WebSocket revaluation loop ended")

    async def _account_update_listener_loop(self) -> None:
        """
        Listen for backend cash mutation signals and overwrite local cash immediately.

        Backend emits:
          {"event": "ACCOUNT_UPDATE", "account_id": "...", "new_cash": 1050000}
        """
        if not self._account_update_stop_event:
            self._account_update_stop_event = asyncio.Event()

        stop_event = self._account_update_stop_event

        base = (self.config.backend_url or "").rstrip("/")
        if base.startswith("https://"):
            ws_base = base.replace("https://", "wss://", 1)
        elif base.startswith("http://"):
            ws_base = base.replace("http://", "ws://", 1)
        else:
            ws_base = base

        ws_url = (
            f"{ws_base}/ws/account_updates/me"
            f"?token={self.config.api_token}"
            f"&account_id={self.config.account_id}"
        )

        import websockets

        backoff_s = 1.0
        while not stop_event.is_set():
            try:
                async with websockets.connect(ws_url, ping_interval=30) as ws:
                    backoff_s = 1.0
                    log_line(f"🔔 ACCOUNT_UPDATE listener connected | account_id={self.config.account_id}")

                    while not stop_event.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=60.0)
                        except asyncio.TimeoutError:
                            continue

                        if raw is None:
                            continue

                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue

                        if not isinstance(msg, dict):
                            continue
                        if msg.get("event") != "ACCOUNT_UPDATE":
                            continue

                        new_cash = float(msg.get("new_cash") or 0.0)
                        self.portfolio.overwrite_cash(new_cash)

                        # Persist so restarts keep the same injected cash mid-session.
                        try:
                            summary = self.portfolio.get_summary()
                            positions_dict = {
                                pos["symbol"]: {"qty": pos["qty"], "avg_cost": pos["avg_cost"]}
                                for pos in summary.positions
                            }
                            self.account_manager.save_account(
                                cash=float(summary.cash),
                                positions=positions_dict,
                                equity=float(summary.equity),
                            )
                        except Exception:
                            pass

                        log_line(f"💰 ACCOUNT_UPDATE received | new_cash={new_cash:,.0f}")

            except asyncio.CancelledError:
                break
            except Exception as exc:
                if stop_event.is_set():
                    break
                log_line(
                    f"⚠️ ACCOUNT_UPDATE listener error: {exc}. Reconnecting in {backoff_s:.1f}s"
                )
                await asyncio.sleep(backoff_s)
                backoff_s = min(30.0, backoff_s * 2.0)

    def _backend_is_source_of_truth(self) -> bool:
        """Use backend-managed valuation when a backend session is configured."""
        return bool(self._backend_client and self.config.backend_url and self.config.api_token and not self.config.local_mode)
            
    def _evaluate_strategy_with_seeded_data(self) -> None:
        """
        One-time initial strategy evaluation using seeded historical data.
        
        ARCHITECTURE: This allows strategies to evaluate immediately after historical
        data is seeded (e.g., for indicator initialization) without waiting for
        the next bar close event.
        
        This is called ONCE after WebSocket connection and historical seeding,
        before waiting for live bar close events.
        
        Only runs if:
        - Using WebSocket mode
        - Historical bars exist in aggregator (from seeding)
        """
        if not self._using_websocket:
            return  # Only for WebSocket mode
        
        if not hasattr(self.service, 'get_bar_history'):
            return  # Service doesn't support bar history
        
        log_line("\n" + "="*70)
        log_line("🔍 Initial Strategy Evaluation with Seeded Historical Data")
        log_line("="*70)
        
        evaluated_count = 0
        skipped_count = 0
        
        for symbol in self.symbols:
            try:
                # Get bar history (includes seeded bars)
                history_df = self.service.get_bar_history(symbol)
                
                if history_df is None or history_df.empty:
                    skipped_count += 1
                    log_line(f"  ⏭️  {symbol}: No historical bars (will wait for WebSocket bars)")
                    continue
                
                bar_count = len(history_df)
                log_line(f"  📊 {symbol}: {bar_count} bar(s) available")
                
                # Execute strategy with historical data
                # Use the most recent bar's timestamp
                if 'timestamp' in history_df.columns:
                    latest_timestamp = pd.to_datetime(history_df['timestamp'].iloc[-1])
                    if isinstance(latest_timestamp, pd.Timestamp):
                        latest_timestamp = latest_timestamp.to_pydatetime()
                else:
                    latest_timestamp = now_tz()
                
                self._execute_strategy_for_symbol(symbol, history_df, latest_timestamp)
                evaluated_count += 1
                
            except Exception as e:
                log_line(f"  ❌ {symbol}: Error during initial evaluation: {e}")
                skipped_count += 1
        
        log_line("="*70)
        if evaluated_count > 0:
            log_line(f"✅ Initial evaluation complete: {evaluated_count} symbol(s) evaluated")
            log_line(f"⏭️  Skipped: {skipped_count} symbol(s) (no historical data)")
            log_line("📊 Strategy will now react to live WebSocket bar close events")
        else:
            log_line(f"ℹ️  No symbols evaluated (no seeded historical data)")
            log_line("📊 Strategy will evaluate when first bar closes from WebSocket")
        log_line("="*70 + "\n")
    
    def _execute_strategy_for_symbol(self, symbol: str, df: pd.DataFrame, timestamp: datetime) -> None:
        """
        Execute strategy logic for a single symbol.
        
        ARCHITECTURE: This method processes strategy orders immediately after on_data().
        All orders flow through the engine's unified execution pipeline.
        
        Args:
            symbol: Symbol to execute strategy for
            df: Historical bar data with indicators
            timestamp: Current bar close timestamp
        """
        try:
            # Call strategy's on_data method
            if hasattr(self.strategy, 'on_data'):
                # Create symbol -> DataFrame mapping
                data = {symbol: df}
                self.strategy.on_data(data)
            
            # Process any orders generated by the strategy
            # This ensures all orders flow through the engine's execution pipeline
            orders = self.strategy.get_orders()
            if orders:
                for order in orders:
                    order_symbol = order.get('symbol', '').upper()
                    # Only process orders for the current symbol (or all if multi-symbol strategy)
                    if order_symbol == symbol.upper() or not hasattr(self.strategy, 'symbols'):
                        try:
                            self.execute_order(
                                symbol=order_symbol,
                                side=order.get('side', 'BUY'),
                                quantity=order.get('quantity', 0),
                                execution_timestamp=timestamp,
                                source='strategy_bar_close'
                            )
                        except Exception as order_exc:
                            log_line(f"Failed to execute strategy order for {order_symbol}: {order_exc}", exc_info=True)
                
                # Clear processed orders
                self.strategy.clear_orders()
            
        except Exception as e:
            log_line(f"Strategy execution error for {symbol}: {e}", exc_info=True)


    async def _continuous_revaluation_loop(self) -> None:
        """
        Continuous background loop for portfolio revaluation (TRADITIONAL mode only).
        
        ARCHITECTURE: This method should NOT be called in WebSocket LIVE mode.
        In WebSocket mode, use _websocket_revaluation_loop() instead.
        
        This method is for traditional mode (non-WebSocket) only and may use REST fallbacks.
        """
        # ARCHITECTURE: Strictly block REST fallback in WebSocket LIVE mode
        if self._using_websocket and self._trading_mode == TradingMode.LIVE:
            raise RuntimeError(
                "ARCHITECTURE VIOLATION: _continuous_revaluation_loop() should not be called "
                "in WebSocket LIVE mode. Use _websocket_revaluation_loop() instead."
            )
        
        # If using WebSocketStreamProvider (but not LIVE mode), use WebSocket revaluation
        if self._using_websocket:
            await self._websocket_revaluation_loop()
            return
        
        # TRADITIONAL MODE: REST-based revaluation (for backtesting/legacy modes)
        # This path is NOT used in LIVE mode - it's for backward compatibility only
        from ...data.websocket_client import PSXWebSocketClient, TickData
        
        ws_client: Optional[PSXWebSocketClient] = None
        use_websocket = True
        last_revaluation = time.time()
        
        try:
            # Try to initialize WebSocket (for traditional mode, not LIVE)
            if use_websocket:
                try:
                    ws_client = PSXWebSocketClient()
                    
                    def on_price_update(tick: TickData):
                        """Handle WebSocket price update - revalue immediately"""
                        nonlocal last_revaluation
                        
                        # Throttle to min 1 second between revaluations
                        now_time = time.time()
                        if now_time - last_revaluation < 1.0:
                            return
                        
                        try:
                            summary = self.portfolio.get_summary()
                            if not summary.positions:
                                return
                            
                            # Get prices from WebSocket cache
                            current_prices = ws_client.get_cached_prices()
                            if not current_prices:
                                return
                            
                            # Filter to positions we hold
                            position_prices = {
                                pos["symbol"]: current_prices.get(pos["symbol"], self._last_seen_price.get(pos["symbol"], 0))
                                for pos in summary.positions
                            }
                            
                            # Revalue
                            now = now_tz()
                            self.portfolio.revalue_and_snapshot(now, position_prices)
                            self._last_seen_price.update(position_prices)
                            
                            # Publish to dashboard
                            self._publish_revaluation_update(now, position_prices)
                            
                            last_revaluation = now_time
                        except Exception as exc:
                            logger.debug(f"Error in WebSocket callback: {exc}")
                    
                    ws_client.register_tick_callback(on_price_update)
                    
                    # Start WebSocket
                    symbols_to_track = list(self.symbols)
                    summary = self.portfolio.get_summary()
                    for pos in summary.positions:
                        if pos["symbol"] not in symbols_to_track:
                            symbols_to_track.append(pos["symbol"])
                    
                    logger.info(f"🔌 Starting WebSocket for {len(symbols_to_track)} symbols...")
                    await ws_client.start(symbols=symbols_to_track)
                    logger.info("✅ WebSocket connected - real-time streaming active")
                    
                except Exception as e:
                    logger.warning(f"WebSocket failed: {e}. Using REST fallback (traditional mode only).")
                    use_websocket = False
                    ws_client = None
            
            # Main loop (TRADITIONAL MODE ONLY - not LIVE)
            while not self._revaluation_stop_event.is_set():
                try:
                    # WebSocket mode: callbacks handle updates
                    if use_websocket and ws_client and ws_client.is_connected:
                        await asyncio.sleep(5.0)
                        
                        # Add new position symbols
                        summary = self.portfolio.get_summary()
                        for pos in summary.positions:
                            if pos["symbol"] not in ws_client.subscribed_symbols:
                                ws_client.add_symbol(pos["symbol"])
                        continue
                    
                    # REST fallback (TRADITIONAL MODE ONLY - NOT LIVE)
                    # ARCHITECTURE: This should never execute in LIVE mode
                    if self._trading_mode == TradingMode.LIVE:
                        logger.error(
                            "❌ ARCHITECTURE VIOLATION: REST fallback attempted in LIVE mode! "
                            "This should never happen. WebSocket should be the only data source. "
                            "Stopping revaluation loop."
                        )
                        break
                    
                    summary = self.portfolio.get_summary()
                    if not summary.positions:
                        await asyncio.sleep(self.config.revaluation_interval)
                        continue
                    
                    market_status = self._market_hours_service.get_status()
                    if not market_status.is_open:
                        await asyncio.sleep(min(self.config.revaluation_interval * 4, 300))
                        continue
                    
                    # Fetch mark-to-market prices via REST (bid for longs, ask for shorts).
                    current_prices: Dict[str, float] = {}
                    for pos in summary.positions:
                        symbol = pos["symbol"]
                        try:
                            price_data = self.service.get_price(symbol)
                            if price_data and "price" in price_data:
                                from ...data.paper_spread import mark_to_market_price

                                qty = float(pos.get("qty") or 0.0)
                                current_prices[symbol] = mark_to_market_price(price_data, qty=qty)
                        except Exception as exc:
                            logger.debug(f"Could not fetch {symbol}: {exc}")
                            if symbol in self._last_seen_price:
                                from ...data.paper_spread import synthetic_bid_ask_from_last

                                mid = float(self._last_seen_price[symbol])
                                bid, ask = synthetic_bid_ask_from_last(mid)
                                q = float(pos.get("qty") or 0.0)
                                current_prices[symbol] = ask if q < 0 else bid
                    
                    if current_prices:
                        now = now_tz()
                        self.portfolio.revalue_and_snapshot(now, current_prices)
                        self._last_seen_price.update(current_prices)
                        self._publish_revaluation_update(now, current_prices)
                    
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.debug(f"Error in revaluation loop: {exc}")
                
                # Sleep (REST mode - TRADITIONAL ONLY)
                if not use_websocket:
                    try:
                        await asyncio.wait_for(
                            self._revaluation_stop_event.wait(),
                            timeout=self.config.revaluation_interval
                        )
                        break
                    except asyncio.TimeoutError:
                        pass
                
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log_line(f"Fatal error in revaluation loop: {exc}")
        finally:
            if ws_client:
                try:
                    await ws_client.stop()
                except Exception:
                    pass
    
    def _publish_revaluation_update(self, now: datetime, current_prices: Dict[str, float]) -> None:
        """Publish portfolio revaluation to dashboard"""
        try:
            if not hasattr(self, "_telemetry") or not self._telemetry:
                return

            telemetry_data = None
            if self._backend_is_source_of_truth():
                try:
                    backend_valuation = self._backend_client.get_portfolio_valuation(
                        mode="PAPER",
                        bot_id=self.bot_id,
                        refresh=True,
                    )
                    telemetry_data = {
                        "timestamp": backend_valuation.get("timestamp", now.isoformat()),
                        "type": "revaluation",
                        "bot_id": self.bot_id,
                        "equity": backend_valuation.get("equity"),
                        "cash": backend_valuation.get("cash"),
                        "positions_value": backend_valuation.get("positions_value"),
                        "positions": backend_valuation.get("positions", []),
                        "equity_curve": [],
                        "metrics": {},
                    }
                except Exception as backend_exc:
                    log_line(f"Backend valuation fallback failed: {backend_exc}")

            if telemetry_data is None:
                from ...trader_core.portfolio.metrics import compute_portfolio_metrics

                metrics_payload = compute_portfolio_metrics(
                    portfolio=self.portfolio,
                    timestamp=now,
                    latest_prices=current_prices,
                    initial_capital=self._initial_capital,
                )

                telemetry_data = {
                    "timestamp": now.isoformat(),
                    "type": "revaluation",
                    "bot_id": self.bot_id,
                    "equity": metrics_payload.get("equity"),
                    "cash": metrics_payload.get("cash"),
                    "positions_value": metrics_payload.get("positions_value"),
                    "positions": metrics_payload.get("positions", []),
                    "equity_curve": metrics_payload.get("equity_curve", []),
                    "metrics": {
                        "total_return_pct": metrics_payload["metrics"].total_return_pct,
                        "session_return_pct": metrics_payload["metrics"].session_return_pct,
                        "cumulative_return_pct": metrics_payload["metrics"].cumulative_return_pct,
                        "unrealized_pnl": metrics_payload.get("unrealized_pnl"),
                        "realized_pnl": metrics_payload.get("realized_pnl"),
                        "exposure_pct": metrics_payload["metrics"].exposure_pct,
                    },
                }

            # For CallbackTelemetry (dashboard), call callback directly with dict
            # For other telemetry types, they expect CycleReport, so skip revaluation updates
            if isinstance(self._telemetry, CompositeTelemetry):
                # Check if any sink is CallbackTelemetry
                for sink in self._telemetry._sinks:
                    if isinstance(sink, CallbackTelemetry) and hasattr(sink, '_callback') and sink._callback:
                        try:
                            sink._callback(telemetry_data)
                        except Exception:
                            pass  # Silently ignore callback errors for revaluation
            elif isinstance(self._telemetry, CallbackTelemetry) and hasattr(self._telemetry, '_callback') and self._telemetry._callback:
                try:
                    self._telemetry._callback(telemetry_data)
                except Exception:
                    pass  # Silently ignore callback errors for revaluation
        except Exception as exc:
            # Use log_line for consistency (logger may not be accessible in thread context)
            log_line(f"Error publishing revaluation: {exc}")


    async def _sync_positions_with_backend(self) -> None:
        """Sync local portfolio with backend order executions."""
        if not self._backend_client:
            return
        
        try:
            # First sync or periodic sync
            last_sync = getattr(self, "_last_sync_time", None)
            start_time = last_sync.isoformat() if last_sync else None
            
            executions = self._backend_client.get_order_executions(
                since=start_time,
                limit=100
            )
            
            if executions:
                log_line(f"Syncing {len(executions)} executions from backend...")
                for execution in executions:
                    # Avoid duplicate processing if we have local trade history?
                    # For now just apply blindly or check if trade id exists?
                    # The portfolio service tracks trades. 
                    # Simpler approach: Reconstruct portfolio from backend positions endpoint?
                    # But we want to maintain local state continuity.
                    
                    # Just update positions for now
                    sym = execution['symbol']
                    qty = float(execution['quantity'])
                    price = float(execution['price'])
                    side = execution['side']
                    
                    # We rely on portfolio service to track pnl
                    if side == 'BUY':
                        self.portfolio.buy(sym, qty, price)
                    else:
                        self.portfolio.sell(sym, qty, price)
                
                self._last_sync_time = datetime.now(timezone.utc)
                log_line("Portfolio synced with backend executions.")
                
        except Exception as exc:
            log_line(f"Failed to sync with backend: {exc}")

    async def cycle_once(self) -> None:
        if not self.is_running:
            return
        if not self.is_running:
            return
        
        # Sync with backend executions (authoritative source)
        if self.config.backend_url:
            await self._sync_positions_with_backend()
            
        now = now_tz()
        
        # Check if market day has changed (reset tracking)
        if self._today_date and now.date() != self._today_date:
            log_line("Market day changed. Resetting first trade tracking.")
            self._today_date = now.date()
            self._symbol_first_trade_time.clear()
            self._symbol_open_price_today.clear()
            self._last_seen_ts.clear()
            self._off_hours_scan_done = False  # Reset to allow new off-hours scan on new market day
            self._refresh_session_baseline()
        
        # Check if we're in paper trading window (includes post-market data processing)
        market_status = self._market_hours_service.get_status()
        can_paper_trade = market_status.can_paper_trade
        market_is_open = market_status.is_open
        can_trade = market_status.can_trade
        
        if not can_paper_trade:
            # Outside paper trading window - run off-hours scan if not done yet
            if not self._off_hours_scan_done:
                self._run_off_hours_scan()
                return
            
            # Off-hours scan already done - just log queued signals and sleep
            if self._queued_signals:
                log_line(f"Paper trading closed. {len(self._queued_signals)} signal(s) queued for next market open.")
            
            # Market fully closed - skip first trade check and go to sleep
            # The sleep will happen in _sleep_until_next_cycle()
            cycle_end = self._determine_cycle_end(now)
            if cycle_end is None:
                # No cycle to process, just sleep until next market open
                await self._sleep_until_next_cycle()
                return
            # If cycle_end is set, continue to process cycle (shouldn't happen when market closed, but handle gracefully)
            
        elif market_is_open and not can_trade:
            # Market is open but data not yet available (waiting for first 15-min batch)
            local_time = now.astimezone(self._local_tz) if hasattr(self, "_local_tz") and self._local_tz else now
            message = f"Waiting for first data batch (15-min delay). Market opened at 9:32 AM, data available ~9:45 AM..."
            log_line(message)
            self._log_system_event(
                event="waiting_for_data",
                message=message,
                level="info",
                local_time=local_time.isoformat(),
            )
            await asyncio.sleep(30.0)  # Retry after 30 seconds
            return
        
        
        # Load and process queued orders from BACKEND ONLY when market opens
        if market_is_open and can_trade:
            if self._backend_client:
                try:
                    # Fetch QUEUED orders from backend for this bot
                    queued_orders_resp = self._backend_client._reader.get(
                        f"{self._backend_client.base_url}/orders",
                        params={"status": "QUEUED", "bot_id": self.bot_id, "limit": 1000},
                        headers={
                            "X-PyTrader-Token": self._backend_client.api_token,
                            "x-trading-mode": "live",
                        }
                    )
                    queued_orders_resp.raise_for_status()
                    queued_orders_data = queued_orders_resp.json()
                    queued_orders = queued_orders_data.get("orders", [])
                    
                    if queued_orders:
                        log_line(f"✓ Found {len(queued_orders)} queued order(s) from backend. Processing...")
                        self._process_backend_queued_orders(queued_orders, now)
                    else:
                        log_line(f"✓ No queued orders found in backend for {self.bot_id}")
                except Exception as exc:
                    log_line(f"❌ Failed to load queued orders from backend: {exc}")
            else:
                log_line(f"⚠️ No backend client configured - cannot load queued orders")
        
        
        # Check if we're still waiting for first trade per symbol (only if market is open)
        # Skip this check if market is closed - off-hours scan uses fallback data
        # ARCHITECTURE: In WebSocket mode, skip REST-based data loading
        if self._using_websocket:
            # WebSocket mode: First trades come from WebSocket ticks, not REST
            # Skip this check - WebSocket will provide data as ticks arrive
            pass
        elif can_paper_trade:
            missing_first_trades = [sym for sym in self.symbols if sym not in self._symbol_first_trade_time]
            if missing_first_trades:
                for sym in missing_first_trades:
                    try:
                        self._load_symbol_history(sym, up_to=now, use_cache=False, publish=False)
                    except Exception:
                        continue
                if not self._symbol_first_trade_time:
                    log_line("Waiting for today's first market trade...")
                    await asyncio.sleep(30.0)  # Retry after 30 seconds
                    return
        cycle_end = self._determine_cycle_end(now)
        if cycle_end is None:
            # If we have a last cycle, calculate when the next one should be
            if self._last_cycle_close is not None:
                next_expected = self._last_cycle_close + self._cycle_delta
                session_end = self._session_end
                if session_end is not None and next_expected > session_end:
                    last_cycle_str = self._format_local_time(self._last_cycle_close)
                    print(f"\n⏸️  Market session ended. Last cycle was at {last_cycle_str}\n")
                else:
                    local_time = now.astimezone(self._local_tz) if hasattr(self, "_local_tz") and self._local_tz else now
                    next_local = next_expected.astimezone(self._local_tz) if hasattr(self, "_local_tz") and self._local_tz else next_expected
                    next_label = self._format_local_time(next_local)
                    current_label = self._format_local_time(local_time)
                    print(f"\n⏸️  Waiting for next cycle at {next_label} (current: {current_label})\n")
            return
        try:
            self._process_cycle(cycle_end, telemetry=True, warm_start=False, log_warm=False)
        except Exception as exc:
            log_line(f"Cycle processing failed: {exc}. Continuing to next cycle...")
            import traceback
            log_line(f"Traceback details: {traceback.format_exc()}")

    def _run_off_hours_scan(self) -> None:
        """Run a single strategy scan using the most recent available data."""
        self._off_hours_scan_done = True
        log_line("\n" + "=" * 70)
        log_line("🌙 MARKET CLOSED: Running off-hours strategy scan...")
        log_line("=" * 70)
        
        # Use a fake cycle end time (now) for the scan
        scan_time = now_tz()
        
        try:
            # Force process cycle with fallback enabled
            self._process_cycle(
                scan_time, 
                telemetry=False, # Don't publish off-hours data to stream
                warm_start=False, 
                log_warm=False,
                fallback_to_recent=True # ENABLE FALLBACK
            )
            
            # Report queued signals
            queued_count = len(self._queued_signals)
            if queued_count > 0:
                log_line("=" * 70)
                log_line(f"✅ OFF-HOURS SCAN COMPLETE: {queued_count} signal(s) queued for next market open.")
                for sig in self._queued_signals:
                    log_line(f"   -> {sig.symbol}: {sig.side} {sig.target_qty} @ ~{sig.signal_price:.2f}")
                log_line("=" * 70 + "\n")
                
                # All signals are now automatically persisted to SQLite storage
            else:
                log_line("✅ OFF-HOURS SCAN COMPLETE: No signals generated.\n")
                
        except Exception as exc:
            log_line(f"Off-hours scan failed: {exc}")
            import traceback
            log_line(traceback.format_exc())

    def _determine_cycle_end(self, now: datetime) -> Optional[datetime]:
        if self._session_start is None or self._session_end is None:
            self._session_start, session_market_close = today_session_window(now)
            # Extend session end by 15 minutes to allow processing final batch
            self._session_end = session_market_close + timedelta(minutes=15)
        if now < self._session_start:
            return None
        if self._sleep_seconds is not None:
            # Dev mode: run cycles immediately
            base = self._last_cycle_close or self._session_start
            return base + self._cycle_delta
        # Normal mode: align to cycle boundaries
        cycle_end = self._floor_to_cycle(now)
        # If we've already processed this exact cycle, wait for the next one
        if self._last_cycle_close is not None and cycle_end <= self._last_cycle_close:
            return None
        # If cycle_end is before session start, use session start as first cycle
        if cycle_end < self._session_start:
            cycle_end = self._session_start
        if cycle_end > self._session_end:
            return None
        return cycle_end

    def _process_cycle(
        self,
        cycle_end: datetime,
        *,
        telemetry: bool,
        warm_start: bool,
        log_warm: bool,
        fallback_to_recent: bool = False,
    ) -> None:
        """
        Process a single trading cycle.
        
        ARCHITECTURE: This method should NOT be called in WebSocket LIVE mode.
        In WebSocket mode, strategy execution happens via _on_websocket_bar_close() callback.
        """
        # ARCHITECTURE: Block REST-based cycle processing in WebSocket LIVE mode
        if self._using_websocket and self._trading_mode == TradingMode.LIVE:
            raise RuntimeError(
                "_process_cycle() should not be called in WebSocket LIVE mode. "
                "Strategy execution happens via _on_websocket_bar_close() callback."
            )
        
        if self._session_start is None:
            return
        if self._last_cycle_close is None:
            self._last_cycle_close = self._session_start
        cycle_start = self._last_cycle_close
        portfolio_summary = self.portfolio.get_summary()
        summary_positions = {pos["symbol"]: pos["qty"] for pos in portfolio_summary.positions}
        cash_bucket = {"value": float(portfolio_summary.cash)}
        prices: Dict[str, float] = {}
        cycle_trades: List[Dict[str, Any]] = []
        batch_reports: List[Dict[str, Any]] = []
        cycle_commission_total = 0.0
        slippage_weighted_sum = 0.0
        slippage_qty_total = 0

        for symbol in self.symbols:
            try:
                df_full = self._load_symbol_history(
                    symbol,
                    up_to=cycle_end,
                    use_cache=self.config.use_cache,
                    publish=telemetry,
                    fallback_to_recent=fallback_to_recent,
                )
                self._intraday_cache[symbol] = df_full
                self._session_data[symbol] = df_full
                if df_full.empty:
                    if symbol not in self._symbol_first_trade_time:
                        if not warm_start:
                            log_line(f"[{symbol}] Waiting for today's first trade...")
                    elif not warm_start:
                        cycle_label = self._format_local_time(cycle_end)
                        message = f"No data available for {symbol} in cycle {cycle_label}."
                        log_line(message)
                        self._log_system_event(
                            event="missing_market_data",
                            message=message,
                            level="warning",
                            symbol=symbol,
                            cycle_end=cycle_end.isoformat(),
                        )
                    batch_reports.append(
                        self._summarize_empty_batch(symbol, cycle_start, cycle_end)
                    )
                    continue

                last_price = float(df_full["price"].iloc[-1])
                prices[symbol] = last_price
                self._last_seen_price[symbol] = last_price
                prev_snapshot = self._active_signals.get(symbol)
                snapshot, summary = self._build_signal_snapshot(symbol, df_full, cycle_end)
                signal_status = "no_signal"
                snapshot_to_execute: Optional[SignalSnapshot] = None

                if prev_snapshot and prev_snapshot.executed_at is None:
                    snapshot_to_execute = prev_snapshot
                    signal_status = "execute_pending"
                    if snapshot and not self._signals_equal(prev_snapshot, snapshot):
                        self._active_signals[symbol] = snapshot
                    elif snapshot:
                        self._active_signals[symbol] = prev_snapshot
                    else:
                        self._active_signals[symbol] = prev_snapshot
                elif snapshot:
                    if prev_snapshot and self._signals_equal(prev_snapshot, snapshot):
                        signal_status = "unchanged"
                        self._active_signals[symbol] = prev_snapshot
                    else:
                        self._active_signals[symbol] = snapshot
                        snapshot_to_execute = snapshot
                        signal_status = "refreshed"
                else:
                    self._active_signals.pop(symbol, None)

                summary["signal_status"] = signal_status
                batch_reports.append(summary)

                self._log_system_event(
                    event="signal_status",
                    message=f"{symbol} signal {signal_status}",
                    level="info",
                    symbol=symbol,
                    status=signal_status,
                    side=(snapshot_to_execute.side if snapshot_to_execute else (snapshot.side if snapshot else None)),
                    qty=(snapshot_to_execute.target_qty if snapshot_to_execute else (snapshot.target_qty if snapshot else 0)),
                )


                if warm_start or snapshot_to_execute is None:
                    summary["note"] = summary.get("note", "signal_pending")
                    continue

                # Check if market is open and can trade (accounting for 15-min delay)
                cycle_status = self._market_hours_service.get_status()
                market_is_open = cycle_status.is_open
                can_trade_now = cycle_status.can_trade
                
                if not can_trade_now:
                    # Market is closed - queue order to BACKEND ONLY (no fallback)
                    if snapshot_to_execute.side in {"BUY", "SELL"}:
                        if self._backend_client:
                            try:
                                order_resp = self._backend_client.create_order(
                                    symbol=snapshot_to_execute.symbol,
                                    side=snapshot_to_execute.side,
                                    quantity=snapshot_to_execute.target_qty,
                                    order_type='MARKET',
                                )
                                log_line(f"[{self.bot_id}] ✓ Order queued to backend: {snapshot_to_execute.symbol} {snapshot_to_execute.side} x {snapshot_to_execute.target_qty}")
                                summary["note"] = "queued_to_backend"
                                summary["execution_side"] = snapshot_to_execute.side or "HOLD"
                                summary["executed_qty"] = 0
                                summary["execution_price"] = None
                                self._log_system_event(
                                    event="signal_queued",
                                    message=f"{symbol} {snapshot_to_execute.side} signal queued to backend for next market open",
                                    level="info",
                                    symbol=symbol,
                                    side=snapshot_to_execute.side,
                                    qty=snapshot_to_execute.target_qty,
                                )
                            except Exception as exc:
                                log_line(f"[{self.bot_id}] ❌ FAILED to queue order to backend: {exc}")
                                summary["note"] = "order_queue_failed"
                        else:
                            log_line(f"[{self.bot_id}] ⚠️ No backend client configured - cannot queue order")
                            summary["note"] = "no_backend_client"
                    continue


                executed = self._execute_signal(
                    snapshot_to_execute,
                    summary,
                    cycle_end,
                    summary_positions,
                    cash_bucket,
                )
                batch_reports[-1] = executed["summary"]
                trade_payload = executed["trade"]
                commission_value = executed.get("commission", 0.0)
                applied_slippage = executed.get("slippage_bps", 0.0)
                executed_qty = executed["summary"].get("executed_qty", 0)
                if commission_value:
                    cycle_commission_total += commission_value
                if executed_qty:
                    slippage_weighted_sum += applied_slippage * executed_qty
                    slippage_qty_total += executed_qty
                if trade_payload and telemetry:
                    cycle_trades.append(trade_payload)
            except Exception as exc:
                log_line(f"Error processing {symbol} in cycle {cycle_end}: {exc}. Continuing...")
                batch_reports.append(
                    {
                        "symbol": symbol,
                        "window_start": cycle_start.isoformat(),
                        "window_end": cycle_end.isoformat(),
                        "status": "error",
                        "note": str(exc),
                        "bias": "NEUTRAL",
                        "delta_pct": 0.0,
                        "total_volume": 0.0,
                        "trades": 0,
                        "vwap": None,
                        "strategy_signal": "HOLD",
                        "execution_side": "HOLD",
                        "executed_qty": 0,
                        "execution_price": None,
                        "last_price": None,
                    }
                )

        if prices:
            # Always revalue portfolio and compute metrics after each cycle (warm or live)
            self.portfolio.revalue_and_snapshot(cycle_end, prices)
            metrics = compute_portfolio_metrics(
                self.portfolio,
                timestamp=cycle_end,
                latest_prices=prices,
                initial_capital=self._initial_capital,  # Pass for accurate total return
            )
            avg_slippage_bps = (
                slippage_weighted_sum / slippage_qty_total if slippage_qty_total else 0.0
            )
            metrics["total_fees"] = cycle_commission_total
            metrics["avg_slippage_bps"] = avg_slippage_bps
            self.metrics_history.append(metrics)
            
            # Get portfolio summary for telemetry and account saving (with current prices)
            summary = self.portfolio.get_summary(prices)
            positions_for_cycle, positions_value, unrealized_total = self._build_positions_snapshot(
                summary.positions,
                prices,
            )
            total_equity = float(summary.cash) + positions_value
            if self.config.reset_session_metrics_on_warm_start and self._metrics_baseline:
                session_unrealized = unrealized_total - self._metrics_baseline["unrealized_pnl"]
                session_realized = float(summary.realized_pnl) - self._metrics_baseline["realized_pnl"]
                summary_display = PortfolioSummary(
                    cash=float(summary.cash),
                    positions=summary.positions,
                    unrealized_pnl=session_unrealized,
                    realized_pnl=session_realized,
                    equity=total_equity,  # Use actual revalued equity, not baseline calculation
                    last_updated=summary.last_updated,
                )
            else:
                summary_display = summary
            summary.unrealized_pnl = unrealized_total
            summary.equity = total_equity
            if self._initial_equity is None:
                self._initial_equity = self.portfolio.initial_cash
            if self._session_start_equity is None:
                # Use initial_cash as baseline, not current equity
                # This ensures session return is calculated from the starting capital
                self._session_start_equity = self.portfolio.initial_cash
            session_baseline = self._session_start_equity or total_equity
            cumulative_baseline = self._initial_equity or total_equity
            session_return_pct = (
                ((total_equity - session_baseline) / session_baseline) * 100 if session_baseline else 0.0
            )
            cumulative_return_pct = (
                ((total_equity - cumulative_baseline) / cumulative_baseline) * 100 if cumulative_baseline else 0.0
            )
            metrics["session_return_pct"] = round(session_return_pct, 2)
            metrics["cumulative_return_pct"] = round(cumulative_return_pct, 2)
            if self.config.reset_session_metrics_on_warm_start and self._metrics_baseline:
                metrics["realized_pnl"] = float(summary.realized_pnl) - self._metrics_baseline["realized_pnl"]
                metrics["unrealized_pnl"] = float(unrealized_total) - self._metrics_baseline["unrealized_pnl"]
            else:
                metrics["realized_pnl"] = float(summary.realized_pnl)
                metrics["unrealized_pnl"] = float(unrealized_total)
            
            # Save account state after each cycle (only in live mode, not warm-start)
            if telemetry and not warm_start:
                positions_dict = {pos["symbol"]: pos["qty"] for pos in summary.positions}
                self.account_manager.save_account(
                    cash=float(summary.cash),
                    positions=positions_dict,
                    equity=total_equity,
                )
            
            # Log metrics and publish telemetry if enabled
            # Note: record_warm_start_trades controls whether warm-start cycles use telemetry

            if self._paper_logger:
                positions_map = {pos["symbol"]: pos["qty"] for pos in summary.positions}
                avg_cost_map = {pos["symbol"]: pos.get("avg_cost", 0.0) for pos in summary.positions}
                for sym, updated_price in prices.items():
                    old_price = self._last_seen_price.get(sym)
                    qty = positions_map.get(sym, 0)
                    avg_cost = avg_cost_map.get(sym, updated_price)
                    unrealized = (updated_price - avg_cost) * qty if qty else 0.0
                    last_logged_price = self._last_logged_price.get(sym)
                    if last_logged_price and last_logged_price != 0:
                        price_change_pct = abs((float(updated_price) - last_logged_price) / last_logged_price) * 100
                    else:
                        price_change_pct = float("inf") if last_logged_price == 0 else 100.0
                    last_logged_unreal = self._last_logged_unrealized.get(sym)
                    unrealized_delta = abs(unrealized - (last_logged_unreal or 0.0))
                    qty_changed = self._last_logged_qty.get(sym) != qty
                    should_log = (
                        last_logged_price is None
                        or qty_changed
                        or price_change_pct >= self._price_log_threshold_pct
                        or unrealized_delta >= self._unrealized_log_threshold
                    )
                    if should_log:
                        self._paper_logger.log_price_update(
                            timestamp=cycle_end,
                            symbol=sym,
                            old_price=old_price,
                            new_price=float(updated_price),
                            position_qty=qty,
                            unrealized_pnl=float(unrealized),
                            equity=total_equity,
                        )
                        self._last_logged_price[sym] = float(updated_price)
                        self._last_logged_unrealized[sym] = float(unrealized)
                        self._last_logged_qty[sym] = qty
                    self._last_seen_price[sym] = float(updated_price)
                self._paper_logger.log_portfolio_snapshot(
                    timestamp=cycle_end,
                    cash=float(summary_display.cash),
                    positions_value=float(positions_value),
                    equity=summary_display.equity,
                    realized_pnl=float(summary_display.realized_pnl),
                    unrealized_pnl=float(summary_display.unrealized_pnl),
                )

            if telemetry:
                
                
                # Write metrics to CSV (always, for analysis)
                trade_metrics = metrics.get("metrics")
                if not isinstance(trade_metrics, TradeMetrics):
                    trade_metrics = TradeMetrics(
                        total_return_pct=float(metrics.get("total_return_pct", 0.0)),
                        daily_return_pct=float(metrics.get("daily_return_pct", 0.0)),
                        session_return_pct=float(metrics.get("session_return_pct", metrics.get("daily_return_pct", 0.0))),
                        cumulative_return_pct=float(metrics.get("cumulative_return_pct", metrics.get("total_return_pct", 0.0))),
                        sharpe_ratio=float(metrics.get("sharpe_ratio", 0.0)),
                        session_sharpe_ratio=float(metrics.get("session_sharpe_ratio", metrics.get("sharpe_ratio", 0.0))),
                        sortino_ratio=float(metrics.get("sortino_ratio", 0.0)),
                        max_drawdown_pct=float(metrics.get("max_drawdown_pct", 0.0)),
                        volatility_pct=float(metrics.get("volatility_pct", 0.0)),
                        win_loss_ratio=float(metrics.get("win_loss_ratio", 0.0)),
                        exposure_pct=float(metrics.get("exposure_pct", 0.0)),
                        turnover_pct=float(metrics.get("turnover_pct", 0.0)),
                        cumulative_pnl=float(metrics.get("cumulative_pnl", 0.0)),
                        sharpe_ratio_available=bool(metrics.get("sharpe_ratio")),
                        session_sharpe_ratio_available=bool(metrics.get("session_sharpe_ratio")),
                        sortino_ratio_available=bool(metrics.get("sortino_ratio")),
                        volatility_available=bool(metrics.get("volatility_pct")),
                        win_loss_ratio_available=bool(metrics.get("win_loss_ratio")),
                    )
                metrics["equity"] = total_equity
                metrics["cash"] = float(summary.cash)
                metrics["positions_value"] = positions_value
                metrics["realized_pnl"] = float(summary_display.realized_pnl)
                metrics["unrealized_pnl"] = float(summary_display.unrealized_pnl)
                metrics["session_return_pct"] = round(session_return_pct, 2)
                metrics["cumulative_return_pct"] = round(cumulative_return_pct, 2)
                metrics["session_sharpe_ratio"] = (
                    trade_metrics.session_sharpe_ratio if trade_metrics.session_sharpe_ratio_available else None
                )
                csv_metrics_payload: Dict[str, Any] = {
                    "total_return_pct": trade_metrics.total_return_pct,
                    "daily_return_pct": trade_metrics.daily_return_pct,
                    "session_return_pct": trade_metrics.session_return_pct,
                    "cumulative_return_pct": trade_metrics.cumulative_return_pct,
                    "unrealized_pnl": float(unrealized_total),
                    "realized_pnl": float(summary.realized_pnl),
                    "sharpe_ratio": trade_metrics.sharpe_ratio if trade_metrics.sharpe_ratio_available else None,
                    "session_sharpe_ratio": (
                        trade_metrics.session_sharpe_ratio if trade_metrics.session_sharpe_ratio_available else None
                    ),
                    "sortino_ratio": trade_metrics.sortino_ratio if trade_metrics.sortino_ratio_available else None,
                    "max_drawdown_pct": trade_metrics.max_drawdown_pct,
                    "volatility_pct": trade_metrics.volatility_pct if trade_metrics.volatility_available else None,
                    "win_loss_ratio": trade_metrics.win_loss_ratio if trade_metrics.win_loss_ratio_available else None,
                    "exposure_pct": trade_metrics.exposure_pct,
                    "turnover_pct": trade_metrics.turnover_pct,
                }
                self.csv_writer.write_metrics(
                    timestamp=cycle_end,
                    equity=total_equity,
                    cash=float(summary.cash),
                    positions_value=positions_value,
                    metrics=csv_metrics_payload,
                    total_fees=cycle_commission_total,
                    avg_slippage_bps=avg_slippage_bps,
                    positions_snapshot=positions_for_cycle,  # Optional JSON snapshot (spec requirement)
                )
                
                # Write trades to CSV
                # Get portfolio state after all trades (cash_after and equity_after)
                # Note: For trades in the same cycle, we use the final state after all trades
                for trade in cycle_trades:
                    price_executed = trade.get("price_executed") or trade.get("price", 0.0)
                    quantity = trade.get("quantity", 0)
                    realized_pnl = trade.get("pnl_realized", 0.0)
                    
                    self.csv_writer.write_trade(
                        timestamp=cycle_end,
                        symbol=trade.get("symbol", ""),
                        side=trade.get("side", ""),
                        quantity=quantity,
                        price=price_executed,
                        realized_pnl=realized_pnl,
                        cash_after=float(summary.cash),
                        equity_after=total_equity,
                        slippage_value=trade.get("slippage_value"),
                    )
                
                # Write positions snapshot to CSV
                self.csv_writer.write_positions(cycle_end, positions_for_cycle, prices)
                
                # Include per-position snapshot in metrics payload for downstream logging
                metrics["positions"] = positions_for_cycle
                
                log_payload = {
                    "metrics": metrics,  # This is the dict from compute_portfolio_metrics
                    "positions": positions_for_cycle,
                    "prices": prices,  # Include prices for fallback in _log_metrics
                    "total_fees": cycle_commission_total,
                    "avg_slippage_bps": avg_slippage_bps,
                    "realized_pnl": float(summary_display.realized_pnl),
                    "unrealized_pnl": float(summary_display.unrealized_pnl),
                    "equity": total_equity,
                    "cash": float(summary.cash),
                    "positions_value": positions_value,
                    "joined_mid_session": self._joined_mid_session,
                }
                recent_trades = self._get_recent_trades()
                
                # Log metrics (concise or detailed based on config)
                self._log_metrics(log_payload, cycle_end, warm_start, recent_trades=recent_trades)
                
                self._publish_cycle(
                    cycle_end,
                    metrics,
                    prices,
                    cycle_trades,
                    batch_reports,
                    total_fees=cycle_commission_total,
                    avg_slippage_bps=avg_slippage_bps,
                    recent_trades=recent_trades,
                )
                # Batch completion is already logged in _log_metrics, no need to duplicate
        else:
            summary = self.portfolio.get_summary(prices)
            positions_for_cycle, positions_value, unrealized_total = self._build_positions_snapshot(summary.positions, prices)
            total_equity = float(summary.cash) + positions_value
            summary.unrealized_pnl = unrealized_total
            summary.equity = total_equity
            if self._paper_logger:
                self._paper_logger.log_portfolio_snapshot(
                    timestamp=cycle_end,
                    cash=float(summary.cash),
                    positions_value=float(positions_value),
                    equity=summary.equity,
                    realized_pnl=float(summary.realized_pnl),
                    unrealized_pnl=float(summary.unrealized_pnl),
                )
            self._log_system_event(
                event="price_missing",
                message="No prices available for cycle",
                level="warning",
                cycle_end=cycle_end.isoformat(),
            )
            if telemetry:
                self._publish_snapshot(cycle_end, status="no_prices")

        self._last_cycle_close = cycle_end

    def _floor_to_cycle(self, when: datetime) -> datetime:
        """
        Floor a timestamp to the nearest cycle boundary.
        For intraday cycles: aligns within the trading session.
        For long cycles (>= 1 day): aligns to market open on the target day.
        """
        cycle_minutes = self.config.cycle_minutes
        is_long_cycle = cycle_minutes >= 1440  # >= 1 day
        
        if is_long_cycle:
            # For long cycles, align to market open on the day
            session_start, _ = today_session_window(when)
            # Skip weekends
            while session_start.weekday() >= 5:
                session_start += timedelta(days=1)
                session_start, _ = today_session_window(session_start)
            return session_start
        
        # For intraday cycles, use session-based alignment
        if self._session_start is None:
            self._session_start, _ = today_session_window(when)
        if when <= self._session_start:
            return self._session_start
        elapsed = when - self._session_start
        steps = int(elapsed.total_seconds() // self._cycle_delta.total_seconds())
        return self._session_start + steps * self._cycle_delta

    def _format_local_time(self, when: datetime, fmt: str = "%H:%M %Z") -> str:
        local_tz = getattr(self, "_local_tz", None)
        if local_tz is None:
            try:
                local_tz = ZoneInfo(getattr(settings, "timezone", "Asia/Karachi"))
                self._local_tz = local_tz
            except Exception:
                local_tz = when.tzinfo
        if when.tzinfo is None and local_tz is not None:
            when = when.replace(tzinfo=local_tz)
        if local_tz is None:
            return when.strftime(fmt)
        return when.astimezone(local_tz).strftime(fmt)

    def _get_symbol_session_start(self, symbol: str) -> Optional[datetime]:
        return self._symbol_first_trade_time.get(symbol)

    def _record_symbol_first_trade(self, symbol: str, ts_utc: pd.Timestamp, price: float) -> None:
        if symbol in self._symbol_first_trade_time:
            return
        local_tz = getattr(self, "_local_tz", None)
        if local_tz is None:
            try:
                local_tz = ZoneInfo(getattr(settings, "timezone", "Asia/Karachi"))
                self._local_tz = local_tz
            except Exception:
                local_tz = None
        first_trade_local = ts_utc
        if local_tz is not None:
            first_trade_local = ts_utc.tz_convert(local_tz)
        first_trade_time = first_trade_local.to_pydatetime()
        self._symbol_first_trade_time[symbol] = first_trade_time
        self._symbol_open_price_today[symbol] = float(price)
        log_line(
            f"[{symbol}] First trade today: {first_trade_local.strftime('%H:%M:%S %Z')} @ {float(price):.2f}"
        )

    def _to_utc_timestamp(self, value: datetime | pd.Timestamp) -> pd.Timestamp:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            raise ValueError("Cannot convert NaT to UTC timestamp")
        if ts.tzinfo is None:
            local_tz = getattr(self, "_local_tz", None)
            if local_tz is None:
                try:
                    local_tz = ZoneInfo(getattr(settings, "timezone", "Asia/Karachi"))
                    self._local_tz = local_tz
                except Exception:
                    local_tz = None
            if local_tz is not None:
                ts = ts.replace(tzinfo=local_tz)
        if ts.tzinfo is not None:
            return ts.tz_convert("UTC")
        return ts

    def _log_daily_first_trades(self) -> None:
        if not self._symbol_first_trade_time:
            log_line("No first trades recorded yet today.")
            return
        log_line("Today's first trades (PKT):")
        for symbol in self.symbols:
            ts = self._symbol_first_trade_time.get(symbol)
            if not ts:
                log_line(f"[{symbol}] No trades yet today.")
                continue
            price = self._symbol_open_price_today.get(symbol)
            ts_label = self._format_local_time(ts)
            price_label = f"{price:.2f}" if price is not None else "n/a"
            log_line(f"[{symbol}] {ts_label} @ {price_label}")

    def _load_symbol_history(
        self,
        symbol: str,
        *,
        up_to: datetime,
        use_cache: bool,
        publish: bool,
        fallback_to_recent: bool = False,
    ) -> pd.DataFrame:
        """
        Load symbol history via REST/pypsx (DEPRECATED for LIVE mode).
        
        ARCHITECTURE: This method uses REST endpoints (PyPSXService) and should NOT
        be used in WebSocket LIVE mode. For LIVE mode, use WebSocket bar history
        from WebSocketStreamProvider.get_bar_history() instead.
        
        Args:
            symbol: Symbol to load.
            up_to: Max timestamp to include.
            use_cache: whether to use cached data.
            publish: whether to publish to telemetry.
            fallback_to_recent: If True, allows returning data from the most recent 
                                trading day if "today" has no data (for off-hours analysis).
        
        CRITICAL: By default (fallback_to_recent=False), only returns trades from 
        today's market day (PKT timezone). Rejects all trades from yesterday or other days.
        
        Raises:
            RuntimeError: If called in WebSocket LIVE mode (use WebSocket data instead).
        """
        # ARCHITECTURE: Strictly block REST calls in WebSocket LIVE mode
        if self._using_websocket and self._trading_mode == TradingMode.LIVE:
            raise RuntimeError(
                f"ARCHITECTURE VIOLATION: Cannot call _load_symbol_history() for {symbol} in "
                f"WebSocket LIVE mode. This method uses REST endpoints (PyPSXService).\n"
                f"For LIVE mode, use WebSocket bar history instead:\n"
                f"  history_df = self.service.get_bar_history(symbol)\n"
                f"Historical data should be seeded separately using seed_historical_bars() "
                f"from pypsx library (separate installation)."
            )
        
        try:
            records = self.service.get_intraday(
                symbol,
                lookback_days=self.config.lookback_days,
                use_cache=use_cache,
            )
        except DataProviderError as exc:
            message = f"Intraday fetch failed for {symbol}: {exc}"
            log_line(message)
            self._log_system_event(
                event="data_provider_error",
                message=message,
                level="error",
                symbol=symbol,
            )
            return self._intraday_cache.get(symbol, _empty_intraday_frame())

        if not records:
            return _empty_intraday_frame()

        df = pd.DataFrame.from_records(records)
        if "timestamp" in df.columns and "ts" not in df.columns:
            df = df.rename(columns={"timestamp": "ts"})
        if "price" not in df.columns and "PRICE" in df.columns:
            df = df.rename(columns={"PRICE": "price"})
        if "volume" not in df.columns:
            if "VOLUME" in df.columns:
                df = df.rename(columns={"VOLUME": "volume"})
            else:
                df["volume"] = 0

        # Robust timestamp parsing:
        # - If ts is already ISO8601, pd.to_datetime will parse it
        # - If ts is numeric, prefer seconds; if too large, treat as ms
        ts_series = _as_series(df["ts"])
        if pd.api.types.is_numeric_dtype(ts_series):
            try:
                # Heuristic: unix ms are typically > 1e12; seconds < 1e11
                unit = "ms" if float(ts_series.iloc[0]) > 1e12 else "s"
                df["ts"] = pd.to_datetime(ts_series, unit=unit, utc=True, errors="coerce")
            except Exception:
                df["ts"] = pd.to_datetime(ts_series, errors="coerce", utc=True)
        else:
            df["ts"] = pd.to_datetime(ts_series, errors="coerce", utc=True)
        df = df.dropna(subset=["ts", "price"])
        volume_series = pd.to_numeric(df["volume"], errors="coerce")
        if not isinstance(volume_series, pd.Series):
            volume_series = pd.Series(volume_series)
        df["volume"] = volume_series.fillna(0)
        df = df.sort_values("ts")

        # CRITICAL: Strict today's date filtering (PKT timezone)
        # Convert timestamps to local market timezone and filter by today's date
        if self._today_date is None:
            self._today_date = now_tz().date()
        
        # Convert to local timezone for date comparison
        ts_series = _as_series(df["ts"])
        df["ts_local"] = ts_series.dt.tz_convert(self._local_tz)
        df["ts_date"] = _as_series(df["ts_local"]).dt.date
        
        # Determine target date: either today, or most recent if fallback enabled
        target_date = self._today_date
        
        # Check if we have data for today
        has_today_data = (_as_series(df["ts_date"]) == self._today_date).any()
        
        if not has_today_data and fallback_to_recent:
            # Fallback: Find the most recent date in the dataframe
            if not df.empty:
                unique_dates = df["ts_date"].unique()
                if len(unique_dates) > 0:
                    target_date = max(unique_dates)
                    log_line(f"[{symbol}] No data for today. Falling back to most recent data: {target_date}")
        
        # Filter to target date
        mask_target = _as_series(df["ts_date"]) == target_date
        df = cast(pd.DataFrame, df.loc[mask_target])
        
        # Clamp to current time (converted to UTC)
        # Note: If fallback used, we ignore 'up_to' time filtering to get full day
        if target_date == self._today_date:
            up_to_ts = self._to_utc_timestamp(up_to)
            mask_up_to = _as_series(df["ts"]) <= up_to_ts
            df = cast(pd.DataFrame, df.loc[mask_up_to])
        
        # Track today's first trade and first price per symbol
        if not df.empty and target_date == self._today_date:
            first_trade_row = df.iloc[0]
            first_trade_ts = first_trade_row["ts"]
            if pd.notna(first_trade_ts):
                self._record_symbol_first_trade(symbol, pd.Timestamp(first_trade_ts), float(first_trade_row["price"]))
        
        symbol_start = self._get_symbol_session_start(symbol)
        if symbol_start is not None:
            cutoff = self._to_utc_timestamp(symbol_start)
            mask_cutoff = _as_series(df["ts"]) >= cutoff
            df = cast(pd.DataFrame, df.loc[mask_cutoff])

        if not df.empty:
            last_seen = self._last_seen_ts.get(symbol)
            new_rows_df: pd.DataFrame
            if last_seen is None:
                new_rows_df = df
            else:
                mask_new = _as_series(df["ts"]) > last_seen
                new_rows_df = cast(pd.DataFrame, df[mask_new])
            
            # Real-time stream filtering: reject any trades not from today or before first trade
            if publish and not new_rows_df.empty:
                filtered_new_rows = []
                for _, row in new_rows_df.iterrows():
                    row_ts_value = row["ts"]
                    if pd.isna(row_ts_value):
                        continue
                    row_ts = pd.Timestamp(row_ts_value).to_pydatetime()
                    row_date = row_ts.astimezone(self._local_tz).date()
                    first_trade_time = self._symbol_first_trade_time.get(symbol)
                    
                    # Reject if not today
                    if row_date != self._today_date:
                        continue
                    
                    # Reject if before first trade of the day
                    if first_trade_time and row_ts < first_trade_time:
                        continue
                    
                    filtered_new_rows.append({
                        "ts": row_ts.isoformat(),
                        "price": float(row["price"]),
                        "volume": float(row.get("volume", 0)),
                    })
                
                if filtered_new_rows:
                    self._telemetry.publish_intraday(symbol, filtered_new_rows)
            
            ts_series = _as_series(df["ts"])
            last_ts = pd.Timestamp(ts_series.max())
            if pd.notna(last_ts):
                self._last_seen_ts[symbol] = last_ts
        
        # Drop temporary columns before returning
        df = df.drop(columns=["ts_local", "ts_date"], errors="ignore")
        return df.reset_index(drop=True)

    def _summarize_empty_batch(
        self,
        symbol: str,
        cycle_start: datetime,
        cycle_end: datetime,
    ) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "window_start": cycle_start.isoformat(),
            "window_end": cycle_end.isoformat(),
            "status": "no_data",
            "bias": "NEUTRAL",
            "delta_pct": 0.0,
            "total_volume": 0.0,
            "trades": 0,
            "vwap": None,
            "strategy_signal": "HOLD",
            "execution_side": "HOLD",
            "executed_qty": 0,
            "execution_price": None,
            "note": "no trades in window",
            "last_price": None,
        }

    def _summarize_batch(
        self,
        symbol: str,
        batch_df: pd.DataFrame,
        cycle_start: datetime,
        cycle_end: datetime,
    ) -> Dict[str, Any]:
        summary = {
            "symbol": symbol,
            "window_start": cycle_start.isoformat(),
            "window_end": cycle_end.isoformat(),
            "status": "ok",
            "bias": "NEUTRAL",
            "delta_pct": 0.0,
            "total_volume": 0.0,
            "trades": 0,
            "vwap": None,
            "strategy_signal": "HOLD",
            "execution_side": "HOLD",
            "executed_qty": 0,
            "execution_price": None,
            "note": "",
            "last_price": None,
        }

        if batch_df.empty:
            summary["status"] = "no_trades"
            return summary

        volume = float(batch_df["volume"].sum())
        notional = float((batch_df["price"] * batch_df["volume"]).sum())
        first_price = float(batch_df["price"].iloc[0])
        last_price = float(batch_df["price"].iloc[-1])
        vwap = notional / volume if volume > 0 else last_price
        prev_vwap = self._last_vwap.get(symbol)
        delta_pct = 0.0
        if prev_vwap:
            delta_pct = ((vwap - prev_vwap) / prev_vwap) * 100 if prev_vwap else 0.0
        else:
            if first_price:
                delta_pct = ((last_price - first_price) / first_price) * 100

        bias = "NEUTRAL"
        threshold = self.config.bias_threshold_pct
        if delta_pct > threshold:
            bias = "BUY"
        elif delta_pct < -threshold:
            bias = "SELL"

        self._last_vwap[symbol] = vwap

        summary.update(
            {
                "bias": bias,
                "delta_pct": delta_pct,
                "total_volume": volume,
                "trades": int(len(batch_df)),
                "vwap": vwap,
                "first_price": first_price,
                "last_price": last_price,
            }
        )
        return summary

    def _build_signal_snapshot(
        self,
        symbol: str,
        df_full: pd.DataFrame,
        cycle_end: datetime,
    ) -> Tuple[Optional[SignalSnapshot], Dict[str, Any]]:
        if df_full.empty:
            return None, self._summarize_empty_batch(symbol, cycle_end - self._cycle_delta, cycle_end)

        session_start = self._session_start or (cycle_end - self._cycle_delta)
        summary = self._summarize_batch(symbol, df_full, session_start, cycle_end)
        summary["window_start"] = session_start.isoformat()
        summary["window_end"] = cycle_end.isoformat()

        try:
            signal = self.strategy.generate_signal(symbol, df_full)
        except Exception as exc:  # pragma: no cover - strategy failure
            message = f"Strategy error for {symbol}: {exc}"
            log_line(message)
            self._log_system_event(
                event="strategy_error",
                message=message,
                level="error",
                symbol=symbol,
            )
            summary["note"] = "strategy_error"
            summary["execution_side"] = "HOLD"
            summary["strategy_signal"] = "HOLD"
            return None, summary

        summary["strategy_signal"] = signal
        execution_side = self._decide_execution(summary, signal)
        summary["execution_side"] = execution_side or "HOLD"
        if not execution_side:
            return None, summary

        last_price = float(df_full["price"].iloc[-1])
        vwap = float(summary.get("vwap") or last_price)
        target_qty = self._position_size_for(last_price)

        snapshot = SignalSnapshot(
            symbol=symbol,
            side=execution_side,
            strategy_signal=signal,
            bias=summary.get("bias", "NEUTRAL"),
            generated_at=cycle_end,
            signal_price=last_price,
            vwap=vwap,
            target_qty=target_qty,
            note=summary.get("note", ""),
            delta_pct=float(summary.get("delta_pct", 0.0)),
            batch_label=self._format_local_time(cycle_end),
        )
        summary["target_qty"] = target_qty
        summary["signal_price"] = last_price
        return snapshot, summary

    @staticmethod
    def _signals_equal(a: SignalSnapshot, b: SignalSnapshot) -> bool:
        return (
            a.side == b.side
            and a.strategy_signal == b.strategy_signal
            and a.target_qty == b.target_qty
        )

    def _decide_execution(self, summary: Dict[str, Any], signal: str) -> Optional[str]:
        bias = summary.get("bias", "NEUTRAL")
        if summary.get("total_volume", 0) <= 0:
            summary["note"] = "zero volume"
            return None
        if bias == "NEUTRAL":
            if signal in {"BUY", "SELL"}:
                summary["note"] = "strategy-driven trade"
                return signal
            summary["note"] = "neutral bias"
            return None
        if signal == bias:
            summary["note"] = "bias aligned with strategy"
            return bias
        if signal == "HOLD":
            summary["note"] = "bias-driven trade"
            return bias
        summary["note"] = f"bias overrode strategy ({signal})"
        return bias

    def _process_queued_signals(self, now: datetime) -> None:
        """
        Process queued signals when market opens.
        
        Args:
            now: Current datetime
        """
        if not self._queued_signals:
            return
        
        log_line(f"Processing {len(self._queued_signals)} queued signal(s) from previous session...")
        
        # Get current portfolio state
        portfolio_summary = self.portfolio.get_summary()
        summary_positions = {pos["symbol"]: pos["qty"] for pos in portfolio_summary.positions}
        cash_bucket = {"value": float(portfolio_summary.cash)}
        
        # Process each queued signal
        processed_signals = []
        for snapshot in self._queued_signals:
            # Log signal age for visibility
            signal_age = (now - snapshot.generated_at).total_seconds() / 3600  # hours
            if signal_age > 24:
                log_line(f"[{snapshot.symbol}] Warning: Signal is {signal_age:.1f} hours old (generated at {snapshot.generated_at.strftime('%Y-%m-%d %H:%M:%S')})")
            try:
                # Get current price for the symbol
                symbol = snapshot.symbol
                if symbol not in self._last_seen_price:
                    # ARCHITECTURE: In WebSocket mode, use WebSocket prices, not REST
                    if self._using_websocket:
                        # Get latest price from WebSocket stream
                        if hasattr(self.service, 'get_latest_price'):
                            latest_price = self.service.get_latest_price(symbol)
                            if latest_price:
                                self._last_seen_price[symbol] = latest_price
                            else:
                                log_line(f"[{symbol}] No WebSocket price available for queued signal. Skipping.")
                                continue
                        else:
                            log_line(f"[{symbol}] WebSocket service does not provide price lookup. Skipping.")
                            continue
                    else:
                        # Traditional mode: Try to load current data via REST
                        try:
                            df_full = self._load_symbol_history(symbol, up_to=now, use_cache=False, publish=False)
                            if not df_full.empty:
                                self._last_seen_price[symbol] = float(df_full["price"].iloc[-1])
                            else:
                                log_line(f"[{symbol}] No data available for queued signal. Skipping.")
                                continue
                        except Exception as exc:
                            log_line(f"[{symbol}] Error loading data for queued signal: {exc}. Skipping.")
                            continue
                
                # Update snapshot with current price if needed
                current_price = self._last_seen_price.get(symbol, snapshot.signal_price)
                snapshot.signal_price = current_price
                snapshot.generated_at = now
                
                # Create a summary dict for the queued signal
                summary = {
                    "symbol": symbol,
                    "window_start": now.isoformat(),
                    "window_end": now.isoformat(),
                    "status": "executing_queued",
                    "bias": snapshot.bias,
                    "delta_pct": 0.0,
                    "total_volume": 0.0,
                    "trades": 0,
                    "vwap": snapshot.vwap,
                    "strategy_signal": snapshot.strategy_signal,
                    "execution_side": snapshot.side or "HOLD",
                }
                
                # Execute the queued signal
                executed = self._execute_signal(
                    snapshot,
                    summary,
                    now,
                    summary_positions,
                    cash_bucket,
                )
                
                if executed.get("trade"):
                    log_line(f"[{symbol}] Queued {snapshot.side} signal executed successfully.")
                    self._log_system_event(
                        event="queued_signal_executed",
                        message=f"{symbol} queued {snapshot.side} signal executed",
                        level="info",
                        symbol=symbol,
                        side=snapshot.side,
                        qty=executed["summary"].get("executed_qty", 0),
                    )
                
                processed_signals.append(snapshot)
            except Exception as exc:
                log_line(f"Error processing queued signal for {snapshot.symbol}: {exc}. Continuing...")
                # Keep the signal in queue if there was an error
                continue
        
        # Remove processed signals from queue and mark as executed in storage
        for signal in processed_signals:
            if signal in self._queued_signals:
                self._queued_signals.remove(signal)
                # Mark as executed in persistent storage (if signal has signal_id attribute)
                signal_id = getattr(signal, 'signal_id', None)
                if signal_id:
                    self.signal_queue.mark_executed(signal_id, now)
        
        
        if processed_signals:
            log_line(f"Processed {len(processed_signals)} queued signal(s).")

    def _process_backend_queued_orders(
        self,
        queued_orders: List[Dict[str, Any]],
        now: datetime
    ) -> None:
        """
        Log queued orders from backend.
        
        IMPORTANT: This method does NOT execute orders or create positions.
        Backend's activate_staged_orders endpoint handles actual execution.
        SDK will sync executions afterward via _sync_executions_from_backend().
        
        Positions must ONLY be created from executions, never from queued orders.
        """
        if not queued_orders:
            return
        
        log_line(f"ℹ️ Found {len(queued_orders)} queued order(s) from backend:")
        
        for order in queued_orders:
            symbol = order.get('symbol', 'UNKNOWN')
            side = order.get('side', 'UNKNOWN')
            quantity = order.get('quantity', 0)
            submission_time = order.get('submission_time', 'unknown')
            
            log_line(f"  - {side} {quantity} {symbol} (scheduled for {submission_time})")
        
        log_line("✓ Backend will auto-execute these orders when market opens")
        log_line("✓ SDK will sync executions and create positions afterward")


    def _execute_signal(
        self,
        snapshot: SignalSnapshot,
        summary: Dict[str, Any],
        cycle_end: datetime,
        positions_snapshot: Dict[str, int],
        cash_bucket: Dict[str, float],
    ) -> Dict[str, Any]:
        symbol = snapshot.symbol
        execution_side = snapshot.side
        summary["execution_side"] = execution_side or "HOLD"
        if execution_side not in {"BUY", "SELL"}:
            summary["note"] = "no_signal"
            return {"summary": summary, "trade": None, "commission": 0.0, "slippage_bps": 0.0}

        signal_price = snapshot.signal_price
        vwap = snapshot.vwap or signal_price

        config_slippage = float(self.config.slippage_bps or 0.0)
        side_sign = 1 if execution_side == "BUY" else -1
        applied_slippage_bps = config_slippage * side_sign
        slippage_multiplier = 1 + applied_slippage_bps / 10_000
        executed_price = signal_price * slippage_multiplier
        slippage_value = abs(executed_price - signal_price)
        
        fees_per_share = float(self.config.commission_per_share or 0.0)
        fees_pct_notional = float(self.config.commission_pct_notional or 0.0)
        
        quantity = max(1, snapshot.target_qty)
        summary["requested_qty"] = quantity

        if execution_side == "BUY":
            available_cash = float(cash_bucket.get("value", 0.0))
            max_affordable = self.portfolio.calculate_affordable_quantity(
                price=signal_price,
                fees_per_share=fees_per_share,
                fees_pct_notional=fees_pct_notional,
                slippage_bps=applied_slippage_bps,
                available_cash=available_cash,
            )
            if max_affordable <= 0:
                summary["note"] = "insufficient_cash"
                return {"summary": summary, "trade": None, "commission": 0.0, "slippage_bps": 0.0}
            quantity = min(quantity, max_affordable)
            lot = max(1, self.config.min_lot)
            quantity = max(lot, (quantity // lot) * lot)
            if quantity <= 0:
                summary["note"] = "insufficient_cash"
                return {"summary": summary, "trade": None, "commission": 0.0, "slippage_bps": 0.0}
        else:
            available = positions_snapshot.get(symbol, 0)
            if available <= 0 and not self.config.allow_short:
                summary["note"] = "no_position_to_sell"
                return {"summary": summary, "trade": None, "commission": 0.0, "slippage_bps": 0.0}
            if available > 0:
                quantity = min(quantity, available)
                if quantity <= 0:
                    summary["note"] = "no_position_to_sell"
                    return {"summary": summary, "trade": None, "commission": 0.0, "slippage_bps": 0.0}

        notional = executed_price * quantity
        commission = quantity * fees_per_share + abs(notional) * fees_pct_notional

        try:
            trade = self.portfolio.record_trade(
                ts=cycle_end,
                symbol=symbol,
                side=execution_side,
                quantity=quantity,
                price=executed_price,
                fees=commission,
                slippage_bps=applied_slippage_bps,
            )
        except ValueError as exc:
            error_msg = str(exc)
            summary["note"] = error_msg.lower().replace(" ", "_")
            self._log_system_event(
                event="order_rejected",
                message=error_msg,
                level="warning",
                symbol=symbol,
                side=execution_side,
            )
            return {"summary": summary, "trade": None, "commission": 0.0, "slippage_bps": 0.0}

        trade_value = quantity * executed_price
        position_before = positions_snapshot.get(symbol, 0)
        cash_before = float(cash_bucket.get("value", 0.0))

        if execution_side == "BUY":
            positions_snapshot[symbol] = position_before + quantity
            cash_bucket["value"] = max(0.0, cash_before - trade_value - commission)
        else:
            positions_snapshot[symbol] = position_before - quantity
            cash_bucket["value"] = cash_before + trade_value - commission

        summary["executed_qty"] = quantity
        summary["execution_price"] = executed_price
        summary["execution_price_raw"] = signal_price
        summary["slippage_bps"] = applied_slippage_bps
        summary["slippage_value"] = slippage_value
        summary["commission"] = commission
        summary["realized_pnl"] = float(trade.pnl_realized)

        snapshot.executed_at = cycle_end

        trade_payload = self._serialize_trade(trade)
        trade_payload.update(
            {
                "bias": snapshot.bias,
                "strategy_signal": snapshot.strategy_signal,
                "vwap": snapshot.vwap,
                "volume": summary.get("total_volume", 0.0),
                "window_end": summary.get("window_end"),
                "commission": commission,
                "slippage_bps": applied_slippage_bps,
                "slippage_value": slippage_value,
                "price_raw": signal_price,
                "price_executed": executed_price,
            }
        )

        if self._paper_logger:
            summary_after = self.portfolio.get_summary()
            price_hints = dict(self._last_seen_price)
            price_hints[symbol] = float(executed_price)
            _, positions_value_after, unrealized_after = self._build_positions_snapshot(
                summary_after.positions,
                price_hints,
            )
            equity_after = float(summary_after.cash) + positions_value_after
            self._paper_logger.log_trade(
                timestamp=cycle_end,
                symbol=symbol,
                side=execution_side,
                quantity=quantity,
                price=executed_price,
                cost=trade_value,
                commission=commission,
                cash_before=cash_before,
                cash_after=float(cash_bucket.get("value", 0.0)),
                position_before=position_before,
                position_after=positions_snapshot.get(symbol, 0),
                realized_pnl=float(trade.pnl_realized),
                equity_after=float(equity_after),
                unrealized_after=float(unrealized_after),
                slippage_value=slippage_value,
            )

        return {
            "summary": summary,
            "trade": trade_payload,
            "commission": commission,
            "slippage_bps": applied_slippage_bps,
        }

    def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        *,
        execution_timestamp: Optional[datetime] = None,
        price: Optional[float] = None,
        source: str = "manual",
    ) -> Dict[str, Any]:
        """
        Unified order execution method - the single source of truth for all order execution.
        
        ARCHITECTURE: This method centralizes all order execution logic:
        - Price discovery (WebSocket, snapshot, or provided)
        - Slippage calculation
        - Commission calculation
        - Portfolio updates
        - Trade logging
        
        This ensures consistent execution regardless of whether orders come from:
        - Strategy on_data() (bar-close execution)
        - Immediate strategy execution
        - Manual client calls (deprecated, should use engine)
        
        Args:
            symbol: Stock symbol
            side: 'BUY' or 'SELL'
            quantity: Number of shares
            execution_timestamp: When to record the trade (default: now)
            price: Optional execution price (if None, will discover from WebSocket/snapshot)
            source: Source identifier for logging ('strategy_bar_close', 'strategy_immediate', 'manual', etc.)
            
        Returns:
            Dict with execution details:
            {
                'success': bool,
                'trade': Optional[Dict],  # Trade details if successful
                'error': Optional[str],   # Error message if failed
                'execution_price': float,
                'quantity': int,
                'commission': float,
                'slippage_bps': float,
            }
        """
        symbol = symbol.upper()
        side = side.upper()
        
        if side not in {'BUY', 'SELL'}:
            return {
                'success': False,
                'error': f"Invalid side: {side}. Must be 'BUY' or 'SELL'",
                'execution_price': 0.0,
                'quantity': 0,
                'commission': 0.0,
                'slippage_bps': 0.0,
            }
        
        if quantity <= 0:
            return {
                'success': False,
                'error': f"Invalid quantity: {quantity}. Must be > 0",
                'execution_price': 0.0,
                'quantity': 0,
                'commission': 0.0,
                'slippage_bps': 0.0,
            }

        summary = self.portfolio.get_summary()

        # Get execution timestamp
        if execution_timestamp is None:
            execution_timestamp = now_tz()

        explicit_price_supplied = price is not None and float(price) > 0
        
        # Price discovery: use provided price, or discover from WebSocket/snapshot
        if price is None:
            # Try WebSocket first (if available)
            if self._using_websocket and hasattr(self.service, 'get_latest_price'):
                price = self.service.get_latest_price(symbol)
            
            # Fallback to last seen price
            if price is None:
                price = self._last_seen_price.get(symbol)
            
            # Final fallback: try to get from snapshot
            if price is None:
                try:
                    snapshot = self.service.get_company_snapshot(symbol)
                    if isinstance(snapshot, dict):
                        price = snapshot.get('current') or snapshot.get('ldcp') or snapshot.get('current_price')
                    elif hasattr(snapshot, 'current'):
                        price = snapshot.current
                    elif hasattr(snapshot, 'ldcp'):
                        price = snapshot.ldcp
                except Exception:
                    pass
            
            if price is None or price <= 0:
                return {
                    'success': False,
                    'error': f"Unable to determine execution price for {symbol}",
                    'execution_price': 0.0,
                    'quantity': 0,
                    'commission': 0.0,
                    'slippage_bps': 0.0,
                }

        # MARKET-style discovery: buy at ask, sell at bid (synthetic when no L2).
        if not explicit_price_supplied:
            try:
                from ...data.paper_spread import mark_execution_price

                quote: Dict[str, Any] = {"price": float(price)}
                try:
                    if hasattr(self.service, "get_price"):
                        raw_q = self.service.get_price(symbol)
                        if isinstance(raw_q, dict):
                            quote = raw_q
                except Exception:
                    pass
                edge = mark_execution_price(quote, side)
                if edge > 0:
                    price = edge
            except Exception:
                pass
        
        # Apply slippage
        config_slippage = float(self.config.slippage_bps or 0.0)
        side_sign = 1 if side == 'BUY' else -1
        applied_slippage_bps = config_slippage * side_sign
        slippage_multiplier = 1 + applied_slippage_bps / 10_000
        executed_price = price * slippage_multiplier
        slippage_value = abs(executed_price - price)
        
        # Calculate commission
        fees_per_share = float(self.config.commission_per_share or 0.0)
        fees_pct_notional = float(self.config.commission_pct_notional or 0.0)
        notional = executed_price * quantity
        commission = quantity * fees_per_share + abs(notional) * fees_pct_notional
        
        # Validate position availability for SELL
        if side == 'SELL':
            current_position = 0
            for pos in summary.positions:
                if pos.get('symbol', '').upper() == symbol:
                    current_position = pos.get('qty', 0)
                    break
            
            if current_position < quantity and not self.config.allow_short:
                return {
                    'success': False,
                    'error': f"Insufficient position: have {current_position}, need {quantity}",
                    'execution_price': executed_price,
                    'quantity': 0,
                    'commission': 0.0,
                    'slippage_bps': applied_slippage_bps,
                }
            
            # Adjust quantity to available position
            if current_position < quantity:
                quantity = current_position
        
        # Validate cash availability for BUY
        if side == 'BUY':
            available_cash = float(summary.cash)
            total_cost = executed_price * quantity + commission
            
            if total_cost > available_cash:
                # Calculate affordable quantity
                max_affordable = self.portfolio.calculate_affordable_quantity(
                    price=executed_price,
                    fees_per_share=fees_per_share,
                    fees_pct_notional=fees_pct_notional,
                    slippage_bps=applied_slippage_bps,
                    available_cash=available_cash,
                )
                
                if max_affordable <= 0:
                    return {
                        'success': False,
                        'error': f"Insufficient cash: need {total_cost:.2f}, have {available_cash:.2f}",
                        'execution_price': executed_price,
                        'quantity': 0,
                        'commission': 0.0,
                        'slippage_bps': applied_slippage_bps,
                    }
                
                # Adjust quantity to affordable amount
                lot = max(1, self.config.min_lot)
                quantity = min(quantity, max_affordable)
                quantity = max(lot, (quantity // lot) * lot)
        
        # Execute trade through portfolio service
        try:
            trade = self.portfolio.record_trade(
                ts=execution_timestamp,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=executed_price,
                fees=commission,
                slippage_bps=applied_slippage_bps,
            )
        except ValueError as exc:
            return {
                'success': False,
                'error': str(exc),
                'execution_price': executed_price,
                'quantity': quantity,
                'commission': commission,
                'slippage_bps': applied_slippage_bps,
            }
        
        # Update last seen price
        self._last_seen_price[symbol] = float(executed_price)
        
        # Log trade
        if self._paper_logger:
            summary_after = self.portfolio.get_summary()
            price_hints = dict(self._last_seen_price)
            price_hints[symbol] = float(executed_price)
            _, positions_value_after, unrealized_after = self._build_positions_snapshot(
                summary_after.positions,
                price_hints,
            )
            equity_after = float(summary_after.cash) + positions_value_after
            
            self._paper_logger.log_trade(
                timestamp=execution_timestamp,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=executed_price,
                cost=notional,
                commission=commission,
                cash_before=float(summary.cash) if side == 'BUY' else float(summary_after.cash),
                cash_after=float(summary_after.cash),
                position_before=0,  # Will be calculated from portfolio
                position_after=0,    # Will be calculated from portfolio
                realized_pnl=float(trade.pnl_realized),
                equity_after=float(equity_after),
                unrealized_after=float(unrealized_after),
                slippage_value=slippage_value,
            )
        
        # Log execution
        log_line(f"✅ [{source}] {side} {quantity} {symbol} @ {executed_price:.2f} | "
                f"Commission: {commission:.2f} | Slippage: {applied_slippage_bps:.1f} bps")
        
        # Serialize trade for return
        trade_payload = self._serialize_trade(trade)
        trade_payload.update({
            'source': source,
            'execution_price': executed_price,
            'price_raw': price,
            'slippage_bps': applied_slippage_bps,
            'slippage_value': slippage_value,
            'commission': commission,
        })
        
        return {
            'success': True,
            'trade': trade_payload,
            'execution_price': executed_price,
            'quantity': quantity,
            'commission': commission,
            'slippage_bps': applied_slippage_bps,
        }
    
    def execute_immediate(
        self,
        symbol: str,
        side: str,
        quantity: int,
        *,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute an order immediately (not waiting for bar close).
        
        ARCHITECTURE: This method allows strategies to execute orders immediately
        when they have enough information, without waiting for the next bar close.
        
        This is useful for:
        - Strategies that want to act on external signals
        - Strategies that have already analyzed sufficient data
        - Manual intervention (though client.create_order() is deprecated)
        
        Args:
            symbol: Stock symbol
            side: 'BUY' or 'SELL'
            quantity: Number of shares
            price: Optional execution price (if None, will discover from WebSocket/snapshot)
            
        Returns:
            Dict with execution details (same format as execute_order)
        """
        return self.execute_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            execution_timestamp=now_tz(),
            price=price,
            source='strategy_immediate',
        )

    def _position_size_for(self, price: float) -> int:
        # Use capital_allocation if set, otherwise use position_notional
        if self.config.capital_allocation is not None:
            # Get current equity from portfolio
            summary = self.portfolio.get_summary()
            equity = summary.equity
            notional = equity * self.config.capital_allocation
        else:
            notional = self.config.position_notional
        
        lot = max(1, self.config.min_lot)
        qty = int(notional // max(price, 1e-6))
        return max(lot, (qty // lot) * lot)

    def _get_recent_trades(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get recent trades from portfolio service.
        
        Args:
            limit: Maximum number of recent trades to return
            
        Returns:
            List of trade dicts with timestamp, symbol, side, quantity, price, pnl_realized
        """
        try:
            # Get recent trades from portfolio service (already returns dicts)
            fetch_limit = limit or 10_000
            trades = self.portfolio.get_trades(limit=fetch_limit)
            if not trades:
                return []
            
            today = self._today_date or now_tz().date()
            recent_trades = []
            for trade in trades:
                ts_value = trade.get("ts", "")
                ts_dt = None
                if isinstance(ts_value, str):
                    try:
                        ts_dt = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
                    except Exception:
                        ts_dt = None
                elif isinstance(ts_value, datetime):
                    ts_dt = ts_value
                
                if ts_dt is not None:
                    ts_local = ts_dt.astimezone(self._local_tz) if getattr(self, "_local_tz", None) else ts_dt
                    if ts_local.date() != today:
                        continue
                trade_dict_ts = ts_value
                if isinstance(ts_value, datetime):
                    trade_dict_ts = ts_value.isoformat()
                
                # Convert timestamp field from 'ts' to 'timestamp' for consistency
                trade_dict = {
                    "timestamp": trade_dict_ts,
                    "symbol": trade.get("symbol", ""),
                    "side": trade.get("side", ""),
                    "quantity": trade.get("quantity", 0),
                    "price": float(trade.get("price", 0.0)),
                    "pnl_realized": float(trade.get("pnl_realized", 0.0)),
                }
                if ts_dt is not None:
                    trade_dict["_sort_key"] = ts_dt
                recent_trades.append(trade_dict)
            
            # Sort trades chronologically so logs show cumulative order from session start
            recent_trades.sort(key=lambda t: t.get("_sort_key") or t.get("timestamp", ""))
            for trade in recent_trades:
                trade.pop("_sort_key", None)
            if limit:
                recent_trades = recent_trades[-limit:]
            return recent_trades
        except Exception as exc:
            # Gracefully handle any issues with getting trades
            log_line(f"Could not retrieve recent trades: {exc}")
            return []

    def _log_metrics(
        self,
        payload: Dict[str, Any],
        cycle_end: datetime,
        warm_start: bool = False,
        recent_trades: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Log cycle metrics - clean, professional format.
        """
        # Extract TradeMetrics from payload
        # payload["metrics"] is a dict from compute_portfolio_metrics with "metrics" key
        metrics_payload = payload.get("metrics", {})
        trade_metrics: TradeMetrics
        if isinstance(metrics_payload, dict) and "metrics" in metrics_payload:
            trade_metrics = metrics_payload["metrics"]
        elif isinstance(metrics_payload, TradeMetrics):
            trade_metrics = metrics_payload
        else:
            # Fallback: build TradeMetrics from dict-like input
            sharpe_raw = metrics_payload.get("sharpe_ratio")
            session_sharpe_raw = metrics_payload.get("session_sharpe_ratio")
            sortino_raw = metrics_payload.get("sortino_ratio")
            volatility_raw = metrics_payload.get("volatility_pct")
            win_loss_raw = metrics_payload.get("win_loss_ratio")
            sharpe_ratio_available = metrics_payload.get("sharpe_ratio_available")
            if sharpe_ratio_available is None:
                sharpe_ratio_available = sharpe_raw is not None
            session_sharpe_ratio_available = metrics_payload.get("session_sharpe_ratio_available")
            if session_sharpe_ratio_available is None:
                session_sharpe_ratio_available = session_sharpe_raw is not None
            sortino_ratio_available = metrics_payload.get("sortino_ratio_available")
            if sortino_ratio_available is None:
                sortino_ratio_available = sortino_raw is not None
            volatility_available = metrics_payload.get("volatility_available")
            if volatility_available is None:
                volatility_available = volatility_raw is not None
            win_loss_ratio_available = metrics_payload.get("win_loss_ratio_available")
            if win_loss_ratio_available is None:
                win_loss_ratio_available = win_loss_raw is not None
            trade_metrics = TradeMetrics(
                total_return_pct=float(metrics_payload.get("total_return_pct", 0.0)),
                daily_return_pct=float(metrics_payload.get("daily_return_pct", 0.0)),
                session_return_pct=float(metrics_payload.get("session_return_pct", metrics_payload.get("daily_return_pct", 0.0))),
                cumulative_return_pct=float(metrics_payload.get("cumulative_return_pct", metrics_payload.get("total_return_pct", 0.0))),
                sharpe_ratio=float(sharpe_raw or 0.0),
                session_sharpe_ratio=float(session_sharpe_raw or 0.0),
                sortino_ratio=float(sortino_raw or 0.0),
                max_drawdown_pct=float(metrics_payload.get("max_drawdown_pct", 0.0)),
                volatility_pct=float(volatility_raw or 0.0),
                win_loss_ratio=float(win_loss_raw or 0.0),
                exposure_pct=float(metrics_payload.get("exposure_pct", 0.0)),
                turnover_pct=float(metrics_payload.get("turnover_pct", 0.0)),
                cumulative_pnl=float(metrics_payload.get("cumulative_pnl", 0.0)),
                sharpe_ratio_available=bool(sharpe_ratio_available),
                session_sharpe_ratio_available=bool(session_sharpe_ratio_available),
                sortino_ratio_available=bool(sortino_ratio_available),
                volatility_available=bool(volatility_available),
                win_loss_ratio_available=bool(win_loss_ratio_available),
            )

        # Always get fresh portfolio summary to ensure accurate positions
        portfolio_summary = self.portfolio.get_summary()
        equity = float(payload.get("equity", portfolio_summary.equity))
        cash = float(payload.get("cash", portfolio_summary.cash))

        # Use positions from payload (with current price info) when available,
        # otherwise build them from the portfolio summary.
        positions = payload.get("positions", []) or []
        if not positions and portfolio_summary.positions:
            prices = payload.get("prices", {})
            for pos in portfolio_summary.positions:
                qty = pos.get("qty", 0)
                if qty <= 0:
                    continue
                symbol = pos["symbol"]
                avg_cost = pos.get("avg_cost", 0.0)
                current_price = prices.get(symbol, avg_cost)
                market_value = current_price * qty
                positions.append(
                    {
                        "symbol": symbol,
                        "qty": qty,
                        "avg_cost": avg_cost,
                        "current_price": current_price,
                        "market_value": market_value,
                    }
                )

        # Total PnL = realized + unrealized from portfolio summary (fallback to cumulative if available)
        total_pnl = float(trade_metrics.cumulative_pnl)
        if total_pnl == 0.0 and (portfolio_summary.realized_pnl or portfolio_summary.unrealized_pnl):
            total_pnl = float(portfolio_summary.realized_pnl) + float(portfolio_summary.unrealized_pnl)

        # Clean, professional logging format matching spec
        cycle_time_str = self._format_local_time(cycle_end)
        
        # Skip logging during warm-start (we'll show summary at end)
        if warm_start and not self.config.verbose_warm_start:
            return
        
        # Calculate total PnL (realized + unrealized)
        total_pnl = float(portfolio_summary.realized_pnl) + float(portfolio_summary.unrealized_pnl)
        
        # Determine bot status
        if not self.is_running:
            bot_status = "stop"
        elif warm_start:
            bot_status = "warm"
        else:
            bot_status = "run"

        if not self.config.detailed_logs:
            log_line(
                f"{bot_status.upper()} {cycle_time_str} | Cash {cash:,.0f} | Equity {equity:,.0f} | "
                f"PnL {total_pnl:+,.0f} | Session {trade_metrics.session_return_pct:.2f}% | "
                f"Total {trade_metrics.total_return_pct:.2f}% | Positions {len(positions)} | "
                f"Exposure {trade_metrics.exposure_pct:.2f}%"
            )
            return

        sharpe_text = f"{trade_metrics.sharpe_ratio:.2f}" if trade_metrics.sharpe_ratio_available else "-"
        sortino_text = (
            f"{trade_metrics.sortino_ratio:.2f}" if trade_metrics.sortino_ratio_available else "-"
        )
        volatility_text = (
            f"{trade_metrics.volatility_pct:.2f}%" if trade_metrics.volatility_available else "-"
        )
        win_loss_text = (
            f"{trade_metrics.win_loss_ratio:.2f}" if trade_metrics.win_loss_ratio_available else "-"
        )
        session_sharpe_text = (
            f"{trade_metrics.session_sharpe_ratio:.2f}"
            if trade_metrics.session_sharpe_ratio_available
            else "-"
        )

        log_line(
            f"Portfolio {trade_metrics.session_return_pct:.2f}% today | "
            f"Total {trade_metrics.total_return_pct:.2f}% | Sharpe {sharpe_text} | "
            f"Session Sharpe {session_sharpe_text} | "
            f"Sortino {sortino_text} | MaxDD {trade_metrics.max_drawdown_pct:.2f}% | "
            f"Vol {volatility_text} | Win/Loss {win_loss_text} | "
            f"Exposure {trade_metrics.exposure_pct:.2f}% | Turnover {trade_metrics.turnover_pct:.2f}%"
        )

        top_positions = positions[:3]
        if top_positions:
            pos_parts = [
                f"{p['symbol']} {p['qty']} @ {p['current_price']:.2f} ({p['market_value']:,.0f})"
                for p in top_positions
            ]
            log_line("Top positions: " + " | ".join(pos_parts))

        total_fees = float(payload.get("total_fees", 0.0))
        avg_slippage = float(payload.get("avg_slippage_bps", 0.0))
        if total_fees or avg_slippage:
            log_line(f"Cycle fees {total_fees:.2f} | Avg slippage {avg_slippage:.2f} bps")

        print("")

        # TOP SECTION: cash, equity, total PnL, open positions summary, bot status
        print("\n" + "-" * 70)
        print("PORTFOLIO SUMMARY")
        print("-" * 70)
        print(f"Cash:        {cash:,.0f} PKR")
        print(f"Equity:      {equity:,.0f} PKR")
        
        # Format total PnL with color
        pnl_str = f"{total_pnl:+,.0f} PKR"
        if total_pnl >= 0:
            pnl_str = self._colorize(pnl_str, "green")
        else:
            pnl_str = self._colorize(pnl_str, "red")
        print(f"Total PnL:   {pnl_str}")
        
        # Open positions summary
        if positions:
            pos_count = len(positions)
            total_value = sum(p.get("market_value", 0.0) for p in positions)
            print(f"Positions:   {pos_count} open | Total Value: {total_value:,.0f} PKR")
        else:
            print("Positions:   0 open")
        
        print(f"Status:      {bot_status.upper()}")
        print("-" * 70)
        
        # PER-SYMBOL DETAILS: quantity, avg cost, current price, unrealized PnL, value
        if positions:
            print("\nPOSITIONS")
            print("-" * 70)
            print(f"{'Symbol':<10} {'Qty':>8} {'Avg Cost':>12} {'Price':>12} {'Unreal PnL':>15} {'Value':>15}")
            print("-" * 70)
            
            for pos in positions:
                symbol = pos.get("symbol", "")
                qty = int(pos.get("qty", 0))
                if not symbol or qty <= 0:
                    continue
                avg_cost = float(pos.get("avg_cost", 0.0))
                current_price = float(pos.get("current_price", avg_cost))
                unrealized_pnl = (current_price - avg_cost) * qty
                market_value = float(pos.get("market_value", current_price * qty))
                
                # Format unrealized PnL with color
                pnl_display = f"{unrealized_pnl:+,.0f}"
                if unrealized_pnl >= 0:
                    pnl_display = self._colorize(pnl_display, "green")
                else:
                    pnl_display = self._colorize(pnl_display, "red")
                
                print(f"{symbol:<10} {qty:>8} {avg_cost:>12.2f} {current_price:>12.2f} {pnl_display:>15} {market_value:>15,.0f}")
            
            print("-" * 70)
        else:
            print("\nPOSITIONS: None")
        
        # BOTTOM ROLLING FEED: last few trades, strategy messages
        recent_trades = recent_trades if recent_trades is not None else self._get_recent_trades()
        if recent_trades:
            print("\nRECENT TRADES (since open)")
            print("-" * 70)
            for trade in recent_trades:
                ts_value = trade.get("timestamp") or trade.get("ts")
                ts_str = str(ts_value) if ts_value is not None else "-"
                parsed_ts: Optional[datetime] = None
                if isinstance(ts_value, str):
                    try:
                        parsed_ts = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
                    except Exception:
                        parsed_ts = None
                elif isinstance(ts_value, datetime):
                    parsed_ts = ts_value
                
                if parsed_ts is not None:
                    ts_str = self._format_local_time(parsed_ts)
                
                symbol = trade.get("symbol", "")
                side = trade.get("side", "")
                quantity = trade.get("quantity", 0)
                price = trade.get("price", 0.0)
                pnl = trade.get("pnl_realized", 0.0)
                
                # Format side with color
                side_display = side
                if side == "BUY":
                    side_display = self._colorize(side, "green")
                elif side == "SELL":
                    side_display = self._colorize(side, "red")
                
                # Format PnL with color
                pnl_display = f"{pnl:+,.0f}"
                if pnl >= 0:
                    pnl_display = self._colorize(pnl_display, "green")
                else:
                    pnl_display = self._colorize(pnl_display, "red")
                
                print(f"{ts_str} | {side_display:<4} {quantity:>4} {symbol:<8} @ {price:>8.2f} | PnL: {pnl_display}")
            print("-" * 70)
        
        print()  # Blank line for readability

    def _print_hourly_summary(self, now: datetime) -> None:
        """Print hourly summary of portfolio performance."""
        if not self.metrics_history:
            return
        last_metrics = self.metrics_history[-1]
        metrics: TradeMetrics = last_metrics["metrics"]
        summary = self.portfolio.get_summary()
        local_time = now.astimezone(self._local_tz) if hasattr(self, "_local_tz") and self._local_tz else now
        
        # Calculate best/worst performing symbol
        positions = last_metrics.get("positions", [])
        best_symbol = None
        worst_symbol = None
        best_pnl = float('-inf')
        worst_pnl = float('inf')
        
        for pos in positions:
            unrealized_pnl = pos.get("unrealized_pnl", 0.0)
            symbol = pos.get("symbol", "")
            if unrealized_pnl > best_pnl:
                best_pnl = unrealized_pnl
                best_symbol = symbol
            if unrealized_pnl < worst_pnl:
                worst_pnl = unrealized_pnl
                worst_symbol = symbol
        
        # Get trades executed this hour
        hour_start = now - timedelta(hours=1)
        all_trades = self.portfolio.get_trades(limit=10000)
        trades_this_hour = []
        for trade in all_trades:
            try:
                trade_ts_str = trade.get("ts", "")
                if isinstance(trade_ts_str, str):
                    trade_ts = datetime.fromisoformat(trade_ts_str.replace("Z", "+00:00"))
                    if trade_ts >= hour_start:
                        trades_this_hour.append(trade)
            except:
                continue
        
        # Calculate win rate from trades this hour
        winning_trades = 0
        losing_trades = 0
        for trade in trades_this_hour:
            pnl = float(trade.get("pnl_realized", 0.0))
            if pnl > 0:
                winning_trades += 1
            elif pnl < 0:
                losing_trades += 1
        
        total_trades_with_pnl = winning_trades + losing_trades
        win_rate = (winning_trades / total_trades_with_pnl * 100) if total_trades_with_pnl > 0 else 0.0
        
        # Format summary
        sharpe_text = f"{metrics.sharpe_ratio:.2f}" if metrics.sharpe_ratio_available else "-"
        sortino_text = f"{metrics.sortino_ratio:.2f}" if metrics.sortino_ratio_available else "-"
        
        time_str = self._format_local_time(now)
        heartbeat_str = self._format_local_time(now, "%Y-%m-%d %H:%M:%S %Z")
        
        print("")
        print("-" * 70)
        log_line(f"HOURLY SUMMARY at {time_str}")
        print("-" * 70)
        log_line(f"Equity:              {summary.equity:,.0f} PKR")
        log_line(f"Total PnL:           {metrics.cumulative_pnl:+,.0f} PKR")
        
        # Best/worst performing symbol
        if best_symbol:
            best_pnl_str = f"{best_symbol} ({best_pnl:+,.0f} PKR)"
            if best_pnl >= 0:
                best_pnl_str = self._colorize(best_pnl_str, "green")
            log_line(f"Best Performer:      {best_pnl_str}")
        else:
            log_line("Best Performer:      None")
        
        if worst_symbol:
            worst_pnl_str = f"{worst_symbol} ({worst_pnl:+,.0f} PKR)"
            if worst_pnl < 0:
                worst_pnl_str = self._colorize(worst_pnl_str, "red")
            log_line(f"Worst Performer:     {worst_pnl_str}")
        else:
            log_line("Worst Performer:     None")
        
        log_line(f"Trades This Hour:    {len(trades_this_hour)}")
        log_line(f"Win Rate:            {win_rate:.1f}% ({winning_trades}W/{losing_trades}L)")
        log_line(f"Drawdown:            {metrics.max_drawdown_pct:.2f}%")
        log_line(f"Last Heartbeat:       {heartbeat_str}")
        print("-" * 70)
        print("")
    
    def _print_session_summary(self) -> None:
        """Print final session summary with all key metrics."""
        if not self.metrics_history:
            return
        
        last_metrics = self.metrics_history[-1]
        metrics: TradeMetrics = last_metrics["metrics"]
        summary = self.portfolio.get_summary()
        
        sharpe_text = f"{metrics.sharpe_ratio:.2f}" if metrics.sharpe_ratio_available else "-"
        sortino_text = f"{metrics.sortino_ratio:.2f}" if metrics.sortino_ratio_available else "-"
        
        # Count total trades (scoped to live session)
        total_trades = max(self._current_trade_count() - self._trade_count_baseline, 0)
        total_cycles = len(self.metrics_history)
        
        # Calculate final return correctly
        initial_equity = self._session_start_equity or self.portfolio.initial_cash
        final_return_pct = ((summary.equity - initial_equity) / initial_equity * 100) if initial_equity > 0 else 0.0
        
        return_str = f"{final_return_pct:+.2f}%"
        if final_return_pct >= 0:
            return_str = self._colorize(return_str, "green")
        else:
            return_str = self._colorize(return_str, "red")
        
        print("\n" + "-" * 70)
        print("SESSION SUMMARY")
        print("-" * 70)
        print(f"Total Cycles: {total_cycles} ({self._warm_start_cycles} warm-start + {total_cycles - self._warm_start_cycles} live)")
        print(f"Joined Mid-Session: {'Yes' if self._joined_mid_session else 'No'}")
        print(f"Total Trades: {total_trades}")
        print(f"Final Equity: {summary.equity:,.0f} PKR")
        print(f"Final Cash: {summary.cash:,.0f} PKR")
        print(f"Total Return: {return_str}")
        print(f"Sharpe Ratio: {sharpe_text}")
        print(f"Max Drawdown: {metrics.max_drawdown_pct:.2f}%")
        
        # Show all positions
        positions = last_metrics.get("positions", [])
        if positions:
            pos_parts = [
                f"{p['symbol']} {p['qty']} @ {p['current_price']:.2f}"
                for p in positions
            ]
            log_line(f"Positions: {' | '.join(pos_parts)}")
        else:
            log_line("Positions: None")
        
        # Show CSV file locations
        log_line(f"Metrics CSV: {self.csv_writer.metrics_path}")
        log_line(f"Trades CSV: {self.csv_writer.trades_path}")
        positions_csv = self.csv_writer.metrics_path.parent / f"{self.csv_writer.metrics_path.stem}_positions.csv"
        if positions_csv.exists():
            log_line(f"Positions CSV: {positions_csv}")
        print("")

    async def _sleep_until_next_cycle(self) -> None:
        if self._sleep_seconds is not None:
            await asyncio.sleep(self._sleep_seconds)
            return
            
        now = now_tz()
        cycle_minutes = self.config.cycle_minutes
        is_long_cycle = cycle_minutes >= 1440  # >= 1 day
        
        # --- MARKET CLOSED CHECK ---
        if not is_market_open(now):
            # Market is closed, wait until next market open
            next_open = next_market_open(now)
            delay = max(60.0, (next_open - now).total_seconds())
            local_time = now.astimezone(self._local_tz) if hasattr(self, "_local_tz") and self._local_tz else now
            next_open_local = next_open.astimezone(self._local_tz) if hasattr(self, "_local_tz") and self._local_tz else next_open
            current_label = self._format_local_time(local_time)
            next_label = self._format_local_time(next_open_local)
            log_line(f"Market closed at {current_label}. Waiting until next session at {next_label}...")
            await asyncio.sleep(min(delay, 3600.0))  # Sleep max 1 hour at a time
            return
        
        # --- CALCULATE DELAY ---
        next_cycle = self._next_cycle_ts(now)
        delay = max(5.0, (next_cycle - now).total_seconds())
        end_time = now.timestamp() + delay
        
        if delay > 60:
            local_time = now.astimezone(self._local_tz) if hasattr(self, "_local_tz") and self._local_tz else now
            next_cycle_local = next_cycle.astimezone(self._local_tz) if hasattr(self, "_local_tz") and self._local_tz else next_cycle
            next_label = self._format_local_time(next_cycle_local)
            
            # Format cycle description for long cycles
            if is_long_cycle:
                days = cycle_minutes // 1440
                cycle_desc = f"{days}-day" if days != 7 else "weekly"
                if days == 1: cycle_desc = "daily"
                elif days >= 28: cycle_desc = f"monthly (~{days} days)"
                
                log_line(f"Waiting for next {cycle_desc} cycle at {next_label}...")
            else:
                log_line(f"Waiting for next {cycle_minutes}-minute batch at {next_label}...")

        # --- PREPARE FOR UPDATES ---
        # Get active positions to update
        try:
            summary = self.portfolio.get_summary()
            active_symbols = [p['symbol'] for p in summary.positions if p.get('symbol')]
        except Exception:
            active_symbols = []
            
        update_interval = 15.0 # Check every 15s (allows time for 10-15 API calls @ 0.6s)
        
        # --- WAIT LOOP WITH UPDATES ---
        while True:
            now_ts = now_tz().timestamp()
            remaining = end_time - now_ts
            
            if remaining <= 0:
                break
                
            # If delay is short or no positions, just sleep
            if remaining < update_interval or not active_symbols:
                await asyncio.sleep(remaining)
                break
                
            # Sleep for interval
            await asyncio.sleep(min(update_interval, remaining))
            
            # Perform update (only if we have active positions)
            try:
                # 1. Fetch latest prices for active positions
                # Note: This is sequential due to rate limit, so it takes time
                prices = {}
                for sym in active_symbols:
                    try:
                        if hasattr(self.service, 'get_price'):
                            data = self.service.get_price(sym)
                            if data and data.get('price'):
                                from ...data.paper_spread import mark_to_market_price

                                qty = next(
                                    (float(p.get('qty') or 0) for p in summary.positions if p.get('symbol') == sym),
                                    0.0,
                                )
                                prices[sym] = mark_to_market_price(data, qty=qty)
                    except Exception:
                        pass
                
                if prices:
                    # 2. Revalue portfolio
                    current_time = now_tz()
                    self.portfolio.revalue_and_snapshot(current_time, prices)
                    
                    # 3. Publish Telemetry Update
                    summary_update = self.portfolio.get_summary(prices)
                    
                    # Construct update report
                    # Using local imports to avoid circular deps
                    from .telemetry import CycleReport
                    from ..portfolio.metrics import compute_portfolio_metrics
                    
                    # Get positions value
                    positions_value = sum(
                        float(p.get("qty", 0)) * float(prices.get(p["symbol"], p.get("avg_cost", 0)))
                        for p in summary_update.positions
                        if p.get("symbol") in prices or p.get("avg_cost")
                    )
                    
                    total_equity = float(summary_update.cash) + positions_value
                    
                    # Get historical context for accurate metrics
                    # Use get_equity_curve() from portfolio service which handles history
                    equity_curve_history = self.portfolio.get_equity_curve(limit=500)
                    
                    # Append current interim point (since it might not be in history yet if verify_and_snapshot wasn't fully committed or if get_equity_curve pulls from db)
                    # Actually revalue_and_snapshot writes to DB, so get_equity_curve should include it.
                    # But just in case, we ensure it's there.
                    
                    recent_trades = self._get_recent_trades()
                    
                    # Compute metrics
                    metrics = compute_portfolio_metrics(
                        portfolio=self.portfolio, # Pass service to let it fetch full history
                        timestamp=current_time,
                        latest_prices=prices,
                        trades_snapshot=recent_trades,
                        initial_capital=self._initial_capital
                    )
                    
                    # Determine Status
                    status = "running"
                    
                    report = CycleReport(
                        bot_id=self.bot_id,
                        timestamp=current_time,
                        status=status,
                        equity=total_equity,
                        cash=float(summary_update.cash),
                        positions_value=positions_value,
                        metrics=metrics["metrics"], # Use the calculated metrics object
                        positions=summary_update.positions,
                        trades=[], # No new trades in wait period
                        prices=prices,
                        batches=[],
                        recent_trades=recent_trades, # Pass recent trades so dashboard shows them
                    )
                    
                    if self._telemetry:
                        self._telemetry.publish(report)
                        # log_line(f"Generated interim update: Equity {total_equity:,.0f}")
                        
            except Exception as e:
                # Don't crash wait loop on update failure
                # log_line(f"Interim update failed: {e}")
                pass

    def _next_cycle_ts(self, now: datetime) -> datetime:
        """
        Calculate the next cycle timestamp, aligned to cycle boundaries.
        Supports cycles from 15 minutes to 30 days (weekly/monthly trading).
        
        For intraday cycles (< 1 day): Aligns to 15-minute boundaries within trading hours.
        For daily/weekly/monthly cycles: Aligns to market open on the target day, skipping weekends.
        """
        cycle_minutes = self.config.cycle_minutes
        is_long_cycle = cycle_minutes >= 1440  # >= 1 day (1440 minutes)
        
        if self._session_start is None or self._session_end is None:
            self._session_start, session_market_close = today_session_window(now)
            # Extend session end by 15 minutes to allow processing final batch
            # Market closes at 3:30 PM, but paper trading continues until 3:45 PM
            self._session_end = session_market_close + timedelta(minutes=15)
        
        if self._last_cycle_close is None:
            # First cycle - calculate next cycle from now
            if is_long_cycle:
                # For long cycles, align to market open on the target day
                days_ahead = cycle_minutes // 1440
                target_date = now.date() + timedelta(days=days_ahead)
                # Skip weekends
                while target_date.weekday() >= 5:
                    target_date += timedelta(days=1)
                # Create datetime for target date at market open
                open_hour = settings.market_hours.open_hour
                open_minute = settings.market_hours.open_minute
                target_dt = datetime.combine(target_date, dt_time(open_hour, open_minute))
                if now.tzinfo:
                    target_dt = target_dt.replace(tzinfo=now.tzinfo)
                session_start, _ = today_session_window(target_dt)
                return session_start
            else:
                # For intraday cycles, align to next cycle boundary
                return self._floor_to_cycle(now) + self._cycle_delta
        
        # Next cycle is last cycle + cycle_delta
        target = self._last_cycle_close + self._cycle_delta
        
        if is_long_cycle:
            # For long cycles, ensure target is on a trading day (skip weekends)
            while target.weekday() >= 5:
                target += timedelta(days=1)
            # Align to market open on that day
            session_start, _ = today_session_window(target)
            if target < session_start:
                target = session_start
            elif target > session_start.replace(hour=15, minute=30):
                # If past market close, move to next trading day
                target = next_market_open(target)
            return target
        
        # For intraday cycles: handle session boundaries
        if self._session_end and target >= self._session_end:
            # Cycle extends past session end - wait until next market open
            return next_market_open(now)
        
        # If target is in the past (shouldn't happen, but handle gracefully)
        if target <= now:
            # Align to next cycle boundary from now
            next_boundary = self._floor_to_cycle(now) + self._cycle_delta
            # If next boundary is past session end, move to next market open
            if self._session_end and next_boundary >= self._session_end:
                return next_market_open(now)
            return max(next_boundary, now + timedelta(seconds=5))
        
        return target

    def _serialize_trade(self, trade: Any) -> Dict[str, Any]:
        return {
            "id": trade.id,
            "timestamp": trade.ts.isoformat() if isinstance(trade.ts, datetime) else None,
            "symbol": trade.symbol,
            "side": trade.side,
            "quantity": trade.quantity,
            "price": float(trade.price),
            "cost": float(trade.cost),
            "pnl_realized": float(trade.pnl_realized),
            "commission": float(getattr(trade, "fees", 0.0)),
            "slippage_bps": float(getattr(trade, "slippage_bps", 0.0)),
            "source": self.bot_id,
            "strategy_name": self._strategy_name,
            "execution_type": "average_cost",
        }

    def _current_trade_count(self) -> int:
        try:
            return len(self.portfolio.get_trades(limit=10_000))
        except Exception:
            return 0

    def _publish_cycle(
        self,
        ts: datetime,
        payload: Dict[str, Any],
        prices: Dict[str, float],
        trades: List[Dict[str, Any]],
        batches: List[Dict[str, Any]],
        *,
        total_fees: float,
        avg_slippage_bps: float,
        recent_trades: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        summary_equity = float(payload["equity"])
        summary_cash = float(payload["cash"])
        positions_value = float(payload["positions_value"])
        metrics: TradeMetrics = payload["metrics"]
        report = CycleReport(
            bot_id=self.bot_id,
            timestamp=ts,
            status="ok",
            equity=summary_equity,
            cash=summary_cash,
            positions_value=positions_value,
            metrics=metrics,
            positions=payload["positions"],
            trades=trades,
            prices={k: float(v) for k, v in prices.items()},
            batches=batches,
            total_fees=total_fees,
            avg_slippage_bps=avg_slippage_bps,
            recent_trades=recent_trades or [],
            initial_cash=self.portfolio.initial_cash,  # Send starting capital
        )
        log_line(f"[{self.bot_id}] Publishing cycle report: equity={summary_equity:.2f}, positions={len(payload['positions'])}")
        self._telemetry.publish(report)
        
        # CRITICAL FIX: Send portfolio state to backend via HTTP
        # This is the missing link - backend needs portfolio updates to reflect state
        if self._backend_client:
            try:
                self._backend_client.update_portfolio(
                    equity=summary_equity,
                    cash=summary_cash,
                    positions=payload["positions"],  # List of {symbol, qty, avg_cost, current_price}
                    positions_value=positions_value,
                    timestamp=ts,
                    status="ok",
                    recent_trades=recent_trades or [],
                    initial_cash=self.portfolio.initial_cash,
                )
                log_line(f"[{self.bot_id}] ✓ Portfolio state sent to backend (equity={summary_equity:.2f})")
            except Exception as exc:
                log_line(f"[{self.bot_id}] ⚠ Warning: Failed to send portfolio update to backend: {exc}")

    def _determine_strategy_name(self, strategy: Any) -> str:
        if hasattr(strategy, "name") and isinstance(getattr(strategy, "name"), str):
            return getattr(strategy, "name")
        strategy_cls = getattr(strategy, "__class__", None)
        if strategy_cls and hasattr(strategy_cls, "__name__"):
            return strategy_cls.__name__
        if isinstance(strategy, str):
            return strategy
        return "custom_strategy"

    def _publish_snapshot(self, ts: datetime, status: str) -> None:
        summary = self.portfolio.get_summary()
        recent_trades = self._get_recent_trades()
        report = CycleReport(
            bot_id=self.bot_id,
            timestamp=ts,
            status=status,
            equity=float(summary.equity),
            cash=float(summary.cash),
            positions_value=max(float(summary.equity) - float(summary.cash), 0.0),
            metrics=TradeMetrics(
                total_return_pct=0.0,
                daily_return_pct=0.0,
                session_return_pct=0.0,
                cumulative_return_pct=0.0,
                sharpe_ratio=0.0,
                session_sharpe_ratio=0.0,
                sortino_ratio=0.0,
                max_drawdown_pct=0.0,
                volatility_pct=0.0,
                win_loss_ratio=0.0,
                exposure_pct=0.0,
                turnover_pct=0.0,
                cumulative_pnl=float(summary.realized_pnl + summary.unrealized_pnl),
                sharpe_ratio_available=False,
                session_sharpe_ratio_available=False,
                sortino_ratio_available=False,
                volatility_available=False,
                win_loss_ratio_available=False,
            ),
            positions=summary.positions,
            trades=[],
            prices={},
            batches=[],
            total_fees=0.0,
            avg_slippage_bps=0.0,
            recent_trades=recent_trades or [],
        )
        self._telemetry.publish(report)

    def _build_telemetry(
        self,
        telemetry: Optional[CompositeTelemetry],
        in_process_push: Optional[Any],
    ) -> tuple[CompositeTelemetry, Optional[TelemetryClient]]:
        if telemetry:
            return telemetry, None

        sinks: List[Any] = []
        
        # Initialize SessionManager for persistent session tracking
        self.session_manager = SessionManager(
            bot_id=self.bot_id,
            log_dir=self.config.log_dir
        )
        
        # Start new session with current configuration
        mode = "live-warm" if self.config.warm_start else "paper-live"
        initial_cash = self.config.initial_cash or 1_000_000.0
        
        self.session_manager.start_session(
            mode=mode,
            initial_cash=initial_cash,
            symbols=self.symbols,
            config={
                "cycle_minutes": self.config.cycle_minutes,
                "position_notional": self.config.position_notional,
                "warm_start": self.config.warm_start,
            }
        )
        
        log_line(f"[{self.bot_id}] Started session: {self.session_manager.current_session.session_id}")
        
        # Add session-aware telemetry (writes to session-scoped files)
        sinks.append(SessionTelemetry(self.session_manager, self.bot_id))
        
        # Keep legacy FileTelemetry for backward compatibility
        sinks.append(FileTelemetry(self.config.log_dir, self.bot_id))
        
        backend_client: Optional[TelemetryClient] = None

        if in_process_push is not None:
            log_line(f"[{self.bot_id}] Using CallbackTelemetry (dashboard mode)")
            sinks.append(CallbackTelemetry(in_process_push))
        elif self.config.backend_url and self.config.api_token and not self.config.local_mode:
            log_line(f"[{self.bot_id}] ✓ Initializing BackendRelayTelemetry")
            log_line(f"[{self.bot_id}]   Backend URL: {self.config.backend_url}")
            log_line(f"[{self.bot_id}]   Token: {self.config.api_token[:10]}...")
            client = TelemetryClient(
                bot_id=self.bot_id,
                api_token=self.config.api_token,
                account_id=self.config.account_id,
                backend_url=self.config.backend_url,
                bot_label=self.bot_id,
                user_id=self.config.user_id,
                use_jwt_auth=self.config.use_jwt_auth,
            )
            sinks.append(BackendRelayTelemetry(client))
            backend_client = client
            log_line(f"[{self.bot_id}] ✓ Backend telemetry ready - will push to {self.config.backend_url}")
        elif self.config.local_mode:
            log_line(f"[{self.bot_id}] 📁 Local mode: Using local files only (no backend)")
        else:
            log_line(f"[{self.bot_id}] ⚠ WARNING: No backend telemetry (backend_url={self.config.backend_url}, token={bool(self.config.api_token)})")

        if not sinks:
            log_line(f"[{self.bot_id}] Using NullTelemetry (no sinks configured)")
            sinks.append(NullTelemetry())

        return CompositeTelemetry(sinks), backend_client

    def _build_backend_log_hook(self) -> Optional[Callable[[str, str, Dict[str, Any], str], None]]:
        client = self._backend_client
        if not client:
            return None

        def _hook(level: str, message: str, context: Dict[str, Any], stream: str) -> None:
            try:
                client.log_event(
                    message=message,
                    level=level,
                    context=context,
                    stream=stream,
                )
            except Exception as exc:
                log_line(f"[{self.bot_id}] Failed to push {stream} log: {exc}")

        return _hook

    def _log_system_event(self, event: str, message: str, level: str = "info", **context: Any) -> None:
        if hasattr(self, "_paper_logger") and self._paper_logger:
            self._paper_logger.log_system(
                event=event,
                message=message,
                level=level,
                context=context or None,
            )

    def _restore_positions_from_account(self, positions: Dict[str, Dict[str, float]]) -> None:
        """Restore positions from account state JSON.
        
        Positions now include both quantity and avg_cost, enabling accurate PnL calculations.
        """
        if not positions:
            return
        
        from ..portfolio.service import Position, Session
        
        # Restore positions to portfolio with saved avg_cost
        with Session(self.portfolio.engine, expire_on_commit=False) as session:
            for symbol, pos_data in positions.items():
                qty = int(pos_data.get("qty", 0))
                avg_cost = float(pos_data.get("avg_cost", 0.0))
                
                if qty == 0:
                    continue
                
                pos = session.get(Position, symbol)
                if pos is None:
                    pos = Position(symbol=symbol, quantity=qty, avg_cost=avg_cost)
                    session.add(pos)
                    log_line(f"Restored position: {symbol} x {qty} @ {avg_cost:.2f}")
                else:
                    # Position exists - update with saved values
                    pos.quantity = qty
                    pos.avg_cost = avg_cost
                    log_line(f"Updated position: {symbol} x {qty} @ {avg_cost:.2f}")
            session.commit()
        
        if positions:
            log_line(f"Restored {len(positions)} positions from account state")

    def get_today_first_price(self, symbol: str) -> Optional[float]:
        """
        Get today's first trade price for a symbol.
        
        This is the opening price used for PnL normalizations and summary stats.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            First price of the day, or None if no trades yet today
        """
        return self._symbol_open_price_today.get(symbol)
    
    def get_today_first_trade_time(self, symbol: str) -> Optional[datetime]:
        """
        Get today's first trade timestamp for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            First trade timestamp of the day, or None if no trades yet today
        """
        return self._symbol_first_trade_time.get(symbol)
    
    def _sync_initial_portfolio(self) -> None:
        """Sync initial portfolio state to backend after positions are restored."""
        try:
            if not self._telemetry or not hasattr(self._telemetry, 'publish'):
                return
            
            summary = self.portfolio.get_summary()
            if not summary.positions:
                return  # No positions to sync
            
            # Get current prices for positions
            # Priority: 1) intraday_cache, 2) last_seen_price, 3) avg_cost from position
            prices: Dict[str, float] = {}
            for pos in summary.positions:
                symbol = pos.get("symbol")
                if not symbol:
                    continue
                
                price = None
                
                # 1. Try intraday cache (most reliable at startup)
                if symbol in self._intraday_cache and not self._intraday_cache[symbol].empty:
                    df = self._intraday_cache[symbol]
                    if 'close' in df.columns:
                        price = float(df["close"].iloc[-1])
                    elif 'price' in df.columns:
                        price = float(df["price"].iloc[-1])
                
                # 2. Try last seen price
                if price is None or price <= 0:
                    price = self._last_seen_price.get(symbol)
                
                # 3. Use avg_cost as fallback (always available from restored positions)
                if price is None or price <= 0:
                    price = pos.get("avg_cost", 0.0)
                
                if price and price > 0:
                    prices[symbol] = price
            
            # If we still don't have prices, use avg_cost for all positions
            if not prices:
                log_line("⚠️ No market prices available for initial sync, using avg_cost")
                for pos in summary.positions:
                    symbol = pos.get("symbol")
                    avg_cost = pos.get("avg_cost", 0.0)
                    if symbol and avg_cost > 0:
                        prices[symbol] = avg_cost
            
            if not prices:
                # Still no prices at all, skip sync
                log_line("⚠️ No prices available for initial portfolio sync, will sync on first cycle")
                return
            
            # Revalue portfolio with current prices
            self.portfolio.revalue_and_snapshot(now_tz(), prices)
            
            # Build positions snapshot
            positions_snapshot, positions_value, _ = self._build_positions_snapshot(
                summary.positions,
                prices,
            )
            
            total_equity = float(summary.cash) + positions_value
            
            # Create a minimal cycle report for initial sync
            from .telemetry import CycleReport
            from ..portfolio.metrics import TradeMetrics
            
            initial_report = CycleReport(
                bot_id=self.bot_id,
                timestamp=now_tz(),
                status="running",
                equity=total_equity,
                cash=float(summary.cash),
                positions_value=positions_value,
                metrics=TradeMetrics(
                    total_return_pct=0.0,
                    daily_return_pct=0.0,
                    session_return_pct=0.0,
                    cumulative_return_pct=0.0,
                    sharpe_ratio=0.0,
                    session_sharpe_ratio=0.0,
                    sortino_ratio=0.0,
                    max_drawdown_pct=0.0,
                    volatility_pct=0.0,
                    win_loss_ratio=0.0,
                    exposure_pct=0.0,
                    turnover_pct=0.0,
                    cumulative_pnl=0.0,
                ),
                positions=positions_snapshot,
                trades=[],
                prices=prices,
                batches=[],
            )
            
            # Publish initial portfolio state
            self._telemetry.publish(initial_report)
            log_line(f"✅ Synced initial portfolio to backend: {len(positions_snapshot)} position(s), equity Rs. {total_equity:,.2f}")
            pos_list = ', '.join([f"{p.get('symbol')} x {p.get('qty')}" for p in positions_snapshot])
            log_line(f"   Positions: {pos_list}")
            
        except Exception as exc:
            log_line(f"⚠️ Failed to sync initial portfolio: {exc}")
            import traceback
            traceback.print_exc()
    
    def _load_queued_signals_from_storage(self) -> None:
        """Load queued signals from persistent storage."""
        try:
            stored_signals = self.signal_queue.get_queued_signals(status='queued')
            if not stored_signals:
                return
            
            log_line(f"Loading {len(stored_signals)} queued signal(s) from persistent storage...")
            
            for sig_data in stored_signals:
                # Reconstruct SignalSnapshot from stored data
                snapshot = SignalSnapshot(
                    symbol=sig_data['symbol'],
                    side=sig_data['side'],
                    strategy_signal=sig_data['strategy_signal'],
                    bias=sig_data['bias'],
                    generated_at=sig_data['generated_at'],
                    signal_price=sig_data['signal_price'],
                    vwap=sig_data['vwap'],
                    target_qty=sig_data['target_qty'],
                    note=sig_data['note'],
                    delta_pct=sig_data['delta_pct'],
                    batch_label=sig_data.get('batch_label'),
                )
                # Store signal_id for later reference
                snapshot.signal_id = sig_data['signal_id']  # type: ignore
                self._queued_signals.append(snapshot)
            
            if stored_signals:
                log_line(f"✅ Loaded {len(stored_signals)} queued signal(s) from storage")
        except Exception as exc:
            log_line(f"⚠️ Failed to load queued signals from storage: {exc}")
    
    def _save_signal_to_queue(self, snapshot: SignalSnapshot) -> None:
        """Save signal to persistent storage."""
        try:
            signal_id = self.signal_queue.enqueue_signal(
                symbol=snapshot.symbol,
                side=snapshot.side,
                strategy_signal=snapshot.strategy_signal,
                bias=snapshot.bias,
                generated_at=snapshot.generated_at,
                signal_price=snapshot.signal_price,
                vwap=snapshot.vwap,
                target_qty=snapshot.target_qty,
                note=snapshot.note,
                delta_pct=snapshot.delta_pct,
                batch_label=snapshot.batch_label,
            )
            # Store signal_id in snapshot for later reference
            snapshot.signal_id = signal_id  # type: ignore
        except Exception as exc:
            log_line(f"⚠️ Failed to save signal to persistent storage: {exc}")
    
__all__ = ["TradingEngine", "EngineConfig", "TradeMetrics", "SignalSnapshot"]

