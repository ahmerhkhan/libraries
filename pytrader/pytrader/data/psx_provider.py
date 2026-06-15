"""PSX Data Provider Implementation"""

from datetime import datetime, timezone
import random
from typing import Dict, Any, Optional, List

from .provider import BaseDataProvider

class PSXDataProvider(BaseDataProvider):
    """
    Pakistan Stock Exchange (PSX) data provider implementation.
    This is a mock implementation for paper trading.
    """
    
    def __init__(self):
        """Initialize the PSX data provider."""
        self.last_prices = {
            "OGDC": 95.50,  # Starting price for OGDC
        }
        
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get current quote for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Quote dictionary with bid, ask, last_price
        """
        # Simulate some price movement
        last_price = self.last_prices.get(symbol, 100.0)
        change = random.uniform(-0.5, 0.5)  # Random price movement
        new_price = max(1.0, last_price + change)
        self.last_prices[symbol] = new_price
        
        # Add some spread
        spread = new_price * 0.001  # 0.1% spread
        bid = new_price - spread/2
        ask = new_price + spread/2
        
        return {
            "symbol": symbol,
            "last_price": new_price,
            "bid": bid,
            "ask": ask,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    def get_history(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get historical data for a symbol."""
        # For paper trading example, return some mock historical data
        current_price = self.last_prices.get(symbol, 100.0)
        history = []
        
        # Generate 100 days of mock data
        for i in range(100):
            price = current_price * (1 + random.uniform(-0.02, 0.02))
            history.append({
                "date": datetime.now(timezone.utc).date(),
                "open": price,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": random.randint(100000, 1000000)
            })
            
        return history
        
    def get_bars(
        self,
        symbol: str,
        timeframe: str = "1min",
        limit: int = 100
    ) -> Optional[List[Dict[str, Any]]]:
        """Get historical bars for a symbol."""
        return None  # Not implemented for this example