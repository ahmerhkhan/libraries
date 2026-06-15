"""
Adapter to bridge user-friendly Strategy class to internal BaseStrategy.

This allows users to write strategies using the simple Strategy interface
while the engine uses the internal BaseStrategy interface. Supports both
simple per-symbol strategies and advanced multi-symbol portfolio strategies.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

# Import trader_core BaseStrategy - try relative import first (package install), then fallback
try:
    from .trader_core.strategies.base import BaseStrategy
except ImportError:
    # Fallback: try absolute import (for development/legacy)
    try:
        from trader_core.strategies.base import BaseStrategy
    except ImportError:
        # Last resort: try adding parent to path
        import sys
        import os
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from trader_core.strategies.base import BaseStrategy

from .strategy import Strategy


class StrategyAdapter(BaseStrategy):
    """
    Adapter that wraps a user-friendly Strategy instance and converts it
    to work with the internal BaseStrategy interface.
    
    The adapter handles:
    - Context building (portfolio, positions, trades, prices)
    - Multi-symbol data aggregation
    - Order collection and signal generation
    """
    
    def __init__(self, user_strategy: Strategy, portfolio_service: Optional[Any] = None):
        """
        Initialize adapter with user strategy.
        
        Args:
            user_strategy: Instance of Strategy subclass
            portfolio_service: Optional PortfolioService instance for context building
        """
        self.user_strategy = user_strategy
        self.portfolio_service = portfolio_service
        self.min_history_bars = getattr(user_strategy, 'min_history_bars', 0)
        self._current_symbol: Optional[str] = None
        self._current_data: Optional[pd.DataFrame] = None
        self._all_symbols_data: Dict[str, pd.DataFrame] = {}
        self._current_prices: Dict[str, float] = {}
        self._context_built: bool = False
        self._expected_symbols: List[str] = []
        self._signals_cache: Dict[str, str] = {}  # Cache signals per symbol
        self._cycle_processed: bool = False
        self._last_cycle_symbols: set = set()  # Track symbols from last cycle
    
    def set_portfolio_service(self, portfolio_service: Any) -> None:
        """Set portfolio service for context building."""
        self.portfolio_service = portfolio_service
    
    def set_engine(self, engine: Any) -> None:
        """Set TradingEngine reference for immediate execution."""
        self.user_strategy.set_engine(engine)
    
    def build_context(self, prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """
        Build full context for user strategy.
        
        Args:
            prices: Current prices dict (symbol -> price)
            
        Returns:
            Context dict with portfolio, positions, trades, prices
        """
        context: Dict[str, Any] = {
            'current_prices': prices or self._current_prices,
            'positions': [],
            'portfolio_summary': {},
            'trades': [],
        }
        
        if self.portfolio_service:
            try:
                # Get portfolio summary
                summary = self.portfolio_service.get_summary()
                context['portfolio_summary'] = {
                    'cash': float(summary.cash),
                    'equity': float(summary.equity),
                    'unrealized_pnl': float(summary.unrealized_pnl),
                    'realized_pnl': float(summary.realized_pnl),
                    'last_updated': summary.last_updated.isoformat() if summary.last_updated else None,
                }
                
                # Build positions list with current prices
                current_prices = prices or self._current_prices
                positions_list = []
                # Handle both dict and list formats
                positions_data = summary.positions
                if isinstance(positions_data, list):
                    for pos in positions_data:
                        # Handle both dict and object formats
                        if isinstance(pos, dict):
                            symbol = pos.get('symbol')
                            qty = pos.get('qty', 0)
                            avg_cost = pos.get('avg_cost', 0.0)
                        else:
                            symbol = getattr(pos, 'symbol', None)
                            qty = getattr(pos, 'qty', 0)
                            avg_cost = getattr(pos, 'avg_cost', 0.0)
                        
                        if symbol:
                            current_price = current_prices.get(symbol, avg_cost)
                            positions_list.append({
                                'symbol': symbol,
                                'qty': qty,
                                'avg_cost': avg_cost,
                                'market_value': current_price * qty,
                                'current_price': current_price,
                            })
                context['positions'] = positions_list
                
                # Get recent trades
                trades = self.portfolio_service.get_trades(limit=100)
                context['trades'] = trades
                
            except Exception as e:
                # If portfolio service fails, use empty context
                from .trader_core.utils import log_line
                log_line(f"[StrategyAdapter] Warning: Could not build context: {e}")
        
        return context
    
    def generate_signal(self, symbol: str, historical_data: pd.DataFrame) -> str:
        """
        Generate trading signal by calling user strategy's on_data method.
        
        This method is called per-symbol by the engine. For advanced strategies
        that need multi-symbol context, we collect data and build context,
        then call on_data once per cycle with all symbols.
        
        Args:
            symbol: Current symbol being processed
            historical_data: Historical OHLCV data
            
        Returns:
            'BUY', 'SELL', or 'HOLD'
        """
        self._current_symbol = symbol
        self._current_data = historical_data
        
        # Store data for this symbol
        df = historical_data.copy()
        
        # Normalize column names: ensure 'close' exists
        if 'close' not in df.columns and 'price' in df.columns:
            df['close'] = df['price']
        elif 'close' not in df.columns and 'CLOSE' in df.columns:
            df['close'] = df['CLOSE']
        
        # Ensure 'volume' exists
        if 'volume' not in df.columns:
            if 'VOLUME' in df.columns:
                df['volume'] = df['VOLUME']
            else:
                df['volume'] = 0
        
        # Store current price
        if not df.empty and 'close' in df.columns:
            self._current_prices[symbol.upper()] = float(df['close'].iloc[-1])
        
        # Store symbol data (normalize symbol to uppercase)
        symbol_upper = symbol.upper()

        # If we already processed the previous cycle and we're seeing the first expected
        # symbol again, reset buffers for the new cycle
        if self._cycle_processed:
            first_expected = self._expected_symbols[0] if self._expected_symbols else None
            if first_expected is None or symbol_upper == first_expected:
                self._all_symbols_data = {}
                self._current_prices = {}
                self._signals_cache = {}
                self._cycle_processed = False
                self._last_cycle_symbols = set()
        
        # Detect new cycle: if this symbol wasn't in the last cycle, we're starting a new cycle
        if symbol_upper not in self._last_cycle_symbols and self._last_cycle_symbols:
            # New cycle detected - clear previous cycle data
            self._all_symbols_data = {}
            self._current_prices = {}
            self._signals_cache = {}
            self._expected_symbols = []
            self._cycle_processed = False
        
        self._all_symbols_data[symbol_upper] = df
        
        # Detect when we've collected all symbols for this cycle
        # Get expected symbols from strategy or from what we've seen
        if not self._expected_symbols:
            # First call in cycle - initialize expected symbols
            if hasattr(self.user_strategy, 'symbols') and self.user_strategy.symbols:
                self._expected_symbols = [s.upper() for s in self.user_strategy.symbols]
            else:
                # Fallback: we'll process when we've seen at least one symbol
                # This handles the case where symbols aren't known upfront
                pass
        
        # Check if we've collected all expected symbols
        collected_symbols = set(self._all_symbols_data.keys())
        
        # Process cycle if we have all expected symbols
        should_process = False
        if self._expected_symbols:
            expected_set = set(self._expected_symbols)
            should_process = collected_symbols >= expected_set
        else:
            # Fallback: if we don't know expected symbols, we can't reliably detect when cycle is complete
            # So we'll process immediately with whatever we have (this handles single-symbol strategies)
            # For multi-symbol strategies, expected_symbols should always be set
            should_process = len(collected_symbols) > 0 and not self._cycle_processed
        
        # If we should process and haven't already processed this cycle
        if should_process and not self._cycle_processed:
            # Build full context with all symbols
            context = self.build_context()
            self.user_strategy.set_context(context)
            
            # Clear previous orders
            self.user_strategy.clear_orders()
            
            # Ensure all_symbols_data is a dict (it should be, but double-check)
            if not isinstance(self._all_symbols_data, dict):
                from .trader_core.utils import log_line
                log_line(f"[StrategyAdapter] ERROR: _all_symbols_data is not dict: {type(self._all_symbols_data)}")
                self._all_symbols_data = {}
                return "HOLD"
            
            # Call on_data ONCE with all symbols
            try:
                # Make a copy to ensure it's a dict
                data_dict = dict(self._all_symbols_data)
                assert isinstance(data_dict, dict), f"data_dict must be dict, got {type(data_dict)}"
                self.user_strategy.on_data(data_dict)
            except Exception as e:
                from .trader_core.utils import log_line
                log_line(f"[StrategyAdapter] Error in {self.user_strategy.__class__.__name__}.on_data: {e}")
                import traceback
                traceback.print_exc()
            
            # Cache signals for all symbols from orders
            orders = self.user_strategy.get_orders()
            self._signals_cache = {}
            for order in orders:
                order_symbol = order['symbol'].upper()
                self._signals_cache[order_symbol] = order['side']
            
            # Mark cycle as processed
            self._cycle_processed = True
            self._last_cycle_symbols = collected_symbols.copy()
        
        # Return cached signal for this symbol, or HOLD if not found
        signal = self._signals_cache.get(symbol_upper, "HOLD")
        return signal
    
    def generate_signals(self, historical_data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate signals DataFrame (required by BaseStrategy).
        
        This method can be used for multi-symbol strategies that need
        to process all symbols together.
        """
        # If we have multiple symbols collected, process them together
        if len(self._all_symbols_data) > 1:
            # Build full context
            context = self.build_context()
            self.user_strategy.set_context(context)
            
            # Clear all orders
            self.user_strategy.clear_orders()
            
            # Call on_data with all symbols (multi-symbol mode)
            try:
                self.user_strategy.on_data(self._all_symbols_data)
            except Exception as e:
                from .trader_core.utils import log_line
                log_line(f"[StrategyAdapter] Error in multi-symbol on_data: {e}")
                import traceback
                traceback.print_exc()
            
            # Reset collected data for next cycle
            self._all_symbols_data = {}
            self._current_prices = {}
        
        # Return DataFrame with signal column
        result = historical_data.copy()
        signal = self.generate_signal(self._current_symbol or "UNKNOWN", historical_data)
        
        if signal == "BUY":
            result["signal"] = 1
        elif signal == "SELL":
            result["signal"] = -1
        else:
            result["signal"] = 0
        
        return result
    
    def get_name(self) -> str:
        """Return strategy name."""
        return self.user_strategy.__class__.__name__


__all__ = ["StrategyAdapter"]
