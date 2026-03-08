#!/usr/bin/env python3
"""
Build continuous signal dataset from historical 1m data.
Same logic as backtest (rolling 5m/15m, evaluate_candidate, regime, approval) but only records
candidate signals + outcomes to DB; no position simulation.
Run from project root: python -m scripts.build_signal_dataset [options]

최적화 포인트:
- 전체 1m 봉을 전부 expensive path로 태우지 않고, cheap prefilter 후 후보만 평가
- skip_existing 조회 시 전체 row 로드 대신 time 컬럼만, 그리고 기간 범위로 제한
- (symbol, time) tuple 대신 time int set만 사용해서 membership check 경량화
"""
import argparse
import logging
import math
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
    get_use_trend_filter,
    load_config,
)
from core.models import CandidateSignalRecord, Direction
from risk.risk_manager import RiskManager, compute_stop_loss, compute_quantity
from strategy.approval_engine import ApprovalContext, score as approval_score
from strategy.feature_extractor import extract_feature_values
from strategy.filters.market_regime import MarketRegimeFilter
from strategy.mtf_ema_pullback import evaluate_candidate
from storage.candle_loader import load_1m_from_db, load_1m_last_n
from storage.database import init_db
from storage.models import CandidateSignalModel
from storage.signal_dataset_logger import log_candidate_signal, save_signal_outcome
from storage.signal_outcome import compute_outcome_for_signal

