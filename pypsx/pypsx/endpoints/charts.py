"""
Charting and visualization module for PyPSX library.

Provides comprehensive charting capabilities for PSX data including:
- OHLC candlestick charts
- Line charts for price trends
- Volume charts
- Multiple timespan support (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y)
- Technical indicators overlay
- Correlation heatmaps and analysis
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from matplotlib.ticker import MaxNLocator
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Union, List, Tuple
from loguru import logger
import warnings
import seaborn as sns

# Suppress matplotlib warnings
warnings.filterwarnings('ignore', category=UserWarning)

from pypsx.endpoints.timeseries import get_history, get_intraday
from pypsx.core.utils import validate_symbol
from pypsx.ticker import PSXTicker


def create_price_chart(symbol: str, period: str = "1y", chart_type: str = "candlestick", 
                      show_volume: bool = True, figsize: Tuple[int, int] = (12, 8),
                      title: Optional[str] = None, save_path: Optional[str] = None) -> Optional[plt.Figure]:
    """
    Create a comprehensive price chart for a symbol.
    
    Args:
        symbol: Stock symbol (e.g., "OGDC", "KSE100")
        period: Time period ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y")
        chart_type: Chart type ("candlestick", "line", "ohlc")
        show_volume: Whether to show volume subplot
        figsize: Figure size (width, height)
        title: Custom chart title
        save_path: Path to save the chart (optional)
        
    Returns:
        matplotlib Figure object, None if failed
        
    Example:
        >>> import pypsx
        >>> fig = pypsx.create_price_chart("OGDC", period="1y", chart_type="candlestick")
        >>> plt.show()
    """
    try:
        logger.info(f"Creating {chart_type} chart for {symbol} (period: {period})")
        
        # Get historical data
        df = get_history(symbol, period)
        if df is None or df.empty:
            logger.error(f"No historical data available for {symbol}")
            return None
        
        # Create figure and subplots
        if show_volume:
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, 
                                          gridspec_kw={'height_ratios': [3, 1]})
        else:
            fig, ax1 = plt.subplots(1, 1, figsize=figsize)
            ax2 = None
        
        # Set title
        if title is None:
            title = f"{symbol} Price Chart ({period})"
        fig.suptitle(title, fontsize=16, fontweight='bold')
        
        # Create the main price chart
        if chart_type == "candlestick":
            _create_candlestick_chart(ax1, df)
        elif chart_type == "line":
            _create_line_chart(ax1, df)
        elif chart_type == "ohlc":
            _create_ohlc_chart(ax1, df)
        else:
            logger.error(f"Unsupported chart type: {chart_type}")
            return None
        
        # Create volume chart if requested
        if show_volume and ax2 is not None:
            _create_volume_chart(ax2, df)
        
        # Format the chart
        _format_chart(fig, ax1, ax2, period)
        
        # Save if path provided
        if save_path:
            import os
            os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)
            fig.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"Chart saved to {save_path}")
        
        logger.info(f"Successfully created {chart_type} chart for {symbol}")
        return fig
        
    except Exception as e:
        logger.error(f"Error creating chart for {symbol}: {e}")
        return None


def create_multi_symbol_chart(symbols: List[str], period: str = "1y", 
                              chart_type: str = "line", figsize: Tuple[int, int] = (12, 8),
                              title: Optional[str] = None, normalize: bool = True) -> Optional[plt.Figure]:
    """
    Create a multi-symbol comparison chart.
    
    Args:
        symbols: List of stock symbols
        period: Time period ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y")
        chart_type: Chart type ("line", "area")
        figsize: Figure size (width, height)
        title: Custom chart title
        normalize: Whether to normalize prices to 100 for comparison
        
    Returns:
        matplotlib Figure object, None if failed
        
    Example:
        >>> import pypsx
        >>> fig = pypsx.create_multi_symbol_chart(["OGDC", "PPL", "KEL"], period="1y")
        >>> plt.show()
    """
    try:
        logger.info(f"Creating multi-symbol chart for {symbols} (period: {period})")
        
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        
        # Set title
        if title is None:
            title = f"Multi-Symbol Comparison ({period})"
        fig.suptitle(title, fontsize=16, fontweight='bold')
        
        colors = plt.cm.Set3(np.linspace(0, 1, len(symbols)))
        
        for i, symbol in enumerate(symbols):
            df = get_history(symbol, period)
            if df is None or df.empty:
                logger.warning(f"No data available for {symbol}")
                continue
            
            if chart_type == "line":
                if normalize:
                    # Normalize to 100 for comparison (internal, not shown to user)
                    normalized_close = (df['CLOSE'] / df['CLOSE'].iloc[0]) * 100
                    ax.plot(df.index, normalized_close, label=symbol, 
                           color=colors[i], linewidth=2)
                else:
                    ax.plot(df.index, df['CLOSE'], label=symbol, 
                           color=colors[i], linewidth=2)
            elif chart_type == "area":
                ax.fill_between(df.index, df['CLOSE'], alpha=0.3, 
                               color=colors[i], label=symbol)
        
        ax.set_ylabel("Price")
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Format x-axis
        _format_x_axis(ax, period)
        
        logger.info(f"Successfully created multi-symbol chart for {len(symbols)} symbols")
        return fig
        
    except Exception as e:
        logger.error(f"Error creating multi-symbol chart: {e}")
        return None


def create_sector_performance_chart(period: str = "1y", figsize: Tuple[int, int] = (14, 10)) -> Optional[plt.Figure]:
    """
    Create a sector performance comparison chart.
    
    Args:
        period: Time period ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y")
        figsize: Figure size (width, height)
        
    Returns:
        matplotlib Figure object, None if failed
        
    Example:
        >>> import pypsx
        >>> fig = pypsx.create_sector_performance_chart(period="1y")
        >>> plt.show()
    """
    try:
        logger.info(f"Creating sector performance chart (period: {period})")
        
        # Get market watch data for sector analysis
        from pypsx.endpoints.market_watch import get_market_watch
        market_df = get_market_watch()
        if market_df is None or market_df.empty:
            logger.error("No market watch data available")
            return None
        
        # Calculate sector performance
        sector_performance = market_df.groupby('SECTOR').agg({
            'CURRENT': 'mean',
            '%CHANGE': 'mean',
            'VOLUME': 'sum'
        }).sort_values('%CHANGE', ascending=False)
        
        # Create figure
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize)
        
        # Sector performance bar chart
        colors = plt.cm.RdYlGn(sector_performance['%CHANGE'].values / 
                              sector_performance['%CHANGE'].abs().max())
        
        bars = ax1.bar(range(len(sector_performance)), sector_performance['%CHANGE'], 
                      color=colors, alpha=0.7)
        
        ax1.set_title(f"Sector Performance ({period})", fontweight='bold')
        ax1.set_ylabel("Average % Change")
        ax1.set_xticks(range(len(sector_performance)))
        ax1.set_xticklabels(sector_performance.index, rotation=45, ha='right')
        ax1.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for i, bar in enumerate(bars):
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.2f}%', ha='center', va='bottom' if height > 0 else 'top')
        
        # Volume by sector
        ax2.bar(range(len(sector_performance)), sector_performance['VOLUME'], 
               color='skyblue', alpha=0.7)
        ax2.set_title("Trading Volume by Sector", fontweight='bold')
        ax2.set_ylabel("Total Volume")
        ax2.set_xticks(range(len(sector_performance)))
        ax2.set_xticklabels(sector_performance.index, rotation=45, ha='right')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        logger.info(f"Successfully created sector performance chart")
        return fig
        
    except Exception as e:
        logger.error(f"Error creating sector performance chart: {e}")
        return None


def create_index_comparison_chart(indices: List[str] = None, period: str = "1y", 
                                figsize: Tuple[int, int] = (12, 8)) -> Optional[plt.Figure]:
    """
    Create an index comparison chart.
    
    Args:
        indices: List of index symbols (default: ["KSE100", "KSE30", "KMI30"])
        period: Time period ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y")
        figsize: Figure size (width, height)
        
    Returns:
        matplotlib Figure object, None if failed
        
    Example:
        >>> import pypsx
        >>> fig = pypsx.create_index_comparison_chart(["KSE100", "KSE30"], period="1y")
        >>> plt.show()
    """
    try:
        if indices is None:
            indices = ["KSE100", "KSE30", "KMI30"]
        
        logger.info(f"Creating index comparison chart for {indices} (period: {period})")
        
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        
        colors = plt.cm.Set1(np.linspace(0, 1, len(indices)))
        
        for i, index in enumerate(indices):
            df = get_history(index, period)
            if df is None or df.empty:
                logger.warning(f"No data available for {index}")
                continue
            
            # Normalize to 100 for comparison (internal, not shown to user)
            normalized_close = (df['CLOSE'] / df['CLOSE'].iloc[0]) * 100
            ax.plot(df.index, normalized_close, label=index, 
                   color=colors[i], linewidth=2)
        
        ax.set_title(f"Index Performance Comparison ({period})", fontweight='bold')
        ax.set_ylabel("Performance")
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Format x-axis
        _format_x_axis(ax, period)
        
        logger.info(f"Successfully created index comparison chart")
        return fig
        
    except Exception as e:
        logger.error(f"Error creating index comparison chart: {e}")
        return None


def _create_candlestick_chart(ax, df: pd.DataFrame):
    """Create a candlestick chart."""
    # Ensure we have OHLC data
    if 'OPEN' not in df.columns or 'HIGH' not in df.columns or 'LOW' not in df.columns or 'CLOSE' not in df.columns:
        # Fallback: use CLOSE for all if OHLC not available
        if 'CLOSE' in df.columns:
            df['OPEN'] = df['CLOSE']
            df['HIGH'] = df['CLOSE']
            df['LOW'] = df['CLOSE']
        else:
            # No price data available
            return
    
    # Use numeric index for positioning
    x_positions = range(len(df))
    
    for i, (date, row) in enumerate(df.iterrows()):
        try:
            open_price = float(row.get('OPEN', row.get('Open', row.get('CLOSE', 0))))
            high_price = float(row.get('HIGH', row.get('High', row.get('CLOSE', 0))))
            low_price = float(row.get('LOW', row.get('Low', row.get('CLOSE', 0))))
            close_price = float(row.get('CLOSE', row.get('Close', 0)))
            
            if pd.isna(open_price) or pd.isna(close_price) or pd.isna(high_price) or pd.isna(low_price):
                continue
            
            # Determine color
            color = 'green' if close_price >= open_price else 'red'
            
            # Draw the wick (high-low line)
            ax.plot([i, i], [low_price, high_price], color='black', linewidth=0.8)
            
            # Draw the body (open-close rectangle)
            body_height = abs(close_price - open_price)
            body_bottom = min(open_price, close_price)
            
            # Only draw body if there's a difference
            if body_height > 0:
                rect = Rectangle((i - 0.35, body_bottom), 0.7, body_height, 
                                facecolor=color, edgecolor='black', linewidth=0.5, alpha=0.8)
                ax.add_patch(rect)
            else:
                # Draw a horizontal line for doji
                ax.plot([i - 0.35, i + 0.35], [close_price, close_price], 
                       color='black', linewidth=1)
        except (ValueError, TypeError) as e:
            # Skip invalid data points
            continue
    
    # Set x-axis labels to dates
    if len(df) > 0:
        # Use date index for x-axis labels
        ax.set_xticks(range(0, len(df), max(1, len(df) // 10)))
        ax.set_xticklabels([df.index[i].strftime('%Y-%m-%d') if hasattr(df.index[i], 'strftime') else str(df.index[i]) 
                           for i in range(0, len(df), max(1, len(df) // 10))], rotation=45, ha='right')


def _create_line_chart(ax, df: pd.DataFrame):
    """Create a line chart."""
    ax.plot(df.index, df['CLOSE'], color='blue', linewidth=2, label='Close Price')
    ax.fill_between(df.index, df['CLOSE'], alpha=0.3, color='blue')


def _create_ohlc_chart(ax, df: pd.DataFrame):
    """Create an OHLC chart."""
    for i, (date, row) in enumerate(df.iterrows()):
        open_price = row['OPEN']
        high_price = row['HIGH']
        low_price = row['LOW']
        close_price = row['CLOSE']
        
        # Draw OHLC lines
        ax.plot([i, i], [low_price, high_price], color='black', linewidth=1)
        ax.plot([i-0.2, i], [open_price, open_price], color='black', linewidth=2)
        ax.plot([i, i+0.2], [close_price, close_price], color='black', linewidth=2)


def _create_volume_chart(ax, df: pd.DataFrame):
    """Create a volume chart."""
    colors = ['green' if row['CLOSE'] >= row['OPEN'] else 'red' 
              for _, row in df.iterrows()]
    ax.bar(range(len(df)), df['VOLUME'], color=colors, alpha=0.7)
    ax.set_ylabel("Volume")


def _format_chart(fig, ax1, ax2, period: str):
    """Format the chart appearance."""
    # Format main chart
    ax1.set_ylabel("Price")
    ax1.grid(True, alpha=0.3)
    
    # Format x-axis
    _format_x_axis(ax1, period)
    
    # Format volume chart if present
    if ax2 is not None:
        ax2.set_ylabel("Volume")
        ax2.grid(True, alpha=0.3)
        _format_x_axis(ax2, period)
    
    plt.tight_layout()


def _format_x_axis(ax, period: str):
    """Format x-axis based on period with proper spacing and labels."""
    # Clear any existing formatting
    ax.tick_params(axis='x', rotation=45)
    
    if period in ["1d"]:
        # For 1 day, show every 4 hours to limit ticks
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    elif period in ["5d"]:
        # For 5 days, show daily intervals
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    elif period in ["1mo"]:
        # For 1 month, show weekly intervals
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    elif period in ["3mo"]:
        # For 3 months, show bi-weekly intervals
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    elif period in ["6mo"]:
        # For 6 months, show monthly intervals
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    elif period in ["1y"]:
        # For 1 year, show monthly intervals
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    elif period in ["2y"]:
        # For 2 years, show quarterly intervals
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    else:  # 5y
        # For 5 years, show yearly intervals
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.xaxis.set_major_locator(mdates.YearLocator())
    
    # Ensure labels don't overlap
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')


def get_chart_data(symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """
    Get formatted chart data for a symbol.
    
    Args:
        symbol: Stock symbol
        period: Time period
        
    Returns:
        DataFrame with chart-ready data
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_chart_data("OGDC", period="1y")
        >>> print(df.head())
    """
    try:
        df = get_history(symbol, period)
        if df is None or df.empty:
            return None
        
        # Add technical indicators
        df = _add_technical_indicators(df)
        
        return df
        
    except Exception as e:
        logger.error(f"Error getting chart data for {symbol}: {e}")
        return None


def _add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add basic technical indicators to the dataframe."""
    # Simple Moving Averages
    df['SMA_20'] = df['CLOSE'].rolling(window=20).mean()
    df['SMA_50'] = df['CLOSE'].rolling(window=50).mean()
    
    # Exponential Moving Averages
    df['EMA_12'] = df['CLOSE'].ewm(span=12).mean()
    df['EMA_26'] = df['CLOSE'].ewm(span=26).mean()
    
    # RSI
    delta = df['CLOSE'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df


def create_technical_analysis_chart(symbol: str, period: str = "1y", 
                                  figsize: Tuple[int, int] = (14, 10)) -> Optional[plt.Figure]:
    """
    Create a comprehensive technical analysis chart.
    
    Args:
        symbol: Stock symbol
        period: Time period
        figsize: Figure size
        
    Returns:
        matplotlib Figure object, None if failed
        
    Example:
        >>> import pypsx
        >>> fig = pypsx.create_technical_analysis_chart("OGDC", period="1y")
        >>> plt.show()
    """
    try:
        logger.info(f"Creating technical analysis chart for {symbol} (period: {period})")
        
        df = get_chart_data(symbol, period)
        if df is None or df.empty:
            logger.error(f"No chart data available for {symbol}")
            return None
        
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=figsize, 
                                           gridspec_kw={'height_ratios': [3, 1, 1]})
        
        # Price chart with moving averages
        ax1.plot(df.index, df['CLOSE'], label='Close Price', color='black', linewidth=1)
        ax1.plot(df.index, df['SMA_20'], label='SMA 20', color='blue', alpha=0.7)
        ax1.plot(df.index, df['SMA_50'], label='SMA 50', color='red', alpha=0.7)
        ax1.set_title(f"{symbol} Technical Analysis ({period})", fontweight='bold')
        ax1.set_ylabel("Price")
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Volume chart
        colors = ['green' if row['CLOSE'] >= row['OPEN'] else 'red' 
                  for _, row in df.iterrows()]
        ax2.bar(range(len(df)), df['VOLUME'], color=colors, alpha=0.7)
        ax2.set_ylabel("Volume")
        ax2.grid(True, alpha=0.3)
        
        # RSI chart
        ax3.plot(df.index, df['RSI'], color='purple', linewidth=1)
        ax3.axhline(y=70, color='red', linestyle='--', alpha=0.7, label='Overbought')
        ax3.axhline(y=30, color='green', linestyle='--', alpha=0.7, label='Oversold')
        ax3.set_ylabel("RSI")
        ax3.set_ylim(0, 100)
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        # Format x-axis for all subplots
        for ax in [ax1, ax2, ax3]:
            _format_x_axis(ax, period)
        
        plt.tight_layout()
        
        logger.info(f"Successfully created technical analysis chart for {symbol}")
        return fig
        
    except Exception as e:
        logger.error(f"Error creating technical analysis chart for {symbol}: {e}")
        return None


