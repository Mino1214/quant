"""
Backtest runner: 1m candles in, same strategy/risk/paper broker, no duplicate signals per bar.
"""
import argparse
import csv
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.models import BlockedCandidateLog, Candle, CandidateSignalRecord, Direction, Timeframe, TradeRecord
from config.loader import load_config, get_approval_settings, get_capital_allocation_settings, get_kelly_settings, get_leverage_settings, get_risk_settings, get_strategy_settings, get_regime_settings
from strategy.mtf_ema_pullback import evaluate_candidate
from strategy.filters.market_regime import MarketRegimeFilter
from strategy.approval_engine import ApprovalContext, score as approval_score
from strategy.feature_extractor import extract_feature_values
from risk.risk_manager import RiskManager, compute_stop_loss, compute_quantity, ema_exit_triggered
from execution.capital_allocator import get_position_size, get_total_open_risk_pct
from execution.signal_quality_ranking import compute_signal_quality_score
from indicators.atr import atr
from indicators.ema import ema
from execution.paper_broker import PaperBroker
from storage.trade_logger import log_blocked_candidate, log_trade
from storage.candle_loader import load_1m_from_db, load_1m_last_n

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_1m_candles_from_csv(path: Path) -> List[Candle]:
    """Load 1m OHLCV from CSV: timestamp,open,high,low,close,volume (timestamp in ms or iso)."""
    candles = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row.get("timestamp", row.get("time", ""))
            if ts.isdigit():
                ts_dt = datetime.utcfromtimestamp(int(ts) / 1000)
            else:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            candles.append(
                Candle(
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0)),
                    timestamp=ts_dt,
                    timeframe=Timeframe.M1,
                )
            )
    return candles


def _agg(block: List[Candle], n: int) -> Candle:
    """1m 블록 5개/15개를 하나의 5m/15m 봉으로. 실전 엔진과 동일."""
    return Candle(
        open=block[0].open,
        high=max(c.high for c in block),
        low=min(c.low for c in block),
        close=block[-1].close,
        volume=sum(c.volume for c in block),
        timestamp=block[-1].timestamp,
        timeframe=Timeframe.M5 if n == 5 else Timeframe.M15,
    )


# 레짐 필터가 15m 55봉 필요(EMA50+slope_lookback) → 15m 60봉 만들어서 넘김
N_15M = 60
N_5M = 60


def rolling_5m_15m(window_1m: List[Candle], n_bars: int = N_15M) -> tuple[List[Candle], List[Candle]]:
    """
    실전 엔진과 동일: 마지막 5봉/15봉이 '방금 마감된 1m 포함'한 현재 구간.
    n_bars는 15m 55봉 이상 필요(레짐) → 기본 60.
    """
    need_5 = n_bars * 5
    need_15 = n_bars * 15
    if len(window_1m) < need_5 or len(window_1m) < need_15:
        return [], []
    candles_5m = []
    for k in range(n_bars):
        start = -(k + 1) * 5
        end = -k * 5 if k > 0 else None
        block = window_1m[start:end]
        if len(block) == 5:
            candles_5m.append(_agg(block, 5))
    candles_5m.reverse()
    candles_15m = []
    for k in range(n_bars):
        start = -(k + 1) * 15
        end = -k * 15 if k > 0 else None
        block = window_1m[start:end]
        if len(block) == 15:
            candles_15m.append(_agg(block, 15))
    candles_15m.reverse()
    return candles_5m, candles_15m


