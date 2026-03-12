"""
실험 러너: Exit 그리드 서치, Cooldown 테스트, Regime 필터 테스트, Exit 비교.

핵심 변경: feature extraction은 build_precomputed_state()로 1회만 수행,
           이후 실험 루프는 PrecomputedState 재사용.

사용 예:
  # Exit 그리드 (timeout / tp / sl 조합)
  python -m backtest.experiments.run_experiments --experiment exit_grid \\
    --from-db --from-ts 2025-03-01 --to-ts 2025-10-31 --sl 0.6 --tp 1.2

  # Regime 필터 (ema20_slope_15m > threshold)
  python -m backtest.experiments.run_experiments --experiment regime \\
    --from-db --from-ts 2025-03-01 --to-ts 2025-10-31 \\
    --thresholds 0.00015,0.0002,0.000285,0.00035 --sl 0.6 --tp 1.2

  # Exit 비교: 기존 고정 TP/SL vs partial TP + trend-follow
  python -m backtest.experiments.run_experiments --experiment exit_compare \\
    --from-db --from-ts 2025-03-01 --to-ts 2025-10-31 \\
    --thresholds 0.0002,0.000285 --sl 0.6 --tp 1.2 --tp1 0.8 \\
    --out exit_compare_set1.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backtest.experiments._simulator import (
    PrecomputedState,
    SimulatorConfig,
    _run_simulator,
    build_precomputed_state,
    metrics_from_simple_trades,
    simulate_old_from_state,
    simulate_partial_from_state,
)
from config.loader import get_strategy_settings
from storage.candle_loader import load_1m_from_db, load_5m_from_db, load_15m_from_db
from strategy.strategies.mtf_trend_pullback_research import evaluate_strict


# --- Exit grid 기본값
EXIT_GRID_TIMEOUT_BARS = [30]
EXIT_GRID_TP_SL = [
    (1.2, 0.6),
]

# --- Cooldown 기본값
COOLDOWN_BARS_OPTIONS = [0, 10]

# --- Regime 필터 기본값
REGIME_THRESHOLDS_DEFAULT = [None, 0.0, 0.0001, 0.000163, 0.000285]


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

def _load_candles_from_db(
    symbol: str = "BTCUSDT",
    limit: Optional[int] = None,
    offset: int = 0,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
) -> Tuple[List[Any], Optional[List[Any]], Optional[List[Any]]]:
    """1m 로드 후, 5m/15m는 1m 구간+룩백으로 로드."""
    from datetime import datetime, timedelta

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

    effective_limit = (limit + offset) if limit is not None else None

    print("loading 1m candles...")
    candles_1m = load_1m_from_db(
        symbol=symbol,
        limit=effective_limit,
        start_ts=start_ts_dt,
        end_ts=end_ts_dt,
    )
    print("1m candles raw loaded:", len(candles_1m))

    if not candles_1m:
        return [], None, None

    if offset > 0:
        candles_1m = candles_1m[offset:]

    if limit is not None:
        candles_1m = candles_1m[:limit]

    print("1m candles sliced:", len(candles_1m), f"(offset={offset}, limit={limit})")

    if not candles_1m:
        return [], None, None

    start_ts = candles_1m[0].timestamp
    end_ts = candles_1m[-1].timestamp

    lookback = timedelta(minutes=60 * 15)
    start_ts = start_ts - lookback

    print("loading 5m candles...")
    candles_5m = load_5m_from_db(symbol=symbol, start_ts=start_ts, end_ts=end_ts)
    print("5m candles loaded:", len(candles_5m))

    print("loading 15m candles...")
    candles_15m = load_15m_from_db(symbol=symbol, start_ts=start_ts, end_ts=end_ts)
    print("15m candles loaded:", len(candles_15m))

    return candles_1m, candles_5m, candles_15m


# ---------------------------------------------------------------------------
# 실험 함수들 — PrecomputedState를 받아 재사용
# ---------------------------------------------------------------------------

def run_exit_grid(
    state: PrecomputedState,
    symbol: str,
    fee_bps: float = 4.0,
    timeouts: Optional[List[int]] = None,
    tp_sl_list: Optional[List[Tuple[float, float]]] = None,
) -> List[Dict[str, Any]]:
    """timeout × (tp, sl) 조합 그리드. state 재사용으로 precompute 1회."""
    timeouts = timeouts or EXIT_GRID_TIMEOUT_BARS
    tp_sl_list = tp_sl_list or EXIT_GRID_TP_SL
    rows = []
    total = len(timeouts) * len(tp_sl_list)
    step = 0

    for timeout_bars in timeouts:
        for tp_pct, sl_pct in tp_sl_list:
            step += 1
            print(f"[exit_grid] {step}/{total} timeout={timeout_bars} tp={tp_pct} sl={sl_pct}")

            cfg = SimulatorConfig(
                timeout_bars=timeout_bars,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                fee_bps=fee_bps,
                cooldown_bars=0,
                regime_threshold=None,
                use_partial_tp=False,
            )
            trades = simulate_old_from_state(state, cfg)
            m = metrics_from_simple_trades(trades)
            row = {
                "timeout_bars": timeout_bars,
                "tp_pct": tp_pct,
                "sl_pct": sl_pct,
                **m,
            }
            print(f"[exit_grid] done  {step}/{total} -> {row}")
            rows.append(row)

    return rows


def run_cooldown_test(
    state: PrecomputedState,
    symbol: str,
    fee_bps: float = 4.0,
    timeout_bars: int = 30,
    tp_pct: float = 0.6,
    sl_pct: float = 0.3,
    cooldown_options: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Cooldown 0 vs 10 등 비교. state 재사용."""
    cooldown_options = cooldown_options or COOLDOWN_BARS_OPTIONS
    rows = []
    for cooldown_bars in cooldown_options:
        cfg = SimulatorConfig(
            timeout_bars=timeout_bars,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            fee_bps=fee_bps,
            cooldown_bars=cooldown_bars,
            regime_threshold=None,
            use_partial_tp=False,
        )
        trades = simulate_old_from_state(state, cfg)
        m = metrics_from_simple_trades(trades)
        rows.append({
            "cooldown_bars": cooldown_bars,
            "timeout_bars": timeout_bars,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            **m,
        })
    return rows


