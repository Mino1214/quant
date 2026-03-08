"""
EMA slope (rate of change over bars). For 15m bias filter.
"""
from typing import List

from core.models import Candle

from indicators.ema import ema_series


def ema_slope(candles: List[Candle], period: int, bars: int = 1) -> float | None:
    """
    Slope of EMA over last `bars` candles: (ema_now - ema_bars_ago) / bars.
    Returns None if not enough data.
    """
    if len(candles) < period + bars:
        return None
    closes = [c.close for c in candles]
    series = ema_series(closes, period)
    # series has None for first (period-1), then values
    valid = [v for v in series if v is not None]
    if len(valid) < bars + 1:
        return None
    ema_now = valid[-1]
    ema_ago = valid[-1 - bars]
    return (ema_now - ema_ago) / bars if bars else 0.0
