# PyPSX - Pakistan Stock Exchange Data Library (v3)

A clean, simple Python library to fetch and analyze Pakistan Stock Exchange (PSX) data from official DPS endpoints. Get real-time market data, historical prices, and powerful analysis tools all in one package.

## Installation

```bash
pip install pypsx
```

## Quick Start

### Basic Usage - Get Stock Information

```python
import pypsx

# Create a ticker object for any stock symbol
ticker = pypsx.PSXTicker("OGDC")  # or use pypsx.Ticker("OGDC")

# Get company information
info = ticker.info
print(f"Company: {info.get('Sector')}")
print(f"Current Price: {info.get('Current')}")

# Get comprehensive snapshot data (OHLCV, bid/ask, circuit breaker, ranges, ratios, etc.)
snapshot = ticker.snapshot
print(f"Open: {snapshot.get('REG', {}).get('Open')}")
print(f"High: {snapshot.get('REG', {}).get('High')}")
print(f"52-Week Range: {snapshot.get('REG', {}).get('52-WEEK RANGE ^')}")
print(f"P/E Ratio: {snapshot.get('REG', {}).get('P/E Ratio (TTM) **')}")

# Get market watch data for this stock
market_data = ticker.market_watch()
print(market_data)

# Get historical price data (1 year)
history = ticker.history(period="1y", interval="1d")
print(history.head())

# Get recent intraday trades (last 2 days)
intraday = ticker.intraday()
print(intraday.head())
```

### Market Data

```python
import pypsx

# Get full market watch (all stocks)
# Note: Different endpoints return different symbol counts
# Market Watch: ~486 symbols (includes all actively traded)
# Trading Board: ~479 symbols (order book data)
market_watch = pypsx.market_watch()
print(f"Total stocks in market watch: {len(market_watch)}")

# Get top performers
performers = pypsx.top_performers()
print("Top Gainers:")
print(performers["top_gainers"].head())

print("Top Decliners:")
print(performers["top_decliners"].head())

print("Most Active:")
print(performers["top_actives"].head())

# Get sector summary
sectors = pypsx.sector_summary()
print(sectors.head())

# Get all available stock symbols from trading board
# get_symbols() returns a list of clean symbols (without suffixes XD, NC, XR)
symbols_list = pypsx.get_symbols()
print(f"Total symbols: {len(symbols_list)}")

# To get DataFrame with Symbol, Name, Tag columns (Tag shows suffix if present)
from endpoints.trading_board import get_symbols as get_symbols_df
symbols_df = get_symbols_df()  # Returns DataFrame with Symbol, Name, Tag columns
print(f"Total symbols (DataFrame): {len(symbols_df)}")
print(symbols_df.head())
```

### Historical Data

```python
import pypsx

# Get 1 year of historical data for a stock
ticker = pypsx.PSXTicker("OGDC")
history = ticker.history(period="1y", interval="1d")

# Get full OHLCV data for specific date range
full_data = ticker.get_historical(start_date="2024-01-01", end_date="2024-12-31")
print(full_data.head())

# Download multiple symbols at once
df = pypsx.download(["OGDC", "PPL", "KEL"], period="6mo", interval="1d")
print(df.head())
```

### Indices and Sectors

```python
import pypsx

# Get all indices overview
indices = pypsx.get_indices()
print(indices.head())

# Get constituents of an index (e.g., KSE100)
kse100 = pypsx.index_constituents("KSE100")
print(f"KSE100 has {len(kse100)} constituents")
print(kse100.head())

# Get sector information
sectors = pypsx.sector_summary()
print(sectors.head())

# Get complete indices breakdown with statistics
indices_breakdown = pypsx.get_indices_breakdown()
print(f"Total indices: {indices_breakdown['total_indices']}")
print(f"Total unique symbols: {indices_breakdown['unique_symbols']}")
for idx, count, stats in indices_breakdown['indices'][:5]:
    print(f"{idx}: {count} symbols (Current: {stats.get('current', 'N/A')})")

# Get complete sector breakdown with company counts and averages
sector_breakdown = pypsx.get_sector_breakdown()
print(f"\nTotal sectors: {sector_breakdown['total_sectors']}")
print(f"Total companies: {sector_breakdown['total_companies']}")
for sector in sector_breakdown['sectors'][:5]:
    name = sector['name']
    count = sector['company_count']
    avg_price = sector['averages'].get('current', 'N/A')
    print(f"{name}: {count} companies (Avg Price: {avg_price})")
```

## Main Features

### 1. Stock Information (`PSXTicker`)

Create a ticker object for any stock symbol:

