"""
Phase 1 — Baseline strategy: reference metrics from candidate_signals 테이블 또는 full backtest.

기본 권장: 수집된 candidate_signals(약 1.7만 건)로 baseline 메트릭 계산 (페이퍼 백테스트 아님).
  python -m analysis.run_baseline --from-candidates-db

전체 1m 봉으로 페이퍼 백테스트할 때만:
  python -m analysis.run_baseline --from-db  # 또는 --data path/to/1m.csv

Outputs:
  baseline_performance.csv, baseline_equity_curve.png, baseline_summary.txt, baseline_metrics.json
"""
import argparse
import asyncio
import csv
import json
import math
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.loader import load_baseline_profile
from storage.candle_loader import load_1m_from_db, load_1m_last_n, load_5m_from_db, load_15m_from_db
from backtest.backtest_runner import run_backtest, load_1m_candles_from_csv
from analysis.stability_map import _filter_by_thresholds, metrics_for_rows


def _metrics_from_trades(trades):
    """Compute total_trades, winrate, avg_R, profit_factor, max_drawdown, sharpe from trade list."""
    n = len(trades)
    if n == 0:
        return {
            "total_trades": 0,
            "winrate": 0.0,
            "avg_R": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
        }
    wins = sum(1 for t in trades if t.pnl > 0)
    winrate = (wins / n) * 100.0
    r_list = [t.rr for t in trades]
    avg_r = sum(r_list) / n
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    # max drawdown from equity curve (cumulative PnL)
    sorted_trades = sorted(trades, key=lambda t: t.closed_at)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted_trades:
        cum += t.pnl
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    # Sharpe (per-trade R): mean(R)/std(R)*sqrt(N); annualized-style
    import math
    if len(r_list) > 1:
        mean_r = sum(r_list) / len(r_list)
        var = sum((x - mean_r) ** 2 for x in r_list) / (len(r_list) - 1)
        std_r = math.sqrt(var) if var > 0 else 0.0
        sharpe = (mean_r / std_r) * math.sqrt(len(r_list)) if std_r > 0 else 0.0
    else:
        sharpe = 0.0
    return {
        "total_trades": n,
        "winrate": winrate,
        "avg_R": avg_r,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "sharpe": round(sharpe, 4),
    }


