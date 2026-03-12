"""
실전형 전략 백테스터.

목적: 후보 전략 1개를 자본관리 포함 실전 형태로 시뮬레이션.
     파라미터 탐색이 아닌 "이 전략으로 실제 돈을 굴리면 살아남는가?" 판단용.

출력:
  - 자본곡선 (equity curve)
  - MDD
  - 월별 수익률
  - 연속 손실 최대치
  - trade 로그 CSV
  - summary JSON

사용 예 (기존 exit):
  python3 -m backtest.run_strategy_backtest \\
    --symbol BTCUSDT \\
    --from-ts 2025-03-01 --to-ts 2025-08-31 \\
    --threshold 0.000285 \\
    --exit-type old \\
    --tp 1.2 --sl 0.6 --timeout-bars 30 \\
    --initial-capital 1000 \\
    --notional-fraction 0.1 --leverage 2 --fee-bps 4 \\
    --out-prefix btc_0308_old

사용 예 (partial exit):
  python3 -m backtest.run_strategy_backtest \\
    --symbol BTCUSDT \\
    --from-ts 2025-03-01 --to-ts 2025-08-31 \\
    --threshold 0.000285 \\
    --exit-type partial \\
    --tp1 0.8 --sl 0.6 --timeout-bars 30 \\
    --initial-capital 1000 \\
    --notional-fraction 0.1 --leverage 2 --fee-bps 4 \\
    --out-prefix btc_0308_partial
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.experiments._simulator import (
    PrecomputedState,
    SimulatorConfig,
    SimpleTrade,
    build_precomputed_state,
    simulate_old_from_state,
    simulate_partial_from_state,
)
from config.loader import get_strategy_settings
from storage.candle_loader import load_1m_from_db, load_5m_from_db, load_15m_from_db
from strategy.strategies.mtf_trend_pullback_research import evaluate_strict


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class StrategyBacktestConfig:
    symbol: str = "BTCUSDT"
    from_ts: Optional[str] = None
    to_ts: Optional[str] = None

    # 진입 필터
    regime_threshold: Optional[float] = 0.000285

    # Exit 방식
    exit_type: str = "old"      # "old" | "partial"
    tp_pct: float = 1.2         # old 전용
    tp1_pct: float = 0.8        # partial 전용
    tp1_size: float = 0.5       # partial 전용: TP1 청산 비중
    sl_pct: float = 0.6
    timeout_bars: int = 30

    # 자본관리
    initial_capital: float = 1000.0
    position_sizing_mode: str = "fixed_fraction"  # "fixed_fraction" | "fixed_risk"
    notional_fraction: float = 0.1   # 자본 대비 노출 비중 (fixed_fraction 모드)
    risk_fraction: float = 0.01      # 자본 대비 리스크 비중 (fixed_risk 모드, 향후 확장)
    leverage: float = 2.0
    fee_bps: float = 4.0


# ---------------------------------------------------------------------------
# 데이터 로드 (run_experiments.py 방식 그대로)
# ---------------------------------------------------------------------------

def _load_candles_from_db(
    symbol: str = "BTCUSDT",
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
) -> Tuple[List[Any], Optional[List[Any]], Optional[List[Any]]]:
    """1m 로드 후 5m/15m는 1m 구간+룩백으로 로드."""
    from datetime import timedelta

    start_ts_dt: Optional[Any] = None
    end_ts_dt: Optional[Any] = None
    if from_ts:
        try:
            start_ts_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        except Exception:
            start_ts_dt = None
    if to_ts:
        try:
            end_ts_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        except Exception:
            end_ts_dt = None

    print("loading 1m candles...")
    candles_1m = load_1m_from_db(symbol=symbol, start_ts=start_ts_dt, end_ts=end_ts_dt)
    print(f"1m candles loaded: {len(candles_1m)}")

    if not candles_1m:
        return [], None, None

    start_ts = candles_1m[0].timestamp
    end_ts_bar = candles_1m[-1].timestamp
    lookback = timedelta(minutes=60 * 15)
    start_ts_with_lookback = start_ts - lookback

    print("loading 5m candles...")
    candles_5m = load_5m_from_db(symbol=symbol, start_ts=start_ts_with_lookback, end_ts=end_ts_bar)
    print(f"5m candles loaded: {len(candles_5m)}")

    print("loading 15m candles...")
    candles_15m = load_15m_from_db(symbol=symbol, start_ts=start_ts_with_lookback, end_ts=end_ts_bar)
    print(f"15m candles loaded: {len(candles_15m)}")

    return candles_1m, candles_5m, candles_15m


# ---------------------------------------------------------------------------
# 자본관리: trade별 포지션 노출 및 PnL 계산
# ---------------------------------------------------------------------------

def _compute_position_notional(equity: float, cfg: StrategyBacktestConfig) -> float:
    """현재 equity 기준 포지션 노출 금액 계산."""
    if cfg.position_sizing_mode == "fixed_fraction":
        return equity * cfg.notional_fraction * cfg.leverage
    # fixed_risk: 손절폭으로 리스크 역산 (향후 확장)
    # risk_usdt = equity * cfg.risk_fraction
    # position = risk_usdt / (cfg.sl_pct / 100.0)
    # return position
    return equity * cfg.notional_fraction * cfg.leverage


# ---------------------------------------------------------------------------
# Trade ledger 생성: SimpleTrade + 자본관리 결합
# ---------------------------------------------------------------------------

@dataclass
class TradeLedger:
    entry_ts: datetime
    exit_ts: datetime
    exit_reason: str
    entry_price: float
    exit_price: float
    pnl_pct: float       # gross pnl (수수료 전)
    net_pct: float       # 수수료 반영 후
    tp1_hit: bool
    equity_before: float
    position_notional: float
    pnl_usdt: float
    equity_after: float


def _build_ledger(
    trades: List[SimpleTrade],
    cfg: StrategyBacktestConfig,
) -> List[TradeLedger]:
    """SimpleTrade 리스트에 자본관리 적용해 TradeLedger 생성."""
    ledger: List[TradeLedger] = []
    equity = cfg.initial_capital

    for t in trades:
        equity_before = equity
        notional = _compute_position_notional(equity, cfg)
        pnl_usdt = notional * (t.net_pct / 100.0)
        equity_after = equity + pnl_usdt

        ledger.append(TradeLedger(
            entry_ts=t.entry_ts,
            exit_ts=t.exit_ts,
            exit_reason=t.exit_reason,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            pnl_pct=t.pnl_pct,
            net_pct=t.net_pct,
            tp1_hit=t.tp1_hit,
            equity_before=equity_before,
            position_notional=notional,
            pnl_usdt=pnl_usdt,
            equity_after=equity_after,
        ))
        equity = equity_after

    return ledger


# ---------------------------------------------------------------------------
# Equity curve
# ---------------------------------------------------------------------------

@dataclass
class EquityPoint:
    ts: datetime
    equity: float
    drawdown_pct: float


def _build_equity_curve(ledger: List[TradeLedger], initial_capital: float) -> List[EquityPoint]:
    """trade 청산 시점 기준 equity curve 생성."""
    curve: List[EquityPoint] = []
    peak = initial_capital

    for t in ledger:
        eq = t.equity_after
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak * 100.0  # 음수
        curve.append(EquityPoint(ts=t.exit_ts, equity=eq, drawdown_pct=dd))

    return curve


# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------

def _compute_summary(
    ledger: List[TradeLedger],
    curve: List[EquityPoint],
    initial_capital: float,
) -> Dict[str, Any]:
    n = len(ledger)
    if n == 0:
        return {
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "total_return_pct": 0.0,
            "final_equity": initial_capital,
            "max_drawdown_pct": 0.0,
            "avg_trade_net_pct": 0.0,
            "max_consecutive_losses": 0,
            "monthly_returns": {},
        }

    wins = sum(1 for t in ledger if t.net_pct > 0)
    win_rate_pct = wins / n * 100.0

    gross_profit = sum(t.pnl_usdt for t in ledger if t.pnl_usdt > 0)
    gross_loss = abs(sum(t.pnl_usdt for t in ledger if t.pnl_usdt < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    final_equity = ledger[-1].equity_after
    total_return_pct = (final_equity - initial_capital) / initial_capital * 100.0
    avg_trade_net_pct = sum(t.net_pct for t in ledger) / n

    max_drawdown_pct = min((p.drawdown_pct for p in curve), default=0.0)

    max_consecutive_losses = _max_consecutive_losses(ledger)
    monthly_returns = _compute_monthly_returns(ledger)

    return {
        "total_trades": n,
        "win_rate_pct": round(win_rate_pct, 2),
        "profit_factor": round(profit_factor, 4),
        "total_return_pct": round(total_return_pct, 4),
        "final_equity": round(final_equity, 4),
        "initial_capital": initial_capital,
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "avg_trade_net_pct": round(avg_trade_net_pct, 4),
        "max_consecutive_losses": max_consecutive_losses,
        "monthly_returns": monthly_returns,
    }


def _max_consecutive_losses(ledger: List[TradeLedger]) -> int:
    max_streak = 0
    current_streak = 0
    for t in ledger:
        if t.net_pct < 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    return max_streak


def _compute_monthly_returns(ledger: List[TradeLedger]) -> Dict[str, Dict[str, float]]:
    """exit_ts 기준 월별 pnl_usdt 합계 및 수익률."""
    monthly: Dict[str, Dict[str, Any]] = {}

    for t in ledger:
        month_key = t.exit_ts.strftime("%Y-%m")
        if month_key not in monthly:
            monthly[month_key] = {
                "pnl_usdt": 0.0,
                "equity_start": t.equity_before,
                "equity_end": t.equity_after,
                "n_trades": 0,
            }
        monthly[month_key]["pnl_usdt"] += t.pnl_usdt
        monthly[month_key]["equity_end"] = t.equity_after
        monthly[month_key]["n_trades"] += 1

    result: Dict[str, Dict[str, float]] = {}
    for month_key, data in sorted(monthly.items()):
        eq_start = data["equity_start"]
        eq_end = data["equity_end"]
        return_pct = (eq_end - eq_start) / eq_start * 100.0 if eq_start > 0 else 0.0
        result[month_key] = {
            "pnl_usdt": round(data["pnl_usdt"], 4),
            "return_pct": round(return_pct, 4),
            "n_trades": data["n_trades"],
        }
    return result


# ---------------------------------------------------------------------------
# 출력 저장
# ---------------------------------------------------------------------------

def _save_summary(summary: Dict[str, Any], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"summary saved: {path}")


def _save_trades_csv(ledger: List[TradeLedger], path: Path) -> None:
    if not ledger:
        return
    fields = [
        "entry_ts", "exit_ts", "exit_reason",
        "entry_price", "exit_price",
        "pnl_pct", "net_pct", "tp1_hit",
        "equity_before", "position_notional", "pnl_usdt", "equity_after",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in ledger:
            w.writerow({
                "entry_ts": t.entry_ts,
                "exit_ts": t.exit_ts,
                "exit_reason": t.exit_reason,
                "entry_price": round(t.entry_price, 6),
                "exit_price": round(t.exit_price, 6),
                "pnl_pct": round(t.pnl_pct, 4),
                "net_pct": round(t.net_pct, 4),
                "tp1_hit": t.tp1_hit,
                "equity_before": round(t.equity_before, 4),
                "position_notional": round(t.position_notional, 4),
                "pnl_usdt": round(t.pnl_usdt, 4),
                "equity_after": round(t.equity_after, 4),
            })
    print(f"trades saved: {path}")


def _save_equity_csv(curve: List[EquityPoint], path: Path) -> None:
    if not curve:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "equity", "drawdown_pct"])
        w.writeheader()
        for p in curve:
            w.writerow({
                "ts": p.ts,
                "equity": round(p.equity, 4),
                "drawdown_pct": round(p.drawdown_pct, 4),
            })
    print(f"equity curve saved: {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="실전형 전략 백테스터")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--from-ts", default=None, help="시작 시간 (예: 2025-03-01)")
    parser.add_argument("--to-ts", default=None, help="종료 시간 (예: 2025-08-31)")

    # 진입 필터
    parser.add_argument("--threshold", type=float, default=None,
                        help="ema20_slope_15m regime 필터 threshold (None이면 필터 없음)")

    # Exit 설정
    parser.add_argument("--exit-type", choices=["old", "partial"], default="old")
    parser.add_argument("--tp", type=float, default=1.2, help="old exit: TP%")
    parser.add_argument("--tp1", type=float, default=0.8, help="partial exit: TP1%")
    parser.add_argument("--tp1-size", type=float, default=0.5, help="partial exit: TP1 청산 비중")
    parser.add_argument("--sl", type=float, default=0.6, help="손절 %")
    parser.add_argument("--timeout-bars", type=int, default=30, help="최대 보유 봉 수")

    # 자본관리
    parser.add_argument("--initial-capital", type=float, default=1000.0, help="초기 자본 (USDT)")
    parser.add_argument("--notional-fraction", type=float, default=0.1,
                        help="자본 대비 포지션 비중 (레버리지 적용 전)")
    parser.add_argument("--leverage", type=float, default=2.0, help="레버리지")
    parser.add_argument("--fee-bps", type=float, default=4.0, help="편도 수수료 (bps)")

    # 출력
    parser.add_argument("--out-prefix", default="strategy_backtest",
                        help="출력 파일 프리픽스 (타임스탬프 자동 추가)")
    parser.add_argument("--out-dir", default=None,
                        help="출력 디렉토리 (기본: backtest/backtest_results)")

    args = parser.parse_args()

    cfg = StrategyBacktestConfig(
        symbol=args.symbol,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        regime_threshold=args.threshold,
        exit_type=args.exit_type,
        tp_pct=args.tp,
        tp1_pct=args.tp1,
        tp1_size=args.tp1_size,
        sl_pct=args.sl,
        timeout_bars=args.timeout_bars,
        initial_capital=args.initial_capital,
        notional_fraction=args.notional_fraction,
        leverage=args.leverage,
        fee_bps=args.fee_bps,
    )

    # -------------------------------------------------------------------
    # 1. 데이터 로드
    # -------------------------------------------------------------------
    candles_1m, candles_5m, candles_15m = _load_candles_from_db(
        symbol=cfg.symbol,
        from_ts=cfg.from_ts,
        to_ts=cfg.to_ts,
    )
    if not candles_1m:
        print("1m 캔들이 없습니다. 종료.")
        sys.exit(1)

    # -------------------------------------------------------------------
    # 2. Precomputed state 1회 생성
    # -------------------------------------------------------------------
    print("[main] precomputed state 생성 (feature extraction, 1회)...")
    state = build_precomputed_state(
        candles_1m=candles_1m,
        candles_5m_full=candles_5m,
        candles_15m_full=candles_15m,
        symbol=cfg.symbol,
        evaluate_fn=evaluate_strict,
        get_settings=get_strategy_settings,
    )
    print("[main] precomputed state 완료.")

    # -------------------------------------------------------------------
    # 3. 전략 시뮬레이션 (exit type 1개)
    # -------------------------------------------------------------------
    sim_cfg = SimulatorConfig(
        timeout_bars=cfg.timeout_bars,
        tp_pct=cfg.tp_pct,
        sl_pct=cfg.sl_pct,
        fee_bps=cfg.fee_bps,
        cooldown_bars=0,
        regime_threshold=cfg.regime_threshold,
        use_partial_tp=(cfg.exit_type == "partial"),
        tp1_pct=cfg.tp1_pct,
        tp1_size=cfg.tp1_size,
    )

    print(f"[main] 시뮬레이션 시작 (exit_type={cfg.exit_type}, threshold={cfg.regime_threshold})...")
    if cfg.exit_type == "partial":
        trades = simulate_partial_from_state(state, sim_cfg)
    else:
        trades = simulate_old_from_state(state, sim_cfg)
    print(f"[main] 시뮬레이션 완료. 총 {len(trades)}건.")

    # -------------------------------------------------------------------
    # 4. 자본관리 적용 → TradeLedger
    # -------------------------------------------------------------------
    ledger = _build_ledger(trades, cfg)

    # -------------------------------------------------------------------
    # 5. Equity curve + Summary metrics
    # -------------------------------------------------------------------
    curve = _build_equity_curve(ledger, cfg.initial_capital)
    summary = _compute_summary(ledger, curve, cfg.initial_capital)

    # -------------------------------------------------------------------
    # 6. 콘솔 출력
    # -------------------------------------------------------------------
    print("\n===== BACKTEST SUMMARY =====")
    print(f"  Symbol         : {cfg.symbol}")
    print(f"  Period         : {cfg.from_ts} ~ {cfg.to_ts}")
    print(f"  Exit type      : {cfg.exit_type}")
    print(f"  Threshold      : {cfg.regime_threshold}")
    print(f"  Initial capital: {cfg.initial_capital} USDT")
    print(f"  Notional frac  : {cfg.notional_fraction} × leverage {cfg.leverage}x")
    print(f"  Fee            : {cfg.fee_bps} bps")
    print("----------------------------")
    print(f"  Total trades   : {summary['total_trades']}")
    print(f"  Win rate       : {summary['win_rate_pct']}%")
    print(f"  Profit factor  : {summary['profit_factor']}")
    print(f"  Total return   : {summary['total_return_pct']}%")
    print(f"  Final equity   : {summary['final_equity']} USDT")
    print(f"  Max drawdown   : {summary['max_drawdown_pct']}%")
    print(f"  Avg net/trade  : {summary['avg_trade_net_pct']}%")
    print(f"  Max consec loss: {summary['max_consecutive_losses']}")
    print("\n  Monthly returns:")
    for month, mr in summary["monthly_returns"].items():
        print(f"    {month}  pnl={mr['pnl_usdt']:+.2f} USDT  ret={mr['return_pct']:+.2f}%  trades={mr['n_trades']}")
    print("============================\n")

    # -------------------------------------------------------------------
    # 7. 파일 저장
    # -------------------------------------------------------------------
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{args.out_prefix}_{ts_str}"

    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).parent / "backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_with_config = {
        "config": {
            "symbol": cfg.symbol,
            "from_ts": cfg.from_ts,
            "to_ts": cfg.to_ts,
            "regime_threshold": cfg.regime_threshold,
            "exit_type": cfg.exit_type,
            "tp_pct": cfg.tp_pct,
            "tp1_pct": cfg.tp1_pct,
            "tp1_size": cfg.tp1_size,
            "sl_pct": cfg.sl_pct,
            "timeout_bars": cfg.timeout_bars,
            "initial_capital": cfg.initial_capital,
            "notional_fraction": cfg.notional_fraction,
            "leverage": cfg.leverage,
            "fee_bps": cfg.fee_bps,
        },
        **summary,
    }

    _save_summary(summary_with_config, out_dir / f"{prefix}_summary.json")
    _save_trades_csv(ledger, out_dir / f"{prefix}_trades.csv")
    _save_equity_csv(curve, out_dir / f"{prefix}_equity.csv")


if __name__ == "__main__":
    main()
