"""
Sync cross-market data: ETH 1m (eth1m), BTC funding rate (btc_funding), BTC open interest (btc_open_interest).
Uses Binance FAPI. All timestamps stored for alignment at signal time T (use only data <= T).
"""
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import requests

from storage.database import engine

logger = logging.getLogger(__name__)

BINANCE_FAPI_BASE = "https://fapi.binance.com"
FUTURES_DATA_BASE = "https://fapi.binance.com/futures/data"
ETH_SYMBOL = "ETHUSDT"
BTC_SYMBOL = "BTCUSDT"


def _utc_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _ensure_eth1m(conn) -> None:
    """Same schema as btc1m for 1m OHLCV."""
    ddl = """
    CREATE TABLE IF NOT EXISTS eth1m (
        symbol VARCHAR(20) NOT NULL,
        openTime BIGINT NOT NULL,
        o DECIMAL(28,10) NOT NULL,
        h DECIMAL(28,10) NOT NULL,
        l DECIMAL(28,10) NOT NULL,
        c DECIMAL(28,10) NOT NULL,
        v DECIMAL(28,10) NOT NULL,
        closeTime BIGINT NOT NULL,
        createdAt BIGINT NOT NULL,
        PRIMARY KEY(symbol, openTime),
        INDEX idx_symbol_time(symbol, openTime)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    cur = conn.cursor()
    try:
        cur.execute(ddl)
        conn.commit()
    finally:
        cur.close()


def _ensure_btc_funding(conn) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS btc_funding (
        fundingTime BIGINT NOT NULL,
        symbol VARCHAR(20) NOT NULL,
        funding_rate DECIMAL(18,8) NOT NULL,
        mark_price DECIMAL(28,10) NULL,
        PRIMARY KEY(fundingTime),
        INDEX idx_time(fundingTime)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    cur = conn.cursor()
    try:
        cur.execute(ddl)
        conn.commit()
    finally:
        cur.close()


def _ensure_btc_open_interest(conn) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS btc_open_interest (
        timestamp BIGINT NOT NULL,
        symbol VARCHAR(20) NOT NULL,
        sum_open_interest DECIMAL(28,8) NOT NULL,
        sum_open_interest_value DECIMAL(28,2) NULL,
        PRIMARY KEY(timestamp),
        INDEX idx_time(timestamp)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    cur = conn.cursor()
    try:
        cur.execute(ddl)
        conn.commit()
    finally:
        cur.close()


def _get_last_open_time_eth1m(conn) -> int:
    cur = conn.cursor()
    try:
        cur.execute("SELECT COALESCE(MAX(openTime), 0) FROM eth1m WHERE symbol = %s", (ETH_SYMBOL,))
        row = cur.fetchone()
        if row and row[0] and int(row[0]) > 0:
            return int(row[0]) + 1
    finally:
        cur.close()
    return _utc_ms(datetime(2023, 1, 1, tzinfo=timezone.utc))


def _fetch_klines(symbol: str, interval: str, start_ms: int, limit: int = 1500) -> list:
    url = f"{BINANCE_FAPI_BASE}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "startTime": start_ms, "limit": limit}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _upsert_eth1m(conn, klines: list) -> None:
    if not klines:
        return
    sql = """
    INSERT INTO eth1m (symbol, openTime, o, h, l, c, v, closeTime, createdAt)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE o=VALUES(o), h=VALUES(h), l=VALUES(l), c=VALUES(c), v=VALUES(v), closeTime=VALUES(closeTime)
    """
    now_ms = int(time.time() * 1000)
    values = [
        (ETH_SYMBOL, int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), int(k[6]), now_ms)
        for k in klines
    ]
    cur = conn.cursor()
    try:
        cur.executemany(sql, values)
        conn.commit()
    finally:
        cur.close()


def sync_eth1m_to_db() -> int:
    """Sync ETHUSDT 1m to eth1m table. Returns total rows synced."""
    raw = engine.raw_connection()
    total = 0
    try:
        _ensure_eth1m(raw)
        start_ms = _get_last_open_time_eth1m(raw)
        while True:
            klines = _fetch_klines(ETH_SYMBOL, "1m", start_ms)
            if not klines:
                break
            _upsert_eth1m(raw, klines)
            total += len(klines)
            start_ms = int(klines[-1][0]) + 1
            time.sleep(0.2)
    finally:
        raw.close()
    logger.info("ETH 1m sync done: %d rows", total)
    return total


def _fetch_funding_rate(symbol: str, start_ms: int, end_ms: Optional[int] = None, limit: int = 1000) -> List[dict]:
    url = f"{BINANCE_FAPI_BASE}/fapi/v1/fundingRate"
    params = {"symbol": symbol, "startTime": start_ms, "limit": limit}
    if end_ms is not None:
        params["endTime"] = end_ms
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _get_last_funding_time(conn) -> int:
    cur = conn.cursor()
    try:
        cur.execute("SELECT COALESCE(MAX(fundingTime), 0) FROM btc_funding WHERE symbol = %s", (BTC_SYMBOL,))
        row = cur.fetchone()
        if row and row[0] and int(row[0]) > 0:
            return int(row[0]) + 1
    finally:
        cur.close()
    return _utc_ms(datetime(2023, 1, 1, tzinfo=timezone.utc))


def _upsert_funding(conn, records: list) -> None:
    if not records:
        return
    sql = """
    INSERT INTO btc_funding (fundingTime, symbol, funding_rate, mark_price)
    VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE funding_rate=VALUES(funding_rate), mark_price=VALUES(mark_price)
    """
    values = [
        (int(r["fundingTime"]), r.get("symbol", BTC_SYMBOL), float(r["fundingRate"]), float(r.get("markPrice", 0)) if r.get("markPrice") else None)
        for r in records
    ]
    cur = conn.cursor()
    try:
        cur.executemany(sql, values)
        conn.commit()
    finally:
        cur.close()


def sync_btc_funding_to_db() -> int:
    """Sync BTC funding rate to btc_funding. Returns total rows synced."""
    raw = engine.raw_connection()
    total = 0
    try:
        _ensure_btc_funding(raw)
        start_ms = _get_last_funding_time(raw)
        while True:
            records = _fetch_funding_rate(BTC_SYMBOL, start_ms)
            if not records:
                break
            _upsert_funding(raw, records)
            total += len(records)
            start_ms = int(records[-1]["fundingTime"]) + 1
            if len(records) < 1000:
                break
            time.sleep(0.2)
    finally:
        raw.close()
    logger.info("BTC funding sync done: %d rows", total)
    return total


def _fetch_open_interest_hist(symbol: str, period: str = "5m", start_ms: Optional[int] = None, end_ms: Optional[int] = None, limit: int = 500) -> List[dict]:
    url = f"{FUTURES_DATA_BASE}/openInterestHist"
    params = {"symbol": symbol, "period": period, "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    if end_ms is not None:
        params["endTime"] = end_ms
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _get_last_oi_time(conn) -> int:
    cur = conn.cursor()
    try:
        cur.execute("SELECT COALESCE(MAX(timestamp), 0) FROM btc_open_interest WHERE symbol = %s", (BTC_SYMBOL,))
        row = cur.fetchone()
        if row and row[0] and int(row[0]) > 0:
            return int(row[0]) + 1
    finally:
        cur.close()
    return _utc_ms(datetime.utcnow().replace(tzinfo=timezone.utc)) - 86400 * 30 * 1000  # ~30 days ago


def _upsert_open_interest(conn, records: list) -> None:
    if not records:
        return
    sql = """
    INSERT INTO btc_open_interest (timestamp, symbol, sum_open_interest, sum_open_interest_value)
    VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE sum_open_interest=VALUES(sum_open_interest), sum_open_interest_value=VALUES(sum_open_interest_value)
    """
    values = [
        (int(r["timestamp"]), r.get("symbol", BTC_SYMBOL), float(r["sumOpenInterest"]), float(r.get("sumOpenInterestValue", 0)) if r.get("sumOpenInterestValue") else None)
        for r in records
    ]
    cur = conn.cursor()
    try:
        cur.executemany(sql, values)
        conn.commit()
    finally:
        cur.close()


def sync_btc_open_interest_to_db(period: str = "5m") -> int:
    """Sync BTC open interest history to btc_open_interest. Returns total rows synced."""
    raw = engine.raw_connection()
    total = 0
    try:
        _ensure_btc_open_interest(raw)
        start_ms = _get_last_oi_time(raw)
        end_ms = _utc_ms(datetime.utcnow().replace(tzinfo=timezone.utc))
        if start_ms >= end_ms:
            return 0
        records = _fetch_open_interest_hist(BTC_SYMBOL, period=period, start_ms=start_ms, end_ms=end_ms, limit=500)
        if records:
            _upsert_open_interest(raw, records)
            total = len(records)
    except Exception as e:
        logger.warning("BTC open interest sync failed: %s", e)
    finally:
        raw.close()
    logger.info("BTC open interest sync done: %d rows", total)
    return total


def sync_all_cross_market() -> None:
    """Run all cross-market syncs: ETH 1m, BTC funding, BTC open interest."""
    sync_eth1m_to_db()
    time.sleep(0.3)
    sync_btc_funding_to_db()
    time.sleep(0.3)
    sync_btc_open_interest_to_db()
