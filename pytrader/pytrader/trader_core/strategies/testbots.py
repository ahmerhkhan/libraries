"""
Strategy implementations adapted from the legacy test bot scripts.
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from .base import BaseStrategy

try:
    from ta.trend import SMAIndicator, MACD
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.volatility import BollingerBands, AverageTrueRange
    from ta.volume import OnBalanceVolumeIndicator

    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False


class TestBotsMomentumStrategy(BaseStrategy):
    """
    Weighted momentum score inspired by `momentum.txt` / `buying on up.txt`.
    """

    def __init__(
        self,
        symbol: Optional[str] = None,
        min_score_norm: float = 0.45,
        max_hold_days: int = 5,
    ) -> None:
        if not TA_AVAILABLE:
            raise ImportError("ta library is required. Install via: pip install ta")

        self.symbol = symbol
        self.min_score_norm = float(min_score_norm)
        self.max_hold_days = int(max_hold_days)
        self.min_history_bars = 60

        self.weights: Dict[str, float] = {
            "C_SMA3_gt_SMA20": 1.0,
            "C_SMA20_gt_SMA50": 0.9,
            "C_Ret5d_positive": 0.7,
            "C_5d_Positive_Momentum": 0.8,
            "MACD_Bullish": 0.8,
            "StochRSI_Bull": 0.6,
            "C_Volume_gt_250k": 0.5,
            "C_Positive_Volume_Spike": 0.7,
            "OBV_Positive": 0.5,
            "C_ATR_not_too_high": 0.4,
            "C_Price_in_range": 0.4,
            "BB_Breakout": 0.1,
            "Gap_Up": 0.4,
            "C_RSI_Bullish": 0.8,
        }
        self.EARLY_EXIT_PCT = 7.0
        self.STOP_LOSS = 4.0

    @staticmethod
    def _dynamic_hold_days(
        rsi: float,
        atr_pct: float,
        sma_short: float,
        sma_long: float,
        max_hold_days: int,
    ) -> int:
        hold = 2
        if 45 <= rsi <= 55 and atr_pct < 4.0:
            hold = 5 if sma_short > sma_long else 3
        if sma_short > sma_long and rsi >= 48 and atr_pct < 3.0:
            hold = 6
        return min(max_hold_days, hold)

    def generate_signals(self, historical_data: pd.DataFrame) -> pd.DataFrame:
        df = historical_data.copy()

        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"DataFrame must include '{col}' column")

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        volume = df["volume"].astype(float)
        open_price = df["open"].astype(float)

        sma3 = SMAIndicator(close=close, window=3).sma_indicator()
        sma20 = SMAIndicator(close=close, window=20).sma_indicator()
        sma50 = SMAIndicator(close=close, window=50).sma_indicator()

        rsi = RSIIndicator(close=close, window=14).rsi()
        stoch = StochasticOscillator(high=high, low=low, close=close, window=14)
        stoch_rsi = stoch.stoch()

        macd = MACD(close=close)
        macd_line = macd.macd()
        macd_signal = macd.macd_signal()
        macd_hist = macd.macd_diff()

        bb = BollingerBands(close=close, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband()

        atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
        atr_pct = (atr / close) * 100.0

        obv = OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()

        ret5d = close.pct_change(5) * 100.0
        ret3d = close.pct_change(3) * 100.0

        vol_avg_5d = volume.rolling(5).mean()
        vol_avg_20d = volume.rolling(20).mean()

        cond = pd.DataFrame(index=df.index)
        cond["C_SMA3_gt_SMA20"] = (sma3 > sma20).astype(int)
        cond["C_SMA20_gt_SMA50"] = (sma20 > sma50).astype(int)
        cond["C_Ret5d_positive"] = (ret5d > 1.0).astype(int)
        cond["C_5d_Positive_Momentum"] = (ret5d > 2.0).astype(int)
        cond["MACD_Bullish"] = (macd_line > macd_signal).astype(int)
        cond["StochRSI_Bull"] = (stoch_rsi > 80).astype(int)
        cond["C_Volume_gt_250k"] = (vol_avg_20d > 250000).astype(int)
        cond["C_Positive_Volume_Spike"] = (volume > (vol_avg_5d * 1.5)).astype(int)
        cond["OBV_Positive"] = (obv > obv.shift(5)).astype(int)
        cond["C_ATR_not_too_high"] = ((atr / close) < 0.04).astype(int)

        price_ma50 = close.rolling(50).mean()
        price_dev = ((close - price_ma50) / price_ma50) * 100.0
        cond["C_Price_in_range"] = ((price_dev > -20.0) & (price_dev < 30.0)).astype(int)
        cond["BB_Breakout"] = (close > bb_upper).astype(int)
        gap_up = ((open_price - close.shift(1)) / close.shift(1))
        cond["Gap_Up"] = (gap_up > 0.02).astype(int)
        cond["C_RSI_Bullish"] = ((rsi > 55) & (rsi < 70)).astype(int)

        total_weight = sum(self.weights.values())
        score = pd.Series(0.0, index=df.index)
        for key, weight in self.weights.items():
            if key in cond:
                score += cond[key] * float(weight)
        score_norm = (score / total_weight).clip(0.0, 1.0)

        threshold = pd.Series(self.min_score_norm, index=df.index)

        signals = pd.Series(0, index=df.index, dtype=int)
        in_position = False
        entry_idx = None
        entry_price = None
        hold_days = 2

        for i in range(len(df)):
            if not in_position:
                if score_norm.iat[i] >= threshold.iat[i]:
                    signals.iat[i] = 1
                    in_position = True
                    entry_idx = i
                    entry_price = close.iat[i]
                    hold_days = self._dynamic_hold_days(
                        float(rsi.iat[i]) if pd.notna(rsi.iat[i]) else 50.0,
                        float(atr_pct.iat[i]) if pd.notna(atr_pct.iat[i]) else 0.0,
                        float(sma3.iat[i]) if pd.notna(sma3.iat[i]) else 0.0,
                        float(sma20.iat[i]) if pd.notna(sma20.iat[i]) else 0.0,
                        self.max_hold_days,
                    )
                continue

            days_held = i - entry_idx if entry_idx is not None else 0
            price = close.iat[i]
            if entry_price is None or price <= 0:
                continue
            gain_pct = (price - entry_price) / entry_price * 100.0

            if days_held < hold_days:
                if gain_pct >= self.EARLY_EXIT_PCT or gain_pct <= -self.EARLY_EXIT_PCT:
                    signals.iat[i] = -1
            else:
                hybrid_target = max(0.35, entry_price * 0.025)
                if price >= entry_price + hybrid_target:
                    signals.iat[i] = -1
                elif gain_pct <= -self.STOP_LOSS:
                    signals.iat[i] = -1
                elif score_norm.iat[i] < threshold.iat[i]:
                    signals.iat[i] = -1
                elif pd.notna(rsi.iat[i]) and rsi.iat[i] < 50:
                    signals.iat[i] = -1
                elif macd_hist.iat[i] < 0:
                    signals.iat[i] = -1
                elif close.iat[i] < sma20.iat[i]:
                    signals.iat[i] = -1

            if signals.iat[i] == -1:
                in_position = False
                entry_idx = None
                entry_price = None

        df["signal"] = signals
        df["score"] = score
        df["score_norm"] = score_norm
        df["gain_pct"] = close.pct_change() * 100.0
        return df


class BuyingOnUpStrategy(TestBotsMomentumStrategy):
    """Higher baseline score and longer hold similar to `buying on up.txt`."""

    def __init__(self, symbol: Optional[str] = None) -> None:
        super().__init__(symbol=symbol, min_score_norm=0.55, max_hold_days=7)


class BuyingOnDownStrategy(TestBotsMomentumStrategy):
    """Contrarian dip-buying variant from `buying on down.txt`."""

    def __init__(self, symbol: Optional[str] = None) -> None:
        super().__init__(symbol=symbol, min_score_norm=0.35, max_hold_days=4)
        self.weights.update(
            {
                "Gap_Up": 0.2,  # penalize gaps
                "C_Ret5d_positive": 0.4,  # allow mild negative momentum
                "C_Price_in_range": 0.6,
            }
        )
        self.EARLY_EXIT_PCT = 5.0
        self.STOP_LOSS = 5.5


class MLLayerMomentumStrategy(TestBotsMomentumStrategy):
    """
    Lightweight ML-inspired wrapper that nudges weights based on recent returns.
    """

    def __init__(self, symbol: Optional[str] = None, learning_rate: float = 0.1) -> None:
        super().__init__(symbol=symbol, min_score_norm=0.5, max_hold_days=6)
        self.learning_rate = learning_rate

    def adapt_weights(self, returns: pd.Series) -> None:
        if returns.empty:
            return
        recent = returns.tail(5).dropna()
        if recent.empty:
            return
        avg_return = recent.mean()
        adjustment = 1 + (self.learning_rate * avg_return)
        for key in self.weights:
            self.weights[key] = max(0.1, self.weights[key] * adjustment)