```python
ticker = pypsx.PSXTicker("OGDC")
```

**Available Properties:**
- `ticker.info` - Get company information (price, sector, volume, etc.)
- `ticker.snapshot` - Get comprehensive snapshot data from all tabs (OHLCV, bid/ask, circuit breaker, ranges, ratios, etc.)

**Available Methods:**
- `ticker.market_watch()` - Get current market watch row for this stock
- `ticker.sector()` - Get sector-level information
- `ticker.history(period="1y", interval="1d")` - Get historical data
- `ticker.intraday()` - Get intraday trades (last ~2 days)
- `ticker.get_historical(start_date, end_date)` - Get full OHLCV data for date range
- `ticker.dividends()` - Get dividend information (external source)
- `ticker.announcements()` - Get company announcements
- `ticker.orderbook()` - Get trading board data (bid/ask prices)

### 2. Market Data Functions

```python
# Full market watch
market_watch = pypsx.market_watch()

# Top performers
performers = pypsx.top_performers()  # Returns dict with "top_gainers", "top_decliners", "top_actives"

# Sector summary
sectors = pypsx.sector_summary()

# Trading board (order book)
orderbook = pypsx.trading_board()

# Get detailed quote data for a symbol (OHLCV, bid/ask, PE ratio, 52-week range, etc.)
quote = pypsx.get_quote("OGDC")
print(quote)

# Get quotes for multiple symbols
quotes = pypsx.get_quote_batch(["OGDC", "PPL", "KEL"])
for symbol, quote_df in quotes.items():
    if quote_df is not None:
        print(f"{symbol}: {quote_df}")

# Get company fundamentals (business description, financials, ratios, equity profile)
fundamentals = pypsx.get_company_fundamentals("OGDC")
print(fundamentals.head())
# Returns DataFrame with CATEGORY, METRIC, VALUE columns
# Categories include: Profile, Governance, Financials Annual, Financials Quarterly, Ratios, Equity Profile

# Get all symbols
symbols = pypsx.get_symbols()
```

### 3. Batch Downloads

```python
# Download multiple symbols at once
df = pypsx.download(["OGDC", "PPL", "KEL"], period="1y", interval="1d")
print(df.head())

# Get intraday data for multiple symbols
intraday_multi = pypsx.get_intraday_multiple(["OGDC", "PPL"])
print(intraday_multi.head())
```

## Charting and Visualization

PyPSX includes powerful charting capabilities to visualize stock data:

### Price Charts

```python
import matplotlib.pyplot as plt
from endpoints.charts import create_price_chart, create_technical_analysis_chart

# Create a candlestick chart
fig = create_price_chart("OGDC", period="1y", chart_type="candlestick")
plt.show()

# Create a line chart
fig = create_price_chart("PPL", period="6mo", chart_type="line")
plt.show()

# Create technical analysis chart with indicators
fig = create_technical_analysis_chart("OGDC", period="1y")
plt.show()
```

### Comparison Charts

```python
from endpoints.charts import create_multi_symbol_chart, create_index_comparison_chart

# Compare multiple stocks
fig = create_multi_symbol_chart(["OGDC", "PPL", "KEL"], period="1y")
plt.show()

# Compare indices
fig = create_index_comparison_chart(["KSE100", "KMI30"], period="1y")
plt.show()
```

### Correlation Analysis

```python
from endpoints.charts import create_correlation_heatmap

# Create correlation heatmap
fig = create_correlation_heatmap(["OGDC", "PPL", "KEL", "PSO"], period="1y")
plt.show()
```

**Available Chart Functions:**
- `create_price_chart(symbol, period, chart_type)` - Price charts (candlestick, line, OHLC)
- `create_technical_analysis_chart(symbol, period)` - Charts with technical indicators
- `create_multi_symbol_chart(symbols, period)` - Compare multiple stocks
- `create_index_comparison_chart(indices, period)` - Compare indices
- `create_correlation_heatmap(symbols, period)` - Correlation analysis

## Analysis and Statistics

PyPSX includes comprehensive analysis tools for stock data:

### Statistical Analysis

```python
from pypsx.analysis import returns, volatility, correlation, sharpe_ratio

ticker = pypsx.PSXTicker("OGDC")
df = ticker.history(period="1y")

# Calculate returns
rets = returns(df)
print(rets.head())

# Calculate volatility
vol = volatility(df)
print(vol.head())

# Calculate Sharpe ratio
sharpe = sharpe_ratio(df)
print(f"Sharpe Ratio: {sharpe:.3f}")
```

### Technical Indicators

