"""
Position size from account balance, risk per trade, and stop distance.
"""
from typing import Optional

from core.models import Direction


def position_size(
    balance: float,
    risk_pct: float,
    entry_price: float,
    stop_distance: float,
    direction: Direction,
    leverage: float = 1.0,
) -> float:
    """
    Size in quote (e.g. USDT) or contracts so that risk = balance * risk_pct * leverage.
    position_size = (equity * risk_pct/100 * leverage) / stop_distance.
    leverage=1.0 for no regime-adaptive exposure; >1 for TREND, <1 for CHAOTIC.
    Returns quantity (contracts/size). Caller rounds to symbol lot size.
    """
    if stop_distance <= 0 or leverage <= 0:
        return 0.0
    risk_amount = balance * (risk_pct / 100.0) * leverage
    return risk_amount / stop_distance