def _write_equity_curve(trades, output_path: Path) -> bool:
    """Plot cumulative PnL over time. Returns True if saved."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    if not trades:
        return False
    sorted_trades = sorted(trades, key=lambda t: t.closed_at)
    cum = 0.0
    equity = []
    times = []
    for t in sorted_trades:
        cum += t.pnl
        equity.append(cum)
        times.append(t.closed_at)
    fig, ax = plt.subplots()
    ax.plot(range(len(equity)), equity, color="steelblue")
    ax.set_xlabel("Trade index")
    ax.set_ylabel("Cumulative PnL")
    ax.set_title("Baseline strategy — equity curve")
    ax.axhline(0, color="gray", linestyle="--")
    fig.tight_layout()
    fig.savefig(output_path, dpi=100)
    plt.close(fig)
    return True


def _write_summary_txt(
    metrics: dict,
    initial_balance: float,
    final_balance: float,
    output_path: Path,
    from_signals: bool = False,
    total_r: float | None = None,
) -> None:
    lines = [
        "Baseline strategy — performance summary",
        "=" * 50,
        ("(candidate_signals 테이블 기준)" if from_signals else "(full backtest)"),
        "",
        f"Total trades:     {metrics['total_trades']}",
        f"Win rate:         {metrics['winrate']:.2f}%",
        f"Avg R:            {metrics['avg_R']:.4f}",
        f"Profit factor:   {metrics['profit_factor']:.4f}",
        f"Max drawdown:    {metrics['max_drawdown']:.2f}",
        f"Sharpe (R):      {metrics['sharpe']:.4f}",
        "",
    ]
    if from_signals and total_r is not None:
        lines.append(f"Total R:          {total_r:.2f}  (시그널 기준 — 달러 잔고/Net PnL은 backtest 모드에서만 의미 있음)")
    else:
        lines.append(f"Initial balance:  {initial_balance:.2f}")
        lines.append(f"Final balance:    {final_balance:.2f}")
        lines.append(f"Net PnL:          {final_balance - initial_balance:.2f}")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _baseline_metrics_from_candidate_signals(rows: list, baseline_config: dict, r_key: str = "future_r_30") -> tuple[dict, list]:
    """
    candidate_signals 행에 baseline 임계값 적용 후 메트릭 계산.
    Returns (metrics_dict, filtered_rows for equity curve).
    """
    strat = baseline_config.get("strategy", {})
    ema_t = float(strat.get("ema_distance_threshold", 0.0003))
    vol_t = float(strat.get("volume_multiplier", 1.2))
    rsi_t = float(strat.get("rsi_long_min", 45))
    use_trend = bool(strat.get("use_trend_filter", True))
    filtered = _filter_by_thresholds(
        rows, ema_t, vol_t, rsi_t, use_trend_filter=use_trend
    )
    if not filtered:
        return {
            "total_trades": 0, "winrate": 0.0, "avg_R": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0, "sharpe": 0.0,
        }, []
    m = metrics_for_rows(filtered, r_key=r_key, r_cap=20.0)
    r_vals = []
    for r in filtered:
        v = r.get(r_key) or r.get("R_return")
        if v is not None and v != "":
            try:
                r_vals.append(max(-20, min(20, float(v))))
            except (TypeError, ValueError):
                pass
    if len(r_vals) > 1:
        mean_r = sum(r_vals) / len(r_vals)
        var = sum((x - mean_r) ** 2 for x in r_vals) / (len(r_vals) - 1)
        std_r = math.sqrt(var) if var > 0 else 0.0
        sharpe = (mean_r / std_r) * math.sqrt(len(r_vals)) if std_r > 0 else 0.0
    else:
        sharpe = 0.0
    metrics = {
        "total_trades": m["trades"],
        "winrate": m["winrate"],
        "avg_R": m["avg_R"],
        "profit_factor": m["profit_factor"],
        "max_drawdown": m["max_drawdown"],
        "sharpe": round(sharpe, 4),
    }
    return metrics, filtered


def _equity_curve_from_signal_rows(rows: list, r_key: str, output_path: Path) -> bool:
    """candidate_signals 행을 시간순 정렬 후 누적 R로 equity curve 그리기."""
    if not rows:
        return False
    ts_key = "timestamp" if "timestamp" in rows[0] else "open_time"
    with_r = [(r, float(r.get(r_key) or r.get("R_return") or 0)) for r in rows if (r.get(r_key) is not None or r.get("R_return") is not None)]
    if not with_r:
        return False
    try:
        ts = with_r[0][0].get(ts_key)
        if hasattr(ts, "isoformat"):
            sortable = True
        else:
            sortable = isinstance(ts, str)
    except Exception:
        sortable = False
    if sortable:
        with_r.sort(key=lambda x: x[0].get(ts_key) or "")
    cum = 0.0
    equity = []
    for _, r_val in with_r:
        cum += r_val
        equity.append(cum)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.plot(range(len(equity)), equity, color="steelblue")
        ax.set_xlabel("Signal index")
        ax.set_ylabel("Cumulative R")
        ax.set_title("Baseline (candidate_signals) — cumulative R")
        ax.axhline(0, color="gray", linestyle="--")
        fig.tight_layout()
        fig.savefig(output_path, dpi=100)
        plt.close(fig)
        return True
    except ImportError:
        return False


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Baseline metrics: candidate_signals 테이블(권장) 또는 full backtest")
    parser.add_argument("--from-candidates-db", action="store_true", help="[권장] candidate_signals + signal_outcomes 테이블로 메트릭 계산 (수집된 시그널만)")
    parser.add_argument("--from-db", action="store_true", help="1m 캔들 전체로 페이퍼 백테스트 (느림)")
    parser.add_argument("--data", type=str, default="", help="Path to 1m CSV (페이퍼 백테스트용)")
    parser.add_argument("--table", type=str, default="btc1m")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--bars", type=int, default=None, help="--from-db 시 최근 N봉만 사용")
    parser.add_argument("--limit", type=int, default=None, help="--from-db: 과거 N봉만 사용. --from-candidates-db: 불러올 시그널 수 (미지정 시 전부)")
    parser.add_argument("--output-dir", type=str, default="analysis/output")
    parser.add_argument("--signals-table", type=str, default="candidate_signals", help="--from-candidates-db 시 사용할 signals table/view (default: candidate_signals)")
    args = parser.parse_args()

    baseline_config = load_baseline_profile()
    initial_balance = baseline_config.get("backtest", {}).get("initial_balance", 10000.0)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.from_candidates_db:
        # candidate_signals 테이블 사용 (페이퍼 백테스트 없음)
        from storage.database import SessionLocal, init_db
        from storage.repositories import get_candidate_signals_with_outcomes
        init_db()
        db = SessionLocal()
        try:
            limit = args.limit if args.limit is not None else 500_000
            rows = get_candidate_signals_with_outcomes(db, symbol=args.symbol, limit=limit, signals_table=args.signals_table)
        finally:
            db.close()
        if not rows:
            print("candidate_signals 테이블에 데이터가 없습니다. 수집 파이프라인을 먼저 돌리거나 --from-db 로 백테스트하세요.", file=sys.stderr)
            sys.exit(1)
        r_key = "future_r_30" if (rows and rows[0].get("future_r_30") is not None) else "R_return"
        if rows and not any(r.get(r_key) is not None or r.get("R_return") is not None for r in rows[:20]):
            r_key = "R_return"
        print(f"Loaded {len(rows)} candidate signals from DB (r_key={r_key})")
        metrics, filtered_rows = _baseline_metrics_from_candidate_signals(rows, baseline_config, r_key=r_key)
        total_r = sum(
            float(r.get(r_key) or r.get("R_return") or 0)
            for r in filtered_rows
            if r.get(r_key) is not None or r.get("R_return") is not None
        )
        equity_path = out_dir / "baseline_equity_curve.png"
        if _equity_curve_from_signal_rows(filtered_rows, r_key, equity_path):
            print(f"Wrote {equity_path}")
    elif args.from_db or (args.data and Path(args.data).exists()):
        if args.from_db:
            if args.bars is not None:
                candles = load_1m_last_n(args.bars, table=args.table, symbol=args.symbol)
            else:
                candles = load_1m_from_db(table=args.table, limit=args.limit, symbol=args.symbol)
            if not candles:
                print("No candles from DB. Check DATABASE_URL and table.", file=sys.stderr)
                sys.exit(1)
            print(f"Loaded {len(candles)} 1m bars from DB")
            # 5m/15m은 btc5m, btc15m 테이블에서 같은 구간으로 로드 (lookback 60*15분)
            from datetime import timedelta
            start_ts = candles[0].timestamp - timedelta(minutes=60 * 15)
            end_ts = candles[-1].timestamp
            candles_5m = load_5m_from_db(table="btc5m", start_ts=start_ts, end_ts=end_ts, symbol=args.symbol)
            candles_15m = load_15m_from_db(table="btc15m", start_ts=start_ts, end_ts=end_ts, symbol=args.symbol)
            print(f"Loaded {len(candles_5m)} 5m, {len(candles_15m)} 15m from DB")
            trades, final_balance, _ = await run_backtest(
                candles, symbol=args.symbol, config=baseline_config, verbose=False,
                candles_5m=candles_5m, candles_15m=candles_15m,
            )
        else:
            candles = load_1m_candles_from_csv(Path(args.data))
            print(f"Loaded {len(candles)} 1m bars from CSV")
            trades, final_balance, _ = await run_backtest(
                candles, symbol=args.symbol, config=baseline_config, verbose=False
            )
        metrics = _metrics_from_trades(trades)
        # backtest 결과는 별도 파일로 저장 → candidate_signals 기준 baseline_metrics.json 덮어쓰지 않음
        suffix = "_backtest"
        perf_path = out_dir / f"baseline_performance{suffix}.csv"
        with open(perf_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["total_trades", "winrate", "avg_R", "profit_factor", "max_drawdown", "sharpe"])
            w.writeheader()
            w.writerow(metrics)
        print(f"Wrote {perf_path}")
        equity_path = out_dir / f"baseline_equity_curve{suffix}.png"
        if _write_equity_curve(trades, equity_path):
            print(f"Wrote {equity_path}")
        summary_path = out_dir / f"baseline_summary{suffix}.txt"
        _write_summary_txt(metrics, initial_balance, final_balance, summary_path, from_signals=False)
        print(f"Wrote {summary_path}")
        metrics_with_balance = {**metrics, "initial_balance": initial_balance, "final_balance": final_balance}
        json_path = out_dir / f"baseline_metrics{suffix}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(metrics_with_balance, f, indent=2)
        print(f"Wrote {json_path} (Phase 2~8 비교용 baseline은 baseline_metrics.json — from-candidates-db 결과)")
        return
    else:
        print("Use --from-candidates-db (권장: 수집된 시그널) or --from-db / --data (페이퍼 백테스트)", file=sys.stderr)
        sys.exit(1)

    # from_candidates_db 전용 출력 → baseline_metrics.json 등 (파이프라인 비교 기준)
    perf_path = out_dir / "baseline_performance.csv"
    with open(perf_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["total_trades", "winrate", "avg_R", "profit_factor", "max_drawdown", "sharpe"])
        w.writeheader()
        w.writerow(metrics)
    print(f"Wrote {perf_path}")
    summary_path = out_dir / "baseline_summary.txt"
    _write_summary_txt(metrics, initial_balance, initial_balance, summary_path, from_signals=True, total_r=total_r)
    print(f"Wrote {summary_path}")
    metrics_with_balance = {**metrics, "initial_balance": initial_balance, "final_balance": initial_balance, "total_r": total_r}
    json_path = out_dir / "baseline_metrics.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metrics_with_balance, f, indent=2)
    print(f"Wrote {json_path} (Phase 2~8에서 compare_to_baseline() 이 이 파일을 씀)")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