```python
# Import indicators
from analysis import moving_average, rsi, macd, bollinger_bands, exponential_moving_average
# Or: from pypsx.analysis import moving_average, rsi, macd, bollinger_bands

ticker = pypsx.PSXTicker("OGDC")
df = ticker.history(period="1y")

# Moving averages
df['SMA20'] = moving_average(df, window=20)
df['EMA12'] = exponential_moving_average(df, window=12)

# RSI (supports both 'period' and 'window' parameter names)
df['RSI'] = rsi(df, period=14)

# MACD
macd_line, signal, histogram = macd(df)
df['MACD'] = macd_line
df['Signal'] = signal

# Bollinger Bands
ma, upper, lower = bollinger_bands(df, window=20)
df['BB_Upper'] = upper
df['BB_Lower'] = lower
```

### Automated Insights

```python
# Import insight functions
from analysis import interpret_stock, quick_analysis
# Or: from pypsx.analysis import interpret_stock, quick_analysis

ticker = pypsx.PSXTicker("OGDC")
df = ticker.history(period="1y")

# Generate comprehensive insights
insights = interpret_stock(df, "OGDC")
print("Insights:")
for insight in insights['insights']:
    print(f"  - {insight}")

# Quick analysis
analysis = quick_analysis(df, "OGDC")
print(f"Trading Signal: {analysis['trading_signal']}")
print(f"Sharpe Ratio: {analysis['key_metrics']['sharpe_ratio']:.3f}")
print(f"Max Drawdown: {analysis['key_metrics']['max_drawdown']:.3f}")
print(f"Total Return: {analysis['key_metrics']['total_return']:.2%}")

# Get trading signals directly
from analysis import generate_trading_signals
signals = generate_trading_signals(df, "OGDC")
print(f"Primary Signal: {signals['primary_signal']}")
print(f"Confidence: {signals['confidence']:.2%}")
```

**Available Analysis Functions:**

All analysis functions are available from the `analysis` package:

- **Statistics**: `returns()`, `volatility()`, `correlation()`, `beta()`, `correlation_matrix()`
- **Indicators**: `moving_average()`, `rsi()`, `macd()`, `bollinger_bands()`, `stochastic()`, `williams_r()`, `atr()`, `adx()`, `cci()`, `obv()`, `vwap()`
- **Performance**: `sharpe_ratio()`, `sortino_ratio()`, `calmar_ratio()`, `drawdown()`, `max_drawdown()`, `information_ratio()`, `treynor_ratio()`
- **Insights**: `interpret_stock()`, `quick_analysis()`, `portfolio_analysis()`, `market_sentiment_analysis()`, `generate_trading_signals()`

Import them like: `from analysis import sharpe_ratio, rsi` or `from pypsx.analysis import sharpe_ratio, rsi`

## Market Analysis and Breakdowns

### Indices Breakdown

Get a comprehensive breakdown of all PSX indices with constituent counts and statistics:

```python
import pypsx

# Get indices breakdown
breakdown = pypsx.get_indices_breakdown()

print(f"Total Indices: {breakdown['total_indices']}")
print(f"Total Symbols Analyzed: {breakdown['total_symbols_analyzed']}")
print(f"Unique Symbols: {breakdown['unique_symbols']}")

# Print breakdown
for idx, count, stats in breakdown['indices']:
    current = stats.get('current', 'N/A')
    change_pct = stats.get('percentage_change', 'N/A')
    print(f"{idx}: {count} symbols (Current: {current}, Change: {change_pct}%)")
```

**Output includes:**
- Total number of indices
- Constituent count for each index
- Index statistics (Current value, Change, Change %)
- Total symbols analyzed (with duplicates across indices)
- Unique symbols across all indices

**Example Output:**
```
PSX Indices Summary

**Total Indices in PSX: 18 unique indices**

Complete Breakdown:

1. *ALLSHR* - 549 symbols (Current: 98254.73, Change: 2590.07, Change %: 2.71%)
2. *KMIALLSHR* - 259 symbols (Current: 64179.60, Change: 1496.52, Change %: 2.39%)
3. *KSE100* - 100 symbols (Current: 161631.73, Change: 4898.86, Change %: 3.13%)
...

*Total symbols analyzed: 1217* across all indices.

*Total unique symbols: 549* across all indices.
```

### Sector Breakdown

Get a comprehensive breakdown of all PSX sectors with company counts and computed averages:

