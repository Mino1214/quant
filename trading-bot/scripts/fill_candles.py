#!/usr/bin/env python3
"""
DB에 캔들 데이터 채우기: Binance Futures REST에서 1m(필수) / 5m / 15m 가져와서 MySQL에 저장.

사용법 (프로젝트 루트에서):
  cd /Users/myno/Desktop/quant/trading-bot
  export DATABASE_URL="mysql+pymysql://user:pass@host/db?charset=utf8mb4"

  # 최근 7일 1m만 채우기
  PYTHONPATH=. python3 scripts/fill_candles.py

  # 최근 30일 1m + 5m + 15m 채우기
  PYTHONPATH=. python3 scripts/fill_candles.py --days 30 --5m --15m

  # 심볼/테이블 지정
  PYTHONPATH=. python3 scripts/fill_candles.py --symbol BTCUSDT --days 3 --5m --15m
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timedelta

from config.loader import load_config
from market.binance_rest import fetch_klines, last_closed_minute_utc
from storage.candle_persistence import save_candle_1m, save_candle_5m, save_candle_15m

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def run(
    symbol: str,
    days: int,
    do_5m: bool,
    do_15m: bool,
    table_1m: str,
    table_5m: str,
    table_15m: str,
) -> None:
    end = last_closed_minute_utc()
    start = end - timedelta(days=days)
    logger.info("Filling candles: %s from %s to %s (%d days)", symbol, start, end, days)

    # 1m
    candles_1m = await fetch_klines(symbol, "1m", start, end, limit=1500)
    logger.info("Fetched %d x 1m candles from Binance", len(candles_1m))
    for i, c in enumerate(candles_1m):
        save_candle_1m(c, table=table_1m, symbol=symbol)
        if (i + 1) % 500 == 0:
            logger.info("Saved 1m %d / %d", i + 1, len(candles_1m))
    logger.info("Saved 1m -> %s (%d rows)", table_1m, len(candles_1m))

    if do_5m:
        candles_5m = await fetch_klines(symbol, "5m", start, end, limit=1500)
        logger.info("Fetched %d x 5m candles", len(candles_5m))
        for c in candles_5m:
            save_candle_5m(c, table=table_5m, symbol=symbol)
        logger.info("Saved 5m -> %s (%d rows)", table_5m, len(candles_5m))

    if do_15m:
        candles_15m = await fetch_klines(symbol, "15m", start, end, limit=1500)
        logger.info("Fetched %d x 15m candles", len(candles_15m))
        for c in candles_15m:
            save_candle_15m(c, table=table_15m, symbol=symbol)
        logger.info("Saved 15m -> %s (%d rows)", table_15m, len(candles_15m))

    logger.info("Done. Run API with RUN_ENGINE=1 so gap-fill + socket stay in sync.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill DB (btc1m, btc5m, btc15m) from Binance Futures.")
    parser.add_argument("--symbol", type=str, default=None, help="Symbol (default: config)")
    parser.add_argument("--days", type=int, default=7, help="Days of history to fetch (default 7)")
    parser.add_argument("--5m", dest="do_5m", action="store_true", help="Also fetch and save 5m")
    parser.add_argument("--15m", dest="do_15m", action="store_true", help="Also fetch and save 15m")
    parser.add_argument("--table-1m", type=str, default="btc1m", help="Table for 1m (default btc1m)")
    parser.add_argument("--table-5m", type=str, default="btc5m", help="Table for 5m (default btc5m)")
    parser.add_argument("--table-15m", type=str, default="btc15m", help="Table for 15m (default btc15m)")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        try:
            load_config()
        except Exception:
            pass
        if not os.environ.get("DATABASE_URL"):
            logger.error("Set DATABASE_URL (e.g. export DATABASE_URL='mysql+pymysql://...')")
            sys.exit(1)

    config = load_config()
    symbol = args.symbol or config.get("symbol", "BTCUSDT")

    asyncio.run(
        run(
            symbol=symbol,
            days=args.days,
            do_5m=args.do_5m,
            do_15m=args.do_15m,
            table_1m=args.table_1m,
            table_5m=args.table_5m,
            table_15m=args.table_15m,
        )
    )


if __name__ == "__main__":
    main()
