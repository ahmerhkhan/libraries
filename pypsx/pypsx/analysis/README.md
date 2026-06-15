# PyPSX Analysis Module

The PyPSX Analysis Module provides comprehensive financial analysis tools for Pakistan Stock Exchange data, including statistical functions, technical indicators, performance metrics, and automated insights generation.

## 📦 Module Structure

```
pypsx/
 ┣━━ core/
 ┣━━ endpoints/
 ┣━━ format/
 ┣━━ analysis/
 ┃    ┣━━ __init__.py
 ┃    ┣━━ stats.py          # Core statistical functions
 ┃    ┣━━ indicators.py      # Technical analysis indicators
 ┃    ┣━━ performance.py     # Financial performance metrics
 ┃    ┗━━ insights.py        # Automated insight engine
```

## 🚀 Quick Start

```python
import pypsx

# Get stock data
ticker = pypsx.PSXTicker("OGDC")
df = ticker.history(period="1y")

# Generate comprehensive insights
insights = pypsx.interpret_stock(df, "OGDC")
print(insights['insights'])

# Calculate key metrics
sharpe = pypsx.sharpe_ratio(df)
volatility = pypsx.volatility(df)
returns = pypsx.returns(df)

# Technical indicators
ma, upper, lower = pypsx.bollinger_bands(df)
rsi_values = pypsx.rsi(df)
macd_line, signal_line, histogram = pypsx.macd(df)
```

## 📊 Core Statistical Functions (`stats.py`)

### Returns and Volatility
- `returns(df, column='Close')` - Calculate daily percentage returns
- `volatility(df, window=30, column='Close')` - Calculate rolling volatility
- `correlation(df1, df2, column='Close')` - Calculate correlation between stocks
- `correlation_matrix(df_dict, column='Close')` - Calculate correlation matrix

### Risk Metrics
- `var(df, confidence_level=0.05)` - Value at Risk (VaR)
- `cvar(df, confidence_level=0.05)` - Conditional Value at Risk (CVaR)
- `beta(df_stock, df_market)` - Beta coefficient (systematic risk)

### Distribution Analysis
- `skewness(df, column='Close')` - Returns skewness
- `kurtosis(df, column='Close')` - Returns kurtosis
- `autocorrelation(df, lag=1)` - Autocorrelation analysis

## 📈 Technical Indicators (`indicators.py`)

### Moving Averages
- `moving_average(df, window=20)` - Simple Moving Average
- `exponential_moving_average(df, window=20)` - Exponential Moving Average

### Momentum Indicators
- `rsi(df, window=14)` - Relative Strength Index
- `macd(df, fast=12, slow=26, signal=9)` - MACD (Moving Average Convergence Divergence)
- `stochastic(df, k_window=14, d_window=3)` - Stochastic Oscillator
- `williams_r(df, window=14)` - Williams %R

### Volatility Indicators
- `bollinger_bands(df, window=20, num_std=2.0)` - Bollinger Bands
- `atr(df, window=14)` - Average True Range
- `adx(df, window=14)` - Average Directional Index

### Volume Indicators
- `obv(df)` - On-Balance Volume
- `vwap(df)` - Volume Weighted Average Price

### Other Indicators
- `cci(df, window=20)` - Commodity Channel Index

## 💰 Performance Metrics (`performance.py`)

### Risk-Adjusted Returns
- `sharpe_ratio(df, risk_free_rate=0.08)` - Sharpe ratio
- `sortino_ratio(df, risk_free_rate=0.08)` - Sortino ratio
- `calmar_ratio(df)` - Calmar ratio (return/max drawdown)

### Return Analysis
- `cumulative_returns(df)` - Cumulative returns series
- `annualized_return(df)` - Annualized return
- `annualized_volatility(df)` - Annualized volatility

### Drawdown Analysis
- `drawdown(df)` - Drawdown series
- `max_drawdown(df)` - Maximum drawdown
- `drawdown_duration(df)` - Drawdown duration analysis

### Portfolio Metrics
- `information_ratio(df_stock, df_benchmark)` - Information ratio
- `treynor_ratio(df_stock, df_market)` - Treynor ratio
- `jensen_alpha(df_stock, df_market)` - Jensen's alpha (CAPM)

### Performance Statistics
- `win_rate(df)` - Percentage of positive return days
- `profit_loss_ratio(df)` - Average gain / average loss
- `recovery_factor(df)` - Total return / maximum drawdown
- `performance_summary(df)` - Comprehensive performance metrics

