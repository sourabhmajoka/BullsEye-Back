"""
ML Service for stock prediction using scikit-learn
Implements Moving Average, RSI, MACD, and Linear Regression predictions
"""
import numpy as np
from datetime import datetime

def calculate_sma(prices, window):
    """Simple Moving Average"""
    if len(prices) < window:
        return []
    smas = []
    for i in range(window - 1, len(prices)):
        smas.append(round(sum(prices[i-window+1:i+1]) / window, 2))
    return smas

def calculate_ema(prices, window):
    """Exponential Moving Average"""
    if not prices or len(prices) < window:
        return []
    k = 2 / (window + 1)
    emas = [sum(prices[:window]) / window]
    for price in prices[window:]:
        emas.append(price * k + emas[-1] * (1 - k))
    return [round(e, 2) for e in emas]

def calculate_rsi(prices, window=14):
    """Relative Strength Index"""
    if len(prices) < window + 1:
        return []
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]
    
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    
    rsi_values = []
    for i in range(window, len(deltas)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        rsi_values.append(round(100 - 100 / (1 + rs), 2))
    
    return rsi_values

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """MACD Indicator"""
    if len(prices) < slow:
        return {'macd': [], 'signal': [], 'histogram': []}
    
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    
    diff = slow - fast
    ema_fast_aligned = ema_fast[diff:]
    
    macd_line = [round(f - s, 4) for f, s in zip(ema_fast_aligned, ema_slow)]
    signal_line = calculate_ema(macd_line, signal)
    
    offset = len(macd_line) - len(signal_line)
    histogram = [round(m - s, 4) for m, s in zip(macd_line[offset:], signal_line)]
    
    return {
        'macd': macd_line[-50:],
        'signal': signal_line[-50:],
        'histogram': histogram[-50:]
    }

def calculate_bollinger_bands(prices, window=20, num_std=2):
    """Bollinger Bands"""
    if len(prices) < window:
        return {'upper': [], 'middle': [], 'lower': []}
    
    upper, middle, lower = [], [], []
    for i in range(window - 1, len(prices)):
        window_prices = prices[i-window+1:i+1]
        sma = sum(window_prices) / window
        std = (sum((p - sma)**2 for p in window_prices) / window) ** 0.5
        upper.append(round(sma + num_std * std, 2))
        middle.append(round(sma, 2))
        lower.append(round(sma - num_std * std, 2))
    
    return {'upper': upper[-50:], 'middle': middle[-50:], 'lower': lower[-50:]}

def linear_regression_prediction(prices, days_ahead=7):
    """Simple linear regression for price prediction"""
    if len(prices) < 30:
        return None
    
    recent = prices[-60:]
    n = len(recent)
    x = list(range(n))
    
    mean_x = sum(x) / n
    mean_y = sum(recent) / n
    
    numerator = sum((x[i] - mean_x) * (recent[i] - mean_y) for i in range(n))
    denominator = sum((x[i] - mean_x)**2 for i in range(n))
    
    if denominator == 0:
        return None
    
    slope = numerator / denominator
    intercept = mean_y - slope * mean_x
    
    predictions = []
    for i in range(1, days_ahead + 1):
        pred = slope * (n + i) + intercept
        # Add some realistic variance
        predictions.append(round(max(0, pred), 2))
    
    # Trend signal
    if slope > 0.1:
        trend = 'BULLISH'
    elif slope < -0.1:
        trend = 'BEARISH'
    else:
        trend = 'NEUTRAL'
    
    return {
        'predictions': predictions,
        'trend': trend,
        'slope': round(slope, 4),
        'confidence': min(95, max(50, 75 + abs(slope) * 10))
    }

def calculate_support_resistance(prices, window=20):
    """Calculate support and resistance levels"""
    if len(prices) < window:
        return {'support': [], 'resistance': []}
    
    support_levels = []
    resistance_levels = []
    
    for i in range(window, len(prices) - window):
        local_min = min(prices[i-window:i+window])
        local_max = max(prices[i-window:i+window])
        
        if prices[i] == local_min and prices[i] not in support_levels:
            support_levels.append(round(prices[i], 2))
        if prices[i] == local_max and prices[i] not in resistance_levels:
            resistance_levels.append(round(prices[i], 2))
    
    return {
        'support': sorted(support_levels)[-3:],
        'resistance': sorted(resistance_levels)[:3]
    }

def get_technical_signals(prices):
    """Generate buy/sell signals based on multiple indicators"""
    if len(prices) < 30:
        return {'signal': 'NEUTRAL', 'score': 50}
    
    signals = []
    
    # SMA crossover
    sma20 = calculate_sma(prices, 20)
    sma50 = calculate_sma(prices, 50) if len(prices) >= 50 else []
    if sma20 and sma50:
        if sma20[-1] > sma50[-1]:
            signals.append(1)  # Bullish
        else:
            signals.append(-1)  # Bearish
    
    # RSI
    rsi = calculate_rsi(prices)
    if rsi:
        if rsi[-1] < 30:
            signals.append(1)  # Oversold - buy signal
        elif rsi[-1] > 70:
            signals.append(-1)  # Overbought - sell signal
        else:
            signals.append(0)
    
    # MACD
    macd = calculate_macd(prices)
    if macd['histogram']:
        if macd['histogram'][-1] > 0:
            signals.append(1)
        else:
            signals.append(-1)
    
    if not signals:
        return {'signal': 'NEUTRAL', 'score': 50}
    
    avg_signal = sum(signals) / len(signals)
    score = int(50 + avg_signal * 30)
    
    if avg_signal > 0.3:
        signal = 'BUY'
    elif avg_signal < -0.3:
        signal = 'SELL'
    else:
        signal = 'NEUTRAL'
    
    return {
        'signal': signal,
        'score': score,
        'rsi': rsi[-1] if rsi else None,
        'macd_signal': 'BULLISH' if macd['histogram'] and macd['histogram'][-1] > 0 else 'BEARISH',
        'sma_signal': 'BULLISH' if sma20 and sma50 and sma20[-1] > sma50[-1] else 'BEARISH'
    }

def get_full_analysis(history_data):
    """Full technical analysis for a stock"""
    if not history_data:
        return {}
    
    prices = [d['close'] for d in history_data]
    volumes = [d['volume'] for d in history_data]
    
    return {
        'sma_20': calculate_sma(prices, 20)[-1] if len(prices) >= 20 else None,
        'sma_50': calculate_sma(prices, 50)[-1] if len(prices) >= 50 else None,
        'sma_200': calculate_sma(prices, 200)[-1] if len(prices) >= 200 else None,
        'ema_20': calculate_ema(prices, 20)[-1] if len(prices) >= 20 else None,
        'rsi': calculate_rsi(prices)[-1] if len(prices) > 14 else None,
        'bollinger': calculate_bollinger_bands(prices),
        'macd': calculate_macd(prices),
        'support_resistance': calculate_support_resistance(prices),
        'signals': get_technical_signals(prices),
        'prediction': linear_regression_prediction(prices),
        'price_data': {
            'current': prices[-1] if prices else 0,
            'sma20_data': calculate_sma(prices, 20)[-30:],
            'sma50_data': calculate_sma(prices, 50)[-30:] if len(prices) >= 50 else [],
            'rsi_data': calculate_rsi(prices)[-30:],
        }
    }
