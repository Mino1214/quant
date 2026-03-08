"""
Binance Futures WebSocket: 1m / 5m / 15m kline streams. Reconnect logic and Candle emission.
마감 봉(x=true)을 구간별(1m/5m/15m)로 확인해서 해당 테이블에 저장·엔진 반영.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Callable

import aiohttp

from core.models import Candle, Timeframe

logger = logging.getLogger(__name__)

BINANCE_FUTURES_WS = "wss://fstream.binance.com"
# 단일: /ws/<stream>  복합: /stream?streams=a/b/c
INTERVAL_TO_TIMEFRAME = {"1m": Timeframe.M1, "5m": Timeframe.M5, "15m": Timeframe.M15}


def _parse_kline(payload: dict) -> tuple[Candle, bool, str]:
    """
    Parse Binance kline event. Returns (Candle, is_final, interval).
    payload: 루트에 "k" 있거나, combined stream이면 payload["data"]에 "k" 있음.
    """
    data = payload.get("data", payload)
    k = data.get("k", {})
    is_closed = k.get("x", False)
    if isinstance(is_closed, str):
        is_closed = is_closed.lower() == "true"
    interval = k.get("i", "1m")
    tf = INTERVAL_TO_TIMEFRAME.get(interval, Timeframe.M1)
    ts = datetime.utcfromtimestamp(int(k["t"]) / 1000)
    candle = Candle(
        open=float(k["o"]),
        high=float(k["h"]),
        low=float(k["l"]),
        close=float(k["c"]),
        volume=float(k["v"]),
        timestamp=ts,
        timeframe=tf,
    )
    return candle, is_closed, interval


async def run_binance_kline_ws(
    symbol: str,
    on_candle: Callable[[Candle, bool, str], None],
    reconnect_delay: float = 5.0,
) -> None:
    """
    Connect to 1m + 5m + 15m combined stream.
    on_candle(candle, is_closed, interval): interval은 "1m" | "5m" | "15m".
    마감 봉만 DB 저장·1m이면 엔진에 전달.
    """
    s = symbol.lower()
    streams = f"{s}@kline_1m/{s}@kline_5m/{s}@kline_15m"
    url = f"{BINANCE_FUTURES_WS}/stream?streams={streams}"
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url) as ws:
                    logger.info("WebSocket connected: 1m/5m/15m %s", url)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            raw = json.loads(msg.data)
                            data = raw.get("data", raw)
                            if "k" not in data:
                                continue
                            candle, is_closed, interval = _parse_kline(raw)
                            on_candle(candle, is_closed, interval)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("WebSocket error: %s, reconnecting in %ss", e, reconnect_delay)
        await asyncio.sleep(reconnect_delay)