```python
import pypsx

# Get sector breakdown
breakdown = pypsx.get_sector_breakdown()

print(f"Total Sectors: {breakdown['total_sectors']}")
print(f"Total Companies: {breakdown['total_companies']}")

# Print breakdown
for sector in breakdown['sectors'][:10]:  # Top 10 sectors
    name = sector['name']
    count = sector['company_count']
    code = sector['code']
    avg_price = sector['averages'].get('current', 0)
    avg_change = sector['averages'].get('change_%', 0)
    advances = sector['advances']
    declines = sector['declines']
    
    print(f"{name} (Code: {code}):")
    print(f"  Companies: {count}")
    print(f"  Avg Price: {avg_price:.2f}")
    print(f"  Avg Change %: {avg_change:.2f}%")
    print(f"  Advances: {advances}, Declines: {declines}")
    print()
```

**Output includes:**
- Total number of sectors
- Company count per sector
- Average prices, volumes, changes per sector
- Sector-level statistics (advances, declines, turnover)
- Total companies across all sectors

**Example Output:**
```
PSX Sectorwise Summary

**Total Sectors in PSX: 37 unique sectors**

Complete Breakdown:

1. *TEXTILE SPINNING* (Code: 830) - 46 companies (Avg Price: 78.31, Avg Volume: 435833) [Advances: 24, Declines: 14, Turnover: 20048323]
2. *TEXTILE COMPOSITE* (Code: 829) - 39 companies (Avg Price: 192.50, Avg Volume: 254652) [Advances: 25, Declines: 8, Turnover: 9931432]
3. *INV. BANKS / INV. COS. / SECURITIES COS.* (Code: 813) - 35 companies (Avg Price: 756.90, Avg Volume: 2230213) [Advances: 30, Declines: 2, Turnover: 77778422]
...

*Total companies analyzed: 486* across all sectors.
```

## Advanced Usage

### Company Information

```python
import pypsx

ticker = pypsx.PSXTicker("OGDC")

# Get detailed quote data (includes OHLCV, bid/ask prices, PE ratio, 52-week range, VAR, etc.)
quote = pypsx.get_quote("OGDC")
print(quote)
# Output includes: OPEN, HIGH, LOW, VOLUME, BID_PRICE, ASK_PRICE, PE_RATIO, VAR, HAIRCUT, etc.

# Get quotes for multiple symbols
quotes = pypsx.get_quote_batch(["OGDC", "PPL", "KEL"])
for symbol, quote_df in quotes.items():
    if quote_df is not None:
        print(f"{symbol} Quote:")
        print(quote_df)

# Get company fundamentals (business description, financials, ratios, equity profile)
fundamentals = pypsx.get_company_fundamentals("OGDC")
print(fundamentals.head())

# Get comprehensive snapshot data from all tabs (most holistic approach)
snapshot = pypsx.get_snapshot("BOP")
print(snapshot['REG'])  # REG tab contains: OHLCV, circuit breaker, ranges, bid/ask, ratios, etc.
# Or use ticker.snapshot property:
ticker = pypsx.PSXTicker("BOP")
snap = ticker.snapshot
print(f"Open: {snap['REG']['Open']}")
print(f"52-Week Range: {snap['REG']['52-WEEK RANGE ^']}")

# Get announcements
announcements = ticker.announcements()
print(announcements.head())

# Get dividends
dividends = ticker.dividends()
print(dividends)

# Get order book
orderbook = ticker.orderbook()
print(orderbook)
```

### Custom Date Ranges

```python
ticker = pypsx.PSXTicker("OGDC")

# Get historical data for specific date range
historical = ticker.get_historical(
    start_date="2024-01-01",
    end_date="2024-12-31"
)
print(historical.head())
```

## Data Sources

PyPSX uses official Pakistan Stock Exchange DPS endpoints:
- Market Watch: `https://dps.psx.com.pk/market-watch`
- Sector Summary: `https://dps.psx.com.pk/sector-summary/sectorwise`
- Indices: `https://dps.psx.com.pk/indices/{INDEX}`
- Trading Board: `https://dps.psx.com.pk/trading-board/REG/main`
- Performers: `https://dps.psx.com.pk/performers`
- Timeseries: `https://dps.psx.com.pk/timeseries/int/{SYMBOL}`, `.../eod/{SYMBOL}`
- Historical OHLCV: `https://dps.psx.com.pk/historical`

## Examples

### Example 1: Find Top Volume Stocks

```python
import pypsx

# Get market watch
mw = pypsx.market_watch()

# Sort by volume and get top 5
top_volume = mw.nlargest(5, "Volume")[['Current', 'Change %', 'Volume']]
print(top_volume)
```

### Example 2: Compare Stock Performance