def create_correlation_heatmap(symbols: List[str], period: str = "1y", 
                              figsize: Tuple[int, int] = (12, 10)) -> Optional[plt.Figure]:
    """
    Create a correlation heatmap for multiple symbols.
    
    Args:
        symbols: List of stock symbols to analyze
        period: Time period for correlation analysis
        figsize: Figure size (width, height)
        
    Returns:
        matplotlib Figure object, None if failed
        
    Example:
        >>> import pypsx
        >>> fig = pypsx.create_correlation_heatmap(["OGDC", "PPL", "KEL", "MCB"], period="1y")
        >>> plt.show()
    """
    try:
        logger.info(f"Creating correlation heatmap for {symbols} (period: {period})")
        
        # Collect price data for all symbols
        price_data = {}
        for symbol in symbols:
            df = get_history(symbol, period)
            if df is not None and not df.empty:
                price_data[symbol] = df['CLOSE']
            else:
                logger.warning(f"No data available for {symbol}")
        
        if len(price_data) < 2:
            logger.error("Need at least 2 symbols with data for correlation analysis")
            return None
        
        # Create DataFrame with aligned dates
        df_prices = pd.DataFrame(price_data)
        
        # Calculate returns for correlation
        df_returns = df_prices.pct_change(fill_method=None).dropna()
        
        # Calculate correlation matrix
        correlation_matrix = df_returns.corr()
        
        # Create heatmap
        num_symbols = len(correlation_matrix)
        
        # Adjust figure size based on number of symbols for better readability
        if num_symbols <= 20:
            adjusted_figsize = (figsize[0], figsize[1])
        elif num_symbols <= 30:
            adjusted_figsize = (max(figsize[0], 18), max(figsize[1], 16))
        else:
            adjusted_figsize = (max(figsize[0], 24), max(figsize[1], 20))
        
        fig, ax = plt.subplots(1, 1, figsize=adjusted_figsize)
        
        # Only annotate significant correlations (above threshold) to reduce clutter
        # For 30 symbols, only show annotations for strong correlations (|r| >= 0.6)
        if num_symbols <= 15:
            # Small matrices: show all annotations
            annot_data = True
            annot_fontsize = 9
            fmt_str = '.2f'
        elif num_symbols <= 30:
            # Medium matrices: only show strong correlations (|r| >= 0.6)
            # Create annotation array with formatted strings, empty for weak correlations
            annot_data = correlation_matrix.copy()
            weak_mask = correlation_matrix.abs() < 0.6
            # Format all values first
            annot_data = annot_data.map(lambda x: f'{x:.2f}')
            # Replace weak correlations with empty strings
            annot_data[weak_mask] = ''
            annot_fontsize = 8
            fmt_str = ''  # Already formatted as strings
        else:
            # Large matrices: only show very strong correlations (|r| >= 0.7)
            annot_data = correlation_matrix.copy()
            weak_mask = correlation_matrix.abs() < 0.7
            annot_data = annot_data.map(lambda x: f'{x:.2f}')
            annot_data[weak_mask] = ''
            annot_fontsize = 7
            fmt_str = ''  # Already formatted as strings
        
        # Use seaborn for better heatmap
        # Empty strings in annot_data will result in no annotation for those cells
        sns.heatmap(correlation_matrix, annot=annot_data, 
                   cmap='RdYlBu_r', center=0,
                   square=True, linewidths=0.3 if num_symbols > 20 else 0.5,
                   cbar_kws={"shrink": 0.8}, fmt=fmt_str, ax=ax,
                   annot_kws={"size": annot_fontsize},
                   xticklabels=True, yticklabels=True)
        
        ax.set_title(f"Stock Correlation Matrix - {num_symbols} Symbols ({period})", 
                    fontweight='bold', fontsize=16, pad=20)
        ax.set_xlabel("Stocks", fontsize=12)
        ax.set_ylabel("Stocks", fontsize=12)
        
        # Better label formatting - rotate and adjust spacing
        plt.setp(ax.get_xticklabels(), rotation=90, ha='center', va='top', fontsize=9)
        plt.setp(ax.get_yticklabels(), rotation=0, ha='right', va='center', fontsize=9)
        
        # Adjust layout to prevent label cutoff
        plt.tight_layout(rect=[0.05, 0.05, 0.95, 0.95])
        
        logger.info(f"Successfully created correlation heatmap for {len(symbols)} symbols")
        return fig
        
    except Exception as e:
        logger.error(f"Error creating correlation heatmap: {e}")
        return None


