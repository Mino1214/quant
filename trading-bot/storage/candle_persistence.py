"""
1m/5m/15m 봉을 DB 테이블(btc1m, btc5m, btc15m)에 저장.
수집기 스키마: symbol, openTime, o, h, l, c, v, closeTime, createdAt. PK (symbol, openTime).
SAVE_CANDLES=0 이면 저장 비활성화.
"""
import logging
import os
import time
from typing import Optional

from sqlalchemy import text

from core.models import Candle
from storage.database import engine

logger = logging.getLogger(__name__)

SAVE_CANDLES = os.environ.get("SAVE_CANDLES", "1").strip() in ("1", "true", "yes")


def _ts_ms(c: Candle) -> int:
    return int(c.timestamp.timestamp() * 1000)


def _insert_candle(table: str, c: Candle, symbol: str, interval_ms: int) -> None:
    """
    수집기와 동일 스키마: symbol, openTime, o, h, l, c, v, closeTime, createdAt
    + 확장 컬럼(quote_volume, trade_count, taker_buy_volume, taker_buy_quote_volume).
    PK (symbol, openTime) → ON DUPLICATE KEY UPDATE.
    """
    if not SAVE_CANDLES:
        return
    open_ms = _ts_ms(c)
    close_ms = open_ms + interval_ms
    now_ms = int(time.time() * 1000)
    sql = f"""
        INSERT INTO `{table}` (
            symbol,
            openTime,
            o, h, l, c, v,
            closeTime,
            createdAt,
            quote_volume,
            trade_count,
            taker_buy_volume,
            taker_buy_quote_volume
        )
        VALUES (
            :symbol,
            :openTime,
            :o, :h, :l, :c, :v,
            :closeTime,
            :createdAt,
            :quote_volume,
            :trade_count,
            :taker_buy_volume,
            :taker_buy_quote_volume
        )
        ON DUPLICATE KEY UPDATE
          o=VALUES(o),
          h=VALUES(h),
          l=VALUES(l),
          c=VALUES(c),
          v=VALUES(v),
          closeTime=VALUES(closeTime),
          quote_volume=VALUES(quote_volume),
          trade_count=VALUES(trade_count),
          taker_buy_volume=VALUES(taker_buy_volume),
          taker_buy_quote_volume=VALUES(taker_buy_quote_volume)
    """
    params = {
        "symbol": symbol,
        "openTime": open_ms,
        "o": c.open,
        "h": c.high,
        "l": c.low,
        "c": c.close,
        "v": c.volume,
        "closeTime": close_ms,
        "createdAt": now_ms,
        "quote_volume": getattr(c, "quote_volume", None),
        "trade_count": getattr(c, "trade_count", None),
        "taker_buy_volume": getattr(c, "taker_buy_volume", None),
        "taker_buy_quote_volume": getattr(c, "taker_buy_quote_volume", None),
    }
    try:
        with engine.connect() as conn:
            conn.execute(text(sql), params)
            conn.commit()
        logger.debug("Saved %s to DB openTime=%s", table, open_ms)
    except Exception as e:
        logger.warning("Save candle %s (openTime=%s): %s", table, open_ms, e)


def save_candle_1m(c: Candle, table: str = "btc1m", symbol: str = "BTCUSDT") -> None:
    _insert_candle(table, c, symbol, 60_000)


def save_candle_5m(c: Candle, table: str = "btc5m", symbol: str = "BTCUSDT") -> None:
    _insert_candle(table, c, symbol, 5 * 60_000)


def save_candle_15m(c: Candle, table: str = "btc15m", symbol: str = "BTCUSDT") -> None:
    _insert_candle(table, c, symbol, 15 * 60_000)
