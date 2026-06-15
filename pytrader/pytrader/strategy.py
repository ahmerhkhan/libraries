"""
Public Strategy interface for PyTrader SDK.

Users can subclass this Strategy class to create custom trading strategies
without needing to access internal codebase. Supports both simple and advanced
strategies similar to Alpaca SDK patterns.
"""

from __future__ import annotations

from abc import ABC
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd


class Strategy(ABC):
    """
    Base class for user-defined trading strategies.
    
    This interface supports both simple and complex strategies:
    
    **Simple Example:**
        class MyStrategy(Strategy):
            def on_data(self, data):
                df = data['OGDC']
                if df['close'].iloc[-1] > df['close'].iloc[-20]:
                    self.buy('OGDC', 100)
    
    **Advanced Example (Alpaca-style):**
        class AdvancedStrategy(Strategy):
            def on_start(self):
                self.weights = {'SMA_cross': 1.0, 'RSI_bull': 0.8}
                self.stop_loss_pct = 4.0
                self.profit_target_pct = 20.0
            
            def on_data(self, data):
                portfolio = self.portfolio
                positions = self.positions
                
                # Check stop loss / profit targets for existing positions
                for symbol, pos in positions.items():
                    buy_price = pos['avg_cost']
                    current_price = self.current_prices.get(symbol, 0)
                    pct_change = ((current_price - buy_price) / buy_price) * 100
                    
                    if pct_change <= -self.stop_loss_pct:
                        self.sell(symbol, pos['qty'])
                    elif pct_change >= self.profit_target_pct:
                        self.sell(symbol, pos['qty'])
                
                # Scan and evaluate new opportunities
                for symbol, df in data.items():
                    if symbol in positions:
                        continue  # Already have position
                    
                    score = self._calculate_score(df)
                    if score > 0.65 and portfolio['cash'] > 10000:
                        qty = int(portfolio['cash'] * 0.1 / df['close'].iloc[-1])
                        self.buy(symbol, qty)
    """
    
    def __init__(self, symbols: Optional[List[str]] = None, config: Optional[Dict[str, Any]] = None):
        """
        Initialize strategy.
        
        Args:
            symbols: List of symbols this strategy will trade
            config: Optional configuration dictionary
        """
        self.symbols = symbols or []
        self.config = config or {}
        self._orders: List[Dict[str, Any]] = []
        self._context: Optional[Dict[str, Any]] = None
        self._position_metadata: Dict[str, Dict[str, Any]] = {}  # Track buy dates, etc.
        self._engine: Optional[Any] = None  # Reference to TradingEngine (set by adapter)
    
    def on_start(self) -> None:
        """
        Called once before trading begins.
        
        Use this to initialize indicators, set parameters, load weights, etc.
        """
        pass
    
    def on_data(self, data: Dict[str, pd.DataFrame]) -> None:
        """
        Called every cycle with fresh OHLCV data for each symbol.
        
        Args:
            data: Dictionary mapping symbol to DataFrame with columns:
                  ['ts', 'price', 'volume'] or ['ts', 'open', 'high', 'low', 'close', 'volume']
        
        The following properties are available during on_data:
        - self.portfolio: Dict with 'cash', 'equity', 'unrealized_pnl', 'realized_pnl'
        - self.positions: Dict mapping symbol to position info {'qty', 'avg_cost', 'market_value'}
        - self.current_prices: Dict mapping symbol to current price
        - self.trades: List of recent trades (last 100)
        - self.position_metadata: Dict for custom position tracking (buy_date, hold_days, etc.)
        
        Example:
            def on_data(self, data):
                # Access portfolio state
                cash = self.portfolio['cash']
                equity = self.portfolio['equity']
                
                # Access positions
                for symbol, pos in self.positions.items():
                    qty = pos['qty']
                    avg_cost = pos['avg_cost']
                    current_price = self.current_prices[symbol]
                    
                    # Calculate P&L
                    pnl_pct = ((current_price - avg_cost) / avg_cost) * 100
                    
                    # Check hold days
                    buy_date = self.position_metadata.get(symbol, {}).get('buy_date')
                    if buy_date:
                        hold_days = (datetime.now() - buy_date).days
                        if hold_days >= 7:  # Hold for max 7 days
                            self.sell(symbol, qty)
                
                # Evaluate new opportunities
                for symbol, df in data.items():
                    if symbol not in self.positions:
                        score = self._evaluate_symbol(df)
                        if score > 0.7:
                            self.buy(symbol, 100)
        """
        pass
    
    def on_end(self) -> None:
        """
        Called once after trading ends.
        
        Use this for cleanup or final calculations.
        """
        pass
    
    def buy(self, symbol: str, quantity: int) -> None:
        """
        Place a buy order for the given symbol and quantity.
        
        Args:
            symbol: Stock symbol (e.g., 'OGDC', 'HBL')
            quantity: Number of shares to buy
        """
        self._orders.append({
            'symbol': symbol.upper(),
            'side': 'BUY',
            'quantity': quantity,
        })
    
    def sell(self, symbol: str, quantity: int) -> None:
        """
        Place a sell order for the given symbol and quantity.
        
        Args:
            symbol: Stock symbol (e.g., 'OGDC', 'HBL')
            quantity: Number of shares to sell
        """
        self._orders.append({
            'symbol': symbol.upper(),
            'side': 'SELL',
            'quantity': quantity,
        })
    
    def get_orders(self) -> List[Dict[str, Any]]:
        """
        Get pending orders for this cycle.
        
        Returns:
            List of order dictionaries with 'symbol', 'side', 'quantity'
        """
        return self._orders.copy()
    
    def clear_orders(self) -> None:
        """Clear pending orders (called automatically after each cycle)."""
        self._orders.clear()
    
    def set_context(self, context: Dict[str, Any]) -> None:
        """Set context data (called by engine)."""
        self._context = context
        
        # Update position metadata when positions change
        if 'positions' in context:
            # Use positions property to normalize to dict regardless of source format
            positions_dict = self.positions

            # Track new positions
            for symbol, pos in positions_dict.items():
                if symbol not in self._position_metadata:
                    self._position_metadata[symbol] = {
                        'buy_date': datetime.now(),
                        'buy_price': pos.get('avg_cost', 0.0),
                    }

            # Remove closed positions
            current_symbols = set(positions_dict.keys())
            closed_symbols = set(self._position_metadata.keys()) - current_symbols
            for symbol in closed_symbols:
                del self._position_metadata[symbol]
    
    def get_context(self) -> Optional[Dict[str, Any]]:
        """Get current context data."""
        return self._context
    
    @property
    def portfolio(self) -> Dict[str, Any]:
        """
        Access current portfolio state.
        
        Returns:
            Dict with keys:
            - 'cash': Available cash
            - 'equity': Total portfolio equity
            - 'unrealized_pnl': Unrealized profit/loss
            - 'realized_pnl': Realized profit/loss
            - 'last_updated': Last update timestamp
        """
        if not self._context:
            return {
                'cash': 0.0,
                'equity': 0.0,
                'unrealized_pnl': 0.0,
                'realized_pnl': 0.0,
                'last_updated': None,
            }
        summary = self._context.get('portfolio_summary', {})
        return {
            'cash': summary.get('cash', 0.0),
            'equity': summary.get('equity', 0.0),
            'unrealized_pnl': summary.get('unrealized_pnl', 0.0),
            'realized_pnl': summary.get('realized_pnl', 0.0),
            'last_updated': summary.get('last_updated'),
        }
    
    @property
    def positions(self) -> Dict[str, Dict[str, Any]]:
        """
        Access current positions.
        
        Returns:
            Dict mapping symbol to position dict with:
            - 'qty': Quantity held
            - 'avg_cost': Average cost basis
            - 'market_value': Current market value
            - 'current_price': Current price
        """
        if not self._context:
            return {}
        
        positions_data = self._context.get('positions', [])
        
        # Handle case where positions is already a dict (shouldn't happen, but be safe)
        if isinstance(positions_data, dict):
            return positions_data
        
        # Handle case where positions is a list (normal case)
        if not isinstance(positions_data, list):
            return {}
        
        if not positions_data:
            return {}
        
        # Convert list to dict
        result = {}
        for pos in positions_data:
            if isinstance(pos, dict):
                symbol = pos.get('symbol')
                if symbol:
                    result[symbol] = {
                        'qty': pos.get('qty', 0),
                        'avg_cost': pos.get('avg_cost', 0.0),
                        'market_value': pos.get('market_value', 0.0),
                        'current_price': pos.get('current_price', 0.0),
                    }
        return result
    
    @property
    def current_prices(self) -> Dict[str, float]:
        """
        Access current prices for all symbols.
        
        Returns:
            Dict mapping symbol to current price
        """
        if not self._context:
            return {}
        return self._context.get('current_prices', {})
    
    @property
    def trades(self) -> List[Dict[str, Any]]:
        """
        Access recent trade history.
        
        Returns:
            List of trade dicts with:
            - 'ts': Timestamp
            - 'symbol': Symbol
            - 'side': 'BUY' or 'SELL'
            - 'quantity': Quantity
            - 'price': Execution price
            - 'pnl_realized': Realized P&L (for sells)
            - 'fees': Fees paid
        """
        if not self._context:
            return []
        return self._context.get('trades', [])
    
    @property
    def position_metadata(self) -> Dict[str, Dict[str, Any]]:
        """
        Access custom position metadata (buy dates, hold days, etc.).
        
        This is automatically maintained by the strategy. You can also
        manually update it for custom tracking.
        
        Returns:
            Dict mapping symbol to metadata dict
        """
        return self._position_metadata
    
    def get_position_hold_days(self, symbol: str) -> Optional[int]:
        """
        Get number of days a position has been held.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Number of days held, or None if position doesn't exist
        """
        if symbol not in self._position_metadata:
            return None
        buy_date = self._position_metadata[symbol].get('buy_date')
        if not buy_date:
            return None
        if isinstance(buy_date, str):
            buy_date = datetime.fromisoformat(buy_date)
        return (datetime.now() - buy_date).days
    
    def get_position_pnl_pct(self, symbol: str) -> Optional[float]:
        """
        Get unrealized P&L percentage for a position.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            P&L percentage, or None if position doesn't exist
        """
        if symbol not in self.positions:
            return None
        pos = self.positions[symbol]
        buy_price = pos['avg_cost']
        current_price = pos['current_price']
        if buy_price == 0:
            return None
        return ((current_price - buy_price) / buy_price) * 100
    
    def update_position_metadata(self, symbol: str, metadata: Dict[str, Any]) -> None:
        """
        Update custom metadata for a position.
        
        Args:
            symbol: Stock symbol
            metadata: Dict of metadata to update/merge
        """
        if symbol not in self._position_metadata:
            self._position_metadata[symbol] = {}
        self._position_metadata[symbol].update(metadata)
    
    def set_engine(self, engine: Any) -> None:
        """
        Set the TradingEngine reference (called by StrategyAdapter).
        
        This allows strategies to execute orders immediately via buy_now()/sell_now().
        
        Args:
            engine: TradingEngine instance
        """
        self._engine = engine
    
    def buy_now(self, symbol: str, quantity: int, price: Optional[float] = None) -> Dict[str, Any]:
        """
        Execute a buy order immediately (bypasses bar-close queue).
        
        ARCHITECTURE: This method executes orders immediately through the TradingEngine,
        ensuring consistent execution timing, price discovery, and portfolio accounting.
        
        This is the recommended method for:
        - Strategies that want immediate execution based on pre-analyzed data
        - Manual intervention scripts
        - Any scenario where waiting for bar-close is not desired
        
        Args:
            symbol: Stock symbol (e.g., 'OGDC', 'HBL')
            quantity: Number of shares to buy
            price: Optional execution price (if None, engine will discover from WebSocket/snapshot)
            
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
            
        Raises:
            RuntimeError: If engine is not set (strategy not running in engine context)
            
        Example:
            result = strategy.buy_now('OGDC', 100, price=150.0)
            if result['success']:
                print(f"Bought {result['quantity']} @ {result['execution_price']:.2f}")
        """
        if self._engine is None:
            raise RuntimeError(
                "buy_now() requires engine context. "
                "This method can only be called when the strategy is running in a TradingEngine. "
                "For standalone scripts, use client.place_manual_order() instead."
            )
        
        return self._engine.execute_immediate(
            symbol=symbol,
            side='BUY',
            quantity=quantity,
            price=price,
        )
    
    def sell_now(self, symbol: str, quantity: int, price: Optional[float] = None) -> Dict[str, Any]:
        """
        Execute a sell order immediately (bypasses bar-close queue).
        
        ARCHITECTURE: This method executes orders immediately through the TradingEngine,
        ensuring consistent execution timing, price discovery, and portfolio accounting.
        
        This is the recommended method for:
        - Stop-loss / take-profit execution
        - Strategies that want immediate execution based on pre-analyzed data
        - Manual intervention scripts
        - Any scenario where waiting for bar-close is not desired
        
        Args:
            symbol: Stock symbol (e.g., 'OGDC', 'HBL')
            quantity: Number of shares to sell
            price: Optional execution price (if None, engine will discover from WebSocket/snapshot)
            
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
            
        Raises:
            RuntimeError: If engine is not set (strategy not running in engine context)
            
        Example:
            result = strategy.sell_now('OGDC', 100, price=155.0)
            if result['success']:
                print(f"Sold {result['quantity']} @ {result['execution_price']:.2f}")
        """
        if self._engine is None:
            raise RuntimeError(
                "sell_now() requires engine context. "
                "This method can only be called when the strategy is running in a TradingEngine. "
                "For standalone scripts, use client.place_manual_order() instead."
            )
        
        return self._engine.execute_immediate(
            symbol=symbol,
            side='SELL',
            quantity=quantity,
            price=price,
        )


__all__ = ["Strategy"]
