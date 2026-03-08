"""
Load cross-market data for feature building: funding rate, open interest.
All queries use timestamp <= T to avoid future data leakage.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import text

from storage.database import engine

BTC_SYMBOL = "BTCUSDT"


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def load_funding_before(end_ts: datetime, limit: int = 10, symbol: str = BTC_SYMBOL) -> List[dict]:
    """
    Load funding rate rows with fundingTime <= end_ts, most recent first.
    Returns list of dicts with fundingTime, funding_rate, (mark_price).
    """
    sql = """
    SELECT fundingTime, symbol, funding_rate, mark_price
    FROM btc_funding
    WHERE symbol = :symbol AND fundingTime <= :end_ts
    ORDER BY fundingTime DESC
    LIMIT :lim
    """
    with engine.connect() as conn:
        result = conn.execute(
            text(sql),
            {"symbol": symbol, "end_ts": _to_ms(end_ts), "lim": limit},
        )
        return [dict(row._mapping) for row in result]


def load_open_interest_before(end_ts: datetime, limit: int = 10, symbol: str = BTC_SYMBOL) -> List[dict]:
    """
    Load open interest rows with timestamp <= end_ts, most recent first.
    Returns list of dicts with timestamp, sum_open_interest, sum_open_interest_value.
    """
    sql = """
    SELECT timestamp, symbol, sum_open_interest, sum_open_interest_value
    FROM btc_open_interest
    WHERE symbol = :symbol AND timestamp <= :end_ts
    ORDER BY timestamp DESC
    LIMIT :lim
    """
    with engine.connect() as conn:
        result = conn.execute(
            text(sql),
            {"symbol": symbol, "end_ts": _to_ms(end_ts), "lim": limit},
        )
        return [dict(row._mapping) for row in result]