```python
import pypsx
from endpoints.charts import create_multi_symbol_chart
import matplotlib.pyplot as plt

# Compare three stocks
fig = create_multi_symbol_chart(["OGDC", "PPL", "KEL"], period="6mo")
plt.show()

# Save chart to file
fig = create_multi_symbol_chart(["OGDC", "PPL"], period="1y", save_path="comparison.png")
```

### Example 3: Technical Analysis

  ```python
import pypsx
from analysis import rsi, macd, bollinger_bands
  import pandas as pd

ticker = pypsx.PSXTicker("OGDC")
df = ticker.history(period="1y")

# Add technical indicators
df['RSI'] = rsi(df, period=14)
macd_line, signal, _ = macd(df)
df['MACD'] = macd_line
df['Signal'] = signal

ma, upper, lower = bollinger_bands(df)
df['BB_Upper'] = upper
df['BB_Lower'] = lower

# Simple trading signal (SMA crossover)
df['SMA20'] = df['CLOSE'].rolling(20).mean()
df['SMA50'] = df['CLOSE'].rolling(50).mean()
df['Signal'] = (df['SMA20'] > df['SMA50']).astype(int)

print(df[['CLOSE', 'RSI', 'MACD', 'Signal']].tail())
```

### Example 4: Portfolio Analysis

```python
import pypsx
from analysis import portfolio_analysis

# Create a portfolio
portfolio = {
    "OGDC": pypsx.PSXTicker("OGDC").history(period="1y"),
    "PPL": pypsx.PSXTicker("PPL").history(period="1y"),
    "PPL": pypsx.PSXTicker("PPL").history(period="1y")
}

# Analyze portfolio
analysis = portfolio_analysis(portfolio)
print(f"Portfolio Sharpe Ratio: {analysis['sharpe_ratio']:.3f}")
print(f"Portfolio Volatility: {analysis['volatility']:.3f}")
```

## API Reference

### PSXTicker Class

```python
ticker = pypsx.PSXTicker(symbol: str)

# Properties
ticker.info                    # Dict with company info
ticker.snapshot                # Dict with comprehensive snapshot data from all tabs
ticker.fast_info              # Quick metrics dict

# Methods
ticker.history(period="1y", interval="1d")    # Historical data
ticker.intraday()                             # Intraday trades
ticker.get_historical(start_date, end_date)   # Full OHLCV data
ticker.market_watch()                         # Market watch row
ticker.sector()                               # Sector information
ticker.orderbook()                            # Trading board data
ticker.dividends()                            # DataFrame with dividends
ticker.announcements()                        # DataFrame with announcements
```

### Market Functions

```python
pypsx.market_watch()           # Full market watch DataFrame
pypsx.top_performers()         # Dict: {top_gainers, top_decliners, top_actives}
pypsx.sector_summary()         # Sector summary DataFrame
pypsx.get_indices()            # Indices overview DataFrame
pypsx.get_indices_breakdown() # Complete indices breakdown with counts and stats
pypsx.get_sector_breakdown()  # Complete sector breakdown with company counts and averages
pypsx.get_symbols()            # List of all stock symbols
pypsx.trading_board()          # Trading board DataFrame

# Quote functions - Get detailed quote data (OHLCV, bid/ask, PE ratio, 52-week range, etc.)
pypsx.get_quote(symbol)                  # Get detailed quote for a single symbol
pypsx.get_quote_batch(symbols)           # Get quotes for multiple symbols (returns dict)

# Company fundamentals - Get comprehensive company data (business description, financials, ratios, etc.)
pypsx.get_company_fundamentals(symbol)   # Get company fundamentals (returns DataFrame)

# Snapshot - Get comprehensive snapshot data from all tabs (most holistic approach)
pypsx.get_snapshot(symbol)              # Get snapshot data from all tabs (returns dict with tab names as keys)
# Or use ticker.snapshot property for easier access
```

### Download Functions

```python
pypsx.download(symbols, period="1y", interval="1d")    # Batch download
pypsx.get_intraday_multiple(symbols)                   # Multiple intraday
pypsx.get_historical(symbol, start_date, end_date)    # Historical OHLCV
```

## Backward Compatibility

The library maintains backward compatibility:
- `pypsx.Ticker` is an alias for `pypsx.PSXTicker`
- `pypsx.PSXSymbol` is also available (legacy)

## Notes

- **Dividends**: PSX doesn't provide a dividends endpoint. The `dividends` property uses an external data source.
- **Data Availability**: Some data may not be available when the market is closed.
- **Symbol Names**: Use official PSX symbols (e.g., "OGDC", "PPL", "KEL").

## License

MIT License
