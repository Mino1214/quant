#!/usr/bin/env python3
"""
과거 1m 봉을 Binance에서 받아 btc1m 테이블에 채움.
candidate_signals / build_dataset을 쓰려면 최소 약 1000봉 이상 권장(931+).

사용 예:
  cd trading-bot && PYTHONPATH=. python scripts/backfill_1m.py --days 7
  cd trading-bot && PYTHONPATH=. python scripts/backfill_1m.py --days 30
  cd trading-bot && PYTHONPATH=. python scripts/backfill_1m.py --from 2024-01-01 --to 2024-01-31
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _utc_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def main():
    parser = argparse.ArgumentParser(description="Backfill 1m candles from Binance into btc1m")
    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol (default: BTCUSDT)")
    parser.add_argument("--days", type=int, default=None, help="최근 N일치 백필 (예: 7, 30)")
    parser.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD", default=None, help="시작일")
    parser.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD", default=None, help="종료일(미지정 시 오늘)")
    parser.add_argument("--table", default="btc1m", help="DB 테이블 (default: btc1m)")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    if args.days is not None:
        start_dt = now - timedelta(days=args.days)
        end_dt = now
        start_ms = _utc_ms(start_dt)
        end_ms = _utc_ms(end_dt)
    elif args.from_date:
        start_dt = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.to_date:
            end_dt = datetime.strptime(args.to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(microseconds=1)
        else:
            end_dt = now
        start_ms = _utc_ms(start_dt)
        end_ms = _utc_ms(end_dt)
    else:
        print("--days N 또는 --from YYYY-MM-DD [--to YYYY-MM-DD] 중 하나를 지정하세요.")
        sys.exit(1)

    from storage.binance_sync import backfill_1m
    n = backfill_1m(args.symbol, start_ms, end_ms, table=args.table)
    print("Backfill done: %d 1m candles saved to %s" % (n, args.table))


if __name__ == "__main__":
    main()
