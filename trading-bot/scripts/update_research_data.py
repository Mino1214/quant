#!/usr/bin/env python3
"""
Update research data platform: feature_store_1m and outcome_store_1m.

Usage:
  python -m scripts.update_research_data --symbols BTCUSDT
  python -m scripts.update_research_data --all-symbols

- Raw candles (btc1m/5m/15m)은 storage/binance_sync.py가 채운다고 가정.
- 이 스크립트는 feature_store_1m / outcome_store_1m 을 증분 업데이트만 수행한다.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.loader import load_symbols  # noqa: E402
from features.feature_builder_1m import update_feature_store  # noqa: E402
from analysis.outcome_builder import update_outcome_store  # noqa: E402
from storage.database import init_db  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Update feature_store_1m and outcome_store_1m incrementally")
    parser.add_argument("--symbols", nargs="*", default=None, help="Symbols to update (default: config symbols)")
    parser.add_argument("--all-symbols", action="store_true", help="Use all symbols from config/symbols.json")
    args = parser.parse_args()

    init_db()

    if args.all_symbols or not args.symbols:
        symbols = load_symbols()
    else:
        symbols = args.symbols

    logger.info("Updating research data for symbols: %s", symbols)
    update_feature_store(symbols)
    update_outcome_store(symbols)
    logger.info("Done updating research data.")


if __name__ == "__main__":
    main()