## 🔮 Automated Insight Engine (`insights.py`)

### Single Stock Analysis
- `interpret_stock(df, symbol=None)` - Generate comprehensive insights
- `detect_patterns(df, symbol=None)` - Detect technical patterns
- `generate_trading_signals(df, symbol=None)` - Generate trading signals

### Portfolio Analysis
- `interpret_portfolio(portfolio_data)` - Portfolio-level insights
- `market_sentiment_analysis(market_data)` - Market sentiment analysis

### Convenience Functions
- `quick_analysis(df, symbol=None)` - Quick comprehensive analysis
- `portfolio_analysis(portfolio_data)` - Complete portfolio analysis

## 📋 Usage Examples

### Basic Analysis
```python
import pypsx

# Get historical data
ticker = pypsx.PSXTicker("OGDC")
df = ticker.history(period="1y")

# Calculate returns and volatility
returns = pypsx.returns(df)
vol = pypsx.volatility(df, window=30)

# Performance metrics
sharpe = pypsx.sharpe_ratio(df)
max_dd = pypsx.max_drawdown(df)
win_rate = pypsx.win_rate(df)

print(f"Sharpe Ratio: {sharpe:.3f}")
print(f"Max Drawdown: {max_dd:.2%}")
print(f"Win Rate: {win_rate:.2%}")
```

### Technical Analysis
```python
# Moving averages
ma_20 = pypsx.moving_average(df, window=20)
ema_20 = pypsx.exponential_moving_average(df, window=20)

# Bollinger Bands
ma, upper, lower = pypsx.bollinger_bands(df, window=20)

# RSI
rsi_14 = pypsx.rsi(df, window=14)

# MACD
macd_line, signal_line, histogram = pypsx.macd(df)

print(f"Current RSI: {rsi_14.iloc[-1]:.2f}")
print(f"Price vs Upper BB: {df['Close'].iloc[-1] / upper.iloc[-1]:.2%}")
```

### Automated Insights
```python
# Generate comprehensive insights
insights = pypsx.interpret_stock(df, "OGDC")

print("Key Metrics:")
print(f"  Volatility: {insights['volatility']:.4f}")
print(f"  Total Return: {insights['total_return']:.2%}")
print(f"  Sharpe Ratio: {insights['sharpe_ratio']:.3f}")
print(f"  Max Drawdown: {insights['max_drawdown']:.2%}")

print("\nAutomated Insights:")
for insight in insights['insights']:
    print(f"  • {insight}")

# Detect patterns
patterns = pypsx.detect_patterns(df, "OGDC")
print("\nDetected Patterns:")
for pattern in patterns['patterns']:
    print(f"  • {pattern}")

# Trading signals
signals = pypsx.generate_trading_signals(df, "OGDC")
print(f"\nTrading Signal: {signals['primary_signal']}")
print(f"Confidence: {signals['confidence']:.2%}")
```

### Portfolio Analysis
```python
# Create portfolio data
portfolio = {
    "OGDC": pypsx.PSXTicker("OGDC").history(period="1y"),
    "PPL": pypsx.PSXTicker("PPL").history(period="1y"),
    "KEL": pypsx.PSXTicker("KEL").history(period="1y")
}

# Portfolio insights
portfolio_insights = pypsx.interpret_portfolio(portfolio)
print("Portfolio Insights:")
for insight in portfolio_insights['portfolio_insights']:
    print(f"  • {insight}")

# Correlation analysis
corr_matrix = pypsx.correlation_matrix(portfolio)
print("\nCorrelation Matrix:")
print(corr_matrix.round(3))

# Market sentiment
sentiment = pypsx.market_sentiment_analysis(portfolio)
print(f"\nMarket Sentiment: {sentiment['overall_sentiment']}")
print(f"Sentiment Strength: {sentiment['sentiment_strength']}")
```

### Quick Analysis
```python
# One-line comprehensive analysis
analysis = pypsx.quick_analysis(df, "OGDC")

print(f"Trading Signal: {analysis['trading_signal']}")
print(f"Confidence: {analysis['signal_confidence']:.2%}")

print("\nKey Metrics:")
for metric, value in analysis['key_metrics'].items():
    print(f"  {metric}: {value:.4f}")

print("\nTop Insights:")
for insight in analysis['insights'][:3]:
    print(f"  • {insight}")
```

