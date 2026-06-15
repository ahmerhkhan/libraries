from typing import Optional, Dict, Any, cast, Union
import pandas as pd
from pypsx.core.errors import PSXScopeError, PSXNotFoundError
from pypsx.core.utils import normalize_symbol
from pypsx.core.fetchers import fetch_html, fetch_json
from pypsx.core.parsers import (
    parse_market_watch_html,
    parse_timeseries_intraday_json,
    parse_timeseries_eod_json,
    parse_index_constituents_html,
    parse_trading_board_html,
)
from pypsx.endpoints.constants import (
    MARKET_WATCH_URL,
    get_timeseries_intraday_url,
    get_timeseries_eod_url,
    get_index_url,
    TRADING_BOARD_URL,
)
from pypsx.endpoints.announcements import get_announcements
from pypsx.endpoints.historical import get_historical_data
from pypsx.endpoints.market_watch import get_market_watch
from pypsx.endpoints.sectors import get_sector_summary
from pypsx.endpoints.timeseries import get_intraday, get_history
from pypsx.endpoints.company_fundamentals import get_company_fundamentals
from pypsx.endpoints.snapshot import get_snapshot


class PSXTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol.upper().strip()

    def _find_symbol_in_market_watch(self, df: pd.DataFrame) -> pd.DataFrame:
        """Find symbol in Market Watch DataFrame with robust matching."""
        if df.empty:
            raise PSXNotFoundError("Market Watch is empty")
        
        # Try exact match first
        if self.symbol in df.index:
            return df.loc[[self.symbol]]
        
        # Try normalized match (strip suffixes from both symbol and index)
        normalized_symbol = normalize_symbol(self.symbol)
        idx_str = df.index.astype(str)
        
        # Create a mask matching normalized symbols
        normalized_idx = idx_str.str.replace(r"(XD|XR|NC)$", "", regex=True)
        matches = normalized_idx == normalized_symbol
        
        if matches.any():
            matched_idx = df.index[matches]
            return df.loc[matched_idx]
        
        # If still not found, check if symbol exists in any form (case-insensitive)
        idx_lower = idx_str.str.upper()
        match_mask = idx_lower == self.symbol
        if match_mask.any():
            match_idx = df.index[match_mask]
            return df.loc[match_idx]
        
        # Final attempt: search for partial matches (e.g., "OGDC" in "OGDCXD")
        normalized_idx_lower = normalized_idx.str.upper()
        partial_match = normalized_idx_lower == normalized_symbol
        if partial_match.any():
            matched_idx = df.index[partial_match]
            return df.loc[matched_idx]
        
        # If still not found, provide helpful error with available symbols
        available_samples = list(df.index[:10]) if len(df) > 0 else []
        error_msg = f"Symbol '{self.symbol}' not found in Market Watch"
        if available_samples:
            error_msg += f". Available symbols (sample): {', '.join(available_samples)}"
        raise PSXNotFoundError(error_msg)

    @property
    def info(self) -> Dict[str, Any]:
        """
        Get comprehensive company info from company fundamentals and market watch.
        
        Returns comprehensive company information including:
        - Business description
        - Key people (CEO, directors, etc.)
        - Address and website
        - Equity profile
        - Financials (annual and quarterly)
        - Financial ratios
        - Current market data (Sector, Current Price, etc.)
        
        Returns:
            Dictionary with company information organized by category
            
        Example:
            >>> ticker = PSXTicker("OGDC")
            >>> info = ticker.info
            >>> print(info.get('Market Watch', {}).get('Sector'))
            >>> print(info.get('Market Watch', {}).get('Current'))
        """
        info_dict: Dict[str, Any] = {"symbol": self.symbol}
        
        # First, get market watch data for Sector and Current Price
        try:
            market_watch_row = self.market_watch()
            if not market_watch_row.empty:
                market_data: Dict[str, Any] = {}
                if 'Sector' in market_watch_row.columns:
                    market_data['Sector'] = market_watch_row.iloc[0]['Sector']
                if 'Current' in market_watch_row.columns:
                    market_data['Current'] = market_watch_row.iloc[0]['Current']
                if 'Change' in market_watch_row.columns:
                    market_data['Change'] = market_watch_row.iloc[0]['Change']
                if 'Change %' in market_watch_row.columns:
                    market_data['Change %'] = market_watch_row.iloc[0]['Change %']
                if 'Volume' in market_watch_row.columns:
                    market_data['Volume'] = market_watch_row.iloc[0]['Volume']
                if 'LDCP' in market_watch_row.columns:
                    market_data['LDCP'] = market_watch_row.iloc[0]['LDCP']
                if 'Open' in market_watch_row.columns:
                    market_data['Open'] = market_watch_row.iloc[0]['Open']
                if 'High' in market_watch_row.columns:
                    market_data['High'] = market_watch_row.iloc[0]['High']
                if 'Low' in market_watch_row.columns:
                    market_data['Low'] = market_watch_row.iloc[0]['Low']
                
                if market_data:
                    info_dict['Market Watch'] = market_data
        except Exception:
            # Add fallback message
            info_dict['Market Watch'] = {
                'Note': f'Market watch data unavailable for {self.symbol}'
            }
        
        # Get company fundamentals
        try:
            df = get_company_fundamentals(self.symbol, format='dataframe')
            if df is not None and not df.empty:  # type: ignore[union-attr]
                # Reset index to access all levels
                df_reset = df.reset_index()  # type: ignore[union-attr]
                
                # Group by category
                if 'CATEGORY' in df_reset.columns and 'METRIC' in df_reset.columns and 'VALUE' in df_reset.columns:
                    for category in df_reset['CATEGORY'].unique():
                        if pd.isna(category):
                            continue
                        category_str = str(category)
                        category_df = df_reset[df_reset['CATEGORY'] == category]
                        
                        # Create nested dict: category -> metric -> value
                        category_dict: Dict[str, Any] = {}
                        for _, row in category_df.iterrows():
                            metric = str(row['METRIC']) if not pd.isna(row['METRIC']) else ""
                            value = row['VALUE']
                            if value and str(value).strip() and str(value).strip() != 'nan':
                                category_dict[metric] = value
                        
                        if category_dict:
                            info_dict[category_str] = category_dict
                else:
                    # Fallback: convert DataFrame to dict
                    for col in df.columns:  # type: ignore[union-attr]
                        if col not in ['SYMBOL', 'symbol']:
                            info_dict[col] = df[col].to_dict() if len(df) > 0 else {}
        except Exception as e:
            # Add fallback for missing fundamentals
            if 'Profile' not in info_dict:
                info_dict['Profile'] = {
                    'Business Description': f'No business description available for {self.symbol} on PSX website.',
                    'Website': f'No website available for {self.symbol} on PSX website.'
                }
        
        # If no data at all, return minimal info
        if len(info_dict) == 1:  # Only has symbol
            info_dict['Profile'] = {
                'Note': f'Limited data available for {self.symbol} on PSX website.'
            }
        
        # Add top-level convenience keys for backward compatibility
        # Users can access info.get('Sector') and info.get('Current') directly
        if 'Market Watch' in info_dict:
            market_data = info_dict['Market Watch']
            if 'Sector' in market_data:
                info_dict['Sector'] = market_data['Sector']
            if 'Current' in market_data:
                info_dict['Current'] = market_data['Current']
            if 'Change' in market_data:
                info_dict['Change'] = market_data['Change']
            if 'Change %' in market_data:
                info_dict['Change %'] = market_data.get('Change %')
            if 'Volume' in market_data:
                info_dict['Volume'] = market_data['Volume']
        
        return info_dict

    def history(self, period: str = "1y", interval: str = "1d", to_csv: Optional[str] = None) -> pd.DataFrame:
        """
        Get historical price data (EOD or Intraday).
        Note: For full OHLCV data, use get_historical() instead.
        
        Args:
            period: Time period (e.g., "1y", "6m", "5y")
            interval: "1d" for end-of-day or "1m" for intraday
            to_csv: Optional CSV file path to save data
            
        Returns:
            DataFrame with price/volume data
        """
        if interval == "1d":
            df = get_history(self.symbol, period=period, format='dataframe')
        elif interval == "1m":
            df = get_intraday(self.symbol, format='dataframe')
        else:
            raise PSXScopeError("interval must be '1d' or '1m'")
        if df is None or df.empty:  # type: ignore[union-attr]
            raise PSXNotFoundError("No data returned for requested timeseries")
        if to_csv:
            df.to_csv(to_csv)  # type: ignore[union-attr]
        return df
    
    def sector(self) -> pd.DataFrame:
        """
        Get sector information for this symbol.
        
        Returns:
            DataFrame with sector-level data
        """
        df = self.info
        sector_name = df.get("Sector", "")
        if not sector_name:
            return pd.DataFrame()
        
        # Get sector summary
        sector_df = get_sector_summary(format='dataframe')
        if sector_df is None or sector_df.empty:  # type: ignore[union-attr]
            return pd.DataFrame()
        
        # Filter by sector name
        if "Sector Name" in sector_df.columns:  # type: ignore[union-attr]
            matching = sector_df[sector_df["Sector Name"] == sector_name]
            return matching
        return pd.DataFrame()

    def intraday(self) -> pd.DataFrame:
        """Convenience method for 1m intraday data (last ~2 days)."""
        return self.history(period="1d", interval="1m")

    def dividends(self) -> pd.DataFrame:
        """
        Get dividend information for this symbol.
        
        Returns:
            DataFrame with dividend information
            
        Example:
            >>> ticker = PSXTicker("HBL")
            >>> divs = ticker.dividends()
            >>> print(divs)
        """
        try:
            from pypsx.endpoints.dividends import get_dividend_info
            df = get_dividend_info(self.symbol)
            # Remove SYMBOL column if it's in the index (should not be a separate column)
            if isinstance(df, pd.DataFrame) and not df.empty:
                # If SYMBOL is in columns and also in index, drop the column
                if 'SYMBOL' in df.columns and df.index.name == 'SYMBOL':
                    df = df.drop(columns=['SYMBOL'])
                elif 'Symbol' in df.columns and df.index.name == 'Symbol':
                    df = df.drop(columns=['Symbol'])
            return df
        except Exception as e:
            raise PSXNotFoundError(f"Dividends not available: {e}")

    @property
    def fast_info(self) -> Dict[str, Any]:
        """Quick metrics from Market Watch row (price, change, volume)."""
        row = self.marketwatch()
        out: Dict[str, Any] = {}
        for key in ["Current", "Change", "Change %", "Volume", "LDCP", "Open", "High", "Low"]:
            if key in row.columns:
                out[key] = row.iloc[0][key]
        out["symbol"] = row.index[0]
        return out

    def get_historical(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_workers: int = 5,
        show_progress: bool = True
    ) -> pd.DataFrame:
        """
        Get full OHLCV historical data for this symbol.
        
        This method fetches complete Open, High, Low, Close, Volume data by making
        POST requests to https://dps.psx.com.pk/historical for each month.
        
        Args:
            start_date: Start date in "YYYY-MM-DD" format (default: 1 month ago)
            end_date: End date in "YYYY-MM-DD" format (default: today)
            max_workers: Maximum number of parallel threads for fetching months (default: 5)
            show_progress: Show progress bar for monthly fetches (default: True)
            
        Returns:
            DataFrame with TIME as index and OPEN, HIGH, LOW, CLOSE, VOLUME columns
            
        Example:
            >>> t = Ticker("OGDC")
            >>> df = t.get_historical("2024-01-01", "2024-12-31")
            >>> print(df.head())
        """
        return get_historical_data(self.symbol, start_date, end_date, max_workers, show_progress)

    def orderbook(self) -> pd.DataFrame:
        """Get orderbook/trading board data for this symbol."""
        html = fetch_html(TRADING_BOARD_URL, timeout=20.0, ttl=30)
        df = parse_trading_board_html(html)
        if df.empty:
            raise PSXNotFoundError("Trading board is empty")
        
        # Try exact match first
        if self.symbol in df.index:
            return df.loc[[self.symbol]]
        
        # Try normalized match
        normalized_symbol = normalize_symbol(self.symbol)
        idx_str = df.index.astype(str)
        normalized_idx = idx_str.str.replace(r"(XD|XR|NC)$", "", regex=True)
        matches = normalized_idx == normalized_symbol
        
        if matches.any():
            matched_idx = df.index[matches]
            return df.loc[matched_idx]
        
        # Symbol not found
        raise PSXNotFoundError(f"Symbol {self.symbol} not found on trading board")

    # Alias for backward compatibility
    def order_book(self) -> pd.DataFrame:
        """Alias for orderbook(). Deprecated - use orderbook() instead."""
        return self.orderbook()

    def announcements(self) -> pd.DataFrame:
        """
        Get company announcements (financial results, board meetings, etc.).
        
        Returns:
            DataFrame with announcements data
            
        Example:
            >>> ticker = PSXTicker("OGDC")
            >>> announcements = ticker.announcements()
            >>> print(announcements.head())
        """
        df_any = get_announcements(self.symbol, format='dataframe')
        # Return empty DataFrame if None, don't raise error
        if df_any is None:
            return pd.DataFrame(columns=['TITLE', 'SECTION', 'IMAGE_LINK', 'PDF_LINK'])
        if not isinstance(df_any, pd.DataFrame):
            return pd.DataFrame(columns=['TITLE', 'SECTION', 'IMAGE_LINK', 'PDF_LINK'])
        if df_any.empty:
            # Return empty DataFrame with message column
            empty_df = pd.DataFrame(columns=['TITLE', 'SECTION', 'IMAGE_LINK', 'PDF_LINK'])
            empty_df.loc[0] = [f'No announcements available for {self.symbol} on PSX website.', 'N/A', None, None]
            return empty_df
        return df_any

    def market_watch(self) -> pd.DataFrame:
        """Get Market Watch row for this symbol."""
        try:
            html = fetch_html(MARKET_WATCH_URL, timeout=30.0, ttl=30)
        except Exception as e:
            # Retry once with longer timeout
            try:
                html = fetch_html(MARKET_WATCH_URL, timeout=45.0, ttl=30)
            except Exception:
                raise PSXNotFoundError(f"Failed to fetch Market Watch: {e}")
        
        df = parse_market_watch_html(html)
        row = self._find_symbol_in_market_watch(df)
        return row
    
    def marketwatch(self) -> pd.DataFrame:
        """Alias for market_watch(). Deprecated - use market_watch() instead."""
        return self.market_watch()

    @property
    def snapshot(self) -> Dict[str, Any]:
        """
        Get comprehensive snapshot data from all tabs on company page.
        
        This is a more holistic approach that extracts data from ALL tabs
        (REG, Intraday, etc.) on the company page, providing complete
        OHLCV data, bid/ask, circuit breaker, ranges, ratios, etc.
        
        Returns:
            Dictionary with tab names as keys (e.g., 'REG') and stats dictionaries as values
            Each stats dictionary contains metric: value pairs
            
        Example:
            >>> ticker = PSXTicker("BOP")
            >>> snapshot = ticker.snapshot
            >>> print(snapshot['REG']['Open'])
            >>> print(snapshot['REG']['52-WEEK RANGE ^'])
            
        Note:
            The 'REG' tab typically contains the most comprehensive data including:
            - OHLCV (Open, High, Low, Volume)
            - Circuit Breaker
            - Day Range, 52-Week Range
            - Bid/Ask Price and Volume
            - LDCP, VAR, HAIRCUT
            - P/E Ratio
            - 1-Year Change, YTD Change
        """
        try:
            snapshot_data = get_snapshot(self.symbol, format='dict')
            if snapshot_data is None:
                return {}
            # Type check: get_snapshot returns Optional[Union[Dict, pd.DataFrame]]
            # We ensure it's a dict by passing format='dict' and checking
            if isinstance(snapshot_data, dict):
                return cast(Dict[str, Any], snapshot_data)
            return {}
        except Exception as e:
            return {}

    def constituents(self) -> pd.DataFrame:
        """Get index constituents. Only valid for index tickers."""
        url = get_index_url(self.symbol)
        html = fetch_html(url, timeout=30.0, ttl=300)
        df = parse_index_constituents_html(html)
        if df.empty:
            raise PSXScopeError("Constituents available only for index symbols")
        return df


# Alias for backward compatibility
Ticker = PSXTicker


