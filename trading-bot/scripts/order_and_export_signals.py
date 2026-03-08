"""
candidate_signals + signal_outcomes 를 항상 시간순으로 조회/내보내기.

Worker 병렬 처리로 id 순서가 시간 순이 아닐 수 있으므로,
조회 시 ORDER BY time(또는 timestamp), id 로 정렬해 사용.

SQL만 쓰고 싶으면: scripts/sql/query_signals_ordered.sql 참고.

Usage:
  # 시간순 정렬된 행 수 확인
  python -m scripts.order_and_export_signals --check

  # CSV로 내보내기 (parameter scan 등에서 사용 가능)
  python -m scripts.order_and_export_signals --export output/ordered_signals.csv [--symbol BTCUSDT] [--limit 50000]
"""
import argparse
import csv
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.database import SessionLocal, init_db
from storage.repositories import get_candidate_signals_with_outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description="Order candidate_signals+outcomes by time and optionally export")
    parser.add_argument("--check", action="store_true", help="Print row count and first/last time (no export)")
    parser.add_argument("--export", type=str, default="", metavar="PATH", help="Export to CSV (time-ordered)")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=100_000)
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        rows = get_candidate_signals_with_outcomes(db, symbol=args.symbol, limit=args.limit)
        if not rows:
            print("No rows (empty or no outcomes).")
            return

        # 이미 time ASC, id ASC 로 정렬된 상태
        first_ts = rows[0].get("time") or rows[0].get("timestamp")
        last_ts = rows[-1].get("time") or rows[-1].get("timestamp")
        print(f"Rows: {len(rows)} (ordered by time asc)")
        print(f"First: {first_ts}  Last: {last_ts}")

        if args.check:
            return

        if args.export:
            out_path = Path(args.export)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            keys = list(rows[0].keys())
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            print(f"Exported: {out_path} ({len(rows)} rows, time-ordered)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
