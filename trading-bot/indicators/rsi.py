"""
RSI (Relative Strength Index). Input: list of closes.
"""
from typing import List


def rsi(closes: List[float], period: int = 14) -> float | None:
    """
    RSI for the last candle. Returns None if len(closes) < period + 1.
    """
    if len(closes) < period + 1:
        return None
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(ch if ch > 0 else 0.0)
        losses.append(-ch if ch < 0 else 0.0)
    # Use last `period` changes
    g = sum(gains[-period:]) / period
    l = sum(losses[-period:]) / period
    if l == 0:
        return 100.0
    rs = g / l
    return 100.0 - (100.0 / (1.0 + rs))