## 🎯 Key Features

### ✅ Comprehensive Coverage
- **Statistical Functions**: Returns, volatility, correlation, risk metrics
- **Technical Indicators**: RSI, MACD, Bollinger Bands, Stochastic, etc.
- **Performance Metrics**: Sharpe ratio, drawdown analysis, risk-adjusted returns
- **Automated Insights**: Natural language interpretations and pattern detection

### ✅ Flexible Input Support
- **Single Stock**: DataFrame with OHLCV data
- **Multi-Stock**: Dictionary of symbol → DataFrame
- **Portfolio Analysis**: Comprehensive portfolio-level insights

### ✅ Production Ready
- **Vectorized Operations**: Efficient pandas-based calculations
- **Error Handling**: Robust error handling and validation
- **Documentation**: Comprehensive docstrings and examples
- **No Heavy Dependencies**: Lightweight implementation without ta-lib

### ✅ Integration Ready
- **Seamless Integration**: Works with existing PyPSX data functions
- **JSON Export**: Results ready for API responses
- **Extensible**: Easy to add new indicators and metrics

## 🔧 Technical Details

### Dependencies
- `pandas` - Data manipulation and analysis
- `numpy` - Numerical computations
- Standard library modules only

### Performance
- All functions use vectorized pandas operations
- Efficient memory usage with rolling calculations
- Optimized for large datasets

### Error Handling
- Graceful handling of insufficient data
- Validation of input parameters
- Meaningful error messages and fallbacks

## 📚 Function Reference

### Statistical Functions
| Function | Description | Parameters |
|----------|-------------|------------|
| `returns()` | Daily percentage returns | `df`, `column='Close'` |
| `volatility()` | Rolling volatility | `df`, `window=30`, `column='Close'` |
| `correlation()` | Stock correlation | `df1`, `df2`, `column='Close'` |
| `beta()` | Beta coefficient | `df_stock`, `df_market`, `column='Close'` |
| `var()` | Value at Risk | `df`, `confidence_level=0.05` |
| `cvar()` | Conditional VaR | `df`, `confidence_level=0.05` |

### Technical Indicators
| Function | Description | Parameters |
|----------|-------------|------------|
| `moving_average()` | Simple Moving Average | `df`, `window=20`, `column='Close'` |
| `exponential_moving_average()` | EMA | `df`, `window=20`, `column='Close'` |
| `bollinger_bands()` | Bollinger Bands | `df`, `window=20`, `num_std=2.0` |
| `rsi()` | Relative Strength Index | `df`, `window=14`, `column='Close'` |
| `macd()` | MACD | `df`, `fast=12`, `slow=26`, `signal=9` |
| `stochastic()` | Stochastic Oscillator | `df`, `k_window=14`, `d_window=3` |

### Performance Metrics
| Function | Description | Parameters |
|----------|-------------|------------|
| `sharpe_ratio()` | Sharpe ratio | `df`, `risk_free_rate=0.08` |
| `sortino_ratio()` | Sortino ratio | `df`, `risk_free_rate=0.08` |
| `max_drawdown()` | Maximum drawdown | `df`, `column='Close'` |
| `win_rate()` | Win rate percentage | `df`, `column='Close'` |
| `performance_summary()` | Complete metrics | `df`, `risk_free_rate=0.08` |

### Insight Engine
| Function | Description | Parameters |
|----------|-------------|------------|
| `interpret_stock()` | Stock insights | `df`, `symbol=None` |
| `detect_patterns()` | Pattern detection | `df`, `symbol=None` |
| `generate_trading_signals()` | Trading signals | `df`, `symbol=None` |
| `interpret_portfolio()` | Portfolio analysis | `portfolio_data` |
| `quick_analysis()` | Quick analysis | `df`, `symbol=None` |

## 🚀 Getting Started

1. **Install PyPSX** (if not already installed)
2. **Import the analysis module**:
   ```python
   import pypsx
   # or
   from pypsx.analysis import interpret_stock, sharpe_ratio
   ```
3. **Get your data**:
   ```python
   ticker = pypsx.PSXTicker("OGDC")
   df = ticker.history(period="1y")
   ```
4. **Start analyzing**:
   ```python
   insights = pypsx.interpret_stock(df, "OGDC")
   ```

The analysis module is now fully integrated and ready to use with your PyPSX data!