def create_sector_correlation_heatmap(period: str = "1y", 
                                     figsize: Tuple[int, int] = (14, 12)) -> Optional[plt.Figure]:
    """
    Create a sector correlation heatmap showing correlations between different sectors.
    
    Args:
        period: Time period for correlation analysis
        figsize: Figure size (width, height)
        
    Returns:
        matplotlib Figure object, None if failed
        
    Example:
        >>> import pypsx
        >>> fig = pypsx.create_sector_correlation_heatmap(period="1y")
        >>> plt.show()
    """
    try:
        logger.info(f"Creating sector correlation heatmap (period: {period})")
        
        # Get market watch data
        from pypsx.endpoints.market_watch import get_market_watch
        market_df = get_market_watch()
        if market_df is None or market_df.empty:
            logger.error("No market watch data available")
            return None
        
        # Get top stocks from each sector
        sector_data = {}
        sectors = market_df['SECTOR'].value_counts().head(10).index  # Top 10 sectors
        
        for sector in sectors:
            sector_stocks = market_df[market_df['SECTOR'] == sector].index.tolist()
            if len(sector_stocks) >= 3:  # Need at least 3 stocks per sector
                # Take top 3 stocks by volume
                sector_df = market_df.loc[sector_stocks].sort_values('VOLUME', ascending=False)
                top_stocks = sector_df.head(3).index.tolist()
                
                # Get average returns for the sector
                sector_returns = []
                for stock in top_stocks:
                    df = get_history(stock, period)
                    if df is not None and not df.empty:
                        returns = df['CLOSE'].pct_change(fill_method=None).dropna()
                        sector_returns.append(returns)
                
                if sector_returns:
                    # Average the returns across stocks in the sector
                    sector_df_returns = pd.concat(sector_returns, axis=1).mean(axis=1)
                    sector_data[sector] = sector_df_returns
        
        if len(sector_data) < 2:
            logger.error("Need at least 2 sectors with data for correlation analysis")
            return None
        
        # Create DataFrame with sector returns
        df_sector_returns = pd.DataFrame(sector_data)
        
        # Calculate correlation matrix
        correlation_matrix = df_sector_returns.corr()
        
        # Create heatmap
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        
        # Use seaborn for better heatmap
        sns.heatmap(correlation_matrix, annot=True, cmap='RdYlBu_r', center=0,
                   square=True, linewidths=0.5, cbar_kws={"shrink": 0.8},
                   fmt='.2f', ax=ax)
        
        ax.set_title(f"Sector Correlation Matrix ({period})", fontweight='bold', fontsize=14)
        ax.set_xlabel("Sectors")
        ax.set_ylabel("Sectors")
        
        # Rotate labels for better readability
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
        plt.setp(ax.get_yticklabels(), rotation=0)
        
        plt.tight_layout()
        
        logger.info(f"Successfully created sector correlation heatmap for {len(sector_data)} sectors")
        return fig
        
    except Exception as e:
        logger.error(f"Error creating sector correlation heatmap: {e}")
        return None


