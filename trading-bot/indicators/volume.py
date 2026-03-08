"""
Volume Moving Average (VMA). Input: list of Candle or list of volumes.
"""
from typing import List, Union

from core.models import Candle


def _volumes(candles: List[Union[Candle, float]]) -> List[float]:
    if not candles:
        return []
    if isinstance(candles[0], Candle):
        return [c.volume for c in candles]
    return list(candles)


def vma(volumes: List[float], period: int) -> float | None:
    """Simple moving average of volume. Returns None if len(volumes) < period."""
    if len(volumes) < period:
        return None
    return sum(volumes[-period:]) / period


def vma_from_candles(candles: List[Candle], period: int) -> float | None:
    return vma(_volumes(candles), period)
