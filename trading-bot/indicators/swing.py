"""
Swing high / swing low over a lookback window. For hybrid stop loss.
"""
from typing import List

from core.models import Candle


def swing_low(candles: List[Candle], lookback: int) -> float | None:
    """
    Lowest low in the last `lookback` candles. Used for long stop.
    Returns None if len(candles) < lookback.
    """
    if len(candles) < lookback:
        return None
    return min(c.low for c in candles[-lookback:])


def swing_high(candles: List[Candle], lookback: int) -> float | None:
    """
    Highest high in the last `lookback` candles. Used for short stop.
    Returns None if len(candles) < lookback.
    """
    if len(candles) < lookback:
        return None
    return max(c.high for c in candles[-lookback:])
