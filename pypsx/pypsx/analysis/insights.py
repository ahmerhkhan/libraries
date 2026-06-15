"""
Automated Insight Engine for PyPSX Analysis Module

This module provides intelligent analysis and natural language insights
from stock data. It automatically interprets technical patterns, performance
metrics, and market behavior to generate actionable insights.
"""

import pandas as pd
import numpy as np
from typing import Union, Dict, List, Optional, Tuple
from .stats import returns, volatility, correlation, beta, skewness, kurtosis, _get_price_column
from .indicators import rsi, macd, bollinger_bands, moving_average, exponential_moving_average
from .performance import (
    sharpe_ratio, sortino_ratio, calmar_ratio, cumulative_returns, 
    max_drawdown, win_rate, profit_loss_ratio, annualized_return, 
    annualized_volatility, performance_summary
)


def interpret_stock(df: pd.DataFrame, 
                   symbol: Optional[str] = None,
                   risk_free_rate: float = 0.08) -> Dict:
    """
    Generate comprehensive insights for a single stock.
    
    Args:
        df: Stock DataFrame with OHLCV data
        symbol: Stock symbol (optional)
        risk_free_rate: Risk-free rate for calculations (default: 0.08)
    
    Returns:
        Dictionary containing insights and metrics
        
    Example:
        >>> import pypsx
        >>> ticker = pypsx.PSXTicker("OGDC")
        >>> df = ticker.history(period="1y")
        >>> insights = interpret_stock(df, "OGDC")
        >>> print(insights['insights'])
    """
    if df is None or df.empty:
        return {
            "symbol": symbol,
            "error": "No data available",
            "insights": ["Insufficient data for analysis"]
        }
    
    if len(df) < 5:
        return {
            "symbol": symbol,
            "error": "Insufficient data points",
            "insights": [f"Need at least 5 data points, got {len(df)}"]
        }
    
    try:
        # Calculate key metrics with error handling
        vol = volatility(df).mean() if len(df) >= 2 else 0
        ret = cumulative_returns(df).iloc[-1] if len(cumulative_returns(df)) > 0 else 0
        sharpe = sharpe_ratio(df, risk_free_rate) if len(df) >= 2 else 0
        sortino = sortino_ratio(df, risk_free_rate) if len(df) >= 2 else 0
        max_dd = max_drawdown(df) if len(df) >= 2 else 0
        win_rate_val = win_rate(df) if len(df) >= 2 else 0
        ann_ret = annualized_return(df) if len(df) >= 2 else 0
        ann_vol = annualized_volatility(df) if len(df) >= 2 else 0
        
        # Technical indicators with error handling
        try:
            rsi_series = rsi(df)
            rsi_val = rsi_series.iloc[-1] if len(rsi_series) > 0 else 50
        except Exception:
            rsi_val = 50
            
        try:
            macd_line, signal_line, histogram = macd(df)
            macd_val = macd_line.iloc[-1] if len(macd_line) > 0 else 0
            signal_val = signal_line.iloc[-1] if len(signal_line) > 0 else 0
        except Exception:
            macd_val = 0
            signal_val = 0
            histogram = pd.Series([0])
        
        # Bollinger Bands
        try:
            ma, upper_bb, lower_bb = bollinger_bands(df)
            price_col = _get_price_column(df)
            current_price = df[price_col].iloc[-1]
            if len(upper_bb) > 0 and len(lower_bb) > 0:
                bb_position = (current_price - lower_bb.iloc[-1]) / (upper_bb.iloc[-1] - lower_bb.iloc[-1])
            else:
                bb_position = 0.5
        except Exception:
            bb_position = 0.5
        
        # Generate insights
        insights = []
        
        # Volatility insights
        if vol > 0.03:
            insights.append("High volatility — price fluctuates significantly.")
        elif vol < 0.015:
            insights.append("Low volatility — relatively stable price movement.")
        else:
            insights.append("Moderate volatility — balanced price movement.")
        
        # Risk-adjusted performance
        if sharpe < 0:
            insights.append("Negative Sharpe ratio — poor risk-adjusted returns.")
        elif sharpe > 1:
            insights.append("Strong Sharpe ratio — outperforming on risk-adjusted basis.")
        elif sharpe > 0.5:
            insights.append("Good Sharpe ratio — decent risk-adjusted performance.")
        else:
            insights.append("Weak Sharpe ratio — underperforming on risk-adjusted basis.")
        
        # Return performance
        if ret > 0.2:
            insights.append("Strong uptrend — over 20% cumulative gain during period.")
        elif ret > 0.1:
            insights.append("Moderate uptrend — positive performance observed.")
        elif ret < -0.1:
            insights.append("Significant downtrend — substantial losses during period.")
        elif ret < -0.05:
            insights.append("Mild downtrend — slight negative performance.")
        else:
            insights.append("Sideways movement — minimal price change.")
        
        # Drawdown analysis
        if max_dd < -0.2:
            insights.append("High drawdown risk — significant peak-to-trough losses.")
        elif max_dd < -0.1:
            insights.append("Moderate drawdown risk — notable peak-to-trough losses.")
        else:
            insights.append("Low drawdown risk — relatively stable performance.")
        
        # Win rate analysis
        if win_rate_val > 0.6:
            insights.append("High win rate — majority of trading days are positive.")
        elif win_rate_val < 0.4:
            insights.append("Low win rate — majority of trading days are negative.")
        else:
            insights.append("Balanced win rate — mixed daily performance.")
        
        # RSI analysis
        if rsi_val > 70:
            insights.append("Overbought conditions — RSI suggests potential reversal.")
        elif rsi_val < 30:
            insights.append("Oversold conditions — RSI suggests potential bounce.")
        elif rsi_val > 50:
            insights.append("Bullish momentum — RSI indicates upward pressure.")
        else:
            insights.append("Bearish momentum — RSI indicates downward pressure.")
        
        # MACD analysis
        if macd_val > signal_val and histogram.iloc[-1] > 0:
            insights.append("Bullish MACD signal — momentum turning positive.")
        elif macd_val < signal_val and histogram.iloc[-1] < 0:
            insights.append("Bearish MACD signal — momentum turning negative.")
        
        # Bollinger Bands analysis
        if bb_position > 0.8:
            insights.append("Near upper Bollinger Band — potential resistance level.")
        elif bb_position < 0.2:
            insights.append("Near lower Bollinger Band — potential support level.")
        
        # Sortino ratio analysis
        if sortino > 1:
            insights.append("Excellent downside risk management — strong Sortino ratio.")
        elif sortino > 0.5:
            insights.append("Good downside risk management — decent Sortino ratio.")
        
        return {
            "symbol": symbol,
            "volatility": vol,
            "total_return": ret,
            "annualized_return": ann_ret,
            "annualized_volatility": ann_vol,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown": max_dd,
            "win_rate": win_rate_val,
            "rsi": rsi_val,
            "macd": macd_val,
            "macd_signal": signal_val,
            "bollinger_position": bb_position,
            "insights": insights
        }
        
    except Exception as e:
        return {
            "symbol": symbol,
            "error": str(e),
            "insights": ["Error in analysis - insufficient data or calculation error"]
        }


