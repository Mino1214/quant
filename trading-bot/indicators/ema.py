"""
Exponential Moving Average. Input: list of closes or list of Candle.
"""
from typing import List, Optional, Union

from core.models import Candle


def _closes(candles: List[Union[Candle, float]]) -> List[float]:
    if not candles:
        return []
    if isinstance(candles[0], Candle):
        return [c.close for c in candles]
    return list(candles)


def ema(closes: List[float], period: int) -> Optional[float]:
    """Single EMA value for the last period. Returns None if len(closes) < period."""
    if len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    val = sum(closes[:period]) / period
    for i in range(period, len(closes)):
        val = closes[i] * k + val * (1 - k)
    return val


def ema_series(closes: List[float], period: int) -> List[Optional[float]]:
    """EMA for each index. First (period-1) values are None."""
    out: List[Optional[float]] = [None] * (period - 1)
    if len(closes) < period:
        return out + [None] * (len(closes) - len(out))
    k = 2.0 / (period + 1)
    val = sum(closes[:period]) / period
    out.append(val)
    for i in range(period, len(closes) - 1):
        val = closes[i] * k + val * (1 - k)
        out.append(val)
    return out


def emas_from_candles(candles: List[Candle], periods: List[int]) -> dict[int, Optional[float]]:
    """Compute multiple EMAs (e.g. 8, 21, 50) from candle list. Returns last value per period."""
    c = _closes(candles)
    return {p: ema(c, p) for p in periods}
