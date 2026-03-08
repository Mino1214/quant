"""
RiskManager: daily limits (loss/profit R, max trades, cooldown), and stop/TP calculation.
Reusable for backtest and realtime.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

from core.models import Candle, Direction, RiskSettings, TradeRecord

from indicators.atr import atr
from indicators.ema import ema
from risk.position_size import position_size


def ema_exit_triggered(
    candles_1m: List[Candle],
    direction: Direction,
    confirm_bars: int,
    ema_fast: int = 8,
    ema_mid: int = 21,
) -> bool:
    """
    True if last `confirm_bars` bars all satisfy EMA trend exit (long: EMA8 < EMA21, short: EMA8 > EMA21).
    N봉 연속 확인으로 일시적 눌림에서 조기 청산 방지 → 큰 추세 유지.
    """
    if len(candles_1m) < confirm_bars + max(ema_fast, ema_mid):
        return False
    for j in range(confirm_bars):
        subset = candles_1m[: len(candles_1m) - j]
        closes = [c.close for c in subset]
        ema8_val = ema(closes, ema_fast)
        ema21_val = ema(closes, ema_mid)
        if ema8_val is None or ema21_val is None:
            return False
        if direction == Direction.LONG and ema8_val >= ema21_val:
            return False
        if direction == Direction.SHORT and ema8_val <= ema21_val:
            return False
    return True


@dataclass
class RiskCheckResult:
    allowed: bool
    reason_code: str


def compute_stop_loss(
    entry: float,
    direction: Direction,
    candles_1m: List[Candle],
    settings: RiskSettings,
) -> float:
    """
    Initial stop loss: ATR only. SL = entry ± ATR * atr_multiplier.
    Long: entry - ATR * mult, Short: entry + ATR * mult.
    """
    atr_val = atr(candles_1m, settings.atr_period) or 0.0
    if direction == Direction.LONG:
        return entry - atr_val * settings.atr_multiplier
    return entry + atr_val * settings.atr_multiplier


def compute_take_profit(
    entry: float, stop_loss: float, direction: Direction, rr: float
) -> float:
    """RR-based target. Risk = |entry - sl|, target = entry + rr * risk (long) or entry - rr * risk (short)."""
    risk = abs(entry - stop_loss)
    if direction == Direction.LONG:
        return entry + rr * risk
    return entry - rr * risk


def compute_quantity(
    balance: float,
    entry: float,
    stop_loss: float,
    direction: Direction,
    settings: RiskSettings,
) -> float:
    stop_distance = abs(entry - stop_loss)
    return position_size(
        balance, settings.risk_per_trade_pct, entry, stop_distance, direction
    )


class RiskManager:
    def __init__(self, settings: RiskSettings):
        self.settings = settings
        self._daily_trades: List[TradeRecord] = []  # in-memory; reset by date
        self._last_trade_bar_ts: Optional[datetime] = None
        self._current_date: Optional[date] = None

    def _ensure_date(self, now: datetime) -> None:
        d = now.date()
        if self._current_date != d:
            self._current_date = d
            self._daily_trades = []

    def daily_pnl_r(self, now: datetime) -> float:
        """Sum of rr of all trades today."""
        self._ensure_date(now)
        return sum(t.rr for t in self._daily_trades)

    def daily_trade_count(self, now: datetime) -> int:
        self._ensure_date(now)
        return len(self._daily_trades)

    def record_trade(self, trade: TradeRecord) -> None:
        self._ensure_date(trade.closed_at)
        self._daily_trades.append(trade)

    def can_trade(self, now: datetime, cooldown_bars: int = 1) -> RiskCheckResult:
        """
        Check daily loss limit, profit limit, max trades, and cooldown.
        cooldown_bars: min bars since last trade (caller can pass from settings).
        """
        self._ensure_date(now)
        r = self.daily_pnl_r(now)
        if r <= self.settings.daily_loss_limit_r:
            return RiskCheckResult(False, "daily_loss_limit")
        if r >= self.settings.daily_profit_limit_r:
            return RiskCheckResult(False, "daily_profit_limit")
        if self.daily_trade_count(now) >= self.settings.max_trades_per_day:
            return RiskCheckResult(False, "max_trades_per_day")
        # Cooldown: 청산한 봉 시각 기준, cooldown_bars 봉(분) 지나야 새 진입 가능 (1m = 60s)
        if self._last_trade_bar_ts is not None:
            elapsed_sec = (now - self._last_trade_bar_ts).total_seconds()
            need_sec = cooldown_bars * 60  # 1 bar = 60s
            if elapsed_sec < need_sec:
                return RiskCheckResult(False, "cooldown")
        return RiskCheckResult(True, "ok")

    def set_last_trade_time(self, ts: datetime) -> None:
        self._last_trade_bar_ts = ts
