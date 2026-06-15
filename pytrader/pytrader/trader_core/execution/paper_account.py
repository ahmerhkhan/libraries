"""
Persistent paper trading account state management.

Handles storage and retrieval of paper trading account state (cash, positions, equity)
across sessions, similar to Alpaca's paper trading model.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils import log_line, now_tz


@dataclass
class PaperAccountState:
    """Paper trading account state snapshot."""
    user_id: str
    bot_id: str  # Bot identifier for isolation
    cash: float
    positions: Dict[str, Dict[str, float]]  # symbol -> {qty: int, avg_cost: float}
    equity: float
    last_update: str  # ISO format timestamp
    account_id: Optional[str] = None  # Optional account identifier
    initial_capital: Optional[float] = None  # Original starting capital for total return calculation

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PaperAccountState:
        """Create from dictionary."""
        return cls(**data)


class PaperAccountManager:
    """Manages persistent paper trading account state."""

    def __init__(
        self,
        user_id: str = "default",
        bot_id: str = "default",
        data_dir: Path = Path("user_data/accounts"),
        default_cash: float = 1_000_000.0,
    ) -> None:
        self.user_id = user_id
        self.bot_id = bot_id
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Include bot_id in file path for proper isolation
        self.account_file = self.data_dir / f"{user_id}-{bot_id}.json"
        self.default_cash = default_cash

    def load_account(self) -> Optional[PaperAccountState]:
        """Load account state from disk."""
        if not self.account_file.exists():
            return None
        try:
            with self.account_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                state = PaperAccountState.from_dict(data)
                # Validate that loaded state matches expected bot_id
                if state.bot_id != self.bot_id:
                    log_line(
                        f"[WARN] Loaded account state has bot_id={state.bot_id}, "
                        f"expected {self.bot_id}. State mismatch - returning None."
                    )
                    return None
                return state
        except Exception as exc:
            log_line(f"[WARN] Failed to load account state from {self.account_file}: {exc}")
            return None

    def save_account(
        self,
        cash: float,
        positions: Dict[str, Dict[str, float]],  # symbol -> {qty: int, avg_cost: float}
        equity: float,
        account_id: Optional[str] = None,
        initial_capital: Optional[float] = None,
    ) -> None:
        """Save account state to disk.
        
        Args:
            cash: Current cash balance
            positions: Dict mapping symbol to {qty, avg_cost}
            equity: Total equity value
            account_id: Optional account identifier
            initial_capital: Original starting capital (preserved from first run)
        """
        # Load existing state to preserve initial_capital if not provided
        existing_initial_capital = None
        if initial_capital is None:
            existing_state = self.load_account()
            if existing_state:
                existing_initial_capital = existing_state.initial_capital
        
        state = PaperAccountState(
            user_id=self.user_id,
            bot_id=self.bot_id,
            cash=cash,
            positions=positions,
            equity=equity,
            last_update=now_tz().isoformat(),
            account_id=account_id,
            initial_capital=initial_capital or existing_initial_capital,
        )
        try:
            with self.account_file.open("w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2)
        except Exception as exc:
            log_line(f"[WARN] Failed to save account state to {self.account_file}: {exc}")

    def reset_account(self, initial_cash: Optional[float] = None) -> PaperAccountState:
        """Reset account to initial state (cash only, no positions)."""
        cash = initial_cash if initial_cash is not None else self.default_cash
        state = PaperAccountState(
            user_id=self.user_id,
            bot_id=self.bot_id,
            cash=cash,
            positions={},
            equity=cash,
            last_update=now_tz().isoformat(),
            initial_capital=cash,  # Set initial_capital on reset
        )
        self.save_account(cash, {}, cash, initial_capital=cash)
        log_line(f"[INFO] Reset paper account for {self.user_id}/{self.bot_id}: cash={cash:,.0f}")
        return state

    def get_account_summary(self) -> Dict[str, Any]:
        """Get current account summary."""
        state = self.load_account()
        if state is None:
            return {
                "user_id": self.user_id,
                "cash": self.default_cash,
                "positions": {},
                "equity": self.default_cash,
                "exists": False,
            }
        return {
            "user_id": state.user_id,
            "cash": state.cash,
            "positions": state.positions,
            "equity": state.equity,
            "last_update": state.last_update,
            "exists": True,
        }


__all__ = ["PaperAccountManager", "PaperAccountState"]