# Reuse backtest rolling logic
from backtest.backtest_runner import N_15M, rolling_5m_15m

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# -----------------------------
# cheap prefilter utilities
# -----------------------------
def _ema_list(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    out = [values[0]]
    prev = values[0]
    for v in values[1:]:
        prev = alpha * v + (1.0 - alpha) * prev
        out.append(prev)
    return out


def _rolling_mean(values: list[float], window: int) -> list[float | None]:
    out = [None] * len(values)
    if window <= 0 or len(values) < window:
        return out

    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out[i] = running / window
    return out


def _build_candidate_indices(candles_1m: list, strat_settings, need_bars: int, outcome_bars: int) -> list[int]:
    """
    빠른 1차 후보 필터.
    expensive path(rolling_5m_15m / evaluate_candidate) 전 단계에서 obvious non-candidate 제거.
    """
    closes = [float(c.close) for c in candles_1m]
    volumes = [float(c.volume) for c in candles_1m]

    ema_fast = _ema_list(closes, getattr(strat_settings, "ema_fast", 8))
    ema_slow = _ema_list(closes, getattr(strat_settings, "ema_slow", 50))
    vol_ma = _rolling_mean(volumes, getattr(strat_settings, "volume_ma_period", 20))

    # 설정값이 너무 강하면 후보가 0개가 될 수 있으니, prefilter는 본 필터보다 약하게 적용
    raw_ema_dist = float(getattr(strat_settings, "ema_distance_threshold", 0.0) or 0.0)
    raw_vol_mult = float(getattr(strat_settings, "volume_multiplier", 0.0) or 0.0)

    pre_ema_dist = raw_ema_dist * 0.5 if raw_ema_dist > 0 else 0.0
    pre_vol_mult = min(raw_vol_mult, 1.0) if raw_vol_mult > 0 else 0.0

    candidate_idx: list[int] = []

    start_i = need_bars
    end_i = len(candles_1m) - outcome_bars

    for i in range(start_i, end_i):
        close = closes[i]
        if close <= 0:
            continue

        ema_dist = abs(ema_fast[i] - ema_slow[i]) / close
        if ema_dist < pre_ema_dist:
            continue

        vma = vol_ma[i]
        if vma is not None and vma > 0 and pre_vol_mult > 0:
            vratio = volumes[i] / vma
            if vratio < pre_vol_mult:
                continue

        candidate_idx.append(i)

    logger.info(
        "Cheap prefilter: %d / %d bars survived (%.2f%%)",
        len(candidate_idx),
        max(1, end_i - start_i),
        (len(candidate_idx) / max(1, end_i - start_i)) * 100.0,
    )
    return candidate_idx


def build_dataset(
    candles_1m: list,
    symbol: str,
    config: dict,
    skip_existing_times: set[int] | None = None,
) -> tuple[int, int]:
    """
    One pass over filtered 1m candidate bars:
    emit candidate signals (executed/blocked), persist to DB, compute outcomes.
    skip_existing_times: set[int(timestamp)] to skip already-logged signals.
    Returns (count_logged, count_skipped).
    """
    skip_existing_times = skip_existing_times or set()

    cfg = config or load_config()
    strat_settings = get_strategy_settings(cfg)
    risk_settings = get_risk_settings(cfg)
    regime_settings = get_regime_settings(cfg)
    approval_settings = get_approval_settings(cfg)

    regime_filter = (
        MarketRegimeFilter(regime_settings)
        if regime_settings and getattr(regime_settings, "enabled", True)
        else None
    )
    risk_mgr = RiskManager(risk_settings)

    need_bars = 15 * N_15M          # minimum for 15m
    outcome_bars = 31               # need 30 bars after for future_r_30
    count_logged = 0
    count_skipped = 0

    candidate_indices = _build_candidate_indices(
        candles_1m=candles_1m,
        strat_settings=strat_settings,
        need_bars=need_bars,
        outcome_bars=outcome_bars,
    )

    for n, i in enumerate(candidate_indices, 1):
        bar = candles_1m[i]

        # Skip if already in DB
        if bar.timestamp in skip_existing_times:
            count_skipped += 1
            continue

        # 이제부터만 expensive path
        window_1m = candles_1m[: i + 1]
        candles_5m, candles_15m = rolling_5m_15m(window_1m, n_bars=N_15M)
        if len(candles_5m) < 50 or len(candles_15m) < 55:
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

        # stop_loss sanity guard
        if stop_loss is None or math.isclose(entry_price, stop_loss, rel_tol=0.0, abs_tol=1e-12):
            continue

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

        # Trend filter: LONG only if ema20>ema50 and ema50_slope>0, SHORT only if opposite
        if get_use_trend_filter(cfg):
            bias = features.get("trend_bias", 0.0) or 0.0
            if candidate.direction == Direction.LONG and bias < 0.5:
                count_skipped += 1
                continue
            if candidate.direction == Direction.SHORT and bias > -0.5:
                count_skipped += 1
                continue

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

        if count_logged % 500 == 0:
            logger.info(
                "Progress: checked=%d/%d logged=%d skipped=%d last_ts=%s",
                n, len(candidate_indices), count_logged, count_skipped, bar.timestamp
            )

    return count_logged, count_skipped


def sync_recent_from_db(
    symbol: str = "BTCUSDT",
    table: str = "btc1m",
    n_bars: int = 5000,
) -> tuple[int, int]:
    """
    동기화된 1m 중 최근 n_bars로, candidate_signals에 없는 시점만 후보 생성 + signal_outcomes 저장.
    서버 기동 시 1번(Binance sync) 직후 호출용.
    """
    candles_1m = load_1m_last_n(n_bars, table=table, symbol=symbol)
    min_bars = 15 * N_15M + 31  # need_bars + outcome_bars
    if len(candles_1m) < min_bars:
        return 0, 0

    start_ts = candles_1m[0].timestamp if candles_1m else None
    end_ts = candles_1m[-1].timestamp if candles_1m else None
    skip_set = load_existing_times(symbol, start_ts=start_ts, end_ts=end_ts)
    config = load_config()
    return build_dataset(candles_1m, symbol, config, skip_existing_times=skip_set)


def load_existing_times(symbol: str, start_ts=None, end_ts=None) -> set[int]:
    """
    Load existing signal times only.
    기존 코드처럼 전체 row(all())를 가져오지 않고, time 컬럼만 범위 제한 조회.
    """
    init_db()
    from storage.database import SessionLocal

    db = SessionLocal()
    try:
        q = db.query(CandidateSignalModel.time).filter(CandidateSignalModel.symbol == symbol)

        if start_ts is not None:
            q = q.filter(CandidateSignalModel.time >= start_ts)
        if end_ts is not None:
            q = q.filter(CandidateSignalModel.time <= end_ts)

        rows = q.all()
        return {r[0] for r in rows}
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

    logger.info(
        "Loading 1m candles from %s symbol=%s start=%s end=%s limit=%s",
        args.table, args.symbol, args.start, args.end, args.limit
    )
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

    logger.info(
        "Loaded %d 1m candles from %s to %s",
        len(candles_1m), candles_1m[0].timestamp, candles_1m[-1].timestamp
    )

    skip_set = (
        load_existing_times(
            args.symbol,
            start_ts=candles_1m[0].timestamp,
            end_ts=candles_1m[-1].timestamp,
        )
        if args.skip_existing
        else set()
    )
    if skip_set:
        logger.info("Skipping %d existing timestamps", len(skip_set))

    config = load_config()
    logged, skipped = build_dataset(candles_1m, args.symbol, config, skip_existing_times=skip_set)
    logger.info("Done: logged=%d skipped=%d", logged, skipped)


if __name__ == "__main__":
    main()