"""
Paper broker: simulates orders and positions. 4-stage exit (SL, partial TP, trailing, time stop).
Logs trades to storage.
"""
import logging
from datetime import datetime
from typing import List, Optional

from core.models import Direction, Position, RiskSettings, TradeRecord

from execution.base_broker import BaseBroker

logger = logging.getLogger(__name__)


def _make_trade_record(
    symbol: str,
    side: Direction,
    size: float,
    entry: float,
    exit_price: float,
    stop_loss: float,
    reason_exit: str,
    opened_at: datetime,
    closed_at: datetime,
    commission_rate: float = 0.0,
) -> TradeRecord:
    risk = abs(entry - stop_loss)
    pnl_gross = (exit_price - entry) * size if side == Direction.LONG else (entry - exit_price) * size
    fee = (entry * size + exit_price * size) * commission_rate if commission_rate > 0 else 0.0
    pnl = pnl_gross - fee
    rr = (pnl / (risk * size)) if risk and size else 0.0
    return TradeRecord(
        symbol=symbol,
        side=side,
        size=size,
        entry_price=entry,
        exit_price=exit_price,
        stop_loss=stop_loss,
        take_profit=0.0,
        pnl=pnl,
        rr=rr,
        reason_entry="",
        reason_exit=reason_exit,
        opened_at=opened_at,
        closed_at=closed_at,
    )


