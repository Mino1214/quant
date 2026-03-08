"""
Walk-forward validation: train/test date splits, run backtest on test period, store results.
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import TradeRecord

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _metrics_from_trades(trades: List[TradeRecord]) -> dict:
    """Compute profit_factor, avg_R, drawdown from trade list."""
    if not trades:
        return {"profit_factor": 0.0, "avg_R": 0.0, "drawdown": 0.0}
    n = len(trades)
    total_r = sum(t.rr for t in trades)
    avg_R = total_r / n
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cum += t.pnl
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {"profit_factor": min(profit_factor, 100.0), "avg_R": avg_R, "drawdown": max_dd}


async def run_one_fold(
    test_start: datetime,
    test_end: datetime,
    train_start: datetime,
    train_end: datetime,
    symbol: str = "BTCUSDT",
    table: str = "btc1m",
    strategy_name: str = "mtf_ema_pullback",
) -> dict:
    """
    Load 1m from train_start to test_end, run backtest, keep only trades closed in [test_start, test_end], return metrics.
    """
    from storage.candle_loader import load_1m_from_db
    from backtest.backtest_runner import run_backtest

    candles = load_1m_from_db(
        table=table,
        start_ts=train_start,
        end_ts=test_end,
        symbol=symbol,
    )
    if len(candles) < 900:
        logger.warning("Insufficient candles for fold test_end=%s", test_end)
        return {
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "profit_factor": 0.0,
            "avg_R": 0.0,
            "drawdown": 0.0,
            "stability_score": 0.0,
            "strategy_name": strategy_name,
        }

    trades, _, _ = await run_backtest(candles, symbol=symbol, config=None, verbose=False)
    # Only trades that closed in test window
    test_trades = [t for t in trades if test_start <= t.closed_at <= test_end]
    m = _metrics_from_trades(test_trades)
    m["train_start"] = train_start
    m["train_end"] = train_end
    m["test_start"] = test_start
    m["test_end"] = test_end
    m["strategy_name"] = strategy_name
    m["stability_score"] = 0.0  # set after multiple folds
    return m


def run_walk_forward(
    folds: List[Tuple[datetime, datetime, datetime, datetime]],
    symbol: str = "BTCUSDT",
    table: str = "btc1m",
    strategy_name: str = "mtf_ema_pullback",
) -> List[dict]:
    """Run all folds and compute stability_score from avg_R variance across folds."""
    async def _run():
        results = []
        for train_start, train_end, test_start, test_end in folds:
            r = await run_one_fold(
                test_start, test_end, train_start, train_end,
                symbol=symbol, table=table, strategy_name=strategy_name,
            )
            results.append(r)
        return results

    results = asyncio.run(_run())
    # stability_score: higher when avg_R is stable across folds (e.g. 1 / (1 + std(avg_R)))
    if len(results) >= 2:
        avg_rs = [r["avg_R"] for r in results]
        import numpy as np
        std_r = float(np.std(avg_rs))
        for r in results:
            r["stability_score"] = 1.0 / (1.0 + std_r) if std_r >= 0 else 1.0
    return results


def save_walk_forward_results(results: List[dict]) -> None:
    """Persist to walk_forward_results table."""
    from datetime import datetime as dt
    from storage.database import SessionLocal, init_db
    from storage.models import WalkForwardResultModel
    init_db()
    db = SessionLocal()
    try:
        for r in results:
            row = WalkForwardResultModel(
                train_start=r.get("train_start"),
                train_end=r.get("train_end"),
                test_start=r.get("test_start"),
                test_end=r.get("test_end"),
                profit_factor=r.get("profit_factor"),
                avg_R=r.get("avg_R"),
                drawdown=r.get("drawdown"),
                stability_score=r.get("stability_score"),
                strategy_name=r.get("strategy_name", "mtf_ema_pullback"),
                created_at=dt.utcnow(),
            )
            db.add(row)
        db.commit()
        logger.info("Saved %d walk-forward results", len(results))
    finally:
        db.close()


def default_folds() -> List[Tuple[datetime, datetime, datetime, datetime]]:
    """Example: train 2019-2022, test 2023; train 2020-2023, test 2024."""
    return [
        (datetime(2019, 1, 1), datetime(2022, 12, 31), datetime(2023, 1, 1), datetime(2023, 12, 31)),
        (datetime(2020, 1, 1), datetime(2023, 12, 31), datetime(2024, 1, 1), datetime(2024, 12, 31)),
    ]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--table", type=str, default="btc1m")
    parser.add_argument("--save-db", action="store_true")
    args = parser.parse_args()
    folds = default_folds()
    results = run_walk_forward(folds, symbol=args.symbol, table=args.table)
    for r in results:
        logger.info("Fold test %s–%s: profit_factor=%.2f avg_R=%.2f drawdown=%.2f", r["test_start"].date(), r["test_end"].date(), r["profit_factor"], r["avg_R"], r["drawdown"])
    if args.save_db:
        save_walk_forward_results(results)
