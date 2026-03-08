"""
Aggregate 1m candles into 5m and 15m. Emits only when a higher TF candle CLOSES.
"""
from datetime import datetime
from typing import Callable, Optional

from core.models import Candle, Timeframe


def aggregate_candles(candles: list[Candle], target_minutes: int) -> Optional[Candle]:
    """
    Aggregate 1m candles into one candle of target_minutes (e.g. 5 or 15).
    candles must be in time order; we use the last full set that forms a complete bar.
    """
    if not candles or len(candles) < target_minutes:
        return None
    # Use last `target_minutes` 1m candles
    block = candles[-target_minutes:]
    return Candle(
        open=block[0].open,
        high=max(c.high for c in block),
        low=min(c.low for c in block),
        close=block[-1].close,
        volume=sum(c.volume for c in block),
        timestamp=block[-1].timestamp,
        timeframe=Timeframe.M5 if target_minutes == 5 else Timeframe.M15,
    )


class TimeframeAggregator:
    """
    Consumes 1m closed candles and produces 5m/15m closed candles.
    Calls on_5m_closed / on_15m_closed when a full bar is ready.
    """

    def __init__(
        self,
        on_5m_closed: Optional[Callable[[Candle], None]] = None,
        on_15m_closed: Optional[Callable[[Candle], None]] = None,
    ):
        self._1m_buffer: list[Candle] = []
        self._max_1m = 30  # keep enough for 15m
        self._on_5m_closed = on_5m_closed
        self._on_15m_closed = on_15m_closed

    def push_1m(self, candle: Candle) -> None:
        self._1m_buffer.append(candle)
        if len(self._1m_buffer) > self._max_1m:
            self._1m_buffer = self._1m_buffer[-self._max_1m :]

        if len(self._1m_buffer) >= 5:
            c5 = aggregate_candles(self._1m_buffer, 5)
            if c5 and self._on_5m_closed:
                self._on_5m_closed(c5)
        if len(self._1m_buffer) >= 15:
            c15 = aggregate_candles(self._1m_buffer, 15)
            if c15 and self._on_15m_closed:
                self._on_15m_closed(c15)

    def get_5m_candles(self, n: int = 50) -> list[Candle]:
        """Return last n complete 5m bars (from current 1m buffer)."""
        if len(self._1m_buffer) < 5:
            return []
        out = []
        buf = list(self._1m_buffer)
        for i in range(0, len(buf) - 4, 5):
            block = buf[i : i + 5]
            out.append(aggregate_candles(block, 5))
        return [c for c in out if c is not None][-n:]

    def get_15m_candles(self, n: int = 50) -> list[Candle]:
        if len(self._1m_buffer) < 15:
            return []
        out = []
        buf = list(self._1m_buffer)
        for i in range(0, len(buf) - 14, 15):
            block = buf[i : i + 15]
            out.append(aggregate_candles(block, 15))
        return [c for c in out if c is not None][-n:]