def interpret_portfolio(portfolio_data: Dict[str, pd.DataFrame], 
                       risk_free_rate: float = 0.08) -> Dict:
    """
    Generate insights for a portfolio of stocks.
    
    Args:
        portfolio_data: Dictionary of symbol -> DataFrame
        risk_free_rate: Risk-free rate for calculations (default: 0.08)
    
    Returns:
        Dictionary containing portfolio insights and individual stock analysis
        
    Example:
        >>> portfolio = {
        ...     "OGDC": pypsx.PSXTicker("OGDC").history(period="1y"),
        ...     "PPL": pypsx.PSXTicker("PPL").history(period="1y"),
        ...     "KEL": pypsx.PSXTicker("KEL").history(period="1y")
        ... }
        >>> insights = interpret_portfolio(portfolio)
        >>> print(insights['portfolio_insights'])
    """
    if not portfolio_data:
        return {"error": "No portfolio data provided"}
    
    # Individual stock analysis
    individual_insights = {}
    for symbol, df in portfolio_data.items():
        individual_insights[symbol] = interpret_stock(df, symbol, risk_free_rate)
    
    # Portfolio-level analysis
    portfolio_insights = []
    
    # Calculate portfolio metrics
    returns_data = {}
    volatilities = {}
    sharpe_ratios = {}
    
    for symbol, df in portfolio_data.items():
        if df is not None and not df.empty:
            returns_data[symbol] = returns(df)
            volatilities[symbol] = volatility(df).mean()
            sharpe_ratios[symbol] = sharpe_ratio(df, risk_free_rate)
    
    if not returns_data:
        return {
            "individual_insights": individual_insights,
            "portfolio_insights": ["No valid data for portfolio analysis"],
            "error": "Insufficient data for portfolio analysis"
        }
    
    # Portfolio diversification analysis
    if len(returns_data) > 1:
        # Calculate average correlation
        symbols = list(returns_data.keys())
        correlations = []
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                corr = correlation(portfolio_data[symbols[i]], portfolio_data[symbols[j]])
                if not np.isnan(corr):
                    correlations.append(abs(corr))
        
        avg_correlation = np.mean(correlations) if correlations else 0
        
        if avg_correlation < 0.3:
            portfolio_insights.append("Well-diversified portfolio — low correlation between holdings.")
        elif avg_correlation > 0.7:
            portfolio_insights.append("Concentrated portfolio — high correlation between holdings.")
        else:
            portfolio_insights.append("Moderately diversified portfolio — balanced correlation structure.")
    
    # Performance comparison
    best_performer = max(sharpe_ratios.items(), key=lambda x: x[1] if not np.isnan(x[1]) else -np.inf)
    worst_performer = min(sharpe_ratios.items(), key=lambda x: x[1] if not np.isnan(x[1]) else np.inf)
    
    if best_performer[1] > 1:
        portfolio_insights.append(f"Best performer: {best_performer[0]} with strong risk-adjusted returns.")
    elif best_performer[1] > 0:
        portfolio_insights.append(f"Best performer: {best_performer[0]} with positive risk-adjusted returns.")
    
    if worst_performer[1] < 0:
        portfolio_insights.append(f"Underperformer: {worst_performer[0]} showing negative risk-adjusted returns.")
    
    # Risk analysis
    avg_volatility = np.mean(list(volatilities.values()))
    if avg_volatility > 0.03:
        portfolio_insights.append("High portfolio volatility — consider risk management strategies.")
    elif avg_volatility < 0.015:
        portfolio_insights.append("Low portfolio volatility — conservative risk profile.")
    
    return {
        "individual_insights": individual_insights,
        "portfolio_insights": portfolio_insights,
        "portfolio_metrics": {
            "avg_correlation": avg_correlation if len(returns_data) > 1 else 0,
            "avg_volatility": avg_volatility,
            "best_performer": best_performer[0] if best_performer[1] > -np.inf else None,
            "worst_performer": worst_performer[0] if worst_performer[1] < np.inf else None
        }
    }