def run_regime_filter_test(
    state: PrecomputedState,
    symbol: str,
    fee_bps: float = 4.0,
    timeout_bars: int = 30,
    tp_pct: float = 0.6,
    sl_pct: float = 0.3,
    thresholds: Optional[List[Optional[float]]] = None,
) -> List[Dict[str, Any]]:
    """
    Regime 필터: ema20_slope_15m > threshold별 메트릭.
    threshold=None이면 필터 없음.
    state 재사용 — threshold마다 numpy boolean mask만 새로 생성.
    """
    thresholds = thresholds if thresholds is not None else REGIME_THRESHOLDS_DEFAULT
    rows = []
    for th in thresholds:
        cfg = SimulatorConfig(
            timeout_bars=timeout_bars,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            fee_bps=fee_bps,
            cooldown_bars=0,
            regime_threshold=th,
            use_partial_tp=False,
        )
        trades = simulate_old_from_state(state, cfg)
        m = metrics_from_simple_trades(trades)
        rows.append({
            "regime_threshold": "" if th is None else th,
            "timeout_bars": timeout_bars,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            **m,
        })
    return rows


def run_exit_compare(
    state: PrecomputedState,
    symbol: str,
    fee_bps: float = 4.0,
    timeout_bars: int = 30,
    old_tp_pct: float = 1.2,
    sl_pct: float = 0.6,
    tp1_pct: float = 0.8,
    tp1_size: float = 0.5,
    thresholds: Optional[List[Optional[float]]] = None,
) -> List[Dict[str, Any]]:
    """
    각 regime threshold별로 기존 exit vs partial TP exit 나란히 비교.
    state 재사용 — precompute 1회, threshold/exit 조합마다 Numba만 재실행.
    """
    if thresholds is None:
        thresholds = [0.0002, 0.000285]

    rows = []
    total = len(thresholds) * 2
    step = 0

    for th in thresholds:
        th_label = "" if th is None else th

        # 기존 고정 TP/SL exit
        step += 1
        print(f"[exit_compare] {step}/{total} threshold={th_label} exit=old tp={old_tp_pct} sl={sl_pct}")
        cfg_old = SimulatorConfig(
            timeout_bars=timeout_bars,
            tp_pct=old_tp_pct,
            sl_pct=sl_pct,
            fee_bps=fee_bps,
            cooldown_bars=0,
            regime_threshold=th,
            use_partial_tp=False,
        )
        trades_old = simulate_old_from_state(state, cfg_old)
        m_old = metrics_from_simple_trades(trades_old)
        rows.append({
            "exit_type": "old",
            "regime_threshold": th_label,
            "timeout_bars": timeout_bars,
            "tp_pct": old_tp_pct,
            "tp1_pct": "",
            "sl_pct": sl_pct,
            **m_old,
        })
        print(f"[exit_compare] done  -> {rows[-1]}")

        # Partial TP + trend-follow exit
        step += 1
        print(f"[exit_compare] {step}/{total} threshold={th_label} exit=partial tp1={tp1_pct} sl={sl_pct}")
        cfg_partial = SimulatorConfig(
            timeout_bars=timeout_bars,
            sl_pct=sl_pct,
            fee_bps=fee_bps,
            cooldown_bars=0,
            regime_threshold=th,
            use_partial_tp=True,
            tp1_pct=tp1_pct,
            tp1_size=tp1_size,
        )
        trades_partial = simulate_partial_from_state(state, cfg_partial)
        m_partial = metrics_from_simple_trades(trades_partial)
        rows.append({
            "exit_type": "partial",
            "regime_threshold": th_label,
            "timeout_bars": timeout_bars,
            "tp_pct": "",
            "tp1_pct": tp1_pct,
            "sl_pct": sl_pct,
            **m_partial,
        })
        print(f"[exit_compare] done  -> {rows[-1]}")

    return rows


