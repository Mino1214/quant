"""
Execution engine: position sizing and order placement (market, SL, TP).
Uses risk_per_trade = equity * risk_pct, position_size = risk / stop_distance.
Delegates to broker for place_market_order, place_stop_loss_order, place_take_profit_order.
"""
import logging
from datetime import datetime
from typing import Optional

from core.models import Direction
from risk.risk_manager import compute_quantity

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Orchestrates order placement and position sizing."""

    def __init__(
        self,
        broker,
        equity: float = 10000.0,
        risk_pct: float = 0.01,
        risk_settings=None,
    ):
        self.broker = broker
        self.equity = equity
        self.risk_pct = risk_pct
        self.risk_settings = risk_settings

    def set_equity(self, equity: float) -> None:
        self.equity = equity

    def position_size(self, entry: float, stop_loss: float, direction: Direction) -> float:
        """risk_per_trade = equity * risk_pct; size = risk / stop_distance."""
        if self.risk_settings is None:
            risk = self.equity * self.risk_pct
            stop_distance = abs(entry - stop_loss)
            if stop_distance <= 0:
                return 0.0
            return risk / stop_distance
        return compute_quantity(
            self.equity, entry, stop_loss, direction, self.risk_settings
        )

    async def execute_entry(
        self,
        symbol: str,
        side: Direction,
        entry: float,
        stop_loss: float,
        take_profit: Optional[float] = None,
        opened_at: Optional[datetime] = None,
    ) -> Optional[str]:
        """
        Compute size, place market order, SL and TP. Returns order id or None.
        """
        qty = self.position_size(entry, stop_loss, side)
        if qty <= 0:
            logger.warning("ExecutionEngine: qty<=0 entry=%s sl=%s", entry, stop_loss)
            return None
        oid = await self.broker.place_market_order(symbol, side, qty, reduce_only=False)
        if oid is None:
            return None
        from execution.paper_broker import PaperBroker
        if isinstance(self.broker, PaperBroker):
            self.broker.set_fill_price(entry, stop_loss, take_profit, opened_at=opened_at)
        await self.broker.place_stop_loss_order(symbol, side, qty, stop_loss, reduce_only=True)
        await self.broker.place_take_profit_order(symbol, side, qty, entry, reduce_only=True)
        logger.info("ExecutionEngine: entry %s %s qty=%s sl=%s", symbol, side.value, qty, stop_loss)
        return oid
