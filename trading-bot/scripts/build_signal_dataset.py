"""
Build continuous signal dataset from historical 1m data.
Same logic as backtest (rolling 5m/15m, evaluate_candidate, regime, approval) but only records
candidate signals + outcomes to DB; no position simulation.
Run from project root: python -m scripts.build_signal_dataset [options]
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.loader import (
    get_approval_settings,
    get_regime_settings,
    get_risk_settings,
    get_strategy_settings,
    load_config,
)
from core.models import CandidateSignalRecord, Candle, Direction
from risk.risk_manager import RiskManager, compute_stop_loss, compute_quantity
from strategy.approval_engine import ApprovalContext, score as approval_score
from strategy.feature_extractor import extract_feature_values
from strategy.filters.market_regime import MarketRegimeFilter
from strategy.mtf_ema_pullback import evaluate_candidate
from storage.candle_loader import load_1m_from_db
from storage.database import init_db
from storage.models import CandidateSignalModel
from storage.signal_dataset_logger import log_candidate_signal, save_signal_outcome
from storage.signal_outcome import compute_outcome_for_signal

# Reuse backtest rolling logic
from backtest.backtest_runner import N_15M, rolling_5m_15m

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_dataset(
    candles_1m: list,
    symbol: str,
    config: dict,
    skip_existing_times: set = None,
) -> tuple[int, int]:
    """
    One pass over 1m candles: emit candidate signals (executed/blocked), persist to DB, compute outcomes.
    skip_existing_times: set of (symbol, time) or (time,) to skip already-logged signals.
    Returns (count_logged, count_skipped).
    """
    skip_existing_times = skip_existing_times or set()
    cfg = config or load_config()
    strat_settings = get_strategy_settings(cfg)
    risk_settings = get_risk_settings(cfg)
    regime_settings = get_regime_settings(cfg)
    approval_settings = get_approval_settings(cfg)
    regime_filter = MarketRegimeFilter(regime_settings) if regime_settings and getattr(regime_settings, "enabled", True) else None
    risk_mgr = RiskManager(risk_settings)

    need_bars = 15 * N_15M  # minimum for 15m
    outcome_bars = 31  # need 30 bars after for future_r_30
    count_logged = 0
    count_skipped = 0

    for i in range(need_bars, len(candles_1m) - outcome_bars):
        bar = candles_1m[i]
        window_1m = candles_1m[: i + 1]
        candles_5m, candles_15m = rolling_5m_15m(window_1m, n_bars=N_15M)
        if len(candles_5m) < 50 or len(candles_15m) < 55:
            continue

        # Skip if already in DB
        if (symbol, bar.timestamp) in skip_existing_times:
            count_skipped += 1
            continue

        regime_result = None
        if regime_filter is not None:
            regime_result = regime_filter.evaluate(candles_15m)
            if not regime_result.allow_trading:
                continue

        candidate = evaluate_candidate(candles_15m, candles_5m, window_1m, strat_settings, symbol)
        if candidate is None:
            continue
        if regime_result is not None:
            if candidate.direction == Direction.LONG and not regime_result.can_long:
                continue
            if candidate.direction == Direction.SHORT and not regime_result.can_short:
                continue

        entry_price = bar.close
        stop_loss = compute_stop_loss(entry_price, candidate.direction, window_1m, risk_settings)
        ctx = ApprovalContext(
            candles_1m=window_1m,
            candles_5m=candles_5m,
            candles_15m=candles_15m,
            entry_price=entry_price,
            stop_loss=stop_loss,
            regime_result=regime_result,
        )
        result = approval_score(
            candidate, ctx, approval_settings, strat_settings, risk_settings,
        )
        regime_str = regime_result.regime.value if regime_result is not None else "UNKNOWN"
        features = extract_feature_values(window_1m, candles_5m, strat_settings)

        if not result.allowed:
            trade_outcome = "blocked"
            blocked_reason = result.blocked_reason
            approval_score_val = result.total_score
        else:
            check = risk_mgr.can_trade(bar.timestamp, risk_settings.cooldown_bars)
            if not check.allowed:
                trade_outcome = "blocked"
                blocked_reason = check.reason_code or "risk"
                approval_score_val = result.total_score
            else:
                qty = compute_quantity(10000.0, entry_price, stop_loss, candidate.direction, risk_settings)
                if qty <= 0:
                    trade_outcome = "blocked"
                    blocked_reason = "qty<=0"
                    approval_score_val = result.total_score
                else:
                    trade_outcome = "executed"
                    blocked_reason = None
                    approval_score_val = result.total_score

        record = CandidateSignalRecord(
            timestamp=bar.timestamp,
            entry_price=entry_price,
            regime=regime_str,
            trend_direction=candidate.direction,
            approval_score=approval_score_val,
            feature_values=features,
            trade_outcome=trade_outcome,
            blocked_reason=blocked_reason,
            symbol=symbol,
        )
        cid = log_candidate_signal(record)
        if cid is None:
            continue
        count_logged += 1

        candles_after = candles_1m[i + 1 : i + 1 + outcome_bars]
        outcome = compute_outcome_for_signal(
            cid, candles_after, entry_price, stop_loss, candidate.direction,
        )
        save_signal_outcome(outcome)

    return count_logged, count_skipped


def load_existing_times(symbol: str) -> set:
    """Load (symbol, time) pairs already in candidate_signals for skip_existing."""
    init_db()
    from storage.database import SessionLocal
    db = SessionLocal()
    try:
        rows = db.query(CandidateSignalModel).filter(CandidateSignalModel.symbol == symbol).all()
        return {(symbol, r.time) for r in rows}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build signal dataset from historical 1m candles")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--table", type=str, default="btc1m")
    parser.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=None, help="Max 1m rows to load (oldest first)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip bars already in candidate_signals")
    args = parser.parse_args()

    start_ts = None
    end_ts = None
    if args.start:
        start_ts = datetime.strptime(args.start, "%Y-%m-%d")
    if args.end:
        end_ts = datetime.strptime(args.end + " 23:59:59", "%Y-%m-%d %H:%M:%S")

    logger.info("Loading 1m candles from %s symbol=%s start=%s end=%s limit=%s", args.table, args.symbol, args.start, args.end, args.limit)
    candles_1m = load_1m_from_db(
        table=args.table,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=args.limit,
        symbol=args.symbol,
    )
    if not candles_1m:
        logger.warning("No candles loaded")
        return
    logger.info("Loaded %d 1m candles from %s to %s", len(candles_1m), candles_1m[0].timestamp, candles_1m[-1].timestamp)

    skip_set = load_existing_times(args.symbol) if args.skip_existing else set()
    if skip_set:
        logger.info("Skipping %d existing (symbol, time) pairs", len(skip_set))

    config = load_config()
    logged, skipped = build_dataset(candles_1m, args.symbol, config, skip_existing_times=skip_set)
    logger.info("Done: logged=%d skipped=%d", logged, skipped)


if __name__ == "__main__":
    main()
