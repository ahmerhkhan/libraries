"""Core strategy abstraction for the PyTrader SDK."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    """All trading strategies must implement :meth:`generate_signals`.

    The returned DataFrame must contain a ``signal`` column with:

    * ``1``  – BUY
    * ``-1`` – SELL
    * ``0``  – HOLD
    """

    min_history_bars: int = 0

    @abstractmethod
    def generate_signals(self, historical_data: pd.DataFrame) -> pd.DataFrame:
        """Produce a signal column from the supplied OHLCV data."""

    def generate_signal(self, symbol: str, historical_data: pd.DataFrame) -> str:
        """Convenience wrapper returning only the latest BUY/SELL/HOLD decision."""
        df = self.generate_signals(historical_data)
        if df is None or df.empty or "signal" not in df:
            return "HOLD"
        latest = df["signal"].iloc[-1]
        if latest > 0:
            return "BUY"
        if latest < 0:
            return "SELL"
        return "HOLD"

    def get_name(self) -> str:
        """Return a human readable strategy name."""
        return self.__class__.__name__


__all__ = ["BaseStrategy"]