def detect_patterns(df: pd.DataFrame, 
                   symbol: Optional[str] = None) -> Dict:
    """
    Detect common technical patterns in stock data.
    
    Args:
        df: Stock DataFrame with OHLCV data
        symbol: Stock symbol (optional)
    
    Returns:
        Dictionary containing detected patterns
        
    Example:
        >>> patterns = detect_patterns(df, "OGDC")
        >>> print(patterns['patterns'])
    """
    if df is None or df.empty or len(df) < 5:
        return {
            "symbol": symbol,
            "patterns": ["Insufficient data for pattern detection"],
            "error": f"Need at least 5 data points for pattern analysis, got {len(df) if df is not None else 0}"
        }
    
    patterns = []
    
    try:
        # Get recent data for pattern detection
        recent_data = df.tail(min(20, len(df)))
        price_col = _get_price_column(df)
        current_price = recent_data[price_col].iloc[-1]
        
        # Moving average patterns
        ma_20 = moving_average(df, 20)
        ma_50 = moving_average(df, 50) if len(df) >= 50 else None
        
        if len(ma_20) > 0 and len(ma_50) > 0:
            if ma_20.iloc[-1] > ma_50.iloc[-1] and ma_20.iloc[-2] <= ma_50.iloc[-2]:
                patterns.append("Golden Cross — 20-day MA crossed above 50-day MA (bullish signal)")
            elif ma_20.iloc[-1] < ma_50.iloc[-1] and ma_20.iloc[-2] >= ma_50.iloc[-2]:
                patterns.append("Death Cross — 20-day MA crossed below 50-day MA (bearish signal)")
        
        # Bollinger Bands patterns
        ma, upper_bb, lower_bb = bollinger_bands(df)
        if len(upper_bb) > 0 and len(lower_bb) > 0:
            bb_width = (upper_bb.iloc[-1] - lower_bb.iloc[-1]) / ma.iloc[-1]
            if bb_width < 0.1:
                patterns.append("Bollinger Squeeze — low volatility, potential breakout ahead")
            elif current_price > upper_bb.iloc[-1]:
                patterns.append("Above Upper Bollinger Band — potential overbought condition")
            elif current_price < lower_bb.iloc[-1]:
                patterns.append("Below Lower Bollinger Band — potential oversold condition")
        
        # RSI patterns
        rsi_val = rsi(df)
        if len(rsi_val) > 0:
            current_rsi = rsi_val.iloc[-1]
            if current_rsi > 80:
                patterns.append("Extreme Overbought — RSI above 80, strong reversal risk")
            elif current_rsi < 20:
                patterns.append("Extreme Oversold — RSI below 20, strong bounce potential")
            elif current_rsi > 70:
                patterns.append("Overbought Territory — RSI above 70, caution advised")
            elif current_rsi < 30:
                patterns.append("Oversold Territory — RSI below 30, potential buying opportunity")
        
        # MACD patterns
        macd_line, signal_line, histogram = macd(df)
        if len(macd_line) > 0 and len(signal_line) > 0:
            if macd_line.iloc[-1] > signal_line.iloc[-1] and macd_line.iloc[-2] <= signal_line.iloc[-2]:
                patterns.append("MACD Bullish Crossover — momentum turning positive")
            elif macd_line.iloc[-1] < signal_line.iloc[-1] and macd_line.iloc[-2] >= signal_line.iloc[-2]:
                patterns.append("MACD Bearish Crossover — momentum turning negative")
        
        # Volume patterns (handle both 'VOLUME' and 'Volume')
        vol_col = 'VOLUME' if 'VOLUME' in df.columns else ('Volume' if 'Volume' in df.columns else None)
        if vol_col is not None:
            avg_volume = df[vol_col].rolling(20).mean()
            if len(avg_volume) > 0:
                current_volume = df[vol_col].iloc[-1]
                avg_vol = avg_volume.iloc[-1]
                if pd.notna(current_volume) and pd.notna(avg_vol) and avg_vol > 0:
                    if current_volume > avg_vol * 1.5:
                        patterns.append("High Volume — unusual trading activity detected")
                    elif current_volume < avg_vol * 0.5:
                        patterns.append("Low Volume — reduced trading interest")
        
        # Price momentum patterns
        returns_5d = returns(df).tail(5)
        if len(returns_5d) >= 5:
            if all(returns_5d > 0):
                patterns.append("5-Day Winning Streak — consecutive positive days")
            elif all(returns_5d < 0):
                patterns.append("5-Day Losing Streak — consecutive negative days")
        
        if not patterns:
            patterns.append("No significant patterns detected in current data")
        
        return {
            "symbol": symbol,
            "patterns": patterns,
            "analysis_period": f"Last {len(recent_data)} days"
        }
        
    except Exception as e:
        return {
            "symbol": symbol,
            "patterns": ["Error in pattern detection"],
            "error": str(e)
        }


