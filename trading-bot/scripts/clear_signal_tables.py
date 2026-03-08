#!/usr/bin/env python3
"""
candidate_signals / signal_outcomes 테이블 비우기.
FK 제약 때문에 순서대로 삭제: signal_outcomes(자식) → candidate_signals(부모).

사용 예:
  cd trading-bot && PYTHONPATH=. python scripts/clear_signal_tables.py
  cd trading-bot && PYTHONPATH=. python scripts/clear_signal_tables.py --dry-run
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from storage.database import engine


def main():
    parser = argparse.ArgumentParser(description="Clear candidate_signals and signal_outcomes (FK-safe order)")
    parser.add_argument("--dry-run", action="store_true", help="Only print SQL, do not execute")
    args = parser.parse_args()

    # 자식 먼저, 부모 나중
    steps = [
        ("signal_outcomes", "DELETE FROM signal_outcomes"),
        ("candidate_signals", "DELETE FROM candidate_signals"),
    ]

    with engine.connect() as conn:
        for name, sql in steps:
            if args.dry_run:
                print(sql + ";")
                continue
            try:
                r = conn.execute(text(sql))
                conn.commit()
                print("%s: %d row(s) deleted" % (name, r.rowcount))
            except Exception as e:
                print("Error %s: %s" % (name, e), file=sys.stderr)
                sys.exit(1)

    if not args.dry_run:
        print("Done. Tables cleared in FK-safe order.")


if __name__ == "__main__":
    main()
