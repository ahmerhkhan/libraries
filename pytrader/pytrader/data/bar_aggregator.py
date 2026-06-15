"""
Bar Aggregator - Aggregates WebSocket ticks into OHLCV bars.

Converts real-time tick data from psx-terminal WebSocket into time-based candlestick bars
for strategy execution. Maintains bar history for technical indicator calculations.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class TickData:
    """Single tick/trade from WebSocket."""
    symbol: str
    price: float
    volume: int
    timestamp: datetime
    high: Optional[float] = None
    low: Optional[float] = None
    open_price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass
class AggregatedBar:
    """Aggregated OHLCV bar from ticks."""
    symbol: str
    timestamp: datetime  # Bar close timestamp
    open: float
    high: float
    low: float
    close: float
    volume: int
    trades: int = 0


class BarAggregator:
    """
    Aggregates WebSocket ticks into time-based OHLCV bars.
    
    Features:
    - Configurable bar interval (1m, 5m, 15m, 1h, etc.)
    - Maintains bar history for indicator calculations
    - Aligns bars to cycle boundaries (e.g., :00, :15, :30, :45 for 15-min)
    - Emits bar close events for strategy execution
    """
    
    def __init__(self, interval_minutes: int = 15, max_history: int = 500):
        """
        Initialize bar aggregator.
        
        Args:
            interval_minutes: Bar interval in minutes (default: 15)
            max_history: Maximum number of bars to keep in history (default: 500)
        """
        self.interval_minutes = interval_minutes
        self.max_history = max_history
        
        # Per-symbol state
        self._current_bars: Dict[str, Dict] = {}  # symbol -> {open, high, low, close, volume, trades, ts}
        self._bar_history: Dict[str, Deque[AggregatedBar]] = {}  # symbol -> deque of bars
        self._last_bar_close: Dict[str, datetime] = {}  # symbol -> last bar close time
        
        logger.info(f"BarAggregator initialized: interval={interval_minutes}m, max_history={max_history}")
    
    def add_tick(self, tick: TickData) -> Optional[AggregatedBar]:
        """
        Add a tick and return completed bar if bar closed.
        
        Args:
            tick: Tick data from WebSocket
            
        Returns:
            Completed bar if bar period closed, else None
        """
        symbol = tick.symbol
        
        # Calculate bar timestamp (aligned to interval)
        bar_ts = self._align_to_interval(tick.timestamp)
        
        # Initialize history for this symbol if needed
        if symbol not in self._bar_history:
            self._bar_history[symbol] = deque(maxlen=self.max_history)
            self._last_bar_close[symbol] = bar_ts
        
        # Check if we need to close the current bar
        completed_bar = None
        if symbol in self._current_bars:
            current_bar_ts = self._current_bars[symbol]['ts']
            if bar_ts > current_bar_ts:
                # Bar period changed - close current bar
                completed_bar = self._close_bar(symbol)
                self._reset_bar(symbol, tick, bar_ts)
            else:
                # Update current bar
                self._update_bar(symbol, tick)
        else:
            # First tick for this symbol
            self._reset_bar(symbol, tick, bar_ts)
        
        return completed_bar
    
    def _align_to_interval(self, ts: datetime) -> datetime:
        """Align timestamp to bar interval boundary."""
        # Round down to nearest interval
        minutes = (ts.minute // self.interval_minutes) * self.interval_minutes
        aligned = ts.replace(minute=minutes, second=0, microsecond=0)
        return aligned
    
    def _reset_bar(self, symbol: str, tick: TickData, bar_ts: datetime) -> None:
        """Start a new bar with the first tick."""
        self._current_bars[symbol] = {
            'ts': bar_ts,
            'open': tick.price,
            'high': tick.price,
            'low': tick.price,
            'close': tick.price,
            'volume': tick.volume,
            'trades': 1,
        }
    
    def _update_bar(self, symbol: str, tick: TickData) -> None:
        """Update current bar with new tick."""
        bar = self._current_bars[symbol]
        bar['high'] = max(bar['high'], tick.price)
        bar['low'] = min(bar['low'], tick.price)
        bar['close'] = tick.price
        bar['volume'] += tick.volume
        bar['trades'] += 1
    
    def _close_bar(self, symbol: str) -> AggregatedBar:
        """Close current bar and add to history."""
        bar_data = self._current_bars[symbol]
        completed_bar = AggregatedBar(
            symbol=symbol,
            timestamp=bar_data['ts'],
            open=bar_data['open'],
            high=bar_data['high'],
            low=bar_data['low'],
            close=bar_data['close'],
            volume=bar_data['volume'],
            trades=bar_data['trades'],
        )
        
        # Add to history
        self._bar_history[symbol].append(completed_bar)
        self._last_bar_close[symbol] = bar_data['ts']
        
        logger.debug(f"Bar closed: {symbol} @ {completed_bar.timestamp} | "
                    f"O:{completed_bar.open:.2f} H:{completed_bar.high:.2f} "
                    f"L:{completed_bar.low:.2f} C:{completed_bar.close:.2f} V:{completed_bar.volume}")
        
        return completed_bar
    
    def get_history(self, symbol: str, bars: Optional[int] = None) -> pd.DataFrame:
        """
        Get bar history as DataFrame for strategy indicators.
        
        Args:
            symbol: Symbol to get history for
            bars: Number of bars to return (default: all available)
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        if symbol not in self._bar_history or not self._bar_history[symbol]:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        history = list(self._bar_history[symbol])
        if bars:
            history = history[-bars:]
        
        df = pd.DataFrame([
            {
                'timestamp': bar.timestamp,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume,
            }
            for bar in history
        ])
        
        return df
    
    def get_current_bar(self, symbol: str) -> Optional[Dict]:
        """Get current (incomplete) bar for a symbol."""
        return self._current_bars.get(symbol)
    
    def seed_history(self, symbol: str, bars: List[AggregatedBar]) -> None:
        """
        Seed bar history with historical bars (e.g., from pypsx library).
        
        This allows strategies to have historical data for indicator calculations
        without waiting for bars to accumulate from WebSocket ticks.
        
        Args:
            symbol: Symbol to seed bars for
            bars: List of AggregatedBar objects to add to history
        """
        symbol = symbol.upper()
        if not bars:
            return
        
        # Initialize history if needed
        if symbol not in self._bar_history:
            self._bar_history[symbol] = deque(maxlen=self.max_history)
        
        # Add bars to history (oldest first, maintain chronological order)
        for bar in bars:
            self._bar_history[symbol].append(bar)
        
        # Update last bar close time
        if bars:
            self._last_bar_close[symbol] = bars[-1].timestamp
        
        logger.info(f"Seeded {len(bars)} historical bars for {symbol}")
    
    def force_close_all_bars(self) -> List[AggregatedBar]:
        """Force close all current bars (e.g., at market close)."""
        closed_bars = []
        for symbol in list(self._current_bars.keys()):
            bar = self._close_bar(symbol)
            closed_bars.append(bar)
        self._current_bars.clear()
        return closed_bars


__all__ = ["BarAggregator", "TickData", "AggregatedBar"]
