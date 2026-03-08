"""
Engine state: 1m/5m/15m buffers, last bias/trend/trigger, last signal bar to avoid duplicates.
"""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.models import Candle, Direction, Timeframe


@dataclass
class EngineState:
    """Mutable state for realtime engine."""
    candles_1m: deque = field(default_factory=lambda: deque(maxlen=500))
    candles_5m: list = field(default_factory=list)
    candles_15m: list = field(default_factory=list)
    current_1m: Optional[Candle] = None  # 진행 중인 1m 봉 (WS 매 틱 갱신, 대시보드용)
    last_ws_at: Optional[datetime] = None  # 마지막 WebSocket 수신 시각 (UTC)
    last_bias: Optional[Direction] = None
    last_trend: Optional[Direction] = None
    last_trigger: Optional[Direction] = None
    last_regime: Optional[str] = None
    last_regime_blocked: Optional[str] = None
    last_signal_bar_ts: Optional[datetime] = None
    last_order_at: Optional[datetime] = None  # 마지막 진입 주문 시각 (매매 들어갔는지 확인용)
    last_1m_ts: Optional[datetime] = None
    last_5m_ts: Optional[datetime] = None
    last_15m_ts: Optional[datetime] = None

    def add_1m(self, c: Candle) -> None:
        self.candles_1m.append(c)
        self.last_1m_ts = c.timestamp

    def add_5m(self, c: Candle) -> None:
        self.candles_5m.append(c)
        if len(self.candles_5m) > 100:
            self.candles_5m = self.candles_5m[-100:]
        self.last_5m_ts = c.timestamp

    def add_15m(self, c: Candle) -> None:
        self.candles_15m.append(c)
        if len(self.candles_15m) > 100:
            self.candles_15m = self.candles_15m[-100:]
        self.last_15m_ts = c.timestamp

    def get_1m_list(self, n: Optional[int] = None) -> list:
        lst = list(self.candles_1m)
        if n:
            lst = lst[-n:]
        return lst

    def get_5m_list(self, n: Optional[int] = None) -> list:
        if n:
            return self.candles_5m[-n:]
        return list(self.candles_5m)

    def get_15m_list(self, n: Optional[int] = None) -> list:
        if n:
            return self.candles_15m[-n:]
        return list(self.candles_15m)
