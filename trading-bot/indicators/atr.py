"""
Average True Range. Input: list of Candle or (high, low, close) arrays.
"""
from typing import List, Optional, Union

from core.models import Candle


def _hlc(candles: List[Candle]) -> List[tuple[float, float, float]]:
    return [(c.high, c.low, c.close) for c in candles]


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(candles: List[Candle], period: int = 14) -> Optional[float]:
    """
    ATR of the last candle. Uses typical (high, low, close).
    Returns None if len(candles) < period + 1.
    """
    if len(candles) < period + 1:
        return None
    hlc = _hlc(candles)
    trs = []
    for i in range(1, len(hlc)):
        h, l, c = hlc[i]
        prev_c = hlc[i - 1][2]
        trs.append(true_range(h, l, prev_c))
    if len(trs) < period:
        return None
    # Simple moving average of last `period` TRs
    return sum(trs[-period:]) / period
