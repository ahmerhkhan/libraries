"""Mean reversion templates for PSX equities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .base import BaseStrategy


@dataclass
class BollingerMeanReversionStrategy(BaseStrategy):
    """Classic Bollinger-band revert-to-mean strategy."""

    period: int = 20
    std_dev: float = 2.0
    symbol: Optional[str] = None

    def __post_init__(self) -> None:
        self.min_history_bars = max(self.period + 2, 2)

    @staticmethod
    def _ensure_close(df: pd.DataFrame) -> pd.DataFrame:
        if "close" in df.columns:
            return df
        if "price" in df.columns:
            clone = df.copy()
            clone["close"] = clone["price"]
            return clone
        raise ValueError("DataFrame must have 'close' or 'price' column")

    def generate_signals(self, historical_data: pd.DataFrame) -> pd.DataFrame:
        df = self._ensure_close(historical_data.copy())
        rolling = df["close"].rolling(window=self.period, min_periods=self.period)
        df["ma"] = rolling.mean()
        df["std"] = rolling.std()
        df["upper"] = df["ma"] + self.std_dev * df["std"]
        df["lower"] = df["ma"] - self.std_dev * df["std"]

        df["signal"] = 0
        df.loc[df["close"] <= df["lower"], "signal"] = 1
        df.loc[df["close"] >= df["upper"], "signal"] = -1
        df.loc[df["ma"].isna(), "signal"] = 0
        return df


@dataclass
class VWAPReversionStrategy(BaseStrategy):
    """Intraday VWAP reversion with simple bias."""

    lookback: int = 30
    threshold_pct: float = 0.8
    symbol: Optional[str] = None

    def __post_init__(self) -> None:
        self.min_history_bars = max(self.lookback + 2, 2)

    def generate_signals(self, historical_data: pd.DataFrame) -> pd.DataFrame:
        if "close" not in historical_data or "volume" not in historical_data:
            raise ValueError("DataFrame must include 'close' and 'volume'")

        df = historical_data.copy()
        close = df["close"].astype(float)
        volume = df["volume"].astype(float).clip(lower=0)

        price_vol = close * volume
        rolling_vol = volume.rolling(self.lookback, min_periods=self.lookback).sum()
        rolling_price_vol = price_vol.rolling(self.lookback, min_periods=self.lookback).sum()
        df["vwap"] = rolling_price_vol / rolling_vol

        deviation = (close - df["vwap"]) / df["vwap"] * 100.0
        df["signal"] = 0
        df.loc[deviation <= -self.threshold_pct, "signal"] = 1
        df.loc[deviation >= self.threshold_pct, "signal"] = -1
        df.loc[df["vwap"].isna(), "signal"] = 0
        return df


__all__ = ["BollingerMeanReversionStrategy", "VWAPReversionStrategy"]


