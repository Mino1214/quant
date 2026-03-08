"""
Binance Futures USDT-M REST: 1m klines for gap-fill.
"""
import logging
from datetime import datetime, timedelta
from typing import List

import aiohttp

from core.models import Candle, Timeframe

logger = logging.getLogger(__name__)

BASE = "https://fapi.binance.com/fapi/v1/klines"


async def fetch_klines_1m(
    symbol: str,
    start_time: datetime,
    end_time: datetime | None = None,
    limit: int = 1000,
) -> List[Candle]:
    """
    Fetch 1m klines from Binance Futures. start_time/end_time in UTC.
    Returns list of Candle in order. Max 1500 per request.
    """
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000) if end_time else None
    params = {
        "symbol": symbol.upper(),
        "interval": "1m",
        "startTime": start_ms,
        "limit": min(limit, 1500),
    }
    if end_ms is not None:
        params["endTime"] = end_ms

    out: List[Candle] = []
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(BASE, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("Binance klines %s: %s %s", resp.status, params, text[:200])
                    break
                data = await resp.json()
            if not data:
                break
            for row in data:
                # [open_time, open, high, low, close, volume, ...]
                ts = datetime.utcfromtimestamp(row[0] / 1000.0)
                out.append(
                    Candle(
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                        timestamp=ts,
                        timeframe=Timeframe.M1,
                    )
                )
            if len(data) < limit:
                break
            params["startTime"] = data[-1][0] + 60_000  # next minute
            if end_ms and params["startTime"] >= end_ms:
                break
    return out


async def fetch_klines(
    symbol: str,
    interval: str,
    start_time: datetime,
    end_time: datetime | None = None,
    limit: int = 1500,
) -> List[Candle]:
    """
    Fetch klines from Binance Futures. interval: "1m", "5m", "15m".
    Returns list of Candle in order. Paginates automatically.
    """
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000) if end_time else None
    tf = Timeframe.M1
    if interval == "5m":
        tf = Timeframe.M5
    elif interval == "15m":
        tf = Timeframe.M15
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "startTime": start_ms,
        "limit": min(limit, 1500),
    }
    if end_ms is not None:
        params["endTime"] = end_ms
    out: List[Candle] = []
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(BASE, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("Binance klines %s: %s %s", resp.status, params, text[:200])
                    break
                data = await resp.json()
            if not data:
                break
            for row in data:
                ts = datetime.utcfromtimestamp(row[0] / 1000.0)
                out.append(
                    Candle(
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                        timestamp=ts,
                        timeframe=tf,
                    )
                )
            if len(data) < limit:
                break
            step_ms = {"1m": 60_000, "5m": 5 * 60_000, "15m": 15 * 60_000}.get(interval, 60_000)
            params["startTime"] = data[-1][0] + step_ms
            if end_ms and params["startTime"] >= end_ms:
                break
    return out


def last_closed_minute_utc() -> datetime:
    """UTC 기준 마지막으로 마감된 1m 봉 시각 (현재 분은 아직 미마감)."""
    now = datetime.utcnow()
    return now.replace(second=0, microsecond=0) - timedelta(minutes=1)


async def fill_gap_1m(engine, symbol: str) -> int:
    """
    없는데이터(누락 구간)를 Binance REST로 채움 → 소켓으로 받는 봉과 연속되게.
    state 마지막 시각 다음 ~ 방금 마감된 1분까지 1m만 채움. 버퍼 비어 있으면 최근 750분.
    """
    state = engine.state
    end = last_closed_minute_utc()
    lst = state.get_1m_list()
    if lst:
        last_ts = lst[-1].timestamp
        start = last_ts.replace(second=0, microsecond=0) + timedelta(minutes=1)
    else:
        start = end - timedelta(minutes=750)
    if start >= end:
        logger.info("No 1m gap to fill (already up to %s)", end)
        return 0
    gap_mins = int((end - start).total_seconds() // 60)
    logger.info("Filling missing 1m data: %s ~ %s (%d minutes) so socket stays in sync", start, end, gap_mins)
    candles = await fetch_klines_1m(symbol, start, end, limit=1500)
    for c in candles:
        engine._on_1m_closed(c, quiet=True)
    if candles:
        logger.info("Gap fill done: %d 1m candles (sync with socket from here)", len(candles))
    return len(candles)
