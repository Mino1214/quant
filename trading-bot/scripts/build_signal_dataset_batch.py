#!/usr/bin/env python3
"""
배치: 구간을 월 단위로 나눠 build_signal_dataset을 반복 실행.
메모리·시간 부담을 줄이고, 중간에 끊겨도 --skip-existing 로 이어서 실행 가능.
--workers N 이면 N개 청크를 동시에 처리해 속도 향상.

개선점:
- ProcessPoolExecutor 제거 → ThreadPoolExecutor 사용
  (이 작업은 CPU 바운드가 아니라 subprocess 대기라 스레드가 더 적합)
- 기본 chunk-months 확대 (기본 6)
- 진행 로그를 완료 순서대로 바로 확인 가능
- 큰 청크 기준으로 실행해 subprocess startup overhead 감소

사용 예:
  cd trading-bot && PYTHONPATH=. python scripts/build_signal_dataset_batch.py --from 2020-01-01 --to 2024-12-31
  cd trading-bot && PYTHONPATH=. python scripts/build_signal_dataset_batch.py --from 2020-01-01 --to 2026-03-07 --workers 4 --chunk-months 6
"""
import argparse
import calendar
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_ENV = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}


def _run_chunk(symbol: str, table: str, start: str, end: str) -> tuple[str, str, int]:
    """한 청크 구간 실행. 반환 (start, end, returncode)."""
    cmd = [
        sys.executable,
        "-m",
        "scripts.build_signal_dataset",
        "--start", start,
        "--end", end,
        "--skip-existing",
        "--symbol", symbol,
        "--table", table,
    ]

    logger.info("START %s ~ %s", start, end)

    r = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=BASE_ENV,
    )
    return (start, end, r.returncode)


def month_range(start: datetime, end: datetime):
    """Yield (start_date, end_date) for each month in [start, end]."""
    y, m = start.year, start.month
    end_y, end_m = end.year, end.month

    while (y, m) <= (end_y, end_m):
        last_day = calendar.monthrange(y, m)[1]
        month_start = datetime(y, m, 1, tzinfo=timezone.utc)
        month_end = datetime(y, m, last_day, 23, 59, 59, tzinfo=timezone.utc)

        s = max(month_start, start)
        e = min(month_end, end)

        if s <= e:
            yield (s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"))

        y, m = (y, m + 1) if m < 12 else (y + 1, 1)


def group_months(months: list[tuple[str, str]], chunk_months: int) -> list[tuple[str, str]]:
    """월 범위를 chunk_months 개씩 묶어서 큰 실행 청크를 만든다."""
    if chunk_months <= 1:
        return months

    grouped = []
    for i in range(0, len(months), chunk_months):
        chunk = months[i:i + chunk_months]
        grouped.append((chunk[0][0], chunk[-1][1]))
    return grouped


def main():
    parser = argparse.ArgumentParser(
        description="Run build_signal_dataset in date chunks. Uses --skip-existing so you can resume."
    )
    parser.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD", required=False, help="Start date")
    parser.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD", required=False, help="End date")
    parser.add_argument("--days", type=int, default=None, help="Last N days from today (UTC)")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--table", type=str, default="btc1m")
    parser.add_argument("--workers", "-j", type=int, default=4, help="병렬 처리할 청크 개수 (기본 4)")
    parser.add_argument("--chunk-months", type=int, default=6, help="한 번에 몇 개월씩 묶어 처리할지 (기본 6)")
    parser.add_argument("--dry-run", action="store_true", help="Only print chunk ranges, do not run")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)

    if args.days is not None:
        start = now - timedelta(days=args.days)
        end = now
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
    elif args.from_date and args.to_date:
        start_str = args.from_date
        end_str = args.to_date
        start = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(end_str + " 23:59:59", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    else:
        parser.error("Provide --from and --to, or --days N")

    months = list(month_range(start, end))
    chunks = group_months(months, args.chunk_months)

    logger.info(
        "Batch: %s ~ %s → %d month(s), grouped into %d chunk(s), chunk_months=%d",
        start_str, end_str, len(months), len(chunks), args.chunk_months
    )

    if args.dry_run:
        for s, e in chunks:
            print(f"  --start {s} --end {e}")
        return

    workers = max(1, int(args.workers))
    failed = []

    if workers <= 1:
        for i, (s, e) in enumerate(chunks, 1):
            logger.info("--- [%d/%d] %s ~ %s ---", i, len(chunks), s, e)
            try:
                _, _, code = _run_chunk(args.symbol, args.table, s, e)
                if code != 0:
                    failed.append((s, e))
                    logger.warning("Exit code %d for %s ~ %s", code, s, e)
            except Exception as ex:
                failed.append((s, e))
                logger.exception("Failed %s ~ %s: %s", s, e, ex)
    else:
        logger.info("Running %d chunk(s) with %d workers", len(chunks), workers)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_run_chunk, args.symbol, args.table, s, e): (s, e)
                for s, e in chunks
            }

            done_count = 0
            for future in as_completed(futures):
                s, e = futures[future]
                done_count += 1
                try:
                    _, _, code = future.result()
                    if code != 0:
                        failed.append((s, e))
                        logger.warning("[%d/%d] Exit %d %s ~ %s", done_count, len(chunks), code, s, e)
                    else:
                        logger.info("[%d/%d] OK %s ~ %s", done_count, len(chunks), s, e)
                except Exception as ex:
                    failed.append((s, e))
                    logger.exception("[%d/%d] Failed %s ~ %s: %s", done_count, len(chunks), s, e, ex)

    if failed:
        logger.warning("Failed %d chunk(s): %s", len(failed), failed)
        sys.exit(1)

    logger.info("Batch done: all %d chunk(s) completed.", len(chunks))


if __name__ == "__main__":
    main()