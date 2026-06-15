"""Classic SMA momentum strategies tailored for PSX."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .base import BaseStrategy


@dataclass
class SMAMomentumStrategy(BaseStrategy):
    """Simple moving-average momentum strategy.

    Generates BUY when price crosses above the moving average,
    SELL when it crosses below, and HOLD otherwise.
    """

    ma_period: int = 20
    symbol: Optional[str] = None

    def __post_init__(self) -> None:
        self.min_history_bars = max(self.ma_period + 2, 2)

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
        df["ma"] = df["close"].rolling(window=self.ma_period, min_periods=self.ma_period).mean()

        df["signal"] = 0
        df.loc[df["close"] > df["ma"], "signal"] = 1
        df.loc[df["close"] < df["ma"], "signal"] = -1
        df.loc[df["ma"].isna(), "signal"] = 0

        df["signal_change"] = df["signal"].diff().fillna(0)
        df.loc[df["signal_change"] == 0, "signal"] = 0
        df.drop(columns=["signal_change"], inplace=True)

        return df


@dataclass
class DualSMAMomentumStrategy(BaseStrategy):
    """Dual moving-average crossover strategy."""

    fast_period: int = 12
    slow_period: int = 26
    symbol: Optional[str] = None

    def __post_init__(self) -> None:
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be < slow_period")
        self.min_history_bars = self.slow_period + 2

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
        df["fast_ma"] = df["close"].rolling(window=self.fast_period, min_periods=self.fast_period).mean()
        df["slow_ma"] = df["close"].rolling(window=self.slow_period, min_periods=self.slow_period).mean()

        df["signal"] = 0
        df.loc[df["fast_ma"] > df["slow_ma"], "signal"] = 1
        df.loc[df["fast_ma"] < df["slow_ma"], "signal"] = -1
        df.loc[df["slow_ma"].isna(), "signal"] = 0

        df["signal_change"] = df["signal"].diff().fillna(0)
        df.loc[df["signal_change"] == 0, "signal"] = 0
        df.drop(columns=["signal_change"], inplace=True)
        return df


@dataclass
class RSIMomentumStrategy(BaseStrategy):
    """Momentum strategy using RSI thresholds."""

    period: int = 14
    lower_threshold: float = 30.0
    upper_threshold: float = 70.0

    def __post_init__(self) -> None:
        if self.lower_threshold >= self.upper_threshold:
            raise ValueError("lower_threshold must be < upper_threshold")
        self.min_history_bars = self.period + 2

    @staticmethod
    def _ensure_close(df: pd.DataFrame) -> pd.DataFrame:
        if "close" in df.columns:
            return df
        if "price" in df.columns:
            clone = df.copy()
            clone["close"] = clone["price"]
            return clone
        raise ValueError("DataFrame must include 'close' column for RSI strategy")

    def generate_signals(self, historical_data: pd.DataFrame) -> pd.DataFrame:
        df = self._ensure_close(historical_data.copy())
        delta = df["close"].diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / self.period, adjust=False).mean()
        loss = -delta.clip(upper=0).ewm(alpha=1 / self.period, adjust=False).mean()
        rs = gain / loss.replace(0, pd.NA)
        df["rsi"] = 100 - (100 / (1 + rs))
        df["rsi"] = df["rsi"].fillna(50.0)
        df["signal"] = 0
        rsi_shift = df["rsi"].shift(1)
        df.loc[
            (rsi_shift <= self.lower_threshold) & (df["rsi"] > self.lower_threshold),
            "signal",
        ] = 1
        df.loc[
            (rsi_shift >= self.upper_threshold) & (df["rsi"] < self.upper_threshold),
            "signal",
        ] = -1
        return df


@dataclass
class MACDCrossoverStrategy(BaseStrategy):
    """Classic MACD signal-line crossover strategy."""

    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9

    def __post_init__(self) -> None:
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be < slow_period")
        self.min_history_bars = self.slow_period + self.signal_period

    @staticmethod
    def _ensure_close(df: pd.DataFrame) -> pd.DataFrame:
        if "close" in df.columns:
            return df
        if "price" in df.columns:
            clone = df.copy()
            clone["close"] = clone["price"]
            return clone
        raise ValueError("DataFrame must include 'close' column for MACD strategy")

    def generate_signals(self, historical_data: pd.DataFrame) -> pd.DataFrame:
        df = self._ensure_close(historical_data.copy())
        df["ema_fast"] = df["close"].ewm(span=self.fast_period, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow_period, adjust=False).mean()
        df["macd"] = df["ema_fast"] - df["ema_slow"]
        df["macd_signal"] = df["macd"].ewm(span=self.signal_period, adjust=False).mean()

        df["signal"] = 0
        macd_shift = df["macd"].shift(1)
        signal_shift = df["macd_signal"].shift(1)
        df.loc[(macd_shift <= signal_shift) & (df["macd"] > df["macd_signal"]), "signal"] = 1
        df.loc[(macd_shift >= signal_shift) & (df["macd"] < df["macd_signal"]), "signal"] = -1
        return df


__all__ = [
    "SMAMomentumStrategy",
    "DualSMAMomentumStrategy",
    "RSIMomentumStrategy",
    "MACDCrossoverStrategy",
]