class PaperBroker(BaseBroker):
    def __init__(self, initial_balance: float = 10000.0, commission_rate: float = 0.0004):
        self._balance = initial_balance
        self._commission_rate = commission_rate  # taker 수수료 (예: 0.0004 = 0.04%) → PnL에서 차감
        self._position: Optional[Position] = None
        self._pending_sl: Optional[float] = None
        self._pending_tp: Optional[float] = None  # unused in 4-stage exit; kept for interface

    async def place_market_order(
        self,
        symbol: str,
        side: Direction,
        quantity: float,
        reduce_only: bool = False,
    ) -> Optional[str]:
        self._position = Position(
            symbol=symbol,
            side=side,
            size=quantity,
            entry_price=0.0,
            opened_at=datetime.utcnow(),
            tp1_hit=False,
            highest_price_since_entry=0.0,
            lowest_price_since_entry=0.0,
            bars_in_trade=0,
        )
        logger.info(
            "===== PAPER 매매 체결 ===== %s %s qty=%s (진입) order_id=%s",
            symbol, side.value, quantity, "paper-" + datetime.utcnow().strftime("%Y%m%d%H%M%S"),
        )
        return "paper-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")

    def set_fill_price(
        self,
        price: float,
        stop_loss: float,
        take_profit: Optional[float] = None,
        opened_at: Optional[datetime] = None,
    ) -> None:
        """Set entry and initial SL (ATR-based). take_profit ignored in 4-stage exit."""
        if self._position:
            use_opened_at = opened_at if opened_at is not None else self._position.opened_at
            hi = price if self._position.side == Direction.LONG else 0.0
            lo = price if self._position.side == Direction.SHORT else 0.0
            self._position = Position(
                symbol=self._position.symbol,
                side=self._position.side,
                size=self._position.size,
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit or 0.0,
                opened_at=use_opened_at,
                tp1_hit=False,
                highest_price_since_entry=hi,
                lowest_price_since_entry=lo,
                bars_in_trade=0,
            )
            self._pending_sl = stop_loss

    async def place_stop_loss_order(
        self,
        symbol: str,
        side: Direction,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
    ) -> Optional[str]:
        self._pending_sl = stop_price
        logger.info("Paper: SL order %s @ %s", symbol, stop_price)
        return "paper-sl-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")

    async def place_take_profit_order(
        self,
        symbol: str,
        side: Direction,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
    ) -> Optional[str]:
        self._pending_tp = stop_price
        logger.info("Paper: TP order %s @ %s", symbol, stop_price)
        return "paper-tp-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")

    async def close_position(self, symbol: str) -> bool:
        if self._position and self._position.symbol == symbol:
            self._position = None
            self._pending_sl = None
            self._pending_tp = None
            logger.info("Paper: position closed %s", symbol)
            return True
        return False

    async def get_open_position(self, symbol: str) -> Optional[Position]:
        if self._position and self._position.symbol == symbol:
            return self._position
        return None

    def check_stop_tp(
        self,
        low: float,
        high: float,
        close: float,
        atr_current: float,
        ema8: Optional[float],
        ema21: Optional[float],
        risk_settings: RiskSettings,
        closed_at: Optional[datetime] = None,
        ema_exit_triggered: Optional[bool] = None,
    ) -> List[TradeRecord]:
        """
        4-stage exit. Priority: 1) SL, 2) EMA exit, 3) Time stop, 4) Trailing.
        Partial TP: +1R 도달 시 50% 청산 (별도 관리).
        Returns list of TradeRecords (0, 1, or 2 e.g. partial + full same bar).
        """
        if not self._position or self._pending_sl is None:
            return []

        use_closed_at = closed_at if closed_at is not None else datetime.utcnow()
        entry = self._position.entry_price
        side = self._position.side
        size = self._position.size
        sl = self._pending_sl
        risk = abs(entry - sl)
        results: List[TradeRecord] = []

        # Update state: highest (long), lowest (short), bars_in_trade
        if side == Direction.LONG:
            new_high = max(self._position.highest_price_since_entry, high)
            new_low = self._position.lowest_price_since_entry
        else:
            new_high = self._position.highest_price_since_entry
            new_low = min(self._position.lowest_price_since_entry, low) if self._position.lowest_price_since_entry > 0 else low
        self._position = Position(
            symbol=self._position.symbol,
            side=self._position.side,
            size=self._position.size,
            entry_price=entry,
            stop_loss=self._position.stop_loss,
            take_profit=self._position.take_profit,
            opened_at=self._position.opened_at,
            tp1_hit=self._position.tp1_hit,
            highest_price_since_entry=new_high,
            lowest_price_since_entry=new_low,
            bars_in_trade=self._position.bars_in_trade + 1,
        )
        bars_in_trade = self._position.bars_in_trade
        highest = self._position.highest_price_since_entry
        lowest = self._position.lowest_price_since_entry

        # Partial TP: +1R 도달 시 50% 청산
        partial_R = getattr(risk_settings, "partial_tp_R", 1.0)
        partial_size_ratio = getattr(risk_settings, "partial_tp_size", 0.5)
        if not self._position.tp1_hit and risk > 0:
            if side == Direction.LONG and high >= entry + partial_R * risk:
                close_size = size * partial_size_ratio
                exit_p = entry + partial_R * risk
                tr = _make_trade_record(
                    self._position.symbol, side, close_size, entry, exit_p, sl,
                    "partial_tp", self._position.opened_at, use_closed_at,
                    self._commission_rate,
                )
                results.append(tr)
                size = size - close_size
                self._position = Position(
                    symbol=self._position.symbol,
                    side=self._position.side,
                    size=size,
                    entry_price=entry,
                    stop_loss=self._position.stop_loss,
                    take_profit=self._position.take_profit,
                    opened_at=self._position.opened_at,
                    tp1_hit=True,
                    highest_price_since_entry=highest,
                    lowest_price_since_entry=lowest,
                    bars_in_trade=bars_in_trade,
                )
                if size <= 0:
                    self._position = None
                    self._pending_sl = None
                    return results
            elif side == Direction.SHORT and low <= entry - partial_R * risk:
                close_size = size * partial_size_ratio
                exit_p = entry - partial_R * risk
                tr = _make_trade_record(
                    self._position.symbol, side, close_size, entry, exit_p, sl,
                    "partial_tp", self._position.opened_at, use_closed_at,
                    self._commission_rate,
                )
                results.append(tr)
                size = size - close_size
                self._position = Position(
                    symbol=self._position.symbol,
                    side=self._position.side,
                    size=size,
                    entry_price=entry,
                    stop_loss=self._position.stop_loss,
                    take_profit=self._position.take_profit,
                    opened_at=self._position.opened_at,
                    tp1_hit=True,
                    highest_price_since_entry=highest,
                    lowest_price_since_entry=lowest,
                    bars_in_trade=bars_in_trade,
                )
                if size <= 0:
                    self._position = None
                    self._pending_sl = None
                    return results

        # Full exit: priority 1) SL, 2) EMA, 3) Time, 4) Trailing
        exit_price: Optional[float] = None
        reason_exit = ""

        # 1) Stop Loss
        if side == Direction.LONG and low <= sl:
            exit_price = sl
            reason_exit = "stop_loss"
        elif side == Direction.SHORT and high >= sl:
            exit_price = sl
            reason_exit = "stop_loss"

        # 2) EMA Trend Exit (ema_exit_triggered=N봉 연속 조건 시 사용, 아니면 ema8/ema21 즉시)
        if exit_price is None:
            if ema_exit_triggered is not None:
                if ema_exit_triggered:
                    exit_price = close
                    reason_exit = "ema_exit"
            elif ema8 is not None and ema21 is not None:
                if side == Direction.LONG and ema8 < ema21:
                    exit_price = close
                    reason_exit = "ema_exit"
                elif side == Direction.SHORT and ema8 > ema21:
                    exit_price = close
                    reason_exit = "ema_exit"

        # 3) Time Stop
        max_bars = getattr(risk_settings, "max_bars_in_trade", 30)
        if exit_price is None and bars_in_trade >= max_bars:
            exit_price = close
            reason_exit = "time_stop"

        # 4) Trailing Stop (after partial TP)
        trail_mult = getattr(risk_settings, "trailing_atr_multiplier", 2.0)
        if exit_price is None and self._position.tp1_hit and atr_current > 0:
            if side == Direction.LONG:
                trail_stop = highest - atr_current * trail_mult
                if low <= trail_stop:
                    exit_price = trail_stop
                    reason_exit = "trailing_stop"
            else:
                trail_stop = lowest + atr_current * trail_mult
                if high >= trail_stop:
                    exit_price = trail_stop
                    reason_exit = "trailing_stop"

        if exit_price is not None and size > 0:
            tr = _make_trade_record(
                self._position.symbol, side, size, entry, exit_price, sl,
                reason_exit, self._position.opened_at, use_closed_at,
                self._commission_rate,
            )
            results.append(tr)
            self._position = None
            self._pending_sl = None

        return results
