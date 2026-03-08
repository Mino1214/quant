"""
1m candle buffer. Emits only when a candle is CLOSED (final).
"""
from collections import deque
from datetime import datetime
from typing import Callable, Optional

from core.models import Candle, Timeframe


class CandleBuffer:
    """
    Holds 1m candles. When a new closed candle is pushed (x_is_final=True),
    appends it and optionally notifies via callback.
    """

    def __init__(
        self,
        maxlen: int = 500,
        on_candle_closed: Optional[Callable[[Candle], None]] = None,
    ):
        self._buffer: deque[Candle] = deque(maxlen=maxlen)
        self._on_candle_closed = on_candle_closed

    def push(self, candle: Candle, is_closed: bool = True) -> None:
        if is_closed:
            self._buffer.append(candle)
            if self._on_candle_closed:
                self._on_candle_closed(candle)

    def get_closed_candles(self, n: Optional[int] = None) -> list[Candle]:
        """Return last n closed candles (oldest first). If n is None, return all."""
        candles = list(self._buffer)
        if n is not None:
            candles = candles[-n:]
        return candles

    def last_closed(self) -> Optional[Candle]:
        if not self._buffer:
            return None
        return self._buffer[-1]

    def __len__(self) -> int:
        return len(self._buffer)
