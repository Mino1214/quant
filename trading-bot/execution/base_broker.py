"""
Broker interface. Strategy engine only depends on this.
Paper and Live implement the same interface.
"""
from abc import ABC, abstractmethod
from typing import Optional

from core.models import Direction, OrderRequest, Position


class BaseBroker(ABC):
    @abstractmethod
    async def place_market_order(
        self,
        symbol: str,
        side: Direction,
        quantity: float,
        reduce_only: bool = False,
    ) -> Optional[str]:
        """Place market order. Returns order_id or None."""
        pass

    @abstractmethod
    async def place_stop_loss_order(
        self,
        symbol: str,
        side: Direction,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
    ) -> Optional[str]:
        """Place STOP_MARKET. Returns order_id or None."""
        pass

    @abstractmethod
    async def place_take_profit_order(
        self,
        symbol: str,
        side: Direction,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
    ) -> Optional[str]:
        """Place TAKE_PROFIT_MARKET. Returns order_id or None."""
        pass

    @abstractmethod
    async def close_position(self, symbol: str) -> bool:
        """Close full position for symbol. Returns success."""
        pass

    @abstractmethod
    async def get_open_position(self, symbol: str) -> Optional[Position]:
        """Return current open position or None."""
        pass