# ---------------------------------------------------------------------------
# CSV 저장
# ---------------------------------------------------------------------------

def _save_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    # exit_reasons 같은 dict 값은 str로 변환해서 저장
    serialized = []
    for r in rows:
        serialized.append({k: (str(v) if isinstance(v, dict) else v) for k, v in r.items()})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(serialized[0].keys()))
        w.writeheader()
        w.writerows(serialized)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest experiments")
    parser.add_argument(
        "--experiment",
        choices=["exit_grid", "cooldown", "regime", "exit_compare"],
        required=True,
    )
    parser.add_argument("--from-db", action="store_true")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--out", default=None)
    # exit_grid
    parser.add_argument("--timeouts", default=None, help="Comma-separated e.g. 10,30,60")
    parser.add_argument("--tp-sl", default=None, help="Comma-separated pairs e.g. 0.6,0.3,0.8,0.4")
    # cooldown
    parser.add_argument("--cooldown-bars", default=None)
    parser.add_argument("--timeout-bars", type=int, default=30)
    parser.add_argument("--tp", type=float, default=0.6)
    parser.add_argument("--sl", type=float, default=0.3)
    # regime / exit_compare
    parser.add_argument("--thresholds", default=None, help="Comma-separated e.g. 0.0002,0.000285")
    # exit_compare partial TP
    parser.add_argument("--tp1", type=float, default=0.8)
    parser.add_argument("--tp1-size", type=float, default=0.5)
    args = parser.parse_args()

    if args.from_db:
        candles_1m, candles_5m, candles_15m = _load_candles_from_db(
            symbol=args.symbol,
            limit=args.limit,
            offset=args.offset,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
        )
    else:
        print("--from-db required for now.")
        sys.exit(1)

    if not candles_1m:
        print("No 1m candles loaded.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Precompute: feature extraction 1회만 수행
    # -----------------------------------------------------------------------
    print("[main] building precomputed state (feature extraction, once)...")
    state = build_precomputed_state(
        candles_1m=candles_1m,
        candles_5m_full=candles_5m,
        candles_15m_full=candles_15m,
        symbol=args.symbol,
        evaluate_fn=evaluate_strict,
        get_settings=get_strategy_settings,
    )
    print("[main] precomputed state ready.")

    # -----------------------------------------------------------------------
    # 실험 실행 (state 재사용)
    # -----------------------------------------------------------------------
    rows: List[Dict[str, Any]] = []

    if args.experiment == "exit_grid":
        timeouts = [int(x) for x in args.timeouts.split(",")] if args.timeouts else None
        tp_sl_list = None
        if args.tp_sl:
            parts = [float(x) for x in args.tp_sl.split(",")]
            tp_sl_list = [(parts[i], parts[i + 1]) for i in range(0, len(parts), 2)]
        rows = run_exit_grid(
            state, args.symbol, fee_bps=args.fee_bps,
            timeouts=timeouts, tp_sl_list=tp_sl_list,
        )

    elif args.experiment == "cooldown":
        cooldown_options = [int(x) for x in args.cooldown_bars.split(",")] if args.cooldown_bars else None
        rows = run_cooldown_test(
            state, args.symbol, fee_bps=args.fee_bps,
            timeout_bars=args.timeout_bars, tp_pct=args.tp, sl_pct=args.sl,
            cooldown_options=cooldown_options,
        )

    elif args.experiment == "regime":
        thresholds = _parse_thresholds(args.thresholds)
        rows = run_regime_filter_test(
            state, args.symbol, fee_bps=args.fee_bps,
            timeout_bars=args.timeout_bars, tp_pct=args.tp, sl_pct=args.sl,
            thresholds=thresholds,
        )

    elif args.experiment == "exit_compare":
        thresholds = _parse_thresholds(args.thresholds)
        rows = run_exit_compare(
            state, args.symbol, fee_bps=args.fee_bps,
            timeout_bars=args.timeout_bars, old_tp_pct=args.tp, sl_pct=args.sl,
            tp1_pct=args.tp1, tp1_size=args.tp1_size,
            thresholds=thresholds,
        )

    for r in rows:
        print(r)
    if args.out:
        _save_csv(rows, Path(args.out))
        print(f"Saved to {args.out}")


def _parse_thresholds(raw: Optional[str]) -> Optional[List[Optional[float]]]:
    if not raw:
        return None
    result = []
    for x in raw.split(","):
        x = x.strip()
        if x.lower() == "none":
            result.append(None)
        else:
            result.append(float(x))
    return result


if __name__ == "__main__":
    print("starting experiment runner...")
    main()
