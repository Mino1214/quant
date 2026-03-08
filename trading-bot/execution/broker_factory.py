"""
Broker factory: paper or live from config trading_mode.
"""
from typing import Optional

from execution.base_broker import BaseBroker
from execution.paper_broker import PaperBroker
from execution.binance_broker import BinanceBroker


def create_broker(
    trading_mode: str,
    initial_balance: float = 10000.0,
    commission_rate: float = 0.0004,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> BaseBroker:
    if trading_mode == "live":
        return BinanceBroker(api_key=api_key, api_secret=api_secret)
    return PaperBroker(initial_balance=initial_balance, commission_rate=commission_rate)
