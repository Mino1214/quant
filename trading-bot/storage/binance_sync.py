"""
서버 시작 시 Binance Futures → DB 동기화 (1m, 5m, 15m).
DB에 없는 구간을 Binance REST로 채워서 btc1m, btc5m, btc15m을 최신화.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from config.loader import load_config
from storage.database import engine

logger = logging.getLogger(__name__)

BINANCE_FAPI_BASE = "https://fapi.binance.com"
MAX_LIMIT = 1500
INTERVALS = ("1m", "5m", "15m")
TABLE_BY_INTERVAL = {"1m": "btc1m", "5m": "btc5m", "15m": "btc15m"}


def _utc_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _fetch_klines(symbol: str, interval: str, start_ms: int) -> list:
    url = f"{BINANCE_FAPI_BASE}/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "limit": MAX_LIMIT,
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _ensure_table(conn, table: str) -> None:
    ddl = f"""
    CREATE TABLE IF NOT EXISTS `{table}` (
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


def _get_last_open_time(conn, table: str, symbol: str) -> int:
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COALESCE(MAX(openTime), 0) FROM `{}` WHERE symbol = %s".format(table),
            (symbol,),
        )
        row = cursor.fetchone()
        if row and row[0] is not None and int(row[0]) > 0:
            return int(row[0]) + 1
    finally:
        cursor.close()
    return _utc_ms(datetime(2019, 1, 1, tzinfo=timezone.utc))


def _upsert_klines(conn, table: str, symbol: str, klines: list) -> None:
    if not klines:
        return
    sql = f"""
    INSERT INTO `{table}` (symbol, openTime, o, h, l, c, v, closeTime, createdAt)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        o=VALUES(o), h=VALUES(h), l=VALUES(l), c=VALUES(c), v=VALUES(v), closeTime=VALUES(closeTime)
    """
    now_ms = int(time.time() * 1000)
    values = [
        (
            symbol,
            int(k[0]),
            float(k[1]),
            float(k[2]),
            float(k[3]),
            float(k[4]),
            float(k[5]),
            int(k[6]),
            now_ms,
        )
        for k in klines
    ]
    cursor = conn.cursor()
    try:
        cursor.executemany(sql, values)
        conn.commit()
    finally:
        cursor.close()


def _sync_interval(raw_conn, symbol: str, interval: str, table: str) -> int:
    total = 0
    start_ms = _get_last_open_time(raw_conn, table, symbol)
    while True:
        klines = _fetch_klines(symbol, interval, start_ms)
        if not klines:
            break
        _upsert_klines(raw_conn, table, symbol, klines)
        total += len(klines)
        first_ts = int(klines[0][0])
        last_ts = int(klines[-1][0])
        logger.info(
            "[%s] saved %d | %s ~ %s",
            interval,
            len(klines),
            datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc),
            datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc),
        )
        start_ms = last_ts + 1
        time.sleep(0.2)
    return total


def backfill_1m(
    symbol: str,
    start_ms: int,
    end_ms: Optional[int] = None,
    table: str = "btc1m",
) -> int:
    """
    과거 1m 봉을 start_ms ~ end_ms(미지정 시 현재까지) 구간으로 Binance에서 가져와 table에 저장.
    candidate_signals 생성을 위해 최소 약 931봉(15*60+31) 이상 권장.
    """
    raw = engine.raw_connection()
    total = 0
    try:
        _ensure_table(raw, table)
        current = start_ms
        while True:
            klines = _fetch_klines(symbol, "1m", current)
            if not klines:
                break
            last_ts = int(klines[-1][0])
            if end_ms is not None and last_ts > end_ms:
                klines = [k for k in klines if int(k[0]) <= end_ms]
                if not klines:
                    break
                last_ts = int(klines[-1][0])
            _upsert_klines(raw, table, symbol, klines)
            total += len(klines)
            logger.info(
                "[1m backfill] saved %d | %s ~ %s (total %d)",
                len(klines),
                datetime.fromtimestamp(int(klines[0][0]) / 1000, tz=timezone.utc),
                datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc),
                total,
            )
            current = last_ts + 1
            if end_ms is not None and current > end_ms:
                break
            time.sleep(0.2)
    finally:
        raw.close()
    return total


def sync_binance_to_db(symbol: Optional[str] = None) -> None:
    """
    Binance Futures에서 1m, 5m, 15m을 가져와 DB(btc1m, btc5m, btc15m)에 최신화.
    config에서 symbol 사용. DB 연결은 get_database_url() 사용.
    """
    symbol = symbol or load_config().get("symbol", "BTCUSDT")
    # pymysql raw connection for executemany
    raw = engine.raw_connection()
    try:
        for interval in INTERVALS:
            table = TABLE_BY_INTERVAL[interval]
            try:
                _ensure_table(raw, table)
                n = _sync_interval(raw, symbol, interval, table)
                logger.info("[DONE] %s updated rows: %d", interval, n)
            except Exception as e:
                logger.warning("Sync %s failed: %s", interval, e)
            time.sleep(0.3)
    finally:
        raw.close()
    logger.info("Binance sync done for %s", symbol)