def generate_trading_signals(df: pd.DataFrame, 
                           symbol: Optional[str] = None) -> Dict:
    """
    Generate trading signals based on technical analysis.
    
    Args:
        df: Stock DataFrame with OHLCV data
        symbol: Stock symbol (optional)
    
    Returns:
        Dictionary containing trading signals and confidence levels
        
    Example:
        >>> signals = generate_trading_signals(df, "OGDC")
        >>> print(f"Signal: {signals['primary_signal']}")
        >>> print(f"Confidence: {signals['confidence']}")
    """
    if df is None or df.empty or len(df) < 5:
        return {
            "symbol": symbol,
            "primary_signal": "HOLD",
            "confidence": 0,
            "signals": ["Insufficient data for signal generation"],
            "error": f"Need at least 5 data points for signal analysis, got {len(df) if df is not None else 0}"
        }
    
    signals = []
    bullish_signals = 0
    bearish_signals = 0
    
    try:
        # RSI signals
        rsi_val = rsi(df)
        if len(rsi_val) > 0:
            current_rsi = rsi_val.iloc[-1]
            if current_rsi < 30:
                signals.append("RSI Oversold — BUY signal")
                bullish_signals += 1
            elif current_rsi > 70:
                signals.append("RSI Overbought — SELL signal")
                bearish_signals += 1
        
        # MACD signals
        macd_line, signal_line, histogram = macd(df)
        if len(macd_line) > 0 and len(signal_line) > 0:
            if macd_line.iloc[-1] > signal_line.iloc[-1] and histogram.iloc[-1] > 0:
                signals.append("MACD Bullish — BUY signal")
                bullish_signals += 1
            elif macd_line.iloc[-1] < signal_line.iloc[-1] and histogram.iloc[-1] < 0:
                signals.append("MACD Bearish — SELL signal")
                bearish_signals += 1
        
        # Moving Average signals
        ma_20 = moving_average(df, 20)
        if len(ma_20) > 0:
            price_col = _get_price_column(df)
            current_price = df[price_col].iloc[-1]
            if current_price > ma_20.iloc[-1]:
                signals.append("Price above 20-day MA — BUY signal")
                bullish_signals += 1
            else:
                signals.append("Price below 20-day MA — SELL signal")
                bearish_signals += 1
        
        # Bollinger Bands signals
        ma, upper_bb, lower_bb = bollinger_bands(df)
        if len(upper_bb) > 0 and len(lower_bb) > 0:
            price_col = _get_price_column(df)
            current_price = df[price_col].iloc[-1]
            if current_price < lower_bb.iloc[-1]:
                signals.append("Price below Lower BB — BUY signal")
                bullish_signals += 1
            elif current_price > upper_bb.iloc[-1]:
                signals.append("Price above Upper BB — SELL signal")
                bearish_signals += 1
        
        # Determine primary signal
        # Count all signals, not just bullish/bearish
        total_signals = bullish_signals + bearish_signals
        max_signals = 4  # Maximum possible signals (RSI, MACD, MA, BB)
        
        if total_signals == 0:
            primary_signal = "HOLD"
            confidence = 0.0
        elif bullish_signals > bearish_signals:
            primary_signal = "BUY"
            # Confidence based on signal strength (bullish/total possible)
            confidence = max(bullish_signals / max_signals, bullish_signals / total_signals if total_signals > 0 else 0)
        elif bearish_signals > bullish_signals:
            primary_signal = "SELL"
            # Confidence based on signal strength (bearish/total possible)
            confidence = max(bearish_signals / max_signals, bearish_signals / total_signals if total_signals > 0 else 0)
        else:
            primary_signal = "HOLD"
            # If equal, confidence is lower but not zero
            confidence = min(bullish_signals, bearish_signals) / max_signals if max(bullish_signals, bearish_signals) > 0 else 0.0
        
        # Ensure confidence is between 0 and 1
        confidence = max(0.0, min(1.0, confidence))
        
        return {
            "symbol": symbol,
            "primary_signal": primary_signal,
            "confidence": confidence,
            "bullish_signals": bullish_signals,
            "bearish_signals": bearish_signals,
            "signals": signals
        }
        
    except Exception as e:
        return {
            "symbol": symbol,
            "primary_signal": "HOLD",
            "confidence": 0,
            "signals": ["Error in signal generation"],
            "error": str(e)
        }


