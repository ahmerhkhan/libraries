"""
PSXStream: Simulated streaming system for PSX market data.

This module provides a lightweight streaming wrapper that mimics live data updates
by polling PSX endpoints at regular intervals. Note that this does not provide
real-time data - PSX data has a 15-minute delay.
"""

import time
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Union
import pandas as pd

# Lazy import to avoid circular dependency
# from pypsx.endpoints.market_watch import get_market_watch


class PSXStream:
    """
    Simulated streaming wrapper for delayed PSX data.
    
    Mimics live updates by polling endpoints periodically. This stream does not
    provide real-time data - PSX data has a 15-minute delay.
    
    Example:
        >>> from pypsx import PSXStream  # or: from pypsx.core.stream import PSXStream
        >>> 
        >>> def on_update(data):
        ...     print(f"[{data['timestamp']}] Update received for {len(data['data'])} symbols")
        ... 
        >>> stream = PSXStream(symbols=["HBL", "KEL", "PSO"], interval=30)
        >>> stream.subscribe(on_update)
        >>> 
        >>> # Later...
        >>> # stream.stop()
    """
    
    def __init__(self, symbols: Union[str, List[str]], interval: int = 15):
        """
        Initialize PSXStream.
        
        Args:
            symbols: Single symbol or list of symbols to stream
            interval: Polling interval in seconds (default: 15)
            
        Note:
            The interval parameter controls how often we fetch data. PSX data
            itself has a 15-minute delay, so setting interval < 15 seconds
            will fetch the same delayed data multiple times.
        """
        if isinstance(symbols, str):
            symbols = [symbols]
        
        # Normalize symbols to uppercase
        self.symbols = [str(s).upper() for s in symbols]
        self.interval = interval
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
    
    def _fetch_data(self) -> Dict[str, Any]:
        """
        Fetch market watch data for subscribed symbols.
        
        Returns:
            Dictionary containing:
            - timestamp: ISO format timestamp
            - delayed: True (PSX data is always delayed)
            - delay_minutes: 15 (PSX delay period)
            - data: DataFrame or dict with filtered symbol data
            - symbols: List of symbols requested
        """
        try:
            # Lazy import to avoid circular dependency
            from pypsx.endpoints.market_watch import get_market_watch
            
            # Fetch full market watch data
            market_df = get_market_watch(format='dataframe')
            
            if market_df is None or market_df.empty:
                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "delayed": True,
                    "delay_minutes": 15,
                    "data": pd.DataFrame(),
                    "symbols": self.symbols,
                    "error": "Market watch data unavailable"
                }
            
            # Filter by requested symbols
            # Market watch uses Symbol as index
            filtered_data = market_df[market_df.index.isin(self.symbols)]
            
            # Ensure all requested symbols are in the result (even if empty)
            # This way subscribers know if a symbol is missing
            result_symbols = set(filtered_data.index) if not filtered_data.empty else set()
            missing_symbols = set(self.symbols) - result_symbols
            
            if missing_symbols:
                # Create empty rows for missing symbols
                missing_df = pd.DataFrame(
                    index=list(missing_symbols),
                    columns=market_df.columns if not market_df.empty else []
                )
                if filtered_data.empty:
                    filtered_data = missing_df
                else:
                    filtered_data = pd.concat([filtered_data, missing_df])
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "delayed": True,
                "delay_minutes": 15,
                "data": filtered_data,
                "symbols": self.symbols,
                "available_symbols": list(result_symbols),
                "missing_symbols": list(missing_symbols) if missing_symbols else []
            }
            
        except Exception as e:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "delayed": True,
                "delay_minutes": 15,
                "data": pd.DataFrame(),
                "symbols": self.symbols,
                "error": str(e)
            }
    
    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """
        Subscribe to updates. Callback receives each new dataset.
        
        Args:
            callback: Function that will be called with update data on each fetch.
                     The callback receives a dictionary with:
                     - timestamp: ISO format timestamp
                     - delayed: True
                     - delay_minutes: 15
                     - data: DataFrame with symbol data
                     - symbols: List of requested symbols
                     - available_symbols: List of symbols found in market data
                     - missing_symbols: List of symbols not found (if any)
                     - error: Error message (if fetch failed)
        
        Raises:
            RuntimeError: If stream is already running
        """
        with self._lock:
            if self.running:
                raise RuntimeError("Stream is already running. Call stop() before subscribing again.")
            
            self.running = True
            symbol_str = ', '.join(self.symbols)
            print(f"Subscribed to {symbol_str} (15-min delayed feed, polling every {self.interval}s)...")
        
        def _loop() -> None:
            """Internal loop that fetches data periodically."""
            while self.running:
                try:
                    update = self._fetch_data()
                    callback(update)
                except Exception as e:
                    # Call callback with error info
                    callback({
                        "timestamp": datetime.utcnow().isoformat(),
                        "delayed": True,
                        "delay_minutes": 15,
                        "data": pd.DataFrame(),
                        "symbols": self.symbols,
                        "error": f"Callback error: {str(e)}"
                    })
                
                # Sleep for interval, but check running flag periodically
                sleep_time = 0
                while sleep_time < self.interval and self.running:
                    time.sleep(min(1, self.interval - sleep_time))
                    sleep_time += 1
        
        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """
        Stop streaming.
        
        This method stops the polling loop. The thread will exit after
        the current fetch cycle completes.
        """
        with self._lock:
            if not self.running:
                return
            
            self.running = False
        
        if self._thread is not None:
            # Wait for thread to finish (with timeout)
            self._thread.join(timeout=self.interval + 5)
        
        print(f"Stream stopped for {', '.join(self.symbols)}")
    
    def is_running(self) -> bool:
        """
        Check if stream is currently running.
        
        Returns:
            True if stream is active, False otherwise
        """
        with self._lock:
            return self.running

