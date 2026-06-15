"""Trading configuration."""

import os
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class TradingMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"

@dataclass
class TradingConfig:
    """Trading client configuration."""
    
    queue_orders: bool = False
    """Whether to queue orders outside market hours."""
    
    check_market_hours: bool = True
    """Whether to check market hours before order submission."""
    
    bot_id: Optional[str] = None
    """Bot identifier for queued orders."""
    
    user_id: Optional[str] = "default"
    """User identifier for bot tracking."""

    mode: TradingMode = TradingMode.PAPER
    """Mode of operation: PAPER (live paper trading) or BACKTEST (historical/backtest)."""
    allow_short: bool = False
    """Whether short-selling is allowed for this client. Defaults to False for main strategies."""
    
    def get_store_path(self, bot_id: Optional[str] = None) -> str:
        """Get path for local storage."""
        base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "store")
        os.makedirs(base_dir, exist_ok=True)
        return os.path.join(base_dir, f"{bot_id or self.bot_id or 'default'}.db")