def market_sentiment_analysis(market_data: Dict[str, pd.DataFrame]) -> Dict:
    """
    Analyze overall market sentiment from multiple stocks.
    
    Args:
        market_data: Dictionary of symbol -> DataFrame
    
    Returns:
        Dictionary containing market sentiment analysis
        
    Example:
        >>> market_data = {
        ...     "OGDC": pypsx.PSXTicker("OGDC").history(period="1m"),
        ...     "PPL": pypsx.PSXTicker("PPL").history(period="1m"),
        ...     "KEL": pypsx.PSXTicker("KEL").history(period="1m")
        ... }
        >>> sentiment = market_sentiment_analysis(market_data)
        >>> print(f"Market sentiment: {sentiment['overall_sentiment']}")
    """
    if not market_data:
        return {"error": "No market data provided"}
    
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    
    individual_sentiments = {}
    
    for symbol, df in market_data.items():
        if df is None or df.empty:
            continue
        
        try:
            # Generate signals for each stock
            signals = generate_trading_signals(df, symbol)
            primary_signal = signals.get('primary_signal', 'HOLD')
            
            individual_sentiments[symbol] = {
                'signal': primary_signal,
                'confidence': signals.get('confidence', 0)
            }
            
            if primary_signal == 'BUY':
                bullish_count += 1
            elif primary_signal == 'SELL':
                bearish_count += 1
            else:
                neutral_count += 1
                
        except Exception:
            continue
    
    total_stocks = bullish_count + bearish_count + neutral_count
    
    if total_stocks == 0:
        return {"error": "No valid data for sentiment analysis"}
    
    # Determine overall sentiment
    bullish_ratio = bullish_count / total_stocks
    bearish_ratio = bearish_count / total_stocks
    
    if bullish_ratio > 0.6:
        overall_sentiment = "BULLISH"
        sentiment_strength = "Strong"
    elif bullish_ratio > 0.4:
        overall_sentiment = "BULLISH"
        sentiment_strength = "Moderate"
    elif bearish_ratio > 0.6:
        overall_sentiment = "BEARISH"
        sentiment_strength = "Strong"
    elif bearish_ratio > 0.4:
        overall_sentiment = "BEARISH"
        sentiment_strength = "Moderate"
    else:
        overall_sentiment = "NEUTRAL"
        sentiment_strength = "Mixed"
    
    return {
        "overall_sentiment": overall_sentiment,
        "sentiment_strength": sentiment_strength,
        "bullish_stocks": bullish_count,
        "bearish_stocks": bearish_count,
        "neutral_stocks": neutral_count,
        "bullish_ratio": bullish_ratio,
        "bearish_ratio": bearish_ratio,
        "individual_sentiments": individual_sentiments,
        "analysis_summary": f"{overall_sentiment} market sentiment with {sentiment_strength.lower()} conviction"
    }
