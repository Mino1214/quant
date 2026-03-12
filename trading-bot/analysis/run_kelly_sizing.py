"""
Phase 7 — Position sizing with Kelly: run baseline backtest with Kelly enabled, export sizing and risk metrics.

Usage:
  python -m analysis.run_kelly_sizing --from-db [--bars 50000] [--output-dir analysis/output]

Outputs:
  kelly_sizing_results.csv   — per-trade: timestamp, side, pnl, rr, kelly_fraction, allocated_risk_pct
  equity_curve_kelly.png
  risk_analysis.txt
"""
import argparse
import asyncio
import csv
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.loader import load_baseline_profile
from storage.candle_loader import load_1m_from_db, load_1m_last_n
from backtest.backtest_runner import run_backtest


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Kelly sizing: backtest with baseline, export sizing results")
    parser.add_argument("--from-db", action="store_true")
    parser.add_argument("--table", type=str, default="btc1m")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--bars", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default="analysis/output")
    args = parser.parse_args()

    if not args.from_db:
        print("Use --from-db", file=sys.stderr)
        sys.exit(1)

    if args.bars is not None:
        candles = load_1m_last_n(args.bars, table=args.table, symbol=args.symbol)
    else:
        candles = load_1m_from_db(table=args.table, limit=args.limit, symbol=args.symbol)
    if not candles:
        print("No candles from DB", file=sys.stderr)
        sys.exit(1)

    config = load_baseline_profile()
    trades, final_balance, candidate_signals = await run_backtest(
        candles, symbol=args.symbol, config=config, verbose=False
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-trade: get kelly/risk from candidate_signals (executed only)
    executed_ts = {t.opened_at: t for t in trades}
    rows = []
    for rec in candidate_signals:
        if rec.trade_outcome != "executed":
            continue
        t = executed_ts.get(rec.timestamp)
        if not t:
            continue
        rows.append({
            "timestamp": rec.timestamp.isoformat() if hasattr(rec.timestamp, "isoformat") else str(rec.timestamp),
            "side": t.side.value,
            "pnl": t.pnl,
            "rr": t.rr,
            "kelly_fraction": getattr(rec, "kelly_fraction", None) or "",
            "allocated_risk_pct": getattr(rec, "allocated_risk_pct", None) or "",
        })

    csv_path = out_dir / "kelly_sizing_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "side", "pnl", "rr", "kelly_fraction", "allocated_risk_pct"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {csv_path} ({len(rows)} trades)")

    # Equity curve
    if trades:
        sorted_trades = sorted(trades, key=lambda t: t.closed_at)
        cum = 0.0
        equity = []
        for t in sorted_trades:
            cum += t.pnl
            equity.append(cum)
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots()
            ax.plot(range(len(equity)), equity, color="steelblue")
            ax.set_xlabel("Trade index")
            ax.set_ylabel("Cumulative PnL")
            ax.set_title("Equity curve (Kelly sizing)")
            ax.axhline(0, color="gray", linestyle="--")
            fig.tight_layout()
            fig.savefig(out_dir / "equity_curve_kelly.png", dpi=100)
            plt.close(fig)
            print(f"Wrote {out_dir / 'equity_curve_kelly.png'}")
        except ImportError:
            pass

    # risk_analysis.txt
    initial = config.get("backtest", {}).get("initial_balance", 10000.0)
    n = len(trades)
    total_r = sum(t.rr for t in trades)
    avg_r = total_r / n if n else 0
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else 0
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for t in sorted(trades, key=lambda x: x.closed_at):
        cum += t.pnl
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    lines = [
        "Risk analysis (Kelly sizing)",
        "=" * 50,
        f"Trades: {n}",
        f"Avg R: {avg_r:.4f}",
        f"Profit factor: {pf:.2f}",
        f"Max drawdown: {max_dd:.2f}",
        f"Initial balance: {initial:.2f}",
        f"Final balance: {final_balance:.2f}",
    ]
    (out_dir / "risk_analysis.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_dir / 'risk_analysis.txt'}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