def create_index_correlation_heatmap(indices: List[str] = None, period: str = "1y",
                                   figsize: Tuple[int, int] = (10, 8)) -> Optional[plt.Figure]:
    """
    Create a correlation heatmap for PSX indices.
    
    Args:
        indices: List of index symbols (default: ["KSE100", "KSE30", "KMI30", "ALLSHR"])
        period: Time period for correlation analysis
        figsize: Figure size (width, height)
        
    Returns:
        matplotlib Figure object, None if failed
        
    Example:
        >>> import pypsx
        >>> fig = pypsx.create_index_correlation_heatmap(["KSE100", "KSE30"], period="1y")
        >>> plt.show()
    """
    try:
        if indices is None:
            indices = ["KSE100", "KSE30", "KMI30", "ALLSHR"]
        
        logger.info(f"Creating index correlation heatmap for {indices} (period: {period})")
        
        # Collect index data
        index_data = {}
        for index in indices:
            df = get_history(index, period)
            if df is None or not df.empty:
                index_data[index] = df['CLOSE']
            else:
                logger.warning(f"No data available for {index}")
        
        if len(index_data) < 2:
            logger.error("Need at least 2 indices with data for correlation analysis")
            return None
        
        # Create DataFrame with aligned dates
        df_indices = pd.DataFrame(index_data)
        
        # Calculate returns for correlation
        df_returns = df_indices.pct_change(fill_method=None).dropna()
        
        # Calculate correlation matrix
        correlation_matrix = df_returns.corr()
        
        # Create heatmap
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        
        # Use seaborn for better heatmap
        sns.heatmap(correlation_matrix, annot=True, cmap='RdYlBu_r', center=0,
                   square=True, linewidths=0.5, cbar_kws={"shrink": 0.8},
                   fmt='.2f', ax=ax)
        
        ax.set_title(f"Index Correlation Matrix ({period})", fontweight='bold', fontsize=14)
        ax.set_xlabel("Indices")
        ax.set_ylabel("Indices")
        
        plt.tight_layout()
        
        logger.info(f"Successfully created index correlation heatmap for {len(indices)} indices")
        return fig
        
    except Exception as e:
        logger.error(f"Error creating index correlation heatmap: {e}")
        return None