async def run_backtest(
    candles_1m: List[Candle],
    symbol: str = "BTCUSDT",
    config: Optional[dict] = None,
    verbose: bool = False,
) -> tuple[List[TradeRecord], float, List[CandidateSignalRecord]]:
    """
    백테스트 = 실전 봇과 동일 세팅·매매기법.
    verbose=True면 0건일 때 왜 막혔는지 요약 카운트 출력.
    Returns (trades, balance, candidate_signals) for Signal Distribution Analysis.
    """
    cfg = config or load_config()
    strat_settings = get_strategy_settings(cfg)
    risk_settings = get_risk_settings(cfg)
    regime_settings = get_regime_settings(cfg)
    approval_settings = get_approval_settings(cfg)
    capital_allocation_settings = get_capital_allocation_settings(cfg)
    kelly_settings = get_kelly_settings(cfg)
    leverage_settings = get_leverage_settings(cfg)
    regime_filter = MarketRegimeFilter(regime_settings) if regime_settings.enabled else None
    initial_balance = cfg.get("backtest", {}).get("initial_balance", 10000.0)
    commission_rate = cfg.get("backtest", {}).get("commission_rate", 0.0004)

    broker = PaperBroker(initial_balance=initial_balance, commission_rate=commission_rate)
    risk_mgr = RiskManager(risk_settings)
    trades: List[TradeRecord] = []
    candidate_signals: List[CandidateSignalRecord] = []
    last_executed_candidate_idx: Optional[int] = None
    balance = initial_balance
    last_signal_bar_ts: Optional[datetime] = None
    current_approval_score: int = 0

    if verbose:
        cnt_regime_block = cnt_no_signal = cnt_regime_dir = cnt_risk = cnt_qty = cnt_entries = 0
        score_0 = score_1 = score_2 = score_3 = 0

    # 실전 엔진과 동일: config.json + 동일 5m/15m 집계(마지막 봉에 현재 1m 포함)
    for i in range(len(candles_1m)):
        bar = candles_1m[i]
        window_1m = candles_1m[: i + 1]
        candles_5m, candles_15m = rolling_5m_15m(window_1m, n_bars=N_15M)
        if len(candles_5m) < 50 or len(candles_15m) < 55:
            continue

        # Check 4-stage exit for existing position first
        pos = await broker.get_open_position(symbol)
        if pos is not None:
            atr_val = atr(window_1m, risk_settings.atr_period) or 0.0
            closes = [c.close for c in window_1m]
            ema8 = ema(closes, 8) if len(closes) >= 8 else None
            ema21 = ema(closes, 21) if len(closes) >= 21 else None
            confirm = getattr(risk_settings, "ema_exit_confirm_bars", 1)
            ema_triggered = ema_exit_triggered(
                window_1m, pos.side, confirm,
                strat_settings.ema_fast, strat_settings.ema_mid,
            )
            closed_list = broker.check_stop_tp(
                bar.low, bar.high, bar.close,
                atr_val, ema8, ema21, risk_settings,
                closed_at=bar.timestamp,
                ema_exit_triggered=ema_triggered,
            )
            for closed in closed_list:
                closed.approval_score = current_approval_score
                closed.blocked_reason = None
                closed.mode = "backtest"
                trades.append(closed)
                balance += closed.pnl
                risk_mgr.record_trade(closed)
                risk_mgr.set_last_trade_time(bar.timestamp)
                log_trade(closed)
            if closed_list and last_executed_candidate_idx is not None:
                total_r = sum(c.rr for c in closed_list)
                first_opened = closed_list[0].opened_at
                last_closed = closed_list[-1].closed_at
                holding_bars = int((last_closed - first_opened).total_seconds() // 60)
                rec = candidate_signals[last_executed_candidate_idx]
                rec.R_return = total_r
                rec.holding_time_bars = holding_bars
                last_executed_candidate_idx = None
            if closed_list:
                continue

        # Market regime filter: block if not tradeable or direction not allowed
        regime_result = None
        if regime_filter is not None:
            regime_result = regime_filter.evaluate(candles_15m)
            if not regime_result.allow_trading:
                if verbose:
                    cnt_regime_block += 1
                    sc = getattr(regime_result, "score", 0)
                    if sc == 0:
                        score_0 += 1
                    elif sc == 1:
                        score_1 += 1
                    elif sc == 2:
                        score_2 += 1
                    else:
                        score_3 += 1
                continue
        # No position: candidate → approval → entry
        candidate = evaluate_candidate(candles_15m, candles_5m, window_1m, strat_settings, symbol)
        if candidate is None:
            if verbose:
                cnt_no_signal += 1
            continue
        if regime_result is not None:
            if candidate.direction == Direction.LONG and not regime_result.can_long:
                if verbose:
                    cnt_regime_dir += 1
                continue
            if candidate.direction == Direction.SHORT and not regime_result.can_short:
                if verbose:
                    cnt_regime_dir += 1
                continue
        if last_signal_bar_ts == bar.timestamp:
            continue

        entry_price = bar.close
        stop_loss = compute_stop_loss(
            entry_price, candidate.direction, window_1m, risk_settings
        )
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
        if len(candles_15m) >= 50:
            try:
                from features.multi_tf_feature_builder import build_multi_tf_features
                multi_tf = build_multi_tf_features(
                    window_1m, candles_5m, candles_15m,
                    bar.timestamp, strat_settings,
                )
                features = {**features, **multi_tf}
            except Exception:
                pass
        try:
            from features.cross_market_feature_builder import build_cross_market_features
            features = build_cross_market_features(
                bar.timestamp, features, strat_settings, eth_candles=None,
            )
        except Exception:
            pass
        if not result.allowed:
            log_blocked_candidate(BlockedCandidateLog(
                symbol=symbol,
                direction=candidate.direction,
                timestamp=bar.timestamp,
                total_score=result.total_score,
                blocked_reason=result.blocked_reason or "approval",
                category_scores=result.category_scores,
                reason_entry=candidate.reason_code,
            ))
            candidate_signals.append(CandidateSignalRecord(
                timestamp=bar.timestamp,
                entry_price=entry_price,
                regime=regime_str,
                trend_direction=candidate.direction,
                approval_score=result.total_score,
                feature_values=features,
                trade_outcome="blocked",
                blocked_reason=result.blocked_reason,
                symbol=symbol,
            ))
            continue

        current_approval_score = result.total_score
        check = risk_mgr.can_trade(bar.timestamp, risk_settings.cooldown_bars)
        if not check.allowed:
            if verbose:
                cnt_risk += 1
            continue

        cap = capital_allocation_settings
        use_allocator = cap is not None and getattr(cap, "enabled", False)
        signal_quality_score = None
        allocated_risk_pct = None
        kelly_fraction = None

        if use_allocator:
            # Backtest: no ML by default; use approval-based proxy for quality score
            win_prob = 0.4 + (current_approval_score / 7.0) * 0.4
            expected_r = 0.25
            stability = getattr(cap, "default_strategy_stability_score", 0.5)
            signal_quality_score = compute_signal_quality_score(win_prob, expected_r, stability)
            if signal_quality_score <= cap.min_quality_threshold:
                if verbose:
                    cnt_qty += 1
                continue
            kelly = kelly_settings
            use_kelly = kelly is not None and getattr(kelly, "enabled", False)
            override_risk_pct = None
            if use_kelly:
                from execution.kelly_allocator import compute_kelly_risk
                avg_win_R = getattr(kelly, "avg_win_R", 1.2)
                avg_loss_R = getattr(kelly, "avg_loss_R", -1.0)
                kelly_result = compute_kelly_risk(
                    win_prob, avg_win_R, avg_loss_R, kelly,
                    signal_quality_score=signal_quality_score,
                    expected_R=expected_r,
                )
                kelly_fraction = kelly_result.get("kelly_fraction")
                if kelly_result.get("skip"):
                    if verbose:
                        cnt_qty += 1
                    continue
                override_risk_pct = kelly_result.get("final_risk_pct")
            pos = await broker.get_open_position(symbol)
            current_risk_pct = get_total_open_risk_pct([pos], balance) if pos else 0.0
            qty, allocated_risk_pct = get_position_size(
                balance, entry_price, stop_loss, candidate.direction,
                signal_quality_score, regime_str, cap, current_risk_pct,
                override_risk_pct=override_risk_pct,
                leverage_settings=leverage_settings,
            )
        else:
            qty = compute_quantity(
                balance, entry_price, stop_loss, candidate.direction, risk_settings
            )

        if qty <= 0:
            if verbose:
                cnt_qty += 1
            continue

        if verbose:
            cnt_entries += 1
        candidate_signals.append(CandidateSignalRecord(
            timestamp=bar.timestamp,
            entry_price=entry_price,
            regime=regime_str,
            trend_direction=candidate.direction,
            approval_score=current_approval_score,
            feature_values=features,
            trade_outcome="executed",
            blocked_reason=None,
            symbol=symbol,
            signal_quality_score=signal_quality_score,
            allocated_risk_pct=allocated_risk_pct,
            kelly_fraction=kelly_fraction,
        ))
        last_executed_candidate_idx = len(candidate_signals) - 1
        await broker.place_market_order(symbol, candidate.direction, qty, reduce_only=False)
        broker.set_fill_price(entry_price, stop_loss, None, opened_at=bar.timestamp)
        await broker.place_stop_loss_order(
            symbol, candidate.direction, qty, stop_loss, reduce_only=True
        )
        await broker.place_take_profit_order(
            symbol, candidate.direction, qty, entry_price, reduce_only=True
        )
        last_signal_bar_ts = bar.timestamp
        logger.info(
            "Backtest entry %s %s @ %s sl=%s qty=%s approval_score=%s",
            symbol, candidate.direction.value, entry_price, stop_loss, qty, current_approval_score,
        )

    if verbose and len(trades) == 0:
        logger.info(
            "Backtest 진단(0건): regime_block=%s no_signal=%s regime_dir=%s risk_block=%s qty<=0=%s → 진입=%s",
            cnt_regime_block, cnt_no_signal, cnt_regime_dir, cnt_risk, cnt_qty, cnt_entries,
        )
        if cnt_regime_block > 0:
            logger.info(
                "  regime 스코어 분포(막힌 봉): score0=%s score1=%s score2=%s score3=%s (2 이상이면 통과, threshold 확인)",
                score_0, score_1, score_2, score_3,
            )
            # 전부 score 0이면 실제 adx/slope/natr 한 번 샘플 로그 (기준 조정용)
            if score_0 == cnt_regime_block and regime_filter is not None:
                sample_i = min(25000, len(candles_1m) - 1)
                w = candles_1m[: sample_i + 1]
                c5, c15 = rolling_5m_15m(w, N_15M)
                if len(c15) >= 55:
                    r = regime_filter.evaluate(c15)
                    first_15 = c15[0]
                    last_15 = c15[-1]
                    logger.info(
                        "  [샘플 1봉] adx=%.4f slope_pct=%.6f natr=%.4f → config에서 adx_min/slope_threshold_pct/natr_min 을 이보다 낮게 하면 통과",
                        r.adx, r.slope_pct, r.natr,
                    )
                    logger.info(
                        "  [15m 집계 확인] 첫봉 O=%.2f H=%.2f L=%.2f C=%.2f | 마지막봉 O=%.2f H=%.2f L=%.2f C=%.2f (H=L이면 데이터/컬럼 점검)",
                        first_15.open, first_15.high, first_15.low, first_15.close,
                        last_15.open, last_15.high, last_15.low, last_15.close,
                    )

    # Trades already logged when closed (with approval_score)
    return trades, balance, candidate_signals


async def main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default="", help="Path to 1m CSV (timestamp,open,high,low,close,volume)")
    parser.add_argument("--from-db", action="store_true", help="Load 1m candles from DB table (btc1m)")
    parser.add_argument("--table", type=str, default="btc1m", help="Table name when using --from-db (default: btc1m)")
    parser.add_argument("--limit", type=int, default=None, help="When --from-db: max rows from oldest (첫 봉부터 N개)")
    parser.add_argument("--bars", type=int, default=None, help="When --from-db: 기준(가장 최근 봉)으로부터 이전 N봉만 사용 (권장)")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--verbose", "-v", action="store_true", help="0건일 때 막힌 이유 요약 출력")
    parser.add_argument("--export-candidates", type=str, default="", help="Export candidate signals to CSV for Signal Distribution Analysis")
    parser.add_argument("--run-analysis", action="store_true", help="Run Signal Distribution Analysis (uses --export-candidates path or default)")
    args = parser.parse_args()

    if args.from_db:
        if args.bars is not None:
            # 기준(가장 최근 봉)으로부터 이전 N봉만 사용
            candles = load_1m_last_n(args.bars, table=args.table, symbol=args.symbol)
            if not candles:
                logger.warning("No rows from table %s (last %d bars). Check DATABASE_URL and symbol.", args.table, args.bars)
                return
            logger.info("Loaded last %d 1m bars from DB table %s (symbol=%s)", len(candles), args.table, args.symbol)
        else:
            candles = load_1m_from_db(table=args.table, limit=args.limit, symbol=args.symbol)
            if not candles:
                logger.warning("No rows from table %s. Check DATABASE_URL and table columns (open_time, open, high, low, close, volume).", args.table)
                return
            logger.info("Loaded %d 1m candles from DB table %s", len(candles), args.table)
    elif args.data and Path(args.data).exists():
        candles = load_1m_candles_from_csv(Path(args.data))
        logger.info("Loaded %d 1m candles from CSV", len(candles))
    else:
        logger.info("Use --data path/to/1m.csv for CSV, or --from-db to load from DB table btc1m.")
        logger.info("CSV format: timestamp,open,high,low,close,volume")
        return

    trades, final_balance, candidate_signals = await run_backtest(candles, args.symbol, verbose=args.verbose)

    # Signal Distribution Analysis: export and/or run analysis
    if args.export_candidates:
        from storage.signal_distribution_export import export_candidate_signals
        export_candidate_signals(candidate_signals, Path(args.export_candidates))
    if args.run_analysis:
        from storage.signal_distribution_export import export_candidate_signals
        csv_path = Path(args.export_candidates) if args.export_candidates else Path("analysis/output/candidates.csv")
        if not args.export_candidates:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            export_candidate_signals(candidate_signals, csv_path)
        out_dir = csv_path.parent
        rc = subprocess.run(
            [sys.executable, "-m", "analysis.run_signal_analysis", "--candidates-csv", str(csv_path), "--output-dir", str(out_dir)],
            cwd=Path(__file__).resolve().parent.parent,
        )
        if rc.returncode != 0:
            logger.warning("Signal analysis exited with code %s", rc.returncode)

    # 요약: 승률, R, runup/dd, profit factor
    cfg = load_config()
    initial_balance = cfg.get("backtest", {}).get("initial_balance", 10000.0)
    n = len(trades)
    if n > 0:
        wins = sum(1 for t in trades if t.pnl > 0)
        losses = n - wins
        win_rate_pct = (wins / n) * 100.0
        total_pnl = final_balance - initial_balance
        total_r = sum(t.rr for t in trades)
        avg_r = total_r / n
        win_r_list = [t.rr for t in trades if t.pnl > 0]
        loss_r_list = [t.rr for t in trades if t.pnl <= 0]
        avg_win_r = sum(win_r_list) / len(win_r_list) if win_r_list else 0.0
        avg_loss_r = sum(loss_r_list) / len(loss_r_list) if loss_r_list else 0.0
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
        max_runup = peak
        logger.info(
            "Backtest done: %d trades, final balance %.2f (PnL %.2f)",
            n, final_balance, total_pnl,
        )
        logger.info(
            "  승률 %.1f%% (승 %d / 패 %d) | 총 R %.2f | 평균 R %.2f | avg_win_R %.2f | avg_loss_R %.2f",
            win_rate_pct, wins, losses, total_r, avg_r, avg_win_r, avg_loss_r,
        )
        logger.info(
            "  max_runup %.2f | max_drawdown %.2f | profit_factor %.2f",
            max_runup, max_dd, profit_factor,
        )
    else:
        logger.info("Backtest done: 0 trades, final balance %.2f", final_balance)


def main() -> None:
    import asyncio
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
