from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class MarketHours:
    open_hour: int = 9
    open_minute: int = 32  # PSX opens at 9:32 AM
    close_hour: int = 15
    close_minute: int = 30  # PSX closes at 3:30 PM


@dataclass
class Settings:
    # Database
    db_url: str = os.getenv("PYTRADER_DB_URL", "sqlite:///data/trader.db")

    # DEPRECATED: PSX backend via pypsx-library (15-minute delay)
    # Only use for backtesting or fallback - NOT recommended for live trading
    psx_base_url: str = os.getenv(
        "PYPSX_BASE_URL",
        "",  # Empty by default - pypsx-library is fallback only
    )
    http_timeout_seconds: int = int(os.getenv("PYPSX_TIMEOUT", "30"))

    # PSX Terminal API (RECOMMENDED for live/paper trading - real-time data)
    psx_terminal_base_url: str = os.getenv(
        "PSX_TERMINAL_BASE_URL",
        "https://psxterminal.com/api"
    )
    psx_terminal_ws_url: str = os.getenv(
        "PSX_TERMINAL_WS_URL",
        "wss://psxterminal.com/"
    )
    psx_terminal_timeout: int = int(os.getenv("PSX_TERMINAL_TIMEOUT", "15"))

    # Market
    market_hours: MarketHours = MarketHours()
    timezone: str = os.getenv("PYTRADER_TZ", "Asia/Karachi")

    # Trading defaults
    default_cash: float = float(os.getenv("PYTRADER_CASH", "1000000"))
    default_symbols: List[str] = field(default_factory=lambda: (os.getenv("PYTRADER_SYMBOLS", "").split(",") if os.getenv("PYTRADER_SYMBOLS") else []))
    position_size_pk: float = float(os.getenv("PYTRADER_POSITION_SIZE_PK", "100000"))  # notional per trade by default
    min_lot: int = int(os.getenv("PYTRADER_MIN_LOT", "1"))

    # Scheduler
    alignment_minutes: int = int(os.getenv("PYTRADER_ALIGN_MIN", "15"))

    # API Authentication
    api_keys: List[str] = field(default_factory=lambda: (os.getenv("PYTRADER_API_KEYS", "").split(",") if os.getenv("PYTRADER_API_KEYS") else []))
    require_api_key: bool = os.getenv("PYTRADER_REQUIRE_API_KEY", "false").lower() == "true"
    
    # Hosted PyTrader API (Render). Override PYTRADER_BACKEND_URL for a different deployment.
    backend_url: str = os.getenv("PYTRADER_BACKEND_URL", "https://api.pypsx.com").rstrip("/")

    # Hosted PyTrader Paper API. Override PYTRADER_PAPER_BACKEND_URL for paper trading deployments.
    paper_backend_url: str = os.getenv("PYTRADER_PAPER_BACKEND_URL", "https://paper-api.pypsx.com").rstrip("/")

    # Optional explicit WS base override. If not set, derived from backend_url/paper_backend_url.
    backend_ws_url: str = os.getenv("PYTRADER_BACKEND_WS_URL", "").rstrip("/")

    def resolve_backend_url(self, *, paper: bool) -> str:
        return (self.paper_backend_url if paper else self.backend_url).rstrip("/")

    def resolve_backend_ws_base(self, *, paper: bool) -> str:
        """
        Return websocket base url (ws:// or wss://) for the selected backend.
        """
        explicit = str(self.backend_ws_url or "").strip()
        if explicit:
            return explicit.rstrip("/")
        base = self.resolve_backend_url(paper=paper)
        if base.startswith("https://"):
            return base.replace("https://", "wss://", 1)
        if base.startswith("http://"):
            return base.replace("http://", "ws://", 1)
        if base.startswith("wss://") or base.startswith("ws://"):
            return base.rstrip("/")
        return "wss://" + base.lstrip("/").rstrip("/")

    @property
    def BACKEND_WS_URL(self) -> str:
        """
        Primary WebSocket base for algo bots (paper backend).
        Set `PYTRADER_BACKEND_WS_URL` or derive from `PYTRADER_PAPER_BACKEND_URL`.
        """
        return self.resolve_backend_ws_base(paper=True)


settings = Settings()

