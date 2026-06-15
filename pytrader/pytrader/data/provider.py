"""Abstract base class for data providers."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime


class BaseDataProvider(ABC):
    """
    Abstract base class for data providers.
    
    All data providers must implement this interface to ensure
    consistent data format across different sources (PyPSX, official PSX API, CSV, etc.).
    """
    
    @abstractmethod
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get current quote for a symbol.
        
        Args:
            symbol: Stock symbol (e.g., "OGDC", "PPL")
            
        Returns:
            Dictionary with standardized quote data:
            {
                "symbol": str,
                "last_price": float,
                "bid": float (optional),
                "ask": float (optional),
                "volume": int (optional),
                "datetime": str (ISO format)
            }
            
        Raises:
            SymbolNotFoundError: If symbol is not found
            DataProviderError: If there's an error fetching data
        """
        pass
    
    @abstractmethod
    def get_history(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Get historical OHLCV data for a symbol.
        
        Args:
            symbol: Stock symbol (e.g., "OGDC", "PPL")
            start: Start date (optional)
            end: End date (optional)
            
        Returns:
            List of dictionaries with standardized OHLCV data:
            [
                {
                    "symbol": str,
                    "datetime": str (ISO format),
                    "open": float,
                    "high": float,
                    "low": float,
                    "close": float,
                    "volume": int
                },
                ...
            ]
            
        Raises:
            SymbolNotFoundError: If symbol is not found
            DataProviderError: If there's an error fetching data
        """
        pass