def create_rolling_correlation_chart(symbol1: str, symbol2: str, period: str = "1y",
                                    window: int = 30, figsize: Tuple[int, int] = (12, 8)) -> Optional[plt.Figure]:
    """
    Create a rolling correlation chart between two symbols.
    
    Args:
        symbol1: First stock symbol
        symbol2: Second stock symbol
        period: Time period for analysis
        window: Rolling window size (days)
        figsize: Figure size (width, height)
        
    Returns:
        matplotlib Figure object, None if failed
        
    Example:
        >>> import pypsx
        >>> fig = pypsx.create_rolling_correlation_chart("OGDC", "PPL", period="1y", window=30)
        >>> plt.show()
    """
    try:
        logger.info(f"Creating rolling correlation chart for {symbol1} vs {symbol2} (period: {period})")
        
        # Get data for both symbols
        df1 = get_history(symbol1, period)
        df2 = get_history(symbol2, period)
        
        if df1 is None or df2 is None or df1.empty or df2.empty:
            logger.error(f"No data available for {symbol1} or {symbol2}")
            return None
        
        # Align the data
        df_combined = pd.DataFrame({
            symbol1: df1['CLOSE'],
            symbol2: df2['CLOSE']
        }).dropna()
        
        # Calculate returns
        returns = df_combined.pct_change(fill_method=None).dropna()
        
        # Calculate rolling correlation
        rolling_corr = returns[symbol1].rolling(window=window).corr(returns[symbol2])
        
        # Create chart
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        
        ax.plot(rolling_corr.index, rolling_corr.values, linewidth=2, color='blue')
        ax.axhline(y=0, color='red', linestyle='--', alpha=0.7)
        ax.axhline(y=0.5, color='green', linestyle='--', alpha=0.7, label='Strong Positive')
        ax.axhline(y=-0.5, color='orange', linestyle='--', alpha=0.7, label='Strong Negative')
        
        ax.set_title(f"Rolling Correlation: {symbol1} vs {symbol2} ({window}-day window)", 
                    fontweight='bold', fontsize=14)
        ax.set_ylabel("Correlation Coefficient")
        ax.set_ylim(-1, 1)
        ax.grid(True, alpha=0.3)
        ax.legend()
        
        # Format x-axis
        _format_x_axis(ax, period)
        
        plt.tight_layout()
        
        logger.info(f"Successfully created rolling correlation chart")
        return fig
        
    except Exception as e:
        logger.error(f"Error creating rolling correlation chart: {e}")
        return None