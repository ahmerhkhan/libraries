"""
CSV data provider for backtesting with flexible column mapping.

Supports various CSV formats including:
- OHLCV format (open, high, low, close, volume)
- Simple format (symbol, timestamp, price, volume)
- Custom column mappings
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from ..utils.exceptions import DataProviderError
from ..utils.logger import log_line


@dataclass
class CSVColumnMapping:
    """
    Column mapping configuration for CSV files.
    
    Maps user's CSV columns to standard OHLCV format.
    """
    # Required columns
    timestamp: str  # Column name for timestamp
    price: Optional[str] = None  # Column name for price (used when OHLCV not available)
    
    # OHLCV columns (optional - will use price if not provided)
    open: Optional[str] = None
    high: Optional[str] = None
    low: Optional[str] = None
    close: Optional[str] = None
    volume: Optional[str] = None
    
    # Optional columns
    symbol: Optional[str] = None  # Column name for symbol (if CSV contains multiple symbols)
    
    def __post_init__(self):
        """Validate that we have at least timestamp and one price column."""
        if not self.timestamp:
            raise ValueError("timestamp column is required")
        
        # If no OHLCV columns specified, we need a price column
        if not any([self.open, self.high, self.low, self.close, self.price]):
            raise ValueError("At least one price column (price, open, high, low, or close) is required")


class CSVDataProvider:
    """
    Data provider that reads historical data from CSV files.
    
    Supports flexible column mapping to handle various CSV formats.
    """
    
    def __init__(
        self,
        csv_path: Union[str, Path],
        column_mapping: Optional[CSVColumnMapping] = None,
        symbol: Optional[str] = None,
        delimiter: str = ",",
        encoding: str = "utf-8",
    ):
        """
        Initialize CSV data provider.
        
        Args:
            csv_path: Path to CSV file
            column_mapping: Column mapping configuration. If None, auto-detects common formats.
            symbol: Symbol to filter by (if CSV contains symbol column). 
                    If CSV has symbol column and this is None, will filter by symbol in get_historical().
            delimiter: CSV delimiter (default: comma)
            encoding: File encoding (default: utf-8)
        """
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise DataProviderError(f"CSV file not found: {csv_path}")
        
        self.delimiter = delimiter
        self.encoding = encoding
        self.symbol = symbol.upper() if symbol else None
        
        # Auto-detect column mapping if not provided
        if column_mapping is None:
            column_mapping = self._auto_detect_mapping()
        
        self.column_mapping = column_mapping
    
    def _auto_detect_mapping(self) -> CSVColumnMapping:
        """
        Auto-detect column mapping by reading CSV header.
        
        Tries to match common column name patterns.
        """
        try:
            # Read just the header
            with open(self.csv_path, "r", encoding=self.encoding, newline="") as f:
                reader = csv.reader(f, delimiter=self.delimiter)
                header = next(reader)
        except Exception as exc:
            raise DataProviderError(f"Failed to read CSV header: {exc}") from exc
        
        # Normalize header (lowercase, strip whitespace)
        header_lower = [col.lower().strip() for col in header]
        header_map = {col.lower().strip(): col for col in header}
        
        # Find timestamp column
        timestamp_col = None
        for pattern in ["timestamp", "ts", "date", "datetime", "time"]:
            for i, col in enumerate(header_lower):
                if pattern in col:
                    timestamp_col = header_map[header_lower[i]]
                    break
            if timestamp_col:
                break
        
        if not timestamp_col:
            raise DataProviderError(
                f"Could not auto-detect timestamp column. Found columns: {header}. "
                "Please specify column_mapping manually."
            )
        
        # Find price columns
        price_col = None
        open_col = None
        high_col = None
        low_col = None
        close_col = None
        volume_col = None
        symbol_col = None
        
        for col in header_lower:
            if col in ["price", "p", "last_price", "last"]:
                price_col = header_map[col]
            elif col in ["open", "o"]:
                open_col = header_map[col]
            elif col in ["high", "h"]:
                high_col = header_map[col]
            elif col in ["low", "l"]:
                low_col = header_map[col]
            elif col in ["close", "c", "closing_price"]:
                close_col = header_map[col]
            elif col in ["volume", "vol", "v", "qty", "quantity"]:
                volume_col = header_map[col]
            elif col in ["symbol", "sym", "ticker", "stock"]:
                symbol_col = header_map[col]
        
        # If no price column found but we have close, use close
        if not price_col and close_col:
            price_col = close_col
        
        # If still no price column, try to find any numeric column
        if not price_col:
            for col in header:
                if col.lower() not in [timestamp_col.lower(), "symbol", "sym", "ticker"]:
                    try:
                        # Try reading first row to see if it's numeric
                        with open(self.csv_path, "r", encoding=self.encoding, newline="") as f:
                            reader = csv.DictReader(f, delimiter=self.delimiter)
                            first_row = next(reader)
                            float(first_row[col])
                            price_col = col
                            break
                    except (ValueError, KeyError):
                        continue
        
        if not price_col and not any([open_col, high_col, low_col, close_col]):
            raise DataProviderError(
                f"Could not auto-detect price column. Found columns: {header}. "
                "Please specify column_mapping manually."
            )
        
        return CSVColumnMapping(
            timestamp=timestamp_col,
            price=price_col,
            open=open_col,
            high=high_col,
            low=low_col,
            close=close_col,
            volume=volume_col,
            symbol=symbol_col,
        )
    
    def get_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        interval: str = "1d",
    ) -> List[Dict[str, Any]]:
        """
        Get historical data from CSV file.
        
        Args:
            symbol: Symbol to filter by (if CSV contains symbol column)
            start: Start date filter (optional)
            end: End date filter (optional)
            interval: Data interval (not used for CSV, but kept for API compatibility)
        
        Returns:
            List of dictionaries with OHLCV data
        """
        try:
            df = pd.read_csv(
                self.csv_path,
                delimiter=self.delimiter,
                encoding=self.encoding,
                parse_dates=False,  # We'll parse dates manually
            )
        except Exception as exc:
            raise DataProviderError(f"Failed to read CSV file: {exc}") from exc
        
        if df.empty:
            raise DataProviderError(f"CSV file is empty: {self.csv_path}")
        
        # Filter by symbol if symbol column exists
        if self.column_mapping.symbol and self.column_mapping.symbol in df.columns:
            symbol_filter = df[self.column_mapping.symbol].str.upper().str.strip() == symbol.upper()
            df = df[symbol_filter].copy()
            if df.empty:
                raise DataProviderError(f"No data found for symbol {symbol} in CSV")
        elif self.symbol:
            # CSV was initialized with a specific symbol, but different symbol requested
            if symbol.upper() != self.symbol:
                raise DataProviderError(
                    f"CSV file is configured for symbol {self.symbol}, but {symbol} was requested. "
                    "Either provide a CSV with symbol column, or use separate CSV files per symbol."
                )
        
        # Parse timestamp
        if self.column_mapping.timestamp not in df.columns:
            raise DataProviderError(
                f"Timestamp column '{self.column_mapping.timestamp}' not found in CSV. "
                f"Available columns: {list(df.columns)}"
            )
        
        df["_parsed_ts"] = pd.to_datetime(df[self.column_mapping.timestamp], errors="coerce")
        df = df.dropna(subset=["_parsed_ts"])
        
        if df.empty:
            raise DataProviderError("No valid timestamps found in CSV after parsing")
        
        # Apply date filters
        if start:
            df = df[df["_parsed_ts"] >= pd.Timestamp(start)]
        if end:
            df = df[df["_parsed_ts"] <= pd.Timestamp(end)]
        
        if df.empty:
            raise DataProviderError(f"No data found in date range {start} to {end}")
        
        # Extract price data
        # Determine which price to use
        if self.column_mapping.close:
            close_col = self.column_mapping.close
        elif self.column_mapping.price:
            close_col = self.column_mapping.price
        else:
            # Fallback: use first available OHLC column
            for col in [self.column_mapping.open, self.column_mapping.high, self.column_mapping.low]:
                if col and col in df.columns:
                    close_col = col
                    break
            else:
                raise DataProviderError("No price column available")
        
        # Build OHLCV data
        result = []
        for _, row in df.iterrows():
            ts = row["_parsed_ts"]
            if pd.isna(ts):
                continue
            
            # Ensure timezone-aware
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            
            # Get close price
            try:
                close = float(row[close_col])
            except (ValueError, KeyError):
                continue
            
            # Get OHLC values
            open_price = close
            high_price = close
            low_price = close
            
            if self.column_mapping.open and self.column_mapping.open in df.columns:
                try:
                    open_price = float(row[self.column_mapping.open])
                except (ValueError, KeyError):
                    pass
            
            if self.column_mapping.high and self.column_mapping.high in df.columns:
                try:
                    high_price = float(row[self.column_mapping.high])
                except (ValueError, KeyError):
                    pass
            
            if self.column_mapping.low and self.column_mapping.low in df.columns:
                try:
                    low_price = float(row[self.column_mapping.low])
                except (ValueError, KeyError):
                    pass
            
            # Get volume
            volume = 0.0
            if self.column_mapping.volume and self.column_mapping.volume in df.columns:
                try:
                    volume = float(row[self.column_mapping.volume])
                except (ValueError, KeyError):
                    pass
            
            result.append({
                "datetime": ts.isoformat(),
                "date": ts.date().isoformat(),
                "ts": ts.isoformat(),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
            })
        
        # Sort by timestamp
        result.sort(key=lambda x: x["ts"])
        
        return result


__all__ = ["CSVDataProvider", "CSVColumnMapping"]

